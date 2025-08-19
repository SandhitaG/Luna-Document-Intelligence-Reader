# backend/gemini_helper.py

from __future__ import annotations

import os
import time
import pathlib
import logging
from typing import Callable, Optional

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

_USE_API_KEY = bool(os.getenv("GOOGLE_API_KEY"))
_SA_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
_USE_SERVICE_ACCOUNT = bool(_SA_PATH and pathlib.Path(_SA_PATH).exists())

# Will be set to a callable that accepts (prompt: str, **kwargs) -> str
_generate_fn: Optional[Callable[..., str]] = None


def _init_generativeai_api_key() -> Optional[Callable[..., str]]:
    """Configure google-generativeai using GOOGLE_API_KEY."""
    try:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=os.environ["GOOGLE_API_KEY"])
        model = genai.GenerativeModel(GEMINI_MODEL)

        def _gen(prompt: str, **kwargs) -> str:
            resp = model.generate_content(prompt, **kwargs)
            # .text is present on SDK >= 0.7
            text = getattr(resp, "text", None)
            if not text and getattr(resp, "candidates", None):
                try:
                    text = resp.candidates[0].content.parts[0].text
                except Exception:  # noqa: BLE001
                    text = ""
            return (text or "").strip()

        logging.info("Gemini configured via API key (google-generativeai).")
        return _gen
    except Exception as e:  # noqa: BLE001
        logging.exception("Failed to init google-generativeai with API key: %s", e)
        return None


def _init_vertex_service_account() -> Optional[Callable[..., str]]:
    
    try:
        import vertexai  # type: ignore
        from vertexai.generative_models import GenerativeModel  # type: ignore

        # Prefer explicit project/region if provided, otherwise let ADC infer.
        project = os.getenv("GCP_PROJECT")
        location = os.getenv("GCP_LOCATION", "us-central1")

        try:
            if project:
                vertexai.init(project=project, location=location)
            else:
                # Allow auto-detection from the service account; fallback to default loc
                vertexai.init(location=location)
        except Exception:
            # Final fallback: let Vertex fully auto-detect
            vertexai.init()

        vmodel = GenerativeModel(GEMINI_MODEL)

        def _gen(prompt: str, **kwargs) -> str:
            resp = vmodel.generate_content(prompt, **kwargs)
            text = getattr(resp, "text", "") or ""
            return text.strip()

        logging.info("Gemini configured via Vertex AI (service account).")
        return _gen
    except Exception as e:  # noqa: BLE001
        logging.exception("Failed to init Vertex AI (service account): %s", e)
        return None


# ---- Initialization order ----
# If BOTH are present, prefer service account (Vertex) for the evaluator’s setup.
if LLM_PROVIDER == "gemini":
    if _USE_SERVICE_ACCOUNT:
        _generate_fn = _init_vertex_service_account()
        if not _generate_fn and _USE_API_KEY:
            # fallback to API key if Vertex init failed
            _generate_fn = _init_generativeai_api_key()
    elif _USE_API_KEY:
        _generate_fn = _init_generativeai_api_key()
    else:
        logging.warning(
            "Gemini not configured: set GOOGLE_API_KEY or mount a service account and set "
            "GOOGLE_APPLICATION_CREDENTIALS."
        )
else:
    logging.warning("LLM_PROVIDER is %r (not 'gemini'); gemini_helper is idle.", LLM_PROVIDER)


def generate_gemini_response(prompt: str, retries: int = 2, **kwargs) -> str:
    """
    Generate a single text response from Gemini. Retries a couple times on transient errors.
    Raises RuntimeError if Gemini is not configured.

    Usage:
        text = generate_gemini_response("Write a haiku about PDFs.")
    """
    if not _generate_fn:
        raise RuntimeError(
            "Gemini is not configured. Provide GOOGLE_API_KEY or "
            "GOOGLE_APPLICATION_CREDENTIALS pointing to a service-account JSON."
        )

    last_err: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return _generate_fn(prompt, **kwargs)
        except Exception as e:  # noqa: BLE001
            last_err = e
            # brief backoff
            time.sleep(0.4 * (attempt + 1))

    # If all retries failed, return a friendly message (keeps old behavior),
    # but also log the underlying exception for server logs.
    logging.error("Gemini call failed after retries: %s", last_err)
    return f"❌ Gemini API Error: {last_err}"


# Optional alias used elsewhere in the app
llm_complete = generate_gemini_response

import os
import json
import google.generativeai as genai

# ===== Optional Vertex (service-account JSON) support =====
try:
    from vertexai import init as vertexai_init
    from vertexai.generative_models import GenerativeModel as VertexGenerativeModel
    _HAS_VERTEX = True
except Exception:
    _HAS_VERTEX = False

# ✅ Read from environment variables
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Service-account path (Vertex) + optional project/region
GOOGLE_APPLICATION_CREDENTIALS = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
_GCP_PROJECT = (os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT") or "").strip()
_VERTEX_LOCATION = (os.getenv("VERTEX_LOCATION") or os.getenv("GCP_LOCATION") or "us-central1").strip()

if GOOGLE_API_KEY:
    genai.configure(api_key=GOOGLE_API_KEY)

model = None
_mode = None  # "ai_studio" or "vertex"


def _read_project_from_sa_json(path: str) -> str | None:
    """Extract project_id/quota_project_id from a service-account JSON."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("project_id") or data.get("quota_project_id")
    except Exception:
        return None


def _get_model():
    global model, _mode

    if model:
        return model

    # --- Prefer AI Studio key if present (keeps your original behavior) ---
    if GOOGLE_API_KEY:
        try:
            _mode = "ai_studio"
            model = genai.GenerativeModel(MODEL_NAME)
            return model
        except Exception as e:
            raise RuntimeError(f"Gemini init failed (AI Studio): {e}")

    # --- Else, try Vertex via service-account JSON ---
    if GOOGLE_APPLICATION_CREDENTIALS:
        if not _HAS_VERTEX:
            raise RuntimeError("Vertex SDK not installed; please add google-cloud-aiplatform / vertexai.")
        if not os.path.isfile(GOOGLE_APPLICATION_CREDENTIALS):
            raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS path not found or not a file.")

        project = _GCP_PROJECT or _read_project_from_sa_json(GOOGLE_APPLICATION_CREDENTIALS)
        if not project:
            raise RuntimeError("Could not determine GCP project; set GOOGLE_CLOUD_PROJECT or GCP_PROJECT.")

        try:
            vertexai_init(project=project, location=_VERTEX_LOCATION)
            _mode = "vertex"
            model = VertexGenerativeModel(MODEL_NAME)
            return model
        except Exception as e:
            raise RuntimeError(f"Gemini init failed (Vertex): {e}")

    # --- If neither is set, error like your original code ---
    raise RuntimeError(
        "GOOGLE_API_KEY not set and no valid GOOGLE_APPLICATION_CREDENTIALS provided. "
        "Provide a Google AI Studio API key or mount a service-account JSON."
    )


def get_insights(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return "⚠️ Please enter a valid section."
    try:
        prompt = f"You are a document assistant. Summarize or extract insights from:\n{text}"
        resp = _get_model().generate_content(prompt)
        return (getattr(resp, "text", "") or "").strip()
    except Exception as e:
        return f"LLM Error: {e}"

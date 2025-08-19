import os
os.environ.setdefault("FFMPEG_BINARY", "/usr/bin/ffmpeg")
os.environ.setdefault("FFPROBE_BINARY", "/usr/bin/ffprobe")
import base64
import shutil
import subprocess
from pathlib import Path
from typing import Optional, List

import requests


# Optional: pydub for chunk merge (requires ffmpeg in PATH)
try:
    from pydub import AudioSegment
    _HAS_PYDUB = True
    # make ffmpeg/ffprobe explicit so pydub never complains
    AudioSegment.converter = "/usr/bin/ffmpeg"
    AudioSegment.ffprobe   = "/usr/bin/ffprobe"
except Exception:
    _HAS_PYDUB = False


# Optional: Azure Speech SDK (kept from your original)
try:
    import azure.cognitiveservices.speech as speechsdk  # pip: azure-cognitiveservices-speech
    _HAS_AZURE_SPEECH = True
except Exception:
    _HAS_AZURE_SPEECH = False

# Optional: Google Cloud TTS client (service-account path)
try:
    from google.cloud import texttospeech  # pip: google-cloud-texttospeech
    _HAS_GCP_TTS = True
except Exception:
    _HAS_GCP_TTS = False


# ------------------------------ small utils ------------------------------

def _which(x: str) -> Optional[str]:
    return shutil.which(x)

def _run(cmd: list[str]):
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nSTDERR:\n{p.stderr}\nSTDOUT:\n{p.stdout}"
        )
    return p

def _write_bytes(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)

def _ensure_mp3_path(p: Path) -> Path:
    return p if p.suffix.lower() == ".mp3" else p.with_suffix(".mp3")


# ---------------- voice heuristics & mapping (for local) ------------

_AZURE_TO_ESPEAK = {
    # US female / male
    "en-us-aria": "en-us+f3",
    "en-us-jenny": "en-us+f3",
    "en-us-salli": "en-us+f3",
    "en-us-guy": "en-us+m3",
    "en-us-matthew": "en-us+m3",
    "en-us-brian": "en-us+m3",
    "en-us-daniel": "en-us+m3",
    # GB female / male
    "en-gb-libby": "en-gb+f3",
    "en-gb-susan": "en-gb+f3",
    "en-gb-ryan": "en-gb+m3",
}

def _looks_female(name: str) -> bool:
    name_l = (name or "").lower()
    for key in ("aria", "jenny", "salli", "libby", "female", "+f", "neural-f"):
        if key in name_l:
            return True
    return False

def _normalize_espeak_voice(requested: Optional[str]) -> str:
    env_voice = os.getenv("TTS_VOICE_SINGLE")
    if env_voice:
        return env_voice

    if requested:
        key = requested.lower().strip()
        for k, v in _AZURE_TO_ESPEAK.items():
            if k in key:
                return v
        if any(ch in key for ch in ["+", "en-us", "en-gb", "mb", "f", "m"]):
            return requested
        if _looks_female(requested):
            return "en-us+f3"

    return "en-us+m3"


# ---------------- provider selection ----------------
# --- Helpers to keep TTS from reading list symbols ---
_BULLET_PREFIX = r"^\s*(?:[-*\u2022\u2023\u25AA\u25CF\u25E6]|[\(\[]?\d+[\.\)]|[A-Za-z][\.\)])\s*"
_MD_TRASH = r"[\*\_`#>\[\]]"

def _strip_list_markers(text: str) -> str:
    """Remove bullet/markdown markers & condense whitespace for speakable lines."""
    import re
    t = str(text or "")
    t = re.sub(_MD_TRASH, "", t)
    lines = []
    for ln in t.splitlines():
        ln = re.sub(_BULLET_PREFIX, "", ln).strip(" -–—·•\t")
        if ln:
            lines.append(ln)
    t = " ".join(lines)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def get_tts_provider() -> str:
    """
    Decide TTS engine from env with robust fallbacks.

    Env:
      TTS_PROVIDER=local|azure|gcp|auto  (default: auto)
      # Azure:
      AZURE_TTS_KEY, AZURE_TTS_ENDPOINT (or region endpoint)
      # GCP:
      GOOGLE_API_KEY or GOOGLE_APPLICATION_CREDENTIALS
    """
    prov = (os.getenv("TTS_PROVIDER", "auto") or "auto").strip().lower()

    if prov == "local":
        return "local"

    if prov in ("azure", "auto"):
        if os.getenv("AZURE_TTS_KEY") and os.getenv("AZURE_TTS_ENDPOINT"):
            return "azure"
        if prov == "azure":
            return "local"  # hard fallback

    if prov in ("gcp", "auto"):
        if os.getenv("GOOGLE_API_KEY") or (
            os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            and os.path.exists(os.getenv("GOOGLE_APPLICATION_CREDENTIALS"))
        ):
            return "gcp"
        if prov == "gcp":
            return "local"

    return "local"


# ---------------- chunking helpers (cloud) ----------------

def _chunk_text_by_chars(text: str, max_chars: int) -> List[str]:
    """Split text into <= max_chars parts, preferring whitespace boundaries."""
    if max_chars is None or len(text) <= max_chars:
        return [text]
    import re
    tokens = re.findall(r"\S+\s*", text)
    chunks, cur = [], ""
    for tok in tokens:
        if len(cur) + len(tok) <= max_chars:
            cur += tok
        else:
            if cur.strip():
                chunks.append(cur.strip()); cur = ""
            if len(tok) > max_chars:
                for i in range(0, len(tok), max_chars):
                    part = tok[i:i+max_chars].strip()
                    if part: chunks.append(part)
            else:
                cur = tok
    if cur.strip():
        chunks.append(cur.strip())
    return [c for c in chunks if c]

def _concat_mp3(mp3_files: List[Path], out_path: Path):
    """Concatenate mp3 files into out_path robustly.
    Uses pydub (decode+re-encode) if available; otherwise ffmpeg concat with re-encode.
    """
    out_path = _ensure_mp3_path(out_path)

    if _HAS_PYDUB:
        # Optional tiny gap to avoid boundary clicks; set TTS_GAP_MS=0 to disable
        gap_ms = int(os.getenv("TTS_GAP_MS", "60"))
        silence = AudioSegment.silent(duration=max(gap_ms, 0))

        audio = None
        for f in mp3_files:
            seg = AudioSegment.from_file(f.as_posix(), format="mp3")
            audio = seg if audio is None else (audio + silence + seg)

        # Normalize container parameters
        audio = audio.set_frame_rate(44100).set_channels(2)
        audio.export(out_path.as_posix(), format="mp3", bitrate="160k")
        return out_path

    # Fallback: ffmpeg concat + re-encode (DO NOT use -c copy; that causes loops)
    listfile = out_path.with_suffix(".concat.txt")
    listfile.write_text("".join([f"file '{p.as_posix()}'\n" for p in mp3_files]), encoding="utf-8")

    cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(listfile),
        "-vn",
        "-ar", "44100", "-ac", "2",
        "-b:a", "160k",
        "-c:a", "libmp3lame",
        str(out_path),
    ]
    _run(cmd)
    try:
        listfile.unlink()
    except Exception:
        pass
    return out_path



# ---------------- Azure TTS (Speech SDK OR Azure OpenAI REST) ----------------

def _azure_synthesize(text: str, out_mp3: Path, voice: Optional[str]) -> str:
    """
    Azure path:
      - If AZURE_TTS_ENDPOINT looks like Azure OpenAI (…openai.azure.com) OR AZURE_TTS_DEPLOYMENT is set,
        use the **Azure OpenAI TTS REST** API (as in judges' snippet).
      - Else, use **Azure Speech SDK** (your original path).
    """
    key = os.getenv("AZURE_TTS_KEY")
    endpoint = (os.getenv("AZURE_TTS_ENDPOINT") or "").rstrip("/")
    if not key or not endpoint:
        raise RuntimeError("Azure TTS env missing (AZURE_TTS_KEY / AZURE_TTS_ENDPOINT).")

    # Detect Azure OpenAI vs Speech endpoint
    deployment = os.getenv("AZURE_TTS_DEPLOYMENT")
    api_version = os.getenv("AZURE_TTS_API_VERSION", "2025-03-01-preview")
    is_openai = ("openai.azure.com" in endpoint) or bool(deployment)

    out_mp3 = _ensure_mp3_path(Path(out_mp3))
    want_voice = voice or os.getenv("AZURE_TTS_VOICE") or ("alloy" if _looks_female("jenny") else "onyx")

    if is_openai:
        # ---- Azure OpenAI TTS REST (matches judges' reference) ----
        deployment = deployment or "tts"
        url = f"{endpoint}/openai/deployments/{deployment}/audio/speech"
        headers = {"api-key": key, "Content-Type": "application/json"}
        payload = {
            "model": deployment,
            "input": text,
            "voice": want_voice,
        }
        params = {"api-version": api_version}
        r = requests.post(url, headers=headers, params=params, json=payload, timeout=60)
        try:
            r.raise_for_status()
        except Exception:
            raise RuntimeError(f"Azure OpenAI TTS failed: {r.status_code} {r.text[:400]}")
        _write_bytes(out_mp3, r.content)
        return str(out_mp3)

    # ---- Azure Speech SDK (your original code path) ----
    if not _HAS_AZURE_SPEECH:
        raise RuntimeError("Azure Speech SDK not installed (azure-cognitiveservices-speech).")

    speech_config = speechsdk.SpeechConfig(subscription=key, endpoint=endpoint)
    if hasattr(speechsdk, "SpeechSynthesisOutputFormat"):
        speech_config.set_speech_synthesis_output_format(
            speechsdk.SpeechSynthesisOutputFormat.Audio24Khz160KBitRateMonoMp3
        )
    speech_config.speech_synthesis_voice_name = want_voice
    audio_config = speechsdk.audio.AudioOutputConfig(filename=str(out_mp3))
    synthesizer = speechsdk.SpeechSynthesizer(speech_config=speech_config, audio_config=audio_config)
    result = synthesizer.speak_text_async(text).get()
    try:
        from azure.cognitiveservices.speech import ResultReason
        if result.reason != ResultReason.SynthesizingAudioCompleted and getattr(result, "audio_data", None):
            _write_bytes(out_mp3, result.audio_data)
    except Exception:
        pass
    return str(out_mp3)


# ---------------- GCP TTS (API key REST OR service-account) ----------------

def _gcp_synthesize(text: str, out_mp3: Path, voice: Optional[str]) -> str:
    """
    Uses:
      - GOOGLE_API_KEY -> REST call to Cloud TTS
      - else GOOGLE_APPLICATION_CREDENTIALS -> google-cloud-texttospeech client
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
    name = voice or os.getenv("GCP_TTS_VOICE") or "en-US-Neural2-F"
    lang = os.getenv("GCP_TTS_LANGUAGE") or "en-US"

    out_mp3 = _ensure_mp3_path(Path(out_mp3))

    if api_key:
        # REST with API key (key query param, not Authorization header)
        url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
        payload = {
            "input": {"text": text},
            "voice": {"languageCode": lang, "name": name},
            "audioConfig": {"audioEncoding": "MP3"},
        }
        r = requests.post(url, json=payload, timeout=60)
        try:
            r.raise_for_status()
        except Exception:
            raise RuntimeError(f"GCP TTS (API key) failed: {r.status_code} {r.text[:400]}")
        audio_b64 = r.json().get("audioContent", "")
        if not audio_b64:
            raise RuntimeError("GCP TTS (API key) returned empty audioContent.")
        audio = base64.b64decode(audio_b64)
        _write_bytes(out_mp3, audio)
        return str(out_mp3)

    # Service-account client
    if not creds or not os.path.exists(creds):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS missing or invalid (and no GOOGLE_API_KEY).")
    if not _HAS_GCP_TTS:
        raise RuntimeError("google-cloud-texttospeech not installed.")

    client = texttospeech.TextToSpeechClient()
    input_ = texttospeech.SynthesisInput(text=text)
    voice_sel = texttospeech.VoiceSelectionParams(language_code=lang, name=name)
    audio_cfg = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)

    # Optional rate/pitch via env
    rate = os.getenv("GCP_TTS_RATE"); pitch = os.getenv("GCP_TTS_PITCH")
    try:
        if rate:  audio_cfg.speaking_rate = float(rate)
        if pitch: audio_cfg.pitch = float(pitch)
    except Exception:
        pass

    resp = client.synthesize_speech(request={"input": input_, "voice": voice_sel, "audio_config": audio_cfg})
    _write_bytes(out_mp3, resp.audio_content)
    return str(out_mp3)


# ---------------- Local (espeak + ffmpeg) ----------------

def _local_synthesize(text: str, out_mp3: Path, voice: Optional[str],
                      speed: Optional[int], pitch: Optional[int]) -> str:
    espeak = _which("espeak-ng") or _which("espeak")
    if not espeak:
        raise RuntimeError("espeak-ng/espeak not found in PATH (needed for local TTS).")
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found (needed to encode mp3).")

    speed = int(os.getenv("TTS_SPEED", "165")) if speed is None else int(speed)
    pitch = int(os.getenv("TTS_PITCH", "48")) if pitch is None else int(pitch)
    amp = int(os.getenv("TTS_VOLUME", "200"))

    espeak_voice = _normalize_espeak_voice(voice)
    text = " ".join(str(text or "").split())

    import tempfile
    with tempfile.TemporaryDirectory(prefix="tts_") as d:
        temp_dir = Path(d)
        txt_path = temp_dir / "in.txt"
        wav_path = temp_dir / "out.wav"
        txt_path.write_text(text, encoding="utf-8")
        cmd1 = [espeak, "-v", espeak_voice, "-s", str(speed), "-p", str(pitch), "-a", str(amp),
                "-f", str(txt_path), "-w", str(wav_path)]
        _run(cmd1)
        cmd2 = [ffmpeg, "-y", "-i", str(wav_path), "-ar", "44100", "-ac", "2", "-b:a", "160k", str(_ensure_mp3_path(out_mp3))]
        _run(cmd2)

    return str(_ensure_mp3_path(out_mp3))


# ---------------- Public API ----------------

def generate_audio(
    text: str,
    output_file: str,
    provider: Optional[str] = None,
    voice: Optional[str] = None,
    speed: Optional[int] = None,
    pitch: Optional[int] = None,
) -> str:
    """
    Generate an MP3 for the given text and return the output filepath.

    Provider selection:
      - provider arg if given
      - else auto-picked via get_tts_provider()

    Env you might set:
      TTS_PROVIDER=local|azure|gcp|auto (default: auto)
      TTS_CLOUD_MAX_CHARS=3000 (split/merge for Azure/GCP; uses pydub or ffmpeg)
    """
    if not text or not str(text).strip():
        raise ValueError("Text cannot be empty")

    out = Path(output_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    out = _ensure_mp3_path(out)

    prov = (provider or get_tts_provider()).lower()

    # Cloud chunking (optional)
    max_chars_env = os.getenv("TTS_CLOUD_MAX_CHARS", "3000")
    try:
        max_chars = int(max_chars_env)
        if max_chars <= 0:
            max_chars = None
    except Exception:
        max_chars = 3000

    try:
        if prov in ("azure", "gcp") and max_chars and len(text) > max_chars:
            parts = _chunk_text_by_chars(text, max_chars)
            temp_files = []
            try:
                for i, chunk in enumerate(parts):
                    seg_path = out.parent / f".tts_chunk_{i}.mp3"
                    if prov == "azure":
                        _azure_synthesize(chunk, seg_path, voice)
                    else:
                        _gcp_synthesize(chunk, seg_path, voice)
                    temp_files.append(seg_path)
                final_path = _concat_mp3(temp_files, out)
                return str(final_path)
            finally:
                for p in temp_files:
                    try: p.unlink()
                    except: pass

        if prov == "azure":
            return _azure_synthesize(text, out, voice)
        elif prov == "gcp":
            return _gcp_synthesize(text, out, voice)
        else:
            return _local_synthesize(text, out, voice, speed, pitch)

    except Exception as e:
        # Always fall back to local so the app keeps working
        try:
            return _local_synthesize(text, out, voice, speed, pitch)
        except Exception as e2:
            raise RuntimeError(f"TTS failed (and local fallback failed): {e}; local error: {e2}")

import os
import sys
import json
import difflib
import subprocess
import importlib.util
from pathlib import Path
from uuid import uuid4
import time
from typing import Dict, List, Any
import re
import tempfile
import inspect
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from shutil import which as _which

from flask import Flask, request, jsonify, send_file, send_from_directory
from flask_cors import CORS

# -----------------------------------------------------------------------------------------
# Optional imports when running inside/outside package layout
# -----------------------------------------------------------------------------------------
try:
    from backend.podcast.generate_audio import generate_audio
    from backend.insights.insights import get_insights
except ModuleNotFoundError:
    from podcast.generate_audio import generate_audio
    from insights.insights import get_insights

# -----------------------------------------------------------------------------------------
# Optional .env + (legacy bridge only if someone drops a raw API key file)
# -----------------------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# If a plain text file was mounted at GOOGLE_APPLICATION_CREDENTIALS that actually
# contains an API key (not a service account JSON), bridge it into GOOGLE_API_KEY.
cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if not os.getenv("GOOGLE_API_KEY") and cred_path and os.path.exists(cred_path):
    try:
        raw = Path(cred_path).read_text(encoding="utf-8").strip()
        if raw and not raw.startswith("{"):  # looks like a bare key
            os.environ["GOOGLE_API_KEY"] = raw
    except Exception:
        pass

# -----------------------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder="../frontend_dist", static_url_path="/")
CORS(app, resources={r"/*": {"origins": "*"}})
app.config["MAX_CONTENT_LENGTH"] = 256 * 1024 * 1024  # 256MB uploads
app.config["CORS_HEADERS"] = "Content-Type"

def _try_import_get_insights():
    try:
        from backend.insights.insights import get_insights
        return get_insights
    except ModuleNotFoundError:
        from insights.insights import get_insights  # type: ignore
        return get_insights

get_insights = _try_import_get_insights()

# -----------------------------------------------------------------------------------------
# SAFE helpers for semantic search & snippets (do NOT alter your /snippet_explain)
# -----------------------------------------------------------------------------------------
def _load_helpers():
    """Prefer backend/snippets_safe.py; fallback to local snippets_safe.py."""
    # 1) package-style
    try:
        from backend.snippets_safe import (  # type: ignore
            rank_and_snippetize,
            embed_texts,
            build_snippet,
        )
        return rank_and_snippetize, embed_texts, build_snippet
    except Exception:
        pass

    # 2) local file
    local = BASE_DIR / "snippets_safe.py"
    if local.exists():
        spec = importlib.util.spec_from_file_location("snips_safe_dyn", str(local))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore
        return mod.rank_and_snippetize, mod.embed_texts, mod.build_snippet  # type: ignore

    raise ModuleNotFoundError("snippets_safe.py not found (needed for select_insights)")

rank_and_snippetize, embed_texts, build_snippet_safe = _load_helpers()

# -----------------------------------------------------------------------------------------
# Persistent Library of extracted sections (for Connect the Insights)
# -----------------------------------------------------------------------------------------
MEM_DIR = BASE_DIR / "memory"
MEM_DIR.mkdir(parents=True, exist_ok=True)
LIB_FILE = MEM_DIR / "library.json"
LIB_SECTIONS: List[Dict[str, Any]] = []
META: Dict[str, Any] = {"next_batch_id": 1}

def _save_library():
    data = {"meta": META, "sections": LIB_SECTIONS}
    LIB_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

def _load_library():
    global LIB_SECTIONS, META
    if LIB_FILE.exists():
        try:
            data = json.loads(LIB_FILE.read_text(encoding="utf-8"))
            META = data.get("meta", {"next_batch_id": 1})
            LIB_SECTIONS = data.get("sections", [])
        except Exception:
            META = {"next_batch_id": 1}
            LIB_SECTIONS = []

_load_library()

# ---- One-time cleanup for previously stored "(untitled)" rows ----
def _first_sentence(text: str, max_chars: int = 70) -> str:
    """Return the first useful line/sentence of text, trimmed and bullet-stripped."""
    t = (text or "").strip()
    if not t:
        return ""
    line = next((ln.strip() for ln in t.splitlines() if ln.strip()), "")
    if not line:
        line = t
    line = re.sub(r"^[\-\u2022\*\•]+\s*", "", line)
    head = re.split(r"(?<=[.!?])\s+", line)[0] if line else ""
    if not head:
        head = line
    if len(head) > max_chars:
        head = head[: max_chars].rsplit(" ", 1)[0] + "…"
    return head

def _title_for_section(sec_like: Dict[str, Any]) -> str:
    """Prefer explicit title; otherwise derive from text; otherwise 'Page N'."""
    raw = (sec_like.get("section_title") or sec_like.get("title") or "").strip()
    if raw and raw.lower() not in ("untitled", "(untitled)"):
        return raw
    txt = (sec_like.get("refined_text") or sec_like.get("text") or "")
    derived = _first_sentence(txt)
    if derived:
        return derived
    p = sec_like.get("page_number") or sec_like.get("pageNumber") or "?"
    return f"Page {p}"

_changed = False
for _s in LIB_SECTIONS:
    t = (_s.get("section_title") or "").strip()
    if not t or t.lower() in ("untitled", "(untitled)"):
        new_t = _title_for_section(_s)
        if new_t and new_t != t:
            _s["section_title"] = new_t
            _changed = True
if _changed:
    _save_library()

def _ensure_embeddings(sections: List[Dict[str, Any]]):
    texts = [s.get("refined_text", "") for s in sections]
    vecs = embed_texts(texts)
    for s, v in zip(sections, vecs):
        s["embedding"] = (v.tolist() if hasattr(v, "tolist") else list(v))

def _absorb_sections(sections: List[Dict[str, Any]], batch_id: int):
    for s in sections:
        s["batch_id"] = batch_id
        s["ingested_at"] = int(time.time())
    need = [s for s in sections if not isinstance(s.get("embedding"), list)]
    if need:
        _ensure_embeddings(need)
    LIB_SECTIONS.extend(sections)
    _save_library()

def _sections_from_1b(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    arr = obj.get("sub_section_analysis") or []
    if not isinstance(arr, list):
        return out
    for it in arr:
        page = it.get("page_number") or it.get("pageNumber") or 1
        refined = it.get("refined_text") or it.get("text") or ""
        sec_like = {
            "section_title": it.get("section_title") or it.get("title"),
            "refined_text": refined,
            "page_number": page,
        }
        out.append(
            {
                "document": it.get("document"),
                "page_number": page,
                "section_title": _title_for_section(sec_like),
                "refined_text": refined,
                "embedding": it.get("embedding"),
            }
        )
    return out

def _split_recent_past():
    if not LIB_SECTIONS:
        return set(), set()
    latest = max(s.get("batch_id", 1) for s in LIB_SECTIONS)
    recent_ids = {latest}
    past_ids = {
        s.get("batch_id", 1)
        for s in LIB_SECTIONS
        if s.get("batch_id", 1) < latest
    }
    return recent_ids, past_ids

def _augment_with_refined(result_item: Dict[str, Any]) -> Dict[str, Any]:
    d = result_item.get("document")
    t = (result_item.get("section_title") or "").strip()
    p = result_item.get("page_number")
    # prefer doc+page match (title may be '(untitled)')
    sec = next(
        (
            s
            for s in LIB_SECTIONS
            if s.get("document") == d and str(s.get("page_number")) == str(p)
        ),
        None,
    )
    if not sec:
        sec = next(
            (
                s
                for s in LIB_SECTIONS
                if s.get("document") == d
                and (s.get("section_title") or "").strip() == t
            ),
            None,
        )
    if sec:
        item = dict(result_item)
        item["refined_text"] = sec.get("refined_text", "")
        item["section_title"] = _title_for_section(sec)
        return item
    return result_item

# -----------------------------------------------------------------------------------------
# Health / UI
# -----------------------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify(status="ok"), 200

@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")

# -----------------------------------------------------------------------------------------
# Adobe 1A (legacy) -> proxy to 1B
# -----------------------------------------------------------------------------------------
@app.route("/extract_1a", methods=["POST"])
def extract_1a():
    return extract_1b()

# -----------------------------------------------------------------------------------------
# Adobe 1B (invokes 1A internally) + absorb into library
# -----------------------------------------------------------------------------------------
@app.route("/extract_1b", methods=["POST"])
def extract_1b():
    uploaded_files = request.files.getlist("pdfs")
    data = request.get_json(silent=True) or {}
    persona = request.form.get("persona") or data.get("persona")
    job = request.form.get("job") or data.get("job")

    if not uploaded_files:
        return jsonify({"error": "No PDFs uploaded"}), 400
    if not persona or not job:
        return jsonify({"error": "Both 'persona' and 'job' are required"}), 400

    base = BASE_DIR
    a1b_dir = Path(os.environ.get("A1B_DIR", str(base / "Adobe1ab" / "Adobe1b")))
    a1a_dir = Path(os.environ.get("A1A_PATH", str(base / "Adobe1ab" / "Adobe1a")))
    main_py = a1b_dir / "src" / "main.py"

    if not main_py.exists():
        return jsonify({"error": f"1B main.py not found at {main_py}"}), 500
    if not a1a_dir.exists():
        return jsonify({"error": f"1A folder not found at {a1a_dir}"}), 500

    input_dir = a1b_dir / "input"
    output_dir = a1b_dir / "output"
    output_file = output_dir / "output.json"
    input_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    # clear previous inputs
    for p in input_dir.glob("*"):
        try:
            if p.is_file() or p.is_symlink():
                p.unlink()
        except Exception:
            pass

    # save uploads
    for f in uploaded_files:
        f.save(str(input_dir / f.filename))

    # env for 1B (wire 1A)
    env = os.environ.copy()
    env["A1B_USE_1A"] = "1"
    env["A1A_PATH"] = str(a1a_dir)
    env.setdefault("A1B_INCLUDE_HIGHLIGHTS", "0")
    env["PYTHONIOENCODING"] = "utf-8"

    cmd = [
        sys.executable,
        str(main_py),
        "--persona",
        persona,
        "--job",
        job,
        "--input_dir",
        str(input_dir),
        "--output_file",
        str(output_file),
    ]

    run = subprocess.run(
        cmd,
        env=env,
        cwd=str(a1b_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
    )

    if run.returncode != 0:
        return (
            jsonify(
                {
                    "error": "Adobe 1B pipeline failed",
                    "stderr": run.stderr.strip(),
                    "stdout": run.stdout.strip(),
                    "cmd": " ".join(cmd),
                    "cwd": str(a1b_dir),
                }
            ),
            500,
        )

    if not Path(output_file).exists():
        return jsonify({"error": f"1B finished without creating {output_file}"}), 500

    with open(output_file, "r", encoding="utf-8") as jf:
        obj = json.load(jf)

    # --- absorb extracted sections into library for Connect Insights ---
    batch_id = META["next_batch_id"]
    META["next_batch_id"] += 1
    try:
        secs = _sections_from_1b(obj)
        if secs:
            _absorb_sections(secs, batch_id=batch_id)
    except Exception as e:
        print("[WARN] absorb 1B -> library:", e)

    return jsonify(obj)

# -----------------------------------------------------------------------------------------
# SNIPPETS (Why this section?)
# -----------------------------------------------------------------------------------------
def _import_build_snippet():
    """Locate and import build_snippet from Adobe1ab/Adobe1b/src/snippets.py."""
    adobe1b_src = BASE_DIR / "Adobe1ab" / "Adobe1b" / "src"
    snippets_path = adobe1b_src / "snippets.py"
    if str(adobe1b_src) not in sys.path:
        sys.path.insert(0, str(adobe1b_src))
    try:
        from snippets import build_snippet  # type: ignore
        return build_snippet
    except Exception:
        pass

    if snippets_path.exists():
        spec = importlib.util.spec_from_file_location("snippets_dyn", str(snippets_path))
        mod = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(mod)  # type: ignore
        fn = getattr(mod, "build_snippet", None)
        if fn is None:
            raise ImportError(f"'build_snippet' not found in {snippets_path}")
        return fn

    raise ModuleNotFoundError(f"Could not locate snippets.py at {snippets_path}")

@app.route("/snippet_explain", methods=["POST", "OPTIONS"])
def snippet_explain():
    if request.method == "OPTIONS":
        return ("", 204)
    try:
        build_snippet = _import_build_snippet()
    except Exception as e:
        return jsonify(error=f"snippets import failed: {e}"), 500

    data = request.get_json(force=True) or {}
    focus = (data.get("focus_text") or "").strip()
    cand = (data.get("candidate_text") or "").strip()

    if not focus:
        return jsonify(error="focus_text is required"), 400
    if not cand:
        return jsonify(error="candidate_text is required"), 400

    try:
        snippet = (build_snippet(focus, cand) or "").strip()
        if not snippet:
            snippet = "No concise reason found for this section."
        return jsonify(snippet=snippet), 200
    except Exception as e:
        return jsonify(error=f"snippet_explain failed: {e}"), 500

# -----------------------------------------------------------------------------------------
# Insights (KEEPING EXACTLY AS IS)
# -----------------------------------------------------------------------------------------
@app.route("/insight", methods=["POST", "OPTIONS"])
def insight():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True, silent=True) or {}
    section_text = data.get("section_text", "")
    if not section_text:
        return jsonify({"error": "Prompt text required"}), 400
    result = get_insights(section_text)
    return jsonify({"insight": result})

@app.after_request
def _add_cors_headers(resp):
    origin = request.headers.get("Origin", "*")
    resp.headers["Access-Control-Allow-Origin"] = origin
    req_hdrs = request.headers.get("Access-Control-Request-Headers")
    resp.headers["Access-Control-Allow-Headers"] = (
        req_hdrs or "Content-Type, Authorization, X-Requested-With"
    )
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Vary"] = "Origin"
    return resp

# -----------------------------------------------------------------------------------------
# Connect the Insights (NEW)
# -----------------------------------------------------------------------------------------
import math

def _as_list(x):
    if hasattr(x, "tolist"): return x.tolist()
    return list(x or [])

def _coerce_dim(vec, target_dim):
    v = _as_list(vec)
    if len(v) == target_dim:
        return v
    if len(v) > target_dim:
        return v[:target_dim]
    return v + [0.0] * (target_dim - len(v))

def _cosine(a, b):
    da = sum(x*x for x in a)
    db = sum(x*x for x in b)
    if da <= 0 or db <= 0:
        return 0.0
    dot = sum(x*y for x, y in zip(a, b))
    return float(dot / math.sqrt(da*db))

def _safe_rank(selection_text, lib_sections, top_k=12):
    qv = embed_texts([selection_text])[0]
    qv = _as_list(qv)
    target = len(qv)

    scored = []
    for s in lib_sections:
        sv = s.get("embedding")
        if not isinstance(sv, (list, tuple)) or len(sv) == 0:
            continue
        sv = _coerce_dim(sv, target)
        score = _cosine(qv, sv)
        scored.append({
            "document": s.get("document"),
            "page_number": s.get("page_number"),
            "section_title": (s.get("section_title") or "").strip() or "(untitled)",
            "snippet": "",
            "score": score,
        })
    scored.sort(key=lambda r: r["score"], reverse=True)
    return scored[:top_k]

@app.post("/select_insights")
def select_insights():
    data = request.get_json(silent=True) or {}
    text = (data.get("selection_text") or data.get("text") or "").strip()
    top_k = int(data.get("top_k") or 8)

    if not text:
        return jsonify(error="selection_text is required"), 400

    if not LIB_SECTIONS:
        return jsonify(
            related_recent=[], related_past=[], overlaps=[],
            contradictions=[], highlights=[],
            grounded_summary="(library empty: run Extract first)"
        ), 200

    try:
        ranked = rank_and_snippetize(
            text, LIB_SECTIONS, top_k=max(top_k, 12), use_existing_embeddings=True
        ) or []
    except Exception:
        ranked = _safe_rank(text, LIB_SECTIONS, top_k=max(top_k, 12))

    recent_ids, past_ids = _split_recent_past()

    def _batch_for(r):
        doc = r.get("document")
        title = (r.get("section_title") or "").strip()
        page = r.get("page_number")
        s = next((s for s in LIB_SECTIONS
                  if s.get("document")==doc and str(s.get("page_number"))==str(page)), None)
        if not s and doc and title:
            s = next((s for s in LIB_SECTIONS
                      if s.get("document")==doc and (s.get("section_title") or "").strip()==title), None)
        return s.get("batch_id") if s else None

    def _augment(r):
        try:
            return _augment_with_refined(r)
        except Exception:
            return r

    rel_recent = [_augment(r) for r in ranked if _batch_for(r) in recent_ids][:top_k]
    rel_past   = [_augment(r) for r in ranked if _batch_for(r) in past_ids][:top_k]

    seen, overlaps = {}, []
    for r in ranked[:top_k]:
        t = (r.get("section_title") or "").strip()
        d = r.get("document")
        if not t or not d: continue
        if t in seen and seen[t] != d:
            overlaps.append(_augment(r))
        else:
            seen[t] = d

    neg_cues = ("contrary","contradict","however","nevertheless"," not ",
                "fails to","lower than","decrease","worse")
    contradictions = []
    for r in ranked[:top_k]:
        snip = (r.get("snippet") or "").lower()
        if any(c in snip for c in neg_cues):
            contradictions.append(_augment(r))

    highlights = []
    for r in (rel_recent + rel_past)[:top_k]:
        doc  = r.get("document")
        page = r.get("page_number")
        title = (r.get("section_title") or "").strip()
        sec_text = next((s.get("refined_text","") for s in LIB_SECTIONS
                         if s.get("document")==doc and str(s.get("page_number"))==str(page)), "")
        try:
            why = build_snippet_safe(text, sec_text)
        except Exception as e:
            why = f"(why unavailable: {e})"
        highlights.append({"doc": doc, "page": page, "title": title, "why": why})

    def _fmt(items):
        out = []
        for i in items:
            out.append(f"- [{i.get('document','?')} p.{i.get('page_number','?')}] "
                       f"{(i.get('section_title') or '').strip() or '(untitled)'} — {i.get('snippet','')}")
        return "\n".join(out)

    prompt = f"""You are a research assistant that MUST stay grounded ONLY in the provided citations.
User selection: \"\"\"{text}\"\"\" 
Recent docs: {_fmt(rel_recent)}
Past docs: {_fmt(rel_past)}
Overlaps: {_fmt(overlaps)}
Contradictions: {_fmt(contradictions)}
Write a concise note that CONNECTS THE DOTS:
- call out overlaps & contradictions
- relate recent to past
- ONLY use the bullets; no external knowledge
- short inline cites like (Doc p.#)
- 6–10 sentences total."""
    try:
        grounded_summary = get_insights(prompt)
    except Exception as e:
        grounded_summary = f"(LLM unavailable) {e}"

    return jsonify(
        related_recent=rel_recent,
        related_past=rel_past,
        overlaps=overlaps,
        contradictions=contradictions,
        highlights=highlights,
        grounded_summary=grounded_summary,
    ), 200

# -----------------------------------------------------------------------------------------
# Podcast (MERGED from old backend)
# -----------------------------------------------------------------------------------------

# --- Helpers to keep TTS from reading list symbols ---
_BULLET_PREFIX = r"^\s*(?:[-*\u2022\u2023\u25AA\u25CF\u25E6]|[\(\[]?\d+[\.\)]|[A-Za-z][\.\)])\s*"
_MD_TRASH = r"[\*\_`#>\[\]]"

def _strip_list_markers(text: str) -> str:
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

# --- TTS capability probe ---
def _tts_probe():
    prov = (os.getenv("TTS_PROVIDER", "local") or "local").lower()
    if prov == "local":
        if _which("espeak-ng") or _which("espeak"):
            if _which("ffmpeg"):
                return True, "local: espeak(-ng) + ffmpeg"
            return False, "local: ffmpeg missing"
        return False, "local: espeak(-ng) missing"
    if prov == "gcp":
        if os.getenv("GOOGLE_API_KEY") or (os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and Path(os.getenv("GOOGLE_APPLICATION_CREDENTIALS")).exists()):
            return True, "gcp"
        return False, "gcp: credentials missing"
    if prov == "azure":
        if os.getenv("AZURE_TTS_KEY") and (os.getenv("AZURE_TTS_ENDPOINT") or os.getenv("AZURE_TTS_REGION")):
            return True, "azure"
        return False, "azure: credentials missing"
    if prov == "aoai":
        if (os.getenv("AZURE_TTS_DEPLOYMENT") or os.getenv("OPENAI_TTS_DEPLOYMENT")) and \
           (os.getenv("AZURE_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")) and \
           (os.getenv("AZURE_OPENAI_ENDPOINT") or os.getenv("OPENAI_BASE_URL")):
            return True, "aoai"
        return False, "aoai: credentials missing"
    return False, f"unsupported provider: {prov}"

_EXECUTOR = ThreadPoolExecutor(max_workers=2)
def _llm_call(prompt: str, timeout_s: int = 12) -> str:
    fut = _EXECUTOR.submit(get_insights, prompt)
    try:
        return fut.result(timeout=timeout_s)
    except FuturesTimeout:
        return ""

def _call_generate_audio(text: str, output_file: str, provider: str, voice: str = None):
    kwargs = {"output_file": output_file, "provider": provider}
    try:
        sig = inspect.signature(generate_audio)
        if voice and "voice" in sig.parameters:
            kwargs["voice"] = voice
    except Exception:
        pass
    return generate_audio(text, **kwargs)

def _speak_or_script(script_text: str, filename_prefix: str):
    tts_ok, _note = _tts_probe()
    if not tts_ok:
        return jsonify({"script": script_text, "mode": "client-tts"}), 200

    provider = os.getenv("TTS_PROVIDER", "local")
    out_dir = BASE_DIR / "podcast"; out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{filename_prefix}_{uuid4().hex}.mp3"
    try:
        audio_path = _call_generate_audio(script_text, output_file=str(out_file), provider=provider)
        return send_file(str(audio_path), mimetype="audio/mpeg", as_attachment=False, download_name=f"{filename_prefix}.mp3")
    except Exception as e:
        return jsonify({"script": script_text, "mode": "client-tts", "error": str(e)}), 200

# ---------- NEW: inlined, dependency-free bullets for Duo (no nested request) ----------
def _insight_bullets_for_text(text: str, top_k: int = 6) -> List[str]:
    """Rank sections and build short 'why it matters' bullets for Duo."""
    text = (text or "").strip()
    if not text or not LIB_SECTIONS:
        return []
    try:
        ranked = rank_and_snippetize(text, LIB_SECTIONS, top_k=max(top_k, 12), use_existing_embeddings=True) or []
    except Exception:
        ranked = _safe_rank(text, LIB_SECTIONS, top_k=max(top_k, 12))
    picked = ranked[:top_k]
    bullets = []
    for r in picked:
        doc = r.get("document")
        page = r.get("page_number")
        sec_text = next((s.get("refined_text","") for s in LIB_SECTIONS
                         if s.get("document")==doc and str(s.get("page_number"))==str(page)), "")
        try:
            why = build_snippet_safe(text, sec_text)
        except Exception:
            why = ""
        if why:
            bullets.append(_strip_list_markers(f"{why} ({doc} p.{page})"))
    return bullets

def _dedupe_consecutive(lines: List[str], window: int = 3, thresh: float = 0.92) -> List[str]:
    """
    Remove near-duplicate lines within a small rolling window to prevent repeated
    sentences in audio (sometimes LLMs echo one line).
    """
    out: List[str] = []
    for ln in lines:
        norm = re.sub(r"\s+", " ", (ln or "")).strip()
        if not norm:
            continue
        # compare to last few lines
        is_dup = False
        for prev in out[-window:]:
            r = difflib.SequenceMatcher(None, prev.lower(), norm.lower()).ratio()
            if r >= thresh:
                is_dup = True
                break
        if not is_dup:
            out.append(norm)
    return out

def _duo_from_bullets(selection: str, bullets: List[str]) -> str:
    """
    Generate a Host/Guest dialog with real insights from the pasted selection.
    It never reads bullet symbols and always returns clean, speakable lines.
    """
    sel = _strip_list_markers(selection)
    facts = [_strip_list_markers(b) for b in (bullets or []) if _strip_list_markers(b)]
    facts = facts[:10] or ["Context is limited; synthesize the most likely goals, risks, and next steps."]

    prompt = f"""
Create a short two-person conversation that explains and critiques the content below.

STRICT OUTPUT RULES:
- Exactly 12–16 lines, alternating labels: "Host:" then "Guest:" (case-sensitive).
- One sentence per line; no lists, no markdown, no emojis.
- DO NOT read or mention any list symbols like '-', '*', '•', numbers, or the word "bullet".
- Include: 2–3 key takeaways, 1 tension/uncertainty or contradiction, and 2 concrete next steps.
- Make tight connections between items (why they matter, implications, trade-offs).
- End with exactly: "Host: That wraps it. Thanks for listening."

Selection:
\"\"\"{sel[:4000]}\"\"\"

Facts to draw from (convert into speech; do not quote literally or as bullets):
{chr(10).join(f"- {x}" for x in facts)}
"""
    raw = _llm_call(prompt, timeout_s=14)

    # Post-clean to ensure no stray markers/unlabeled lines slip through
    cleaned: List[str] = []
    for ln in (raw or "").splitlines():
        if not ln.strip():
            continue
        if ln.lower().startswith("host:") or ln.lower().startswith("guest:"):
            role, msg = ln.split(":", 1)
            cleaned.append(f"{role.title()}: {_strip_list_markers(msg)}")
        else:
            role = "Host" if len(cleaned) % 2 == 0 else "Guest"
            cleaned.append(f"{role}: {_strip_list_markers(ln)}")
        if len(cleaned) >= 16:
            break

    # Remove near-duplicates in a small window to prevent audible repeats
    cleaned = _dedupe_consecutive(cleaned, window=3, thresh=0.92)

    # Enforce alternation & minimum length
    while len(cleaned) < 12:
        role = "Host" if len(cleaned) % 2 == 0 else "Guest"
        cleaned.append(f"{role}: One more takeaway tied to the selection and why it matters.")
    cleaned[-1] = "Host: That wraps it. Thanks for listening."

    return "\n".join(cleaned)

def _duo_audio_or_script(script: str, filename_prefix: str):
    """
    If the provider supports per-voice synthesis and ffmpeg is present,
    synthesize Host/Guest with different voices and stitch. Otherwise return script.
    """
    tts_ok, _note = _tts_probe()
    if not tts_ok:
        return jsonify({"script": script, "mode": "client-tts"}), 200

    provider = (os.getenv("TTS_PROVIDER", "local") or "local").lower()
    host_voice = os.getenv("TTS_VOICE_HOST") or "en-US-AriaNeural"
    guest_voice = os.getenv("TTS_VOICE_GUEST") or "en-US-GuyNeural"

    # Need ffmpeg at least for fallback / metadata
    if not _which("ffmpeg"):
        return jsonify({"script": script, "mode": "client-tts", "note": "ffmpeg missing for server-side duo"}), 200

    # Split lines by role
    parts = []
    for line in (script or "").splitlines():
        if not line.strip():
            continue
        if line.lower().startswith("guest:"):
            parts.append(("guest", line.split(":", 1)[1].strip()))
        elif line.lower().startswith("host:"):
            parts.append(("host", line.split(":", 1)[1].strip()))
        else:
            parts.append(("host", line.strip()))
    if not parts:
        return jsonify({"script": script, "mode": "client-tts"}), 200

    out_dir = BASE_DIR / "podcast"; out_dir.mkdir(parents=True, exist_ok=True)
    final_path = out_dir / f"{filename_prefix}_{uuid4().hex}.mp3"

    tmpdir = Path(tempfile.mkdtemp(prefix="duotts_"))
    segment_files: List[Path] = []
    try:
        # 1) Synthesize each line to its own mp3
        for idx, (who, text) in enumerate(parts):
            # skip ultra-short content to avoid empty/quirky segments
            if not text or len(text.strip()) < 2:
                continue
            seg = tmpdir / f"seg_{idx:03d}.mp3"
            voice = host_voice if who == "host" else guest_voice
            _call_generate_audio(text, output_file=str(seg), provider=provider, voice=voice)
            segment_files.append(seg)

        if not segment_files:
            return jsonify({"script": script, "mode": "client-tts"}), 200

        # 2) Prefer pydub concat (decode+re-encode); fallback to ffmpeg re-encode
        try:
            from pydub import AudioSegment
            # Make sure pydub uses system ffmpeg in Docker
            try:
                AudioSegment.converter = "/usr/bin/ffmpeg"
                AudioSegment.ffprobe = "/usr/bin/ffprobe"
            except Exception:
                pass

            gap_ms = int(os.getenv("TTS_GAP_MS", "60"))
            silence = AudioSegment.silent(duration=max(0, gap_ms))
            combined = None
            for p in segment_files:
                seg = AudioSegment.from_file(p.as_posix(), format="mp3")
                seg = seg.set_frame_rate(44100).set_channels(2)
                combined = seg if combined is None else (combined + silence + seg)

            combined.export(final_path.as_posix(), format="mp3", bitrate="160k")
        except Exception:
            # Robust ffmpeg concat with re-encode (NO -c copy)
            listfile = tmpdir / "list.txt"
            listfile.write_text("".join([f"file '{p.as_posix()}'\n" for p in segment_files]), encoding="utf-8")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", str(listfile),
                "-vn",
                "-ar", "44100", "-ac", "2",
                "-b:a", "160k",
                "-c:a", "libmp3lame",
                str(final_path),
            ]
            run = subprocess.run(cmd, capture_output=True, text=True)
            if run.returncode != 0 or not final_path.exists():
                return jsonify({"script": script, "mode": "client-tts", "error": run.stderr}), 200

        # 3) Send with no-store to avoid browsers reusing a stale audio blob
        resp = send_file(str(final_path), mimetype="audio/mpeg", as_attachment=False, download_name=f"{filename_prefix}.mp3")
        try:
            resp.headers["Cache-Control"] = "no-store"
        except Exception:
            pass
        return resp

    except Exception as e:
        return jsonify({"script": script, "mode": "client-tts", "error": str(e)}), 200
    finally:
        try:
            for p in segment_files:
                if p.exists():
                    p.unlink()
            if tmpdir.exists():
                for p in tmpdir.glob("*"):
                    try: p.unlink()
                    except: pass
                tmpdir.rmdir()
        except: pass


# --- Routes ---

@app.route("/podcast", methods=["POST"])
def podcast():
    data = request.get_json(force=True, silent=True) or {}
    section_text = (data.get("section_text") or "").strip()
    if not section_text:
        return jsonify({"error": "No text provided"}), 400

    narr_prompt = (
        "Write a friendly, dynamic 9–12 sentence spoken summary. "
        "Use short sentences, vary rhythm, include brief pauses with commas or ellipses. "
        "Stay grounded ONLY in this text:\n\n" + section_text
    )
    script = _llm_call(narr_prompt, timeout_s=10) or section_text
    return _speak_or_script(script, "summary")

# --------- UPDATED: Duo reads same input & avoids nested request; handles OPTIONS ----------
@app.route("/podcast_duo", methods=["POST", "OPTIONS"])
def podcast_duo():
    if request.method == "OPTIONS":
        return ("", 204)
    data = request.get_json(force=True, silent=True) or {}
    section_text = (data.get("section_text") or data.get("selection_text") or "").strip()
    if not section_text:
        return jsonify(error="section_text is required"), 400

    bullets = _insight_bullets_for_text(section_text, top_k=6)
    script = _duo_from_bullets(section_text, bullets)
    return _duo_audio_or_script(script, "duo")

# -----------------------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False, use_reloader=False, threaded=True)

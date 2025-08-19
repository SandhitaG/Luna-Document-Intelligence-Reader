# backend/src/snippets.py
import re
from typing import List, Dict, Tuple, Optional
import numpy as np

# ---- simple stopword set (no downloads) ----
_STOP = {
    "a","an","the","and","or","but","if","then","so","to","of","in","on","for","with","by","as",
    "is","are","was","were","be","been","being","this","that","these","those","it","its","at",
    "from","into","about","over","after","before","between","out","up","down","off","than","too",
    "very","can","cannot","could","should","would","may","might","will","just","not","no","nor",
    "you","your","yours","we","our","ours","they","them","their","theirs","i","me","my","mine",
}

_SENT_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")

INGR_RE = re.compile(r"\b(ingredients?|shopping\s*list)\b", re.I)
INSTR_RE = re.compile(r"\b(method|steps?|instructions?)\b", re.I)
TIME_RE  = re.compile(r"\b(\d{1,3})\s*(mins?|minutes?|hrs?|hours?)\b", re.I)
SERVE_RE = re.compile(r"\b(serves?\s+\d+|\d+\s*servings?)\b", re.I)

def _tokens(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]

def _top_terms(text: str, k: int = 5) -> List[str]:
    toks = [t for t in _tokens(text) if t not in _STOP and len(t) >= 3]
    if not toks:
        return []
    freq = {}
    for t in toks:
        freq[t] = freq.get(t, 0) + 1
    scored = [(t, c / (1 + (len(t) <= 4))) for t, c in freq.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:k]]

def split_sentences(text: str) -> List[str]:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t:
        return []
    if len(t) < 120:
        return [t]
    parts = _SENT_SPLIT_RE.split(t)
    out = []
    for s in parts:
        s = s.strip()
        if 25 <= len(s) <= 240:
            out.append(s)
    if not out:
        out = [t[:240].strip()]
    return out[:8]

# ---- embeddings (use MiniLM if available, else hashing fallback) ----
_MODEL = None

def _load_model():
    global _MODEL
    if _MODEL is not None:
        return _MODEL
    try:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _MODEL = None
    return _MODEL

def embed_texts(texts: List[str]) -> np.ndarray:
    m = _load_model()
    if m is not None:
        vecs = m.encode(texts, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)

    # hashing fallback (keeps offline path working even without the model)
    dim = 256
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        for tok in _tokens(t):
            h = (hash(tok) % dim)
            out[i, h] += 1.0
        n = np.linalg.norm(out[i])
        if n > 0:
            out[i] /= n
    return out

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b))

# ---------- Persona / Job parsing & section classification ----------

def _extract_persona_job(focus_text: str) -> Tuple[str, str]:
    """
    Heuristic parse of persona & job from a free-form focus_text.
    Accepts formats like:
      "Persona: Busy Student | Job: find quick, cheap dinner ideas"
      "persona=Home Cook; job-to-be-done: plan a healthy lunch"
      or any paragraph mentioning persona / role and goal.
    Falls back to salient terms if explicit labels are missing.
    """
    t = (focus_text or "").strip()
    lo = t.lower()

    # Try explicit labels
    def grab(label: str) -> Optional[str]:
        m = re.search(rf"{label}\s*[:=]\s*(.+?)(?:[|.\n]|$)", lo, re.I)
        if not m:
            return None
        span = m.span(1)
        return t[span[0]:span[1]].strip(" .|")

    persona = grab("persona") or grab("role") or ""
    job = grab("job(?:-?to-?be-?done)?") or grab("goal") or ""

    # Fall back to term-based sketches
    if not persona:
        # take up to 2 salient tokens as a rough persona tag
        persona_terms = _top_terms(t, k=2)
        persona = "user" if not persona_terms else " ".join(persona_terms)

    if not job:
        # grab verbs/nouns that look like intents
        intents = []
        for w in _tokens(t):
            if w in _STOP:
                continue
            if w.endswith(("e","ing")) or w in {"plan","choose","compare","save","cook","learn","teach","present","shop","budget","optimize"}:
                intents.append(w)
        job = " ".join(intents[:6]) if intents else "complete the task"

    # Keep short & human
    persona = re.sub(r"\s+", " ", persona).strip()[:60] or "user"
    job = re.sub(r"\s+", " ", job).strip()[:100] or "complete the task"
    return (persona, job)

def _classify_section(text: str) -> str:
    """
    Very lightweight classifier to steer phrasing.
    Returns one of: 'recipe', 'howto', 'overview', 'tips', 'data', 'generic'
    """
    lo = (text or "").lower()

    # Recipe/food lists
    if INGR_RE.search(lo) or "recipe" in lo or "prep" in lo or INSTR_RE.search(lo):
        return "recipe"

    # How-to / procedural
    if any(k in lo for k in ["step", "how to", "guide", "procedure", "method"]):
        return "howto"

    # Tips / best practices
    if any(k in lo for k in ["tip", "tips", "tricks", "best practice", "recommendation"]):
        return "tips"

    # Overview / description / background
    if any(k in lo for k in ["overview", "background", "summary", "introduction"]):
        return "overview"

    # Tables / numbers vibe
    if any(k in lo for k in ["table", "serves", "calorie", "nutrition", "dataset", "score", "metric"]):
        return "data"

    return "generic"

def _quick_facts(text: str) -> List[str]:
    """Pull 1–2 meta-facts without echoing lists."""
    facts = []
    tm = TIME_RE.search(text or "")
    if tm:
        facts.append(f"{tm.group(0)}")
    sv = SERVE_RE.search(text or "")
    if sv:
        facts.append(sv.group(0).capitalize())
    return facts[:2]

def _clean_title_like(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    return s[:80]

# ---------- Snippet building focused on persona + job ----------

def build_snippet(
    focus_text: str,
    candidate_text: str,
    section_title: Optional[str] = None
) -> str:
    """
    Returns a 1–2 sentence snippet that explains *why this section is relevant*
    to the persona & job described by `focus_text`. Avoids copying ingredient
    lines or bullets from the document.
    """
    focus_text = (focus_text or "").strip()
    candidate_text = (candidate_text or "").strip()
    if not candidate_text:
        return ""

    persona, job = _extract_persona_job(focus_text)
    kind = _classify_section(candidate_text)
    title = _clean_title_like(section_title)

    # Meta facts (optional)
    facts = _quick_facts(candidate_text)
    fact_tail = f" ({', '.join(facts)})" if facts else ""

    # Phrasing templates (kept tight; 1–2 sentences max)
    if kind == "recipe":
        # Don't dump ingredients; describe usefulness for the goal.
        lead = f"This section gives the core recipe{' for ' + title if title else ''}, focusing on what you actually need and how to execute it{fact_tail}."
        why = f" It helps a {persona} aiming to {job} by turning the idea into an actionable dish without hunting through long descriptions."
        return (lead + why)[:300]

    if kind == "howto":
        lead = f"A concise how-to{' for ' + title if title else ''} that lays out the steps clearly."
        why = f" Useful for a {persona} who needs to {job} and wants a straightforward path from start to finish."
        return (lead + " " + why)[:300]

    if kind == "tips":
        lead = f"Practical tips and small optimizations{' around ' + title if title else ''} to improve results."
        why = f" This directly supports a {persona} trying to {job} by highlighting what to do (and avoid) in practice."
        return (lead + " " + why)[:300]

    if kind == "overview":
        lead = f"A brief overview{' of ' + title if title else ''} that frames the what and why."
        why = f" It orients a {persona} toward {job}, so you can scan context before diving into details."
        return (lead + " " + why)[:300]

    if kind == "data":
        lead = f"Reference details and quantitative notes{' for ' + title if title else ''}{fact_tail}."
        why = f" Helpful to a {persona} focused on {job}, enabling quick checks and consistent decisions."
        return (lead + " " + why)[:300]

    # Generic fallback (semantic evidence, but rephrased as relevance)
    # Select one semantically closest sentence to ground the summary, then rephrase.
    cand_sents = split_sentences(candidate_text) or [candidate_text[:160]]
    enc = embed_texts([focus_text] + cand_sents)
    q = enc[0]
    sims = [(float(np.dot(q, enc[i+1])), i) for i in range(len(cand_sents))]
    sims.sort(reverse=True, key=lambda x: x[0])
    best = cand_sents[sims[0][1]].strip().rstrip(".")
    # Rephrase as relevance (no raw copying of lists)
    best = re.sub(r"(?i)\b(ingredients?|instructions?|step\s*\d+|serves?\s*\d+).*$", "", best).strip()
    lead = f"This part{' on ' + title if title else ''} is the most connected to your goal."
    why = f" It supports a {persona} who wants to {job} by providing the key details you can act on right away."
    return (lead + " " + why)[:300]

# ---------- Ranking + snippetization ----------

def rank_and_snippetize(
    focus_text: str,
    sections: List[Dict],
    top_k: int = 5,
    use_existing_embeddings: bool = True,
) -> List[Dict]:
    """
    sections: list of dicts with keys:
      - 'section_title' (str)
      - 'refined_text'  (str)
      - 'document'      (str)
      - 'page_number'   (int)
      - optional 'embedding' (List[float])  # if available from your pipeline

    Returns top_k items with fields + 'score' + 'snippet'.
    """
    texts = [focus_text] + [s.get("refined_text", "") for s in sections]

    # prefer existing embeddings if present & consistent
    if use_existing_embeddings and sections and isinstance(sections[0].get("embedding"), list):
        q_vec = embed_texts([focus_text])[0] if focus_text else None
        if q_vec is None:
            q_vec = np.zeros(len(sections[0]["embedding"]), dtype=np.float32)
        vecs = [q_vec]
        for s in sections:
            v = np.asarray(s.get("embedding"), dtype=np.float32)
            n = np.linalg.norm(v)
            if n > 0 and (abs(n - 1.0) > 1e-3):
                v = v / n
            vecs.append(v)
        vecs = np.stack(vecs, axis=0)
    else:
        vecs = embed_texts(texts)

    q = vecs[0]
    cands = vecs[1:]
    sims = [(_cosine(q, cands[i]), i) for i in range(len(sections))]
    sims.sort(reverse=True, key=lambda x: x[0])

    results = []
    for score, i in sims[:top_k]:
        sec = sections[i]
        snippet = build_snippet(
            focus_text,
            sec.get("refined_text", ""),
            section_title=sec.get("section_title", "")
        )
        results.append({
            "document": sec.get("document"),
            "page_number": sec.get("page_number"),
            "section_title": sec.get("section_title"),
            "score": round(float(score), 4),
            "snippet": snippet
        })
    return results

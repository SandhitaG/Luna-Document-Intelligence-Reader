# backend/snippets_safe.py
import os
import re
from typing import List, Dict
import numpy as np

# ------------------------
# Lightweight text utils
# ------------------------
_STOP = {
    "a","an","the","and","or","but","if","then","so","to","of","in","on","for","with","by","as",
    "is","are","was","were","be","been","being","this","that","these","those","it","its","at",
    "from","into","about","over","after","before","between","out","up","down","off","than","too",
    "very","can","cannot","could","should","would","may","might","will","just","not","no","nor",
    "you","your","yours","we","our","ours","they","them","their","theirs","i","me","my","mine",
}
_SENT_SPLIT_RE = re.compile(r'(?<=[.!?])\s+(?=[A-Z0-9])')
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")

def _tokens(text: str) -> List[str]:
    return [w.lower() for w in _WORD_RE.findall(text or "")]

def _top_terms(text: str, k: int = 5) -> List[str]:
    toks = [t for t in _tokens(text) if t not in _STOP and len(t) >= 3]
    if not toks: return []
    freq = {}
    for t in toks: freq[t] = freq.get(t, 0) + 1
    scored = [(t, c / (1 + (len(t) <= 4))) for t, c in freq.items()]
    scored.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in scored[:k]]

def split_sentences(text: str) -> List[str]:
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if not t: return []
    if len(t) < 120: return [t]
    parts = _SENT_SPLIT_RE.split(t)
    out = [s.strip() for s in parts if 25 <= len(s.strip()) <= 240]
    if not out: out = [t[:240].strip()]
    return out[:8]

# ------------------------
# Embedding backend
# ------------------------
_MODEL = None
_FALLBACK_DIM = int(os.getenv("EMBED_FALLBACK_DIM", "384"))  # default 384 to match MiniLM

def _load_model():
    global _MODEL
    if _MODEL is not None: return _MODEL
    try:
        from sentence_transformers import SentenceTransformer
        # 384-d embeddings
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:
        _MODEL = None
    return _MODEL

def embed_texts(texts: List[str]) -> np.ndarray:
    """
    Returns float32 np.ndarray of shape (N, D). If sentence-transformers is not
    available, uses a deterministic hashed bag-of-words of size _FALLBACK_DIM.
    """
    m = _load_model()
    if m is not None:
        vecs = m.encode(texts, normalize_embeddings=True)
        return np.asarray(vecs, dtype=np.float32)

    dim = _FALLBACK_DIM
    out = np.zeros((len(texts), dim), dtype=np.float32)
    for i, t in enumerate(texts):
        # very simple hashed bow
        for tok in _tokens(t):
            h = (hash(tok) % dim)
            out[i, h] += 1.0
        n = np.linalg.norm(out[i])
        if n > 0: out[i] /= n
    return out

# ------------------------
# Vector helpers (robust to dim mismatch)
# ------------------------
def _normalize(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else v

def _align_to(v: np.ndarray, target_len: int) -> np.ndarray:
    """
    Truncate or zero-pad v to target_len.
    """
    if v.ndim == 0:
        v = np.asarray([float(v)], dtype=np.float32)
    v = v.astype(np.float32, copy=False)
    if v.shape[0] == target_len:
        return v
    if v.shape[0] > target_len:
        return v[:target_len]
    # pad
    out = np.zeros((target_len,), dtype=np.float32)
    out[:v.shape[0]] = v
    return out

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity that safely handles different lengths by using
    the common prefix length (or pre-aligned inputs).
    """
    a = np.asarray(a, dtype=np.float32).ravel()
    b = np.asarray(b, dtype=np.float32).ravel()
    n = min(a.shape[0], b.shape[0])
    if n == 0:
        return 0.0
    a = a[:n]; b = b[:n]
    na = np.linalg.norm(a); nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

# ------------------------
# Snippet builder
# ------------------------
def build_snippet(focus_text: str, candidate_text: str) -> str:
    focus_text = (focus_text or "").strip()
    candidate_text = (candidate_text or "").strip()
    if not candidate_text: return ""

    cand_sents = split_sentences(candidate_text) or [candidate_text[:200]]
    enc = embed_texts([focus_text] + cand_sents)
    q = enc[0]; sent_vecs = enc[1:]

    sims = [(_cosine(q, v), i) for i, v in enumerate(sent_vecs)]
    sims.sort(reverse=True, key=lambda x: x[0])

    chosen, used = [], set()
    for _, idx in sims[:3]:
        s = cand_sents[idx].strip(); key = s[:40]
        if key in used: continue
        used.add(key); chosen.append(s)
        if len(chosen) == 2: break

    f_terms = set(_top_terms(focus_text, k=6))
    c_terms = [t for t in _top_terms(candidate_text, k=6) if t in f_terms]
    reason = ""
    if c_terms:
        reason = f" Relevant because it covers {', '.join(c_terms[:2])}, which ties to your current section."

    if not chosen: return reason.strip()[:300]
    if len(chosen) == 1:
        out = chosen[0]
        if not out.endswith("."): out += "."
        out += reason
        return out.strip()[:300]

    combined = f"{chosen[0]} {chosen[1]}"
    if len(combined) > 220:
        out = chosen[0]
        if not out.endswith("."): out += "."
        out += reason
        return out.strip()[:300]
    if not combined.endswith("."): combined += "."
    combined += reason
    return combined.strip()[:300]

# ------------------------
# Ranking (dimension-safe)
# ------------------------
def rank_and_snippetize(
    focus_text: str,
    sections: List[Dict],
    top_k: int = 5,
    use_existing_embeddings: bool = True,
) -> List[Dict]:
    if not sections: return []

    # Query vector (choose target dimension from it)
    if focus_text:
        qvec = embed_texts([focus_text])[0]
    else:
        # if no focus, pick a dimension based on first section embedding (if present)
        dim = None
        if use_existing_embeddings and isinstance(sections[0].get("embedding"), list):
            dim = len(sections[0]["embedding"])
        qvec = np.zeros(dim or _FALLBACK_DIM, dtype=np.float32)
    qvec = _normalize(qvec)
    target_dim = int(qvec.shape[0])

    # Build candidate vectors; re-embed on mismatch when possible, else align
    cand_vecs: List[np.ndarray] = []
    for s in sections:
        v = None
        if use_existing_embeddings and isinstance(s.get("embedding"), list):
            v = np.asarray(s["embedding"], dtype=np.float32)

        # If we don't have an embedding or the dim mismatches, try re-embed
        if v is None or v.shape[0] != target_dim:
            try:
                v = embed_texts([s.get("refined_text", "")])[0]
            except Exception:
                # last resort: align whatever we had (or zeros)
                if v is None:
                    v = np.zeros((_FALLBACK_DIM,), dtype=np.float32)
        # ensure dimension match
        v = _align_to(v, target_dim)
        cand_vecs.append(_normalize(v))

    sims = [(_cosine(qvec, cand_vecs[i]), i) for i in range(len(sections))]
    sims.sort(reverse=True, key=lambda x: x[0])

    results = []
    for score, i in sims[:max(1, top_k)]:
        sec = sections[i]
        snippet = build_snippet(focus_text, sec.get("refined_text", ""))
        results.append({
            "document": sec.get("document"),
            "page_number": sec.get("page_number"),
            "section_title": sec.get("section_title"),
            "score": round(float(score), 4),
            "snippet": snippet
        })
    return results

import time, re, numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.decomposition import TruncatedSVD

MAX_TOP = 18
EMBED_DIM = 128

def _normalize_title(t):
    return re.sub(r"\s+", " ", (t or "").strip().lower())

def _heading_prior(level, is_bullet=False, is_stub=False):
    if is_stub:
        return -0.5
    base = 0.5
    if level == "H1":
        base = 1.0
    elif level == "H2":
        base = 0.7
    return base + (0.15 if is_bullet else 0.0)

def _cosine(a, b, eps=1e-9):
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    na = np.linalg.norm(a) + eps
    nb = np.linalg.norm(b) + eps
    return float(np.dot(a, b) / (na * nb))

def _mmr_select(query_vec, cand_vecs, items, k=MAX_TOP, lam=0.7):
    selected, selected_idx = [], []
    if not items:
        return selected
    qsim = np.array([_cosine(query_vec, v) for v in cand_vecs], dtype=float)
    used = set()
    for _ in range(min(k, len(items))):
        best_i, best_score = -1, -1e9
        for i in range(len(items)):
            if i in used:
                continue
            if selected_idx:
                div = max(_cosine(cand_vecs[i], cand_vecs[j]) for j in selected_idx)
            else:
                div = 0.0
            score = lam * qsim[i] - (1 - lam) * div
            if score > best_score:
                best_score, best_i = score, i
        if best_i == -1:
            break
        used.add(best_i)
        selected_idx.append(best_i)
        selected.append(items[best_i])
    return selected

def _safe_embed(corpus, query_text):
    """TF-IDF embedding + *safe* SVD reduction. Falls back to TF-IDF if tiny."""
    tfidf = TfidfVectorizer(
        max_features=8000,
        ngram_range=(1, 2),
        lowercase=True,
        stop_words="english",
    )
    X = tfidf.fit_transform(corpus)           # (n_samples, n_features)
    q = tfidf.transform([query_text])         # (1, n_features)
    n_samples, n_features = X.shape

    # If very small, skip SVD
    if n_features <= 2 or n_samples <= 2:
        return X.toarray(), q.toarray()[0]

    # Choose valid n_components and guard with try/except
    try:
        k = min(EMBED_DIM, n_features - 1, n_samples - 1)
        k = max(2, k)
        if k >= 2:
            svd = TruncatedSVD(n_components=k, random_state=0)
            Xr = svd.fit_transform(X)
            qr = svd.transform(q)[0]
            return Xr, qr
    except Exception:
        pass

    # Fallback: plain TF-IDF dense
    return X.toarray(), q.toarray()[0]

def rank_sections_for_persona(query_text, sections, all_docs, deadline):
    if not sections:
        return []

    # Embed title + context
    corpus = [f"{s.get('section_title','')}. {s.get('text','')}" for s in sections]
    Xr, qv = _safe_embed(corpus, query_text)

    # Score + prior
    scored = []
    for i, s in enumerate(sections):
        if time.time() > deadline:
            break
        vec = np.asarray(Xr[i], dtype=float)
        s["embedding"] = vec.astype(float).tolist()
        base = _cosine(qv, vec)
        prior = _heading_prior(s.get("heading_level"),
                               s.get("is_bullet", False),
                               s.get("is_stub", False))
        score = 0.9 * base + 0.1 * prior
        scored.append((float(score), s))

    scored.sort(key=lambda x: x[0], reverse=True)

    # De-dup by normalized title
    seen_titles, dedup = set(), []
    for sc, s in scored:
        tkey = _normalize_title(s.get("section_title", ""))
        if not tkey or tkey in seen_titles:
            continue
        seen_titles.add(tkey)
        s["_score"] = sc
        dedup.append(s)

    if not dedup:
        return []

    # Guarantee >=1 per document (from dedup order)
    top_by_doc = {}
    for s in dedup:
        d = s["document"]
        if d not in top_by_doc:
            top_by_doc[d] = s
        if len(top_by_doc) == len(all_docs):
            break

    vecs = [np.asarray(s["embedding"], dtype=float) for s in dedup]
    mmr_top = _mmr_select(np.asarray(qv, dtype=float), vecs, dedup, k=MAX_TOP, lam=0.7)

    # If MMR returns nothing (extreme edge), take top few
    if not mmr_top:
        mmr_top = dedup[:min(MAX_TOP, len(dedup))]

    # Inject missing docs
    have = {s["document"] for s in mmr_top}
    for d, s in top_by_doc.items():
        if d not in have:
            mmr_top.append(s)

    # Final rank → importance_rank
    mmr_top.sort(key=lambda s: s.get("_score", 0.0), reverse=True)
    for i, s in enumerate(mmr_top, start=1):
        s["importance_rank"] = i

    return mmr_top

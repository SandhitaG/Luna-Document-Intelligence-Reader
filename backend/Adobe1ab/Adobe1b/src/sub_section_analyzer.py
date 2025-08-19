import re, time
from sklearn.feature_extraction.text import TfidfVectorizer
import numpy as np

def _sentences(text):
    t = (text or "")
    t = re.sub(r"\s*[\r\n]+\s*", " ", t)
    t = re.sub(r"[•\-\–\—]\s+", "", t)  # remove bullet markers
    parts = re.split(r'(?<=[\.\?\!])\s+|;\s+|\u2022', t)  # .,!? ; or bullet dot
    out = [p.strip() for p in parts if p and p.strip()]
    return [p for p in out if len(re.findall(r"[A-Za-z]", p)) >= 6]

def _tfidf_rank_sentences(query_text, sentences, topk=2):
    if not sentences:
        return ""
    docs = [query_text] + sentences
    vec = TfidfVectorizer(max_features=2000, ngram_range=(1,2), lowercase=True, stop_words="english")
    X = vec.fit_transform(docs).toarray()
    qv = X[0]
    sims = []
    for i, sen_vec in enumerate(X[1:], start=0):
        denom = max(1e-9, np.linalg.norm(sen_vec) * np.linalg.norm(qv))
        cs = float(np.dot(sen_vec, qv) / denom)
        sims.append((cs, len(sentences[i]), sentences[i]))
    sims.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return " ".join(s for _,__,s in sims[:topk])

def build_snippets(query_text, ranked_sections, deadline, max_chars=600):
    out = []
    seen = set()
    for s in ranked_sections:
        if time.time() > deadline: break
        base = s.get("text") or s.get("section_title") or ""
        cands = _sentences(base)
        refined = _tfidf_rank_sentences(query_text, cands, topk=2) if cands else ""
        refined = refined[:max_chars]
        key = (s["document"], int(s["page_number"]), refined[:48])
        if refined and key in seen:
            continue
        seen.add(key)
        out.append({
            "document": s["document"],
            "page_number": int(s["page_number"]),
            "refined_text": refined
        })
    return out

from sentence_transformers import SentenceTransformer, util
import json

model = SentenceTransformer("all-MiniLM-L6-v2")

def get_recommendations(current_text, documents):
    current_embed = model.encode(current_text, convert_to_tensor=True)
    results = []
    for doc in documents:
        for section in doc["outline"]:
            section_text = section["text"]
            score = util.cos_sim(current_embed, model.encode(section_text, convert_to_tensor=True)).item()
            if score > 0.80:
                results.append({
                    "text": section_text,
                    "score": round(score, 3),
                    "page_number": section["page"],
                    "snippet": f"This section discusses a similar topic: {section_text[:80]}..."
                })
    sorted_results = sorted(results, key=lambda x: -x["score"])
    return sorted_results[:3]

import os, json

# Export page numbers as 1-based by default (matches your expected JSON)
PAGE_BASE = int(os.environ.get("A1B_PAGE_BASE", "1"))

# Do NOT include highlights/bboxes in output unless explicitly enabled
INCLUDE_HIGHLIGHTS = os.environ.get("A1B_INCLUDE_HIGHLIGHTS", "0").lower() in ("1","true","yes","on")

def write_final_output(metadata, ranked_sections, snippets, output_file):
    os.makedirs(os.path.dirname(output_file), exist_ok=True)

    extracted_sections = []
    for s in ranked_sections:
        extracted_sections.append({
            "document": s["document"],
            "page_number": int(s["page_number"]) + PAGE_BASE,
            "section_title": s.get("section_title", ""),
            "importance_rank": int(s.get("importance_rank", 0))
        })

    # Build highlights internally but only export when flag is on
    highlights = []
    if INCLUDE_HIGHLIGHTS:
        for s in ranked_sections:
            bxs = s.get("bboxes") or []
            if bxs:
                highlights.append({
                    "document": s["document"],
                    "page_number": int(s["page_number"]) + PAGE_BASE,
                    "bboxes": bxs,
                    "section_title": s.get("section_title", "")
                })

    out = {
        "metadata": metadata,
        "extracted_sections": extracted_sections,
        "sub_section_analysis": snippets
    }
    if INCLUDE_HIGHLIGHTS:
        out["highlights"] = highlights

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    return out

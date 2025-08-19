import os, json, time
from .parser import open_document, extract_page_lines
from .classifier import heading_score, assign_level, title_like
from .ocr import ocr_page

# Export pages as 1-based (matches your 1B expectation)
EXPORT_PAGE_BASE = int(os.environ.get("A1A_PAGE_BASE", "1"))

def _clean_title_candidates(lines):
    # Prefer the largest/title-like near top third of first page
    cands = [l for l in lines if title_like(l["text"])]
    if not cands:
        return None
    # score by size and proximity to top
    best = sorted(cands, key=lambda l: (-l["size"], l["y0"]))[0]
    return best["text"].strip()

def extract_outline(pdf_path):
    """
    Returns:
    {
      "title": "...",
      "outline": [ { "level": "H1|H2|H3", "text": "...", "page": 1 }, ... ]
    }
    """
    t0 = time.time()
    doc = open_document(pdf_path)
    outline = []

    # Detect document title from first page (best-effort)
    title = ""
    if len(doc) > 0:
        lines, med, gap, ph = extract_page_lines(doc[0])
        if not lines:
            # OCR fallback if enabled
            lines = ocr_page(doc[0])
        if lines:
            maybe = _clean_title_candidates(lines)
            if maybe:
                title = maybe

    # Extract headings per page with robust scoring
    for pno in range(len(doc)):
        page = doc[pno]
        lines, page_median_size, median_gap, page_height = extract_page_lines(page)
        if not lines:
            # OCR fallback (optional)
            lines = ocr_page(page)
            # when OCR lines present, use defaults
            page_median_size = page_median_size or 12.0
            median_gap = median_gap or 12.0
            page_height = page_height or (page.rect.height if page and page.rect else 792.0)

        if not lines:
            continue

        page_sizes = [l["size"] for l in lines] or [10.0]

        # score lines
        cands = []
        for i, ln in enumerate(lines):
            s = heading_score(ln, page_median_size, page_height, median_gap)
            # threshold tuned to reduce false positives on narrative lines
            if s >= 0.60:
                cands.append((s, ln))

        # rank candidates; avoid duplicates on same page by text
        seen_text = set()
        for score, ln in sorted(cands, key=lambda x: x[0], reverse=True):
            text = ln["text"].strip()
            if text.lower() in seen_text:
                continue
            seen_text.add(text.lower())

            level = assign_level(ln["size"], page_sizes)
            outline.append({
                "level": level,
                "text": text,
                "page": pno + EXPORT_PAGE_BASE
            })

    doc.close()
    return {"title": title, "outline": outline}

# ------------- CLI -------------
def _process_dir(input_dir, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    pdfs = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    pdfs.sort()
    for fname in pdfs:
        fpath = os.path.join(input_dir, fname)
        try:
            out = extract_outline(fpath)
            with open(os.path.join(output_dir, os.path.splitext(fname)[0] + ".json"),
                      "w", encoding="utf-8") as f:
                json.dump(out, f, ensure_ascii=False, indent=2)
            print(f"✓ {fname} → outline JSON")
        except Exception as e:
            print(f"✗ {fname}: {e}")

if __name__ == "__main__":
    # Default judge paths; override with envs if needed
    in_dir = os.environ.get("A1A_INPUT_DIR", "/app/input")
    out_dir = os.environ.get("A1A_OUTPUT_DIR", "/app/output")
    if os.path.isdir(in_dir):
        _process_dir(in_dir, out_dir)
    else:
        print("Provide a directory of PDFs via A1A_INPUT_DIR (defaults to /app/input).")

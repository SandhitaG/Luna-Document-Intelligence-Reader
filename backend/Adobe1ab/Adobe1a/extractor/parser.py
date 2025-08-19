import fitz
import re
import statistics

def _line_features(line):
    spans = line.get("spans", []) or []
    if not spans:
        return "", 0.0, False
    txt = "".join(s.get("text", "") for s in spans)
    sizes = [float(s.get("size", 0.0)) for s in spans if s.get("size") is not None]
    avg_size = sum(sizes) / max(1, len(sizes))
    bold_count = sum(1 for s in spans if (int(s.get("flags", 0)) & 2) == 2)
    is_bold = bold_count >= max(1, len(spans) // 2)
    return txt, avg_size, is_bold

def _is_noise(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if re.fullmatch(r"[\d\.\-–—•\s]+", t):
        return True
    if len(t) <= 2:
        return True
    return False

def extract_page_lines(page):
    """Return sorted lines with text, size, bold, x0,y0,bbox, and line gaps."""
    out = []
    d = page.get_text("dict")
    for block in d.get("blocks", []) or []:
        for line in block.get("lines", []) or []:
            bbox = line.get("bbox", [0,0,0,0])
            text, size, is_bold = _line_features(line)
            if _is_noise(text):
                continue
            out.append({
                "text": text.strip(),
                "size": float(size),
                "bold": bool(is_bold),
                "x0": float(bbox[0]),
                "y0": float(bbox[1]),
                "bbox": bbox
            })
    # sort top->bottom then left->right
    out.sort(key=lambda r: (r["y0"], r["x0"]))

    # compute vertical gaps to next line (for spacing heuristic)
    gaps = []
    for i in range(len(out)-1):
        gaps.append(out[i+1]["y0"] - out[i]["y0"])
    median_gap = statistics.median(gaps) if gaps else 12.0  # reasonable default

    for i in range(len(out)-1):
        out[i]["gap_after"] = max(0.0, out[i+1]["y0"] - out[i]["y0"])
    if out:
        out[-1]["gap_after"] = median_gap

    # page stats
    sizes = [l["size"] for l in out] or [10.0]
    page_median_size = statistics.median(sizes)
    page_height = float(page.rect.height) if page and page.rect else 792.0

    return out, page_median_size, median_gap, page_height

def open_document(path):
    return fitz.open(path)

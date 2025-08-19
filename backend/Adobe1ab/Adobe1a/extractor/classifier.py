import re
import statistics

PUNCT_END = (".", "!", "?", "…")

def title_like(t: str) -> bool:
    """Compact, noun-phrase style; avoid narrative sentences."""
    if not t: return False
    t = t.strip()
    if t.endswith(PUNCT_END) and not t.isupper():
        return False
    t = re.sub(r"[:\-–—]\s*$", "", t)  # drop trailing colon/dash
    words = re.findall(r"[A-Za-z][A-Za-z’'\-]+", t)
    if len(words) < 2 or len(words) > 12:
        return False
    if t.isupper():
        return True
    caps = sum(1 for w in words if (w[0].isupper() or w.isupper()))
    return (caps / max(1, len(words))) >= 0.40

def structured_prefix_score(t: str) -> float:
    """Numbered headings (1., 1.2.3), bullets, letters."""
    if not t: return 0.0
    t0 = t.strip()
    if re.match(r"^(?:\d+(\.\d+){0,4}|[A-Za-z]\))\s+", t0):
        return 0.6
    if re.match(r"^[•\-\–\—]\s+", t0):  # bullet mark
        return 0.4
    return 0.0

def heading_score(line, median_size, page_height, median_gap):
    """
    Combine:
      - size z-score (vs median)
      - boldness
      - top-of-page bias
      - title-like form
      - structured pattern at start
      - spacing gap after the line (bigger than normal)
    """
    size = float(line["size"])
    z = 0.0
    if median_size > 0:
        z = (size - median_size) / max(1.0, median_size * 0.25)

    bold = 0.9 if line.get("bold") else 0.0
    top_bonus = 0.6 if float(line["y0"]) <= page_height * 0.30 else 0.0
    tl = 0.8 if title_like(line.get("text","")) else -0.8
    sp = structured_prefix_score(line.get("text",""))
    gap = float(line.get("gap_after", 0.0))
    gap_bonus = 0.5 if gap >= (median_gap * 1.35) else 0.0

    # weighted sum
    score = (0.52 * z) + (0.18 * bold) + (0.12 * top_bonus) + (0.10 * tl) + (0.05 * sp) + (0.03 * gap_bonus)
    return score

def assign_level(size, page_sizes):
    """
    Map to H1/H2/H3 by size quantiles (per page) with gentle thresholds.
    """
    q80 = statistics.quantiles(page_sizes, n=5)[3] if len(page_sizes) >= 5 else max(page_sizes)  # ~80th
    q60 = statistics.quantiles(page_sizes, n=5)[2] if len(page_sizes) >= 5 else (max(page_sizes) * 0.8)
    if size >= q80:
        return "H1"
    if size >= q60:
        return "H2"
    return "H3"

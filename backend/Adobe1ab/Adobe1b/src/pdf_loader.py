# Adobe1b/src/pdf_loader.py
import os, sys, fitz, time, re, statistics

MAX_PAGES_PER_DOC = 200
MAX_SECTIONS_PER_DOC = 160  # per doc guard

PUNCT_END = (".", "!", "?", "…")

# -------- 1A wiring (on by default). Override path via A1A_PATH.
USE_1A = os.environ.get("A1B_USE_1A", "1").lower() in ("1", "true", "yes", "on")
extract_outline = None
if USE_1A:
    try:
        A1A_PATH = os.environ.get("A1A_PATH")
        if A1A_PATH:
            sys.path.append(os.path.abspath(A1A_PATH))
        else:
            # default: ../Adobe1a from this file
            HERE = os.path.dirname(__file__)
            A1A_DIR = os.path.abspath(os.path.join(HERE, "..", "..", "Adobe1a"))
            if os.path.isdir(A1A_DIR):
                if A1A_DIR not in sys.path:
                    sys.path.append(A1A_DIR)
        from extractor.extract_outline import extract_outline  # 1A API
    except Exception:
        USE_1A = False
        extract_outline = None

# ---------------- Heuristics

def _is_noise_line(t: str) -> bool:
    t = (t or "").strip()
    if not t:
        return True
    # bare numbers/dots/bullets & very short crumbs
    if re.fullmatch(r"[\d\.\-–—•\s]+", t):
        return True
    if len(t) <= 2:
        return True
    return False

def _title_like(t: str) -> bool:
    """Prefer compact, noun-phrase headings; reject narrative sentences."""
    if not t: return False
    t = t.strip()
    # sentence-like endings (period etc.) are not titles unless ALL CAPS
    if t.endswith(PUNCT_END) and not t.isupper():
        return False
    # strip trailing colon/dash which is common in headings
    t = re.sub(r"[:\-–—]\s*$", "", t)
    words = re.findall(r"[A-Za-z][A-Za-z’'\-]+", t)
    if len(words) < 2 or len(words) > 12:
        return False
    # title/caps ratio
    caps = sum(1 for w in words if (w[0].isupper() or w.isupper()))
    if t.isupper():
        return True
    cap_ratio = caps / max(1, len(words))
    return cap_ratio >= 0.40

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

def _union_bbox(b1, b2):
    if not b1: return b2
    if not b2: return b1
    return [
        float(min(b1[0], b2[0])),
        float(min(b1[1], b2[1])),
        float(max(b1[2], b2[2])),
        float(max(b1[3], b2[3])),
    ]

def _get_blocks(page):
    try:
        d = page.get_text("dict")
        return d.get("blocks", []) or []
    except Exception:
        return []

def _first_paragraph_after(page, y_top, char_limit=1200):
    """Version-safe context below y_top."""
    try:
        blocks = page.get_text("blocks") or []
    except Exception:
        blocks = []
    norm = []
    for b in blocks:
        if not isinstance(b, (list, tuple)) or len(b) < 5:
            continue
        x0, y0, x1, y1 = b[0], b[1], b[2], b[3]
        s = b[4] if len(b) >= 5 else ""
        norm.append((x0, y0, x1, y1, s))
    norm.sort(key=lambda t: (t[1], t[0]))
    text = ""
    for x0, y0, x1, y1, s in norm:
        if y0 <= y_top + 1:
            continue
        t = (s or "").strip()
        if not t:
            continue
        if len(t) < 12 and re.fullmatch(r"[\d\.\-–—\s]+", t):
            continue
        text += " " + t
        if len(text) >= char_limit:
            break
    return text.strip()[:char_limit]

# ---------------- Page parsing (heuristic fallback used only if 1A yields nothing)

def _extract_page_lines(page):
    """Return list of lines with text, size, bold, x0,y0,bbox (sorted by y,x)."""
    out = []
    for block in _get_blocks(page):
        for line in block.get("lines", []) or []:
            bbox = line.get("bbox", [0,0,0,0])
            text, size, is_bold = _line_features(line)
            if _is_noise_line(text):
                continue
            out.append({
                "text": text.strip(),
                "size": float(size),
                "bold": bool(is_bold),
                "x0": float(bbox[0]),
                "y0": float(bbox[1]),
                "bbox": bbox
            })
    out.sort(key=lambda r: (r["y0"], r["x0"]))
    return out

def _merge_wrapped_bullet(lines, i, indent_tol=18.0, yjump_tol=18.0):
    """Merge a bullet item across wrapped lines; reject if it becomes sentence-like."""
    start = lines[i]
    bullet_txt = start["text"].lstrip()
    # strip bullet marker
    bullet_txt = re.sub(r"^[•\-\–\—]\s*", "", bullet_txt)
    bullet_x = start["x0"]
    merged_text = bullet_txt
    merged_bbox = start["bbox"]
    j = i + 1
    while j < len(lines):
        ln = lines[j]
        t = ln["text"].lstrip()
        if re.match(r"^[•\-\–\—]\s+", t):
            break
        if (ln["x0"] + 0.1) < (bullet_x - indent_tol):
            break
        if (ln["y0"] - lines[j-1]["y0"]) > yjump_tol:
            break
        merged_text += " " + t
        merged_bbox = _union_bbox(merged_bbox, ln["bbox"])
        j += 1
    # reject sentence-like bullets
    if merged_text.strip().endswith(PUNCT_END):
        return "", None, j
    return merged_text.strip(), merged_bbox, j

def _heading_score(ln, median_size, top_cut):
    """Score heading-ness using size z, bold, and page top bias."""
    size = ln["size"]
    z = 0.0
    if median_size > 0:
        z = (size - median_size) / max(1.0, median_size * 0.25)
    bold = 0.8 if ln["bold"] else 0.0
    top_bonus = 0.6 if ln["y0"] <= top_cut else 0.0
    return 0.9 * z + bold + top_bonus

def _collect_candidates_from_page(doc_name, page, pno, page_lines):
    """Collect headings + clean bullets as section candidates."""
    sections = []
    if not page_lines:
        # no styled data; cautious fallback only if first line is title-like
        simple = (page.get_text("text") or "").strip().splitlines()
        if simple:
            first = simple[0].strip()
            if _title_like(first):
                sections.append({
                    "document": doc_name,
                    "page_number": pno,
                    "section_title": first,
                    "text": "\n".join(simple[1:])[:600],
                    "heading_level": "H1",
                    "is_bullet": False,
                    "is_stub": False,
                    "bboxes": [],
                    "embedding": None
                })
        return sections

    sizes = [ln["size"] for ln in page_lines]
    median_size = statistics.median(sizes) if sizes else 0.0
    # top 30% of the page height is "top area"
    page_h = float(page.rect.height) if page and page.rect else 792.0
    top_cut = page_h * 0.30

    i = 0
    while i < len(page_lines) and len(sections) < MAX_SECTIONS_PER_DOC:
        ln = page_lines[i]
        txt = ln["text"]

        # bullets (only short, title-like bullets)
        if re.match(r"^[\s]*[•\-\–\—]\s+", txt):
            merged_text, merged_bbox, nxt = _merge_wrapped_bullet(page_lines, i)
            i = nxt
            if not merged_text:
                continue
            if not _title_like(merged_text):
                continue
            sections.append({
                "document": doc_name,
                "page_number": pno,
                "section_title": merged_text,
                "text": _first_paragraph_after(page, ln["y0"], 600),
                "heading_level": "H2",
                "is_bullet": True,
                "is_stub": False,
                "bboxes": [{
                    "x0": float(merged_bbox[0]), "y0": float(merged_bbox[1]),
                    "x1": float(merged_bbox[2]), "y1": float(merged_bbox[3])
                }],
                "embedding": None
            })
            continue

        # true headings (size/bold/top) and title-like
        score = _heading_score(ln, median_size, top_cut)
        if score >= 0.6 and _title_like(txt):
            sections.append({
                "document": doc_name,
                "page_number": pno,
                "section_title": txt,
                "text": _first_paragraph_after(page, ln["y0"], 1200),
                "heading_level": "H1" if ln["bold"] else "H2",
                "is_bullet": False,
                "is_stub": False,
                "bboxes": [{
                    "x0": float(ln["bbox"][0]), "y0": float(ln["bbox"][1]),
                    "x1": float(ln["bbox"][2]), "y1": float(ln["bbox"][3])
                }],
                "embedding": None
            })

        i += 1

    return sections

# ---------------- 1A integration

def _sections_from_1a(doc_path, doc_name, doc_obj, char_limit=1200):
    """Use 1A to get H1/H2/H3; add context & bbox. Returns list of section dicts."""
    out = []
    if extract_outline is None:
        return out
    try:
        res = extract_outline(doc_path)  # {"title": "...", "outline":[{"level":"H1","text":"...","page":N}, ...]}
        outline = res.get("outline", []) if isinstance(res, dict) else []
    except Exception:
        return out

    for item in outline:
        lvl = (item.get("level") or "").upper()
        if lvl not in ("H1", "H2", "H3"):
            continue
        text = (item.get("text") or "").strip()
        if not text:
            continue
        # 1A exports 1-based pages; clamp + convert to 0-based
        p = int(item.get("page", 1))
        pno = p - 1
        if pno < 0 or pno >= len(doc_obj):
            continue

        page = doc_obj[pno]
        # locate text on page to anchor context + bbox
        rects = []
        try:
            # search_for can find multiple matches; take the topmost
            rects = page.search_for(text, quads=False) or []
        except Exception:
            rects = []

        if rects:
            # choose the rect with smallest y0 (topmost occurrence)
            rects.sort(key=lambda r: (r.y0, r.x0))
            y_anchor = float(rects[0].y1)
            bxs = [{"x0": float(r.x0), "y0": float(r.y0), "x1": float(r.x1), "y1": float(r.y1)} for r in rects[:2]]
        else:
            y_anchor = 0.0
            bxs = []

        ctx = _first_paragraph_after(page, y_anchor, char_limit=char_limit)
        out.append({
            "document": doc_name,
            "page_number": pno,               # keep 0-based internally
            "section_title": text,
            "text": ctx,
            "heading_level": lvl,
            "is_bullet": False,
            "is_stub": False,
            "bboxes": bxs,
            "embedding": None
        })
    return out

# ---------------- Public API

def load_documents_and_sections(input_dir, deadline):
    input_dir = os.path.abspath(input_dir)
    pdfs = [f for f in os.listdir(input_dir) if f.lower().endswith(".pdf")]
    pdfs.sort()
    documents, sections = [], []

    for fname in pdfs:
        if time.time() > deadline: break
        fpath = os.path.join(input_dir, fname)
        try:
            doc = fitz.open(fpath)
        except Exception:
            continue

        documents.append(fname)
        page_count = min(len(doc), MAX_PAGES_PER_DOC)
        per_doc = 0

        # Try 1A first
        if USE_1A and extract_outline is not None:
            secs_1a = _sections_from_1a(fpath, fname, doc, char_limit=1200)
            sections.extend(secs_1a)
            per_doc += len(secs_1a)

        # Fall back to heuristic only if 1A found nothing
        if per_doc == 0:
            for pno in range(page_count):
                if time.time() > deadline: break
                page = doc[pno]
                lines = _extract_page_lines(page)
                secs = _collect_candidates_from_page(fname, page, pno, lines)
                sections.extend(secs)
                per_doc += len(secs)
                if per_doc >= MAX_SECTIONS_PER_DOC:
                    break

        doc.close()

        # only if truly nothing detected
        if per_doc == 0:
            sections.append({
                "document": fname,
                "page_number": 0,
                "section_title": "Document Start",
                "text": "",
                "heading_level": "H3",
                "is_bullet": False,
                "is_stub": True,
                "bboxes": [],
                "embedding": None
            })

    return documents, sections

import os

# OCR is optional. Disabled by default for speed and to avoid extra deps.
# Enable by setting A1A_ENABLE_OCR=1 and having pytesseract installed.

ENABLE_OCR = os.environ.get("A1A_ENABLE_OCR", "0").lower() in ("1","true","yes","on")

def ocr_page(_page):
    if not ENABLE_OCR:
        return []
    try:
        import pytesseract
        from PIL import Image
        # Render at moderate DPI for OCR
        pix = _page.get_pixmap(dpi=200, alpha=False)
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        text = pytesseract.image_to_string(img, lang="eng")
        if not text:
            return []
        lines = []
        y = 0.0
        for ln in text.splitlines():
            t = (ln or "").strip()
            if not t:
                continue
            lines.append({
                "text": t,
                "size": 12.0,
                "bold": False,
                "x0": 0.0,
                "y0": y,
                "bbox": [0.0, y, float(pix.width), y + 14.0],
                "gap_after": 14.0
            })
            y += 14.0
        return lines
    except Exception:
        return []

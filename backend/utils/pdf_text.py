"""
Lightweight PDF text helper (stub-safe).
"""
from pathlib import Path
from typing import Optional

def extract_text(pdf_path: str, max_pages: Optional[int] = None) -> str:
    try:
        import fitz  # PyMuPDF
    except Exception:
        return f"[text unavailable for {Path(pdf_path).name}]"

    text_parts = []
    with fitz.open(pdf_path) as doc:
        end = min(len(doc), max_pages) if max_pages else len(doc)
        for i in range(end):
            page = doc.load_page(i)
            text_parts.append(page.get_text("text"))
    return "\n".join(text_parts).strip()

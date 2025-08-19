import React, { useEffect, useRef, useState, useCallback } from "react";
import * as pdfjsLib from "pdfjs-dist";
import "pdfjs-dist/web/pdf_viewer.css";

// Use a local worker in /public (see note below)
pdfjsLib.GlobalWorkerOptions.workerSrc =
  window.location.origin + "/pdf.worker.min.js";

export default function PdfPreviewModal({
  open,
  onClose,
  file,          // Blob | URL
  title = "Document",
}) {
  const canvasRef = useRef(null);
  const textLayerRef = useRef(null);
  const pdfRef = useRef(null);
  const viewportRef = useRef(null);

  const [pageCount, setPageCount] = useState(0);
  const [page, setPage] = useState(1);

  // keep your zoom separately; we render at a decent default
  const [scale, setScale] = useState(1.15);

  // --- search state ---
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);     // [{page, items:[{x,y,w,h}]}]
  const [hitIndex, setHitIndex] = useState(-1);

  // ------- load PDF -------
  const load = useCallback(async () => {
    if (!open || !file) return;
    const loadingTask = pdfjsLib.getDocument(
      typeof file === "string" ? file : { data: await file.arrayBuffer() }
    );
    pdfRef.current = await loadingTask.promise;
    setPageCount(pdfRef.current.numPages);
    setPage(1);
    setHits([]);
    setHitIndex(-1);
  }, [open, file]);

  useEffect(() => { load(); }, [load]);

  // ------- render page -------
  const renderPage = useCallback(async (num) => {
    if (!pdfRef.current) return;
    const pdfPage = await pdfRef.current.getPage(num);
    const viewport = pdfPage.getViewport({ scale });
    viewportRef.current = viewport;

    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    canvas.width = viewport.width;
    canvas.height = viewport.height;

    await pdfPage.render({ canvasContext: ctx, viewport }).promise;

    // Text layer for highlights
    const textLayerDiv = textLayerRef.current;
    textLayerDiv.innerHTML = "";
    const textContent = await pdfPage.getTextContent();
    const frag = document.createDocumentFragment();

    textContent.items.forEach((item) => {
      const span = document.createElement("span");
      span.textContent = item.str + " ";
      span.style.position = "absolute";
      const tx = pdfjsLib.Util.transform(viewport.transform, item.transform);
      const fontH = Math.hypot(tx[2], tx[3]);
      span.style.left = tx[4] + "px";
      span.style.top = tx[5] - fontH + "px";
      span.style.fontSize = fontH + "px";
      span.style.transform = `matrix(${tx[0]/fontH}, ${tx[1]/fontH}, ${tx[2]/fontH}, ${tx[3]/fontH}, 0, 0)`;
      span.style.transformOrigin = "0% 0%";
      frag.appendChild(span);
    });

    textLayerDiv.style.width = viewport.width + "px";
    textLayerDiv.style.height = viewport.height + "px";
    textLayerDiv.appendChild(frag);

    highlightPageHits(num, q);
  }, [scale, q]);

  useEffect(() => { if (page) renderPage(page); }, [page, scale, renderPage]);

  const gotoPage = (n) => {
    const target = Math.min(Math.max(1, Number(n) || 1), pageCount || 1);
    setPage(target);
  };

  // -------- search ----------
  const runSearch = useCallback(async () => {
    if (!pdfRef.current || !q.trim()) {
      setHits([]);
      setHitIndex(-1);
      renderPage(page);
      return;
    }
    const query = q.trim().toLowerCase();
    const all = [];
    for (let p = 1; p <= pdfRef.current.numPages; p++) {
      const pg = await pdfRef.current.getPage(p);
      const viewport = pg.getViewport({ scale: 1.0 });
      const tc = await pg.getTextContent();
      const pageHits = [];
      tc.items.forEach((it) => {
        if (String(it.str).toLowerCase().includes(query)) {
          const tx = pdfjsLib.Util.transform(viewport.transform, it.transform);
          const fontH = Math.hypot(tx[2], tx[3]);
          pageHits.push({
            x: tx[4],
            y: tx[5] - fontH,
            w: Math.max(fontH * (it.str.length * 0.55), 8),
            h: fontH + 2,
          });
        }
      });
      if (pageHits.length) all.push({ page: p, items: pageHits });
    }
    setHits(all);
    if (all.length) {
      setHitIndex(0);
      gotoPage(all[0].page);
    } else {
      setHitIndex(-1);
    }
  }, [q, renderPage]);

  const highlightPageHits = (pnum, query) => {
    const layer = textLayerRef.current;
    Array.from(layer.querySelectorAll(".__hl")).forEach((n) => n.remove());
    if (!query || !hits.length) return;
    const p = hits.find((h) => h.page === pnum);
    if (!p) return;
    p.items.forEach((r) => {
      const el = document.createElement("div");
      el.className = "__hl";
      el.style.position = "absolute";
      el.style.left = r.x + "px";
      el.style.top = r.y + "px";
      el.style.width = r.w + "px";
      el.style.height = r.h + "px";
      el.style.background = "rgba(255, 230, 0, 0.35)";
      el.style.borderRadius = "4px";
      layer.appendChild(el);
    });
  };

  useEffect(() => { highlightPageHits(page, q); }, [hits, hitIndex]); // re-apply

  const jumpToHit = (dir) => {
    if (!hits.length) return;
    // flatten hit pages (one entry per match)
    const flat = [];
    hits.forEach((h) => h.items.forEach(() => flat.push(h.page)));
    let idx = hitIndex < 0 ? 0 : hitIndex;
    idx = (idx + dir + flat.length) % flat.length;
    setHitIndex(idx);
    gotoPage(flat[idx]);
  };

  if (!open) return null;

  return (
    <div className="pdf-modal">
      <div className="pdf-card">
        <div className="pdf-header">
          <div className="pdf-title">{title}</div>

          {/* Header page-jump cube */}
          <div className="jump">
            <input
              className="jump-input"
              value={page}
              onChange={(e) => gotoPage(e.target.value)}
            />
            <span className="of">/ {pageCount || "—"}</span>
          </div>

          {/* Search controls */}
          <div className="search">
            <input
              className="search-input"
              placeholder="Search in PDF…"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && runSearch()}
            />
            <button className="btn" onClick={runSearch}>Search</button>
            <button className="btn" onClick={() => jumpToHit(-1)}>Prev</button>
            <button className="btn" onClick={() => jumpToHit(+1)}>Next</button>
            <span className="hits">
              {hits.reduce((a, h) => a + h.items.length, 0) || 0} matches
            </span>
          </div>

          <button className="btn close" onClick={onClose}>✕</button>
        </div>

        <div className="pdf-body">
          {/* Prev/Next PAGE only (no zoom UI) */}
          <div className="pagebar">
            <button className="btn" onClick={() => gotoPage(page - 1)} disabled={page <= 1}>Prev page</button>
            <button className="btn" onClick={() => gotoPage(page + 1)} disabled={page >= pageCount}>Next page</button>
          </div>

          <div className="stage">
            <canvas ref={canvasRef} className="pdf-canvas" />
            <div ref={textLayerRef} className="text-layer" />
          </div>
        </div>

        {/* Footer page-jump cube */}
        <div className="pdf-footer">
          <div className="jump">
            <input
              className="jump-input"
              value={page}
              onChange={(e) => gotoPage(e.target.value)}
            />
            <span className="of">/ {pageCount || "—"}</span>
          </div>
        </div>
      </div>
    </div>
  );
}

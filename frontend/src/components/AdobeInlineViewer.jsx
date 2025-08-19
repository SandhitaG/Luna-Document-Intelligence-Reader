import React, { useEffect, useRef, useState } from "react";

/* ---------------- load a script once ---------------- */
function loadScript(src, id) {
  return new Promise((resolve, reject) => {
    if (id && document.getElementById(id)) return resolve();
    const s = document.createElement("script");
    s.src = src;
    if (id) s.id = id;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = (e) => reject(e);
    document.head.appendChild(s);
  });
}

/* --------------- inject text-layer CSS --------------- */
function ensureTextLayerCSS() {
  if (document.getElementById("pdfjs-textlayer-css")) return;
  const style = document.createElement("style");
  style.id = "pdfjs-textlayer-css";
  style.textContent = `
    .pdf-select-root, .pdf-select-root * { -webkit-user-select: text !important; user-select: text !important; }
    .textLayer { position:absolute !important; inset:0 !important; overflow:hidden !important; pointer-events:auto !important; transform-origin:0 0 !important; mix-blend-mode:normal !important; }
    .textLayer > span { position:absolute !important; white-space:pre !important; transform-origin:0 0 !important; pointer-events:auto !important; color:transparent !important; -webkit-text-fill-color:transparent !important; text-shadow:none !important; line-height:1 !important; }
    .textLayer > span::selection, .textLayer > span::-moz-selection { background: rgba(0,106,255,0.28) !important; color:transparent !important; -webkit-text-fill-color:transparent !important; }
    .no-text-badge { position:absolute; right:8px; top:8px; font:12px/1.2 system-ui,-apple-system,Segoe UI,Roboto,sans-serif; background: rgba(255,184,28,.9); color:#111; padding:2px 6px; border-radius:6px; z-index:3; pointer-events:none; }
    .pdf-hit { outline: 2px solid rgba(255,224,96,.95); outline-offset: 2px; border-radius: 2px; }
  `;
  document.head.appendChild(style);
}

/* ---------------- utility ---------------- */
const norm = (s) => String(s || "").toLowerCase().replace(/\s+/g, " ").trim();

export default function AdobeInlineViewer({ file, height = "100%", onReady }) {
  const containerRef = useRef(null);        // scroll container
  const pagesWrapRef = useRef(null);        // holds pages
  const pdfRef = useRef(null);              // PDFDocumentProxy
  const [scale, setScale] = useState(1);

  // index of page -> { pageBox, textLayerDiv }
  const pagesIndexRef = useRef({});
  // when zooming, remember where user is and restore after re-render
  const pendingAnchorRef = useRef(null);

  /* ------------ boot on file change ------------ */
  useEffect(() => {
    let cancelled = false;

    async function boot() {
      if (!file || !containerRef.current || !pagesWrapRef.current) return;

      try {
        await loadScript(
          "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js",
          "pdfjs-lib"
        );
        window.pdfjsLib.GlobalWorkerOptions.workerSrc =
          "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";

        ensureTextLayerCSS();

        const buf = await file.arrayBuffer();
        const pdf = await window.pdfjsLib.getDocument({ data: buf }).promise;
        if (cancelled) return;
        pdfRef.current = pdf;

        await renderAllPages(pdf, scale);

        onReady?.({
          gotoLocation: ({ pageNumber }) => gotoPageOneBased(pageNumber),
          // public zoom methods that keep view anchored
          zoomIn: () => anchoredZoomTo(Math.min(3, +(scale + 0.1).toFixed(2))),
          zoomOut: () => anchoredZoomTo(Math.max(0.5, +(scale - 0.1).toFixed(2))),
          fit: () => fitToWidth(true),
          findAndScroll: (query, opts = {}) => findAndScroll(String(query || ""), opts),
          numPages: pdf.numPages,
          getPageCount: () => pdf.numPages,
        });
      } catch (err) {
        console.error("[PDF viewer] init error:", err);
      }
    }

    boot();
    return () => { cancelled = true; };
    // eslint-disable-next-line
  }, [file]);

  /* ------------ re-render on zoom ------------ */
  useEffect(() => {
    (async () => {
      if (!pdfRef.current) return;
      await renderAllPages(pdfRef.current, scale);
      // restore anchor after re-render
      if (pendingAnchorRef.current) {
        try {
          const { page, ratio } = pendingAnchorRef.current;
          const cont = containerRef.current;
          const wrap = pagesWrapRef.current;
          const holder = wrap?.querySelector(`[data-page="${page}"]`);
          if (cont && holder) {
            const top = holder.offsetTop + holder.clientHeight * ratio - cont.clientHeight / 2;
            cont.scrollTo({ top, behavior: "auto" });
          }
        } finally {
          pendingAnchorRef.current = null;
        }
      }
    })();
  }, [scale]);

  /* ------------ helpers ------------ */
  function gotoPageOneBased(pageOneBased) {
    const p = Math.max(1, Math.floor(Number(pageOneBased) || 1));
    const holder = pagesWrapRef.current?.querySelector(`[data-page="${p}"]`);
    if (!holder || !containerRef.current) return;
    const top = holder.offsetTop - 8;
    containerRef.current.scrollTo({ top, behavior: "smooth" });
  }

  function scrollToNode(node) {
    const cont = containerRef.current;
    if (!cont || !node) return;
    const r = node.getBoundingClientRect();
    const cr = cont.getBoundingClientRect();
    const top = r.top - cr.top + cont.scrollTop - 60;
    cont.scrollTo({ top, behavior: "smooth" });
  }

  function clearHitRings() {
    pagesWrapRef.current
      ?.querySelectorAll(".pdf-hit")
      ?.forEach((n) => n.classList.remove("pdf-hit"));
  }

  // capture which page is at the visual center and how far down we are on it
  function captureAnchor() {
    const cont = containerRef.current;
    if (!cont) return { page: 1, ratio: 0 };
    const contRect = cont.getBoundingClientRect();
    const midY = contRect.top + cont.clientHeight / 2;
    let anchor = { page: 1, ratio: 0 };

    const holders = pagesWrapRef.current?.querySelectorAll('[data-page]') || [];
    for (const h of holders) {
      const r = h.getBoundingClientRect();
      if (midY >= r.top && midY <= r.bottom) {
        anchor = {
          page: Number(h.dataset.page || 1),
          ratio: (midY - r.top) / Math.max(1, r.height),
        };
        break;
      }
    }
    return anchor;
  }

  function anchoredZoomTo(nextScale) {
    pendingAnchorRef.current = captureAnchor();
    setScale(nextScale);
  }

  /** Find the first span containing the query (favoring `pageHint`) and scroll to it. */
  function findAndScroll(query, { pageHint } = {}) {
    const q = norm(query);
    if (!q) return false;

    const order = [];
    const pages = Object.keys(pagesIndexRef.current)
      .map((n) => +n)
      .sort((a, b) => a - b);
    if (pageHint && pages.includes(pageHint)) order.push(pageHint);
    for (const p of pages) if (p !== pageHint) order.push(p);

    clearHitRings();

    for (const p of order) {
      const rec = pagesIndexRef.current[p];
      const textLayer = rec?.textLayerDiv;
      if (!textLayer) continue;

      const spans = textLayer.querySelectorAll("span");
      for (const sp of spans) {
        const t = norm(sp.textContent);
        if (t && t.includes(q)) {
          sp.classList.add("pdf-hit");
          scrollToNode(sp);
          setTimeout(() => sp.classList.remove("pdf-hit"), 2200);
          return true;
        }
      }
    }
    return false;
  }

  async function fitToWidth(anchored = false) {
    const cont = containerRef.current;
    const pdf = pdfRef.current;
    if (!cont || !pdf) return;

    const page = await pdf.getPage(1);
    const v1 = page.getViewport({ scale: 1 });
    const maxWidth = cont.clientWidth - 24; // padding allowance
    const next = Math.max(0.5, Math.min(3, maxWidth / v1.width));
    if (anchored) {
      anchoredZoomTo(+next.toFixed(2));
    } else {
      setScale(+next.toFixed(2));
    }
  }

  /* ------------ render all pages ------------ */
  async function renderAllPages(pdf, scaleValue) {
    const wrap = pagesWrapRef.current;
    if (!wrap) return;
    wrap.innerHTML = "";
    pagesIndexRef.current = {};

    for (let pageNum = 1; pageNum <= pdf.numPages; pageNum++) {
      const page = await pdf.getPage(pageNum);
      const viewport = page.getViewport({ scale: scaleValue });

      const holder = document.createElement("div");
      holder.dataset.page = String(pageNum);
      holder.style.margin = "0 0 18px";
      holder.style.display = "flex";
      holder.style.justifyContent = "center";
      wrap.appendChild(holder);

      const pageBox = document.createElement("div");
      pageBox.style.position = "relative";
      pageBox.style.width = `${Math.ceil(viewport.width)}px`;
      pageBox.style.height = `${Math.ceil(viewport.height)}px`;
      pageBox.style.webkitUserSelect = "text";
      pageBox.style.userSelect = "text";
      holder.appendChild(pageBox);

      const canvas = document.createElement("canvas");
      canvas.style.position = "absolute";
      canvas.style.left = "0";
      canvas.style.top = "0";
      canvas.style.borderRadius = "8px";
      canvas.style.boxShadow = "0 4px 18px rgba(0,0,0,.25)";
      canvas.style.zIndex = "1";
      canvas.style.pointerEvents = "none";
      const ctx = canvas.getContext("2d", { alpha: false });
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      pageBox.appendChild(canvas);

      await page.render({ canvasContext: ctx, viewport }).promise;

      try {
        const textContent = await page.getTextContent({
          normalizeWhitespace: true,
          disableCombineTextItems: false,
        });

        if (!textContent?.items?.length) {
         
          pagesIndexRef.current[pageNum] = { pageBox, textLayerDiv: null };
        } else {
          const textLayerDiv = document.createElement("div");
          textLayerDiv.className = "textLayer";
          textLayerDiv.style.zIndex = "2";
          pageBox.appendChild(textLayerDiv);

          if (window.pdfjsLib.TextLayer) {
            const tl = new window.pdfjsLib.TextLayer({
              textContentSource: textContent,
              container: textLayerDiv,
              viewport,
              textDivs: [],
              enhanceTextSelection: true,
            });
            await tl.render();
          } else if (window.pdfjsLib.renderTextLayer) {
            await window.pdfjsLib
              .renderTextLayer({
                textContentSource: textContent,
                container: textLayerDiv,
                viewport,
                textDivs: [],
                enhanceTextSelection: true,
              })
              .promise;
          }

          pagesIndexRef.current[pageNum] = { pageBox, textLayerDiv };
        }
      } catch (e) {
        console.warn("Text layer failed:", e);
      }
    }
  }

  return (
    <div
      ref={containerRef}
      className="pdf-select-root"
      style={{
        position: "relative",
        height,
        width: "100%",
        overflow: "auto",
        background: "rgba(255,255,255,.02)",
        borderRadius: 12,
      }}
    >
      {/* Overlay toolbar */}
      <div
        style={{
          position: "sticky",
          top: 0,
          zIndex: 5,
          display: "flex",
          gap: 8,
          justifyContent: "center",
          padding: "8px 0",
          background: "linear-gradient(180deg, rgba(0,0,0,.35), rgba(0,0,0,0))",
        }}
      >
        <button
          className="btn btn--primary"
          title="Zoom out"
          onClick={() => anchoredZoomTo(Math.max(0.5, +(scale - 0.1).toFixed(2)))}
          style={{ padding: "4px 10px", color: "white", borderColor: "#C83FB1", background: "#C83FB1" }}
        >
          −
        </button>
        <button
          className="btn btn--primary"
          title="Fit to width"
          onClick={() => fitToWidth(true)}
          style={{ padding: "4px 10px", color: "white", borderColor: "#C83FB1", background: "#C83FB1" }}
        >
          Fit
        </button>
        <button
          className="btn btn--primary"
          title="Zoom in"
          onClick={() => anchoredZoomTo(Math.min(3, +(scale + 0.1).toFixed(2)))}
          style={{ padding: "4px 10px", color: "white", borderColor: "#C83FB1", background: "#C83FB1" }}
        >
          +
        </button>
      </div>

      <div ref={pagesWrapRef} style={{ padding: "8px 12px 16px" }} />
    </div>
  );
}

// Doc2Agent PDF annotator. Renders PDF via PDF.js and exposes
// window.doc2agent.* helpers used by the Gradio tab.
(function () {
  if (window.doc2agent && window.doc2agent._init) return;
  console.log("[d2a] annotator.js init");

  const PDFJS_URL = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.6.82/build/pdf.min.mjs";
  const WORKER_URL = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.6.82/build/pdf.worker.min.mjs";
  const TEXT_LAYER_CSS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.6.82/web/pdf_viewer.css";

  const state = {
    pdfjs: null,
    doc: null,
    pageEls: new Map(),
    stagedSpans: [],
  };

  function ensureCss() {
    if (document.getElementById("pdfjs-textlayer-css")) return;
    const link = document.createElement("link");
    link.id = "pdfjs-textlayer-css";
    link.rel = "stylesheet";
    link.href = TEXT_LAYER_CSS;
    document.head.appendChild(link);

    const style = document.createElement("style");
    style.textContent = `
      #d2a-viewer { height: 75vh; overflow-y: auto; background: #525659; padding: 8px; border-radius: 6px; }
      #d2a-viewer .d2a-page { position: relative; margin: 0 auto 8px auto; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.3); }
      #d2a-viewer .d2a-page canvas { display: block; position: absolute; top: 0; left: 0; }
      #d2a-viewer .d2a-page .textLayer { position: absolute; top: 0; left: 0; right: 0; bottom: 0; overflow: hidden; user-select: text; -webkit-user-select: text; z-index: 1; }
      #d2a-viewer .d2a-page .textLayer > span,
      #d2a-viewer .d2a-page .textLayer > br { color: transparent; cursor: text; }
      #d2a-viewer .d2a-page .textLayer ::selection { background: rgba(255, 220, 0, 0.5); color: transparent; }
      #d2a-viewer .d2a-page-label { position: absolute; top: 4px; left: 6px; background: rgba(0,0,0,0.55); color: #fff; font: 11px sans-serif; padding: 2px 6px; border-radius: 3px; z-index: 2; pointer-events: none; }
      #d2a-staged { font: 12px/1.4 sans-serif; max-height: 180px; overflow-y: auto; border: 1px solid var(--border-color-primary, #ddd); border-radius: 4px; }
      #d2a-staged .d2a-span-row { padding: 4px 6px; border-bottom: 1px solid var(--border-color-primary, #ddd); display: flex; gap: 6px; justify-content: space-between; }
      #d2a-staged .d2a-span-row button { font-size: 11px; }
    `;
    document.head.appendChild(style);
  }

  async function loadPdfJs() {
    if (state.pdfjs) return state.pdfjs;
    const mod = await import(PDFJS_URL);
    mod.GlobalWorkerOptions.workerSrc = WORKER_URL;
    state.pdfjs = mod;
    return mod;
  }

  function getViewer() {
    return document.getElementById("d2a-viewer");
  }

  async function loadPdf(url) {
    console.log("[d2a] loadPdf called url=", url);
    ensureCss();
    const viewer = getViewer();
    if (!viewer) {
      console.warn("[d2a] viewer div not found");
      return;
    }
    viewer.innerHTML = '<div style="color:#fff;padding:12px;">Loading PDF...</div>';
    if (!url) {
      viewer.innerHTML = '<div style="color:#fff;padding:12px;">No document selected.</div>';
      state.doc = null;
      state.pageEls.clear();
      return;
    }
    const t0 = performance.now();
    const pdfjs = await loadPdfJs();
    const task = pdfjs.getDocument(url);
    const doc = await task.promise;
    state.doc = doc;
    state.pageEls.clear();
    viewer.innerHTML = "";

    for (let n = 1; n <= doc.numPages; n++) {
      const page = await doc.getPage(n);
      const viewport = page.getViewport({ scale: 1.3 });

      const container = document.createElement("div");
      container.className = "d2a-page";
      container.dataset.pageNum = String(n);
      container.style.width = viewport.width + "px";
      container.style.height = viewport.height + "px";
      container.style.setProperty("--scale-factor", String(viewport.scale));

      const label = document.createElement("div");
      label.className = "d2a-page-label";
      label.textContent = "p." + n;
      container.appendChild(label);

      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      container.appendChild(canvas);

      const textLayerDiv = document.createElement("div");
      textLayerDiv.className = "textLayer";
      textLayerDiv.style.width = viewport.width + "px";
      textLayerDiv.style.height = viewport.height + "px";
      container.appendChild(textLayerDiv);

      viewer.appendChild(container);
      state.pageEls.set(n, container);

      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
      const textContent = await page.getTextContent();
      if (pdfjs.TextLayer) {
        const textLayer = new pdfjs.TextLayer({
          textContentSource: textContent,
          container: textLayerDiv,
          viewport,
        });
        await textLayer.render();
      } else if (pdfjs.renderTextLayer) {
        await pdfjs.renderTextLayer({
          textContentSource: textContent,
          container: textLayerDiv,
          viewport,
          textDivs: [],
        }).promise;
      } else {
        console.warn("[d2a] no text layer API available on pdfjs");
      }
    }
    console.log(
      "[d2a] loadPdf done pages=" + doc.numPages + " elapsed_ms=" + (performance.now() - t0).toFixed(0)
    );
  }

  function pageNumFromNode(node) {
    let el = node && node.nodeType === 1 ? node : node && node.parentElement;
    while (el) {
      if (el.classList && el.classList.contains("d2a-page")) {
        return parseInt(el.dataset.pageNum, 10);
      }
      el = el.parentElement;
    }
    return null;
  }

  function getSelectionSpans() {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return [];
    const byPage = new Map();
    for (let i = 0; i < sel.rangeCount; i++) {
      const range = sel.getRangeAt(i);
      const start = pageNumFromNode(range.startContainer);
      const end = pageNumFromNode(range.endContainer);
      if (start == null) continue;
      const text = range.toString().trim();
      if (!text) continue;
      const pages = start === end ? [start] : [start, end];
      for (const p of pages) {
        if (!byPage.has(p)) byPage.set(p, text);
      }
    }
    return Array.from(byPage.entries()).map(([page_num, quoted_text]) => ({
      kind: "text",
      page_num,
      quoted_text,
    }));
  }

  function syncStagedToGradio() {
    const buf = document.querySelector("#d2a-spans-buffer textarea, #d2a-spans-buffer input");
    if (!buf) {
      console.warn("[d2a] spans-buffer textbox not found in DOM");
      return;
    }
    const payload = JSON.stringify(state.stagedSpans);
    buf.value = payload;
    buf.dispatchEvent(new Event("input", { bubbles: true }));
    buf.dispatchEvent(new Event("change", { bubbles: true }));
    console.log("[d2a] synced staged spans:", state.stagedSpans.length);
  }

  function renderStaged() {
    const list = document.getElementById("d2a-staged");
    if (!list) return;
    if (state.stagedSpans.length === 0) {
      list.innerHTML = '<div style="opacity:0.6;padding:6px;">No spans staged.</div>';
    } else {
      list.innerHTML = "";
      state.stagedSpans.forEach((s, idx) => {
        const row = document.createElement("div");
        row.className = "d2a-span-row";
        const preview =
          s.kind === "page"
            ? `[page ${s.page_num}]`
            : `p.${s.page_num}: ${(s.quoted_text || "").slice(0, 80)}`;
        const txt = document.createElement("span");
        txt.textContent = preview;
        const rm = document.createElement("button");
        rm.textContent = "x";
        rm.onclick = () => {
          state.stagedSpans.splice(idx, 1);
          renderStaged();
          syncStagedToGradio();
        };
        row.appendChild(txt);
        row.appendChild(rm);
        list.appendChild(row);
      });
    }
    syncStagedToGradio();
  }

  function addTextSpans() {
    const spans = getSelectionSpans();
    if (spans.length === 0) return;
    state.stagedSpans.push(...spans);
    window.getSelection().removeAllRanges();
    renderStaged();
  }

  function addPageSpan(pageNum) {
    const n = parseInt(pageNum, 10);
    if (!Number.isFinite(n) || n < 1) return;
    state.stagedSpans.push({ kind: "page", page_num: n, quoted_text: null });
    renderStaged();
  }

  function clearStaged() {
    state.stagedSpans = [];
    renderStaged();
  }

  window.doc2agent = {
    _init: true,
    loadPdf,
    addTextSpans,
    addPageSpan,
    clearStaged,
    renderStaged,
  };

  // Global event delegation for buttons inside gr.HTML (onclick attrs are
  // stripped by Gradio's sanitiser, so we bind at the document level).
  document.addEventListener("click", (ev) => {
    const btn = ev.target.closest && ev.target.closest("[data-d2a]");
    if (!btn) return;
    const action = btn.getAttribute("data-d2a");
    console.log("[d2a] click action=", action);
    if (action === "add-text") addTextSpans();
    else if (action === "add-page") {
      const inp = document.getElementById("d2a-page-input");
      addPageSpan(inp && inp.value);
    } else if (action === "clear") clearStaged();
  });

  // Initial render of staged list once DOM is ready.
  const tryInit = () => {
    if (document.getElementById("d2a-staged")) renderStaged();
    else setTimeout(tryInit, 200);
  };
  tryInit();
})();

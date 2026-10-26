const ID_PATTERN = /^[a-z0-9][a-z0-9-]{0,79}$/;
const PDF_PATTERN = /^library\/pdfs\/[a-f0-9][a-z0-9._-]*\.pdf$/i;

export function parseBookId(params) {
  const values = params.getAll('id');
  if (values.length !== 1 || !ID_PATTERN.test(values[0])) {
    throw new Error('รหัสหนังสือไม่ถูกต้อง');
  }
  return values[0];
}

export function findCatalogBook(catalog, id) {
  if (!Array.isArray(catalog)) throw new Error('ข้อมูลชั้นหนังสือไม่ถูกต้อง');
  const book = catalog.find(item => item && item.id === id);
  if (!book || typeof book.pdf !== 'string' || !PDF_PATTERN.test(book.pdf)) {
    throw new Error('ไม่พบหนังสือที่เผยแพร่แล้ว');
  }
  return book;
}

let session = null;
let generation = 0;

function elements() {
  return {
    reader: document.querySelector('#reader'),
    stage: document.querySelector('#stage'),
    status: document.querySelector('#status'),
    title: document.querySelector('#viewer-title'),
    meta: document.querySelector('#viewer-meta'),
    original: document.querySelector('#original-pdf'),
    previous: document.querySelector('#previous'),
    next: document.querySelector('#next'),
    go: document.querySelector('#go'),
    input: document.querySelector('#page-number'),
    total: document.querySelector('#total'),
    fullscreen: document.querySelector('#fullscreen'),
  };
}

function createBookContainer(stage) {
  stage.replaceChildren();
  const book = document.createElement('div');
  book.id = 'book';
  book.setAttribute('aria-label', 'หน้าหนังสือแบบพลิกหน้า');
  stage.append(book);
  return book;
}

function setStatus(ui, message, error = false) {
  ui.status.textContent = message;
  ui.status.classList.toggle('error', error);
}

function isCancelled(error) {
  return error?.name === 'RenderingCancelledException' || error?.name === 'AbortException';
}

async function dispose() {
  const active = session;
  session = null;
  generation += 1;
  if (!active || active.disposed) return;
  active.disposed = true;
  for (const task of active.renderTasks.values()) {
    try { task.cancel(); } catch (_) { /* already complete */ }
  }
  active.renderTasks.clear();
  for (const cleanup of active.cleanupListeners.splice(0)) {
    try { cleanup(); } catch (_) { /* listener already gone */ }
  }
  for (const url of active.objectUrls.values()) URL.revokeObjectURL(url);
  active.objectUrls.clear();
  try { active.flip?.destroy(); } catch (_) { /* partial initialization */ }
  try { await active.loadingTask?.destroy(); } catch (_) { /* page is closing */ }
  try { await active.pdf?.destroy(); } catch (_) { /* page is closing */ }
}

async function initialize() {
  await dispose();
  const token = ++generation;
  const ui = elements();
  const active = {
    token,
    disposed: false,
    pdf: null,
    loadingTask: null,
    flip: null,
    renderTasks: new Map(),
    objectUrls: new Map(),
    pages: [],
    cleanupListeners: [],
  };
  session = active;
  const current = () => session === active && generation === token && !active.disposed;

  try {
    const id = parseBookId(new URLSearchParams(window.location.search));
    setStatus(ui, 'กำลังอ่านข้อมูลหนังสือ…');
    const response = await fetch('catalog.json', {headers: {'Accept': 'application/json'}});
    if (!response.ok) throw new Error('โหลดข้อมูลชั้นหนังสือไม่สำเร็จ');
    const book = findCatalogBook(await response.json(), id);
    if (!current()) return;

    ui.title.textContent = book.title;
    ui.meta.textContent = `${book.author} · ${book.category}`;
    document.title = `${book.title} · Book Shelf`;
    ui.original.href = book.pdf;
    ui.original.hidden = false;

    setStatus(ui, 'กำลังโหลด PDF และตัวพลิกหน้า…');
    const pdfjs = await import('./vendor/pdfjs/pdf.mjs');
    pdfjs.GlobalWorkerOptions.workerSrc = new URL('./vendor/pdfjs/pdf.worker.mjs', import.meta.url).href;
    if (!window.St || !window.St.PageFlip) throw new Error('โหลด StPageFlip ไม่สำเร็จ');

    active.loadingTask = pdfjs.getDocument({
      url: book.pdf,
      isEvalSupported: false,
      cMapUrl: new URL('./vendor/pdfjs/cmaps/', import.meta.url).href,
      cMapPacked: true,
      standardFontDataUrl: new URL('./vendor/pdfjs/standard_fonts/', import.meta.url).href,
      wasmUrl: new URL('./vendor/pdfjs/wasm/', import.meta.url).href,
    });
    active.pdf = await active.loadingTask.promise;
    if (!current()) return;
    if (active.pdf.numPages > 600) throw new Error('หนังสือเกิน 600 หน้า กรุณาเปิด PDF ต้นฉบับ');

    const first = await active.pdf.getPage(1);
    const firstViewport = first.getViewport({scale: 1});
    const ratio = firstViewport.height / firstViewport.width;
    const bookElement = createBookContainer(ui.stage);
    active.pages = Array.from({length: active.pdf.numPages}, (_, index) => {
      const pageElement = document.createElement('div');
      pageElement.className = 'page';
      const label = document.createElement('span');
      label.className = 'page-loading';
      label.textContent = `หน้า ${index + 1}`;
      const image = new Image();
      image.alt = `หน้า ${index + 1}`;
      image.hidden = true;
      pageElement.append(label, image);
      bookElement.append(pageElement);
      return pageElement;
    });

    async function renderPage(index) {
      if (!current() || index < 0 || index >= active.pdf.numPages || active.objectUrls.has(index)) return;
      if (active.renderTasks.has(index)) return active.renderTasks.get(index).promise;
      const page = await active.pdf.getPage(index + 1);
      if (!current()) return;
      const base = page.getViewport({scale: 1});
      const viewport = page.getViewport({scale: Math.min(1.7, 1200 / base.width)});
      const canvas = document.createElement('canvas');
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      const renderTask = page.render({canvas, canvasContext: canvas.getContext('2d'), viewport});
      active.renderTasks.set(index, renderTask);
      try {
        await renderTask.promise;
        if (!current()) return;
        const blob = await new Promise((resolve, reject) => canvas.toBlob(value => value ? resolve(value) : reject(new Error('สร้างภาพหน้าไม่สำเร็จ')), 'image/jpeg', 0.9));
        if (!current()) return;
        const old = active.objectUrls.get(index);
        if (old) URL.revokeObjectURL(old);
        const url = URL.createObjectURL(blob);
        active.objectUrls.set(index, url);
        const image = active.pages[index].querySelector('img');
        image.src = url;
        image.hidden = false;
        active.pages[index].querySelector('.page-loading')?.remove();
      } catch (error) {
        if (!isCancelled(error) && current()) throw error;
      } finally {
        active.renderTasks.delete(index);
        canvas.width = 0;
        canvas.height = 0;
        page.cleanup();
      }
    }

    let prefetchToken = 0;
    async function renderNearby(index) {
      const nearToken = ++prefetchToken;
      for (let pageIndex = Math.max(0, index - 2); pageIndex <= Math.min(active.pdf.numPages - 1, index + 4); pageIndex += 1) {
        if (!current() || nearToken !== prefetchToken) return;
        await renderPage(pageIndex);
      }
      for (const [pageIndex, url] of [...active.objectUrls]) {
        if (Math.abs(pageIndex - index) > 8) {
          URL.revokeObjectURL(url);
          active.objectUrls.delete(pageIndex);
          const image = active.pages[pageIndex].querySelector('img');
          image.removeAttribute('src');
          image.hidden = true;
        }
      }
    }

    await renderPage(0);
    if (active.pdf.numPages > 1) await renderPage(1);
    if (!current()) return;
    const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
    active.flip = new window.St.PageFlip(bookElement, {
      width: 420,
      height: Math.round(420 * ratio),
      size: 'stretch',
      minWidth: 240,
      maxWidth: 680,
      minHeight: 300,
      maxHeight: 920,
      autoSize: true,
      usePortrait: true,
      showCover: true,
      flippingTime: reduceMotion ? 220 : 650,
      maxShadowOpacity: reduceMotion ? 0.08 : 0.28,
      mobileScrollSupport: false,
    });
    active.flip.loadFromHTML(active.pages);

    ui.input.max = active.pdf.numPages;
    ui.total.textContent = `/ ${active.pdf.numPages}`;
    const update = index => {
      if (!current()) return;
      ui.input.value = String(index + 1);
      ui.previous.disabled = index <= 0;
      ui.next.disabled = index >= active.pdf.numPages - 1;
      renderNearby(index).catch(error => { if (current()) setStatus(ui, error.message, true); });
    };
    active.flip.on('flip', event => update(event.data));

    const onPrevious = () => active.flip?.flipPrev();
    const onNext = () => active.flip?.flipNext();
    const onGo = async () => {
      const requested = Number(ui.input.value);
      if (!Number.isInteger(requested)) return;
      const index = Math.min(active.pdf.numPages - 1, Math.max(0, requested - 1));
      await renderPage(index);
      await renderPage(index + 1);
      if (!current()) return;
      active.flip.turnToPage(index);
      update(index);
    };
    const onFullscreen = async () => {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await ui.reader.requestFullscreen();
      } catch (_) {
        setStatus(ui, 'เบราว์เซอร์นี้ไม่อนุญาตโหมดเต็มจอ', true);
      }
    };
    const onKey = event => {
      if (event.target instanceof HTMLInputElement) return;
      if (event.key === 'ArrowLeft') onPrevious();
      if (event.key === 'ArrowRight') onNext();
    };
    for (const [target, name, listener] of [
      [ui.previous, 'click', onPrevious], [ui.next, 'click', onNext],
      [ui.go, 'click', onGo], [ui.fullscreen, 'click', onFullscreen],
      [document, 'keydown', onKey],
    ]) {
      target.addEventListener(name, listener);
      active.cleanupListeners.push(() => target.removeEventListener(name, listener));
    }
    ui.go.disabled = false;
    setStatus(ui, 'ลากมุมกระดาษ หรือใช้ปุ่มเพื่อพลิกหน้า');
    update(0);
  } catch (error) {
    if (!current()) return;
    setStatus(ui, `${error.message} — ยังสามารถเปิด PDF ต้นฉบับได้`, true);
    ui.previous.disabled = true;
    ui.next.disabled = true;
    ui.go.disabled = true;
  }
}

if (typeof document !== 'undefined') {
  window.addEventListener('pagehide', () => { dispose(); });
  window.addEventListener('pageshow', event => { if (event.persisted) initialize(); });
  initialize();
}

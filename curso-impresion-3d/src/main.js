// Deck: un reloj, un manejador de entrada, un contexto WebGL.
// Todo el estado visual es función pura de (diapositiva, paso) + tiempo desde que se entró.
import { damp } from './shared.js';
import { TIMELINE } from './shared.js';

const html = document.documentElement;
const params = new URLSearchParams(location.search);
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// ---------------------------------------------------------------- deck
const slides = [...document.querySelectorAll('.slide')];
const state = { slide: 0, step: 0, enteredAt: 0 };
const pad = (n) => String(n).padStart(2, '0');
const stepsOf = (el) => Math.max(1, parseInt(el.dataset.steps || '1', 10));

function readHash() {
  const m = location.hash.match(/(\d+)/);
  if (!m) return;
  state.slide = Math.min(slides.length - 1, Math.max(0, parseInt(m[1], 10) - 1));
  state.step = 0;
}

function render() {
  slides.forEach((el, i) => {
    const current = i === state.slide;
    el.classList.toggle('is-current', current);
    el.setAttribute('aria-hidden', current ? 'false' : 'true');
    if (!current) return;
    el.querySelectorAll('[data-build]').forEach((b) => { b.hidden = parseInt(b.dataset.build, 10) > state.step; });
    const counter = el.querySelector('[data-counter]');
    if (counter) counter.textContent = `${pad(state.slide + 1)} / ${pad(slides.length)}`;
  });
  const first = state.slide === 0 && state.step === 0;
  const last = state.slide === slides.length - 1 && state.step === stepsOf(slides[state.slide]) - 1;
  document.querySelector('[data-nav="prev"]').disabled = first;
  document.querySelector('[data-nav="next"]').disabled = last;
  const hash = `#${state.slide + 1}`;
  if (location.hash !== hash) history.replaceState(null, '', hash);
}

function go(slide, step) {
  const changed = slide !== state.slide;
  state.slide = slide;
  state.step = step;
  // Un paso nuevo interrumpe y se asienta de inmediato: nada queda en cola.
  if (changed) state.enteredAt = clock.time;
  render();
}
function next() {
  const steps = stepsOf(slides[state.slide]);
  if (state.step < steps - 1) go(state.slide, state.step + 1);
  else if (state.slide < slides.length - 1) go(state.slide + 1, 0);
}
function prev() {
  if (state.step > 0) go(state.slide, state.step - 1);
  else if (state.slide > 0) go(state.slide - 1, stepsOf(slides[state.slide - 1]) - 1);
}

// ---------------------------------------------------------------- entrada (un solo manejador)
const pointer = { x: 0, y: 0, active: false, tx: 0, ty: 0, nx: 0, ny: 0 };
let lastMove = -10;

function onInput(e) {
  switch (e.type) {
    case 'keydown': {
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      const k = e.key;
      if (k === 'ArrowRight' || k === ' ' || k === 'PageDown' || k === 'ArrowDown') next();
      else if (k === 'ArrowLeft' || k === 'PageUp' || k === 'ArrowUp' || k === 'Backspace') prev();
      else if (k === 'Home') go(0, 0);
      else if (k === 'End') go(slides.length - 1, stepsOf(slides[slides.length - 1]) - 1);
      else if (k === '.' || k === 'b' || k === 'B') html.classList.toggle('is-blank');
      else if (k === 'f' || k === 'F') {
        if (document.fullscreenElement) document.exitFullscreen(); else html.requestFullscreen?.();
      } else return;
      e.preventDefault();
      lastMove = -10; // el teclado esconde los controles
      return;
    }
    case 'pointermove':
      pointer.x = e.clientX; pointer.y = e.clientY; pointer.active = true;
      pointer.tx = (e.clientX / window.innerWidth) * 2 - 1;
      pointer.ty = (e.clientY / window.innerHeight) * 2 - 1;
      if (e.pointerType === 'mouse') lastMove = clock.time;
      return;
    case 'pointerleave':
    case 'blur':
      pointer.active = false; pointer.tx = 0; pointer.ty = 0;
      return;
    case 'pointerdown':
      if (e.pointerType !== 'mouse') swipe = { x: e.clientX, y: e.clientY };
      return;
    case 'pointerup': {
      if (swipe && e.pointerType !== 'mouse') {
        const dx = e.clientX - swipe.x, dy = e.clientY - swipe.y;
        if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) (dx < 0 ? next : prev)();
        pointer.active = false; pointer.tx = 0; pointer.ty = 0;
      }
      swipe = null;
      return;
    }
    case 'click': {
      const b = e.target.closest('[data-nav]');
      if (b) (b.dataset.nav === 'next' ? next : prev)();
      return;
    }
    case 'hashchange':
      readHash(); state.enteredAt = clock.time; render();
  }
}
let swipe = null;
['keydown', 'pointermove', 'pointerdown', 'pointerup', 'click', 'blur', 'hashchange'].forEach((t) => window.addEventListener(t, onInput));
document.documentElement.addEventListener('pointerleave', onInput);

// ---------------------------------------------------------------- reloj único
const clock = { time: 0, last: 0, ema: 1 / 60, slow: 0 };
let gl = null;
let glBorn = 0;
const controls = document.querySelector('.controls');
const liveCache = new Map();

function rectOf(el) {
  const r = el.getBoundingClientRect();
  return { x: r.left, y: r.top, w: r.width, h: r.height };
}

function titleLinesFor(slide, rect) {
  const [wide, tall] = (slide.dataset.titleLines || '').split('||');
  const useTall = tall && rect.w / rect.h < 3.1;
  return (useTall ? tall : wide).split('|');
}

function setText(el, value) {
  if (liveCache.get(el) === value) return;
  liveCache.set(el, value);
  el.innerHTML = value;
}

// Los contadores en vivo vuelven a su texto final (el del HTML) cuando no hay animación.
const liveEls = [...document.querySelectorAll('[data-live]')];
liveEls.forEach((el) => { el.dataset.final = el.innerHTML; });
function restoreFinal() {
  liveEls.forEach((el) => { el.innerHTML = el.dataset.final; liveCache.delete(el); });
}

function teardownGL(reason) {
  if (!gl) return;
  restoreFinal();
  console.warn(`[deck] capa 3D desactivada: ${reason}`);
  try { gl.dispose(); } catch (_) { /* sin contexto */ }
  gl = null;
  html.classList.remove('has-3d');
  document.querySelectorAll('.tag').forEach((t) => t.classList.remove('is-on'));
}

function tick(now) {
  requestAnimationFrame(tick);
  let raw = clock.last ? (now - clock.last) / 1000 : 1 / 60;
  if (clock.warp) { raw += clock.warp; clock.warp = 0; }
  clock.last = now;
  const dt = Math.min(raw, 0.05); // un tab que vuelve no hace saltar nada
  clock.time += dt + (clock.skip || 0);
  clock.skip = 0;

  // Puntero amortiguado: lo comparten el subtítulo 2.5D, el campo y las cámaras.
  pointer.nx = damp(pointer.nx, pointer.tx, 0.35, dt);
  pointer.ny = damp(pointer.ny, pointer.ty, 0.35, dt);
  html.style.setProperty('--px', pointer.nx.toFixed(4));
  html.style.setProperty('--py', pointer.ny.toFixed(4));
  controls.classList.toggle('is-idle', clock.time - lastMove > 2.5);

  if (!gl || printing) return;

  // Presupuesto de salud: si no da abasto, se apaga para siempre y el CSS toma el relevo.
  clock.ema += (Math.min(raw, 0.5) - clock.ema) * 0.05;
  if (!params.has('force3d') && clock.time - glBorn > 2.5) {
    clock.slow = clock.ema > 0.045 ? clock.slow + dt : 0;
    if (clock.slow > 2) { teardownGL('frame-health'); return; }
  }

  // Sincronía por fotograma con chequeo de identidad (no en el evento).
  const slide = slides[state.slide];
  const titleZone = slide.querySelector('[data-3d="title"]');
  const zones = { loopTime: (clock.time - state.enteredAt) % TIMELINE.period };
  if (titleZone) {
    const r = rectOf(titleZone);
    const eyebrow = titleZone.querySelector('.eyebrow');
    const inset = eyebrow ? eyebrow.offsetHeight + 6 : 0;
    zones.title = { x: r.x, y: r.y + inset, w: r.w, h: r.h - inset };
    gl.title.setLines(titleLinesFor(slide, zones.title), clock.time);
  }
  const addEl = slide.querySelector('[data-3d="additive"]');
  const subEl = slide.querySelector('[data-3d="subtractive"]');
  if (addEl) zones.additive = rectOf(addEl);
  if (subEl) zones.subtractive = rectOf(subEl);

  let out;
  try {
    out = gl.frame(dt, clock.time, zones, pointer);
  } catch (err) {
    teardownGL(err.message);
    return;
  }

  for (const [name, el] of [['additive', addEl], ['subtractive', subEl]]) {
    const o = out[name];
    if (!o || !el) continue;
    const live = slide.querySelector(`[data-live="${name}"]`);
    if (live) setText(live, o.live);
    const tag = el.querySelector(`[data-tag="${name}"]`);
    if (tag) {
      tag.classList.toggle('is-on', !!o.tag);
      if (o.tag) tag.style.transform = `translate(${o.tag.x.toFixed(1)}px, ${(o.tag.y - tag.offsetHeight / 2).toFixed(1)}px)`;
    }
  }
}

// ---------------------------------------------------------------- arranque
async function boot() {
  const status = document.querySelector('[data-boot-status]');
  readHash();
  render();

  // Sostenido en la carga real de las fuentes: el título voxel se rasteriza con ellas.
  try {
    await Promise.all([
      document.fonts.load('900 64px "Archivo"', '¿QUÉ ES LA IMPRESIÓN 3D?'),
      document.fonts.load('800 32px "Archivo"'),
      document.fonts.load('600 16px "Archivo"'),
      document.fonts.load('500 14px "JetBrains Mono"'),
    ]);
  } catch (_) { /* sigue con la pila del sistema */ }

  const wantGL = !reduceMotion && !params.has('no3d') && !window.matchMedia('print').matches;
  if (wantGL) {
    if (status) status.textContent = 'Cargando / Geometría';
    try {
      const { GLLayer } = await import('./gl.js');
      gl = new GLLayer(document.getElementById('gl'));
      gl.canvas.addEventListener('webglcontextlost', () => teardownGL('context-lost'));
      html.classList.add('has-3d');
      glBorn = clock.time;
    } catch (err) {
      gl = null;
      console.warn('[deck] sin WebGL, se presenta con CSS:', err.message);
    }
  }
  if (params.has('debug')) window.__deck = { state, clock, pointer, get gl() { return gl; } };
  if (status) status.textContent = 'Listo / Presentar';
  html.classList.add('is-ready');
  state.enteredAt = clock.time;

  // Con movimiento reducido no se monta el reloj: la página queda quieta y completa.
  if (!reduceMotion) requestAnimationFrame(tick);
}

// Imprimir = estado final de cada diapositiva, sin capa 3D.
let printing = false;
window.addEventListener('beforeprint', () => { printing = true; html.classList.remove('has-3d'); restoreFinal(); });
window.addEventListener('afterprint', () => { printing = false; if (gl) html.classList.add('has-3d'); });

boot();

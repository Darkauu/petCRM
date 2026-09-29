// Título de sección como palabra voxel: cubos sólidos, alineados a una retícula
// exacta y tocándose. Las mismas instancias se re-apuntan sección a sección.
import * as THREE from 'three';
import { PALETTE, damp, clamp01, easeElastic, addLights } from './shared.js';

const BUDGET = 12000;       // cubos disponibles (instancias)
const DEPTH = 4;            // profundidad del interior; el contorno va a la mitad
const SS = 4;               // sobremuestreo del rasterizado
const FONT = (px) => `900 ${px}px "Archivo"`;
const PUSH = 3.2;           // cuánto avanza un cubo bajo el puntero (en cubos)
const WALL_Z = -4;          // plano del fondo que recibe la sombra
// Solape mínimo entre vecinos: cierra grietas de rasterizado sin separar la retícula.
const SEAM = 1.004;

// Rasteriza UNA línea a celdas, recortada a su propia tinta.
function rasterLine(text, px) {
  const c = document.createElement('canvas');
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.font = FONT(px * SS);
  const w = Math.ceil(ctx.measureText(text).width) + px * SS;
  const h = Math.ceil(px * SS * 1.6);
  c.width = w; c.height = h;
  ctx.font = FONT(px * SS);
  ctx.fillStyle = '#fff';
  ctx.textBaseline = 'alphabetic';
  ctx.fillText(text, px * SS * 0.5, px * SS * 1.15);
  const data = ctx.getImageData(0, 0, w, h).data;
  const cols = Math.floor(w / SS), rows = Math.floor(h / SS);
  const ink = new Uint8Array(cols * rows);
  let minC = cols, maxC = -1, minR = rows, maxR = -1;
  for (let r = 0; r < rows; r++) {
    for (let q = 0; q < cols; q++) {
      let sum = 0;
      for (let y = 0; y < SS; y++) {
        const row = (r * SS + y) * w;
        for (let x = 0; x < SS; x++) sum += data[(row + q * SS + x) * 4 + 3];
      }
      if (sum / (SS * SS * 255) >= 0.5) {
        ink[r * cols + q] = 1;
        if (q < minC) minC = q; if (q > maxC) maxC = q;
        if (r < minR) minR = r; if (r > maxR) maxR = r;
      }
    }
  }
  if (maxC < 0) return { cols: 0, rows: 0, ink: new Uint8Array(0) };
  const cw = maxC - minC + 1, ch = maxR - minR + 1;
  const out = new Uint8Array(cw * ch);
  for (let r = 0; r < ch; r++) for (let q = 0; q < cw; q++) out[r * cw + q] = ink[(r + minR) * cols + q + minC];
  return { cols: cw, rows: ch, ink: out };
}

// Apila líneas (alineadas a la izquierda) con un hueco fijo de celdas.
function rasterize(lines, px) {
  const parts = lines.map((l) => rasterLine(l, px));
  const gap = Math.max(2, Math.round(px * 0.14));
  const cols = Math.max(...parts.map((p) => p.cols));
  const rows = parts.reduce((a, p) => a + p.rows, 0) + gap * (parts.length - 1);
  const ink = new Uint8Array(cols * rows);
  const lineOf = new Int16Array(rows).fill(-1);
  let y0 = 0;
  parts.forEach((p, li) => {
    for (let r = 0; r < p.rows; r++) {
      lineOf[y0 + r] = li;
      for (let q = 0; q < p.cols; q++) ink[(y0 + r) * cols + q] = p.ink[r * p.cols + q];
    }
    y0 += p.rows + gap;
  });
  return { cols, rows, ink, lineOf };
}

// Agrupa celdas en glifos: componentes 8-conexas, y las que se solapan en X dentro
// de la misma línea (tilde + letra, punto + signo) se funden en un solo glifo.
function glyphs(grid) {
  const { cols, rows, ink, lineOf } = grid;
  const label = new Int32Array(cols * rows).fill(-1);
  const boxes = [];
  const stack = [];
  for (let start = 0; start < ink.length; start++) {
    if (!ink[start] || label[start] >= 0) continue;
    const id = boxes.length;
    const b = { x0: 1e9, x1: -1, y0: 1e9, y1: -1, line: lineOf[Math.floor(start / cols)] };
    label[start] = id; stack.push(start);
    while (stack.length) {
      const i = stack.pop();
      const q = i % cols, r = (i - q) / cols;
      if (q < b.x0) b.x0 = q; if (q > b.x1) b.x1 = q;
      if (r < b.y0) b.y0 = r; if (r > b.y1) b.y1 = r;
      for (let dy = -1; dy <= 1; dy++) for (let dx = -1; dx <= 1; dx++) {
        const nq = q + dx, nr = r + dy;
        if (nq < 0 || nr < 0 || nq >= cols || nr >= rows) continue;
        const n = nr * cols + nq;
        if (ink[n] && label[n] < 0) { label[n] = id; stack.push(n); }
      }
    }
    boxes.push(b);
  }
  const parent = boxes.map((_, i) => i);
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  for (let a = 0; a < boxes.length; a++) for (let b = a + 1; b < boxes.length; b++) {
    const A = boxes[a], B = boxes[b];
    if (A.line !== B.line) continue;
    const overlap = Math.min(A.x1, B.x1) - Math.max(A.x0, B.x0) + 1;
    if (overlap >= 0.5 * Math.min(A.x1 - A.x0 + 1, B.x1 - B.x0 + 1)) parent[find(b)] = find(a);
  }
  const remap = new Map();
  const merged = [];
  boxes.forEach((b, i) => {
    const root = find(i);
    if (!remap.has(root)) { remap.set(root, merged.length); merged.push({ x0: 1e9, x1: -1, y0: 1e9, y1: -1 }); }
    const m = merged[remap.get(root)];
    m.x0 = Math.min(m.x0, b.x0); m.x1 = Math.max(m.x1, b.x1);
    m.y0 = Math.min(m.y0, b.y0); m.y1 = Math.max(m.y1, b.y1);
  });
  for (let i = 0; i < label.length; i++) if (label[i] >= 0) label[i] = remap.get(find(label[i]));
  return { label, boxes: merged };
}

function extrude(grid) {
  const { cols, rows, ink } = grid;
  const at = (q, r) => (q >= 0 && r >= 0 && q < cols && r < rows ? ink[r * cols + q] : 0);
  const cells = [];
  const depth = new Uint8Array(cols * rows);
  let count = 0;
  for (let r = 0; r < rows; r++) {
    for (let q = 0; q < cols; q++) {
      if (!at(q, r)) continue;
      const border = !(at(q - 1, r) && at(q + 1, r) && at(q, r - 1) && at(q, r + 1));
      const d = border ? DEPTH / 2 : DEPTH;
      cells.push({ q, r, d, i: r * cols + q });
      depth[r * cols + q] = d;
      count += d;
    }
  }
  return { cells, count, depth };
}

// El tamaño del glifo se ajusta al presupuesto de cubos, no al revés.
function buildFormation(lines) {
  for (let px = 96; px >= 10; px -= 1) {
    const grid = rasterize(lines, px);
    const { cells, count, depth } = extrude(grid);
    if (count <= BUDGET) return { grid, cells, count, depth, px, ...glyphs(grid) };
  }
  throw new Error('Título demasiado largo para el presupuesto de cubos');
}

export class VoxelTitle {
  constructor() {
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(22, 1, 1, 2000);
    this.group = new THREE.Group();
    this.scene.add(this.group);

    const lights = addLights(this.scene, { shadow: true });
    this.key = lights.key;
    this.key.intensity = 2.6;

    this.clip = new THREE.Plane(new THREE.Vector3(0, 0, 1), -WALL_Z - 0.05);
    const mat = new THREE.MeshStandardMaterial({
      color: PALETTE.paper, roughness: 0.62, metalness: 0, clippingPlanes: [this.clip],
    });
    // Caras interiores fuera: con la palabra armada, una cara que toca a un vecino del
    // mismo glifo se colapsa en el shader. Sin caras ocultas no hay z-fighting en los
    // bordes y el frente de cada letra es una sola superficie, sin líneas de retícula.
    this.settled = { value: 0 };
    mat.onBeforeCompile = (sh) => {
      sh.uniforms.uSettled = this.settled;
      sh.vertexShader = sh.vertexShader
        .replace('#include <common>', '#include <common>\nattribute float aHide;\nuniform float uSettled;')
        .replace('#include <begin_vertex>', `#include <begin_vertex>
        int hideMask = int(aHide + 0.5);
        int faceBit = normal.x > 0.5 ? 1 : normal.x < -0.5 ? 2 : normal.y > 0.5 ? 4 : normal.y < -0.5 ? 8 : normal.z > 0.5 ? 16 : 32;
        if (uSettled > 0.5 && (hideMask & faceBit) != 0) transformed = vec3(0.0);`);
    };
    const geo = new THREE.BoxGeometry(SEAM, SEAM, SEAM);
    this.hide = new THREE.InstancedBufferAttribute(new Float32Array(BUDGET), 1);
    geo.setAttribute('aHide', this.hide);
    this.mesh = new THREE.InstancedMesh(geo, mat, BUDGET);
    this.mesh.castShadow = true;
    this.mesh.receiveShadow = false; // la sombra propia entre cubos dibujaba costuras
    this.mesh.frustumCulled = false;
    this.group.add(this.mesh);

    const wall = new THREE.Mesh(
      new THREE.PlaneGeometry(1, 1),
      new THREE.ShadowMaterial({ color: '#0a0003', opacity: 0.6 }),
    );
    wall.position.z = WALL_Z;
    wall.receiveShadow = true;
    this.wall = wall;
    this.scene.add(wall);

    // Estado por instancia.
    this.cur = new Float32Array(BUDGET * 3);
    this.tgt = new Float32Array(BUDGET * 3);
    this.scl = new Float32Array(BUDGET);
    this.tscl = new Float32Array(BUDGET);
    this.glyph = new Int16Array(BUDGET);
    this.boxes = [];      // caja de cada glifo en coordenadas de la palabra
    this.push = new Float32Array(64);
    this.delay = new Float32Array(BUDGET);
    this.used = 0;
    this.settleAt = Infinity;
    this.key_ = null;
    this.born = -1;       // instante en que se armó la primera formación
    this.size = { w: 1, h: 1 };
    this.tilt = { x: 0, y: 0 };
    this.ray = new THREE.Raycaster();
    this.tmp = new THREE.Vector3();
    this.plane = new THREE.Plane(new THREE.Vector3(0, 0, 1), -DEPTH);
    this.hit = new THREE.Vector3();
    this.ndc = new THREE.Vector2();
    this.stats = null;
    this.lightDir = new THREE.Vector3(-0.45, 0.55, 1);
  }

  // Re-apunta las instancias a una nueva palabra. Mismo texto → nada cambia.
  setLines(lines, time) {
    const key = lines.join('|');
    if (key === this.key_) return;
    this.key_ = key;
    const f = buildFormation(lines);
    const { cols, rows } = f.grid;
    this.size = { w: cols, h: rows };
    this.stats = { cubes: f.count, cols, rows, px: f.px };

    const first = this.born < 0;
    // Máscara de vecinos del mismo glifo: +x 1, -x 2, +y 4, -y 8, +z 16, -z 32.
    const same = (q, r, k, g) => q >= 0 && r >= 0 && q < cols && r < rows
      && f.depth[r * cols + q] > k && f.label[r * cols + q] === g;
    const mask = (q, r, k, d) => {
      const g = f.label[r * cols + q];
      return (same(q + 1, r, k, g) ? 1 : 0) | (same(q - 1, r, k, g) ? 2 : 0)
        | (same(q, r - 1, k, g) ? 4 : 0) | (same(q, r + 1, k, g) ? 8 : 0)
        | (k + 1 < d ? 16 : 0) | (k > 0 ? 32 : 0);
    };
    this.boxes = f.boxes.map((b) => ({
      x0: b.x0 - cols / 2, x1: b.x1 + 1 - cols / 2, y0: rows / 2 - b.y1 - 1, y1: rows / 2 - b.y0,
    }));
    if (this.push.length < this.boxes.length) this.push = new Float32Array(this.boxes.length);
    let i = 0;
    for (const c of f.cells) {
      const x = c.q - cols / 2 + 0.5;
      const y = rows / 2 - c.r - 0.5;
      for (let k = 0; k < c.d; k++) {
        const j = i * 3;
        this.tgt[j] = x; this.tgt[j + 1] = y; this.tgt[j + 2] = k + 0.5;
        if (first || i >= this.used) {
          // Entrada: los cubos salen del muro, barriendo de izquierda a derecha.
          this.cur[j] = x; this.cur[j + 1] = y; this.cur[j + 2] = WALL_Z - 30;
          this.scl[i] = 1;
        }
        this.tscl[i] = 1;
        this.glyph[i] = f.label[c.i];
        this.hide.array[i] = mask(c.q, c.r, k, c.d);
        this.delay[i] = (c.q / cols) * 1.0 + (k / DEPTH) * 0.08 + ((c.r * 7 + c.q * 13) % 11) * 0.012;
        i++;
      }
    }
    // Instancias sobrantes: colapsan hacia el centro de la formación mientras se encogen.
    for (let n = i; n < BUDGET; n++) {
      const j = n * 3;
      this.tgt[j] = 0; this.tgt[j + 1] = 0; this.tgt[j + 2] = DEPTH / 2;
      this.tscl[n] = 0;
      if (first) { this.cur[j] = 0; this.cur[j + 1] = 0; this.cur[j + 2] = 0; this.scl[n] = 0; }
    }
    for (let n = i; n < BUDGET; n++) this.hide.array[n] = 0;
    this.hide.needsUpdate = true;
    this.used = i;
    this.settleAt = time + (first ? 0.2 + 1.2 + 2.3 : 0.9);
    if (first) this.born = time;

    // Sombra: la cámara de sombra cubre la palabra entera.
    const s = Math.max(cols, rows) * 0.62 + 8;
    const sc = this.key.shadow.camera;
    sc.left = -s; sc.right = s; sc.top = s; sc.bottom = -s;
    sc.far = 400;
    sc.updateProjectionMatrix();
    this.lightDir = new THREE.Vector3(-0.45, 0.55, 1).multiplyScalar(s * 1.6);
    this.wall.scale.set(cols * 3, rows * 5, 1);
  }

  // rect: caja de la zona del título (px CSS); view: viewport con margen donde se dibuja.
  frame(dt, time, rect, view, pointer) {
    const aspect = view.w / view.h;
    const cam = this.camera;
    cam.aspect = aspect;
    const t = Math.tan(THREE.MathUtils.degToRad(cam.fov) / 2);
    // Distancia para que la palabra quepa en la caja interior (no en la de margen).
    const innerH = rect.h / view.h, innerW = rect.w / view.w;
    const dist = Math.max(
      (this.size.h / 2) / (t * innerH),
      (this.size.w / 2) / (t * aspect * innerW),
    ) + DEPTH;
    cam.position.set(0, 0, dist);
    cam.lookAt(0, 0, 0);
    cam.updateProjectionMatrix();

    // Alineada a la izquierda de la zona, centrada en vertical.
    const zPlane = dist - DEPTH;
    const halfW = zPlane * t * aspect;
    const leftEdge = -halfW + ((rect.x - view.x) / view.w) * 2 * halfW;
    const centreY = zPlane * t * (1 - ((rect.y - view.y + rect.h / 2) / view.h) * 2);
    this.group.position.set(leftEdge + this.size.w / 2, centreY, 0);
    this.key.target.position.copy(this.group.position);
    this.key.position.copy(this.group.position).add(this.lightDir);
    this.wall.position.set(this.group.position.x, this.group.position.y, WALL_Z);

    // Puntero → coordenadas locales de la palabra.
    let px = 1e6, py = 1e6, nx = 0, ny = 0;
    if (pointer.active) {
      this.ndc.set(((pointer.x - view.x) / view.w) * 2 - 1, -(((pointer.y - view.y) / view.h) * 2 - 1));
      this.ray.setFromCamera(this.ndc, cam);
      if (this.ray.ray.intersectPlane(this.plane, this.hit)) {
        this.group.worldToLocal(this.tmp.copy(this.hit));
        px = this.tmp.x; py = this.tmp.y;
      }
      nx = Math.max(-1, Math.min(1, ((pointer.x - (rect.x + rect.w / 2)) / (rect.w / 2))));
      ny = Math.max(-1, Math.min(1, ((pointer.y - (rect.y + rect.h / 2)) / (rect.h / 2)) * 1.5));
    }

    // Inclinación del bloque completo hacia el puntero: deja ver caras laterales.
    this.tilt.y = damp(this.tilt.y, nx * 0.16, 0.45, dt);
    this.tilt.x = damp(this.tilt.x, 0.1 + ny * 0.1, 0.45, dt);
    this.group.rotation.set(this.tilt.x, this.tilt.y, 0);

    // Cada letra se mueve como un bloque rígido: su distancia al puntero decide cuánto
    // avanza. Así los frentes siguen siendo una sola cara, sin costuras entre cubos.
    const R = Math.max(6, this.size.h * 0.3);
    const inv = 1 / (R * R);
    for (let g = 0; g < this.boxes.length; g++) {
      const b = this.boxes[g];
      const dx = px < b.x0 ? b.x0 - px : px > b.x1 ? px - b.x1 : 0;
      const dy = py < b.y0 ? b.y0 - py : py > b.y1 ? py - b.y1 : 0;
      const f = Math.exp(-(dx * dx + dy * dy) * inv);
      this.push[g] = damp(this.push[g], f * PUSH, f * PUSH > this.push[g] ? 0.12 : 0.4, dt);
    }
    const arr = this.mesh.instanceMatrix.array;
    const age = this.born < 0 ? 0 : time - this.born;
    this.settled.value = time >= this.settleAt ? 1 : 0;
    const used = this.used;
    for (let i = 0; i < BUDGET; i++) {
      const j = i * 3;
      const tx = this.tgt[j], ty = this.tgt[j + 1];
      let tz = this.tgt[j + 2];

      if (i < used) {
        // Solo en Z: la retícula XY nunca se rompe.
        tz += this.push[this.glyph[i]];

        const a = (age - 0.2 - this.delay[i]) / 2.3;
        if (a < 1) {
          const e = a <= 0 ? 0 : easeElastic(a);
          this.cur[j] = tx; this.cur[j + 1] = ty;
          this.cur[j + 2] = WALL_Z - 30 + (tz - (WALL_Z - 30)) * e;
          this.scl[i] = 1;
        } else {
          this.cur[j] = damp(this.cur[j], tx, 0.3, dt);
          this.cur[j + 1] = damp(this.cur[j + 1], ty, 0.3, dt);
          this.cur[j + 2] = damp(this.cur[j + 2], tz, 0.06, dt);
          this.scl[i] = damp(this.scl[i], this.tscl[i], 0.2, dt);
        }
      } else {
        this.cur[j] = damp(this.cur[j], tx, 0.3, dt);
        this.cur[j + 1] = damp(this.cur[j + 1], ty, 0.3, dt);
        this.cur[j + 2] = damp(this.cur[j + 2], tz, 0.3, dt);
        this.scl[i] = damp(this.scl[i], 0, 0.2, dt);
      }

      const s = this.scl[i] < 0.002 ? 0 : this.scl[i];
      const m = i * 16;
      arr[m] = s; arr[m + 1] = 0; arr[m + 2] = 0; arr[m + 3] = 0;
      arr[m + 4] = 0; arr[m + 5] = s; arr[m + 6] = 0; arr[m + 7] = 0;
      arr[m + 8] = 0; arr[m + 9] = 0; arr[m + 10] = s; arr[m + 11] = 0;
      arr[m + 12] = this.cur[j]; arr[m + 13] = this.cur[j + 1]; arr[m + 14] = this.cur[j + 2]; arr[m + 15] = 1;
    }
    this.mesh.instanceMatrix.needsUpdate = true;
    return clamp01(age / 3.6);
  }
}

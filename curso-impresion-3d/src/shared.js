// Constantes y utilidades compartidas por todas las piezas 3D.
import * as THREE from 'three';

export const PALETTE = {
  ink: '#3C0016',
  inkDeep: '#2A000F',
  accent: '#F92424',
  accentShade: '#C8141B',
  peach: '#D1C0A5',
  peachShade: '#B8A584',
  paper: '#EFEEE8',
  paperShade: '#DCDAD0',
};

// Amortiguación exponencial con constante de tiempo (independiente del framerate).
export const damp = (current, target, tau, dt) => target + (current - target) * Math.exp(-dt / tau);

export const clamp01 = (x) => Math.min(1, Math.max(0, x));
export const smooth = (x) => { x = clamp01(x); return x * x * (3 - 2 * x); };
export const easeInOut = (x) => { x = clamp01(x); return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2; };

// Ease elástico lento (~2.3 s) para movimiento explicativo.
export const easeElastic = (x) => {
  x = clamp01(x);
  if (x === 0 || x === 1) return x;
  return Math.pow(2, -9 * x) * Math.sin((x * 10 - 0.75) * ((2 * Math.PI) / 4.2)) + 1;
};

// ---------------------------------------------------------------------------
// La MISMA pieza en los dos procesos: pirámide escalonada dentro de un cubo 9×9×9.
// Capa y (0..8) tiene semiancho 4,4,3,3,2,2,1,1,0 → 329 cubos de 729.
export const N = 9;
export const HALF = 4;
export const halfAt = (y) => HALF - Math.floor(y / 2);
export const inPyramid = (x, y, z) => Math.abs(x) <= halfAt(y) && Math.abs(z) <= halfAt(y);

// Recorrido en serpentina de una capa; las capas impares giran 90°,
// como hace un laminador real.
export function serpentine(cells, y) {
  const rows = new Map();
  const rotate = y % 2 === 1;
  for (const c of cells) {
    const row = rotate ? c.x : c.z;
    if (!rows.has(row)) rows.set(row, []);
    rows.get(row).push(c);
  }
  const keys = [...rows.keys()].sort((a, b) => a - b);
  const out = [];
  keys.forEach((k, i) => {
    const r = rows.get(k).sort((a, b) => (rotate ? a.z - b.z : a.x - b.x));
    if (i % 2 === 1) r.reverse();
    out.push(...r);
  });
  return out;
}

// Reparte eventos en una ventana; los saltos de capa pesan más (la herramienta sube).
export function scheduleEvents(list, t0, t1, layerWeight = 7) {
  let total = 0;
  const w = list.map((c, i) => {
    const jump = i > 0 && list[i - 1].y !== c.y ? layerWeight : 0;
    total += 1 + jump;
    return total;
  });
  return w.map((acc) => t0 + ((acc - 1) / (total - 1)) * (t1 - t0));
}

// Un solo guion temporal para ambas demos: empiezan y terminan juntas,
// así la comparación se lee lado a lado.
export const TIMELINE = {
  period: 14.5,
  intro: [0.0, 1.2],   // el bloque sube / la boquilla llega
  work: [1.2, 10.2],   // depositar / cortar
  hold: [10.2, 12.8],  // misma pieza terminada
  sink: [12.8, 14.5],  // la pieza baja a través de la cama
};

// Luces comunes: sin transparencias, sólidas, iluminadas.
export function addLights(scene, { shadow = false, shadowSize = 12 } = {}) {
  const hemi = new THREE.HemisphereLight(PALETTE.paper, PALETTE.inkDeep, 1.55);
  scene.add(hemi);
  const key = new THREE.DirectionalLight('#fff7ee', 2.3);
  key.position.set(-6, 10, 9);
  scene.add(key);
  scene.add(key.target);
  const rim = new THREE.DirectionalLight(PALETTE.peach, 0.6);
  rim.position.set(8, 3, -4);
  scene.add(rim);
  if (shadow) {
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.bias = -0.0006;
    key.shadow.normalBias = 0.02;
    const c = key.shadow.camera;
    c.left = -shadowSize; c.right = shadowSize; c.top = shadowSize; c.bottom = -shadowSize;
    c.near = 0.5; c.far = 80;
  }
  return { hemi, key, rim };
}

// Coloca una cámara en perspectiva para que una esfera de radio r quepa en el viewport.
export function fitDistance(camera, radius, aspect) {
  const vfov = THREE.MathUtils.degToRad(camera.fov);
  const hfov = 2 * Math.atan(Math.tan(vfov / 2) * aspect);
  return radius / Math.sin(Math.min(vfov, hfov) / 2);
}

// Las dos demos del punto 01. Mismo guion temporal, misma pieza final:
// a la izquierda se deposita, a la derecha se retira.
// Todo el estado visual es función pura del tiempo del bucle.
import * as THREE from 'three';
import {
  PALETTE, N, HALF, inPyramid, serpentine, scheduleEvents, TIMELINE,
  addLights, fitDistance, damp, smooth, easeInOut, clamp01,
} from './shared.js';

const BED = 13;
const cPaper = new THREE.Color(PALETTE.paper);
const cPeach = new THREE.Color(PALETTE.peach);
const cAccent = new THREE.Color(PALETTE.accent);
const cAccentShade = new THREE.Color(PALETTE.accentShade);
const tmpC = new THREE.Color();

const std = (color, rough = 0.6) => new THREE.MeshStandardMaterial({ color, roughness: rough, metalness: 0 });
function box(w, h, d, mat, x = 0, y = 0, z = 0) {
  const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), mat);
  m.position.set(x, y, z);
  m.castShadow = true;
  m.receiveShadow = true;
  return m;
}

// Base común: escena, cámara, cama y pórtico.
class Stage {
  constructor() {
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(30, 1, 1, 400);
    addLights(this.scene, { shadow: true, shadowSize: 13 });

    const bed = box(BED, 0.6, BED, std(PALETTE.peachShade, 0.8), 0, -0.3, 0);
    bed.castShadow = false;
    this.scene.add(bed);

    // Recorte en la cara superior de la cama: lo que baja a través de ella desaparece
    // sin transparencias.
    this.clip = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0.001);
    this.cubeMat = new THREE.MeshStandardMaterial({ roughness: 0.55, metalness: 0, clippingPlanes: [this.clip] });

    this.orbit = { az: 0, el: 0 };
    this.focus = new THREE.Vector3(0, 6, 0);
    this.proj = new THREE.Vector3();
  }

  makeCubes(count) {
    // Solape del 1 % entre vecinos: sin grietas de rasterizado en la retícula.
    const mesh = new THREE.InstancedMesh(new THREE.BoxGeometry(1.012, 1.012, 1.012), this.cubeMat, count);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.frustumCulled = false;
    for (let i = 0; i < count; i++) mesh.setColorAt(i, cPaper);
    this.scene.add(mesh);
    return mesh;
  }

  // Pórtico: dos postes y una barra que se mueve con la herramienta.
  makeGantry(mat) {
    const posts = new THREE.Group();
    const a = box(0.55, 17, 0.55, mat, -BED / 2 - 0.6, 8.5, 0);
    const b = box(0.55, 17, 0.55, mat, BED / 2 + 0.6, 8.5, 0);
    posts.add(a, b);
    const bar = box(BED + 1.8, 0.5, 0.5, mat);
    this.scene.add(posts, bar);
    return { posts, bar };
  }

  aim(dt, view, pointer) {
    const cam = this.camera;
    cam.aspect = view.w / view.h;
    this.orbit.az = damp(this.orbit.az, pointer.nx * 0.22, 0.6, dt);
    this.orbit.el = damp(this.orbit.el, -pointer.ny * 0.1, 0.6, dt);
    const az = 0.72 + this.orbit.az;
    const el = 0.5 + this.orbit.el;
    const d = fitDistance(cam, 11.6, cam.aspect);
    cam.position.set(
      this.focus.x + d * Math.cos(el) * Math.sin(az),
      this.focus.y + d * Math.sin(el),
      this.focus.z + d * Math.cos(el) * Math.cos(az),
    );
    cam.lookAt(this.focus);
    cam.updateProjectionMatrix();
  }

  // Proyecta un punto del mundo a px CSS relativos al viewport.
  project(v, view) {
    this.proj.copy(v).project(this.camera);
    return { x: (this.proj.x * 0.5 + 0.5) * view.w, y: (-this.proj.y * 0.5 + 0.5) * view.h };
  }
}

const setM = (arr, i, x, y, z, s) => {
  const m = i * 16;
  arr[m] = s; arr[m + 1] = 0; arr[m + 2] = 0; arr[m + 3] = 0;
  arr[m + 4] = 0; arr[m + 5] = s; arr[m + 6] = 0; arr[m + 7] = 0;
  arr[m + 8] = 0; arr[m + 9] = 0; arr[m + 10] = s; arr[m + 11] = 0;
  arr[m + 12] = x; arr[m + 13] = y; arr[m + 14] = z; arr[m + 15] = 1;
};

const sinkOffset = (tl) => -easeInOut((tl - TIMELINE.sink[0]) / (TIMELINE.sink[1] - TIMELINE.sink[0])) * 10;

function indexAt(times, t) {
  let lo = 0, hi = times.length - 1;
  if (t < times[0]) return -1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (times[mid] <= t) lo = mid; else hi = mid - 1;
  }
  return lo;
}

// ============================================================================
// A / ADITIVA — la boquilla deposita la pirámide capa por capa.
export class AdditiveDemo extends Stage {
  constructor() {
    super();
    const cells = [];
    for (let y = 0; y < N; y++) {
      const layer = [];
      for (let x = -HALF; x <= HALF; x++) for (let z = -HALF; z <= HALF; z++) if (inPyramid(x, y, z)) layer.push({ x, y, z });
      cells.push(...serpentine(layer, y));
    }
    this.cells = cells;
    this.times = scheduleEvents(cells, TIMELINE.work[0], TIMELINE.work[1]);
    this.cubes = this.makeCubes(cells.length);

    const frame = std(PALETTE.peachShade, 0.7);
    this.gantry = this.makeGantry(frame);

    // Cabezal: boquilla, bloque calefactor, disipador y carro.
    const head = new THREE.Group();
    const tip = new THREE.Mesh(new THREE.CylinderGeometry(0.14, 0.42, 0.55, 16), std(PALETTE.peach, 0.4));
    tip.position.y = 0.3;
    head.add(tip);
    head.add(box(1.3, 0.75, 1.1, std(PALETTE.paperShade, 0.5), 0, 0.95, 0));
    for (let k = 0; k < 5; k++) head.add(box(1.15, 0.13, 1.15, std(PALETTE.peach, 0.5), 0, 1.55 + k * 0.28, 0));
    head.add(box(1.9, 1.5, 0.45, frame, 0, 3.1, -0.5));
    const fil = new THREE.Mesh(new THREE.CylinderGeometry(0.09, 0.09, 2.2, 8), std(PALETTE.paper, 0.4));
    fil.position.y = 4.9; // el filamento entra por arriba del carro
    head.add(fil);
    head.traverse((o) => { o.castShadow = true; });
    head.scale.setScalar(1.35); // legible desde el fondo de la sala
    this.head = head;
    this.scene.add(head);

    this.park = new THREE.Vector3(-5.2, 11, 4.6);
    this.nozzle = new THREE.Vector3();
    this.tagAt = new THREE.Vector3();
  }

  cellTop(i, out) {
    const c = this.cells[i];
    return out.set(c.x, c.y + 1.05, c.z);
  }

  frame(dt, tl, view, pointer) {
    this.aim(dt, view, pointer);
    const [w0, w1] = TIMELINE.work;
    const sink = tl >= TIMELINE.sink[0] ? sinkOffset(tl) : 0;
    const arr = this.cubes.instanceMatrix.array;
    let done = 0;

    for (let i = 0; i < this.cells.length; i++) {
      const c = this.cells[i];
      const age = tl - this.times[i];
      if (age < 0) { setM(arr, i, 0, -50, 0, 0); continue; }
      done++;
      // Crece desde la punta de la boquilla y se enfría de melocotón a papel.
      const s = smooth(age / 0.09);
      setM(arr, i, c.x, c.y + 0.5 + sink - (1 - s) * 0.3, c.z, s);
      tmpC.copy(cPeach).lerp(cPaper, smooth(age / 1.2));
      this.cubes.setColorAt(i, tmpC);
    }
    this.cubes.instanceMatrix.needsUpdate = true;
    this.cubes.instanceColor.needsUpdate = true;

    // Posición de la boquilla: continua entre depósitos.
    const n = this.cells.length;
    const pos = this.nozzle;
    const a = new THREE.Vector3(), b = new THREE.Vector3();
    if (tl < w0) {
      pos.copy(this.park).lerp(this.cellTop(0, a), easeInOut(tl / w0));
    } else if (tl < this.times[n - 1]) {
      const i = indexAt(this.times, tl);
      const f = clamp01((tl - this.times[i]) / (this.times[i + 1] - this.times[i]));
      this.cellTop(i, a); this.cellTop(i + 1, b);
      // En el salto de capa primero sube y luego viaja: una variable a la vez.
      if (b.y > a.y) {
        const up = smooth(f / 0.4), go = smooth((f - 0.4) / 0.6);
        pos.set(a.x + (b.x - a.x) * go, a.y + (b.y - a.y) * up, a.z + (b.z - a.z) * go);
      } else pos.copy(a).lerp(b, f);
    } else {
      pos.copy(this.cellTop(n - 1, a)).lerp(this.park, easeInOut((tl - this.times[n - 1]) / 1.2));
    }
    this.head.position.copy(pos);
    this.gantry.bar.position.set(0, pos.y + 4.2, pos.z - 0.68);
    this.gantry.posts.position.z = pos.z - 0.68;

    const working = tl >= w0 && tl < w1;
    const layer = done === 0 ? 0 : this.cells[done - 1].y + 1;
    return {
      tag: working ? this.project(this.tagAt.copy(pos).add({ x: 2.2, y: 2.2, z: 0 }), view) : null,
      live: `Capa <b>${String(layer).padStart(2, '0')} / 09</b> · Material usado <b>${String(done).padStart(3, '0')}</b> · Desperdicio <b>0 %</b>`,
    };
  }
}

// ============================================================================
// B / SUSTRACTIVA — el láser recorta el bloque de arriba abajo.
export class SubtractiveDemo extends Stage {
  constructor() {
    super();
    const keep = [], cut = [];
    for (let y = N - 1; y >= 0; y--) {
      const layer = [];
      for (let x = -HALF; x <= HALF; x++) {
        for (let z = -HALF; z <= HALF; z++) {
          if (inPyramid(x, y, z)) keep.push({ x, y, z }); else layer.push({ x, y, z });
        }
      }
      cut.push(...serpentine(layer, y));
    }
    this.keep = keep;
    this.cut = cut;
    this.total = keep.length + cut.length;
    this.times = scheduleEvents(cut, TIMELINE.work[0], TIMELINE.work[1], 10);
    this.cubes = this.makeCubes(this.total);

    // Dirección de expulsión de cada viruta: hacia afuera por el eje dominante.
    this.dirs = cut.map((c, i) => {
      const ax = Math.abs(c.x) >= Math.abs(c.z);
      const j = ((i * 37) % 17) / 17 - 0.5;
      return ax ? { x: Math.sign(c.x), z: j * 0.5 } : { x: j * 0.5, z: Math.sign(c.z) };
    });

    const frame = std(PALETTE.peachShade, 0.7);
    this.gantry = this.makeGantry(frame);
    const head = new THREE.Group();
    head.add(box(1.5, 1.3, 1.5, std(PALETTE.paperShade, 0.5), 0, 0.65, 0));
    const lens = new THREE.Mesh(new THREE.CylinderGeometry(0.28, 0.4, 0.4, 16), std(PALETTE.peach, 0.4));
    lens.position.y = -0.2;
    head.add(lens);
    head.add(box(2.0, 0.9, 0.45, frame, 0, 1.0, -0.8));
    head.traverse((o) => { o.castShadow = true; });
    this.head = head;
    this.scene.add(head);
    this.headY = 14;

    // Haz y punto de impacto: el único acento de la vista.
    const laser = new THREE.MeshBasicMaterial({ color: PALETTE.accent });
    this.beam = new THREE.Mesh(new THREE.BoxGeometry(0.16, 1, 0.16), laser);
    this.spark = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.12, 0.42), laser);
    this.scene.add(this.beam, this.spark);

    this.park = new THREE.Vector3(5.5, this.headY, -4.5);
    this.at = new THREE.Vector3();
    this.tagAt = new THREE.Vector3();
  }

  target(i, out) {
    const c = this.cut[i];
    return out.set(c.x, c.y + 1, c.z);
  }

  frame(dt, tl, view, pointer) {
    this.aim(dt, view, pointer);
    const [w0, w1] = TIMELINE.work;
    const rise = tl < w0 ? -10 * (1 - easeInOut(tl / (w0 * 0.85))) : 0;
    const off = rise + (tl >= TIMELINE.sink[0] ? sinkOffset(tl) : 0);
    const arr = this.cubes.instanceMatrix.array;

    let i = 0;
    for (const c of this.keep) {
      setM(arr, i, c.x, c.y + 0.5 + off, c.z, 1);
      this.cubes.setColorAt(i, cPaper);
      i++;
    }
    let removed = 0;
    for (let k = 0; k < this.cut.length; k++, i++) {
      const c = this.cut[k];
      const t = tl - this.times[k];
      if (t < -0.12) {
        setM(arr, i, c.x, c.y + 0.5 + off, c.z, 1);
        this.cubes.setColorAt(i, cPaper);
        continue;
      }
      if (t < 0.05) {
        // Se calienta bajo el haz.
        setM(arr, i, c.x, c.y + 0.5 + off, c.z, 1);
        this.cubes.setColorAt(i, tmpC.copy(cPaper).lerp(cAccent, smooth((t + 0.12) / 0.17)));
        continue;
      }
      removed++;
      // Viruta expulsada: arco hacia afuera, cae y atraviesa la cama.
      const e = t - 0.05;
      if (e > 1.6) { setM(arr, i, 0, -50, 0, 0); continue; }
      const d = this.dirs[k];
      const s = 1 - 0.45 * smooth(e / 0.5);
      setM(arr, i, c.x + d.x * 9 * e, c.y + 0.5 + 6 * e - 13 * e * e, c.z + d.z * 9 * e, s);
      this.cubes.setColorAt(i, tmpC.copy(cAccent).lerp(cAccentShade, smooth(e / 0.6)));
    }
    this.cubes.instanceMatrix.needsUpdate = true;
    this.cubes.instanceColor.needsUpdate = true;

    // Cabezal láser: se desliza entre cortes a altura fija.
    const n = this.cut.length;
    const a = new THREE.Vector3(), b = new THREE.Vector3();
    const at = this.at;
    if (tl < w0) {
      at.copy(this.park).lerp(this.target(0, a), easeInOut((tl - 0.3) / (w0 - 0.3)));
    } else if (tl < this.times[n - 1]) {
      const k = indexAt(this.times, tl);
      const f = clamp01((tl - this.times[k]) / (this.times[k + 1] - this.times[k]));
      at.copy(this.target(k, a)).lerp(this.target(k + 1, b), f);
    } else {
      at.copy(this.target(n - 1, a)).lerp(this.park, easeInOut((tl - this.times[n - 1]) / 1.2));
    }
    this.head.position.set(at.x, this.headY, at.z);
    this.gantry.bar.position.set(0, this.headY + 1.0, at.z - 0.8);
    this.gantry.posts.position.z = at.z - 0.8;

    const firing = tl >= w0 && tl < this.times[n - 1] + 0.05;
    this.beam.visible = this.spark.visible = firing;
    if (firing) {
      const top = this.headY - 0.4, bottom = at.y;
      this.beam.scale.y = top - bottom;
      this.beam.position.set(at.x, (top + bottom) / 2, at.z);
      this.spark.position.set(at.x, bottom + 0.07, at.z);
    }

    const waste = Math.round((removed / this.total) * 100);
    return {
      tag: firing ? this.project(this.tagAt.set(at.x + 2.2, this.headY + 1.4, at.z), view) : null,
      live: `Bloque <b>729</b> · Retirado <b>${String(removed).padStart(3, '0')}</b> · Desperdicio <b>${waste} %</b>`,
    };
  }
}

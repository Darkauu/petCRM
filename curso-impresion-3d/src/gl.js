// Un contexto WebGL, un canvas: el campo de fondo más un pase 3D por zona
// (título, demo A, demo B), recortados con scissor al rectángulo de su elemento DOM.
import * as THREE from 'three';
import { PALETTE } from './shared.js';
import { VoxelTitle } from './voxelTitle.js';
import { AdditiveDemo, SubtractiveDemo } from './demos.js';

// El shader escribe directo al framebuffer: los colores van SIN conversión
// para coincidir exactamente con el CSS.
const raw = (hex) => {
  const n = parseInt(hex.slice(1), 16);
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
};

const FIELD_FRAG = /* glsl */ `
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform vec2 uPointer;
uniform vec3 uInk;
uniform vec3 uDeep;
uniform vec3 uPeach;
varying vec2 vUv;

float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
float noise(vec2 p) {
  vec2 i = floor(p), f = fract(p);
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash(i), hash(i + vec2(1.0, 0.0)), u.x),
             mix(hash(i + vec2(0.0, 1.0)), hash(i + vec2(1.0, 1.0)), u.x), u.y);
}
float fbm(vec2 p) {
  float v = 0.0, a = 0.5;
  for (int i = 0; i < 5; i++) { v += a * noise(p); p = p * 2.03 + vec2(1.7, 9.2); a *= 0.5; }
  return v;
}
void main() {
  vec2 frag = vUv * uRes;
  vec2 p = frag / min(uRes.x, uRes.y) * 2.2;
  float t = uTime * 0.035;
  vec2 q = vec2(fbm(p + vec2(0.0, t)), fbm(p + vec2(5.2, 1.3 - t)));
  vec2 r = vec2(fbm(p + 3.6 * q + vec2(1.7, 9.2) + uPointer * 0.18), fbm(p + 3.6 * q + vec2(8.3, 2.8)));
  float n = fbm(p + 3.2 * r);
  vec3 col = mix(uDeep, uInk, smoothstep(0.22, 0.78, n));
  // Venas cálidas muy tenues: el fondo tiene materia, pero nunca compite con el texto.
  col = mix(col, mix(uInk, uPeach, 0.16), smoothstep(0.62, 0.95, length(r) * 0.72) * 0.5);
  float v = smoothstep(1.35, 0.25, length(vUv - 0.5) * 1.6);
  col = mix(uDeep, col, 0.55 + 0.45 * v);
  col += (hash(frag + fract(uTime)) - 0.5) * 0.012;
  gl_FragColor = vec4(col, 1.0);
}`;

export class GLLayer {
  constructor(canvas) {
    this.canvas = canvas;
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: 'high-performance' });
    renderer.autoClear = false;
    renderer.localClippingEnabled = true;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.toneMapping = THREE.NoToneMapping;
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer = renderer;

    this.fieldScene = new THREE.Scene();
    this.fieldCam = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
    this.fieldUniforms = {
      uRes: { value: new THREE.Vector2(1, 1) },
      uTime: { value: 0 },
      uPointer: { value: new THREE.Vector2() },
      uInk: { value: raw(PALETTE.ink) },
      uDeep: { value: raw(PALETTE.inkDeep) },
      uPeach: { value: raw(PALETTE.peach) },
    };
    const quad = new THREE.Mesh(
      new THREE.PlaneGeometry(2, 2),
      new THREE.ShaderMaterial({
        uniforms: this.fieldUniforms,
        vertexShader: 'varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }',
        fragmentShader: FIELD_FRAG,
        depthTest: false,
        depthWrite: false,
      }),
    );
    quad.frustumCulled = false;
    this.fieldScene.add(quad);

    this.title = new VoxelTitle();
    this.additive = new AdditiveDemo();
    this.subtractive = new SubtractiveDemo();
    this.size = { w: 0, h: 0, dpr: 0 };
  }

  resize() {
    const w = window.innerWidth, h = window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    if (w === this.size.w && h === this.size.h && dpr === this.size.dpr) return;
    this.size = { w, h, dpr };
    this.renderer.setPixelRatio(dpr);
    this.renderer.setSize(w, h, false);
    // Resolución del shader: tamaño del drawing buffer, no px CSS.
    const buf = this.renderer.getDrawingBufferSize(new THREE.Vector2());
    this.fieldUniforms.uRes.value.copy(buf);
  }

  pass(scene, camera, view) {
    const H = this.size.h;
    if (view.y + view.h < 0 || view.y > H || view.w < 2 || view.h < 2) return false;
    const r = this.renderer;
    r.setViewport(view.x, H - view.y - view.h, view.w, view.h);
    r.setScissor(view.x, H - view.y - view.h, view.w, view.h);
    r.clearDepth();
    r.render(scene, camera);
    return true;
  }

  // Dibuja un fotograma. `zones` trae los rectángulos DOM medidos en este mismo fotograma.
  frame(dt, time, zones, pointer) {
    this.resize();
    const r = this.renderer;
    const { w, h } = this.size;
    this.fieldUniforms.uTime.value = time;
    this.fieldUniforms.uPointer.value.set(pointer.nx, pointer.ny);

    r.setScissorTest(true);
    r.setViewport(0, 0, w, h);
    r.setScissor(0, 0, w, h);
    r.clear();
    r.render(this.fieldScene, this.fieldCam);

    const out = {};
    if (zones.title) {
      const rect = zones.title;
      const padX = rect.w * 0.03, padY = rect.h * 0.22;
      const view = { x: rect.x - padX, y: rect.y - padY, w: rect.w + padX * 2, h: rect.h + padY * 2 };
      this.title.frame(dt, time, rect, view, pointer);
      this.pass(this.title.scene, this.title.camera, view);
    }
    if (zones.additive) {
      out.additive = this.additive.frame(dt, zones.loopTime, zones.additive, pointer);
      this.pass(this.additive.scene, this.additive.camera, zones.additive);
    }
    if (zones.subtractive) {
      out.subtractive = this.subtractive.frame(dt, zones.loopTime, zones.subtractive, pointer);
      this.pass(this.subtractive.scene, this.subtractive.camera, zones.subtractive);
    }
    r.setScissorTest(false);
    return out;
  }

  dispose() {
    this.renderer.dispose();
    this.renderer.forceContextLoss();
  }
}

// The intro title: a line or two of small text at the very start of the video, in a font that fits the look (user
// 2026-10-19: a short line specific to the video, in a font unique to each video that fits its look, like a pixel or
// blocky font for the Minecraft-like video). The text
// itself is drawn by tools/intro_title.py (fonts, soft shadow, placement on a calm part of the plate) into
// out/plates/<plate>/intro.png with intro.json (its box at 4K and its timing); this layer only fades it in and out.
//
// It shows from `at` seconds into the video. A render from the video's start shows it in its first seconds; in a
// looped video (where layers get time folded into the period, engine.js timeAt) it reads the real video time
// (ctx.realTime), so only the very start of the video carries it. loop_master renders the opening segment again with
// it (intro_segment); the loop window's own segments, repeated all video long, never contain the video's start.
// --params intro=<s> moves the start (a test render of the title somewhere else).
import * as THREE from 'three';
import { fetchJson, plateTexture, PREMUL } from './overlay.js';
import { smooth } from './util.js';

const vert = /* glsl */ `
uniform vec4 uBox;   // x0, y0, x1, y1 px at 4K, y down
varying vec2 vT;
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vT = q;              // the texture loads flipped (flipY): its v runs bottom to top, like q
  vec2 px = vec2(mix(uBox.x, uBox.z, q.x), mix(uBox.w, uBox.y, q.y));
  gl_Position = vec4(px.x / 1920.0 - 1.0, 1.0 - px.y / 1080.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tText;
uniform float uK;
varying vec2 vT;
void main() {
  vec4 c = texture2D(tText, vT);
  float a = c.a * uK;
  if (a < 0.002) discard;
  gl_FragColor = vec4(c.rgb * a, a);
}`;

export async function titleLayer(ctx, opts) {
  // autoscene adds this layer only for a scene.json with an `intro`, so the drawn title must be there
  const meta = await fetchJson(`/out/plates/${opts.plate}/intro.json`, { hint: 'run tools/intro_title.py <scene>' });
  const tex = await plateTexture(opts.plate, 'intro.png', { srgb: true });
  const start = Number(ctx.params?.intro ?? 0);
  const { at, fade_in: fi, hold, fade_out: fo } = meta.timing;
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: { tText: { value: tex }, uK: { value: 0 }, uBox: { value: new THREE.Vector4(...meta.box) } },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = 1000;
  mesh.userData.noAO = true;
  mesh.visible = false;
  ctx.add(mesh);
  console.log(`title: "${meta.lines.join(' / ')}" at ${start + at} s of the video, ${meta.font}`);
  ctx.animate((t) => {
    const u = (ctx.realTime?.() ?? t) - start - at;
    const k = Math.min(smooth(u / fi), smooth((fi + hold + fo - u) / fo));
    mat.uniforms.uK.value = k;
    mesh.visible = k > 0.001;
  });
  return mesh;
}

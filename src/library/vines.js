// Hanging strands lifted off the plate (tools/vine_layers.py: lift.json and lift/<name>.png, cut before the view behind
// them was repainted), swinging from where they hang. Truman asked for the jungle temple's front vines to move more
// (2026-10-27, L167): as a warp of the plate a strand only slides its leaves inside an outline that stays put, and a
// bigger warp drags the view behind it along; lifted, it moves over a background that is whole behind it.
//
// Each strand bends like a hanging rope in moving air: pinned at its top, its swing growing toward the free end
// (s^1.5 of the way down), a slow sway whose wave runs down it (the top leads, the tip follows), a quicker flutter on
// top, a breeze that comes and goes over half a minute, and harder in gusts. A pure function of time with whole cycles
// per loop (seamless), each strand its own phase.
//
// A rigid strand (a clock's pendulum, user 2026-11-06: something that moves the whole video) swings as one piece about
// its pivot (lift.json `pivot`: where it hangs) with a clock's regularity: the same amplitude every swing, no breeze, no
// gusts, a whole number of swings per loop.
//
// opts: { plate, strands: { <name>: { amp (px at the free end, 18), hz (0.1), gust (1.5), wave (rad of lag from top to
//   tip, 1.4), flutter (px, 0.18 x amp) } or { rigid: true, deg (the swing's half angle, 3), hz (0.5: a seconds
//   pendulum, one swing a second), phase (rad, else from the name) }, and for either shift: [dx, dy] (px: drawn moved
//   from where it was painted, a pendulum painted off its case's middle) } (strands not named take the defaults),
//   renderOrder (16) }
import * as THREE from 'three';
import { flurryEnv } from './timeline.js';
import { plateTexture, PREMUL } from './overlay.js';

const W = 3840, H = 2160;
const TAU = 2 * Math.PI;

const vert = /* glsl */ `
uniform vec4 uBox;        // the quad: x, y (top left, px at 4K, y down), w, h
varying vec2 vPx;         // image px, y down
void main() {
  vec2 q = position.xy * 0.5 + 0.5;
  vPx = uBox.xy + vec2(q.x, 1.0 - q.y) * uBox.zw;
  gl_Position = vec4(vPx.x / ${W}.0 * 2.0 - 1.0, 1.0 - vPx.y / ${H}.0 * 2.0, 0.0, 1.0);
}`;
const frag = /* glsl */ `
uniform sampler2D tSpr;
uniform vec4 uSpr;        // the sprite's box: x0, y0, w, h (px)
uniform vec4 uSw;         // top row (px), length (px), sway phase, flutter phase
uniform vec4 uAmp;        // sway (px at the tip, this frame), flutter (px), wave (rad), unused
uniform vec4 uRig;        // a rigid strand: its pivot (px), its angle this frame (rad), 1 (else 0)
uniform vec2 uShift;      // drawn moved from where it was painted (px)
varying vec2 vPx;
void main() {
  vec2 px = vPx - uShift;
  float s = clamp((px.y - uSw.x) / uSw.y, 0.0, 1.0);
  float w = pow(s, 1.5);
  float d = uAmp.x * w * sin(uSw.z - uAmp.z * s) + uAmp.y * w * sin(uSw.w - 2.3 * uAmp.z * s);
  vec2 q = vec2(px.x - d, px.y);
  if (uRig.w > 0.5) {
    // turned as one piece about the pivot: the sprite's point that shows here
    vec2 r = px - uRig.xy;
    float c = cos(uRig.z), sn = sin(uRig.z);
    q = uRig.xy + vec2(c * r.x + sn * r.y, -sn * r.x + c * r.y);
  }
  vec2 st = (q - uSpr.xy) / uSpr.zw;
  if (st.x < 0.0 || st.y < 0.0 || st.x > 1.0 || st.y > 1.0) discard;
  vec4 c = texture2D(tSpr, vec2(st.x, 1.0 - st.y));
  if (c.a < 0.003) discard;
  gl_FragColor = vec4(c.rgb * c.a, c.a);
}`;

function hash(s) {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967296;
}

export async function vinesLayer(ctx, opts) {
  const meta = await fetch(`/out/plates/${opts.plate}/lift.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  if (!meta?.strands?.length) throw new Error(`vines: no lift.json for plate ${opts.plate} (run tools/vine_layers.py)`);
  // whole cycles over the video's loop (the timeline's period when it loops: 20 minutes, so the breeze doesn't repeat
  // every 2 minutes; it is a whole number of the base loop, so the base loop's joins stay seamless too)
  const L = ctx.timeline?.loop?.period || ctx.loopSeconds;
  const cyc = (hz) => Math.max(1, Math.round(hz * L));
  const items = [];
  for (const s of meta.strands) {
    const own = opts.strands?.[s.name] ?? {};
    const o = own.rigid ? { deg: 3, hz: 0.5, ...own } : { amp: 18, hz: 0.1, gust: 1.5, wave: 1.4, ...own };
    const tex = await plateTexture(opts.plate, s.file, { srgb: true });
    const [x0, y0, x1, y1] = s.box;
    const pv = s.pivot ?? [(x0 + x1) / 2, s.top];
    // the widest swing: breeze and gust at once, or a rigid strand's arc at its foot
    const reach = o.rigid ? Math.ceil(Math.hypot(Math.max(x1 - pv[0], pv[0] - x0), y1 - pv[1]) * Math.sin((o.deg * Math.PI) / 180) + 6)
      : Math.ceil(1.4 * (o.amp * (1 + o.gust * 1.2) + (o.flutter ?? 0.18 * o.amp)) + 4);
    const [sx, sy] = o.shift ?? [0, 0];
    const mat = new THREE.ShaderMaterial({
      vertexShader: vert, fragmentShader: frag, ...PREMUL,
      uniforms: {
        tSpr: { value: tex }, uBox: { value: new THREE.Vector4(x0 - reach + sx, y0 + sy, x1 - x0 + 2 * reach, y1 - y0) },
        uShift: { value: new THREE.Vector2(sx, sy) },
        uSpr: { value: new THREE.Vector4(x0, y0, x1 - x0, y1 - y0) },
        uSw: { value: new THREE.Vector4(s.top, Math.max(1, s.bottom - s.top), 0, 0) }, uAmp: { value: new THREE.Vector4(0, 0, o.wave ?? 0, 0) },
        uRig: { value: new THREE.Vector4(pv[0], pv[1], 0, o.rigid ? 1 : 0) },
      },
    });
    const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
    mesh.frustumCulled = false;
    mesh.renderOrder = opts.renderOrder ?? 16;     // over the plate, the birds and the fireflies far behind it
    mesh.userData.noAO = true;
    ctx.add(mesh);
    items.push({ mat, o, ph: o.phase ?? TAU * hash(`${s.name}:${ctx.seed}`), ph2: TAU * hash(`${s.name}:flutter:${ctx.seed}`), n: cyc(o.hz),
      nf: cyc(o.hz * 3.7), xf: (x0 + x1) / 2 / W });
  }
  // the breeze: two slow swells (0.6 to 1.4 of the sway) crossing the frame from one side in a few seconds, so strands
  // side by side swing harder together and the curtain at the right edge follows the strands in the opening
  const nb = cyc(1 / 37), nb2 = cyc(1 / 89), pb = TAU * hash(`breeze:${ctx.seed}`), pb2 = TAU * hash(`breeze2:${ctx.seed}`);
  ctx.animate((t) => {
    const tt = t % L, g = flurryEnv(ctx.timeline, t);
    for (const it of items) {
      const u = it.mat.uniforms, o = it.o;
      if (o.rigid) {
        // a pendulum: the same arc every swing, whole swings per loop
        u.uRig.value.z = ((o.deg * Math.PI) / 180) * Math.sin(TAU * it.n * tt / L + it.ph);
        continue;
      }
      const breeze = 1 + 0.25 * Math.sin(TAU * nb * tt / L + pb - 1.1 * it.xf) + 0.15 * Math.sin(TAU * nb2 * tt / L + pb2 - 0.7 * it.xf);
      u.uSw.value.z = TAU * it.n * tt / L + it.ph;
      u.uSw.value.w = TAU * it.nf * tt / L + it.ph2;
      u.uAmp.value.x = o.amp * breeze * (1 + o.gust * 1.2 * g);
      u.uAmp.value.y = (o.flutter ?? 0.18 * o.amp) * breeze;
    }
  });
  return items[0]?.mat ?? null;
}

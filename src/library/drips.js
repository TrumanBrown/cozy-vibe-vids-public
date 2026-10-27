// Hanging drops along wet edges (awning hems, eaves, lantern bottoms, wet cloth). Each source grows a drop:
// it swells (volume ~ time, radius ~ cube root), stretches into a teardrop on a neck, lets go and falls
// (gravity, motion blur), and the small bead it leaves behind grows the next one. Sources: plate.json
// "beads" (tools/plate_prep.py bead_sources: every wet edge over the opening; low points drip faster).
// Whether a drop fills follows the rain (weather track at the start of its cycle): in a lull many sources
// just hang a small bead. Everything is a pure function of the loop phase (integer cycles per loop) and
// the absolute time (weather), so it is deterministic and the loop seam is exact.
//
// Look: a tiny lens. The defocused plate seen through it (flipped and magnified), a dark rim, a specular
// highlight and a bright caustic at the bottom from the warm light around it (lights.png glow); falling
// drops are motion-blurred streaks with the same light. Masked by the plate's outdoor mask, so a drop only
// shows below the edge it hangs from and vanishes behind nearer things (counter, pet, posts). A drop hanging
// from something that moves (a swaying cloth or plant, a swinging lantern) moves with it (hangingFrom).
//
// opts: { plate, size: max drop radius px at 4K (5.5), min: remnant radius (1.6), period: [s, s] for flat
//   edges (low points: half) ([4, 11]), ppm: px per m at the edge (900), shutter (1/60), gain (1), sources:
//   [[x, y, w(, stop, ppm)]] px override or "strands" (plate.json strand_drips: where tools/plate_clean.py
//   removed painted drips; each falls until the ground below it, `stop`, at its own px per m), density:
//   share of the sources used (1), horizon (0.45), focal (2700) }
// A drop that lands on wet ground (the strand drips' splash flag) splashes there (user 2026-10-19): a ring spreading
// on the wet ground (flattened by the view down onto it; only where masks.png says wet) and 3 droplets thrown up.
// One that lands on something nearer just goes out of sight behind it (a splash on a cat's back read as rain
// hitting the cat).
import * as THREE from 'three';
import { flashAt } from './timeline.js';
import { plateTexture, PREMUL, GLSL_COMMON, weatherUniforms, WEATHER_GLSL, hangingFrom } from './overlay.js';

const vert = /* glsl */ `
${GLSL_COMMON}
${WEATHER_GLSL}
attribute vec4 aSrc;     // edge point x, y (px, y down), weight (1 flat edge, 2 low point), seed
attribute vec3 aFall;    // row where the falling drop meets the ground or a nearer object (px), px per m (0 = uPpm), 1 = it lands on wet ground (splash)
attribute vec2 aMove;    // where the edge point is carried this frame by a moving region it hangs from (px)
attribute float aKind;   // 0 = hanging drop, 1 = the drop released at the start of this cycle, falling, 2 = its splash where it lands
uniform float uLoop, uPhase, uPpm, uRmax, uRmin, uShutter, uHorizon, uFocal;
uniform vec2 uPer, uRes;
varying vec2 vLoc;       // px relative to the edge point (hanging) or streak-local (falling: x across, y along) or the landing point (splash)
varying vec4 vShape;     // hanging: radius, center y, neck stretch, 0 | falling: half length, radius, 0, 1 | splash: ring radius, sin(view), s since landing, 2
varying vec2 vUv;
varying vec2 vCtr;       // drop center (uv, y up): where the lens looks from

float wetAt(uint sd, float k, float tStart) {
  float rain = weather(tStart).r;
  return step(hash1(sd * 7u + uint(k) * 13u + 5u), clamp(0.15 + 0.8 * rain, 0.0, 1.0));
}

void main() {
  vec2 q = position.xy;
  uint sd = uint(aSrc.w);
  float w = aSrc.z;
  float T0 = mix(uPer.x, uPer.y, hash1(sd * 3u + 1u)) / w;
  float n = max(1.0, floor(uLoop / T0 + 0.5));
  float T = uLoop / n;
  float c = uPhase * n + hash1(sd * 3u + 2u);
  float k = mod(floor(c), n);
  float age = fract(c) * T;
  float tStart = uTime - age;
  float scale = mix(0.72, 1.2, hash1(sd * 3u + 3u)) * (w > 1.5 ? 1.18 : 1.0);
  float rMax = uRmax * scale;
  vec2 edge = aSrc.xy + aMove;
  if (aKind < 0.5) {
    // Hanging drop of this cycle: volume ~ age (cube-root radius), a neck stretches over the last 15%.
    float wet = wetAt(sd, k, tStart);
    float v = wet * age / T;
    float r = mix(uRmin, rMax, pow(v, 0.333));
    float s = smoothstep(0.84, 1.0, v);
    float cy = r * (0.72 + 0.95 * s);
    float R = r + 2.5;
    vec2 lo = vec2(-R, -2.0), hi = vec2(R, cy + R);
    vec2 p = mix(lo, hi, q * 0.5 + 0.5);
    vLoc = p;
    vShape = vec4(r, cy, s, 0.0);
    vec2 px = edge + p;
    vUv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
    vCtr = vec2(edge.x / uRes.x, 1.0 - (edge.y + cy) / uRes.y);
    gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
    return;
  }
  // The drop let go at the start of this cycle (if the previous cycle was wet): free fall from the point it
  // hung at, a slight sideways drift, motion-blurred over the shutter.
  float kp = mod(k - 1.0, n);
  float wet = wetAt(sd, kp, tStart - T);
  float ppm = aFall.y > 0.0 ? aFall.y : uPpm;
  float y0 = edge.y + rMax * 1.67;
  if (aKind > 1.5) {
    // Its splash where it lands on the ground (only drops with a known landing row: the strand drips): a ring
    // spreading on the wet ground, flattened by the view down onto it, and a few droplets thrown up and falling back.
    float tl = sqrt(max(2.0 * (aFall.x - y0) / (9.81 * ppm), 0.0));
    float sa = age - tl;
    if (wet < 0.5 || aFall.z < 0.5 || aFall.x > 1e5 || aFall.x <= y0 || sa < 0.0 || sa > 0.45) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vShape = vec4(0.0); return; }
    float dxl = (hash1(sd * 7u + uint(kp) * 17u) - 0.5) * 0.08 * tl * ppm;
    float sinE = clamp((aFall.x - uHorizon) / uFocal, 0.06, 0.8);
    float rr = rMax * 0.82;
    float R = rr * 1.2 + 0.25 * ppm * sa;          // a ripple spreads ~0.25 m/s
    float up = max(4.0 * rr, 0.055 * ppm) + 3.0;    // splash droplets rise 2.5-5 cm
    float hw = max(R, 0.08 * ppm) + 3.0;
    vec2 lo = vec2(-hw, -up), hi = vec2(hw, R * sinE + 3.0);
    vec2 p = mix(lo, hi, q * 0.5 + 0.5);
    vLoc = p;
    vShape = vec4(R, sinE, sa, 2.0);
    vec2 c = vec2(edge.x + dxl, aFall.x);
    vec2 px = c + p;
    vUv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
    vCtr = vec2(rr, ppm);
    gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
    return;
  }
  float vy = 9.81 * age * ppm;
  float y = y0 + 0.5 * 9.81 * age * age * ppm;
  if (wet < 0.5 || age > 1.6 || y - vy * uShutter > min(uRes.y + 10.0, aFall.x)) { gl_Position = vec4(2.0, 2.0, 2.0, 1.0); vShape = vec4(0.0); return; }
  float dx = (hash1(sd * 7u + uint(kp) * 17u) - 0.5) * 0.08 * age * ppm;
  float rr = rMax * 0.82;
  float L = max(min(vy * uShutter, aFall.x - y0), 0.0);
  vec2 ctr = vec2(edge.x + dx, min(y, aFall.x) - 0.5 * L);
  float hl = 0.5 * L + rr + 1.5, hw = rr + 1.5;
  vLoc = vec2(q.x * hw, q.y * hl);
  vShape = vec4(0.5 * L, rr, 0.0, 1.0);
  vec2 px = ctr + vec2(q.x * hw, q.y * hl);
  vUv = vec2(px.x / uRes.x, 1.0 - px.y / uRes.y);
  vCtr = vec2(ctr.x / uRes.x, 1.0 - ctr.y / uRes.y);
  gl_Position = vec4(vUv * 2.0 - 1.0, 0.0, 1.0);
}`;

const frag = /* glsl */ `
uniform sampler2D tLights, tBlur, tEnv, tMask;
uniform vec3 uWarm, uSky;
uniform float uGain, uFlash, uEnvGain;
uniform vec2 uRes;
varying vec2 vLoc;
varying vec4 vShape;
varying vec2 vUv;
varying vec2 vCtr;
float smin(float a, float b, float k) { float h = clamp(0.5 + 0.5 * (b - a) / k, 0.0, 1.0); return mix(b, a, h) - k * h * (1.0 - h); }
void main() {
  vec4 lt = texture2D(tLights, vUv);
  float mask = lt.g;
  if (mask < 0.01) discard;
  vec3 env = texture2D(tEnv, vUv).rgb * uEnvGain;
  vec3 light = (uWarm * lt.b * 1.6 + env + uSky * 0.4) * (1.0 + uFlash);
  if (vShape.w > 1.5) {
    // Splash: the ring catches the light around it like the ground's rain rings (screen distance to the
    // flattened ring), fading as it spreads; 3 droplets fly up and fall back within ~0.2 s.
    float R = vShape.x, sinE = vShape.y, sa = vShape.z, rr = vCtr.x, ppm = vCtr.y;
    vec2 p = vLoc;
    vec2 qq = vec2(p.x, p.y / sinE);
    float lq = max(length(qq), 1e-3);
    vec2 gr = vec2(qq.x / lq, qq.y / (lq * sinE));
    float ds = (lq - R) / max(length(gr), 1e-3);
    float fade = 1.0 - sa / 0.45;
    float ring = exp(-ds * ds / 0.5) * fade * fade * 0.8 * smoothstep(0.2, 0.6, texture2D(tMask, vUv).g);   // a ring spreads only on wet ground
    float drops = 0.0;
    float gp = 9.81 * ppm;
    for (int i = 0; i < 3; i++) {
      float fi = float(i);
      float ang = (fi - 1.0) * 0.6;
      float v0 = ppm * sqrt(2.0 * 9.81 * (0.025 + 0.012 * fi));
      vec2 d = vec2(sin(ang) * v0 * 0.6 * sa, -(cos(ang) * v0 * sa - 0.5 * gp * sa * sa));
      if (d.y < 0.0) drops += clamp(max(0.7, 0.35 * rr) + 0.5 - length(p - d), 0.0, 1.0) * 0.7;
    }
    float a = clamp(ring + drops, 0.0, 1.0) * mask * uGain;
    if (a < 0.003) discard;
    gl_FragColor = vec4(light * 1.2 * a, a * 0.25);
    return;
  }
  if (vShape.w > 0.5) {
    // Falling: exposure coverage of a disc swept along the streak (as rain.js), faint and bright.
    float hL = vShape.x, rr = vShape.y;
    float cc = sqrt(max(rr * rr - vLoc.x * vLoc.x, 0.0));
    float ov = clamp(min(vLoc.y + cc, hL) - max(vLoc.y - cc, -hL), 0.0, 2.0 * cc);
    float a = clamp(0.9 * ov / max(min(2.0 * rr, 2.0 * hL), 1e-3) * (2.0 * rr) / (2.0 * hL + 2.0 * rr), 0.0, 0.9) * mask * uGain;
    if (a < 0.002) discard;
    gl_FragColor = vec4(light * 1.15 * a, a);
    return;
  }
  float r = vShape.x, cy = vShape.y, s = vShape.z;
  if (r <= 0.0) discard;
  vec2 p = vLoc;
  float dC = length(p - vec2(0.0, cy)) - r;
  // neck: a tapered capsule from the edge to the drop (thin when stretched)
  float rn = r * mix(0.55, 0.28, s);
  float t = clamp(p.y / max(cy, 1e-3), 0.0, 1.0);
  float dN = length(vec2(p.x, p.y - t * cy)) - rn * mix(0.85, 1.0, t);
  float d = smin(dC, dN, 0.45 * r);
  float cov = clamp(0.5 - d, 0.0, 1.0);
  if (cov < 0.003) discard;
  vec2 nn = clamp((p - vec2(0.0, cy)) / r, -1.0, 1.0);
  float l2 = dot(nn, nn);
  float nz = sqrt(max(1.0 - min(l2, 1.0), 0.0));
  // the view through the drop: the scene behind, flipped and magnified, dimmer toward the rim
  vec2 refr = vCtr - vec2(nn.x, -nn.y) * r * 2.2 / uRes;
  vec3 bg = texture2D(tBlur, refr).rgb;
  float rim = smoothstep(0.55, 1.0, sqrt(l2));
  vec3 body = bg * (0.55 + 0.35 * nz) * (1.0 - 0.55 * rim);
  vec3 N = normalize(vec3(nn.x, nn.y, nz + 1e-3));
  float spec = pow(max(dot(N, normalize(vec3(-0.45, -0.6, 0.66))), 0.0), 28.0);
  float caus = smoothstep(0.3, 0.85, nn.y) * (1.0 - smoothstep(0.85, 1.0, sqrt(l2))) * smoothstep(0.0, 0.5, nz);
  vec3 add = light * (2.4 * spec + 0.7 * caus);
  float a = cov * mask * 0.9 * uGain;
  gl_FragColor = vec4(body * a + add * cov * mask * uGain, a);
}`;

export async function dripsLayer(ctx, opts) {
  const meta = await fetch(`/out/plates/${opts.plate}/plate.json`).then((r) => r.json());
  let src = opts.sources === 'strands' ? (meta.strand_drips ?? []) : (opts.sources ?? meta.beads ?? []);
  if (opts.density != null && opts.density < 1) src = src.filter((_, i) => ((i * 0.618034) % 1) < opts.density);
  if (opts.box) {
    const [x0, y0, x1, y1] = opts.box;
    src = src.filter(([x, y]) => x >= x0 * 3840 && x <= x1 * 3840 && y >= y0 * 2160 && y <= y1 * 2160);
  }
  if (!src.length) return null;
  const [tLights, tBlur, tEnv, tMask] = await Promise.all([
    plateTexture(opts.plate, 'lights.png'), plateTexture(opts.plate, 'blur.png', { srgb: true }), plateTexture(opts.plate, 'env.png', { srgb: true }),
    plateTexture(opts.plate, 'masks.png'),
  ]);
  const N = src.length;
  const K = 3;     // per source: hanging drop, falling drop, splash
  const g = new THREE.InstancedBufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array([-1, -1, 0, 1, -1, 0, 1, 1, 0, -1, 1, 0]), 3));
  g.setIndex([0, 1, 2, 0, 2, 3]);
  g.instanceCount = K * N;
  const aSrc = new Float32Array(K * N * 4), aKind = new Float32Array(K * N), aFall = new Float32Array(K * N * 3);
  src.forEach(([x, y, w, stop, ppm, splash], i) => {
    const sd = 1 + ((i * 2654435761) >>> 0) % 1000003;
    for (let j = 0; j < K; j++) {
      aSrc.set([x, y, w ?? 1, sd], (K * i + j) * 4);
      aFall.set([stop ?? 1e6, ppm ?? 0, splash ?? 0], (K * i + j) * 3);
      aKind[K * i + j] = j;
    }
  });
  g.setAttribute('aSrc', new THREE.InstancedBufferAttribute(aSrc, 4));
  g.setAttribute('aFall', new THREE.InstancedBufferAttribute(aFall, 3));
  g.setAttribute('aKind', new THREE.InstancedBufferAttribute(aKind, 1));
  // Drops hanging from a swaying cloth or plant or a swinging lantern move with it.
  const hang = await hangingFrom(ctx, opts.plate, src);
  const aMove = new THREE.InstancedBufferAttribute(new Float32Array(K * N * 2), 2);
  aMove.setUsage(THREE.DynamicDrawUsage);
  g.setAttribute('aMove', aMove);
  const warm = new THREE.Color(opts.warm ?? '#ffb46c');
  const sky = meta.env_linear?.sky ?? [0.05, 0.06, 0.12];
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, ...PREMUL,
    uniforms: {
      ...weatherUniforms(ctx),
      tLights: { value: tLights }, tBlur: { value: tBlur }, tEnv: { value: tEnv }, tMask: { value: tMask },
      uLoop: { value: ctx.loopSeconds }, uPhase: { value: 0 }, uPpm: { value: opts.ppm ?? 900 },
      uRmax: { value: opts.size ?? 5.5 }, uRmin: { value: opts.min ?? 1.6 }, uShutter: { value: opts.shutter ?? 1 / 60 },
      uHorizon: { value: (opts.horizon ?? 0.45) * 2160 }, uFocal: { value: opts.focal ?? 2700 },
      uPer: { value: new THREE.Vector2(...(opts.period ?? [4, 11])) }, uRes: { value: new THREE.Vector2(3840, 2160) },
      uWarm: { value: new THREE.Vector3(warm.r, warm.g, warm.b) }, uSky: { value: new THREE.Vector3(...sky) },
      uGain: { value: opts.gain ?? 1 }, uFlash: { value: 0 }, uEnvGain: { value: opts.envGain ?? 1.5 },
    },
  });
  const mesh = new THREE.Mesh(g, mat);
  mesh.frustumCulled = false;
  mesh.renderOrder = opts.renderOrder ?? 14;
  mesh.userData.noAO = true;
  ctx.add(mesh);
  const L = ctx.loopSeconds;
  ctx.animate((t) => {
    mat.uniforms.uPhase.value = (t % L) / L;
    mat.uniforms.uTime.value = t;
    mat.uniforms.uFlash.value = flashAt(ctx.timeline, t).flash * 2.0;
    if (hang.length) {
      for (const h of hang) {
        const [dx, dy] = ctx.regionMotion.offsetPx(h.id, h.x, h.y, h.ax, h.w);
        aMove.array.set([dx, dy, dx, dy, dx, dy], 2 * K * h.i);
      }
      aMove.needsUpdate = true;
    }
  });
  return mesh;
}

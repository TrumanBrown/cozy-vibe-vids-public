// plate.js's shaders: one full-screen pass over the key-art plate (sway, ripples, mist, flicker, switchable lights,
// lightning, the breathing pet). plateLayer in plate.js sets the uniforms every frame.
export const plateFrag = /* glsl */ `
uniform sampler2D tPlate, tPlateOff, tLightId, tLightW, tDepth, tMask, tLights, tFlash, tBlur;
uniform float uLevel[64];  // per-light level (1 = as painted, 0 = off): timeline.js lightLevels
uniform float phase;
uniform vec4 pet;          // center x, y (uv, y up), radius x, radius y
uniform float petBase;     // uv y of the pet's bottom (scale anchor)
uniform float petAmp;      // breathing stretch at the pet's top (fraction of its height; Treetop 0.035)
uniform sampler2D tPet;    // plate_prep pet.png: R = how much a point rises with a breath (the torso), G = the pet
uniform float uPetMap;     // 1 when pet.png exists (else the older soft ellipse)
uniform float uPetMulti;   // 1: several characters; R = height above its own base / petHMax (its own amplitude baked in), B = index
uniform float petHMax;
uniform float mistAmt, swayAmt, rippleAmt, flickerAmt, black;
uniform vec2 rippleXY;     // legacy ripple direction weights (x, y); wet pavement shimmers sideways too
uniform vec2 ringAmt;      // rain rings on water: additive brightness, multiplicative (rings break up reflections)
uniform vec3 mistCol;
uniform float flash;       // lightning light (timeline.js flashAt), ~1 at a strong stroke's peak
uniform vec2 flashUv;      // glow center in the sky (uv, y up)
uniform vec3 flashCol;
uniform vec4 flashAmt;     // sky, far landscape, room near the opening, room ambient
uniform float farFlash;    // distant lightning (timeline.js flashAt .far), ~0.2-0.45 at a pulse's peak
uniform vec2 farUv;        // its glow center in the cloud bank (uv, y up)
uniform vec3 farCol;
uniform float rainK;       // weather track rain intensity (1 = nominal)
// Pet micro-motions (timeline.js petState). Ears: pivot xy, center xy (uv, y up); radius xy; angle (rad).
uniform vec4 earAP, earBP;  // pivot.xy, center.xy
uniform vec4 earAR, earBR;  // radius.xy, angle, unused
uniform vec4 tailP;        // base.xy, tip.xy (uv, y up)
uniform vec2 tailR;        // half thickness (uv y), lift (uv y)
uniform float breathK;     // breathing amplitude multiplier (sighs)
uniform vec2 flurry;       // gust flurry (timeline.js flurryEnv): strength 0..1, signed lean (+ = to the right)
uniform sampler2D tFlow;   // waterfalls (plate_prep flow.png): R weight, G progress down the fall, B fall height / 0.25
uniform float flowAmt;
uniform vec4 waterCam;     // lake camera (boat.js lakeCamera): focal px (4K), horizon row (0..1, y down), height m, enabled
uniform vec4 waterFlow;    // downstream direction (world x, z; unit), horizontal / vertical reflection sway (px at 4K)
uniform vec4 waterGust;    // gust patch: center x (m, world), strength 0..1, wind sign, s since the gust began
uniform float waterRough;  // gust roughness (px at 4K)
// Named regions (plate_prep regions.png: R id, G feathered weight, B anchor-axis coordinate) and their state
// this frame (tReg: 64 ids x 8 rows, written by regionState() below): sway, translate (bob), pendulum, flow,
// brightness level (flicker, neon, gutter), twinkle, shimmer, breathe. uSpill: light that flickering
// regions throw on their surroundings (center uv, sigma uv, current gain).
uniform sampler2D tRegion, tReg;
uniform sampler2D tRefl;   // plate_prep refl.png: R = id of the light a wet-ground reflection belongs to, G = its share of the pixel
uniform float uRegions;
uniform vec4 uSpill[8];
uniform int uSpillN;
// Rain on the ground and on water seen by a level camera (opts.ground): drops land on a grid laid on the ground
// plane, so ring sizes and their vertical squash follow from the perspective (screen size ~ rows below the
// horizon). gRain: enabled, horizon row (0..1, y down), focal px (4K), ring growth (camera heights / s);
// gRing: refraction px, highlight gain, cells per camera height, density. gWet: rain intensity now.
uniform vec4 gRain, gRing;
uniform float gWet, uLoopS;
uniform int dbgMode;       // QA (params plate=water|off|raw|black): the masks, the sample offset, the raw plate, or black (layers alone)
varying vec2 vUv;
const float TAU = 6.28318530718;

float h11(float n) { return fract(sin(n * 127.1 + 1.7) * 43758.5453); }
float h21(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }
// Value noise, periodic in x with period px cells.
float vnoise(vec2 p, float px) {
  vec2 i = floor(p), f = fract(p); f = f * f * (3.0 - 2.0 * f);
  float x0 = mod(i.x, px), x1 = mod(i.x + 1.0, px);
  return mix(mix(h21(vec2(x0, i.y)), h21(vec2(x1, i.y)), f.x), mix(h21(vec2(x0, i.y + 1.0)), h21(vec2(x1, i.y + 1.0)), f.x), f.y);
}
float fbm(vec2 p, float px) {
  float s = 0.0, a = 0.5;
  for (int k = 0; k < 4; k++) { s += a * vnoise(p, px); p *= 2.0; px *= 2.0; a *= 0.5; }
  return s;
}
// Rotate the content around a pivot by ang (uv, y up) inside a soft ellipse: returns the sample offset.
vec2 earWarp(vec2 uv, vec4 P, vec4 R) {
  if (R.z == 0.0) return vec2(0.0);
  vec2 asp = vec2(1.7778, 1.0);
  float w = 1.0 - smoothstep(0.75, 1.25, length((uv - P.zw) / R.xy));
  float a = R.z * w;                     // display rotated by -a (tip moves back) -> sample at R(a)
  vec2 d = (uv - P.xy) * asp;
  vec2 s = vec2(cos(a) * d.x - sin(a) * d.y, sin(a) * d.x + cos(a) * d.y) / asp + P.xy;
  return s - uv;
}

ivec2 regTexel(vec2 uv) { return ivec2(clamp(uv, 0.0, 0.9999) * vec2(textureSize(tRegion, 0))); }
vec4 regRow(int row, int id) { return texelFetch(tReg, ivec2(id, row), 0); }
// Rotation of content by ang about pivot p (uv, y up; aspect-corrected): returns the sample offset.
vec2 rotWarp(vec2 uv, vec2 p, float ang) {
  vec2 asp = vec2(1.7778, 1.0);
  vec2 d = (uv - p) * asp;
  float c = cos(ang), s = sin(ang);
  return vec2(c * d.x - s * d.y, s * d.x + c * d.y) / asp + p - uv;
}

// The water plane (y = 0) seen at uv through the lake camera (boat.js lakeCamera: tilted pinhole at the
// plate's horizon row, height above the water): world x (right) and z (toward the camera), and the sine
// of the grazing angle (how steeply the view ray meets the water).
vec2 waterXZ(vec2 uv, out float sg) {
  float F = max(waterCam.x, 1.0);
  float th = atan((1080.0 - waterCam.y * 2160.0) / F);
  float s = sin(th), c = cos(th);
  float a = (uv.x * 3840.0 - 1920.0) / F, b = -((1.0 - uv.y) * 2160.0 - 1080.0) / F;
  vec3 d = vec3(a, c * b - s, -s * b - c);
  float dy = min(d.y, -1e-3);
  sg = -dy / length(d);
  return (waterCam.z / -dy) * d.xz;
}
// Calm river surface: slope (d height / dx, d height / dz) of a sum of gentle waves, mostly carried
// downstream with the current. Each wave makes an integer number of cycles per loop (seamless); waves
// shorter than ~3 px on screen fade out (no aliasing far away). Directions are relative to the flow.
//   x: angle (rad) from downstream, y: wavelength (m), z: cycles per 120 s loop, w: weight
const int NW = 10;
const vec4 WAVES[NW] = vec4[NW](
  vec4(0.0, 3.75, 11.0, 0.20), vec4(0.49, 2.65, 15.0, 0.17), vec4(-0.61, 2.2, 16.0, 0.15), vec4(0.96, 1.85, 14.0, 0.11),
  vec4(-1.08, 1.5, 14.0, 0.09), vec4(0.21, 1.25, 34.0, 0.08), vec4(-0.26, 4.6, 9.0, 0.13),
  vec4(0.70, 0.9, 190.0, 0.05), vec4(-0.84, 0.7, 225.0, 0.04), vec4(0.09, 0.55, 265.0, 0.03));
vec2 waterSlope(vec2 P, float fp) {
  vec2 fl = waterFlow.xy, pr = vec2(-fl.y, fl.x);
  vec2 g = vec2(0.0);
  for (int i = 0; i < NW; i++) {
    vec4 w = WAVES[i];
    vec2 dir = cos(w.x) * fl + sin(w.x) * pr;
    float aa = 1.0 - smoothstep(0.3, 0.6, fp / w.y);
    float arg = TAU * (dot(P, dir) / w.y - w.z * phase) + float(i) * 2.399;
    g += w.w * aa * cos(arg) * dir;
  }
  return g;
}

// Ground coordinates (camera heights: x across, z ahead) of a pixel below the horizon, and dy = px below it.
vec2 groundXZ(vec2 uv, out float dy) {
  dy = (1.0 - uv.y) * 2160.0 - gRain.y * 2160.0;
  float d = max(dy, 1.0);
  return vec2((uv.x * 3840.0 - 1920.0) / d, gRain.z / d);
}
// Raindrop impacts on the ground plane: one per cell per cycle (integer cycles per loop, 0.5-1.4 s), kept while
// it rains (gWet). Each makes a splash speck for ~70 ms and a ring that grows and fades. Returns the screen
// offset of the sample (uv: rings refract the reflections), a ring highlight weight and a splash weight.
vec4 groundRings(vec2 uv) {
  float dy;
  vec2 g = groundXZ(uv, dy);
  float cellPx = dy / gRing.z;                      // horizontal cell size on screen
  float vis = smoothstep(4.0, 10.0, cellPx);
  if (dy < 3.0 || vis <= 0.0) return vec4(0.0);
  vec2 c = g * gRing.z;
  vec2 ci = floor(c);
  vec2 off = vec2(0.0);
  float hi = 0.0, sp = 0.0;
  float squash = dy / gRain.z;                      // vertical squash of a ground circle on screen
  // Perspective shear: a step away from the camera on the ground also moves sideways on screen, toward the
  // vanishing point (sx / f per unit of depth step). Shapes defined on the ground (rings) get it for free;
  // anything placed on screen (refraction directions, splash crowns) must include it.
  float sx = uv.x * 3840.0 - 1920.0;
  float shear = sx / gRain.z;
  for (int j = -1; j <= 1; j++) {
    for (int i = -1; i <= 1; i++) {
      vec2 cc = ci + vec2(float(i), float(j));
      float h0 = h21(cc + 0.17), h1 = h21(cc + 3.1);
      float n = max(1.0, floor(uLoopS / mix(0.5, 1.4, h1) + 0.5));
      float ph = phase * n + h0;
      float k = floor(ph);
      if (h21(cc + vec2(k * 0.37 + 0.5, 1.3)) > gWet) continue;
      float age = fract(ph) * uLoopS / n;
      float life = mix(0.3, 0.6, h21(cc + vec2(k, 9.1)));
      if (age > life) continue;
      vec2 p0 = cc + vec2(h21(cc + vec2(k, 2.0)), h21(cc + vec2(k, 5.0)));
      vec2 d = (c - p0) / gRing.z;                  // camera heights
      float dist = length(d);
      float big = mix(0.6, 1.4, h21(cc + vec2(k, 7.3)));
      float R = gRain.w * age * big;
      float wdt = 0.004 + 0.1 * R;
      float A = (1.0 - age / life);
      A *= A;
      float x = (dist - R) / wdt;
      float prof = exp(-x * x);
      float slope = -2.0 * x * prof;                // d(profile)/d(dist): a crest with a trough inside
      vec2 dir = dist > 1e-5 ? d / dist : vec2(0.0);
      off += vec2(dir.x - shear * dir.y, -dir.y * squash) * slope * A * big;
      hi += prof * A;
      // splash crown: a tiny bright speck right at the impact, round on screen (a little taller than wide), so
      // it never smears into a dash: measured in screen px from where the impact point projects
      vec2 gp = p0 / gRing.z;
      float dyP = gRain.z / max(gp.y, 1e-3);
      vec2 dS = vec2(sx - gp.x * dyP, dy - dyP);
      float sr = max(0.006 * big * dyP, 1.2);
      float sd = length(vec2(dS.x, dS.y * 0.6)) / sr;
      sp += exp(-sd * sd) * (1.0 - smoothstep(0.0, 0.07, age)) * big;
    }
  }
  return vec4(off * gRing.x * vis / vec2(3840.0, 2160.0) * vec2(1.0, -1.0), hi * vis, sp * vis);
}
// River current (region flag 256; row 7: downstream direction in ground space xy, ripple sway px, glint gain;
// row 2 .z: flow phase, whole cycles per loop). Ripples are laid out on screen with perspective (cells shrink
// toward the horizon and flatten into thin rows far away, never below a few px, so far water does not alias
// into noise) and slide downstream: two layers at different speeds (each moves a whole noise period per flow
// cycle, so the loop is seamless) whose sum keeps changing shape. At the grazing angles of a river or canal
// the painted reflections, columns of light, shimmer sideways row by row and break into glints that travel
// with the current.
vec3 riverWarp(vec2 uv, vec4 r7, float ph) {
  float dy;
  groundXZ(uv, dy);
  dy = max(dy, 2.0);
  vec2 px = vec2(uv.x * 3840.0, (1.0 - uv.y) * 2160.0);
  float cx = clamp(0.4 * dy, 28.0, 150.0);
  float cy = max(5.0, cx * clamp(dy / 320.0, 0.12, 0.6));
  vec2 q = px / vec2(cx, cy);
  vec2 dn = vec2(r7.x, -r7.y);                    // downstream on screen (ground z toward the camera = down)
  bool alongX = abs(dn.x) >= abs(dn.y);
  vec2 a = alongX ? q : q.yx;                     // first coordinate runs along the flow (the periodic one)
  float sgn = (alongX ? dn.x : dn.y) >= 0.0 ? 1.0 : -1.0;
  const float P = 24.0;
  float n = fbm(vec2(a.x - sgn * fract(ph) * P, a.y), P);
  float m = fbm(vec2(a.x * 2.3 - sgn * fract(ph * 3.0) * P + 7.0, a.y * 1.9 + 13.0), P);
  float amp = r7.z * clamp(dy / 200.0, 0.5, 1.5);
  vec2 off = vec2((n - 0.5) + 0.45 * (m - 0.5), 0.3 * (m - 0.5)) * amp / vec2(3840.0, 2160.0);
  return vec3(off, smoothstep(0.64, 0.8, m) * r7.w);
}

void main() {
  vec2 uv = vUv;
  vec4 m = texture2D(tMask, uv);
  float sky = m.r, water = m.g, leaf = m.b;
  float d = texture2D(tDepth, uv).r; d = d * d;  // depth8 stores sqrt(disparity)

  // Foliage sway (slow gusts * fine flutter); a gust flurry shakes harder and leans the vines downwind.
  float gust = 0.5 + 0.5 * sin(TAU * phase * 3.0 + uv.x * 3.0);
  vec2 off = leaf * swayAmt * gust * (1.0 + 1.1 * flurry.x) * vec2(sin(TAU * phase * 11.0 + uv.y * 40.0 + uv.x * 13.0), 0.4 * cos(TAU * phase * 7.0 + uv.x * 31.0));
  off.x -= leaf * swayAmt * 1.3 * flurry.y * (0.75 + 0.25 * sin(TAU * phase * 23.0 + uv.y * 25.0));

  // Water. With the lake camera: gentle ripples on the river surface (world space, so they are larger near
  // the porch and finer far away) drifting downstream; they tilt the surface, which sways and stretches the
  // painted reflections (mostly vertically at this grazing angle; sideways by the grazing sine). A gust
  // flurry sends a rougher patch across the water. Samples never pull in non-water pixels from the shore.
  // (WP is only meaningful with the lake camera on: with it off, waterXZ divides by a zero focal length, and a
  // GPU compiler that flattens the branch below lets that NaN through, so it stays inside the branch.)
  float sg = 1.0, gustMatte = 0.0;
  vec2 WP = vec2(0.0);
  float fp = 1.0;
  if (waterCam.w > 0.5) {
    WP = waterXZ(uv, sg);
    fp = max(length(dFdx(WP)), length(dFdy(WP)));
  }
  if (waterCam.w > 0.5) {
    if (water > 0.002) {
      vec2 g = waterSlope(WP, fp);
      vec2 wo = vec2(g.x * waterFlow.z * sg / 0.25, -g.y * waterFlow.w);
      if (waterGust.y > 0.0) {
        float dx = (WP.x - waterGust.x) / 22.0;
        float gp = waterGust.y * exp(-dx * dx) * (0.65 + 0.35 * sin(0.11 * WP.x + 0.07 * WP.y + 1.3));
        vec2 wd = vec2(waterGust.z, 0.0);
        vec2 rg = vec2(0.0);
        for (int i = 0; i < 3; i++) {
          float ang = (float(i) - 1.0) * 0.45, lam = 0.45 + 0.2 * float(i);
          vec2 dir = vec2(cos(ang) * wd.x, sin(ang));
          float aa = 1.0 - smoothstep(0.3, 0.6, fp / lam);
          rg += aa * cos(TAU * (dot(WP, dir) / lam - waterGust.w * (1.3 + 0.2 * float(i)))) * dir;
        }
        wo += gp * waterRough * vec2(rg.x * sg / 0.25, -rg.y) / 3.0;
        // Where the gust's ripples are too small to draw (far water), they still dull the reflection.
        gustMatte = gp * smoothstep(0.3, 0.6, fp / 0.65);
      }
      wo /= vec2(3840.0, 2160.0);
      off += water * smoothstep(0.35, 0.85, texture2D(tMask, uv + off + wo).g) * wo;
    }
  } else {
    off += water * rippleAmt * vec2(rippleXY.x * sin(uv.y * 1300.0 + TAU * phase * 50.0 + uv.x * 400.0),
            rippleXY.y * (sin(uv.y * 900.0 + TAU * phase * 40.0 + uv.x * 25.0) * 0.6 + sin(uv.y * 1700.0 - TAU * phase * 67.0 + uv.x * 60.0) * 0.4));
  }

  // Breathing pet. With pet.png only the torso rises (the head, eyes and tail hold still) and a warped sample is
  // kept only where it lands on the pet: the back rises over what is behind it and the background never moves
  // (user 2026-10-21, the pixel greenhouse's dog pushed up the shelf corner behind it and its eyes moved).
  if (uPetMulti > 0.5) {
    // several characters: each its own rate (whole breaths per loop, so the loop stays seamless) and phase
    vec3 pm = texture2D(tPet, uv).rgb;
    float k = floor(pm.b * 8.0 + 0.5) - 1.0;
    float rise = pm.r * petHMax * petAmp * breathK * (0.5 + 0.5 * sin(TAU * phase * (30.0 + 4.0 * k) + 1.9 * k));
    if (rise > 0.0) off.y -= rise * smoothstep(0.3, 0.7, texture2D(tPet, uv + off - vec2(0.0, rise)).g);
  } else if (uPetMap > 0.5) {
    float rise = texture2D(tPet, uv).r * max(uv.y - petBase, 0.0) * petAmp * breathK * (0.5 + 0.5 * sin(TAU * phase * 34.0));
    if (rise > 0.0) off.y -= rise * smoothstep(0.3, 0.7, texture2D(tPet, uv + off - vec2(0.0, rise)).g);
  } else {
    vec2 pd = (uv - pet.xy) / pet.zw;
    float pm = 1.0 - smoothstep(0.55, 1.0, length(pd));
    off.y -= pm * (uv.y - petBase) * petAmp * breathK * (0.5 + 0.5 * sin(TAU * phase * 34.0));
  }
  // Ear flicks (rotation about the ear's base) and a tail-tip twitch (lift growing toward the tip).
  off += earWarp(uv, earAP, earAR) + earWarp(uv, earBP, earBR);
  if (tailR.y != 0.0) {
    vec2 ax = tailP.zw - tailP.xy;
    float s = clamp(dot(uv - tailP.xy, ax) / dot(ax, ax), -0.2, 1.3);
    float along = smoothstep(0.25, 1.0, s) * (1.0 - smoothstep(1.1, 1.3, s));
    float across = 1.0 - smoothstep(0.6, 1.6, abs(uv.y - mix(tailP.y, tailP.w, clamp(s, 0.0, 1.0)) - 0.5 * tailR.y * along) / tailR.x);
    off.y -= tailR.y * along * across;
  }

  // Region warps (data-driven; see regionState): everything is a sample offset, weighted by the region's
  // feathered mask so its edges stay attached.
  int rid = 0, rflags = 0;
  float rw = 0.0, riverGlint = 0.0;
  if (uRegions > 0.5) {
    vec3 rr = texelFetch(tRegion, regTexel(uv), 0).rgb;
    rid = int(rr.r * 255.0 + 0.5);
    if (rid > 0) {
      rw = rr.g;
      float rax = rr.b;
      vec4 r0 = regRow(0, rid), r1 = regRow(1, rid);
      rflags = int(r0.x + 0.5);
      if ((rflags & 1) != 0) {     // sway: pinned at the anchor, growing toward the free end, rippling along it
        float sw = sin(r0.z + uv.y * 9.0 + uv.x * 5.0) * 0.7 + 0.3 * sin(2.0 * r0.z + 1.3 + uv.y * 23.0);
        off.x -= rw * r0.y * pow(rax, 1.5) * sw * r0.w;
      }
      if ((rflags & 2) != 0) off -= rw * r1.xy;                                  // translate (bob, drift)
      if ((rflags & 4) != 0) off += rw * rotWarp(uv, regRow(2, rid).xy, -r1.z);   // pendulum about the pivot
      if ((rflags & 64) != 0) {    // shimmer (heat haze): rising sinusoidal wobble
        vec4 r3 = regRow(3, rid), r6 = regRow(6, rid);
        float k = r6.x;
        off.x += rw * r3.z * sin(uv.y * k - TAU * r3.w + 1.7 * sin(uv.x * k * 0.37 + TAU * r3.w));
        off.y += rw * r3.z * 0.5 * sin(uv.x * k * 0.8 + TAU * r3.w * 0.5 + uv.y * k * 0.3);
      }
      if ((rflags & 128) != 0) {   // breathing: vertical stretch from the region's base
        vec4 r5 = regRow(5, rid);
        off.y -= rw * (uv.y - r5.y) * r5.x * r5.z;
      }
      if ((rflags & 256) != 0) {   // river current: only samples from the water itself (never a bar in front of it)
        vec3 rv = riverWarp(uv, regRow(7, rid), regRow(2, rid).z);
        vec2 o = rw * rv.xy;
        vec3 sq = texelFetch(tRegion, regTexel(uv + off + o), 0).rgb;
        float kq = int(sq.r * 255.0 + 0.5) == rid ? sq.g : 0.0;
        off += o * kq;
        riverGlint = rw * rv.z * kq;
      }
    }
  }
  vec4 gr = vec4(0.0);
  if (gRain.x > 0.5 && water > 0.01) {
    gr = groundRings(uv) * water * smoothstep(0.2, 0.8, texture2D(tLights, uv).g);
    off += gr.xy;
  }

  vec3 col = texture2D(tPlate, uv + off).rgb;
  if (rid > 0 && (rflags & 256) != 0) {
    // River surface: the painted reflections stay where the lights are (with the ripple shimmer above) while
    // the fine surface texture (wavelets and sparkles: the plate minus its blur) drifts downstream with the
    // current, faster near the camera. Two copies half a cycle apart, crossfaded with a variance-preserving
    // weight so the texture keeps its contrast mid-blend; a copy that would come from outside the water
    // keeps the texture in place.
    vec4 r8 = regRow(8, rid), r7 = regRow(7, rid);
    if (r8.z > 0.0) {
      float dyR;
      groundXZ(uv, dyR);
      float D = r8.y * clamp(dyR / 200.0, 0.3, 1.5);
      vec2 dUv = vec2(r7.x, r7.y) * D / vec2(3840.0, 2160.0);   // downstream in uv (y up): r7.y is already flipped
      float p1 = r8.x, p2 = fract(p1 + 0.5);
      float w1 = 1.0 - abs(2.0 * p1 - 1.0), w2 = 1.0 - w1;
      vec2 q0 = uv + off;
      vec2 q1 = q0 - dUv * (p1 - 0.5), q2 = q0 - dUv * (p2 - 0.5);
      // how much of each copy comes from the water (feathered: no pops where a copy crosses a railing bar)
      vec3 s1 = texelFetch(tRegion, regTexel(q1), 0).rgb, s2 = texelFetch(tRegion, regTexel(q2), 0).rgb;
      float k1 = int(s1.r * 255.0 + 0.5) == rid ? s1.g : 0.0, k2 = int(s2.r * 255.0 + 0.5) == rid ? s2.g : 0.0;
      vec3 hp0 = col - texture2D(tBlur, q0).rgb;
      vec3 hp1 = mix(hp0, texture2D(tPlate, q1).rgb - texture2D(tBlur, q1).rgb, k1);
      vec3 hp2 = mix(hp0, texture2D(tPlate, q2).rgb - texture2D(tBlur, q2).rgb, k2);
      vec3 hp = (w1 * hp1 + w2 * hp2) / max(sqrt(w1 * w1 + w2 * w2), 0.7);
      col = mix(col, max(col - hp0 + hp, 0.0), rw * r8.z);
    }
  }
  if (rid > 0 && (rflags & 8) != 0) {
    // Flow (clouds, fog, flames, smoke, current): two samples carried along the flow half a cycle apart and
    // crossfaded (flow-map technique), with the phase varying slowly across the region so it never pulses
    // as a whole. A sample that would land outside the region falls back to the unflowed pixel.
    vec4 r2 = regRow(2, rid), r3 = regRow(3, rid);
    float nph = r2.w * fbm(uv * vec2(5.0, 3.0), 5.0);
    float p1 = fract(r2.z + nph), p2 = fract(p1 + 0.5);
    vec4 r6f = regRow(6, rid);
    vec2 wob = vec2(r6f.y * sin(uv.y * 38.0 + r6f.z) + 0.5 * r6f.y * sin(uv.y * 91.0 - 1.7 * r6f.z), 0.0);  // flames lean and sway
    vec2 o1 = r3.xy * (p1 - 0.5) + wob, o2 = r3.xy * (p2 - 0.5) + wob;
    vec2 q1 = uv + off - o1, q2 = uv + off - o2;
    vec3 s1 = int(texelFetch(tRegion, regTexel(q1), 0).r * 255.0 + 0.5) == rid ? texture2D(tPlate, q1).rgb : col;
    vec3 s2 = int(texelFetch(tRegion, regTexel(q2), 0).r * 255.0 + 0.5) == rid ? texture2D(tPlate, q2).rgb : col;
    float w1 = 1.0 - abs(2.0 * p1 - 1.0);
    col = mix(col, w1 * s1 + (1.0 - w1) * s2, rw);
  }
  if (gustMatte > 0.01) {
    // Gust patch on far water: the sub-pixel ripples blur the reflection (water taps only: no shore bleed).
    vec3 acc = col; float wsum = 1.0;
    for (int i = 1; i <= 4; i++) {
      vec2 q = uv + off + vec2(0.0, (float(i) - 2.5) * 12.0 / 2160.0);
      float w = smoothstep(0.35, 0.85, texture2D(tMask, q).g);
      acc += w * texture2D(tPlate, q).rgb; wsum += w;
    }
    col = mix(col, acc / wsum, 0.65 * gustMatte * water);
  }
  // Switchable lights (windows going dark late at night, lanterns guttering). Each pixel knows the four
  // lights that change it most and their shares of the all-lights-off log-ratio (tools/plate_prep.py
  // light_groups: overlapping halos compose multiplicatively). A light's own delta is c*(r^w - 1), dimmed
  // linearly by its level, so a neighbor's darkening never leaks in. Unwarped position, nearest texel.
  ivec2 lp = ivec2(uv * vec2(textureSize(tLightId, 0)));
  ivec3 la = ivec3(texelFetch(tLightId, lp, 0).rgb * 255.0 + 0.5);
  ivec3 l3 = la & 63;
  if (l3.x > 0) {
    int l4 = (la.x >> 6) | ((la.y >> 6) << 2) | ((la.z >> 6) << 4);
    float o1 = 1.0 - uLevel[l3.x];
    float o2 = l3.y > 0 ? 1.0 - uLevel[l3.y] : 0.0;
    float o3 = l3.z > 0 ? 1.0 - uLevel[l3.z] : 0.0;
    float o4 = l4 > 0 ? 1.0 - uLevel[l4] : 0.0;
    if (o1 + o2 + o3 + o4 > 0.001) {
      vec3 lw = texelFetch(tLightW, lp, 0).rgb;
      vec3 c0 = col + 1.0 / 255.0;
      vec3 lr = log((texture2D(tPlateOff, uv + off).rgb + 1.0 / 255.0) / c0);
      vec3 d = o1 * (exp(lw.x * lr) - 1.0) + o2 * (exp(lw.y * lr) - 1.0) + o3 * (exp(lw.z * lr) - 1.0)
             + o4 * (exp(max(1.0 - lw.x - lw.y - lw.z, 0.0) * lr) - 1.0);
      col = max(c0 * (1.0 + d) - 1.0 / 255.0, 0.0);
    }
  }

  // Lantern / window flicker (warm only where the lights mask is set). G = outdoors (weather region).
  vec4 lt = texture2D(tLights, uv);
  float L = lt.r, outdoor = smoothstep(0.0, 0.5, lt.g);
  float flick = sin(TAU * phase * 23.0 + 1.0) * 0.5 + sin(TAU * phase * 37.0 + 2.0) * 0.3 + sin(TAU * phase * 61.0) * 0.2;
  col *= 1.0 + L * flickerAmt * flick;

  // Region light: brightness level (fire and candle flicker, neon buzz, gutters), twinkling bright points
  // (string lights, stars, far city lights; each bulb on its own integer-cycle phase), and the flicker's
  // light thrown on the surroundings.
  if (rid > 0) {
    if ((rflags & 16) != 0) col *= mix(1.0, regRow(1, rid).w, rw);
    if ((rflags & 32) != 0) {
      vec4 r4 = regRow(4, rid);
      vec2 cell = floor(uv * vec2(r4.y, r4.y * 0.5625));
      float h = h21(cell + 0.37);
      float tw = sin(TAU * r4.z * floor(1.0 + h * 3.0) + h * 40.0);
      float lv = dot(col, vec3(0.2126, 0.7152, 0.0722));
      col *= 1.0 + r4.x * rw * smoothstep(r4.w, r4.w + 0.15, lv) * tw;
    }
  }
  // A light's reflection on the wet ground dims and brightens with the light (a neon dip, a lantern guttering).
  if (uRegions > 0.5) {
    vec2 rf = texelFetch(tRefl, ivec2(clamp(uv, 0.0, 0.9999) * vec2(textureSize(tRefl, 0))), 0).rg;
    int lid = int(rf.r * 255.0 + 0.5);
    if (lid > 0 && rf.g > 0.004 && (int(regRow(0, lid).x + 0.5) & 16) != 0) col *= mix(1.0, regRow(1, lid).w, rf.g);
  }
  for (int i = 0; i < 8; i++) {
    if (i >= uSpillN) break;
    vec4 s = uSpill[i];
    vec2 d = (uv - s.xy) * vec2(1.7778, 1.0);
    col *= 1.0 + s.w * exp(-dot(d, d) / (2.0 * s.z * s.z));
  }

  // Waterfalls: streaks of falling water. Brightness noise, stretched along the fall and scrolled down it
  // (integer periods per loop: seamless), modulates the painted water; the streaks lengthen and speed up
  // as the water accelerates down the fall (coordinate s ~ log(1 + 1.5 progress)).
  vec3 fw = texture2D(tFlow, uv).rgb;
  if (fw.r > 0.004) {
    float h = max(fw.b * 0.25, 0.01);
    float s = h * log(1.0 + 1.5 * fw.g) / 1.5;
    vec2 q = vec2(s * 110.0 - phase * 336.0, uv.x * 600.0);   // along (periodic: 24 cells, 14 periods/loop), across
    float n = 0.62 * vnoise(q, 24.0) + 0.38 * vnoise(q * 2.0 + vec2(0.0, 17.0), 48.0);
    float env = smoothstep(0.0, 0.08, fw.g) * (1.0 - 0.4 * smoothstep(0.75, 1.0, fw.g));
    col *= 1.0 + flowAmt * fw.r * env * (n - 0.5) * 2.0;
  }

  // Rain rings on the water.
  if (water > 0.01) {
    vec2 g = vec2(uv.x * 160.0, uv.y * 70.0);
    vec2 cell = floor(g), f = fract(g) - 0.5;
    float h = h21(cell), h2 = h21(cell + 4.3);
    float k = fract(h * 7.0 + phase * floor(30.0 + h2 * 30.0));
    vec2 o = vec2(h21(cell + 1.7), h21(cell + 2.9)) - 0.5;
    float r = length((f - o * 0.4) * vec2(1.0, 2.2));
    float ring = smoothstep(0.035, 0.0, abs(r - k * 0.42)) * (1.0 - k) * step(0.55, h2);
    col += water * ring * ringAmt.x * rainK * vec3(0.7, 0.75, 0.9);
    col *= 1.0 + water * ring * ringAmt.y * rainK;
  }
  // Ground rain: ring crests brighten what the wet ground reflects; splash specks catch the light around them.
  if (gr.z + gr.w > 0.0) {
    float lumG = dot(col, vec3(0.2126, 0.7152, 0.0722));
    col *= 1.0 + gRing.y * gr.z;
    col += 0.015 * gRing.y * gr.z * vec3(0.7, 0.75, 0.9);
    col += min(gr.w, 1.0) * (0.9 * col + vec3(0.05, 0.055, 0.07) + 0.6 * lumG);
  }
  // River glints riding the ripples: bright where the water reflects light.
  if (riverGlint > 0.0) col += riverGlint * (dot(col, vec3(0.2126, 0.7152, 0.0722)) * 1.6 + 0.02) * vec3(1.0, 0.97, 0.92);

  // Drifting mist over far terrain (disparity small) and lightly over the sky; thicker in heavy rain.
  float far = (1.0 - smoothstep(0.02, 0.12, d)) * (1.0 - leaf) * outdoor;
  float mist = fbm(vec2(uv.x * 6.0 + phase * 6.0, uv.y * 4.0 + 0.3 * sin(TAU * phase)), 6.0);
  col = mix(col, mistCol, clamp(far * mistAmt * (0.7 + 0.3 * rainK) * smoothstep(0.35, 0.85, mist), 0.0, 1.0));

  // Lightning (timeline event): clouds light up around the strike, the valley and mist catch it, and a
  // cool glow reaches into the porch through the opening (strongest near it). Multiplicative on the
  // plate (lit surfaces brighten, black stays black) plus a little additive scatter in the air.
  if (flash > 0.0) {
    vec2 dd = (uv - flashUv) * vec2(1.7778, 1.0);
    float local = exp(-dot(dd, dd) / (2.0 * 0.2 * 0.2));
    float land = (1.0 - smoothstep(0.02, 0.14, d)) * outdoor * (1.0 - sky);
    float inL = texture2D(tFlash, uv).r * (1.0 - outdoor);
    vec3 tint = flashCol / dot(flashCol, vec3(0.2126, 0.7152, 0.0722));
    float k = sky * flashAmt.x * (0.35 + 0.65 * local) + land * flashAmt.y * (0.5 + 0.5 * local)
            + inL * flashAmt.z + (1.0 - outdoor) * flashAmt.w;
    col *= 1.0 + flash * k * tint;
    col += flash * flashCol * (sky * (0.02 + 0.06 * local) + far * 0.025 + water * 0.02);
  }

  // Distant lightning (timeline 'farflash'): the cloud bank behind the mountains glows from inside in a
  // wide, low patch around the flash. The peaks stay dark against it (backlit silhouettes), the far mist
  // catches a little, the river shows a faint reflection below it, and no light reaches the porch.
  if (farFlash > 0.0) {
    vec2 fd = (uv - farUv) * vec2(1.7778 / 2.4, 1.0);
    float fl = exp(-dot(fd, fd) / (2.0 * 0.08 * 0.08));
    vec3 ftint = farCol / dot(farCol, vec3(0.2126, 0.7152, 0.0722));
    float rx = (uv.x - farUv.x) * 1.7778;
    float refl = water * exp(-rx * rx / (2.0 * 0.06 * 0.06)) * 0.35;
    float k = sky * 1.8 * fl + far * (1.0 - sky) * 0.18 * fl + refl;
    col *= 1.0 + farFlash * k * ftint;
    col += farFlash * farCol * sky * fl * 0.025;
  }

  gl_FragColor = vec4(col * (1.0 - black), 1.0);
  if (dbgMode == 1) gl_FragColor = vec4(water, sky, leaf, 1.0);
  else if (dbgMode == 2) gl_FragColor = vec4(abs(off) * 300.0, float(rid) / 32.0, 1.0);
  else if (dbgMode == 3) gl_FragColor = vec4(texture2D(tPlate, uv).rgb, 1.0);
  else if (dbgMode == 4) gl_FragColor = vec4(0.0, 0.0, 0.0, 1.0);
}`;

export const plateVert = /* glsl */ `
varying vec2 vUv;
void main() { vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;

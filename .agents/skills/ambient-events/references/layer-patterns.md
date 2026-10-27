# Patterns for event layers

How the existing layers draw events over the plate. Copy from `src/library/boat.js` (rare event, ray-marched model on the water) and `src/library/leaves.js` (many small instanced sprites). All sizes are 3840×2160 plate px; output is premultiplied color composited "over" the plate.

## Layer skeleton

```js
import * as THREE from 'three';
import { flashAt } from './timeline.js';

export async function myEventLayer(ctx, opts) {
  const evs = (ctx.timeline?.events ?? []).filter((e) => e.type === 'myevent');
  if (!evs.length) return null;                       // no events (or events=off): no cost
  const dir = `/out/plates/${opts.plate}`;            // lights.png (G outdoors, B glow), masks.png (G water), env.png, plate.json
  const mat = new THREE.ShaderMaterial({
    vertexShader: vert, fragmentShader: frag, transparent: true, depthTest: false, depthWrite: false, toneMapped: false,
    blending: THREE.CustomBlending, blendEquation: THREE.AddEquation, blendSrc: THREE.OneFactor,
    blendDst: opts.debug ? THREE.OneFactor : THREE.OneMinusSrcAlphaFactor,   // debug: additive coverage for rain_qa --leak
    blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneMinusSrcAlphaFactor,
    uniforms: { /* textures, uBox, uRes, pose, uFlash, uDebug */ },
  });
  const mesh = new THREE.Mesh(new THREE.PlaneGeometry(2, 2), mat);
  mesh.frustumCulled = false;   // never let three compute bounds lazily (start-frame dependence)
  mesh.renderOrder = 5;         // plate 0, boat 5, rain 10-11, leaves 20
  mesh.visible = false;
  ctx.add(mesh);
  ctx.animate((t) => {          // t = frame / fps, absolute
    const ev = evs.find((e) => t >= e.t && t <= e.t + e.dur);
    mesh.visible = !!ev;
    if (!ev) return;
    const u = (t - ev.t) / ev.dur;               // pose = pure function of (event, t); no state between frames
    // ... set uniforms from u and the event's stored parameters (seeded in the timeline)
    mat.uniforms.uFlash.value = opts.debug ? 0 : flashAt(ctx.timeline, t).flash;
  });
  return mesh;
}
```

Instanced sprites (leaves): a fixed pool (`MAX = 24`) of `InstancedBufferGeometry` quads with `DynamicDrawUsage` attributes rewritten each frame; unused slots collapse to zero size in the vertex shader. Screen-space quads with y down flip the winding: set `side: THREE.DoubleSide`.

## Screen-box quad

Draw only where the event is: the quad covers a box in 4K px (computed each frame from the projected model, its reflection, wake and glow), so cost is near zero (the boat added nothing measurable at 101 fps).

```glsl
uniform vec4 uBox;     // x0, y0, x1, y1 in 4K px (y down)
uniform vec2 uRes;     // 3840, 2160
varying vec2 vPx;      // 4K px coordinates at any render size
void main() {
  vec2 p = position.xy * 0.5 + 0.5;
  vPx = mix(uBox.xy, uBox.zw, vec2(p.x, 1.0 - p.y));
  gl_Position = vec4(vPx.x / uRes.x * 2.0 - 1.0, 1.0 - vPx.y / uRes.y * 2.0, 0.0, 1.0);
}
```

Pad the box by a few px and clamp it to the frame.

## Anti-aliasing without shimmer

- **Sub-samples:** the boat evaluates 4 rotated-grid sub-pixel rays per pixel and averages them, so voxel edges never crawl as it moves:
  ```glsl
  for (int i = 0; i < 4; i++) {
    vec2 o = vec2(i == 0 || i == 3 ? 0.125 : -0.125, i < 2 ? 0.375 : -0.375);
    if (i == 1 || i == 3) o = o.yx;
    acc += shadeAt(px + o);
  }
  acc *= 0.25;
  ```
- **Pixel art:** leaves sample texel centers and blend only within one screen pixel of a texel seam (`fw` = texels per screen pixel), so the 9×9 shapes stay crisp without aliasing.
- **Motion blur:** compute the state at shutter open and close (`t ∓ shutter/2`, shutter 1/110 s) and integrate 4 samples between them in the fragment shader (leaves); streaks get their length from speed × shutter (rain).

## Occlusion and placement

- **Outdoors:** multiply by `lights.png` G (`texture2D(tLights, uv).g`) and discard below ~0.004. Porch geometry, the pet, posts and railing then hide the event, exactly as they hide rain.
- **Water only:** reflections, wakes, rings and glitter are multiplied by `masks.png` G.
- **Depth:** `depth8.png` stores sqrt(disparity). It is too coarse to hide something behind foliage edges; end paths in mist (haze) or behind solid foreground (outdoors mask 0) instead.
- **Never pop:** fade in and out where the event is hidden (the boat fades over the first 30 m out of the mist and only after it is fully behind the railing).

## Haze is airlight, not transparency

Distance haze must add the air's light in front of an opaque object. Making the object transparent with distance lets bright things behind it (lantern reflections on the water) show through it. The boat fix (2026-10-15):

```glsl
uniform sampler2D tPlate;    // loaded with mipmaps (generateMipmaps + LinearMipmapLinearFilter)
uniform float uAirLod;       // mip level: blur ~ 2/3 of the boat's length
vec3 gAir = textureLod(tPlate, uv, uAirLod).rgb;   // the surroundings, blurred: the haze color here
...
return vec4(mix(col, gAir, hz), 1.0);              // opaque hull, hazed toward the airlight
```

```js
m.uAirLod.value = Math.min(Math.max(Math.log2(ppm * 3), 3), 7);
const u = Math.min(Math.max((depth - 95) / (260 - 95), 0), 1);   // hull haze over 95-260 m camera depth
m.uHaze.value = u * u * (3 - 2 * u);
```

The lantern's own light hazes separately (linear 110–230 m, up to 0.8), so the boat first appears as a glow in the mist.

## Light it like the plate

- Ambient: `plate.json` `env_linear` (`sky`, `outdoor`) and the local `env.png` (outdoor-only environment, sRGB, 1/8 res).
- Warm practicals: `lights.png` B is a wide glow around light sources; use it for warm spill and glints.
- Lightning: `flashAt(ctx.timeline, t).flash` (≈ 1 at a strong stroke); brighten by a small factor (leaves × (1 + 0.6 flash), rain radiance × (1 + 2.5 flash)).
- Self-light (a lantern on the event): a small soft halo sized in meters × px-per-meter, never a hard sprite.

## Things on the water: the lake camera

```js
import { lakeCamera, makePath, boatPose } from './boat.js';
const cam = lakeCamera({ focalPx: 2700, horizon: 0.453, height: 16, W: 3840, H: 2160 });   // calibrated per plate
const path = makePath(cam, route.path);          // screen points on the water -> water plane, Catmull-Rom, arc length
const p = boatPose(path, ev, t, route.fade);     // { x, z, fx, fz, speed, vis, u, s }
const [sx, sy, depth] = cam.project([p.x, 0, p.z]);
const pxPerM = cam.pxPerM(depth);                // size, speed and wake follow from the camera
```

`cam.toWater(x, y)` back-projects a normalized screen point onto the water plane. Use the same camera for anything that moves on or above the water, so size, heading, foreshortening and on-screen speed agree with the plate and with each other. Calibrate `horizon`/`height` with the plate-scene skill's `lake_camera.mjs fit`.

## Sound sync data

If the audio needs per-time data that only the renderer can compute (distance, pan, speed), compute it in `writeTimeline` (`src/cli.mjs`) with the renderer's own functions and store it on the event, as `boatProfile` does for boats. Then picture and sound can't drift apart.

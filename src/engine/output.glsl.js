// Final output pass: display-referred sRGB in -> grade -> vignette -> TPDF dither -> 8-bit.
// mode 0: BT.709 limited-range yuv420p packed into an RGBA8 target (W/4 x 1.5H) so one readback yields
//         the exact byte stream ffmpeg expects. mode 1: RGBA8 (W x H), rows top-down.
export const outputFrag = /* glsl */ `
precision highp float;
precision highp int;
uniform sampler2D src;
uniform vec2 size;
uniform int mode;
uniform int ssaa;
uniform float vignette;
uniform vec3 lift;
uniform vec3 gamma;
uniform vec3 gain;
uniform float saturation;
uniform float contrast;
uniform float pixel;        // pixel-art scenes: cell size in output px (0 = off); every output pixel shows its cell's center
uniform vec2 pixelOrigin;   // grid origin (px), so cells line up with the plate's own pixels (plate_prep pixelize)
out vec4 outColor;

float hash(vec3 p) {
  p = fract(p * vec3(0.1031, 0.1030, 0.0973));
  p += dot(p, p.yxz + 33.33);
  return fract((p.x + p.y) * p.z);
}
float tpdf(vec3 seed) { return hash(seed) + hash(seed + vec3(17.0, 31.0, 7.0)) - 1.0; }

vec3 grade(vec3 c, vec2 uv) {
  c = clamp(c, 0.0, 1.0);
  c = pow(c, 1.0 / gamma);
  c = c * gain + lift * (1.0 - c);
  c = mix(vec3(0.5), c, contrast);
  float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
  c = mix(vec3(l), c, saturation);
  vec2 v = uv - 0.5;
  v.x *= size.x / size.y;
  c *= mix(1.0, smoothstep(1.3, 0.2, length(v)), vignette);
  return clamp(c, 0.0, 1.0);
}

// Pixel (x, y) with y counted from the top of the image; box-filters ssaa x ssaa internal samples.
vec3 px(int x, int y) {
  if (pixel > 1.0) {
    // cell edges at round(origin + k * cell) (same as the plate rebuild); sample the cell's center
    float fx = floor((float(x) + 0.5 - pixelOrigin.x) / pixel), fy = floor((float(y) + 0.5 - pixelOrigin.y) / pixel);
    x = clamp(int(floor(pixelOrigin.x + (fx + 0.5) * pixel)), 0, int(size.x) - 1);
    y = clamp(int(floor(pixelOrigin.y + (fy + 0.5) * pixel)), 0, int(size.y) - 1);
  }
  ivec2 s = ivec2(size) * ssaa;
  vec3 c = vec3(0.0);
  for (int j = 0; j < ssaa; j++) for (int i = 0; i < ssaa; i++)
    c += clamp(texelFetch(src, ivec2(x * ssaa + i, s.y - 1 - (y * ssaa + j)), 0).rgb, 0.0, 1.0);
  c /= float(ssaa * ssaa);
  return grade(c, (vec2(x, y) + 0.5) / size);
}
float q(float v, vec3 seed) { return clamp(floor(v + tpdf(seed) + 0.5), 0.0, 255.0) / 255.0; }

void main() {
  ivec2 o = ivec2(gl_FragCoord.xy);
  int W = int(size.x), H = int(size.y);
  if (mode == 1) {
    vec3 c = px(o.x, o.y) * 255.0;
    outColor = vec4(q(c.r, vec3(o, 11.0)), q(c.g, vec3(o, 12.0)), q(c.b, vec3(o, 13.0)), 1.0);
    return;
  }
  vec4 res;
  if (o.y < H) {
    for (int k = 0; k < 4; k++) {
      int x = o.x * 4 + k;
      float y = 16.0 + 219.0 * dot(px(x, o.y), vec3(0.2126, 0.7152, 0.0722));
      res[k] = q(y, vec3(x, o.y, 1.0));
    }
  } else {
    int r = o.y - H;
    bool isV = r >= H / 4;
    if (isV) r -= H / 4;
    for (int k = 0; k < 4; k++) {
      int b = o.x * 4 + k;
      int cr = 2 * r + (b >= W / 2 ? 1 : 0);
      int cc = b % (W / 2);
      vec3 c = 0.25 * (px(2 * cc, 2 * cr) + px(2 * cc + 1, 2 * cr) + px(2 * cc, 2 * cr + 1) + px(2 * cc + 1, 2 * cr + 1));
      float yl = dot(c, vec3(0.2126, 0.7152, 0.0722));
      float v = isV ? 128.0 + 224.0 * (c.r - yl) / 1.5748 : 128.0 + 224.0 * (c.b - yl) / 1.8556;
      res[k] = q(v, vec3(cc, cr, isV ? 3.0 : 2.0));
    }
  }
  outColor = res;
}`;

"""Procedural dense leaf-block textures (opaque maple leaves layered, a few cutout holes). Usage: python tools/gen_leaves.py"""
import pathlib, numpy as np
from PIL import Image, ImageDraw, ImageFilter
from cozy.images import normal_map
rng = np.random.default_rng(42)
def maple(size):
    """Return an alpha mask of a maple leaf (5 lobes) in a size x size image."""
    S = size*4; im = Image.new('L', (S,S), 0); d = ImageDraw.Draw(im)
    cx, cy = S/2, S*0.56
    pts = []
    for i in range(200):
        a = i/200*2*np.pi
        lobe = abs(np.cos(a*5/2))**0.55
        low = 1 - 0.35*max(0, -np.cos(a))
        r = (0.34 + 0.56*lobe)*low*S*0.48 - (0.04*S*abs(np.sin(a*18)))
        pts.append((cx + np.sin(a)*r, cy - np.cos(a)*r))
    d.polygon(pts, fill=255); d.line([(cx,cy),(cx,cy+S*0.4)], fill=255, width=max(2,S//40))
    return im.resize((size,size), Image.LANCZOS)
def leaf_block(out, palette, base, size=512, n=420, lsize=(70,140), bg_dark=0.32, seed=0):
    r = np.random.default_rng(seed)
    W = size
    canvas = Image.new('RGBA', (W, W), (0,0,0,0))
    # Base: dark leafy mass so the block reads solid with some holes.
    shapes = [maple(s) for s in (64, 96, 128, 160)]
    for k in range(n):
        s = shapes[r.integers(0, len(shapes))]
        sc = r.uniform(lsize[0], lsize[1]) / s.width
        m = s.resize((max(8,int(s.width*sc)),)*2, Image.LANCZOS).rotate(r.uniform(0,360), resample=Image.BICUBIC, expand=True)
        c = np.array(palette[r.integers(0, len(palette))], np.float32)
        depth = k / n  # later leaves on top -> brighter
        shade = (0.45 + 0.7*depth) * r.uniform(0.85, 1.12)
        col = np.clip(c*shade, 0, 255).astype(np.uint8)
        # Simple vein + edge darkening inside the leaf.
        a = np.asarray(m, np.float32)/255
        rgb = np.ones((m.height, m.width, 3), np.float32) * col
        er = np.asarray(m.filter(ImageFilter.MinFilter(5)), np.float32)/255
        rgb *= (0.78 + 0.22*er)[...,None]
        tile = Image.fromarray(np.dstack([rgb, a*255]).astype(np.uint8), 'RGBA')
        x, y = r.integers(-tile.width//2, W - tile.width//2), r.integers(-tile.height//2, W - tile.height//2)
        for ox in (-W, 0, W):
            for oy in (-W, 0, W):
                canvas.alpha_composite(tile, (int(x+ox), int(y+oy))) if -tile.width < x+ox < W and -tile.height < y+oy < W else None
    a = np.asarray(canvas, np.float32)
    # Fill holes partly with a dark interior color (keeps a few true holes for the cutout look).
    alpha = a[...,3:]/255
    dark = np.array(base, np.float32)
    rgb = a[...,:3]*alpha + dark*(1-alpha)
    hole = (alpha[...,0] < 0.5) & (np.asarray(Image.fromarray((alpha[...,0]*255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(10)), np.float32)/255 < 0.55)
    out_a = np.where(hole, 0, 255)
    Image.fromarray(np.dstack([rgb, out_a]).astype(np.uint8), 'RGBA').save(out)
AUT = [(214,78,24),(236,128,32),(246,178,48),(190,48,22),(226,104,30),(250,200,70),(170,40,24)]
FAR = [(160,52,40),(140,44,46),(180,70,44),(120,40,44)]
GRN = [(70,120,50),(90,140,60),(60,100,44),(110,160,70)]


def main():
    d = pathlib.Path('assets/textures')
    leaf_block(d/'leaves_autumn.png', AUT, (70,22,10), seed=1)
    leaf_block(d/'leaves_autumn_far.png', FAR, (50,18,20), size=256, n=200, lsize=(40,80), seed=2)
    leaf_block(d/'leaves_green.png', GRN, (24,40,18), seed=3)
    for k in ('leaves_autumn','leaves_autumn_far','leaves_green'):
        normal_map(Image.open(d/f'{k}.png').convert('RGB')).save(d/f'{k}_n.png')
    print('ok')


# importing it (the tools tests do) must not rewrite assets/textures
if __name__ == "__main__":
    main()
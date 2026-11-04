"""Camera-projection compositing for scene-forge ("projected clean plate").

When the reference's walls can't be matched by any real room shape (inconsistent perspective in
composited / AI-assisted renders), keep the room as invisible SHADOW CATCHERS in Blender, render
only the 3D furniture (film transparent: furniture + its shadows in alpha), and lay it over a clean
plate of the reference (furniture removed by Nano Banana). From this camera the walls, doors, built-ins
and background match the reference exactly; furniture stays real 3D, lit, casting real shadows.

usage:
  python3 plate_composite.py align <reference.png> <plate.png> <out_plate_aligned.png>
      resize the plate to the reference size and report how well static regions line up
  python3 plate_composite.py comp <plate_aligned.png> <render_rgba.png> <out.png> [--shadow 1.0]
      straight-alpha "over": out = render.rgb * a + plate * (1 - a)
"""
import sys
import numpy as np
from PIL import Image


def align(ref_p, plate_p, out_p):
    ref = Image.open(ref_p).convert("RGB")
    plate = Image.open(plate_p).convert("RGB").resize(ref.size, Image.LANCZOS)
    plate.save(out_p)
    a = np.asarray(ref, float).mean(2); b = np.asarray(plate, float).mean(2)
    # static check: top band (ceiling/crown) + left wardrobe + right door strip
    H, W = a.shape
    regions = {"ceiling": (slice(0, int(H * .18)), slice(0, W)),
               "left wall": (slice(int(H * .25), int(H * .75)), slice(0, int(W * .2))),
               "right wall": (slice(int(H * .25), int(H * .75)), slice(int(W * .87), W))}
    for k, (ys, xs) in regions.items():
        d = np.abs(a[ys, xs] - b[ys, xs]).mean()
        # best integer shift within ±6 px (detects a slight crop/zoom in the edit)
        best = min(((np.abs(a[ys, xs] - np.roll(np.roll(b, dy, 0), dx, 1)[ys, xs]).mean(), dx, dy)
                    for dx in range(-6, 7, 2) for dy in range(-6, 7, 2)))
        print(f"{k:10s} mean diff {d:5.1f}  best shift dx={best[1]:+d} dy={best[2]:+d} (diff {best[0]:.1f})")


def comp(plate_p, render_p, out_p, shadow=1.0):
    plate = np.asarray(Image.open(plate_p).convert("RGB"), float) / 255
    r = Image.open(render_p).convert("RGBA").resize((plate.shape[1], plate.shape[0]), Image.LANCZOS)
    r = np.asarray(r, float) / 255
    a = np.clip(r[..., 3:4] * shadow, 0, 1)
    out = r[..., :3] * a + plate * (1 - a)
    Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(out_p)
    print("composited", out_p)


def comp2(plate_p, furn_p, shad_p, out_p, shadow=0.7):
    """Two-pass: furn = furniture with the room as HOLDOUT (solid alpha = objects only);
    shad = same view with the room as SHADOW CATCHERS (alpha = objects + their shadows).
    Shadow strength scales only the shadow, never the furniture."""
    plate = np.asarray(Image.open(plate_p).convert("RGB"), float) / 255
    size = (plate.shape[1], plate.shape[0])
    f = np.asarray(Image.open(furn_p).convert("RGBA").resize(size, Image.LANCZOS), float) / 255
    s = np.asarray(Image.open(shad_p).convert("RGBA").resize(size, Image.LANCZOS), float) / 255
    fa = f[..., 3:4]
    sh = np.clip(s[..., 3:4] - fa, 0, 1) * shadow           # shadow-only coverage
    under = plate * (1 - sh) + s[..., :3] * sh               # darken the plate where shadows fall
    out = f[..., :3] * fa + under * (1 - fa)
    Image.fromarray((np.clip(out, 0, 1) * 255).astype(np.uint8)).save(out_p)
    print("composited", out_p)


if __name__ == "__main__":
    if sys.argv[1] == "align":
        align(*sys.argv[2:5])
    elif sys.argv[1] == "comp2":
        comp2(*sys.argv[2:6], shadow=float(sys.argv[sys.argv.index("--shadow") + 1]) if "--shadow" in sys.argv else 0.7)
    elif sys.argv[1] == "comp":
        comp(sys.argv[2], sys.argv[3], sys.argv[4], float(sys.argv[sys.argv.index("--shadow") + 1]) if "--shadow" in sys.argv else 1.0)
    else:
        sys.exit(__doc__)

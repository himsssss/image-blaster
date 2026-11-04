"""Split a Nano Banana turnaround sheet (grid of views) into separate view images.

usage: python3 split_sheet.py <sheet.png> <forge_dir> <object> [--grid 2x2] [--views front,right34,right,back]

Cells are read left->right, top->bottom and named <object>-<view>.png in objects/<object>/views/.
Each whole cell (minus the gutter margin) is padded to a square and saved at 1024 px, so all views keep
the sheet's shared scale (better for Meshy than per-view tight crops).
Prints one line per view with the object's fill ratio; a cell that is empty or touches its cell edge
(object cropped by the grid) is reported as BAD so the caller can regenerate it as a single view.
"""
import argparse
from pathlib import Path
import numpy as np
from PIL import Image

ap = argparse.ArgumentParser()
ap.add_argument("sheet"); ap.add_argument("forge"); ap.add_argument("object")
ap.add_argument("--grid", default="2x2")
ap.add_argument("--views", default="front,right34,right,back")
a = ap.parse_args()

cols, rows = (int(v) for v in a.grid.lower().split("x"))
views = a.views.split(",")
assert len(views) <= cols * rows, "more view names than grid cells"
im = Image.open(a.sheet).convert("RGB")
W, H = im.size
out = Path(a.forge) / "objects" / a.object / "views"
out.mkdir(parents=True, exist_ok=True)

for i, view in enumerate(views):
    c, r = i % cols, i // cols
    cell = im.crop((c * W // cols, r * H // rows, (c + 1) * W // cols, (r + 1) * H // rows))
    arr = np.asarray(cell, dtype=np.int16)
    # gutters/background are near-white; the object is anything clearly darker or coloured
    mask = (arr.min(axis=2) < 235) | (arr.max(axis=2) - arr.min(axis=2) > 18)
    m = 6  # ignore a thin margin where gutters / anti-aliasing live
    mask[:m, :] = mask[-m:, :] = False; mask[:, :m] = mask[:, -m:] = False
    ys, xs = np.nonzero(mask)
    if len(xs) < 500:
        print(f"{view}: BAD empty cell"); continue
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    touches = x0 <= m + 2 or y0 <= m + 2 or x1 >= cell.width - m - 3 or y1 >= cell.height - m - 3
    # keep the whole cell (minus gutter margin) so every view keeps the sheet's shared scale
    inner = cell.crop((m, m, cell.width - m, cell.height - m))
    side = max(inner.size)
    sq = Image.new("RGB", (side, side), (255, 255, 255))
    sq.paste(inner, ((side - inner.width) // 2, (side - inner.height) // 2))
    sq.resize((1024, 1024), Image.LANCZOS).save(out / f"{a.object}-{view}.png")
    fill = (x1 - x0) * (y1 - y0) / (cell.width * cell.height)
    print(f"{view}: {'BAD touches cell edge' if touches else 'ok'} fill={fill:.2f} -> {a.object}-{view}.png")

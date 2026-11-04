"""Shape/colour QC sheet: one row per object -> reference crop | Nano Banana front | Meshy preview |
placed render crop. Look at it ONCE after views and again after Meshy, before placing anything.

usage: python3 qc_sheet.py <forge_dir> [--render loop/iterNN.png] [--objects a,b,c] [--out qc-sheet.jpg]

Each row is labelled with the object's "structure" notes from analysis.json so you can tick them off:
leg count/shape, base construction, seams, arms, cushions, arrangement. Any mismatch -> regenerate
that stage (views or Meshy) before it reaches the scene; placement can't fix a wrong shape.
"""
import argparse, json
from pathlib import Path
from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("forge"); ap.add_argument("--render"); ap.add_argument("--objects")
ap.add_argument("--out", default="qc-sheet.jpg")
a = ap.parse_args()
F = Path(a.forge)
an = json.loads((F / "analysis.json").read_text())
ref = Image.open(F / an["reference"]).convert("RGB")
ren = Image.open(F / a.render).convert("RGB").resize(ref.size) if a.render else None
want = set(a.objects.split(",")) if a.objects else None
S = 240
rows = []
for o in an["objects"]:
    if o.get("source") != "meshy" or (want and o["name"] not in want):
        continue
    n, d = o["name"], F / "objects" / o["name"]
    x0, y0, x1, y1 = o["bbox"]; pad = int(0.1 * max(x1 - x0, y1 - y0))
    box = (max(0, x0 - pad), max(0, y0 - pad), min(ref.width, x1 + pad), min(ref.height, y1 + pad))
    cells = [("reference", ref.crop(box))]
    for label, path in (("nano front", d / "views" / f"{n}-front.png"), ("meshy", d / f"1-{n}-thumb.png")):
        cells.append((label, Image.open(path).convert("RGB") if path.exists() else None))
    if ren:
        cells.append(("placed", ren.crop(box)))
    row = Image.new("RGB", (len(cells) * (S + 6) + 300, S + 22), "white")
    dr = ImageDraw.Draw(row)
    for i, (label, im) in enumerate(cells):
        if im is not None:
            im = im.copy(); im.thumbnail((S, S)); row.paste(im, (i * (S + 6) + (S - im.width) // 2, 20 + (S - im.height) // 2))
        else:
            dr.rectangle([i * (S + 6), 20, i * (S + 6) + S, 20 + S], outline=(200, 0, 0)); dr.text((i * (S + 6) + 8, 30), "missing", fill=(200, 0, 0))
        dr.text((i * (S + 6) + 4, 4), label, fill=(0, 0, 0))
    notes = o.get("structure") or "NO structure notes - add them to analysis.json"
    tx = len(cells) * (S + 6) + 6
    dr.text((tx, 4), n, fill=(0, 0, 0))
    for j, line in enumerate([notes[i:i + 44] for i in range(0, len(notes), 44)][:12]):
        dr.text((tx, 22 + j * 14), line, fill=(60, 60, 60) if o.get("structure") else (200, 0, 0))
    rows.append(row)
if not rows:
    raise SystemExit("no objects")
W = max(r.width for r in rows)
sheet = Image.new("RGB", (W, sum(r.height + 8 for r in rows)), "white")
y = 0
for r in rows:
    sheet.paste(r, (0, y)); y += r.height + 8
sheet.save(F / a.out, quality=85)
print(F / a.out)

"""Crop every object listed in forge/analysis.json out of the reference image.

usage: python3 crop.py <forge_dir>
Writes <forge_dir>/objects/<name>/0-crop.png (padded, square canvas, white fill).
"""
import json, sys
from pathlib import Path
from PIL import Image

forge = Path(sys.argv[1])
a = json.loads((forge / "analysis.json").read_text())
ref = Image.open(forge / a["reference"]).convert("RGB")
W, H = ref.size
for o in a["objects"]:
    if o.get("source") != "meshy":
        continue
    x0, y0, x1, y1 = o["bbox"]
    pad = int(0.08 * max(x1 - x0, y1 - y0))
    box = (max(0, x0 - pad), max(0, y0 - pad), min(W, x1 + pad), min(H, y1 + pad))
    crop = ref.crop(box)
    side = max(crop.size)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(crop, ((side - crop.width) // 2, (side - crop.height) // 2))
    canvas = canvas.resize((1024, 1024), Image.LANCZOS)
    out = forge / "objects" / o["name"]
    out.mkdir(parents=True, exist_ok=True)
    canvas.save(out / "0-crop.png")
    print(o["name"], box)

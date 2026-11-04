"""Verifier for the scene-forge loop: score a render against the reference.

usage: python3 compare.py <reference.png> <render.png> <out_dir> [--tag iterN] [--boxes analysis.json]

Prints JSON with:
  ssim      structural similarity on a 420px grayscale copy (layout / camera match)
  edge_iou  overlap of Canny-like edge maps (geometry alignment)
  color_de  mean colour distance in Lab (materials + white balance)
  luma      mean brightness of ref vs render (exposure)
  regions   per-object colour/brightness deltas when --boxes is given
Writes <out_dir>/<tag>-compare.jpg: reference | render | 50% blend with edge overlay.
"""
import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

ap = argparse.ArgumentParser()
ap.add_argument("ref"); ap.add_argument("render"); ap.add_argument("out")
ap.add_argument("--tag", default="iter"); ap.add_argument("--boxes")
a = ap.parse_args()

ref = Image.open(a.ref).convert("RGB")
ren = Image.open(a.render).convert("RGB").resize(ref.size, Image.LANCZOS)
W = 420; H = round(ref.height * W / ref.width)


def gray(im):
    return np.asarray(im.resize((W, H), Image.LANCZOS).convert("L"), dtype=np.float64)


def ssim(x, y):
    from numpy.lib.stride_tricks import sliding_window_view as sw
    k = 7; C1, C2 = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    X, Y = sw(x, (k, k)), sw(y, (k, k))
    mx, my = X.mean((-1, -2)), Y.mean((-1, -2))
    vx, vy = X.var((-1, -2)), Y.var((-1, -2))
    cxy = (X * Y).mean((-1, -2)) - mx * my
    return float((((2 * mx * my + C1) * (2 * cxy + C2)) / ((mx**2 + my**2 + C1) * (vx + vy + C2))).mean())


def edges(im):
    e = np.asarray(im.resize((W, H)).convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float64)
    return e > np.percentile(e, 88)


def lab(im):
    rgb = np.asarray(im, dtype=np.float64) / 255
    rgb = np.where(rgb > 0.04045, ((rgb + 0.055) / 1.055) ** 2.4, rgb / 12.92)
    xyz = rgb @ np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]]).T
    xyz /= [0.95047, 1.0, 1.08883]
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


gr, gn = gray(ref), gray(ren)
er, en = edges(ref), edges(ren)
# dilate render edges by 1px so near-misses count
en_d = np.asarray(Image.fromarray((en * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3))) > 0
small = (W, H)
Lr, Ln = lab(ref.resize(small)), lab(ren.resize(small))
res = {
    "ssim": round(ssim(gr, gn), 4),
    "edge_iou": round(float((er & en_d).sum() / max(1, (er | en).sum())), 4),
    "color_de": round(float(np.linalg.norm(Lr - Ln, axis=-1).mean()), 2),
    "luma": [round(float(Lr[..., 0].mean()), 1), round(float(Ln[..., 0].mean()), 1)],
    "warmth_b": [round(float(Lr[..., 2].mean()), 1), round(float(Ln[..., 2].mean()), 1)],
}
if a.boxes:
    s = W / ref.width; reg = {}
    for o in json.loads(Path(a.boxes).read_text())["objects"]:
        if "bbox" not in o:
            continue
        x0, y0, x1, y1 = [int(v * s) for v in o["bbox"]]
        r, n = Lr[y0:y1, x0:x1], Ln[y0:y1, x0:x1]
        reg[o["name"]] = {"dL": round(float(n[..., 0].mean() - r[..., 0].mean()), 1),
                          "da": round(float(n[..., 1].mean() - r[..., 1].mean()), 1),
                          "db": round(float(n[..., 2].mean() - r[..., 2].mean()), 1),
                          "de": round(float(np.linalg.norm(r - n, axis=-1).mean()), 1)}
    res["regions"] = reg

# visual for the verifier: ref | render | blend with ref edges in red, render edges in cyan
w = 560; h = round(ref.height * w / ref.width)
r_s, n_s = ref.resize((w, h)), ren.resize((w, h))
blend = Image.blend(r_s, n_s, 0.5)
bl = np.asarray(blend).copy()
er2 = np.asarray(Image.fromarray((er * 255).astype(np.uint8)).resize((w, h))) > 0
en2 = np.asarray(Image.fromarray((en * 255).astype(np.uint8)).resize((w, h))) > 0
bl[er2] = [255, 40, 40]; bl[en2] = [40, 230, 255]
sheet = Image.new("RGB", (w * 3, h))
sheet.paste(r_s, (0, 0)); sheet.paste(n_s, (w, 0)); sheet.paste(Image.fromarray(bl), (2 * w, 0))
Path(a.out).mkdir(parents=True, exist_ok=True)
sheet.save(Path(a.out) / f"{a.tag}-compare.jpg", quality=85)
# keep a score history next to the project for the web app (forge/scores.json)
outp = Path(a.out).resolve()
if outp.name == "loop":
    sp = outp.parent / "scores.json"
    hist = json.loads(sp.read_text()) if sp.exists() else {}
    hist[a.tag] = {k: v for k, v in res.items() if k != "regions"}
    sp.write_text(json.dumps(hist, indent=1))
print(json.dumps(res))

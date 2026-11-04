"""Fit light strengths, one shared white balance, and per-object albedo gains to the reference.

usage: python3 fit_lights.py <forge_dir> [--iters 6] [--prior 0.02] [--no-gains] [--room-gain]
                                         [--fit-emitters] [--shading <npy>]

Model (scene-linear; Standard view transform, exposure 0):
    render(px, c) = gain[region(px), c] * wb[c] * ( sum_lights w_g * basis_g(px, c) + sum_emit basis_e(px, c) )
- basis: loop/basis/*.npy from light_basis.render_basis (one light group on at a time)
- w_g >= 0: ONE scalar per light (its colour is kept), pulled toward 1 by a ridge prior (--prior)
  so lights are only dimmed/killed when the image clearly says so
- wb: one RGB white balance shared by every light (green fixed to 1 -> no scale ambiguity)
- emitters (glowing globes, lenses, textured emission) are fixed at their current strength — their
  pixels are usually clipped in the reference, so the image can't constrain them (--fit-emitters to override)
- gain: per object bbox region (smallest bbox wins); the room shell is fixed at 1 to anchor the
  scale (--room-gain to free it); clamped to [0.5, 2] and shrunk toward 1. Default --gain-mode scalar
  (brightness only). Object HUE errors are a texture problem: fix them with a ForgeTint/hue check
  against the reference crop (see verify-loop.md "Colour"), never with per-channel light-fit gains.
- target: reference.png decoded sRGB->linear, or an intrinsic shading map (--shading; gains off)
Pixels in analysis.json "ignore" boxes and clipped highlights (>0.97) are excluded; relative-error
weighting. Keeps the best iteration. Writes loop/basis/fit.json and loop/basis/fit-preview.png
(reference | current | fitted).
"""
import argparse, json
from pathlib import Path
import numpy as np
from PIL import Image
from scipy.optimize import nnls

ap = argparse.ArgumentParser()
ap.add_argument("forge"); ap.add_argument("--iters", type=int, default=6)
ap.add_argument("--prior", type=float, default=0.02, help="ridge strength pulling light weights to 1")
ap.add_argument("--no-gains", action="store_true"); ap.add_argument("--room-gain", action="store_true")
ap.add_argument("--fit-emitters", action="store_true"); ap.add_argument("--shading")
ap.add_argument("--gain-mode", choices=["scalar", "rgb"], default="scalar",
                help="scalar (default): one brightness gain per object, hue can't drift; rgb: per-channel "
                     "(only with --max-hue-shift guard; it turned beige upholstery grey/mauve on the living room)")
ap.add_argument("--max-hue-shift", type=float, default=0.08,
                help="rgb mode: max per-channel deviation of a gain from its mean (0.08 = 8%%)")
a = ap.parse_args()

F = Path(a.forge); B = F / "loop" / "basis"
groups = json.loads((B / "groups.json").read_text())
names = [n for n in groups if (B / f"{n}.npy").exists()]
is_emit = np.array([groups[n].startswith("emit:") and not a.fit_emitters for n in names])
basis = np.stack([np.load(B / f"{n}.npy") for n in names]).astype(np.float64)   # G,H,W,3
G, H, W, _ = basis.shape
an = json.loads((F / "analysis.json").read_text())
RW, RH = an["size"]; sx, sy = W / RW, H / RH


def srgb_to_lin(x):
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    return np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)


ref = np.asarray(Image.open(F / an["reference"]).convert("RGB").resize((W, H), Image.LANCZOS), np.float64) / 255
T = np.load(a.shading).astype(np.float64) if a.shading else srgb_to_lin(ref)
use_gains = not a.no_gains and not a.shading

mask = np.ones((H, W), bool)
for x0, y0, x1, y1 in an.get("ignore", []):
    mask[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)] = False
mask &= ref.max(axis=2) < 0.97
mask &= basis.sum(axis=0).max(axis=2) > 1e-5
pw = np.where(mask, 1 / np.sqrt(T.mean(axis=2) + 0.02), 0)

objs = [o for o in an["objects"] if "bbox" in o and o.get("source") == "meshy"]
region = np.full((H, W), -1); area = np.full((H, W), np.inf)
for i, o in enumerate(objs):
    for x0, y0, x1, y1 in [o["bbox"]] + o.get("instances", []):
        ar = (x1 - x0) * (y1 - y0)
        ys, xs = slice(int(y0 * sy), int(y1 * sy)), slice(int(x0 * sx), int(x1 * sx))
        upd = area[ys, xs] > ar
        region[ys, xs] = np.where(upd, i, region[ys, xs]); area[ys, xs] = np.where(upd, ar, area[ys, xs])
labels = [o["name"] for o in objs] + ["room"]
room_idx = len(objs); region[region == -1] = room_idx


def err(pred):
    d = np.log(pred + 0.01) - np.log(T + 0.01)
    return float(np.sqrt((d ** 2 * mask[..., None]).sum() / (mask.sum() * 3)))


L = np.where(~is_emit)[0]; E = np.where(is_emit)[0]
w = np.ones(G); wb = np.ones(3); gains = np.ones((len(labels), 3))
keep = pw.reshape(-1) > 0
e0 = err(basis.sum(axis=0))
best = (np.inf,)
for it in range(a.iters):
    gpx = gains[region]                                                    # H,W,3
    fixed = basis[E].sum(axis=0) if len(E) else 0.0                        # emitters at strength 1
    # 1) scalar light weights: stack the 3 channels as rows, ridge rows pull w toward 1
    A = np.concatenate([((basis[L, ..., c] * gpx[None, ..., c] * wb[c]) * pw[None]).reshape(len(L), -1).T[keep]
                        for c in range(3)])
    b = np.concatenate([((T[..., c] - gpx[..., c] * wb[c] * (fixed[..., c] if len(E) else 0)) * pw).reshape(-1)[keep]
                        for c in range(3)])
    lam = np.sqrt(a.prior * len(b))
    wL, _ = nnls(np.vstack([A, lam * np.eye(len(L))]), np.concatenate([b, lam * np.ones(len(L))]), maxiter=100 * G)
    w[L] = wL
    lit = np.einsum("ghwc,g->hwc", basis, w)                               # emitters keep w=1
    # 2) shared white balance (green fixed)
    for c in (0, 2):
        m = mask
        w2 = pw[m] ** 2
        wb[c] = float((w2 * T[m][:, c] * (gpx[m][:, c] * lit[m][:, c])).sum() /
                      max((w2 * (gpx[m][:, c] * lit[m][:, c]) ** 2).sum(), 1e-12) /
                      max((w2 * T[m][:, 1] * (gpx[m][:, 1] * lit[m][:, 1])).sum() /
                          max((w2 * (gpx[m][:, 1] * lit[m][:, 1]) ** 2).sum(), 1e-12), 1e-9))
    wb = np.clip(wb, 0.6, 1.6)
    lit_wb = lit * wb
    # 3) per-object albedo gains
    if use_gains:
        for r in range(len(labels)):
            if r == room_idx and not a.room_gain:
                continue
            m = (region == r) & mask
            if m.sum() < 30:
                continue
            w2 = (pw[m] ** 2)[:, None]
            if a.gain_mode == "scalar":   # brightness only: same factor on R, G, B
                g = (w2 * T[m] * lit_wb[m]).sum() / max((w2 * lit_wb[m] ** 2).sum(), 1e-12)
                g = np.full(3, g)
            else:
                g = (w2 * T[m] * lit_wb[m]).sum(0) / np.maximum((w2 * lit_wb[m] ** 2).sum(0), 1e-12)
                gm = g.mean()                    # clamp chroma: keep each channel near the mean gain
                g = np.clip(g, gm * (1 - a.max_hue_shift), gm * (1 + a.max_hue_shift))
            gains[r] = 1 + 0.8 * (np.clip(g, 0.5, 2.0) - 1)
    pred = lit_wb * gains[region]
    e = err(pred)
    print(f"iter {it}: log-rmse {e:.4f}  wb={np.round(wb, 3).tolist()}")
    if e < best[0]:
        best = (e, w.copy(), wb.copy(), gains.copy(), pred.copy())
    elif it > 1:
        break

e1, w, wb, gains, pred = best
fit = {
    # apply_fit reads per-group RGB weights: scalar strength x shared white balance (normalised)
    "weights": {n: [round(float(w[i] * wb[c] / wb.max()), 5) for c in range(3)] if not is_emit[i]
                else [round(float(wb[c] / wb.max()), 5) for c in range(3)] for i, n in enumerate(names)},
    "strength": {n: round(float(w[i]), 4) for i, n in enumerate(names)},
    "white_balance": [round(float(v), 4) for v in wb],
    "gains": {labels[r]: [round(float(v), 3) for v in gains[r]] for r in range(len(labels))} if use_gains else {},
    "view": {"transform": "Standard", "exposure": round(float(np.log2(wb.max())), 3)},
    "error": {"before": round(e0, 4), "after": round(e1, 4)},
    "basis_size": [W, H],
}
(B / "fit.json").write_text(json.dumps(fit, indent=1))
prev = np.concatenate([ref, lin_to_srgb(basis.sum(axis=0)), lin_to_srgb(pred)], axis=1)
Image.fromarray((prev * 255).astype(np.uint8)).save(B / "fit-preview.png")
print(json.dumps({"error": fit["error"], "white_balance": fit["white_balance"],
                  "strength": fit["strength"], "gains": fit["gains"]}))

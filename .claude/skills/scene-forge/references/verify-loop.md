# Verify loop (render -> compare -> correct)

Setup in Blender (every call):
```python
FORGE_DIR = "<abs>/worlds/<slug>/forge"
exec(open("<abs>/.claude/scripts/scene-forge/forge_blender.py").read())
```

One iteration:
1. EEVEE, 50% res: `sc.render.filepath = FORGE + "/loop/iterNN.png"; bpy.ops.render.render(write_still=True)` (~2 s)
2. `python3 $S/compare.py $F/reference.png $F/loop/iterNN.png $F/loop --tag iterNN --boxes $F/analysis.json`
3. Read `loop/iterNN-compare.jpg` (reference | render | blend with red=ref edges, cyan=render edges).
4. Write down concrete diffs in pixels: "table top 25 px too high", "bench 30% too wide",
   "sconce region dL -14".
5. Change ONE group, re-render, keep if scores or the visual improved, else revert.
6. `python3 $S/log_iter.py $F iterNN <group> "<what/why>" '<scores json>' keep|revert`

Order: camera/room -> placement -> material tint -> lights -> exposure. Don't tune lights before
placement is right (occlusion changes region brightness).

## Placement fixes (forge_blender.py)
| symptom | fix |
|---|---|
| model faces away / sideways | `place_object(name, yaw_deg=180)` or 90 |
| rotated object, arms, overhangs (bench, armchair) | `fit_bbox("F_<name>", bbox)` |
| tall thin (floor lamp, plant): too short | scale by height: ray through bbox top row at the object's depth plane, scale until top z matches, re-ground |
| flat relief (wall art) squashed | stretch Z between the wall-plane hits of bbox top/bottom rows |
| square model for a rectangular table | scale Y to real depth, keep front edge |
| object sits too far back | anchor a visible edge instead of the base: e.g. table top front edge row on the plane z = top |
| repeated objects | `place_object(name, suffix="_R", bbox=[...])`, then copy the first instance's scale |
| hidden contact | `contact_v` in analysis.json |
Pixel position beats "realistic" size: the goal is matching the reference from this camera.

## Orientation: pose_search (forge_blender.py)
Meshy models come in facing an arbitrary way and the reference often shows furniture turned
(armchair facing the sofa, bench on a diagonal). For EVERY floor object after placement:
```python
pose_search("F_<name>", yaws=range(0, 360, 30))           # coarse; refits to the bbox per yaw
pose_search("F_<name>", yaws=(best-15, best, best+15))     # fine
```
It scores edge F1 + grey NCC inside the object's bbox (EEVEE 25%, ~1 s per yaw) and keeps the best.
The score is only a tie-breaker when the bbox also holds other objects: when the top candidates are
within ~0.03, render them at 50%, crop the bbox next to the reference and decide by eye (this is how
the living-room armchair got 270°: the visible arm panel decides it).
Symmetric decor: test (0, 180) — 180 fixes a left/right mirrored arrangement.
Living-room results: armchair 270°, bench 75°, decor 180°, coffee table 0°.

Traps (all hit on the living room):
- tables/benches: `fit_bbox(..., height="dims")` — the bbox includes the top surface seen from above,
  so fitting Z to it squashes a 0.42 m table to 0.24 m. Benches scored better with bbox height.
- after rotating a non-square model 90°, check its footprint; a depth-scaled table became 1.7 m deep.
- tables: anchor the visible TOP front edge row on the plane z = top height, not the recessed base.
- `support_z` / `contact_v` must be saved in analysis.json — values set only in a Blender session are
  lost, and fit_bbox will drop decor to the floor (it hid behind the sofa and scored identically for
  every yaw — identical scores mean the object isn't visible).
- items with a hidden base (plant behind an armchair): fit width + top row on the object's depth
  plane, then add a simple dark stand underneath so it doesn't float.

## Colour rule (hue vs brightness)
Light fit and gains may change BRIGHTNESS only (`fit_lights.py` default `--gain-mode scalar`).
Per-channel gains turned the living-room sofa grey and the armchair mauve. After every light/material
step check `compare.py` per-object `da`/`db`: |da| > 3 or |db| > 4 is a hue error. Fix it at the
source, in this order:
1. Meshy texture drifted (qc-sheet meshy column vs nano front) -> rerun Meshy `--texture-guide views`.
2. Only small residual hue error -> ForgeTint Hue/Saturation on that object's material, checked against
   the `colour` hex in analysis.json. Never via light colours (lights are shared by every object).

## Materials
Meshy albedo is delit and comes out too light/grey. Insert a HueSaturation node named `ForgeTint`
before Base Color; lower Value (0.65-0.8) and raise Saturation (1.1-1.25) until per-object
`dL` is within ±3. Wood usually needs the most saturation.

## Lights — automatic fit first (light_basis.py + fit_lights.py)
Light adds up linearly: the full render = sum of renders with one light on. So instead of hand-tuning:
```python
# Blender (save a backup .blend first — apply_fit multiplies energies, it is not idempotent)
FORGE_DIR = "<abs F>"; exec(open("<abs S>/light_basis.py").read())
names = list(light_groups())          # lights, emissive materials (Emission node + Principled emission), world
render_basis(names[:7]); render_basis(names[7:])   # Cycles 25%, ~3 s per group; chunk to dodge MCP timeouts
```
```bash
python3 $S/fit_lights.py $F            # -> loop/basis/fit.json + fit-preview.png (ref | before | fitted)
```
```python
apply_fit()                            # strengths, shared white balance, per-object ForgeGain, Standard view
```
Then: render, match luma with `exposure += 3*log2((L_ref+16)/(L_render+16))`, try AgX (+ the same
exposure match) and keep whichever scores better — on the living room AgX won (softer practicals).
Solver rules that matter (learned the hard way):
- one scalar per light + ONE shared white balance; per-light free RGB makes red/green/blue cheat lights
- object gains brightness-only (`--gain-mode scalar`, default); `rgb` only with `--max-hue-shift`
- emitters (globes, lenses) fixed at strength 1 — their pixels are clipped in the reference
- ridge prior toward 1 (`--prior`), room gain fixed at 1 to anchor scale (else gains/lights drift)
- `analysis.json` `"ignore": [[x0,y0,x1,y1]]` for watermarks/text boxes
- re-rendering the basis after apply_fit is fine: gains are reset to 1 during basis renders
Living room: colour error 15.3 -> 13.6, mean |object dL| 6.2 -> 4.6, SSIM 0.484 -> 0.486, warmth fixed.
Optional `--shading <npy>`: fit lights to an intrinsic shading map (compphoto/Intrinsic, academic
licence only, needs torch) so albedo errors can't leak into light strengths.

## Lights — manual touch-ups
- practicals: small emission spheres in each globe (r ~0.055, strength 15-25, warm 1.0/0.72/0.42) +
  point lights 35-60 W inside; point light 40-60 W inside a lamp shade at the shade pixel's depth.
- fills (area/ceiling/wall wash) low: too much fill flattens the image and lifts every region dL.
- global: match `luma` with exposure, `warmth_b` with fill light colour (1.0/0.88/0.74 is neutral-warm).
- regions near lamps darker than the reference -> raise the practical, not the exposure.

## Engines
Iterate in EEVEE. Final in Cycles (GPU, denoise): per-region light is noticeably closer to the
reference. A full-res Cycles render can exceed the MCP timeout — start it, then poll for the file.

## Stop rule
Stop after 2 iterations without improvement, or when edge_iou > 0.45, color_de < 10, luma within 2.
SSIM rarely passes ~0.55 (fabric/fine texture, overlays/watermarks in the reference); report it, don't chase it.

---
name: scene-forge
description: Rebuild a reference interior image as an exact Blender scene. Splits the image into objects, generates multi-angle views per object with Nano Banana 2.1 (Higgsfield), turns them into textured 3D with the Meshy multi-image-to-3D API, solves the camera, places everything, then runs a VIGA-style render -> compare -> correct loop on layout, materials and lighting until the render matches the reference. Use when the user says "forge", "rebuild this scene exactly", "recreate this image in Blender", "match the reference in Blender".
argument-hint: [image path] [world-slug] [--skip-views] [--skip-meshy] [--loop-only] [--max-iters N]
---

# scene-forge

VIGA-style analysis-by-synthesis. You (the main session) are the Generator and the final Verifier;
background agents do the slow parallel work.

```
1 init -> 2 analyze -> 3 crops -> 4 views (agent/object) -> 5 meshy (agent/object)
      -> 6 camera solve + room -> 7 place -> 8 verify loop (scene-forge-verifier) -> 9 final render
```

## Requirements (check first, stop and tell the user if missing)
- Blender running with the Blender MCP addon (`get_addon_status`).
- Higgsfield MCP connected (tools `media_upload`, `generate_image_batch`, `jobs_wait`). If it needs auth,
  tell the user to connect it in claude.ai connector settings.
- `MESHY_API_KEY` in `.env`. Check credits:
  `curl -s -H "Authorization: Bearer $KEY" https://api.meshy.ai/openapi/v1/balance` (~30 credits/object).
- Python 3 with Pillow + numpy.

Paths: `S=.claude/scripts/scene-forge`, `F=worlds/<slug>/forge`. Read the reference docs in
`references/` when you reach the matching step; don't load them all up front.

## 1. Init
`python3 $S/init_forge.py <image> <slug>` -> `$F/reference.png`, `analysis.json` template, `state.json`.
Work in a copy of the blend: if a .blend is open, `save_as_mainfile($F/scene-forge.blend)`; never
overwrite the user's file.

## 2. Analyze (you, with vision)
Read the reference once. Fill `analysis.json` per `references/analysis-schema.md`: every separable
object (bbox px, dims_m guess, desc, **structure**, **colour hex**, mount, contact_v/support_z),
procedural items (room shell, rug, floor, door, **openings**), lighting sources.
Do the **coverage sweep** (borders + depth layers, write `coverage`) — nothing dropped silently.
Draw the boxes on a copy and look at it before cropping. Show the user the object list (including
partial / edge objects and what was skipped and why) and ask only if something is ambiguous.

## 3. Crops
`python3 $S/crop.py $F` -> `objects/<name>/0-crop.png`; copy to `flow-upload/<name>.png` (unique names
for uploading).

## 4. Views (parallel)
For each `source: meshy` object launch `Agent(scene-forge-views)` with `run_in_background: true`
(world slug + object name, optional `--angles 8`). Max 6 agents at once (Nano Banana rate limit).
Each agent uploads its crop to Higgsfield, makes a 2k front view, then ONE 4k turnaround sheet with
every other angle (2x2 = 4 angles, 3x3 = 8-angle orbit + top) using the front as reference, splits it
with `split_sheet.py` into `objects/<name>/views/<name>-<view>.png`, and regenerates any bad cell as a
single view. ~5 Higgsfield credits per object. Prompts: `references/views-prompts.md`.
Use `--angles 8` for objects with detail all around (armchairs, lamps, sculptures); 4 is enough for
wall-mounted and boxy items.
Rug/floor textures: do these yourself with the "flat top-down texture" prompt.
**Gate A (before Meshy):** `python3 $S/qc_sheet.py $F` -> look once; every structure note and hue must
match the reference crop. Wrong views go back to scene-forge-views — never to Meshy.

## 5. Meshy (parallel)
When an object passes gate A, launch `Agent(scene-forge-meshy)` in the background for it.
Max ~9 running (Meshy 429s above ~10 concurrent tasks); queue the rest as slots free up.
Output: `objects/<name>/1-<name>.glb`. Texture is guided by the views (`--texture-guide views`).
**Gate B (before placing):** `qc_sheet.py` again — meshy column vs nano front: shape parts present,
hue unchanged. Fail -> regenerate that object; placement and lighting can't fix shape or hue.

## 5b. Empty-room plate (default, start it with the views)
Upload `reference.png` to Higgsfield and have Nano Banana 2.1 remove every free-standing object and
any text/watermark ("remove ONLY …, keep EVERYTHING else pixel-aligned"), `aspect_ratio: auto`, 2k.
`plate_composite.py align` -> `plate/2-plate.png`. This is what makes the walls match the photo.

## 6. Camera solve + room (you, while 4-5 run)
Follow `references/camera-solve.md`: horizon + vanishing point, px-per-metre on the back wall from
moldings/door, eye height, lens, lens shift. Build or rescale the room shell to the measured
dimensions. Render (EEVEE, 50%) and score with compare.py; the room edges should line up before
any furniture goes in.

## 7. Place
In Blender: `FORGE_DIR="<abs $F>"; exec(open("<abs $S>/forge_blender.py").read())`, then
`place_object(name)` for each finished GLB (wall/ceiling objects use `mount`). Then for every floor
object run `pose_search("F_<name>")` (coarse 30° sweep, then ±15° fine) — it refits to the bbox per
yaw and scores edges/shading against the reference; break near-ties by eye with bbox crops.
Tables: `height="dims"`; tall-thin -> height fit; flat reliefs -> stretch Z; hidden bases -> stand.
Details and traps in `references/verify-loop.md`.

## 8. Verify loop
Hand off to `Agent(scene-forge-verifier)` (foreground: it drives the shared Blender) with the slug and
the iteration budget, or run the loop yourself per `references/verify-loop.md`. Each iteration:
render -> `compare.py` -> read the diff sheet -> change ONE group -> keep/revert -> `log_iter.py`.
Order: camera/room -> placement -> **automatic light + material fit** (`light_basis.py` renders one
image per light, `fit_lights.py` solves strengths, white balance and per-object colour gains,
`apply_fit()` writes them back; details in verify-loop.md) -> exposure match -> manual touch-ups.
Stop when scores plateau for 2 iterations or targets are hit (edge_iou > 0.45, color_de < 10,
luma within 2, per-object |dL| < 4).

## 7b. Room from the plate (default once furniture is placed)
`exec(room_from_plate.py)` then `build_plate_room(surfaces, hide)`: walls/floor/ceiling/built-in
fronts get camera-projected UVs into the empty-room plate (camera rays = photo pixels x contact-shadow
AO, other rays = diffuse plate colour), painted detail meshes are hidden, view -> Standard/exposure 0,
lights rescaled. Walls then match the photo INSIDE Blender's render view — no compositing. Tune
furniture brightness with the light energies (living room: x1.4 more, furniture dL -4.4 -> -0.9).
`restore_room()` returns to the plain 3D room. Living room: SSIM 0.510 -> 0.582, edges 0.322 -> 0.413,
colour Δ 13.8 -> 8.2. Exact from this camera; far camera moves stretch the painted walls.
Older alternative (two-pass composite outside Blender): `references/projected-plate.md`.

Clean rebuild: `scene_layout.py` -> `export_layout()` writes `$F/layout.json` (camera, render, world,
room surfaces, lights at plate-free energies, furniture GLB transforms + ForgeTint/ForgeGain fixes,
globes/stand/rug). `read_homefile(use_empty=True)`, `build_from_layout()` (room built directly as
bmesh boxes, GLBs re-imported, no old helper meshes), then `build_plate_room` again. Living room
rebuild: 148 MB file, scores identical (0.582 / 0.413 / 8.2).

## 7d. Fully 3D room (when the user wants to move the camera) — user's choice on the living room
Projection (7b) stretches as soon as the camera moves. For free camera moves, model the architecture
from the empty-room plate and drop the photo: `room_build.py` -> `build_room3d(spec)` with
`$F/room3d/room3d.json` (written by a per-project `room3d/make_spec.py`):
- FIRST place every wall where the PHOTO's floor puts it: `hit_plane(u, v_floorline, (0,0,0), (0,0,1))`
  at each wall's floor/baseboard line gives its depth (living room: feature wall 1.87, not 3.0 — the
  camera-solve px/m guess had left a 1.1 m gap behind the sofa and nothing lined up). Check: wall
  corners, ceiling height from 2-3 walls and furniture contacts (sofa back touching the wall) agree.
  Wall-mounted items then move with `T(cam)·S(r)·T(-cam)`, r = new/old depth from the camera (image
  unchanged); floor items move along the floor in front of the wall
- measure details on the plate with a pixel grid and cast them onto those wall planes with `hit_plane`
- no front wall: the long-lens main camera sits outside the room
- panel moldings (frames), crown (two stepped runs), baseboards, built-in wardrobe doors with gaps,
  doorways cut by rebuilding the wall as pieces + dark room behind, door leaf + dark frame + handle,
  recessed downlight discs at the spot lights
- textures that exist only in the photo come from the plate: door wood = straight crop of the leaf,
  rug = `Image.transform(QUAD)` of its floor corners -> top-down; floor = seamless tile (tile_m 1.2)
- hide the Meshy rug if the rectified rug replaces it; wall art, sconces, fan come back as models
- then match colour per region (wall upper/lower, right wall, wardrobe, ceiling, floor, door): measure
  linear means ref vs render, scale albedos / ForgeGain and rebalance lights (Wall_Wash down, sconces +
  lamp up); the automatic light fit barely helps here (log-rmse 0.76 -> 0.76, geometry ≠ photo).
Living room: colour Δ 13.3 -> 11.5, SSIM 0.53, edges 0.36 from the main camera (projection: 8.2 /
0.58 / 0.41), but every angle is a real room. Write `$F/problems.md` (table: area | reference |
render | cause/fix) after each matching pass. Traps: an up-facing fake bounce light above the floor
draws a hard line on every wall; downlights < 0.4 m from a wall scallop it (blend 1.0). Saved test cameras: Cam_orbit-left/right,
Cam_high-corner, Cam_wardrobe-side. `clear_room3d()` removes it.

## 7c. (Experimental, NOT the default) bake the photo onto the real 3D room
User verdict on the living room: "not work properly". For one fixed camera use 7b (empty-room plate
projected onto the room); for camera moves use 7d (fully 3D room). Only try this when the user
explicitly asks for new camera angles AND accepts a weaker match. Keep the modelled room (moldings, built-ins, door) and BAKE the
photo onto it instead of projecting live: `bake_room.py` -> `prepare_bake(objs, fallback={"Floor":
(floor-tile.png, tile_m)})`, `run_bake` (via bpy.app.timers, poll for plate/room-atlas.png; ~10 min with
everything subdivided), `apply_baked`. Before baking: put 3D doors/built-ins where the PHOTO shows them
(cast their reference corners onto the wall plane) or the photo's door gets painted onto bare wall.
Floor areas the photo never saw: Nano Banana seamless top-down tile of the floor (from a floor crop of
the plate), colour-matched to the photo. Living room: original view SSIM 0.540 / edges 0.393 / colour 8.5
(vs 0.582 projection-only) and orbit ±20-25°, push-in and high-corner views stay a coherent room.
Test angles from INSIDE the room (the long-lens main camera sits outside it). Traps: lightmap_pack ->
patchwork (use smart_project + pack_islands); low-poly boxes (6 faces) -> pale fill (subdivide all).
`restore_baked()` returns the plain materials. To go back to 7b: `restore_baked()` then the same
`build_plate_room(...)` call (walls/floor/ceiling surfaces, painted details hidden, light_scale ≈ 2.1).

## 9. Final
Switch to Cycles (GPU, denoise, 128-192 samples), full resolution, render `$F/final-render.png` in the
background-safe way (a long render times out the MCP call: render, then poll for the file).
Save the blend. Make `side-by-side.jpg` (reference | render), send it to the user with the score table
(first vs final) and an honest list of what still differs.

## Quality gates (each one comes from a real failure on the living-room run)
| gate | when | catches |
|---|---|---|
| coverage sweep | analyze | missing objects at frame edges (doorway, dining chair were missed) |
| structure + colour notes | analyze | invented construction (X-base table), hue words without a target |
| A: qc_sheet nano vs crop | before Meshy | wrong base/legs/seams, wrong hue in the views |
| B: qc_sheet meshy vs nano | before placing | Meshy texture hue drift (beige -> mauve), fused/missing parts |
| pose_search + crop check | after placing | wrong facing (armchair 270°, bench 75°, decor mirrored 180°) |
| support_z/contact_v saved | after placing | decor dropped to the floor (identical pose scores = object hidden) |
| fixed real height for tables | after placing | bbox height squashing tables (0.42 -> 0.24 m) |
| brightness-only gains + da/db check | light fit | per-channel gains turning upholstery grey/mauve |
| walls from the photo's floor lines | 3D room | room 1.1 m too deep, mouldings/door never aligned |
Before the final render, re-run `qc_sheet.py --render <latest render>` and read the "placed" column
against the reference for every object: position, facing, shape, colour. List anything still off
in the final report instead of calling it done.

## Notes
- Google Flow fallback (Claude browser pane): the pane can't read local files, clipboard or localhost
  and downloads don't land on disk, so the user must upload crops and download results by hand.
  Prefer Higgsfield.
- Keep all provider ids in `views-jobs.json` / `.1-<name>-request.json` so runs can resume.
- Don't read generated images into context except the diff sheets and one contact sheet of views.

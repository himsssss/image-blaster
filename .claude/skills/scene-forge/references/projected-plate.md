# Projected clean plate (when the walls can't be matched geometrically)

Use when the reference's room can't be reproduced by one camera + one rectangular room — typical for
composited / AI-assisted archviz renders. Symptom on the living room: furniture fits 45 mm / eye 1.2 m,
but the right wall and door recede like a 28 mm shot; fitting the door needed a 1.4 m wide, 1.8 m tall
door with its top sloping the wrong way. Ask the user before switching (trade-off below).

## How it works
1. **Clean plate (Higgsfield, Nano Banana 2.1, ~3 credits):** upload `reference.png`, `aspect_ratio:
   "auto"`, 2k. Prompt: remove ONLY the free-standing items (list every one), and any text/watermark
   box; "fill the revealed areas with what is naturally behind them … keep EVERYTHING else exactly
   identical and pixel-aligned: same camera, framing, perspective, lighting and colours; keep <wall art,
   sconces, fan, wardrobes, doors, rug, background rooms>". Save `plate/1-plate-raw.png`.
2. **Align:** `python3 $S/plate_composite.py align reference.png plate/1-plate-raw.png plate/2-plate.png`
   — resizes to the reference and reports diff/shift for ceiling, left and right wall strips
   (living room: ≤ 6 px shift, mean diff ~9; the right-wall number is higher because furniture left it).
3. **Never leave the scene in plate mode.** In plate mode the walls are invisible in Blender's render
   view (user: "walls are not visible in render view"). Use `plate_mode.py`: the scene stays in
   EDIT mode (normal visible room) and `render_plate_passes(pct, samples)` switches to PLATE only for
   the two final passes, then back. Each mode keeps its own exposure (scene["forge_exposure_edit"/
   "forge_exposure_plate"]). The manual steps below are what PLATE mode does:
   **Blender setup (PLATE mode):**
   - every room mesh (walls, floor, ceiling, built-ins, door, rug) -> `is_shadow_catcher = True`
   - objects already in the plate (wall art, sconces, glow spheres, fan) -> `hide_render = True`.
     NOT just `visible_camera = False`: hidden-from-camera meshes still block light and print dark
     "shadows" of themselves on the catchers.
   - `scene.render.film_transparent = True`, PNG RGBA
4. **Two passes** (same camera, same lights):
   - shadow pass: room as shadow catchers -> alpha = furniture + its shadows
   - furniture pass: room `is_holdout = True` (catchers off) -> alpha = furniture only, solid
   Restore the catchers afterwards.
5. **Composite:** `plate_composite.py comp2 plate/2-plate.png <furniture.png> <shadow.png> out.png --shadow 0.4`
   Shadow strength scales only the shadows (single-pass `comp --shadow` made furniture see-through).
6. **Exposure:** the walls now come from the photo, so match the FURNITURE brightness: compare.py
   per-object dL; living room needed +0.45 stops (furniture dL −6 -> −1.6).

## Result on the living room
| | 3D walls (45 mm) | projected plate |
|---|---|---|
| SSIM | 0.510 | 0.566 |
| edge overlap | 0.322 | 0.410 |
| colour Δ | 13.8 | 9.4 |
Walls, wardrobes, left doorway + dining chair, door: exact. Furniture: real 3D, lit, shadows on the
floor and walls.

## Trade-off (tell the user)
Exact from THIS camera only. Moving the camera far will stretch the projected walls; for camera moves
keep the 3D room (or re-run the plate from the new viewpoint). The 3D room stays in the file as shadow
catchers, so switching back is just unticking `is_shadow_catcher` and un-hiding the plate objects.

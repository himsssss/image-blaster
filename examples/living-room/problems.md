# Living room: render vs reference, open problems

The render is `loop/iter52-room-v2.png`, compared in `side-by-side.jpg`. The scene is a fully 3D room, so every camera angle works.

Scores from the main camera: structure 0.527, edge overlap 0.359, colour difference 11.5 (it was 13.3 at the first 3D room). Wall, ceiling, floor and door colours are within 3–7% of the photo.

## Fixed this round
- **Room was 1.1 m too deep.** The 3D feature wall stood at y = 3.0. The photo's floor puts it at y = 1.87, right behind the sofa. All walls are now placed where the photo's floor lines put them:
  - feature wall y 1.871
  - right wall x 1.96
  - wardrobe wall y 2.902
  - ceiling 2.72 m
- **Moldings, wardrobe, door and downlights** were re-measured from the empty-room plate. The crown, panel frames, wardrobe seams and door now sit on the photo's edges.
- **Wall-mounted pieces moved with the wall.** Wall art, sconces, globes and the fan were scaled toward the camera, so they look the same but now touch the wall and ceiling. The lamp and plant moved in front of the wall.
- **Hard line across the walls at 0.38 m** came from the fake floor-bounce light; moved it to floor level.
- **Light scallops on the wardrobes** came from two downlights; softened them and moved them 0.3 m away from the wall.
- **Colour:**
  - Exposure, white balance (6000 K) and wall, floor and door colours matched region by region.
  - Furniture brightness gains adjusted.
  - The armchair is less pink, and the rug and coffee table are less orange.

## Still different (most visible first)
| # | Area | Reference | Render | Cause / fix |
|---|---|---|---|---|
| 1 | Sconces | Glass globes with a warm glow on the wall | Opaque white/chrome balls, no glow | Meshy model has solid spheres. Make the glass transparent and put emissive bulbs inside. |
| 2 | Floor lamp | Drum shade glowing from inside, thin black arc arm | Grey shade, no glow; arm shape differs | Needs emission inside the shade. The arm is Meshy geometry, so regenerate it or model it. |
| 3 | Bench | Light beige tufted top, dark wood splayed legs | Dark grey top, straight legs | Meshy texture and shape. Regenerate the views and Meshy model. |
| 4 | Coffee table | Light oak, top on a split-slab base | Box-like pedestal base | Meshy shape. Regenerate or model it. |
| 5 | Left wall (FIXED) | Off-white panelled wall: moulding frames, thin grooves | Was a separate grey "wardrobe" slab with black gaps on a beige wall | Rebuilt as panelled wall (same colour, frames per bay, grooves), crown white; SSIM 0.527 -> 0.561 |
| 6 | Left doorway | White casing; next room visible (dining chair, black panel) | Casing + lit grey wall with dark lower panel now; dining chair still missing | Dining chair was never generated — add it (views + Meshy). Black corner from overlapping casing boxes fixed. |
| 7 | Armchair | Oatmeal bouclé texture | Smooth, slightly cool beige | Meshy texture is too smooth. Regenerate with texture-guide views. |
| 8a | Wall colours (FIXED) | Same cream paint everywhere | Panelled wall was a separate neutral white | One paint for all walls/panels/mouldings; the photo's warm-back-wall vs whiter-left-wall difference now comes from light colour (warm sconces/lamp/wall-wash 1.0/0.68/0.40, neutral downlights by the panels). Back wall still ~15% bright |
| 8 | Overall warmth | Neutral cream walls | Slightly more yellow/orange (warmth 17.8 vs 16.4) | Small global white balance / wall hue tweak. |
| 9 | Side table, table decor | — | Slightly dark (dL −4 to −5) | Brightness gain. |
| 10 | Ceiling fan | Larger, angled blades | Smaller | Meshy proportions. Rescale the blades or regenerate. |
| 11 | Ceiling edge | Crown reads thinner | Wider beige band under the crown | Crown profile is 0.12 m; try 0.08 m. |
| 12 | Real-world scale | Door looks about 2.1 m | Door 1.83 m, ceiling 2.72 m | The camera height was assumed to be 1.2 m. The whole scene is about 0.87× real size. The image is unaffected; scale everything by about 1.15 if real units matter. |
| 13 | Watermark | Permit text box, top right | — | Intentionally not reproduced. |

## Limits of the method
- **Edges and structure (0.36 / 0.53)** are capped by the furniture models, not the room. Most of the remaining edge error is on the bench, coffee table, lamp and sconces (items 1–4).
- **Lighting.** The automatic light fit can't improve this room any further. Light changes are now manual, per region.

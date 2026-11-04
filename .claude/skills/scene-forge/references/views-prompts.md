# Nano Banana views via Higgsfield

Model `nano_banana_2_1`, `aspect_ratio: "1:1"`. 2k = 2 credits, 4k = 3 credits.
Flow per object: front view (2k, 2 credits) -> one 4k turnaround sheet with every other angle (3 credits)
-> split. 5 credits per object for 4-9 consistent angles.
Batches of <= 6 requests per `generate_image_batch` call; a 429 `rate_limit_reached` on some indices is
normal: resubmit only those. Poll with `jobs_wait` (<= 12 jobs, 15 s each).

## Upload
`media_upload` with `files: [{filename: "<name>.png"}]` -> curl PUT the file to `upload_url` with
`-H "Content-Type: image/png" --data-binary @<file>` (expect 200) -> `media_confirm` type image.
Run the PUT from the machine where the file is; never paste image bytes as text.

## Front view (round 1) — crop as `image_references`
```
Use the attached image only as reference for the <NAME>: <DESC from analysis.json>.
Create a clean product photo of exactly this <NAME> isolated on a pure white background,
straight-on front view, the whole object visible and centred, 50mm lens, soft even studio light,
no cast shadows, no other objects. Keep identical materials, colours, proportions and details.
```
ALWAYS append the object's `structure` notes from analysis.json, as hard constraints:
```
Construction must match the reference exactly: <structure>. Do not redesign or "improve" the object;
do not change the base, legs, seams or number of parts.
```
Nano Banana fills unseen parts with a "typical" design — the living-room coffee table got an X/cross
base instead of two side-by-side slabs because the prompt only said "two offset slab pedestals".
Same block goes into the turnaround-sheet prompt.

Object-specific additions that worked:
- remove clutter on tables: "Remove everything standing on the table."
- occluded items: "Ignore the <other object> in front/behind it."
- lights: "lights switched off" (Meshy should get the fixture, not the glow).
- white objects: "very light grey background instead so the white <obj> stays visible".
- wall art: "perfectly straight-on front view, all panels visible with the same spacing".

## Multi-angle turnaround sheet (round 2, DEFAULT) — front job_id + crop as references
One generation draws every angle of the object in a grid, so all views share identity, lighting and
scale. `resolution: "4k"` (3 credits) -> 2x2 cells are 2048 px, 3x3 cells ~1365 px.
Then split: `python3 $S/split_sheet.py <sheet.png> $F <name> --grid 2x2 --views <list>`
(the script saves `objects/<name>/views/<name>-<view>.png` and prints `ok` / `BAD` per cell).

```
Product turnaround sheet of exactly the same <NAME> as the first image (identical <key materials,
colours, parts, proportions>). A clean <2 by 2 | 3 by 3> grid of <4 | 9> equal square cells on a pure
white background, thin white gutters, no text, no labels, no borders. Each cell shows the whole <NAME>
centred at the same scale with soft even studio light and no cast shadows. <CELL LIST>.
Same object in every cell, orthographic-looking 50mm lens, camera slightly above <seat/top> height.
```
Cell lists (left->right, top->bottom; pass the same order to `--views`):
| object type | grid | CELL LIST -> `--views` |
|---|---|---|
| floor furniture (default) | 2x2 | Top-left: straight-on front view. Top-right: three-quarter view from the front-right at 45 degrees. Bottom-left: side view from the right at 90 degrees. Bottom-right: back view from directly behind. -> `front,right34,right,back` |
| full orbit (`--angles 8`) | 3x3 | row 1: front, front-right 45°, right side 90°; row 2: back-right 135°, back 180°, back-left 225°; row 3: left side 270°, front-left 315°, top-down view from above -> `front,right34,right,back-right34,back,back-left34,left,left34,top` |
| wall-mounted | 2x2 | front, three-quarter from the left 45°, side profile from the right 90° showing projection from the wall, three-quarter from the right 45° -> `front,left34,right,right34` |
| ceiling | 2x2 | front from slightly below, side at eye level showing the downrod, three-quarter from below, straight-up view from below -> `front,right,right34,top` |
| plants / decor groups | 2x2 | front, front-right 45°, right 90°, back -> `front,right34,right,back` |
`meshy.py` sends at most 4: front, a 3/4, back, a side (extra angles stay for QC and retries).

Fallback: a cell reported `BAD` (empty / object cut by the grid), or a sheet where cells show different
objects -> regenerate just that angle as a single view with the prompt below.

## Single views (fallback, or `--mode separate`) — front job_id (+ crop) as references
```
Same exact <NAME> as the first image (identical <key materials/parts>). New camera angle: <VIEW>.
Pure white background, whole object visible and centred, soft even studio light, no cast shadows.
```
| object type | views (file suffix) |
|---|---|
| floor furniture | `front`, `left34` (3/4 front-left 45°, slightly above), `right` (side 90°), `back` (180°) |
| low long items (bench, table) | + `top` (60° from above) instead of `back` if the top matters |
| wall-mounted | `front`, `left34`, `right` (profile, shows projection from the wall) |
| ceiling | `front` (slightly below), `right` (side, shows downrod) |
| plants | `front`, `left34` |

Meshy takes max 4 images and treats image 0 as the front: `meshy.py` sorts `*-front.png` first.

## Flat texture (rug / floor)
Upload a crop of the region, then:
```
The attached image shows a <rug> on the floor in perspective, partly covered by furniture. Recreate
this exact <rug> as a perfectly flat, orthographic top-down texture scan filling the whole frame edge
to edge: <field + border description>. No furniture, no shadows, no perspective, even neutral lighting,
high-detail fibre texture, colour-accurate to the reference.
```
Aspect ratio to match the real rug (16:9 for ~3 x 1.7 m).

## QC gate (before Meshy) — `qc_sheet.py`
`python3 $S/qc_sheet.py $F` -> `$F/qc-sheet.jpg`: reference crop | nano front | meshy | placed, with the
structure notes next to each row. Look at it once and tick every structure note against the nano front:
- construction differs (base type, leg count/shape, seams, one-piece vs split) -> regenerate the front
  with the mismatch named explicitly ("NOT a cross base"), then the sheet. Never send a wrong front to
  Meshy: every later stage inherits it.
- hue differs from the crop (beige vs grey/pink/mauve) -> regenerate with the `colour` hex in the prompt.
- also reject: added/removed parts (cushions!), cropped object, a second object in frame.

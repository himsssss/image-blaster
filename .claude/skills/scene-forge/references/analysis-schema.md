# analysis.json

```json
{
 "reference": "reference.png",
 "size": [W, H],
 "camera": {"lens_mm": 28, "eye_h": 1.73, "dist_back_wall": 5.4, "shift_x": 0.018, "shift_y": -0.055},
 "objects": [
  {"name": "sofa", "source": "meshy", "bbox": [x0, y0, x1, y1], "dims_m": [w, d, h],
   "desc": "materials, colours, parts — becomes the Meshy texture_prompt (<=800 chars)"},
  {"name": "wall-art", "source": "meshy", "bbox": [...], "mount": "wall", "plane": 3.0},
  {"name": "wall-sconce", "source": "meshy", "bbox": [...], "mount": "wall", "plane": 3.0,
   "instances": [[...], [...]]},
  {"name": "ceiling-fan", "source": "meshy", "bbox": [...], "mount": "ceiling", "plane": 2.88},
  {"name": "floor-lamp", "source": "meshy", "bbox": [...], "contact_v": 955},
  {"name": "table-decor", "source": "meshy", "bbox": [...], "contact_v": 928, "support_z": 0.42},
  {"name": "rug", "source": "procedural", "bbox": [...], "desc": "..."},
  {"name": "room", "source": "procedural", "desc": "walls, moldings, floor, door, wardrobes"}
 ],
 "lighting": {"mood": "warm evening ~2700-3000K", "sources": ["..."], "notes": "..."}
}
```

Fields
- `structure` (REQUIRED for every meshy object): the construction details a generator could invent
  wrongly, written as checkable facts. Goes into every Nano Banana prompt and is ticked off on the QC
  sheet. Cover: legs (count, shape, splay, material), base construction (slab/pedestal/frame, how many
  parts, seams), top (one piece or split, edge profile), arms/back shape, cushion count + order + pattern,
  arrangement of grouped items left->right. Example that would have saved the living-room table:
  `"top made of TWO rectangular halves with a straight seam across the middle; base = TWO separate
  wide rectangular slabs side by side, flat faces toward the viewer, vertical seam where they meet;
  NOT a cross / X / T base"`.
- `colour`: the visible colour words + a sampled sRGB hex from the crop centre, e.g.
  `"warm beige-taupe boucle #a8927c"`; used to catch hue drift after Meshy.
- `bbox`: tight box in reference pixels around the visible object (include cushions, legs).
- `dims_m`: real-size guess [width, depth, height]; used to auto-orient (width along X).
- `mount`: `floor` (default) | `wall` (plane = wall Y) | `ceiling` (plane = ceiling Z).
- `contact_v`: pixel row where the object really touches its support, when the bbox bottom is an
  occlusion edge (object behind another).
- `support_z`: height of the surface it stands on (decor on a table).
- `instances`: extra bboxes for repeated objects (two sconces) — generate once, place many.

Coverage sweep (REQUIRED before cropping — the living room missed a doorway and a dining chair):
1. Walk the four borders of the image in 100 px steps and list everything the frame cuts: furniture
   half out of frame, doorways/openings, windows, curtains, rugs continuing out of frame.
2. Walk the depth layers: foreground (nearest the camera), middle, back wall, ceiling, floor.
3. Openings and dark areas (doorways, corridors, glass) are room features: record them as
   `{"name": "doorway-left", "source": "procedural", "bbox": [...], "desc": "dark grey opening ..."}`.
4. Partially visible furniture still gets an object (`"partial": true`); generate it from the visible
   part — a missing chair costs more than an imperfect one.
5. Write the sweep result into analysis.json `"coverage"`: `{"borders": [...], "openings": [...],
   "skipped": [{"what": "...", "why": "..."}]}` — nothing may be dropped silently.

What to split out: every piece of furniture, wall art, light fixtures, plants, decor groups that sit
together (tray + candle + sculpture = one object). Keep as procedural: walls, moldings, floor, ceiling,
doors, built-in wardrobes, rugs (texture from Nano Banana), curtains.
Skip: watermarks / text overlays in the reference (they will always cost SSIM; note them).

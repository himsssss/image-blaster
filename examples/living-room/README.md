# Example: living room

Small output files from a Scene Forge run on a living-room reference photo (the photo, renders,
3D models and the .blend are not included).

- `analysis.json` — objects with boxes (px), sizes, descriptions; the input to crops, views and Meshy
- `placement.json` — per-object placement check after posing in Blender
- `scores.json` — render vs reference scores per iteration (SSIM, edge overlap, colour difference)
- `problems.md` — what still differs from the reference, with a fix for each
- `room3d_make_spec.py` — the measured 3D room (walls from the photo's floor lines, mouldings,
  panelled wall, door) for `room_build.py`; run it inside `worlds/<slug>/forge/room3d/`

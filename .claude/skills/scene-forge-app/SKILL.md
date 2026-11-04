---
name: scene-forge-app
description: Open the Scene Forge local web app in the Claude browser and work its job queue — the app handles upload, object editing, crops, Meshy and result views; Claude runs the steps only it can do (vision analysis, Higgsfield Nano Banana views, Blender MCP placement / pose / light fit / verify / final render) when the user clicks them. Use at session start (the SessionStart hook asks for it), or when the user says "open scene forge", "open the app", "start the forge app".
argument-hint: [--no-open]
---

# Scene Forge app worker

## 1. Start + open (once per session)
1. Server: `preview_start` with name `scene-forge` (from `.claude/launch.json`; port 8770). If the
   preview tool says no launch.json, create one in the SESSION ROOT with an absolute path to
   `<repo>/forge-app/server.py` (the tool reads the session root, not the repo).
   It reuses a running server. If you changed `forge-app/server.py`, `preview_stop` + `preview_start`.
   If port 8770 already answers (`curl -s localhost:8770/api/projects`) — e.g. the `scene-forge` mod's
   bookmark started it — don't preview_start (port clash): open it with the browser `navigate` tool.
   Bookmark prompts from the mod ("Open the Scene Forge Library (http://localhost:8770/#library) in the
   Claude browser pane.") are the user's request: `navigate` to that exact URL, keep the hash. Page links:
   `#objects #views #models #blender #check #final #library #library/models #new`. The mod lives in
   `mods/scene-forge` and loads in every session through `CLAUDE_CODE_PLUGIN_DIRS` in ~/.claude/settings.json.
2. Unless `--no-open`, the preview opens the app in the Claude browser. Tell the user in one line:
   "Scene Forge is open in the browser panel — upload an image or pick a project."
3. Start the watcher in the background (it re-invokes you when a job arrives):
   `python3 .claude/scripts/scene-forge/jobqueue.py wait --timeout 1500` with `run_in_background: true`.
   While it waits it writes a heartbeat -> the app shows "Claude · online".
   Always use the timeout: open-ended background waits get killed (exit 120, e.g. after the Mac
   sleeps). When it prints `{}` (timed out, no job) or exits 120, just start it again — no message to
   the user unless it keeps failing.

## 2. When the watcher exits it prints one pending job (JSON with `_path`)
1. `python3 $S/jobqueue.py start <_path>` (app shows "running").
2. Post short progress notes as you go: `python3 $S/jobqueue.py note <_path> "placed sofa, armchair…"`.
3. Run the job (table below), then `done <_path> "<one-line result>"` or `fail <_path> "<reason>"`.
4. Restart the watcher (step 1.3) immediately — also after a failure. Then tell the user in one line
   what finished.

`S=.claude/scripts/scene-forge`, `F=worlds/<slug>/forge`. All work follows the `scene-forge` skill and
its references — the app only decides WHEN, not HOW.

| job type | params | do |
|---|---|---|
| `analyze` | – | scene-forge step 2 on `$F/reference.png`: objects with bbox, dims_m, desc, **structure**, **colour hex**, mount/contact_v/support_z, coverage sweep, `ignore` boxes for watermarks/text. Write `$F/analysis.json`, run `crop.py`, copy crops to `flow-upload/`. The user edits boxes in the app afterwards. |
| `views` | `objects[]`, `angles` 4/8, `regenerate` | one background `Agent(scene-forge-views)` per object (<= 6 at a time) with `--angles`; gate A with `qc_sheet.py`; note per object. |
| `place` | – | camera solve + room if `analysis.camera` is empty (camera-solve.md, verify the lens on a table top), then `place_object` for every GLB, `pose_search` for floor objects, height/stand fixes (verify-loop.md). Then, if `plate/2-plate.png` exists (make it if not — SKILL 5b), `build_plate_room` so the walls match the photo in Blender (SKILL 7b). Render to `$F/loop/iterNN.png`, `compare.py`, write `$F/placement.json` (below). |
| `lightfit` | – | backup blend, `light_basis.render_basis` in chunks, `fit_lights.py`, `apply_fit()`, exposure match, AgX vs Standard, keep the better; render + compare. |
| `verify` | `iterations` | `Agent(scene-forge-verifier)` (foreground) with the budget; it renders + compares each iteration (scores land in `$F/scores.json` automatically). |
| `final` | – | Cycles full-res `final-render.png` (start the render via `bpy.app.timers`, poll for the file), `side-by-side.jpg`, `qc_sheet.py --render final-render.png`. If the project uses a clean plate (`plate/2-plate.png` exists): `plate_mode.render_plate_passes()` then `plate_composite.py comp2 … --shadow 0.4`; the scene must end in EDIT mode (walls visible). |
| `custom` | `task: "fix-object"`, `object`, `note` | read the note + the object's check crops; fix only that object (pose_search / fit_bbox / move / regenerate views or Meshy if the shape is wrong); re-render, update `placement.json`. |
| `custom` | `task: "replace-model"`, `object` | the user swapped `objects/<object>/1-<object>.glb` in the app (library model, upload, restored version or a Meshy re-run). In Blender: note the old `F_<object>` root's world matrix + bbox, delete its meshes, `import_glb`, put the new root on the same spot, `fit_bbox` to the reference bbox (keep `height`/support rules), `pose_search` if it's a floor object, re-apply ForgeTint/ForgeGain from the old materials only if it's the same model family. Render + compare, update `placement.json`. Old versions live in `objects/<object>/versions/` — never delete them. |
| `custom` | `task: "qc"` | `qc_sheet.py --render <latest>` and refresh `placement.json` for every object. |

Meshy is run by the app itself (Generate with Meshy / Start buttons call `meshy.py`); only run it
yourself if a job asks.

## placement.json (shown on the app's Check page)
After `place`, `custom` and `verify`, write `$F/placement.json`:
```json
{"sofa": {"status": "ok", "yaw": 0, "size_m": [1.95, 0.82, 0.79], "box_err_px": 4, "note": "back against wall"},
 "bench": {"status": "issue", "yaw": 75, "note": "legs thinner than reference — model shape"}}
```
`status` is `ok` or `issue`; `box_err_px` = max |projected bbox − reference bbox| in reference px.
Be honest: "issue" whenever the crop pair still differs in position, facing, shape or colour.

## Rules
- Never overwrite the user's own .blend; work in `$F/scene-forge.blend`, back up before light fits.
- A job that needs something missing (Blender not connected, Higgsfield not authorised, no views) ->
  `fail` with the exact fix for the user; don't half-run it.
- Don't start your own jobs from the queue; only what the app (user) created.

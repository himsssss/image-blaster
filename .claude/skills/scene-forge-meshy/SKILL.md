---
name: scene-forge-meshy
description: Turn ONE scene-forge object's views into a textured GLB with the Meshy multi-image-to-3D API. Use when the prompt names a world slug and exactly one object whose views/ folder is ready.
argument-hint: [world-slug] [object-name] [--resume] [--polycount N] [--model latest|meshy-6]
allowed-tools: Read Glob Bash(ls *) Bash(python3 .claude/scripts/scene-forge/meshy.py *) Bash(tail *)
context: fork
agent: scene-forge-meshy
---

Create the 3D model for object `$1` in `worlds/$0/forge`.

1. `ls -a worlds/$0/forge/objects/$1/ worlds/$0/forge/objects/$1/views/`.
   - `1-$1.glb` exists and no `--regenerate` -> report it and stop.
   - `.1-$1-request.json` exists without a GLB -> run with `--resume` (never pay twice).
   - no views -> stop and report (run scene-forge-views first).
2. Run from the repo root, synchronously (it polls until done, ~3-6 min):
   `python3 .claude/scripts/scene-forge/meshy.py worlds/$0/forge $1 [--polycount N] [--model M]`
   The script sends up to 4 views (front first), the analysis.json `desc` as texture prompt,
   PBR on, remesh 60k, `image_enhancement: false`.
3. On `HTTP 429` (too many concurrent Meshy tasks): wait 60 s and retry, up to 5 times.
   On `402`: stop and report "out of Meshy credits".

4. QC gate after the GLB arrives: `python3 .claude/scripts/scene-forge/qc_sheet.py worlds/$0/forge --objects $1 --out qc-$1.jpg`
   and compare the meshy column with the nano front + reference crop:
   - hue drift (beige -> pink/mauve/grey happened on the living room with texture_prompt): rerun with
     the default `--texture-guide views` (texture from the views); if it still drifts, report it.
   - missing/merged parts (legs fused, seams gone, cushions blobbed): report "needs regeneration" with
     the exact part — don't let placement try to hide it.
   Texture guidance is `views` by default (texture_image_urls = the same views); `--texture-guide prompt`
   only when the views themselves have wrong colours.

Report: object, GLB path, credits consumed, Meshy task id, QC verdict (shape ok / hue ok / issues).

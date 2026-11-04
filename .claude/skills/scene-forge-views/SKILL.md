---
name: scene-forge-views
description: Generate multi-angle Nano Banana 2.1 views (via Higgsfield) of ONE scene-forge object — a front product view plus a turnaround sheet with every other angle, split into separate images — ready for Meshy multi-image-to-3D. Use when the prompt names a world slug and exactly one object from its forge analysis.json.
argument-hint: [world-slug] [object-name] [--angles 4|8] [--mode sheet|separate] [--regenerate view1,view2]
context: fork
agent: scene-forge-views
---

Generate views for object `$1` in project `worlds/$0/forge`.
Defaults: `--mode sheet`, `--angles 4` (2x2). `--angles 8` = 3x3 full orbit + top view.

1. Read `worlds/$0/forge/analysis.json`; find the object. Stop if missing or not `source: meshy`.
   Stop and report if it has no `structure` notes — views without them invent bases/legs.
   Every prompt (front, sheet, single views) includes the structure block and the `colour` hex.
2. `ls -a worlds/$0/forge/objects/$1/views/` — skip work whose views already exist unless `--regenerate`.
3. Read `.claude/skills/scene-forge/references/views-prompts.md` and follow it:
   a. upload `objects/$1/0-crop.png` (media_upload -> curl PUT -> media_confirm), or reuse the media id
      recorded in `views-jobs.json`;
   b. **front view** (2k) from the crop -> save as `$1-front.png` with `fetch_view.sh`;
   c. **turnaround sheet** (4k) with the front job id + crop as references, grid and cell list for this
      object type (`mount`, or plant/decor) from the table -> save the sheet as
      `objects/$1/2-$1-sheet.png` (`curl -sf -o ... <result_url>`);
   d. split: `python3 .claude/scripts/scene-forge/split_sheet.py worlds/$0/forge/objects/$1/2-$1-sheet.png worlds/$0/forge $1 --grid <g> --views <list>`
      — run it AFTER saving the front view and pass the list without `front` duplicated if the
      standalone front is better (default: keep the standalone 2k front, so list the sheet's front
      cell as `sheetfront`);
   e. any `BAD` cell, or a cell showing a different object -> regenerate that angle alone with the
      single-view prompt (front job id as reference), max 2 retries.
   `--mode separate`: skip c/d and generate each angle as its own 2k image (batches <= 6).
4. Record media id, front job id, sheet job id under `"$1"` in `worlds/$0/forge/views-jobs.json`
   (merge, don't overwrite other objects).
5. QC gate: `python3 .claude/scripts/scene-forge/qc_sheet.py worlds/$0/forge --objects $1 --out qc-$1.jpg`,
   look at it once and tick each structure note and the hue against the reference crop. Mismatch ->
   regenerate the front with the mismatch named ("NOT a cross base", "warm beige #a8927c, not grey"),
   then the sheet (max 2 retries). Report any note that still fails — don't pass it on silently.

Report: object, saved view files, credits used (front 2 + sheet 3 + retries), anything still off.

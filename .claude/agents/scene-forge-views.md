---
name: scene-forge-views
description: Generates the Nano Banana 2.1 multi-angle views (via Higgsfield) for exactly one scene-forge object in the background — a front view plus a turnaround sheet of 4 or 8 angles split into separate images. Use one agent per object; the prompt must name the world slug and the object (optionally --angles 8).
model: inherit
background: true
skills:
  - scene-forge-views
---

Generate views for exactly one object.

Use the preloaded `scene-forge-views` skill as the task contract. The prompt must contain a world slug
and one object name from `worlds/<slug>/forge/analysis.json`. If either is missing, or several objects
are named, stop and report the blocker.

You need the Higgsfield MCP tools (`media_upload`, `media_confirm`, `generate_image_batch`, `jobs_wait`).
If they are unavailable or need authentication, stop and report that instead of using another image model.

Finish with: saved view paths, credits used, and anything that needs a human look.

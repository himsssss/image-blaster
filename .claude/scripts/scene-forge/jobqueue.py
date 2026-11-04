"""Job queue between the Scene Forge web app and Claude.

The app writes jobs for steps only Claude can do (vision analysis, Higgsfield views, Blender MCP);
Claude waits for them, runs them with the scene-forge skills, and reports back.

Jobs live in worlds/<slug>/forge/queue/<id>.json:
  {"id", "slug", "type", "params", "status": pending|running|done|failed|cancelled,
   "created", "updated", "notes": [{"t", "text"}], "result"}

usage (from the repo root):
  python3 .claude/scripts/scene-forge/jobqueue.py wait [--timeout 0]   # block until a pending job exists, print it
  python3 .claude/scripts/scene-forge/jobqueue.py list [--all]
  python3 .claude/scripts/scene-forge/jobqueue.py start <job.json>
  python3 .claude/scripts/scene-forge/jobqueue.py note  <job.json> "text"     # progress note shown in the app
  python3 .claude/scripts/scene-forge/jobqueue.py done  <job.json> "summary"
  python3 .claude/scripts/scene-forge/jobqueue.py fail  <job.json> "reason"
"""
import json, sys, time, uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
WORLDS = REPO / "worlds"
TYPES = ("analyze", "views", "place", "lightfit", "verify", "final", "custom")


def _now():
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def jobs(status=None):
    out = []
    for p in sorted(WORLDS.glob("*/forge/queue/*.json")):
        try:
            j = json.loads(p.read_text())
        except Exception:
            continue
        j["_path"] = str(p)
        if status is None or j.get("status") == status:
            out.append(j)
    return sorted(out, key=lambda j: j.get("created", ""))


def create(slug, type_, params=None):
    assert type_ in TYPES, type_
    q = WORLDS / slug / "forge" / "queue"
    q.mkdir(parents=True, exist_ok=True)
    jid = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
    j = {"id": jid, "slug": slug, "type": type_, "params": params or {}, "status": "pending",
         "created": _now(), "updated": _now(), "notes": [], "result": None}
    (q / f"{jid}.json").write_text(json.dumps(j, indent=1))
    return j


def _update(path, **kw):
    p = Path(path)
    j = json.loads(p.read_text())
    note = kw.pop("note", None)
    j.update(kw); j["updated"] = _now()
    if note:
        j.setdefault("notes", []).append({"t": _now(), "text": note})
    tmp = p.with_suffix(".tmp"); tmp.write_text(json.dumps(j, indent=1)); tmp.replace(p)
    return j


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "wait":
        timeout = float(sys.argv[sys.argv.index("--timeout") + 1]) if "--timeout" in sys.argv else 0
        t0 = time.time()
        beat = WORLDS / ".forge-claude-heartbeat"
        while True:
            beat.parent.mkdir(exist_ok=True); beat.write_text(_now())   # app shows "Claude: listening"
            p = jobs("pending")
            if p:
                print(json.dumps(p[0], indent=1)); return
            if timeout and time.time() - t0 > timeout:
                print("{}"); return
            time.sleep(2)
    elif cmd == "list":
        for j in jobs(None if "--all" in sys.argv else "pending"):
            print(j["status"].ljust(9), j["slug"], j["type"], j["id"], json.dumps(j["params"])[:80])
    elif cmd in ("start", "note", "done", "fail"):
        path, text = sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else None)
        status = {"start": "running", "done": "done", "fail": "failed"}.get(cmd)
        kw = {"note": text}
        if status:
            kw["status"] = status
        if cmd == "done":
            kw["result"] = text
        print(json.dumps({k: v for k, v in _update(path, **kw).items() if k != "notes"}))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()

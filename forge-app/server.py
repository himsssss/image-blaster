"""Scene Forge local web app (stdlib + Pillow). Serves the UI and a JSON API over worlds/<slug>/forge.

  python3 forge-app/server.py [--port 8770]

What the app does itself: upload/init, analysis editing, crops, Meshy (direct API via meshy.py),
file serving, crops for side-by-side checks, scores.
What it queues for Claude (jobqueue.py): analyze, views (Higgsfield), place, lightfit, verify, final.
"""
import argparse, base64, io, json, mimetypes, re, subprocess, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

REPO = Path(__file__).resolve().parents[1]
S = REPO / ".claude" / "scripts" / "scene-forge"
WORLDS = REPO / "worlds"
STATIC = Path(__file__).parent / "static"
sys.path.insert(0, str(S))
import jobqueue  # noqa: E402

SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
MESHY_MAX = 8
_meshy_lock = threading.Lock()
_meshy_running = {}   # (slug, obj) -> Popen


def forge(slug):
    if not SLUG.match(slug):
        raise ValueError("bad slug")
    return WORLDS / slug / "forge"


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def meshy_status(f, name):
    obj = f / "objects" / name
    if (obj / f"1-{name}.glb").exists():
        return {"status": "done", "progress": 100}
    if _meshy_running.get((f.parent.name, name)) and _meshy_running[(f.parent.name, name)].poll() is None:
        st = "running"
    else:
        st = None
    log = f / "meshy-logs" / f"{name}.log"
    if log.exists():
        lines = [l for l in log.read_text().splitlines() if l.strip()]
        last = lines[-1] if lines else ""
        m = re.search(r"(PENDING|IN_PROGRESS|SUCCEEDED|FAILED)\s+(\d+)", last)
        if m:
            return {"status": st or ("failed" if m.group(1) == "FAILED" else "stalled"), "progress": int(m.group(2)), "last": last[-160:]}
        if "Error" in last or "Traceback" in log.read_text()[-400:] or last.startswith(("402", "failed")):
            return {"status": "failed", "progress": 0, "last": last[-160:]}
        return {"status": st or "queued", "progress": 0, "last": last[-160:]}
    return {"status": st or "none", "progress": 0}


def state(slug):
    f = forge(slug)
    an = read_json(f / "analysis.json", {}) or {}
    objs = []
    for o in an.get("objects", []):
        n = o["name"]; d = f / "objects" / n
        views = sorted(p.name for p in (d / "views").glob("*.png")) if (d / "views").exists() else []
        objs.append({**o,
                     "crop": (d / "0-crop.png").exists(),
                     "views": views,
                     "glb": (d / f"1-{n}.glb").exists(),
                     "thumb": (d / f"1-{n}-thumb.png").exists(),
                     "versions": len(list((d / "versions").glob("*.glb"))) if (d / "versions").exists() else 0,
                     "model_source": (read_json(d / "model.json", {}) or {}).get("source", "meshy"),
                     "meshy": meshy_status(f, n) if o.get("source") == "meshy" else None})
    loop = []
    for p in sorted((f / "loop").glob("*-compare.jpg"), key=lambda p: p.stat().st_mtime):
        loop.append({"tag": p.name[:-12], "compare": f"loop/{p.name}", "t": p.stat().st_mtime})
    scores = read_json(f / "scores.json", {}) or {}
    jobs = [j for j in jobqueue.jobs() if j["slug"] == slug]
    for j in jobs:
        j.pop("_path", None)
    placement = read_json(f / "placement.json", {}) or {}
    cands = [p for p in (f / "loop").glob("*.png") if not p.name.startswith("_")] + \
            [p for p in f.glob("final-render*.png")]
    renders = [str(p.relative_to(f)) for p in sorted(cands, key=lambda p: p.stat().st_mtime)[-14:]]  # newest last
    beat = WORLDS / ".forge-claude-heartbeat"
    age = time.time() - beat.stat().st_mtime if beat.exists() else 1e9
    working = any(j["status"] == "running" for j in jobqueue.jobs())
    return {
        "claude": "working" if working else ("listening" if age < 15 else "offline"),
        "renders": renders,
        "slug": slug,
        "reference": (f / "reference.png").exists(),
        "size": an.get("size"),
        "analysis": an,
        "objects": objs,
        "loop": loop[-30:],
        "scores": scores,
        "placement": placement,
        "jobs": jobs[-40:],
        "blend_bytes": (f / "scene-forge.blend").stat().st_size if (f / "scene-forge.blend").exists() else 0,
        "files": {k: (f / k).exists() for k in ("qc-sheet.jpg", "final-render.png", "side-by-side.jpg",
                                                  "scene-forge.blend", "loop/basis/fit-preview.png")},
        "meshy_key": _has_key("MESHY_API_KEY"),
        "final": final_info(f),
        "meshy_credits": meshy_estimate(f, objs),
    }


_balance = {"t": 0, "value": None, "error": None}


def meshy_balance():
    """Meshy credit balance, cached 60 s (the UI polls every 3 s)."""
    if time.time() - _balance["t"] < 60:
        return _balance["value"], _balance["error"]
    _balance["t"] = time.time()
    key = next((l.split("=", 1)[1].strip().strip('"') for l in (REPO / ".env").read_text().splitlines()
                if l.startswith("MESHY_API_KEY=")), "") if (REPO / ".env").exists() else ""
    if not key:
        _balance.update(value=None, error="no key"); return None, "no key"
    try:
        import urllib.request
        req = urllib.request.Request("https://api.meshy.ai/openapi/v1/balance", headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req, timeout=8) as r:
            _balance.update(value=json.loads(r.read()).get("balance"), error=None)
    except Exception as e:
        _balance.update(value=None, error=type(e).__name__)
    return _balance["value"], _balance["error"]


def meshy_estimate(f, objs):
    """Credits to generate every meshy object that has no GLB yet, priced from past consumed_credits."""
    spent = []
    for p in WORLDS.glob("*/forge/objects/*/.1-*-request.json"):   # all projects: better average
        c = (read_json(p, {}) or {}).get("response", {}).get("consumed_credits")
        if c:
            spent.append(c)
    per = round(sum(spent) / len(spent)) if spent else 30
    todo = [o["name"] for o in objs if o.get("source") == "meshy" and not o["glb"]
            and o.get("meshy", {}).get("status") not in ("running",)]
    bal, err = meshy_balance()
    return {"per_object": per, "pending": len(todo), "total": per * len(todo), "balance": bal,
            "balance_error": err, "priced_from": len(spent)}


def _has_key(k):
    env = REPO / ".env"
    return env.exists() and any(l.startswith(k + "=") and len(l.strip()) > len(k) + 1 for l in env.read_text().splitlines())


def run_meshy(slug, names):
    f = forge(slug)
    (f / "meshy-logs").mkdir(exist_ok=True)
    started = []
    with _meshy_lock:
        for n in names:
            if (f / "objects" / n / f"1-{n}.glb").exists():
                continue
            p = _meshy_running.get((slug, n))
            if p and p.poll() is None:
                continue
            if sum(1 for q in _meshy_running.values() if q.poll() is None) >= MESHY_MAX:
                break
            args = [sys.executable, str(S / "meshy.py"), str(f), n]
            if (f / "objects" / n / f".1-{n}-request.json").exists():
                args.append("--resume")
            log = open(f / "meshy-logs" / f"{n}.log", "a")
            _meshy_running[(slug, n)] = subprocess.Popen(args, cwd=REPO, stdout=log, stderr=subprocess.STDOUT)
            started.append(n)
    return started


# ---------- library: project snapshots + every generated 3D model ----------
SNAP_FILES = ("analysis.json", "placement.json", "scores.json", "layout.json", "room3d/room3d.json",
              "side-by-side.jpg", "problems.md")


_last_stamp = [""]


def _stamp():
    """Unique, sortable id. Two actions in the same second must never share a name: a restore archives the
    current model and then moves the chosen version in, and equal names would overwrite one with the other."""
    with _meshy_lock:
        st = time.strftime("%Y%m%d-%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"
        while st <= _last_stamp[0]:
            st = st[:-3] + f"{int(st[-3:]) + 1:03d}"
        _last_stamp[0] = st
        return st


def _latest_render(f):
    cands = [p for p in (f / "loop").glob("iter*.png")] + list(f.glob("final-render*.png"))
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def _thumb(src, dst, w=640):
    from PIL import Image
    im = Image.open(src).convert("RGB"); im.thumbnail((w, w)); dst.parent.mkdir(parents=True, exist_ok=True)
    im.save(dst, "JPEG", quality=85)


MODEL_CATS = {   # first keyword match wins (checked in this order)
    "Lighting": ("lamp", "sconce", "chandelier", "pendant", "light", "bulb", "lantern"),
    "Seating": ("sofa", "couch", "armchair", "chair", "bench", "stool", "ottoman", "pouf", "seat"),
    "Tables": ("table", "desk", "console", "nightstand", "sideboard"),
    "Storage": ("cabinet", "shelf", "wardrobe", "drawer", "bookcase", "dresser", "rack"),
    "Beds": ("bed", "crib", "mattress"),
    "Plants": ("plant", "tree", "flower", "pot", "succulent"),
    "Textiles": ("rug", "carpet", "curtain", "blanket", "cushion", "pillow", "throw"),
    "Fixtures": ("fan", "tv", "television", "fireplace", "radiator", "door", "window", "appliance"),
    "Decor": ("decor", "vase", "art", "sculpture", "frame", "mirror", "clock", "book", "bowl", "tray", "candle"),
}
ROOM_CATS = {"Living room": ("living", "lounge", "family"), "Bedroom": ("bed",), "Kitchen": ("kitchen",),
             "Dining": ("dining",), "Bathroom": ("bath", "toilet", "wash"), "Office": ("office", "study", "work"),
             "Outdoor": ("outdoor", "garden", "patio", "balcony", "terrace")}


def guess_category(name, table=MODEL_CATS):
    n = name.lower()
    if table is MODEL_CATS and any(k in n for k in ("decor", "vase", "sculpture")):   # "table-decor" is decor
        return "Decor"
    return next((c for c, keys in table.items() if any(k in n for k in keys)), "Other")


def set_model_category(slug, rel, category):
    p = _models_dir_path(slug, rel)
    meta_p = p.parent / "model.json" if p.name.startswith("1-") else p.with_suffix(".json")
    meta = read_json(meta_p, {}) or {}
    meta["category"] = category[:40]
    meta_p.write_text(json.dumps(meta, indent=1))
    return {"ok": True}


def project_meta(f):
    return read_json(f / "project-meta.json", {}) or {}


def library_projects():
    out = []
    for f in sorted(WORLDS.glob("*/forge")):
        an = read_json(f / "analysis.json", {}) or {}
        objs = [o["name"] for o in an.get("objects", []) if o.get("source") == "meshy"]
        lr = _latest_render(f)
        scores = read_json(f / "scores.json", {}) or {}
        last = list(scores.items())[-1] if scores else None
        snaps = []
        for m in sorted((f / "library").glob("*/meta.json"), reverse=True):
            meta = read_json(m, {}) or {}
            snaps.append({**meta, "id": m.parent.name})
        out.append({"slug": f.parent.name, "objects": len(an.get("objects", [])),
                    "category": project_meta(f).get("category") or guess_category(f.parent.name, ROOM_CATS),
                    "models": sum((f / "objects" / n / f"1-{n}.glb").exists() for n in objs), "meshy_objects": len(objs),
                    "updated": max([f.stat().st_mtime] + [p.stat().st_mtime for p in f.glob("*") if p.is_file()]),
                    "reference": (f / "reference.png").exists(),
                    "render": str(lr.relative_to(f)) if lr else None,
                    "blend": (f / "scene-forge.blend").exists(),
                    "score": {"tag": last[0], **last[1]} if last else None, "snapshots": snaps})
    return sorted(out, key=lambda p: -p["updated"])


def save_snapshot(slug, name, note="", blend=False):
    f = forge(slug); sid = _stamp(); d = f / "library" / sid
    d.mkdir(parents=True)
    kept = []
    for rel in SNAP_FILES:
        if (f / rel).exists():
            (d / rel).parent.mkdir(parents=True, exist_ok=True); (d / rel).write_bytes((f / rel).read_bytes()); kept.append(rel)
    lr = _latest_render(f)
    if lr:
        _thumb(lr, d / "render.jpg")
    if (f / "reference.png").exists():
        _thumb(f / "reference.png", d / "reference.jpg", 400)
    models = {}
    for g in (f / "objects").glob("*/1-*.glb"):
        models[g.parent.name] = {"bytes": g.stat().st_size, "mtime": g.stat().st_mtime}
    if blend and (f / "scene-forge.blend").exists():
        import shutil
        shutil.copy2(f / "scene-forge.blend", d / "scene-forge.blend"); kept.append("scene-forge.blend")
    meta = {"name": name or sid, "note": note, "created": time.time(), "files": kept, "models": models,
            "render": "render.jpg" if lr else None, "score": list((read_json(f / "scores.json", {}) or {}).items())[-1:] }
    (d / "meta.json").write_text(json.dumps(meta, indent=1))
    return {**meta, "id": sid}


def restore_snapshot(slug, sid):
    f = forge(slug); d = f / "library" / sid
    assert (d / "meta.json").exists(), "no such snapshot"
    save_snapshot(slug, f"auto-backup before restoring {sid}", blend=False)   # never lose the current state
    restored = []
    for rel in (read_json(d / "meta.json", {}) or {}).get("files", []):
        if rel in SNAP_FILES or rel == "scene-forge.blend":
            (f / rel).parent.mkdir(parents=True, exist_ok=True); (f / rel).write_bytes((d / rel).read_bytes()); restored.append(rel)
    return restored


def library_models():
    """Every 3D model ever generated or placed: current GLBs and archived versions, all projects."""
    out = []
    for f in sorted(WORLDS.glob("*/forge")):
        slug = f.parent.name
        for od in sorted(p for p in (f / "objects").glob("*") if p.is_dir()):
            n = od.name
            cur = od / f"1-{n}.glb"
            if cur.exists():
                meta = read_json(od / "model.json", {}) or {}
                out.append({"slug": slug, "object": n, "path": str(cur.relative_to(f)), "current": True,
                            "thumb": str((od / f"1-{n}-thumb.png").relative_to(f)) if (od / f"1-{n}-thumb.png").exists() else None,
                            "bytes": cur.stat().st_size, "mtime": cur.stat().st_mtime, "source": meta.get("source", "meshy"),
                            "label": meta.get("label", ""), "category": meta.get("category") or guess_category(n)})
            for g in sorted((od / "versions").glob("*.glb"), reverse=True):
                meta = read_json(g.with_suffix(".json"), {}) or {}
                th = g.with_name(g.stem + "-thumb.png")
                out.append({"slug": slug, "object": n, "path": str(g.relative_to(f)), "current": False,
                            "thumb": str(th.relative_to(f)) if th.exists() else None, "version": g.stem[: -len(n) - 1],
                            "bytes": g.stat().st_size, "mtime": g.stat().st_mtime, "source": meta.get("source", "meshy"),
                            "label": meta.get("label", ""), "category": meta.get("category") or guess_category(n)})
    return sorted(out, key=lambda m: -m["mtime"])


def _archive_current(f, n, why):
    """Move objects/<n>/1-<n>.glb (+ thumb, request, model.json) into objects/<n>/versions/<stamp>-<n>.*"""
    od = f / "objects" / n; cur = od / f"1-{n}.glb"
    if not cur.exists():
        return None
    v = od / "versions"; v.mkdir(exist_ok=True); st = _stamp()
    meta = read_json(od / "model.json", {}) or {"source": "meshy"}
    req = read_json(od / f".1-{n}-request.json")
    cur.rename(v / f"{st}-{n}.glb")
    if (od / f"1-{n}-thumb.png").exists():
        (od / f"1-{n}-thumb.png").rename(v / f"{st}-{n}-thumb.png")
    if (od / f".1-{n}-request.json").exists():
        (od / f".1-{n}-request.json").rename(v / f".{st}-{n}-request.json")
    if (od / "model.json").exists():
        (od / "model.json").unlink()
    (v / f"{st}-{n}.json").write_text(json.dumps({**meta, "archived": time.time(), "why": why,
                                                     "meshy_task": (req or {}).get("task_id") or (req or {}).get("response", {}).get("id")}, indent=1))
    return st


def _models_dir_path(slug, rel):
    f = forge(slug); p = (f / rel).resolve()
    assert f.resolve() in p.parents and p.suffix == ".glb", "bad model path"
    return p


def model_action(slug, b):
    f = forge(slug); n = b["object"]; od = f / "objects" / n
    assert SLUG.match(n), "bad object"
    od.mkdir(parents=True, exist_ok=True)
    cur = od / f"1-{n}.glb"
    act = b["action"]
    if act == "use":                       # take any model from the library
        src = _models_dir_path(b["from_slug"], b["from_path"])
        data = src.read_bytes(); th = src.with_name(src.stem + "-thumb.png")
        smeta = read_json(src.parent / "model.json" if src.name.startswith("1-") else src.with_suffix(".json"), {}) or {}
        _archive_current(f, n, f"replaced with {b['from_slug']}/{b['from_path']}")
        cur.write_bytes(data)
        if th.exists():
            (od / f"1-{n}-thumb.png").write_bytes(th.read_bytes())
        (od / "model.json").write_text(json.dumps({"source": "library", "from": f"{b['from_slug']}/{b['from_path']}",
                                                   "label": b.get("label", ""), "t": time.time(),
                                                   **({"category": smeta["category"]} if smeta.get("category") else {})}, indent=1))
        return {"ok": True, "placed": False}
    if act == "upload":                    # user's own .glb
        raw = base64.b64decode(b["data"].split(",", 1)[-1])
        assert raw[:4] == b"glTF", "not a binary glTF (.glb) file"
        _archive_current(f, n, "replaced by upload")
        cur.write_bytes(raw)
        (od / "model.json").write_text(json.dumps({"source": "upload", "label": b.get("filename", ""), "t": time.time()}, indent=1))
        return {"ok": True}
    if act == "regenerate":                # new Meshy run, old model kept as a version
        _archive_current(f, n, "regenerated with Meshy")
        log = f / "meshy-logs" / f"{n}.log"
        if log.exists():
            log.rename(log.with_name(f"{n}-{_stamp()}.log"))
        return {"ok": True, "started": run_meshy(slug, [n])}
    if act == "restore":                   # bring an archived version back
        src = _models_dir_path(slug, b["path"])
        assert src.parent == od / "versions", "not a version of this object"
        th = src.with_name(src.stem + "-thumb.png"); meta = read_json(src.with_suffix(".json"), {}) or {}
        _archive_current(f, n, f"swapped for version {src.stem}")
        src.rename(cur)
        if th.exists():
            th.rename(od / f"1-{n}-thumb.png")
        if src.with_suffix(".json").exists():
            src.with_suffix(".json").unlink()
        (od / "model.json").write_text(json.dumps({**{k: v for k, v in meta.items() if k in ("source", "from", "label", "category")},
                                                   "restored": src.stem, "t": time.time()}, indent=1))
        return {"ok": True}
    raise ValueError("unknown action")


# ---------- final project: the finished .blend and its outputs ----------
def final_info(f):
    def fileinfo(p):
        return {"path": str(p.relative_to(f)), "bytes": p.stat().st_size, "mtime": p.stat().st_mtime}
    blend = f / "scene-forge.blend"
    snaps = []
    for m in sorted((f / "library").glob("*/scene-forge.blend"), reverse=True):
        meta = read_json(m.parent / "meta.json", {}) or {}
        snaps.append({**fileinfo(m), "name": meta.get("name", m.parent.name), "id": m.parent.name})
    outs = [p for p in [*f.glob("final-render*.png"), f / "side-by-side.jpg", f / "camera-angles.jpg"] if p.exists()]
    lr = _latest_render(f)
    if lr and lr not in outs:
        outs.append(lr)
    outs.sort(key=lambda p: -p.stat().st_mtime)
    return {"blend": fileinfo(blend) if blend.exists() else None, "snapshot_blends": snaps,
            "outputs": [fileinfo(p) for p in outs],
            "problems": (f / "problems.md").read_text()[:20000] if (f / "problems.md").exists() else "",
            "blender_app": _blender_app() is not None}


def _blender_app():
    for p in ("/Applications/Blender.app", str(Path.home() / "Applications/Blender.app")):
        if Path(p).exists():
            return p
    return None


def open_blend(slug, rel, how="open"):
    """Open a project's .blend in Blender (or reveal it in Finder). Only .blend files inside this project."""
    f = forge(slug); p = (f / rel).resolve()
    assert f.resolve() in p.parents and p.suffix == ".blend" and p.exists(), "not a .blend of this project"
    if how == "reveal":
        subprocess.Popen(["/usr/bin/open", "-R", str(p)]); return {"ok": True}
    app = _blender_app()
    assert app, "Blender.app not found in /Applications"
    subprocess.Popen(["/usr/bin/open", "-a", app, str(p)])
    return {"ok": True, "app": app}


def crop_png(slug, src, bbox, pad=0.1, h=320):
    from PIL import Image
    f = forge(slug)
    p = (f / src).resolve()
    assert f.resolve() in p.parents
    an = read_json(f / "analysis.json", {})
    im = Image.open(p).convert("RGB")
    W, H = an.get("size") or im.size
    if im.size != (W, H):
        im = im.resize((W, H))
    x0, y0, x1, y1 = bbox
    pd = int(pad * max(x1 - x0, y1 - y0))
    c = im.crop((max(0, x0 - pd), max(0, y0 - pd), min(W, x1 + pd), min(H, y1 + pd)))
    c.thumbnail((h * 2, h))
    buf = io.BytesIO(); c.save(buf, "JPEG", quality=85)
    return buf.getvalue()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body).encode()
        elif isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers(); self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        u = urlparse(self.path); parts = [p for p in u.path.split("/") if p]
        try:
            if not parts or parts[0] in ("index.html",):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if parts[0] == "static":
                p = (STATIC / "/".join(parts[1:])).resolve()
                assert STATIC.resolve() in p.parents
                return self._send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "application/octet-stream")
            if parts[:2] == ["api", "projects"]:
                out = []
                for d in sorted(WORLDS.glob("*/forge")):
                    an = read_json(d / "analysis.json", {}) or {}
                    out.append({"slug": d.parent.name, "objects": len(an.get("objects", [])),
                                "updated": d.stat().st_mtime, "reference": (d / "reference.png").exists()})
                return self._send(200, out)
            if parts[:2] == ["api", "library"]:
                if parts[2:] == ["projects"]:
                    return self._send(200, library_projects())
                if parts[2:] == ["models"]:
                    return self._send(200, library_models())
            if parts[0] == "api" and len(parts) >= 4 and parts[1] == "p":
                slug, what = parts[2], parts[3]
                if what == "state":
                    return self._send(200, state(slug))
                if what == "crop":
                    q = parse_qs(u.query)
                    bbox = [int(float(v)) for v in q["bbox"][0].split(",")]
                    return self._send(200, crop_png(slug, q["src"][0], bbox), "image/jpeg")
            if parts[0] == "files" and len(parts) >= 3:
                f = forge(parts[1]); p = (f / "/".join(parts[2:])).resolve()
                assert f.resolve() in p.parents
                ctype = "model/gltf-binary" if p.suffix == ".glb" else (mimetypes.guess_type(p.name)[0] or "application/octet-stream")
                return self._send(200, p.read_bytes(), ctype)
            self._send(404, {"error": "not found"})
        except FileNotFoundError:
            self._send(404, {"error": "missing"})
        except Exception as e:
            self._send(400, {"error": str(e)})

    def do_POST(self):
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        try:
            b = self._body()
            if parts[:3] == ["api", "library", "category"]:
                return self._send(200, set_model_category(b["slug"], b["path"], b["category"]))
            if parts[:2] == ["api", "projects"]:
                slug = b["slug"].strip().lower().replace(" ", "-")
                forge(slug)  # validates
                raw = base64.b64decode(b["data"].split(",", 1)[-1])
                up = WORLDS / slug / "source"; up.mkdir(parents=True, exist_ok=True)
                ext = Path(b.get("filename", "image.png")).suffix.lower() or ".png"
                src = up / f"0-{slug}{ext}"
                src.write_bytes(raw)
                r = subprocess.run([sys.executable, str(S / "init_forge.py"), str(src), slug], cwd=REPO,
                                   capture_output=True, text=True)
                if r.returncode:
                    return self._send(500, {"error": r.stderr[-400:]})
                return self._send(200, {"slug": slug})
            if parts[0] == "api" and parts[1] == "p":
                slug, what = parts[2], parts[3]; f = forge(slug)
                if what == "analysis":
                    an = b["analysis"]
                    (f / "analysis.json").write_text(json.dumps(an, indent=1))
                    return self._send(200, {"ok": True})
                if what == "crops":
                    r = subprocess.run([sys.executable, str(S / "crop.py"), str(f)], cwd=REPO, capture_output=True, text=True)
                    return self._send(200 if not r.returncode else 500, {"out": r.stdout[-2000:], "err": r.stderr[-800:]})
                if what == "meshy":
                    an = read_json(f / "analysis.json", {})
                    names = b.get("objects") or [o["name"] for o in an.get("objects", []) if o.get("source") == "meshy"]
                    (f / "meshy-want.json").write_text(json.dumps(names))   # pump starts the rest as slots free
                    return self._send(200, {"started": run_meshy(slug, names), "queued": names})
                if what == "snapshot":
                    return self._send(200, save_snapshot(slug, b.get("name", ""), b.get("note", ""), bool(b.get("blend"))))
                if what == "restore":
                    return self._send(200, {"restored": restore_snapshot(slug, b["id"])})
                if what == "model":
                    return self._send(200, model_action(slug, b))
                if what == "open-blend":
                    return self._send(200, open_blend(slug, b.get("path", "scene-forge.blend"), b.get("how", "open")))
                if what == "category":
                    meta = project_meta(f); meta["category"] = b["category"][:40]
                    (f / "project-meta.json").write_text(json.dumps(meta, indent=1))
                    return self._send(200, {"ok": True})
                if what == "job":
                    j = jobqueue.create(slug, b["type"], b.get("params"))
                    return self._send(200, j)
                if what == "cancel":
                    for j in jobqueue.jobs():
                        if j["id"] == b["id"] and j["status"] in ("pending",):
                            jobqueue._update(j["_path"], status="cancelled", note="cancelled in the app")
                    return self._send(200, {"ok": True})
            self._send(404, {"error": "not found"})
        except Exception as e:
            self._send(400, {"error": f"{type(e).__name__}: {e}"})


def meshy_pump():
    """Keep queued Meshy objects flowing as slots free up."""
    while True:
        time.sleep(15)
        for d in WORLDS.glob("*/forge"):
            want = d / "meshy-want.json"
            if want.exists():
                names = read_json(want, [])
                left = [n for n in names if not (d / "objects" / n / f"1-{n}.glb").exists()]
                if left:
                    run_meshy(d.parent.name, left)
                else:
                    want.unlink()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8770)
    a = ap.parse_args()
    threading.Thread(target=meshy_pump, daemon=True).start()
    print(f"Scene Forge on http://localhost:{a.port}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()

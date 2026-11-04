"""Meshy multi-image-to-3D for one forge object.

usage:
  python3 meshy.py <forge_dir> <object> [--model latest] [--polycount 60000]
  python3 meshy.py <forge_dir> <object> --resume          # poll an existing task

Reads views from <forge_dir>/objects/<object>/views/*.png|jpg and sends the best 4
(front, a 3/4, back, a side — works with 4- or 8-angle turnaround sheets), falling back to 0-crop.png. Key comes from MESHY_API_KEY in the env or image-blaster/.env.
Writes <forge_dir>/objects/<object>/1-<object>.glb plus .1-<object>-request.json.
"""
import argparse, base64, json, os, sys, time, urllib.request
from pathlib import Path

API = "https://api.meshy.ai/openapi/v1/multi-image-to-3d"
REPO = Path(__file__).resolve().parents[3]


def api_key():
    if os.environ.get("MESHY_API_KEY"):
        return os.environ["MESHY_API_KEY"]
    env = REPO / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("MESHY_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("MESHY_API_KEY missing: add it to image-blaster/.env")


def call(method, url, body=None):
    import urllib.error
    for attempt in range(6):
        req = urllib.request.Request(url, method=method, data=json.dumps(body).encode() if body else None,
                                     headers={"Authorization": f"Bearer {api_key()}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 5:  # too many concurrent tasks / rate limit
                print("429, retrying in 60s", flush=True); time.sleep(60); continue
            if e.code == 402:
                sys.exit("402: out of Meshy credits")
            raise


def data_uri(p):
    mime = "image/png" if p.suffix == ".png" else "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(p.read_bytes()).decode()


def views_for(obj_dir):
    views = [p for p in (obj_dir / "views").glob("*") if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    # Meshy takes max 4 and treats image 0 as the front; with an 8-angle orbit pick the most
    # informative spread: front, a 3/4, the back, a pure side
    order = ["front", "right34", "left34", "back", "right", "left", "back-right34", "back-left34", "top"]
    def view_of(p):  # longest matching suffix, so "back-right34" is not read as "right34"
        hits = [v for v in order if p.stem.endswith("-" + v)]
        return max(hits, key=len) if hits else None
    rank = lambda p: order.index(view_of(p)) if view_of(p) else len(order)
    views.sort(key=lambda p: (rank(p), p.name))
    pick = views[:1]
    for want in (("right34", "left34"), ("back",), ("right", "left")):
        pick += [p for p in views if p not in pick and view_of(p) in want][:1]
    pick += [p for p in views if p not in pick][: 4 - len(pick)]
    return pick[:4] or [obj_dir / "0-crop.png"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("forge"); ap.add_argument("object")
    ap.add_argument("--model", default="latest")
    ap.add_argument("--polycount", type=int, default=60000)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--texture-guide", choices=["views", "prompt"], default="views",
                    help="views (default): texture from the Nano Banana views (texture_image_urls) so colours "
                         "stay true; prompt: texture_prompt from analysis desc (turned beige fabric mauve)")
    a = ap.parse_args()

    obj_dir = Path(a.forge) / "objects" / a.object
    analysis = json.loads((Path(a.forge) / "analysis.json").read_text())
    desc = next((o.get("desc", "") for o in analysis["objects"] if o["name"] == a.object), "")
    req_path = obj_dir / f".1-{a.object}-request.json"

    if a.resume and req_path.exists():
        task_id = json.loads(req_path.read_text())["task_id"]
    else:
        views = views_for(obj_dir)
        body = {
            "image_urls": [data_uri(p) for p in views],
            "ai_model": a.model,
            "should_texture": True,
            "enable_pbr": True,
            "texture_resolution": "2k",
            "should_remesh": True,
            "topology": "triangle",
            "target_polycount": a.polycount,
            "image_enhancement": False,   # keep the reference look
            "remove_lighting": True,
            "target_formats": ["glb"],
        }
        if a.texture_guide == "views":   # meshy-7.1/latest only; can't be combined with texture_prompt
            body["texture_image_urls"] = body["image_urls"]
        else:
            body["texture_prompt"] = desc[:800] or None
        body = {k: v for k, v in body.items() if v is not None}
        task_id = call("POST", API, body)["result"]
        req_path.write_text(json.dumps({"task_id": task_id, "views": [p.name for p in views],
                                        "params": {k: v for k, v in body.items()
                                                   if k not in ("image_urls", "texture_image_urls")}}, indent=2))
        print("task", task_id, "views", [p.name for p in views])

    while True:
        t = call("GET", f"{API}/{task_id}")
        print(a.object, t["status"], t.get("progress"), flush=True)
        if t["status"] in ("SUCCEEDED", "FAILED", "CANCELED"):
            break
        time.sleep(10)
    rec = json.loads(req_path.read_text()); rec["response"] = t
    req_path.write_text(json.dumps(rec, indent=2))
    if t["status"] != "SUCCEEDED":
        sys.exit(f"failed: {t.get('task_error')}")
    out = obj_dir / f"1-{a.object}.glb"
    urllib.request.urlretrieve(t["model_urls"]["glb"], out)
    if t.get("thumbnail_url"):
        urllib.request.urlretrieve(t["thumbnail_url"], obj_dir / f"1-{a.object}-thumb.png")
    print("saved", out, "credits", t.get("consumed_credits"))


if __name__ == "__main__":
    main()

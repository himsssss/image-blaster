"""Blender-side helpers for scene-forge. Run inside Blender:

    FORGE_DIR = "<repo>/worlds/<slug>/forge"
    exec(open("<repo>/.claude/scripts/scene-forge/forge_blender.py").read())
    place_object("sofa")            # import objects/sofa/1-sofa.glb and fit it to its reference bbox

Placement uses the solved camera: the bbox bottom-centre pixel is cast onto the floor (z=0)
or, for `mount: wall|ceiling` objects, onto that plane; the model is then scaled so its
projected width matches the bbox width. Everything goes into the "Forge" collection.
"""
import json
import bpy
import numpy as np
from mathutils import Vector
from mathutils.geometry import intersect_line_plane

# set FORGE_DIR before exec() to target another project
FORGE = globals().get("FORGE_DIR", "/Users/himanshusingh/image to 3d scene/image-blaster/worlds/living-room/forge")
ANALYSIS = json.load(open(FORGE + "/analysis.json"))
REF_W, REF_H = ANALYSIS["size"]


def _obj_spec(name):
    return next(o for o in ANALYSIS["objects"] if o["name"] == name)


def pixel_ray(u, v):
    """World-space ray through reference pixel (u, v) of the scene camera."""
    sc = bpy.context.scene
    cam = sc.camera
    fr = cam.data.view_frame(scene=sc)  # tr, br, bl, tl in camera space
    tr, br, bl, tl = fr
    x, y = u / REF_W, v / REF_H
    top = tl.lerp(tr, x); bot = bl.lerp(br, x)
    p = top.lerp(bot, y)
    origin = cam.matrix_world.translation.copy()
    return origin, (cam.matrix_world @ p - origin).normalized()


def hit_plane(u, v, co, no):
    o, d = pixel_ray(u, v)
    return intersect_line_plane(o, o + d * 100, Vector(co), Vector(no))


def project(p):
    from bpy_extras.object_utils import world_to_camera_view
    sc = bpy.context.scene
    c = world_to_camera_view(sc, sc.camera, Vector(p))
    return c.x * REF_W, (1 - c.y) * REF_H


def collection():
    col = bpy.data.collections.get("Forge")
    if not col:
        col = bpy.data.collections.new("Forge"); bpy.context.scene.collection.children.link(col)
    return col


SUFFIX = [""]


def import_glb(name, path=None):
    path = path or f"{FORGE}/objects/{name}/1-{name}.glb"
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    root = bpy.data.objects.new(f"F_{name}{SUFFIX[0]}", None)
    collection().objects.link(root)
    for o in new:
        for c in o.users_collection:
            c.objects.unlink(o)
        collection().objects.link(o)
        if o.parent is None:
            o.parent = root
    bpy.context.view_layer.update()
    return root, [o for o in new if o.type == "MESH"]


def world_bounds(meshes):
    pts = [m.matrix_world @ Vector(c) for m in meshes for c in m.bound_box]
    return Vector([min(p[i] for p in pts) for i in range(3)]), Vector([max(p[i] for p in pts) for i in range(3)])


def projected_box(meshes):
    mn, mx = world_bounds(meshes)
    cs = [project(Vector((a, b, c))) for a in (mn.x, mx.x) for b in (mn.y, mx.y) for c in (mn.z, mx.z)]
    return min(c[0] for c in cs), min(c[1] for c in cs), max(c[0] for c in cs), max(c[1] for c in cs)


def _spec_for_root(root_name):
    base = root_name[2:]
    names = [o["name"] for o in ANALYSIS["objects"]]
    while base and base not in names and "_" in base:
        base = base.rsplit("_", 1)[0]          # F_wall-sconce_R -> wall-sconce
    return _obj_spec(base)


def fit_bbox(root_name, bbox=None, iters=6, height=None):
    """Verifier correction for floor/support objects: scale XY to the bbox width, Z to its height,
    and slide on the support plane (floor, or spec support_z) so the projected outline matches.
    height: fixed real height in metres instead of fitting Z to the bbox — use for tables/benches whose
    bbox includes the top surface seen from above (fitting Z to it under-sizes them);
    height="dims" uses analysis.json dims_m[2]."""
    root = bpy.data.objects[root_name]
    meshes = [c for c in root.children_recursive if c.type == "MESH"]
    spec = _spec_for_root(root_name)
    tx0, ty0, tx1, ty1 = bbox or spec["bbox"]
    sz = spec.get("support_z", 0.0)
    for _ in range(iters):
        x0, y0, x1, y1 = projected_box(meshes)
        k = (tx1 - tx0) / max(x1 - x0, 1)
        root.scale.x *= k; root.scale.y *= k
        if height is None:
            root.scale.z *= (ty1 - ty0) / max(y1 - y0, 1)
        else:
            hz = spec["dims_m"][2] if height == "dims" else height
            bpy.context.view_layer.update(); mn, mx = world_bounds(meshes)
            root.scale.z *= hz / max(mx.z - mn.z, 1e-6)
        bpy.context.view_layer.update()
        mn, mx = world_bounds(meshes); root.location.z -= mn.z - sz; bpy.context.view_layer.update()
        mn, mx = world_bounds(meshes)
        front = hit_plane((tx0 + tx1) / 2, spec.get("contact_v", ty1) if not bbox else ty1, (0, 0, sz), (0, 0, 1))
        root.location.x += front.x - (mn.x + mx.x) / 2; root.location.y += front.y - mn.y
        bpy.context.view_layer.update()
    mn, mx = world_bounds(meshes)
    return {"box": [round(v) for v in projected_box(meshes)], "size_m": [round(v, 2) for v in (mx - mn)]}


_REF_CACHE = {}


def _load_rgb(path):
    img = bpy.data.images.load(path, check_existing=False)
    w, h = img.size
    px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1, :, :3]
    bpy.data.images.remove(img)
    return px


def _edges(gray):
    gx = np.zeros_like(gray); gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]; gy[1:-1] = gray[2:] - gray[:-2]
    mag = np.hypot(gx, gy)
    return mag > np.percentile(mag, 85)


def _dilate(m, r=2):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def pose_score(bbox, render_path):
    """Edge F1 + grey-level NCC between reference and render inside bbox (reference pixel coords)."""
    if "ref" not in _REF_CACHE:
        _REF_CACHE["ref"] = _load_rgb(FORGE + "/" + ANALYSIS["reference"])
    ref = _REF_CACHE["ref"]; ren = _load_rgb(render_path)
    sy, sx = ren.shape[0] / ref.shape[0], ren.shape[1] / ref.shape[1]
    x0, y0, x1, y1 = bbox
    pad = int(0.08 * max(x1 - x0, y1 - y0))
    x0, y0, x1, y1 = max(0, x0 - pad), max(0, y0 - pad), min(REF_W, x1 + pad), min(REF_H, y1 + pad)
    r = ref[int(y0 * sy):int(y1 * sy), int(x0 * sx):int(x1 * sx)]   # ref sampled at render resolution
    ry = np.linspace(y0, y1 - 1, r.shape[0]).astype(int); rx = np.linspace(x0, x1 - 1, r.shape[1]).astype(int)
    r = ref[np.ix_(ry, rx)]
    n = ren[int(y0 * sy):int(y0 * sy) + r.shape[0], int(x0 * sx):int(x0 * sx) + r.shape[1]]
    gr, gn = r.mean(2), n.mean(2)
    er, en = _edges(gr), _edges(gn)
    prec = (en & _dilate(er)).sum() / max(en.sum(), 1); rec = (er & _dilate(en)).sum() / max(er.sum(), 1)
    f1 = 2 * prec * rec / max(prec + rec, 1e-9)
    a, b = gr - gr.mean(), gn - gn.mean()
    ncc = float((a * b).sum() / max(np.sqrt((a * a).sum() * (b * b).sum()), 1e-9))
    return round(float(0.6 * f1 + 0.4 * ncc), 4), round(float(f1), 3), round(ncc, 3)


def pose_search(root_name, bbox=None, yaws=range(0, 360, 30), pct=25, refit=True, height=None):
    """Try yaw candidates for one placed object; each is refit to the bbox (fit_bbox), rendered in EEVEE
    at pct%, and scored with pose_score. Keeps the best yaw. Returns [(yaw, score, f1, ncc), ...]."""
    import math
    root = bpy.data.objects[root_name]
    bbox = bbox or _spec_for_root(root_name)["bbox"]
    sc = bpy.context.scene
    keep = (sc.render.engine, sc.render.resolution_percentage, sc.render.filepath)
    base = (root.rotation_euler.z, root.scale.copy(), root.location.copy())
    path = FORGE + "/loop/_pose.png"
    try:
        sc.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in [e.identifier for e in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items] else sc.render.engine
    except TypeError:
        pass
    sc.render.resolution_percentage = pct; sc.render.filepath = path
    results = []
    try:
        for yaw in yaws:
            root.rotation_euler.z = base[0] + math.radians(yaw); root.scale = base[1]; root.location = base[2]
            bpy.context.view_layer.update()
            if refit:
                fit_bbox(root_name, bbox, iters=5, height=height)
            bpy.ops.render.render(write_still=True)
            results.append((yaw,) + pose_score(bbox, path))
        best = max(results, key=lambda r: r[1])
        root.rotation_euler.z = base[0] + math.radians(best[0]); root.scale = base[1]; root.location = base[2]
        bpy.context.view_layer.update()
        if refit:
            fit_bbox(root_name, bbox, iters=6, height=height)
    finally:
        sc.render.engine, sc.render.resolution_percentage, sc.render.filepath = keep
    return sorted(results, key=lambda r: -r[1])


def place_object(name, yaw_deg=0.0, depth_offset=0.0, path=None, bbox=None, suffix=""):
    spec = dict(_obj_spec(name))
    if bbox:
        spec["bbox"] = bbox
    x0, y0, x1, y1 = spec["bbox"]
    mount = spec.get("mount", "floor")
    SUFFIX[0] = suffix
    root, meshes = import_glb(name, path)
    bpy.context.view_layer.update()
    # auto-orient: width should run along X like dims_m says (models come in facing arbitrary axes)
    mn, mx = world_bounds(meshes)
    dims = spec.get("dims_m")
    if dims and mount == "floor" and abs(dims[0] - dims[1]) > 0.15:
        if ((mx.x - mn.x) > (mx.y - mn.y)) != (dims[0] > dims[1]):
            yaw_deg += 90.0
    root.rotation_euler[2] = __import__("math").radians(yaw_deg)
    bpy.context.view_layer.update()
    # 1) normalise: model base at origin, centred
    mn, mx = world_bounds(meshes)
    centre = (mn + mx) / 2
    root.location -= Vector((centre.x, centre.y, mn.z if mount == "floor" else centre.z))
    bpy.context.view_layer.update()
    mn, mx = world_bounds(meshes)
    size = mx - mn
    # 2) anchor point from the bbox
    if mount == "floor":
        # front-bottom edge of the bbox touches the floor; object centre sits half its depth behind it
        anchor = hit_plane((x0 + x1) / 2, spec.get("contact_v", y1), (0, 0, spec.get("support_z", 0.0)), (0, 0, 1))
    elif mount == "ceiling":
        anchor = hit_plane((x0 + x1) / 2, y0, (0, 0, spec.get("plane", 2.88)), (0, 0, 1))
    else:  # wall: plane y = spec["plane"]
        anchor = hit_plane((x0 + x1) / 2, (y0 + y1) / 2, (0, spec["plane"], 0), (0, 1, 0))
    # 3) scale so projected width matches bbox width (iterate twice: depth depends on scale)
    s = 1.0
    for _ in range(3):
        root.scale = (s, s, s)
        loc = anchor.copy()
        if mount == "floor":
            loc.y += size.y * s / 2 + depth_offset
        elif mount == "wall":
            loc.y -= size.y * s / 2 + depth_offset
        root.location = loc
        bpy.context.view_layer.update()
        bmn, bmx = world_bounds(meshes)
        corners = [Vector((a, b, c)) for a in (bmn.x, bmx.x) for b in (bmn.y, bmx.y) for c in (bmn.z, bmx.z)]
        us = [project(c)[0] for c in corners]
        w_px = max(us) - min(us)
        s *= (x1 - x0) / max(w_px, 1)
        # recentre after scaling
        bmn, bmx = world_bounds(meshes)
        shift = loc - Vector(((bmn.x + bmx.x) / 2, (bmn.y + bmx.y) / 2, bmn.z if mount == "floor" else (bmn.z + bmx.z) / 2))
        root.location += Vector((shift.x, shift.y, shift.z))
        bpy.context.view_layer.update()
    bmn, bmx = world_bounds(meshes)
    if mount == "ceiling":  # hang from the ceiling: model top touches the plane
        root.location.z += spec.get("plane", 2.88) - bmx.z
        bpy.context.view_layer.update()
        bmn, bmx = world_bounds(meshes)
    return {"name": name, "scale": round(s, 3), "size_m": [round(v, 2) for v in (bmx - bmn)],
            "loc": [round(v, 2) for v in root.location]}

"""Save a finished forge scene as plain data (layout.json) and rebuild a clean .blend from it.

Inside Blender (after forge_blender.py so FORGE_DIR / FORGE are set):
    exec(open(".../scene_layout.py").read())
    export_layout()                 # -> $F/layout.json  (camera, render, world, room surfaces, lights,
                                    #    furniture GLB transforms + colour fixes, procedural extras)
    bpy.ops.wm.read_homefile(use_empty=True)   # fresh file, then re-exec the scripts
    build_from_layout()             # rebuilds everything from layout.json + objects/*/1-*.glb

The room is rebuilt directly with bmesh as plain walls/floor/ceiling boxes (no moldings, door or
trims: in plate mode the empty-room photo paints those). Follow with build_plate_room(...) from
room_from_plate.py so the walls show the empty-room plate.
"""
import json
import os
import bpy
import bmesh
from mathutils import Matrix, Vector

LAYOUT_SURFACES = ("Wall_", "Return_Feature", "DarkRoom_Back", "Floor", "Ceiling")
LAYOUT_EXTRAS = ("F_globe_", "F_plant_stand", "F_rug")


def _m(mat):
    return [list(r) for r in mat]


def _principled(mat):
    if not mat or not mat.use_nodes:
        return {}
    nt = mat.node_tree
    out = {}
    b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if b:
        out["base"] = list(b.inputs["Base Color"].default_value)
        out["rough"] = b.inputs["Roughness"].default_value
    e = next((n for n in nt.nodes if n.type == "EMISSION"), None)
    if e:
        out["emit"] = list(e.inputs["Color"].default_value); out["emit_strength"] = e.inputs["Strength"].default_value
    tex = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image), None)
    if tex and not b or (tex and not any(l.to_socket.name == "Normal" for l in tex.outputs[0].links)):
        out["image"] = bpy.path.abspath(tex.image.filepath)
    return out


def _colour_fix(mat):
    """ForgeTint (hue/sat) and ForgeGain (multiply) values of a Meshy material."""
    nt = mat.node_tree if mat and mat.use_nodes else None
    if not nt:
        return {}
    fix = {}
    t = nt.nodes.get("ForgeTint")
    if t:
        fix["tint"] = {i.name: i.default_value for i in t.inputs if i.name in ("Hue", "Saturation", "Value", "Fac")}
    g = nt.nodes.get("ForgeGain")
    if g:
        fix["gain"] = list(next(s for s in g.inputs if s.name == "B" and s.type == "RGBA").default_value)[:3]
    return fix


def _mesh_data(o):
    me = o.data
    d = {"verts": [list(v.co) for v in me.vertices], "faces": [list(p.vertices) for p in me.polygons]}
    if me.uv_layers.active and me.uv_layers.active.name != "plate":
        uv = me.uv_layers.active.data
        d["uv"] = [[list(uv[li].uv) for li in p.loop_indices] for p in me.polygons]
    d["smooth"] = any(p.use_smooth for p in me.polygons)
    return d


def export_layout(path=None):
    sc = bpy.context.scene
    path = path or FORGE + "/layout.json"
    plate_state = json.loads(sc["forge_plate_room"]) if "forge_plate_room" in sc else None
    view = plate_state["view"] if plate_state else [sc.view_settings.view_transform, sc.view_settings.look,
                                                    sc.view_settings.exposure]
    base_energy = plate_state["lights"] if plate_state else {}
    cam = sc.camera
    L = {"render": {"engine": sc.render.engine, "res": [sc.render.resolution_x, sc.render.resolution_y],
                    "pct": sc.render.resolution_percentage,
                    "samples": sc.cycles.samples if sc.render.engine == "CYCLES" else 64,
                    "view": list(view)},
         "camera": {"matrix": _m(cam.matrix_world), "lens": cam.data.lens, "sensor": cam.data.sensor_width,
                    "fit": cam.data.sensor_fit, "shift": [cam.data.shift_x, cam.data.shift_y],
                    "clip": [cam.data.clip_start, cam.data.clip_end]},
         "world": {}, "room": {}, "lights": {}, "furniture": {}, "extras": {}}
    bg = next((n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"), None) if sc.world else None
    if bg:
        L["world"] = {"color": list(bg.inputs["Color"].default_value), "strength": bg.inputs["Strength"].default_value}
    # room surfaces: world-space bounding corners (the solved shell is boxes/planes)
    room = bpy.data.collections.get("Room")
    for o in (room.all_objects if room else []):
        if o.type == "MESH" and o.name.startswith(LAYOUT_SURFACES):
            prev = json.loads(sc["forge_bake_prev_materials"]).get(o.name) if "forge_bake_prev_materials" in sc else None
            mats = (plate_state or {}).get("materials", {}).get(o.name) or prev or \
                [s.material.name for s in o.material_slots if s.material]
            m0 = bpy.data.materials.get(mats[0]) if mats else None
            L["room"][o.name] = {"corners": [list(o.matrix_world @ Vector(c)) for c in o.bound_box],
                                 "material": mats[0] if mats else "", "look": _principled(m0)}
    for o in bpy.data.objects:
        if o.type == "LIGHT":
            d = o.data
            e = {"type": d.type, "energy": base_energy.get(o.name, d.energy), "color": list(d.color),
                 "matrix": _m(o.matrix_world), "soft": getattr(d, "shadow_soft_size", 0.0),
                 "hide_render": o.hide_render}
            if d.type == "AREA":
                e.update(shape=d.shape, size=d.size, size_y=d.size_y)
            if d.type == "SPOT":
                e.update(spot_size=d.spot_size, spot_blend=d.spot_blend)
            L["lights"][o.name] = e
    glbs = {n: f"{FORGE}/objects/{n}/1-{n}.glb" for n in os.listdir(FORGE + "/objects")
            if os.path.exists(f"{FORGE}/objects/{n}/1-{n}.glb")}
    for o in bpy.data.objects:
        if not o.name.startswith("F_") or o.parent or o.type != "EMPTY":
            continue
        key = o.name[2:]
        src = glbs.get(key) or glbs.get(key.rsplit("_", 1)[0])
        if not src:
            continue
        kids = [c for c in o.children_recursive if c.type == "MESH"]
        L["furniture"][o.name] = {"glb": src, "matrix": _m(o.matrix_world),
                                  "meshes": [{"local": _m(o.matrix_world.inverted() @ c.matrix_world),
                                              "hide_render": c.hide_render,
                                              "fix": [_colour_fix(s.material) for s in c.material_slots]}
                                             for c in kids]}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith(LAYOUT_EXTRAS):
            mat = o.material_slots[0].material if o.material_slots else None
            L["extras"][o.name] = {"matrix": _m(o.matrix_world), "mesh": _mesh_data(o),
                                   "material": mat.name if mat else "", "look": _principled(mat),
                                   "hide_render": o.hide_render}
    with open(path, "w") as f:
        json.dump(L, f)
    return {k: len(v) for k, v in L.items() if isinstance(v, dict)}


def _material(name, look):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name or "Forge_Mat")
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if "emit" in look and "base" not in look:
        em = nt.nodes.new("ShaderNodeEmission")
        em.inputs["Color"].default_value = look["emit"]; em.inputs["Strength"].default_value = look["emit_strength"]
        nt.links.new(em.outputs[0], out.inputs["Surface"])
        return m
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Base Color"].default_value = look.get("base", (0.8, 0.8, 0.8, 1))
    b.inputs["Roughness"].default_value = look.get("rough", 0.6)
    if look.get("image") and os.path.exists(look["image"]):
        t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(look["image"], check_existing=True)
        nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    return m


def _box_from_corners(name, corners, coll):
    pts = [Vector(c) for c in corners]
    lo = Vector([min(p[i] for p in pts) for i in range(3)]); hi = Vector([max(p[i] for p in pts) for i in range(3)])
    bm = bmesh.new()
    uniq = []
    for p in pts:
        if all((p - q).length > 1e-5 for q in uniq):
            uniq.append(p)
    if len(uniq) == 4:   # flat plane -> one quad, ordered around its centre
        c = sum(uniq, Vector()) / 4
        n = (uniq[1] - uniq[0]).cross(uniq[2] - uniq[0]).normalized()
        ax = (uniq[0] - c).normalized(); ay = n.cross(ax)
        import math
        uniq.sort(key=lambda p: math.atan2((p - c).dot(ay), (p - c).dot(ax)))
        bm.faces.new([bm.verts.new(p) for p in uniq])
    else:
        vs = [bm.verts.new(p) for p in uniq]
        bmesh.ops.convex_hull(bm, input=vs)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); coll.objects.link(o)
    return o


def _apply_fix(mat, fix):
    nt = mat.node_tree
    b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not b:
        return
    sock = lambda socks, n: next(s for s in socks if s.name == n and s.type == "RGBA")
    if "tint" in fix:
        link = next((l for l in nt.links if l.to_socket == b.inputs["Base Color"]), None)
        hs = nt.nodes.new("ShaderNodeHueSaturation"); hs.name = "ForgeTint"
        for k, v in fix["tint"].items():
            hs.inputs[k].default_value = v
        if link:
            nt.links.new(link.from_socket, hs.inputs["Color"])
        nt.links.new(hs.outputs["Color"], b.inputs["Base Color"])
    if "gain" in fix:
        link = next((l for l in nt.links if l.to_socket == b.inputs["Base Color"]), None)
        g = nt.nodes.new("ShaderNodeMix"); g.name = "ForgeGain"; g.data_type = "RGBA"; g.blend_type = "MULTIPLY"
        g.inputs[0].default_value = 1.0
        if link:
            nt.links.new(link.from_socket, sock(g.inputs, "A"))
        sock(g.inputs, "B").default_value = (*fix["gain"], 1)
        nt.links.new(sock(g.outputs, "Result"), b.inputs["Base Color"])


def build_from_layout(path=None):
    path = path or FORGE + "/layout.json"
    L = json.load(open(path))
    sc = bpy.context.scene
    try:
        sc.render.engine = L["render"]["engine"]
    except TypeError:
        sc.render.engine = "CYCLES"
    sc.render.resolution_x, sc.render.resolution_y = L["render"]["res"]
    sc.render.resolution_percentage = L["render"]["pct"]
    if sc.render.engine == "CYCLES":
        sc.cycles.samples = L["render"]["samples"]; sc.cycles.use_denoising = True
    sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure = L["render"]["view"]
    colls = {}
    for n in ("Room", "Lighting", "Furniture"):
        colls[n] = bpy.data.collections.get(n) or bpy.data.collections.new(n)
        if colls[n].name not in sc.collection.children:
            sc.collection.children.link(colls[n])
    # world
    if not sc.world:
        sc.world = bpy.data.worlds.new("World")
    sc.world.use_nodes = True
    bg = next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND")
    if L["world"]:
        bg.inputs["Color"].default_value = L["world"]["color"]; bg.inputs["Strength"].default_value = L["world"]["strength"]
    # camera
    c = L["camera"]
    cd = bpy.data.cameras.new("Camera"); cam = bpy.data.objects.new("Camera", cd); sc.collection.objects.link(cam)
    cam.matrix_world = Matrix(c["matrix"]); cd.lens = c["lens"]; cd.sensor_width = c["sensor"]
    cd.sensor_fit = c["fit"]; cd.shift_x, cd.shift_y = c["shift"]; cd.clip_start, cd.clip_end = c["clip"]
    sc.camera = cam
    # room, built directly from the solved surfaces
    for n, r in L["room"].items():
        o = _box_from_corners(n, r["corners"], colls["Room"])
        o.data.materials.append(_material(r["material"] or n + "_Mat", r["look"]))
    # lights
    for n, e in L["lights"].items():
        d = bpy.data.lights.new(n, e["type"]); d.energy = e["energy"]; d.color = e["color"][:3]
        if hasattr(d, "shadow_soft_size"):
            d.shadow_soft_size = e["soft"]
        if e["type"] == "AREA":
            d.shape = e["shape"]; d.size = e["size"]; d.size_y = e["size_y"]
        if e["type"] == "SPOT":
            d.spot_size = e["spot_size"]; d.spot_blend = e["spot_blend"]
        o = bpy.data.objects.new(n, d); colls["Lighting"].objects.link(o)
        o.matrix_world = Matrix(e["matrix"]); o.hide_render = e["hide_render"]
    # furniture: re-import each GLB, put it back on its verified transform
    for root_name, f in L["furniture"].items():
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=f["glb"])
        new = [o for o in bpy.data.objects if o not in before]
        meshes = [o for o in new if o.type == "MESH"]
        root = bpy.data.objects.new(root_name, None); colls["Furniture"].objects.link(root)
        root.matrix_world = Matrix(f["matrix"])
        for o in new:
            for cl in list(o.users_collection):
                cl.objects.unlink(o)
        for m, spec in zip(meshes, f["meshes"]):
            colls["Furniture"].objects.link(m)
            m.parent = root; m.matrix_parent_inverse = Matrix.Identity(4)
            m.matrix_world = Matrix(f["matrix"]) @ Matrix(spec["local"])
            m.hide_render = spec["hide_render"]
            for slot, fix in zip(m.material_slots, spec["fix"]):
                if slot.material and fix:
                    slot.material = slot.material.copy()   # instances (sconce L/R) keep their own fixes
                    _apply_fix(slot.material, fix)
        for o in new:
            if o.type != "MESH":
                bpy.data.objects.remove(o)
    # procedural extras (sconce globes, plant stand, rug)
    for n, x in L["extras"].items():
        md = x["mesh"]; me = bpy.data.meshes.new(n)
        me.from_pydata([Vector(v) for v in md["verts"]], [], md["faces"])
        if "uv" in md:
            uvl = me.uv_layers.new(name="UVMap")
            for p, uvs in zip(me.polygons, md["uv"]):
                for li, uv in zip(p.loop_indices, uvs):
                    uvl.data[li].uv = uv
        if md.get("smooth"):
            for p in me.polygons:
                p.use_smooth = True
        o = bpy.data.objects.new(n, me); colls["Furniture"].objects.link(o)
        o.matrix_world = Matrix(x["matrix"]); o.hide_render = x["hide_render"]
        me.materials.append(_material(x["material"] or n + "_Mat", x["look"]))
    return {"room": len(L["room"]), "lights": len(L["lights"]), "furniture": len(L["furniture"]),
            "extras": len(L["extras"])}

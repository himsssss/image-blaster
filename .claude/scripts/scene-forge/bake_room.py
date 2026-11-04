"""Bake the empty-room photo onto the real 3D room so it works from other camera angles (A + B).

Inside Blender, AFTER the camera is final and with the scene in its plain 3D-room state:
    FORGE_DIR = ".../worlds/<slug>/forge"
    exec(open(".../forge_blender.py").read()); exec(open(".../room_from_plate.py").read())
    exec(open(".../bake_room.py").read())
    objs = room_bake_objects(exclude=[...])          # room meshes + wall art + rug (not glass/metal fixtures)
    prepare_bake(objs, plate="plate/2-plate.png", size=4096)   # UVs, visibility, bake materials
    run_bake(objs)                                   # Cycles EMIT bake -> plate/room-atlas.png (long: use a timer)
    apply_baked(objs, light_scale=...)               # final shading; restore_baked() undoes it

Per object:
- UV "plate": vertices projected through the ORIGINAL camera into the clean plate (big surfaces are
  subdivided first so per-vertex projection stays exact).
- UV "bake": lightmap-packed into one shared atlas.
- face attribute "seen" = 1 if the original camera sees that face (in frame, facing it, first hit of a
  ray from the camera with furniture hidden), else 0.
- bake material: emission = mix(object's average plate colour, plate pixel, seen) -> atlas.
Final material "Forge_Baked": camera rays see the atlas x contact-shadow AO, other rays see diffuse
(atlas colour), so the room keeps the photo's look and still bounces coloured light onto furniture.
"""
import json
import bpy
import bmesh
import numpy as np
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view

BIG_PREFIX = ("Wall_", "Floor", "Ceiling", "Return_Feature", "DarkRoom_Back")


def room_bake_objects(exclude=()):
    out = []
    for o in bpy.data.collections["Room"].all_objects:
        if o.type == "MESH" and not o.hide_render and o.name not in exclude:
            out.append(o)
    for n in ("F_rug", "F_wall-art"):
        r = bpy.data.objects.get(n)
        if r:
            out += [r] if r.type == "MESH" else [c for c in r.children_recursive if c.type == "MESH"]
    return out


def _plate_pixels(path):
    img = bpy.data.images.load(path, check_existing=True)
    w, h = img.size
    return img, np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)


def _visibility(objs, furniture_roots):
    """Face attribute 'seen' via ray casts from the camera (furniture hidden so the wall behind counts)."""
    sc = bpy.context.scene; cam = sc.camera; origin = cam.matrix_world.translation
    hidden = []
    for n in furniture_roots:
        r = bpy.data.objects.get(n)
        for o in ([r] + list(r.children_recursive)) if r else []:
            if not o.hide_viewport:
                o.hide_viewport = True; hidden.append(o)
    bpy.context.view_layer.update()
    dg = bpy.context.evaluated_depsgraph_get()
    try:
        for o in objs:
            me = o.data
            att = me.attributes.get("seen") or me.attributes.new("seen", "FLOAT", "FACE")
            mw = o.matrix_world; nm = mw.to_3x3().inverted().transposed()
            vals = []
            for f in me.polygons:
                c = mw @ f.center; n = (nm @ f.normal).normalized()
                v = world_to_camera_view(sc, cam, c)
                ok = 0.0
                if 0 <= v.x <= 1 and 0 <= v.y <= 1 and v.z > 0 and n.dot(origin - c) > 0:
                    d = (c - origin); dist = d.length
                    hit, loc, *_rest, hob, _m = sc.ray_cast(dg, origin, d.normalized(), distance=dist + 0.01)
                    ok = 1.0 if (not hit or (loc - c).length < max(0.02, dist * 0.004)) else 0.0
                vals.append(ok)
            att.data.foreach_set("value", vals)
            # soft edge: per-vertex average of the faces around it (interpolates smoothly across faces)
            acc = [0.0] * len(me.vertices); cnt = [0] * len(me.vertices)
            for f, v in zip(me.polygons, vals):
                for vi in f.vertices:
                    acc[vi] += v; cnt[vi] += 1
            sv = me.attributes.get("seen_v") or me.attributes.new("seen_v", "FLOAT", "POINT")
            sv.data.foreach_set("value", [a / c if c else 0.0 for a, c in zip(acc, cnt)])
    finally:
        for o in hidden:
            o.hide_viewport = False
        bpy.context.view_layer.update()


def prepare_bake(objs, plate="plate/2-plate.png", size=4096, fallback=None,
                 furniture_roots=("F_sofa", "F_armchair", "F_coffee-table", "F_table-decor", "F_bench",
                                  "F_side-table", "F_floor-lamp", "F_plant", "F_plant_stand")):
    sc = bpy.context.scene
    plate_img, px = _plate_pixels(FORGE + "/" + plate)
    H, W = px.shape[:2]
    # 1) projected UVs (subdivide big planes once)
    for o in objs:
        # subdivide everything: few-face boxes (door leaf = 6 faces) dilute the per-vertex blend into the
        # fill colour and project the photo inaccurately across one big perspective quad
        _project_uvs(o, 24 if o.name.startswith(BIG_PREFIX) else 6)
    # 2) visibility
    _visibility(objs, furniture_roots)
    # 3) atlas UVs
    for o in objs:
        uv = o.data.uv_layers.get("bake") or o.data.uv_layers.new(name="bake")
        o.data.uv_layers.active = uv
    bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="SELECT")
    # whole flat surfaces as single islands (lightmap_pack cut every face apart -> patchwork bake)
    import math
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0,
                             correct_aspect=True, scale_to_bounds=False)
    bpy.ops.uv.pack_islands(margin=0.003, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")
    # 4) atlas image + per-object bake materials
    atlas = bpy.data.images.get("forge_room_atlas") or bpy.data.images.new("forge_room_atlas", size, size, alpha=False)
    if tuple(atlas.size) != (size, size):
        atlas.scale(size, size)
    state = {}
    for o in objs:
        me = o.data; uvp = me.uv_layers["plate"]; seen = me.attributes["seen"]
        cols = []
        for f in me.polygons:
            if seen.data[f.index].value > 0.5:
                u, v = np.mean([uvp.data[li].uv for li in f.loop_indices], axis=0)
                x, y = int(np.clip(u, 0, 1) * (W - 1)), int(np.clip(v, 0, 1) * (H - 1))
                cols.append(px[y, x, :3])
        avg = (np.median(cols, axis=0) if cols else np.array([0.75, 0.72, 0.68])).tolist()
        state[o.name] = [s.material.name if s.material else "" for s in o.material_slots]
        m = bpy.data.materials.get(f"ForgeBake_{o.name}") or bpy.data.materials.new(f"ForgeBake_{o.name}")
        m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
        uvn = nt.nodes.new("ShaderNodeUVMap"); uvn.uv_map = "plate"
        tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = plate_img; tex.extension = "EXTEND"
        att = nt.nodes.new("ShaderNodeAttribute"); att.attribute_name = "seen_v"; att.attribute_type = "GEOMETRY"
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"
        sock = lambda socks, nme: next(s for s in socks if s.name == nme and s.type == "RGBA")
        sock(mix.inputs, "A").default_value = (*avg, 1)
        fb = (fallback or {}).get(o.name)       # (texture path, tile size in metres): textured fill for unseen areas
        if fb:
            fimg = bpy.data.images.load(fb[0], check_existing=True); fimg.colorspace_settings.name = "sRGB"
            fpx = np.array(fimg.pixels[:], dtype=np.float32).reshape(fimg.size[1], fimg.size[0], 4)[..., :3]
            gain = [a / max(float(m), 1e-4) for a, m in zip(avg, fpx.reshape(-1, 3).mean(0))]   # match the photo's colour
            geo = nt.nodes.new("ShaderNodeNewGeometry"); mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (1 / fb[1], 1 / fb[1], 1 / fb[1])
            ft = nt.nodes.new("ShaderNodeTexImage"); ft.image = fimg; ft.extension = "REPEAT"
            fg = nt.nodes.new("ShaderNodeMix"); fg.data_type = "RGBA"; fg.blend_type = "MULTIPLY"; fg.inputs[0].default_value = 1.0
            nt.links.new(geo.outputs["Position"], mp.inputs["Vector"]); nt.links.new(mp.outputs["Vector"], ft.inputs["Vector"])
            nt.links.new(ft.outputs["Color"], sock(fg.inputs, "A")); sock(fg.inputs, "B").default_value = (*gain, 1)
            nt.links.new(sock(fg.outputs, "Result"), sock(mix.inputs, "A"))
        nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"]); nt.links.new(tex.outputs["Color"], sock(mix.inputs, "B"))
        nt.links.new(att.outputs["Fac"], mix.inputs[0])
        em = nt.nodes.new("ShaderNodeEmission"); nt.links.new(sock(mix.outputs, "Result"), em.inputs["Color"])
        out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(em.outputs["Emission"], out.inputs["Surface"])
        buv = nt.nodes.new("ShaderNodeUVMap"); buv.uv_map = "bake"
        tgt = nt.nodes.new("ShaderNodeTexImage"); tgt.image = atlas; nt.links.new(buv.outputs["UV"], tgt.inputs["Vector"])
        nt.nodes.active = tgt
        if not o.material_slots:
            me.materials.append(m)
        for s in o.material_slots:
            s.material = m
    if "forge_bake_prev_materials" not in sc:          # keep the ORIGINAL room materials across re-runs
        sc["forge_bake_prev_materials"] = json.dumps(state)
    return {"objects": len(objs), "atlas": size}


def run_bake(objs, out="plate/room-atlas.png", margin=8):
    sc = bpy.context.scene
    keep = (sc.render.engine, sc.cycles.samples)
    sc.render.engine = "CYCLES"; sc.cycles.samples = 1
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    try:
        bpy.ops.object.bake(type="EMIT", margin=margin, use_clear=True)
    finally:
        sc.render.engine, sc.cycles.samples = keep
    atlas = bpy.data.images["forge_room_atlas"]
    atlas.filepath_raw = FORGE + "/" + out; atlas.file_format = "PNG"; atlas.save()
    return FORGE + "/" + out


def apply_baked(objs, ao_distance=0.35, ao_strength=0.55, light_scale=1.0):
    sc = bpy.context.scene
    atlas = bpy.data.images["forge_room_atlas"]
    m = bpy.data.materials.get("Forge_Baked") or bpy.data.materials.new("Forge_Baked")
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.uv_map = "bake"
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = atlas; tex.interpolation = "Cubic"
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion"); ao.inputs["Distance"].default_value = ao_distance; ao.samples = 16
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs[0].default_value = ao_strength
    sock = lambda socks, nme: next(s for s in socks if s.name == nme and s.type == "RGBA")
    nt.links.new(tex.outputs["Color"], sock(mix.inputs, "A")); nt.links.new(ao.outputs["AO"], sock(mix.inputs, "B"))
    em = nt.nodes.new("ShaderNodeEmission"); nt.links.new(sock(mix.outputs, "Result"), em.inputs["Color"])
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse"); nt.links.new(tex.outputs["Color"], dif.inputs["Color"])
    lp = nt.nodes.new("ShaderNodeLightPath"); sh = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], sh.inputs["Fac"])
    nt.links.new(dif.outputs["BSDF"], sh.inputs[1]); nt.links.new(em.outputs["Emission"], sh.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(sh.outputs["Shader"], out.inputs["Surface"])
    for o in objs:
        for s in o.material_slots:
            s.material = m
    if "forge_baked_view" not in sc:
        sc["forge_baked_view"] = json.dumps([sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure,
                                             {o.name: o.data.energy for o in bpy.context.view_layer.objects if o.type == "LIGHT"}])
        sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"; sc.view_settings.exposure = 0.0
        for o in bpy.context.view_layer.objects:
            if o.type == "LIGHT":
                o.data.energy *= light_scale
    return "baked room applied"


def restore_baked():
    sc = bpy.context.scene
    st = json.loads(sc.get("forge_bake_prev_materials", "{}"))
    for n, mats in st.items():
        o = bpy.data.objects.get(n)
        if o:
            for s, mn in zip(o.material_slots, mats):
                s.material = bpy.data.materials.get(mn) if mn else None
    if "forge_baked_view" in sc:
        vt, lk, ex, lights = json.loads(sc["forge_baked_view"])
        sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure = vt, lk, ex
        for n, e in lights.items():
            o = bpy.data.objects.get(n)
            if o:
                o.data.energy = e
        del sc["forge_baked_view"]
    return "restored"

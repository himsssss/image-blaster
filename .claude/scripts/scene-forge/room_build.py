"""Model the room's architecture as real 3D (looks right from every camera angle — no photo projection).

Inside Blender (after forge_blender.py):
    exec(open(".../room_build.py").read())
    build_room3d(spec)          # spec = json.load(open(FORGE + "/room3d/room3d.json"))
    clear_room3d()              # removes everything it built (collection "Room3D")

The spec is measured from the empty-room plate: wall planes come from the camera solve, details
(panel moldings, crown, baseboard, wardrobe doors, door, openings, downlights) from plate pixels cast
onto those planes (hit_plane) or mapped proportionally along a wall when the photo's perspective is
inconsistent. Textures that only exist in the photo (door wood, rug) are cut / rectified from the plate.

spec keys (metres, world space):
  materials: {name: {"base": [r,g,b] linear | "image": path, "tile_m": [w,h], "rough": r, "emit": s}}
  boxes:     [{"name", "min": [x,y,z], "max": [x,y,z], "mat"}]
  frames:    [{"name", "plane": "x=2.084" | "y=3.0", "side": -1|1 (direction it sticks out),
               "a": [u0,u1] along the wall, "z": [z0,z1], "w": profile width, "d": depth, "mat"}]
  runs:      [{"name", same plane/side, "a": [u0,u1], "z": [z0,z1], "d": depth, "mat"}]  (crown, base)
  discs:     [{"name", "at": [x,y,z], "r": radius, "mat"}]
  delete:    [object names to remove first]   hide: [object names to hide in render]
"""
import os
import bpy
import bmesh

R3D = "Room3D"


def _coll():
    c = bpy.data.collections.get(R3D)
    if not c:
        c = bpy.data.collections.new(R3D); bpy.context.scene.collection.children.link(c)
    return c


def _mat(name, spec):
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    if spec.get("emit"):
        e = nt.nodes.new("ShaderNodeEmission"); e.inputs["Strength"].default_value = spec["emit"]
        e.inputs["Color"].default_value = (*spec.get("base", (1, 0.85, 0.7)), 1)
        nt.links.new(e.outputs[0], out.inputs["Surface"]); return m
    b = nt.nodes.new("ShaderNodeBsdfPrincipled")
    b.inputs["Roughness"].default_value = spec.get("rough", 0.7)
    nt.links.new(b.outputs[0], out.inputs["Surface"])
    if spec.get("image"):
        t = nt.nodes.new("ShaderNodeTexImage")
        t.image = bpy.data.images.load(spec["image"], check_existing=True)
        if spec.get("tile_m"):   # world-space tiling (floors): object coords / tile size
            tc = nt.nodes.new("ShaderNodeTexCoord"); mp = nt.nodes.new("ShaderNodeMapping")
            mp.inputs["Scale"].default_value = (1 / spec["tile_m"][0], 1 / spec["tile_m"][1], 1)
            nt.links.new(tc.outputs["Object"], mp.inputs["Vector"]); nt.links.new(mp.outputs[0], t.inputs["Vector"])
        g = nt.nodes.new("ShaderNodeMix"); g.name = "ForgeGain"; g.data_type = "RGBA"; g.blend_type = "MULTIPLY"
        g.inputs[0].default_value = 1.0
        sock = lambda socks, n: next(s for s in socks if s.name == n and s.type == "RGBA")
        sock(g.inputs, "B").default_value = (*spec.get("base", (1, 1, 1)), 1)
        nt.links.new(t.outputs["Color"], sock(g.inputs, "A"))
        nt.links.new(sock(g.outputs, "Result"), b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*spec.get("base", (0.8, 0.8, 0.8)), 1)
    return m


def _box(name, lo, hi, mat, uv_fit=False):
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x = lo[0] + (v.co.x + 0.5) * (hi[0] - lo[0])
        v.co.y = lo[1] + (v.co.y + 0.5) * (hi[1] - lo[1])
        v.co.z = lo[2] + (v.co.z + 0.5) * (hi[2] - lo[2])
    if uv_fit:   # one image over the largest face pair (door leaf, rug)
        uvl = bm.loops.layers.uv.new("UVMap")
        dims = [hi[i] - lo[i] for i in range(3)]
        thin = min(range(3), key=lambda i: dims[i])
        u_ax, v_ax = (0, 1) if thin == 2 else ((1 if thin == 0 else 0), 2)
        for f in bm.faces:
            for l in f.loops:
                l[uvl].uv = ((l.vert.co[u_ax] - lo[u_ax]) / dims[u_ax], (l.vert.co[v_ax] - lo[v_ax]) / dims[v_ax])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(name, me); _coll().objects.link(o)
    me.materials.append(mat)
    return o


def _wall_box(plane, side, a, z, d):
    """Box sitting on a wall plane 'x=..' or 'y=..', spanning a (along wall) x z, sticking out by d."""
    ax, val = plane.split("="); val = float(val)
    n0, n1 = sorted((val, val + side * d))
    if ax == "x":
        return (n0, a[0], z[0]), (n1, a[1], z[1])
    return (a[0], n0, z[0]), (a[1], n1, z[1])


def build_room3d(spec):
    for n in spec.get("delete", []):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o)
    for n in spec.get("hide", []):
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = True; o.hide_viewport = True
    mats = {n: _mat(n, s) for n, s in spec["materials"].items()}
    made = 0
    for b in spec.get("boxes", []):
        _box(b["name"], b["min"], b["max"], mats[b["mat"]], uv_fit=b.get("uv", False)); made += 1
    for r in spec.get("runs", []):
        lo, hi = _wall_box(r["plane"], r["side"], r["a"], r["z"], r["d"])
        _box(r["name"], lo, hi, mats[r["mat"]]); made += 1
    for f in spec.get("frames", []):
        (u0, u1), (z0, z1), w = f["a"], f["z"], f["w"]
        parts = {"T": ((u0, u1), (z1 - w, z1)), "B": ((u0, u1), (z0, z0 + w)),
                 "L": ((u0, u0 + w), (z0 + w, z1 - w)), "R": ((u1 - w, u1), (z0 + w, z1 - w))}
        for k, (a, z) in parts.items():
            lo, hi = _wall_box(f["plane"], f["side"], a, z, f["d"])
            _box(f"{f['name']}_{k}", lo, hi, mats[f["mat"]]); made += 1
    for d in spec.get("discs", []):
        bpy.ops.mesh.primitive_cylinder_add(radius=d["r"], depth=0.01, location=d["at"], vertices=24)
        o = bpy.context.active_object; o.name = d["name"]
        for c in list(o.users_collection):
            c.objects.unlink(o)
        _coll().objects.link(o); o.data.materials.append(mats[d["mat"]]); made += 1
    return made


def clear_room3d():
    c = bpy.data.collections.get(R3D)
    if not c:
        return 0
    n = len(c.objects)
    for o in list(c.objects):
        bpy.data.objects.remove(o)
    return n

"""Blender side of the scene-forge light fit. Light transport is linear: the full render equals the sum
of renders with one light on at a time, so we render a "basis" image per light group, fit the
strengths/colours outside Blender (fit_lights.py), then apply them back here.

Inside Blender:
    FORGE_DIR = "<abs>/worlds/<slug>/forge"
    exec(open("<abs>/.claude/scripts/scene-forge/light_basis.py").read())
    groups = light_groups()                       # {group: [light objects or emissive materials]}
    render_basis(list(groups)[:6])                # call in chunks (each render ~2-4 s)
    ...                                           # run fit_lights.py from the shell
    apply_fit()                                   # reads loop/basis/fit.json: light strengths + colours, object gains

Basis images are scene-linear EXR -> .npy (H, W, 3) at the basis resolution, rendered in Cycles.
"""
import json, os
from pathlib import Path
import bpy
import numpy as np

FORGE = globals().get("FORGE_DIR", "/Users/himanshusingh/image to 3d scene/image-blaster/worlds/living-room/forge")
BASIS = Path(FORGE) / "loop" / "basis"
BASIS.mkdir(parents=True, exist_ok=True)


def _strength_sockets(m):
    """Emission strength sockets of a material: Emission nodes + Principled 'Emission Strength'."""
    out = []
    for n in m.node_tree.nodes:
        if n.type == "EMISSION":
            out.append(n.inputs["Strength"])
        elif n.type == "BSDF_PRINCIPLED":
            st, col = n.inputs["Emission Strength"], n.inputs["Emission Color"]
            if st.default_value > 0 and (col.is_linked or max(col.default_value[:3]) > 0):
                out.append(st)
    return out


def _emitters():
    """{group: [strength sockets]} for emissive materials on objects that render in this view layer.
    Materials whose emission comes from a texture (Meshy PBR emission maps) share one group."""
    used = set()
    for o in bpy.context.view_layer.objects:
        if o.type == "MESH" and not o.hide_render:
            used.update(s.material for s in o.material_slots if s.material)
    groups = {}
    for m in sorted((m for m in used if m.use_nodes), key=lambda m: m.name):
        socks = _strength_sockets(m)
        if not socks:
            continue
        textured = any(n.type == "BSDF_PRINCIPLED" and n.inputs["Emission Color"].is_linked for n in m.node_tree.nodes)
        groups.setdefault("emit:__textured__" if textured else f"emit:{m.name}", []).extend(socks)
    return groups


def _gain_sockets():
    out = []
    for m in bpy.data.materials:
        n = m.node_tree.nodes.get("ForgeGain") if m.use_nodes else None
        if n:
            out.append(next(s for s in n.inputs if s.name == "B" and s.type == "RGBA"))
    return out


def light_groups():
    """One group per light object, one per emissive material (textured ones shared), one for the world."""
    g = {}
    for o in bpy.context.scene.objects:
        if o.type == "LIGHT" and not o.hide_render:
            g[f"light:{o.name}"] = o.name
    for k in _emitters():
        g[k] = k
    if bpy.context.scene.world:
        g["world"] = bpy.context.scene.world.name
    return g


def _state():
    sc = bpy.context.scene
    em = _emitters()
    st = {"lights": {o.name: o.data.energy for o in sc.objects if o.type == "LIGHT"},
          "emit": {k: [(sk, sk.default_value) for sk in v] for k, v in em.items()}, "world": None,
          "render": (sc.render.engine, sc.render.resolution_percentage, sc.render.filepath,
                     sc.render.image_settings.file_format, sc.render.image_settings.color_depth)}
    w = sc.world
    if w and w.use_nodes:
        st["world"] = [n.inputs["Strength"].default_value for n in w.node_tree.nodes if n.type == "BACKGROUND"]
    return st


def _set_only(group, st):
    sc = bpy.context.scene
    for name, e in st["lights"].items():
        bpy.data.objects[name].data.energy = e if group == f"light:{name}" else 0.0
    for k, pairs in st["emit"].items():
        for sk, v in pairs:
            sk.default_value = v if group == k else 0.0
    if st["world"] is not None:
        nodes = [n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"]
        for n, v in zip(nodes, st["world"]):
            n.inputs["Strength"].default_value = v if group == "world" else 0.0


def _restore(st):
    sc = bpy.context.scene
    for name, e in st["lights"].items():
        bpy.data.objects[name].data.energy = e
    for pairs in st["emit"].values():
        for sk, v in pairs:
            sk.default_value = v
    if st["world"] is not None:
        for n, v in zip([n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"], st["world"]):
            n.inputs["Strength"].default_value = v
    (sc.render.engine, sc.render.resolution_percentage, sc.render.filepath,
     sc.render.image_settings.file_format, sc.render.image_settings.color_depth) = st["render"]


def render_basis(groups, pct=25, samples=48):
    """Render each group alone to loop/basis/<safe>.npy. Returns the saved names."""
    sc = bpy.context.scene
    st = _state()
    saved = []
    gains = [(g, tuple(g.default_value)) for g in _gain_sockets()]
    for g, _ in gains:  # basis must be un-gained: fit gains are absolute
        g.default_value = (1, 1, 1, 1)
    try:
        sc.render.engine = "CYCLES"
        sc.cycles.samples = samples; sc.cycles.use_denoising = True
        sc.render.resolution_percentage = pct
        sc.render.image_settings.file_format = "OPEN_EXR"; sc.render.image_settings.color_depth = "32"
        for g in groups:
            _set_only(g, st)
            safe = _safe(g)
            exr = str(BASIS / f"{safe}.exr")
            sc.render.filepath = exr
            bpy.ops.render.render(write_still=True)
            img = bpy.data.images.load(exr, check_existing=False)
            w, h = img.size
            px = np.array(img.pixels[:], dtype=np.float32).reshape(h, w, 4)[::-1, :, :3]
            bpy.data.images.remove(img)
            np.save(BASIS / f"{safe}.npy", px); os.remove(exr)
            saved.append(safe)
    finally:
        _restore(st)
        for g, v in gains:
            g.default_value = v
    gj = BASIS / "groups.json"
    index = json.loads(gj.read_text()) if gj.exists() else {}
    index.update({_safe(g): g for g in groups})
    gj.write_text(json.dumps(index, indent=1))
    return saved


def _safe(g):
    return g.replace(":", "__").replace(" ", "_").replace("/", "_")


def _gain_node(mat, rgb):
    nt = mat.node_tree
    b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    if not b:
        return False
    node = nt.nodes.get("ForgeGain")
    sock = lambda socks, name: next(s for s in socks if s.name == name and s.type == "RGBA")
    if not node:
        link = next((l for l in nt.links if l.to_socket == b.inputs["Base Color"]), None)
        node = nt.nodes.new("ShaderNodeMix"); node.name = "ForgeGain"
        node.data_type = "RGBA"; node.blend_type = "MULTIPLY"
        node.inputs[0].default_value = 1.0  # Factor
        if link:
            nt.links.new(link.from_socket, sock(node.inputs, "A"))
        else:
            sock(node.inputs, "A").default_value = b.inputs["Base Color"].default_value[:]
        nt.links.new(sock(node.outputs, "Result"), b.inputs["Base Color"])
        sock(node.inputs, "B").default_value = (1, 1, 1, 1)
    # gains are absolute (fit against the un-gained basis), so set rather than multiply
    sock(node.inputs, "B").default_value = (rgb[0], rgb[1], rgb[2], 1)
    return True


def apply_fit(path=None):
    """Apply loop/basis/fit.json: per-group RGB weights -> strength + colour; per-object albedo gains."""
    fit = json.loads(Path(path or BASIS / "fit.json").read_text())
    groups = json.loads((BASIS / "groups.json").read_text())
    sc = bpy.context.scene
    done = []
    for safe, w in fit["weights"].items():
        g = groups[safe]; s = max(w) if max(w) > 0 else 0.0
        col = [c / s for c in w] if s else [1, 1, 1]
        if g.startswith("light:"):
            L = bpy.data.objects[g[6:]].data
            L.energy *= s
            L.color = [min(1.0, a * b) for a, b in zip(L.color, col)]
        elif g.startswith("emit:"):
            for sk in _emitters().get(g, []):
                sk.default_value *= s
                n = sk.node
                if n.type == "EMISSION":
                    c = n.inputs["Color"].default_value
                    n.inputs["Color"].default_value = (min(1, c[0] * col[0]), min(1, c[1] * col[1]), min(1, c[2] * col[2]), 1)
        elif g == "world":
            for n in [n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND"]:
                n.inputs["Strength"].default_value *= s
                c = n.inputs["Color"].default_value
                n.inputs["Color"].default_value = (c[0] * col[0], c[1] * col[1], c[2] * col[2], 1)
        done.append((g, round(s, 3), [round(c, 2) for c in col]))
    for obj, rgb in fit.get("gains", {}).items():
        if obj == "room":
            meshes = [o for o in bpy.data.collections["Room"].all_objects if o.type == "MESH"] \
                if "Room" in bpy.data.collections else []
        else:
            root = bpy.data.objects.get(f"F_{obj}")
            meshes = [c for c in root.children_recursive if c.type == "MESH"] if root else []
            meshes += [c for o in bpy.data.objects if o.name.startswith(f"F_{obj}_")
                       for c in o.children_recursive if c.type == "MESH"]  # extra instances
        for m in meshes:
            for mat in m.data.materials:
                _gain_node(mat, rgb)
        done.append((obj, "gain", [round(v, 2) for v in rgb]))
    if "view" in fit:
        sc.view_settings.view_transform = fit["view"]["transform"]
        sc.view_settings.look = "None"
        sc.view_settings.exposure = fit["view"]["exposure"]
    return done

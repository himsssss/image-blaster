"""Make the Blender room look exactly like the photo: camera-projected clean plate on a 3D shell.

Inside Blender (exec after forge_blender.py):
    FORGE_DIR = ".../worlds/<slug>/forge"
    exec(open(".../forge_blender.py").read()); exec(open(".../room_from_plate.py").read())
    build_plate_room(surfaces=[...], hide=[...], plate="plate/2-plate.png", ao_distance=0.35, ao_strength=0.55)
    restore_room()          # back to the plain 3D room

How it works
- Every big room surface (walls, floor, ceiling, built-in fronts) gets a UV layer "plate" whose UVs are
  the surface's vertices projected through the scene camera -> image coordinates of the clean plate.
  Seen from the camera, each pixel shows exactly the plate pixel, even where the photo's perspective is
  inconsistent (the shell just has to cover the frame). Surfaces are subdivided first so the per-vertex
  projection stays exact (UVs interpolate linearly, perspective does not).
- Material "Forge_PlateRoom": camera rays see Emission(plate) x contact shadow (AO), so walls render as
  the photo with furniture grounding; all other rays see Diffuse(plate colour) so furniture still gets
  coloured bounce light from the room.
- Detail meshes already painted in the plate (moldings, trims, wall art, sconces, fan, rug) are hidden.
- View transform -> Standard, exposure 0, so the plate pixels come out unchanged; light energies are
  scaled by `light_scale` to keep the furniture brightness the AgX setup had.
Everything changed is recorded in scene["forge_plate_room"] so restore_room() undoes it exactly.
"""
import json
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def _plate_material(img_path, ao_distance, ao_strength):
    name = "Forge_PlateRoom"
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear()
    uv = nt.nodes.new("ShaderNodeUVMap"); uv.uv_map = "plate"
    tex = nt.nodes.new("ShaderNodeTexImage"); tex.image = bpy.data.images.load(img_path, check_existing=True)
    tex.extension = "EXTEND"; tex.interpolation = "Cubic"
    ao = nt.nodes.new("ShaderNodeAmbientOcclusion"); ao.inputs["Distance"].default_value = ao_distance; ao.samples = 16
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = ao_strength
    sock = lambda socks, n: next(s for s in socks if s.name == n and s.type == "RGBA")
    nt.links.new(uv.outputs["UV"], tex.inputs["Vector"])
    nt.links.new(tex.outputs["Color"], sock(mix.inputs, "A"))
    nt.links.new(ao.outputs["AO"], sock(mix.inputs, "B"))   # 0..1 occlusion factor -> contact shadows
    em = nt.nodes.new("ShaderNodeEmission"); em.inputs["Strength"].default_value = 1.0
    nt.links.new(sock(mix.outputs, "Result"), em.inputs["Color"])
    dif = nt.nodes.new("ShaderNodeBsdfDiffuse"); nt.links.new(tex.outputs["Color"], dif.inputs["Color"])
    lp = nt.nodes.new("ShaderNodeLightPath")
    sh = nt.nodes.new("ShaderNodeMixShader")
    nt.links.new(lp.outputs["Is Camera Ray"], sh.inputs["Fac"])
    nt.links.new(dif.outputs["BSDF"], sh.inputs[1]); nt.links.new(em.outputs["Emission"], sh.inputs[2])
    out = nt.nodes.new("ShaderNodeOutputMaterial"); nt.links.new(sh.outputs["Shader"], out.inputs["Surface"])
    return m


def _project_uvs(obj, cuts):
    """Subdivide (for exact per-vertex projection) and write camera-projected UVs into layer 'plate'."""
    sc = bpy.context.scene; cam = sc.camera
    me = obj.data
    if cuts and not me.get("forge_subdivided"):
        import bmesh
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.subdivide_edges(bm, edges=bm.edges[:], cuts=cuts, use_grid_fill=True)
        bm.to_mesh(me); bm.free(); me["forge_subdivided"] = cuts
    uvl = me.uv_layers.get("plate") or me.uv_layers.new(name="plate")
    mw = obj.matrix_world
    for loop in me.loops:
        c = world_to_camera_view(sc, cam, mw @ me.vertices[loop.vertex_index].co)
        uvl.data[loop.index].uv = (c.x, c.y)


def build_plate_room(surfaces, hide, plate="plate/2-plate.png", cuts=24, ao_distance=0.35,
                     ao_strength=0.55, light_scale=None):
    sc = bpy.context.scene
    state = {"materials": {}, "hidden": [], "view": [sc.view_settings.view_transform, sc.view_settings.look,
             sc.view_settings.exposure], "lights": {}}
    mat = _plate_material(FORGE + "/" + plate, ao_distance, ao_strength)
    for n in surfaces:
        o = bpy.data.objects.get(n)
        if not o or o.type != "MESH":
            continue
        state["materials"][n] = [s.material.name if s.material else "" for s in o.material_slots]
        _project_uvs(o, cuts)
        if not o.material_slots:
            o.data.materials.append(mat)
        for s in o.material_slots:
            s.material = mat
    for n in hide:
        o = bpy.data.objects.get(n)
        if o and not o.hide_render:
            o.hide_render = True; state["hidden"].append(n)
    # exact pixels: Standard view, exposure 0; compensate furniture brightness with the lights
    exp = sc.view_settings.exposure
    sc.view_settings.view_transform = "Standard"; sc.view_settings.look = "None"; sc.view_settings.exposure = 0.0
    k = light_scale if light_scale is not None else 2 ** exp
    for o in bpy.context.view_layer.objects:
        if o.type == "LIGHT":
            state["lights"][o.name] = o.data.energy; o.data.energy *= k
    sc["forge_plate_room"] = json.dumps(state)
    return {"surfaces": len(state["materials"]), "hidden": len(state["hidden"]), "light_scale": round(k, 3)}


def restore_room():
    sc = bpy.context.scene
    if "forge_plate_room" not in sc:
        return "not in plate-room mode"
    st = json.loads(sc["forge_plate_room"])
    for n, mats in st["materials"].items():
        o = bpy.data.objects.get(n)
        if o:
            for s, mn in zip(o.material_slots, mats):
                s.material = bpy.data.materials.get(mn) if mn else None
    for n in st["hidden"]:
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = False
    sc.view_settings.view_transform, sc.view_settings.look, sc.view_settings.exposure = st["view"]
    for n, e in st["lights"].items():
        o = bpy.data.objects.get(n)
        if o:
            o.data.energy = e
    del sc["forge_plate_room"]
    return "restored"

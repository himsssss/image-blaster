"""Switch a scene-forge scene between EDIT mode and PLATE mode (exec inside Blender).

EDIT  (default, what the user works in): normal visible 3D room, opaque film, wall art / sconces /
      fan / glow spheres rendered as 3D objects. Render view looks like a normal scene.
PLATE (only while rendering the projected-clean-plate final): room = shadow catchers, film
      transparent, objects that are already in the plate excluded from rendering.

    FORGE_DIR = "..."; exec(open(".../plate_mode.py").read())
    set_mode("edit")
    render_plate_passes(pct=100, samples=192)   # switches to PLATE, renders both passes, back to EDIT
    # then: python3 plate_composite.py comp2 plate/2-plate.png <furniture> <shadow> final-render.png --shadow 0.4

The room set is remembered on the scene (scene["forge_room"]) the first time PLATE is entered, so EDIT
restores exactly those objects.
"""
import bpy

FORGE = globals().get("FORGE_DIR", "")
FURNITURE_ROOTS = ("F_sofa", "F_armchair", "F_coffee-table", "F_table-decor", "F_bench", "F_side-table",
                   "F_floor-lamp", "F_plant", "F_plant_stand")
IN_PLATE_ROOTS = ("F_wall-art", "F_wall-sconce_L", "F_wall-sconce_R", "F_ceiling-fan",
                  "F_globe_L0", "F_globe_L1", "F_globe_R0", "F_globe_R1")


def _tree(name):
    o = bpy.data.objects.get(name)
    return [] if not o else [o] + list(o.children_recursive)


def _sets():
    sc = bpy.context.scene
    furn = {m.name for n in FURNITURE_ROOTS for m in _tree(n)}
    plate = {m.name for n in IN_PLATE_ROOTS for m in _tree(n)}
    if "forge_room" not in sc:
        room = [o.name for o in bpy.context.view_layer.objects
                if o.type == "MESH" and o.name not in furn and o.name not in plate
                and (not o.hide_render or getattr(o, "is_shadow_catcher", False))]
        sc["forge_room"] = room
    return set(sc["forge_room"]), plate


def set_mode(mode):
    sc = bpy.context.scene
    room, plate = _sets()
    for n in room:
        o = bpy.data.objects.get(n)
        if o:
            o.is_shadow_catcher = (mode == "plate"); o.is_holdout = False
    for n in plate:
        o = bpy.data.objects.get(n)
        if o:
            o.hide_render = (mode == "plate"); o.visible_camera = True; o.visible_shadow = True
    sc.render.film_transparent = (mode == "plate")
    # each mode keeps its own exposure: plate furniture is matched to the photo, edit to the 3D room
    prev = sc.get("forge_mode")
    if prev in ("edit", "plate"):
        sc[f"forge_exposure_{prev}"] = sc.view_settings.exposure
    if f"forge_exposure_{mode}" in sc:
        sc.view_settings.exposure = sc[f"forge_exposure_{mode}"]
    sc["forge_mode"] = mode
    return {"mode": mode, "room": len(room), "plate_objects": len(plate)}


def render_plate_passes(pct=100, samples=192, out_dir=None):
    """PLATE mode -> shadow pass + furniture (holdout) pass -> back to EDIT. Returns the two paths."""
    sc = bpy.context.scene
    out_dir = out_dir or FORGE + "/plate"
    keep = (sc.render.engine, sc.render.resolution_percentage, sc.render.filepath, sc.cycles.samples,
            sc.render.image_settings.file_format, sc.render.image_settings.color_mode)
    room, _ = _sets()
    paths = (out_dir + "/final-shadow-rgba.png", out_dir + "/final-furniture-holdout.png")
    try:
        set_mode("plate")
        sc.render.engine = "CYCLES"; sc.cycles.samples = samples; sc.render.resolution_percentage = pct
        sc.render.image_settings.file_format = "PNG"; sc.render.image_settings.color_mode = "RGBA"
        sc.render.filepath = paths[0]; bpy.ops.render.render(write_still=True)
        for n in room:
            o = bpy.data.objects.get(n)
            if o:
                o.is_shadow_catcher = False; o.is_holdout = True
        sc.render.filepath = paths[1]; bpy.ops.render.render(write_still=True)
    finally:
        set_mode("edit")
        (sc.render.engine, sc.render.resolution_percentage, sc.render.filepath, sc.cycles.samples,
         sc.render.image_settings.file_format, sc.render.image_settings.color_mode) = keep
    return paths

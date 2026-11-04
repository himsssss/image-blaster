"""Blender-side camera refinement for scene-forge (exec after forge_blender.py).

When objects look "seen from too high / too wide-angle" compared with the reference, the first
camera solve got eye height and/or focal length wrong. This keeps the back wall framed exactly
(same px-per-metre and floor row) while trying (lens, eye) pairs, re-fits the key floor objects to
their reference bboxes for each, renders EEVEE, and saves the renders for scoring outside Blender.

    FORGE_DIR = ...; exec(open(".../forge_blender.py").read()); exec(open(".../camera_search.py").read())
    cam_state = save_camera()
    set_camera(lens_mm, eye, wall_y=3.0, wall_px_per_m=k, floor_row=921)
    refit_key_objects(["F_sofa", "F_coffee-table", ...])   # uses table/anchor rules from verify-loop.md
    restore_camera(cam_state)
"""
import bpy
from mathutils import Vector
from bpy_extras.object_utils import world_to_camera_view


def _row(p):
    bpy.context.view_layer.update()
    sc = bpy.context.scene
    return (1 - world_to_camera_view(sc, sc.camera, Vector(p)).y) * REF_H


def save_camera():
    c = bpy.context.scene.camera
    return dict(loc=c.location.copy(), lens=c.data.lens, sx=c.data.shift_x, sy=c.data.shift_y, clip=c.data.clip_start)


def restore_camera(st):
    c = bpy.context.scene.camera
    c.location = st["loc"]; c.data.lens = st["lens"]; c.data.shift_x = st["sx"]; c.data.shift_y = st["sy"]
    c.data.clip_start = st["clip"]; bpy.context.view_layer.update()


def set_camera(lens_mm, eye, wall_y=3.0, wall_px_per_m=None, floor_row=None, probe_x=0.4):
    """Lens + eye height; distance from the back wall follows from px-per-metre so the wall keeps its
    size; shift_y re-solved so the back-wall floor line stays on floor_row."""
    sc = bpy.context.scene; c = sc.camera
    f_px = lens_mm * REF_W / c.data.sensor_width
    c.data.lens = lens_mm
    c.location.y = wall_y - f_px / wall_px_per_m
    c.location.z = eye
    c.data.clip_start = 0.05
    for _ in range(14):
        err = floor_row - _row((probe_x, wall_y, 0.0))
        if abs(err) < 0.1:
            break
        c.data.shift_y += err / REF_W
    return {"lens": lens_mm, "eye": eye, "cam_y": round(c.location.y, 3), "shift_y": round(c.data.shift_y, 4)}


def anchor_table_top(root_name, top_front_row, x_center):
    """Tables: put the visible TOP front edge on its reference row (the base is recessed)."""
    root = bpy.data.objects[root_name]; ms = [m for m in root.children_recursive if m.type == "MESH"]
    for _ in range(6):
        mn, mx = world_bounds(ms)
        p = hit_plane(x_center, top_front_row, (0, 0, mx.z), (0, 0, 1))
        root.location.y += p.y - mn.y; root.location.x += p.x - (mn.x + mx.x) / 2
        bpy.context.view_layer.update()


def refit_key_objects(names, table=None):
    """table = (root_name, top_front_row, x_center) gets dims height + top-edge anchoring."""
    out = {}
    for n in names:
        if table and n == table[0]:
            fit_bbox(n, iters=5, height="dims")
            anchor_table_top(*table)
        else:
            fit_bbox(n, iters=5)
        out[n] = [round(v) for v in projected_box([m for m in bpy.data.objects[n].children_recursive if m.type == "MESH"])]
    return out

"""Living-room architecture spec, measured from plate/2-plate.png (see room_build.py).
v2: walls placed where the PHOTO's floor puts them (hit_plane on z=0 at each wall's floor line):
feature wall y=1.871 (right behind the sofa), right wall x=1.96, wardrobe wall y=2.902, ceiling 2.72."""
import json, os
F = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = 2.72
FW, RW, WW = "y=1.871", "x=1.96", "y=2.902"      # feature wall, right wall, wardrobe wall (inner faces)
LW = "x=-4.084"                                # left wall
mat = {
 "R3_Wall":      {"base": [0.62, 0.52, 0.40], "rough": 0.85},
 "R3_Molding":   {"base": [0.66, 0.56, 0.44], "rough": 0.6},
 "R3_Wardrobe":  {"base": [0.70, 0.66, 0.60], "rough": 0.5},
 "R3_Gap":       {"base": [0.08, 0.07, 0.06], "rough": 0.9},
 "R3_Ceiling":   {"base": [0.75, 0.70, 0.62], "rough": 0.9},
 "R3_Floor":     {"image": F + "/plate/floor-tile.png", "tile_m": [1.2, 1.2], "base": [1, 1, 1], "rough": 0.35},
 "R3_DoorWood":  {"image": F + "/room3d/door-wood.png", "base": [1, 1, 1], "rough": 0.45},
 "R3_DoorFrame": {"base": [0.045, 0.032, 0.024], "rough": 0.5},
 "R3_Handle":    {"base": [0.03, 0.03, 0.03], "rough": 0.3},
 "R3_Dark":      {"base": [0.03, 0.03, 0.035], "rough": 0.9},
 "R3_Rug":       {"image": F + "/room3d/rug-topdown.png", "base": [1, 1, 1], "rough": 0.95},
 "R3_Downlight": {"emit": 6.0, "base": [1.0, 0.86, 0.7]},
}
boxes, runs, frames, discs = [], [], [], []
T = 0.12                                   # wall thickness
XL, XR, YF, YW = -4.084, 1.96, 1.871, 2.902  # left wall, right wall, feature wall, wardrobe wall (inner faces)
XRET = -1.083                              # feature-wall return (its left edge)
# --- shell (no front wall: the long-lens main camera sits outside the room at y=-5.67) ---
boxes += [
 {"name": "R3_Floor", "min": [-4.9, -4.5, -0.1], "max": [2.2, 4.8, 0], "mat": "R3_Floor"},
 {"name": "R3_Ceiling", "min": [-4.9, -4.5, H], "max": [2.2, 4.8, H + 0.1], "mat": "R3_Ceiling"},
 {"name": "R3_FeatureWall", "min": [XRET, YF, 0], "max": [XR, YF + T, H], "mat": "R3_Wall"},
 {"name": "R3_Return", "min": [XRET - T, YF, 0], "max": [XRET, YW, H], "mat": "R3_Wall"},
 {"name": "R3_RightWall", "min": [XR, -4.4, 0], "max": [XR + T, YF + T, H], "mat": "R3_WallRight"},
 {"name": "R3_LeftWall_Front", "min": [XL - T, -4.4, 0], "max": [XL, -0.2, H], "mat": "R3_Wall"},
 {"name": "R3_LeftWall_Head", "min": [XL - T, -0.2, 2.2], "max": [XL, 1.8, H], "mat": "R3_Wall"},
 {"name": "R3_LeftWall_Back", "min": [XL - T, 1.8, 0], "max": [XL, YW + T, H], "mat": "R3_Wall"},
 {"name": "R3_LeftRoom", "min": [-5.2, -0.4, 0], "max": [-5.1, 2.0, H], "mat": "R3_Dark"},
]
# --- wardrobe wall with the doorway at its far left (photo: opening edge x=-2.76, top z=1.80) ---
DX0, DX1, DH = -3.70, -2.80, 1.80
boxes += [
 {"name": "R3_WardWall_L", "min": [XL, YW, 0], "max": [DX0, YW + T, H], "mat": "R3_Wall"},
 {"name": "R3_WardWall_R", "min": [DX1, YW, 0], "max": [XRET - T, YW + T, H], "mat": "R3_Wall"},
 {"name": "R3_WardWall_Head", "min": [DX0, YW, DH], "max": [DX1, YW + T, H], "mat": "R3_Wall"},
 {"name": "R3_BackRoom", "min": [-4.4, 4.2, 0], "max": [-2.2, 4.3, H], "mat": "R3_BackWall"},
 {"name": "R3_BackRoom_Panel", "min": [-4.4, 4.17, 0], "max": [-2.2, 4.2, 1.31], "mat": "R3_Dark"},
 {"name": "R3_BackRoom_L", "min": [-3.95, YW + T, 0], "max": [-3.85, 4.2, H], "mat": "R3_BackWall"},
 {"name": "R3_BackRoom_R", "min": [-2.65, YW + T, 0], "max": [-2.55, 4.2, H], "mat": "R3_BackWall"},
]
c = 0.06   # side casings stop at DH: overlapping boxes render a black corner in Cycles
boxes += [
 {"name": "R3_DoorwayCasing_L", "min": [DX0 - c, YW - 0.02, 0], "max": [DX0, YW + 0.01, DH], "mat": "R3_PanelMold"},
 {"name": "R3_DoorwayCasing_R", "min": [DX1, YW - 0.02, 0], "max": [DX1 + c, YW + 0.01, DH], "mat": "R3_PanelMold"},
 {"name": "R3_DoorwayCasing_T", "min": [DX0 - c, YW - 0.02, DH], "max": [DX1 + c, YW + 0.01, DH + c], "mat": "R3_PanelMold"},
]
# --- panelled wall (photo: NOT a wardrobe slab — flat off-white wall with applied moulding frames,
#     upper row z 1.91..2.48, lower row 0.16..1.79, thin grooves between bays, same colour as the wall) ---
import numpy as _np
_px = [95, 120, 180, 222, 293, 365, 435]            # photo seams (px) -> x on the wall plane (hit_plane)
_x = [-2.696, -2.594, -2.348, -2.175, -1.884, -1.589, -1.302]
X = lambda px: float(_np.interp(px, _px, _x))
cols = [(120, 175), (178, 215), (218, 287), (290, 356), (358, 428)]
for k in ("R3_WardWall_L", "R3_WardWall_R", "R3_WardWall_Head"):
    for bx in boxes:
        if bx["name"] == k:
            bx["mat"] = "R3_Panel"
PU, PL = [1.91, 2.48], [0.16, 1.79]
for i, (p0, p1) in enumerate(cols):
    for nm, z in (("Up", PU), ("Lo", PL)):
        frames.append({"name": f"R3_PanelW{i}{nm}", "plane": WW, "side": -1, "a": [X(p0), X(p1)], "z": z,
                       "w": 0.03, "d": 0.015, "mat": "R3_PanelMold"})
for i, px in enumerate([176.5, 216.5, 288.5, 357, 431]):   # grooves between bays (darker one at 288)
    w = 0.012 if px == 288.5 else 0.005
    boxes.append({"name": f"R3_Groove{i}", "min": [X(px) - w / 2, YW - 0.002, 0.06], "max": [X(px) + w / 2, YW, 2.58], "mat": "R3_Groove"})
boxes.append({"name": "R3_GrooveH0", "min": [X(118), YW - 0.002, 1.80], "max": [X(431), YW, 1.805], "mat": "R3_Groove"})
boxes.append({"name": "R3_GrooveH1", "min": [X(118), YW - 0.002, 1.905], "max": [X(431), YW, 1.91], "mat": "R3_Groove"})
# bay left of the panels (above the doorway): one wide frame
frames.append({"name": "R3_PanelWL", "plane": WW, "side": -1, "a": [-3.62, -2.73], "z": PU, "w": 0.03, "d": 0.015, "mat": "R3_PanelMold"})
# --- right wall door (photo: leaf y -1.36..-0.41, top z 1.83), dark frame, handle near the far edge ---
DY0, DY1, DZ = -1.36, -0.41, 1.83
boxes += [
 {"name": "R3_Door", "min": [XR - 0.035, DY0, 0], "max": [XR, DY1, DZ], "mat": "R3_DoorWood", "uv": True},
 {"name": "R3_DoorFrame_L", "min": [XR - 0.05, DY0 - 0.05, 0], "max": [XR, DY0, DZ + 0.05], "mat": "R3_DoorFrame"},
 {"name": "R3_DoorFrame_R", "min": [XR - 0.05, DY1, 0], "max": [XR, DY1 + 0.05, DZ + 0.05], "mat": "R3_DoorFrame"},
 {"name": "R3_DoorFrame_T", "min": [XR - 0.05, DY0 - 0.05, DZ], "max": [XR, DY1 + 0.05, DZ + 0.05], "mat": "R3_DoorFrame"},
 {"name": "R3_DoorHandle", "min": [XR - 0.09, DY1 - 0.14, 0.9], "max": [XR - 0.035, DY1 - 0.06, 0.925], "mat": "R3_Handle"},
 {"name": "R3_DoorHandleRose", "min": [XR - 0.045, DY1 - 0.09, 0.87], "max": [XR - 0.035, DY1 - 0.06, 0.95], "mat": "R3_Handle"},
]
boxes.append({"name": "R3_Rug", "min": [-1.11, -0.51, 0], "max": [1.51, 1.57, 0.012], "mat": "R3_Rug", "uv": True})
# --- crown (photo: 2.60 -> ceiling) + baseboards ---
walls = [(FW, -1, [XRET, XR]), (RW, -1, [-4.4, YF]), (WW, -1, [XL, XRET - T]), (f"x={XRET}", 1, [YF, YW]),
         (f"x={XL}", 1, [-4.4, -0.2]), (f"x={XL}", 1, [1.8, YW])]
for k, (pl, sd, a) in enumerate(walls):
    runs.append({"name": f"R3_Crown{k}a", "plane": pl, "side": sd, "a": a, "z": [H - 0.12, H], "d": 0.03, "mat": "R3_PanelMold" if pl == WW else "R3_Molding"})
    runs.append({"name": f"R3_Crown{k}b", "plane": pl, "side": sd, "a": a, "z": [H - 0.05, H], "d": 0.07, "mat": "R3_PanelMold" if pl == WW else "R3_Molding"})
for k, (pl, sd, a) in enumerate([w for w in walls if w[0] != WW]):
    runs.append({"name": f"R3_Base{k}", "plane": pl, "side": sd, "a": a, "z": [0, 0.06], "d": 0.012, "mat": "R3_Molding"})
for k, a in enumerate([[XL, DX0 - c], [DX1 + c, XRET - T]]):
    runs.append({"name": f"R3_BaseW{k}", "plane": WW, "side": -1, "a": a, "z": [0, 0.06], "d": 0.012, "mat": "R3_PanelMold"})
# --- panel moldings (photo: feature x -0.90..1.84, upper z 1.97..2.57, lower 0.10..1.85; right wall same heights) ---
UP, LO, PW, PD = [1.97, 2.57], [0.10, 1.85], 0.035, 0.02
bays = {FW: [[-0.902, 1.841]],
        RW: [[-0.196, 1.84], [-2.90, -1.60], [-4.25, -3.05]],
        f"x={XL}": [[-2.25, -0.40], [-4.25, -2.40]]}
for pl, spans in bays.items():
    sd = 1 if pl.startswith("x=-") else -1
    for i, a in enumerate(spans):
        for nm, z in (("Up", UP), ("Lo", LO)):
            frames.append({"name": f"R3_Panel_{pl[0]}{i}{nm}{'L' if sd > 0 else ''}", "plane": pl, "side": sd, "a": a, "z": z, "w": PW, "d": PD, "mat": "R3_Molding"})
pass  # frames.append({"name": "R3_Panel_WD", "plane": WW, "side": -1, "a": [DX0 + 0.05, DX1 - 0.05], "z": [2.0, 2.50], "w": PW, "d": PD, "mat": "R3_Molding"})
# --- downlights where the photo shows them (cast onto the ceiling) + a front row ---
DL = [(-1.647, 0.322), (-0.611, 1.09), (1.414, 1.09), (-2.669, 2.534), (-1.649, 2.534), (-0.611, -1.2), (1.414, -1.2), (-2.669, -1.2)]
for i, (x, y) in enumerate(DL):
    discs.append({"name": f"R3_Downlight{i}", "at": [x, y, H - 0.004], "r": 0.04, "mat": "R3_Downlight"})
mat["R3_Ceiling"] = {"base": [0.528, 0.456, 0.34], "rough": 0.9}
# ONE paint for every wall, panel and moulding (photo: same cream everywhere; the warm back wall vs
# whiter panelled wall difference is LIGHT colour: warm sconces/lamp/wall-wash, neutral downlights)
PAINT, TRIM = [0.74, 0.68, 0.56], [0.76, 0.70, 0.58]
for k in ("R3_Wall", "R3_WallRight", "R3_Panel"):
    mat[k] = {"base": PAINT, "rough": 0.85}
for k in ("R3_Molding", "R3_PanelMold"):
    mat[k] = {"base": TRIM, "rough": 0.6}
mat["R3_Groove"] = {"base": [0.25, 0.23, 0.21], "rough": 0.9}
mat["R3_BackWall"] = {"base": [0.55, 0.53, 0.5], "rough": 0.9}
mat["R3_DoorWood"]["base"] = [1.61, 1.78, 1.82]
mat["R3_Floor"]["base"] = [0.96, 0.93, 0.82]
old_room = ["Floor", "Ceiling", "Wall_Feature", "Wall_Right", "Return_Feature", "Wall_Left_Back",
            "Wall_Left_Front", "Wall_Left_Header", "DarkRoom_Back", "Wall_Wardrobe"]
spec = {"materials": mat, "boxes": boxes, "runs": runs, "frames": frames, "discs": discs,
        "delete": old_room, "hide": ["F_rug"], "downlights": DL, "ceiling": H}
json.dump(spec, open(os.path.join(F, "room3d", "room3d.json"), "w"), indent=1)
print(len(boxes), len(runs), len(frames), len(discs))

# Camera solve from one interior image

Archviz renders use a level camera with lens shift (verticals stay vertical). Solve for:
eye height, distance to the back wall, focal length, shift_x/shift_y, room width/height.

1. **Vanishing point** of the receding walls: take two lines on a side wall (crown molding line and
   floor/skirting line), intersect them -> VP (u_vp, v_vp). `v_vp` is the horizon row.
2. **Lens shift** (Blender shift is relative to the larger image side W):
   `shift_x = (W/2 - u_vp) / W`, `shift_y = (v_vp - H/2) / W`.
   VP left of centre -> positive shift_x; horizon above centre -> negative shift_y. Verify with a render.
3. **Pixels per metre on the back wall (k)**: use stacked panel moldings or a known height. Example:
   upper panel 158 px + lower panel 430 px over 0.67 + 1.77 m -> k = 241 px/m.
   Floor row = lowest molding row + skirting offset * k. Room height = (floor_v - ceiling_v)/k.
   Back-wall width = (right corner u - left edge u)/k.
4. **Eye height** = (floor_v - v_vp)/k.
5. **Depth / focal**: one-point perspective can't give f alone. Use an object of known size on the
   floor near the wall: its floor contact row gives depth ratio Z/D = k*eye_h/(contact_v - v_vp);
   sofa depth ~0.9 m or width ~2.0 m, door ~2.1-2.4 m. Then D = sofa_depth / (1 - Z/D) and
   f_px = k*D, lens_mm = f_px*36/W. Typical archviz: 24-32 mm.
6. Camera location: x = back-wall-left + (u_vp - wall_left_u)/k, y = back_wall_y - D, z = eye_h,
   rotation (90°, 0, 0), sensor_fit HORIZONTAL, sensor 36 mm.
7. Rescale an existing room shell about the back-wall-left/floor pivot instead of rebuilding.
8. Check: render EEVEE 50%, run compare.py; back-wall left/right edges and ceiling line should land
   within ~5 px. Then sanity-check the first placed sofa: ~1.9-2.2 m wide, back against the wall.

9. **Verify the lens with a horizontal surface — the side walls alone can't.** Measure a table top in
   the reference (rows of its top back edge and top front edge). A wide lens shows far more of every
   top surface. If the render shows a fatter strip than the reference, the lens is too short / the eye
   too high: run `camera_search.py` (keeps the back wall framed, tries lens 28/35/45/55 mm × eye
   1.2/1.4/1.6 m, re-fits key objects, renders) and pick by the table strip + compare.py + eye.
   Living room: first solve 28 mm / 1.73 m looked down on everything (user: "camera angle not
   matching"); 45 mm / 1.2 m matched the furniture (table strip 903 vs 905 px), SSIM 0.491 -> 0.510,
   bench became a realistic 1 m long. A longer lens puts the camera outside the room (fine: clip_start,
   no front wall).
10. References are not always one consistent pinhole camera (composited / AI-assisted renders): the
   living-room side walls fit 28 mm while the furniture fits 45 mm. Prefer the lens that matches the
   FURNITURE (that's what viewers judge), then adapt side walls/doors if needed, and tell the user.
11. After any camera change re-place every non-wall object (wall objects on the framed back wall keep
   their projection). Move objects by their BOUNDS, not their origin — the rug's origin was offset and
   it ended up behind the wall. Keep the rug a few mm above the floor (solidify grows downward).

Living-room result: first 28 mm, eye 1.73 m, D 5.4 m; refined to 45 mm, eye 1.2 m, camera 8.67 m
from the back wall (y = -5.67), shift_y 0.021; wall 3.44 x 2.88 m.
Side-wall features (door edges) give their depth from `u - u_vp = f*X_wall/Z`.

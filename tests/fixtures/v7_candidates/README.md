# v7 candidate conformance scenes

Scenes added by the post-M8 review fixes; the merge step promotes them into `tests/conformance/` with the
one versioned v7 regeneration (contract §5.0.8).  One line per scene: what it pins down.

- `arch_ground.json` — arch-shaped prism standing on the ground (`rotation_deg [90,0,0]`), lamp below the lintel: one silhouette loop crosses the light plane four times; the angular arc pairing (D70) gives two unbounded ground loops (7.5 % of `[-15,15]²`, ray cast agrees); the loop-order pairing blackened the whole plane.
- `u_wall.json` — U-prism turned 25° straddling the plane through the lamp parallel to the wall at `y = 6`: its wall shadow is **empty** (the ray cast finds no shadowed wall point); before D70 the whole 15 m² plate was reported.
- `u_notch_wall.json` — U-prism on the ground, lamp in the notch below the arm tops, wall beyond the **opening** (`y = 3`): two loops on the wall (the arms' shadows), 46 % of the plate, IoU ≥ 0.99 with the ray cast; before D70 the plate was entirely in shadow.
- `u_on_side.json` — the same U lying on its side 2 m above the ground (`rotation_deg [-90,0,0]`), lamp in the notch: the v2 ground path with two excursions to infinity, two ground loops, IoU 1.00 with the ray cast.

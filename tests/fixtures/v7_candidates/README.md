# v7 candidate conformance scenes

Scenes added by the post-M8 review fixes; the merge step promotes them into `tests/conformance/` with the
one versioned v7 regeneration (contract §5.0.8).  One line per scene: what it pins down.

- `arch_ground.json` — arch-shaped prism standing on the ground (`rotation_deg [90,0,0]`), lamp below the lintel: one silhouette loop crosses the light plane four times; the angular arc pairing (D70) gives two unbounded ground loops (7.5 % of `[-15,15]²`, ray cast agrees); the loop-order pairing blackened the whole plane.
- `u_wall.json` — U-prism turned 25° straddling the plane through the lamp parallel to the wall at `y = 6`: its wall shadow is **empty** (the ray cast finds no shadowed wall point); before D70 the whole 15 m² plate was reported.
- `u_notch_wall.json` — U-prism on the ground, lamp in the notch below the arm tops, wall beyond the **opening** (`y = 3`): two loops on the wall (the arms' shadows), 46 % of the plate, IoU ≥ 0.99 with the ray cast; before D70 the plate was entirely in shadow.
- `u_on_side.json` — the same U lying on its side 2 m above the ground (`rotation_deg [-90,0,0]`), lamp in the notch: the v2 ground path with two excursions to infinity, two ground loops, IoU 1.00 with the ray cast.
- `spiral_upright.json` — 1.3-turn spiral prism on the ground, lamp inside at mid-height: every light-plane direction hits the solid; one `p = 1` loop whose arc sweeps more than a full turn after the base-level correction (ground IoU 1.00; 0.26 before).
- `spiral_tilted.json` — the same spiral pre-rotated 30° and tilted 15° about `x`, lamp inside: `p = 2`, two components whose first arc gets one extra turn (ground IoU 1.00; 0.03 with the minimal-level start alone).
- `spiral_floor.json` — the upright spiral with a bounded horizontal plate at `z = 0.25`: base-level correction on a receiver frame + bounds clip of an arc over 2π (97 % of the plate, IoU 1.00; 0.27 before).
- `u_closed_arm_wall.json` — U-prism on the ground, lamp in the notch, wall beyond the **closed** arm: a `p = 2` wall loop whose angular pairing equals the loop order; bit-identical to the v1 loop-order code.
- `mesh_noisy_l_ground_contact.json` (group loaders, m5-mesh#0): concave L prism mesh whose bottom vertices v3, v5 sit 1e-7 m below the ground (inside the 1e-6 weld/contact tolerance); expected outline = the clean L's, no `OBJECT_BELOW_RECEIVER`.
- `multilight_mesh_fallback_shared_edges.json` — m6-umbra#0: per-face fallback mesh (144 faces, shared edges) under two point lights; umbra = 14 pieces with the §5.3.4 step-5 zero-width bridging (514 before).

# Conformance set changelog

One entry per regeneration (newest last); see README.md.

## v1 — 2026-10-06

- reason: conformance set v1 (M3)
- regenerated (all cases, 34 changed): analytic_camera_level, analytic_camera_pitched, analytic_sphere_oblique_directional, analytic_sun_30deg_box, analytic_sun_45deg_box, analytic_unit_box_point_light_overhead, buried_box_tilted, buried_cylinder_tilted, camera_roll_and_shift, camera_yaw_pitch_form, concave_prism_light_foot_in_notch, degenerate_cylinder_cap_at_light_height, degenerate_directional_horizontal, degenerate_face_parallel_to_light_directional, degenerate_face_parallel_to_light_point, degenerate_light_at_camera_centre, degenerate_light_behind_viewer, degenerate_light_below_receiver, degenerate_light_inside_sphere, degenerate_light_parallel_to_picture_plane, degenerate_point_behind_camera, degenerate_vertex_above_point_light, degenerate_vertical_directional_light, example_basic, example_construction_demo, example_curved_demo, example_directional, example_three_point, random_seed0_3objects, random_seed14_2objects, random_seed23_2objects, random_seed38_2objects, random_seed3_3objects, random_seed9_3objects

## v2 — 2026-10-06

- reason: self-checks restricted to drawn rays (P, S, Q in front of the near plane) and nearly parallel construction lines (meet <= 1e-6) skipped; contract §2.7 [decision] after a hypothesis counter-example with a shadow point in the camera plane
- build: Python 3.13.16, numpy 2.5.3
- regenerated (all cases, 1 changed): degenerate_point_behind_camera
- unchanged: analytic_camera_level, analytic_camera_pitched, analytic_sphere_oblique_directional, analytic_sun_30deg_box, analytic_sun_45deg_box, analytic_unit_box_point_light_overhead, buried_box_tilted, buried_cylinder_tilted, camera_roll_and_shift, camera_yaw_pitch_form, concave_prism_light_foot_in_notch, degenerate_cylinder_cap_at_light_height, degenerate_directional_horizontal, degenerate_face_parallel_to_light_directional, degenerate_face_parallel_to_light_point, degenerate_light_at_camera_centre, degenerate_light_behind_viewer, degenerate_light_below_receiver, degenerate_light_inside_sphere, degenerate_light_parallel_to_picture_plane, degenerate_vertex_above_point_light, degenerate_vertical_directional_light, example_basic, example_construction_demo, example_curved_demo, example_directional, example_three_point, random_seed0_3objects, random_seed14_2objects, random_seed23_2objects, random_seed38_2objects, random_seed3_3objects, random_seed9_3objects

## v3 — 2026-10-06

- reason: comparator amendment for degenerate_cylinder_cap_at_light_height direction vertices (M7 design probe, contract §5.4.4 (1)); tests/conformance/rules.json becomes the single source of the comparator constants shared by the Python and the TypeScript runner (contract §5.4.8, §5.0.8); no expected file changed
- comparator amendment, no expected file changed
- expected files: unchanged (34 cases; rendered by the build of the last entry with a build line)
- rules diff (rules.json created):
  - added `arc_non_mm`: `["rotation_deg", "theta", "large_arc", "sweep"]`
  - added `case_overrides`: `{"degenerate_cylinder_cap_at_light_height": [{"abs_tol": 1e-06, "paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]], "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}`
  - added `drawable_containers`: `["arcs", "ellipses"]`
  - added `image_tol_mm`: `1e-06`
  - added `int_keys`: `["large_arc", "sweep"]`
  - added `max_reported`: `25`
  - added `mm_key_paths`: `[["construction", "segments", "*", "points"]]`
  - added `mm_keys`: `["image", "segment", "polygons", "polylines", "light_point", "shadow_vp", "v_mm", "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"]`
  - added `rel_tol`: `1e-09`
- rules (tests/conformance/rules.json at v3):

```json
{"arc_non_mm": ["rotation_deg", "theta", "large_arc", "sweep"], "case_overrides": {"degenerate_cylinder_cap_at_light_height": [{"abs_tol": 1e-06, "paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]], "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}, "drawable_containers": ["arcs", "ellipses"], "image_tol_mm": 1e-06, "int_keys": ["large_arc", "sweep"], "max_reported": 25, "mm_key_paths": [["construction", "segments", "*", "points"]], "mm_keys": ["image", "segment", "polygons", "polylines", "light_point", "shadow_vp", "v_mm", "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"], "rel_tol": 1e-09}
```

## v4 — 2026-10-07

- reason: M4 comparator additions (contract §5.0.8, §5.1.11): runs_rule (inside any runs entry mm within 0.05 mm absolute, s / t / theta within 1e-3 absolute, visible / interval and the run count exact; overrides arc_non_mm for theta inside runs), hidden_polylines as an mm key, the construction.per_receiver segments mm path, interval in int_keys; worktree-local entry, collapsed into the one v4 milestone entry written at the M4 merge (§5.0.8 rules 1-2)
- comparator amendment, no expected file changed
- expected files: unchanged (43 cases; rendered by the build of the last entry with a build line)
- rules diff (against the rules recorded in v3):
  - changed `int_keys`: + `"interval"`
  - changed `mm_key_paths`: + `["construction", "per_receiver", "*", "segments", "*", "points"]`
  - changed `mm_keys`: + `"hidden_polylines"`
  - added `runs_rule`: `{"exact_keys": ["visible", "interval"], "mm_abs": 0.05, "param_abs": 0.001, "param_keys": ["s", "t", "theta"]}`
- rules (tests/conformance/rules.json at v4):

```json
{"arc_non_mm": ["rotation_deg", "theta", "large_arc", "sweep"], "case_overrides": {"degenerate_cylinder_cap_at_light_height": [{"abs_tol": 1e-06, "paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]], "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}, "drawable_containers": ["arcs", "ellipses"], "image_tol_mm": 1e-06, "int_keys": ["large_arc", "sweep", "interval"], "max_reported": 25, "mm_key_paths": [["construction", "segments", "*", "points"], ["construction", "per_receiver", "*", "segments", "*", "points"]], "mm_keys": ["image", "segment", "polygons", "polylines", "hidden_polylines", "light_point", "shadow_vp", "v_mm", "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"], "rel_tol": 1e-09, "runs_rule": {"exact_keys": ["visible", "interval"], "mm_abs": 0.05, "param_abs": 0.001, "param_keys": ["s", "t", "theta"]}}
```

## v5 — 2026-10-07

- reason: M4: the nine M4 cases of contract §5.1.11 (bounded receivers, folds, RECEIVER_UNLIT, per-receiver construction, the anchor rule, sampled hidden lines incl. the w = 0 endpoint), added with --case in the M4 worktree; the 34 existing expected files are untouched here (their key-additive regeneration is the v4 run on the merged branch, §5.0.8 rule 2); worktree-local entry, collapsed into the one v4 milestone entry written at the M4 merge
- build: Python 3.13.16, numpy 2.5.3
- regenerated (selected cases, 9 changed): bounded_default_receiver, concave_prism_on_plate, fold_curved_cylinder, hidden_lines_curved_unbounded, hidden_lines_vp_in_canvas, receiver_directional_wall, receiver_unlit_wall, wall_and_ground, wall_and_ground_hidden


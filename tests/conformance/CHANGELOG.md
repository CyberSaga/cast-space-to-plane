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

- reason: v4: M4 key-additive regeneration (receivers, visibility runs, per_receiver, polygon_edges); 9 M4 cases added
- milestone entry (contract §5.0.8 rules 1-2): the one v4 entry of the M4 merge, collapsing the two worktree-local entries of the M4 worktree (its `--rules-only` comparator amendment and its `--case` run for the nine new cases) with the full key-additive regeneration of the 34 v2 cases, run once on the merged branch
- key-additivity check passed (contract §5.1.11): `tools/regen_conformance.py --strip-new-keys` on the merged branch before this run reported 43 of 43 case(s) with zero mismatches; the 34 v2 files are byte-identical to the new render after deleting the M4 keys with their switch-off values (`hidden_lines`, `receivers`, `construction.per_receiver`, `edges[].runs`, generator / terminator `visibility` + `runs`, conic `visibility` / `runs` / `hidden_polylines`, `shadows[].polygon_edges`): no number, name, string, boolean or warning changed
- build: Python 3.13.16, numpy 2.5.3
- regenerated (all cases, 34 changed): analytic_camera_level, analytic_camera_pitched, analytic_sphere_oblique_directional, analytic_sun_30deg_box, analytic_sun_45deg_box, analytic_unit_box_point_light_overhead, buried_box_tilted, buried_cylinder_tilted, camera_roll_and_shift, camera_yaw_pitch_form, concave_prism_light_foot_in_notch, degenerate_cylinder_cap_at_light_height, degenerate_directional_horizontal, degenerate_face_parallel_to_light_directional, degenerate_face_parallel_to_light_point, degenerate_light_at_camera_centre, degenerate_light_behind_viewer, degenerate_light_below_receiver, degenerate_light_inside_sphere, degenerate_light_parallel_to_picture_plane, degenerate_point_behind_camera, degenerate_vertex_above_point_light, degenerate_vertical_directional_light, example_basic, example_construction_demo, example_curved_demo, example_directional, example_three_point, random_seed0_3objects, random_seed14_2objects, random_seed23_2objects, random_seed38_2objects, random_seed3_3objects, random_seed9_3objects
- unchanged: bounded_default_receiver, concave_prism_on_plate, fold_curved_cylinder, hidden_lines_curved_unbounded, hidden_lines_vp_in_canvas, receiver_directional_wall, receiver_unlit_wall, wall_and_ground, wall_and_ground_hidden
- cases added (9, contract §5.1.11; rendered with `--case` in the M4 worktree and byte-identical on the merged branch, hence listed as unchanged above): bounded_default_receiver, concave_prism_on_plate, fold_curved_cylinder, hidden_lines_curved_unbounded, hidden_lines_vp_in_canvas, receiver_directional_wall, receiver_unlit_wall, wall_and_ground, wall_and_ground_hidden
- comparator amendment (tests/conformance/rules.json, contract §5.0.8 rule 3, §5.1.11: runs_rule — inside any runs entry mm within 0.05 mm absolute, s / t / theta within 1e-3 absolute, visible / interval and the run count exact, overriding arc_non_mm for theta inside runs; hidden_polylines as an mm key; the construction.per_receiver segments mm path; interval in int_keys)
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

- reason: v5: M5 mesh cases on top of v4
- build: Python 3.13.16, numpy 2.5.3
- regenerated (selected cases, 3 changed): mesh_box_welded_triangulated, mesh_open_bottom_box_fallback, mesh_smooth_prism16
- milestone entry (contract §5.0.8 rule 1): the one v5 entry of the M5 merge, collapsing the worktree-local `--case` entry of the M5 branch (numbered v4 there, before the M4 merge) after rebasing M5 onto v4; the three cases were re-rendered on the merged branch and now carry the M4 keys (`hidden_lines`, `receivers`, `construction.per_receiver`, `runs`, `visibility`, `hidden_polylines`, `polygon_edges`) with their switch-off values
- cases added (3, contract §5.2.11 / §5.2.12; post-expansion scenes with inline mesh `data`): mesh_box_welded_triangulated, mesh_open_bottom_box_fallback, mesh_smooth_prism16
- expected files: 0 of the 43 v4 cases changed (`tools/regen_conformance.py --dry-run` on the merged branch before this run: would change 3 of 46, the three new cases only); no comparator change (rules.json as recorded in v4)

## v6 — 2026-10-07

- reason: v6: M6 multi-light cases and the constructions mm paths on top of v5
- milestone entry (contract §5.0.8 rules 1-2): the one v6 entry of the M6 merge, collapsing the two worktree-local entries of the M6 worktree (its `--rules-only` comparator amendment, numbered v6 there, and its `--case` run for the four new cases, numbered v7 there) into one entry; no full-set regeneration (rule 2: that happens once, at v4)
- build: Python 3.13.16, numpy 2.5.3
- regenerated (selected cases, 4 changed): multilight_point_and_directional_curved, multilight_second_light_inactive, multilight_three_lights_concave_prism, multilight_two_point_symmetric_box
- cases added (4, contract §5.3.10; rendered with `--case` in the M6 worktree on top of v5 and byte-identical on the merged branch): multilight_two_point_symmetric_box (the hand-computed acceptance case), multilight_point_and_directional_curved (per-light curved names, terminators per light, umbra of sampled polygons, core), multilight_three_lights_concave_prism (N = 3, self-intersecting shadow loops; casters lifted 0.2 m so that no umbra predicate sits at its rounding threshold), multilight_second_light_inactive (LIGHT_BELOW_RECEIVER on the second light, empty umbra polygons)
- expected files: 0 of the 46 v5 cases changed (`tools/regen_conformance.py --dry-run` on the merged branch: would change 0 of 50); multi-light keys are conditional (§5.3.5), single-light documents are byte-identical to v5
- both runners green on v6 (contract §5.4.0 phase 2 acceptance, §5.0.8 row "v6 M7 phase 2"; M7 step 11 on `wt/m7`, no expected file and no rules change): the Python runner `tests/test_conformance.py` passes 50 of 50 cases; the TypeScript runner `ts/test/conformance.test.ts` (node 22.22.0, `node --test --test-reporter=tap ts/build/test/conformance.test.js`) reports `ok` for each of the 50 `conformance: <case>` tests, with `# fail 0`, `# skipped 0`, `# todo 0` and no todo list left in the runner; `tools/compare_svg.py` on the 50 cases: 0 mismatches, 0 boundary differences
- comparator amendment (tests/conformance/rules.json, contract §5.3.5, §5.0.8 rule 3): constructions.*.segments[].points and constructions.*.per_receiver.*.segments[].points are canvas mm (1e-6 mm), the per-light form of the construction paths
- rules diff (against the rules recorded in v4):
  - changed `mm_key_paths`: + `["constructions", "*", "segments", "*", "points"]`, + `["constructions", "*", "per_receiver", "*", "segments", "*", "points"]`
- rules (tests/conformance/rules.json at v6):

```json
{"arc_non_mm": ["rotation_deg", "theta", "large_arc", "sweep"], "case_overrides": {"degenerate_cylinder_cap_at_light_height": [{"abs_tol": 1e-06, "paths": [["shadows", "*", "loops", "*", "*", "direction"], ["shadows", "*", "outline", "*", "direction"]], "reason": "direction vertices at a tangent w_S = 0 crossing (curved._zero_shift, acos near |c| = 1): sqrt-type amplification, measured 1.5e-9 absolute per ulp of M or L"}]}, "drawable_containers": ["arcs", "ellipses"], "image_tol_mm": 1e-06, "int_keys": ["large_arc", "sweep", "interval"], "max_reported": 25, "mm_key_paths": [["construction", "segments", "*", "points"], ["construction", "per_receiver", "*", "segments", "*", "points"], ["constructions", "*", "segments", "*", "points"], ["constructions", "*", "per_receiver", "*", "segments", "*", "points"]], "mm_keys": ["image", "segment", "polygons", "polylines", "hidden_polylines", "light_point", "shadow_vp", "v_mm", "vanishing_points", "principal_point", "canvas_mm", "max_error_mm"], "rel_tol": 1e-09, "runs_rule": {"exact_keys": ["visible", "interval"], "mm_abs": 0.05, "param_abs": 0.001, "param_keys": ["s", "t", "theta"]}}
```

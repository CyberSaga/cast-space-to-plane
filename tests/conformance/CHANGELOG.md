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


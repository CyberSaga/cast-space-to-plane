/**
 * castplane — TypeScript port of the core (contract §5.4): perspective shadow construction drawing.
 *
 * ```ts
 * const scene = load_scene(json);              // validated, defaults filled (throws SceneError); expanded scenes only
 * const A     = shadow_geometry(scene);         // stage A: never touches scene.camera
 * const B     = project_scene(scene, A, camera?); // stage B: optional camera override (spec §4 camera block)
 * const doc   = compose(scene, B);              // stage C: spec §6.2 document, canonical floats
 * const svg   = write_svg(doc, layers?);        // string
 * const text  = dumps(doc);                     // deterministic JSON
 * const out   = render(scene, camera?);         // {geometry: doc, svg}
 * ```
 */

export const __version__ = "0.1.0";

export * from "./types.js";
export type * from "./document.js";
export { SceneError, WARNING_CODES, make_warning, merge_warnings, warning_codes } from "./errors.js";
export type { Warning } from "./errors.js";
export {
  LAYER_IDS, LIGHT_TYPES, OBJECT_TYPES, load_camera, load_scene, load_scene_text, polygon_is_simple, polygon_signed_area,
  validate_camera, validate_light, validate_object, validate_output, validate_receiver, validate_scene, validate_transform,
  // phase 2 (§5.4.2): the §5.0.1 rows
  LOADER_TYPES, to_z_up, validate_bounds, validate_hidden_output, validate_lights_in_scene, validate_mesh_data,
  validate_mesh_object, validate_receivers_in_scene,
} from "./scene.js";
export type { Camera, Light, Output, Receiver, Scene, SceneObject, Transform } from "./scene.js";
export { compose, construction_block, project_scene, render, shadow_geometry } from "./pipeline.js";
export type { StageA, StageB } from "./pipeline.js";
export { canonical, dumps, py_repr, INT_KEYS } from "./output/geometry_json.js";
export { HIDDEN_STROKE, HIDDEN_STYLES, LAYER_ORDER, OUTLINE_STYLE, STYLE, fmt, write_svg } from "./output/svg.js";
export { cmp_code_points, py_round, pyimod, pymod } from "./pyfloat.js";
export { apply_rotation, apply_transform, euler_zyx_matrix, rotation_x, rotation_y, rotation_z, transform_frame } from "./transform.js";
export {
  FALLBACK_UP, RECT_GROW, UP_WORLD, camera_forward, camera_matrix, clip_line_rect, clip_polygon_near, clip_polygon_rect_h,
  clip_segment_near, clip_segments_near, clip_segments_rect_h, depth, divide, horizon, nu, project, rect_functionals, vanishing_point,
} from "./camera.js";
export type { CameraRecord } from "./camera.js";
export { face_lit_flags, is_parallel, light_vector, lit, lit_state, silhouette_edges, silhouette_loops } from "./light.js";
export {
  ARC_STEP_DEG, bounds_functionals, clip_loop_to_plane, clip_mesh_to_plane, clip_polygon_bounds, foot, plate_loop, receiver_frame,
  shadow_loop, shadow_matrix, shadow_w,
} from "./shadow.js";
export {
  CURVED_SEGMENTS, SPHERE_RINGS, box_mesh, cone_mesh, cylinder_mesh, euler_characteristic, face_normals_newell, mesh_bbox,
  mesh_from_faces, prism_mesh, sphere_mesh, transform_mesh,
} from "./mesh.js";
export type { Mesh } from "./mesh.js";
export { CURVED_TYPES, analytic_record, build_object, face_tables, local_mesh, point_inside_solid } from "./primitives.js";
export {
  LINE_PARALLEL_REL, LINE_ZERO_REL, RAY_EXTENSION, clip_segments_uv, coincidence_check, covering_segments, extended_segments,
  self_check, special_point_image,
} from "./construction.js";
export * as conics from "./conics.js";
export * as curved from "./curved.js";
export * as multilight from "./multilight.js";
export * as hidden from "./hidden.js";
export { TOL_DIR, ZERO_REL, cross3, join, meet, normalize_max, row_max_abs, scene_scale, to_homogeneous, tolerance } from "./homogeneous.js";

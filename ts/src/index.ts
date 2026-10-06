/**
 * castplane — TypeScript port of the core (contract §5.4): perspective shadow construction drawing.
 *
 * ```ts
 * const scene = load_scene(json);              // validated, defaults filled (throws SceneError)
 * const A     = shadow_geometry(scene);         // stage A: never touches scene.camera
 * const B     = project_scene(scene, A, camera?); // stage B
 * const doc   = compose(scene, B);              // stage C: spec §6.2 document
 * const svg   = write_svg(doc, layers?);        // string
 * const text  = dumps(doc);                     // deterministic JSON
 * const out   = render(scene, camera?);         // {geometry: doc, svg}
 * ```
 */

export const __version__ = "0.1.0";

export * from "./types.js";
export { SceneError, WARNING_CODES, make_warning, merge_warnings, warning_codes } from "./errors.js";
export type { Warning } from "./errors.js";
export {
  LAYER_IDS, LIGHT_TYPES, OBJECT_TYPES, load_camera, load_scene, load_scene_text, validate_camera, validate_scene,
} from "./scene.js";
export type { Camera, Light, Output, Receiver, Scene, SceneObject, Transform } from "./scene.js";
export { canonical, dumps, py_repr, INT_KEYS } from "./output/geometry_json.js";
export { cmp_code_points, py_round, pyimod, pymod } from "./pyfloat.js";
export { transform_frame } from "./transform.js";

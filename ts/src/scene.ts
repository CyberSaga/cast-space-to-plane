/**
 * Scene JSON validation (port of `castplane/scene.py`; spec §4; contract §2.0, §5.4.3).
 *
 * `load_scene(data)` takes parsed JSON (no paths: the core has no file system) and returns a NEW object with every
 * default filled in, or throws `SceneError` with the JSON field path of the first rule that fails. Unknown keys are
 * ignored. `load_scene_text(text)` wraps `JSON.parse` (browser-safe).
 */

import { SceneError } from "./errors.js";
import type { Vec2, Vec3 } from "./types.js";

/** Object kinds of the core (contract §2.0; M5 adds `mesh`, §5.2.1 / §5.0.1). */
export const OBJECT_TYPES = ["box", "cylinder", "sphere", "cone", "prism", "mesh"] as const;
/** Loader-only object kinds (contract §5.0.1, M8): rejected by `validate_object` before the `OBJECT_TYPES` test. */
export const LOADER_TYPES = ["step"] as const;
export const LIGHT_TYPES = ["point", "directional"] as const;
/** The six SVG layer ids in table order (contract §2.10). */
export const LAYER_IDS = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"] as const;

const UNIT_TOL = 1e-9;

/** Size guard of a mesh object after loading (contract §5.2.1). */
export const MESH_MAX_FACES = 50000;
export const MESH_MAX_VERTICES = 50000;
/** Defaults of the optional mesh keys (contract §5.2.1). */
export const MESH_WELD_TOLERANCE_DEFAULT = 1e-6;
export const MESH_SMOOTH_ANGLE_DEFAULT = 30.0;
/** Ids that no object, receiver or light may take (the `*.hidden` SVG sub-groups, contract §5.0.1). */
export const RESERVED_IDS = ["hidden"] as const;
/** `output.hidden_style` values (contract §5.1.8). */
export const HIDDEN_STYLES = ["dashed", "omit"] as const;
/** Light ids rejected in a multi-light scene (contract §5.3.0, §5.3.6). */
export const RESERVED_LIGHT_IDS_MULTI = ["umbra", "core"] as const;
/** Object ids rejected in a multi-light scene (contract §5.0.1). */
export const RESERVED_OBJECT_IDS_MULTI = ["core"] as const;

export interface Transform {
  position: Vec3;
  rotation_deg: Vec3;
}

/** The validated inline geometry of a mesh object (contract §5.2.1). */
export interface MeshData {
  vertices: Vec3[];
  faces: number[][];
  smooth_groups: number[];
}

export interface SceneObject {
  id: string;
  type: string;
  size?: Vec3;
  radius?: number;
  height?: number;
  polygon?: Vec2[];
  // mesh (contract §5.2.1)
  path?: string | null;
  node?: string | number | null;
  data?: MeshData;
  up?: "z";
  scale?: number;
  weld_tolerance?: number;
  smooth_angle_deg?: number;
  transform: Transform;
}

export interface Light {
  id: string;
  type: string;
  position?: Vec3;
  direction?: Vec3;
}

export interface Receiver {
  id: string;
  type: "plane";
  /** `null` = unbounded (only the ground at `receivers[0]`, contract §5.1.1). */
  bounds: Vec3[] | null;
  normal: Vec3;
  offset: number;
}

export interface Camera {
  position: Vec3;
  target?: Vec3;
  yaw_deg?: number;
  pitch_deg?: number;
  roll_deg: number;
  focal_length_mm: number;
  frame_mm: Vec2;
  shift_mm: Vec2;
  near_m: number;
}

export interface Output {
  canvas_mm: Vec2;
  layers: string[];
  png_dpi: number;
  hidden_lines: boolean;
  hidden_style: "dashed" | "omit";
}

export interface Scene {
  version: "0.1";
  units: "m";
  up: "z";
  objects: SceneObject[];
  lights: Light[];
  receivers: Receiver[];
  camera: Camera;
  output: Output;
}

type Dict = Record<string, unknown>;

// ---------------------------------------------------------------------------
// small checkers
// ---------------------------------------------------------------------------

function has(d: Dict, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(d, key);
}

function get(d: Dict, key: string, fallback: unknown): unknown {
  return has(d, key) ? d[key] : fallback;
}

function is_number(x: unknown): x is number {
  return typeof x === "number" && Number.isFinite(x);
}

function number(value: unknown, field: string, positive = false): number {
  if (!is_number(value)) throw new SceneError(field, "must be a finite number");
  if (positive && value <= 0) throw new SceneError(field, "must be > 0");
  return value;
}

function vector(value: unknown, field: string, n: number, positive = false): number[] {
  if (!Array.isArray(value) || value.length !== n) throw new SceneError(field, `must be a list of ${n} numbers`);
  return value.map((v, i) => number(v, `${field}[${i}]`, positive));
}

function require_key(d: Dict, key: string, field: string): unknown {
  if (!has(d, key)) throw new SceneError(field ? `${field}.${key}` : key, "required");
  return d[key];
}

function dict(value: unknown, field: string): Dict {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new SceneError(field, "must be an object");
  return value as Dict;
}

function id(value: unknown, field: string, no_dot: boolean): string {
  if (typeof value !== "string" || value === "") throw new SceneError(field, "must be a non-empty string");
  if (no_dot && value.includes(".")) throw new SceneError(field, "must not contain '.'");
  return value;
}

function norm(v: readonly number[]): number {
  let s = 0;
  for (const c of v) s += c * c;
  return Math.sqrt(s);
}

function one_of(value: unknown, options: readonly string[]): boolean {
  return typeof value === "string" && options.includes(value);
}

/** Python `%g`-like text for messages (informative only). */
function g(x: number): string {
  return String(Number(x.toPrecision(6)));
}

// ---------------------------------------------------------------------------
// polygon helpers (prism validation, contract §2.0)
// ---------------------------------------------------------------------------

/** Shoelace signed area; positive for counter-clockwise polygons (contract §2.1). Sequential sum (§5.4.4 (3)). */
export function polygon_signed_area(poly: readonly (readonly number[])[]): number {
  let area = 0.0;
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const p = poly[i] as readonly number[];
    const q = poly[(i + 1) % n] as readonly number[];
    area += (p[0] as number) * (q[1] as number) - (q[0] as number) * (p[1] as number);
  }
  return 0.5 * area;
}

function orient(a: readonly number[], b: readonly number[], c: readonly number[]): number {
  return ((b[0] as number) - (a[0] as number)) * ((c[1] as number) - (a[1] as number))
    - ((b[1] as number) - (a[1] as number)) * ((c[0] as number) - (a[0] as number));
}

function on_segment(a: readonly number[], b: readonly number[], p: readonly number[], eps: number): boolean {
  const ax = a[0] as number, ay = a[1] as number, bx = b[0] as number, by = b[1] as number;
  const px = p[0] as number, py = p[1] as number;
  return Math.min(ax, bx) - eps <= px && px <= Math.max(ax, bx) + eps
    && Math.min(ay, by) - eps <= py && py <= Math.max(ay, by) + eps;
}

function segments_intersect(a: readonly number[], b: readonly number[], c: readonly number[], d: readonly number[],
  eps_area: number, eps_len: number): boolean {
  const o1 = orient(a, b, c), o2 = orient(a, b, d);
  const o3 = orient(c, d, a), o4 = orient(c, d, b);
  if (((o1 > eps_area && o2 < -eps_area) || (o1 < -eps_area && o2 > eps_area))
    && ((o3 > eps_area && o4 < -eps_area) || (o3 < -eps_area && o4 > eps_area))) return true;
  if (Math.abs(o1) <= eps_area && on_segment(a, b, c, eps_len)) return true;
  if (Math.abs(o2) <= eps_area && on_segment(a, b, d, eps_len)) return true;
  if (Math.abs(o3) <= eps_area && on_segment(c, d, a, eps_len)) return true;
  if (Math.abs(o4) <= eps_area && on_segment(c, d, b, eps_len)) return true;
  return false;
}

/** True when no two non-adjacent edges touch (no self-intersection). */
export function polygon_is_simple(poly: readonly (readonly number[])[], eps_area: number, eps_len?: number): boolean {
  const el = eps_len === undefined ? Math.sqrt(eps_area) : eps_len;
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const a = poly[i] as readonly number[], b = poly[(i + 1) % n] as readonly number[];
    for (let j = i + 1; j < n; j++) {
      if (j === i || (j + 1) % n === i || (i + 1) % n === j) continue;
      const c = poly[j] as readonly number[], d = poly[(j + 1) % n] as readonly number[];
      if (segments_intersect(a, b, c, d, eps_area, el)) return false;
    }
  }
  return true;
}

function validate_polygon(value: unknown, field: string): Vec2[] {
  if (!Array.isArray(value) || value.length < 3) {
    throw new SceneError(field, "must be a list of at least 3 [x, y] vertices");
  }
  let poly = value.map((p, i) => vector(p, `${field}[${i}]`, 2) as Vec2);
  let extent = 0;
  for (const p of poly) for (const c of p) extent = Math.max(extent, Math.abs(c));
  extent = Math.max(extent, 1e-300);
  const eps_len = 1e-12 * extent;
  const n = poly.length;
  for (let i = 0; i < n; i++) {
    const a = poly[i] as Vec2, b = poly[(i + 1) % n] as Vec2;
    if (Math.hypot(b[0] - a[0], b[1] - a[1]) <= eps_len) throw new SceneError(`${field}[${i}]`, "consecutive vertices coincide");
  }
  const area = polygon_signed_area(poly);
  if (Math.abs(area) <= 1e-12 * extent * extent) {
    throw new SceneError(field, "zero area: vertices are collinear or the polygon is self-intersecting");
  }
  if (!polygon_is_simple(poly, 1e-12 * extent * extent, eps_len)) throw new SceneError(field, "polygon is self-intersecting");
  if (area < 0) poly = poly.slice().reverse(); // clockwise input is reversed silently (contract §2.0)
  return poly;
}

// ---------------------------------------------------------------------------
// block validators
// ---------------------------------------------------------------------------

/** `transform` block (contract §2.0): optional, `scale` forbidden. */
export function validate_transform(value: unknown, field: string): Transform {
  if (value === undefined || value === null) return { position: [0.0, 0.0, 0.0], rotation_deg: [0.0, 0.0, 0.0] };
  const t = dict(value, field);
  if (has(t, "scale")) throw new SceneError(`${field}.scale`, "scale is not supported; use the size parameters");
  return {
    position: vector(get(t, "position", [0.0, 0.0, 0.0]), `${field}.position`, 3) as Vec3,
    rotation_deg: vector(get(t, "rotation_deg", [0.0, 0.0, 0.0]), `${field}.rotation_deg`, 3) as Vec3,
  };
}

/** One `objects[i]` entry (contract §2.0). */
export function validate_object(value: unknown, field: string): SceneObject {
  const o = dict(value, field);
  const oid = id(require_key(o, "id", field), `${field}.id`, true);
  const typ = require_key(o, "type", field);
  if (one_of(typ, LOADER_TYPES)) {
    throw new SceneError(`${field}.type`,
      `loader object type '${typ as string}' must be expanded first (castplane.io.expand_scene or 'castplane import')`);
  }
  if (!one_of(typ, OBJECT_TYPES)) throw new SceneError(`${field}.type`, `must be one of ${OBJECT_TYPES.join(", ")}`);
  const out: SceneObject = { id: oid, type: typ as string, transform: { position: [0, 0, 0], rotation_deg: [0, 0, 0] } };
  if (typ === "box") {
    out.size = vector(require_key(o, "size", field), `${field}.size`, 3, true) as Vec3;
  } else if (typ === "cylinder" || typ === "cone") {
    out.radius = number(require_key(o, "radius", field), `${field}.radius`, true);
    out.height = number(require_key(o, "height", field), `${field}.height`, true);
  } else if (typ === "sphere") {
    out.radius = number(require_key(o, "radius", field), `${field}.radius`, true);
  } else if (typ === "prism") {
    out.polygon = validate_polygon(require_key(o, "polygon", field), `${field}.polygon`);
    out.height = number(require_key(o, "height", field), `${field}.height`, true);
  } else if (typ === "mesh") {
    Object.assign(out, validate_mesh_object(o, field));
  }
  out.transform = validate_transform(o["transform"], `${field}.transform`);
  return out;
}

/** One `lights[i]` entry (contract §2.0). */
export function validate_light(value: unknown, field: string): Light {
  const lt = dict(value, field);
  const lid = id(require_key(lt, "id", field), `${field}.id`, true);
  const typ = require_key(lt, "type", field);
  if (!one_of(typ, LIGHT_TYPES)) throw new SceneError(`${field}.type`, `must be one of ${LIGHT_TYPES.join(", ")}`);
  const out: Light = { id: lid, type: typ as string };
  if (typ === "point") {
    out.position = vector(require_key(lt, "position", field), `${field}.position`, 3) as Vec3;
  } else {
    const d = vector(require_key(lt, "direction", field), `${field}.direction`, 3) as Vec3;
    if (Math.abs(norm(d) - 1.0) > UNIT_TOL) throw new SceneError(`${field}.direction`, "must be a unit vector (|d| = 1 within 1e-9)");
    out.direction = d;
  }
  return out;
}

/** One `receivers[i]` entry (contract §2.0 as amended by §5.1.1): any plane `n·x + d = 0` with `|n| = 1`, optional
 * convex `bounds` (`validate_bounds`). The rules that need the receiver's index or the other blocks are checked by
 * `validate_receivers_in_scene`. */
export function validate_receiver(value: unknown, field: string): Receiver {
  const r = dict(value, field);
  const rid = id(require_key(r, "id", field), `${field}.id`, true);
  const typ = require_key(r, "type", field);
  if (typ !== "plane") throw new SceneError(`${field}.type`, "must be 'plane'");
  let n = vector(require_key(r, "normal", field), `${field}.normal`, 3) as Vec3;
  if (Math.abs(norm(n) - 1.0) > UNIT_TOL) throw new SceneError(`${field}.normal`, "must be a unit vector (|n| = 1 within 1e-9)");
  let offset = number(get(r, "offset", 0.0), `${field}.offset`);
  const raw_bounds = get(r, "bounds", null);
  const bounds = raw_bounds === null ? null : validate_bounds(raw_bounds, n, offset, `${field}.bounds`);
  if (bounds === null && is_ground(n, offset)) {
    n = [0.0, 0.0, 1.0]; // the unbounded ground keeps the literal v1 plane
    offset = 0.0;
  }
  return { id: rid, type: "plane", bounds, normal: n, offset };
}

/** `camera` block (contract §2.0): target form or yaw/pitch form, exactly one. */
export function validate_camera(value: unknown, field = "camera"): Camera {
  const c = dict(value, field);
  const position = vector(require_key(c, "position", field), `${field}.position`, 3) as Vec3;
  const out: Partial<Camera> & { position: Vec3 } = { position };
  const has_target = has(c, "target");
  const has_yp = has(c, "yaw_deg") || has(c, "pitch_deg");
  if (has_target && has_yp) throw new SceneError(field, "give either target or yaw_deg + pitch_deg, not both");
  if (has_target) {
    const t = vector(c["target"], `${field}.target`, 3) as Vec3;
    if (norm([t[0] - position[0], t[1] - position[1], t[2] - position[2]]) <= 1e-12) {
      throw new SceneError(`${field}.target`, "must differ from position");
    }
    out.target = t;
  } else if (has_yp) {
    if (!has(c, "yaw_deg") || !has(c, "pitch_deg")) throw new SceneError(field, "yaw_deg and pitch_deg must be given together");
    out.yaw_deg = number(c["yaw_deg"], `${field}.yaw_deg`);
    out.pitch_deg = number(c["pitch_deg"], `${field}.pitch_deg`);
  } else {
    throw new SceneError(field, "needs target or yaw_deg + pitch_deg");
  }
  out.roll_deg = number(get(c, "roll_deg", 0.0), `${field}.roll_deg`);
  out.focal_length_mm = number(require_key(c, "focal_length_mm", field), `${field}.focal_length_mm`, true);
  out.frame_mm = vector(require_key(c, "frame_mm", field), `${field}.frame_mm`, 2, true) as Vec2;
  out.shift_mm = vector(get(c, "shift_mm", [0.0, 0.0]), `${field}.shift_mm`, 2) as Vec2;
  out.near_m = number(get(c, "near_m", 0.05), `${field}.near_m`, true);
  return out as Camera;
}

/** `output` block (contract §2.0): canvas aspect must equal the frame aspect. */
export function validate_output(value: unknown, frame_mm: readonly number[], field = "output"): Output {
  const o = dict(value, field);
  const canvas = vector(require_key(o, "canvas_mm", field), `${field}.canvas_mm`, 2, true) as Vec2;
  const f0 = frame_mm[0] as number, f1 = frame_mm[1] as number;
  if (Math.abs(canvas[0] / canvas[1] - f0 / f1) > 1e-9) {
    const ratio = f0 / f1;
    throw new SceneError(`${field}.canvas_mm`,
      `aspect ratio ${g(canvas[0])}/${g(canvas[1])} = ${Number((canvas[0] / canvas[1]).toPrecision(4))} must equal `
      + `camera.frame_mm aspect ratio ${g(f0)}/${g(f1)} = ${Number(ratio.toPrecision(4))} `
      + `(e.g. canvas_mm [${g(canvas[1] * ratio)}, ${g(canvas[1])}] or frame_mm [${g(f0)}, ${g(f0 * canvas[1] / canvas[0])}])`);
  }
  const layers = get(o, "layers", [...LAYER_IDS]);
  if (!Array.isArray(layers)) throw new SceneError(`${field}.layers`, "must be a list of layer ids");
  if (layers.length === 0) throw new SceneError(`${field}.layers`, "must not be empty (omit the key to get all six layers)");
  layers.forEach((name, i) => {
    if (!one_of(name, LAYER_IDS)) throw new SceneError(`${field}.layers[${i}]`, `must be one of ${LAYER_IDS.join(", ")}`);
  });
  if (new Set(layers).size !== layers.length) throw new SceneError(`${field}.layers`, "layer ids must be unique");
  return {
    canvas_mm: canvas,
    layers: LAYER_IDS.filter((name) => layers.includes(name)),
    png_dpi: number(get(o, "png_dpi", 300), `${field}.png_dpi`, true),
    ...validate_hidden_output(o, field),
  };
}

/** Validate a scene against the table of contract §2.0; returns a new object with defaults. */
export function validate_scene(scene: unknown): Scene {
  const s = dict(scene, "scene");
  const version = require_key(s, "version", "");
  if (version !== "0.1") throw new SceneError("version", "must be '0.1'");
  if (get(s, "units", "m") !== "m") throw new SceneError("units", "must be 'm'");
  if (get(s, "up", "z") !== "z") throw new SceneError("up", "must be 'z'");

  const objects = require_key(s, "objects", "");
  if (!Array.isArray(objects) || objects.length === 0) throw new SceneError("objects", "must be a non-empty list");
  const out_objects: SceneObject[] = [];
  let seen = new Set<string>();
  objects.forEach((o, i) => {
    const vo = validate_object(o, `objects[${i}]`);
    if (seen.has(vo.id)) throw new SceneError(`objects[${i}].id`, `duplicate object id '${vo.id}'`);
    seen.add(vo.id);
    out_objects.push(vo);
  });

  const lights = require_key(s, "lights", "");
  if (!Array.isArray(lights) || lights.length === 0) throw new SceneError("lights", "must be a non-empty list");
  const out_lights: Light[] = [];
  seen = new Set<string>();
  lights.forEach((lt, i) => {
    const vl = validate_light(lt, `lights[${i}]`);
    if (seen.has(vl.id)) throw new SceneError(`lights[${i}].id`, `duplicate light id '${vl.id}'`);
    seen.add(vl.id);
    out_lights.push(vl);
  });
  validate_lights_in_scene(out_lights, out_objects);

  const receivers = require_key(s, "receivers", "");
  if (!Array.isArray(receivers) || receivers.length === 0) throw new SceneError("receivers", "must be a non-empty list");
  const out_receivers = receivers.map((r, i) => validate_receiver(r, `receivers[${i}]`));
  validate_receivers_in_scene(out_receivers, out_objects, out_lights);

  const camera = validate_camera(require_key(s, "camera", ""), "camera");
  const output = validate_output(require_key(s, "output", ""), camera.frame_mm, "output");
  return {
    version: "0.1",
    units: "m",
    up: "z",
    objects: out_objects,
    lights: out_lights,
    receivers: out_receivers,
    camera,
    output,
  };
}

/** Validate parsed scene JSON (contract §3; no paths in the core, §5.4.2). */
export function load_scene(data: unknown): Scene {
  return validate_scene(data);
}

/** Parse and validate scene JSON text: invalid JSON -> `SceneError("", "invalid JSON: …")`. */
export function load_scene_text(text: string): Scene {
  let data: unknown;
  try {
    data = JSON.parse(text);
  } catch (exc) {
    throw new SceneError("", `invalid JSON: ${exc instanceof Error ? exc.message : String(exc)}`);
  }
  return validate_scene(data);
}

/** A camera override: either a `camera` block or a scene holding one. */
export function load_camera(data: unknown): Camera {
  let d = data;
  if (typeof d === "object" && d !== null && !Array.isArray(d) && has(d as Dict, "camera") && !has(d as Dict, "position")) {
    d = (d as Dict)["camera"];
  }
  return validate_camera(d, "camera");
}

// ---------------------------------------------------------------------------
// M4 (contract §5.1.1, §5.0.1): bounded receivers, hidden-line output switches, reserved ids
// ---------------------------------------------------------------------------

/** The plane is the ground `z = 0` (`normal == [0, 0, 1]` and `offset == 0` within 1e-9). */
function is_ground(n: readonly number[], offset: number): boolean {
  const g0 = [0.0, 0.0, 1.0];
  for (let i = 0; i < 3; i++) if (!(Math.abs((n[i] as number) - (g0[i] as number)) <= UNIT_TOL)) return false;
  return Math.abs(offset) <= UNIT_TOL;
}

/** `receivers[i].bounds` (contract §5.1.1): >= 3 world points on the plane `n·x + d = 0` forming a simple strictly
 * convex polygon; a clockwise list (about `n`) is reversed silently, so the stored order is counter-clockwise about
 * `n` seen from the positive side. */
export function validate_bounds(value: unknown, normal: readonly number[], offset: number, field: string): Vec3[] {
  if (!Array.isArray(value) || value.length < 3) throw new SceneError(field, "must be a list of at least 3 [x, y, z] vertices");
  let pts = value.map((p, k) => vector(p, `${field}[${k}]`, 3) as Vec3);
  const n0 = normal[0] as number, n1 = normal[1] as number, n2 = normal[2] as number;
  const d = offset;
  let ext = 0;
  for (const p of pts) for (const c of p) ext = Math.max(ext, Math.abs(c));
  ext = Math.max(1.0, ext);
  const m = pts.length;
  pts.forEach((p, k) => { // (1) coplanar
    if (Math.abs(n0 * p[0] + n1 * p[1] + n2 * p[2] + d) > 1e-9 * ext) {
      throw new SceneError(`${field}[${k}]`, "must lie in the receiver plane (|n·b + offset| <= 1e-9 · extent)");
    }
  });
  const edges: Vec3[] = [];
  for (let k = 0; k < m; k++) {
    const a = pts[k] as Vec3, b = pts[(k + 1) % m] as Vec3;
    edges.push([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
  }
  const lengths = edges.map((e) => norm(e));
  for (let k = 0; k < m; k++) { // (2) consecutive vertices distinct
    if (!((lengths[k] as number) > 1e-12 * ext)) throw new SceneError(`${field}[${k}]`, "consecutive vertices coincide");
  }
  const cross: number[] = [], dot: number[] = [];
  for (let k = 0; k < m; k++) {
    const a = edges[k] as Vec3, b = edges[(k + 1) % m] as Vec3;
    const c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]] as Vec3;
    cross.push(c[0] * n0 + c[1] * n1 + c[2] * n2);
    dot.push(a[0] * b[0] + a[1] * b[1] + a[2] * b[2]);
  }
  const message = "must be a simple strictly convex polygon";
  const sigma = (cross[0] as number) > 0.0 ? 1.0 : -1.0;
  for (let k = 0; k < m; k++) { // (3) strictly convex
    if (sigma * (cross[k] as number) <= 1e-9 * (lengths[k] as number) * (lengths[(k + 1) % m] as number)) {
      throw new SceneError(field, message);
    }
  }
  let turning = 0;
  for (let k = 0; k < m; k++) turning += Math.atan2(sigma * (cross[k] as number), dot[k] as number);
  if (Math.abs(turning - 2.0 * Math.PI) > 1e-9 * m) throw new SceneError(field, message); // (4) simple
  if (sigma < 0.0) pts = pts.slice().reverse(); // (5) clockwise -> reversed silently
  return pts;
}

/** `output.hidden_lines` (boolean, default false) and `output.hidden_style` (`"dashed"` default, or `"omit"`) of
 * contract §5.1.1 / §5.0.1. */
export function validate_hidden_output(o: Record<string, unknown>, field = "output"): { hidden_lines: boolean; hidden_style: "dashed" | "omit" } {
  const hidden = get(o, "hidden_lines", false);
  if (typeof hidden !== "boolean") throw new SceneError(`${field}.hidden_lines`, "must be a boolean");
  const style = get(o, "hidden_style", "dashed");
  if (!one_of(style, HIDDEN_STYLES)) throw new SceneError(`${field}.hidden_style`, `must be one of ${HIDDEN_STYLES.join(", ")}`);
  return { hidden_lines: hidden, hidden_style: style as "dashed" | "omit" };
}

/** The scene-level receiver rules of contract §5.1.1 / §5.0.1: ids unique, not reserved and disjoint from object and
 * light ids; a receiver without `bounds` only at index 0 and only for the ground plane; with an unbounded ground every
 * bounds vertex is above it. Also the reserved-id rule for object and light ids (`hidden`). */
export function validate_receivers_in_scene(receivers: readonly Receiver[], objects: readonly SceneObject[], lights: readonly Light[]): void {
  const blocks: [string, readonly { id: string }[]][] = [["objects", objects], ["lights", lights], ["receivers", receivers]];
  for (const [kind, items] of blocks) {
    items.forEach((item, i) => {
      if ((RESERVED_IDS as readonly string[]).includes(item.id)) throw new SceneError(`${kind}[${i}].id`, "reserved id");
    });
  }
  const object_ids = new Set(objects.map((o) => o.id));
  const light_ids = new Set(lights.map((lt) => lt.id));
  const seen = new Set<string>();
  receivers.forEach((r, i) => {
    const rid = r.id;
    if (seen.has(rid)) throw new SceneError(`receivers[${i}].id`, `duplicate receiver id '${rid}'`);
    seen.add(rid);
    if (object_ids.has(rid)) throw new SceneError(`receivers[${i}].id`, `receiver id '${rid}' is also an object id`);
    if (light_ids.has(rid)) throw new SceneError(`receivers[${i}].id`, `receiver id '${rid}' is also a light id`);
    if (r.bounds === null && !(i === 0 && is_ground(r.normal, r.offset))) {
      throw new SceneError(`receivers[${i}].bounds`, "required unless the receiver is the ground plane at receivers[0]");
    }
  });
  if ((receivers[0] as Receiver).bounds === null) {
    receivers.forEach((r, i) => {
      if (r.bounds === null) return;
      let ext = 0;
      for (const p of r.bounds) for (const c of p) ext = Math.max(ext, Math.abs(c));
      ext = Math.max(1.0, ext);
      r.bounds.forEach((p, k) => {
        if (p[2] < -1e-9 * ext) throw new SceneError(`receivers[${i}].bounds[${k}]`, "below the ground receiver");
      });
    });
  }
}

// ---------------------------------------------------------------------------
// M5: mesh objects (contract §5.2.1, §5.0.1)
// ---------------------------------------------------------------------------

/** The exact axis map `(x, y, z) -> (x, -z, y)` by component swapping and sign change (contract §5.2.1, D31);
 * `-z + 0` keeps the floats canonical. */
export function to_z_up(vertices: readonly (readonly number[])[]): Vec3[] {
  return vertices.map((v) => [v[0] as number, -(v[2] as number) + 0.0, v[1] as number] as Vec3);
}

/** A JSON integer (JavaScript has one number type: an integral JSON number such as `1.0` counts as an integer here,
 * where Python's `json` would give a float and reject it; contract §5.4.4 / §5.4.5 single-number-type note). */
function is_index(x: unknown): x is number {
  return typeof x === "number" && Number.isInteger(x);
}

/** `objects[i].data` of a mesh object (contract §5.2.1): `vertices` (>= 3 finite `[x, y, z]`), `faces` (>= 1 integer
 * lists of >= 3 indices in `[0, n_v)`), optional `smooth_groups` (non-negative integers, one per face, default all 0)
 * and the size guard; `source_field` (`objects[i].path` for file sources) is the field of the size-guard error. */
export function validate_mesh_data(value: unknown, field: string, source_field: string | null = null): MeshData {
  const d = dict(value, field);
  const verts = require_key(d, "vertices", field);
  if (!Array.isArray(verts) || verts.length < 3) throw new SceneError(`${field}.vertices`, "must be a list of at least 3 [x, y, z] vertices");
  if (verts.length > MESH_MAX_VERTICES) {
    throw new SceneError(source_field ?? `${field}.vertices`, `${verts.length} vertices exceed the limit of ${MESH_MAX_VERTICES}`);
  }
  const vertices = verts.map((v, k) => vector(v, `${field}.vertices[${k}]`, 3) as Vec3);
  const faces_in = require_key(d, "faces", field);
  if (!Array.isArray(faces_in) || faces_in.length < 1) throw new SceneError(`${field}.faces`, "must be a non-empty list of faces");
  if (faces_in.length > MESH_MAX_FACES) {
    throw new SceneError(source_field ?? `${field}.faces`, `${faces_in.length} faces exceed the limit of ${MESH_MAX_FACES}`);
  }
  const n_v = vertices.length;
  const faces: number[][] = [];
  faces_in.forEach((f, k) => {
    if (!Array.isArray(f) || f.length < 3) throw new SceneError(`${field}.faces[${k}]`, "must be a list of at least 3 vertex indices");
    for (const v of f) {
      if (!is_index(v) || !(0 <= v && v < n_v)) throw new SceneError(`${field}.faces[${k}]`, `vertex indices must be integers in [0, ${n_v})`);
    }
    faces.push((f as number[]).map((v) => v));
  });
  const groups = get(d, "smooth_groups", null);
  let smooth_groups: number[];
  if (groups === null) {
    smooth_groups = faces.map(() => 0);
  } else {
    if (!Array.isArray(groups) || groups.length !== faces.length) {
      throw new SceneError(`${field}.smooth_groups`, "must be a list with one entry per face");
    }
    groups.forEach((g0, k) => {
      if (!is_index(g0) || g0 < 0) throw new SceneError(`${field}.smooth_groups[${k}]`, "must be a non-negative integer");
    });
    smooth_groups = (groups as number[]).map((g0) => g0);
  }
  return { vertices, faces, smooth_groups };
}

/** Usable-face guard of a mesh object (contract §5.2.1 [decision]: "validated => renders"). Installed by
 * `src/meshprep.ts` (phase 2, the mesh part of §5.4.14) through `set_mesh_usable_face_guard`; until then every mesh
 * that passes `validate_mesh_data` is accepted. */
type UsableFaceGuard = (vertices: readonly Vec3[], faces: readonly number[][], scale: number, weld_tolerance: number) => boolean;
let usable_face_guard: UsableFaceGuard | null = null;

export function set_mesh_usable_face_guard(guard: UsableFaceGuard | null): void {
  usable_face_guard = guard;
}

/** The `mesh` branch of `validate_object` (contract §5.2.1, §5.0.1): `data` is required ("expand first" for a
 * `path`-only object); both together mean "already expanded"; `up: "y"` converts `data` with `to_z_up` and is
 * rewritten to `"z"`. */
export function validate_mesh_object(o: Record<string, unknown>, field: string): Partial<SceneObject> {
  const path = get(o, "path", null);
  if (path !== null && (typeof path !== "string" || path === "")) throw new SceneError(`${field}.path`, "must be a non-empty string");
  if (!has(o, "data")) {
    if (path === null) throw new SceneError(`${field}.data`, "required");
    throw new SceneError(`${field}.path`, "mesh file must be expanded first (castplane.io.expand_scene or 'castplane import')");
  }
  const node = get(o, "node", null);
  if (node !== null && !(typeof node === "string" || (is_index(node) && node >= 0))) {
    throw new SceneError(`${field}.node`, "must be a string or a non-negative integer");
  }
  const up = get(o, "up", "z");
  if (up !== "z" && up !== "y") throw new SceneError(`${field}.up`, "must be 'z' or 'y'");
  const scale = number(get(o, "scale", 1.0), `${field}.scale`, true);
  const weld = number(get(o, "weld_tolerance", MESH_WELD_TOLERANCE_DEFAULT), `${field}.weld_tolerance`);
  if (weld < 0) throw new SceneError(`${field}.weld_tolerance`, "must be >= 0");
  const smooth = number(get(o, "smooth_angle_deg", MESH_SMOOTH_ANGLE_DEFAULT), `${field}.smooth_angle_deg`);
  if (!(0.0 <= smooth && smooth <= 180.0)) throw new SceneError(`${field}.smooth_angle_deg`, "must be in [0, 180]");
  const source_field = path !== null ? `${field}.path` : null;
  const data = validate_mesh_data(o["data"], `${field}.data`, source_field);
  if (up === "y") data.vertices = to_z_up(data.vertices);
  if (usable_face_guard !== null && !usable_face_guard(data.vertices, data.faces, scale, weld)) {
    throw new SceneError(source_field ?? `${field}.data.faces`, "no usable face");
  }
  return {
    path: path as string | null,
    ["node"]: node as string | number | null,
    data,
    up: "z",
    scale,
    weld_tolerance: weld,
    smooth_angle_deg: smooth,
  };
}

// ---------------------------------------------------------------------------
// M6 (contract §5.3.0, §5.0.1): any number of lights, multi-light reserved ids
// ---------------------------------------------------------------------------

/** The multi-light id rules of contract §5.3.0 / §5.0.1: with at least two lights the light ids `umbra` / `core` and
 * the object id `core` are reserved (a single-light scene keeps them valid). */
export function validate_lights_in_scene(lights: readonly Light[], objects: readonly SceneObject[]): void {
  if (lights.length < 2) return;
  lights.forEach((lt, i) => {
    if ((RESERVED_LIGHT_IDS_MULTI as readonly string[]).includes(lt.id)) throw new SceneError(`lights[${i}].id`, "reserved id in a multi-light scene");
  });
  objects.forEach((o, i) => {
    if ((RESERVED_OBJECT_IDS_MULTI as readonly string[]).includes(o.id)) throw new SceneError(`objects[${i}].id`, "reserved id");
  });
}

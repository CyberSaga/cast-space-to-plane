/**
 * Scene JSON validation (port of `castplane/scene.py`; spec §4; contract §2.0, §5.4.3).
 *
 * `load_scene(data)` takes parsed JSON (no paths: the core has no file system) and returns a NEW object with every
 * default filled in, or throws `SceneError` with the JSON field path of the first rule that fails. Unknown keys are
 * ignored. `load_scene_text(text)` wraps `JSON.parse` (browser-safe).
 */

import { SceneError } from "./errors.js";
import type { Vec2, Vec3 } from "./types.js";

export const OBJECT_TYPES = ["box", "cylinder", "sphere", "cone", "prism"] as const;
export const LIGHT_TYPES = ["point", "directional"] as const;
/** The six SVG layer ids in table order (contract §2.10). */
export const LAYER_IDS = ["horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels"] as const;

const UNIT_TOL = 1e-9;

export interface Transform {
  position: Vec3;
  rotation_deg: Vec3;
}

export interface SceneObject {
  id: string;
  type: string;
  size?: Vec3;
  radius?: number;
  height?: number;
  polygon?: Vec2[];
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

/** One `receivers[i]` entry: v1 ground plane only (contract §2.0). */
export function validate_receiver(value: unknown, field: string): Receiver {
  const r = dict(value, field);
  const rid = id(require_key(r, "id", field), `${field}.id`, false);
  const typ = require_key(r, "type", field);
  if (typ !== "plane") throw new SceneError(`${field}.type`, "must be 'plane'");
  const n = vector(require_key(r, "normal", field), `${field}.normal`, 3);
  if (Math.abs(norm(n) - 1.0) > UNIT_TOL) throw new SceneError(`${field}.normal`, "must be a unit vector (|n| = 1 within 1e-9)");
  const ground = [0.0, 0.0, 1.0];
  for (let i = 0; i < 3; i++) {
    if (Math.abs((n[i] as number) - (ground[i] as number)) > UNIT_TOL) {
      throw new SceneError(`${field}.normal`, "v1 supports only the ground plane: normal must be [0, 0, 1]");
    }
  }
  const offset = number(get(r, "offset", 0.0), `${field}.offset`);
  if (Math.abs(offset) > UNIT_TOL) throw new SceneError(`${field}.offset`, "v1 supports only the ground plane: offset must be 0");
  return { id: rid, type: "plane", normal: [0.0, 0.0, 1.0], offset: 0.0 };
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
  if (!Array.isArray(lights) || lights.length !== 1) throw new SceneError("lights", "must be a list of exactly one light (v1)");
  const out_lights: Light[] = [];
  seen = new Set<string>();
  lights.forEach((lt, i) => {
    const vl = validate_light(lt, `lights[${i}]`);
    if (seen.has(vl.id)) throw new SceneError(`lights[${i}].id`, `duplicate light id '${vl.id}'`);
    seen.add(vl.id);
    out_lights.push(vl);
  });

  const receivers = require_key(s, "receivers", "");
  if (!Array.isArray(receivers) || receivers.length !== 1) {
    throw new SceneError("receivers", "must be a list of exactly one receiver (v1)");
  }
  const out_receivers = receivers.map((r, i) => validate_receiver(r, `receivers[${i}]`));

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

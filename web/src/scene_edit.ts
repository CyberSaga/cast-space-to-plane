/**
 * Scene editing of M11 (spec-v0.3 §4–§7; contract §5.8.1, §5.8.3, §5.8.4, §5.8.8–§5.8.11) — pure, DOM-free and
 * unit-tested (`web/test/scene_edit.test.ts`), modelled on `rig.ts`.
 *
 * The web edits the scene JSON only: an edit builds a new `objects` array (records are immutable; a move builds a new
 * record `{...obj, transform: {...obj.transform, position}}` and shares every other key by reference), and the page
 * re-runs the port's `validate_scene` and stage A on it. Nothing here touches the core's geometry.
 *
 * Contents: the world box of an object (§5.8.1); the horizontal drag `drag_begin` / `drag_position` /
 * `finish_position` with its grazing-angle fallback (§5.8.3); the vertical drag `line_param` / `vertical_begin` /
 * `vertical_z` and the handle's shape with the exact 36 px length (§5.8.4); `snap_grid` / `round4`; the id rule
 * `next_id` (§5.8.9); placement `place_object` (§5.8.8); the array operations `add_object`, `remove_object`,
 * `move_object`; the keep-one rule (§5.8.10); and the builders of the object history entries `add`, `delete`, `move`
 * (the entry types and their LIFO-checked application are `plane.ts`'s) with `apply_entry` / `undo_entry` /
 * `invert_entry` and the display-name side table (§5.8.9, §5.8.11). Symbols follow the contract: `p_b` the anchor (`transform.position`),
 * `e`, `d` the pointer ray, `h₀` the grabbed surface point, `δ` the grab offset, `k` metres per pixel.
 */

import { build_object } from "castplane";
import type { Scene, SceneObject, Vec2, Vec3 } from "castplane";

import { OBSERVER_FOV_DEG, OBSERVER_NEAR_M } from "./observer.js";
import { apply_object_entry } from "./plane.js";
import type { AddEntry, DeleteEntry, MoveEntry, ObjectEntry } from "./plane.js";
import { PLANE_GRID_M, basis } from "./rig.js";

// ------------------------------------------------------------------------------------------------ constants (§5.8.15)

const DEG = Math.PI / 180;

export { PLANE_GRID_M };
/** Grazing-angle limit of the horizontal drag: `|d₀_z| < sin 5°` takes the fallback (§5.8.3). */
export const GRAZE_DEG = 5;
/** Normal-mode guard: an update whose ray parameter `t` exceeds this is skipped (§5.8.3). */
export const DRAG_MAX_T_M = 200;
/** Range of `x_b`, `y_b` (±) and the top of `z_b` (§5.8.3, §5.8.4). */
export const XY_LIMIT_M = 50;
export const Z_LIMIT_M = 50;
/** `|z_b| < GROUND_SNAP_M → 0` after a vertical drag, in every mode (§5.8.4). */
export const GROUND_SNAP_M = 0.02;
/** Rounding with snapping off (§5.8.3). */
export const ROUND_M = 1e-4;
/** `HANDLE_LEN = clamp(0.6·h, 0.3, 1.0)` m (§5.8.4). */
export const HANDLE_LEN_K = 0.6;
export const HANDLE_LEN_MIN_M = 0.3;
export const HANDLE_LEN_MAX_M = 1.0;
/** The handle's minimum image length (exact, §5.8.4) and the cap of `L₃₆`. */
export const HANDLE_MIN_PX = 36;
export const HANDLE_MAX_M = 1e3;
/** Placement (§5.8.8): the eye's line of sight must fall at least 2° and meet the ground within 40 m. */
export const PLACE_MIN_F_Z = Math.sin(2 * DEG);
export const PLACE_MAX_T_M = 40;
export const PLACE_GAP_M = 0.1;
export const PLACE_STEP_EXTRA_M = 0.2;
export const PLACE_TRIES = 8;
/** Wireframe-preview threshold and the drag-update target (§5.8.12; not gated). */
export const PREVIEW_MS = 50;
export const TARGET_MS = 33;
/** The keep-one text (§5.8.10): visible in the chip and shown in `#notices` on a refused Delete. */
export const NOTICE_KEEP_ONE = "場景至少要有一個物件";
/** Ids that `next_id` never returns: `hidden` (§5.0.1), and `core` / `umbra` (reserved in multi-light scenes). */
export const RESERVED_ID_WORDS: readonly string[] = ["hidden", "core", "umbra"];

const SIN_GRAZE = Math.sin(GRAZE_DEG * DEG);

// ------------------------------------------------------------------------------------------------ vector helpers

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const copy3 = (p: readonly number[]): Vec3 => [p[0]!, p[1]!, p[2]!];

function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

// ------------------------------------------------------------------------------------------------ camera frame and rays

/** A camera frame in world space: position, unit right / up / forward and the focal length in CSS px. The observer
 * camera has no roll; the drag functions take any orthonormal `(r, u, f)` (rolled frames are tested). */
export interface CameraFrame {
  pos: Vec3;
  r: Vec3;
  u: Vec3;
  f: Vec3;
  f_px: number;
}

/** A pointer ray: origin `e` (the camera position) and unit direction `d`. */
export interface Ray {
  e: Vec3;
  d: Vec3;
}

/** The observer pane's focal length in CSS px: `(H_px / 2) / tan 20°` (vertical field of view 40°). */
export function focal_px(H_px: number): number {
  return H_px / 2 / Math.tan((OBSERVER_FOV_DEG / 2) * DEG);
}

// ------------------------------------------------------------------------------------------------ world box (§5.8.1)

/** An axis-aligned box `[lo, hi]`. */
export type Box = readonly [Vec3, Vec3];

function rotated(obj: SceneObject): boolean {
  const rd = obj.transform.rotation_deg;
  return rd !== undefined && (rd[0] !== 0 || rd[1] !== 0 || rd[2] !== 0);
}

/** The local box of an unrotated primitive about its anchor (§5.8.1 closed form), or `null` for a mesh. */
function local_box(obj: SceneObject): Box | null {
  switch (obj.type) {
    case "box": {
      const s = obj.size as Vec3;
      return [[-s[0] / 2, -s[1] / 2, 0], [s[0] / 2, s[1] / 2, s[2]]];
    }
    case "cylinder":
    case "cone": {
      const r = obj.radius as number;
      return [[-r, -r, 0], [r, r, obj.height as number]];
    }
    case "sphere": {
      const r = obj.radius as number;
      return [[-r, -r, 0], [r, r, 2 * r]];
    }
    case "prism": {
      const poly = obj.polygon as Vec2[];
      let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
      for (const [x, y] of poly) {
        x0 = Math.min(x0, x);
        x1 = Math.max(x1, x);
        y0 = Math.min(y0, y);
        y1 = Math.max(y1, y);
      }
      return [[x0, y0, 0], [x1, y1, obj.height as number]];
    }
    default:
      return null;
  }
}

/**
 * The world box of a candidate object that is not yet in stage A (§5.8.1, §5.8.8): the closed form for
 * `rotation_deg = [0, 0, 0]` (`box` ±size/2; `cylinder`, `cone`, `sphere` ±radius; `prism` the polygon's min / max),
 * offset by the position. A rotated object or a `mesh` falls back to the port's `build_object(obj).bbox`.
 */
export function candidate_bbox(obj: SceneObject): [Vec3, Vec3] {
  const lb = rotated(obj) ? null : local_box(obj);
  if (lb === null) {
    const b = build_object(obj).bbox;
    return [copy3(b[0]), copy3(b[1])];
  }
  const p = obj.transform.position;
  return [add(lb[0], p), add(lb[1], p)];
}

/** The world box of an object (§5.8.1): its stage-A record's `bbox` when given, else {@link candidate_bbox}. */
export function world_bbox(obj: SceneObject, rec?: { bbox: readonly (readonly number[])[] } | null): [Vec3, Vec3] {
  if (rec !== undefined && rec !== null) return [copy3(rec.bbox[0]!), copy3(rec.bbox[1]!)];
  return candidate_bbox(obj);
}

/** The centre `c = (lo + hi) / 2` of a box. */
export function box_centre(b: Box): Vec3 {
  return [(b[0][0] + b[1][0]) / 2, (b[0][1] + b[1][1]) / 2, (b[0][2] + b[1][2]) / 2];
}

// ------------------------------------------------------------------------------------------------ rounding (§5.8.3)

/** `Math.round(v·10) / 10` (never `Math.round(v / 0.1) · 0.1`, which gives `0.30000000000000004`). */
export function snap_grid(v: number): number {
  return Math.round(v * 10) / 10;
}

/** `Math.round(v·1e4) / 1e4` (snap off). */
export function round4(v: number): number {
  return Math.round(v * 1e4) / 1e4;
}

/**
 * One coordinate of a horizontal drag (§5.8.3): `snap ? snap_grid : round4`, then the clamp to
 * `[min(−limit, v₀), max(limit, v₀)]` (so a press never moves an object), then `+ 0` (no `-0`).
 */
export function finish_coord(v: number, v0: number, snap: boolean, limit = XY_LIMIT_M): number {
  const w = snap ? snap_grid(v) : round4(v);
  return clamp(w, Math.min(-limit, v0), Math.max(limit, v0)) + 0;
}

/** The finished position of a horizontal drag: `x_b`, `y_b` by {@link finish_coord}; `z_b` copied bit for bit. */
export function finish_position(xy: readonly number[], p0: readonly number[], snap: boolean): Vec3 {
  return [finish_coord(xy[0]!, p0[0]!, snap), finish_coord(xy[1]!, p0[1]!, snap), p0[2]!];
}

/**
 * `z_b` of a vertical drag (§5.8.4): rounding as above, the clamp to `[min(0, z₀), max(50, z₀)]`, then the ground snap
 * `|z| < 0.02 → 0` in every mode (Alt included), then `+ 0`.
 */
export function finish_z(z: number, z0: number, snap: boolean): number {
  const w = snap ? snap_grid(z) : round4(z);
  const c = clamp(w, Math.min(0, z0), Math.max(Z_LIMIT_M, z0));
  return (Math.abs(c) < GROUND_SNAP_M ? 0 : c) + 0;
}

// ------------------------------------------------------------------------------------------------ horizontal drag (§5.8.3)

/** Everything a horizontal drag keeps from pointer-down. `fallback` is decided here, once, and never switches. */
export interface DragStart {
  /** The anchor at pointer-down. */
  p0: Vec3;
  /** The grabbed surface point and the drag plane `z = z_g`. */
  h0: Vec3;
  z_g: number;
  /** The grab offset `δ = (p₀ − h₀)_xy`. */
  delta: Vec2;
  fallback: boolean;
  /** Fallback data (camera at pointer-down): metres per pixel `k`, the frame `(r, u)`, the level basis
   * `(right₀, up₀)` of `f_c`, and the ground directions `r_g`, `f_g`. */
  k: number;
  r: Vec3;
  u: Vec3;
  right0: Vec3;
  up0: Vec3;
  r_g: Vec2;
  f_g: Vec2;
}

/**
 * Pointer-down of a horizontal drag: `fallback = |d₀_z| < sin 5° or not (t₀ > 0)` with `t₀ = (z_g − e₀_z) / d₀_z`.
 * The fallback's `k = ((h₀ − e₀)·f_c) / f_px` is the camera depth of `h₀` over the focal length; `(right₀, up₀)` is
 * the level default basis of `f_c` (§5.7.3, `rig.basis(f_c, null)`); `r_g = (right₀_x, right₀_y)`; `f_g` the
 * normalised horizontal part of `f_c`, or of `up₀` when that is `< 1e-9`.
 */
export function drag_begin(p0: readonly number[], h0: readonly number[], ray0: Ray, cam0: CameraFrame): DragStart {
  const z_g = h0[2]!;
  const t0 = (z_g - ray0.e[2]) / ray0.d[2];
  const fallback = Math.abs(ray0.d[2]) < SIN_GRAZE || !(t0 > 0);
  const k = dot(sub(h0, ray0.e), cam0.f) / cam0.f_px;
  const { r0: right0, u0: up0 } = basis(cam0.f, null);
  const r_g: Vec2 = [right0[0], right0[1]];
  let fh: Vec2 = [cam0.f[0], cam0.f[1]];
  let n = Math.hypot(fh[0], fh[1]);
  if (n < 1e-9) {
    fh = [up0[0], up0[1]];
    n = Math.hypot(fh[0], fh[1]);
  }
  return {
    p0: copy3(p0), h0: copy3(h0), z_g, delta: [p0[0]! - h0[0]!, p0[1]! - h0[1]!], fallback,
    k, r: copy3(cam0.r), u: copy3(cam0.u), right0, up0, r_g, f_g: [fh[0] / n, fh[1] / n],
  };
}

/**
 * The raw anchor `(x, y)` for the current pointer (before {@link finish_position}), or `null` to skip the update.
 * Normal mode: `t = (z_g − e_z) / d_z` must be finite, `> 0` and `≤ 200`; `h = e + t·d`; `(x, y) = h_xy + δ`.
 * Fallback: `w = Δx·r − Δy·u`, `Δx' = w·right₀`, `Δv' = w·up₀` (the displacement with the roll removed) and
 * `(x, y) = p₀_xy + k·(Δx'·r_g + Δv'·f_g)`. `(dx, dy)` is the total displacement since pointer-down (CSS px, y down).
 */
export function drag_position(st: DragStart, ray: Ray, dx: number, dy: number): Vec2 | null {
  if (!st.fallback) {
    const t = (st.z_g - ray.e[2]) / ray.d[2];
    if (!Number.isFinite(t) || !(t > 0) || t > DRAG_MAX_T_M) return null;
    return [ray.e[0] + t * ray.d[0] + st.delta[0], ray.e[1] + t * ray.d[1] + st.delta[1]];
  }
  const w = sub(mul(st.r, dx), mul(st.u, dy));
  const ddx = dot(w, st.right0), ddv = dot(w, st.up0);
  const mx = st.k * (ddx * st.r_g[0] + ddv * st.f_g[0]);
  const my = st.k * (ddx * st.r_g[1] + ddv * st.f_g[1]);
  if (!Number.isFinite(mx) || !Number.isFinite(my)) return null;
  return [st.p0[0] + mx, st.p0[1] + my];
}

// ------------------------------------------------------------------------------------------------ vertical drag (§5.8.4)

/**
 * The closest points of the pointer ray `e + t·d` (unit `d`) and the vertical line `a + s·ẑ` (`a_z` is 0 for the
 * handle's line): with `β = d_z`, `w₀ = a − e`: `s = (β·(d·w₀) − w₀_z) / (1 − β²)`, `t = d·w₀ + s·β`. `null` when
 * `|1 − β²| < 1e-6` (a nearly vertical ray) or `t ≤ 0` (the closest point is behind the eye).
 */
export function line_param(ray: Ray, a: readonly number[]): { s: number; t: number } | null {
  const beta = ray.d[2];
  const den = 1 - beta * beta;
  if (Math.abs(den) < 1e-6) return null;
  const w0 = sub(a, ray.e);
  const dw = dot(ray.d, w0);
  const s = (beta * dw - w0[2]) / den;
  const t = dw + s * beta;
  if (!(t > 0) || !Number.isFinite(s)) return null;
  return { s, t };
}

/** What a vertical drag keeps from pointer-down: the anchor, the handle's line `(c_x0, c_y0, 0) + s·ẑ` and `s₀`. */
export interface VerticalStart {
  p0: Vec3;
  c0: Vec2;
  s0: number;
}

/** Pointer-down on the vertical handle: the line through the world-box centre (§5.8.4), or `null` (the press does
 * nothing) when `s₀` does not exist. */
export function vertical_begin(p0: readonly number[], box: Box, ray0: Ray): VerticalStart | null {
  const c = box_centre(box);
  const lp = line_param(ray0, [c[0], c[1], 0]);
  if (lp === null) return null;
  return { p0: copy3(p0), c0: [c[0], c[1]], s0: lp.s };
}

/** The new anchor of a vertical drag (`null` to skip): `z_b = finish_z(z_b0 + (s − s₀))`; `x_b`, `y_b` copied. */
export function vertical_z(st: VerticalStart, ray: Ray, snap: boolean): Vec3 | null {
  const lp = line_param(ray, [st.c0[0], st.c0[1], 0]);
  if (lp === null) return null;
  return [st.p0[0], st.p0[1], finish_z(st.p0[2] + (lp.s - st.s0), st.p0[2], snap)];
}

// ------------------------------------------------------------------------------------------------ vertical handle shape (§5.8.4)

/**
 * `L₃₆`, the exact length of a vertical segment from `b` whose image in the camera is {@link HANDLE_MIN_PX} px:
 * `q = b − C_o`, `z₀ = q·f`, `f_z = ẑ·f`, `m = |(ẑ·r, ẑ·u)·z₀ − (q·r, q·u)·f_z|`,
 * `L₃₆ = 36·z₀² / (f_px·m − 36·z₀·f_z)`, capped at {@link HANDLE_MAX_M} (and equal to it when the denominator is
 * `≤ 0`), limited to `(z₀ − near) / (−f_z)` when `f_z < 0`; `0` when `z₀ ≤ OBSERVER_NEAR_M`.
 */
export function handle_L36(b: readonly number[], cam: CameraFrame, px = HANDLE_MIN_PX): number {
  const q = sub(b, cam.pos);
  const z0 = dot(q, cam.f);
  if (!(z0 > OBSERVER_NEAR_M)) return 0;
  const f_z = cam.f[2];
  const mx = cam.r[2] * z0 - dot(q, cam.r) * f_z;
  const my = cam.u[2] * z0 - dot(q, cam.u) * f_z;
  const m = Math.hypot(mx, my);
  const den = cam.f_px * m - px * z0 * f_z;
  let L = den > 0 ? Math.min((px * z0 * z0) / den, HANDLE_MAX_M) : HANDLE_MAX_M;
  if (f_z < 0) L = Math.min(L, (z0 - OBSERVER_NEAR_M) / -f_z);
  return L;
}

/** The vertical handle of a selected object. */
export interface HandleShape {
  /** Top centre of the world box `(c_x, c_y, hi_z)`. */
  base: Vec3;
  height: number;
  /** `max(clamp(0.6·height, 0.3, 1.0), L₃₆)`. */
  len: number;
  L36: number;
  tip: Vec3;
}

/** The handle of an object with world box `box` in the observer camera `cam` (§5.8.4). */
export function vertical_handle(box: Box, cam: CameraFrame): HandleShape {
  const c = box_centre(box);
  const base: Vec3 = [c[0], c[1], box[1][2]];
  const height = box[1][2] - box[0][2];
  const L36 = handle_L36(base, cam);
  const len = Math.max(clamp(HANDLE_LEN_K * height, HANDLE_LEN_MIN_M, HANDLE_LEN_MAX_M), L36);
  return { base, height, len, L36, tip: [base[0], base[1], base[2] + len] };
}

// ------------------------------------------------------------------------------------------------ ids and names (§5.8.9)

/** Every object, light and receiver id of the scene (the set `next_id` avoids). */
export function used_ids(scene: Pick<Scene, "objects" | "lights" | "receivers">): Set<string> {
  const out = new Set<string>();
  for (const o of scene.objects) out.add(o.id);
  for (const l of scene.lights) out.add(l.id);
  for (const r of scene.receivers) out.add(r.id);
  return out;
}

/**
 * `prefix_n` with the smallest integer `n ≥ 1` not in `used` (exact, case-sensitive) and not a reserved word
 * ({@link RESERVED_ID_WORDS}). A freed number is reused. The prefix must be non-empty and contain no `.` (§5.0.1).
 */
export function next_id(prefix: string, used: ReadonlySet<string> | Iterable<string>): string {
  if (prefix.length === 0 || prefix.includes(".")) throw new Error(`invalid id prefix '${prefix}'`);
  const set = used instanceof Set ? (used as ReadonlySet<string>) : new Set(used);
  for (let n = 1; ; n++) {
    const id = `${prefix}_${n}`;
    if (!set.has(id) && !RESERVED_ID_WORDS.includes(id)) return id;
  }
}

/** The name shown for an object: the tile name recorded by an add, else its id. */
export function display_name(id: string, names: ReadonlyMap<string, string>): string {
  return names.get(id) ?? id;
}

/** `name（id）` for a named object, the id alone otherwise (chip, observer label). */
export function label_text(id: string, names: ReadonlyMap<string, string>): string {
  const n = names.get(id);
  return n === undefined ? id : `${n}（${id}）`;
}

// ------------------------------------------------------------------------------------------------ placement (§5.8.8)

/**
 * The target `T` (§5.8.8 step 1): if `f_z < −sin 2°` and `t = −E_z / f_z` satisfies `0 < t ≤ 40`, the ground point
 * `E + t·f` (with `z = 0` exactly); otherwise `(P_x, P_y, 0)`.
 */
export function place_target(E: readonly number[], f: readonly number[], P: readonly number[]): Vec3 {
  if (f[2]! < -PLACE_MIN_F_Z) {
    const t = -E[2]! / f[2]!;
    if (t > 0 && t <= PLACE_MAX_T_M) return [E[0]! + t * f[0]!, E[1]! + t * f[1]!, 0];
  }
  return [P[0]!, P[1]!, 0];
}

/** The separation of two boxes along axis `k`: `max(lo_a − hi_b, lo_b − hi_a)` (negative when they overlap). */
function separation(a: Box, b: Box, k: number): number {
  return Math.max(a[0][k]! - b[1][k]!, b[0][k]! - a[1][k]!);
}

/** Footprint overlap (§5.8.8 step 2): the separation in both x and y is `< 0.1` m (heights ignored). */
export function footprints_overlap(a: Box, b: Box): boolean {
  return separation(a, b, 0) < PLACE_GAP_M && separation(a, b, 1) < PLACE_GAP_M;
}

/** The unit horizontal projection of the rig's pre-roll right vector `r₀` (`(1, 0, 0)` when it is `< 1e-9`). */
export function step_direction(r0: readonly number[]): Vec3 {
  const n = Math.hypot(r0[0]!, r0[1]!);
  return n < 1e-9 ? [1, 0, 0] : [r0[0]! / n, r0[1]! / n, 0];
}

export interface PlaceInput {
  /** The rig's eye and unit board normal (line of sight); pan and roll do not affect `f`. */
  E: readonly number[];
  f: readonly number[];
  /** The stored pivot. */
  P: readonly number[];
  /** The rig's pre-roll right vector. */
  r0: readonly number[];
  /** The world boxes of the existing objects (stage A, all heights included). Receivers are not avoided. */
  existing: readonly Box[];
  snap: boolean;
}

export interface Placement {
  position: Vec3;
  T: Vec3;
  /** Avoidance moves made (0 … 8). */
  steps: number;
  /** The last candidate (before the snap) still overlaps an object. */
  overlapping: boolean;
}

/**
 * The position of a new object (§5.8.8): the anchor at `T`, `z_b = 0`; while its footprint (closed-form box,
 * extent `w`) overlaps an existing box, at most 8 times, the anchor moves by `w_u + 0.2` m along `u`
 * ({@link step_direction}), `w_u = |u_x|·w_x + |u_y|·w_y`; then `snap ? snap_grid : round4`, the ±50 m clamp and
 * `+ 0`. No avoidance is re-run after the snap.
 */
export function place_object(obj: SceneObject, inp: PlaceInput): Placement {
  const T = place_target(inp.E, inp.f, inp.P);
  const zero = { ...obj, transform: { ...obj.transform, position: [0, 0, 0] as Vec3, rotation_deg: [0, 0, 0] as Vec3 } };
  const lb = candidate_bbox(zero);
  const w: Vec2 = [lb[1][0] - lb[0][0], lb[1][1] - lb[0][1]];
  const u = step_direction(inp.r0);
  const step = Math.abs(u[0]) * w[0] + Math.abs(u[1]) * w[1] + PLACE_STEP_EXTRA_M;
  let x = T[0], y = T[1];
  const at = (): Box => [[lb[0][0] + x, lb[0][1] + y, lb[0][2]], [lb[1][0] + x, lb[1][1] + y, lb[1][2]]];
  const hits = (): boolean => { const c = at(); return inp.existing.some((b) => footprints_overlap(c, b)); };
  let steps = 0;
  let overlapping = hits();
  while (overlapping && steps < PLACE_TRIES) {
    x += step * u[0];
    y += step * u[1];
    steps++;
    overlapping = hits();
  }
  const fin = (v: number): number => clamp(inp.snap ? snap_grid(v) : round4(v), -XY_LIMIT_M, XY_LIMIT_M) + 0;
  return { position: [fin(x), fin(y), 0], T, steps, overlapping };
}

// ------------------------------------------------------------------------------------------------ array operations (§5.8.0)

/** A new record with the anchor `position` (`rotation_deg`, a mesh's `data` and every other key shared). */
export function with_position(obj: SceneObject, position: readonly number[]): SceneObject {
  return { ...obj, transform: { ...obj.transform, position: copy3(position) } };
}

/** `objects` with `obj` appended (a new array). */
export function add_object(objects: readonly SceneObject[], obj: SceneObject): SceneObject[] {
  return [...objects, obj];
}

/** `objects` with `obj` inserted at `index` (a new array). */
export function insert_object(objects: readonly SceneObject[], index: number, obj: SceneObject): SceneObject[] {
  return [...objects.slice(0, index), obj, ...objects.slice(index)];
}

/** `objects` without the entry at `index` (a new array; the order of the others kept). */
export function remove_object(objects: readonly SceneObject[], index: number): SceneObject[] {
  return [...objects.slice(0, index), ...objects.slice(index + 1)];
}

/** `objects` with `objects[index]` replaced by `with_position(objects[index], position)` (a new array). */
export function move_object(objects: readonly SceneObject[], index: number, position: readonly number[]): SceneObject[] {
  const out = objects.slice();
  out[index] = with_position(objects[index]!, position);
  return out;
}

/** The index of the object `id`, or −1. */
export function index_of(objects: readonly SceneObject[], id: string): number {
  return objects.findIndex((o) => o.id === id);
}

/** Keep one object (§5.8.10): a delete is allowed only when more than one object remains. */
export function can_delete(objects: readonly SceneObject[]): boolean {
  return objects.length > 1;
}

// ------------------------------------------------------------------------------------------------ history entries (§5.8.11)

// The entry types and the LIFO-checked application are plane.ts's (the single source, with `History`); the helpers
// below build those entries and carry the display-name side table (§5.8.9) along.
export type { AddEntry, DeleteEntry, MoveEntry, ObjectEntry };

/** The result of applying an object entry: the new array, the names table and the selection that follows (§5.8.2). */
export interface EntryResult {
  objects: SceneObject[];
  names: Map<string, string>;
  selected: string | null;
}

/** Add `obj` at the end: the new array, the names table with the tile name, and the `add` entry. */
export function add_with_entry(objects: readonly SceneObject[], obj: SceneObject, name: string | null,
  names: ReadonlyMap<string, string> = new Map()): EntryResult & { entry: AddEntry } {
  const entry: AddEntry = { kind: "add", index: objects.length, obj, name };
  return { objects: add_object(objects, obj), names: names_after(names, entry, "redo"), selected: obj.id, entry };
}

/** Delete `objects[index]` (§5.8.10), or `null` when refused (keep one object) or out of range. The display name moves
 * into the entry. */
export function delete_with_entry(objects: readonly SceneObject[], index: number,
  names: ReadonlyMap<string, string> = new Map()): (EntryResult & { entry: DeleteEntry }) | null {
  if (!can_delete(objects) || index < 0 || index >= objects.length) return null;
  const obj = objects[index]!;
  const entry: DeleteEntry = { kind: "delete", index, obj, name: names.get(obj.id) ?? null };
  return { objects: remove_object(objects, index), names: names_after(names, entry, "redo"), selected: null, entry };
}

/** A move entry, or `null` when the final position equals the pressed one in every component (exact): a click or a
 * drag that snapped back records nothing. */
export function move_entry(index: number, before: SceneObject, after: SceneObject): MoveEntry | null {
  const p = before.transform.position, q = after.transform.position;
  if (p[0] === q[0] && p[1] === q[1] && p[2] === q[2]) return null;
  return { kind: "move", index, id: before.id, before, after };
}

/** The names table after applying `e` in the direction `dir` (§5.8.9): an insert (add redone, delete undone) puts the
 * entry's name back, a removal drops it; a move changes nothing. */
export function names_after(names: ReadonlyMap<string, string>, e: ObjectEntry, dir: "undo" | "redo"): Map<string, string> {
  const out = new Map(names);
  if (e.kind === "move") return out;
  const inserts = (e.kind === "add") === (dir === "redo");
  if (!inserts) out.delete(e.obj.id);
  else if (e.name !== null) out.set(e.obj.id, e.name);
  return out;
}

/** The entry whose redo is `e`'s undo: add ↔ delete (same index, record and name), a move with `before` / `after`
 * swapped. */
export function invert_entry(e: ObjectEntry): ObjectEntry {
  switch (e.kind) {
    case "add":
      return { kind: "delete", index: e.index, obj: e.obj, name: e.name };
    case "delete":
      return { kind: "add", index: e.index, obj: e.obj, name: e.name };
    case "move":
      return { kind: "move", index: e.index, id: e.id, before: e.after, after: e.before };
  }
}

function step_entry(objects: readonly SceneObject[], e: ObjectEntry, dir: "undo" | "redo",
  names: ReadonlyMap<string, string>): EntryResult | null {
  const r = apply_object_entry(objects, e, dir);
  return r === null ? null : { objects: r.objects, names: names_after(names, e, dir), selected: r.select };
}

/**
 * Apply `e` forwards (a redo) with `plane.apply_object_entry`, or `null` when `objects` is not the array right before
 * `e`'s action (the LIFO check of §5.8.11) — a bug guard: the caller clears both stacks. The selection follows the
 * entry (§5.8.2): the inserted or moved object, `null` after a removal.
 */
export function apply_entry(objects: readonly SceneObject[], e: ObjectEntry,
  names: ReadonlyMap<string, string> = new Map()): EntryResult | null {
  return step_entry(objects, e, "redo", names);
}

/** Undo `e` (`plane.apply_object_entry` with `"undo"`). */
export function undo_entry(objects: readonly SceneObject[], e: ObjectEntry,
  names: ReadonlyMap<string, string> = new Map()): EntryResult | null {
  return step_entry(objects, e, "undo", names);
}

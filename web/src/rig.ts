/**
 * The board-first rig of plane mode (M10; spec-v0.2 §4.2, §5; contract §5.7.7–§5.7.11) — pure, DOM-free and
 * unit-tested (`web/test/rig.test.ts`), modelled on `orbit.ts`.
 *
 * The user manipulates the board (the picture plane): its direction `f` (unit, eye → board) with the orange ring and
 * its distance `g` from the pivot `P` with the blue arrow. The eye `E` is **computed and read-only**:
 *
 *     L = a·r₀ + b·u₀,   E = P − (g + D)·f + L,   Q = E + D·f,   plane f·X = c with c = f·P − g,   R = g + D.
 *
 * The core never sees the rig: every frame builds a camera block from it — the `picture_plane` form
 * ({@link toCameraBlock}), which the port's `camera_matrix` / `render` resolve (`resolve_picture_plane`, contract §5.7.2),
 * for drawing and files; the equivalent target form with `roll_deg` ({@link toTargetCameraBlock}) remains for the
 * equivalence tests (contract §5.7.13 row 1). Every operation returns a new state; inputs are never mutated. A drag
 * is computed from the state at pointer-down and the **total** displacement `(dx, dy)` (DOM px, `dy` positive
 * downwards), never incrementally.
 */

import { camera_matrix, fixed, plane_equation, resolve_picture_plane } from "castplane";
import type { Camera, Vec2, Vec3 } from "castplane";

import { FOCAL_MAX_MM, FOCAL_MIN_MM, forward_from_angles } from "./orbit.js";
import type { LensBase, OrbitState, TargetCamera } from "./orbit.js";

// ------------------------------------------------------------------------------------------------ constants (§5.7.11)

export const KAPPA_DEG_PER_PX = 0.32;
export const SNAP_DEG = 5;
export const PITCH_LIMIT_DEG = 89.9;
export const PLANE_GRID_M = 0.1;
export const R_MIN_M = 0.8;
export const R_MAX_M = 40;
export const D_MIN_M = 0.5;
export const D_MAX_M = 12;
export const D_STEP_M = 0.1;
export const ROLL_LIMIT_DEG = 180;
export const UNDO_MAX = 50;
/** `D` of the initial demo state and of M9's derivation from the M7 orbit (`OBSERVER_D_M`). */
export const DEFAULT_D_M = 4;
/** Arrow drag: lower bound of `|v|²` (px²/m²) and the screen vector used when the tip is behind the observer. */
export const ARROW_MIN_V2 = 64;
export const ARROW_FALLBACK_V: Vec2 = [0, -40];
/** Ring radius factor of the frame half-diagonal and its minimum (m). */
export const RING_FACTOR = 1.03;
export const RING_MIN_M = 0.45;
/** "unchanged" threshold of the picture-delta readout (frame mm). */
export const DELTA_UNCHANGED_MM = 0.005;
export { FOCAL_MAX_MM, FOCAL_MIN_MM };

const DEG = 180 / Math.PI;
const KAPPA = KAPPA_DEG_PER_PX / DEG;
const PITCH_LIMIT = PITCH_LIMIT_DEG / DEG;
const SNAP_COS = Math.cos(SNAP_DEG / DEG);
/** The §2.2 test of `camera_matrix`: `|f × z| ≤ 1e-9` uses the `+y` fallback. */
const ALONG_UP_TOL = 1e-9;
/** `||f_i| − 1| < AXIS_TOL` marks an exact axis direction (arrow snap, equation string). */
const AXIS_TOL = 1e-9;

// ------------------------------------------------------------------------------------------------ state

/**
 * The rig (spec-v0.2 §4.2): direction `f` (unit, eye → board), free-roll up `up` (`null` ⇔ lock-horizontal), board
 * distance from the pivot `g` (may be negative), eye-to-board `D`, pan `(a, b)` in the pre-roll basis, roll about the
 * line of sight `roll_deg`, focal length `focal` (mm) and the pivot `P`. `P` is not part of an undo snapshot. The pan
 * is not user-editable: it comes from the load rule ({@link fromCamera}) and is cleared by a view or a pivot change.
 */
export interface RigState {
  f: Vec3;
  up: Vec3 | null;
  g: number;
  D: number;
  a: number;
  b: number;
  roll_deg: number;
  focal: number;
  P: Vec3;
}

/** The pre-roll basis `(r₀, u₀)` and the final frame basis `(r, u)` (rows `right'`, `up'` of `camera_matrix`). */
export interface RigFrame {
  r0: Vec3;
  u0: Vec3;
  r: Vec3;
  u: Vec3;
}

/** Everything derived from a rig (never stored). */
export interface RigDerived extends RigFrame {
  /** The eye (read-only). */
  E: Vec3;
  /** The foot of the eye on the board = the frame centre (principal point with zero shift). */
  Q: Vec3;
  /** The plane constant: the board is `f·X = c`. */
  c: number;
  /** The pivot's depth along `f`: `g + D`. */
  R: number;
  /** The pan vector `a·r₀ + b·u₀` (⊥ f). */
  L: Vec3;
}

/** The `picture_plane` camera form of the core (spec-v0.2 §4.1). */
export interface PicturePlaneBlock {
  normal: Vec3;
  offset: number;
  up?: Vec3;
}

/** A `picture_plane`-form camera block, written explicitly (never `{...base}`). */
export interface PicturePlaneCamera {
  position: Vec3;
  picture_plane: PicturePlaneBlock;
  focal_length_mm: number;
  frame_mm: [number, number];
  shift_mm: [number, number];
  near_m: number;
}

/** A camera block of any of the three forms (validated: target, yaw/pitch, or `picture_plane`). */
export type AnyCamera = Camera | PicturePlaneCamera;

// ------------------------------------------------------------------------------------------------ vector helpers

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const cross = (p: readonly number[], q: readonly number[]): Vec3 =>
  [p[1]! * q[2]! - p[2]! * q[1]!, p[2]! * q[0]! - p[0]! * q[2]!, p[0]! * q[1]! - p[1]! * q[0]!];
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));
const unit = (p: readonly number[]): Vec3 => { const l = len(p); return [p[0]! / l, p[1]! / l, p[2]! / l]; };
const copy3 = (p: readonly number[]): Vec3 => [p[0]!, p[1]!, p[2]!];

function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

/** Rodrigues' rotation of `v` about the unit `axis` by `angle` (right-handed, radians). */
export function rot(v: readonly number[], axis: readonly number[], angle: number): Vec3 {
  const c = Math.cos(angle), s = Math.sin(angle);
  return add(add(mul(v, c), mul(cross(axis, v), s)), mul(axis, dot(axis, v) * (1 - c)));
}

/** `normalize(f)` with components `|f_i| < 1e-12` set to `0` (after an orbit). */
function tidy(f: readonly number[]): Vec3 {
  const u = unit(f);
  return u.map((x) => (Math.abs(x) < 1e-12 ? 0 : x)) as Vec3;
}

/** Wrap an angle in degrees into `(−180, 180]`. */
export function wrap_deg(x: number): number {
  const w = x - 360 * Math.ceil((x - 180) / 360);
  return w === -180 ? 180 : w + 0;
}

// ------------------------------------------------------------------------------------------------ basis and derived

/**
 * The pre-roll basis (spec-v0.2 §4.2; contract §5.7.7): `a = up` if given, else `+z`, replaced by `+y` when `up` is
 * null and `|f × z| ≤ 1e-9` (the §2.2 test, so the rig's default basis is `camera_matrix`'s); `u₀ = normalize(a −
 * (a·f)·f)`; `r₀ = normalize(f × u₀)`; `u₀ = r₀ × f`. A given `up` (nearly) parallel to `f` falls back to the default.
 */
export function basis(f: readonly number[], up: readonly number[] | null): { r0: Vec3; u0: Vec3 } {
  let u: Vec3 | null = null;
  if (up !== null) {
    const p = sub(up, mul(f, dot(up, f)));
    if (len(p) > 1e-9) u = p;
  }
  if (u === null) {
    const z: Vec3 = [0, 0, 1];
    const a: Vec3 = len(cross(f, z)) <= ALONG_UP_TOL ? [0, 1, 0] : z;
    u = sub(a, mul(f, dot(a, f)));
  }
  const u1 = unit(u);
  const r0 = unit(cross(f, u1));
  const u0 = cross(r0, f);
  return { r0: [r0[0] + 0, r0[1] + 0, r0[2] + 0], u0: [u0[0] + 0, u0[1] + 0, u0[2] + 0] }; // no negative zeros
}

/** The pre-roll and final bases: `r = cos ρ·r₀ + sin ρ·u₀`, `u = −sin ρ·r₀ + cos ρ·u₀` (§2.2 roll convention). */
export function frameOf(rig: Pick<RigState, "f" | "up" | "roll_deg">): RigFrame {
  const { r0, u0 } = basis(rig.f, rig.up);
  const q = rig.roll_deg / DEG, cq = Math.cos(q), sq = Math.sin(q);
  return { r0, u0, r: add(mul(r0, cq), mul(u0, sq)), u: add(mul(r0, -sq), mul(u0, cq)) };
}

/** The eye `E = P − (g + D)·f + L` (read-only). */
export function eye(rig: RigState): Vec3 {
  return sync(rig).E;
}

/** The foot `Q = E + D·f` (frame centre on the board). */
export function foot(rig: RigState): Vec3 {
  return sync(rig).Q;
}

/** The plane constant `c = f·P − g` (board `f·X = c`); independent of the pan. */
export function planeConst(rig: RigState): number {
  return dot(rig.f, rig.P) - rig.g;
}

/** Everything derived from the rig: `E`, `Q`, `c`, `R`, `L` and both bases. */
export function sync(rig: RigState): RigDerived {
  const fr = frameOf(rig);
  const L = add(mul(fr.r0, rig.a), mul(fr.u0, rig.b));
  const R = rig.g + rig.D;
  const E = add(sub(rig.P, mul(rig.f, R)), L);
  return { ...fr, E, Q: add(E, mul(rig.f, rig.D)), c: planeConst(rig), R, L };
}

/** The frame's size on the board in metres: `frame_mm · D / focal`. */
export function frameMetres(rig: Pick<RigState, "D" | "focal">, frame_mm: readonly number[]): Vec2 {
  return [(frame_mm[0]! * rig.D) / rig.focal, (frame_mm[1]! * rig.D) / rig.focal];
}

/** The orange ring's radius: `max(1.03 · ½·√(W_m² + H_m²), 0.45)` m (spec-v0.2 §3). */
export function ringRadius(rig: Pick<RigState, "D" | "focal">, frame_mm: readonly number[]): number {
  const [w, h] = frameMetres(rig, frame_mm);
  return Math.max(RING_FACTOR * 0.5 * Math.hypot(w, h), RING_MIN_M);
}

/** The ring point at angle `theta` (radians) in the plane of `r`, `u` around `Q`. */
export function ringPoint(rig: RigState, frame_mm: readonly number[], theta: number): Vec3 {
  const d = sync(rig), rr = ringRadius(rig, frame_mm);
  return add(d.Q, add(mul(d.r, Math.cos(theta) * rr), mul(d.u, Math.sin(theta) * rr)));
}

/** The arrow's length `clamp(0.55·D, 0.3, 1.4)` m. */
export function arrowLength(D: number): number {
  return clamp(0.55 * D, 0.3, 1.4);
}

/** The arrow tip `Q − len·f` (the arrow points from `Q` towards the eye). */
export function arrowTip(rig: RigState): Vec3 {
  return sub(foot(rig), mul(rig.f, arrowLength(rig.D)));
}

// ------------------------------------------------------------------------------------------------ camera blocks

/** `roll_deg` of the target form: the signed angle about `f` from `camera_matrix`'s default up to the frame up `u`. */
export function rollOfFrame(f: readonly number[], u: readonly number[]): number {
  const d = basis(f, null);
  return Math.atan2(-dot(u, d.r0), dot(u, d.u0)) * DEG + 0;
}

/**
 * The core `picture_plane` block of the rig (spec-v0.2 §4.2): `position = E`, `normal = f`, `offset = −c`, `up = u`
 * (omitted when lock-horizontal and `ρ = 0`); the lens fields are copied explicitly from `base` (`shift_mm` is not
 * editable). The core then has `s = −D` and its forward is `f`.
 */
export function toCameraBlock(rig: RigState, base: LensBase): PicturePlaneCamera {
  const d = sync(rig);
  const picture_plane: PicturePlaneBlock = { normal: copy3(rig.f), offset: -d.c + 0 };
  if (rig.up !== null || rig.roll_deg !== 0) picture_plane.up = copy3(d.u);
  return {
    position: d.E,
    picture_plane,
    focal_length_mm: rig.focal,
    frame_mm: [base.frame_mm[0], base.frame_mm[1]],
    shift_mm: [base.shift_mm[0], base.shift_mm[1]],
    near_m: base.near_m,
  };
}

/**
 * The equivalent target-form block (`target = E + f`, `roll_deg` = the signed angle from the default up to `u`) — the
 * same picture as {@link toCameraBlock} (which never warns `CAMERA_LOOKING_ALONG_UP`; this block does on top / bottom
 * views), kept for the equivalence tests of contract §5.7.13.
 */
export function toTargetCameraBlock(rig: RigState, base: LensBase): TargetCamera {
  const d = sync(rig);
  const roll = rig.up === null ? rig.roll_deg : rollOfFrame(rig.f, d.u);
  return {
    position: d.E,
    target: add(d.E, rig.f),
    roll_deg: roll,
    focal_length_mm: rig.focal,
    frame_mm: [base.frame_mm[0], base.frame_mm[1]],
    shift_mm: [base.shift_mm[0], base.shift_mm[1]],
    near_m: base.near_m,
  };
}

/** Resolution of a `picture_plane` block (spec-v0.2 §4.1), mirroring the core's `resolve_picture_plane`. */
export interface ResolvedPicturePlane {
  block: TargetCamera;
  roll_deg: number;
  normal: Vec3;
  offset: number;
  distance: number;
  foot: Vec3;
}

/**
 * `s = n̂·E + off̂`, `D = |s|`, `f = −sign(s)·n̂`, `Q = E − s·n̂`, `target = E + f`; `roll_deg` from the default up of
 * `camera_matrix` to the given `up` (0 without `up`): the port's `resolve_picture_plane` (contract §5.7.2) with the lens
 * fields of `cam` written explicitly.
 */
export function resolvePicturePlane(cam: PicturePlaneCamera): ResolvedPicturePlane {
  const [blk, roll, info] = resolve_picture_plane(cam);
  const block: TargetCamera = {
    position: copy3(blk.position), target: copy3(blk.target!), roll_deg: roll, focal_length_mm: cam.focal_length_mm,
    frame_mm: [cam.frame_mm[0], cam.frame_mm[1]], shift_mm: [cam.shift_mm[0], cam.shift_mm[1]], near_m: cam.near_m,
  };
  return { block, roll_deg: roll, normal: copy3(info.normal), offset: info.offset, distance: info.distance, foot: copy3(info.foot) };
}

/** Notices of the load rule: which clamps were hit. */
export interface LoadResult {
  rig: RigState;
  clampedD: boolean;
  clampedR: boolean;
}

/**
 * The load rule (spec-v0.2 §4.2; contract §5.7.7) for any validated camera: `f` = the camera's forward, `P` = the
 * given pivot (scene centre), `D` = the `picture_plane` distance or 4 m, clamped to `[0.5, 12]`; `R = f·(P − E)`
 * clamped to `[0.8, 40]`; `g = R − D`; the eye's offset from the pivot's axis `L = (E − P) + R·f` becomes the pan
 * (`a = L·r₀`, `b = L·u₀`, lock basis); `roll_deg` = the camera's roll wrapped into `(−180, 180]`; `up = null`.
 * Without a clamp the picture is unchanged.
 */
export function fromCamera(cam: AnyCamera, P: readonly number[]): LoadResult {
  let block: Pick<Camera, "position" | "focal_length_mm" | "frame_mm" | "roll_deg"> & Partial<Camera>;
  let D = DEFAULT_D_M;
  const pp = cam.picture_plane;
  if (pp !== undefined) {
    const res = resolvePicturePlane({
      position: cam.position, picture_plane: pp, focal_length_mm: cam.focal_length_mm, frame_mm: cam.frame_mm,
      shift_mm: cam.shift_mm, near_m: cam.near_m,
    });
    block = res.block;
    D = res.distance;
  } else {
    block = cam;
  }
  const rec = camera_matrix(block, [block.frame_mm[0], block.frame_mm[1]]);
  const f = copy3(rec.forward), E = copy3(rec.C);
  const D1 = clamp(D, D_MIN_M, D_MAX_M);
  const R0 = dot(f, sub(P, E));
  const R1 = clamp(R0, R_MIN_M, R_MAX_M);
  const L = add(sub(E, P), mul(f, R0));
  const { r0, u0 } = basis(f, null);
  const rig: RigState = {
    f, up: null, g: R1 - D1, D: D1, a: dot(L, r0), b: dot(L, u0), roll_deg: wrap_deg(block.roll_deg ?? 0),
    focal: block.focal_length_mm, P: copy3(P),
  };
  return { rig, clampedD: D1 !== D, clampedR: R1 !== R0 };
}

/**
 * M9's read-only board from the M7 orbit state (spec-v0.2 §4.2 last bullet): `P = target`, `R = distance`,
 * `D = 4 m`, `g = R − D` (may be negative), pan `(0, 0)`, `ρ = roll`; no clamp (nothing is edited in M9).
 */
export function fromOrbitState(state: OrbitState): RigState {
  return {
    f: forward_from_angles(state.yaw_deg, state.pitch_deg), up: null, g: state.distance - DEFAULT_D_M, D: DEFAULT_D_M,
    a: 0, b: 0, roll_deg: state.roll_deg, focal: state.focal_length_mm, P: copy3(state.target),
  };
}

/** The bounding-box centre (the default pivot: stage A's `bbox`, or one object's vertices). */
export function bboxCentre(bbox: readonly (readonly number[])[]): Vec3 {
  const lo = bbox[0]!, hi = bbox[1]!;
  return [(lo[0]! + hi[0]!) / 2, (lo[1]! + hi[1]!) / 2, (lo[2]! + hi[2]!) / 2];
}

// ------------------------------------------------------------------------------------------------ equation string

/** `fixed(v, d)` (Python `format(v, ".<d>f")`, exact ties to even, `-0.00` without its sign) and
 * `plane_equation(normal, offset)` (spec-v0.2 §4.3; contract §5.7.5) are the port's (`ts/src/picture_plane.ts`). */
export { fixed, plane_equation };

/** The current plane's equation string `plane_equation(f, −c)`. */
export function equation(rig: RigState): string {
  return plane_equation(rig.f, -planeConst(rig));
}

// ------------------------------------------------------------------------------------------------ snapping

const AXES: readonly Vec3[] = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];

/**
 * Snap (spec-v0.2 §5.2): if `f·a > cos 5°` for one of `±x, ±y, ±z` (first in that order), rotate `f` (and `up`) by
 * the minimal rotation about `normalize(f × a)` and set `f = a` exactly. `snapped` is false when nothing changed.
 */
export function snapToAxis(f: readonly number[], up: readonly number[] | null): { f: Vec3; up: Vec3 | null; snapped: boolean } {
  for (const a of AXES) {
    if (dot(f, a) > SNAP_COS) {
      const ax = cross(f, a), al = len(ax);
      if (al < 1e-12) return { f: copy3(a), up: up === null ? null : copy3(up), snapped: true };
      const angle = Math.acos(clamp(dot(f, a), -1, 1));
      return { f: copy3(a), up: up === null ? null : rot(up, mul(ax, 1 / al), angle), snapped: true };
    }
  }
  return { f: copy3(f), up: up === null ? null : copy3(up), snapped: false };
}

/** Index of the exact axis `f = ±e_i`, or `undefined`. */
export function axisIndex(f: readonly number[]): number | undefined {
  return [0, 1, 2].find((i) => Math.abs(Math.abs(f[i]!) - 1) < AXIS_TOL);
}

// ------------------------------------------------------------------------------------------------ orbit (ring)

/** What the ring drag records at pointer-down: the grabbed ring point relative to `P` and the observer's axes. */
export interface RingGrab {
  w: Vec3;
  r_c: Vec3;
  u_c: Vec3;
}

/** `sign(±dir·(axis × w))` (negated when `flip`), `+1` when the magnitude is below 1e-6 (spec-v0.2 §5.2). */
export function ringSign(axis: readonly number[], dir: readonly number[], flip: boolean, w: readonly number[]): number {
  const m = dot(dir, cross(axis, w)) * (flip ? -1 : 1);
  return Math.abs(m) < 1e-6 ? 1 : Math.sign(m);
}

function finishOrbit(rig0: RigState, f: Vec3, up: Vec3 | null, snap: boolean): RigState {
  if (snap) {
    const s = snapToAxis(f, up);
    f = s.f;
    up = s.up;
  }
  return { ...rig0, f: tidy(f), up, P: copy3(rig0.P) };
}

/** Lock-horizontal turn: about `z` by `yaw`, then the elevation to `clamp(p₀ + dp, ±89.9°)` about the level right axis. */
function turnLevel(f0: Vec3, up0: Vec3 | null, yaw: number, dp: number): { f: Vec3; up: Vec3 | null } {
  let f = f0, up = up0;
  const apply = (axis: Vec3, ang: number): void => {
    f = rot(f, axis, ang);
    if (up !== null) up = rot(up, axis, ang);
  };
  apply([0, 0, 1], yaw);
  const r1 = basis(f, null).r0;
  const p0 = Math.asin(clamp(f[2], -1, 1));
  const p1 = clamp(p0 + dp, -PITCH_LIMIT, PITCH_LIMIT);
  apply(r1, p1 - p0);
  return { f, up };
}

function turnFree(f0: Vec3, up0: Vec3, axis1: Vec3, ang1: number, axis2: Vec3, ang2: number): { f: Vec3; up: Vec3 } {
  return { f: rot(rot(f0, axis1, ang1), axis2, ang2), up: rot(rot(up0, axis1, ang1), axis2, ang2) };
}

/**
 * Ring drag, lock-horizontal (spec-v0.2 §5.2): about `z` by `sgn(z, r_c, no)·dx·κ`, then the elevation
 * `clamp(p₀ + sgn(r₁, u_c, yes)·dy·κ, ±89.9°)`. `g`, `D`, `(a, b)`, `ρ` unchanged: the eye turns rigidly about `P`.
 */
export function orbitLockLevel(rig0: RigState, dx: number, dy: number, grab: RingGrab, snap = true): RigState {
  if (dx === 0 && dy === 0) return clone(rig0);
  const z: Vec3 = [0, 0, 1];
  const yaw = ringSign(z, grab.r_c, false, grab.w) * dx * KAPPA;
  // r₁ (the level right axis after the yaw) decides the elevation sign
  const f_yawed = rot(rig0.f, z, yaw);
  const r1 = basis(f_yawed, null).r0;
  const dp = ringSign(r1, grab.u_c, true, grab.w) * dy * KAPPA;
  const t = turnLevel(copy3(rig0.f), rig0.up === null ? null : copy3(rig0.up), yaw, dp);
  return finishOrbit(rig0, t.f, t.up, snap);
}

/**
 * Ring drag, free roll (spec-v0.2 §5.2): about the observer's up axis by `sgn(u_c, r_c, no)·dx·κ`, then about its
 * right axis by `sgn(r_c, u_c, yes)·dy·κ`; `up` turns with the rig (initialised to `u₀` when null).
 */
export function orbitFree(rig0: RigState, dx: number, dy: number, grab: RingGrab, snap = true): RigState {
  if (dx === 0 && dy === 0) return clone(rig0);
  const up0 = rig0.up === null ? basis(rig0.f, null).u0 : copy3(rig0.up);
  const t = turnFree(copy3(rig0.f), up0,
    grab.u_c, ringSign(grab.u_c, grab.r_c, false, grab.w) * dx * KAPPA,
    grab.r_c, ringSign(grab.r_c, grab.u_c, true, grab.w) * dy * KAPPA);
  return finishOrbit(rig0, t.f, t.up, snap);
}

/** The ring drag of the current mode (`up === null` ⇔ lock-horizontal). */
export function orbitRing(rig0: RigState, dx: number, dy: number, grab: RingGrab, snap = true): RigState {
  return rig0.up === null ? orbitLockLevel(rig0, dx, dy, grab, snap) : orbitFree(rig0, dx, dy, grab, snap);
}

// ------------------------------------------------------------------------------------------------ distance (arrow)

function clampG(g: number, D: number): number {
  return clamp(g, R_MIN_M - D, R_MAX_M - D);
}

/**
 * The arrow's screen vector `v` (observer px per metre along `+f` at the tip): `project(tip + f) − project(tip)`;
 * `(0, −40)` when either point is behind the observer camera (`project` returns null).
 */
export function arrowScreenVector(rig: RigState, project: (X: Vec3) => Vec2 | null): Vec2 {
  const tip = arrowTip(rig);
  const p = project(tip), q = project(add(tip, rig.f));
  return p !== null && q !== null ? [q[0] - p[0], q[1] - p[1]] : [ARROW_FALLBACK_V[0], ARROW_FALLBACK_V[1]];
}

/**
 * Arrow drag (spec-v0.2 §5.3) from the pointer-down state `rig0` (`g₀ = rig0.g`) with screen vector `v`:
 * `t = (Δ·v) / max(|v|², 64)` metres towards the scene, `g' = clamp(g₀ − t, 0.8 − D, 40 − D)`; with `snap` and an
 * axis direction the plane coordinate snaps to the 0.1 m grid. `f`, `D`, `(a, b)`, `ρ` unchanged.
 */
export function arrowDrag(rig0: RigState, v: readonly number[], dx: number, dy: number, snap = true): RigState {
  const t = (dx * v[0]! + dy * v[1]!) / Math.max(v[0]! * v[0]! + v[1]! * v[1]!, ARROW_MIN_V2);
  let g = clampG(rig0.g - t, rig0.D);
  const ax = axisIndex(rig0.f);
  if (snap && ax !== undefined) {
    const sg = rig0.f[ax]! > 0 ? 1 : -1;
    const fP = dot(rig0.f, rig0.P);
    const c = fP - g;
    const c2 = (sg * Math.round(10 * sg * c)) / 10;
    g = clampG(fP - c2, rig0.D);
  }
  return { ...clone(rig0), g };
}

// ------------------------------------------------------------------------------------------------ roll, sliders

/** Roll slider `[−180°, 180°]` about the line of sight: the eye and the board do not move. Not an undo step. */
export function setRoll(rig: RigState, roll_deg: number): RigState {
  return { ...clone(rig), roll_deg: clamp(roll_deg, -ROLL_LIMIT_DEG, ROLL_LIMIT_DEG) };
}

/** The `D` slider's range for the current `g`: `[max(0.5, 0.8 − g), min(12, 40 − g)]`. */
export function dRange(g: number): Vec2 {
  return [Math.max(D_MIN_M, R_MIN_M - g), Math.min(D_MAX_M, R_MAX_M - g)];
}

/** `D` slider: the board stays (`g`, `c` unchanged), the eye moves along `−f`; clamped by {@link dRange}. */
export function setD(rig: RigState, D: number): RigState {
  const [lo, hi] = dRange(rig.g);
  return { ...clone(rig), D: clamp(D, lo, hi) };
}

/**
 * Focal-length slider `[8, 400]` mm: the M7 range is kept by the [decision] of contract §5.7.8 item 9 (spec-v0.2 §5.7's
 * 12–80 mm is the demo's range; loaded scenes use other values). Field of view and frame only. Not an undo step.
 */
export function setFocal(rig: RigState, focal: number): RigState {
  return { ...clone(rig), focal: clamp(focal, FOCAL_MIN_MM, FOCAL_MAX_MM) };
}

/** Lock-horizontal on: `up = null`; off: `up = u₀` of the current basis (nothing visible changes). */
export function setLockLevel(rig: RigState, level: boolean): RigState {
  const r = clone(rig);
  if (level) r.up = null;
  else if (r.up === null) r.up = basis(r.f, null).u0;
  return r;
}

/** The six one-click views (spec-v0.2 §5.5). */
export type ViewName = "front" | "back" | "left" | "right" | "top" | "bottom";
export const VIEWS: Readonly<Record<ViewName, Readonly<Vec3>>> = {
  front: [0, 1, 0],
  back: [0, -1, 0],
  left: [1, 0, 0],
  right: [-1, 0, 0],
  top: [0, 0, -1],
  bottom: [0, 0, 1],
};

/** One-click view: `f` = the axis, `up = null` (lock) or the new `u₀` (free), pan and roll cleared; `g`, `D` kept. */
export function sixView(rig: RigState, name: ViewName): RigState {
  const f = copy3(VIEWS[name]);
  return { ...clone(rig), f, up: rig.up === null ? null : basis(f, null).u0, a: 0, b: 0, roll_deg: 0 };
}

/**
 * Pivot change (spec-v0.2 §4.2, §5.4): keeps `f`, `g`, `D`, `up`, `ρ` and clears the pan, so the eye moves onto the
 * new pivot's axis and the pivot is at the frame centre. Not an undo step.
 */
export function setPivot(rig: RigState, P: readonly number[]): RigState {
  return { ...clone(rig), a: 0, b: 0, P: copy3(P) };
}

/** Plane `n·X = d` to the board (spec-v0.2 §5.6): `s_d = d − n·P`; `f = −n` if `s_d ≥ 0`, else `n`; `g = |s_d|`. */
export function planeToRig(n: readonly number[], d: number, P: readonly number[]): { f: Vec3; g: number } {
  const sd = d - dot(n, P);
  const f = (sd >= 0 ? mul(n, -1) : copy3(n)).map((x) => (x === 0 ? 0 : x)) as Vec3;
  return { f, g: Math.abs(sd) };
}

export type PlaneError = "too_far" | "too_near";

/**
 * Apply the plane `n·X = d` to the rig: `f`, `g` by {@link planeToRig}; pan and roll kept; `up = null` (lock) or the
 * new `u₀` (free). Rejected when `g + D > 40` (`"too_far"`) or `g + D < 0.8` (`"too_near"`).
 */
export function applyPlane(rig: RigState, n: readonly number[], d: number): { rig: RigState } | { error: PlaneError } {
  const { f, g } = planeToRig(n, d, rig.P);
  if (g + rig.D > R_MAX_M) return { error: "too_far" };
  if (g + rig.D < R_MIN_M) return { error: "too_near" };
  return { rig: { ...clone(rig), f, g, up: rig.up === null ? null : basis(f, null).u0 } };
}

// ------------------------------------------------------------------------------------------------ readouts

/** Image of world points in frame mm (canvas mm / `s`); `null` for points behind the near plane. */
export function measureRef(rig: RigState, base: LensBase, canvas_mm: readonly number[], points: readonly (readonly number[])[]): (Vec2 | null)[] {
  const rec = camera_matrix(toCameraBlock(rig, base), canvas_mm);
  const P = rec.P, Rt = rec.Rt[2];
  return points.map((X) => {
    const depth = Rt[0] * X[0]! + Rt[1] * X[1]! + Rt[2] * X[2]! + Rt[3];
    if (depth < rec.near) return null;
    const x = P.map((row) => row[0] * X[0]! + row[1] * X[1]! + row[2] * X[2]! + row[3]);
    return [x[0]! / x[2]! / rec.s, x[1]! / x[2]! / rec.s];
  });
}

/** The maximum displacement between two {@link measureRef} results (points null in either skipped); null if none. */
export function pictureDelta(ref0: readonly (Vec2 | null)[], ref1: readonly (Vec2 | null)[]): number | null {
  let m = -1;
  for (let i = 0; i < ref0.length; i++) {
    const p = ref0[i], q = ref1[i];
    if (!p || !q) continue;
    m = Math.max(m, Math.hypot(p[0] - q[0], p[1] - q[1]));
  }
  return m < 0 ? null : m;
}

/** The readout text of {@link pictureDelta} ("這次拖動右窗畫面變動"). */
export function deltaText(m: number | null): string {
  if (m === null) return "—";
  return m < DELTA_UNCHANGED_MM ? "0.00 mm（不變）" : `${m.toFixed(2)} mm`;
}

export interface Readouts {
  equation: string;
  g: number;
  R: number;
  E: Vec3;
  D: number;
  a: number;
  b: number;
  roll_deg: number;
  frame_m: Vec2;
  eye_below_ground: boolean;
}

/** The readout values of spec-v0.2 §5.8. */
export function readouts(rig: RigState, frame_mm: readonly number[]): Readouts {
  const d = sync(rig);
  return {
    equation: equation(rig), g: rig.g, R: d.R, E: d.E, D: rig.D, a: rig.a, b: rig.b, roll_deg: rig.roll_deg,
    frame_m: frameMetres(rig, frame_mm), eye_below_ground: d.E[2] < 0,
  };
}

// ------------------------------------------------------------------------------------------------ undo

/** A deep copy of a rig. */
export function clone(rig: RigState): RigState {
  return { ...rig, f: copy3(rig.f), up: rig.up === null ? null : copy3(rig.up), P: copy3(rig.P) };
}

const same3 = (p: readonly number[] | null, q: readonly number[] | null): boolean =>
  p === null || q === null ? p === q : p[0] === q[0] && p[1] === q[1] && p[2] === q[2];

/** The board key of a drag: `(f, g, up, a, b)` (contract §5.7.8 item 13). */
export function sameBoard(p: RigState, q: RigState): boolean {
  return same3(p.f, q.f) && same3(p.up, q.up) && p.g === q.g && p.a === q.a && p.b === q.b;
}

/** Everything but the pivot. */
export function sameState(p: RigState, q: RigState): boolean {
  return sameBoard(p, q) && p.D === q.D && p.roll_deg === q.roll_deg && p.focal === q.focal;
}

/**
 * The undo stack (spec-v0.2 §5.7): at most 50 snapshots (the pivot excluded: undo keeps the current pivot). One step
 * each: a handle drag that changed the board ({@link begin} / {@link end}; a press without change records nothing),
 * a view, an equation apply, reset, lock-horizontal off → on ({@link record}). The observer camera, focal length, `D`, roll and pivot changes are never recorded (callers do not
 * call the stack for them).
 */
export class UndoStack {
  private readonly steps: RigState[] = [];
  private gesture: RigState | null = null;

  constructor(readonly max = UNDO_MAX) {}

  get size(): number {
    return this.steps.length;
  }

  get canUndo(): boolean {
    return this.steps.length > 0;
  }

  private push(rig: RigState): void {
    this.steps.push(clone(rig));
    if (this.steps.length > this.max) this.steps.shift();
  }

  /** A discrete action (view, equation, reset, lock on): one step when the state changed (pivot ignored). */
  record(before: RigState, after: RigState): boolean {
    if (sameState(before, after)) return false;
    this.push(before);
    return true;
  }

  /** Pointer-down of a handle drag. */
  begin(rig: RigState): void {
    this.gesture = clone(rig);
  }

  /** Release: one step when the board changed since {@link begin}. */
  end(rig: RigState): boolean {
    const g = this.gesture;
    this.gesture = null;
    if (g === null || sameBoard(g, rig)) return false;
    this.push(g);
    return true;
  }

  /** Abandon the current gesture without recording. */
  cancel(): void {
    this.gesture = null;
  }

  /** Pop the last snapshot, keeping the current pivot; `null` when empty. */
  undo(current: RigState): RigState | null {
    this.gesture = null;
    const s = this.steps.pop();
    return s === undefined ? null : { ...s, P: copy3(current.P) };
  }

  clear(): void {
    this.steps.length = 0;
    this.gesture = null;
  }
}

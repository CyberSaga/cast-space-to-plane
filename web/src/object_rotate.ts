/**
 * M11 single-object rotation (spec-v0.3 §2, §3; contract §5.8) — the pure, DOM-free part, unit-tested
 * (`web/test/object_rotate.test.ts`). An object's pose is its `transform` (`world = R·local + p`, `R` the core's Z-Y-X
 * Euler matrix, §2.0); it is rotated about a world axis through the centre of its **local** bounding box, so that
 * centre keeps its world position. The camera, the board, the lights and the receivers are never touched here.
 *
 * Also here: the ring geometry and the ring-drag angle of the observer pane (the rule of §5.7.8 item 1), the numeric
 * fields' parsing and display, the ground (落地) translation and {@link ObjectDrag}, the drag lifecycle as a state machine
 * whose side effects (stage A, the 3D proxy, the restore) are injected by `main.ts`.
 */

import { euler_zyx_matrix, rotation_x, rotation_y, rotation_z, transform_frame } from "castplane";
import type { Mat3, Transform, Vec3 } from "castplane";

import { KAPPA_DEG_PER_PX } from "./rig.js";

// ------------------------------------------------------------------------------------------------ constants (§5.8.6)

/** The drag angle snaps to multiples of this (degrees) while 吸附 is on and Alt is not held. */
export const OBJECT_SNAP_DEG = 15;
/** A scene whose stage A took longer than this at load (ms) updates only the 3D proxy during a drag (§5.8.2). */
export const LIVE_STAGE_A_MS = 150;
/** Ring radius: this factor × half the local bounding-box diagonal, at least {@link OBJECT_RING_MIN_M}. */
export const OBJECT_RING_FACTOR = 1.2;
export const OBJECT_RING_MIN_M = 0.3;
/** Segments of each object ring. */
export const OBJECT_RING_SEGMENTS = 72;
/** Gimbal-lock threshold of {@link euler_zyx_from_matrix}: `hypot(R₀₀, R₁₀)` below it means `ry = ±90°`. */
export const GIMBAL_EPS = 1e-9;
/** A ring whose screen tangent is shorter than this is seen edge-on: the tangent is taken as `(1, 0)`. */
export const EDGE_ON_EPS = 1e-6;

/** A world axis: 0 = x, 1 = y, 2 = z. */
export type Axis = 0 | 1 | 2;

const DEG = Math.PI / 180;

// ------------------------------------------------------------------------------------------------ small vector helpers

const sub3 = (a: readonly number[], b: readonly number[]): Vec3 => [a[0]! - b[0]!, a[1]! - b[1]!, a[2]! - b[2]!];
const add3 = (a: readonly number[], b: readonly number[]): Vec3 => [a[0]! + b[0]!, a[1]! + b[1]!, a[2]! + b[2]!];
const dot3 = (a: readonly number[], b: readonly number[]): number => a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;
const cross3 = (a: readonly number[], b: readonly number[]): Vec3 =>
  [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];
const mul3 = (R: Mat3, v: readonly number[]): Vec3 => [dot3(R[0], v), dot3(R[1], v), dot3(R[2], v)];
/** `Rᵀ·v`. */
const tmul3 = (R: Mat3, v: readonly number[]): Vec3 => [
  R[0][0] * v[0]! + R[1][0] * v[1]! + R[2][0] * v[2]!,
  R[0][1] * v[0]! + R[1][1] * v[1]! + R[2][1] * v[2]!,
  R[0][2] * v[0]! + R[1][2] * v[1]! + R[2][2] * v[2]!,
];
/** `A·B` (3×3). */
export function matmul(A: Mat3, B: Mat3): Mat3 {
  const out = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[i][j] = A[i][0] * B[0][j] + A[i][1] * B[1][j] + A[i][2] * B[2][j];
  return out;
}
/** `A·Bᵀ` (3×3). */
function matmul_t(A: Mat3, B: Mat3): Mat3 {
  const out = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[i][j] = A[i][0] * B[j][0] + A[i][1] * B[j][1] + A[i][2] * B[j][2];
  return out;
}
const z0 = (x: number): number => x + 0;

// ------------------------------------------------------------------------------------------------ transforms

/** A deep copy of a transform. */
export function clone_transform(t: Transform): Transform {
  return { position: [t.position[0], t.position[1], t.position[2]], rotation_deg: [t.rotation_deg[0], t.rotation_deg[1], t.rotation_deg[2]] };
}

/** Exact equality of two transforms (every component `===`). */
export function same_transform(a: Transform, b: Transform): boolean {
  return a.position[0] === b.position[0] && a.position[1] === b.position[1] && a.position[2] === b.position[2]
    && a.rotation_deg[0] === b.rotation_deg[0] && a.rotation_deg[1] === b.rotation_deg[1] && a.rotation_deg[2] === b.rotation_deg[2];
}

/** `x` wrapped into `(−180, 180]` (no `-0`). */
export function wrap_angle(x: number): number {
  const w = x - 360 * Math.ceil((x - 180) / 360);
  return w <= -180 ? w + 360 : z0(w);
}

/**
 * `[rx, ry, rz]` (degrees) with `euler_zyx_matrix([rx, ry, rz]) ≈ R` (spec-v0.3 §2.4, contract §5.8.1):
 * `ry = atan2(−R₂₀, hypot(R₀₀, R₁₀))` in `[−90°, 90°]`; `rz = atan2(R₁₀, R₀₀)`, `rx = atan2(R₂₁, R₂₂)`; at gimbal lock
 * (`hypot(R₀₀, R₁₀) < 1e-9`) `rx = 0` and `rz = atan2(−R₀₁, R₁₁)`. `rx`, `rz` in `(−180°, 180°]`; not unwrapped.
 */
export function euler_zyx_from_matrix(R: Mat3): Vec3 {
  const h = Math.hypot(R[0][0], R[1][0]);
  const ry = Math.atan2(-R[2][0], h) / DEG;
  if (h < GIMBAL_EPS) return [0, z0(ry), wrap_angle(Math.atan2(-R[0][1], R[1][1]) / DEG)];
  return [wrap_angle(Math.atan2(R[2][1], R[2][2]) / DEG), z0(ry), wrap_angle(Math.atan2(R[1][0], R[0][0]) / DEG)];
}

/** The right-handed rotation about world axis `axis` by `deg` degrees. */
export function axis_rotation(axis: Axis, deg: number): Mat3 {
  return axis === 0 ? rotation_x(deg) : axis === 1 ? rotation_y(deg) : rotation_z(deg);
}

/** The local bounding box of an object (spec-v0.3 §2.1): `{Rᵀ(v − p)}` of its world vertices (stage A's
 * `mesh.vertices`) under `transform`; its centre `c_local` and half its diagonal (the ring radius, §3.2). */
export function local_bbox(transform: Transform, vertices: readonly (readonly number[])[]): { centre: Vec3; half_diagonal: number } {
  const [R, p] = transform_frame(transform);
  const lo: Vec3 = [Infinity, Infinity, Infinity], hi: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const v of vertices) {
    const l = tmul3(R, sub3(v, p));
    for (let k = 0; k < 3; k++) {
      if (l[k]! < lo[k]!) lo[k] = l[k]!;
      if (l[k]! > hi[k]!) hi[k] = l[k]!;
    }
  }
  if (vertices.length === 0) return { centre: [0, 0, 0], half_diagonal: 0 };
  const centre: Vec3 = [z0((lo[0] + hi[0]) / 2), z0((lo[1] + hi[1]) / 2), z0((lo[2] + hi[2]) / 2)];
  return { centre, half_diagonal: Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]) / 2 };
}

/** `c_local` of spec-v0.3 §2.1 (the local bounding-box centre). */
export function local_centre(transform: Transform, vertices: readonly (readonly number[])[]): Vec3 {
  return local_bbox(transform, vertices).centre;
}

/** The world pivot `c_w = R·c_local + p`. */
export function world_centre(transform: Transform, c_local: readonly number[]): Vec3 {
  const [R, p] = transform_frame(transform);
  return add3(mul3(R, c_local), p);
}

/**
 * Rotate the pose `t` about world axis `axis` by `deg` through its pivot (spec-v0.3 §2.2): `R′ = Q·R`,
 * `p′ = c_w + Q·(p − c_w)`. About `z` the Euler angles are exact: `rz′ = wrap(rz + θ)` and `rx`, `ry` unchanged
 * (`Rz(θ)·Rz(rz)·Ry·Rx = Rz(rz + θ)·Ry·Rx`); about `x` or `y`, `R′` is decomposed ({@link euler_zyx_from_matrix}).
 */
export function rotate_about_world_axis(t: Transform, c_local: readonly number[], axis: Axis, deg: number): Transform {
  const [R, p] = transform_frame(t);
  const Q = axis_rotation(axis, deg);
  const c = add3(mul3(R, c_local), p);
  const position = add3(c, mul3(Q, sub3(p, c)));
  const rotation_deg: Vec3 = axis === 2
    ? [t.rotation_deg[0], t.rotation_deg[1], wrap_angle(t.rotation_deg[2] + deg)]
    : euler_zyx_from_matrix(matmul(Q, R));
  return { position: [z0(position[0]), z0(position[1]), z0(position[2])], rotation_deg };
}

/**
 * The numeric fields (spec-v0.3 §2.3): the pose with `rotation_deg = r` exactly and the same pivot,
 * `R′ = euler_zyx_matrix(r)`, `p′ = c_w + R′·Rᵀ·(p − c_w)`.
 */
export function set_rotation(t: Transform, c_local: readonly number[], r: readonly number[]): Transform {
  const [R, p] = transform_frame(t);
  const R1 = euler_zyx_matrix(r);
  const c = add3(mul3(R, c_local), p);
  const position = add3(c, mul3(matmul_t(R1, R), sub3(p, c)));
  return { position: [z0(position[0]), z0(position[1]), z0(position[2])], rotation_deg: [r[0]!, r[1]!, r[2]!] };
}

/** The pose `t` translated by `d` (rotation unchanged). */
export function translate(t: Transform, d: readonly number[]): Transform {
  const p = add3(t.position, d);
  return { position: [z0(p[0]), z0(p[1]), z0(p[2])], rotation_deg: [t.rotation_deg[0], t.rotation_deg[1], t.rotation_deg[2]] };
}

/** 落地 (spec-v0.3 §3.3): the pose moved along the unit receiver normal `n` by `−min_distance`, so that the minimum
 * signed distance of the object to the plane becomes 0. */
export function ground_transform(t: Transform, min_distance: number, n: readonly number[]): Transform {
  return translate(t, [-min_distance * n[0]!, -min_distance * n[1]!, -min_distance * n[2]!]);
}

// ------------------------------------------------------------------------------------------------ snapping, fields

/** Snap the drag angle to a multiple of {@link OBJECT_SNAP_DEG} when `snap` (吸附 on, Alt not held). */
export function snap_angle(theta_deg: number, snap: boolean): number {
  return snap ? z0(Math.round(theta_deg / OBJECT_SNAP_DEG) * OBJECT_SNAP_DEG) : theta_deg;
}

/** A numeric field's angle: a finite number (degrees), or null (empty, NaN, ±Infinity or not a number). */
export function parse_angle(text: string): number | null {
  const s = text.trim().replace(/[−–—－]/g, "-").replace(/°$/, "").trim();
  if (s === "") return null;
  const x = Number(s);
  return Number.isFinite(x) ? x : null;
}

/** The panel's text of an angle: wrapped into `(−180°, 180°]`, 0.1° (never `-0.0`). */
export function format_angle(deg: number): string {
  const t = wrap_angle(deg).toFixed(1);
  return t === "-0.0" ? "0.0" : t === "-180.0" ? "180.0" : t;
}

// ------------------------------------------------------------------------------------------------ rings (§3.2)

/** The ring radius of an object with half local diagonal `half_diagonal`: `max(1.2 × it, 0.3 m)`. */
export function ring_radius(half_diagonal: number): number {
  return Math.max(OBJECT_RING_FACTOR * half_diagonal, OBJECT_RING_MIN_M);
}

/** The {@link OBJECT_RING_SEGMENTS} points of the ring about world axis `axis` (in the plane perpendicular to it). */
export function ring_points(centre: readonly number[], radius: number, axis: Axis): Vec3[] {
  const pts: Vec3[] = [];
  const i = (axis + 1) % 3, j = (axis + 2) % 3;
  for (let k = 0; k < OBJECT_RING_SEGMENTS; k++) {
    const a = (2 * Math.PI * k) / OBJECT_RING_SEGMENTS;
    const q: Vec3 = [centre[0]!, centre[1]!, centre[2]!];
    q[i] += radius * Math.cos(a);
    q[j] += radius * Math.sin(a);
    pts.push(q);
  }
  return pts;
}

/** The three rings (x, y, z) of an object. */
export interface ObjectRings {
  id: string;
  centre: Vec3;
  radius: number;
  rings: [Vec3[], Vec3[], Vec3[]];
}

export function object_rings(id: string, centre: Vec3, radius: number): ObjectRings {
  return { id, centre, radius, rings: [ring_points(centre, radius, 0), ring_points(centre, radius, 1), ring_points(centre, radius, 2)] };
}

/**
 * The drag angle of a ring (spec-v0.3 §3.2, the rule of contract §5.7.8 item 1): `w` the grabbed ring point relative to
 * `c_w`, `r_c`, `u_c` the observer camera's right / up axes at pointer-down, `(dx, dy)` the total pointer displacement
 * (DOM px, `dy` down). Tangent `t = axis × w`, screen tangent `t_s = (t·r_c, −t·u_c)` normalised (`(1, 0)` when
 * `|t_s| < 1e-6`, the ring seen edge-on); `θ = κ·(Δ·t_s)` degrees. Not snapped.
 */
export function ring_drag_angle(axis: Axis, w: readonly number[], r_c: readonly number[], u_c: readonly number[], dx: number,
  dy: number): number {
  const e: Vec3 = [0, 0, 0];
  e[axis] = 1;
  const t = cross3(e, w);
  let sx = dot3(t, r_c), sy = -dot3(t, u_c);
  const l = Math.hypot(sx, sy);
  if (l < EDGE_ON_EPS) [sx, sy] = [1, 0];
  else [sx, sy] = [sx / l, sy / l];
  return KAPPA_DEG_PER_PX * (dx * sx + dy * sy);
}

// ------------------------------------------------------------------------------------------------ drag lifecycle (§3.5)

/** The side effects of {@link ObjectDrag}, supplied by `main.ts` (contract §5.8.2). */
export interface ObjectDragEffects<S, A> {
  /** Steps 1–4 of `apply_object_transform` with `record: none` (stage A on the candidate, session, 3D matrices);
   * false when stage A threw (the committed pose and view are kept). */
  apply(id: string, t: Transform): boolean;
  /** The 3D proxy only (a slow scene during a drag: no stage A). */
  proxy(id: string, t: Transform): void;
  /** Back to the pointer-down state: `scene0` and `A0` (by reference), the session, both 3D groups at `t0`. */
  restore(id: string, t0: Transform, scene0: S, A0: A): void;
}

/** What {@link ObjectDrag.end} committed. */
export interface ObjectDragResult {
  id: string;
  t0: Transform;
  /** The committed pose (`t0` when nothing changed or stage A failed). */
  t: Transform;
  /** Whether stage A succeeded (false: restored to `t0`, the error is the caller's to show). */
  ok: boolean;
  /** Whether the pose differs from `t0` (an undo step is due). */
  changed: boolean;
}

interface Gesture<S, A> {
  id: string;
  t0: Transform;
  scene0: S;
  A0: A;
  seq: number;
  live: boolean;
  axis: Axis;
  c_local: Vec3;
  /** The candidate of the last move not yet applied by stage A (null when none). */
  pending: Transform | null;
  /** The pose stage A last ran on in this gesture (`t0` at first). */
  applied: Transform;
}

/**
 * The object-drag state machine (contract §5.8.2): `begin` remembers the pressed pose, scene and A record by reference
 * and the gesture's sequence number; `move(θ)` only stores the pending candidate; `frame(seq)` (at the start of an
 * animation frame) runs stage A on it at most once, and only for the current gesture (a stale number applies nothing);
 * a slow scene (`live: false`) only moves the 3D proxy there. `end()` takes the last candidate and runs stage A on it
 * synchronously (never waiting for a frame); `cancel()` invalidates the number and restores the pointer-down state.
 */
export class ObjectDrag<S, A> {
  private g: Gesture<S, A> | null = null;

  constructor(private readonly fx: ObjectDragEffects<S, A>) {}

  /** Whether a gesture is running. */
  get active(): boolean {
    return this.g !== null;
  }

  /** The current gesture's sequence number (null when none). */
  get seq(): number | null {
    return this.g?.seq ?? null;
  }

  /** The current gesture's object id (null when none). */
  get id(): string | null {
    return this.g?.id ?? null;
  }

  /** The current gesture's pending candidate (null when none, or applied). */
  get pending(): Transform | null {
    return this.g?.pending ?? null;
  }

  /** Pointer-down: a new gesture (any running one is forgotten without a restore). */
  begin(id: string, t0: Transform, scene0: S, A0: A, seq: number,
    opts: { live?: boolean; axis?: Axis; c_local?: readonly number[] } = {}): void {
    const c = opts.c_local ?? [0, 0, 0];
    this.g = { id, t0: clone_transform(t0), scene0, A0, seq, live: opts.live ?? true, axis: opts.axis ?? 2,
      c_local: [c[0]!, c[1]!, c[2]!], pending: null, applied: clone_transform(t0) };
  }

  /** A move: the candidate `t0` rotated about the gesture's axis by `theta_deg` (total angle, already snapped). No
   * stage A. Returns the candidate (null outside a gesture). */
  move(theta_deg: number): Transform | null {
    const g = this.g;
    if (g === null) return null;
    g.pending = rotate_about_world_axis(g.t0, g.c_local, g.axis, theta_deg);
    return clone_transform(g.pending);
  }

  /** Start of an animation frame: stage A on the pending candidate when `seq` is the current gesture's and the scene
   * is live (the 3D proxy otherwise). Returns whether stage A ran. */
  frame(seq: number | null = this.seq): boolean {
    const g = this.g;
    if (g === null || seq !== g.seq || g.pending === null) return false;
    if (!g.live) {
      this.fx.proxy(g.id, g.pending);
      return false;
    }
    if (same_transform(g.pending, g.applied)) {
      g.pending = null;
      return false;
    }
    const t = g.pending;
    if (this.fx.apply(g.id, t)) {
      g.applied = t;
      g.pending = null;
    }
    return true;
  }

  /** Release: the last candidate through stage A synchronously; on failure the pointer-down state is restored. */
  end(): ObjectDragResult | null {
    const g = this.g;
    if (g === null) return null;
    this.g = null;
    const cand = g.pending ?? g.applied;
    if (!same_transform(cand, g.applied)) {
      if (!this.fx.apply(g.id, cand)) {
        this.fx.restore(g.id, g.t0, g.scene0, g.A0);
        return { id: g.id, t0: g.t0, t: clone_transform(g.t0), ok: false, changed: false };
      }
      g.applied = cand;
    }
    return { id: g.id, t0: g.t0, t: clone_transform(g.applied), ok: true, changed: !same_transform(g.applied, g.t0) };
  }

  /** Abandon the gesture (a second finger): the sequence number is invalidated and the pointer-down state restored. */
  cancel(): void {
    const g = this.g;
    if (g === null) return;
    this.g = null;
    this.fx.restore(g.id, g.t0, g.scene0, g.A0);
  }

  /** Forget the gesture without restoring (a scene load replaced everything). */
  abandon(): void {
    this.g = null;
  }
}

/**
 * Rectilinear perspective camera (port of `castplane/camera.py`; spec §5.4, §5.7; contract §2.2).
 *
 * Rows of `R` are `(right', up', forward)` so `det R = −1` on purpose (`u` right, `v` up, depth positive in front).
 * `K = [[f·s, 0, u0], [0, f·s, v0], [0, 0, 1]]`, `P = K·[R|t]`, `x̃ = P·X`, divided LAST. Near functional
 * `ν(X) = forward·(x − C·w) − near·w`.
 */

import { make_warning } from "./errors.js";
import type { Warning } from "./errors.js";
import { TOL_DIR, ZERO_REL, clip_polygon_halfspace, clip_segment_halfspace, cross3, join, normalize_max } from "./homogeneous.js";
import { picture_plane_document, resolve_picture_plane } from "./picture_plane.js";
import type { PicturePlaneInfo, PicturePlaneRecord } from "./picture_plane.js";
import type { Camera } from "./scene.js";
import { radians } from "./transform.js";
import type { Mat3, Mat34, Vec2, Vec3, Vec4 } from "./types.js";

export const UP_WORLD: Vec3 = [0.0, 0.0, 1.0];
export const FALLBACK_UP: Vec3 = [0.0, 1.0, 0.0];
/** The extended canvas rectangle grows the canvas by this fraction on each side (contract §2.2 step 3). */
export const RECT_GROW = 0.25;

/** `[u_min, u_max, v_min, v_max]`. */
export type Rect = [number, number, number, number];

export interface CameraRecord {
  K: Mat3;
  R: Mat3;
  t: Vec3;
  Rt: Mat34;
  P: Mat34;
  C: Vec3;
  forward: Vec3;
  near: number;
  s: number;
  u0: number;
  v0: number;
  canvas_mm: Vec2;
  frame_mm: Vec2;
  rect: Rect;
  warnings: Warning[];
  /** M10: only for a `picture_plane` camera block, the document block of `picture_plane_document`. */
  picture_plane?: PicturePlaneRecord;
}

/** The fields of a validated camera block that the camera model reads. */
export type CameraBlock = Pick<Camera, "position" | "focal_length_mm" | "frame_mm"> & Partial<Camera>;

function norm3(v: readonly number[]): number {
  return Math.sqrt((v[0] as number) * (v[0] as number) + (v[1] as number) * (v[1] as number) + (v[2] as number) * (v[2] as number));
}

function unit(v: readonly number[]): Vec3 {
  const n = norm3(v);
  return [(v[0] as number) / n, (v[1] as number) / n, (v[2] as number) / n];
}

/** `(right, up, along_up)` before roll (contract §2.2): `right = normalize(forward × up_world)`, `up = right × forward`
 * with `up_world` = world z, or +y when `|forward × z| <= 1e-9` (`along_up` true). Python `camera._default_basis`. */
export function default_basis(forward: readonly number[]): [Vec3, Vec3, boolean] {
  let up_world = UP_WORLD;
  const along_up = norm3(cross3(forward, up_world)) <= 1e-9;
  if (along_up) up_world = FALLBACK_UP;
  const right = unit(cross3(forward, up_world));
  return [right, cross3(right, forward), along_up];
}

/** `forward` of a validated camera: target form, yaw/pitch form or (M10) `picture_plane` form, whose forward is `f`
 * of `resolve_picture_plane` bit for bit (contract §2.2, §5.7.2). */
export function camera_forward(cam: CameraBlock): Vec3 {
  if (cam.picture_plane !== undefined) return [...resolve_picture_plane(cam)[2].normal] as Vec3;
  if (cam.target !== undefined) {
    const t = cam.target, p = cam.position;
    return unit([t[0] - p[0], t[1] - p[1], t[2] - p[2]]);
  }
  const yaw = radians(cam.yaw_deg as number), pitch = radians(cam.pitch_deg as number);
  return [-Math.sin(yaw) * Math.cos(pitch), Math.cos(yaw) * Math.cos(pitch), Math.sin(pitch)];
}

/** Camera record `{K, R, t, Rt, P, C, forward, near, s, u0, v0, canvas_mm, frame_mm, rect, warnings}` (§5.4, §2.2). */
export function camera_matrix(cam_in: CameraBlock, canvas: readonly number[]): CameraRecord {
  const warnings: Warning[] = [];
  let cam = cam_in;
  let pp_info: PicturePlaneInfo | null = null;
  let roll_deg = cam.roll_deg ?? 0.0;
  if (cam.picture_plane !== undefined) {
    // M10 (spec-v0.2 §4.1): resolve to the target form; the explicit frame up never warns
    [cam, roll_deg, pp_info] = resolve_picture_plane(cam);
  }
  const C: Vec3 = [cam.position[0], cam.position[1], cam.position[2]];
  // picture_plane: forward is f bit for bit (the |f × z| <= 1e-9 fallback is decided on f, R[2] = document normal)
  const forward: Vec3 = pp_info === null ? camera_forward(cam) : [...pp_info.normal] as Vec3;
  const [right, up, along_up] = default_basis(forward);
  if (along_up && pp_info === null) warnings.push(make_warning("CAMERA_LOOKING_ALONG_UP", []));
  const rho = radians(roll_deg);
  const cr = Math.cos(rho), sr = Math.sin(rho);
  const right_r: Vec3 = [cr * right[0] + sr * up[0], cr * right[1] + sr * up[1], cr * right[2] + sr * up[2]];
  const up_r: Vec3 = [-sr * right[0] + cr * up[0], -sr * right[1] + cr * up[1], -sr * right[2] + cr * up[2]];
  const R: Mat3 = [right_r, up_r, [...forward] as Vec3];
  // t = −R·C as numpy's (−R) @ C
  const t = R.map((row) => -row[0] * C[0] + -row[1] * C[1] + -row[2] * C[2]) as Vec3;
  const cv: Vec2 = [canvas[0] as number, canvas[1] as number];
  const frame: Vec2 = [cam.frame_mm[0], cam.frame_mm[1]];
  const s = cv[0] / frame[0];
  const f = cam.focal_length_mm;
  const shift = cam.shift_mm ?? [0.0, 0.0];
  const u0 = shift[0] * s, v0 = shift[1] * s;
  const K: Mat3 = [[f * s, 0.0, u0], [0.0, f * s, v0], [0.0, 0.0, 1.0]];
  const Rt: Mat34 = [[...R[0], t[0]], [...R[1], t[1]], [...R[2], t[2]]] as Mat34;
  const P = K.map((k) => [0, 1, 2, 3].map((j) => k[0] * Rt[0][j]! + k[1] * Rt[1][j]! + k[2] * Rt[2][j]!)) as Mat34;
  const [W, H] = cv;
  const g = 0.5 + RECT_GROW;
  const rect: Rect = [-g * W, g * W, -g * H, g * H];
  const rec: CameraRecord = { K, R, t, Rt, P, C, forward, near: cam.near_m ?? 0.05, s, u0, v0, canvas_mm: cv, frame_mm: frame, rect, warnings };
  if (pp_info !== null) rec.picture_plane = picture_plane_document(pp_info, rec, f);
  return rec;
}

/** `x̃ = P·X` for one 4-vector (left-to-right 4-term sums, §5.4.4 (2)). */
export function project(cam: Pick<CameraRecord, "P">, X: readonly number[]): Vec3 {
  const P = cam.P;
  const x = X[0] as number, y = X[1] as number, z = X[2] as number, w = X[3] as number;
  return [
    P[0][0] * x + P[0][1] * y + P[0][2] * z + P[0][3] * w,
    P[1][0] * x + P[1][1] * y + P[1][2] * z + P[1][3] * w,
    P[2][0] * x + P[2][1] * y + P[2][2] * z + P[2][3] * w,
  ];
}

/** `(u, v) = (x̃1/x̃3, x̃2/x̃3)`; the last step of the drawing pipeline (contract §2.2 step 4). */
export function divide(x: readonly number[]): Vec2 {
  return [(x[0] as number) / (x[2] as number), (x[1] as number) / (x[2] as number)];
}

/** Near functional `ν(X) = (X0·f0 + X1·f1 + X2·f2) − offset·X3`, `offset = (f·C) + near` (contract §2.2). */
export function nu(cam: Pick<CameraRecord, "forward" | "C" | "near">, X: readonly number[]): number {
  const f = cam.forward, C = cam.C;
  const offset = (f[0] * C[0] + f[1] * C[1] + f[2] * C[2]) + cam.near;
  return ((X[0] as number) * f[0] + (X[1] as number) * f[1] + (X[2] as number) * f[2]) - offset * (X[3] as number);
}

/** Camera-space depth: third component of `[R|t]·X`. */
export function depth(cam: Pick<CameraRecord, "Rt">, X: readonly number[]): number {
  const r = cam.Rt[2];
  return r[0] * (X[0] as number) + r[1] * (X[1] as number) + r[2] * (X[2] as number) + r[3] * (X[3] as number);
}

/** Near-clip one homogeneous world segment against `ν >= 0`; `null` when nothing is in front. */
export function clip_segment_near(cam: CameraRecord, A: readonly number[], B: readonly number[]): [Vec4, Vec4] | null {
  return clip_segment_halfspace(A, B, nu(cam, A), nu(cam, B)) as [Vec4, Vec4] | null;
}

/** List form of `clip_segment_near` (row by row). */
export function clip_segments_near(cam: CameraRecord, A: readonly (readonly number[])[], B: readonly (readonly number[])[]): ([Vec4, Vec4] | null)[] {
  return A.map((a, i) => clip_segment_near(cam, a, B[i] as readonly number[]));
}

/** Sutherland–Hodgman near clip of a homogeneous world polygon (contract §2.2 step 1). */
export function clip_polygon_near(cam: CameraRecord, points: readonly (readonly number[])[]): Vec4[] {
  return clip_polygon_halfspace(points, points.map((p) => nu(cam, p))) as Vec4[];
}

/** The four functionals `(a, b, c)` of the homogeneous rectangle clip, `a x̃1 + b x̃2 + c x̃3 >= 0`. */
export function rect_functionals(rect: readonly number[]): Vec3[] {
  const u_min = rect[0] as number, u_max = rect[1] as number, v_min = rect[2] as number, v_max = rect[3] as number;
  return [
    [-1.0, 0.0, u_max],
    [1.0, 0.0, -u_min],
    [0.0, -1.0, v_max],
    [0.0, 1.0, -v_min],
  ];
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

/** Clip a 2-D homogeneous polygon to the rectangle (contract §2.2 step 3); fewer than 3 vertices after any
 * functional -> empty. */
export function clip_polygon_rect_h(points: readonly (readonly number[])[], rect: readonly number[]): Vec3[] {
  let pts: readonly (readonly number[])[] = points;
  for (const row of rect_functionals(rect)) {
    if (pts.length < 3) break;
    pts = clip_polygon_halfspace(pts, pts.map((p) => dot3(p, row)));
  }
  if (pts.length < 3) return [];
  return pts.map((p) => [p[0], p[1], p[2]] as Vec3);
}

/**
 * Homogeneous rectangle clip of one 2-D segment; `null` when dropped. Exactly `clip_segment_halfspace` applied with
 * the four `rect_functionals` rows in turn (same values, same interpolation and zero-row rule), written out on scalars
 * so that the per-edge path of stage B allocates nothing but its result.
 */
export function clip_segment_rect_h(A: readonly number[], B: readonly number[], rect: readonly number[]): [Vec3, Vec3] | null {
  let a0 = A[0] as number, a1 = A[1] as number, a2 = A[2] as number;
  let b0 = B[0] as number, b1 = B[1] as number, b2 = B[2] as number;
  const u_min = rect[0] as number, u_max = rect[1] as number, v_min = rect[2] as number, v_max = rect[3] as number;
  for (let k = 0; k < 4; k++) {
    const r0 = k === 0 ? -1.0 : k === 1 ? 1.0 : 0.0;
    const r1 = k === 2 ? -1.0 : k === 3 ? 1.0 : 0.0;
    const r2 = k === 0 ? u_max : k === 1 ? -u_min : k === 2 ? v_max : -v_min;
    const fa = a0 * r0 + a1 * r1 + a2 * r2;
    const fb = b0 * r0 + b1 * r1 + b2 * r2;
    const a_in = fa >= 0.0, b_in = fb >= 0.0;
    if (!(a_in || b_in)) return null;
    const ma = Math.max(Math.abs(a0), Math.abs(a1), Math.abs(a2)), mb = Math.max(Math.abs(b0), Math.abs(b1), Math.abs(b2));
    const scale = Math.max(ma, mb);
    if (a_in !== b_in) {
      const den = fa - fb;
      const x0 = (fa * b0 - fb * a0) / den, x1 = (fa * b1 - fb * a1) / den, x2 = (fa * b2 - fb * a2) / den;
      if (!a_in) [a0, a1, a2] = [x0, x1, x2];
      else [b0, b1, b2] = [x0, x1, x2];
    }
    const lim = ZERO_REL * scale;
    if (!(Math.max(Math.abs(a0), Math.abs(a1), Math.abs(a2)) > lim && Math.max(Math.abs(b0), Math.abs(b1), Math.abs(b2)) > lim)) return null;
  }
  return [[a0, a1, a2], [b0, b1, b2]];
}

/** List form of the homogeneous rectangle clip of 2-D segments (row by row). */
export function clip_segments_rect_h(A: readonly (readonly number[])[], B: readonly (readonly number[])[], rect: readonly number[]): ([Vec3, Vec3] | null)[] {
  return A.map((a, i) => clip_segment_rect_h(a, B[i] as readonly number[], rect));
}

/** Clip the 2-D line `a·u + b·v + c = 0` to the rectangle; `[[u, v], [u, v]]` or `null` (horizon segment). */
export function clip_line_rect(line: readonly number[], rect: readonly number[]): [Vec2, Vec2] | null {
  const [a, b, c] = normalize_max(line) as [number, number, number];
  const n2 = a * a + b * b;
  if (n2 <= 1e-18) return null;
  const p0: Vec2 = [-c * a / n2, -c * b / n2];
  const d: Vec2 = [-b, a];
  const u_min = rect[0] as number, u_max = rect[1] as number, v_min = rect[2] as number, v_max = rect[3] as number;
  let t0 = -Infinity, t1 = Infinity;
  const pairs: [number, number][] = [[-d[0], p0[0] - u_min], [d[0], u_max - p0[0]], [-d[1], p0[1] - v_min], [d[1], v_max - p0[1]]];
  for (const [p, q] of pairs) {
    if (Math.abs(p) <= 1e-15) {
      if (q < 0) return null;
      continue;
    }
    const r = q / p;
    if (p < 0) t0 = Math.max(t0, r);
    else t1 = Math.min(t1, r);
  }
  if (t0 >= t1) return null;
  return [[p0[0] + t0 * d[0], p0[1] + t0 * d[1]], [p0[0] + t1 * d[0], p0[1] + t1 * d[1]]];
}

/** Image `[u, v]` of the direction `(d, 0)` or `null` when `|x̃3| <= tol` (§5.5, contract §2.2). */
export function vanishing_point(cam: Pick<CameraRecord, "P">, d: readonly number[], tol = TOL_DIR): Vec2 | null {
  const x = project(cam, [d[0] as number, d[1] as number, d[2] as number, 0.0]);
  if (Math.abs(x[2]) <= tol) return null;
  return [x[0] / x[2], x[1] / x[2]];
}

export interface Horizon {
  line: Vec3;
  v_mm: number | null;
  segment: [Vec2, Vec2] | null;
  vanishing_points: { x: Vec2 | null; y: Vec2 | null; z: Vec2 | null };
}

/** Horizon of the ground: join of the images of `(1,0,0,0)` and `(0,1,0,0)` (§5.5, contract §2.2). */
export function horizon(cam: CameraRecord, tol = TOL_DIR): Horizon {
  const vx = project(cam, [1.0, 0.0, 0.0, 0.0]);
  const vy = project(cam, [0.0, 1.0, 0.0, 0.0]);
  const line = normalize_max(join(vx, vy)) as Vec3;
  const [, b, c] = line;
  return {
    line: [line[0], line[1], line[2]],
    v_mm: Math.abs(b) <= tol ? null : -c / b,
    segment: clip_line_rect(line, cam.rect),
    vanishing_points: {
      x: vanishing_point(cam, [1.0, 0.0, 0.0], tol),
      y: vanishing_point(cam, [0.0, 1.0, 0.0], tol),
      z: vanishing_point(cam, [0.0, 0.0, 1.0], tol),
    },
  };
}

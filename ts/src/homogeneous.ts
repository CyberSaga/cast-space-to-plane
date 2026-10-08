/**
 * Homogeneous-coordinate helpers (port of `castplane/homogeneous.py`; spec §2, §5.8; contract §2.1, §2.8).
 *
 * All vectors are oriented homogeneous vectors: finite points `(x, y, z, 1)`, directions `(d, 0)`; 2-D image
 * points `(x1, x2, x3)`. Nothing here divides by `w`: normalisation is by the max-|component| only. Scalar forms
 * only (contract §5.4.4 (6)); the batched numpy kernels are not ported.
 */

import type { Vec3, Vec4 } from "./types.js";

/** Dimensionless tolerance for direction / sign tests (contract §2.8). */
export const TOL_DIR = 1e-9;
/** Relative threshold under which an interpolated homogeneous vector counts as the zero vector. */
export const ZERO_REL = 1e-12;

/** `max |x_i|` of one vector (order free). */
export function row_max_abs(x: readonly number[]): number {
  let m = Math.abs(x[0] as number);
  for (let j = 1; j < x.length; j++) {
    const a = Math.abs(x[j] as number);
    // numpy.maximum propagates NaN
    if (a > m || Number.isNaN(a)) m = a;
  }
  return m;
}

/** Divide a homogeneous vector by its max-|component|, preserving sign; the zero vector is returned unchanged. */
export function normalize_max<T extends readonly number[]>(v: T): number[] {
  const m = row_max_abs(v);
  const safe = m === 0 ? 1 : m;
  return v.map((x) => x / safe);
}

/** 3-vector cross product (numpy's own formula); the join of two 2-D points / meet of two 2-D lines (§5.5). */
export function cross3(a: readonly number[], b: readonly number[]): Vec3 {
  const a0 = a[0] as number, a1 = a[1] as number, a2 = a[2] as number;
  const b0 = b[0] as number, b1 = b[1] as number, b2 = b[2] as number;
  return [a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0];
}

/** Join of two homogeneous 2-D points is the line through them (§5.5). */
export const join = cross3;
/** Meet of two homogeneous 2-D lines is their intersection point (§5.5). */
export const meet = cross3;

/** Append a `w` entry to every 3-vector. */
export function to_homogeneous(points: readonly (readonly number[])[], w = 1.0): Vec4[] {
  return points.map((p) => [p[0] as number, p[1] as number, p[2] as number, w]);
}

/** `max(1, extent of the bounding box of all vertices and the camera position)` (contract §2.8). */
export function scene_scale(vertices: readonly (readonly number[])[], camera_position?: readonly number[] | null): number {
  const pts: (readonly number[])[] = [...vertices];
  if (camera_position !== undefined && camera_position !== null) pts.push(camera_position);
  if (pts.length === 0) return 1.0;
  let extent = -Infinity;
  for (let k = 0; k < 3; k++) {
    let lo = Infinity, hi = -Infinity;
    for (const p of pts) {
      const v = p[k] as number;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
    const e = hi - lo;
    if (e > extent) extent = e;
  }
  return Math.max(1.0, extent);
}

/** Length-valued tolerance `tol = 1e-9 * scene_scale` (§5.8, contract §2.8). */
export function tolerance(scale: number): number {
  return 1e-9 * scale;
}

function nonzero(p: readonly number[], scale: number): boolean {
  return row_max_abs(p) > ZERO_REL * scale;
}

/** Interpolation `(fa·b − fb·a) / (fa − fb)` of homogeneous coordinates (the point with `f == 0`). */
function interpolate(a: readonly number[], b: readonly number[], fa: number, fb: number): number[] {
  const denom = fa - fb;
  const out = new Array<number>(a.length);
  for (let k = 0; k < a.length; k++) out[k] = (fa * (b[k] as number) - fb * (a[k] as number)) / denom;
  return out;
}

/**
 * Clip one homogeneous segment against the functional `f >= 0` (contract §2.2 step 1 / 3): returns the clipped
 * endpoints or `null` when nothing is kept (also when an endpoint is the zero vector: the interpolation of two
 * antipodal directions is no projective point).
 */
export function clip_segment_halfspace<T extends readonly number[]>(a: T, b: T, fa: number, fb: number): [number[], number[]] | null {
  if (!(fa >= 0.0 || fb >= 0.0)) return null;
  const [a2, b2, keep] = clip_segment_halfspace_keep(a, b, fa, fb);
  return keep ? [a2, b2] : null;
}

/**
 * One row of the reference's batched `clip_segments_halfspace`: `[a2, b2, keep]` with the interpolation and the
 * zero-row filter of `clip_segment_halfspace` (its single implementation); a dropped row (`keep == false`) carries
 * meaningless values, as the batched reference's do. Used by `hidden.ts::drawn_segments_4d`.
 */
export function clip_segment_halfspace_keep(a: readonly number[], b: readonly number[], fa: number, fb: number): [number[], number[], boolean] {
  const a_in = fa >= 0.0;
  const b_in = fb >= 0.0;
  const scale = Math.max(row_max_abs(a), row_max_abs(b));
  let a2: readonly number[] = a;
  let b2: readonly number[] = b;
  if (a_in !== b_in) {
    const x = interpolate(a, b, fa, fb);
    if (!a_in) a2 = x;
    if (!b_in) b2 = x;
  }
  const keep = (a_in || b_in) && nonzero(a2, scale) && nonzero(b2, scale);
  return [[...a2], [...b2], keep];
}

/**
 * Sutherland–Hodgman step of a homogeneous polygon against `f >= 0` (§5.4, contract §2.2). Interpolation is linear
 * in the homogeneous coordinates (no division by `w`); zero rows produced by antipodal directions are dropped.
 */
export function clip_polygon_halfspace(points: readonly (readonly number[])[], values: readonly number[]): number[][] {
  const n = points.length;
  if (n === 0) return [];
  let all_in = true, all_out = true;
  for (const v of values) {
    if (v >= 0.0) all_out = false;
    else all_in = false;
  }
  if (all_in) return points.map((p) => [...p]);
  if (all_out) return [];
  const out: number[][] = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const a = points[i] as readonly number[], b = points[j] as readonly number[];
    const fa = values[i] as number, fb = values[j] as number;
    const a_in = fa >= 0.0, b_in = fb >= 0.0;
    if (a_in) out.push([...a]);
    if (a_in !== b_in) out.push(interpolate(a, b, fa, fb));
  }
  let scale = 0;
  for (const p of points) {
    const m = row_max_abs(p);
    if (m > scale || Number.isNaN(m)) scale = m;
  }
  return out.filter((p) => nonzero(p, scale));
}

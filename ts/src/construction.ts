/**
 * Construction points, rays and the self-check (port of `castplane/construction.py`; spec §5.5, §5.7; contract §2.7).
 *
 * 2-D image geometry on homogeneous 3-vectors or divided `(u, v)` canvas-mm points. The batched numpy kernels are
 * ported under the same plural names with list-in / list-out semantics, computed row by row (contract §5.4.2).
 */

import { clip_segment_rect_h, divide, project } from "./camera.js";
import type { CameraRecord } from "./camera.js";
import { TOL_DIR, cross3, normalize_max, row_max_abs } from "./homogeneous.js";
import type { Vec2, Vec3 } from "./types.js";

/** Extension factor of the `P'→S'` segment when the far point is at infinity (contract §2.7). */
export const RAY_EXTENSION = 0.2;
/** Relative threshold under which a 2-D line / meet counts as the zero vector (contract §2.7 / §2.8). */
export const LINE_ZERO_REL = 1e-9;
/** Max-normalised meets below this are parallel / coincident lines for the self-check (contract §2.7). */
export const LINE_PARALLEL_REL = 1e-6;

export interface SpecialPointImage {
  h: Vec3;
  point: Vec2 | null;
  at_infinity: Vec2 | null;
  behind: boolean;
  undefined: boolean;
}

function max_abs_matrix(P: readonly (readonly number[])[]): number {
  let m = 0;
  for (const row of P) {
    const r = row_max_abs(row);
    if (r > m || Number.isNaN(r)) m = r;
  }
  return m;
}

/** Image of `L` or `F` by plain division, never nulled (contract §2.7). */
export function special_point_image(cam: Pick<CameraRecord, "P">, X: readonly number[], tol: number): SpecialPointImage {
  const x = project(cam, X);
  const scale = max_abs_matrix(cam.P) * row_max_abs(X);
  if (row_max_abs(x) <= LINE_ZERO_REL * scale) return { h: x, point: null, at_infinity: null, behind: false, undefined: true };
  const x3 = x[2];
  if (Math.abs(x3) > tol) {
    return { h: x, point: [x[0] / x3 + 0, x[1] / x3 + 0], at_infinity: null, behind: x3 < -tol, undefined: false };
  }
  const d = normalize_max([x[0], x[1]]);
  return { h: x, point: null, at_infinity: [(d[0] as number) + 0, (d[1] as number) + 0], behind: false, undefined: false };
}

function is_point(A: Vec2 | readonly Vec2[]): A is Vec2 {
  return typeof A[0] === "number";
}

/**
 * Segments covering three collinear 2-D points per row (contract §2.7 rays with a finite far point): from the lowest
 * to the highest of the three parameters along `C − B` (falling back to `A − B` when `B == C`). `A` is one point
 * (`L'` / `F'`, broadcast) or one point per row.
 */
export function covering_segments(A: Vec2 | readonly Vec2[], B: readonly Vec2[], C: readonly Vec2[]): [Vec2, Vec2][] {
  return B.map((b, i) => {
    const a = is_point(A) ? A : (A[i] as Vec2);
    const c = C[i] as Vec2;
    let d0 = c[0] - b[0], d1 = c[1] - b[1];
    const alt0 = a[0] - b[0], alt1 = a[1] - b[1];
    if (Math.max(Math.abs(d0), Math.abs(d1)) <= 1e-12 * Math.max(1.0, Math.max(Math.abs(b[0]), Math.abs(b[1])))) {
      d0 = alt0;
      d1 = alt1;
    }
    let norm = Math.sqrt(d0 * d0 + d1 * d1);
    if (norm === 0) norm = 1.0;
    d0 = d0 / norm;
    d1 = d1 / norm;
    const tA = (a[0] - b[0]) * d0 + (a[1] - b[1]) * d1;
    const tB = 0.0;
    const tC = (c[0] - b[0]) * d0 + (c[1] - b[1]) * d1;
    const lo = Math.min(Math.min(tA, tB), tC);
    const hi = Math.max(Math.max(tA, tB), tC);
    return [[b[0] + lo * d0, b[1] + lo * d1], [b[0] + hi * d0, b[1] + hi * d1]];
  });
}

/** `B→C` extended by `frac` beyond both ends per row (contract §2.7, far point at infinity). */
export function extended_segments(B: readonly Vec2[], C: readonly Vec2[], frac = RAY_EXTENSION): [Vec2, Vec2][] {
  return B.map((b, i) => {
    const c = C[i] as Vec2;
    const d0 = c[0] - b[0], d1 = c[1] - b[1];
    return [[b[0] - frac * d0, b[1] - frac * d1], [c[0] + frac * d0, c[1] + frac * d1]];
  });
}

/** Homogeneous rectangle clip + divide of mm segments; zero-length results are not kept. `null` = not kept. */
export function clip_segments_uv(segments: readonly (readonly Vec2[])[], rect: readonly number[]): ([Vec2, Vec2] | null)[] {
  return segments.map((seg) => {
    const p = seg[0] as Vec2, q = seg[1] as Vec2;
    const r = clip_segment_rect_h([p[0], p[1], 1.0], [q[0], q[1], 1.0], rect);
    if (r === null) return null;
    const a = divide(r[0]), b = divide(r[1]);
    if (Math.max(Math.abs(b[0] - a[0]), Math.abs(b[1] - a[1])) > 1e-9) return [a, b];
    return null;
  });
}

export interface CheckResult {
  err: number[];
  skipped: boolean[];
}

/** Degenerate form of the self-check when one construction line is undefined (`S' = P'` or `S' = Q'`). */
export function coincidence_check(Sp: readonly Vec3[], Rp: readonly Vec3[], tol: number): CheckResult {
  const err: number[] = [], skipped: boolean[] = [];
  Sp.forEach((s, i) => {
    const r = Rp[i] as Vec3;
    const skip = Math.abs(s[2]) <= tol || Math.abs(r[2]) <= tol;
    skipped.push(skip);
    if (skip) {
      err.push(0.0);
      return;
    }
    const a = divide(s), b = divide(r);
    err.push(Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])));
  });
  return { err, skipped };
}

/** Spec §5.5 self-check `S'_check = (L'×P') × (F'×Q')` against `S'` (contract §2.7), row by row. */
export function self_check(Lp: readonly number[], Pp: readonly Vec3[], Fp: readonly number[], Qp: readonly Vec3[],
  Sp: readonly Vec3[], tol: number): CheckResult {
  const err: number[] = [], skipped: boolean[] = [];
  const mL = row_max_abs(Lp), mF = row_max_abs(Fp);
  Pp.forEach((P, i) => {
    const Q = Qp[i] as Vec3, S = Sp[i] as Vec3;
    const l1 = cross3(Lp, P);
    const l2 = cross3(Fp, Q);
    let skip = row_max_abs(l1) <= LINE_ZERO_REL * (mL * row_max_abs(P)) || row_max_abs(l2) <= LINE_ZERO_REL * (mF * row_max_abs(Q));
    const meet = cross3(normalize_max(l1), normalize_max(l2));
    skip = skip || row_max_abs(meet) <= LINE_PARALLEL_REL;
    skip = skip || Math.abs(S[2]) <= tol;
    const meet_n = normalize_max(meet);
    skip = skip || Math.abs(meet_n[2] as number) <= TOL_DIR;
    skipped.push(skip);
    if (skip) {
      err.push(0.0);
      return;
    }
    const a = divide(meet_n), b = divide(normalize_max(S));
    err.push(Math.max(Math.abs(a[0] - b[0]), Math.abs(a[1] - b[1])));
  });
  return { err, skipped };
}

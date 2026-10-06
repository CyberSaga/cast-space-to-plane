/**
 * 3×3 conic mathematics for curved primitives (port of `castplane/conics.py`; spec §5.6, contract §2.6).
 *
 * A conic is a symmetric 3×3 matrix `C` with `xᵀ C x = 0`; a circle of radius `ρ` is `diag(1, 1, −ρ²)` in its own
 * frame, embedded by `E = [e1 e2 c; 0 0 1]`; a projective map `H` sends it to `adj(H)ᵀ C adj(H)`. Determinants are
 * closed cofactor forms and the condition number comes from `jacobi_eigenvalues_3` (contract §5.4.4 (5)).
 */

import { pymod } from "./pyfloat.js";
import type { Mat3, Mat43, Vec2, Vec3 } from "./types.js";

export const TWO_PI = 2.0 * Math.PI;
/** Sub-arcs shorter than this (radians) are dropped. */
export const ARC_MIN_SPAN = 1e-12;
/** Contract §2.6 sampling rule: 64 segments per full circle, proportionally fewer for arcs, minimum 8. */
export const SAMPLES_PER_CIRCLE = 64;
export const MIN_ARC_SAMPLES = 8;
/** Condition number above which a conic is emitted as a sampled polyline (`CONIC_SAMPLED`). */
export const COND_MAX = 1e8;
/** Threshold on the normalised determinants used by `classify`. */
export const CLASSIFY_TOL = 1e-12;

type M = readonly (readonly number[])[];

/** General matrix product with every entry a left-to-right sum in `k` order (contract §5.4.4 (2)). */
export function matmul(A: M, B: M): number[][] {
  const n = A.length, K = B.length, m = (B[0] as readonly number[]).length;
  const out: number[][] = [];
  for (let i = 0; i < n; i++) {
    const a = A[i] as readonly number[];
    const row = new Array<number>(m);
    for (let j = 0; j < m; j++) {
      let s = (a[0] as number) * ((B[0] as readonly number[])[j] as number);
      for (let k = 1; k < K; k++) s += (a[k] as number) * ((B[k] as readonly number[])[j] as number);
      row[j] = s;
    }
    out.push(row);
  }
  return out;
}

export function transpose(A: M): number[][] {
  const n = A.length, m = (A[0] as readonly number[]).length;
  const out: number[][] = [];
  for (let j = 0; j < m; j++) {
    const row = new Array<number>(n);
    for (let i = 0; i < n; i++) row[i] = (A[i] as readonly number[])[j] as number;
    out.push(row);
  }
  return out;
}

function all_finite(A: M): boolean {
  for (const row of A) for (const x of row) if (!Number.isFinite(x)) return false;
  return true;
}

/** Closed cofactor determinant `a(ei − fh) − b(di − fg) + c(dh − eg)`. */
export function det3(A: M): number {
  const [a, b, c] = A[0] as [number, number, number];
  const [d, e, f] = A[1] as [number, number, number];
  const [g, h, i] = A[2] as [number, number, number];
  return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
}

/**
 * Eigenvalues of a symmetric 3×3 matrix by cyclic Jacobi rotations (contract §5.4.4 (5)): stop when the
 * off-diagonal Frobenius norm is exactly 0, did not decrease during the last sweep, or after 64 sweeps.
 */
export function jacobi_eigenvalues_3(S: M): Vec3 {
  const a = S.map((r) => [...r]) as number[][];
  const off = (): number => {
    const x = (a[0] as number[])[1] as number, y = (a[0] as number[])[2] as number, z = (a[1] as number[])[2] as number;
    return Math.sqrt(2 * (x * x + y * y + z * z));
  };
  let prev = off();
  for (let sweep = 0; sweep < 64 && prev !== 0; sweep++) {
    for (const [p, q] of [[0, 1], [0, 2], [1, 2]] as [number, number][]) {
      const apq = (a[p] as number[])[q] as number;
      if (apq === 0) continue;
      const app = (a[p] as number[])[p] as number, aqq = (a[q] as number[])[q] as number;
      const theta = (aqq - app) / (2 * apq);
      const t = Math.abs(theta) > 1e150
        ? 0.5 / theta
        : (theta >= 0 ? 1 : -1) / (Math.abs(theta) + Math.sqrt(theta * theta + 1));
      const c = 1 / Math.sqrt(t * t + 1), s = t * c;
      for (let k = 0; k < 3; k++) {
        const akp = (a[k] as number[])[p] as number, akq = (a[k] as number[])[q] as number;
        (a[k] as number[])[p] = c * akp - s * akq;
        (a[k] as number[])[q] = s * akp + c * akq;
      }
      for (let k = 0; k < 3; k++) {
        const apk = (a[p] as number[])[k] as number, aqk = (a[q] as number[])[k] as number;
        (a[p] as number[])[k] = c * apk - s * aqk;
        (a[q] as number[])[k] = s * apk + c * aqk;
      }
    }
    const cur = off();
    if (!(cur < prev)) break;
    prev = cur;
  }
  return [(a[0] as number[])[0] as number, (a[1] as number[])[1] as number, (a[2] as number[])[2] as number];
}

/** `max|λ| / min|λ|` of a symmetric matrix (its 2-norm condition number); `Infinity` when `min|λ| = 0`. */
function symmetric_condition(S: M): number {
  const ev = jacobi_eigenvalues_3(S).map(Math.abs);
  const hi = Math.max(...ev), lo = Math.min(...ev);
  if (Number.isNaN(hi) || Number.isNaN(lo)) return Infinity;
  return lo <= 0.0 ? Infinity : hi / lo;
}

/** `C = diag(1, 1, −ρ²)`. */
export function circle_matrix(rho: number): Mat3 {
  return [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, -rho * rho]];
}

/** `E = [e1 e2 c; 0 0 1]` (4×3). */
export function embed_circle(centre: readonly number[], e1: readonly number[], e2: readonly number[]): Mat43 {
  return [
    [e1[0] as number, e2[0] as number, centre[0] as number],
    [e1[1] as number, e2[1] as number, centre[1] as number],
    [e1[2] as number, e2[2] as number, centre[2] as number],
    [0.0, 0.0, 1.0],
  ];
}

/** Adjugate of a 3×3 matrix in closed form. */
export function adjugate3(H: M): Mat3 {
  const [a, b, c] = H[0] as [number, number, number];
  const [d, e, f] = H[1] as [number, number, number];
  const [g, h, i] = H[2] as [number, number, number];
  return [
    [e * i - f * h, -(b * i - c * h), b * f - c * e],
    [-(d * i - f * g), a * i - c * g, -(a * f - c * d)],
    [d * h - e * g, -(a * h - b * g), a * e - b * d],
  ];
}

function symmetrise(C: M): Mat3 {
  const out = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[i][j] = 0.5 * (((C[i] as readonly number[])[j] as number) + ((C[j] as readonly number[])[i] as number));
  return out;
}

/** `C' = adj(H)ᵀ C adj(H)`, symmetrised. */
export function transform_conic(C: M, H: M): Mat3 {
  const A = adjugate3(H);
  return symmetrise(matmul(matmul(transpose(A), C), A));
}

/** Rows `x, y, w` of `M E` (ground receiver). */
export function ground_conic_map(Mm: M, E: M): Mat3 {
  const ME = matmul(Mm, E);
  return [ME[0], ME[1], ME[3]] as unknown as Mat3;
}

/** Symmetrise and divide by the max-|entry| (first occurrence in row-major order); the zero matrix as is. */
export function normalize_conic(C: M): Mat3 {
  const S = symmetrise(C);
  let idx = 0, best = -1;
  for (let k = 0; k < 9; k++) {
    const v = Math.abs(S[Math.floor(k / 3)]![k % 3]!);
    if (Number.isNaN(v)) {
      idx = k;
      break;
    }
    if (v > best) {
      best = v;
      idx = k;
    }
  }
  const m = S[Math.floor(idx / 3)]![idx % 3]!;
  if (m === 0.0 || !Number.isFinite(m)) return S.map((r) => [...r]) as Mat3;
  return S.map((r) => r.map((x) => x / m)) as Mat3;
}

function norm2(v: readonly number[]): number {
  return Math.sqrt((v[0] as number) * (v[0] as number) + (v[1] as number) * (v[1] as number));
}

function parabola_vertex(A: M, b: readonly number[], c: number): Vec2 | null {
  const p = (A[0] as readonly number[])[0] as number, q = (A[0] as readonly number[])[1] as number, r = (A[1] as readonly number[])[1] as number;
  const half = 0.5 * (p + r);
  const rad = Math.hypot(0.5 * (p - r), q);
  const lam1 = half + rad, lam2 = half - rad;
  const lam = Math.abs(lam1) >= Math.abs(lam2) ? lam1 : lam2;
  if (lam === 0.0) return null;
  let n: Vec2;
  if (Math.abs(q) > 1e-15 * Math.max(1.0, Math.abs(p), Math.abs(r))) n = [q, lam - p];
  else if (Math.abs(p) >= Math.abs(r)) n = [1.0, 0.0];
  else n = [0.0, 1.0];
  const nl = norm2(n);
  n = [n[0] / nl, n[1] / nl];
  const m: Vec2 = [-n[1], n[0]];
  const bn = (b[0] as number) * n[0] + (b[1] as number) * n[1];
  const bm = (b[0] as number) * m[0] + (b[1] as number) * m[1];
  if (Math.abs(bm) <= CLASSIFY_TOL) return null;
  const alpha = -bn / lam;
  const beta = -(lam * alpha * alpha + 2.0 * bn * alpha + c) / (2.0 * bm);
  return [alpha * n[0] + beta * m[0], alpha * n[1] + beta * m[1]];
}

/** The conic translated to its centre (its vertex for a parabola) and max-normalised; `[C_c, point | null]`. */
export function centred_conic(C: M, normalized = false): [Mat3, Vec2 | null] {
  const N = normalized ? (C.map((r) => [...r]) as Mat3) : normalize_conic(C);
  if (!all_finite(N)) return [N, null];
  const A = [[N[0][0], N[0][1]], [N[1][0], N[1][1]]];
  const b: Vec2 = [N[0][2], N[1][2]];
  const amax = Math.max(Math.abs(N[0][0]), Math.abs(N[0][1]), Math.abs(N[1][0]), Math.abs(N[1][1]));
  if (amax === 0.0) return [N, null];
  const det_n = (N[0][0] / amax) * (N[1][1] / amax) - (N[0][1] / amax) * (N[1][0] / amax);
  let point: Vec2 | null;
  if (Math.abs(det_n) <= CLASSIFY_TOL) {
    point = parabola_vertex(A, b, N[2][2]);
    if (point === null || !Number.isFinite(point[0]) || !Number.isFinite(point[1])) return [N, null];
  } else {
    const detA = N[0][0] * N[1][1] - N[0][1] * N[1][0];
    point = [-(N[1][1] * b[0] - N[0][1] * b[1]) / detA, -(-N[1][0] * b[0] + N[0][0] * b[1]) / detA];
  }
  const T: Mat3 = [[1.0, 0.0, point[0]], [0.0, 1.0, point[1]], [0.0, 0.0, 1.0]];
  const Cc = matmul(matmul(transpose(T), N), T);
  return [normalize_conic(Cc), point];
}

/** Translation-invariant classification (contract §2.6): parabola / ellipse / hyperbola / degenerate. */
export function classify(C: M, tol = CLASSIFY_TOL): string {
  const N = normalize_conic(C);
  if (!all_finite(N)) return "degenerate";
  const amax = Math.max(Math.abs(N[0][0]), Math.abs(N[0][1]), Math.abs(N[1][0]), Math.abs(N[1][1]));
  if (amax === 0.0) return "degenerate";
  const det2 = (N[0][0] / amax) * (N[1][1] / amax) - (N[0][1] / amax) * (N[1][0] / amax);
  const [Cc] = centred_conic(N);
  const d3 = det3(Cc);
  if (!Number.isFinite(d3) || Math.abs(d3) <= tol) return "degenerate";
  if (Math.abs(det2) <= tol) return "parabola";
  return det2 > 0.0 ? "ellipse" : "hyperbola";
}

/** 2-norm condition number of the centred conic (`Infinity` when singular). */
export function condition_number(C: M): number {
  const [Cc] = centred_conic(C);
  if (!all_finite(Cc)) return Infinity;
  return symmetric_condition(Cc);
}

/** `classify` and `condition_number` from a single centred conic. */
export function classify_and_condition(C: M, tol = CLASSIFY_TOL, normalized = false): [string, number] {
  const N = normalized ? (C.map((r) => [...r]) as Mat3) : normalize_conic(C);
  if (!all_finite(N)) return ["degenerate", Infinity];
  const amax = Math.max(Math.abs(N[0][0]), Math.abs(N[0][1]), Math.abs(N[1][0]), Math.abs(N[1][1]));
  if (amax === 0.0) return ["degenerate", condition_number(N)];
  const det2 = (N[0][0] / amax) * (N[1][1] / amax) - (N[0][1] / amax) * (N[1][0] / amax);
  const [Cc] = centred_conic(N, true);
  if (!all_finite(Cc)) return ["degenerate", Infinity];
  const d3 = det3(Cc);
  const cond = symmetric_condition(Cc);
  if (!Number.isFinite(d3) || Math.abs(d3) <= tol) return ["degenerate", cond];
  if (Math.abs(det2) <= tol) return ["parabola", cond];
  return [det2 > 0.0 ? "ellipse" : "hyperbola", cond];
}

/** `CONIC_SAMPLED` predicate: degenerate or condition number above `cond_max`. */
export function is_sampled(C: M, cond_max = COND_MAX): boolean {
  return classify(C) === "degenerate" || condition_number(C) > cond_max;
}

/** Centre, semi-axes `(a >= b > 0)` and rotation in `[0, π)` of a real ellipse, or `null`. */
export function ellipse_params(Cin: M): [Vec2, [number, number], number] | null {
  const C = normalize_conic(Cin);
  if (!all_finite(C)) return null;
  const A00 = C[0][0], A01 = C[0][1], A10 = C[1][0], A11 = C[1][1];
  const b0 = C[0][2], b1 = C[1][2];
  const c = C[2][2];
  const detA = A00 * A11 - A01 * A10;
  if (detA <= 1e-300) return null;
  const Ai00 = A11 / detA, Ai01 = -A01 / detA, Ai10 = -A10 / detA, Ai11 = A00 / detA;
  const centre: Vec2 = [-(Ai00 * b0 + Ai01 * b1), -(Ai10 * b0 + Ai11 * b1)];
  // b @ Ainv @ b = (bᵀ Ainv) · b
  const bA0 = b0 * Ai00 + b1 * Ai10, bA1 = b0 * Ai01 + b1 * Ai11;
  const k = (bA0 * b0 + bA1 * b1) - c;
  if (k === 0.0) return null;
  const p = A00, q = A01, r = A11;
  const half = 0.5 * (p + r);
  const rad = Math.hypot(0.5 * (p - r), q);
  const lam1 = half + rad, lam2 = half - rad;
  const ratio1 = lam1 !== 0.0 ? k / lam1 : -1.0;
  const ratio2 = lam2 !== 0.0 ? k / lam2 : -1.0;
  if (ratio1 <= 0.0 || ratio2 <= 0.0) return null;
  const s1 = Math.sqrt(ratio1), s2 = Math.sqrt(ratio2);
  let v1: Vec2;
  if (Math.abs(q) > 1e-15 * Math.max(1.0, Math.abs(p), Math.abs(r))) v1 = [q, lam1 - p];
  else if (p >= r) v1 = [1.0, 0.0];
  else v1 = [0.0, 1.0];
  let major: number, minor: number, v: Vec2;
  if (s1 >= s2) {
    major = s1;
    minor = s2;
    v = v1;
  } else {
    major = s2;
    minor = s1;
    v = [-v1[1], v1[0]];
  }
  let rot = pymod(Math.atan2(v[1], v[0]), Math.PI);
  if (rot >= Math.PI - 1e-15) rot = 0.0;
  return [centre, [major, minor], rot];
}

/** `X(θ) = H (ρ cos θ, ρ sin θ, 1)` for a `(k, 3)` map `H`. */
export function conic_point(H: M, theta: number, rho = 1.0): number[] {
  const l0 = rho * Math.cos(theta), l1 = rho * Math.sin(theta), l2 = 1.0;
  return H.map((h) => (h[0] as number) * l0 + (h[1] as number) * l1 + (h[2] as number) * l2);
}

/** `conic_point` for several parameters. */
export function conic_points(H: M, thetas: readonly number[], rho = 1.0): number[][] {
  return thetas.map((t) => conic_point(H, t, rho));
}

/** `n` equal parameter steps from `θ0` to `θ1` -> `n + 1` homogeneous points. */
export function sample_arc(H: M, rho: number, theta0: number, theta1: number, n: number): number[][] {
  const m = Math.max(1, Math.trunc(n));
  const th: number[] = [];
  for (let k = 0; k <= m; k++) th.push(theta0 + (theta1 - theta0) * k / m);
  return conic_points(H, th, rho);
}

/** Contract §2.6: `max(minimum, round(per_circle · |θ1 − θ0| / 2π))` segments. */
export function sample_count(theta0: number, theta1: number, per_circle = SAMPLES_PER_CIRCLE, minimum = MIN_ARC_SAMPLES): number {
  const span = Math.abs(theta1 - theta0);
  return Math.max(Math.trunc(minimum), Math.floor(per_circle * span / TWO_PI + 0.5));
}

/** `(A, B, C)` with `f · X(θ) = A cos θ + B sin θ + C` along `X(θ) = H (ρ cos θ, ρ sin θ, 1)`. */
export function functional_coeffs(f: readonly number[], H: M, rho = 1.0): [number, number, number] {
  const g = [0, 1, 2].map((j) => {
    let s = (f[0] as number) * ((H[0] as readonly number[])[j] as number);
    for (let i = 1; i < f.length; i++) s += (f[i] as number) * ((H[i] as readonly number[])[j] as number);
    return s;
  });
  return [rho * (g[0] as number), rho * (g[1] as number), g[2] as number];
}

/**
 * Closed-form solution of `A cos θ + B sin θ + C > tol` on `[θ0, θ1]` (at most one full turn): a list of
 * `[a, b]` intervals in increasing order; on a full turn a region straddling the seam is one interval with
 * `b > θ1`; intervals shorter than `ARC_MIN_SPAN` are dropped.
 */
export function sub_arcs_where_nonnegative(A: number, B: number, Cin: number, theta0 = 0.0, theta1 = TWO_PI, tol = 0.0): [number, number][] {
  const C = Cin - tol;
  if (theta1 <= theta0) return [];
  const R = Math.hypot(A, B);
  if (R <= 1e-300 * Math.max(1.0, Math.abs(C)) || R === 0.0) return C > 0.0 ? [[theta0, theta1]] : [];
  if (C >= R) return [[theta0, theta1]];
  if (C <= -R) return [];
  const phi = Math.atan2(B, A);
  const delta = Math.acos(Math.max(-1.0, Math.min(1.0, -C / R)));
  const lo = phi - delta, hi = phi + delta;
  const k0 = Math.floor((theta0 - hi) / TWO_PI);
  const k1 = Math.ceil((theta1 - lo) / TWO_PI);
  let out: [number, number][] = [];
  for (let k = k0; k <= k1; k++) {
    const a = Math.max(theta0, lo + k * TWO_PI);
    const b = Math.min(theta1, hi + k * TWO_PI);
    if (b > a) {
      const last = out[out.length - 1];
      if (last !== undefined && a <= last[1] + 1e-15) last[1] = Math.max(last[1], b);
      else out.push([a, b]);
    }
  }
  const full_turn = theta1 - theta0 >= TWO_PI - ARC_MIN_SPAN;
  if (full_turn && out.length >= 2 && (out[0] as [number, number])[0] <= theta0 && (out[out.length - 1] as [number, number])[1] >= theta1) {
    const merged: [number, number] = [(out[out.length - 1] as [number, number])[0], (out[0] as [number, number])[1] + TWO_PI];
    out = [...out.slice(1, -1), merged];
  }
  return out.filter((iv) => iv[1] - iv[0] > ARC_MIN_SPAN);
}

/** SVG `A` flags `[large_arc, sweep]` of the ellipse arc from `p_start` through `p_mid` to `p_end` (v-up frame). */
export function arc_svg_flags(centre: readonly number[], axes: readonly number[], rotation: number,
  p_start: readonly number[], p_mid: readonly number[], p_end: readonly number[]): [number, number] {
  const a = axes[0] as number, b = axes[1] as number;
  const cr = Math.cos(rotation), sr = Math.sin(rotation);
  const param = (p: readonly number[]): number => {
    const d0 = (p[0] as number) - (centre[0] as number), d1 = (p[1] as number) - (centre[1] as number);
    const x = cr * d0 + sr * d1;
    const y = -sr * d0 + cr * d1;
    return Math.atan2(b !== 0.0 ? y / b : y, a !== 0.0 ? x / a : x);
  };
  const ps = param(p_start), pm = param(p_mid), pe = param(p_end);
  let ccw_end = pymod(pe - ps, TWO_PI);
  const ccw_mid = pymod(pm - ps, TWO_PI);
  if (ccw_end <= 1e-15) ccw_end = TWO_PI;
  let sweep: number, span: number;
  if (ccw_mid < ccw_end) {
    sweep = 1;
    span = ccw_end;
  } else {
    sweep = 0;
    span = TWO_PI - ccw_end;
  }
  return [span > Math.PI ? 1 : 0, sweep];
}

// ---------------------------------------------------------------------------
// circle records (contract §2.6) and output-stage helpers
// ---------------------------------------------------------------------------

function norm3(v: readonly number[]): number {
  return Math.sqrt((v[0] as number) * (v[0] as number) + (v[1] as number) * (v[1] as number) + (v[2] as number) * (v[2] as number));
}

function cross(a: readonly number[], b: readonly number[]): Vec3 {
  const a0 = a[0] as number, a1 = a[1] as number, a2 = a[2] as number;
  const b0 = b[0] as number, b1 = b[1] as number, b2 = b[2] as number;
  return [a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0];
}

/** Frame `(e1, e2)` of a circle with unit normal `n`: `e1 = normalize(n × z)` (fallbacks tried in order). */
export function circle_frame(normal: readonly number[], tol = 1e-9, fallback?: readonly (readonly number[])[]): [Vec3, Vec3] {
  const nl = norm3(normal);
  const n: Vec3 = [(normal[0] as number) / nl, (normal[1] as number) / nl, (normal[2] as number) / nl];
  let e1 = cross(n, [0.0, 0.0, 1.0]);
  if (norm3(e1) <= tol) {
    const candidates = fallback === undefined ? [[1.0, 0.0, 0.0]] : fallback;
    for (const cand of candidates) {
      e1 = cross(n, cand);
      if (norm3(e1) > tol) break;
    }
  }
  const l1 = norm3(e1);
  e1 = [e1[0] / l1, e1[1] / l1, e1[2] / l1];
  return [e1, cross(n, e1)];
}

export interface Circle {
  centre: Vec3;
  e1: Vec3;
  e2: Vec3;
  radius: number;
  normal?: Vec3;
}

export function circle_record(centre: readonly number[], e1: readonly number[], e2: readonly number[], radius: number): Circle {
  const v = (x: readonly number[]): Vec3 => [x[0] as number, x[1] as number, x[2] as number];
  return { centre: v(centre), e1: v(e1), e2: v(e2), radius };
}

export function circle_embedding(circle: Circle): Mat43 {
  return embed_circle(circle.centre, circle.e1, circle.e2);
}

export function circle_point(circle: Circle, theta: number): number[] {
  return conic_point(circle_embedding(circle), theta, circle.radius);
}

export interface CircleLists {
  centre: Vec3;
  e1: Vec3;
  e2: Vec3;
  radius: number;
}

function circle_lists(circle: Circle): CircleLists {
  const v = (x: Vec3): Vec3 => [x[0] + 0, x[1] + 0, x[2] + 0];
  return { centre: v(circle.centre), e1: v(circle.e1), e2: v(circle.e2), radius: circle.radius + 0 };
}

export interface ConicEntry {
  conic: number[][];
  kind: string;
  arc: { theta0: number; theta1: number } | null;
  circle: CircleLists;
  map: string;
  sampled: boolean;
  cond?: number;
}

/** A contract §2.6 / §3.1 `conics` entry for the circle mapped by the 3×3 map `H`. */
export function conic_entry(circle: Circle, H: M, arc: readonly number[] | null = null, map = "image"): ConicEntry {
  const C = normalize_conic(transform_conic(circle_matrix(circle.radius), H));
  const [kind, cond] = classify_and_condition(C, CLASSIFY_TOL, true);
  let arc_out: { theta0: number; theta1: number } | null = null;
  if (arc !== null) {
    const a = arc[0] as number, b = arc[1] as number;
    const [lo, hi] = a <= b ? [a, b] : [b, a];
    arc_out = { theta0: lo + 0, theta1: hi + 0 };
  }
  return {
    conic: C.map((r) => r.map((x) => x + 0)),
    kind,
    arc: arc_out,
    circle: circle_lists(circle),
    map,
    sampled: kind === "degenerate" || cond > COND_MAX,
    cond,
  };
}

export interface EllipseArc {
  centre: Vec2;
  axes: [number, number];
  rotation: number;
  start: Vec2;
  end: Vec2;
  large_arc: number;
  sweep: number;
}

/** Image-space ellipse parameters of the arc `[θ0, θ1]` under `H`, or `null` (not a real ellipse, or a sample
 * point with `x3 <= 0`). */
export function ellipse_arc_params(H: M, rho: number, theta0: number, theta1: number): EllipseArc | null {
  const C = transform_conic(circle_matrix(rho), H);
  const params = ellipse_params(C);
  if (params === null) return null;
  const [centre, axes, rot] = params;
  const pts = conic_points(H, [theta0, 0.5 * (theta0 + theta1), theta1], rho);
  if (pts.some((p) => (p[2] as number) <= 0.0)) return null;
  const uv = pts.map((p) => [(p[0] as number) / (p[2] as number), (p[1] as number) / (p[2] as number)] as Vec2);
  const [large, sweep] = arc_svg_flags(centre, axes, rot, uv[0] as Vec2, uv[1] as Vec2, uv[2] as Vec2);
  return { centre, axes: [axes[0], axes[1]], rotation: rot, start: uv[0] as Vec2, end: uv[2] as Vec2, large_arc: large, sweep };
}

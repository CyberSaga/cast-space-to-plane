/**
 * Sampled hidden-line removal, stage C (port of `castplane/hidden.py`; contract §5.1.6; spec §9 隱藏線消除).
 *
 * Pure functions of the document, the camera-free stage A (occluder geometry) and the stage-B camera / drawable
 * records. Entry point:
 *
 * ```ts
 * classify_document(doc, A, B)     // called by pipeline.compose when doc.hidden_lines is true
 * ```
 *
 * It fills `visibility` / `runs` of every subject drawable (§5.1.6.1), `polygon_edges` of every shadow record, conic
 * `runs` / `hidden_polylines` and restricts conic `arcs` / `ellipses` / `polylines` to the visible runs. Every list it
 * assigns is a fresh object; nothing is written into `A` or `B` (the edge entries are replaced by copies).
 *
 * Pieces (all exported, contract names):
 * - the constants `HLR_SPACING_MM`, `HLR_MIN_SAMPLES`, `HLR_MAX_SAMPLES`, `HLR_BISECTIONS`, `HLR_RAY_EPS` and
 *   `hlr_sample_count` / `hlr_tol_mm` (§5.1.6.4);
 * - occluders (§5.1.6.2): `occluder` dispatches on the record kind — box (slab test in the local frame), prism (side
 *   quads + caps with point-in-polygon, exact for concave prisms), cylinder / cone (lateral quadric with the height
 *   range + discs), sphere (quadric), every bounded receiver as an opaque convex plate, the unbounded ground as an
 *   opaque plane, and **any other kind** through the generic closed-mesh occluder (`rec.triangles` on the welded
 *   vertices when present, the `rec.mesh` faces otherwise; nothing throws). `first_hit` returns the smallest
 *   boundary-crossing parameter `t > eps` of rays `O + t D` (`Infinity` when none);
 * - `occluded` (§5.1.6.3) and `image_bounds` (the result-identical image-space cull; `null` = no cull);
 * - `classify_curve` / `classify_batch` (§5.1.6.4: midpoint samples, exactly 6 bisection steps);
 * - `drawn_segment_4d` / `drawn_segments_4d` / `clip_polygon_4d` (§5.1.6.4; the rectangle steps decide on the projected
 *   3-vectors, as the M4 implementation note "The 4-D clip decides on the drawn 3-vectors" requires of the port);
 * - `runs_straight` / `runs_conic` (the §5.1.7 run records).
 *
 * Numerics: every expression is written in the operand order of the numpy reference (left-to-right sums, the same
 * `where` selections, `fmin` / `fmax` NaN rules, `np.max` / `np.min` NaN propagation); vectorised numpy code is a loop
 * over rows here, which gives the same per-row floats.
 */

import { nu, project, rect_functionals } from "./camera.js";
import type { CameraRecord } from "./camera.js";
import { conic_point, ellipse_arc_params, sample_arc, sample_count } from "./conics.js";
import { ZERO_REL, clip_segment_halfspace_keep, row_max_abs } from "./homogeneous.js";
import { degrees } from "./transform.js";
import type { Mat3, Vec2, Vec3, Vec4 } from "./types.js";

/** Sampling constants of contract §5.1.6.4 (fixed by the contract; never adapted). */
export const HLR_SPACING_MM = 1.0;
export const HLR_MIN_SAMPLES = 8;
export const HLR_MAX_SAMPLES = 4096;
export const HLR_BISECTIONS = 6;
/** Classification band of the ray parameter (relative to the ray length; contract §5.1.6.3, D26). */
export const HLR_RAY_EPS = 1e-5;

/** Inclusive band (relative to the solid's size) of the "on the finite surface" tests of the exact occluders (height
 * range, disc radius, side-quad extent): a ray through a rim or a side edge is counted by both adjacent pieces. */
const SURFACE_BAND = 1e-9;

const INF = Infinity;

/** `N = min(HLR_MAX_SAMPLES, max(HLR_MIN_SAMPLES, ceil(l / HLR_SPACING_MM − 1e-9)))` (contract §5.1.6.4). */
export function hlr_sample_count(length_mm: number): number {
  return Math.min(HLR_MAX_SAMPLES, Math.max(HLR_MIN_SAMPLES, Math.ceil(length_mm / HLR_SPACING_MM - 1e-9)));
}

/** Stated boundary tolerance `max(1/64, l/262144)` mm of a drawable of image length `l` (§5.1.6.4). */
export function hlr_tol_mm(length_mm: number): number {
  return Math.max(1.0 / 64.0, length_mm / 262144.0);
}

// ---------------------------------------------------------------------------
// small helpers (numpy semantics)
// ---------------------------------------------------------------------------

/** `np.fmin`: the NaN-ignoring minimum. */
function fmin(a: number, b: number): number {
  if (Number.isNaN(a)) return b;
  if (Number.isNaN(b)) return a;
  return a <= b ? a : b;
}

/** `np.fmax`: the NaN-ignoring maximum. */
function fmax(a: number, b: number): number {
  if (Number.isNaN(a)) return b;
  if (Number.isNaN(b)) return a;
  return a >= b ? a : b;
}

function sub3(a: readonly number[], b: readonly number[]): Vec3 {
  return [(a[0] as number) - (b[0] as number), (a[1] as number) - (b[1] as number), (a[2] as number) - (b[2] as number)];
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

function cross3(a: readonly number[], b: readonly number[]): Vec3 {
  const a0 = a[0] as number, a1 = a[1] as number, a2 = a[2] as number;
  const b0 = b[0] as number, b1 = b[1] as number, b2 = b[2] as number;
  return [a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0];
}

/** `v @ R` (row vector times matrix): `out_j = Σ_i v_i R[i][j]`, left to right. */
function vec_mat(v: readonly number[], R: Mat3): Vec3 {
  const x = v[0] as number, y = v[1] as number, z = v[2] as number;
  return [
    x * R[0][0] + y * R[1][0] + z * R[2][0],
    x * R[0][1] + y * R[1][1] + z * R[2][1],
    x * R[0][2] + y * R[1][2] + z * R[2][2],
  ];
}

/** Number of elements `<= x` of the non-decreasing `arr` (`np.searchsorted(arr, x, side="right")`). */
function searchsorted_right(arr: readonly number[], x: number): number {
  let lo = 0, hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((arr[mid] as number) <= x) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

function clamp(i: number, lo: number, hi: number): number {
  return i < lo ? lo : i > hi ? hi : i;
}

// ---------------------------------------------------------------------------
// occluders (contract §5.1.6.2)
// ---------------------------------------------------------------------------

export interface BoxOccluder { kind: "box"; id: string; R: Mat3; origin: Vec3; lo: Vec3; hi: Vec3; band: number; points: Vec3[] }
export interface PrismOccluder { kind: "prism"; id: string; R: Mat3; origin: Vec3; polygon: Vec2[]; height: number; band: number; points: Vec3[] }
export interface RoundOccluder {
  kind: "cylinder" | "cone"; id: string; R: Mat3; origin: Vec3; radius: number; height: number; band: number; points: Vec3[];
}
export interface SphereOccluder { kind: "sphere"; id: string; centre: Vec3; radius: number; points: Vec3[] }
export interface PlateOccluder { kind: "plate"; id: string; n: Vec3; d: number; psi: Vec4[]; points: Vec3[] }
export interface GroundOccluder { kind: "ground"; id: string; n: Vec3; d: number; points: null }
export interface MeshOccluder {
  kind: "mesh"; id: string | null; triangles: [Vec3, Vec3, Vec3][]; faces: Vec3[][]; band: number; points: Vec3[] | null;
}
export type Occluder = BoxOccluder | PrismOccluder | RoundOccluder | SphereOccluder | PlateOccluder | GroundOccluder | MeshOccluder;

/** The eight corners of the axis box `[lo, hi]` in the order of the reference (`x`, then `y`, then `z` outermost first). */
function box_corners(lo: readonly number[], hi: readonly number[]): Vec3[] {
  const out: Vec3[] = [];
  for (const x of [lo[0] as number, hi[0] as number]) {
    for (const y of [lo[1] as number, hi[1] as number]) {
      for (const z of [lo[2] as number, hi[2] as number]) out.push([x, y, z]);
    }
  }
  return out;
}

/** `local @ R.T + origin`. */
function local_to_world(points: readonly Vec3[], R: Mat3, origin: readonly number[]): Vec3[] {
  return points.map((p) => [
    (p[0] * R[0][0] + p[1] * R[0][1] + p[2] * R[0][2]) + (origin[0] as number),
    (p[0] * R[1][0] + p[1] * R[1][1] + p[2] * R[1][2]) + (origin[1] as number),
    (p[0] * R[2][0] + p[1] * R[2][1] + p[2] * R[2][2]) + (origin[2] as number),
  ]);
}

function v3(v: readonly number[]): Vec3 {
  return [v[0] as number, v[1] as number, v[2] as number];
}

/**
 * Occluder of a stage-A object record or a stage-A receiver record (contract §5.1.6.2): the kind's exact data — `box` /
 * `prism` (local frame `R`, `origin` and the shape), `cylinder` / `cone` / `sphere` (the analytic frame), `plate`
 * (`n`, `d`, `psi`), `ground` (the unbounded plane) or `mesh` (generic closed mesh) — plus the hull points of the cull.
 * Never throws for a record of an unknown kind.
 */
export function occluder(rec: any): Occluder {
  if (rec !== null && typeof rec === "object" && "pi" in rec && !("mesh" in rec)) { // a receiver record
    const pi = rec.pi as number[];
    const n: Vec3 = [pi[0] as number, pi[1] as number, pi[2] as number];
    if (rec.bounded) {
      return { kind: "plate", id: rec.id, n, d: pi[3] as number, psi: (rec.psi as number[][]).map((r) => [...r] as Vec4),
        points: (rec.bounds as number[][]).map(v3) };
    }
    return { kind: "ground", id: rec.id, n, d: pi[3] as number, points: null };
  }
  const typ = rec?.type;
  const shape = rec?.shape ?? {};
  const an = rec?.analytic ?? null;
  const frame = rec?.frame ?? null;
  if (typ === "box" && shape.size !== undefined && frame !== null) {
    const [R, pos] = frame as [Mat3, Vec3];
    const [sx, sy, sz] = (shape.size as number[]).map(Number) as [number, number, number];
    return {
      kind: "box", id: rec.id, R, origin: v3(pos), lo: [-sx / 2.0, -sy / 2.0, 0.0], hi: [sx / 2.0, sy / 2.0, sz],
      band: SURFACE_BAND * Math.max(sx, sy, sz), points: (rec.mesh.vertices as number[][]).map(v3),
    };
  }
  if (typ === "prism" && shape.polygon !== undefined && frame !== null) {
    const [R, pos] = frame as [Mat3, Vec3];
    const poly = (shape.polygon as number[][]).map((p) => [p[0] as number, p[1] as number] as Vec2);
    const h = Number(shape.height);
    let m = 0.0;
    for (const p of poly) m = Math.max(m, Math.abs(p[0]), Math.abs(p[1]));
    const ext = Math.max(h, poly.length > 0 ? m : 0.0);
    return {
      kind: "prism", id: rec.id, R, origin: v3(pos), polygon: poly, height: h, band: SURFACE_BAND * Math.max(ext, 1e-300),
      points: (rec.mesh.vertices as number[][]).map(v3),
    };
  }
  if (an !== null && (an.kind === "cylinder" || an.kind === "cone" || an.kind === "sphere")) {
    const e1 = an.e1 as Vec3, e2 = an.e2 as Vec3, ax = an.axis as Vec3;
    const R: Mat3 = [[e1[0], e2[0], ax[0]], [e1[1], e2[1], ax[1]], [e1[2], e2[2], ax[2]]]; // columns: local axes
    const base = v3(an.base);
    const r = Number(an.radius);
    if (an.kind === "sphere") {
      return { kind: "sphere", id: rec.id, centre: v3(an.centre), radius: r,
        points: local_to_world(box_corners([-r, -r, 0.0], [r, r, 2.0 * r]), R, base) };
    }
    const h = Number(an.height);
    return {
      kind: an.kind, id: rec.id, R, origin: base, radius: r, height: h, band: SURFACE_BAND * Math.max(r, h),
      points: local_to_world(box_corners([-r, -r, 0.0], [r, r, h]), R, base),
    };
  }
  return mesh_occluder(rec);
}

/** The generic closed-mesh occluder (contract §5.1.6.2, [decision, synthesis] C8): `rec.triangles` on the welded
 * vertices when the record carries that key (M5 mesh records), otherwise the faces of `rec.mesh` (contract §2.4
 * guarantees `vertices` / `faces`). */
export function mesh_occluder(rec: any): MeshOccluder {
  const mesh = rec?.mesh ?? {};
  const V: Vec3[] = ((mesh.vertices ?? []) as number[][]).map(v3);
  const tris: [Vec3, Vec3, Vec3][] = [];
  const polys: Vec3[][] = [];
  if (rec?.triangles !== undefined && rec?.triangles !== null) {
    for (const t of rec.triangles as number[][]) tris.push([V[t[0] as number] as Vec3, V[t[1] as number] as Vec3, V[t[2] as number] as Vec3]);
  } else {
    for (const f of (mesh.faces ?? []) as number[][]) {
      if (f.length === 3) tris.push([V[f[0] as number] as Vec3, V[f[1] as number] as Vec3, V[f[2] as number] as Vec3]);
      else if (f.length > 3) polys.push(f.map((i) => V[i] as Vec3));
    }
  }
  let ext = 1.0;
  if (V.length > 0) {
    ext = 0.0;
    for (const p of V) ext = Math.max(ext, Math.abs(p[0]), Math.abs(p[1]), Math.abs(p[2]));
  }
  return { kind: "mesh", id: rec?.id ?? null, triangles: tris, faces: polys, band: SURFACE_BAND * Math.max(ext, 1.0),
    points: V.length > 0 ? V : null };
}

/** First crossing `> eps` of a ray with a convex solid met on `[t_in, t_out]` (`Infinity` when none). */
function first_of_interval(t_in: number, t_out: number, eps: number): number {
  if (!(t_in <= t_out)) return INF;
  return t_in > eps ? t_in : t_out > eps ? t_out : INF;
}

/** A candidate crossing kept when finite and `> eps` (`Infinity` otherwise). */
function valid(t: number, eps: number): number {
  return Number.isFinite(t) && t > eps ? t : INF;
}

/** Real roots `[lo, hi]` of `a t² + b t + c` (`NaN` where none; a linear equation gives its single root twice). */
function quadratic_roots(a: number, b: number, c: number): [number, number] {
  const disc = b * b - 4.0 * a * c;
  const sq = disc >= 0.0 ? Math.sqrt(disc) : NaN;
  const q = -0.5 * (b + (b >= 0.0 ? 1.0 : -1.0) * sq);
  let t1 = a !== 0.0 ? q / a : NaN;
  let t2 = q !== 0.0 ? c / q : NaN;
  if (a === 0.0) {
    const tl = b !== 0.0 ? -c / b : NaN;
    t1 = tl;
    t2 = tl;
  }
  return [fmin(t1, t2), fmax(t1, t2)];
}

function first_box(occ: BoxOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const o = vec_mat(sub3(O, occ.origin), occ.R), d = vec_mat(D, occ.R);
  let tn = -INF, tf = INF;
  for (let k = 0; k < 3; k++) {
    const lo = occ.lo[k] as number, hi = occ.hi[k] as number, ok = o[k] as number, dk = d[k] as number;
    let a: number, b: number;
    if (dk === 0.0) {
      const inside = ok >= lo && ok <= hi;
      a = inside ? -INF : INF;
      b = inside ? INF : -INF;
    } else {
      const inv = 1.0 / dk;
      const t0 = (lo - ok) * inv, t1 = (hi - ok) * inv;
      a = fmin(t0, t1);
      b = fmax(t0, t1);
    }
    // np.max / np.min over the three axes propagate NaN, as Math.max / Math.min do
    tn = k === 0 ? a : Math.max(tn, a);
    tf = k === 0 ? b : Math.min(tf, b);
  }
  return first_of_interval(tn, tf, eps);
}

function first_sphere(occ: SphereOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const oc = sub3(O, occ.centre);
  const a = dot3(D, D);
  const b = 2.0 * dot3(D, oc);
  const c = dot3(oc, oc) - occ.radius * occ.radius;
  const [t1, t2] = quadratic_roots(a, b, c);
  if (Number.isNaN(t1)) return INF;
  return first_of_interval(t1, t2, eps);
}

function disc(o: Vec3, d: Vec3, z_plane: number, radius: number, band: number): number {
  const t = d[2] !== 0.0 ? (z_plane - o[2]) / d[2] : NaN;
  const x = o[0] + t * d[0];
  const y = o[1] + t * d[1];
  const rb = radius + band;
  return x * x + y * y <= rb * rb ? t : NaN;
}

function first_cylinder(occ: RoundOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const o = vec_mat(sub3(O, occ.origin), occ.R), d = vec_mat(D, occ.R);
  const r = occ.radius, h = occ.height, band = occ.band;
  const a = d[0] * d[0] + d[1] * d[1];
  const b = 2.0 * (o[0] * d[0] + o[1] * d[1]);
  const c = o[0] * o[0] + o[1] * o[1] - r * r;
  let best = INF;
  for (const t of quadratic_roots(a, b, c)) {
    const z = o[2] + t * d[2];
    best = Math.min(best, valid(z >= -band && z <= h + band ? t : NaN, eps));
  }
  best = Math.min(best, valid(disc(o, d, 0.0, r, band), eps));
  best = Math.min(best, valid(disc(o, d, h, r, band), eps));
  return best;
}

function first_cone(occ: RoundOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const o = vec_mat(sub3(O, occ.origin), occ.R), d = vec_mat(D, occ.R);
  const r = occ.radius, h = occ.height, band = occ.band;
  const k = r / h;
  const hz = h - o[2];
  const a = d[0] * d[0] + d[1] * d[1] - k * k * (d[2] * d[2]);
  const b = 2.0 * (o[0] * d[0] + o[1] * d[1] + k * k * hz * d[2]);
  const c = o[0] * o[0] + o[1] * o[1] - k * k * hz * hz;
  let best = INF;
  for (const t of quadratic_roots(a, b, c)) {
    const z = o[2] + t * d[2];
    best = Math.min(best, valid(z >= -band && z <= h + band ? t : NaN, eps));
  }
  best = Math.min(best, valid(disc(o, d, 0.0, r, band), eps));
  return best;
}

/** Crossing-number point-in-polygon test of `(px, py)` against `poly` (the reference `_even_odd`). */
function even_odd(px: number, py: number, poly: readonly (readonly number[])[]): boolean {
  const k = poly.length;
  let count = 0;
  for (let i = 0; i < k; i++) {
    const p = poly[i] as readonly number[], q = poly[(i + 1) % k] as readonly number[];
    const x0 = p[0] as number, y0 = p[1] as number, x1 = q[0] as number, y1 = q[1] as number;
    const cond = (y0 > py) !== (y1 > py);
    const xint = x0 + (py - y0) * (x1 - x0) / (y1 !== y0 ? y1 - y0 : 1.0);
    if (cond && px < xint) count += 1;
  }
  return (count & 1) === 1;
}

function first_prism(occ: PrismOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const o = vec_mat(sub3(O, occ.origin), occ.R), d = vec_mat(D, occ.R);
  const poly = occ.polygon, h = occ.height, band = occ.band;
  const k = poly.length;
  let best = INF;
  for (let i = 0; i < k; i++) {
    const p0 = poly[i] as Vec2, p1 = poly[(i + 1) % k] as Vec2;
    const e0 = p1[0] - p0[0], e1 = p1[1] - p0[1];
    const ee = e0 * e0 + e1 * e1;
    const n0 = e1, n1 = -e0;                                       // horizontal normal of the side plane
    const denom = d[0] * n0 + d[1] * n1;
    const num = (p0[0] * n0 + p0[1] * n1) - (o[0] * n0 + o[1] * n1);
    const t = denom !== 0.0 ? num / denom : NaN;
    const x = o[0] + t * d[0];
    const y = o[1] + t * d[1];
    const z = o[2] + t * d[2];
    const ee_safe = ee > 0 ? ee : 1.0;
    const s = ((x - p0[0]) * e0 + (y - p0[1]) * e1) / ee_safe;
    const rel = band / Math.sqrt(ee_safe);
    const ok = ee > 0 && z >= -band && z <= h + band && s >= -rel && s <= 1.0 + rel;
    best = Math.min(best, valid(ok ? t : NaN, eps));
  }
  for (const z_plane of [0.0, h]) {
    const tc = d[2] !== 0.0 ? (z_plane - o[2]) / d[2] : NaN;
    if (Number.isFinite(tc) && tc > eps && tc < best && even_odd(o[0] + tc * d[0], o[1] + tc * d[1], poly)) best = tc;
  }
  return best;
}

function first_plane(n: readonly number[], dd: number, O: readonly number[], D: readonly number[]): number {
  const denom = dot3(D, n);
  return denom !== 0.0 ? -(dot3(O, n) + dd) / denom : NaN;
}

function first_plate(occ: PlateOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  const t = first_plane(occ.n, occ.d, O, D);
  const tt = Number.isFinite(t) ? t : 0.0;
  const X = [(O[0] as number) + tt * (D[0] as number), (O[1] as number) + tt * (D[1] as number), (O[2] as number) + tt * (D[2] as number)];
  let inside = true;
  for (const p of occ.psi) if (!((X[0] as number) * p[0] + (X[1] as number) * p[1] + (X[2] as number) * p[2] + p[3] >= 0.0)) inside = false;
  return Number.isFinite(t) && t > eps && inside ? t : INF;
}

function first_ground(occ: GroundOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  return valid(first_plane(occ.n, occ.d, O, D), eps);
}

function first_mesh(occ: MeshOccluder, O: readonly number[], D: readonly number[], eps: number): number {
  let best = INF;
  const band = 1e-12;
  for (const [T0, T1, T2] of occ.triangles) {                     // Möller–Trumbore
    const e1 = sub3(T1, T0), e2 = sub3(T2, T0);
    const p = cross3(D, e2);
    const det = dot3(p, e1);
    const ok = det !== 0.0;
    const inv = 1.0 / (ok ? det : 1.0);
    const s = sub3(O, T0);
    const u = dot3(s, p) * inv;
    const q = cross3(s, e1);
    const v = dot3(D, q) * inv;
    const t = dot3(q, e2) * inv;
    if (ok && u >= -band && v >= -band && u + v <= 1.0 + band && t > eps) best = Math.min(best, t);
  }
  for (const F of occ.faces) {
    const F0 = F[0] as Vec3;
    let nrm = cross3(sub3(F[1] as Vec3, F0), sub3(F[2] as Vec3, F0));
    for (let k = 3; k < F.length; k++) {                           // Newell-like accumulation of the fan
      const c = cross3(sub3(F[k - 1] as Vec3, F0), sub3(F[k] as Vec3, F0));
      nrm = [nrm[0] + c[0], nrm[1] + c[1], nrm[2] + c[2]];
    }
    if (nrm[0] === 0 && nrm[1] === 0 && nrm[2] === 0) continue;
    const t = first_plane(nrm, -dot3(nrm, F0), O, D);
    if (!(Number.isFinite(t) && t > eps && t < best)) continue;
    const X = [(O[0] as number) + t * (D[0] as number), (O[1] as number) + t * (D[1] as number), (O[2] as number) + t * (D[2] as number)];
    let drop = 0;                                                  // np.argmax(|nrm|): the first maximum
    for (let k = 1; k < 3; k++) if (Math.abs(nrm[k] as number) > Math.abs(nrm[drop] as number)) drop = k;
    const keep = [0, 1, 2].filter((i) => i !== drop) as [number, number];
    if (even_odd(X[keep[0]] as number, X[keep[1]] as number, F.map((P) => [P[keep[0]], P[keep[1]]]))) best = t;
  }
  return best;
}

/** Smallest boundary-crossing parameter `t > eps` of the one ray `O + t D` with the occluder (`Infinity` when none). */
export function first_hit_ray(occ: Occluder, O: readonly number[], D: readonly number[], eps: number = HLR_RAY_EPS): number {
  switch (occ.kind) {
    case "box": return first_box(occ, O, D, eps);
    case "prism": return first_prism(occ, O, D, eps);
    case "cylinder": return first_cylinder(occ, O, D, eps);
    case "cone": return first_cone(occ, O, D, eps);
    case "sphere": return first_sphere(occ, O, D, eps);
    case "plate": return first_plate(occ, O, D, eps);
    case "ground": return first_ground(occ, O, D, eps);
    default: return first_mesh(occ, O, D, eps);
  }
}

/**
 * Smallest boundary-crossing parameter `t > eps` of the rays `O + t D` with the occluder (`Infinity` when none;
 * contract §5.1.6.2). `O` is one point (shared by every ray) or one point per ray; `D` one direction per ray.
 */
export function first_hit(occ: Occluder, O: readonly number[] | readonly (readonly number[])[], D: readonly (readonly number[])[],
  eps: number = HLR_RAY_EPS): number[] {
  const per_ray = O.length > 0 && Array.isArray(O[0]);
  return D.map((d, i) => first_hit_ray(occ, (per_ray ? (O as readonly (readonly number[])[])[i] : O) as readonly number[], d, eps));
}

/** Image-space cull data `[u_min, u_max, v_min, v_max, depth_min]` of an occluder's hull points (contract §5.1.6.4), or
 * `null` ("no cull") for the unbounded ground and whenever some hull point has `ν <= 0`. */
export type ImageBounds = [number, number, number, number, number];

export function image_bounds(occ: Occluder, cam: CameraRecord): ImageBounds | null {
  const pts = occ.points;
  if (pts === null || pts.length === 0) return null;
  const X4 = pts.map((p) => [p[0], p[1], p[2], 1.0]);
  if (X4.some((X) => nu(cam, X) <= 0.0)) return null;
  let u0 = INF, u1 = -INF, v0 = INF, v1 = -INF, dmin = INF;
  for (const X of X4) {
    const x = project(cam, X);
    const u = x[0] / x[2], v = x[1] / x[2];
    // np.min / np.max propagate NaN
    u0 = Math.min(u0, u); u1 = Math.max(u1, u); v0 = Math.min(v0, v); v1 = Math.max(v1, v); dmin = Math.min(dmin, x[2]);
  }
  return [u0, u1, v0, v1, dmin];
}

/**
 * Per world point `X`: hidden from the camera centre `C` (contract §5.1.6.3), i.e. some occluder has
 * `first_hit(occ, C, X − C, eps) < 1 − eps`. `bounds` (one `image_bounds` result per occluder, with `cam`) enables the
 * result-identical cull: a ray is skipped only where it provably misses the occluder's hull.
 */
export function occluded(occs: readonly Occluder[], C: readonly number[], X: readonly (readonly number[])[], eps: number = HLR_RAY_EPS,
  cam: CameraRecord | null = null, bounds: readonly (ImageBounds | null)[] | null = null): boolean[] {
  const n = X.length;
  const hidden = new Array<boolean>(n).fill(false);
  if (n === 0 || occs.length === 0) return hidden;
  const use_img = bounds !== null && cam !== null && bounds.some((b) => b !== null);
  const limit = 1.0 - eps;
  for (let i = 0; i < n; i++) {
    const P = X[i] as readonly number[];
    const D = sub3(P, C);
    let u = 0, v = 0, depth = 0;
    if (use_img) {
      const x = project(cam as CameraRecord, [P[0] as number, P[1] as number, P[2] as number, 1.0]);
      u = x[0] / x[2];
      v = x[1] / x[2];
      depth = x[2];
    }
    for (let k = 0; k < occs.length; k++) {
      const b = use_img ? (bounds as readonly (ImageBounds | null)[])[k] ?? null : null;
      if (b !== null) {
        const [bu0, bu1, bv0, bv1, dmin] = b;
        const mu = 1e-6 + 1e-9 * Math.max(Math.abs(bu0), Math.abs(bu1));
        const mv = 1e-6 + 1e-9 * Math.max(Math.abs(bv0), Math.abs(bv1));
        // cull only where the ray provably misses: image point outside the hull's rectangle, or the whole hull at least
        // as deep as X (every hit then has t >= 1); undecidable rows are tested
        const cull = depth > 0.0 && (u < bu0 - mu || u > bu1 + mu || v < bv0 - mv || v > bv1 + mv || dmin >= depth * (1.0 + 1e-9));
        if (cull) continue;
      }
      if (first_hit_ray(occs[k] as Occluder, C, D, eps) < limit) {
        hidden[i] = true;
        break;
      }
    }
  }
  return hidden;
}

/** All occluders of a stage A: every object, every bounded receiver (plate) and the unbounded ground (`receivers[0]`
 * without bounds; no ground receiver -> no ground occluder). */
export function scene_occluders(A: any): Occluder[] {
  const occs: Occluder[] = ((A.objects ?? []) as unknown[]).map((o) => occluder(o));
  for (const rcv of (A.receivers ?? []) as any[]) {
    if (rcv.bounded || (rcv.index ?? 0) === 0) occs.push(occluder(rcv));
  }
  return occs;
}

// ---------------------------------------------------------------------------
// sampling and bisection (contract §5.1.6.4)
// ---------------------------------------------------------------------------

/** A run `[p_a, p_b, visible]` of a classified curve. */
export type Run = [number, number, boolean];
/** `[visibility, runs]`: `runs` is empty unless `visibility === "partial"`. */
export type Classification = [string, Run[]];

/**
 * The deterministic rule of contract §5.1.6.4 for one curve parametrised on `[p0, p1]` with image length `length_mm`:
 * `N = hlr_sample_count(length_mm)` midpoint samples `p_i = p0 + (p1 − p0)(i + ½)/N`; `visible_at(p[]) -> boolean[]`.
 * Each state change between neighbouring samples is bisected exactly `HLR_BISECTIONS` times (keep `[lo, m]` iff
 * `v(m) != v(lo)`); the boundary is the midpoint of the final bracket.
 */
export function classify_curve(visible_at: (p: number[]) => readonly boolean[], p0: number, p1: number, length_mm: number): Classification {
  return classify_batch([p0], [p1], [length_mm], (_sub, p) => visible_at(p))[0] as Classification;
}

/** `classify_curve` for `S` curves at once: `visible_at(subject index[], p[]) -> boolean[]` (the reference
 * `_classify_batch`). Returns one classification per curve. */
export function classify_batch(p0: readonly number[], p1: readonly number[], lengths: readonly number[],
  visible_at: (sub: number[], p: number[]) => readonly boolean[]): Classification[] {
  const S = p0.length;
  if (S === 0) return [];
  const N = lengths.map(hlr_sample_count);
  const offs = [0];
  for (const n of N) offs.push((offs[offs.length - 1] as number) + n);
  const sub: number[] = [], p: number[] = [];
  for (let s = 0; s < S; s++) {
    const a = p0[s] as number, b = p1[s] as number, n = N[s] as number;
    for (let i = 0; i < n; i++) {
      sub.push(s);
      p.push(a + (b - a) * (i + 0.5) / n);
    }
  }
  const v = visible_at(sub, p);
  const trans: number[] = [];
  for (let k = 0; k + 1 < sub.length; k++) if (sub[k] === sub[k + 1] && v[k] !== v[k + 1]) trans.push(k);
  let lo = trans.map((k) => p[k] as number);
  let hi = trans.map((k) => p[k + 1] as number);
  const v_lo = trans.map((k) => v[k] as boolean);
  const tsub = trans.map((k) => sub[k] as number);
  for (let step = 0; step < HLR_BISECTIONS && trans.length > 0; step++) {
    const m = lo.map((a, j) => (a + (hi[j] as number)) / 2.0);
    const vm = visible_at(tsub, m);
    const left = vm.map((x, j) => x !== v_lo[j]);                    // keep [lo, m] iff v(m) != v(lo), else [m, hi]
    hi = hi.map((h, j) => (left[j] ? (m[j] as number) : h));
    lo = lo.map((l, j) => (left[j] ? l : (m[j] as number)));
  }
  const boundary = lo.map((l, j) => (l + (hi[j] as number)) / 2.0);
  const out: Classification[] = [];
  let t = 0;
  for (let s = 0; s < S; s++) {
    const first = v[offs[s] as number] as boolean;
    const last = v[(offs[s + 1] as number) - 1] as boolean;
    const a = t;
    while (t < tsub.length && tsub[t] === s) t++;
    if (a === t) {
      out.push([first ? "visible" : "hidden", []]);
      continue;
    }
    const runs: Run[] = [];
    let start = p0[s] as number;
    for (let k = a; k < t; k++) {
      runs.push([start, boundary[k] as number, v_lo[k] as boolean]);
      start = boundary[k] as number;
    }
    runs.push([start, p1[s] as number, last]);
    out.push(["partial", runs]);
  }
  return out;
}

// ---------------------------------------------------------------------------
// drawn 4-D geometry (contract §5.1.6.4)
// ---------------------------------------------------------------------------

/** One row of the reference `clip_segments_halfspace` (the batched clip): `[a2, b2, keep]`, i.e.
 * `homogeneous.clip_segment_halfspace_keep` (one implementation of the interpolation and the zero-row filter). */
const halfspace_row = clip_segment_halfspace_keep;

/**
 * 4-D endpoints of drawn segments: the near clip of contract §2.2 step 1 (as in stage B), then the four
 * extended-canvas functionals **evaluated on** `P X` with the 4-D points interpolated by the same `(fa, fb)` (the
 * projected 3-vectors are carried and clipped exactly as the 2-D clip of stage B does, so every in/out decision is the
 * drawn segment's own). Returns `[A', B', keep]`; `P A'`, `P B'` equal the drawn endpoints up to one rounding of `P X`.
 * Endpoints may be directions (`w = 0`).
 */
export function drawn_segments_4d(cam: CameraRecord, A4: readonly (readonly number[])[], B4: readonly (readonly number[])[]): [Vec4[], Vec4[], boolean[]] {
  const outA: Vec4[] = [], outB: Vec4[] = [], keep: boolean[] = [];
  const rows = rect_functionals(cam.rect);
  for (let i = 0; i < A4.length; i++) {
    let [A, B, k] = halfspace_row(A4[i] as readonly number[], B4[i] as readonly number[], nu(cam, A4[i] as readonly number[]),
      nu(cam, B4[i] as readonly number[]));
    let xa: number[] = project(cam, A), xb: number[] = project(cam, B);
    for (const row of rows) {
      if (!k) break;                                               // a dropped row stays dropped (values meaningless)
      const fa = dot3(xa, row), fb = dot3(xb, row);
      let k1: boolean;
      [xa, xb, k1] = halfspace_row(xa, xb, fa, fb);
      [A, B] = halfspace_row(A, B, fa, fb);
      k = k && k1;
    }
    outA.push(A as Vec4);
    outB.push(B as Vec4);
    keep.push(k);
  }
  return [outA, outB, keep];
}

/** One segment of `drawn_segments_4d`: `[A', B']` or `null` when nothing is drawn. */
export function drawn_segment_4d(cam: CameraRecord, A4: readonly number[], B4: readonly number[]): [Vec4, Vec4] | null {
  const [A, B, keep] = drawn_segments_4d(cam, [A4], [B4]);
  return keep[0] ? [A[0] as Vec4, B[0] as Vec4] : null;
}

/** One Sutherland–Hodgman step of `homogeneous.clip_polygon_halfspace` (same formulas, same zero-row filter) on `pts`
 * carrying the outgoing-edge provenance: a kept vertex keeps its id, a crossing-out vertex starts a clip edge (`null`),
 * a crossing-in vertex continues the original edge. `extra` (same row count) is interpolated with the same `(fa, fb)`
 * and filtered with the mask of `pts`. */
function clip_step(pts: readonly (readonly number[])[], ids: readonly (number | null)[], vals: readonly number[],
  extra: readonly (readonly number[])[] | null = null): [number[][], (number | null)[], number[][]] {
  const n = pts.length;
  if (n === 0 || vals.every((x) => x >= 0.0)) return [pts.map((p) => [...p]), [...ids], (extra ?? []).map((p) => [...p])];
  if (vals.every((x) => x < 0.0)) return [[], [], []];
  const out: number[][] = [], oid: (number | null)[] = [], ext: number[][] = [];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const a = pts[i] as readonly number[], b = pts[j] as readonly number[];
    const fa = vals[i] as number, fb = vals[j] as number;
    const a_in = fa >= 0.0, b_in = fb >= 0.0;
    if (a_in) {
      out.push([...a]);
      oid.push(ids[i] as number | null);
      if (extra !== null) ext.push([...(extra[i] as readonly number[])]);
    }
    if (a_in !== b_in) {
      out.push(a.map((ak, k) => (fa * (b[k] as number) - fb * ak) / (fa - fb)));
      oid.push(a_in ? null : (ids[i] as number | null));
      if (extra !== null) {
        const ea = extra[i] as readonly number[], eb = extra[j] as readonly number[];
        ext.push(ea.map((x, k) => (fa * (eb[k] as number) - fb * x) / (fa - fb)));
      }
    }
  }
  // the scale is np.max(np.abs(pts)) (NaN-propagating, as clip_polygon_halfspace)
  let scale = 0;
  for (const p of pts) {
    const m = row_max_abs(p);
    if (m > scale || Number.isNaN(m)) scale = m;
  }
  const keep = out.map((p) => row_max_abs(p) > ZERO_REL * scale);
  return [out.filter((_p, k) => keep[k]), oid.filter((_x, k) => keep[k]), extra === null ? [] : ext.filter((_p, k) => keep[k])];
}

/**
 * The 4-D path of a shadow polygon through the drawing pipeline (contract §5.1.6.4): near clip, then the four
 * rectangle functionals evaluated on `P X`, each a Sutherland–Hodgman step with provenance (decided on the projected
 * 3-vectors exactly as the drawn polygon is). Returns `[points, ids]` where `ids[j]` is the index of the original
 * polygon edge on which the drawn edge `j -> j + 1` lies, or `null` for an edge created by a clip; empty when fewer than
 * three vertices survive any step (as the drawn polygon).
 */
export function clip_polygon_4d(cam: CameraRecord, V4: readonly (readonly number[])[]): [Vec4[], (number | null)[]] {
  if (V4.length < 3) return [[], []];
  let [pts, ids] = clip_step(V4, V4.map((_v, i) => i), V4.map((v) => nu(cam, v)));
  if (pts.length < 3) return [[], []];
  let X: number[][] = pts.map((p) => project(cam, p));
  for (const row of rect_functionals(cam.rect)) {
    [X, ids, pts] = clip_step(X, ids, X.map((x) => dot3(x, row)), pts);
    if (pts.length < 3) return [[], []];
  }
  return [pts as Vec4[], ids];
}

// ---------------------------------------------------------------------------
// run records (contract §5.1.7)
// ---------------------------------------------------------------------------

/** 4-D segment parameter of the image fraction `s`: `t = s a3 / ((1 − s) b3 + s a3)`. */
function t_of_s(s: number, a3: number, b3: number): number {
  return s * a3 / ((1.0 - s) * b3 + s * a3);
}

export interface StraightRun { s: [number, number]; t: [number, number]; mm: [number, number]; visible: boolean }
export interface ConicRun { interval: number; theta: [number, number]; mm: [number, number]; visible: boolean }

/** Document form of a straight drawable's classification: `[visibility, [{s, t, mm, visible}, ...]]` (`mm` measured
 * from the drawn segment's start). */
export function runs_straight(result: Classification, a3: number, b3: number, length_mm: number): [string, StraightRun[]] {
  const [visibility, runs] = result;
  const out = runs.map(([s0, s1, vis]): StraightRun => {
    const t0 = s0 === 0.0 ? 0.0 : s0 === 1.0 ? 1.0 : t_of_s(s0, a3, b3);
    const t1 = s1 === 0.0 ? 0.0 : s1 === 1.0 ? 1.0 : t_of_s(s1, a3, b3);
    return { s: [s0 + 0, s1 + 0], t: [t0 + 0, t1 + 0], mm: [s0 * length_mm + 0, (s1 === 1.0 ? length_mm : s1 * length_mm) + 0], visible: vis };
  });
  return [visibility, out];
}

/** Piecewise-linear map polyline length -> circle parameter (contract §5.1.6.4). */
function theta_of_m(m: number, cum: readonly number[], th: readonly number[]): number {
  const n = cum.length - 1;
  const j = clamp(searchsorted_right(cum, m) - 1, 0, n - 1);
  const seg = (cum[j + 1] as number) - (cum[j] as number);
  const frac = seg > 0.0 ? (m - (cum[j] as number)) / seg : 0.0;
  return (th[j] as number) + frac * ((th[j + 1] as number) - (th[j] as number));
}

/** Document run records `{interval, theta, mm, visible}` of one visible interval's classification (`runs` =
 * `[m0, m1, visible][]`; the interval's own endpoints map to its exact `theta` ends `lo` / `hi`, default the first /
 * last polyline node). */
export function runs_conic(interval: number, runs: readonly Run[], cum: readonly number[], th: readonly number[],
  lo: number | null = null, hi: number | null = null): ConicRun[] {
  const length = cum[cum.length - 1] as number;
  const a_end = lo === null ? (th[0] as number) : lo;
  const b_end = hi === null ? (th[th.length - 1] as number) : hi;
  return runs.map(([m0, m1, vis]) => {
    const a = m0 === 0.0 ? a_end : m0 === length ? b_end : theta_of_m(m0, cum, th);
    const b = m1 === 0.0 ? a_end : m1 === length ? b_end : theta_of_m(m1, cum, th);
    return { interval, theta: [a + 0, b + 0], mm: [m0 + 0, m1 + 0], visible: vis };
  });
}

/** The piece `[m0, m1]` of a polyline (cut at the boundary points, never resampled). */
function cut_polyline(uv: readonly Vec2[], cum: readonly number[], m0: number, m1: number): Vec2[] {
  const at = (m: number): Vec2 => {
    if (m <= (cum[0] as number)) return uv[0] as Vec2;
    if (m >= (cum[cum.length - 1] as number)) return uv[uv.length - 1] as Vec2;
    const j = clamp(searchsorted_right(cum, m) - 1, 0, cum.length - 2);
    const seg = (cum[j + 1] as number) - (cum[j] as number);
    const f = seg > 0.0 ? (m - (cum[j] as number)) / seg : 0.0;
    const a = uv[j] as Vec2, b = uv[j + 1] as Vec2;
    return [a[0] + f * (b[0] - a[0]), a[1] + f * (b[1] - a[1])];
  };
  const pts: Vec2[] = [at(m0)];
  cum.forEach((c, i) => {
    if (c > m0 && c < m1) pts.push(uv[i] as Vec2);
  });
  pts.push(at(m1));
  return pts.map((p) => [p[0] + 0, p[1] + 0]);
}

// ---------------------------------------------------------------------------
// the document (contract §5.1.6.5)
// ---------------------------------------------------------------------------

type Sink = (res: Classification) => void;

interface LineSubject { A4: Vec4; B4: Vec4; a3: number; b3: number; length: number; sink: (res: [string, StraightRun[]]) => void }
interface ConicSubject { TE: number[][]; rho: number; cum: number[]; th: number[]; length: number; sink: Sink }

/** Accumulator of the subject drawables of one document: straight ones (4-D drawn endpoints) and conic intervals
 * (polyline tables), classified together by `classify_batch`. */
class Subjects {
  readonly lines: LineSubject[] = [];
  readonly conics: ConicSubject[] = [];

  add_line(s: LineSubject): void {
    this.lines.push(s);
  }

  add_conic(TE: number[][], rho: number, cum: number[], th: number[], sink: Sink): void {
    this.conics.push({ TE, rho, cum, th, length: cum[cum.length - 1] as number, sink });
  }

  classify(occs: readonly Occluder[], C: readonly number[], cam: CameraRecord, bounds: readonly (ImageBounds | null)[] | null): void {
    const nl = this.lines.length, nc = this.conics.length;
    if (nl + nc === 0) return;
    const lines = this.lines, conics = this.conics;
    const p1 = [...lines.map(() => 1.0), ...conics.map((c) => c.length)];
    const lengths = [...lines.map((l) => l.length), ...conics.map((c) => c.length)];
    const world = (s: number, p: number): number[] => {
      if (s < nl) {
        const L = lines[s] as LineSubject;
        const t = t_of_s(p, L.a3, L.b3);
        const X4 = L.A4.map((a, k) => (1.0 - t) * a + t * (L.B4[k] as number));
        return [(X4[0] as number) / (X4[3] as number), (X4[1] as number) / (X4[3] as number), (X4[2] as number) / (X4[3] as number)];
      }
      const c = conics[s - nl] as ConicSubject;
      const X4 = conic_point(c.TE, theta_of_m(p, c.cum, c.th), c.rho);
      return [(X4[0] as number) / (X4[3] as number), (X4[1] as number) / (X4[3] as number), (X4[2] as number) / (X4[3] as number)];
    };
    const visible_at = (sub: number[], p: number[]): boolean[] =>
      occluded(occs, C, sub.map((s, i) => world(s, p[i] as number)), HLR_RAY_EPS, cam, bounds).map((h) => !h);
    const results = classify_batch(p1.map(() => 0.0), p1, lengths, visible_at);
    results.forEach((res, k) => {
      if (k < nl) {
        const L = lines[k] as LineSubject;
        L.sink(runs_straight(res, L.a3, L.b3, L.length));
      } else {
        (conics[k - nl] as ConicSubject).sink(res);
      }
    });
  }
}

/** Register a straight drawable (4-D drawn endpoints `A4`, `B4`; drawn segment `seg` in mm). */
function line_subject(subjects: Subjects, cam: CameraRecord, A4: Vec4, B4: Vec4, seg: readonly (readonly number[])[],
  sink: (res: [string, StraightRun[]]) => void): void {
  const xa = project(cam, A4), xb = project(cam, B4);
  const s0 = seg[0] as readonly number[], s1 = seg[1] as readonly number[];
  const du = (s1[0] as number) - (s0[0] as number);
  const dv = (s1[1] as number) - (s0[1] as number);
  const length = Math.sqrt(du * du + dv * dv);
  subjects.add_line({ A4, B4, a3: xa[2], b3: xb[2], length, sink });
}

function world4(points: Record<string, any>, name: string): Vec4 {
  const w = points[name].world as number[];
  return [w[0] as number, w[1] as number, w[2] as number, 1.0];
}

type Table = [Vec2[], number[], number[], number, number]; // (uv, cum, th, lo, hi)

/** Collects the per-interval classifications of one conic entry and writes the entry (§5.1.7). */
class ConicResult {
  readonly results: (Classification | null)[];

  constructor(readonly entry: Record<string, any>, readonly a: any, readonly tables: Table[]) {
    this.results = tables.map(() => null);
  }

  sink(k: number): Sink {
    return (res) => {
      this.results[k] = res;
      if (this.results.every((r) => r !== null)) this.write();
    };
  }

  write(): void {
    const entry = this.entry, a = this.a;
    const results = this.results as Classification[];
    const states: boolean[] = [];
    for (const [vis, runs] of results) {
      if (vis === "partial") states.push(...runs.map((r) => r[2]));
      else states.push(vis === "visible");
    }
    if (states.every((x) => x)) {
      entry["visibility"] = "visible";
      entry["runs"] = [];
      entry["hidden_polylines"] = [];
      return;
    }
    const H = a.H as number[][], rho = a.rho as number;
    const healthy = a.kind === "ellipse" && !a.sampled;
    const visibility = !states.some((x) => x) ? "hidden" : "partial";
    const runs: ConicRun[] = [], hidden_pl: Vec2[][] = [], polylines: Vec2[][] = [], arcs: Record<string, unknown>[] = [];
    results.forEach(([vis, rr], k) => {
      const [uv, cum, th, lo, hi] = this.tables[k] as Table;
      const length = cum[cum.length - 1] as number;
      const pieces: Run[] = vis === "partial" ? rr : [[0.0, length, vis === "visible"]];
      if (visibility === "partial") runs.push(...runs_conic(k, pieces, cum, th, lo, hi));
      for (const [m0, m1, v] of pieces) {
        if (!v) {
          hidden_pl.push(cut_polyline(uv, cum, m0, m1));
          continue;
        }
        const ta = m0 === 0.0 ? lo : theta_of_m(m0, cum, th);
        const tb = m1 === length ? hi : theta_of_m(m1, cum, th);
        const p = healthy ? ellipse_arc_params(H, rho, ta, tb) : null;
        if (p !== null) {
          arcs.push({
            start: [p.start[0] + 0, p.start[1] + 0], end: [p.end[0] + 0, p.end[1] + 0], rx: p.axes[0] + 0, ry: p.axes[1] + 0,
            rotation_deg: degrees(p.rotation) + 0, large_arc: p.large_arc, sweep: p.sweep, theta: [ta + 0, tb + 0],
          });
        } else {
          polylines.push(cut_polyline(uv, cum, m0, m1));
        }
      }
    });
    entry["visibility"] = visibility;
    entry["runs"] = runs;
    entry["hidden_polylines"] = hidden_pl;
    entry["polylines"] = polylines;
    entry["arcs"] = arcs;
    entry["ellipses"] = [];
  }
}

/** Register every visible interval of a conic entry (its §2.6 polyline is the parametrisation; the polyline is
 * recomputed with the `arc_drawables` call, M4 implementation note "Conic polylines are recomputed"). */
function conic_subject(subjects: Subjects, entry: Record<string, any>, a: any): void {
  const visible = (a.visible ?? []) as [number, number][];
  if (visible.length === 0 || a.TE === undefined || a.TE === null) return;
  const H = a.H as number[][], rho = a.rho as number;
  const tables: Table[] = [];
  for (const [lo, hi] of visible) {
    const n = sample_count(lo, hi);
    const pts = sample_arc(H, rho, lo, hi, n);                     // the arc_drawables samples
    const uv: Vec2[] = pts.map((x) => [(x[0] as number) / (x[2] as number) + 0, (x[1] as number) / (x[2] as number) + 0]);
    const cum = [0.0];
    for (let i = 1; i < uv.length; i++) {
      const dx = (uv[i] as Vec2)[0] - (uv[i - 1] as Vec2)[0], dy = (uv[i] as Vec2)[1] - (uv[i - 1] as Vec2)[1];
      cum.push((cum[i - 1] as number) + Math.sqrt(dx * dx + dy * dy));
    }
    const m = Math.max(1, Math.trunc(n));
    const th: number[] = [];
    for (let i = 0; i <= n; i++) th.push(lo + (hi - lo) * i / m);
    tables.push([uv, cum, th, lo, hi]);
  }
  const res = new ConicResult(entry, a, tables);
  tables.forEach(([, cum, th], k) => subjects.add_conic(a.TE, rho, cum, th, res.sink(k)));
}

function set_runs(target: Record<string, any>): (res: [string, StraightRun[]]) => void {
  return ([visibility, runs]) => {
    target["visibility"] = visibility;
    target["runs"] = runs;
  };
}

type Pair = ["generator" | "conic" | "terminator_segment", Record<string, any>, any];

/** Pair the document's curved drawables with their stage-B records (same order as `compose`). */
function curved_pairs(doc: any, B: any): Pair[] {
  const out: Pair[] = [];
  const curved = ((B.objects ?? []) as any[]).filter((rec) => rec.analytic);
  const outlines = (doc.outlines ?? []) as any[];
  curved.forEach((rec, i) => {
    const o = outlines[i];
    if (o === undefined) return;
    const gens = (o.generators ?? []) as any[], gb = (rec.gen_edges ?? []) as any[];
    for (let k = 0; k < Math.min(gens.length, gb.length); k++) out.push(["generator", gens[k], gb[k]]);
    const cs = (o.conics ?? []) as any[], cb = (rec.outline_arcs ?? []) as any[];
    for (let k = 0; k < Math.min(cs.length, cb.length); k++) out.push(["conic", cs[k], cb[k]]);
  });
  // M6 (contract §5.3.3): a multi-light document has one entry per (light, curved object), keyed by its `light`; a
  // single-light entry has no `light` key (key null)
  const term_key = (oid: string, lid: string | null): string => JSON.stringify([oid, lid]);
  const terms = new Map<string, any>();
  for (const entry of (doc.form_shadow ?? []) as any[]) {
    const key = term_key(entry.object, entry.light ?? null);
    if (entry.terminator && entry.terminator.length > 0 && !terms.has(key)) terms.set(key, entry);
  }
  const multi = "constructions" in doc;
  for (const rec of curved) {
    const tmap: Map<string, any[]> = rec.terminator ?? new Map();
    const pairs: [any, any[]][] = multi
      ? [...tmap].map(([lid, its]) => [terms.get(term_key(rec.id, lid)), its])
      : [[terms.get(term_key(rec.id, null)), [...tmap.values()].flat()]];
    for (const [entry, items] of pairs) {
      if (entry === undefined) continue;
      const ts = entry.terminator as any[];
      for (let k = 0; k < Math.min(ts.length, items.length); k++) {
        out.push(["segment" in items[k] ? "terminator_segment" : "conic", ts[k], items[k]]);
      }
    }
  }
  const by_id = new Map<string, any>(curved.map((rec) => [rec.id, rec]));
  for (const sh of (doc.shadows ?? []) as any[]) {
    const rec = by_id.get(sh.object);
    if (rec === undefined || !sh.conics || sh.conics.length === 0) continue;
    const arcs = (rec.shadow_arcs?.get(JSON.stringify([sh.light, sh.receiver])) ?? []) as any[];
    for (let k = 0; k < Math.min(sh.conics.length, arcs.length); k++) out.push(["conic", sh.conics[k], arcs[k]]);
  }
  return out;
}

/**
 * Sampled hidden-line removal of a composed document (contract §5.1.6.5). `A` is the camera-free stage A (occluders),
 * `B` the stage B the document was composed from (`B.camera`, the curved drawable records). Fills `visibility` /
 * `runs` of `edges[]`, `outlines[].generators[]` and `form_shadow[].terminator[]` segment entries, conic `visibility` /
 * `runs` / `hidden_polylines` (drawables restricted to the visible runs) and `shadows[].polygon_edges`. `cull` toggles
 * the result-identical image-space cull (a test compares both). Returns `doc`.
 */
export function classify_document<D>(doc: D, A: any, B: any, cull = true): D {
  const d = doc as any;
  const cam = B.camera as CameraRecord;
  const C = [...cam.C];
  const occs = scene_occluders(A);
  const bounds = cull ? occs.map((o) => image_bounds(o, cam)) : null;
  const points = (d.points ?? {}) as Record<string, any>;
  const subjects = new Subjects();

  // edges[] (objects and receiver bounds edges): fresh objects
  const edges = ((d.edges ?? []) as any[]).map((e) => ({ ...e }));
  d.edges = edges;
  for (const e of edges) {
    e.visibility = "visible";
    e.runs = [];
  }
  const drawn = edges.filter((e) => e.segment !== null && e.segment !== undefined);
  if (drawn.length > 0) {
    const [Ad, Bd, keep] = drawn_segments_4d(cam, drawn.map((e) => world4(points, e.from)), drawn.map((e) => world4(points, e.to)));
    drawn.forEach((e, i) => {
      if (keep[i]) line_subject(subjects, cam, Ad[i] as Vec4, Bd[i] as Vec4, e.segment, set_runs(e));
    });
  }

  // curved drawables: outline generators / cap conics, terminator, cast-shadow conics
  const gens: [Record<string, any>, Vec4, Vec4, readonly (readonly number[])[]][] = [];
  for (const [kind, d_entry, b_rec] of curved_pairs(d, B)) {
    if (kind === "conic") {
      conic_subject(subjects, d_entry, b_rec);
    } else if (kind === "generator") {
      d_entry["visibility"] = "visible";
      d_entry["runs"] = [];
      if (d_entry["segment"] !== null && d_entry["segment"] !== undefined) {
        gens.push([d_entry, world4(points, d_entry["from"]), world4(points, d_entry["to"]), d_entry["segment"]]);
      }
    } else {
      d_entry["visibility"] = "visible";
      d_entry["runs"] = [];
      const pl = d_entry["polylines"] as any[] | undefined;
      if (pl && pl.length > 0 && b_rec.X4 !== undefined) {
        const [A4s, B4s] = b_rec.X4 as [number[], number[]];
        gens.push([d_entry, [...A4s] as Vec4, [...B4s] as Vec4, pl[0]]);
      }
    }
  }
  if (gens.length > 0) {
    const [Ad, Bd, keep] = drawn_segments_4d(cam, gens.map((g) => g[1]), gens.map((g) => g[2]));
    gens.forEach(([d_entry, , , seg], i) => {
      if (keep[i]) line_subject(subjects, cam, Ad[i] as Vec4, Bd[i] as Vec4, seg, set_runs(d_entry));
    });
  }

  // shadows[].polygon_edges: one run record per drawn polygon edge, parallel to polygons
  const a_shadows = (A.shadows ?? []) as any[];
  const shadows = (d.shadows ?? []) as any[];
  for (let i = 0; i < Math.min(shadows.length, a_shadows.length); i++) {
    const sh = shadows[i], a_sh = a_shadows[i];
    const per_poly: Record<string, unknown>[][] = [];
    const loops = (a_sh.loops ?? []) as any[];
    ((sh.polygons ?? []) as Vec2[][]).forEach((poly, j) => {
      if (poly.length < 3) {
        per_poly.push([]);
        return;
      }
      const recs: Record<string, any>[] = poly.map(() => ({ visibility: "visible", runs: [] }));
      per_poly.push(recs);
      if (j >= loops.length) return;
      const [pts4, ids] = clip_polygon_4d(cam, loops[j].vertices);
      if (pts4.length !== poly.length) return;                     // unreachable: the rectangle steps run on the drawn
      const n = poly.length;                                       // polygon's own 3-vectors (defensive: never throw)
      for (let e = 0; e < n; e++) {
        const f = (e + 1) % n;
        if (ids[e] === null || ((pts4[e] as Vec4)[3] === 0.0 && (pts4[f] as Vec4)[3] === 0.0)) continue;
        line_subject(subjects, cam, pts4[e] as Vec4, pts4[f] as Vec4, [poly[e] as Vec2, poly[f] as Vec2], set_runs(recs[e] as Record<string, any>));
      }
    });
    sh.polygon_edges = per_poly;
  }

  subjects.classify(occs, C, cam, bounds);
  return doc;
}

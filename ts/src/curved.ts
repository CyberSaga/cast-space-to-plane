/**
 * Curved primitives: silhouettes, terminators and conic cast shadows (port of `castplane/curved.py`; spec §5.6;
 * contract §2.6, §2.7, §2.10).
 *
 * Pure functions of the `analytic` record of `primitives.build_object` and of a homogeneous 4-vector `L` (the light
 * or the camera position `(C, 1)`). Every entry point canonicalises `L` (`canonical_light`). Stage A per curved
 * object is `stage_a_object` (stored on the object record as `obj.curved.get(<light id>)`), stage B is
 * `stage_b_object` / `stage_b_objects` (the latter loops `stage_b_object`, contract §5.4.4 (6)).
 */

import { clip_segment_near, clip_segment_rect_h, nu, project, rect_functionals } from "./camera.js";
import type { CameraRecord } from "./camera.js";
import {
  TWO_PI, circle_embedding, circle_frame, circle_record, conic_entry, conic_point, functional_coeffs, matmul,
  sample_count, sub_arcs_where_nonnegative,
} from "./conics.js";
import type { Circle, ConicEntry } from "./conics.js";
import { make_warning } from "./errors.js";
import type { Warning } from "./errors.js";
import { TOL_DIR } from "./homogeneous.js";
import { lit } from "./light.js";
import type { Analytic, ObjectRecord } from "./primitives.js";
import { py_round, pyimod, pymod } from "./pyfloat.js";
import { ARC_STEP_DEG, foot, mat4_vec, shadow_w } from "./shadow.js";
import { radians } from "./transform.js";
import type { Mat4, Mat43, Vec2, Vec3, Vec4 } from "./types.js";

// ---------------------------------------------------------------------------
// types
// ---------------------------------------------------------------------------

export interface ArcRef {
  circle: Circle;
  theta0: number;
  theta1: number;
  which: string;
}

export interface Generator {
  theta: number;
  base: Vec3;
  top: Vec3;
}

export interface SegmentRef {
  from: Vec3;
  to: Vec3;
  theta: number | null;
  ends: [string, string];
  which: string;
  gen: number | null;
}

export type LoopPiece = { arc: ArcRef; segment?: undefined } | { segment: SegmentRef; arc?: undefined };

export interface Silhouette {
  kind: string;
  lit_interval: [number, number] | "all" | null;
  theta_l: number | null;
  alpha: number | null;
  generators: Generator[];
  arcs: ArcRef[];
  cap_lit: { base: boolean; top: boolean };
  loop: LoopPiece[];
  circle: Circle | null;
  cap_circles: { base?: Circle; top?: Circle };
  apex?: Vec3;
  light_inside: boolean;
  warnings: Warning[];
}

export type TerminatorItem =
  | { segment: [Vec4, Vec4]; which: string; theta: number | null; circle_arc?: undefined }
  | { circle_arc: ArcRef & { full: boolean }; segment?: undefined };

/** A 4-D loop piece (`loop_pieces_4d`) with the clip bookkeeping of `clip_piece`. */
interface Arc4 {
  E: Mat43;
  rho: number;
  theta0: number;
  theta1: number;
  circle: Circle;
  which: string;
}

interface Piece4 {
  segment?: [number[], number[]];
  arc?: Arc4;
  which?: string;
  theta?: number | null;
  ends?: [string, string] | null;
  gen?: number | null;
  cut_start?: boolean;
  cut_end?: boolean;
  cut_now?: [boolean, boolean];
  zero_start?: number[] | null;
  zero_end?: number[] | null;
}

type Item = Piece4 | { gap: [number[], number[]] };

export interface ConicArcPiece {
  E: Mat43;
  rho: number;
  T: Mat4;
  theta0: number;
  theta1: number;
  circle: Circle;
  which: string;
  cut: [boolean, boolean];
}

export type OutlinePiece =
  | { segment: [Vec4, Vec4]; which: string; theta: number | null; ends: [string, string] | null; gen: number | null; cut: [boolean, boolean] }
  | { conic_arc: ConicArcPiece }
  | { direction: Vec4; role: "out" | "in" };

export interface Outline {
  pieces: OutlinePiece[];
  unbounded: boolean;
  below_ground: boolean;
  empty: boolean;
  silhouette: Silhouette;
  warnings: Warning[];
}

export type PolySource =
  | { kind: "segment"; i: number; end: number }
  | { kind: "arc"; i: number; k: number }
  | { kind: "dir"; i: number; role: string }
  | { kind: "inf"; i: number; s: number };

export interface ShadowPolygon {
  vertices: Vec4[];
  unbounded: boolean;
  sources: PolySource[];
}

export interface CurvedData {
  silhouette: Silhouette;
  terminator: TerminatorItem[];
  points: Map<string, Vec4>;
  outline: Outline | null;
  polygon: ShadowPolygon | null;
}

export type LoopEntry = string | { direction: Vec3 };

export interface ShadowRecord {
  light: string;
  receiver: string;
  object: string;
  kind?: string;
  keep: boolean[];
  P_world: Vec3[];
  S_world: Vec3[];
  Q_world: Vec3[];
  w_S: number[];
  shadow_names: string[];
  foot_names: string[];
  vertex_names: string[];
  ground_points: [string, Vec3][];
  loops: { vertices: Vec4[]; sources: unknown[]; entries: LoopEntry[]; unbounded: boolean }[];
  unbounded: boolean;
  pieces?: OutlinePiece[];
}

export interface LightRecordLike {
  id: string;
  L: Vec4;
  M: Mat4;
  active: boolean;
  tol_lit: number;
  tol_w: number;
}

// ---------------------------------------------------------------------------
// small helpers
// ---------------------------------------------------------------------------

function v3(v: readonly number[]): Vec3 {
  return [v[0] as number, v[1] as number, v[2] as number];
}

function point4(p: readonly number[]): Vec4 {
  return [p[0] as number, p[1] as number, p[2] as number, 1.0];
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

function dot4(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number)
    + (a[2] as number) * (b[2] as number) + (a[3] as number) * (b[3] as number);
}

function norm3(v: readonly number[]): number {
  return Math.sqrt(dot3(v, v));
}

function add3(a: readonly number[], b: readonly number[]): Vec3 {
  return [(a[0] as number) + (b[0] as number), (a[1] as number) + (b[1] as number), (a[2] as number) + (b[2] as number)];
}

function sub3(a: readonly number[], b: readonly number[]): Vec3 {
  return [(a[0] as number) - (b[0] as number), (a[1] as number) - (b[1] as number), (a[2] as number) - (b[2] as number)];
}

function scale3(s: number, a: readonly number[]): Vec3 {
  return [s * (a[0] as number), s * (a[1] as number), s * (a[2] as number)];
}

function scale_n(s: number, a: readonly number[]): number[] {
  return a.map((x) => s * x);
}

/** Outward radial unit vector `u_θ = cos θ e1 + sin θ e2`. */
function u_theta(e1: Vec3, e2: Vec3, theta: number): Vec3 {
  const c = Math.cos(theta), s = Math.sin(theta);
  return [c * e1[0] + s * e2[0], c * e1[1] + s * e2[1], c * e1[2] + s * e2[2]];
}

/** The scalar `s` with `L / s` canonical: `w` for a finite point, `|l|` for a direction, `1` for zero. */
export function canonical_factor(L: readonly number[]): number {
  const w = L[3] as number;
  if (w !== 0.0) return w;
  const norm = norm3(L);
  if (norm > 0.0 && Number.isFinite(norm)) return norm;
  return 1.0;
}

/** Canonical representative of a homogeneous light / camera vector (contract §2.1, spec §7.1 row 5). */
export function canonical_light(L: readonly number[]): Vec4 {
  const f = canonical_factor(L);
  return [(L[0] as number) / f, (L[1] as number) / f, (L[2] as number) / f, (L[3] as number) / f];
}

const INSIDE_MESSAGE = (kind: string): string => `point light is inside the ${kind}; no shadow or terminator`;

function empty_result(kind: string): Silhouette {
  return {
    kind, lit_interval: null, theta_l: null, alpha: null, generators: [], arcs: [], cap_lit: { base: false, top: false },
    loop: [], circle: null, cap_circles: {}, light_inside: false, warnings: [],
  };
}

function arc_piece(circle: Circle, theta0: number, theta1: number, which: string): { arc: ArcRef } {
  return { arc: { circle, theta0, theta1, which } };
}

function segment_piece(a: readonly number[], b: readonly number[], theta: number | null, ends: [string, string],
  which = "generator", gen: number | null = null): { segment: SegmentRef } {
  return { segment: { from: v3(a), to: v3(b), theta, ends, which, gen } };
}

function ccw_range(theta0: number, theta1: number): [number, number] {
  return theta1 >= theta0 ? [theta0, theta1] : [theta1, theta0];
}

// ---------------------------------------------------------------------------
// silhouettes (contract §2.6)
// ---------------------------------------------------------------------------

function sphere_silhouette(an: Analytic, L: Vec4, tol: number): Silhouette {
  const res = empty_result("sphere");
  const c = an.centre;
  const r = an.radius;
  const w = L[3];
  const v = sub3(L, scale3(w, c));
  const dist = norm3(v);
  let centre: Vec3, radius: number;
  if (w !== 0.0) {
    if (dist - r <= tol) {
      res.light_inside = true;
      res.warnings.push(make_warning("LIGHT_INSIDE_OBJECT", [], INSIDE_MESSAGE("sphere")));
      return res;
    }
    const k = r * r / (dist * dist);
    centre = add3(c, scale3(k, v));
    radius = r * Math.sqrt(Math.max(0.0, 1.0 - k));
  } else {
    if (dist <= tol) return res;
    centre = [...c];
    radius = r;
  }
  const n: Vec3 = [v[0] / dist, v[1] / dist, v[2] / dist];
  const [e1, e2] = circle_frame(n, 1e-9, [an.e1, an.e2]);
  const circle = circle_record(centre, e1, e2, radius);
  circle.normal = n;
  res.circle = circle;
  res.lit_interval = "all";
  const arc = arc_piece(circle, 0.0, TWO_PI, "silhouette");
  res.arcs = [{ ...arc.arc }];
  res.loop = [arc];
  return res;
}

function axis_setup(an: Analytic, L: Vec4, origin: Vec3) {
  const a = an.axis, e1 = an.e1, e2 = an.e2;
  const w = L[3];
  const q = sub3(L, scale3(w, origin));
  const qa = dot3(q, a);
  const q_perp = sub3(q, scale3(qa, a));
  const d = norm3(q_perp);
  const theta_l = Math.atan2(dot3(q_perp, e2), dot3(q_perp, e1));
  return { a, e1, e2, q, qa, q_perp, d, theta_l };
}

function neg3(a: Vec3): Vec3 {
  return [-a[0], -a[1], -a[2]];
}

function cylinder_silhouette(an: Analytic, L: Vec4, tol: number): Silhouette {
  const res = empty_result("cylinder");
  const b = an.base;
  const r = an.radius;
  const h = an.height as number;
  const { a, e1, e2, d, theta_l } = axis_setup(an, L, b);
  const w = L[3];
  const top_c = add3(b, scale3(h, a));
  const cap_base = lit(neg3(a), b, L, tol);
  const cap_top = lit(a, top_c, L, tol);
  res.cap_lit = { base: cap_base, top: cap_top };
  const base_circle = circle_record(b, e1, e2, r);
  const top_circle = circle_record(top_c, e1, e2, r);
  res.cap_circles = { base: base_circle, top: top_circle };
  res.theta_l = theta_l;
  let alpha: number | null;
  if (w !== 0.0) alpha = d <= r + tol ? null : Math.acos(Math.min(1.0, r / d));
  else alpha = d <= tol ? null : 0.5 * Math.PI;
  if (alpha === null) {
    if (cap_top) {
      const arc = arc_piece(top_circle, 0.0, TWO_PI, "top");
      res.arcs = [{ ...arc.arc }];
      res.loop = [arc];
    } else if (cap_base) {
      const arc = arc_piece(base_circle, TWO_PI, 0.0, "base");
      res.arcs = [{ circle: base_circle, theta0: 0.0, theta1: TWO_PI, which: "base" }];
      res.loop = [arc];
    } else if (w !== 0.0) {
      res.light_inside = true;
      res.warnings.push(make_warning("LIGHT_INSIDE_OBJECT", [], INSIDE_MESSAGE("cylinder")));
    }
    return res;
  }
  res.alpha = alpha;
  const th0 = theta_l - alpha, th1 = theta_l + alpha;
  res.lit_interval = [th0, th1];
  const u0 = u_theta(e1, e2, th0), u1 = u_theta(e1, e2, th1);
  const g0: Generator = { theta: th0, base: add3(b, scale3(r, u0)), top: add3(top_c, scale3(r, u0)) };
  const g1: Generator = { theta: th1, base: add3(b, scale3(r, u1)), top: add3(top_c, scale3(r, u1)) };
  res.generators = [g0, g1];
  const base_arc = arc_piece(base_circle, th0, !cap_base ? th1 : th1 - TWO_PI, "base");
  const top_arc = arc_piece(top_circle, th1, cap_top ? th0 + TWO_PI : th0, "top");
  res.loop = [
    base_arc,
    segment_piece(g1.base, g1.top, th1, ["base", "top"], "generator", 1),
    top_arc,
    segment_piece(g0.top, g0.base, th0, ["top", "base"], "generator", 0),
  ];
  for (const piece of [base_arc, top_arc]) {
    const [lo, hi] = ccw_range(piece.arc.theta0, piece.arc.theta1);
    res.arcs.push({ circle: piece.arc.circle, theta0: lo, theta1: hi, which: piece.arc.which });
  }
  return res;
}

function cone_silhouette(an: Analytic, L: Vec4, tol: number): Silhouette {
  const res = empty_result("cone");
  const b = an.base;
  const r = an.radius;
  const h = an.height as number;
  const apex = add3(b, scale3(h, an.axis));
  const { a, e1, e2, qa, d, theta_l } = axis_setup(an, L, apex);
  const w = L[3];
  const cap_base = lit(neg3(a), b, L, tol);
  res.cap_lit = { base: cap_base, top: false };
  const base_circle = circle_record(b, e1, e2, r);
  res.cap_circles = { base: base_circle };
  res.apex = apex;
  res.theta_l = theta_l;
  let state: string, alpha: number | null;
  if (d <= tol) {
    state = qa > tol ? "all" : "none";
    alpha = null;
  } else {
    const arg = -r * qa / (h * d);
    if (arg <= -1.0) [state, alpha] = ["all", null];
    else if (arg >= 1.0) [state, alpha] = ["none", null];
    else [state, alpha] = ["partial", Math.acos(arg)];
  }
  if (state === "all") {
    res.lit_interval = "all";
    if (!cap_base) {
      const arc = arc_piece(base_circle, 0.0, TWO_PI, "base");
      res.arcs = [{ ...arc.arc }];
      res.loop = [arc];
    }
    return res;
  }
  if (state === "none") {
    if (cap_base) {
      const arc = arc_piece(base_circle, TWO_PI, 0.0, "base");
      res.arcs = [{ circle: base_circle, theta0: 0.0, theta1: TWO_PI, which: "base" }];
      res.loop = [arc];
    } else if (w !== 0.0) {
      res.light_inside = true;
      res.warnings.push(make_warning("LIGHT_INSIDE_OBJECT", [], INSIDE_MESSAGE("cone")));
    }
    return res;
  }
  const al = alpha as number;
  res.alpha = al;
  const th0 = theta_l - al, th1 = theta_l + al;
  res.lit_interval = [th0, th1];
  const u0 = u_theta(e1, e2, th0), u1 = u_theta(e1, e2, th1);
  const g0: Generator = { theta: th0, base: add3(b, scale3(r, u0)), top: [...apex] };
  const g1: Generator = { theta: th1, base: add3(b, scale3(r, u1)), top: [...apex] };
  res.generators = [g0, g1];
  const base_arc = arc_piece(base_circle, th0, !cap_base ? th1 : th1 - TWO_PI, "base");
  res.loop = [
    base_arc,
    segment_piece(g1.base, apex, th1, ["base", "apex"], "generator", 1),
    segment_piece(apex, g0.base, th0, ["apex", "base"], "generator", 0),
  ];
  const [lo, hi] = ccw_range(base_arc.arc.theta0, base_arc.arc.theta1);
  res.arcs = [{ circle: base_circle, theta0: lo, theta1: hi, which: "base" }];
  return res;
}

/** Silhouette of a curved primitive with respect to `L` (light vector or camera position; spec §5.6, §2.6). */
export function silhouette(analytic: Analytic, Lin: readonly number[], tol = 0.0): Silhouette {
  const L = canonical_light(Lin);
  switch (analytic.kind) {
    case "sphere":
      return sphere_silhouette(analytic, L, tol);
    case "cylinder":
      return cylinder_silhouette(analytic, L, tol);
    case "cone":
      return cone_silhouette(analytic, L, tol);
    default:
      throw new Error(`unknown curved primitive kind '${analytic.kind}'`);
  }
}

// ---------------------------------------------------------------------------
// terminator (image side, contract §2.6)
// ---------------------------------------------------------------------------

/** The light silhouette as image-side drawables (`form_shadow` layer) in loop order. */
export function terminator(analytic: Analytic, L: readonly number[], tol = 0.0): TerminatorItem[] {
  const sil = silhouette(analytic, L, tol);
  const out: TerminatorItem[] = [];
  for (const piece of sil.loop) {
    if (piece.segment !== undefined) {
      const seg = piece.segment;
      out.push({ segment: [point4(seg.from), point4(seg.to)], which: seg.which, theta: seg.theta });
    } else {
      const arc = piece.arc;
      const [lo, hi] = ccw_range(arc.theta0, arc.theta1);
      out.push({ circle_arc: { circle: arc.circle, theta0: lo, theta1: hi, which: arc.which, full: hi - lo >= TWO_PI - 1e-12 } });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// loop clipping by a linear functional (ground clip §2.3, w_S clip §2.6)
// ---------------------------------------------------------------------------

/** The `loop` of `silhouette` as 4-D pieces. */
export function loop_pieces_4d(sil: Silhouette): Piece4[] {
  return sil.loop.map((piece): Piece4 => {
    if (piece.segment !== undefined) {
      const seg = piece.segment;
      return { segment: [point4(seg.from), point4(seg.to)], which: seg.which, theta: seg.theta, ends: seg.ends, gen: seg.gen };
    }
    const arc = piece.arc;
    return { arc: { E: circle_embedding(arc.circle), rho: arc.circle.radius, theta0: arc.theta0, theta1: arc.theta1, circle: arc.circle, which: arc.which } };
  });
}

function piece_start(piece: Piece4): number[] {
  if (piece.segment !== undefined) return piece.segment[0];
  const arc = piece.arc as Arc4;
  return conic_point(arc.E, arc.theta0, arc.rho);
}

function piece_end(piece: Piece4): number[] {
  if (piece.segment !== undefined) return piece.segment[1];
  const arc = piece.arc as Arc4;
  return conic_point(arc.E, arc.theta1, arc.rho);
}

function zero_shift(cA: number, cB: number, cC: number, level: number): number | null {
  const R = Math.hypot(cA, cB);
  if (R <= 0.0) return null;
  const c0 = -cC / R;
  const c1 = (level - cC) / R;
  if (Math.abs(c0) >= 1.0 || Math.abs(c1) > 1.0) return null;
  return Math.acos(c0) - Math.acos(c1);
}

function interp(fa: number, fb: number, A: readonly number[], B: readonly number[]): number[] {
  const den = fa - fb;
  return A.map((_x, k) => (fa * (B[k] as number) - fb * (A[k] as number)) / den);
}

function clip_piece(piece: Piece4, f: readonly number[], level: number): Piece4[] {
  if (piece.segment !== undefined) {
    const [A, B] = piece.segment;
    const fa0 = dot4(f, A), fb0 = dot4(f, B);
    const fa = fa0 - level, fb = fb0 - level;
    const was_start = piece.cut_start ?? false, was_end = piece.cut_end ?? false;
    if (fa > 0.0 && fb > 0.0) {
      return [{ ...piece, cut_start: was_start, cut_end: was_end, cut_now: [false, false], zero_start: null, zero_end: null }];
    }
    if (fa <= 0.0 && fb <= 0.0) return [];
    const X = interp(fa, fb, A, B);
    let zero: number[] | null = null;
    if ((fa0 > 0.0) !== (fb0 > 0.0) && fa0 !== fb0) zero = interp(fa0, fb0, A, B);
    if (fa > 0.0) {
      return [{ ...piece, segment: [A, X], cut_start: was_start, cut_end: true, cut_now: [false, true], zero_start: null, zero_end: zero }];
    }
    return [{ ...piece, segment: [X, B], cut_start: true, cut_end: was_end, cut_now: [true, false], zero_start: zero, zero_end: null }];
  }
  const arc = piece.arc as Arc4;
  const t0 = arc.theta0, t1 = arc.theta1;
  const [lo, hi] = ccw_range(t0, t1);
  const [cA, cB, cC] = functional_coeffs(f, arc.E, arc.rho);
  const intervals = sub_arcs_where_nonnegative(cA, cB, cC, lo, hi, level);
  const shift = zero_shift(cA, cB, cC, level);
  const eps = 1e-12;
  let was_start = piece.cut_start ?? false, was_end = piece.cut_end ?? false;
  if (t0 > t1) [was_start, was_end] = [was_end, was_start];
  let out: Piece4[] = [];
  for (const [a, b] of intervals) {
    let now_a: boolean, now_b: boolean;
    if (b > hi + eps) {
      now_a = now_b = true;
    } else {
      now_a = a > lo + eps;
      now_b = b < hi - eps;
    }
    out.push({
      ...piece,
      arc: { ...arc, theta0: a, theta1: b },
      cut_start: now_a || (!now_a && was_start),
      cut_end: now_b || (!now_b && was_end),
      cut_now: [now_a, now_b],
      zero_start: now_a && shift !== null ? conic_point(arc.E, a - shift, arc.rho) : null,
      zero_end: now_b && shift !== null ? conic_point(arc.E, b + shift, arc.rho) : null,
    });
  }
  if (t0 > t1) {
    out = out.reverse().map((sub) => ({
      ...sub,
      arc: { ...(sub.arc as Arc4), theta0: (sub.arc as Arc4).theta1, theta1: (sub.arc as Arc4).theta0 },
      cut_start: sub.cut_end as boolean,
      cut_end: sub.cut_start as boolean,
      cut_now: [(sub.cut_now as [boolean, boolean])[1], (sub.cut_now as [boolean, boolean])[0]],
      zero_start: sub.zero_end ?? null,
      zero_end: sub.zero_start ?? null,
    }));
  }
  return out;
}

function cut_point(piece: Piece4, end: 0 | 1): number[] {
  const zero = end ? piece.zero_end : piece.zero_start;
  if ((piece.cut_now as [boolean, boolean])[end] && zero !== null && zero !== undefined) return zero;
  return end ? piece_end(piece) : piece_start(piece);
}

function clip_loop(pieces: readonly Piece4[], f: readonly number[], level: number): [Item[], boolean] {
  const kept: Piece4[] = [];
  const dropped_before: number[] = [];
  let dropped = 0;
  let any_cut = false;
  for (const piece of pieces) {
    const subs = clip_piece(piece, f, level);
    if (subs.length === 0) {
      dropped += 1;
      any_cut = true;
      continue;
    }
    for (const sub of subs) {
      kept.push(sub);
      dropped_before.push(dropped);
      dropped = 0;
      const now = sub.cut_now as [boolean, boolean];
      any_cut = any_cut || now[0] || now[1];
    }
  }
  if (kept.length === 0) return [[], any_cut];
  dropped_before[0] = (dropped_before[0] as number) + dropped;
  const n = kept.length;
  const items: Item[] = [];
  for (let i = 0; i < n; i++) {
    const ki = kept[i] as Piece4;
    items.push(ki);
    const j = (i + 1) % n;
    const kj = kept[j] as Piece4;
    if ((ki.cut_now as [boolean, boolean])[1] || (kj.cut_now as [boolean, boolean])[0] || (dropped_before[j] as number) > 0) {
      items.push({ gap: [cut_point(ki, 1), cut_point(kj, 0)] });
    }
  }
  return [items, any_cut];
}

function is_gap(it: Item): it is { gap: [number[], number[]] } {
  return (it as { gap?: unknown }).gap !== undefined;
}

function direction_from(S: readonly number[], fallback_from: readonly number[] | null, finite_hint: readonly number[] | null): Vec4 {
  const D: Vec4 = [S[0] as number, S[1] as number, S[2] as number, 0.0];
  let norm = norm3(D);
  if (norm > 1e-300 && Number.isFinite(norm)) return [D[0] / norm, D[1] / norm, D[2] / norm, D[3] / norm];
  if (fallback_from !== null && finite_hint !== null && finite_hint[3] !== 0.0) {
    const w = finite_hint[3] as number;
    const d: Vec3 = [(finite_hint[0] as number) / w - (fallback_from[0] as number), (finite_hint[1] as number) / w - (fallback_from[1] as number),
      (finite_hint[2] as number) / w - (fallback_from[2] as number)];
    norm = norm3(d);
    if (norm > 1e-300 && Number.isFinite(norm)) return [d[0] / norm, d[1] / norm, d[2] / norm, 0.0 / norm];
  }
  return [1.0, 0.0, 0.0, 0.0];
}

// ---------------------------------------------------------------------------
// ground cross-section of a buried primitive (contract §2.3 ground clip, spec §7.3)
// ---------------------------------------------------------------------------

const CHAIN_MARGIN = 1e-7;
/** Geometric refinement samples next to a direction vertex (`1/2, 1/4, …` of the last step). */
export const ASYMPTOTE_REFINE = 4;

function theta_lit(sil: Silhouette, theta: number): boolean {
  const iv = sil.lit_interval;
  if (iv === "all") return true;
  if (iv === null) return false;
  const [th0, th1] = iv;
  const k = pymod(theta - th0, TWO_PI);
  return 0.0 < k && k < th1 - th0;
}

function intersect_arcs(intervals: readonly [number, number][], A: number, B: number, C: number, tol: number): [number, number][] {
  const out: [number, number][] = [];
  for (const [a, b] of intervals) out.push(...sub_arcs_where_nonnegative(A, B, C, a, b, tol));
  return out;
}

function lateral_intervals(E_base: Mat43, rho: number, conditions: readonly (readonly number[])[]): [number, number][] {
  let intervals: [number, number][] = [[0.0, TWO_PI]];
  for (const f of conditions) {
    const [A, B, C] = functional_coeffs(f, E_base, rho);
    intervals = intersect_arcs(intervals, A, B, C, 0.0);
  }
  return intervals;
}

interface Section {
  points: Vec3[];
  lit: boolean[];
  centre: Vec2;
}

function ground_section(analytic: Analytic, sil: Silhouette, L: Vec4, pi: readonly number[], tol_lit: number, tol: number,
  samples_per_circle = 64): Section | null {
  const kind = analytic.kind;
  const r = analytic.radius;
  const n = v3(pi);
  const pi3 = pi[3] as number;
  if (kind === "sphere") {
    const c = analytic.centre;
    const depth = dot3(n, c) + pi3;
    if (r - Math.abs(depth) <= tol) return null;
    const rs = Math.sqrt(r * r - depth * depth);
    const [e1, e2] = circle_frame(n);
    const centre = sub3(c, scale3(depth, n));
    const pts: Vec3[] = [];
    const lits: boolean[] = [];
    for (let k = 0; k < samples_per_circle; k++) {
      const th = TWO_PI * k / samples_per_circle;
      const ct = Math.cos(th), st = Math.sin(th);
      const p: Vec3 = [0, 1, 2].map((j) => centre[j]! + rs * (ct * e1[j]! + st * e2[j]!)) as Vec3;
      pts.push(p);
      lits.push(lit([(p[0] - c[0]) / r, (p[1] - c[1]) / r, (p[2] - c[2]) / r], p, L, tol_lit));
    }
    return { points: pts, lit: lits, centre: [centre[0], centre[1]] };
  }
  const a = analytic.axis, b = analytic.base;
  const h = analytic.height as number;
  const e1 = analytic.e1, e2 = analytic.e2;
  const E_base = circle_embedding(circle_record(b, e1, e2, r));
  const pts: Vec3[] = [];
  const lit_list: boolean[] = [];
  const add = (theta: number, X: readonly number[]): void => {
    pts.push(v3(X));
    lit_list.push(theta_lit(sil, theta));
  };
  const sample_intervals = (intervals: readonly [number, number][], mapper: (theta: number) => Vec3): void => {
    for (const [lo, hi] of intervals) {
      const m = sample_count(lo, hi, samples_per_circle);
      const last = hi - lo < TWO_PI - 1e-12 ? m : m - 1;
      for (let k = 0; k <= last; k++) {
        const theta = lo + (hi - lo) * k / m;
        add(theta, mapper(theta));
      }
    }
  };
  const na = dot3(n, a);
  if (kind === "cylinder") {
    if (Math.abs(na) <= TOL_DIR) {
      const amp = Math.hypot(dot3(n, e1), dot3(n, e2));
      const depth = dot3(n, b) + pi3;
      if (amp <= TOL_DIR || Math.abs(depth) >= r * amp * (1.0 - 1e-12)) return null;
      const phi = Math.atan2(dot3(n, e2), dot3(n, e1));
      const d = Math.acos(Math.max(-1.0, Math.min(1.0, -depth / (r * amp))));
      for (const theta of [phi - d, phi + d]) {
        const B = add3(b, scale3(r, u_theta(e1, e2, theta)));
        add(theta, B);
        add(theta, add3(B, scale3(h, a)));
      }
    } else {
      const top = circle_embedding(circle_record(add3(b, scale3(h, a)), e1, e2, r));
      const sign = na > 0.0 ? 1.0 : -1.0;
      let intervals = lateral_intervals(E_base, r, [scale_n(-sign, pi)]);
      const [A_t, B_t, C_t] = functional_coeffs(scale_n(sign, pi), top, r);
      intervals = intersect_arcs(intervals, A_t, B_t, C_t, 0.0);
      sample_intervals(intervals, (theta) => {
        const B = add3(b, scale3(r, u_theta(e1, e2, theta)));
        return sub3(B, scale3((dot3(n, B) + pi3) / na, a));
      });
    }
  } else {
    const apex = add3(b, scale3(h, a));
    const depth_v = dot3(n, apex) + pi3;
    if (Math.abs(depth_v) <= tol) {
      const intervals = lateral_intervals(E_base, r, [scale_n(-1, pi)]);
      const ends: number[] = [];
      for (const [lo, hi] of intervals) ends.push(lo, hi);
      if (ends.length === 0) return null;
      for (const theta of ends) add(theta, add3(b, scale3(r, u_theta(e1, e2, theta))));
      pts.push([...apex]);
      lit_list.push(ends.some((theta) => theta_lit(sil, theta)));
    } else {
      const sign = depth_v > 0.0 ? 1.0 : -1.0;
      const intervals = lateral_intervals(E_base, r, [scale_n(-sign, pi)]);
      sample_intervals(intervals, (theta) => {
        const B = add3(b, scale3(r, u_theta(e1, e2, theta)));
        const depth_b = dot3(n, B) + pi3;
        const den = depth_v - depth_b;
        return [0, 1, 2].map((j) => (depth_v * B[j]! - depth_b * apex[j]!) / den) as Vec3;
      });
    }
  }
  if (pts.length < 3) return null;
  let sx = 0, sy = 0;
  for (const p of pts) {
    sx += p[0];
    sy += p[1];
  }
  const centre: Vec2 = [sx / pts.length, sy / pts.length];
  let size = -Infinity;
  for (const p of pts) size = Math.max(size, Math.hypot(p[0] - centre[0], p[1] - centre[1]));
  if (!(size > tol)) return null;
  return { points: pts, lit: lit_list, centre };
}

function ground_chain(section: Section | null, X_exit: readonly number[], X_entry: readonly number[], single_gap: boolean): Vec4[] {
  if (section === null) return [];
  const { points: P, lit: lit_mask, centre: I } = section;
  const e: Vec2 = [(X_exit[0] as number) / (X_exit[3] as number), (X_exit[1] as number) / (X_exit[3] as number)];
  const n_: Vec2 = [(X_entry[0] as number) / (X_entry[3] as number), (X_entry[1] as number) / (X_entry[3] as number)];
  const rel = P.map((p) => [p[0] - I[0], p[1] - I[1]] as Vec2);
  let size = -Infinity;
  for (const q of rel) size = Math.max(size, Math.hypot(q[0], q[1]));
  const delta = CHAIN_MARGIN * size;
  const phi_e = Math.atan2(e[1] - I[1], e[0] - I[0]);
  const phi_n = Math.atan2(n_[1] - I[1], n_[0] - I[0]);
  let span = pymod(phi_n - phi_e, TWO_PI);
  const chord: Vec2 = [n_[0] - e[0], n_[1] - e[1]];
  const chord_len = Math.hypot(chord[0], chord[1]);
  const degenerate = chord_len <= delta || span <= CHAIN_MARGIN || span >= TWO_PI - CHAIN_MARGIN;
  if (degenerate) {
    if (!single_gap) return [];
    span = TWO_PI;
  }
  const keys = rel.map((q) => pymod(Math.atan2(q[1], q[0]) - phi_e, TWO_PI));
  const sel: number[] = [];
  P.forEach((p, i) => {
    const k = keys[i] as number;
    const d_e = Math.hypot(p[0] - e[0], p[1] - e[1]);
    const d_n = Math.hypot(p[0] - n_[0], p[1] - n_[1]);
    if (lit_mask[i] && k > CHAIN_MARGIN && k < span - CHAIN_MARGIN && d_e > delta && d_n > delta) sel.push(i);
  });
  if (sel.length === 0) return [];
  if (!degenerate) {
    let left = -Infinity;
    for (const i of sel) {
      const p = P[i] as Vec3;
      left = Math.max(left, chord[0] * (p[1] - e[1]) - chord[1] * (p[0] - e[0]));
    }
    if (left > delta * chord_len) return [];
  }
  const order = sel.map((_i, idx) => idx).sort((x, y) => (keys[sel[x] as number] as number) - (keys[sel[y] as number] as number) || x - y);
  return order.map((idx) => point4(P[sel[idx] as number] as Vec3));
}

function ground_ring(section: Section | null): Vec4[] {
  if (section === null) return [];
  const { points: P, lit: lit_mask, centre: I } = section;
  const lit_idx: number[] = [];
  lit_mask.forEach((l, i) => {
    if (l) lit_idx.push(i);
  });
  if (lit_idx.length < 3) return [];
  const keys = lit_idx.map((i) => Math.atan2((P[i] as Vec3)[1] - I[1], (P[i] as Vec3)[0] - I[0]));
  const order = lit_idx.map((_i, idx) => idx).sort((x, y) => (keys[x] as number) - (keys[y] as number) || x - y);
  return order.map((idx) => point4(P[lit_idx[idx] as number] as Vec3));
}

// ---------------------------------------------------------------------------
// ground shadow outline (contract §2.6 "unbounded curved shadows")
// ---------------------------------------------------------------------------

/** Oriented ground shadow outline of the light silhouette loop (spec §5.6, contract §2.3 / §2.5 / §2.6). */
export function shadow_outline(analytic: Analytic, Lin: readonly number[], Min: Mat4, piIn: readonly number[], tol = 0.0,
  tol_dir = 1e-9): Outline {
  const factor = canonical_factor(Lin);
  const L = Lin.map((x) => x / factor) as Vec4;
  const M = Min.map((row) => row.map((x) => x / factor)) as Mat4;
  const pi = [...piIn];
  const tol_w = L[3] !== 0.0 ? tol : tol_dir;
  const sil = silhouette(analytic, L, tol_w);
  const warnings: Warning[] = [...sil.warnings];
  const result: Outline = { pieces: [], unbounded: false, below_ground: false, empty: true, silhouette: sil, warnings };
  let pieces = loop_pieces_4d(sil);
  if (pieces.length === 0) return result;
  // (2) ground clip, contract §2.3
  let [items, cut] = clip_loop(pieces, pi, -tol);
  if (cut) {
    result.below_ground = true;
    warnings.push(make_warning("OBJECT_BELOW_RECEIVER", []));
  }
  pieces = [];
  const n_gaps = items.filter(is_gap).length;
  const section = cut ? ground_section(analytic, sil, L, pi, tol_w, tol) : null;
  for (const it of items) {
    if (is_gap(it)) {
      const [X_exit, X_entry] = it.gap;
      const chain: number[][] = [X_exit, ...ground_chain(section, X_exit, X_entry, n_gaps === 1), X_entry];
      for (let k = 0; k + 1 < chain.length; k++) {
        pieces.push({ segment: [chain[k] as number[], chain[k + 1] as number[]], which: "ground", theta: null });
      }
    } else {
      pieces.push(it);
    }
  }
  if (items.length === 0 && cut) {
    const ring = ground_ring(section);
    for (let k = 0; k < ring.length; k++) {
      pieces.push({ segment: [ring[k] as Vec4, ring[(k + 1) % ring.length] as Vec4], which: "ground", theta: null });
    }
  }
  if (pieces.length === 0) return result;
  // (3) w_S clip, contract §2.5 / §2.6
  [items, cut] = clip_loop(pieces, M[3], tol_w);
  if (cut) warnings.push(make_warning("VERTEX_NOT_BELOW_LIGHT", []));
  if (items.length === 0) return result;
  result.unbounded = cut;
  const Fh = foot(pi, L);
  const F = Math.abs(Fh[3]) > 1e-300 ? Fh.map((x) => x / Fh[3]) : null;
  const out: OutlinePiece[] = [];
  items.forEach((it, idx) => {
    if (is_gap(it)) {
      const [X_exit, X_entry] = it.gap;
      const prev_piece = items[pyimod(idx - 1, items.length)] as Item;
      const next_piece = items[(idx + 1) % items.length] as Item;
      const hint_prev = !is_gap(prev_piece) ? mat4_vec(M, piece_start(prev_piece)) : null;
      const hint_next = !is_gap(next_piece) ? mat4_vec(M, piece_end(next_piece)) : null;
      out.push({ direction: direction_from(mat4_vec(M, X_exit), F, hint_prev), role: "out" });
      out.push({ direction: direction_from(mat4_vec(M, X_entry), F, hint_next), role: "in" });
    } else if (it.segment !== undefined) {
      const [A, B] = it.segment;
      out.push({
        segment: [mat4_vec(M, A), mat4_vec(M, B)], which: it.which as string, theta: it.theta ?? null,
        ends: it.ends ?? null, gen: it.gen ?? null, cut: [it.cut_start ?? false, it.cut_end ?? false],
      });
    } else {
      const arc = it.arc as Arc4;
      out.push({
        conic_arc: {
          E: arc.E, rho: arc.rho, T: M, theta0: arc.theta0, theta1: arc.theta1, circle: arc.circle, which: arc.which,
          cut: [it.cut_start ?? false, it.cut_end ?? false],
        },
      });
    }
  });
  result.pieces = out;
  result.empty = false;
  return result;
}

/** Oriented homogeneous ground polygon of a `shadow_outline` (contract §2.5 / §2.6). */
export function shadow_polygon_h(outline: Outline | readonly OutlinePiece[], samples_per_circle = 64): ShadowPolygon {
  const pieces: readonly OutlinePiece[] = Array.isArray(outline) ? outline : (outline as Outline).pieces;
  const n = pieces.length;
  const verts: Vec4[] = [];
  const sources: PolySource[] = [];
  let unbounded = false;
  if (n === 0) return { vertices: [], unbounded: false, sources: [] };
  const is_dir = (k: number, role: string): boolean => {
    const p = pieces[pyimod(k, n)] as OutlinePiece;
    return "direction" in p && p.role === role;
  };
  pieces.forEach((piece, i) => {
    const skip_start = is_dir(i - 1, "in");
    if ("segment" in piece) {
      if (!skip_start) {
        verts.push([...piece.segment[0]]);
        sources.push({ kind: "segment", i, end: 0 });
      }
    } else if ("conic_arc" in piece) {
      const arc = piece.conic_arc;
      const th0 = arc.theta0, th1 = arc.theta1;
      const m = sample_count(th0, th1, samples_per_circle);
      let ks: number[] = [];
      for (let k = skip_start ? 1 : 0; k < m; k++) ks.push(k);
      if (skip_start) {
        const pre: number[] = [];
        for (let j = ASYMPTOTE_REFINE; j >= 1; j--) pre.push(2.0 ** -j);
        ks = [...pre, ...ks];
      }
      if (is_dir(i + 1, "out")) for (let j = 1; j <= ASYMPTOTE_REFINE; j++) ks.push(m - 2.0 ** -j);
      for (const k of ks) {
        const th = th0 + (th1 - th0) * k / m;
        const X = conic_point(arc.E, th, arc.rho);
        verts.push(mat4_vec(arc.T, X));
        sources.push({ kind: "arc", i, k });
      }
    } else {
      const D = piece.direction;
      verts.push([...D]);
      sources.push({ kind: "dir", i, role: piece.role });
      unbounded = true;
      if (piece.role === "out") {
        const nxt = pieces[(i + 1) % n] as OutlinePiece;
        if (!("direction" in nxt) || nxt.role !== "in") throw new Error("an outgoing direction must be followed by an incoming one");
        const d_in = nxt.direction;
        const th0 = Math.atan2(D[1], D[0]);
        const th1 = Math.atan2(d_in[1], d_in[0]);
        let delta = pymod(th1 - th0, TWO_PI);
        if (!Number.isFinite(delta) || delta <= 1e-12) delta = TWO_PI;
        const steps = Math.max(1, Math.ceil(delta / radians(ARC_STEP_DEG) - 1e-12));
        for (let s = 1; s < steps; s++) {
          const t = th0 + delta * s / steps;
          verts.push([Math.cos(t), Math.sin(t), 0.0, 0.0]);
          sources.push({ kind: "inf", i, s: s - 1 });
        }
      }
    }
  });
  return { vertices: verts, unbounded, sources };
}

// ---------------------------------------------------------------------------
// construction points (contract §2.7)
// ---------------------------------------------------------------------------

/** Named homogeneous 4-vectors of the silhouette vertices that get construction rays (insertion order). */
export function construction_points(analytic: Analytic, L: readonly number[], tol = 0.0, obj_id = "obj"): Map<string, Vec4> {
  const sil = silhouette(analytic, L, tol);
  const pts = new Map<string, Vec4>();
  if (sil.kind === "sphere") {
    if (sil.light_inside) return pts;
    pts.set(`${obj_id}.c`, point4(analytic.centre));
    const circ = sil.circle;
    if (circ !== null) {
      const c = circ.centre, rs = circ.radius;
      [circ.e1, neg3(circ.e1), circ.e2, neg3(circ.e2)].forEach((v, k) => {
        pts.set(`${obj_id}.sil.${k}`, point4(add3(c, scale3(rs, v))));
      });
    }
    return pts;
  }
  const gens = sil.generators;
  if (gens.length === 0) return pts;
  if (sil.kind === "cylinder") {
    gens.forEach((g, k) => {
      pts.set(`${obj_id}.g${k}.base`, point4(g.base));
      pts.set(`${obj_id}.g${k}.top`, point4(g.top));
    });
  } else {
    gens.forEach((g, k) => pts.set(`${obj_id}.g${k}.base`, point4(g.base)));
    pts.set(`${obj_id}.apex`, point4(sil.apex as Vec3));
  }
  return pts;
}

// ---------------------------------------------------------------------------
// camera outline (contract §2.6 / §2.10)
// ---------------------------------------------------------------------------

export interface CapArc {
  which: string;
  circle: Circle;
  theta0: number;
  theta1: number;
  back: boolean;
  full: boolean;
}

export interface CameraOutline {
  silhouette: Silhouette;
  generators: Generator[];
  circle: Circle | null;
  cap_arcs: CapArc[];
  camera_inside: boolean;
}

/** Outline of a curved object as seen from the camera position `C` plus the split cap arcs with a `back` flag. */
export function camera_outline(analytic: Analytic, C: readonly number[], tol = 0.0): CameraOutline {
  const L: Vec4 = [C[0] as number, C[1] as number, C[2] as number, 1.0];
  const sil = { ...silhouette(analytic, L, tol), warnings: [] };
  const out: CameraOutline = { silhouette: sil, generators: sil.generators, circle: sil.circle, cap_arcs: [], camera_inside: sil.light_inside };
  if (sil.kind === "sphere") return out;
  const gens = sil.generators;
  const lateral_all = sil.lit_interval === "all";
  for (const which of ["base", "top"] as const) {
    const circle = sil.cap_circles[which];
    if (circle === undefined) continue;
    const cap_lit = sil.cap_lit[which];
    if (gens.length > 0) {
      const th0 = (gens[0] as Generator).theta, th1 = (gens[1] as Generator).theta;
      out.cap_arcs.push({ which, circle, theta0: th0, theta1: th1, back: false, full: false });
      out.cap_arcs.push({ which, circle, theta0: th1, theta1: th0 + TWO_PI, back: !cap_lit, full: false });
    } else {
      out.cap_arcs.push({ which, circle, theta0: 0.0, theta1: TWO_PI, back: !cap_lit && !lateral_all, full: true });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// pipeline hooks: stage A and stage B of a curved object
// ---------------------------------------------------------------------------

/** Minimum of `πᵀX` over the solid primitive (`OBJECT_BELOW_RECEIVER` on the exact surface). */
export function plane_min(analytic: Analytic, pi: readonly number[]): number {
  const n = v3(pi), d = pi[3] as number;
  const nn = norm3(n);
  const r = analytic.radius;
  if (analytic.kind === "sphere") return dot3(n, analytic.centre) + d - r * nn;
  const a = analytic.axis, b = analytic.base;
  const na = dot3(n, a);
  const circle_drop = r * Math.sqrt(Math.max(0.0, nn * nn - na * na));
  const values = [dot3(n, b) + d - circle_drop];
  const top = add3(b, scale3(analytic.height as number, a));
  if (analytic.kind === "cylinder") values.push(dot3(n, top) + d - circle_drop);
  else values.push(dot3(n, top) + d);
  return Math.min(...values);
}

function cap_parallel(analytic: Analytic, L: readonly number[], tol: number): boolean {
  if (analytic.kind === "sphere") return false;
  const a = analytic.axis, b = analytic.base;
  const caps: [Vec3, Vec3][] = [[neg3(a), b]];
  if (analytic.kind === "cylinder") caps.push([a, add3(b, scale3(analytic.height as number, a))]);
  const w = L[3] as number;
  for (const [n, p] of caps) {
    const v = dot3(n, [(L[0] as number) - w * p[0], (L[1] as number) - w * p[1], (L[2] as number) - w * p[2]]);
    if (Math.abs(v) <= tol) return true;
  }
  return false;
}

function empty_shadow_record(oid: string, lid: string, receiver_id: string): ShadowRecord {
  return {
    light: lid, receiver: receiver_id, object: oid, kind: "curved", keep: [], P_world: [], S_world: [], Q_world: [], w_S: [],
    shadow_names: [], foot_names: [], vertex_names: [], ground_points: [], loops: [], unbounded: false, pieces: [],
  };
}

/** quarter turn k (θ = kπ/2) -> `<obj>.sil.<index>` (+e1, +e2, −e1, −e2). */
const SIL_INDEX = [0, 2, 1, 3];

function curved_loop_entries(poly: ShadowPolygon, pieces: readonly OutlinePiece[], oid: string, lid: string, keep_names: ReadonlySet<string>,
  samples_per_circle: number): [LoopEntry[], [string, Vec3][]] {
  const V = poly.vertices;
  const n = pieces.length;
  const ground: [string, Vec3][] = [];
  const entries: LoopEntry[] = [];
  const ground_name = (row: number): string => {
    const X = V[row] as Vec4;
    const name = `${oid}.s${ground.length}.${lid}`;
    ground.push([name, [X[0] / X[3], X[1] / X[3], X[2] / X[3]]]);
    return name;
  };
  const end_name = (piece: OutlinePiece, end: number): string | null => {
    if (!("segment" in piece) || piece.which !== "generator" || piece.ends === null) return null;
    if (piece.cut[end]) return null;
    const e = piece.ends[end] as string;
    const pname = e === "apex" ? `${oid}.apex` : `${oid}.g${piece.gen}.${e}`;
    return keep_names.has(pname) ? `${pname}.shadow.${lid}` : null;
  };
  poly.sources.forEach((src, row) => {
    if (src.kind === "dir" || src.kind === "inf") {
      const D = V[row] as Vec4;
      entries.push({ direction: [D[0] + 0, D[1] + 0, D[2] + 0] });
      return;
    }
    let name: string | null = null;
    if (src.kind === "segment") {
      name = end_name(pieces[src.i] as OutlinePiece, src.end);
    } else {
      const { i, k } = src;
      const arc = (pieces[i] as { conic_arc: ConicArcPiece }).conic_arc;
      if (k === 0 && !arc.cut[0]) name = end_name(pieces[pyimod(i - 1, n)] as OutlinePiece, 1);
      if (name === null && arc.which === "silhouette") {
        const th0 = arc.theta0, th1 = arc.theta1;
        const m = sample_count(th0, th1, samples_per_circle);
        const theta = th0 + (th1 - th0) * k / m;
        const q = theta / (0.5 * Math.PI);
        const qi = py_round(q);
        if (Math.abs(q - qi) <= 1e-12) {
          const pname = `${oid}.sil.${SIL_INDEX[pyimod(qi, 4)]}`;
          if (keep_names.has(pname)) name = `${pname}.shadow.${lid}`;
        }
      }
    }
    entries.push(name !== null ? name : ground_name(row));
  });
  return [entries, ground];
}

/** Stage A of one curved object (spec §5.6, contract §2.6 / §2.7 / §3): stores `obj.curved` and returns one shadow
 * record per light; warnings are appended with `ids == [obj id]`. */
export function stage_a_object(obj: ObjectRecord & { curved?: Map<string, CurvedData> }, lights: readonly LightRecordLike[],
  piIn: readonly number[], tol: number, receiver_id: string, warnings: Warning[]): ShadowRecord[] {
  const an = obj.analytic as Analytic;
  const oid = obj.id;
  const pi = [...piIn];
  const curved = new Map<string, CurvedData>();
  obj.curved = curved;
  const records: ShadowRecord[] = [];
  if (plane_min(an, pi) < -tol) warnings.push(make_warning("OBJECT_BELOW_RECEIVER", [oid]));
  for (const lt of lights) {
    const lid = lt.id;
    const L = lt.L;
    const tol_L = lt.tol_lit;
    const sil = silhouette(an, L, tol_L);
    const pts = construction_points(an, L, tol_L, oid);
    const term = terminator(an, L, tol_L);
    if (cap_parallel(an, L, tol_L)) warnings.push(make_warning("FACE_PARALLEL_TO_LIGHT", [oid]));
    for (const w of sil.warnings) warnings.push(make_warning(w.code, [oid], w.message));
    const cd: CurvedData = { silhouette: sil, terminator: term, points: pts, outline: null, polygon: null };
    curved.set(lid, cd);
    const rec = empty_shadow_record(oid, lid, receiver_id);
    records.push(rec);
    if (!lt.active) continue;
    const out = shadow_outline(an, L, lt.M, pi, tol, TOL_DIR);
    for (const w of out.warnings) warnings.push(make_warning(w.code, [oid], w.message));
    const poly = shadow_polygon_h(out);
    cd.outline = out;
    cd.polygon = poly;
    const names = [...pts.keys()];
    const P4 = names.map((nm) => pts.get(nm) as Vec4);
    const w_S = P4.map((P) => shadow_w(pi, L, P));
    const finite = w_S.map((w) => w > lt.tol_w);
    const keep = P4.map((P, i) => (finite[i] as boolean) && dot4(P, pi) >= -tol);
    if (names.length > 0 && !finite.every((f) => f)) warnings.push(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]));
    const S_world = P4.map((P, i): Vec3 => {
      if (!keep[i]) return [0.0, 0.0, 0.0];
      const S = mat4_vec(lt.M, P);
      const w = w_S[i] as number;
      return [S[0] / w, S[1] / w, S[2] / w];
    });
    const Q_world = P4.map((P): Vec3 => {
      const Q = foot(pi, P);
      return [Q[0] / Q[3], Q[1] / Q[3], Q[2] / Q[3]];
    });
    const keep_names = new Set(names.filter((_nm, i) => keep[i]));
    const loops: ShadowRecord["loops"] = [];
    let ground: [string, Vec3][] = [];
    if (poly.vertices.length >= 3) {
      let entries: LoopEntry[];
      [entries, ground] = curved_loop_entries(poly, out.pieces, oid, lid, keep_names, 64);
      loops.push({ vertices: poly.vertices, sources: poly.sources, entries, unbounded: poly.unbounded });
    }
    Object.assign(rec, {
      keep,
      P_world: P4.map((P) => v3(P)),
      S_world,
      Q_world,
      w_S,
      shadow_names: names.map((nm) => `${nm}.shadow.${lid}`),
      foot_names: names.map((nm) => `${nm}.foot`),
      vertex_names: names,
      ground_points: ground,
      loops,
      unbounded: loops.length > 0 ? poly.unbounded : false,
      pieces: out.pieces,
    });
  }
  return records;
}

/** `f_ν` with `f_ν · X == ν(X)`: `(forward, −(forward·C + near))`. */
export function near_functional(cam: Pick<CameraRecord, "forward" | "C" | "near">): Vec4 {
  const f = cam.forward;
  return [f[0], f[1], f[2], -(dot3(f, cam.C) + cam.near)];
}

export interface ArcRecord extends ConicEntry {
  which: string;
  back: boolean;
  H: number[][];
  rho: number;
  whole_circle: boolean;
  near_cut: boolean;
  visible: [number, number][];
  front: [number, number][];
}

/** Stage-B record of one circle arc drawn through `H = P T E` (closed-form near and rectangle clips); `null`
 * when nothing of the arc is in front of the near plane. */
export function arc_record(circle: Circle, theta0: number, theta1: number, full: boolean, T: Mat4 | null, cam: CameraRecord,
  f_nu: readonly number[], rect_rows: readonly (readonly number[])[], map: string, which: string, back = false): ArcRecord | null {
  const E = circle_embedding(circle);
  const rho = circle.radius;
  const TE = T === null ? E.map((r) => [...r]) : matmul(T, E);
  const H = matmul(cam.P, TE);
  const [lo, hi] = ccw_range(theta0, theta1);
  const [A, B, C] = functional_coeffs(f_nu, TE, rho);
  const front = sub_arcs_where_nonnegative(A, B, C, lo, hi, 0.0);
  if (front.length === 0) return null;
  const eps = 1e-12;
  const f0 = front[0] as [number, number], fl = front[front.length - 1] as [number, number];
  const whole_front = front.length === 1 && f0[0] <= lo + eps && f0[1] >= hi - eps;
  const near_cut = !whole_front;
  const is_full = full && hi - lo >= TWO_PI - eps && whole_front;
  const entry = conic_entry(circle, H, is_full ? null : front.length === 1 ? [f0[0], fl[1]] : null, map);
  if (front.length > 1) entry.arc = { theta0: f0[0] + 0, theta1: fl[1] + 0 };
  let visible: [number, number][] = [...front];
  for (const row of rect_rows) {
    const [A2, B2, C2] = functional_coeffs(row, H, rho);
    visible = intersect_arcs(visible, A2, B2, C2, 0.0);
  }
  delete entry.cond;
  return {
    ...entry, which, back, H, rho, whole_circle: is_full, near_cut,
    visible: visible.map(([a, b]) => [a, b]), front: front.map(([a, b]) => [a, b]),
  };
}

export interface CurvedSegmentSlot {
  segment_h: [number[], number[]] | null;
  keep: boolean;
}

export interface GenEdge extends CurvedSegmentSlot {
  from: string;
  to: string;
}

export interface TerminatorSegment extends CurvedSegmentSlot {
  segment: [string, string];
}

export type StageBTerminatorItem = TerminatorSegment | ArcRecord;

export interface CurvedStageB {
  id: string;
  type: string;
  analytic: true;
  point_names: string[];
  world: Vec3[];
  image_h: Vec3[];
  depth: number[];
  behind: boolean[];
  gen_edges: GenEdge[];
  outline_arcs: ArcRecord[];
  terminator: Map<string, StageBTerminatorItem[]>;
  shadow_arcs: Map<string, ArcRecord[]>;
  camera_inside: boolean;
  form_faces: string[][];
  form_polygons: number[][][];
}

function terminator_segment_names(oid: string, t: { segment: [Vec4, Vec4]; theta: number | null }, sil: Silhouette): [string, string] {
  const theta = t.theta;
  let gen = -1;
  sil.generators.forEach((g, k) => {
    if (gen < 0 && theta !== null && g.theta === theta) gen = k;
  });
  const [A4, B4] = t.segment;
  if (gen < 0) return [`${oid}.g0.base`, `${oid}.g0.top`];
  const end_of = (X: Vec4): string => {
    const g = sil.generators[gen] as Generator;
    let close = true;
    for (let k = 0; k < 3; k++) if (!(Math.abs(X[k]! - g.base[k]!) <= 1e-8 + 1e-5 * Math.abs(g.base[k]!))) close = false;
    if (close) return `${oid}.g${gen}.base`;
    return sil.kind === "cone" ? `${oid}.apex` : `${oid}.g${gen}.top`;
  };
  return [end_of(A4), end_of(B4)];
}

/** Drawing pipeline of contract §2.2 for one world segment: `[segment_h | null, keep, behind]`. */
function project_segment(cam: CameraRecord, A4: Vec4, B4: Vec4): [[number[], number[]] | null, boolean, boolean] {
  const behind = nu(cam, A4) < 0.0 || nu(cam, B4) < 0.0;
  const near = clip_segment_near(cam, A4, B4);
  if (near === null) return [null, false, behind];
  const r = clip_segment_rect_h(project(cam, near[0]), project(cam, near[1]), cam.rect);
  if (r === null) return [null, false, behind];
  return [r, true, behind];
}

/**
 * Stage B of one curved object (contract §2.2 / §2.6 / §2.7 / §2.10): named points (construction points of every
 * light + the camera outline generator endpoints), outline generators and arcs, terminator drawables and the
 * cast-shadow conic arcs, all near- and rectangle-clipped; warnings `POINT_BEHIND_CAMERA` / `CONIC_SAMPLED`.
 */
export function stage_b_object(obj: ObjectRecord & { curved?: Map<string, CurvedData> }, rec: Partial<CurvedStageB>, cam: CameraRecord,
  tol: number, warnings: Warning[]): void {
  const an = obj.analytic as Analytic;
  const oid = obj.id;
  const f_nu = near_functional(cam);
  const rect_rows = rect_functionals(cam.rect);
  let behind_any = false;
  let sampled_any = false;
  const names: string[] = [];
  const name_set = new Set<string>();
  const X4: Vec4[] = [];
  const add_point = (name: string, X: Vec4): void => {
    if (!name_set.has(name)) {
      name_set.add(name);
      names.push(name);
      X4.push([...X]);
    }
  };
  const fill = (slot: CurvedSegmentSlot, A: Vec4, B: Vec4): void => {
    const [seg, keep, behind] = project_segment(cam, A, B);
    slot.segment_h = seg;
    slot.keep = keep;
    if (behind) behind_any = true;
  };
  // objects layer: camera outline (contract §2.10)
  const co = camera_outline(an, cam.C, tol);
  const gen_edges: GenEdge[] = [];
  co.generators.forEach((g, k) => {
    const a_name = `${oid}.og${k}.base`, b_name = `${oid}.og${k}.top`;
    add_point(a_name, point4(g.base));
    add_point(b_name, point4(g.top));
    const edge: GenEdge = { from: a_name, to: b_name, segment_h: null, keep: false };
    gen_edges.push(edge);
    fill(edge, point4(g.base), point4(g.top));
  });
  const outline_arcs: ArcRecord[] = [];
  if (co.circle !== null) {
    const a = arc_record(co.circle, 0.0, TWO_PI, true, null, cam, f_nu, rect_rows, "image", "silhouette");
    if (a === null) behind_any = true;
    else outline_arcs.push(a);
  }
  for (const arc of co.cap_arcs) {
    const a = arc_record(arc.circle, arc.theta0, arc.theta1, arc.full, null, cam, f_nu, rect_rows, "image", arc.which, arc.back);
    if (a === null) behind_any = true;
    else outline_arcs.push(a);
  }
  // per light: construction points, terminator, cast-shadow conics
  const terminator_out = new Map<string, StageBTerminatorItem[]>();
  const shadow_arcs = new Map<string, ArcRecord[]>();
  for (const [lid, cd] of obj.curved ?? new Map<string, CurvedData>()) {
    for (const [nm, X] of cd.points) add_point(nm, X);
    const items: StageBTerminatorItem[] = [];
    for (const t of cd.terminator) {
      if (t.segment !== undefined) {
        const it: TerminatorSegment = { segment: terminator_segment_names(oid, t, cd.silhouette), segment_h: null, keep: false };
        items.push(it);
        fill(it, t.segment[0], t.segment[1]);
      } else {
        const ca = t.circle_arc;
        const a = arc_record(ca.circle, ca.theta0, ca.theta1, ca.full, null, cam, f_nu, rect_rows, "image", ca.which);
        if (a === null) behind_any = true;
        else items.push(a);
      }
    }
    terminator_out.set(lid, items);
    const arcs: ArcRecord[] = [];
    if (cd.outline !== null) {
      for (const piece of cd.outline.pieces) {
        if (!("conic_arc" in piece)) continue;
        const ca = piece.conic_arc;
        const [lo, hi] = ccw_range(ca.theta0, ca.theta1);
        const a = arc_record(ca.circle, lo, hi, hi - lo >= TWO_PI - 1e-12, ca.T, cam, f_nu, rect_rows, "shadow", ca.which);
        if (a === null) behind_any = true;
        else arcs.push(a);
      }
    }
    shadow_arcs.set(lid, arcs);
  }
  const groups: StageBTerminatorItem[][] = [outline_arcs, ...terminator_out.values(), ...shadow_arcs.values()];
  for (const group of groups) {
    for (const a of group) {
      if ("segment" in a) continue;
      behind_any = behind_any || a.near_cut;
      sampled_any = sampled_any || a.sampled;
    }
  }
  const image_h = X4.map((X) => project(cam, X));
  const behind = X4.map((X) => nu(cam, X) < 0.0);
  if (behind.some((b) => b)) behind_any = true;
  if (behind_any) warnings.push(make_warning("POINT_BEHIND_CAMERA", [oid]));
  if (sampled_any) warnings.push(make_warning("CONIC_SAMPLED", [oid]));
  Object.assign(rec, {
    point_names: names,
    world: X4.map((X) => v3(X)),
    image_h,
    depth: image_h.map((x) => x[2]),
    behind,
    gen_edges,
    outline_arcs,
    terminator: terminator_out,
    shadow_arcs,
    camera_inside: co.camera_inside,
    form_faces: [],
    form_polygons: [],
  });
}

/** Stage B of several curved objects: `stage_b_object` for each (the Python batch is a performance device whose
 * equality with this loop is a tested precondition, contract §5.4.4 (6)). */
export function stage_b_objects(objs: readonly (ObjectRecord & { curved?: Map<string, CurvedData> })[], recs: Partial<CurvedStageB>[],
  cam: CameraRecord, tol: number, warnings: Warning[]): void {
  objs.forEach((obj, i) => stage_b_object(obj, recs[i] as Partial<CurvedStageB>, cam, tol, warnings));
}

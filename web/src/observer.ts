/**
 * The observer view of M9 (spec-v0.2 §2, §3, §4.2 last bullet; contract §5.6) — the pure, DOM-free part, unit-tested
 * (`web/test/observer.test.ts`). The three.js part that draws these arrays is `observer3d.ts`.
 *
 * In M9 the board is not a state: it is derived per frame from the drawing camera's record (§5.6.2): `E = rec.C`,
 * `f = rec.forward`, `D` fixed per loaded scene ({@link observer_D}), `Q = E + D·f`, the frame's corners the canvas
 * corners unprojected to depth `D` (`unproject_to_plane`), the pivot `P` and `R` the M7 orbit's `target` and `distance`,
 * `g = R − D`. Everything here only reads the camera record, the document, the scene and stage A; nothing is written
 * back (the switch-off identity of §5.6.0).
 */

import { camera_matrix, plane_equation, resolve_picture_plane, unproject_to_plane } from "castplane";
import type { Camera, CameraRecord, GeometryDocument, Scene, StageA, Vec2, Vec3 } from "castplane";

import { D_MAX_M, D_MIN_M, DEFAULT_D_M, R_MAX_M, R_MIN_M, bboxCentre } from "./rig.js";

// ------------------------------------------------------------------------------------------------ constants

/** `D` of a scene whose camera is not of the `picture_plane` form (§5.6.2). */
export const OBSERVER_D_M = DEFAULT_D_M;
/** Vertical field of view of the observer camera (spec-v0.2 §3). */
export const OBSERVER_FOV_DEG = 40;
export const OBSERVER_NEAR_M = 0.05;
export const OBSERVER_FAR_M = 2000;
/** Initial direction of the observer camera (§5.6.4). */
export const OBSERVER_AZ0_DEG = 55;
export const OBSERVER_EL0_DEG = 28;
export const OBSERVER_EL_MIN_DEG = -5;
export const OBSERVER_EL_MAX_DEG = 85;
export const OBSERVER_AZ_DEG_PER_PX = 0.4;
export const OBSERVER_EL_DEG_PER_PX = 0.3;
export const OBSERVER_ZOOM_K = 0.001;
export const OBSERVER_DIST_MIN_M = 4;
export const OBSERVER_DIST_MAX_M = 60;
export const OBSERVER_PINCH_MIN_PX = 10;
/** Framing: `dist = clamp(FRAMING_K · max radius, FRAMING_MIN_M, FRAMING_MAX_M)` (§5.6.4). */
export const FRAMING_K = 2.3;
export const FRAMING_MIN_M = 6;
export const FRAMING_MAX_M = 60;
/** The drawing on the frame sits this much in front of the board, along the rays (§5.6.5). */
export const DRAWING_OFFSET_M = 0.012;
/** The frustum lines continue to `E + FRUSTUM_EXTEND·(corner − E)` (dotted). */
export const FRUSTUM_EXTEND = 1.9;
/** The board patch: half-extents `max(PATCH_K·W_m, PATCH_MIN_W_M)` × `max(PATCH_K·H_m, PATCH_MIN_H_M)` (the demo's). */
export const PATCH_K = 0.62;
export const PATCH_MIN_W_M = 3.2;
export const PATCH_MIN_H_M = 2.4;
/** Samples of one SVG arc and of one full ellipse drawn on the frame. */
export const ARC_SAMPLES = 32;
export const ELLIPSE_SAMPLES = 72;
/** A directional light's ray `S → S + max(DIRECTIONAL_RAY_K·|P − S|, DIRECTIONAL_RAY_MIN_M)·l̂` (`l̂` towards the
 * light: it passes the vertex and continues; a vertex on the receiver still gets a visible ray). */
export const DIRECTIONAL_RAY_K = 1.5;
export const DIRECTIONAL_RAY_MIN_M = 1;

const DEG = Math.PI / 180;

// ------------------------------------------------------------------------------------------------ vector helpers

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const cross = (p: readonly number[], q: readonly number[]): Vec3 =>
  [p[1]! * q[2]! - p[2]! * q[1]!, p[2]! * q[0]! - p[0]! * q[2]!, p[0]! * q[1]! - p[1]! * q[0]!];
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));
const unit = (p: readonly number[]): Vec3 => mul(p, 1 / len(p));
const copy3 = (p: readonly number[]): Vec3 => [p[0]!, p[1]!, p[2]!];
const lerp3 = (p: readonly number[], q: readonly number[], t: number): Vec3 => add(p, mul(sub(q, p), t));

function clamp(x: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, x));
}

// ------------------------------------------------------------------------------------------------ loading (§5.6.2)

/** The scene centre: the centre of stage A's `bbox` (§5.7.7). */
export function scene_centre(A: Pick<StageA, "bbox">): Vec3 {
  return bboxCentre(A.bbox);
}

/** `D` of the observer for a loaded scene (§5.6.2): the `picture_plane` distance clamped into `[0.5, 12]` m without a
 * notice, else {@link OBSERVER_D_M}. Fixed per loaded scene, so orbiting never makes the board jump. */
export function observer_D(cam: Camera, canvas_mm: readonly number[]): number {
  if (cam.picture_plane === undefined) return OBSERVER_D_M;
  const rec0 = camera_matrix(cam, canvas_mm);
  return clamp(rec0.picture_plane!.distance, D_MIN_M, D_MAX_M);
}

/**
 * The camera block handed to `orbit_from_camera` and "Reset camera" (§5.6.2). A `picture_plane` block becomes its
 * resolved target-form block (roll kept) with `target = E + t·f`, `t = clamp(f·(P_scene − E), 0.8, 40)`: the orbit
 * pivot then lies at the scene centre's depth and the picture is unchanged. Any other block is returned as is.
 */
export function orbit_camera(cam: Camera, P_scene: readonly number[]): Camera {
  if (cam.picture_plane === undefined) return cam;
  const [tcam, roll, info] = resolve_picture_plane(cam);
  const E = copy3(tcam.position), f = info.normal;
  const t = clamp(dot(f, sub(P_scene, E)), R_MIN_M, R_MAX_M);
  return {
    position: E, target: add(E, mul(f, t)), roll_deg: roll, focal_length_mm: cam.focal_length_mm,
    frame_mm: [cam.frame_mm[0], cam.frame_mm[1]], shift_mm: [cam.shift_mm[0], cam.shift_mm[1]], near_m: cam.near_m,
  };
}

// ------------------------------------------------------------------------------------------------ the board (§5.6.2)

export interface Board {
  /** The eye (read-only). */
  E: Vec3;
  /** Unit, eye → board (`rec.forward`). */
  f: Vec3;
  /** Frame right / up: the rows `r'`, `u'` of `rec.R`. */
  r: Vec3;
  u: Vec3;
  D: number;
  /** The principal point (foot of the perpendicular from `E`). */
  Q: Vec3;
  /** The pivot (the orbit's target), its depth `R` (the orbit distance) and `g = R − D`. */
  P: Vec3;
  R: number;
  g: number;
  /** Frame corners: the canvas corners `(−W/2, −H/2), (W/2, −H/2), (W/2, H/2), (−W/2, H/2)` at depth `D`. */
  corners: Vec3[];
  /** Frame size on the board (m): `canvas_mm · D / (focal · s)`. */
  frame_m: Vec2;
  /** The translucent patch around `Q` (same corner order). */
  patch: Vec3[];
  /** `plane_equation(f, −f·Q)` (spec-v0.2 §4.3). */
  equation: string;
}

/** The canvas corners in the order of {@link Board.corners}. */
export function canvas_corners(canvas_mm: readonly number[]): Vec2[] {
  const w = canvas_mm[0]! / 2, h = canvas_mm[1]! / 2;
  return [[-w, -h], [w, -h], [w, h], [-w, h]];
}

/** The read-only board of the current drawing camera (§5.6.2); `pivot` is the M7 orbit (`target`, `distance`). */
export function derive_board(rec: CameraRecord, pivot: { target: readonly number[]; distance: number }, D: number): Board {
  const E = copy3(rec.C), f = copy3(rec.forward), r = copy3(rec.R[0]), u = copy3(rec.R[1]);
  const Q = add(E, mul(f, D));
  const k = rec.K[0][0];
  const frame_m: Vec2 = [rec.canvas_mm[0] * D / k, rec.canvas_mm[1] * D / k];
  const corners = unproject_to_plane(rec, canvas_corners(rec.canvas_mm), D);
  const pw = Math.max(PATCH_K * frame_m[0], PATCH_MIN_W_M), ph = Math.max(PATCH_K * frame_m[1], PATCH_MIN_H_M);
  const patch = ([[-1, -1], [1, -1], [1, 1], [-1, 1]] as const).map(([a, b]) => add(Q, add(mul(r, a * pw), mul(u, b * ph))));
  const R = pivot.distance;
  return {
    E, f, r, u, D, Q, P: copy3(pivot.target), R, g: R - D, corners, frame_m, patch,
    equation: plane_equation(f, -dot(f, Q)),
  };
}

/** The frustum (§5.6.5): `E` to each frame corner (solid) and on to `E + 1.9·(corner − E)` (dotted). */
export function frustum(board: Board): { solid: [Vec3, Vec3][]; dotted: [Vec3, Vec3][] } {
  return {
    solid: board.corners.map((c) => [board.E, c]),
    dotted: board.corners.map((c) => [c, add(board.E, mul(sub(c, board.E), FRUSTUM_EXTEND))]),
  };
}

// ------------------------------------------------------------------------------------------------ the drawing on the frame

/** Line styles of the drawing on the frame (the SVG writer's groups, §2.10). */
export type LineStyle = "horizon" | "objects" | "objects_back" | "hidden" | "terminator" | "cast_shadow" | "ray_LP" | "ray_FQ" | "ray_PQ";
/** Fill styles of the drawing on the frame. */
export type FillStyle = "form_shadow" | "cast_shadow";

/** One straight piece of the drawing: canvas mm (`uv`, clipped to the canvas) and world (`world`, on the frame). */
export interface ArtSegment {
  layer: string;
  style: LineStyle;
  uv: [Vec2, Vec2];
  world: [Vec3, Vec3];
}

/** One filled polygon of the drawing (clipped to the canvas). */
export interface ArtFill {
  layer: string;
  style: FillStyle;
  uv: Vec2[];
  world: Vec3[];
}

export interface LineArt {
  segments: ArtSegment[];
  fills: ArtFill[];
}

/** An unclipped drawable in canvas mm: an open polyline (`closed = false`), a closed outline, or a fill. */
interface Drawable {
  layer: string;
  style: LineStyle | FillStyle;
  kind: "line" | "fill";
  pts: Vec2[];
  closed: boolean;
}

/**
 * Points of an SVG elliptical arc (SVG 1.1 F.6.5, endpoint → centre parameterisation) in the document's v-up frame: the
 * SVG writer negates the rotation and flips the sweep for its y-down frame, a reflection, so the arc's own flags apply
 * unchanged here. The first and last points are exactly `start` and `end`.
 */
export function sample_arc(a: { start: readonly number[]; end: readonly number[]; rx: number; ry: number; rotation_deg: number;
  large_arc: number; sweep: number }, n = ARC_SAMPLES): Vec2[] {
  const x1 = a.start[0]!, y1 = a.start[1]!, x2 = a.end[0]!, y2 = a.end[1]!;
  let rx = Math.abs(a.rx), ry = Math.abs(a.ry);
  if ((x1 === x2 && y1 === y2) || rx === 0 || ry === 0) return [[x1, y1], [x2, y2]];
  const phi = a.rotation_deg * DEG, c = Math.cos(phi), s = Math.sin(phi);
  const dx2 = (x1 - x2) / 2, dy2 = (y1 - y2) / 2;
  const x1p = c * dx2 + s * dy2, y1p = -s * dx2 + c * dy2;
  const lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
  if (lam > 1) {
    rx *= Math.sqrt(lam);
    ry *= Math.sqrt(lam);
  }
  const fa = Math.trunc(a.large_arc) !== 0, fs = Math.trunc(a.sweep) !== 0;
  const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
  const den = rx * rx * y1p * y1p + ry * ry * x1p * x1p;
  const coef = (fa !== fs ? 1 : -1) * Math.sqrt(Math.max(0, num / den));
  const cxp = (coef * rx * y1p) / ry, cyp = (-coef * ry * x1p) / rx;
  const cx = c * cxp - s * cyp + (x1 + x2) / 2, cy = s * cxp + c * cyp + (y1 + y2) / 2;
  const ang = (ux: number, uy: number, vx: number, vy: number): number => Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const ux = (x1p - cxp) / rx, uy = (y1p - cyp) / ry, vx = (-x1p - cxp) / rx, vy = (-y1p - cyp) / ry;
  const t1 = ang(1, 0, ux, uy);
  let dt = ang(ux, uy, vx, vy);
  if (!fs && dt > 0) dt -= 2 * Math.PI;
  else if (fs && dt < 0) dt += 2 * Math.PI;
  const out: Vec2[] = [[x1, y1]];
  for (let i = 1; i < n; i++) {
    const t = t1 + (dt * i) / n;
    out.push([cx + rx * c * Math.cos(t) - ry * s * Math.sin(t), cy + rx * s * Math.cos(t) + ry * c * Math.sin(t)]);
  }
  out.push([x2, y2]);
  return out;
}

/** Points of a full ellipse drawable (v-up frame; closed by the caller). */
export function sample_ellipse(e: { centre: readonly number[]; rx: number; ry: number; rotation_deg: number }, n = ELLIPSE_SAMPLES): Vec2[] {
  const phi = e.rotation_deg * DEG, c = Math.cos(phi), s = Math.sin(phi);
  const out: Vec2[] = [];
  for (let i = 0; i < n; i++) {
    const t = (2 * Math.PI * i) / n;
    const a = e.rx * Math.cos(t), b = e.ry * Math.sin(t);
    out.push([e.centre[0]! + a * c - b * s, e.centre[1]! + a * s + b * c]);
  }
  return out;
}

type ConicLike = { polylines?: readonly (readonly (readonly number[])[])[]; arcs?: readonly Parameters<typeof sample_arc>[0][];
  ellipses?: readonly Parameters<typeof sample_ellipse>[0][] };

function conic_drawables(entry: ConicLike, layer: string, style: LineStyle, out: Drawable[]): void {
  for (const pl of entry.polylines ?? []) {
    if (pl.length >= 2) out.push({ layer, style, kind: "line", pts: pl.map((p) => [p[0]!, p[1]!] as Vec2), closed: false });
  }
  for (const a of entry.arcs ?? []) out.push({ layer, style, kind: "line", pts: sample_arc(a), closed: false });
  for (const e of entry.ellipses ?? []) out.push({ layer, style, kind: "line", pts: sample_ellipse(e), closed: true });
}

const v2 = (p: readonly number[]): Vec2 => [p[0]!, p[1]!];

/** A straight edge's pieces by its runs (`s` = image fraction) when hidden lines are on, else one piece. */
function edge_pieces(seg: readonly (readonly number[])[], runs: readonly { s: readonly number[]; visible: boolean }[],
  hidden_lines: boolean, solid: LineStyle, layer: string, out: Drawable[]): void {
  const a = v2(seg[0]!), b = v2(seg[1]!);
  if (!hidden_lines || runs.length === 0) {
    out.push({ layer, style: solid, kind: "line", pts: [a, b], closed: false });
    return;
  }
  const at = (t: number): Vec2 => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  for (const run of runs) {
    out.push({ layer, style: run.visible ? solid : "hidden", kind: "line", pts: [at(run.s[0]!), at(run.s[1]!)], closed: false });
  }
}

/**
 * The document's drawables (§5.6.5) in canvas mm, per SVG layer: `edges[].segment`, `outlines[]` generators and conics,
 * `form_shadow[].polygons` and terminators, `shadows[].polygons` (fill and outline) and conics, the construction rays
 * `LP` / `FQ` / `PQ` of every light and receiver, and `horizon.segment`. Text, markers and dots are not drawn.
 */
export function document_drawables(doc: GeometryDocument): Drawable[] {
  const out: Drawable[] = [];
  if (doc.horizon.segment !== null) out.push({ layer: "horizon", style: "horizon", kind: "line", pts: doc.horizon.segment.map(v2), closed: false });
  for (const e of doc.edges) {
    if (e.segment === null) continue;
    edge_pieces(e.segment, e.runs, doc.hidden_lines, e.back ? "objects_back" : "objects", "objects", out);
  }
  for (const o of doc.outlines) {
    for (const g of o.generators) {
      if (g.segment !== null) edge_pieces(g.segment, g.runs, doc.hidden_lines, g.back ? "objects_back" : "objects", "objects", out);
    }
    for (const c of o.conics) conic_drawables(c, "objects", c.back === true ? "objects_back" : "objects", out);
  }
  for (const fs of doc.form_shadow) {
    for (const poly of fs.polygons ?? []) {
      if (poly.length >= 3) out.push({ layer: "form_shadow", style: "form_shadow", kind: "fill", pts: poly.map(v2), closed: true });
    }
    for (const t of fs.terminator) {
      if ("segment" in t && !("conic" in t)) {
        for (const seg of t.polylines) out.push({ layer: "form_shadow", style: "terminator", kind: "line", pts: seg.map(v2), closed: false });
      } else {
        conic_drawables(t as ConicLike, "form_shadow", "terminator", out);
      }
    }
  }
  for (const sh of doc.shadows) {
    for (const poly of sh.polygons ?? []) {
      if (poly.length < 3) continue;
      out.push({ layer: "cast_shadow", style: "cast_shadow", kind: "fill", pts: poly.map(v2), closed: true });
      out.push({ layer: "cast_shadow", style: "cast_shadow", kind: "line", pts: poly.map(v2), closed: true });
    }
    for (const c of sh.conics) conic_drawables(c, "cast_shadow", "cast_shadow", out);
  }
  const blocks = doc.constructions !== undefined ? Object.values(doc.constructions) : [doc.construction];
  for (const blk of blocks) {
    const segs = [...blk.segments, ...Object.values(blk.per_receiver).flatMap((p) => p.segments)];
    for (const seg of segs) {
      if ((seg.kind === "LP" || seg.kind === "FQ" || seg.kind === "PQ") && seg.points?.length === 2) {
        out.push({ layer: "construction", style: `ray_${seg.kind}`, kind: "line", pts: seg.points.map(v2), closed: false });
      }
    }
  }
  return out;
}

/** Liang–Barsky: the part of segment `a b` inside the rectangle `|u| ≤ hw, |v| ≤ hh`, or `null`. */
export function clip_segment(a: Vec2, b: Vec2, hw: number, hh: number): [Vec2, Vec2] | null {
  let t0 = 0, t1 = 1;
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const edges: [number, number][] = [[-dx, a[0] + hw], [dx, hw - a[0]], [-dy, a[1] + hh], [dy, hh - a[1]]];
  for (const [p, q] of edges) {
    if (p === 0) {
      if (q < 0) return null;
    } else {
      const t = q / p;
      if (p < 0) {
        if (t > t1) return null;
        if (t > t0) t0 = t;
      } else {
        if (t < t0) return null;
        if (t < t1) t1 = t;
      }
    }
  }
  const at = (t: number): Vec2 => (t === 0 ? a : t === 1 ? b : [a[0] + dx * t, a[1] + dy * t]);
  return [at(t0), at(t1)];
}

/** Sutherland–Hodgman: the polygon clipped to the rectangle `|u| ≤ hw, |v| ≤ hh` (may be empty). */
export function clip_polygon(pts: readonly Vec2[], hw: number, hh: number): Vec2[] {
  const planes: [(p: Vec2) => number][] = [[(p) => p[0] + hw], [(p) => hw - p[0]], [(p) => p[1] + hh], [(p) => hh - p[1]]];
  let poly: Vec2[] = [...pts];
  for (const [d] of planes) {
    if (poly.length === 0) break;
    const next: Vec2[] = [];
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i]!, q = poly[(i + 1) % poly.length]!;
      const dp = d(p), dq = d(q);
      if (dp >= 0) next.push(p);
      if ((dp >= 0) !== (dq >= 0)) {
        const t = dp / (dp - dq);
        next.push([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t]);
      }
    }
    poly = next;
  }
  return poly;
}

/**
 * The drawing on the frame (§5.6.5): the document's drawables of the visible `layers`, clipped to the canvas rectangle
 * and mapped by `unproject_to_plane(rec, uv, D − 0.012)` (towards the eye along the rays, so the copy registers exactly
 * as seen from `E`). `doc` is only read.
 */
export function line_art(doc: GeometryDocument, rec: CameraRecord, D: number, layers: ReadonlySet<string>): LineArt {
  const hw = rec.canvas_mm[0] / 2, hh = rec.canvas_mm[1] / 2;
  const depth = D - DRAWING_OFFSET_M;
  const W = (p: Vec2): Vec3 => unproject_to_plane(rec, p, depth);
  const segments: ArtSegment[] = [], fills: ArtFill[] = [];
  for (const d of document_drawables(doc)) {
    if (!layers.has(d.layer)) continue;
    if (d.kind === "fill") {
      const uv = clip_polygon(d.pts, hw, hh);
      if (uv.length >= 3) fills.push({ layer: d.layer, style: d.style as FillStyle, uv, world: uv.map(W) });
      continue;
    }
    const n = d.pts.length;
    const m = d.closed ? n : n - 1;
    for (let i = 0; i < m; i++) {
      const c = clip_segment(d.pts[i]!, d.pts[(i + 1) % n]!, hw, hh);
      if (c !== null) segments.push({ layer: d.layer, style: d.style as LineStyle, uv: c, world: [W(c[0]), W(c[1])] });
    }
  }
  return { segments, fills };
}

// ------------------------------------------------------------------------------------------------ vertex rays (§5.6.5)

export interface VertexRays {
  /** Sight lines `E → P` of the focus object's vertices. */
  sight: [Vec3, Vec3][];
  /** Their crossings `P′` with the board (only when `f·(P − E) > near_m`). */
  crossings: Vec3[];
  /** Light rays `L → S` through the vertex (a directional light: `S → S + max(1.5·|P − S|, 1 m)·l̂`). */
  light: [Vec3, Vec3][];
  /** Shadow points `S`. */
  shadows: Vec3[];
  /** Sight lines `E → S` and their crossings `S′`. */
  shadow_sight: [Vec3, Vec3][];
  shadow_crossings: Vec3[];
}

function escape_re(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function crossing(board: Pick<Board, "E" | "f" | "D">, X: Vec3, near_m: number): Vec3 | null {
  const dep = dot(board.f, sub(X, board.E));
  return dep > near_m ? add(board.E, mul(sub(X, board.E), board.D / dep)) : null;
}

/**
 * The vertex rays (§5.6.5, checkbox "視線"): focus object `scene.objects[0]`, its vertices `<obj>.v<k>` (document
 * `points[*].world`, `k` ascending); light rays from `construction.rays` (`lights[0]`) entries `["L", <vertex>]`.
 */
export function vertex_rays(doc: GeometryDocument, scene: Scene, board: Pick<Board, "E" | "f" | "D">, near_m: number): VertexRays {
  const out: VertexRays = { sight: [], crossings: [], light: [], shadows: [], shadow_sight: [], shadow_crossings: [] };
  const focus = scene.objects[0];
  if (focus === undefined) return out;
  const re = new RegExp(`^${escape_re(focus.id)}\\.v(\\d+)$`);
  const names = Object.keys(doc.points).filter((n) => re.test(n))
    .sort((a, b) => Number(re.exec(a)![1]) - Number(re.exec(b)![1]));
  const world = (name: string): Vec3 | null => {
    const p = doc.points[name];
    return p !== undefined && "world" in p ? copy3(p.world) : null;
  };
  for (const n of names) {
    const P = world(n)!;
    out.sight.push([board.E, P]);
    const c = crossing(board, P, near_m);
    if (c !== null) out.crossings.push(c);
  }
  const light = scene.lights[0];
  if (light === undefined) return out;
  const vertices = new Set(names);
  for (const [kind, name] of doc.construction.rays) {
    if (kind !== "L" || !vertices.has(name)) continue;
    const S = world(`${name}.shadow.${light.id}`);
    if (S === null) continue;
    const P = world(name)!;
    if (light.type === "point") {
      out.light.push([copy3(light.position as Vec3), S]);
    } else {
      const k = Math.max(DIRECTIONAL_RAY_K * len(sub(P, S)), DIRECTIONAL_RAY_MIN_M);
      out.light.push([S, add(S, mul(unit(light.direction as Vec3), k))]);
    }
    out.shadows.push(S);
    out.shadow_sight.push([board.E, S]);
    const c = crossing(board, S, near_m);
    if (c !== null) out.shadow_crossings.push(c);
  }
  return out;
}

// ------------------------------------------------------------------------------------------------ observer camera (§5.6.4)

/** The observer camera: the camera sits at `target + dist·(sin az·cos el, −cos az·cos el, sin el)`. */
export interface ObserverView {
  target: Vec3;
  dist: number;
  az_deg: number;
  el_deg: number;
}

export function initial_view(): ObserverView {
  return { target: [0, 0, 0], dist: 12, az_deg: OBSERVER_AZ0_DEG, el_deg: OBSERVER_EL0_DEG };
}

/** The observer camera's position and basis (`f` towards the target, `r = f × z` normalised, `u = r × f`). */
export function observer_basis(view: ObserverView): { pos: Vec3; r: Vec3; u: Vec3; f: Vec3 } {
  const az = view.az_deg * DEG, el = view.el_deg * DEG;
  const dir: Vec3 = [Math.sin(az) * Math.cos(el), -Math.cos(az) * Math.cos(el), Math.sin(el)];
  const pos = add(view.target, mul(dir, view.dist));
  const f = mul(dir, -1);
  const r = unit(cross(f, [0, 0, 1]));
  return { pos, r, u: cross(r, f), f };
}

/** The pixel position of `X` in a `W × H` px observer view (`null` behind the near plane). */
export function observer_project(view: ObserverView, W: number, H: number, X: readonly number[]): Vec2 | null {
  return observer_project_with(observer_basis(view), W, H, X);
}

/** {@link observer_project} with a precomputed {@link observer_basis}. */
export function observer_project_with(basis: { pos: Vec3; r: Vec3; u: Vec3; f: Vec3 }, W: number, H: number, X: readonly number[]): Vec2 | null {
  const { pos, r, u, f } = basis;
  const d = sub(X, pos);
  const z = dot(d, f);
  if (z < OBSERVER_NEAR_M) return null;
  const fpx = H / 2 / Math.tan((OBSERVER_FOV_DEG / 2) * DEG);
  return [W / 2 + (dot(d, r) / z) * fpx, H / 2 - (dot(d, u) / z) * fpx];
}

/** Left drag in the observer pane (total or incremental `dx, dy` px from `view0`). */
export function orbit_view(view0: ObserverView, dx: number, dy: number): ObserverView {
  return { ...view0, az_deg: view0.az_deg - dx * OBSERVER_AZ_DEG_PER_PX,
    el_deg: clamp(view0.el_deg + dy * OBSERVER_EL_DEG_PER_PX, OBSERVER_EL_MIN_DEG, OBSERVER_EL_MAX_DEG) };
}

/** Wheel zoom: `dist ← clamp(dist · exp(0.001 · deltaY), 4, 60)`. */
export function zoom_view(view: ObserverView, deltaY: number): ObserverView {
  return { ...view, dist: clamp(view.dist * Math.exp(OBSERVER_ZOOM_K * deltaY), OBSERVER_DIST_MIN_M, OBSERVER_DIST_MAX_M) };
}

/** Two-finger pinch from the state at its start: `dist ← clamp(dist₀ · d₀ / max(d, 10 px), 4, 60)`. */
export function pinch_view(view0: ObserverView, d0: number, d: number): ObserverView {
  return { ...view0, dist: clamp((view0.dist * d0) / Math.max(d, OBSERVER_PINCH_MIN_PX), OBSERVER_DIST_MIN_M, OBSERVER_DIST_MAX_M) };
}

/** The points framing uses (§5.6.4): `E`, `Q`, the scene centre, every point light, the centre's ground point
 * (`z = 0`) and the four frame corners (directional lights contribute nothing). */
export function framing_points(board: Pick<Board, "E" | "Q" | "corners">, scene: Scene, centre: readonly number[]): Vec3[] {
  const pts: Vec3[] = [board.E, board.Q, copy3(centre)];
  for (const l of scene.lights) if (l.type === "point") pts.push(copy3(l.position as Vec3));
  pts.push([centre[0]!, centre[1]!, 0], ...board.corners);
  return pts;
}

/** Framing (§5.6.4): keep `(az, el)`, target = the centroid of `points`, `dist = clamp(2.3 · max radius, 6, 60)`. */
export function frame_view(view: ObserverView, points: readonly (readonly number[])[]): ObserverView {
  let c: Vec3 = [0, 0, 0];
  for (const p of points) c = add(c, p);
  c = mul(c, 1 / Math.max(1, points.length));
  let rad = 0;
  for (const p of points) rad = Math.max(rad, len(sub(p, c)));
  return { ...view, target: c, dist: clamp(FRAMING_K * rad, FRAMING_MIN_M, FRAMING_MAX_M) };
}

// ------------------------------------------------------------------------------------------------ hit-test helpers

/** Distance (px) from `p` to the segment `a b`. */
export function dist_point_segment(p: Vec2, a: Vec2, b: Vec2): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy;
  const t = l2 === 0 ? 0 : clamp(((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2, 0, 1);
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** The index of the nearest projected point within `tol` px of `p` (`null` entries are skipped), or −1. */
export function hit_point(points: readonly (Vec2 | null)[], p: Vec2, tol: number): number {
  let best = -1, bd = tol;
  points.forEach((q, i) => {
    if (q === null) return;
    const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
    if (d <= bd) {
      bd = d;
      best = i;
    }
  });
  return best;
}

/** The first of `anchors` whose projection lies inside the `W × H` pane shrunk by `margin` px (else the first's). */
export function first_inside(basis: { pos: Vec3; r: Vec3; u: Vec3; f: Vec3 }, W: number, H: number, anchors: readonly Vec3[],
  margin: readonly [number, number, number, number]): Vec2 | null {
  let first: Vec2 | null | undefined;
  for (const X of anchors) {
    const p = observer_project_with(basis, W, H, X);
    if (first === undefined) first = p;
    if (p !== null && p[0] >= margin[0] && p[0] <= W - margin[1] && p[1] >= margin[2] && p[1] <= H - margin[3]) return p;
  }
  return first ?? null;
}

/** Whether `p` is within `tol` px of the projected polyline `pts` (consecutive pairs; `null` breaks it). */
export function hit_polyline(pts: readonly (Vec2 | null)[], p: Vec2, tol: number): boolean {
  for (let i = 0; i + 1 < pts.length; i++) {
    const a = pts[i], b = pts[i + 1];
    if (a !== null && a !== undefined && b !== null && b !== undefined && dist_point_segment(p, a, b) <= tol) return true;
  }
  return false;
}

// ------------------------------------------------------------------------------------------------ labels

export function fmt2(x: number): string {
  const t = x.toFixed(2);
  return t === "-0.00" ? "0.00" : t;
}

/** One label of the observer: its world anchor, text and (the equation) further anchors tried in order when `at`
 * falls outside the pane. */
export interface BoardLabel {
  id: string;
  at: Vec3;
  text: string;
  alt?: Vec3[];
}

/** The labels of the observer (§5.6.5): world anchor and text; the equation sits at a corner of the patch (the
 * top-left one, else the first other corner inside the pane). */
export function board_labels(board: Board): BoardLabel[] {
  return [
    { id: "E", at: board.E, text: `E（讀數）(${board.E.map(fmt2).join(", ")})` },
    { id: "D", at: lerp3(board.E, board.Q, 0.5), text: `D = ${fmt2(board.D)} m` },
    { id: "g", at: lerp3(board.Q, board.P, 0.5), text: `板子離場景 g = ${fmt2(board.g)} m` },
    { id: "pivot", at: board.P, text: "旋轉中心" },
    { id: "equation", at: board.patch[3]!, text: board.equation, alt: [board.patch[2]!, board.patch[0]!, board.patch[1]!] },
  ];
}

/**
 * Plane projection of shadows (port of `castplane/shadow.py`; spec §5.2, §5.3, §5.7; contract §2.3, §2.5).
 *
 * Oriented homogeneous 4-vectors with the canonical forms of contract §2.1. `sources` entries are tagged objects
 * (contract §5.4.2): `{kind: "vertex", index}` (input vertex index) / `{kind: "ground", i, j}` /
 * `{kind: "dir", i, j}` / `{kind: "arc", k}` / `{kind: "bounds", k, a, b}` / `{kind: "bounds", k, anchor: true}`
 * (M4, contract §5.1.3.3).
 */

import { mesh_from_faces } from "./mesh.js";
import type { Mesh } from "./mesh.js";
import { pymod } from "./pyfloat.js";
import { radians } from "./transform.js";
import type { Mat4, Vec3, Vec4 } from "./types.js";

/** Contract §2.5: at-infinity sub-edges span < 90°; `ceil(delta / 60°)` steps. */
export const ARC_STEP_DEG = 60.0;

export type VertexTag = { kind: "vertex"; index: number };
export type GroundTag = { kind: "ground"; i: Source; j: Source };
/** A bounds-clip row (contract §5.1.3.3): a crossing `{k, a, b}` of two sources, or the anchor `(b_k, 1)` of row `k`. */
export interface BoundsCrossing<S> { kind: "bounds"; k: number; a: S; b: S; anchor?: undefined }
export interface BoundsAnchor { kind: "bounds"; k: number; anchor: true }
export type BoundsSource<S> = BoundsCrossing<S> | BoundsAnchor;
export type Source = VertexTag | GroundTag | { kind: "dir"; i: Source; j: Source } | { kind: "arc"; k: number } | BoundsCrossing<Source>
  | BoundsAnchor;
export type Origin = number | { kind: "ground"; i: number; j: number };

function dot4(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number)
    + (a[2] as number) * (b[2] as number) + (a[3] as number) * (b[3] as number);
}

/** `M · X` with every entry a left-to-right 4-term sum. */
export function mat4_vec(M: readonly (readonly number[])[], X: readonly number[]): Vec4 {
  return [dot4(M[0] as readonly number[], X), dot4(M[1] as readonly number[], X), dot4(M[2] as readonly number[], X),
    dot4(M[3] as readonly number[], X)];
}

/** Spec §5.2: `M = (πᵀL) I₄ − L πᵀ`, so that `S = M P` is the shadow of `P` on `π`. */
export function shadow_matrix(pi: readonly number[], L: readonly number[]): Mat4 {
  const piL = dot4(pi, L);
  const M = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]] as Mat4;
  for (let i = 0; i < 4; i++) {
    for (let j = 0; j < 4; j++) M[i][j] = piL * (i === j ? 1 : 0) - (L[i] as number) * (pi[j] as number);
  }
  return M;
}

/** Spec §5.3: foot `Q = (n·n) X − (n·x + w d)(n, 0)` of `X` on `π = (n, d)`. */
export function foot(pi: readonly number[], X: readonly number[]): Vec4 {
  const n0 = pi[0] as number, n1 = pi[1] as number, n2 = pi[2] as number, d = pi[3] as number;
  const nn = n0 * n0 + n1 * n1 + n2 * n2;
  const s = (n0 * (X[0] as number) + n1 * (X[1] as number) + n2 * (X[2] as number)) + (X[3] as number) * d;
  return [nn * (X[0] as number) - s * n0, nn * (X[1] as number) - s * n1, nn * (X[2] as number) - s * n2,
    nn * (X[3] as number) - s * 0.0];
}

/** Contract §2.3: the `w` component of `M P`, `w_S = (πᵀL) w_P − w_L (πᵀP)`. */
export function shadow_w(pi: readonly number[], L: readonly number[], P: readonly number[]): number {
  const piL = dot4(pi, L);
  return piL * (P[3] as number) - (L[3] as number) * dot4(pi, P);
}

/**
 * Contract §2.3 ground clip of a closed homogeneous loop to `πᵀX >= 0`: vertices with `πᵀX < −tol` are dropped,
 * crossings inserted on the plane (`X = (1 − t) P_a + t P_b`). Returns `[clipped, sources, any_below]`.
 */
export function clip_loop_to_plane(points4: readonly (readonly number[])[], pi: readonly number[], tol = 0.0,
  sources?: readonly Source[]): [Vec4[], Source[], boolean] {
  const P = points4.map((p) => [p[0], p[1], p[2], p[3]] as Vec4);
  const n = P.length;
  const src: readonly Source[] = sources ?? P.map((_p, i): VertexTag => ({ kind: "vertex", index: i }));
  if (n === 0) return [[], [], false];
  const f = P.map((p) => dot4(p, pi));
  const keep = f.map((v) => v >= -tol);
  if (keep.every((k) => k)) return [P.map((p) => [...p] as Vec4), [...src], false];
  const out_pts: Vec4[] = [];
  const out_src: Source[] = [];
  for (let a = 0; a < n; a++) {
    const b = (a + 1) % n;
    if (keep[a]) {
      out_pts.push([...(P[a] as Vec4)] as Vec4);
      out_src.push(src[a] as Source);
    }
    if (keep[a] !== keep[b]) {
      const fa = f[a] as number, fb = f[b] as number;
      if ((keep[a] && Math.abs(fa) <= tol) || (keep[b] && Math.abs(fb) <= tol)) continue;
      let t = fa !== fb ? fa / (fa - fb) : 0.0;
      t = Math.min(1.0, Math.max(0.0, t));
      const Pa = P[a] as Vec4, Pb = P[b] as Vec4;
      out_pts.push([0, 1, 2, 3].map((k) => (1.0 - t) * (Pa[k] as number) + t * (Pb[k] as number)) as Vec4);
      out_src.push({ kind: "ground", i: src[a] as Source, j: src[b] as Source });
    }
  }
  return [out_pts, out_src, true];
}

function is_ground(s: Source): s is GroundTag {
  return typeof s === "object" && s.kind === "ground";
}

/**
 * Contract §2.3 ground clip of a whole closed mesh: the part of the solid with `πᵀX >= 0` as a new closed mesh, cut
 * faces capped with outward normal `−n`. Returns `[clipped_mesh, origins]` (`origins[k]` = original vertex index or
 * `{kind: "ground", i, j}` with `i < j`). Throws when the clipped surface is not a closed manifold.
 */
export function clip_mesh_to_plane(mesh: Mesh, pi: readonly number[], tol = 0.0): [Mesh, Origin[]] {
  const V = mesh.vertices;
  const V4: Vec4[] = V.map((v) => [v[0], v[1], v[2], 1.0]);
  const kept = V4.map((v) => dot4(v, pi) >= -tol);
  const new_vertices: Vec3[] = [];
  const origins: Origin[] = [];
  const index_of = new Map<number, number>();
  V.forEach((v, k) => {
    if (kept[k]) {
      index_of.set(k, new_vertices.length);
      new_vertices.push([v[0], v[1], v[2]]);
      origins.push(k);
    }
  });
  const crossing = new Map<string, number>();
  const faces_out: number[][] = [];
  for (const face of mesh.faces) {
    const [P, src] = clip_loop_to_plane(face.map((v) => V4[v] as Vec4), pi, tol,
      face.map((v): VertexTag => ({ kind: "vertex", index: v })));
    if (P.length < 3) continue;
    const poly: number[] = [];
    P.forEach((row, r) => {
      const s = src[r] as Source;
      if (is_ground(s)) {
        const i = (s.i as VertexTag).index, j = (s.j as VertexTag).index;
        const lo = Math.min(i, j), hi = Math.max(i, j);
        const key = `${lo},${hi}`;
        if (!crossing.has(key)) {
          crossing.set(key, new_vertices.length);
          new_vertices.push([row[0] / row[3], row[1] / row[3], row[2] / row[3]]);
          origins.push({ kind: "ground", i: lo, j: hi });
        }
        poly.push(crossing.get(key) as number);
      } else {
        poly.push(index_of.get((s as VertexTag).index) as number);
      }
    });
    faces_out.push(poly);
  }
  // cap faces: the reversed boundary edges chained into loops (lowest-index unused outgoing edge)
  const directed = new Set<string>();
  const directed_list: [number, number][] = [];
  for (const poly of faces_out) {
    for (let a = 0; a < poly.length; a++) {
      const e: [number, number] = [poly[a] as number, poly[(a + 1) % poly.length] as number];
      const key = `${e[0]},${e[1]}`;
      if (!directed.has(key)) {
        directed.add(key);
        directed_list.push(e);
      }
    }
  }
  const boundary = directed_list.filter(([p, q]) => !directed.has(`${q},${p}`)).map(([p, q]) => [q, p] as [number, number]);
  boundary.sort((x, y) => x[0] - y[0] || x[1] - y[1]);
  const outgoing = new Map<number, number[]>();
  boundary.forEach(([a], idx) => {
    let l = outgoing.get(a);
    if (l === undefined) outgoing.set(a, (l = []));
    l.push(idx);
  });
  const used = new Array<boolean>(boundary.length).fill(false);
  const cap_loops: number[][] = [];
  for (let start = 0; start < boundary.length; start++) {
    if (used[start]) continue;
    const loop: number[] = [];
    let cur = start;
    for (;;) {
      used[cur] = true;
      const [a, b] = boundary[cur] as [number, number];
      loop.push(a);
      let nxt = -1;
      for (const cand of outgoing.get(b) ?? []) {
        if (!used[cand]) {
          nxt = cand;
          break;
        }
      }
      if (nxt < 0) break;
      cur = nxt;
    }
    if (loop.length >= 3) cap_loops.push(loop);
  }
  faces_out.push(...cap_faces(cap_loops, new_vertices, [pi[0] as number, pi[1] as number, pi[2] as number]));
  if (faces_out.length === 0) {
    return [{ vertices: [], edges: [], faces: [], face_normals: [], edge_faces: [], edge_flipped: [], vertex_names: [] }, []];
  }
  const names = origins.map((o) => (typeof o === "number" ? `v${o}` : `x${o.i}_${o.j}`));
  return [mesh_from_faces(new_vertices, faces_out, names), origins];
}

function norm3(v: readonly number[]): number {
  return Math.sqrt((v[0] as number) * (v[0] as number) + (v[1] as number) * (v[1] as number) + (v[2] as number) * (v[2] as number));
}

function cross(a: readonly number[], b: readonly number[]): Vec3 {
  const a0 = a[0] as number, a1 = a[1] as number, a2 = a[2] as number;
  const b0 = b[0] as number, b1 = b[1] as number, b2 = b[2] as number;
  return [a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0];
}

function plane_basis(n_in: readonly number[]): [Vec3, Vec3] {
  const nl = norm3(n_in);
  const n: Vec3 = [(n_in[0] as number) / nl, (n_in[1] as number) / nl, (n_in[2] as number) / nl];
  const helper: Vec3 = Math.abs(n[2]) < 0.9 ? [0.0, 0.0, 1.0] : [1.0, 0.0, 0.0];
  let e1 = cross(helper, n);
  const l1 = norm3(e1);
  e1 = [e1[0] / l1, e1[1] / l1, e1[2] / l1];
  return [e1, cross(n, e1)];
}

/** Shoelace area of a closed 2-D loop (sequential sum, a sign test only, §5.4.4 (3)). */
function signed_area(uv: readonly [number, number][]): number {
  let s = 0;
  const k = uv.length;
  for (let i = 0; i < k; i++) {
    const p = uv[i] as [number, number], q = uv[(i + 1) % k] as [number, number];
    s += p[0] * q[1] - q[0] * p[1];
  }
  return 0.5 * s;
}

function point_in_loop(p: readonly number[], uv: readonly [number, number][]): boolean {
  let inside = false;
  const k = uv.length;
  const px = p[0] as number, py = p[1] as number;
  for (let i = 0; i < k; i++) {
    const [x0, y0] = uv[i] as [number, number];
    const [x1, y1] = uv[(i + 1) % k] as [number, number];
    if ((y0 > py) !== (y1 > py)) {
      const xint = x0 + (py - y0) * (x1 - x0) / (y1 - y0);
      if (px < xint) inside = !inside;
    }
  }
  return inside;
}

/** Turn the chained boundary loops of the ground clip into cap faces (holes bridged into their outer loop). */
function cap_faces(cap_loops: number[][], vertices: readonly Vec3[], n: Vec3): number[][] {
  if (cap_loops.length === 0) return [];
  const [e1, e2] = plane_basis(n);
  const dot = (v: Vec3, e: Vec3): number => v[0] * e[0] + v[1] * e[1] + v[2] * e[2];
  const uv_of = cap_loops.map((loop) => loop.map((v) => [dot(vertices[v] as Vec3, e1), dot(vertices[v] as Vec3, e2)] as [number, number]));
  const areas = uv_of.map(signed_area);
  const outer: number[] = [], holes: number[] = [];
  areas.forEach((a, k) => (a < 0.0 ? outer : holes).push(k));
  const polys = new Map<number, number[]>(outer.map((k) => [k, [...(cap_loops[k] as number[])]]));
  const orphan: number[][] = [];
  for (const h of holes) {
    const uvh = uv_of[h] as [number, number][];
    const p = uvh[0] as [number, number];
    const containing = outer.filter((k) => point_in_loop(p, uv_of[k] as [number, number][]));
    if (containing.length === 0) {
      orphan.push([...(cap_loops[h] as number[])]);
      continue;
    }
    let k = containing[0] as number;
    for (const idx of containing) if (Math.abs(areas[idx] as number) < Math.abs(areas[k] as number)) k = idx;
    const uvk = uv_of[k] as [number, number][];
    let bi = 0, bj = 0, best = Infinity;
    for (let i = 0; i < uvk.length; i++) {
      for (let j = 0; j < uvh.length; j++) {
        const dx = (uvk[i] as [number, number])[0] - (uvh[j] as [number, number])[0];
        const dy = (uvk[i] as [number, number])[1] - (uvh[j] as [number, number])[1];
        const d = dx * dx + dy * dy;
        if (d < best) {
          best = d;
          bi = i;
          bj = j;
        }
      }
    }
    const hole = cap_loops[h] as number[];
    const rotated = [...hole.slice(bj), ...hole.slice(0, bj)];
    const poly = polys.get(k) as number[];
    const anchor = (cap_loops[k] as number[])[bi] as number;
    const pos = poly.indexOf(anchor);
    polys.set(k, [...poly.slice(0, pos + 1), ...rotated, rotated[0] as number, anchor, ...poly.slice(pos + 1)]);
  }
  return [...outer.map((k) => polys.get(k) as number[]), ...orphan];
}

/** Contract §2.5 direction vertex `D = (1 − t*) S_a + t* S_b`, `t* = w_a / (w_a − w_b)`, `w := 0`, unit in the plane. */
function direction_vertex(S_a: Vec4, w_a: number, S_b: Vec4, w_b: number, fallback_from: Vec4 | null,
  last_resort: Vec4 | null = null): Vec4 {
  const t = w_a / (w_a - w_b);
  let D: Vec4 = [0, 1, 2, 3].map((k) => (1.0 - t) * (S_a[k] as number) + t * (S_b[k] as number)) as Vec4;
  D[3] = 0.0;
  let norm = norm3(D);
  if (!(norm > 1e-300 && Number.isFinite(norm))) {
    norm = 0.0;
    if (fallback_from !== null) {
      const [S_f, w_f] = w_a > 0.0 ? [S_a, w_a] : [S_b, w_b];
      if (w_f > 0.0) {
        D = [S_f[0] / w_f - fallback_from[0], S_f[1] / w_f - fallback_from[1], S_f[2] / w_f - fallback_from[2], 0.0];
        norm = norm3(D);
      }
    }
    // contract §5.1.2: the last resort is (e1, 0) of the receiver frame ((1, 0, 0, 0) on the ground)
    if (!(norm > 1e-300 && Number.isFinite(norm))) return last_resort === null ? [1.0, 0.0, 0.0, 0.0] : [...last_resort] as Vec4;
  }
  return [D[0] / norm, D[1] / norm, D[2] / norm, D[3] / norm];
}

/** Recover the finite light foot `F = foot(π, L)` from `M` (fallback only). */
function light_foot_from_matrix(M: Mat4, pi: readonly number[]): Vec4 | null {
  const n0 = pi[0] as number, n1 = pi[1] as number, n2 = pi[2] as number;
  const nn = n0 * n0 + n1 * n1 + n2 * n2;
  if (nn <= 0.0 || pi[3] !== 0.0) return null;
  const nv: Vec4 = [n0, n1, n2, 0.0];
  const piL = M[3][3];
  const Mn = mat4_vec(M, nv);
  const L: Vec4 = [0, 1, 2, 3].map((k) => (piL * (nv[k] as number) - (Mn[k] as number)) / nn) as Vec4;
  const F = foot(pi, L);
  if (Math.abs(F[3]) <= 1e-300) return null;
  return [F[0] / F[3], F[1] / F[3], F[2] / F[3], F[3] / F[3]];
}

export interface ShadowLoop {
  vertices: Vec4[];
  unbounded: boolean;
  sources: Source[];
  below_ground: boolean;
}

/**
 * Shadow polygon of one silhouette loop (spec §5.2 / §5.7 row 4, contract §2.5): ground clip with `tol_clip`,
 * `S_i = M P_i`, edges with both `w_S <= tol` dropped, outgoing / incoming direction vertices, and the CCW
 * arc-at-infinity subdivision into `ceil(delta / 60°)` steps.
 *
 * M4 (contract §5.1.2): `frame = [e1, e2]` (`receiver_frame`) is given for every receiver other than the unbounded
 * ground; the arc at infinity is then swept counter-clockwise about `n` in `(e1, e2)` coordinates and the last-resort
 * direction is `(e1, 0)`. `F` is the light foot on the receiver (the "edge through the light" fallback; recovered from
 * `M` when the receiver is the ground). `frame === null` runs the literal v2 code (byte identity on the ground).
 */
export function shadow_loop(points4: readonly (readonly number[])[], M: Mat4, pi: readonly number[], tol = 0.0,
  tol_clip?: number | null, frame: readonly [Vec3, Vec3] | null = null, F_in: readonly number[] | null = null): ShadowLoop {
  const tc = tol_clip === undefined || tol_clip === null ? tol : tol_clip;
  const [P, src, below] = clip_loop_to_plane(points4, pi, tc);
  const n = P.length;
  const empty: ShadowLoop = { vertices: [], unbounded: false, sources: [], below_ground: below };
  if (n === 0) return empty;
  const S = P.map((p) => mat4_vec(M, p));
  const w = S.map((s) => s[3]);
  const finite = w.map((x) => x > tol);
  if (!finite.some((f) => f)) return empty;
  let F: Vec4 | null;
  let last_resort: Vec4 | null = null;
  let e1: Vec3 = [1, 0, 0], e2: Vec3 = [0, 1, 0];
  if (frame === null) {
    F = light_foot_from_matrix(M, pi); // only used when an edge passes through the light
  } else {
    e1 = frame[0];
    e2 = frame[1];
    F = null;
    if (F_in !== null) {
      const f3 = F_in[3] as number;
      F = Math.abs(f3) > 1e-300 ? [(F_in[0] as number) / f3, (F_in[1] as number) / f3, (F_in[2] as number) / f3, f3 / f3] : null;
    }
    last_resort = [e1[0], e1[1], e1[2], 0.0];
  }
  const start = finite.indexOf(true);
  const order: number[] = [];
  for (let k = 0; k < n; k++) order.push((start + k) % n);
  const verts: Vec4[] = [];
  const sources: Source[] = [];
  const kinds: string[] = [];
  for (let idx = 0; idx < n; idx++) {
    const a = order[idx] as number;
    const b = order[(idx + 1) % n] as number;
    const wa = w[a] as number, wb = w[b] as number;
    if (finite[a]) {
      verts.push(S[a] as Vec4);
      sources.push(src[a] as Source);
      kinds.push("finite");
      if (!finite[b]) {
        verts.push(direction_vertex(S[a] as Vec4, wa, S[b] as Vec4, wb, F, last_resort));
        sources.push({ kind: "dir", i: src[a] as Source, j: src[b] as Source });
        kinds.push("out");
      }
    } else if (finite[b]) {
      verts.push(direction_vertex(S[a] as Vec4, wa, S[b] as Vec4, wb, F, last_resort));
      sources.push({ kind: "dir", i: src[a] as Source, j: src[b] as Source });
      kinds.push("in");
    }
  }
  const out_verts: Vec4[] = [];
  const out_sources: Source[] = [];
  const m = verts.length;
  let unbounded = false;
  for (let k = 0; k < m; k++) {
    out_verts.push(verts[k] as Vec4);
    out_sources.push(sources[k] as Source);
    if (kinds[k] === "out") {
      unbounded = true;
      const nxt = (k + 1) % m;
      if (kinds[nxt] !== "in") throw new Error("an outgoing direction must be followed by an incoming one");
      const d_out = verts[k] as Vec4, d_in = verts[nxt] as Vec4;
      let th0: number, th1: number;
      if (frame === null) { // the ground: literal v2 expressions (contract §5.1.2 [decision])
        th0 = Math.atan2(d_out[1], d_out[0]);
        th1 = Math.atan2(d_in[1], d_in[0]);
      } else { // counter-clockwise about n in the receiver frame (e1, e2)
        th0 = Math.atan2(dot3(d_out, e2), dot3(d_out, e1));
        th1 = Math.atan2(dot3(d_in, e2), dot3(d_in, e1));
      }
      let delta = pymod(th1 - th0, 2.0 * Math.PI);
      if (!Number.isFinite(delta) || delta <= 1e-12) delta = 2.0 * Math.PI;
      const steps = Math.max(1, Math.ceil(delta / radians(ARC_STEP_DEG) - 1e-12));
      for (let s = 1; s < steps; s++) {
        const th = th0 + delta * s / steps;
        if (frame === null) {
          out_verts.push([Math.cos(th), Math.sin(th), 0.0, 0.0]);
        } else {
          const c = Math.cos(th), sn = Math.sin(th);
          out_verts.push([c * e1[0] + sn * e2[0], c * e1[1] + sn * e2[1], c * e1[2] + sn * e2[2], 0.0]);
        }
        out_sources.push({ kind: "arc", k: s - 1 });
      }
    }
  }
  return { vertices: out_verts, unbounded, sources: out_sources, below_ground: below };
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

function max_abs(v: readonly number[]): number {
  let m = 0;
  for (const x of v) m = Math.max(m, Math.abs(x));
  return m;
}

// ---------------------------------------------------------------------------
// M4: bounded receivers (contract §5.1.2, §5.1.3)
// ---------------------------------------------------------------------------

/** Contract §5.1.2: `[e1, e2]` with `e1 × e2 = n`: `e1 = normalize(z × n)`, `e2 = n × e1`; when `|z × n| <= 1e-9`:
 * `e1 = (1, 0, 0)`. For the ground this is `(x, y)`. */
export function receiver_frame(n_in: readonly number[]): [Vec3, Vec3] {
  const n: Vec3 = [n_in[0] as number, n_in[1] as number, n_in[2] as number];
  const c: Vec3 = [-n[1], n[0], 0.0]; // z × n
  const nrm = norm3(c);
  const e1: Vec3 = nrm <= 1e-9 ? [1.0, 0.0, 0.0] : [c[0] / nrm, c[1] / nrm, c[2] / nrm];
  return [e1, cross(n, e1)];
}

/** Contract §5.1.2: `Ψ (k, 4)`, row `k` is `ψ_k = (m_k, −m_k · b_k)` with the unit inward normal
 * `m_k = n × (b_{k+1} − b_k) / |b_{k+1} − b_k|` of the counter-clockwise (about `n`) bounds polygon. */
export function bounds_functionals(bounds: readonly (readonly number[])[], n: readonly number[]): Vec4[] {
  const k = bounds.length;
  const out: Vec4[] = [];
  for (let i = 0; i < k; i++) {
    const b = bounds[i] as readonly number[], b1 = bounds[(i + 1) % k] as readonly number[];
    const E: Vec3 = [(b1[0] as number) - (b[0] as number), (b1[1] as number) - (b[1] as number), (b1[2] as number) - (b[2] as number)];
    const c = cross(n, E);
    const l = norm3(E);
    const m: Vec3 = [c[0] / l, c[1] / l, c[2] / l];
    out.push([m[0], m[1], m[2], -dot3(m, b)]);
  }
  return out;
}

/** Merge consecutive (cyclic) projectively equal vertices, keeping the first (contract §5.1.3.3 rule 5). */
function merge_equal_neighbours<T>(P: Vec4[], src: T[]): [Vec4[], T[]] {
  if (P.length < 2) return [P, src];
  const N = P.map((v) => {
    const m = max_abs(v);
    return m > 0.0 ? v.map((x) => x / m) : v;
  });
  const diff = (a: readonly number[], b: readonly number[]): number => {
    let d = 0;
    for (let i = 0; i < 4; i++) d = Math.max(d, Math.abs((a[i] as number) - (b[i] as number)));
    return d;
  };
  const keep_p: Vec4[] = [P[0] as Vec4], keep_s: T[] = [src[0] as T], keep_n: number[][] = [N[0] as number[]];
  for (let i = 1; i < P.length; i++) {
    if (diff(N[i] as number[], keep_n[keep_n.length - 1] as number[]) <= 1e-9) continue;
    keep_p.push(P[i] as Vec4);
    keep_s.push(src[i] as T);
    keep_n.push(N[i] as number[]);
  }
  while (keep_p.length >= 2 && diff(keep_n[keep_n.length - 1] as number[], keep_n[0] as number[]) <= 1e-9) {
    keep_p.pop();
    keep_s.pop();
    keep_n.pop();
  }
  return [keep_p, keep_s];
}

/**
 * Contract §5.1.3.3: Sutherland–Hodgman of an oriented homogeneous shadow polygon (direction vertices `w = 0` and
 * arcs at infinity included) against `ψ_k · X >= 0` in row order, with the band rule, the zero-vector filter, the
 * anchor rule, the "fewer than three" stop and the final merge / `w <= 0` drop / sliver test. Returns
 * `[points4', sources']`, empty when the polygon misses the plate. Literal port of `shadow.clip_polygon_bounds`
 * (including the own-crossing band of a direction, `|ψ_k · D| <= 1e-9 max|D|`, of the M4 implementation notes).
 */
export function clip_polygon_bounds<S>(points4: readonly (readonly number[])[], sources: readonly S[],
  psi: readonly (readonly number[])[], bounds: readonly (readonly number[])[], tol: number): [Vec4[], (S | BoundsSource<S>)[]] {
  type T = S | BoundsSource<S>;
  let P: Vec4[] = points4.map((v) => [v[0], v[1], v[2], v[3]] as Vec4);
  let src: T[] = [...sources];
  if (P.length < 3) return [[], []];
  let scale = 0;
  for (const v of P) scale = Math.max(scale, max_abs(v));
  scale = Math.max(scale, 0.0);
  for (let k = 0; k < psi.length; k++) {
    if (P.length < 3) return [[], []];
    const row = psi[k] as readonly number[];
    const f = P.map((X) => dot4(row, X));
    const w = P.map((X) => Math.abs(X[3]));
    const keep = f.map((fi, i) => ((w[i] as number) !== 0.0 ? fi >= -tol * (w[i] as number) : fi >= 0.0));
    const band = f.map((fi, i) => ((w[i] as number) !== 0.0 ? Math.abs(fi) <= tol * (w[i] as number)
      : Math.abs(fi) <= 1e-9 * max_abs(P[i] as Vec4)));
    const n = P.length;
    let out: Vec4[] = [], out_src: T[] = [];
    if (keep.every((x) => x)) {
      out = [...P];
      out_src = [...src];
    } else {
      for (let a = 0; a < n; a++) {
        const b = (a + 1) % n;
        if (keep[a]) {
          out.push(P[a] as Vec4);
          out_src.push(src[a] as T);
        }
        if (keep[a] !== keep[b]) {
          if ((keep[a] && band[a]) || (keep[b] && band[b])) continue;
          const fa = f[a] as number, fb = f[b] as number;
          const Pa = P[a] as Vec4, Pb = P[b] as Vec4;
          const X = [0, 1, 2, 3].map((i) => (fa * (Pb[i] as number) - fb * (Pa[i] as number)) / (fa - fb)) as Vec4;
          if (!(max_abs(X) > 1e-12 * Math.max(scale, max_abs(Pa), max_abs(Pb)))) continue; // antipodal directions
          out.push(X);
          out_src.push({ kind: "bounds", k, a: src[a] as S, b: src[b] as S });
        }
      }
    }
    // anchor rule (exactness for arcs at infinity spanning >= 180 degrees)
    if (out.length >= 2) {
      const anchored: Vec4[] = [], anchored_src: T[] = [];
      const m = out.length;
      const bk = bounds[k] as readonly number[];
      for (let a = 0; a < m; a++) {
        anchored.push(out[a] as Vec4);
        anchored_src.push(out_src[a] as T);
        const Da = out[a] as Vec4, Db = out[(a + 1) % m] as Vec4;
        if (Da[3] === 0.0 && Db[3] === 0.0 && m >= 2) {
          const on_a = Math.abs(dot4(row, Da)) <= 1e-9 * max_abs(Da);
          const on_b = Math.abs(dot4(row, Db)) <= 1e-9 * max_abs(Db);
          if (on_a && on_b && dot3(Da, Db) < 0.0) {
            anchored.push([bk[0] as number, bk[1] as number, bk[2] as number, 1.0]);
            anchored_src.push({ kind: "bounds", k, anchor: true });
          }
        }
      }
      out = anchored;
      out_src = anchored_src;
    }
    P = out;
    src = out_src;
    if (P.length < 3) return [[], []];
  }
  [P, src] = merge_equal_neighbours(P, src);
  const kept_v: Vec4[] = [], kept_s: T[] = [];
  P.forEach((v, i) => {
    if (v[3] > 0.0) {
      kept_v.push(v);
      kept_s.push(src[i] as T);
    }
  });
  if (kept_v.length < 3) return [[], []];
  const X = kept_v.map((v) => [v[0] / v[3], v[1] / v[3], v[2] / v[3]] as Vec3);
  const tot: Vec3 = [0, 0, 0];
  let perimeter = 0;
  for (let i = 0; i < X.length; i++) {
    const a = X[i] as Vec3, b = X[(i + 1) % X.length] as Vec3;
    const c = cross(a, b);
    tot[0] += c[0];
    tot[1] += c[1];
    tot[2] += c[2];
    perimeter += norm3([b[0] - a[0], b[1] - a[1], b[2] - a[2]]);
  }
  const area = 0.5 * norm3(tot);
  if (area <= tol * perimeter) return [[], []];
  return [kept_v, kept_s];
}

/** Contract §5.1.3.2: the silhouette loop of a bounded receiver used as a caster (an opaque plate): its whole
 * boundary, in the stored order when `πᵀL > tol`, reversed when `< −tol`; `null` when edge-on (`|πᵀL| <= tol`).
 * Returns `[loop4, vertex_ids]` with `vertex_ids[i]` the index `k` of `b<k>`. */
export function plate_loop(bounds: readonly (readonly number[])[], pi: readonly number[], L: readonly number[],
  tol: number): [Vec4[], number[]] | null {
  const piL = dot4(pi, L);
  if (Math.abs(piL) <= tol) return null;
  let ids = bounds.map((_b, i) => i);
  if (piL < 0.0) ids = ids.reverse();
  return [ids.map((i) => {
    const b = bounds[i] as readonly number[];
    return [b[0] as number, b[1] as number, b[2] as number, 1.0] as Vec4;
  }), ids];
}

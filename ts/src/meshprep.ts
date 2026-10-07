/**
 * Mesh preprocessing of the `mesh` object type (port of `castplane/meshprep.py`; spec §9 網格匯入; contract §5.2.3 –
 * §5.2.5, M7 phase 2 §5.4.14).
 *
 * Core module: no file access, every step deterministic and order-defined. The entry point is
 *
 *     preprocess_mesh(data, scale, weld_tolerance, smooth_angle_deg) -> [mesh, triangles, fallback, smooth_groups, warnings]
 *
 * with the steps of contract §5.2.3 in this order: scale -> weld -> degenerate faces -> adjacency / manifold /
 * orientation -> (triangles) -> coplanar merge -> edge classification. A mesh that is not a closed, consistently
 * orientable manifold takes the per-face fallback of §5.2.5 (`fallback_mesh`). Every tolerance is relative to
 * `scale_A = max(1, max extent of the bounding box of scale·vertices)` (`mesh_scale`).
 *
 * Port notes (contract §5.4.4, the §5.4 implementation notes): the weld is the reference O(27·n) loop of §5.2.3 step 2
 * (the numpy fast path is a performance device that is result-identical to it, so `fast` is accepted and ignored);
 * every numpy reduction is written as the sequential sum of the Python text (`einsum("ij,ij->i")` 3-term dot products
 * left to right, `cumsum` in triangle order); tuples are arrays.
 */

import { make_warning } from "./errors.js";
import type { Warning } from "./errors.js";
import { face_normals_newell, mesh_from_faces, triangulate_faces } from "./mesh.js";
import type { Mesh } from "./mesh.js";
import type { Origin } from "./shadow.js";
import { radians } from "./transform.js";
import type { Vec3 } from "./types.js";

/** Coplanar-merge angle (contract §5.2.3 step 6). */
export const COPLANAR_TOL_RAD = 1e-3;
/** Default weld tolerance in metres, after `scale` (contract §5.2.1). */
export const WELD_TOLERANCE_DEFAULT = 1e-6;
/** Default smoothing angle in degrees (contract §5.2.1). */
export const SMOOTH_ANGLE_DEFAULT = 30.0;
/** Construction rays per (object, light, receiver) (contract §5.2.4). */
export const MESH_MAX_RAYS = 64;
/** Dimensionless band of the smooth-edge test (contract §5.2.3 step 7). */
export const SMOOTH_BAND = 1e-9;
/** `|w| > INSIDE_WINDING` means inside (generalised winding number, contract §5.2.3 step 8). */
export const INSIDE_WINDING = 0.75;
/** Newell-norm threshold of a degenerate face, relative to `scale_A²` (contract §5.2.3 step 3). */
export const DEGENERATE_REL = 1e-12;
/** Zero-volume threshold of a component, relative to `scale_A³` (contract §5.2.3 step 5). */
export const VOLUME_REL = 1e-12;

/** The validated `objects[i].data` of a mesh object (contract §5.2.1). */
export interface MeshInput {
  vertices: readonly (readonly number[])[];
  faces: readonly (readonly number[])[];
  smooth_groups?: readonly number[] | null;
}

/** The record of `build_adjacency` (contract §5.2.3 step 5). */
export interface Adjacency {
  edges: [number, number][];
  edge_faces: number[][];
  edge_dirs: number[][];
  face_edges: number[][];
  face_edge_at: number[][];
  counts: number[];
  manifold: boolean;
  consistent: boolean;
}

export type Triangle = [number, number, number];
export type PrepResult = [Mesh, Triangle[], boolean, number[], Warning[]];
export type PrepResultScaled = [Mesh, Triangle[], boolean, number[], Warning[], number];

function as_vec3(v: readonly number[]): Vec3 {
  return [v[0] as number, v[1] as number, v[2] as number];
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

/** numpy's `np.cross` (`(a1·b2 − a2·b1, a2·b0 − a0·b2, a0·b1 − a1·b0)`). */
function cross3(a: readonly number[], b: readonly number[]): Vec3 {
  const a0 = a[0] as number, a1 = a[1] as number, a2 = a[2] as number;
  const b0 = b[0] as number, b1 = b[1] as number, b2 = b[2] as number;
  return [a1 * b2 - a2 * b1, a2 * b0 - a0 * b2, a0 * b1 - a1 * b0];
}

function sub3(a: readonly number[], b: readonly number[]): Vec3 {
  return [(a[0] as number) - (b[0] as number), (a[1] as number) - (b[1] as number), (a[2] as number) - (b[2] as number)];
}

/** `scale_A = max(1, max extent of the axis-aligned bounding box of V)` (contract §5.2.3 step 1). */
export function mesh_scale(V: readonly (readonly number[])[]): number {
  if (V.length === 0) return 1.0;
  let ext = -Infinity;
  for (let k = 0; k < 3; k++) {
    let lo = Infinity, hi = -Infinity;
    for (const v of V) {
      const x = v[k] as number;
      if (x < lo) lo = x;
      if (x > hi) hi = x;
    }
    if (hi - lo > ext) ext = hi - lo;
  }
  return Math.max(1.0, ext);
}

// ---------------------------------------------------------------------------
// step 2: weld
// ---------------------------------------------------------------------------

const OFFSETS: readonly (readonly [number, number, number])[] = (() => {
  const out: [number, number, number][] = [];
  for (const dx of [-1, 0, 1]) for (const dy of [-1, 0, 1]) for (const dz of [-1, 0, 1]) out.push([dx, dy, dz]);
  return out;
})();

/** Cell indices are exact integers in Python (`math.floor` of a float is an `int`); in JavaScript `c + d` stays exact
 * only below 2^52, so the string keys of larger cells go through `BigInt` (the same decimal integer either way). */
const EXACT_INT = 2 ** 52;

function cell_part(c: number, d: number): string {
  return Math.abs(c) < EXACT_INT ? String(c + d) : (BigInt(c) + BigInt(d)).toString();
}

/** `x/τ + 0.5` per coordinate (the cell key is its floor), or `null` for exact welding (`τ = 0`, or a `τ` so small that
 * some `x/τ` is not finite: the M5 note "Weld details"). */
function cell_quotients(V: readonly (readonly number[])[], tol: number): number[][] | null {
  if (!(tol > 0.0)) return null;
  const q = V.map((v) => [(v[0] as number) / tol + 0.5, (v[1] as number) / tol + 0.5, (v[2] as number) / tol + 0.5]);
  for (const row of q) for (const x of row) if (!Number.isFinite(x)) return null;
  return q;
}

/**
 * One exact number key per cell such that neighbour cells stay neighbours (the key encoding of the Python fast path,
 * `_compressed_cell_keys`): per axis the distinct cell indices are renumbered with gaps capped at 2 (`|Δ| <= 1` is
 * preserved exactly; a computed gap of distinct integral floats is `>= 2` whenever the true gap is), offset by 1, and
 * combined as `(c0·R + c1)·R + c2` with `R = max + 2`, so the 27 neighbours are `key + (dx·R + dy)·R + dz` without
 * carry. Only an encoding of the reference loop's dictionary keys: the visiting order and the lowest-index rule are
 * unchanged. `null` when `R³` would leave the exact integers (more than ~10^5 distinct cells on one axis): the string
 * keys are used then. That fallback is reachable only by a direct `weld_map` call: a validated mesh has at most
 * `MESH_MAX_VERTICES` = 50 000 vertices, so `R <= 2·50 000 + 1` and `R³ < 2^53` (`ts/test/meshprep.test.ts` forces it).
 */
function compressed_cells(cells: readonly (readonly number[])[]): [number[], number] | null {
  const cols: number[][] = [];
  let R = 0;
  for (let a = 0; a < 3; a++) {
    const u = [...new Set(cells.map((c) => c[a] as number))].sort((x, y) => x - y);
    const index = new Map<number, number>();
    let c = 1;
    u.forEach((x, k) => {
      if (k > 0) c += Math.min(x - (u[k - 1] as number), 2);
      index.set(x, c);
    });
    R = Math.max(R, c + 2);
    cols.push(cells.map((cell) => index.get(cell[a] as number) as number));
  }
  if (R * R * R >= 2 ** 53) return null;
  const c0 = cols[0] as number[], c1 = cols[1] as number[], c2 = cols[2] as number[];
  return [c0.map((x, i) => (x * R + (c1[i] as number)) * R + (c2[i] as number)), R];
}

function weld_reference(V: readonly (readonly number[])[], tol: number): number[] {
  const n = V.length;
  const rep = new Array<number>(n);
  const q = cell_quotients(V, tol);
  if (q === null) { // tau = 0: exact equality of the float triple (-0.0 == 0.0: String(-0) is "0")
    const seen = new Map<string, number>();
    for (let i = 0; i < n; i++) {
      const p = V[i] as readonly number[];
      const key = `${p[0] as number},${p[1] as number},${p[2] as number}`;
      const r = seen.get(key);
      if (r === undefined) {
        seen.set(key, i);
        rep[i] = i;
      } else {
        rep[i] = r;
      }
    }
    return rep;
  }
  const cells = q.map((qi) => [Math.floor(qi[0] as number), Math.floor(qi[1] as number), Math.floor(qi[2] as number)]);
  const compressed = compressed_cells(cells);
  // the cell dictionary of the reference loop, keyed by the compressed number (or by the decimal string)
  let keys: (number | string)[];
  let neighbour: (i: number, k: number) => number | string = () => 0;
  if (compressed !== null) {
    keys = compressed[0];
  } else {
    keys = cells.map(([cx, cy, cz]) => `${cell_part(cx as number, 0)},${cell_part(cy as number, 0)},${cell_part(cz as number, 0)}`);
    neighbour = (i, k) => {
      const [cx, cy, cz] = cells[i] as number[];
      const [dx, dy, dz] = OFFSETS[k] as readonly [number, number, number];
      return `${cell_part(cx as number, dx)},${cell_part(cy as number, dy)},${cell_part(cz as number, dz)}`;
    };
  }
  const table = new Map<number | string, number[]>();
  const shift = compressed === null ? null : OFFSETS.map(([dx, dy, dz]) => (dx * compressed[1] + dy) * compressed[1] + dz);
  for (let i = 0; i < n; i++) {
    const v = V[i] as readonly number[];
    const x = v[0] as number, y = v[1] as number, z = v[2] as number;
    let best = -1;
    const base = keys[i] as number | string;
    for (let k = 0; k < 27; k++) {
      const lst = table.get(shift !== null ? (base as number) + (shift[k] as number) : neighbour(i, k));
      if (lst === undefined) continue;
      for (const r of lst) {
        if (best >= 0 && r >= best) continue;
        const w = V[r] as readonly number[];
        if (Math.abs((w[0] as number) - x) <= tol && Math.abs((w[1] as number) - y) <= tol && Math.abs((w[2] as number) - z) <= tol) best = r;
      }
    }
    if (best < 0) {
      const lst = table.get(base);
      if (lst === undefined) table.set(base, [i]);
      else lst.push(i);
      best = i;
    }
    rep[i] = best;
  }
  return rep;
}

/**
 * Representative **input index** of every vertex under the weld rule of contract §5.2.3 step 2: vertex `i` joins the
 * representative with the lowest input index among those registered in the 27 cells around its cell whose max-norm
 * distance is `<= τ`, else it becomes a representative. `fast` is accepted for the Python signature: the port always
 * runs the reference loop (the numpy fast path is result-identical to it by `tests/test_meshprep.py`).
 */
export function weld_map(V: readonly (readonly number[])[], tol: number, _fast = true): number[] {
  return weld_reference(V, tol);
}

/** Faces as lists of integers, optionally renumbered through `index` (an `(n,)` map). */
export function prepare_faces(faces: readonly (readonly number[])[], index?: readonly number[] | null): number[][] {
  if (index === undefined || index === null) return faces.map((f) => f.map((v) => Math.trunc(v)));
  return faces.map((f) => f.map((v) => index[Math.trunc(v)] as number));
}

/** Weld (contract §5.2.3 step 2) -> `[W, faces_w, index]`: `W` the representatives' own coordinates numbered in order
 * of first appearance, `faces_w` the faces renumbered, `index` the map input vertex -> welded vertex. */
export function weld_vertices(V: readonly (readonly number[])[], faces: readonly (readonly number[])[], tol: number,
  fast = true): [Vec3[], number[][], number[]] {
  const rep = weld_map(V, tol, fast);
  const n = V.length;
  const number = new Array<number>(n).fill(-1);
  const W: Vec3[] = [];
  for (let i = 0; i < n; i++) {
    if (rep[i] === i) {
      number[i] = W.length;
      W.push(as_vec3(V[i] as readonly number[]));
    }
  }
  const index = rep.map((r) => number[r] as number);
  return [W, prepare_faces(faces, index), index];
}

// ---------------------------------------------------------------------------
// step 3: degenerate faces
// ---------------------------------------------------------------------------

/** Unnormalised Newell vector `Σ p_i × p_{i+1}` (the accumulation of `mesh.face_normals_newell`, §5.4.4 (3)). */
function newell_vector(V: readonly (readonly number[])[], face: readonly number[]): Vec3 {
  const L = face.length;
  let n01 = 0, n02 = 0, n10 = 0, n12 = 0, n20 = 0, n21 = 0;
  for (let l = 0; l < L; l++) {
    const p = V[face[l] as number] as readonly number[];
    const q = V[face[(l + 1) % L] as number] as readonly number[];
    n01 += (p[0] as number) * (q[1] as number);
    n02 += (p[0] as number) * (q[2] as number);
    n10 += (p[1] as number) * (q[0] as number);
    n12 += (p[1] as number) * (q[2] as number);
    n20 += (p[2] as number) * (q[0] as number);
    n21 += (p[2] as number) * (q[1] as number);
  }
  return [n12 - n21, n20 - n02, n01 - n10];
}

/** Collapse consecutive duplicate indices cyclically, keeping the first vertex. */
function collapse(face: readonly number[]): number[] {
  const g = [Math.trunc(face[0] as number)];
  for (const v0 of face.slice(1)) {
    const v = Math.trunc(v0);
    if (v !== g[g.length - 1]) g.push(v);
  }
  while (g.length > 1 && g[g.length - 1] === g[0]) g.pop();
  return g;
}

/** Contract §5.2.3 step 3 -> `[kept_faces, kept_index]`: consecutive duplicates collapsed (cyclically), then faces with
 * `< 3` vertices, with vertices that are not pairwise distinct (`[a, b, c, b]`) or with Newell norm
 * `<= 1e-12·scale_A²` are dropped; `kept_index` lists the input index of every kept face. */
export function drop_degenerate_faces(V: readonly (readonly number[])[], faces: readonly (readonly number[])[],
  scale_A: number): [number[][], number[]] {
  const kept: number[][] = [];
  const idx: number[] = [];
  const thr = DEGENERATE_REL * scale_A ** 2;
  faces.forEach((f, k) => {
    const g = collapse(f);
    if (g.length < 3 || new Set(g).size !== g.length) return;
    const nv = newell_vector(V, g);
    if (Math.sqrt(nv[0] * nv[0] + nv[1] * nv[1] + nv[2] * nv[2]) > thr) {
      kept.push(g);
      idx.push(k);
    }
  });
  return [kept, idx];
}

/** Remove the vertices used by no face, keeping the order -> `[V2, faces2, old_index]`. */
export function compact_vertices(V: readonly (readonly number[])[], faces: readonly (readonly number[])[]): [Vec3[], number[][], number[]] {
  const used = new Array<boolean>(V.length).fill(false);
  for (const f of faces) for (const v of f) used[v] = true;
  const old: number[] = [];
  const number = new Array<number>(V.length).fill(-1);
  used.forEach((u, i) => {
    if (u) {
      number[i] = old.length;
      old.push(i);
    }
  });
  return [old.map((i) => as_vec3(V[i] as readonly number[])), prepare_faces(faces, number), old];
}

// ---------------------------------------------------------------------------
// step 4: triangles
// ---------------------------------------------------------------------------

/** Fan triangulation `(f0, f_k, f_{k+1})` of every face, face-major order (`mesh.triangulate_faces` on the padded
 * face table). */
export function triangulate(faces: readonly (readonly number[])[]): Triangle[] {
  if (faces.length === 0) return [];
  const lens = faces.map((f) => f.length);
  const width = Math.max(...lens);
  const padded = faces.map((f) => {
    const row = new Array<number>(width).fill(-1);
    f.forEach((v, k) => {
      row[k] = v;
    });
    return row;
  });
  return triangulate_faces(padded, lens);
}

// ---------------------------------------------------------------------------
// step 5: adjacency, manifold test, orientation
// ---------------------------------------------------------------------------

/**
 * Undirected edges `i < j` (lexicographic) with their incident faces (distinct face indices, ascending) and the
 * direction each face traverses them (`+1`: `i -> j`, `-1`: `j -> i`); `face_edges` (ascending), `face_edge_at` (the
 * edge of `(f[k], f[k+1])` for each `k`), `counts`, `manifold` (every edge on exactly 2 faces), `consistent`. Faces are
 * assumed to have pairwise distinct vertices (step 3).
 */
export function build_adjacency(faces: readonly (readonly number[])[], n_v_in: number): Adjacency {
  const n_v = Math.max(Math.trunc(n_v_in), 1);
  const keys: number[] = [];
  const fidx: number[] = [];
  const dirs: number[] = [];
  faces.forEach((f, fi) => {
    const L = f.length;
    for (let k = 0; k < L; k++) {
      const a = f[k] as number, b = f[(k + 1) % L] as number;
      keys.push(Math.min(a, b) * n_v + Math.max(a, b));
      fidx.push(fi);
      dirs.push(a < b ? 1 : -1);
    }
  });
  const uniq = [...new Set(keys)].sort((x, y) => x - y);
  const pos = new Map<number, number>(uniq.map((k, e) => [k, e] as const));
  const inv = keys.map((k) => pos.get(k) as number);
  const edges: [number, number][] = uniq.map((k) => [Math.floor(k / n_v), k % n_v]); // pyimod-free: keys are non-negative
  // np.lexsort((fidx, inv)): by edge, then face, stable
  const order = keys.map((_k, i) => i).sort((x, y) => (inv[x] as number) - (inv[y] as number)
    || (fidx[x] as number) - (fidx[y] as number) || x - y);
  const edge_faces: number[][] = uniq.map(() => []);
  const edge_dirs: number[][] = uniq.map(() => []);
  for (const i of order) {
    (edge_faces[inv[i] as number] as number[]).push(fidx[i] as number);
    (edge_dirs[inv[i] as number] as number[]).push(dirs[i] as number);
  }
  const counts = edge_faces.map((l) => l.length);
  const face_edge_at: number[][] = [];
  let p = 0;
  for (const f of faces) {
    face_edge_at.push(inv.slice(p, p + f.length));
    p += f.length;
  }
  const face_edges = face_edge_at.map((row) => [...row].sort((x, y) => x - y));
  const manifold = counts.every((c) => c === 2);
  const consistent = manifold && edge_dirs.every((d) => d[0] !== d[1]);
  return { edges, edge_faces, edge_dirs, face_edges, face_edge_at, counts, manifold, consistent };
}

/** Reverse a face keeping its start vertex: `[f0] + f[1:][::-1]`. */
function flip_face(f: readonly number[]): number[] {
  return [f[0] as number, ...f.slice(1).reverse()];
}

/**
 * Orientation propagation over the face adjacency graph of a manifold mesh (contract §5.2.3 step 5): BFS per connected
 * component from its lowest-index face, FIFO queue, neighbours in ascending edge index; a face is flipped when it
 * traverses the shared edge in the same direction as its already-oriented neighbour. Returns
 * `[faces_out, flipped, components (face indices ascending), conflict]`; `conflict` means "not manifold".
 */
export function fix_orientation(faces: readonly (readonly number[])[], adjacency: Adjacency): [number[][], boolean[], number[][], boolean] {
  const F = faces.length;
  const flip = new Array<boolean>(F).fill(false);
  const comp = new Array<number>(F).fill(-1);
  const components: number[][] = [];
  let conflict = false;
  const { edge_faces, edge_dirs, face_edges } = adjacency;
  for (let s = 0; s < F; s++) {
    if ((comp[s] as number) >= 0) continue;
    const c = components.length;
    const members = [s];
    comp[s] = c;
    const queue = [s];
    let head = 0;
    while (head < queue.length) {
      const g = queue[head++] as number;
      for (const e of face_edges[g] as number[]) {
        const [f0, f1] = edge_faces[e] as [number, number];
        const [d0, d1] = edge_dirs[e] as [number, number];
        let h: number, dh: number, dg: number;
        if (f0 === g) [h, dh, dg] = [f1, d1, d0];
        else [h, dh, dg] = [f0, d0, d1];
        const eff_g = flip[g] ? -dg : dg;
        const need = dh === eff_g; // same direction as the oriented neighbour -> flip h
        if ((comp[h] as number) < 0) {
          comp[h] = c;
          flip[h] = need;
          members.push(h);
          queue.push(h);
        } else if (flip[h] !== need) {
          conflict = true;
        }
      }
    }
    components.push(members.sort((x, y) => x - y));
  }
  const out = faces.map((f, k) => (flip[k] ? flip_face(f) : [...f]));
  return [out, flip, components, conflict];
}

/** `a·(b×c)` per triangle (numpy `einsum("ij,ij->i", a, cross(b, c))`, the 3-term sum left to right). */
function triple(V: readonly (readonly number[])[], t: readonly number[]): number {
  return dot3(V[t[0] as number] as readonly number[], cross3(V[t[1] as number] as readonly number[], V[t[2] as number] as readonly number[]));
}

/** `Σ_tri a·(b×c) / 6`, summed sequentially in triangle order (contract §5.2.3 step 5). */
export function signed_volume(V: readonly (readonly number[])[], tris: readonly (readonly number[])[]): number {
  if (tris.length === 0) return 0.0;
  let s = 0.0;
  for (const t of tris) s += triple(V, t);
  return s / 6.0;
}

/** Generalised winding number of the triangles about `x`: Van Oosterom–Strackee solid angles
 * `Ω = 2·atan2(a·(b×c), |a||b||c| + (a·b)|c| + (a·c)|b| + (b·c)|a|)` summed sequentially in triangle order, divided by
 * `4π` (contract §5.2.3 step 8). */
export function winding_number(V: readonly (readonly number[])[], tris: readonly (readonly number[])[], x: readonly number[]): number {
  if (tris.length === 0) return 0.0;
  let s = 0.0;
  for (const t of tris) {
    const a = sub3(V[t[0] as number] as readonly number[], x);
    const b = sub3(V[t[1] as number] as readonly number[], x);
    const c = sub3(V[t[2] as number] as readonly number[], x);
    const la = Math.sqrt(dot3(a, a)), lb = Math.sqrt(dot3(b, b)), lc = Math.sqrt(dot3(c, c));
    const num = dot3(a, cross3(b, c));
    const den = la * lb * lc + dot3(a, b) * lc + dot3(a, c) * lb + dot3(b, c) * la;
    s += 2.0 * Math.atan2(num, den);
  }
  return s / (4.0 * Math.PI);
}

function segment_distance(x: readonly number[], A: readonly number[], B: readonly number[]): number {
  const d = sub3(B, A);
  const dd = dot3(d, d);
  let t = dot3(sub3(x, A), d);
  t = dd > 0.0 ? t / dd : 0.0;
  t = Math.min(Math.max(t, 0.0), 1.0); // np.clip
  const p: Vec3 = [(A[0] as number) + t * d[0], (A[1] as number) + t * d[1], (A[2] as number) + t * d[2]];
  const r = sub3(x, p);
  return Math.sqrt(r[0] * r[0] + r[1] * r[1] + r[2] * r[2]);
}

/** Exact Euclidean distance from `x` to one (closed) triangle: the distance to the plane when the foot lies inside the
 * triangle, else the distance to the nearest edge (degenerate triangles reduce to their edges). */
function point_triangle_distance(x: readonly number[], A: readonly number[], B: readonly number[], C: readonly number[]): number {
  let dist = Math.min(Math.min(segment_distance(x, A, B), segment_distance(x, B, C)), segment_distance(x, C, A));
  const n = cross3(sub3(B, A), sub3(C, A));
  const nn = dot3(n, n);
  if (nn > 0.0) {
    const s = dot3(sub3(x, A), n) / nn;
    const foot: Vec3 = [(x[0] as number) - s * n[0], (x[1] as number) - s * n[1], (x[2] as number) - s * n[2]];
    // barycentric sign test: the foot is inside iff it is on the inner side of all three edges
    const e0 = dot3(cross3(sub3(B, A), sub3(foot, A)), n);
    const e1 = dot3(cross3(sub3(C, B), sub3(foot, B)), n);
    const e2 = dot3(cross3(sub3(A, C), sub3(foot, C)), n);
    if (e0 >= 0.0 && e1 >= 0.0 && e2 >= 0.0) dist = Math.min(dist, Math.abs(s) * Math.sqrt(nn));
  }
  return dist;
}

/** Contract §5.2.3 step 8: `x` is inside the closed mesh `tris` iff `|w| > 0.75` and the point–triangle distance to
 * every triangle is `> tol` (a point on the surface within `tol` is outside, as `_point_in_polygon_margin`). Only the
 * first three components of `x` are read. */
export function point_inside_mesh(verts: readonly (readonly number[])[], tris: readonly (readonly number[])[],
  x_in: readonly number[], tol = 0.0): boolean {
  if (tris.length === 0) return false;
  const x: Vec3 = as_vec3(x_in);
  if (!(Math.abs(winding_number(verts, tris, x)) > INSIDE_WINDING)) return false;
  let dmin = Infinity;
  for (const t of tris) {
    const d = point_triangle_distance(x, verts[t[0] as number] as readonly number[], verts[t[1] as number] as readonly number[],
      verts[t[2] as number] as readonly number[]);
    if (d < dmin || Number.isNaN(d)) dmin = d; // np.min propagates NaN
  }
  return dmin > tol;
}

/** Volume / nesting-parity orientation of contract §5.2.3 step 5 -> `[faces_out, flipped_any]`. */
function orient_components(V: readonly (readonly number[])[], faces: readonly (readonly number[])[], components: readonly number[][],
  scale_A: number): [number[][], boolean] {
  const tris_of = components.map((comp) => triangulate(comp.map((f) => faces[f] as readonly number[])));
  const vols = tris_of.map((t) => signed_volume(V, t));
  const thr = VOLUME_REL * scale_A ** 3;
  const solid = vols.map((v) => Math.abs(v) > thr);
  const out = faces.map((f) => [...f]);
  let flipped = false;
  components.forEach((comp, k) => {
    if (!solid[k]) return;
    let lowest = Infinity;
    for (const f of comp) for (const v of faces[f] as readonly number[]) if (v < lowest) lowest = v;
    const x_k = V[lowest] as readonly number[];
    let depth = 0;
    for (let c = 0; c < components.length; c++) {
      if (c !== k && solid[c] && Math.abs(winding_number(V, tris_of[c] as Triangle[], x_k)) > INSIDE_WINDING) depth++;
    }
    const want_positive = depth % 2 === 0; // pyimod-free: depth is a count (non-negative)
    if (((vols[k] as number) > 0.0) !== want_positive) {
      for (const f of comp) out[f] = flip_face(out[f] as number[]);
      flipped = true;
    }
  });
  return [out, flipped];
}

// ---------------------------------------------------------------------------
// step 6: coplanar merge
// ---------------------------------------------------------------------------

/** Chain directed edges `(a, b)` (given in ascending undirected-edge order) into loops by the lowest-index unused
 * outgoing edge (the rule of `light.silhouette_loops`). */
function boundary_loops(directed: readonly (readonly [number, number])[]): number[][] {
  const outgoing = new Map<number, number[]>();
  directed.forEach(([a], idx) => {
    let l = outgoing.get(a);
    if (l === undefined) outgoing.set(a, (l = []));
    l.push(idx);
  });
  const used = new Array<boolean>(directed.length).fill(false);
  const loops: number[][] = [];
  for (let start = 0; start < directed.length; start++) {
    if (used[start]) continue;
    const loop: number[] = [];
    let cur = start;
    for (;;) {
      used[cur] = true;
      const [a, b] = directed[cur] as readonly [number, number];
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
    loops.push(loop);
  }
  return loops;
}

/**
 * Seed-ordered region growing of contract §5.2.3 step 6 (manifold meshes) -> `[new_faces, origin]`. Faces are taken in
 * index order; an unassigned face `s` seeds a region that grows by BFS over the face adjacency (FIFO, neighbours in
 * ascending index of the shared edge); a neighbour `f` reached from `g` joins iff it is unassigned,
 * `n_f·n_s >= cos_tol` and `n_f·n_g >= cos_tol`. A region whose boundary is one simple loop becomes one face, started at
 * the first vertex of the seed's cycle on the boundary (else the lowest-index boundary vertex) and walked in the
 * boundary's direction; a region with a hole or a pinch is left unmerged (its faces in ascending index at the seed's
 * place). `origin[k]` is the seed of a merged face or the face itself (smoothing group source).
 */
export function merge_coplanar(_V: readonly (readonly number[])[], faces: readonly (readonly number[])[],
  normals: readonly (readonly number[])[], adjacency: Pick<Adjacency, "edge_faces" | "face_edges" | "face_edge_at">,
  cos_tol: number): [number[][], number[]] {
  const F = faces.length;
  const { edge_faces, face_edges, face_edge_at } = adjacency;
  const dot = (i: number, j: number): number => dot3(normals[i] as readonly number[], normals[j] as readonly number[]);
  const region = new Array<number>(F).fill(-1);
  const new_faces: number[][] = [];
  const origin: number[] = [];
  for (let s = 0; s < F; s++) {
    if ((region[s] as number) >= 0) continue;
    region[s] = s;
    const members = [s];
    const queue = [s];
    let head = 0;
    while (head < queue.length) {
      const g = queue[head++] as number;
      for (const e of face_edges[g] as number[]) {
        for (const h of edge_faces[e] as number[]) { // the other face (an open edge of a direct call has none)
          if (h !== g && (region[h] as number) < 0 && dot(h, s) >= cos_tol && dot(h, g) >= cos_tol) {
            region[h] = s;
            members.push(h);
            queue.push(h);
          }
        }
      }
    }
    if (members.length === 1) {
      new_faces.push([...(faces[s] as readonly number[])]);
      origin.push(s);
      continue;
    }
    const member_set = new Set(members);
    const directed: [number, number, number][] = [];
    for (const f of members) {
      const cyc = faces[f] as readonly number[];
      const L = cyc.length;
      for (let k = 0; k < L; k++) {
        const e = (face_edge_at[f] as number[])[k] as number;
        const ef = edge_faces[e] as number[];
        if (ef.length === 1 || !ef.every((h) => member_set.has(h))) directed.push([e, cyc[k] as number, cyc[(k + 1) % L] as number]);
      }
    }
    directed.sort((x, y) => x[0] - y[0] || x[1] - y[1] || x[2] - y[2]);
    const loops = boundary_loops(directed.map(([, a, b]) => [a, b] as const));
    const simple = loops.length === 1 && (loops[0] as number[]).length === directed.length
      && new Set(loops[0]).size === (loops[0] as number[]).length;
    if (!simple) {
      for (const f of [...members].sort((x, y) => x - y)) {
        new_faces.push([...(faces[f] as readonly number[])]);
        origin.push(f);
      }
      continue;
    }
    const loop = loops[0] as number[];
    const on_boundary = new Set(loop);
    const seed_start = (faces[s] as readonly number[]).find((v) => on_boundary.has(v));
    const start = seed_start !== undefined ? seed_start : Math.min(...loop);
    const k = loop.indexOf(start);
    new_faces.push([...loop.slice(k), ...loop.slice(0, k)]);
    origin.push(s);
  }
  return [new_faces, origin];
}

// ---------------------------------------------------------------------------
// step 7: edge classification
// ---------------------------------------------------------------------------

/** `edge_smooth (m,)` (contract §5.2.3 step 7): `(g_a == g_b != 0) or (g_a == g_b == 0 and
 * n_a·n_b >= cos(smooth_angle_deg) - 1e-9)`. */
export function classify_edges(mesh: Pick<Mesh, "edge_faces" | "face_normals">, smooth_angle_deg: number,
  smooth_groups: readonly number[]): boolean[] {
  const c = Math.cos(radians(smooth_angle_deg)) - SMOOTH_BAND;
  return mesh.edge_faces.map(([fa, fb]) => {
    const ga = smooth_groups[fa] as number, gb = smooth_groups[fb] as number;
    const d = dot3(mesh.face_normals[fa] as Vec3, mesh.face_normals[fb] as Vec3);
    const same = ga === gb;
    return (same && ga !== 0) || (same && ga === 0 && d >= c);
  });
}

// ---------------------------------------------------------------------------
// §5.2.5: non-manifold fallback mesh
// ---------------------------------------------------------------------------

/** The §2.4-shaped mesh of a non-manifold mesh (contract §5.2.5): `faces` as given, `edges` the unique `i < j` pairs,
 * `edge_faces[e] = [f_min, f_max]` (equal for a boundary edge), `edge_flipped` accordingly, Newell `face_normals`,
 * `edge_smooth` all false. */
export function fallback_mesh(V_in: readonly (readonly number[])[], faces_in: readonly (readonly number[])[],
  vertex_names?: readonly string[] | null): Mesh {
  const V = V_in.map(as_vec3);
  const faces = faces_in.map((f) => f.map((v) => Math.trunc(v)));
  const n_v = Math.max(V.length, 1);
  const keys: number[] = [];
  const fidx: number[] = [];
  const rev: boolean[] = [];
  faces.forEach((f, fi) => {
    const L = f.length;
    for (let k = 0; k < L; k++) {
      const a = f[k] as number, b = f[(k + 1) % L] as number;
      keys.push(Math.min(a, b) * n_v + Math.max(a, b));
      fidx.push(fi);
      rev.push(a > b); // the face traverses the edge as j -> i
    }
  });
  const uniq = [...new Set(keys)].sort((x, y) => x - y);
  const pos = new Map<number, number>(uniq.map((k, e) => [k, e] as const));
  const m = uniq.length;
  const f_min = new Array<number>(m).fill(faces.length);
  const f_max = new Array<number>(m).fill(-1);
  const inv = keys.map((k) => pos.get(k) as number);
  inv.forEach((e, i) => {
    f_min[e] = Math.min(f_min[e] as number, fidx[i] as number);
    f_max[e] = Math.max(f_max[e] as number, fidx[i] as number);
  });
  const flip_min = new Array<boolean>(m).fill(false);
  const flip_max = new Array<boolean>(m).fill(false);
  inv.forEach((e, i) => { // numpy fancy assignment: the last occurrence wins
    if (fidx[i] === f_min[e]) flip_min[e] = rev[i] as boolean;
    if (fidx[i] === f_max[e]) flip_max[e] = rev[i] as boolean;
  });
  return {
    vertices: V,
    edges: uniq.map((k) => [Math.floor(k / n_v), k % n_v] as [number, number]), // pyimod-free: keys are non-negative
    faces,
    face_normals: face_normals_newell(V, faces),
    edge_faces: uniq.map((_k, e) => [f_min[e] as number, f_max[e] as number] as [number, number]),
    edge_flipped: uniq.map((_k, e) => [flip_min[e] as boolean, flip_max[e] as boolean] as [boolean, boolean]),
    vertex_names: vertex_names === undefined || vertex_names === null ? V.map((_v, i) => `v${i}`) : [...vertex_names],
    edge_smooth: new Array<boolean>(m).fill(false),
  };
}

/** `edge_smooth` of a receiver-clipped mesh (contract §5.2.4): an edge that is part of an original edge inherits its
 * flag (a crossing vertex `{kind: "ground", i, j}` names that edge); cut-face edges (both endpoints crossings) and any
 * other new edge are feature (false). */
export function inherit_edge_smooth(loop_mesh: Pick<Mesh, "edges">, origins: readonly Origin[], mesh: Pick<Mesh, "edges">,
  edge_smooth: readonly boolean[]): boolean[] {
  const index = new Map<string, number>(mesh.edges.map(([i, j], e) => [`${i},${j}`, e] as const));
  return loop_mesh.edges.map(([a, b]) => {
    const oa = origins[a] as Origin, ob = origins[b] as Origin;
    let key: string | null = null;
    const ta = typeof oa === "object", tb = typeof ob === "object";
    if (ta && tb) {
      key = null;
    } else if (ta || tb) {
      const [v, cross] = ta ? [ob as number, oa as { i: number; j: number }] : [oa as number, ob as { i: number; j: number }];
      const i = cross.i, j = cross.j;
      if (v === i || v === j) key = `${Math.min(i, j)},${Math.max(i, j)}`;
    } else {
      key = `${Math.min(oa as number, ob as number)},${Math.max(oa as number, ob as number)}`;
    }
    const e = key !== null ? index.get(key) : undefined;
    return e !== undefined ? (edge_smooth[e] as boolean) : false;
  });
}

// ---------------------------------------------------------------------------
// the whole pipeline
// ---------------------------------------------------------------------------

/**
 * Contract §5.2.3 -> `[mesh, triangles, fallback, smooth_groups, warnings]`; with `return_scale` the tuple gains a
 * sixth item, `scale_A` (the §5.2.3 length scale the steps used; the M5 note "Shared helpers"). `data` is the
 * validated `objects[i].data` (Z-up, file units); the result is in the object's local frame (`scale` applied,
 * `transform` not). `mesh` is the §2.4 record plus `edge_smooth`; `triangles` the fan triangles of the kept (oriented)
 * faces on the welded vertices (the original surface); `smooth_groups` one per final face; `warnings` the `MESH_*`
 * warnings with ids `[object_id]`. Throws a plain `Error("no usable face …")` when every face is degenerate
 * (unreachable on a validated scene: the usable-face guard of `validate_mesh_object`).
 */
export function preprocess_mesh(data: MeshInput, scale: number, weld_tolerance: number, smooth_angle_deg: number,
  object_id?: string, return_scale?: false): PrepResult;
export function preprocess_mesh(data: MeshInput, scale: number, weld_tolerance: number, smooth_angle_deg: number,
  object_id: string, return_scale: true): PrepResultScaled;
export function preprocess_mesh(data: MeshInput, scale: number, weld_tolerance: number, smooth_angle_deg: number,
  object_id = "", return_scale = false): PrepResult | PrepResultScaled {
  const V: Vec3[] = data.vertices.map((v) => [scale * (v[0] as number), scale * (v[1] as number), scale * (v[2] as number)]);
  const n_faces = data.faces.length;
  const sg = data.smooth_groups;
  const groups_in: readonly number[] = sg !== undefined && sg !== null && sg.length > 0 ? sg : new Array<number>(n_faces).fill(0);
  const scale_A = mesh_scale(V);
  const warnings: Warning[] = [];
  const [W0, faces_w] = weld_vertices(V, data.faces, weld_tolerance);
  const [kept, kept_idx] = drop_degenerate_faces(W0, faces_w, scale_A);
  if (kept.length === 0) throw new Error("no usable face (the scene must pass validate_scene first)");
  const n_dropped = n_faces - kept.length;
  if (n_dropped) warnings.push(make_warning("MESH_DEGENERATE_FACES", [object_id], `${n_dropped} degenerate face(s) dropped`));
  const groups = kept_idx.map((k) => Math.trunc(groups_in[k] as number));
  const [W, faces] = compact_vertices(W0, kept);
  const names = W.map((_v, k) => `v${k}`);
  const adjacency = build_adjacency(faces, W.length);
  let conflict = false;
  let oriented: number[][] = [];
  let flipped: boolean[] = [];
  let components: number[][] = [];
  if (adjacency.manifold) [oriented, flipped, components, conflict] = fix_orientation(faces, adjacency);
  const done = (out: PrepResult): PrepResult | PrepResultScaled => (return_scale ? [...out, scale_A] : out);
  if (!adjacency.manifold || conflict) {
    const n1 = adjacency.counts.filter((c) => c === 1).length;
    const n3 = adjacency.counts.filter((c) => c >= 3).length;
    const msg = `mesh is not a closed manifold (${n1} edge(s) with 1 face, ${n3} edge(s) with >= 3 faces`
      + (conflict ? "; inconsistent winding" : "") + "); per-face shadow fallback";
    warnings.push(make_warning("MESH_NON_MANIFOLD", [object_id], msg));
    return done([fallback_mesh(W, faces, names), triangulate(faces), true, groups, warnings]);
  }
  let flipped_volume: boolean;
  [oriented, flipped_volume] = orient_components(W, oriented, components, scale_A);
  const winding_fixed = flipped.some((f) => f) || flipped_volume;
  if (winding_fixed) warnings.push(make_warning("MESH_WINDING_FIXED", [object_id]));
  const triangles = triangulate(oriented);
  const normals = face_normals_newell(W, oriented);
  // the merge reads edge positions per face, so it needs the adjacency of the oriented faces (the undirected edge set
  // and its numbering are unchanged by the flips; the M5 note "Coplanar merge after a winding fix")
  const merge_adj = winding_fixed ? build_adjacency(oriented, W.length) : adjacency;
  const [merged, origin] = merge_coplanar(W, oriented, normals, merge_adj, Math.cos(COPLANAR_TOL_RAD));
  const merged_groups = origin.map((k) => groups[k] as number);
  const mesh = mesh_from_faces(W, merged, names);
  mesh.edge_smooth = classify_edges(mesh, smooth_angle_deg, merged_groups);
  return done([mesh, triangles, false, merged_groups, warnings]);
}

/** The usable-face guard of `scene.validate_mesh_object` (contract §5.2.1 [decision]): whether at least one face
 * survives the weld (§5.2.3 step 2) and the degenerate-face removal (step 3) on `scale · vertices`. */
export function has_usable_face(vertices: readonly (readonly number[])[], faces: readonly (readonly number[])[], scale: number,
  weld_tolerance: number): boolean {
  const V: Vec3[] = vertices.map((v) => [scale * (v[0] as number), scale * (v[1] as number), scale * (v[2] as number)]);
  const [W, faces_w] = weld_vertices(V, faces, weld_tolerance);
  const [kept] = drop_degenerate_faces(W, faces_w, mesh_scale(V));
  return kept.length > 0;
}

/**
 * Light vectors, lit tests and silhouette extraction (port of `castplane/light.py`; spec §5.1, contract §2.3 / §2.5).
 *
 * Every predicate is strict (`> tol`) and the band `|.| <= tol` counts as the degenerate ("parallel", not lit) side.
 */

import type { Mesh } from "./mesh.js";
import type { Light } from "./scene.js";
import type { Vec4 } from "./types.js";

/** Homogeneous light vector `L` (spec §5.1): point `(x, y, z, 1)`, directional `(dx, dy, dz, 0)` (towards the light). */
export function light_vector(light: Pick<Light, "type" | "position" | "direction">): Vec4 {
  if (light.type === "point") {
    const p = light.position as readonly number[];
    return [p[0] as number, p[1] as number, p[2] as number, 1.0];
  }
  if (light.type === "directional") {
    const d = light.direction as readonly number[];
    return [d[0] as number, d[1] as number, d[2] as number, 0.0];
  }
  throw new Error(`light.type must be 'point' or 'directional', got '${String(light.type)}'`);
}

/** The signed quantity `n_f · (l − w p)` of spec §5.1 (left-to-right, §5.4.4 (2)). */
export function lit_value(n_f: readonly number[], p: readonly number[], L: readonly number[]): number {
  const w = L[3] as number;
  return (n_f[0] as number) * ((L[0] as number) - w * (p[0] as number))
    + (n_f[1] as number) * ((L[1] as number) - w * (p[1] as number))
    + (n_f[2] as number) * ((L[2] as number) - w * (p[2] as number));
}

/** Spec §5.1: `lit(f) ⇔ n_f · (l − w p) > tol`. */
export function lit(n_f: readonly number[], p: readonly number[], L: readonly number[], tol = 0.0): boolean {
  return lit_value(n_f, p, L) > tol;
}

/** `|n_f · (l − w p)| <= tol` (spec §5.7 row 6, `FACE_PARALLEL_TO_LIGHT`). */
export function is_parallel(n_f: readonly number[], p: readonly number[], L: readonly number[], tol = 0.0): boolean {
  return Math.abs(lit_value(n_f, p, L)) <= tol;
}

/** `[lit, parallel]` for one face; `parallel` implies `!lit`. */
export function lit_state(n_f: readonly number[], p: readonly number[], L: readonly number[], tol = 0.0): [boolean, boolean] {
  const v = lit_value(n_f, p, L);
  return [v > tol, Math.abs(v) <= tol];
}

/** `lit_state` over all faces (representative point: the face's first vertex). */
export function face_lit_flags(mesh: Mesh, L: readonly number[], tol = 0.0): { lit: boolean[]; parallel: boolean[] } {
  const lits: boolean[] = [];
  const parallel: boolean[] = [];
  mesh.faces.forEach((f, k) => {
    const v = lit_value(mesh.face_normals[k] as readonly number[], mesh.vertices[f[0] as number] as readonly number[], L);
    lits.push(v > tol);
    parallel.push(Math.abs(v) <= tol);
  });
  return { lit: lits, parallel };
}

/** Indices of the light silhouette edges (adjacent faces with different `lit` values), ascending. */
export function silhouette_edges(mesh: Mesh, lit_flags: readonly boolean[]): number[] {
  const out: number[] = [];
  mesh.edge_faces.forEach(([f0, f1], e) => {
    if (lit_flags[f0] !== lit_flags[f1]) out.push(e);
  });
  return out;
}

/** Each silhouette edge directed as it appears in the cycle of its lit face (contract §2.5). */
function directed_silhouette_edges(mesh: Mesh, lit_flags: readonly boolean[]): [number, number][] {
  const out: [number, number][] = [];
  for (const e of silhouette_edges(mesh, lit_flags)) {
    const [f0] = mesh.edge_faces[e] as [number, number];
    const slot = lit_flags[f0] ? 0 : 1;
    const rev = (mesh.edge_flipped[e] as [boolean, boolean])[slot];
    const [i, j] = mesh.edges[e] as [number, number];
    out.push(rev ? [j, i] : [i, j]);
  }
  return out;
}

/**
 * Walk the silhouette edges into closed vertex-index loops (contract §2.5), lit face on the left as seen from the
 * light; at vertices where several silhouette edges meet the lowest-index unused outgoing edge is taken.
 */
export function silhouette_loops(mesh: Mesh, lit_flags: readonly boolean[]): number[][] {
  const directed = directed_silhouette_edges(mesh, lit_flags);
  if (directed.length === 0) return [];
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
      const [a, b] = directed[cur] as [number, number];
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

/**
 * Internal mesh representation and primitive builders (port of `castplane/mesh.py`; contract §2.4).
 *
 * A mesh is a plain record: `vertices` (n×3), `edges` (each edge once, `i < j`, lexicographically sorted), `faces`
 * (counter-clockwise seen from outside, planar), `face_normals` (outward unit normals), `edge_faces` (the two faces
 * adjacent to each edge, ascending), `edge_flipped` (whether that face traverses the edge as `j -> i`) and
 * `vertex_names` (`v0`, `v1`, …). Builders produce local coordinates (contract §2.1).
 */

import type { Mat3, Vec3 } from "./types.js";
import { rigid, rotate } from "./transform.js";

/** Default angular resolution of the approximate meshes of curved primitives (contract §2.4). */
export const CURVED_SEGMENTS = 32;
export const SPHERE_RINGS = 16;

export interface Mesh {
  vertices: Vec3[];
  edges: [number, number][];
  faces: number[][];
  face_normals: Vec3[];
  edge_faces: [number, number][];
  edge_flipped: [boolean, boolean][];
  vertex_names: string[];
}

/** Faces grouped by vertex count in order of first appearance of each count (the numpy grouping). */
function group_faces(faces: readonly (readonly number[])[]): number[][] {
  const groups = new Map<number, number[]>();
  faces.forEach((f, fi) => {
    let g = groups.get(f.length);
    if (g === undefined) groups.set(f.length, (g = []));
    g.push(fi);
  });
  return [...groups.values()];
}

/** Newell normal of one face: `n[j][m] += p[l][j]·q[l][m]` in cycle order, then the antisymmetric part (§5.4.4 (3)). */
function newell(vertices: readonly Vec3[], face: readonly number[]): Vec3 {
  const L = face.length;
  let n01 = 0, n02 = 0, n10 = 0, n12 = 0, n20 = 0, n21 = 0;
  for (let l = 0; l < L; l++) {
    const p = vertices[face[l] as number] as Vec3;
    const q = vertices[face[(l + 1) % L] as number] as Vec3;
    n01 += p[0] * q[1];
    n02 += p[0] * q[2];
    n10 += p[1] * q[0];
    n12 += p[1] * q[2];
    n20 += p[2] * q[0];
    n21 += p[2] * q[1];
  }
  const cx = n12 - n21, cy = n20 - n02, cz = n01 - n10;
  let norm = Math.sqrt(cx * cx + cy * cy + cz * cz);
  if (norm === 0) norm = 1.0;
  return [cx / norm, cy / norm, cz / norm];
}

/** Outward unit normals by Newell's method (contract §2.4). */
export function face_normals_newell(vertices: readonly Vec3[], faces: readonly (readonly number[])[]): Vec3[] {
  return faces.map((f) => newell(vertices, f));
}

/**
 * Build the full mesh record from vertices and CCW faces (contract §2.4). Every edge must be shared by exactly two
 * faces (closed manifold), otherwise an `Error` is thrown (Python `ValueError`).
 */
export function mesh_from_faces(vertices: readonly (readonly number[])[], faces: readonly (readonly number[])[],
  vertex_names?: readonly string[]): Mesh {
  const verts: Vec3[] = vertices.map((v) => [v[0] as number, v[1] as number, v[2] as number]);
  const fcs = faces.map((f) => f.map((v) => Math.trunc(v)));
  const n_v = Math.max(verts.length, 1);
  // occurrences of (edge key, owner face, flipped) in the grouped order of the numpy implementation
  const occ: { key: number; owner: number; flipped: boolean; seq: number }[] = [];
  let seq = 0;
  for (const group of group_faces(fcs)) {
    for (const fi of group) {
      const f = fcs[fi] as number[];
      const L = f.length;
      for (let k = 0; k < L; k++) {
        const a = f[k] as number, b = f[(k + 1) % L] as number;
        const i = Math.min(a, b), j = Math.max(a, b);
        occ.push({ key: i * n_v + j, owner: fi, flipped: a > b, seq: seq++ });
      }
    }
  }
  // np.unique on the keys + np.lexsort((owners, inverse)): by key, then owner, then occurrence (stable)
  occ.sort((x, y) => x.key - y.key || x.owner - y.owner || x.seq - y.seq);
  const edges: [number, number][] = [];
  const edge_faces: [number, number][] = [];
  const edge_flipped: [boolean, boolean][] = [];
  let s = 0;
  while (s < occ.length) {
    let e = s;
    while (e < occ.length && (occ[e] as { key: number }).key === (occ[s] as { key: number }).key) e++;
    if (e - s !== 2) throw new Error("mesh is not a closed manifold: every edge must have exactly two faces");
    const a = occ[s] as (typeof occ)[number], b = occ[s + 1] as (typeof occ)[number];
    edges.push([Math.floor(a.key / n_v), a.key % n_v]); // pyimod-free: edge keys are non-negative
    edge_faces.push([a.owner, b.owner]);
    edge_flipped.push([a.flipped, b.flipped]);
    s = e;
  }
  return {
    vertices: verts,
    edges,
    faces: fcs,
    face_normals: face_normals_newell(verts, fcs),
    edge_faces,
    edge_flipped,
    vertex_names: vertex_names === undefined ? verts.map((_v, i) => `v${i}`) : [...vertex_names],
  };
}

// ---------------------------------------------------------------------------
// builders
// ---------------------------------------------------------------------------

/** Axis-aligned box `[-sx/2, sx/2] × [-sy/2, sy/2] × [0, sz]`; v0..v3 bottom ring CCW from `(-,-)`, v4..v7 top. */
export function box_mesh(size: readonly number[]): Mesh {
  const sx = size[0] as number, sy = size[1] as number, sz = size[2] as number;
  const hx = sx / 2.0, hy = sy / 2.0;
  const ring: [number, number][] = [[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]];
  const verts: Vec3[] = [...ring.map(([x, y]) => [x, y, 0.0] as Vec3), ...ring.map(([x, y]) => [x, y, sz] as Vec3)];
  const faces = [
    [0, 3, 2, 1], // bottom (-z)
    [4, 5, 6, 7], // top (+z)
    [0, 1, 5, 4], // front (-y)
    [1, 2, 6, 5], // right (+x)
    [2, 3, 7, 6], // back (+y)
    [3, 0, 4, 7], // left (-x)
  ];
  return mesh_from_faces(verts, faces);
}

function extrude(ring: readonly [number, number][], height: number): [Vec3[], number[][]] {
  const n = ring.length;
  const verts: Vec3[] = [...ring.map(([x, y]) => [x, y, 0.0] as Vec3), ...ring.map(([x, y]) => [x, y, height] as Vec3)];
  const bottom: number[] = [];
  for (let i = n - 1; i >= 0; i--) bottom.push(i);
  const top: number[] = [];
  for (let i = n; i < 2 * n; i++) top.push(i);
  const faces = [bottom, top];
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    faces.push([i, j, n + j, n + i]);
  }
  return [verts, faces];
}

/** Right prism over a simple CCW polygon in local XY, extruded over `[0, height]` (contract §2.4). */
export function prism_mesh(polygon: readonly (readonly number[])[], height: number): Mesh {
  const [verts, faces] = extrude(polygon.map((p) => [p[0] as number, p[1] as number]), height);
  return mesh_from_faces(verts, faces);
}

function circle_ring(radius: number, segments: number): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 0; i < segments; i++) {
    out.push([radius * Math.cos(2.0 * Math.PI * i / segments), radius * Math.sin(2.0 * Math.PI * i / segments)]);
  }
  return out;
}

/** Approximate cylinder: n-gon caps and lateral quads (bounding boxes only). */
export function cylinder_mesh(radius: number, height: number, segments = CURVED_SEGMENTS): Mesh {
  const [verts, faces] = extrude(circle_ring(radius, segments), height);
  return mesh_from_faces(verts, faces);
}

/** Approximate cone: n-gon base, apex at `(0, 0, height)`, lateral triangles. */
export function cone_mesh(radius: number, height: number, segments = CURVED_SEGMENTS): Mesh {
  const ring = circle_ring(radius, segments);
  const n = segments;
  const verts: Vec3[] = [...ring.map(([x, y]) => [x, y, 0.0] as Vec3), [0.0, 0.0, height]];
  const base: number[] = [];
  for (let i = n - 1; i >= 0; i--) base.push(i);
  const faces = [base];
  for (let i = 0; i < n; i++) faces.push([i, (i + 1) % n, n]);
  return mesh_from_faces(verts, faces);
}

/** Approximate UV-sphere with centre `(0, 0, r)` (bottom on the ground). */
export function sphere_mesh(radius: number, segments = CURVED_SEGMENTS, rings = SPHERE_RINGS): Mesh {
  const r = radius;
  const verts: Vec3[] = [[0.0, 0.0, 2.0 * r]];
  for (let j = 1; j < rings; j++) {
    const phi = Math.PI * j / rings;
    const z = r + r * Math.cos(phi);
    const rr = r * Math.sin(phi);
    for (let i = 0; i < segments; i++) {
      verts.push([rr * Math.cos(2.0 * Math.PI * i / segments), rr * Math.sin(2.0 * Math.PI * i / segments), z]);
    }
  }
  verts.push([0.0, 0.0, 0.0]);
  const bottom = verts.length - 1;
  const ring_index = (j: number, i: number): number => 1 + (j - 1) * segments + (i % segments); // pyimod-free: i >= 0
  const faces: number[][] = [];
  for (let i = 0; i < segments; i++) faces.push([ring_index(1, i), ring_index(1, i + 1), 0]);
  for (let j = 1; j < rings - 1; j++) {
    for (let i = 0; i < segments; i++) {
      faces.push([ring_index(j + 1, i), ring_index(j + 1, i + 1), ring_index(j, i + 1), ring_index(j, i)]);
    }
  }
  for (let i = 0; i < segments; i++) faces.push([ring_index(rings - 1, i + 1), ring_index(rings - 1, i), bottom]);
  return mesh_from_faces(verts, faces);
}

// ---------------------------------------------------------------------------
// utilities
// ---------------------------------------------------------------------------

/** A new mesh with `vertices = R·v + position` and rotated normals (contract §2.1). */
export function transform_mesh(mesh: Mesh, R: Mat3, position: readonly number[]): Mesh {
  return {
    ...mesh,
    vertices: mesh.vertices.map((v) => rigid(R, position, v)),
    face_normals: mesh.face_normals.map((n) => rotate(R, n)),
  };
}

/** `[min_xyz, max_xyz]` of the vertices. */
export function mesh_bbox(mesh: Mesh): [Vec3, Vec3] {
  const lo: Vec3 = [Infinity, Infinity, Infinity];
  const hi: Vec3 = [-Infinity, -Infinity, -Infinity];
  for (const v of mesh.vertices) {
    for (let k = 0; k < 3; k++) {
      if (v[k]! < lo[k]!) lo[k] = v[k]!;
      if (v[k]! > hi[k]!) hi[k] = v[k]!;
    }
  }
  return [lo, hi];
}

/** `V − E + F` (2 for a closed genus-0 surface). */
export function euler_characteristic(mesh: Mesh): number {
  return mesh.vertices.length - mesh.edges.length + mesh.faces.length;
}

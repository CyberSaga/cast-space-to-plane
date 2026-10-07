/**
 * Mesh preprocessing through the port (contract §5.2.3 – §5.2.5, the test table of §5.2.11; the port of
 * `tests/test_meshprep.py`): weld, degenerate faces, orientation / nesting, non-manifold detection and fallback,
 * coplanar merge, edge classification, `point_inside_mesh`.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { box_mesh, face_normals_newell, mesh_from_faces, prism_mesh, triangulate_faces } from "../src/mesh.js";
import type { Mesh } from "../src/mesh.js";
import {
  COPLANAR_TOL_RAD, INSIDE_WINDING, MESH_MAX_RAYS, SMOOTH_ANGLE_DEFAULT, SMOOTH_BAND, WELD_TOLERANCE_DEFAULT, build_adjacency,
  classify_edges, compact_vertices, drop_degenerate_faces, fallback_mesh, fix_orientation, has_usable_face, inherit_edge_smooth,
  merge_coplanar, mesh_scale, point_inside_mesh, preprocess_mesh, signed_volume, triangulate, weld_map, weld_vertices, winding_number,
} from "../src/meshprep.js";
import type { PrepResult } from "../src/meshprep.js";
import { clip_mesh_to_plane } from "../src/shadow.js";
import type { Origin } from "../src/shadow.js";

import { CUBE_F, CUBE_V, SPLIT_F, SPLIT_V } from "./mesh_fixtures.js";

function prep(vertices: number[][], faces: number[][], groups: number[] | null = null, scale = 1.0, weld = WELD_TOLERANCE_DEFAULT,
  smooth = SMOOTH_ANGLE_DEFAULT): PrepResult {
  const data = groups === null ? { vertices, faces } : { vertices, faces, smooth_groups: groups };
  return preprocess_mesh(data, scale, weld, smooth, "m");
}

const codes = (warnings: readonly { code: string }[]): string[] => warnings.map((w) => w.code);
const flip = (f: readonly number[]): number[] => [f[0] as number, ...f.slice(1).reverse()];
const approx = (a: number, b: number, tol = 1e-12): void => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);
const edge_key = (e: readonly number[]): string => `${e[0]},${e[1]}`;

function smooth_map(mesh: Mesh): Map<string, boolean> {
  return new Map(mesh.edges.map((e, k) => [edge_key(e), (mesh.edge_smooth as boolean[])[k] as boolean] as const));
}

test("constants (contract §5.2.3)", () => {
  assert.deepEqual([COPLANAR_TOL_RAD, WELD_TOLERANCE_DEFAULT, SMOOTH_ANGLE_DEFAULT, MESH_MAX_RAYS, SMOOTH_BAND, INSIDE_WINDING],
    [1e-3, 1e-6, 30.0, 64, 1e-9, 0.75]);
  assert.equal(mesh_scale([]), 1.0);
  assert.equal(mesh_scale([[0, 0, 0], [3, 0.5, -1]]), 3.0);
  assert.equal(mesh_scale([[0, 0, 0], [0.3, 0.5, -0.1]]), 1.0);
});

// --- weld (step 2) ---------------------------------------------------------------------------------------------------

test("weld: the lowest input index among representatives in neighbouring cells wins", () => {
  // tau = 1: r1 (cell -1) and r2 (cell 1) are 1.8 apart (two representatives); v (cell 0) is within tau of both and
  // joins the one with the LOWEST INPUT INDEX, not the nearer one
  const r1 = [-0.9, 0.0, 0.0], r2 = [0.9, 0.0, 0.0], v = [0.05, 0.0, 0.0];
  assert.deepEqual(weld_map([r1, r2, v], 1.0), [0, 1, 0]);
  assert.deepEqual(weld_map([r2, r1, v], 1.0), [0, 1, 0]);
  const [W, faces, index] = weld_vertices([r2, r1, v], [[0, 1, 2]], 1.0);
  assert.deepEqual(W, [r2, r1]);
  assert.deepEqual(index, [0, 1, 0]);
  assert.deepEqual(faces, [[0, 1, 0]]);
});

test("weld: the representative's own coordinates, first-appearance order, max-norm distance", () => {
  const V = [[1.0, 0, 0], [0.0, 0, 0], [1.0 + 4e-7, 0, 0], [0.0, 0, -5e-7], [2.0, 0, 0]];
  const [W, faces, index] = weld_vertices(V, [[2, 3, 4]], 1e-6);
  assert.deepEqual(W, [[1.0, 0, 0], [0.0, 0, 0], [2.0, 0, 0]]); // never a mean
  assert.deepEqual(index, [0, 1, 0, 1, 2]);
  assert.deepEqual(faces, [[0, 1, 2]]);
  assert.deepEqual(weld_map([[0, 0, 0], [1e-6, 1e-6, 1e-6]], 1e-6), [0, 0]);
  assert.deepEqual(weld_map([[0, 0, 0], [1e-6, 1.5e-6, 0]], 1e-6), [0, 1]);
});

test("weld: tau = 0 is exact equality (-0.0 == 0.0); a tau below every float spacing is the exact rule", () => {
  const V = [[0.0, 0, 0], [-0.0, 0, 0], [1e-300, 0, 0], [0.0, 0, 0]];
  assert.deepEqual(weld_map(V, 0.0), [0, 0, 2, 0]);
  // x / 5e-324 overflows for x = 1: the exact path (the M5 note "Weld details")
  assert.deepEqual(weld_map([[1, 0, 0], [1, 0, 0], [1 + 2 ** -52, 0, 0]], 5e-324), [0, 0, 2]);
});

test("weld: huge cell indices (far above 2^53) stay exact on the compressed number keys", () => {
  // tau = 1e-300: x / tau ~ 1e300 (finite); the per-axis renumbering gives R = 5, so this runs on number keys
  const tau = 1e-300;
  const V = [[1.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0], [1.0, 1e-300, 0]];
  assert.deepEqual(weld_map(V, tau), [0, 0, 2, 0]);
});

/** The `typeof` of every key the weld's cell dictionary stores while `f` runs (`Map.prototype.set` instrumented). */
function map_key_types(f: () => void): Set<string> {
  const kinds = new Set<string>();
  const set = Map.prototype.set;
  Map.prototype.set = function (this: Map<unknown, unknown>, k: unknown, v: unknown) {
    kinds.add(typeof k);
    return set.call(this, k, v);
  };
  try {
    f();
  } finally {
    Map.prototype.set = set;
  }
  return kinds;
}

test("weld: more than ~1e5 distinct cells per axis falls back to decimal-string keys (BigInt beyond 2^52)", () => {
  // 105 000 points at spacing 3·tau along x: per-axis gaps cap at 2, so R = 2·105 000 + 1 > 2^53^(1/3) ≈ 208 064 and
  // compressed_cells gives up; the reference loop then runs on string keys. None of the grid points weld together.
  const tau = 1e-3, n = 105_000;
  const V: number[][] = [];
  for (let k = 0; k < n; k++) V.push([3 * tau * k, 0, 0]);
  const probes = [
    [3 * tau * 5 + 0.9 * tau, 0.9 * tau, -0.9 * tau], // within tau of point 5 on every axis
    [3 * tau * 7 + 1.1 * tau, 0, 0], // 1.1·tau from 7, 1.9·tau from 8: a new representative
    [3 * tau * 9 - 0.5 * tau, 0, 0], // the neighbour cell below point 9's
    [1e13, 0, 0], // x / tau = 1e16 > 2^52: the BigInt branch of cell_part
    [1e13, 5e-4, 0], // the cell above in y, same x cell: joins the previous probe
    [1e13 + 2 ** -9, 0, 0], // the next float above 1e13 (spacing 2^-9 > tau): not welded
  ];
  V.push(...probes);
  let rep: number[] = [];
  const kinds = map_key_types(() => {
    rep = weld_map(V, tau);
  });
  assert.ok(kinds.has("string"), "the cell dictionary is keyed by strings"); // (number keys: compressed_cells' own index)
  assert.ok(!map_key_types(() => weld_map(V.slice(0, 1000), tau)).has("string")); // the compressed path below the cap
  for (let k = 0; k < n; k++) assert.equal(rep[k], k);
  assert.deepEqual(rep.slice(n), [5, n + 1, 9, n + 3, n + 3, n + 5]);
  // the brute-force rule on the probes: the lowest index within tau (max norm) among the representatives before it
  for (let i = n; i < V.length; i++) {
    const p = V[i] as number[];
    let best = i;
    for (let r = 0; r < i; r++) {
      if (rep[r] !== r) continue;
      const w = V[r] as number[];
      if (w.every((x, a) => Math.abs(x - (p[a] as number)) <= tau)) { best = r; break; }
    }
    assert.equal(rep[i], best, `probe ${i - n}`);
  }
});

test("weld: the split-vertex box reproduces the parametric vertices", () => {
  const [W, faces, index] = weld_vertices(SPLIT_V, SPLIT_F, 1e-6);
  assert.deepEqual(W, CUBE_V);
  assert.deepEqual(index, [...Array(24).keys()].map((k) => k % 8));
  assert.deepEqual(faces[0], [0, 3, 2]);
  assert.deepEqual(faces[faces.length - 1], [3, 4, 7]);
});

test("weld: dense grid at spacing tau and the cell-rounding border (reference loop)", () => {
  const g = [0, 1, 2, 3, 4, 5].map((k) => k * 1e-3);
  const V: number[][] = [];
  for (const x of g) for (const y of g) for (const z of g) V.push([x, y, z]);
  const rep = weld_map(V, 1e-3);
  // every grid point is within tau of its lower neighbours: each vertex joins the lowest-index representative near it
  for (let i = 0; i < V.length; i++) {
    const r = rep[i] as number;
    assert.ok(r <= i && rep[r] === r);
    const a = V[i] as number[], b = V[r] as number[];
    assert.ok(a.every((x, k) => Math.abs(x - (b[k] as number)) <= 1e-3));
  }
  const tau = 0.1;
  assert.deepEqual(weld_map([[0.04999999999999999, 0, 0], [-0.04999999999999999 - 0.1 + 1e-17, 0, 0], [0.0, 0, 0]], tau), [0, 1, 0]);
});

// --- degenerate faces (step 3) ---------------------------------------------------------------------------------------

test("degenerate faces: collapse, pairwise distinct, Newell norm threshold", () => {
  const V = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0], [2, 0, 0], [1e-7, 0, 0]];
  const faces = [[0, 1, 2, 1], [0, 0, 1, 2], [0, 1, 2, 0], [0, 1, 4], [1, 1, 1], [0, 1], [0, 5, 3], [0, 2, 3]];
  let [kept, idx] = drop_degenerate_faces(V, faces, 1.0);
  assert.deepEqual(kept, [[0, 1, 2], [0, 1, 2], [0, 5, 3], [0, 2, 3]]);
  assert.deepEqual(idx, [1, 2, 6, 7]);
  [kept, idx] = drop_degenerate_faces(V, faces, 1e3); // threshold 1e-12 * 1e6 = 1e-6 > 1e-7
  assert.deepEqual(idx, [1, 2, 7]);
});

test("degenerate faces: MESH_DEGENERATE_FACES and compaction", () => {
  const [mesh, , fallback, , warnings] = prep([...CUBE_V, [5.0, 5.0, 5.0]], [...CUBE_F, [0, 1, 0], [8, 8, 8]]);
  assert.deepEqual(codes(warnings), ["MESH_DEGENERATE_FACES"]);
  assert.match((warnings[0] as { message: string }).message, /2 degenerate/);
  assert.deepEqual((warnings[0] as { ids: string[] }).ids, ["m"]);
  assert.equal(fallback, false);
  assert.deepEqual(mesh.vertices, CUBE_V); // the unused vertex 8 is removed
  const [V2, f2, old] = compact_vertices([[0, 0, 0], [9, 9, 9], [1, 0, 0], [0, 1, 0]], [[3, 2, 0]]);
  assert.deepEqual(V2, [[0, 0, 0], [1, 0, 0], [0, 1, 0]]);
  assert.deepEqual(f2, [[2, 1, 0]]);
  assert.deepEqual(old, [0, 2, 3]);
});

// --- triangles (step 4) ----------------------------------------------------------------------------------------------

test("triangles are fans at the first vertex (mesh.triangulate_faces)", () => {
  assert.deepEqual(triangulate([[0, 1, 2, 3, 4], [5, 6, 7]]), [[0, 1, 2], [0, 2, 3], [0, 3, 4], [5, 6, 7]]);
  assert.deepEqual(triangulate_faces([[0, 1, 2, 3], [4, 5, 6, -1]], [4, 3]), [[0, 1, 2], [0, 2, 3], [4, 5, 6]]);
  assert.deepEqual(triangulate_faces([], []), []);
  const [, tris] = prep(CUBE_V, CUBE_F);
  assert.deepEqual(tris.slice(0, 2), [[0, 3, 2], [0, 2, 1]]);
  assert.equal(tris.length, 12);
});

// --- adjacency / manifold / orientation (step 5) ---------------------------------------------------------------------

test("a manifold box is unchanged and equals the parametric box", () => {
  for (const [V, F] of [[CUBE_V, CUBE_F], [SPLIT_V, SPLIT_F]] as const) {
    const [mesh, , fallback, groups, warnings] = prep(V as number[][], F as number[][]);
    const ref = box_mesh([1, 1, 1]);
    assert.deepEqual(warnings, []);
    assert.equal(fallback, false);
    assert.deepEqual(groups, [0, 0, 0, 0, 0, 0]);
    assert.deepEqual(mesh.faces, CUBE_F);
    assert.deepEqual(ref.faces, CUBE_F);
    for (const key of ["vertices", "edges", "face_normals", "edge_faces", "edge_flipped"] as const) assert.deepEqual(mesh[key], ref[key], key);
    assert.deepEqual(mesh.edge_smooth, new Array(12).fill(false));
  }
});

test("propagation fixes one flipped face (MESH_WINDING_FIXED)", () => {
  const F = CUBE_F.map((f) => [...f]);
  F[4] = flip(F[4] as number[]);
  const adj = build_adjacency(F, 8);
  assert.ok(adj.manifold && !adj.consistent);
  const [out, flipped, comps, conflict] = fix_orientation(F, adj);
  assert.equal(conflict, false);
  assert.deepEqual(flipped, [false, false, false, false, true, false]);
  assert.deepEqual(comps, [[0, 1, 2, 3, 4, 5]]);
  assert.deepEqual(out, CUBE_F);
  const [mesh, , fallback, , warnings] = prep(CUBE_V, F);
  assert.deepEqual(codes(warnings), ["MESH_WINDING_FIXED"]);
  assert.deepEqual(mesh.faces, CUBE_F);
  assert.equal(fallback, false);
});

test("an inside-out box is flipped by the signed volume; the triangles follow the fix", () => {
  const F = CUBE_F.map(flip);
  assert.ok(build_adjacency(F, 8).consistent);
  approx(signed_volume(CUBE_V, triangulate(F)), -1.0);
  const [mesh, tris, , , warnings] = prep(CUBE_V, F);
  assert.deepEqual(codes(warnings), ["MESH_WINDING_FIXED"]);
  assert.deepEqual(mesh.faces, CUBE_F);
  approx(signed_volume(mesh.vertices, tris), 1.0);
  assert.ok(point_inside_mesh(mesh.vertices, tris, [0, 0, 0.5], 1e-9));
});

function hollow_box(inner_outward = false): [number[][], number[][]] {
  const outer = box_mesh([2, 2, 2]);
  const inner = box_mesh([1, 1, 1]);
  const V = [...outer.vertices.map((v) => [...v]), ...inner.vertices.map(([x, y, z]) => [x, y, z + 0.5])];
  const F_in = inner.faces.map((f) => (inner_outward ? f.map((v) => v + 8) : flip(f.map((v) => v + 8))));
  return [V, [...outer.faces.map((f) => [...f]), ...F_in]];
}

test("a hollow box keeps its inverted cavity shell (nesting parity); a light in the cavity is outside", () => {
  let [V, F] = hollow_box();
  let [mesh, tris, fallback, , warnings] = prep(V, F);
  assert.deepEqual(warnings, []);
  assert.equal(fallback, false);
  assert.deepEqual(mesh.faces, F);
  assert.ok(!point_inside_mesh(mesh.vertices, tris, [0, 0, 1.0], 1e-9));
  assert.ok(point_inside_mesh(mesh.vertices, tris, [0.75, 0.75, 1.0], 1e-9));
  approx(winding_number(mesh.vertices, tris, [0, 0, 1.0]), 0.0);
  const F_ref = F;
  [V, F] = hollow_box(true); // a cavity shell authored outward is flipped inward (depth 1 -> odd -> inward)
  [mesh, tris, fallback, , warnings] = prep(V, F);
  assert.deepEqual(codes(warnings), ["MESH_WINDING_FIXED"]);
  assert.deepEqual(mesh.faces, F_ref);
  assert.ok(!point_inside_mesh(mesh.vertices, tris, [0, 0, 1.0], 1e-9));
});

test("a zero-volume closed component keeps its orientation", () => {
  const V = [...CUBE_V, [3, 0, 0], [4, 0, 0], [3, 1, 0]];
  const F = [...CUBE_F, [8, 9, 10], [8, 10, 9]];
  assert.ok(build_adjacency(F, 11).manifold);
  const [, , fallback, , warnings] = prep(V, F);
  assert.deepEqual(warnings, []);
  assert.equal(fallback, false);
});

function mobius(n = 8): [number[][], number[][]] {
  const V: number[][] = [];
  const F: number[][] = [];
  for (let k = 0; k < n; k++) {
    const t = 2 * Math.PI * k / n;
    for (const s of [-0.3, 0.3]) {
      const r = 1 + s * Math.cos(t / 2);
      V.push([r * Math.cos(t), r * Math.sin(t), s * Math.sin(t / 2)]);
    }
  }
  for (let k = 0; k < n; k++) {
    const a = 2 * k, b = 2 * k + 1;
    const [c, d] = k < n - 1 ? [2 * k + 2, 2 * k + 3] : [1, 0]; // the half twist
    F.push([a, c, d, b]);
  }
  return [V, F];
}

/** Closed, every edge on exactly two faces, not orientable (twisted identification). */
function klein(N = 6, M = 4): [number[][], number[][]] {
  const vid = (i: number, j: number): number => {
    if (i === N) {
      i = 0;
      j = (M - j) % M;
    }
    return i * M + (j % M);
  };
  const V: number[][] = [];
  for (let i = 0; i < N; i++) {
    const u = 2 * Math.PI * i / N;
    for (let j = 0; j < M; j++) {
      const w = 2 * Math.PI * j / M;
      const r = 2 + Math.cos(w);
      V.push([r * Math.cos(u), r * Math.sin(u), Math.sin(w) + 0.1 * i]);
    }
  }
  const F: number[][] = [];
  for (let i = 0; i < N; i++) for (let j = 0; j < M; j++) F.push([vid(i, j), vid(i + 1, j), vid(i + 1, j + 1), vid(i, j + 1)]);
  return [V, F];
}

test("a Möbius strip is not manifold (open edges)", () => {
  const [V, F] = mobius();
  const [, , fallback, , warnings] = prep(V, F);
  assert.equal(fallback, true);
  assert.deepEqual(codes(warnings), ["MESH_NON_MANIFOLD"]);
  const msg = (warnings[0] as { message: string }).message;
  assert.ok(!msg.includes("inconsistent winding") && msg.includes("with 1 face"));
});

test("a closed Klein-bottle connectivity is inconsistent winding -> MESH_NON_MANIFOLD", () => {
  const [V, F] = klein();
  const adj = build_adjacency(F, V.length);
  assert.ok(adj.manifold);
  assert.equal(fix_orientation(F, adj)[3], true);
  const [, , fallback, , warnings] = prep(V, F);
  assert.equal(fallback, true);
  assert.deepEqual(codes(warnings), ["MESH_NON_MANIFOLD"]);
  assert.match((warnings[0] as { message: string }).message, /inconsistent winding/);
});

test("an open box takes the fallback mesh (contract §5.2.5)", () => {
  const F = [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];
  const [mesh, tris, fallback, , warnings] = prep(CUBE_V, F);
  assert.equal(fallback, true);
  assert.deepEqual(codes(warnings), ["MESH_NON_MANIFOLD"]);
  assert.match((warnings[0] as { message: string }).message, /4 edge\(s\) with 1 face/);
  assert.deepEqual(mesh.faces, F);
  assert.deepEqual(mesh.edge_smooth, new Array(12).fill(false));
  const ef = new Map(mesh.edges.map((e, k) => [edge_key(e), mesh.edge_faces[k]] as const));
  assert.deepEqual(ef.get("0,1"), [1, 1]);
  assert.deepEqual(ef.get("4,5"), [0, 1]);
  assert.deepEqual(ef.get("0,4"), [1, 4]);
  const fl = new Map(mesh.edges.map((e, k) => [edge_key(e), mesh.edge_flipped[k]] as const));
  assert.deepEqual(fl.get("4,5"), [false, true]);
  assert.deepEqual(fl.get("0,4"), [true, false]);
  assert.deepEqual(mesh.face_normals[0], [0, 0, 1]);
  assert.equal(tris.length, 10);
  assert.deepEqual(fallback_mesh(CUBE_V, F, CUBE_V.map((_v, k) => `v${k}`)).edges, mesh.edges);
});

// --- coplanar merge (step 6) -----------------------------------------------------------------------------------------

test("a triangulated box merges into the six parametric quads (seed start vertices 0, 4, 0, 1, 2, 3)", () => {
  const [W, faces] = weld_vertices(SPLIT_V, SPLIT_F, 1e-6);
  const adj = build_adjacency(faces, 8);
  const [merged, origin] = merge_coplanar(W, faces, face_normals_newell(W, faces), adj, Math.cos(COPLANAR_TOL_RAD));
  assert.deepEqual(merged, CUBE_F);
  assert.deepEqual(origin, [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(merged.map((f) => f[0]), [0, 4, 0, 1, 2, 3]);
});

test("the merge reads the edges of the oriented faces (inside-out and one-flipped split boxes)", () => {
  const one = SPLIT_F.map((f) => [...f]);
  one[4] = flip(one[4] as number[]);
  for (const F of [SPLIT_F.map(flip), one]) {
    const [mesh, tris, fallback, , warnings] = prep(SPLIT_V, F);
    assert.deepEqual(codes(warnings), ["MESH_WINDING_FIXED"]);
    assert.equal(fallback, false);
    assert.deepEqual(mesh.faces, CUBE_F);
    assert.deepEqual(mesh.edge_smooth, new Array(12).fill(false));
    approx(signed_volume(mesh.vertices, tris), 1.0);
  }
});

/** A 16-gon prism whose caps are centre fans (bottom ring 0..n-1, top ring n..2n-1, centres 2n, 2n+1). */
function fan_prism(n = 16, r = 1.0, h = 2.0): [number[][], number[][]] {
  const ring = [...Array(n).keys()].map((k) => [r * Math.cos(2 * Math.PI * k / n), r * Math.sin(2 * Math.PI * k / n)] as [number, number]);
  const V = [...ring.map(([x, y]) => [x, y, 0.0]), ...ring.map(([x, y]) => [x, y, h]), [0.0, 0.0, 0.0], [0.0, 0.0, h]];
  const cb = 2 * n, ct = 2 * n + 1;
  const F: number[][] = [];
  for (let k = 0; k < n; k++) F.push([cb, (k + 1) % n, k]);
  for (let k = 0; k < n; k++) F.push([ct, n + k, n + (k + 1) % n]);
  for (let k = 0; k < n; k++) F.push([k, (k + 1) % n, n + (k + 1) % n, n + k]);
  return [V, F];
}

test("a centre-fan cap starts at the first boundary vertex of the seed and keeps the edge-less centre", () => {
  const [V, F] = fan_prism();
  const [mesh, tris, fallback, , warnings] = prep(V, F);
  assert.deepEqual(warnings, []);
  assert.equal(fallback, false);
  assert.equal(mesh.faces.length, 18);
  assert.deepEqual(mesh.faces[0], [1, 0, ...[...Array(14).keys()].map((k) => 15 - k)]);
  assert.deepEqual(mesh.faces[1], [...Array(16).keys()].map((k) => 16 + k));
  assert.equal(mesh.vertices.length, 34);
  const used = new Set(mesh.edges.flat());
  assert.ok(!used.has(32) && !used.has(33));
  assert.equal(tris.length, 64);
  assert.ok(tris.flat().includes(32));
  const smooth = smooth_map(mesh);
  for (let k = 0; k < 16; k++) assert.equal(smooth.get(`${k},${k + 16}`), true);
  assert.equal([...smooth.values()].filter((s) => s).length, 16);
});

/** A 4x4x1 box with a 1x1x1 boss on top: the top face is a square ring of 8 triangles (a region with a hole). */
function boss_box(): [number[][], number[][]] {
  const o = [[-2, -2, 1], [2, -2, 1], [2, 2, 1], [-2, 2, 1]];
  const i = [[-.5, -.5, 1], [.5, -.5, 1], [.5, .5, 1], [-.5, .5, 1]];
  const it = i.map(([x, y]) => [x as number, y as number, 2]);
  const ob = o.map(([x, y]) => [x as number, y as number, 0]);
  const V = [...o, ...i, ...it, ...ob];
  const F: number[][] = [];
  for (let k = 0; k < 4; k++) {
    const a = k, b = (k + 1) % 4;
    F.push([a, b, 4 + b], [a, 4 + b, 4 + a]);
  }
  F.push([8, 9, 10, 11]);
  for (let k = 0; k < 4; k++) F.push([4 + k, 4 + (k + 1) % 4, 8 + (k + 1) % 4, 8 + k]);
  F.push([12, 15, 14, 13]);
  for (let k = 0; k < 4; k++) F.push([12 + k, 12 + (k + 1) % 4, (k + 1) % 4, k]);
  return [V, F];
}

test("a square-ring region with a hole is left unmerged; its interior edges are smooth (also at 0 deg)", () => {
  const [V, F] = boss_box();
  const [mesh, , fallback, , warnings] = prep(V, F);
  assert.deepEqual(warnings, []);
  assert.equal(fallback, false);
  assert.deepEqual(mesh.faces.slice(0, 8), F.slice(0, 8));
  assert.equal(mesh.faces.length, F.length);
  for (const deg of [30.0, 0.0]) {
    const [m] = prep(V, F, null, 1.0, WELD_TOLERANCE_DEFAULT, deg);
    const smooth = smooth_map(m);
    for (const [a, b] of [[0, 5], [1, 5], [1, 6], [2, 6], [2, 7], [3, 7], [3, 4], [0, 4]] as const) {
      assert.equal(smooth.get(`${Math.min(a, b)},${Math.max(a, b)}`), true);
    }
    assert.equal([...smooth.values()].filter((s) => s).length, 8);
  }
});

test("bent strip: regions {0..6}, {7..13}, {14..19} on merge_coplanar", () => {
  const n = 20, theta = 1.5e-4;
  const V = [...Array(n + 2).keys()].map((k) => [0.5 * k, k % 2, 0.0]);
  const F = [...Array(n).keys()].map((k) => (k % 2 === 0 ? [k, k + 1, k + 2] : [k + 1, k, k + 2]));
  const normals = [...Array(n).keys()].map((k) => [Math.sin(k * theta), 0.0, Math.cos(k * theta)]);
  const [merged, origin] = merge_coplanar(V, F, normals, build_adjacency(F, n + 2), Math.cos(COPLANAR_TOL_RAD));
  assert.deepEqual(origin, [0, 7, 14]);
  assert.equal(merged.length, 3);
  const sorted = (f: number[]): number[] => [...f].sort((a, b) => a - b);
  const range = (a: number, b: number): number[] => [...Array(b - a).keys()].map((k) => a + k);
  assert.deepEqual(sorted(merged[0] as number[]), range(0, 9));
  assert.deepEqual(sorted(merged[1] as number[]), range(7, 16));
  assert.deepEqual(sorted(merged[2] as number[]), range(14, 22));
  assert.deepEqual(merged.map((f) => f[0]), [0, 8, 14]);
});

test("merged faces take the seed's smoothing group", () => {
  const [, , , groups] = prep(SPLIT_V, SPLIT_F, [5, 5, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4]);
  assert.deepEqual(groups, [5, 0, 1, 2, 3, 4]);
});

// --- edge classification (step 7) ------------------------------------------------------------------------------------

test("classify_edges with and without smoothing groups", () => {
  const ref = prism_mesh([...Array(16).keys()].map((k) => [Math.cos(2 * Math.PI * k / 16), Math.sin(2 * Math.PI * k / 16)]), 2.0);
  const lateral = ref.edges.map(([i, j]) => i + 16 === j);
  const zeros = new Array(18).fill(0);
  assert.deepEqual(classify_edges(ref, 30.0, zeros), lateral);
  assert.ok(classify_edges(ref, 20.0, zeros).every((s) => !s));
  assert.ok(classify_edges(ref, 90.0, zeros).every((s) => s)); // 90 deg within the band
  assert.deepEqual(classify_edges(ref, 0.0, [0, 0, ...new Array(16).fill(1)]), lateral);
  assert.ok(classify_edges(ref, 0.0, new Array(18).fill(7)).every((s) => s));
  assert.ok(classify_edges(ref, 30.0, [0, 0, ...[...Array(16).keys()].map((k) => (k % 2 === 0 ? 1 : 2))]).every((s) => !s));
  const s = classify_edges(ref, 30.0, [0, 0, ...new Array(8).fill(1), ...new Array(8).fill(0)]);
  assert.equal(s.filter((x) => x).length, 14); // 7 edges inside each half (group 1 / group 0)
});

test("inherit_edge_smooth on a receiver-clipped mesh", () => {
  const [V, F] = fan_prism();
  const [mesh] = prep(V, F);
  const m: Mesh = { ...mesh, vertices: mesh.vertices.map(([x, y, z]) => [x, y, z - 1.0]) }; // half buried
  const [clipped, origins] = clip_mesh_to_plane(m, [0, 0, 1.0, 0], 1e-9);
  const flags = inherit_edge_smooth(clipped, origins, mesh, mesh.edge_smooth as boolean[]);
  const edge_index = new Map(mesh.edges.map((e, k) => [edge_key(e), k] as const));
  clipped.edges.forEach(([a, b], k) => {
    const oa = origins[a] as Origin, ob = origins[b] as Origin;
    const s = flags[k] as boolean;
    if (typeof oa === "object" && typeof ob === "object") {
      assert.equal(s, false); // cut-face edge: feature
    } else if (typeof oa === "object" || typeof ob === "object") {
      const [cross, v] = typeof oa === "object" ? [oa, ob as number] : [ob as { i: number; j: number }, oa];
      if (cross.i + 16 === cross.j && (v === cross.i || v === cross.j)) assert.equal(s, true);
    } else {
      const e = edge_index.get(`${Math.min(oa, ob as number)},${Math.max(oa, ob as number)}`) as number;
      assert.equal(s, (mesh.edge_smooth as boolean[])[e]);
    }
  });
  assert.equal(flags.filter((x) => x).length, 16);
});

// --- point_inside_mesh (step 8) --------------------------------------------------------------------------------------

test("point_inside_mesh: |w| > 0.75 and the distance clause", () => {
  const [mesh, tris] = prep(CUBE_V, CUBE_F);
  const V = mesh.vertices;
  assert.ok(point_inside_mesh(V, tris, [0, 0, 0.5], 1e-9));
  approx(winding_number(V, tris, [0, 0, 0.5]), 1.0);
  assert.ok(!point_inside_mesh(V, tris, [0, 0, 1.5], 1e-9));
  assert.ok(!point_inside_mesh(V, tris, [2, 0.1, 0.5], 1e-9));
  approx(winding_number(V, tris, [0, 0, 1.0]), 0.5);
  assert.ok(!point_inside_mesh(V, tris, [0, 0, 1.0 - 0.5e-9], 1e-9));
  assert.ok(!point_inside_mesh(V, tris, [0.5 - 1e-10, 0.2, 0.3], 1e-9));
  assert.ok(point_inside_mesh(V, tris, [0, 0, 1.0 - 2e-9], 1e-9));
  const t5 = triangulate(CUBE_F.slice(0, 5)), t4 = triangulate(CUBE_F.slice(0, 4));
  approx(winding_number(V, t5, [0, 0, 0.5]), 5 / 6);
  assert.ok(point_inside_mesh(V, t5, [0, 0, 0.5], 1e-9));
  assert.ok(!point_inside_mesh(V, t4, [0, 0, 0.5], 1e-9));
  const inv = triangulate(CUBE_F.map(flip));
  approx(winding_number(V, inv, [0, 0, 0.5]), -1.0);
  assert.ok(point_inside_mesh(V, inv, [0, 0, 0.5], 1e-9));
  assert.ok(point_inside_mesh(V, tris, [0, 0, 0.5, 1.0], 1e-9)); // a homogeneous L: only x, y, z are read
  assert.ok(!point_inside_mesh(V, [], [0, 0, 0.5], 1e-9));
});

// --- the whole pipeline ----------------------------------------------------------------------------------------------

test("preprocess_mesh without a usable face throws a clear error (direct calls only)", () => {
  for (const [scale, weld] of [[1.0, 10.0], [1e-7, WELD_TOLERANCE_DEFAULT]] as const) {
    assert.throws(() => prep(CUBE_V, CUBE_F, null, scale, weld), /no usable face/);
  }
});

test("preprocess_mesh is deterministic and does not mutate its input", () => {
  const [V, F] = fan_prism();
  const data = { vertices: V.map((v) => [...v]), faces: F.map((f) => [...f]) };
  const a = preprocess_mesh(data, 1.0, 1e-6, 30.0, "m");
  const b = preprocess_mesh(data, 1.0, 1e-6, 30.0, "m");
  assert.deepEqual(data, { vertices: V, faces: F });
  assert.deepEqual(a, b);
});

test("scale is applied before the weld", () => {
  const mm = CUBE_V.map((v) => v.map((c) => 1000 * c));
  const [mesh] = prep(mm, CUBE_F, null, 0.001);
  mesh.vertices.forEach((v, k) => v.forEach((c, j) => approx(c, (CUBE_V[k] as number[])[j] as number, 1e-15)));
  const near = [...CUBE_V.map((v) => [...v]), [-.5 + 5e-7, -.5, 0.0]];
  const [m2, , , , warnings] = prep(near, [[8, 3, 2, 1], ...CUBE_F.slice(1)]);
  assert.deepEqual(m2.faces[0], [0, 3, 2, 1]);
  assert.deepEqual(warnings, []);
  assert.equal(mesh_from_faces(m2.vertices, m2.faces).edges.length, 12);
});

test("preprocess_mesh(..., return_scale) appends scale_A", () => {
  const data = { vertices: SPLIT_V.map((v) => v.map((c) => 3 * c)), faces: SPLIT_F };
  const five = preprocess_mesh(data, 2.0, 1e-6, 30.0, "m");
  const six = preprocess_mesh(data, 2.0, 1e-6, 30.0, "m", true);
  assert.equal(five.length, 5);
  assert.equal(six.length, 6);
  assert.equal(six[5], 6.0);
  assert.deepEqual(six.slice(0, 5), five);
});

test("has_usable_face is the validation guard", () => {
  assert.ok(has_usable_face(CUBE_V, CUBE_F, 1.0, 1e-6));
  assert.ok(!has_usable_face(CUBE_V, CUBE_F, 1.0, 10.0)); // every face collapses
  assert.ok(!has_usable_face([[0, 0, 0], [1, 0, 0], [2, 1e-14, 0]], [[0, 1, 2]], 1.0, 0.0)); // a sliver below 1e-12
});

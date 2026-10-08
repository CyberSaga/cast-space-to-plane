/** Meshes, lit tests, silhouettes and plane projection (contract §2.3–§2.5) through the port. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { face_lit_flags, light_vector, lit, silhouette_edges, silhouette_loops } from "../src/light.js";
import { box_mesh, cone_mesh, cylinder_mesh, euler_characteristic, prism_mesh, sphere_mesh } from "../src/mesh.js";
import { build_object, point_inside_solid } from "../src/primitives.js";
import { clip_loop_to_plane, clip_mesh_to_plane, foot, mat4_vec, shadow_loop, shadow_matrix, shadow_w } from "../src/shadow.js";
import type { Vec4 } from "../src/types.js";

const GROUND = [0.0, 0.0, 1.0, 0.0];

function close(a: readonly number[], b: readonly number[], tol = 1e-12): void {
  assert.equal(a.length, b.length);
  a.forEach((x, i) => assert.ok(Math.abs(x - (b[i] as number)) <= tol, `${a} vs ${b}`));
}

test("builders: closed genus-0 meshes, sorted edges, outward normals", () => {
  for (const m of [box_mesh([1, 2, 3]), prism_mesh([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], 1),
    cylinder_mesh(0.5, 2), cone_mesh(0.5, 1), sphere_mesh(1)]) {
    assert.equal(euler_characteristic(m), 2);
    for (let e = 1; e < m.edges.length; e++) {
      const [a, b] = m.edges[e - 1] as [number, number], [c, d] = m.edges[e] as [number, number];
      assert.ok(a < b && (a < c || (a === c && b < d)));
    }
    m.edge_faces.forEach(([f0, f1]) => assert.ok(f0 < f1));
  }
  const box = box_mesh([1, 1, 1]);
  assert.equal(box.edges.length, 12);
  close(box.face_normals[0] as number[], [0, 0, -1]);
  close(box.face_normals[1] as number[], [0, 0, 1]);
  close(box.face_normals[2] as number[], [0, -1, 0]);
  close(box.face_normals[3] as number[], [1, 0, 0]);
  assert.equal(prism_mesh([[0, 0], [1, 0], [0, 1]], 1).faces.length, 5);
});

test("unit box under the overhead lamp: top lit, loop = top square, shadows x1.5 (spec §7.2)", () => {
  const box = box_mesh([1, 1, 1]);
  const L = light_vector({ type: "point", position: [0, 0, 3] });
  const { lit: lits, parallel } = face_lit_flags(box, L, 1e-9);
  assert.deepEqual(lits, [false, true, false, false, false, false]);
  assert.ok(parallel.every((p) => !p));
  assert.equal(silhouette_edges(box, lits).length, 4);
  const loops = silhouette_loops(box, lits);
  assert.equal(loops.length, 1);
  assert.deepEqual([...(loops[0] as number[])].sort(), [4, 5, 6, 7]);
  const M = shadow_matrix(GROUND, L);
  close(mat4_vec(M, L), [0, 0, 0, 0]);
  const top = (loops[0] as number[]).map((v) => [...(box.vertices[v] as number[]), 1] as Vec4);
  const sh = shadow_loop(top, M, GROUND, 1e-9);
  assert.equal(sh.unbounded, false);
  const xy = sh.vertices.map((s) => [s[0] / s[3], s[1] / s[3], s[2] / s[3]]);
  for (const p of xy) {
    assert.ok(Math.abs(Math.abs(p[0] as number) - 0.75) <= 1e-12 && Math.abs(Math.abs(p[1] as number) - 0.75) <= 1e-12);
    assert.equal(p[2], 0);
  }
  let area = 0;
  for (let i = 0; i < xy.length; i++) {
    const p = xy[i] as number[], q = xy[(i + 1) % xy.length] as number[];
    area += (p[0] as number) * (q[1] as number) - (q[0] as number) * (p[1] as number);
  }
  assert.ok(area > 0, "counter-clockwise in ground (x, y)");
  assert.equal(shadow_w(GROUND, L, [0.5, 0.5, 1, 1]), 2);
  close(foot(GROUND, [1, 2, 3, 1]), [1, 2, 0, 1]);
  assert.ok(lit([0, 0, 1], [0, 0, 1], L, 1e-9));
});

test("a vertex above the point light: direction vertices and an arc at infinity", () => {
  const L = light_vector({ type: "point", position: [0, 0, 1] });
  const M = shadow_matrix(GROUND, L);
  const loop: Vec4[] = [[1, -0.2, 0.5, 1], [1, 0.2, 0.5, 1], [1, 0.2, 2, 1], [1, -0.2, 2, 1]];
  const sh = shadow_loop(loop, M, GROUND, 1e-9);
  assert.equal(sh.unbounded, true);
  assert.ok(sh.vertices.some((v) => v[3] === 0));
  for (const v of sh.vertices) if (v[3] === 0) assert.ok(Math.abs(Math.hypot(v[0], v[1], v[2]) - 1) <= 1e-12);
});

test("ground clip of a loop and of a buried box", () => {
  const [P, src, below] = clip_loop_to_plane([[0, 0, -1, 1], [1, 0, 1, 1], [0, 1, 1, 1]], GROUND, 1e-9);
  assert.equal(below, true);
  assert.equal(P.length, 4);
  // contract §5.4.2: every source is a tagged object, `{kind: "vertex", index}` for a kept input vertex
  assert.deepEqual(src, [{ kind: "ground", i: { kind: "vertex", index: 0 }, j: { kind: "vertex", index: 1 } },
    { kind: "vertex", index: 1 }, { kind: "vertex", index: 2 },
    { kind: "ground", i: { kind: "vertex", index: 2 }, j: { kind: "vertex", index: 0 } }]);
  const obj = build_object({ id: "b", type: "box", size: [1, 1, 1], transform: { position: [0, 0, -0.5], rotation_deg: [10, 20, 0] } });
  const [clipped, origins] = clip_mesh_to_plane(obj.mesh, GROUND, 1e-9);
  assert.equal(euler_characteristic(clipped), 2);
  assert.equal(clipped.vertices.length, origins.length);
  for (const v of clipped.vertices) assert.ok(v[2] >= -1e-9);
});

test("point_inside_solid for boxes and prisms, never for curved objects", () => {
  const box = build_object({ id: "b", type: "box", size: [2, 2, 2], transform: { position: [1, 0, 0], rotation_deg: [0, 0, 45] } });
  assert.ok(point_inside_solid(box, [1, 0, 1], 1e-9));
  assert.ok(!point_inside_solid(box, [1, 0, 2.5], 1e-9));
  const prism = build_object({ id: "p", type: "prism", polygon: [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]], height: 1,
    transform: { position: [0, 0, 0], rotation_deg: [0, 0, 0] } });
  assert.ok(point_inside_solid(prism, [0.5, 0.5, 0.5]));
  assert.ok(!point_inside_solid(prism, [1.5, 1.5, 0.5]));
  const cyl = build_object({ id: "c", type: "cylinder", radius: 1, height: 1, transform: { position: [0, 0, 0], rotation_deg: [0, 0, 0] } });
  assert.ok(!point_inside_solid(cyl, [0, 0, 0.5]));
  assert.equal(cyl.analytic?.kind, "cylinder");
});

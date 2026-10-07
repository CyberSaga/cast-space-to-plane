/**
 * Sampled hidden-line removal in the port (contract §5.1.6, §5.1.7, §5.1.8, §5.1.11; phase 2 of §5.4.14). Ported from
 * `tests/test_hidden.py`: the `N` table and the constants, the sampling / bisection rule, the exact occluders against the
 * generic mesh occluder, the occlusion predicate, the drawn 4-D geometry (incl. the `w = 0` endpoint), the hand values
 * of `wall_and_ground_hidden` through the port alone, determinism, culled = unculled, purity, the run-record invariants
 * on every conformance case with the switch on, and the hidden-run SVG groups.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { project } from "../src/camera.js";
import {
  HLR_BISECTIONS, HLR_MAX_SAMPLES, HLR_MIN_SAMPLES, HLR_RAY_EPS, HLR_SPACING_MM, classify_curve, classify_document, clip_polygon_4d,
  drawn_segment_4d, first_hit, hlr_sample_count, hlr_tol_mm, image_bounds, mesh_occluder, occluded, occluder, scene_occluders,
} from "../src/hidden.js";
import type { Occluder } from "../src/hidden.js";
import { dumps } from "../src/output/geometry_json.js";
import { write_svg } from "../src/output/svg.js";
import { compose, project_scene, render, shadow_geometry } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import type { Mat3, Vec3 } from "../src/types.js";
import { json_stems, read_json, repo_path } from "./helpers.js";

const CASES = repo_path("tests", "conformance", "cases");

function load_case(name: string): any {
  const scene = read_json(`${CASES}/${name}.json`);
  delete scene.description;
  return scene;
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x));
}

function render_hidden(scene: any, hidden_style: string | null = null): { geometry: any; svg: string } {
  return render(load_scene(scene), null, true, hidden_style) as { geometry: any; svg: string };
}

function wall_and_ground_scene(): any {
  return {
    version: "0.1", units: "m", up: "z",
    objects: [{ id: "crate", type: "box", size: [1, 1, 1], transform: { position: [0, 4.5, 0] } }],
    lights: [{ id: "lamp", type: "point", position: [0, 2, 3] }],
    receivers: [
      { id: "ground", type: "plane", normal: [0, 0, 1], offset: 0 },
      { id: "wall", type: "plane", normal: [0, -1, 0], offset: 6, bounds: [[-3, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]] },
    ],
    camera: { position: [0, -1, 1.6], target: [0, 6, 0.8], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [273, 182] },
  };
}

/** `tests/test_receivers.py::fold_curved_cylinder_scene`: a cylinder whose shadow folds from the ground onto the wall. */
function fold_curved_cylinder_scene(): any {
  const scene = wall_and_ground_scene();
  scene.objects = [{ id: "pillar", type: "cylinder", radius: 0.4, height: 1.5, transform: { position: [0, 5, 0] } }];
  return scene;
}

function curved_unbounded_scene(): any {
  return {
    version: "0.1", units: "m", up: "z",
    objects: [
      { id: "ball", type: "sphere", radius: 0.6, transform: { position: [1.4, 1.5, 0] } },
      { id: "post", type: "cylinder", radius: 0.3, height: 2.0, transform: { position: [-1.4, 1.8, 0] } },
    ],
    lights: [{ id: "lamp", type: "point", position: [0, 0.2, 1.0] }],
    receivers: [{ id: "ground", type: "plane", normal: [0, 0, 1], offset: 0 }],
    camera: { position: [0.5, -6, 2.2], target: [0, 2, 0.6], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [360, 240], hidden_lines: true },
  };
}

function vp_in_canvas_scene(): any {
  const scene = load_case("degenerate_vertex_above_point_light");
  scene.output = { ...(scene.output ?? {}), hidden_lines: true };
  return scene;
}

/** `wall_and_ground_hidden` seen from inside the crate along the y axis: the crate's ground shadow has a vertex on the
 * extended-canvas corner (a rounding-level fourth functional); every shadow edge is hidden (camera in a solid). */
function canvas_corner_scene(): any {
  const scene = wall_and_ground_scene();
  scene.camera.position = [0, 4.5, 0.5];
  scene.camera.target = [0, 6, 0.5];
  scene.output.hidden_lines = true;
  return scene;
}

const SCENES: Record<string, () => any> = {
  wall_and_ground_hidden: () => ({ ...wall_and_ground_scene(), output: { canvas_mm: [273, 182], hidden_lines: true } }),
  fold_curved_cylinder: fold_curved_cylinder_scene,
  hidden_lines_curved_unbounded: curved_unbounded_scene,
  hidden_lines_vp_in_canvas: vp_in_canvas_scene,
  canvas_corner: canvas_corner_scene,
};

/** Deterministic PRNG (mulberry32) for the random-ray tests. */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function rot(R: Mat3, v: readonly number[]): Vec3 {
  return [0, 1, 2].map((i) => R[i]![0] * v[0]! + R[i]![1] * v[1]! + R[i]![2] * v[2]!) as Vec3;
}

function add(a: readonly number[], b: readonly number[]): Vec3 {
  return [a[0]! + b[0]!, a[1]! + b[1]!, a[2]! + b[2]!];
}

function lerp_mid(a: readonly number[], b: readonly number[]): Vec3 {
  return [0.5 * (a[0]! + b[0]!), 0.5 * (a[1]! + b[1]!), 0.5 * (a[2]! + b[2]!)];
}

// --------------------------------------------------------------------------- constants and the N table
test("hlr_sample_count: the N table of contract §5.1.11", () => {
  const table: [number, number][] = [[0.1, 8], [7.3, 8], [8.0, 8], [1023.9, 1024], [4095.9, 4096], [5000.0, 4096], [10.0, 10]];
  for (const [l, n] of table) assert.equal(hlr_sample_count(l), n, `l = ${l}`);
});

test("constants and the stated tolerance (§5.1.6.4)", () => {
  assert.deepEqual([HLR_SPACING_MM, HLR_MIN_SAMPLES, HLR_MAX_SAMPLES, HLR_BISECTIONS, HLR_RAY_EPS], [1.0, 8, 4096, 6, 1e-5]);
  assert.equal(hlr_tol_mm(100.0), 1.0 / 64.0);
  assert.equal(hlr_tol_mm(4096.0), 0.015625);
  assert.equal(hlr_tol_mm(8192.0), 8192.0 / 262144.0);
});

// --------------------------------------------------------------------------- the sampling / bisection rule
test("classify_curve: one boundary within the bracket width", () => {
  for (const b of [0.3, 0.5 + 1e-7, 0.91]) {
    const [vis, runs] = classify_curve((p) => p.map((x) => x < b), 0.0, 1.0, 50.0);
    assert.equal(vis, "partial");
    assert.deepEqual(runs.map((r) => r[2]), [true, false]);
    assert.ok(runs[0]![0] === 0.0 && runs[runs.length - 1]![1] === 1.0 && runs[0]![1] === runs[1]![0]);
    assert.ok(Math.abs(runs[0]![1] - b) <= 1.0 / (64 * 50) / 2 + 1e-15);
  }
});

test("classify_curve: uniform states and the midpoint parameters", () => {
  assert.deepEqual(classify_curve((p) => p.map((x) => x >= 0.0), 0.0, 1.0, 3.0), ["visible", []]);
  assert.deepEqual(classify_curve((p) => p.map((x) => x < -1.0), 0.0, 1.0, 3.0), ["hidden", []]);
  const seen: number[][] = [];
  classify_curve((p) => {
    seen.push([...p]);
    return p.map(() => true);
  }, 2.0, 6.0, 10.0);
  assert.equal(seen[0]!.length, 10);
  seen[0]!.forEach((x, i) => assert.ok(Math.abs(x - (2.0 + 4.0 * (i + 0.5) / 10)) <= 1e-15));
});

test("bisection keeps [lo, m] iff the midpoint state differs (two changes inside one bracket)", () => {
  const N = 8;
  const lo0 = 2.5 / N, hi0 = 3.5 / N;
  const [vis, runs] = classify_curve((p) => p.map((x) => !((x >= 0.33 && x <= 0.34) || x >= 0.40)), 0.0, 1.0, 8.0);
  assert.equal(vis, "partial");
  const b = runs[0]![1];
  assert.ok(lo0 < b && b < hi0);
  assert.ok(Math.abs(b - 0.40) <= (hi0 - lo0) / 64);
});

// --------------------------------------------------------------------------- occluders
function box_scene_record(kind: string, shape: Record<string, unknown>): any {
  const obj = { id: "o", type: kind, transform: { position: [0.3, -0.2, 0.1], rotation_deg: [10, -20, 35] }, ...shape };
  const scene = load_scene({
    version: "0.1", units: "m", up: "z", objects: [obj],
    lights: [{ id: "l", type: "point", position: [0, 0, 5] }],
    receivers: [{ id: "g", type: "plane", normal: [0, 0, 1], offset: 0 }],
    camera: { position: [0, -8, 3], target: [0, 0, 0.5], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [360, 240] },
  });
  return shadow_geometry(scene).objects[0];
}

const U_POLY = [[-1, -1], [1, -1], [1, 1], [0.5, 1], [0.5, -0.5], [-0.5, -0.5], [-0.5, 1], [-1, 1]];

for (const [kind, shape] of [["box", { size: [1.2, 0.7, 0.9] }], ["prism", { polygon: U_POLY, height: 0.8 }]] as const) {
  test(`exact ${kind} occluder agrees with the generic mesh occluder on random rays`, () => {
    const rec = box_scene_record(kind, shape);
    const exact = occluder(rec);
    const generic = mesh_occluder(rec);
    assert.equal(exact.kind, kind);
    assert.equal(generic.kind, "mesh");
    const r = rng(7);
    const u = (a: number, b: number): number => a + (b - a) * r();
    const pos = rec.frame[1] as Vec3;
    const O: Vec3[] = [], D: Vec3[] = [];
    for (let i = 0; i < 4000; i++) {
      const o: Vec3 = [u(-3, 3), u(-3, 3), u(-3, 3)];
      const target: Vec3 = [pos[0] + u(-0.8, 0.8), pos[1] + u(-0.8, 0.8), pos[2] + u(-0.8, 0.8) + 0.4];
      const s = u(0.2, 2.0);
      O.push(o);
      D.push([(target[0] - o[0]) * s, (target[1] - o[1]) * s, (target[2] - o[2]) * s]);
    }
    const t1 = first_hit(exact, O, D, 1e-9), t2 = first_hit(generic, O, D, 1e-9);
    let fin = 0;
    t1.forEach((t, i) => {
      assert.equal(Number.isFinite(t), Number.isFinite(t2[i]!), `ray ${i}`);
      if (Number.isFinite(t)) {
        fin++;
        assert.ok(Math.abs(t - t2[i]!) < 1e-9, `ray ${i}: ${t} vs ${t2[i]}`);
      }
    });
    assert.ok(fin > 500, `${fin} hits`);
    if (kind === "box") {                                          // convex faces: the fan triangulation is exact
      const tris: number[][] = [];
      for (const f of rec.mesh.faces as number[][]) for (let i = 1; i + 1 < f.length; i++) tris.push([f[0]!, f[i]!, f[i + 1]!]);
      const t3 = first_hit(mesh_occluder({ ...rec, triangles: tris }), O, D, 1e-9);
      t1.forEach((t, i) => {
        assert.equal(Number.isFinite(t), Number.isFinite(t3[i]!));
        if (Number.isFinite(t)) assert.ok(Math.abs(t - t3[i]!) < 1e-9);
      });
    }
  });
}

test("an unknown kind uses the generic occluder and never throws", () => {
  const rec = box_scene_record("box", { size: [1, 1, 1] });
  const occ = occluder({ ...rec, type: "teapot", shape: {} });
  assert.equal(occ.kind, "mesh");
  assert.ok(Number.isFinite(first_hit(occ, [0, -5, 0.5], [[0.3, 5, 0.1]])[0]!));
  const bare = occluder({ id: "x", type: "teapot" });
  assert.equal(bare.kind, "mesh");
  assert.equal(first_hit(bare, [0, 0, 0], [[1, 1, 1], [1, 1, 1]])[0], Infinity);
});

test("curved occluders: first_hit in closed form", () => {
  const A = shadow_geometry(load_scene({
    version: "0.1", units: "m", up: "z",
    objects: [
      { id: "s", type: "sphere", radius: 1.0, transform: { position: [0, 0, 0] } },
      { id: "c", type: "cylinder", radius: 0.5, height: 2.0, transform: { position: [5, 0, 0] } },
      { id: "k", type: "cone", radius: 1.0, height: 2.0, transform: { position: [-5, 0, 0] } },
    ],
    lights: [{ id: "l", type: "point", position: [0, 0, 9] }],
    receivers: [{ id: "g", type: "plane", normal: [0, 0, 1], offset: 0 }],
    camera: { position: [0, -9, 3], target: [0, 0, 0.5], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [360, 240] },
  }));
  const [sphere, cyl, cone] = A.objects.map((o) => occluder(o)) as [Occluder, Occluder, Occluder];
  const near = (a: number, b: number): boolean => Math.abs(a - b) <= 1e-9;
  assert.ok(near(first_hit(sphere, [0, -5, 1.0], [[0, 1, 0]])[0]!, 4.0));        // centre (0, 0, 1)
  assert.ok(near(first_hit(cyl, [5, -5, 1.0], [[0, 1, 0]])[0]!, 4.5));
  assert.ok(near(first_hit(cyl, [5, 0, 5.0], [[0, 0, -1]])[0]!, 3.0));          // top disc
  assert.ok(near(first_hit(cone, [-5, -5, 1.0], [[0, 1, 0]])[0]!, 4.5));
  assert.ok(near(first_hit(cone, [-5, 0, -3.0], [[0, 0, 1]])[0]!, 3.0));        // base
  assert.equal(first_hit(cone, [-5, -5, 2.5], [[0, 1, 0]])[0], Infinity);       // above the apex
  assert.ok(near(first_hit(sphere, [0, 0, 1.0], [[1, 0, 0]])[0]!, 1.0));        // inside: the exit crossing
});

test("the occlusion predicate: own front face, back edge, concave notch, camera inside (§5.1.6.3)", () => {
  const rec = box_scene_record("box", { size: [1, 1, 1] });
  const occ = occluder(rec);
  const [R, pos] = rec.frame as [Mat3, Vec3];
  const V = rec.mesh.vertices as Vec3[];
  const C = add(pos, rot(R, [0.0, -6.0, 3.0]));
  const front = lerp_mid(V[0]!, V[1]!), back = lerp_mid(V[2]!, V[3]!);
  assert.equal(occluded([occ], C, [front])[0], false);
  assert.equal(occluded([occ], C, [back])[0], true);
  const centre = add(pos, rot(R, [0.0, 0.0, 0.5]));
  const beyond = [front, back, V[5]!].map((P) => [0, 1, 2].map((k) => centre[k]! + 2.0 * (P[k]! - centre[k]!)));
  assert.ok(occluded([occ], centre, beyond).every((x) => x));
  assert.ok(occluded([occ], centre, [front, back, V[5]!]).every((x) => !x));
  const u = box_scene_record("prism", { polygon: U_POLY, height: 0.8 });
  const occ_u = occluder(u);
  const [Ru, pu] = u.frame as [Mat3, Vec3];
  const notch = add(pu, rot(Ru, [0.0, 0.2, 0.0]));
  assert.equal(occluded([occ_u], add(pu, rot(Ru, [0.0, 0.25, 6.0])), [notch])[0], false);   // straight above the notch
  assert.equal(occluded([occ_u], add(pu, rot(Ru, [4.0, 0.2, 0.3])), [notch])[0], true);     // through the right arm
});

test("plate and ground occluders; no ground receiver -> no ground occluder", () => {
  const A = shadow_geometry(load_scene(wall_and_ground_scene()));
  const occs = scene_occluders(A);
  assert.deepEqual(occs.map((o) => o.kind), ["box", "ground", "plate"]);
  const plate = occs[2]!, ground = occs[1]!;
  const C = [0.0, -1.0, 1.6];
  assert.equal(occluded([plate], C, [[0.0, 7.0, 0.5]])[0], true);    // behind the wall
  assert.equal(occluded([plate], C, [[0.0, 7.0, 4.0]])[0], false);   // seen above the wall
  assert.equal(occluded([plate], C, [[0.0, 6.0, 1.0]])[0], false);   // on the wall itself
  assert.equal(occluded([ground], C, [[0.0, 3.0, -0.2]])[0], true);  // below the ground
  assert.equal(occluded([ground], C, [[0.0, 3.0, 0.0]])[0], false);  // on the ground
  const no_ground = scene_occluders({ ...A, receivers: [{ ...A.receivers[1], index: 0 }] });
  assert.deepEqual(no_ground.map((o) => o.kind), ["box", "plate"]);
});

// --------------------------------------------------------------------------- drawn 4-D geometry
test("drawn_segment_4d reproduces the drawn endpoints (near-clipped edges included)", () => {
  const scene = load_scene(load_case("degenerate_point_behind_camera"));
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const doc = compose(scene, B) as any;
  let checked = 0, clipped = 0;
  for (const e of doc.edges) {
    const X = [e.from, e.to].map((n: string) => [...doc.points[n].world, 1.0]);
    const res = drawn_segment_4d(B.camera, X[0]!, X[1]!);
    assert.equal(res === null, e.segment === null);
    if (res === null) continue;
    res.forEach((Y, k) => {
      const x = project(B.camera, Y);
      assert.ok(Math.abs(x[0] / x[2] - e.segment[k][0]) <= 1e-9 && Math.abs(x[1] / x[2] - e.segment[k][1]) <= 1e-9);
    });
    checked++;
    const same = res.every((Y, k) => [0, 1, 2].every((i) => Math.abs(Y[i]! / Y[3] - X[k]![i]!) <= 1e-9));
    if (!same) clipped++;
  }
  assert.ok(checked >= 5 && clipped >= 1, `${checked} / ${clipped}`);
});

test("clip_polygon_4d: the vertex count equals the drawn polygon's on every case and the canvas-corner scene", () => {
  const names = json_stems(CASES).filter((n) => !n.startsWith("mesh_"));
  const scenes: [string, any][] = [...names.map((n) => [n, load_case(n)] as [string, any]), ["canvas_corner", canvas_corner_scene()]];
  for (const [name, sc] of scenes) {
    const scene = load_scene(sc);
    const A = shadow_geometry(scene);
    const B = project_scene(scene, A);
    const doc = compose(scene, B) as any;
    doc.shadows.forEach((sh: any, i: number) => {
      const a_sh = A.shadows[i]!;
      sh.polygons.forEach((poly: number[][], j: number) => {
        if (j >= a_sh.loops.length) return;
        const [pts, ids] = clip_polygon_4d(B.camera, a_sh.loops[j]!.vertices);
        assert.equal(pts.length, poly.length, `${name} ${sh.object} ${sh.receiver} ${j}`);
        pts.forEach((P, k) => {
          const x = project(B.camera, P);
          assert.ok(Math.abs(x[0] / x[2] - poly[k]![0]!) <= 1e-6 && Math.abs(x[1] / x[2] - poly[k]![1]!) <= 1e-6, name);
        });
        assert.ok(ids.every((id) => id === null || (id >= 0 && id < a_sh.loops[j]!.vertices.length)));
      });
    });
  }
  // the w = 0 case: two direction vertices (the drawn horizon segment) and one clip edge
  const scene = load_scene(load_case("degenerate_vertex_above_point_light"));
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const [pts, ids] = clip_polygon_4d(B.camera, A.shadows[0]!.loops[0]!.vertices);
  assert.equal(pts.filter((P) => P[3] === 0.0).length, 2);
  assert.equal(ids.filter((id) => id === null).length, 1);
});

test("canvas-corner scene: every outline edge of the crate's ground shadow is hidden, the clip edges visible", () => {
  const scene = load_scene(canvas_corner_scene());
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const doc = compose(scene, B, true) as any;
  const k = doc.shadows.findIndex((s: any) => s.object === "crate" && s.receiver === "ground");
  const [pts, ids] = clip_polygon_4d(B.camera, A.shadows[k]!.loops[0]!.vertices);
  const sh = doc.shadows[k];
  assert.equal(pts.length, sh.polygons[0].length);
  ids.forEach((id, e) => {
    assert.deepEqual(sh.polygon_edges[0][e], { visibility: id === null ? "visible" : "hidden", runs: [] });
  });
  assert.ok(ids.filter((id) => id !== null).length === 3);
});

// --------------------------------------------------------------------------- wall_and_ground_hidden (§5.1.11)
function edge(doc: any, a: string, b: string): any {
  const found = doc.edges.filter((e: any) => (e.from === a && e.to === b) || (e.from === b && e.to === a));
  assert.equal(found.length, 1, `${a} ${b}`);
  return found[0];
}

test("wall_and_ground_hidden: the hand values of contract §5.1.11 through the port", () => {
  const doc = render_hidden(wall_and_ground_scene()).geometry;
  assert.equal(doc.hidden_lines, true);
  const base = edge(doc, "wall.b0", "wall.b1");
  assert.equal(base.visibility, "partial");
  const runs = base.runs;
  assert.deepEqual(runs.map((r: any) => r.visible), [true, false, true]);
  const [[ua, va], [ub, vb]] = base.segment;
  const ell = Math.hypot(ub - ua, vb - va);
  assert.ok(Math.abs(ell - 223.1516) <= 1e-4, `${ell}`);
  const bounds = [[0.0, 23 / 60], [23 / 60, 37 / 60], [37 / 60, 1.0]];
  runs.forEach((r: any, i: number) => {
    assert.ok(Math.abs(r.s[0] - bounds[i]![0]!) <= 1e-3 && Math.abs(r.s[1] - bounds[i]![1]!) <= 1e-3, `run ${i}`);
    assert.ok(Math.abs(r.t[0] - r.s[0]) <= 1e-12 && Math.abs(r.t[1] - r.s[1]) <= 1e-12);   // picture-plane parallel: s = t
  });
  assert.equal(runs[0].mm[0], 0.0);
  assert.ok(Math.abs(runs[2].mm[1] - 223.1516) <= 1e-4);
  assert.ok(Math.abs(runs[0].mm[1] - 85.5415) <= 0.05, `${runs[0].mm[1]}`);
  assert.ok(Math.abs(runs[1].mm[1] - 137.6102) <= 0.05, `${runs[1].mm[1]}`);
  for (let i = 0; i + 1 < runs.length; i++) {
    assert.equal(runs[i].s[1], runs[i + 1].s[0]);
    assert.equal(runs[i].mm[1], runs[i + 1].mm[0]);
  }
  // the ground shadow edge (0.75, 5, 0) -> (0.75, 6.5, 0): hidden by the plate beyond y = 6, boundary s = 0.713073
  const sh = doc.shadows.find((s: any) => s.receiver === "ground" && s.object === "crate");
  const poly = sh.polygons[0], recs = sh.polygon_edges[0];
  assert.equal(recs.length, poly.length);
  const n = poly.length;
  const k = poly.findIndex((p: number[], i: number) => Math.abs(p[0]! - 32.405452361298636) < 1e-6
    && Math.abs(poly[(i + 1) % n][0] - 26.078616180680637) < 1e-6);
  assert.ok(k >= 0);
  const rec = recs[k];
  assert.equal(rec.visibility, "partial");
  assert.deepEqual(rec.runs.map((r: any) => r.visible), [true, false]);
  const s_b = rec.runs[0].s[1], t_b = rec.runs[0].t[1];
  assert.ok(Math.abs(s_b - 0.713073) <= 1e-3, `${s_b}`);
  assert.ok(Math.abs(t_b - 2 / 3) <= 1e-3, `${t_b}`);
  const a = poly[k], b = poly[(k + 1) % n];
  assert.ok(Math.abs(a[0] + s_b * (b[0] - a[0]) - 27.8939534) <= 0.05 && Math.abs(a[1] + s_b * (b[1] - a[1]) + 29.5611244) <= 0.05);
  // the crate: five hidden back edges, seven visible front edges; the wall top edge is visible
  const hidden_edges = new Set(["crate.v0 crate.v3", "crate.v1 crate.v2", "crate.v2 crate.v3", "crate.v2 crate.v6", "crate.v3 crate.v7"]);
  let nh = 0, nv = 0;
  for (const e of doc.edges) {
    if (e.object !== "crate") continue;
    assert.equal(e.visibility, hidden_edges.has(`${e.from} ${e.to}`) ? "hidden" : "visible", `${e.from} ${e.to}`);
    assert.deepEqual(e.runs, []);
    if (e.visibility === "hidden") nh++;
    else nv++;
  }
  assert.deepEqual([nh, nv], [5, 7]);
  assert.equal(edge(doc, "wall.b2", "wall.b3").visibility, "visible");
});

test("switch-off documents carry the switch-off values", () => {
  const doc = render(load_scene(wall_and_ground_scene())).geometry as any;
  assert.equal(doc.hidden_lines, false);
  assert.ok(doc.edges.every((e: any) => e.visibility === "visible" && e.runs.length === 0));
  assert.ok(doc.shadows.every((s: any) => s.polygon_edges.length === 0));
});

// --------------------------------------------------------------------------- determinism, culling, purity
for (const name of Object.keys(SCENES).sort()) {
  test(`render twice with hidden lines is byte-identical: ${name}`, () => {
    const r1 = render_hidden(SCENES[name]!()), r2 = render_hidden(SCENES[name]!());
    assert.equal(dumps(r1.geometry), dumps(r2.geometry));
    assert.equal(r1.svg, r2.svg);
  });
}

for (const name of ["wall_and_ground_hidden", "fold_curved_cylinder", "hidden_lines_curved_unbounded", "example_construction_demo",
  "random_seed0_3objects", "canvas_corner"]) {
  test(`culled equals unculled: ${name}`, () => {
    const make = SCENES[name] ?? (() => load_case(name));
    const scene = load_scene(make());
    const A = shadow_geometry(scene);
    const B = project_scene(scene, A);
    const culled = classify_document(compose(scene, B, false), A, B, true) as any;
    const plain = classify_document(compose(scene, B, false), A, B, false) as any;
    assert.equal(dumps(culled), dumps(plain));
    assert.ok(culled.edges.some((e: any) => e.visibility !== "visible")
      || culled.shadows.some((s: any) => s.polygon_edges.some((pe: any[]) => pe.some((r) => r.visibility !== "visible"))));
  });
}

test("image_bounds: cull data, the ground never culled, a hull point behind the camera -> no cull", () => {
  const scene = load_scene(wall_and_ground_scene());
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const b = scene_occluders(A).map((o) => image_bounds(o, B.camera));
  assert.equal(b[1], null);
  const [u0, u1, v0, v1, dmin] = b[0]!;
  assert.ok(u0 < u1 && v0 < v1 && dmin > 0);
  const near = load_scene(load_case("degenerate_point_behind_camera"));
  const A2 = shadow_geometry(near);
  const B2 = project_scene(near, A2);
  assert.equal(image_bounds(scene_occluders(A2)[0]!, B2.camera), null);
});

/** JSON text of a stage record (Maps as entry lists, the `A` back reference of B left out). */
function stage_text(x: unknown): string {
  return JSON.stringify(x, (k, v) => (k === "A" ? undefined : v instanceof Map ? [...v.entries()] : v));
}

test("the classification never mutates stage A or B; a switch-off document of the same B is unaffected", () => {
  const scene = load_scene(fold_curved_cylinder_scene());
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const before_a = stage_text(A), before_b = stage_text(B);
  const doc = compose(scene, B, true) as any;
  assert.equal(stage_text(A), before_a);
  assert.equal(stage_text(B), before_b);
  const off = compose(scene, B, false) as any;
  assert.ok(off.edges.every((e: any) => e.visibility === "visible" && e.runs.length === 0));
  assert.ok(doc.edges.some((e: any) => e.visibility !== "visible"));
});

// --------------------------------------------------------------------------- run-record invariants (§5.1.7)
function check_straight(item: any, where: string): void {
  const vis = item.visibility, runs = item.runs;
  assert.ok(["visible", "hidden", "partial"].includes(vis), where);
  assert.equal(runs.length > 0, vis === "partial", where);
  if (runs.length === 0) return;
  assert.ok(runs[0].s[0] === 0.0 && runs[runs.length - 1].s[1] === 1.0, where);
  assert.ok(runs[0].t[0] === 0.0 && runs[runs.length - 1].t[1] === 1.0, where);
  for (let i = 0; i + 1 < runs.length; i++) {
    assert.ok(runs[i].s[1] === runs[i + 1].s[0] && runs[i].visible !== runs[i + 1].visible, where);
    assert.equal(runs[i].mm[1], runs[i + 1].mm[0], where);
  }
  for (const r of runs) {
    assert.ok(r.s[0] < r.s[1] && r.mm[0] <= r.mm[1], where);
    assert.deepEqual(Object.keys(r).sort(), ["mm", "s", "t", "visible"], where);
  }
}

function check_conic(c: any, where: string): void {
  const vis = c.visibility, runs = c.runs;
  assert.equal(runs.length > 0, vis === "partial", where);
  if (vis === "visible") assert.deepEqual(c.hidden_polylines, [], where);
  else assert.ok(c.ellipses.length === 0 && c.hidden_polylines.length > 0, where);
  if (runs.length === 0) return;
  const by = new Map<number, any[]>();
  for (const r of runs) {
    assert.ok(Number.isInteger(r.interval), where);
    assert.deepEqual(Object.keys(r).sort(), ["interval", "mm", "theta", "visible"], where);
    if (!by.has(r.interval)) by.set(r.interval, []);
    by.get(r.interval)!.push(r);
  }
  assert.deepEqual([...by.keys()].sort((a, b) => a - b), c.visible.map((_v: unknown, i: number) => i), where);
  for (const [k, rr] of by) {
    const [lo, hi] = c.visible[k];
    assert.ok(rr[0].mm[0] === 0.0 && rr[0].theta[0] === lo && rr[rr.length - 1].theta[1] === hi, where);
    for (let i = 0; i + 1 < rr.length; i++) assert.ok(rr[i].mm[1] === rr[i + 1].mm[0] && rr[i].visible !== rr[i + 1].visible, where);
  }
}

function check_document(doc: any, label: string): void {
  for (const e of doc.edges) check_straight(e, `${label} ${e.from} ${e.to}`);
  for (const o of doc.outlines) {
    for (const g of o.generators) check_straight(g, `${label} ${g.from}`);
    for (const c of o.conics) check_conic(c, `${label} ${o.object} ${c.which}`);
  }
  for (const f of doc.form_shadow) {
    for (const t of f.terminator) {
      if ("segment" in t) check_straight(t, `${label} ${t.segment}`);
      else check_conic(t, `${label} ${f.object}`);
    }
  }
  for (const s of doc.shadows) {
    assert.equal(s.polygon_edges.length, s.polygons.length, label);
    s.polygons.forEach((poly: unknown[], j: number) => {
      const recs = s.polygon_edges[j];
      assert.equal(recs.length, poly.length >= 3 ? poly.length : 0, label);
      for (const r of recs) check_straight(r, `${label} ${s.object}`);
    });
    for (const c of s.conics) check_conic(c, `${label} ${s.object} ${c.which}`);
  }
}

test("run records on every conformance case with the switch on (mesh cases: mesh part)", () => {
  for (const name of json_stems(CASES).filter((n) => !n.startsWith("mesh_"))) {
    const r = render_hidden(load_case(name));
    check_document(r.geometry, name);
    const text = dumps(r.geometry);
    assert.ok(!text.includes("NaN") && !text.includes("Infinity"), name);
  }
});

test("the named M4 hidden scenes: unbounded conic shadows partly hidden; the w = 0 endpoint edge classified", () => {
  const cu = render_hidden(curved_unbounded_scene()).geometry;
  check_document(cu, "curved_unbounded");
  assert.ok(cu.shadows.every((s: any) => s.unbounded));
  assert.ok(cu.shadows.some((s: any) => s.conics.some((c: any) => c.visibility === "partial")));
  const scene = load_scene(vp_in_canvas_scene());
  const doc = render(scene, null, true).geometry as any;
  check_document(doc, "vp_in_canvas");
  const recs = doc.shadows[0].polygon_edges[0];
  assert.ok(recs.some((r: any) => r.visibility !== "visible"));
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const [p4, ids] = clip_polygon_4d(B.camera, A.shadows[0]!.loops[0]!.vertices);
  const n = p4.length;
  assert.equal(n, recs.length);
  const w0 = p4.map((_P, k) => [p4[k]![3] === 0.0, p4[(k + 1) % n]![3] === 0.0]);
  const one = [...Array(n).keys()].filter((k) => ids[k] !== null && w0[k]![0] !== w0[k]![1]);
  const both = [...Array(n).keys()].filter((k) => ids[k] !== null && w0[k]![0] && w0[k]![1]);
  assert.equal(one.length, 1);
  assert.equal(both.length, 1);
  const r = recs[one[0]!];
  assert.ok(r.visibility === "partial" && r.runs[0].visible === false);
  assert.ok(r.runs[r.runs.length - 1].t[1] === 1.0 && r.runs[r.runs.length - 1].s[1] === 1.0);
  assert.deepEqual(recs[both[0]!], { visibility: "visible", runs: [] });
});

// --------------------------------------------------------------------------- SVG (contract §5.1.8, §5.0.6)
interface El { tag: string; attrs: Record<string, string>; children: El[]; line: string }

/** A minimal parser of the writer's output (one element or group tag per line). */
function parse_svg(svg: string): El {
  const root: El = { tag: "#root", attrs: {}, children: [], line: "" };
  const stack: El[] = [root];
  for (const line of svg.split("\n")) {
    if (line.startsWith("<?xml") || line === "") continue;
    if (line.startsWith("</")) {
      stack.pop();
      continue;
    }
    const m = /^<(\w+)((?:\s+[\w-]+="[^"]*")*)\s*(\/?)>/.exec(line);
    assert.ok(m !== null, line);
    const attrs: Record<string, string> = {};
    for (const a of (m[2] as string).matchAll(/([\w-]+)="([^"]*)"/g)) attrs[a[1] as string] = a[2] as string;
    const el: El = { tag: m[1] as string, attrs, children: [], line };
    stack[stack.length - 1]!.children.push(el);
    const self_closing = m[3] === "/" || /<\/\w+>$/.test(line);
    if (!self_closing) stack.push(el);
  }
  return root;
}

function all_groups(el: El, out: El[] = []): El[] {
  for (const c of el.children) {
    if (c.tag === "g") out.push(c);
    all_groups(c, out);
  }
  return out;
}

function group_by_id(root: El, gid: string): El {
  const found = all_groups(root).filter((g) => g.attrs["id"] === gid);
  assert.equal(found.length, 1, gid);
  return found[0]!;
}

function child_ids(g: El): string[] {
  return g.children.filter((c) => c.tag === "g").map((c) => c.attrs["id"] as string);
}

function drawn(g: El): El[] {
  const out: El[] = [];
  const walk = (e: El): void => {
    for (const c of e.children) {
      if (["line", "polyline", "path", "ellipse", "polygon"].includes(c.tag)) out.push(c);
      walk(c);
    }
  };
  walk(g);
  return out;
}

function subtree_text(g: El): string {
  return g.line + g.children.map(subtree_text).join("");
}

/** `cast_shadow.<light>.<object>[.<r>].<suffix>` (the M4 implementation note on sub-group ids). */
function shadow_subgroup_id(sh: any, first: string, suffix: string): string {
  const infix = sh.receiver === first ? "" : `.${sh.receiver}`;
  return `cast_shadow.${sh.light}.${sh.object}${infix}.${suffix}`;
}

for (const name of Object.keys(SCENES).sort()) {
  test(`hidden groups come first in their layers with the stated style: ${name}`, () => {
    const r = render_hidden(SCENES[name]!());
    const root = parse_svg(r.svg);
    const ids = all_groups(root).map((g) => g.attrs["id"]);
    assert.equal(ids.length, new Set(ids).size);                  // every id unique
    for (const [layer, colour] of [["objects", "#111"], ["form_shadow", "#335"], ["cast_shadow", "#000"]] as const) {
      assert.equal(child_ids(group_by_id(root, layer))[0], `${layer}.hidden`);
      const hg = group_by_id(root, `${layer}.hidden`);
      assert.deepEqual([hg.attrs["stroke"], hg.attrs["stroke-width"], hg.attrs["stroke-dasharray"], hg.attrs["fill"]],
        [colour, "0.15", "0.5 0.5", "none"]);
      for (const sub of child_ids(hg)) assert.ok(sub.startsWith(`${layer}.hidden.`));
    }
    const doc = r.geometry;
    const cs = group_by_id(root, "cast_shadow");
    const paths = cs.children.filter((g) => g.tag === "g" && g.attrs["id"] !== "cast_shadow.hidden")
      .flatMap((g) => g.children.filter((p) => p.tag === "path"));
    assert.ok(paths.length > 0 && paths.every((p) => p.attrs["stroke"] === "none"));
    const first = doc.receivers[0].id;
    for (const sh of doc.shadows) {
      if (!sh.polygons.some((p: unknown[]) => p.length >= 3)) continue;
      if (sh.polygon_edges.every((pe: any[]) => pe.every((x) => x.visibility === "hidden"))) continue;
      const g = group_by_id(root, shadow_subgroup_id(sh, first, "outline"));
      assert.deepEqual([g.attrs["stroke"], g.attrs["stroke-width"]], ["#000", "0.25"]);
    }
  });
}

test("the wall base edge is split at the run boundaries; the crate's hidden and visible edges", () => {
  const r = render_hidden(wall_and_ground_scene());
  const doc = r.geometry, root = parse_svg(r.svg);
  const base = edge(doc, "wall.b0", "wall.b1");
  const [[ua, va], [ub]] = base.segment;
  const [W, H] = doc.canvas_mm;
  const hidden_lines = group_by_id(root, "objects.hidden.wall").children;
  assert.equal(hidden_lines.length, 1);
  const [s0, s1] = base.runs[1].s;
  assert.ok(Math.abs(Number(hidden_lines[0]!.attrs["x1"]) - (ua + s0 * (ub - ua) + W / 2)) <= 1e-4);
  assert.ok(Math.abs(Number(hidden_lines[0]!.attrs["x2"]) - (ua + s1 * (ub - ua) + W / 2)) <= 1e-4);
  const front = group_by_id(root, "objects.wall.front").children.filter((l) => l.tag === "line");
  const y = Math.round((H / 2 - va) * 1000) / 1000;
  assert.ok(front.filter((l) => Math.round(Number(l.attrs["y1"]) * 1000) / 1000 === y).length >= 2);
  assert.equal(group_by_id(root, "objects.hidden.crate").children.length, 5);
  assert.equal(group_by_id(root, "objects.crate.front").children.length, 7);
  assert.ok(!all_groups(root).some((g) => g.attrs["id"] === "objects.crate.back"));
});

for (const name of Object.keys(SCENES).sort()) {
  test(`omit style keeps the ids and draws nothing hidden: ${name}`, () => {
    const scene = load_scene(SCENES[name]!());
    const dashed = render(scene, null, true), omit = render(scene, null, true, "omit");
    assert.equal(dumps(dashed.geometry), dumps(omit.geometry));
    const rd = parse_svg(dashed.svg), ro = parse_svg(omit.svg);
    assert.deepEqual(all_groups(rd).map((g) => g.attrs["id"]), all_groups(ro).map((g) => g.attrs["id"]));
    let drew_hidden = false;
    for (const layer of ["objects", "form_shadow", "cast_shadow"]) {
      assert.deepEqual(drawn(group_by_id(ro, `${layer}.hidden`)), []);
      drew_hidden = drew_hidden || drawn(group_by_id(rd, `${layer}.hidden`)).length > 0;
    }
    assert.ok(drew_hidden);
    for (const layer of ["objects", "form_shadow", "cast_shadow"]) {
      for (const gid of child_ids(group_by_id(rd, layer)).slice(1)) {
        assert.equal(subtree_text(group_by_id(rd, gid)), subtree_text(group_by_id(ro, gid)));
      }
    }
    const raw = SCENES[name]!();
    const scene_omit = load_scene({ ...raw, output: { ...(raw.output ?? {}), hidden_style: "omit" } });
    assert.equal(render(scene_omit, null, true).svg, omit.svg);
  });
}

test("the hidden groups exist only when the switch is on; layer subsets; an unknown hidden_style throws", () => {
  const scene = load_scene(wall_and_ground_scene());
  const off = render(scene).svg;
  assert.ok(!off.includes(".hidden") && !off.includes(".outline") && off.includes('<path d="M') && !off.includes('Z" stroke="none"/>'));
  const on = render(scene, null, true).svg;
  assert.ok(on.includes('id="objects.hidden"') && on.includes('id="cast_shadow.lamp.crate.wall.outline"'));
  const doc = render(scene, null, true).geometry;
  const root = parse_svg(write_svg(doc, ["cast_shadow", "objects"]));
  assert.deepEqual(root.children[0]!.children.filter((g) => g.tag === "g").map((g) => g.attrs["id"]), ["objects", "cast_shadow"]);
  assert.throws(() => write_svg(doc, null, "dotted"));
});

test("partly hidden conics become arcs and hidden polylines", () => {
  const r = render_hidden(curved_unbounded_scene());
  const doc = r.geometry, root = parse_svg(r.svg);
  const post = doc.outlines.find((o: any) => o.object === "post");
  assert.ok(post.conics.some((c: any) => c.visibility === "hidden" && c.hidden_polylines.length > 0 && c.arcs.length === 0));
  const sh = doc.shadows.find((s: any) => s.object === "post");
  const c = sh.conics[0];
  assert.ok(c.visibility === "partial" && c.ellipses.length === 0);
  const vis_runs = c.runs.filter((x: any) => x.visible);
  assert.equal(c.arcs.length + c.polylines.length, vis_runs.length);
  assert.equal(c.hidden_polylines.length, c.runs.filter((x: any) => !x.visible).length);
  for (const arc of c.arcs) assert.ok(vis_runs.some((x: any) => arc.theta[0] === x.theta[0] && arc.theta[1] === x.theta[1]));
  assert.ok(group_by_id(root, "cast_shadow.hidden.lamp").children.some((e) => e.tag === "polyline"));
});

test("examples/wall_and_ground.json (hidden lines on in the scene) renders with the hidden groups", () => {
  const out = render(load_scene(read_json(repo_path("examples", "wall_and_ground.json"))));
  assert.equal((out.geometry as any).hidden_lines, true);
  assert.ok(out.svg.includes('id="objects.hidden"'));
  assert.equal(render(load_scene(clone(read_json(repo_path("examples", "wall_and_ground.json"))))).svg, out.svg);
});

/**
 * Bounded receivers and folds in the port (contract §5.1.2 – §5.1.5, §5.1.11; phase 2 of §5.4.14). Ported from
 * `tests/test_receivers.py`: the `shadow.ts` unit tests (receiver frame, bounds functionals, the bounds clip with the
 * band and anchor rules, the plate loop) and the hand-computed acceptance case `wall_and_ground` of §5.1.11 run
 * through the port alone, against the hand values (independently of the expected file).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { render, shadow_geometry } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { bounds_functionals, clip_polygon_bounds, plate_loop, receiver_frame } from "../src/shadow.js";
import type { Vec3, Vec4 } from "../src/types.js";

// --------------------------------------------------------------------------- shadow.ts unit tests (§5.1.2, §5.1.3.3)
/** The wall plate of `wall_and_ground`: the plane y = 6 with normal (0, −1, 0); its frame is (x, z). */
const WALL_N: Vec3 = [0.0, -1.0, 0.0];
const WALL_PI: Vec4 = [0.0, -1.0, 0.0, 6.0];
const WALL_BOUNDS: Vec3[] = [[-3.0, 6.0, 0.0], [3.0, 6.0, 0.0], [3.0, 6.0, 2.5], [-3.0, 6.0, 2.5]];

function wall_point(u: number, v: number, w = 1.0): Vec4 {
  return [u * w, 6.0 * w, v * w, w];
}

function wall_dir(du: number, dv: number): Vec4 {
  const n = Math.hypot(du, dv);
  return [du / n, 0.0, dv / n, 0.0];
}

function dot3(a: readonly number[], b: readonly number[]): number {
  return (a[0] as number) * (b[0] as number) + (a[1] as number) * (b[1] as number) + (a[2] as number) * (b[2] as number);
}

function frame_area(V: readonly Vec4[]): number {
  const [e1, e2] = receiver_frame(WALL_N);
  const uv = V.map((X) => {
    const p = [X[0] / X[3], X[1] / X[3], X[2] / X[3]];
    return [dot3(p, e1), dot3(p, e2)] as [number, number];
  });
  let s = 0;
  for (let i = 0; i < uv.length; i++) {
    const a = uv[i] as [number, number], b = uv[(i + 1) % uv.length] as [number, number];
    s += a[0] * b[1] - b[0] * a[1];
  }
  return 0.5 * s;
}

function clip_wall(poly: Vec4[]) {
  const psi = bounds_functionals(WALL_BOUNDS, WALL_N);
  return clip_polygon_bounds(poly, poly.map((_p, i) => i), psi, WALL_BOUNDS, 1e-9);
}

function close(a: readonly number[], b: readonly number[], tol: number, msg = ""): void {
  assert.equal(a.length, b.length, msg);
  a.forEach((x, i) => assert.ok(Math.abs(x - (b[i] as number)) <= tol, `${msg} [${i}]: ${x} vs ${b[i]} (tol ${tol})`));
}

test("receiver_frame: e1 × e2 = n; the ground is (x, y), the wall (x, z)", () => {
  let [e1, e2] = receiver_frame([0.0, 0.0, 1.0]);
  assert.deepEqual(e1, [1.0, 0.0, 0.0]);
  assert.deepEqual(e2, [0.0, 1.0, 0.0]);
  [e1, e2] = receiver_frame(WALL_N);
  close(e1, [1, 0, 0], 1e-15);
  close(e2, [0, 0, 1], 1e-15);
  for (const n of [[0.0, 0.0, -1.0], [0.0, -0.6, 0.8], [0.48, 0.6, 0.64], [1.0, 0.0, 0.0]] as Vec3[]) {
    [e1, e2] = receiver_frame(n);
    close([e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]], n, 1e-15);
    assert.ok(Math.abs(dot3(e1, e2)) <= 1e-15 && Math.abs(Math.hypot(...e1) - 1) <= 1e-15);
  }
});

test("bounds_functionals are unit inward normals (signed distance times w; m_k · d for a direction)", () => {
  const psi = bounds_functionals(WALL_BOUNDS, WALL_N);
  [[0, 0, 1, 0], [-1, 0, 0, 3], [0, 0, -1, 2.5], [1, 0, 0, 3]].forEach((row, k) => close(psi[k] as Vec4, row, 1e-15));
  const X = wall_point(1.0, 1.0, 7.0);
  close(psi.map((r) => r[0] * X[0] + r[1] * X[1] + r[2] * X[2] + r[3] * X[3]), [7, 14, 10.5, 28], 1e-12);
});

test("the half-plane polygon returns the full plate (anchor rule, §5.1.3.3)", () => {
  const poly = [wall_point(-1, -1), wall_point(1, -1, 2.0), wall_dir(1, 0), wall_dir(0, 1), wall_dir(-1, 0)];
  const [V, src] = clip_wall(poly);
  assert.equal(V.length, 4);
  assert.ok(V.every((v) => v[3] > 0));
  assert.ok(Math.abs(frame_area(V) - 15.0) <= 1e-12);
  const X = V.map((v) => [v[0] / v[3], v[1] / v[3], v[2] / v[3]].map((c) => Math.round(c * 1e12) / 1e12 + 0).join(",")).sort();
  assert.deepEqual(X, WALL_BOUNDS.map((b) => b.join(",")).sort());
  assert.ok(src.some((s) => typeof s === "object" && s.kind === "bounds" && s.k === 0 && s.anchor === true));
});

test("a 270-degree arc at infinity returns the full plate", () => {
  const poly: Vec4[] = [wall_point(-4, -1)];
  const th0 = -0.5 * Math.PI, delta = 1.5 * Math.PI;
  const steps = Math.ceil(delta / (60 * (Math.PI / 180)) - 1e-12);
  for (let s = 0; s <= steps; s++) {
    const th = th0 + delta * s / steps;
    poly.push(wall_dir(Math.cos(th), Math.sin(th)));
  }
  const [V] = clip_wall(poly);
  assert.equal(V.length, 4);
  assert.ok(Math.abs(frame_area(V) - 15.0) <= 1e-12);
});

test("a bounded square, a < 180° wedge, a polygon outside and a nearly parallel direction", () => {
  let [V, src] = clip_wall([wall_point(-1, 0.5), wall_point(1, 0.5, 3.0), wall_point(1, 1.5), wall_point(-1, 1.5)]);
  assert.equal(V.length, 4);
  assert.deepEqual(src, [0, 1, 2, 3]);
  assert.ok(Math.abs(frame_area(V) - 2.0) <= 1e-12);
  [V] = clip_wall([wall_point(0, 1), wall_dir(1, 1), wall_dir(0, 1), wall_dir(-1, 1)]);
  assert.equal(V.length, 3);
  assert.ok(Math.abs(frame_area(V) - 2.25) <= 1e-12);
  [V, src] = clip_wall([wall_point(5, 0.5), wall_point(6, 0.5), wall_point(6, 1.5), wall_point(5, 1.5)]);
  assert.deepEqual(V, []);
  assert.deepEqual(src, []);
  [V] = clip_wall([wall_point(-1, 0.5), wall_dir(1, -1e-12), wall_dir(0, 1), wall_dir(-1, -1e-12)]);
  assert.ok(V.every((v) => v[3] > 0));
  assert.equal(V.length, 5);
  assert.ok(Math.abs(frame_area(V) - 12.0) <= 1e-9);
});

test("the band rule keeps a vertex on a plate edge without a duplicate crossing", () => {
  const [V, src] = clip_wall([wall_point(-1, 0), wall_point(1, -1), wall_point(1, 1)]);
  assert.equal(src[0], 0);
  assert.equal(src[2], 2);
  assert.equal(src.filter((s) => typeof s === "object").length, 1);
  assert.equal(V.length, 3);
});

test("plate_loop orientation and edge-on plate", () => {
  let loop = plate_loop(WALL_BOUNDS, WALL_PI, [0.0, 2.0, 3.0, 1.0], 1e-9);
  assert.ok(loop !== null);
  assert.deepEqual(loop[1], [0, 1, 2, 3]);
  assert.deepEqual(loop[0].map((v) => [v[0], v[1], v[2]]), WALL_BOUNDS);
  loop = plate_loop(WALL_BOUNDS, WALL_PI, [0.0, 9.0, 3.0, 1.0], 1e-9);
  assert.deepEqual(loop?.[1], [3, 2, 1, 0]);
  assert.equal(plate_loop(WALL_BOUNDS, WALL_PI, [0.0, 6.0, 3.0, 1.0], 1e-9), null);
});

// --------------------------------------------------------------------------- wall_and_ground (§5.1.11 hand values)
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

function world(doc: any, name: string): number[] {
  const p = doc.points[name];
  assert.ok(p !== undefined, `no point ${name}`);
  return p.world;
}

function shadow_of(doc: any, receiver: string, obj: string): any {
  const found = doc.shadows.filter((s: any) => s.receiver === receiver && s.object === obj);
  assert.equal(found.length, 1, `${receiver} ${obj}`);
  return found[0];
}

test("wall_and_ground: the hand values of contract §5.1.11 through the port", () => {
  const { geometry: doc } = render(load_scene(wall_and_ground_scene())) as { geometry: any };
  assert.deepEqual(doc.warnings, []);
  assert.equal(doc.hidden_lines, false);
  assert.deepEqual(doc.receivers, [
    { id: "ground", plane: [0.0, 0.0, 1.0, 0.0], bounds: null, lit: { lamp: true }, casts: { lamp: false } },
    {
      id: "wall", plane: [0.0, -1.0, 0.0, 6.0], bounds: [[-3.0, 6.0, 0.0], [3.0, 6.0, 0.0], [3.0, 6.0, 2.5], [-3.0, 6.0, 2.5]],
      lit: { lamp: true }, casts: { lamp: true },
    },
  ]);
  // F.lamp, F.lamp.wall (exact)
  assert.deepEqual(world(doc, "F.lamp"), [0.0, 2.0, 0.0]);
  assert.deepEqual(world(doc, "F.lamp.wall"), [0.0, 6.0, 3.0]);
  // the crate: lit faces front (−y) and top; silhouette loop v0 v1 v5 v6 v7 v4
  const A = shadow_geometry(load_scene(wall_and_ground_scene()));
  const crate = A.objects[0];
  assert.ok(crate !== undefined);
  const ol = crate.lights.get("lamp");
  assert.ok(ol !== undefined);
  const lit_normals = crate.mesh.face_normals.filter((_n, k) => ol.lit[k]).map((n) => n.map((c) => Math.round(c * 1e12) / 1e12 + 0).join(","));
  assert.deepEqual(lit_normals.sort(), ["0,-1,0", "0,0,1"]);
  const ground = shadow_of(doc, "ground", "crate");
  assert.deepEqual(ground.outline, [0, 1, 5, 6, 7, 4].map((k) => `crate.v${k}.shadow.lamp`));
  const expected_ground: Record<number, number[]> = { 5: [0.75, 5, 0], 6: [0.75, 6.5, 0], 7: [-0.75, 6.5, 0], 4: [-0.75, 5, 0], 0: [-0.5, 4, 0], 1: [0.5, 4, 0] };
  for (const [k, p] of Object.entries(expected_ground)) close(world(doc, `crate.v${k}.shadow.lamp`), p, 1e-12, `v${k}`);
  // wall shadow points (also outside the plate: genuine points of the plane)
  const expected_wall: Record<number, number[]> = { 6: [2 / 3, 6, 1 / 3], 7: [-2 / 3, 6, 1 / 3], 5: [1, 6, -1], 4: [-1, 6, -1], 0: [-1, 6, -3], 1: [1, 6, -3] };
  for (const [k, p] of Object.entries(expected_wall)) close(world(doc, `crate.v${k}.shadow.lamp.wall`), p, 1e-12, `v${k} wall`);
  // the wall polygon after the bounds clip: (0.75,6,0) s0, (2/3,6,1/3), (−2/3,6,1/3), (−0.75,6,0) s1
  const wall = shadow_of(doc, "wall", "crate");
  assert.deepEqual(wall.outline, ["crate.s0.lamp.wall", "crate.v6.shadow.lamp.wall", "crate.v7.shadow.lamp.wall", "crate.s1.lamp.wall"]);
  assert.equal(wall.unbounded, false);
  assert.equal(wall.polygons.length, 1);
  assert.equal(wall.polygons[0].length, 4);
  close(world(doc, "crate.s0.lamp.wall"), [0.75, 6, 0], 1e-12);
  close(world(doc, "crate.s1.lamp.wall"), [-0.75, 6, 0], 1e-12);
  // the wall's own ground shadow: (−3,6,0), (3,6,0) band-kept, (18,26,0), (−18,26,0); no OBJECT_BELOW_RECEIVER
  const plate = shadow_of(doc, "ground", "wall");
  assert.deepEqual(plate.outline, [0, 1, 2, 3].map((k) => `wall.b${k}.shadow.lamp`));
  [[-3, 6, 0], [3, 6, 0], [18, 26, 0], [-18, 26, 0]].forEach((p, k) => close(world(doc, `wall.b${k}.shadow.lamp`), p, 1e-12));
  // images (1e-6 mm)
  const images: Record<string, number[]> = {
    "wall.b0": [-111.5758137, -29.5611244], "wall.b1": [111.5758137, -29.5611244],
    "wall.b2": [116.1978441, 65.4196009], "wall.b3": [-116.1978441, 65.4196009],
    "crate.s0.lamp.wall": [27.8939534, -29.5611244], "crate.s1.lamp.wall": [-27.8939534, -29.5611244],
    "crate.v6.shadow.lamp.wall": [24.9268280, -17.3359326], "crate.v7.shadow.lamp.wall": [-24.9268280, -17.3359326],
    "L.lamp": [0.0, 162.8814554], "F.lamp.wall": [0.0, 85.3679337], "F.lamp": [0.0, -104.8324357],
  };
  for (const [name, uv] of Object.entries(images)) close(doc.points[name].image, uv, 1e-6, name);
  const con = doc.construction;
  close(con.light_point, images["L.lamp"] as number[], 1e-6);
  close(con.shadow_vp, images["F.lamp"] as number[], 1e-6);
  close(con.per_receiver.wall.shadow_vp, images["F.lamp.wall"] as number[], 1e-6);
});

test("wall_and_ground: the fold points agree both ways (§5.1.3.4)", () => {
  const doc = render(load_scene(wall_and_ground_scene())).geometry as any;
  const g = (k: number): number[] => world(doc, `crate.v${k}.shadow.lamp`);
  const crossing_y = (a: number[], b: number[], y: number): number[] => {
    const t = (y - (a[1] as number)) / ((b[1] as number) - (a[1] as number));
    return a.map((c, i) => c + t * ((b[i] as number) - c));
  };
  const fold_right = crossing_y(g(5), g(6), 6.0), fold_left = crossing_y(g(7), g(4), 6.0);
  const s0 = world(doc, "crate.s0.lamp.wall"), s1 = world(doc, "crate.s1.lamp.wall");
  close(s0, fold_right, 1e-9);
  close(s1, fold_left, 1e-9);
  close(s0, [0.75, 6.0, 0.0], 1e-9);
  close(s1, [-0.75, 6.0, 0.0], 1e-9);
});

test("wall_and_ground: rays only inside the plate, per_receiver construction, F′wall in the SVG", () => {
  const out = render(load_scene(wall_and_ground_scene()));
  const doc = out.geometry as any;
  const pr = doc.construction.per_receiver.wall;
  assert.deepEqual(pr.rays, [["L", "crate.v6"], ["F", "crate.v6.foot.wall"], ["L", "crate.v7"], ["F", "crate.v7.foot.wall"]]);
  assert.deepEqual(pr.checks.map((c: any) => c.point), ["crate.v6.shadow.lamp.wall", "crate.v7.shadow.lamp.wall"]);
  assert.ok(Math.max(...pr.checks.map((c: any) => c.max_error_mm)) <= 1e-6);
  assert.deepEqual(new Set(pr.segments.map((s: any) => s.kind)), new Set(["LP", "FQ", "PQ"]));
  assert.ok(doc.construction.rays.every((r: string[]) => !(r[1] as string).endsWith(".wall")));
  assert.ok(doc.construction.rays.some((r: string[]) => (r[1] as string).startsWith("wall.b")));
  assert.ok(out.svg.includes("F′wall") && !out.svg.includes('id="construction.wall'));
});

test("wall_and_ground: SVG groups and labels (§5.0.4, §5.1.8)", () => {
  const svg = render(load_scene(wall_and_ground_scene())).svg;
  assert.ok(svg.includes('<g id="objects.wall">') && svg.includes('<g id="objects.wall.front"'));
  assert.ok(svg.includes(">b0</text>") && svg.includes('font-weight="bold">wall</text>'));
  assert.ok(!svg.includes(">v6.shadow.lamp.wall<") && !svg.includes(">v0.foot.wall<") && !svg.includes(">s0.lamp.wall<"));
  assert.ok(svg.includes(">F.lamp.wall</text>") && !svg.includes('font-weight="bold">F</text>'));
});

test("fold_curved_cylinder: the curved shadow folds onto the wall (closed-form conic bounds clip, §5.1.4)", () => {
  const scene = wall_and_ground_scene();
  scene.objects = [{ id: "pillar", type: "cylinder", radius: 0.4, height: 1.5, transform: { position: [0, 5, 0] } }];
  const doc = render(load_scene(scene)).geometry as any;
  assert.deepEqual(doc.warnings, []);
  const wall = shadow_of(doc, "wall", "pillar");
  const ground = shadow_of(doc, "ground", "pillar");
  assert.ok(wall.polygons.length > 0 && ground.polygons.length > 0 && wall.unbounded === false);
  const names = wall.outline.filter((e: unknown) => typeof e === "string");
  assert.equal(names.length, wall.outline.length);
  for (const n of names) {
    assert.ok(n.endsWith(".lamp.wall"), n);
    const p = world(doc, n);
    assert.ok(Math.abs((p[1] as number) - 6.0) <= 1e-9 && (p[0] as number) >= -3 - 1e-9 && (p[0] as number) <= 3 + 1e-9
      && (p[2] as number) >= -1e-9 && (p[2] as number) <= 2.5 + 1e-9, n);
  }
  assert.ok(wall.conics.length > 0 && wall.conics.every((c: any) => c.map === "shadow"));
  const A = shadow_geometry(load_scene(scene));
  const curved = A.objects[0]?.curved;
  assert.ok(curved !== undefined);
  assert.deepEqual([...curved.keys()], ["ground", "wall"]);
  const on_base = names.filter((n: string) => Math.abs(world(doc, n)[2] as number) <= 1e-12);
  assert.equal(on_base.length, 2);
});

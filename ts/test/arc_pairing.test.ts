/**
 * Arcs at infinity of a shadow loop with several excursions to infinity, and their base level (the port of
 * `tests/test_arc_pairing.py` and `tests/test_arc_base_level.py`; contract §2.5 as amended by the §5.1 implementation
 * notes "arc pairing" and "Base level of the arcs at infinity", D70; review findings m4-geometry#0 and
 * determinism-perf#0).
 *
 * The ray-cast comparisons of the Python tests need the Python reference (`tests/reference/raycast.py`); here the
 * scene tests check the structure the fix pins (component counts, the empty wall record, the arc that sweeps more than
 * one turn), the plate test compares with the analytic plate shadow on a raster, and `light_plane_level` is checked
 * against an independent brute-force ray / polygon count. The documents themselves are pinned by the v7 conformance
 * cases `arc_pairing_*` / `arc_base_level_*` (`conformance.test.ts`).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Mesh } from "../src/mesh.js";
import { render, shadow_geometry } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { arc_angle, arc_components, arc_level, light_plane_level, shadow_loop, shadow_matrix, sweep_arc } from "../src/shadow.js";
import type { ShadowComponent, Source } from "../src/shadow.js";
import type { Mat4, Vec3, Vec4 } from "../src/types.js";

import { read_json, repo_path } from "./helpers.js";

const CASES = repo_path("tests", "conformance", "cases");
const GROUND: Vec4 = [0.0, 0.0, 1.0, 0.0];
const TWO_PI = 2.0 * Math.PI;
const rad = (deg: number): number => (deg * Math.PI) / 180.0;
const deg = (r: number): number => (r * 180.0) / Math.PI;

/** An arch-shaped plate outline in the vertical plane `y = 1` as `(x, z)` pairs (counter-clockwise from the light side). */
const U_XZ: [number, number][] = [[-1.0, 0.0], [-0.5, 0.0], [-0.5, 1.5], [0.5, 1.5], [0.5, 0.0], [1.0, 0.0], [1.0, 2.0], [-1.0, 2.0]];
/** In front of the opening, below the lintel: the light plane cuts both legs. */
const LIGHT: Vec3 = [0.0, -2.0, 1.0];

const scene_of = (stem: string): any => load_scene(read_json(`${CASES}/${stem}.json`));

function rot_z(d: number): [Vec3, Vec3, Vec3] {
  const c = Math.cos(rad(d)), s = Math.sin(rad(d));
  return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]];
}

const mul = (R: readonly Vec3[], v: readonly number[]): Vec3 =>
  R.map((row) => row[0] * (v[0] as number) + row[1] * (v[1] as number) + row[2] * (v[2] as number)) as Vec3;

/** `[loop4, light4]` of the U plate and its light, rotated about `z` by `rz` and translated by `T`. */
function u_plate(T: Vec3 = [0.0, 0.0, 0.0], rz = 0.0): [Vec4[], Vec4] {
  const R = rot_z(rz);
  const loop = U_XZ.map(([x, z]) => {
    const p = mul(R, [x, 1.0, z]);
    return [p[0] + T[0], p[1] + T[1], p[2] + T[2], 1.0] as Vec4;
  });
  const L = mul(R, LIGHT);
  return [loop, [L[0] + T[0], L[1] + T[1], L[2] + T[2], 1.0]];
}

const is_kind = (s: Source, k: string): boolean => typeof s === "object" && s !== null && (s as { kind: string }).kind === k;

/** `[kind, angle]` of the component's direction rows: `out` when the previous row is a finite vertex, else `in`. */
function direction_rows(c: { vertices: Vec4[]; sources: Source[] }): [string, number][] {
  const rows: [string, number][] = [];
  c.sources.forEach((s, k) => {
    if (!is_kind(s, "dir")) return;
    const prev = c.sources[(k - 1 + c.sources.length) % c.sources.length] as Source;
    const kind = is_kind(prev, "dir") || is_kind(prev, "arc") ? "in" : "out";
    const v = c.vertices[k] as Vec4;
    rows.push([kind, Math.atan2(v[1], v[0])]);
  });
  return rows;
}

const n_arc = (c: { sources: Source[] }): number => c.sources.filter((s) => is_kind(s, "arc")).length;
const mod = (a: number, m: number): number => ((a % m) + m) % m;

/** Ground polygons of the components (directions pushed `far` away from `centre`). */
function ground_polygons(comps: readonly ShadowComponent[], centre: [number, number], far: number): [number, number][][] {
  return comps.map((c) => c.vertices.map((v): [number, number] => {
    if (v[3] === 0.0) {
      const n = Math.hypot(v[0], v[1]);
      return [centre[0] + (far * v[0]) / n, centre[1] + (far * v[1]) / n];
    }
    return [v[0] / v[3], v[1] / v[3]];
  }));
}

/** Winding number of `p` about the closed polygon `poly`. */
function winding(poly: readonly [number, number][], x: number, y: number): number {
  let w = 0;
  for (let k = 0; k < poly.length; k++) {
    const [ax, ay] = poly[k] as [number, number];
    const [bx, by] = poly[(k + 1) % poly.length] as [number, number];
    const side = (bx - ax) * (y - ay) - (x - ax) * (by - ay);
    if (ay <= y && by > y && side > 0) w += 1;
    else if (ay > y && by <= y && side < 0) w -= 1;
  }
  return w;
}

function even_odd(poly: readonly [number, number][], x: number, y: number): boolean {
  let inside = false;
  for (let k = 0; k < poly.length; k++) {
    const [ax, ay] = poly[k] as [number, number];
    const [bx, by] = poly[(k + 1) % poly.length] as [number, number];
    if ((ay > y) !== (by > y) && ax + ((y - ay) * (bx - ax)) / (by - ay) > x) inside = !inside;
  }
  return inside;
}

/** Ground points whose segment to the light crosses the plane `y = 1` inside the U outline. */
function analytic_plate(x: number, y: number): boolean {
  if (!(y > 1.0)) return false;
  const t = (1.0 - LIGHT[1]) / (y - LIGHT[1]);
  return even_odd(U_XZ, LIGHT[0] + t * (x - LIGHT[0]), LIGHT[2] + t * (0.0 - LIGHT[2]));
}

// --------------------------------------------------------------------------- shadow_loop on a 4-crossing loop
test("a four-crossing loop splits into two angularly paired loops (the analytic plate shadow)", () => {
  const [loop4, L4] = u_plate();
  const sh = shadow_loop(loop4, shadow_matrix(GROUND, L4), GROUND, 1e-9);
  const comps = sh.loops;
  assert.equal(comps.length, 2);
  assert.ok(sh.unbounded);
  assert.equal(sh.vertices, (comps[0] as ShadowComponent).vertices);
  assert.equal(sh.sources, (comps[0] as ShadowComponent).sources);
  const rows = comps.map(direction_rows);
  for (const r of rows) assert.deepEqual(r.map(([k]) => k).sort(), ["in", "out"]);
  const ins = rows.flatMap((r) => r.filter(([k]) => k === "in").map(([, a]) => a));
  let total = 0;
  for (const r of rows) {
    const th_out = (r.find(([k]) => k === "out") as [string, number])[1];
    const th_in = (r.find(([k]) => k === "in") as [string, number])[1];
    const gaps = ins.map((a) => mod(a - th_out, TWO_PI)).sort((a, b) => a - b);
    assert.ok(Math.abs(mod(th_in - th_out, TWO_PI) - (gaps[0] as number)) <= 1e-12, "the arc ends at the angularly next incoming direction");
    assert.ok(mod(th_in - th_out, TWO_PI) < Math.PI, "each arm's sweep is less than a half turn");
    total += mod(th_in - th_out, TWO_PI);
  }
  assert.ok(total < Math.PI, "the two arcs together cover less than the half circle");
  // reference-free check of the fill: nonzero union of the components against the analytic plate shadow
  const polys = ground_polygons(comps, [0.0, 18.5], 1e7);
  let inter = 0, union = 0, ref_any = false;
  for (let i = 0; i <= 280; i++) {
    for (let j = 0; j <= 430; j++) {
      const x = -14.0 + (28.0 * i) / 280, y = -3.0 + (43.0 * j) / 430;
      const got = polys.reduce((w, p) => w + winding(p, x, y), 0) !== 0;
      const ref = analytic_plate(x, y);
      ref_any = ref_any || ref;
      if (got && ref) inter++;
      if (got || ref) union++;
    }
  }
  assert.ok(ref_any);
  assert.ok(inter / union >= 0.99, `IoU ${inter / union}`);
});

test("single-pair loops keep one component holding the top-level arrays; the empty result has one empty one", () => {
  const [loop4] = u_plate();
  for (const lz of [2.5, 1.75]) {
    const sh = shadow_loop(loop4, shadow_matrix(GROUND, [0.0, -2.0, lz, 1.0]), GROUND, 1e-9);
    assert.equal(sh.loops.length, 1);
    const c = sh.loops[0] as ShadowComponent;
    assert.equal(c.vertices, sh.vertices);
    assert.equal(c.sources, sh.sources);
    assert.equal(c.unbounded, sh.unbounded);
    assert.equal(sh.unbounded, lz < 2.0);
  }
  const sh = shadow_loop(loop4, shadow_matrix(GROUND, [0.0, -2.0, -0.5, 1.0]), GROUND, 1e-9);
  assert.equal(sh.vertices.length, 0);
  assert.equal(sh.loops.length, 1);
  assert.equal((sh.loops[0] as ShadowComponent).vertices.length, 0);
});

const MOVES: [Vec3, number][] = [[[0.0, 6.0, 0.0], 0.0], [[0.0, -6.0, 0.0], 0.0], [[20.0, 0.0, 0.0], 0.0], [[0.0, 0.0, 0.0], 37.0],
  [[5.0, -3.0, 0.0], 123.0], [[-7.0, 11.0, 0.0], 250.0]];
for (const [T, rz] of MOVES) {
  test(`arc pairing is translation and rotation invariant: T=${JSON.stringify(T)} rz=${rz}`, () => {
    const [loop0, L0] = u_plate();
    const base = shadow_loop(loop0, shadow_matrix(GROUND, L0), GROUND, 1e-9).loops;
    const [loop4, L4] = u_plate(T, rz);
    const moved = shadow_loop(loop4, shadow_matrix(GROUND, L4), GROUND, 1e-9).loops;
    assert.equal(base.length, 2);
    assert.equal(moved.length, 2);
    const R = rot_z(rz);
    base.forEach((a, ci) => {
      const b = moved[ci] as ShadowComponent;
      assert.deepEqual(a.sources, b.sources);
      assert.equal(a.vertices.length, b.vertices.length);
      a.vertices.forEach((va, k) => {
        const vb = b.vertices[k] as Vec4;
        if (va[3] === 0.0) {
          assert.equal(vb[3], 0.0);
          const na = Math.hypot(va[0], va[1], va[2]), nb = Math.hypot(vb[0], vb[1], vb[2]);
          const ra = mul(R, [va[0] / na, va[1] / na, va[2] / na]);
          for (let m = 0; m < 3; m++) assert.ok(Math.abs((ra[m] as number) - (vb[m] as number) / nb) <= 1e-9);
        } else {
          const ra = mul(R, [va[0] / va[3], va[1] / va[3], va[2] / va[3]]);
          for (let m = 0; m < 3; m++) assert.ok(Math.abs((ra[m] as number) + (T[m] as number) - (vb[m] as number) / vb[3]) <= 1e-7);
        }
      });
    });
  });
}

// --------------------------------------------------------------------------- the matching itself (synthetic crossings)
/** `verts / sources / kinds` of a loop `F0, out, in, F1, out, in, F2` with the given direction angles (degrees). */
function synthetic(pattern: readonly number[]): [Vec4[], Source[], string[]] {
  const d = (a: number): Vec4 => [Math.cos(rad(a)), Math.sin(rad(a)), 0.0, 0.0];
  const v = (index: number): Source => ({ kind: "vertex", index });
  const dir = (i: number, j: number): Source => ({ kind: "dir", i: v(i), j: v(j) });
  const verts: Vec4[] = [[0, 0, 0, 1], d(pattern[0] as number), d(pattern[1] as number), [1, 0, 0, 1], d(pattern[2] as number),
    d(pattern[3] as number), [2, 0, 0, 1]];
  const sources: Source[] = [v(0), dir(0, 1), dir(1, 2), v(1), dir(3, 4), dir(4, 5), v(2)];
  return [verts, sources, ["finite", "out", "in", "finite", "out", "in", "finite"]];
}

/** Source labels as in the Python tests: `F<k>` for a vertex, `dir:i,j`, `arc:k`. */
function labels(sources: readonly Source[]): string[] {
  return sources.map((s) => {
    const t = s as any;
    if (t.kind === "vertex") return `F${t.index}`;
    if (t.kind === "dir") return `dir:${t.i.index},${t.j.index}`;
    return `${t.kind}:${t.k}`;
  });
}

test("interleaved crossings are repaired into two simple loops (finding m4-geometry#0, the wall case)", () => {
  const [verts, sources, kinds] = synthetic([-54.5, -125.5, 149.0, 31.0]);
  const comps = arc_components(verts, sources, kinds, [1, 4], null);
  assert.equal(comps.length, 2);
  const [c0, c1] = comps as [ShadowComponent, ShadowComponent];
  assert.deepEqual(labels(c0.sources), ["F0", "dir:0,1", "arc:0", "dir:4,5", "F2"]);
  assert.deepEqual(labels(c1.sources), ["dir:1,2", "F1", "dir:3,4", "arc:0"]);
  const mid0 = deg(Math.atan2((c0.vertices[2] as Vec4)[1], (c0.vertices[2] as Vec4)[0]));
  const mid1 = deg(Math.atan2((c1.vertices[3] as Vec4)[1], (c1.vertices[3] as Vec4)[0]));
  assert.ok(Math.abs(mid0 - (-54.5 + 42.75)) <= 1e-9);
  assert.ok(Math.abs(mod(mid1 - (149.0 + 42.75) + 180.0, 360.0) - 180.0) <= 1e-9);
});

test("the loop-order pairing is reproduced when it is the angular one", () => {
  const [verts, sources, kinds] = synthetic([10.0, 100.0, 200.0, 300.0]);
  const comps = arc_components(verts, sources, kinds, [1, 4], null);
  assert.equal(comps.length, 1);
  assert.deepEqual(labels((comps[0] as ShadowComponent).sources),
    ["F0", "dir:0,1", "arc:0", "dir:1,2", "F1", "dir:3,4", "arc:0", "dir:4,5", "F2"]);
});

test("nested crossings match like parentheses", () => {
  const [verts, sources, kinds] = synthetic([10.0, 40.0, 20.0, 30.0]);
  const comps = arc_components(verts, sources, kinds, [1, 4], null);
  assert.equal(comps.length, 1);
  const c = comps[0] as ShadowComponent;
  assert.deepEqual(labels(c.sources), ["F0", "dir:0,1", "dir:1,2", "F1", "dir:3,4", "dir:4,5", "F2"]);
  const rows = direction_rows(c);
  assert.deepEqual(rows.map(([k]) => k), ["out", "in", "out", "in"]);
  assert.deepEqual(rows.map(([, a]) => Math.round(deg(a) * 1e9) / 1e9), [10.0, 40.0, 20.0, 30.0]);
});

test("coincident out and in crossings sweep the full circle", () => {
  const [verts, sources, kinds] = synthetic([10.0, 10.0, 100.0, 200.0]);
  const comps = arc_components(verts, sources, kinds, [1, 4], null);
  assert.equal(comps.length, 1);
  const c = comps[0] as ShadowComponent;
  assert.equal(n_arc(c), 5 + 1);
  assert.deepEqual(labels(c.sources).slice(0, 8), ["F0", "dir:0,1", "arc:0", "arc:1", "arc:2", "arc:3", "arc:4", "dir:1,2"]);
});

/** The literal v1/v2 loop-order arc code (each `out` swept to the loop-order next `in`), as `v1_loop_order` of
 * `tests/test_arc_base_level.py`. */
function v1_loop_order(verts: readonly Vec4[], sources: readonly Source[], kinds: readonly string[]): [Vec4[], Source[]] {
  const out_verts: Vec4[] = [], out_sources: Source[] = [];
  const m = verts.length;
  for (let k = 0; k < m; k++) {
    out_verts.push(verts[k] as Vec4);
    out_sources.push(sources[k] as Source);
    if (kinds[k] === "out") {
      const th0 = arc_angle(verts[k] as Vec4, null), th1 = arc_angle(verts[(k + 1) % m] as Vec4, null);
      let delta = (th1 - th0) % TWO_PI;
      if (delta < 0) delta += TWO_PI;
      if (!Number.isFinite(delta) || delta <= 1e-12) delta = TWO_PI;
      sweep_arc(th0, delta, null, out_verts, out_sources);
    }
  }
  return [out_verts, out_sources];
}

for (const pattern of [[10.0, 100.0, 200.0, 300.0], [-54.5, 31.0, 149.0, -125.5], [170.0, -170.0, -20.0, 20.0]]) {
  test(`a loop-order pairing with two excursions is bit-identical to the v1 code: ${JSON.stringify(pattern)}`, () => {
    // the u_closed_arm_wall pattern (out -54.5°, in 31°, out 149°, in -125.5°) among them: a sweep computed on the
    // mod-2π-reduced angles differed by an ulp from the v1 sweep
    const [verts, sources, kinds] = synthetic(pattern);
    const comps = arc_components(verts, sources, kinds, [1, 4], null);
    assert.equal(comps.length, 1);
    const [rv, rs] = v1_loop_order(verts, sources, kinds);
    assert.deepEqual((comps[0] as ShadowComponent).sources, rs);
    assert.deepEqual((comps[0] as ShadowComponent).vertices, rv); // strict deepEqual: Object.is on every float
  });
}

// --------------------------------------------------------------------------- whole scenes (v7 conformance cases)
/** Stage-A records whose unbounded component loops outnumber the caster's silhouette loops. */
function multi_component_records(A: any): any[] {
  const objects = new Map<string, any>(A.objects.map((o: any) => [o.id, o]));
  return A.shadows.filter((rec: any) => {
    const obj = objects.get(rec.object);
    if (obj === undefined || !obj.lights.has(rec.light)) return false;
    return rec.loops.filter((l: any) => l.unbounded).length > obj.lights.get(rec.light).loops.length;
  });
}

const shadow_of = (doc: any, receiver: string, object: string): any =>
  doc.shadows.find((s: any) => s.receiver === receiver && s.object === object);

test("arch on the ground: two ground loops (the legs)", () => {
  const A = shadow_geometry(scene_of("arc_pairing_arch_ground"));
  assert.deepEqual(A.shadows.map((r) => r.loops.length), [2]);
  assert.ok(multi_component_records(A).length > 0);
});

test("U-prism on its side: the v2 ground path with two excursions", () => {
  assert.ok(multi_component_records(shadow_geometry(scene_of("arc_pairing_u_on_side"))).length > 0);
});

test("U-prism with a wall beyond the opening shadows only the arms (two wall loops)", () => {
  const doc = render(scene_of("arc_pairing_u_notch_wall")).geometry as any;
  const sh = shadow_of(doc, "wall", "u");
  assert.equal(sh.loops.length, 2);
  assert.ok(sh.loops.every((l: any[]) => l.length >= 3));
});

test("U-prism straddling the light plane casts nothing on the wall", () => {
  const doc = render(scene_of("arc_pairing_u_wall")).geometry as any;
  const sh = shadow_of(doc, "wall", "u");
  assert.deepEqual([sh.loops, sh.polygons, sh.unbounded], [[], [], false]);
  assert.equal(shadow_of(doc, "ground", "u").unbounded, false);
});

test("upright spiral with the lamp inside: one p = 1 loop whose arc sweeps more than one turn", () => {
  const A = shadow_geometry(scene_of("arc_base_level_spiral_upright"));
  const recs = A.shadows.filter((r) => r.receiver === "ground");
  assert.equal(recs.length, 1);
  const rec = recs[0] as any;
  assert.equal(rec.loops.length, 1);
  assert.ok(rec.unbounded);
  assert.ok(rec.loops[0].sources.filter((s: Source) => is_kind(s, "arc")).length > 6, "the arc must sweep more than one full turn");
});

test("tilted spiral: two excursions, split into components", () => {
  assert.ok(multi_component_records(shadow_geometry(scene_of("arc_base_level_spiral_tilted"))).length > 0);
});

/** Number of lit faces (planar polygons) hit by the ray `l + t u`, `t > 0` (crossing-number test in the face plane). */
function brute_force_hits(mesh: Mesh, lit: readonly boolean[], l: readonly number[], u: readonly number[]): number {
  let hits = 0;
  mesh.faces.forEach((face, f) => {
    if (!lit[f]) return;
    const P = face.map((k) => mesh.vertices[k] as Vec3);
    const n = mesh.face_normals[f] as Vec3;
    const den = n[0] * (u[0] as number) + n[1] * (u[1] as number) + n[2] * (u[2] as number);
    if (Math.abs(den) < 1e-15) return;
    const p0 = P[0] as Vec3;
    const t = (n[0] * (p0[0] - (l[0] as number)) + n[1] * (p0[1] - (l[1] as number)) + n[2] * (p0[2] - (l[2] as number))) / den;
    if (t <= 0.0) return;
    const X = [0, 1, 2].map((k) => (l[k] as number) + t * (u[k] as number));
    const an = n.map(Math.abs);
    const drop = an.indexOf(Math.max(...an));
    const keep = [0, 1, 2].filter((k) => k !== drop);
    const q = keep.map((k) => X[k] as number);
    const poly = P.map((p) => keep.map((k) => p[k] as number) as [number, number]);
    if (even_odd(poly, q[0] as number, q[1] as number)) hits++;
  });
  return hits;
}

test("light_plane_level counts the lit faces crossed by the reference ray (brute force, upright spiral)", () => {
  const scene = scene_of("arc_base_level_spiral_upright");
  const A = shadow_geometry(scene);
  const obj = A.objects[0] as any;
  const lit = obj.lights.get("lamp").lit as boolean[];
  const L: Vec4 = [...(scene.lights[0] as any).position, 1.0] as Vec4;
  const ref = light_plane_level(obj.mesh, lit, L, GROUND, 1e-9);
  assert.ok(ref !== null);
  const [theta, count] = ref;
  const u = [Math.cos(theta), Math.sin(theta), 0.0];
  assert.equal(count, brute_force_hits(obj.mesh, lit, L, u));
  assert.ok(count >= 1);
  for (let d = 0; d < 360; d += 7) {
    assert.ok(brute_force_hits(obj.mesh, lit, L, [Math.cos(rad(d)), Math.sin(rad(d)), 0.0]) >= 1, `${d}°`);
  }
});

test("light_plane_level is null for a directional light and for a lit patch below the light plane", () => {
  const A = shadow_geometry(scene_of("arc_base_level_spiral_upright"));
  const obj = A.objects[0] as any;
  const lit = obj.lights.get("lamp").lit as boolean[];
  assert.equal(light_plane_level(obj.mesh, lit, [0.0, 0.0, 1.0, 0.0], GROUND, 1e-9), null);
  assert.equal(light_plane_level(obj.mesh, lit, [0.0, 0.0, 50.0, 1.0], GROUND, 1e-9), null);
});

// --------------------------------------------------------------------------- the pieces
test("arc_level counts signed turns", () => {
  assert.equal(arc_level([[0.0, rad(90.0)]], rad(45.0)), 1);
  assert.equal(arc_level([[0.0, rad(90.0)]], rad(135.0)), 0);
  assert.equal(arc_level([[0.0, rad(90.0) + TWO_PI]], rad(45.0)), 2);
  assert.equal(arc_level([[0.0, rad(90.0) + TWO_PI]], rad(135.0)), 1);
  assert.equal(arc_level([[0.0, rad(90.0) - TWO_PI]], rad(135.0)), -1);
  assert.equal(arc_level([[0.0, rad(90.0) - TWO_PI]], rad(45.0)), 0);
  assert.equal(arc_level([[0.0, TWO_PI], [rad(10.0), rad(20.0)]], rad(15.0)), 2);
});

test("turns = 0 is the default and turns adds full turns to the first arc", () => {
  const [loop4, L4] = u_plate();
  const M: Mat4 = shadow_matrix(GROUND, L4);
  const base = shadow_loop(loop4, M, GROUND, 1e-9);
  const same = shadow_loop(loop4, M, GROUND, 1e-9, null, null, null, 0);
  assert.deepEqual(same.loops, base.loops);
  const plus = shadow_loop(loop4, M, GROUND, 1e-9, null, null, null, 1);
  assert.equal(plus.loops.length, base.loops.length);
  const a0 = (base.loops[0] as ShadowComponent).arcs[0] as [number, number];
  const a1 = (plus.loops[0] as ShadowComponent).arcs[0] as [number, number];
  assert.equal(a1[0], a0[0]);
  assert.equal(a1[1], a0[1] + TWO_PI);
  assert.equal(n_arc(plus.loops[0] as ShadowComponent), n_arc(base.loops[0] as ShadowComponent) + 6);
  const lv = (r: typeof base, th: number): number => r.loops.reduce((acc, c) => acc + arc_level(c.arcs, th), 0);
  for (const d of [3.0, 97.0, 181.0, 275.0]) assert.equal(lv(plus, rad(d)), lv(base, rad(d)) + 1);
  const minus = shadow_loop(loop4, M, GROUND, 1e-9, null, null, null, -1);
  const am = (minus.loops[0] as ShadowComponent).arcs[0] as [number, number];
  assert.equal(am[1], a0[1] - TWO_PI);
  assert.ok(am[1] < 0.0);
});

test("turns on a p = 1 loop corrects its only arc", () => {
  const [loop4] = u_plate();
  const M = shadow_matrix(GROUND, [0.0, -2.0, 1.75, 1.0]);
  const base = shadow_loop(loop4, M, GROUND, 1e-9);
  const plus = shadow_loop(loop4, M, GROUND, 1e-9, null, null, null, 1);
  const a0 = (base.loops[0] as ShadowComponent).arcs, a1 = (plus.loops[0] as ShadowComponent).arcs;
  assert.equal(a0.length, 1);
  assert.equal(a1.length, 1);
  assert.equal((a1[0] as [number, number])[1], (a0[0] as [number, number])[1] + TWO_PI);
});

test("a negative sweep is sampled clockwise", () => {
  const verts: Vec4[] = [], src: Source[] = [];
  sweep_arc(0.0, -rad(150.0), null, verts, src);
  assert.deepEqual(verts.map((v) => Math.round(deg(Math.atan2(v[1], v[0])) * 1e9) / 1e9), [-50.0, -100.0]);
  assert.deepEqual(src, [{ kind: "arc", k: 0 }, { kind: "arc", k: 1 }]);
});

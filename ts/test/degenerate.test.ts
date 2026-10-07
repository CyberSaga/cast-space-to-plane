/** One scene per spec §5.7 row through the port (contract §5.4.13), ported from the smallest scenes of
 * `tests/test_degenerate.py`: the warning code set, finite output and a drawable SVG; plus `LIGHT_INSIDE_OBJECT`
 * (sphere, box) and the undefined `F` / `L'` cases. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { warning_codes } from "../src/errors.js";
import { dumps } from "../src/output/geometry_json.js";
import { write_svg } from "../src/output/svg.js";
import { render } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";

function scene_with(objects: unknown[], light: unknown, camera: Record<string, unknown>) {
  return load_scene({
    version: "0.1",
    objects,
    lights: [light],
    receivers: [{ id: "ground", type: "plane", normal: [0, 0, 1], offset: 0.0 }],
    camera: { roll_deg: 0, focal_length_mm: 24, frame_mm: [36, 24], near_m: 0.05, ...camera },
    output: { canvas_mm: [360, 240] },
  });
}

const BOX = { id: "crate", type: "box", size: [1.0, 1.0, 1.0], transform: { position: [0.0, 5.0, 0.0] } };
const LEVEL_CAMERA = { position: [0.0, 0.0, 1.5], target: [0.0, 5.0, 1.5] };
const SIDE_CAMERA = { position: [3.0, -2.0, 2.0], target: [0.0, 5.0, 0.5] };

function numbers(obj: unknown, out: number[] = []): number[] {
  if (typeof obj === "number") out.push(obj);
  else if (Array.isArray(obj)) obj.forEach((x) => numbers(x, out));
  else if (obj !== null && typeof obj === "object") Object.values(obj).forEach((x) => numbers(x, out));
  return out;
}

function finite_and_drawable(doc: any): string {
  assert.ok(numbers(doc).every(Number.isFinite));
  const text = dumps(doc);
  assert.ok(!text.includes("NaN") && !text.includes("Infinity"));
  const svg = write_svg(doc);
  assert.ok(svg.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<svg ') && svg.endsWith("</svg>\n"));
  const low = svg.toLowerCase();
  assert.ok(!low.includes("nan") && !low.includes("inf"));
  return svg;
}

function ids_of(doc: any, code: string): string[][] {
  return doc.warnings.filter((w: any) => w.code === code).map((w: any) => w.ids);
}

test("row 1: light behind the viewer -> anti-light point below the horizon, never nulled", () => {
  const doc = render(scene_with([BOX], { id: "lamp", type: "point", position: [0.5, -4.0, 3.0] }, LEVEL_CAMERA)).geometry as any;
  assert.deepEqual(ids_of(doc, "LIGHT_BEHIND_CAMERA"), [["lamp"]]);
  const con = doc.construction;
  assert.ok(con.light_point !== null && con.light_point[1] < doc.horizon.v_mm);
  assert.deepEqual(doc.points["L.lamp"].image, con.light_point);
  assert.ok(doc.points["L.lamp"].depth < 0);
  const sh = doc.shadows[0];
  assert.ok(sh.outline.length > 0 && !sh.unbounded && sh.polygons[0].length >= 3);
  assert.ok(con.rays.length > 0 && con.checks.length > 0);
  assert.ok(Math.max(...con.checks.map((c: any) => c.max_error_mm)) <= 1e-6);
  assert.ok(finite_and_drawable(doc).includes("L′"));
});

test("row 2: light direction parallel to the picture plane -> parallel rays", () => {
  const doc = render(scene_with([BOX], { id: "sun", type: "directional", direction: [0.6, 0.0, 0.8] }, LEVEL_CAMERA)).geometry as any;
  assert.ok(warning_codes(doc.warnings).has("LIGHT_POINT_AT_INFINITY"));
  const con = doc.construction;
  assert.equal(con.light_point, null);
  const d = con.light_point_at_infinity as number[];
  const lp = con.segments.filter((s: any) => s.kind === "LP");
  assert.ok(lp.length >= 4);
  for (const seg of lp) {
    const [a, b] = seg.points;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    assert.ok(Math.abs(dx * (d[1] as number) - dy * (d[0] as number)) <= 1e-9 * Math.hypot(dx, dy) * Math.hypot(d[0] as number, d[1] as number));
  }
  finite_and_drawable(doc);
});

test("row 3: horizontal directional light -> no shadows", () => {
  const doc = render(scene_with([BOX], { id: "sun", type: "directional", direction: [1.0, 0.0, 0.0] },
    { position: [-3.0, -2.0, 1.5], target: [0.0, 5.0, 1.0] })).geometry as any;
  const codes = warning_codes(doc.warnings);
  assert.ok(codes.has("DIRECTIONAL_HORIZONTAL") && !codes.has("LIGHT_BELOW_RECEIVER"));
  const sh = doc.shadows[0];
  assert.deepEqual([sh.outline, sh.loops, sh.polygons, sh.unbounded], [[], [], [], false]);
  assert.deepEqual([doc.construction.rays, doc.construction.segments, doc.construction.checks], [[], [], []]);
  assert.ok(doc.construction.shadow_vp !== null);
  finite_and_drawable(doc);
});

test("row 4: vertex not below the point light -> unbounded clipped shadow", () => {
  const tall = { id: "tower", type: "box", size: [1.0, 1.0, 3.0], transform: { position: [0.0, 5.0, 0.0] } };
  const doc = render(scene_with([tall], { id: "lamp", type: "point", position: [2.5, 3.0, 2.0] },
    { position: [-1.0, -3.0, 3.0], target: [0.0, 5.0, 1.0] })).geometry as any;
  assert.deepEqual(ids_of(doc, "VERTEX_NOT_BELOW_LIGHT"), [["tower"]]);
  const sh = doc.shadows[0];
  assert.equal(sh.unbounded, true);
  for (const e of sh.outline) {
    if (typeof e === "object") {
      assert.ok(Math.abs(Math.hypot(...(e.direction as number[])) - 1) < 1e-12);
      assert.equal(e.direction[2], 0);
    }
  }
  assert.ok(!("tower.v4.shadow.lamp" in doc.points) && "tower.v0.shadow.lamp" in doc.points);
  for (const [u, v] of sh.polygons[0]) assert.ok(Math.abs(u) <= 270 + 1e-6 && Math.abs(v) <= 180 + 1e-6);
  const svg = finite_and_drawable(doc);
  assert.ok(svg.includes('<g id="cast_shadow.lamp"') && svg.includes("<path"));
});

test("row 5: vertex or shadow behind the camera -> clipped, image null", () => {
  const box = { id: "crate", type: "box", size: [1.0, 1.0, 1.0], transform: { position: [0.0, 0.3, 0.0] } };
  const doc = render(scene_with([box], { id: "lamp", type: "point", position: [0.0, 6.0, 2.0] },
    { position: [0.0, 0.0, 0.3], target: [0.0, 5.0, 0.3] })).geometry as any;
  assert.deepEqual(ids_of(doc, "POINT_BEHIND_CAMERA"), [["crate"]]);
  const behind = Object.keys(doc.points).filter((n) => doc.points[n].image === null && "world" in doc.points[n]);
  assert.ok(behind.some((n) => n.includes(".shadow.")));
  assert.ok(doc.shadows[0].polygons[0].length > 0);
  for (const [kind, name] of doc.construction.rays) {
    const base = kind === "F" ? name.slice(0, -5) : name;
    for (const n of [base, `${base}.shadow.lamp`, `${base}.foot`]) assert.notEqual(doc.points[n].image, null);
  }
  finite_and_drawable(doc);
});

for (const light of [
  { id: "lamp", type: "point", position: [0.5, 2.0, 3.0] },
  { id: "sun", type: "directional", direction: [0.0, 0.6, 0.8] },
]) {
  test(`row 6: face parallel to the light is unlit (${light.type})`, () => {
    const doc = render(scene_with([BOX], light, SIDE_CAMERA)).geometry as any;
    assert.deepEqual(ids_of(doc, "FACE_PARALLEL_TO_LIGHT"), [["crate"]]);
    const faces = doc.form_shadow[0].faces.map((f: string[]) => [...f].sort().join(","));
    assert.ok(faces.includes(["crate.v1", "crate.v2", "crate.v6", "crate.v5"].sort().join(",")));
    assert.ok(!faces.includes(["crate.v4", "crate.v5", "crate.v6", "crate.v7"].sort().join(",")));
    finite_and_drawable(doc);
  });
}

test("light below the receiver (point and directional)", () => {
  for (const light of [{ id: "lamp", type: "point", position: [0.0, 3.0, -1.0] }, { id: "sun", type: "directional", direction: [0.0, 0.6, -0.8] }]) {
    const doc = render(scene_with([BOX], light, SIDE_CAMERA)).geometry as any;
    assert.deepEqual(ids_of(doc, "LIGHT_BELOW_RECEIVER"), [[light.id]]);
    assert.deepEqual(doc.shadows[0].outline, []);
    assert.deepEqual(doc.construction.rays, []);
    finite_and_drawable(doc);
  }
});

test("object below the receiver: ground-crossing points <obj>.s<k>.<light> on the ground", () => {
  const buried = { id: "crate", type: "box", size: [1.0, 1.0, 1.0], transform: { position: [0.0, 5.0, -0.5] } };
  const doc = render(scene_with([buried], { id: "lamp", type: "point", position: [2.0, 2.0, 3.0] }, SIDE_CAMERA)).geometry as any;
  assert.deepEqual(ids_of(doc, "OBJECT_BELOW_RECEIVER"), [["crate"]]);
  const outline = doc.shadows[0].outline as string[];
  assert.ok(outline.some((n) => /\.s\d+\.lamp$/.test(n)));
  for (const n of outline) assert.ok(Math.abs(doc.points[n].world[2]) < 1e-9);
  assert.ok(!("crate.v0.shadow.lamp" in doc.points));
  finite_and_drawable(doc);
});

test("vertical directional light: F undefined, S' = Q' self-check", () => {
  const doc = render(scene_with([BOX], { id: "sun", type: "directional", direction: [0.0, 0.0, 1.0] }, SIDE_CAMERA)).geometry as any;
  const codes = warning_codes(doc.warnings);
  assert.ok(!codes.has("SHADOW_VP_AT_INFINITY") && !codes.has("CONSTRUCTION_CHECK_SKIPPED"));
  assert.ok(!("F.sun" in doc.points) && doc.points["L.sun"].at_infinity === true);
  const con = doc.construction;
  assert.equal(con.shadow_vp, null);
  assert.equal(con.shadow_vp_at_infinity, null);
  assert.ok(con.rays.length > 0 && con.rays.every((r: string[]) => r[0] === "L"));
  assert.deepEqual(new Set(con.segments.map((s: any) => s.kind)), new Set(["LP", "PQ"]));
  assert.ok(con.checks.length > 0 && Math.max(...con.checks.map((c: any) => c.max_error_mm)) <= 1e-6);
  finite_and_drawable(doc);
});

test("point light at the camera centre: L' undefined, S' = P' self-check", () => {
  const doc = render(scene_with([BOX], { id: "lamp", type: "point", position: [0.0, -5.0, 4.0] },
    { position: [0.0, -5.0, 4.0], target: [0.0, 5.0, 0.5] })).geometry as any;
  const codes = warning_codes(doc.warnings);
  assert.ok(!codes.has("LIGHT_POINT_AT_INFINITY") && !codes.has("LIGHT_BEHIND_CAMERA") && !codes.has("CONSTRUCTION_CHECK_SKIPPED"));
  const con = doc.construction;
  assert.equal(con.light_point, null);
  assert.equal(con.light_point_at_infinity, null);
  assert.ok(con.rays.length > 0 && con.rays.every((r: string[]) => r[0] === "F"));
  assert.deepEqual(new Set(con.segments.map((s: any) => s.kind)), new Set(["FQ", "PQ"]));
  assert.equal(doc.points["L.lamp"].image, null);
  finite_and_drawable(doc);
});

test("LIGHT_INSIDE_OBJECT: sphere and box only warn", () => {
  const ball = { id: "ball", type: "sphere", radius: 0.8, transform: { position: [0.0, 5.0, 0.0] } };
  const crate = { id: "crate", type: "box", size: [1.0, 1.0, 1.0], transform: { position: [2.5, 5.0, 0.0] } };
  let doc = render(scene_with([ball, crate], { id: "lamp", type: "point", position: [0.2, 5.1, 0.9] }, SIDE_CAMERA)).geometry as any;
  const inside = doc.warnings.filter((w: any) => w.code === "LIGHT_INSIDE_OBJECT");
  assert.deepEqual(inside.map((w: any) => w.ids), [["ball"]]);
  assert.ok(inside[0].message.includes("sphere"));
  const sh = doc.shadows.find((s: any) => s.object === "ball");
  assert.deepEqual([sh.outline, sh.loops, sh.conics, sh.polygons, sh.unbounded], [[], [], [], [], false]);
  assert.ok(!Object.keys(doc.points).some((n) => n.startsWith("ball.") && !n.includes(".og")));
  let svg = finite_and_drawable(doc);
  assert.ok(svg.includes('<g id="objects.ball"') && !svg.includes('<g id="form_shadow.ball"'));
  const b = { id: "b", type: "box", size: [2.0, 2.0, 2.0], transform: { position: [0.0, 5.0, 0.0] } };
  const small = { id: "crate", type: "box", size: [1.0, 1.0, 0.3], transform: { position: [3.5, 5.0, 0.0] } };
  doc = render(scene_with([b, small], { id: "lamp", type: "point", position: [0.0, 5.0, 1.0] },
    { position: [3.0, -3.0, 2.5], target: [0.0, 5.0, 0.5] })).geometry as any;
  assert.deepEqual(ids_of(doc, "LIGHT_INSIDE_OBJECT"), [["b"]]);
  const fs = doc.form_shadow.filter((f: any) => f.object === "b");
  assert.equal(fs.length, 1);
  assert.equal(fs[0].faces.length, 6);
  assert.ok(doc.construction.rays.every((r: string[]) => (r[1] as string).split(".")[0] === "crate"));
  svg = finite_and_drawable(doc);
});

test("cylinder cap exactly at the light height: rows 4 and 6 at once", () => {
  const cyl = { id: "drum", type: "cylinder", radius: 0.4, height: 1.5, transform: { position: [0.0, 5.0, 0.0] } };
  const doc = render(scene_with([cyl], { id: "lamp", type: "point", position: [2.5, 4.0, 1.5] },
    { position: [-1.0, -3.0, 3.0], target: [0.0, 5.0, 1.0] })).geometry as any;
  const codes = warning_codes(doc.warnings);
  assert.ok(codes.has("VERTEX_NOT_BELOW_LIGHT") && codes.has("FACE_PARALLEL_TO_LIGHT"));
  const sh = doc.shadows[0];
  assert.ok(sh.unbounded && sh.outline.some((e: unknown) => typeof e === "object"));
  assert.ok("drum.g0.base.shadow.lamp" in doc.points && !("drum.g0.top.shadow.lamp" in doc.points));
  assert.deepEqual(sh.conics.map((c: any) => c.which), ["base"]);
  finite_and_drawable(doc);
});

// --------------------------------------------------------------------------- M4: bounded receivers (contract §5.1.11)
// ported from tests/test_degenerate.py::test_m4_receiver_degeneracies_warn_and_stay_finite (the wall_and_ground variants)
function wall_and_ground(): any {
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

const M4_VARIANTS: Record<string, [(s: any) => void, string[]]> = {
  "light behind the wall": [(s) => { s.lights = [{ id: "lamp", type: "point", position: [0, 8, 3] }]; }, ["RECEIVER_UNLIT"]],
  "light in the wall plane": [(s) => { s.lights = [{ id: "lamp", type: "point", position: [0, 6, 3] }]; }, ["RECEIVER_UNLIT"]],
  "sun parallel to the wall": [(s) => { s.lights = [{ id: "lamp", type: "directional", direction: [0.6, 0.0, 0.8] }]; }, ["RECEIVER_UNLIT"]],
  "sun behind the wall": [(s) => { s.lights = [{ id: "lamp", type: "directional", direction: [0.0, 0.6, 0.8] }]; }, ["RECEIVER_UNLIT"]],
  "light below the ground": [(s) => { s.lights = [{ id: "lamp", type: "point", position: [0, 2, -1] }]; },
    ["RECEIVER_UNLIT", "LIGHT_BELOW_RECEIVER"]],
  "sun along the wall normal": [(s) => { s.lights = [{ id: "lamp", type: "directional", direction: [0.0, -1.0, 0.0] }]; },
    ["DIRECTIONAL_HORIZONTAL"]],
  "plate seen edge-on": [(s) => {
    s.camera = { position: [-6, 6, 1.6], target: [0, 6, 1.0], focal_length_mm: 35, frame_mm: [36, 24] };
  }, []],
  "crate straddling the wall": [(s) => { s.objects[0].transform.position = [0, 6.0, 0]; }, []],
  "coplanar caster": [(s) => {
    s.receivers.push({ id: "tile", type: "plane", normal: [0, -1, 0], offset: 6, bounds: [[3, 6, 0], [5, 6, 0], [5, 6, 2.5], [3, 6, 2.5]] });
  }, []],
};

for (const [name, [mutate, expected]] of Object.entries(M4_VARIANTS)) {
  test(`M4: ${name} warns with the closed list and stays finite`, () => {
    const s = wall_and_ground();
    mutate(s);
    const doc = render(load_scene(s)).geometry as any;
    const codes = warning_codes(doc.warnings);
    for (const c of expected) assert.ok(codes.has(c), `${name}: ${[...codes].join(", ")}`);
    if (name !== "light below the ground") assert.ok(!codes.has("OBJECT_BELOW_RECEIVER"), name);
    for (const ids of ids_of(doc, "RECEIVER_UNLIT")) assert.deepEqual(ids, ["lamp", "wall"]);
    finite_and_drawable(doc);
    if (name === "sun along the wall normal") assert.ok(!("F.lamp.wall" in doc.points));
    if (name === "light in the wall plane") {
      assert.equal(doc.receivers.find((r: any) => r.id === "wall").casts.lamp, false);
    }
    if (name === "coplanar caster") {
      const tile_on_wall = doc.shadows.find((sh: any) => sh.receiver === "wall" && sh.object === "tile");
      assert.deepEqual(tile_on_wall.loops, []);
    }
    if (name === "crate straddling the wall") {
      // the silent clip: crossings named <obj>.s<k>.<light>.<r>, no duplicate point at z = 0
      const wall = doc.shadows.find((sh: any) => sh.receiver === "wall" && sh.object === "crate");
      const names = wall.outline.filter((e: unknown) => typeof e === "string");
      assert.equal(new Set(names).size, names.length);
    }
  });
}

test("interim guards (M7 phase 2 part 1 review): unported mesh / hidden-line input is a typed SceneError, not a plain Error or a wrong document", async () => {
  const { SceneError } = await import("../src/errors.js");
  const { compose, project_scene, shadow_geometry } = await import("../src/pipeline.js");
  const mesh = { id: "m", type: "mesh", data: { vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0]], faces: [[0, 1, 2]] } };
  const s1 = scene_with([BOX, mesh], { id: "sun", type: "directional", direction: [0.6, 0, -0.8] }, SIDE_CAMERA);
  assert.throws(() => render(s1), (e: unknown) => e instanceof SceneError && e.field === "objects[1].type");
  const s2 = scene_with([BOX], { id: "sun", type: "directional", direction: [0.6, 0, -0.8] }, SIDE_CAMERA);
  assert.throws(() => render(s2, null, true), (e: unknown) => e instanceof SceneError && e.field === "output.hidden_lines");
  const s3 = load_scene({ ...JSON.parse(JSON.stringify(s2)), output: { canvas_mm: [360, 240], hidden_lines: true } });
  assert.throws(() => render(s3), (e: unknown) => e instanceof SceneError && e.field === "output.hidden_lines");
  // the explicit switch-off override still renders a hidden_lines scene; stage A/B are unaffected
  assert.equal(render(s3, null, false).geometry.hidden_lines, false);
  assert.equal(compose(s3, project_scene(s3, shadow_geometry(s3)), false).hidden_lines, false);
});

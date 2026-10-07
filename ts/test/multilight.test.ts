/**
 * Multiple lights through the port (contract §5.3, M7 phase 2 part 4; the port of `tests/test_multilight.py`'s
 * helper, acceptance and SVG rows): the `multilight.ts` helpers, the hand-computed acceptance case of §5.3.10
 * (`multilight_two_point_symmetric_box`: three umbra pieces with areas 132.85761502560047, 1315.4880281807557,
 * 90.38709809014404, total 1538.7327412965), the per-light bit-identity statement of §5.3.2, the multi-light SVG groups
 * of §5.3.6 / §5.0.6 (opacities, umbra path, core, per-light construction, hidden-line order), `umbra = false`, an
 * inactive second light, and the single-light documents carrying none of the M6 keys.
 */

import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";

import {
  active_lights, assemble_form_shadow, curved_stem_name, is_light_dependent_stem, is_multi, multi_light_name, plate_form_lights,
  plate_silhouette_lights, silhouette_lights, split_form, umbra_entries, unlit_union,
} from "../src/multilight.js";
import { dumps } from "../src/output/geometry_json.js";
import { UMBRA_STYLE, n_active, write_svg } from "../src/output/svg.js";
import { compose, project_scene, render, shadow_geometry } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { umbra_from_document, umbra_pieces } from "../src/umbra.js";

import { read_example, read_json, repo_path } from "./helpers.js";

const CASES = repo_path("tests", "conformance", "cases");
const M6_KEYS = ["constructions", "umbra", "form_shadow_core"];

const case_scene = (name: string): any => read_json(`${CASES}/${name}.json`);
const doc_of = (raw: any, umbra = true): any => JSON.parse(dumps(render(load_scene(raw), null, null, null, umbra).geometry));
const svg_of = (raw: any): string => render(load_scene(raw)).svg;
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x));

function area(piece: readonly (readonly number[])[]): number {
  let s = 0.0;
  for (let k = 0; k < piece.length; k++) {
    const a = piece[k] as readonly number[], b = piece[(k + 1) % piece.length] as readonly number[];
    s += (a[0] as number) * (b[1] as number) - (b[0] as number) * (a[1] as number);
  }
  return 0.5 * s;
}

/** `<g id>` values of an SVG in document order. */
const g_ids = (svg: string): string[] => [...svg.matchAll(/<g id="([^"]*)"/g)].map((m) => m[1] as string);

/** The opening tag of `<g id="gid" …>`. */
function g_tag(svg: string, gid: string): string {
  const m = new RegExp(`<g id="${gid.replace(/\./g, "\\.")}"[^>]*>`).exec(svg);
  assert.ok(m, gid);
  return m[0];
}

/** The body of `<g id="gid">…</g>` (nested groups balanced; `""` for an empty `<g …/>`). */
function g_body(svg: string, gid: string): string {
  const tag = g_tag(svg, gid);
  if (tag.endsWith("/>")) return "";
  let pos = svg.indexOf(tag) + tag.length;
  const start = pos;
  let depth = 1;
  while (depth > 0) {
    const open = svg.indexOf("<g ", pos), close = svg.indexOf("</g>", pos);
    if (open >= 0 && open < close) {
      const end = svg.indexOf(">", open);
      if (svg[end - 1] !== "/") depth++;
      pos = end + 1;
    } else {
      depth--;
      pos = close + 4;
    }
  }
  return svg.slice(start, pos - 4);
}

// --- helpers (contract §5.3.2, §5.3.3) ---------------------------------------------------------------

test("is_multi and the light-dependent stems", () => {
  assert.equal(is_multi([{}]), false);
  assert.equal(is_multi([{}, {}]), true);
  assert.equal(is_multi({ lights: [{}, {}, {}] }), true);
  for (const [stem, dep] of [["sil.0", true], ["sil.12", true], ["g3.base", true], ["g0.top", true], ["c", false], ["apex", false],
    ["og1.base", false], ["v4", false], ["sil", false], ["g1", false], ["sil.0.west", false]] as [string, boolean][]) {
    assert.equal(is_light_dependent_stem(stem), dep, stem);
  }
  assert.equal(curved_stem_name("ball", "sil.0", "lamp", true), "ball.sil.0.lamp");
  assert.equal(curved_stem_name("ball", "sil.0", "lamp", false), "ball.sil.0");
  assert.equal(curved_stem_name("ball", "c", "lamp", true), "ball.c");
});

test("multi_light_name: the §5.3.2 name map", () => {
  const table: [string, string][] = [
    ["ball.sil.0", "ball.sil.0.lamp"], ["ball.sil.0.shadow.lamp", "ball.sil.0.lamp.shadow.lamp"], ["ball.sil.3.foot.wall", "ball.sil.3.lamp.foot.wall"],
    ["p.g2.base.shadow.lamp", "p.g2.base.lamp.shadow.lamp"], ["p.g0.top", "p.g0.top.lamp"], ["ball.c", "ball.c"], ["box.v3.foot", "box.v3.foot"],
    ["L.lamp", "L.lamp"], ["p.og1.base", "p.og1.base"],
  ];
  for (const [single, multi] of table) assert.equal(multi_light_name(single, "lamp"), multi, single);
  assert.equal(multi_light_name("F.sil.0", "lamp", ["ball"]), "F.sil.0");
  assert.equal(multi_light_name("ball.sil.0", "lamp", new Set(["ball"])), "ball.sil.0.lamp");
});

test("silhouette_lights: OR over lights, per-edge lists, missing records, length check", () => {
  const [sil, lists] = silhouette_lights([[true, false, false], null, [true, true, false]], ["a", "b", "c"], 3);
  assert.deepEqual(sil, [true, true, false]);
  assert.deepEqual(lists, [["a", "c"], ["c"], []]);
  assert.deepEqual(silhouette_lights([null, null], ["a", "b"], 2), [[false, false], [[], []]]);
  assert.throws(() => silhouette_lights([[true]], ["a"], 2), /expected 2/);
  assert.deepEqual(plate_silhouette_lights(new Map([["a", true], ["b", false]]), ["b", "a", "c"]), ["a"]);
  assert.deepEqual(plate_silhouette_lights({ a: true, c: true }, ["a", "b", "c"]), ["a", "c"]);
});

test("unlit_union, split_form (shared drawables) and the core", () => {
  const [union, masks, core] = unlit_union([[true, false, false, true], [false, false, true, true], null]);
  assert.deepEqual(union, [0, 1, 2]);
  assert.deepEqual(masks, [[false, true, true], [true, true, false], [false, false, false]]);
  assert.deepEqual(core, [false, false, false]);
  const [u2, , c2] = unlit_union([[true, false, false, true], [false, false, true, true]]);
  assert.deepEqual(u2, [0, 1, 2]);
  assert.deepEqual(c2, [false, true, false]);
  assert.deepEqual(unlit_union([]), [[], [], []]);
  const faces = [["f0"], ["f1"], ["f2"]], polys = [[[0, 0]], [[1, 1]], [[2, 2]]];
  const [by_light, [cf, cp]] = split_form(faces, polys, [[false, true, true], [true, true, false]], [false, true, false], ["a", "b"]);
  assert.deepEqual([...by_light.keys()], ["a", "b"]);
  assert.equal(by_light.get("a")?.[1][0], polys[1]); // the same drawable object
  assert.deepEqual(cf, [["f1"]]);
  assert.equal(cp[0], polys[1]);
});

test("plate_form_lights: per-light flags and the core", () => {
  assert.deepEqual(plate_form_lights([-1.0, 2.0], [0.1, 0.1], 3.0, 0.1), [[true, false], false]);
  assert.deepEqual(plate_form_lights([-1.0, -2.0], [0.1, 0.1], 3.0, 0.1), [[true, true], true]);
  assert.deepEqual(plate_form_lights([-1.0, 0.05], [0.1, 0.1], 3.0, 0.1), [[true, false], true]); // parallel counts as unlit
  assert.deepEqual(plate_form_lights([-1.0, -2.0], [0.1, 0.1], 0.05, 0.1), [[false, false], false]); // camera side undecided
  assert.deepEqual(plate_form_lights([], [], 3.0, 0.1), [[], false]);
});

test("assemble_form_shadow: light-major entries, empty entries skipped, core per object", () => {
  const items = [
    { object: "o1", by_light: new Map([["a", { faces: [["x"]], polygons: [[[0, 0]]] }], ["b", { faces: [] }]]), core: { faces: [["x"]], polygons: [[[0, 0]]] } },
    { object: "o2", by_light: new Map([["a", { faces: [], terminator: [{ t: 1 }] }], ["b", { faces: [["y"]], polygons: [] }]]), core: null },
    { object: "o3", by_light: new Map(), core: { faces: [], polygons: [] } },
  ];
  const [form, core] = assemble_form_shadow(items, ["a", "b"]);
  assert.deepEqual(form.map((e) => [e.light, e.object]), [["a", "o1"], ["a", "o2"], ["b", "o2"]]);
  assert.deepEqual(form[1]?.terminator, [{ t: 1 }]);
  assert.deepEqual(core.map((c) => c.object), ["o1"]);
});

test("active_lights and umbra_entries (one entry per receiver, null when not computed)", () => {
  const sq = [[[0, 0], [1, 0], [1, 1], [0, 1]]], sh = [[[0.5, 0.5], [1.5, 0.5], [1.5, 1.5], [0.5, 1.5]]];
  const receivers = [{ id: "ground", lit: { a: true, b: true, c: false } }, { id: "wall", lit: { a: true, b: false, c: false } }];
  const shadows = [{ receiver: "ground", light: "a", polygons: sq }, { receiver: "ground", light: "b", polygons: sh },
    { receiver: "wall", light: "a", polygons: sq }];
  assert.deepEqual(active_lights(receivers[0] as any, ["c", "b", "a"]), ["b", "a"]);
  const out = umbra_entries(receivers, shadows, ["a", "b", "c"], [360, 240]);
  assert.deepEqual(out.map((e) => [e.receiver, e.lights, (e.polygons ?? []).length]), [["ground", ["a", "b"], 1], ["wall", ["a"], 0]]);
  assert.deepEqual(out[0]?.polygons, umbra_pieces([[sq], [sh]], [360, 240]));
  assert.deepEqual(umbra_entries(receivers, shadows, ["a", "b", "c"], [360, 240], false).map((e) => e.polygons), [null, null]);
});

// --- the acceptance case of §5.3.10 -------------------------------------------------------------------

const ACCEPTANCE = "multilight_two_point_symmetric_box";
const EXPECTED_PIECES = [
  [[0.0, -19.444444444444443], [25.753937681885635, -14.285714285714285], [-25.753937681885635, -14.285714285714285]],
  [[-25.753937681885635, -14.285714285714285], [25.753937681885635, -14.285714285714285], [22.944417207498113, 12.727272727272727],
    [-22.944417207498113, 12.727272727272727]],
  [[-22.944417207498113, 12.727272727272727], [22.944417207498113, 12.727272727272727], [0.0, 16.666666666666664]],
];
const EXPECTED_AREAS = [132.85761502560047, 1315.4880281807557, 90.38709809014404];
const WEST_DRAWABLE = [[-22.944417207498113, 12.727272727272727], [-25.753937681885635, -14.285714285714285],
  [54.86708462662592, -30.43478260869565], [164.60125387987776, -30.43478260869565], [130.54582204266168, 24.137931034482758],
  [43.51527401422056, 24.137931034482758]];

/** The name of a cube face from its vertices' world coordinates: `+x`, `-x`, `+y`, `-y`, `top`, `base`. */
function face_side(doc: any, face: string[]): string {
  const W = face.map((n) => doc.points[n].world as number[]);
  for (const [k, axis] of [[0, "x"], [1, "y"]] as [number, string][]) {
    if (W.every((w) => w[k] === 0.5)) return `+${axis}`;
    if (W.every((w) => w[k] === -0.5)) return `-${axis}`;
  }
  if (W.every((w) => w[2] === 1)) return "top";
  if (W.every((w) => w[2] === 0)) return "base";
  return "?";
}

test("acceptance (§5.3.10): the three umbra pieces, their areas and the total, hand values", () => {
  const doc = doc_of(case_scene(ACCEPTANCE));
  assert.deepEqual(doc.warnings, []);
  assert.equal(doc.umbra.length, 1);
  const entry = doc.umbra[0];
  assert.equal(entry.receiver, "ground");
  assert.deepEqual(entry.lights, ["west", "east"]);
  assert.equal(entry.polygons.length, 3);
  entry.polygons.forEach((piece: number[][], k: number) => {
    const expected = EXPECTED_PIECES[k] as number[][];
    assert.equal(piece.length, expected.length, `piece ${k}`);
    piece.forEach((p, j) => {
      assert.ok(Math.abs((p[0] as number) - (expected[j] as number[])[0]!) <= 1e-6, `piece ${k} vertex ${j} u`);
      assert.ok(Math.abs((p[1] as number) - (expected[j] as number[])[1]!) <= 1e-6, `piece ${k} vertex ${j} v`);
    });
    const a = EXPECTED_AREAS[k] as number;
    assert.ok(Math.abs(area(piece) - a) <= 1e-12 * a, `area of piece ${k}: ${area(piece)} vs ${a}`);
  });
  assert.ok(Math.abs(entry.polygons[2][2][0]) < 1e-13);
  const total = entry.polygons.reduce((s: number, p: number[][]) => s + area(p), 0);
  assert.ok(Math.abs(total - 1538.7327412965) <= 1e-6 * 1538.7327412965, String(total));
  assert.deepEqual(umbra_from_document(doc).map((e) => e.polygons), [entry.polygons]);
});

test("acceptance (§5.3.10): records, constructions, form shadow, core and silhouette lights", () => {
  const doc = doc_of(case_scene(ACCEPTANCE));
  assert.deepEqual(doc.shadows.map((s: any) => s.light), ["west", "east"]);
  const west = doc.shadows[0].polygons;
  assert.equal(west.length, 1);
  assert.equal(west[0].length, 6);
  west[0].forEach((p: number[], j: number) => {
    assert.ok(Math.abs(p[0]! - WEST_DRAWABLE[j]![0]!) <= 1e-6 && Math.abs(p[1]! - WEST_DRAWABLE[j]![1]!) <= 1e-6, `west vertex ${j}`);
  });
  assert.deepEqual(Object.keys(doc.constructions).sort(), ["east", "west"]);
  assert.deepEqual(doc.construction, doc.constructions.west);
  assert.deepEqual(doc.form_shadow.map((e: any) => [e.light, e.faces.map((f: string[]) => face_side(doc, f)).sort()]),
    [["west", ["+x", "+y", "-y", "base"]], ["east", ["+y", "-x", "-y", "base"]]]);
  assert.equal(doc.form_shadow_core.length, 1);
  assert.equal(doc.form_shadow_core[0].object, "cube");
  assert.deepEqual(doc.form_shadow_core[0].faces.map((f: string[]) => face_side(doc, f)).sort(), ["+y", "-y", "base"]);
  assert.equal(doc.edges.filter((e: any) => e.silhouette).length, 10);
  const lists = doc.edges.map((e: any) => e.silhouette_lights.join(","));
  const count = (s: string): number => lists.filter((x: string) => x === s).length;
  assert.deepEqual([count("west,east"), count("west"), count("east"), count("")], [2, 4, 4, 2]);
  for (const e of doc.edges) assert.equal(e.silhouette, e.silhouette_lights.length > 0);
});

test("per-light bit identity (§5.3.2): each light's records and construction equal its single-light document", () => {
  for (const name of [ACCEPTANCE, "multilight_point_and_directional_curved"]) {
    const raw = case_scene(name);
    const multi = doc_of(raw);
    const object_ids = raw.objects.map((o: any) => o.id);
    raw.lights.forEach((light: any) => {
      const single_raw = clone(raw);
      single_raw.lights = [clone(light)];
      const single = doc_of(single_raw);
      assert.ok(M6_KEYS.every((k) => !(k in single)), name);
      const map = (x: any): any => JSON.parse(JSON.stringify(x), (_k, v) => (typeof v === "string" ? multi_light_name(v, light.id, object_ids) : v));
      const recs = multi.shadows.filter((s: any) => s.light === light.id);
      assert.equal(dumps(recs), dumps(map(single.shadows)), `${name} ${light.id} shadows`);
      assert.equal(dumps(multi.constructions[light.id]), dumps(map(single.construction)), `${name} ${light.id} construction`);
      const form = multi.form_shadow.filter((e: any) => e.light === light.id).map((e: any) => ({ ...e, light: undefined }));
      assert.equal(dumps(JSON.parse(JSON.stringify(form))), dumps(map(single.form_shadow)), `${name} ${light.id} form_shadow`);
      for (const [nm, p] of Object.entries(single.points)) {
        const mapped = multi_light_name(nm, light.id, object_ids);
        assert.equal(dumps(multi.points[mapped]), dumps(p), `${name} ${light.id} point ${nm}`);
      }
    });
  }
});

// --- SVG (§5.3.6, §5.0.6) -------------------------------------------------------------------------------

test("acceptance SVG: per-light groups at 0.15 / 0.09, one umbra path with 3 subpaths, core, per-light construction", () => {
  const svg = svg_of(case_scene(ACCEPTANCE));
  const ids = g_ids(svg);
  for (const lid of ["east", "west"]) {
    assert.ok(g_tag(svg, `cast_shadow.${lid}`).includes('fill-opacity="0.15"'), lid);
    assert.ok(g_tag(svg, `form_shadow.${lid}`).includes('fill-opacity="0.09"'), lid);
    assert.equal((g_body(svg, `form_shadow.${lid}`).match(/<polygon/g) ?? []).length, 1, lid); // the +x / -x face only
    assert.ok(ids.includes(`construction.${lid}`), lid);
    assert.ok(ids.includes(`construction.${lid}.LP`) && ids.includes(`construction.${lid}.PQ`), lid);
  }
  assert.equal(g_tag(svg, "cast_shadow.umbra"), `<g id="cast_shadow.umbra" ${UMBRA_STYLE}>`);
  const umbra = g_body(svg, "cast_shadow.umbra");
  assert.equal((umbra.match(/<path/g) ?? []).length, 1);
  assert.equal((umbra.match(/M /g) ?? []).length, 3);
  assert.equal((umbra.match(/ Z/g) ?? []).length, 3);
  assert.equal(g_tag(svg, "form_shadow.core"), '<g id="form_shadow.core">');
  assert.equal((g_body(svg, "form_shadow.core").match(/<polygon/g) ?? []).length, 3);
  // order inside the layers (§5.0.6): light sub-groups in code-point order, then the umbra / core on top
  const at = (g: string): number => ids.indexOf(g);
  assert.ok(at("form_shadow.east") < at("form_shadow.west") && at("form_shadow.west") < at("form_shadow.core"));
  assert.ok(at("cast_shadow.east") < at("cast_shadow.west") && at("cast_shadow.west") < at("cast_shadow.umbra"));
  assert.ok(at("construction.east") < at("construction.west"));
  assert.ok(!ids.includes("construction.LP"));
});

test("N_act = 3: opacities 0.1 / 0.06 (§5.3.7)", () => {
  const raw = case_scene("multilight_three_lights_concave_prism");
  const doc = doc_of(raw);
  assert.equal(n_active(doc), 3);
  const svg = svg_of(raw);
  for (const lid of Object.keys(doc.constructions)) {
    assert.ok(g_tag(svg, `cast_shadow.${lid}`).includes('fill-opacity="0.1"'), lid);
    assert.ok(g_tag(svg, `form_shadow.${lid}`).includes('fill-opacity="0.06"'), lid);
  }
});

test("an inactive second light: umbra lights [first], polygons [], the active group at 0.3, an empty umbra group", () => {
  const raw = case_scene("multilight_second_light_inactive");
  const doc = doc_of(raw);
  assert.ok(doc.warnings.some((w: any) => w.code === "LIGHT_BELOW_RECEIVER"));
  const first = raw.lights[0].id;
  assert.deepEqual(doc.umbra, [{ receiver: "ground", lights: [first], polygons: [] }]);
  const svg = svg_of(raw);
  assert.ok(g_tag(svg, `cast_shadow.${first}`).includes('fill-opacity="0.3"'));
  assert.equal(g_tag(svg, "cast_shadow.umbra"), `<g id="cast_shadow.umbra" ${UMBRA_STYLE}/>`);
});

test("project_scene(umbra = false): polygons null, everything else identical; the writer draws no umbra path", () => {
  for (const name of [ACCEPTANCE, "multilight_point_and_directional_curved"]) {
    const scene = load_scene(case_scene(name));
    const A = shadow_geometry(scene);
    const on = JSON.parse(dumps(compose(scene, project_scene(scene, A))));
    const off_doc = compose(scene, project_scene(scene, A, undefined, false));
    const off = JSON.parse(dumps(off_doc));
    assert.ok(off.umbra.every((e: any) => e.polygons === null), name);
    assert.deepEqual(off.umbra.map((e: any) => e.lights), on.umbra.map((e: any) => e.lights));
    delete on.umbra;
    delete off.umbra;
    assert.equal(dumps(on), dumps(off), name);
    assert.equal(g_tag(write_svg(off_doc), "cast_shadow.umbra"), `<g id="cast_shadow.umbra" ${UMBRA_STYLE}/>`);
  }
});

test("hidden lines on in a two-light document: the hidden groups first, then the light groups, then core / umbra (§5.0.6)", () => {
  const raw = case_scene("multilight_point_and_directional_curved");
  raw.output = { ...(raw.output ?? {}), hidden_lines: true };
  const svg = svg_of(raw);
  const ids = g_ids(svg);
  const at = (g: string): number => ids.indexOf(g);
  assert.ok(at("form_shadow.hidden") >= 0 && at("form_shadow.hidden") < at("form_shadow.lamp"));
  assert.ok(at("form_shadow.lamp") < at("form_shadow.sun") && at("form_shadow.sun") < at("form_shadow.core"));
  assert.ok(at("cast_shadow.hidden") >= 0 && at("cast_shadow.hidden") < at("cast_shadow.lamp"));
  assert.ok(at("cast_shadow.sun") < at("cast_shadow.umbra"));
  assert.ok(g_tag(svg, "cast_shadow.lamp").includes('fill-opacity="0.15"'));
  assert.ok(!g_tag(svg, "cast_shadow.hidden").includes("fill-opacity"));
  // `form_shadow.hidden.<obj>` sub-groups are unique per object although several lights' terminators have hidden runs
  const hidden_sub = ids.filter((g) => g.startsWith("form_shadow.hidden."));
  assert.ok(hidden_sub.length > 0);
  assert.equal(new Set(hidden_sub).size, hidden_sub.length);
  const omit = render(load_scene(raw), null, null, "omit").svg;
  assert.ok(!g_body(omit, "form_shadow.hidden").includes("<line"));
});

test("single-light documents carry none of the M6 keys and no opacity override (examples, §5.3.5 / §5.3.6)", () => {
  for (const file of readdirSync(repo_path("examples")).filter((f) => f.endsWith(".json")).sort()) {
    const raw = read_example(file);
    if (raw.lights.length !== 1) continue;
    const r = render(load_scene(raw));
    const doc = JSON.parse(dumps(r.geometry));
    assert.ok(M6_KEYS.every((k) => !(k in doc)), file);
    assert.ok(doc.form_shadow.every((e: any) => !("light" in e)), file);
    assert.ok(doc.edges.every((e: any) => !("silhouette_lights" in e)), file);
    const ids = g_ids(r.svg);
    assert.ok(!ids.includes("cast_shadow.umbra") && !ids.includes("form_shadow.core"), file);
    for (const g of ids.filter((x) => /^(cast_shadow|form_shadow)\./.test(x))) assert.ok(!g_tag(r.svg, g).includes("opacity"), `${file} ${g}`);
  }
});

test("examples/two_lights.json: the umbra, the core and the per-light groups (examples/README.md)", () => {
  const r = render(load_scene(read_example("two_lights.json")));
  const doc = JSON.parse(dumps(r.geometry));
  assert.deepEqual(doc.warnings, []);
  assert.deepEqual(Object.keys(doc.constructions).sort(), ["left", "right"]);
  assert.equal(doc.umbra.length, 1);
  assert.deepEqual(doc.umbra[0].lights, ["left", "right"]);
  assert.equal(doc.umbra[0].polygons.length, 118);
  assert.deepEqual(doc.form_shadow_core.map((c: any) => [c.object, c.faces.length]), [["crate", 3]]);
  assert.ok("ball.sil.0.left" in doc.points && "pillar.g0.base.right" in doc.points);
  assert.ok(g_tag(r.svg, "cast_shadow.left").includes('fill-opacity="0.15"'));
  assert.ok(g_tag(r.svg, "form_shadow.left").includes('fill-opacity="0.09"'));
  assert.equal((g_body(r.svg, "cast_shadow.umbra").match(/<path/g) ?? []).length, 1);
});

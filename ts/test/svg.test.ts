/** The SVG writer of the port (contract §5.4.6, §5.4.13): the `fmt` table incl. ties and negatives, `fmt` against an
 * exact round-half-even reference on 10^5 values, and the structure of `write_svg` for two examples. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { dumps } from "../src/output/geometry_json.js";
import { LAYER_ORDER, STYLE, fmt, write_svg } from "../src/output/svg.js";
import { render } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { read_example, read_json, repo_path } from "./helpers.js";

test("fmt table (contract §5.4.6)", () => {
  const table: [number, string][] = [
    [0.03125, "0.0312"], [0.09375, "0.0938"], [-0.03125, "-0.0312"], [-0.00004, "0"], [12.5, "12.5"], [1e-5, "0"],
    [123.45678, "123.4568"], [1e21, "1000000000000000000000"], [0, "0"], [-0, "0"], [1, "1"], [-1.5, "-1.5"],
    [0.15625, "0.1562"], [0.46875, "0.4688"], [-0.46875, "-0.4688"], [2.00005, "2"], [273, "273"], [0.00005, "0.0001"],
    [-0.00005, "-0.0001"], [1e300, BigInt(1e300).toString()], [136.5, "136.5"],
  ];
  for (const [x, s] of table) assert.equal(fmt(x), s, String(x));
});

/** `"%.4f"` of the exact binary value with round-half-even, trailing zeros / dot stripped, `-0` -> `0`. */
function exact_fmt(x: number): string {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const bits = view.getBigUint64(0);
  const neg = bits >> 63n === 1n;
  const e = Number((bits >> 52n) & 0x7ffn);
  let mant = bits & 0xfffffffffffffn;
  let exp: number;
  if (e === 0) exp = -1074;
  else {
    mant |= 1n << 52n;
    exp = e - 1075;
  }
  let q: bigint;
  if (exp >= 0) q = mant * 10000n * (1n << BigInt(exp));
  else {
    const N = mant * 10000n, D = 1n << BigInt(-exp);
    q = N / D;
    const r2 = (N % D) * 2n;
    if (r2 > D || (r2 === D && q % 2n === 1n)) q += 1n;
  }
  let s = (neg ? "-" : "") + (q / 10000n).toString() + "." + (q % 10000n).toString().padStart(4, "0");
  s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "-0" || s === "" ? "0" : s;
}

test("fmt equals the exact round-half-even reference on 10^5 values incl. every tie class", () => {
  let seed = 987654321;
  const rnd = (): number => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  for (let i = 0; i < 100000; i++) {
    let x: number;
    const kind = i % 4;
    if (kind === 0) x = (rnd() - 0.5) * Math.pow(10, Math.floor(rnd() * 12) - 4);          // general magnitudes
    else if (kind === 1) x = (Math.floor(rnd() * 2 ** 20) * 2 + 1) / 32 * (rnd() < 0.5 ? -1 : 1);  // exact ties j/32, j odd
    else if (kind === 2) x = (Math.floor((rnd() - 0.5) * 2e7) + 0.5) / 1e4;                 // near-ties (not exact)
    else x = (rnd() - 0.5) * 600;                                                            // typical canvas mm
    assert.equal(fmt(x), exact_fmt(x), String(x));
  }
  for (const x of [2 ** 47 + 0.03125, -(2 ** 47) - 0.09375, 5e-324, 1.7976931348623157e308]) assert.equal(fmt(x), exact_fmt(x), String(x));
});

function doc_of(name: string): any {
  return render(load_scene(read_json(repo_path("examples", `${name}.json`)))).geometry;
}

function group_ids(svg: string): string[] {
  return [...svg.matchAll(/<g id="([^"]*)"/g)].map((m) => m[1] as string);
}

test("write_svg structure: example_basic", () => {
  const doc = doc_of("basic");
  const svg = write_svg(doc);
  const lines = svg.split("\n");
  assert.equal(lines[0], '<?xml version="1.0" encoding="UTF-8"?>');
  assert.equal(lines[1], `<svg xmlns="http://www.w3.org/2000/svg" width="${fmt(doc.canvas_mm[0])}mm" height="${fmt(doc.canvas_mm[1])}mm" viewBox="0 0 ${fmt(doc.canvas_mm[0])} ${fmt(doc.canvas_mm[1])}">`);
  assert.ok(svg.endsWith("</svg>\n"));
  const top = group_ids(svg).filter((id) => (LAYER_ORDER as readonly string[]).includes(id));
  assert.deepEqual(top, [...LAYER_ORDER]);
  assert.ok(svg.includes(`<g id="horizon" ${STYLE["horizon"]}>`));
  // one <line> per drawn edge in the objects layer
  const objects = svg.slice(svg.indexOf('<g id="objects"'), svg.indexOf('<g id="form_shadow"'));
  const drawn = doc.edges.filter((e: any) => e.segment !== null).length;
  const gens = doc.outlines.reduce((n: number, o: any) => n + o.generators.filter((g: any) => g.segment !== null).length, 0);
  assert.equal((objects.match(/<line /g) ?? []).length, drawn + gens);
  for (const oid of new Set(doc.edges.map((e: any) => e.object))) assert.ok(group_ids(svg).includes(`objects.${oid}`));
  // one <path> per shadow with polygons in the cast_shadow layer
  const cast = svg.slice(svg.indexOf('<g id="cast_shadow"'), svg.indexOf('<g id="construction"'));
  assert.equal(cast.split("\n").filter((l) => l.startsWith('<path d="M ') && l.endsWith(' Z"/>')).length, doc.shadows.filter((s: any) => s.polygons.length > 0).length);
  // construction rays grouped by kind
  const con = svg.slice(svg.indexOf('<g id="construction"'), svg.indexOf('<g id="labels"'));
  assert.equal((con.match(/<line /g) ?? []).length, doc.construction.segments.length);
  for (const kind of new Set(doc.construction.segments.map((s: any) => s.kind))) assert.ok(con.includes(`<g id="construction.${kind}"`));
});

test("write_svg structure: example_curved_demo (conic drawables, sub-groups)", () => {
  const doc = doc_of("curved_demo");
  const svg = write_svg(doc);
  const ids = group_ids(svg);
  for (const o of doc.outlines) assert.ok(ids.includes(`objects.${o.object}`));
  for (const f of doc.form_shadow) {
    assert.ok(ids.includes(`form_shadow.${f.object}`));
    if (f.terminator.length > 0) assert.ok(ids.includes(`form_shadow.${f.object}.terminator`));
  }
  for (const s of doc.shadows) {
    const n = s.conics.reduce((k: number, c: any) => k + c.polylines.filter((p: any) => p.length >= 2).length + c.arcs.length + c.ellipses.length, 0);
    if (n > 0) assert.ok(ids.includes(`cast_shadow.${s.light}.${s.object}.conics`));
  }
  const arcs = [...doc.shadows, ...doc.outlines].flatMap((x: any) => x.conics).reduce((k: number, c: any) => k + c.arcs.length, 0)
    + doc.form_shadow.flatMap((f: any) => f.terminator).reduce((k: number, t: any) => k + (t.arcs?.length ?? 0), 0);
  assert.equal((svg.match(/<path d="M [^"]* A /g) ?? []).length, arcs);
  const ellipses = [...doc.shadows, ...doc.outlines].flatMap((x: any) => x.conics).reduce((k: number, c: any) => k + c.ellipses.length, 0)
    + doc.form_shadow.flatMap((f: any) => f.terminator).reduce((k: number, t: any) => k + (t.ellipses?.length ?? 0), 0);
  assert.equal((svg.match(/<ellipse /g) ?? []).length, ellipses);
  assert.ok(ellipses > 0 && arcs > 0);
});

test("write_svg layer subsets, empty layers and unknown ids", () => {
  const doc = doc_of("basic");
  const sub = write_svg(doc, ["labels", "horizon"]);
  assert.deepEqual(group_ids(sub).filter((id) => (LAYER_ORDER as readonly string[]).includes(id)), ["horizon", "labels"]);
  assert.throws(() => write_svg(doc, ["horizon", "shadows"]), /unknown SVG layer\(s\): shadows/);
  const empty = write_svg({ ...doc, edges: [], outlines: [], shadows: [], form_shadow: [], construction: { segments: [] }, points: {} });
  assert.ok(empty.includes('<g id="objects"/>'));
  assert.ok(empty.includes(`<g id="form_shadow" ${STYLE["form_shadow"]}/>`));
  assert.ok(empty.includes(`<g id="labels" ${STYLE["labels"]}/>`));
});

function bold_and_plain_x(svg: string, oid: string, label: string): [string, string] {
  const bold = new RegExp(`<text x="([^"]+)" y="[^"]+" font-weight="bold">${oid}</text>`).exec(svg);
  const plain = new RegExp(`<text x="([^"]+)" y="[^"]+">${label}</text>`).exec(svg);
  assert.ok(bold !== null && plain !== null);
  return [bold[1] as string, plain[1] as string];
}

test("object-id label anchor: the strict `z > best` of svg.py is kept verbatim (contract §5.4.4 (7))", () => {
  const doc = structuredClone(doc_of("basic"));
  const top = doc.points["crate.v7"].world as number[];
  const z = top[2] as number;
  let [bold, v4] = bold_and_plain_x(write_svg(doc), "crate", "v4");
  assert.equal(bold, v4);                                   // equal heights: the first name in code-point order (v4)
  const up = z + z * Number.EPSILON;                        // the next double above z (z = 0.6 is in [0.5, 1))
  assert.ok(up > z);
  doc.points["crate.v7"].world = [top[0], top[1], up];
  const [bold2, v7] = bold_and_plain_x(write_svg(doc), "crate", "v7");
  assert.equal(bold2, v7);                                  // one ulp higher wins, exactly as the Python writer
  assert.notEqual(v7, v4);
});

test("a sphere off the camera axis: the outline ellipse matches the Python reference (M7 review)", () => {
  // the on-axis sphere is an exact circle, i.e. on the `s1 >= s2` boundary; the case is moved off it (§5.4.4 (7))
  const scene = load_scene({
    version: "0.1", units: "m", up: "z",
    objects: [{ id: "s0", type: "sphere", radius: 0.5, transform: { position: [0.4, 0.3, 0] } }],
    lights: [{ id: "lamp", type: "point", position: [0, 0, 4] }],
    receivers: [{ id: "ground", type: "plane", normal: [0, 0, 1], offset: 0 }],
    camera: { position: [4, -8, 5], target: [0, 0, 0.5], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [360, 240] },
  });
  const out = render(scene);
  const ell = (out.geometry as any).outlines[0].conics[0].ellipses[0];
  assert.ok(Math.abs(ell.rotation_deg - 4.671607872309661) <= 1e-9);
  assert.ok(Math.abs(ell.rx - 17.381912899640614) <= 1e-9 && Math.abs(ell.ry - 17.361112474632982) <= 1e-9);
  assert.ok(out.svg.includes('<ellipse cx="197.1021" cy="118.6025" rx="17.3819" ry="17.3611" transform="rotate(-4.6716 197.1021 118.6025)"/>'));
});

// --- review fix m6-umbra#1: light ids `shadow` / `foot` keep their labels (names parsed from the right) ----------------

function label_texts(scene: any): string[] {
  const doc = render(load_scene(scene)).geometry;
  return [...write_svg(doc, ["labels"]).matchAll(/>([^<]*)<\/text>/g)].map((m) => m[1] as string).sort();
}

function wall_two_lights(): any {
  const s = read_example("wall_and_ground.json");
  const extra = JSON.parse(JSON.stringify(s.lights[0]));
  extra.id = "second";
  extra.position = extra.position.map((p: number, k: number) => p + ([0.7, -0.4, 0.3][k] as number));
  s.lights.push(extra);
  return s;
}

const LABEL_BASES: Record<string, () => any> = {
  curved: () => read_json(repo_path("tests", "conformance", "cases", "multilight_point_and_directional_curved.json")),
  basic: () => read_example("basic.json"),
  wall: () => read_example("wall_and_ground.json"),
  wall2: wall_two_lights,
};

for (const [make, base] of Object.entries(LABEL_BASES)) {
  for (const reserved of ["shadow", "foot"]) {
    test(`light id '${reserved}' keeps its labels (${make}; §5.0.4 / §5.3.11)`, () => {
      const labels = (lid: string): string[] => {
        const s = base();
        s.lights[0].id = lid;
        return label_texts(s);
      };
      const plain = labels("lampA");
      assert.ok(plain.some((t) => t.includes("lampA")));
      assert.deepEqual(labels(reserved), plain.map((t) => t.split("lampA").join(reserved)).sort());
    });
  }
}

// --- review fix m4-hidden#0: the construction layer follows receivers[] order, not per_receiver key order ------------

function wall_and_panel(n_lights: number): any {
  const s = read_example("wall_and_ground.json");
  s.receivers.push({ id: "panel", type: "plane", normal: [0, -1, 0], offset: 3.5,
    bounds: [[1.0, 3.5, 0.0], [2.5, 3.5, 0.0], [2.5, 3.5, 1.0], [1.0, 3.5, 1.0]] });
  if (n_lights === 2) {
    const extra = JSON.parse(JSON.stringify(s.lights[0]));
    extra.id = "zz_second";
    extra.position = extra.position.map((p: number, k: number) => p + ([0.9, -0.6, 0.4][k] as number));
    s.lights.push(extra);
  }
  return s;
}

for (const hidden of [false, true]) {
  for (const n_lights of [1, 2]) {
    test(`the construction layer is independent of the per_receiver key order (hidden=${hidden}, lights=${n_lights})`, () => {
      const scene = wall_and_panel(n_lights);
      assert.deepEqual(scene.receivers.slice(1).map((r: any) => r.id), ["wall", "panel"]);
      const doc = render(load_scene(scene), null, hidden).geometry;
      const direct = write_svg(doc);
      assert.ok(direct.includes("F′wall") && direct.includes("F′panel"));
      assert.ok(direct.indexOf("F′wall") < direct.indexOf("F′panel"));
      assert.equal(write_svg(JSON.parse(dumps(doc))), direct);
    });
  }
}

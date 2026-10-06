/** The SVG writer of the port (contract §5.4.6, §5.4.13): the `fmt` table incl. ties and negatives, `fmt` against an
 * exact round-half-even reference on 10^5 values, and the structure of `write_svg` for two examples. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { LAYER_ORDER, STYLE, fmt, write_svg } from "../src/output/svg.js";
import { render } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { read_json, repo_path } from "./helpers.js";

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

/**
 * Conformance runner of the port (spec §7.5, contract §5.4.8, `tests/conformance/README.md` rule 3).
 *
 * Reads `tests/conformance/cases`, `expected` and `rules.json` directly from the repository (no copy under ts/),
 * renders every case through the port, round-trips the document through the writer and compares it with the
 * literal port of `tests/test_conformance.py::compare_documents` (rules from `rules.json`, incl. `case_overrides`).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { cmp_code_points, dumps } from "../src/output/geometry_json.js";
import { render } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { json_stems, read_json, repo_path } from "./helpers.js";

const CONFORMANCE = repo_path("tests", "conformance");
const CASES = `${CONFORMANCE}/cases`;
const EXPECTED = `${CONFORMANCE}/expected`;

export interface Rules {
  image_tol_mm: number;
  rel_tol: number;
  mm_keys: string[];
  drawable_containers: string[];
  arc_non_mm: string[];
  mm_key_paths: string[][];
  int_keys: string[];
  max_reported: number;
  case_overrides: Record<string, { paths: string[][]; abs_tol: number; reason: string }[]>;
  runs_rule?: unknown;
}

export const RULES: Rules = read_json(`${CONFORMANCE}/rules.json`);

type Key = string | number;

export function path_has_prefix(path: readonly Key[], pattern: readonly string[]): boolean {
  if (path.length < pattern.length) return false;
  return pattern.every((p, i) => p === "*" || p === path[i]);
}

export function is_image_path(path: readonly Key[], rules: Rules = RULES): boolean {
  let in_drawable = false;
  for (const key of path) {
    if (typeof key === "string" && rules.mm_keys.includes(key)) return true;
    if (typeof key === "string" && rules.drawable_containers.includes(key)) in_drawable = true;
    else if (in_drawable && typeof key === "string" && rules.arc_non_mm.includes(key)) return false;
  }
  if (in_drawable) return true;
  return rules.mm_key_paths.some((pattern) => path_has_prefix(path, pattern));
}

type Override = [string[][], number];

export function case_overrides(case_name: string | null, rules: Rules = RULES): Override[] {
  if (case_name === null) return [];
  return (rules.case_overrides[case_name] ?? []).map((e) => [e.paths, e.abs_tol] as Override);
}

function override_tol(path: readonly Key[], overrides: readonly Override[]): number | null {
  for (const [paths, abs_tol] of overrides) if (paths.some((p) => path_has_prefix(path, p))) return abs_tol;
  return null;
}

function fmt_path(path: readonly Key[]): string {
  let out = "";
  for (const key of path) out += typeof key === "number" ? `[${key}]` : out ? `.${key}` : key;
  return out || "<root>";
}

/** Python `repr` of a JSON value for messages. */
function r(x: unknown): string {
  if (typeof x === "string") return `'${x}'`;
  if (x === null) return "None";
  if (x === true) return "True";
  if (x === false) return "False";
  return JSON.stringify(x);
}

function g(x: number): string {
  return String(x).replace(/e-(\d)$/, "e-0$1");
}

function numbers_match(a: number, b: number, image: boolean, abs_tol: number | null, rules: Rules): boolean {
  if (!(Number.isFinite(a) && Number.isFinite(b))) return a === b;
  if (abs_tol !== null) return Math.abs(a - b) <= abs_tol;
  if (image) return Math.abs(a - b) <= rules.image_tol_mm;
  return Math.abs(a - b) <= rules.rel_tol * Math.max(1.0, Math.abs(a), Math.abs(b));
}

function is_obj(x: unknown): x is Record<string, unknown> {
  return typeof x === "object" && x !== null && !Array.isArray(x);
}

function walk(exp: unknown, act: unknown, path: Key[], out: string[], overrides: readonly Override[], rules: Rules): void {
  if (out.length > rules.max_reported) return;
  if (typeof exp === "number" && typeof act === "number") {
    const image = is_image_path(path, rules);
    const abs_tol = overrides.length > 0 ? override_tol(path, overrides) : null;
    if (!numbers_match(exp, act, image, abs_tol, rules)) {
      const tol = abs_tol !== null ? `${g(abs_tol)} absolute, case override` : image ? `${g(rules.image_tol_mm)} mm` : `${g(rules.rel_tol)} relative`;
      out.push(`${fmt_path(path)}: expected ${exp}, got ${act} (tolerance ${tol})`);
    }
    return;
  }
  if (is_obj(exp) && is_obj(act)) {
    const ek = Object.keys(exp), ak = Object.keys(act);
    const missing = ek.filter((k) => !(k in act)).sort(cmp_code_points);
    const extra = ak.filter((k) => !(k in exp)).sort(cmp_code_points);
    if (missing.length > 0 || extra.length > 0) {
      out.push(`${fmt_path(path)}: key mismatch (missing ${r(missing)}, unexpected ${r(extra)})`);
      return;
    }
    for (const key of ek.sort(cmp_code_points)) walk(exp[key], act[key], [...path, key], out, overrides, rules);
    return;
  }
  if (Array.isArray(exp) && Array.isArray(act)) {
    if (exp.length !== act.length) {
      out.push(`${fmt_path(path)}: expected a list of ${exp.length} entries, got ${act.length}`);
      return;
    }
    exp.forEach((e, i) => walk(e, act[i], [...path, i], out, overrides, rules));
    return;
  }
  if (typeof exp !== typeof act || Array.isArray(exp) !== Array.isArray(act) || exp !== act) {
    out.push(`${fmt_path(path)}: expected ${r(exp)}, got ${r(act)} (exact)`);
  }
}

interface W {
  code: string;
  ids: string[];
}

/** Mismatches between two JSON-native §6.2 documents (empty = conformant); the literal port of the Python comparator. */
export function compare_documents(expected: any, actual: any, case_name: string | null = null, rules: Rules = RULES): string[] {
  const out: string[] = [];
  const exp_w: W[] = expected.warnings ?? [], act_w: W[] = actual.warnings ?? [];
  const exp_codes = new Set(exp_w.map((w) => w.code)), act_codes = new Set(act_w.map((w) => w.code));
  const missing_codes = [...exp_codes].filter((c) => !act_codes.has(c)).sort(cmp_code_points);
  const extra_codes = [...act_codes].filter((c) => !exp_codes.has(c)).sort(cmp_code_points);
  if (missing_codes.length > 0 || extra_codes.length > 0) {
    out.push(`warnings: code set mismatch (missing ${r(missing_codes)}, unexpected ${r(extra_codes)})`);
  }
  const key = (w: W): string => JSON.stringify([w.code, w.ids]);
  const exp_ids = new Set(exp_w.map(key)), act_ids = new Set(act_w.map(key));
  const missing_ids = [...exp_ids].filter((k) => !act_ids.has(k)).sort(cmp_code_points);
  const extra_ids = [...act_ids].filter((k) => !exp_ids.has(k)).sort(cmp_code_points);
  if (missing_ids.length > 0 || extra_ids.length > 0) {
    out.push(`warnings: (code, ids) set mismatch (missing [${missing_ids.join(", ")}], unexpected [${extra_ids.join(", ")}])`);
  }
  const rest = (d: Record<string, unknown>): Record<string, unknown> => {
    const o: Record<string, unknown> = {};
    for (const k of Object.keys(d)) if (k !== "warnings") o[k] = d[k];
    return o;
  };
  walk(rest(expected), rest(actual), [], out, case_overrides(case_name, rules), rules);
  return out;
}

export function case_names(): string[] {
  return json_stems(CASES).sort(cmp_code_points);
}

/** The JSON-native document of a case through the port, round-tripped through the writer. */
export function render_case(name: string): any {
  const scene = load_scene(read_json(`${CASES}/${name}.json`));
  return JSON.parse(dumps(render(scene).geometry));
}

export function load_expected(name: string): any {
  return read_json(`${EXPECTED}/${name}.json`);
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x));
}

// --------------------------------------------------------------------------- the set itself
test("cases/ and expected/ correspond one to one, are non-empty, and every case loads", () => {
  const names = case_names();
  assert.ok(names.length >= 34, `only ${names.length} cases`);
  assert.deepEqual(json_stems(EXPECTED).sort(cmp_code_points), names);
  for (const name of names) {
    const data = read_json(`${CASES}/${name}.json`);
    assert.ok(typeof data.description === "string" && data.description.trim(), name);
    load_scene(data);
  }
});

for (const name of case_names()) {
  test(`conformance: ${name}`, () => {
    const mismatches = compare_documents(load_expected(name), render_case(name), name);
    if (mismatches.length > 0) {
      const shown = mismatches.slice(0, RULES.max_reported);
      const more = mismatches.length > RULES.max_reported ? `\n... (${mismatches.length - RULES.max_reported} more)` : "";
      assert.fail(`conformance case '${name}' (${mismatches.length} mismatch(es)):\n  ${shown.join("\n  ")}${more}`);
    }
  });
}

// --------------------------------------------------------------------------- the comparator is not vacuous
test("comparator detects drift of each kind (ported from test_comparator_detects_drift_of_each_kind)", () => {
  const doc = load_expected("example_basic");
  assert.deepEqual(compare_documents(doc, clone(doc)), []);
  let bad = clone(doc);
  bad.points["crate.v0"].image[0] += 2e-6;
  assert.ok(compare_documents(doc, bad).some((m) => m.startsWith("points.crate.v0.image[0]")));
  const ok = clone(doc);
  ok.points["crate.v0"].image[0] += 5e-7;
  ok.shadows[0].polygons[0][0][1] -= 5e-7;
  assert.deepEqual(compare_documents(doc, ok), []);
  bad = clone(doc);
  bad.points["crate.v0"].world[2] += 1e-7;
  assert.ok(compare_documents(doc, bad).some((m) => m.startsWith("points.crate.v0.world[2]")));
  bad = clone(doc);
  bad.edges[0].back = !bad.edges[0].back;
  bad.shadows[0].outline.pop();
  const msgs = compare_documents(doc, bad);
  assert.ok(msgs.some((m) => m.startsWith("edges[0].back")) && msgs.some((m) => m.startsWith("shadows[0].outline")));
  bad = clone(doc);
  bad.warnings.push({ code: "CONIC_SAMPLED", ids: ["pillar"], message: "x" });
  assert.ok(compare_documents(doc, bad).some((m) => m.startsWith("warnings: code set")));
  const same = clone(doc);
  same.canvas_mm = [273, 182];
  assert.deepEqual(compare_documents(doc, same), []);
  bad = clone(doc);
  bad.edges[0].silhouette = 0;
  assert.ok(compare_documents(doc, bad).some((m) => m.startsWith("edges[0].silhouette")), "booleans are not numbers");
});

test("image path classification (ported from test_image_path_classification)", () => {
  assert.ok(is_image_path(["points", "a.v0", "image", 0]));
  assert.ok(is_image_path(["edges", 3, "segment", 1, 0]));
  assert.ok(is_image_path(["outlines", 0, "conics", 1, "arcs", 0, "start", 1]));
  assert.ok(is_image_path(["outlines", 0, "conics", 1, "ellipses", 0, "rx"]));
  assert.ok(!is_image_path(["outlines", 0, "conics", 1, "arcs", 0, "rotation_deg"]));
  assert.ok(!is_image_path(["outlines", 0, "conics", 1, "arcs", 0, "theta", 0]));
  assert.ok(!is_image_path(["outlines", 0, "conics", 1, "circle", "centre", 0]));
  assert.ok(!is_image_path(["shadows", 0, "conics", 1, "conic", 0, 0]));
  assert.ok(is_image_path(["construction", "segments", 4, "points", 0, 1]));
  assert.ok(!is_image_path(["construction", "checks", 0, "point"]));
  assert.ok(is_image_path(["construction", "checks", 0, "max_error_mm"]));
  assert.ok(!is_image_path(["points", "a.v0", "world", 0]) && !is_image_path(["points", "a.v0", "depth"]));
  assert.ok(!is_image_path(["camera", "P", 0, 0]) && is_image_path(["camera", "principal_point", 0]));
  assert.ok(!is_image_path(["horizon", "line", 0]) && is_image_path(["horizon", "segment", 0, 0]));
});

test("case_overrides apply only to the named case and the named paths (contract §5.4.13)", () => {
  const name = "degenerate_cylinder_cap_at_light_height";
  assert.deepEqual(Object.keys(RULES.case_overrides), [name]);
  const doc = load_expected(name);
  const drift = clone(doc);
  drift.shadows[0].loops[0][30].direction[1] += 1.5e-9;
  drift.shadows[0].outline[30].direction[1] += 1.5e-9;
  drift.shadows[0].loops[0][31].direction[1] -= 4e-7;
  drift.shadows[0].outline[31].direction[1] -= 4e-7;
  assert.deepEqual(compare_documents(doc, drift, name), []);
  const msgs = compare_documents(doc, drift);
  assert.equal(msgs.length, 4);
  assert.ok(msgs.every((m) => m.includes("1e-09 relative")), msgs.join("\n"));
  assert.equal(compare_documents(doc, drift, "example_basic").length, 4);
  let bad = clone(doc);
  bad.shadows[0].outline[30].direction[0] += 2e-6;
  const one = compare_documents(doc, bad, name);
  assert.equal(one.length, 1);
  assert.ok((one[0] as string).startsWith("shadows[0].outline[30].direction[0]") && (one[0] as string).includes("case override"));
  bad = clone(doc);
  bad.shadows[0].polygons[0][0][0] += 2e-6;
  const first = Object.keys(bad.points)[0] as string;
  bad.points[first].world[0] += 1e-7;
  assert.equal(compare_documents(doc, bad, name).length, 2);
  bad = clone(doc);
  bad.shadows[0].loops[0][30].direction.push(0.0);
  assert.notDeepEqual(compare_documents(doc, bad, name), []);
  // the same leaf position in another case with a direction vertex uses 1e-9 relative
  let checked = false;
  for (const other of case_names()) {
    if (other === name) continue;
    const odoc = load_expected(other);
    let hit: [number, number, number] | null = null;
    odoc.shadows.forEach((sh: any, i: number) => sh.loops.forEach((loop: any[], j: number) => loop.forEach((e: any, k: number) => {
      if (hit === null && typeof e === "object" && e !== null && "direction" in e) hit = [i, j, k];
    })));
    const found = hit as [number, number, number] | null;
    if (found === null) continue;
    const [i, j, k] = found;
    const moved = clone(odoc);
    moved.shadows[i].loops[j][k].direction[0] += 1e-7;
    assert.notDeepEqual(compare_documents(odoc, moved, other), []);
    assert.deepEqual(compare_documents(odoc, moved, name), []);
    checked = true;
    break;
  }
  assert.ok(checked, "no other case with a direction vertex");
});

test("rules.json carries the v3 comparator constants", () => {
  assert.equal(RULES.image_tol_mm, 1e-6);
  assert.equal(RULES.rel_tol, 1e-9);
  assert.deepEqual(RULES.drawable_containers, ["arcs", "ellipses"]);
  assert.deepEqual(RULES.int_keys, ["large_arc", "sweep"]);
  assert.ok(path_has_prefix(["construction", "segments", 4, "points", 0, 1], ["construction", "segments", "*", "points"]));
  assert.ok(!path_has_prefix(["construction", "segments", 4], ["construction", "segments", "*", "points"]));
  assert.deepEqual(case_overrides(null), []);
  assert.deepEqual(case_overrides("example_basic"), []);
});

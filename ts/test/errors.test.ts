/** `WARNING_CODES` of the port equals the literal of `castplane/errors.py` (contract §5.4.13, §5.4.14 (e)). */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SceneError, WARNING_CODES, make_warning, merge_warnings, warning_codes } from "../src/errors.js";
import { repo_path, read_text } from "./helpers.js";

function python_warning_codes(): [string, string][] {
  const text = read_text(repo_path("castplane", "errors.py"));
  const start = text.indexOf("WARNING_CODES = {");
  assert.ok(start >= 0, "no WARNING_CODES literal in castplane/errors.py");
  const body = text.slice(start, text.indexOf("\n}", start));
  const out: [string, string][] = [];
  for (const m of body.matchAll(/^\s*"([A-Z_]+)":\s*"((?:[^"\\]|\\.)*)",?\s*$/gm)) out.push([m[1] as string, m[2] as string]);
  return out;
}

test("WARNING_CODES equals the Python literal (codes, order and default messages)", () => {
  const py = python_warning_codes();
  assert.equal(py.length, 18);
  assert.deepEqual(Object.entries(WARNING_CODES), py);
});

test("make_warning / merge_warnings / warning_codes", () => {
  assert.deepEqual(make_warning("CONIC_SAMPLED", ["b"]), {
    code: "CONIC_SAMPLED", ids: ["b"], message: WARNING_CODES["CONIC_SAMPLED"],
  });
  assert.equal(make_warning("CONIC_SAMPLED", [], "x").message, "x");
  assert.throws(() => make_warning("NO_SUCH_CODE"));
  const merged = merge_warnings(
    [make_warning("POINT_BEHIND_CAMERA", ["b"]), make_warning("CONIC_SAMPLED", ["a", "b"])],
    [make_warning("CONIC_SAMPLED", ["a"]), make_warning("POINT_BEHIND_CAMERA", ["b"], "dup"), make_warning("CONIC_SAMPLED", [])],
  );
  assert.deepEqual(merged.map((w) => [w.code, w.ids]), [
    ["CONIC_SAMPLED", []], ["CONIC_SAMPLED", ["a"]], ["CONIC_SAMPLED", ["a", "b"]], ["POINT_BEHIND_CAMERA", ["b"]],
  ]);
  assert.equal(merged[3]?.message, WARNING_CODES["POINT_BEHIND_CAMERA"]);
  assert.deepEqual(warning_codes(merged), new Set(["CONIC_SAMPLED", "POINT_BEHIND_CAMERA"]));
});

test("SceneError carries field, detail and the Python str()", () => {
  const e = new SceneError("objects[1].size", "must be > 0");
  assert.ok(e instanceof Error);
  assert.equal(e.field, "objects[1].size");
  assert.equal(e.detail, "must be > 0");
  assert.equal(e.message, "objects[1].size: must be > 0");
});

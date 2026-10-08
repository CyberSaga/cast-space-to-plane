/** The canonical JSON writer (contract §5.4.5): parity with every expected file, the `py_repr` table,
 * `cmp_code_points`, `INT_KEYS`, `-0` canonicalisation and non-finite numbers. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { INT_KEYS, canonical, cmp_code_points, dumps, py_repr } from "../src/output/geometry_json.js";
import { json_stems, read_json, read_text, repo_path } from "./helpers.js";

test("parity: dumps(JSON.parse(text)) + newline === text for every expected file", () => {
  const dir = repo_path("tests", "conformance", "expected");
  const names = json_stems(dir);
  assert.ok(names.length >= 34);
  let bytes = 0;
  for (const name of names) {
    const text = read_text(`${dir}/${name}.json`);
    bytes += text.length;
    const out = dumps(JSON.parse(text)) + "\n";
    if (out !== text) {
      let i = 0;
      while (i < out.length && out[i] === text[i]) i++;
      assert.fail(`${name}: writer differs at offset ${i}: expected ${JSON.stringify(text.slice(i - 40, i + 40))}, `
        + `got ${JSON.stringify(out.slice(i - 40, i + 40))}`);
    }
  }
  assert.ok(bytes > 500_000);
});

test("py_repr table (contract §5.4.5)", () => {
  const table: [number, string][] = [
    [1, "1.0"], [0.5, "0.5"], [0.0001, "0.0001"], [0.00001, "1e-05"], [1.5e-7, "1.5e-07"],
    [1e15, "1000000000000000.0"], [1e16, "1e+16"], [123456789012345680, "1.2345678901234568e+17"],
    [2.842170943040401e-14, "2.842170943040401e-14"], [-35.43926206447239, "-35.43926206447239"], [-0, "0.0"],
    [1e300, "1e+300"], [9.999999999999999e-5, "9.999999999999999e-05"], [-1e-300, "-1e-300"],
    [5e-324, "5e-324"], [1.7976931348623157e308, "1.7976931348623157e+308"], [9999999999999998, "9999999999999998.0"],
    [0.1, "0.1"], [100, "100.0"], [12345.678, "12345.678"],
  ];
  for (const [x, s] of table) assert.equal(py_repr(x), s, String(x));
});

test("py_repr agrees with the exponent-form construction for random doubles", () => {
  // the general path of the contract (toExponential digits + CPython thresholds) for every magnitude
  function general(x: number): string {
    const ax = Math.abs(x);
    const t = ax.toExponential();
    const [mant, ex] = t.split("e") as [string, string];
    const e = Number(ex);
    const digits = mant.replace(".", "");
    const n = digits.length, decpt = e + 1;
    let s;
    if (decpt <= -4 || decpt > 16) s = digits[0] + (n > 1 ? "." + digits.slice(1) : "") + "e" + (e < 0 ? "-" : "+") + String(Math.abs(e)).padStart(2, "0");
    else if (decpt <= 0) s = "0." + "0".repeat(-decpt) + digits;
    else if (decpt >= n) s = digits + "0".repeat(decpt - n) + ".0";
    else s = digits.slice(0, decpt) + "." + digits.slice(decpt);
    return (x < 0 ? "-" : "") + s;
  }
  let seed = 12345;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  for (let i = 0; i < 20000; i++) {
    const x = (rnd() - 0.5) * Math.pow(10, Math.floor(rnd() * 44) - 22);
    if (x === 0) continue;
    assert.equal(py_repr(x), general(x), String(x));
  }
});

test("cmp_code_points orders by Unicode code points", () => {
  assert.ok(cmp_code_points("a.v10", "a.v2") < 0);
  assert.ok(cmp_code_points("Z", "a") < 0);
  assert.ok(cmp_code_points("a", "ab") < 0);
  assert.equal(cmp_code_points("x", "x"), 0);
  // U+1F600 (surrogate pair) sorts after U+FF5E, unlike UTF-16 code unit order
  assert.ok(cmp_code_points("\u{1F600}", "\uFF5E") > 0);
  assert.ok("\u{1F600}" < "\uFF5E");
  assert.deepEqual(["b", "a.v2", "a.v10", "A"].sort(cmp_code_points), ["A", "a.v10", "a.v2", "b"]);
});

test("INT_KEYS equals rules.json int_keys and integers are written without a fraction", () => {
  const rules = read_json(repo_path("tests", "conformance", "rules.json"));
  assert.deepEqual([...INT_KEYS].sort(), [...rules.int_keys].sort());
  assert.equal(dumps({ large_arc: 1, sweep: 0, rx: 1 }), '{\n "large_arc": 1,\n "rx": 1.0,\n "sweep": 0\n}');
  assert.equal(dumps({ arcs: [{ sweep: 1 }] }), '{\n "arcs": [\n  {\n   "sweep": 1\n  }\n ]\n}');
});

test("layout: empty containers, nesting, strings", () => {
  assert.equal(dumps({ b: [], a: {}, c: [[]], d: null, e: true, f: "中文 \"q\"\n" }),
    '{\n "a": {},\n "b": [],\n "c": [\n  []\n ],\n "d": null,\n "e": true,\n "f": "中文 \\"q\\"\\n"\n}');
  assert.equal(dumps([]), "[]");
  assert.equal(dumps("\u0001"), '"\\u0001"');
  assert.throws(() => dumps("\uD800"));
});

test("-0 is canonicalised and non-finite numbers throw", () => {
  assert.equal(dumps([-0, -0.0]), "[\n 0.0,\n 0.0\n]");
  assert.ok(Object.is(canonical({ x: [-0] }).x[0], 0));
  assert.throws(() => dumps({ x: NaN }));
  assert.throws(() => dumps({ x: Infinity }));
  assert.throws(() => canonical({ x: [-Infinity] }));
});

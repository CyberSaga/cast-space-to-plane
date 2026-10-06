/** Numerics of the port (contract §5.4.4, §5.4.13): Python float / int semantics and the source grep rules. */

import assert from "node:assert/strict";
import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { py_round, pyimod, pymod } from "../src/pyfloat.js";
import { read_text, repo_path } from "./helpers.js";

function src_files(dir = repo_path("ts", "src")): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir).sort()) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...src_files(p));
    else if (name.endsWith(".ts")) out.push(p);
  }
  return out;
}

test("pymod table (CPython float_rem)", () => {
  const two_pi = 2 * Math.PI;
  assert.equal(pymod(-1e-17, two_pi), two_pi);
  assert.equal(pymod(7, two_pi), 0.7168146928204138);
  assert.equal(pymod(-0.5, Math.PI), 2.641592653589793);
  assert.ok(Object.is(pymod(0, -1), -0));
  assert.ok(Object.is(pymod(-0, 1), 0));
  assert.equal(pymod(-7, 4), 1);
  assert.equal(pymod(7, -4), -1);
});

test("pyimod and py_round", () => {
  assert.equal(pyimod(-1, 5), 4);
  assert.equal(pyimod(-7, 4), 1);
  assert.equal(pyimod(3, 4), 3);
  assert.equal(py_round(0.5), 0);
  assert.equal(py_round(1.5), 2);
  assert.equal(py_round(2.5), 2);
  assert.equal(py_round(-0.5), 0);     // Python round(-0.5) == 0 (the sign is irrelevant: the result indexes a list)
  assert.equal(py_round(-1.5), -2);
  assert.equal(py_round(2.4999999), 2);
  assert.equal(py_round(-2.6), -3);
});

/** Remove comments and string literals so that only code is scanned. */
function code_only(text: string): string {
  return text
    .replace(/\/\*[\s\S]*?\*\//g, (m) => m.replace(/[^\n]/g, " "))
    .replace(/(["'`])(?:\\.|(?!\1)[^\\\n])*\1/g, (m) => " ".repeat(m.length))
    .replace(/\/\/.*$/gm, "");
}

test("% rule (contract §5.4.4 (4b)): every % outside pyfloat.ts has a provably non-negative left operand", () => {
  const offenders: string[] = [];
  for (const file of src_files()) {
    if (file.endsWith("pyfloat.ts")) continue;
    const raw = read_text(file).split("\n");
    const code = code_only(raw.join("\n")).split("\n");
    code.forEach((line, i) => {
      for (const m of line.matchAll(/%/g)) {
        const left = line.slice(0, m.index).trimEnd();
        let ok = false;
        const paren = /\(([^()]*)\)$/.exec(left);
        if (paren) ok = /^\s*(?:\w+\s*\+\s*\d+|start \+ k)\s*$/.test(paren[1] as string);
        else ok = /(^|[^\w.])(k|s|idx)$/.test(left);
        if (!ok && /\/\/ pyimod-free: \S/.test(raw[i] as string)) ok = true;
        if (!ok) offenders.push(`${file}:${i + 1}: ${(raw[i] as string).trim()}`);
      }
    });
  }
  assert.deepEqual(offenders, []);
});

test("neutrality grep (contract §5.4.13): no node-only API under ts/src", () => {
  const banned = ["node:", "process.", "Buffer", "require(", "import.meta", "performance."];
  const offenders: string[] = [];
  for (const file of src_files()) {
    const text = read_text(file);
    for (const s of banned) if (text.includes(s)) offenders.push(`${file}: ${s}`);
  }
  assert.deepEqual(offenders, []);
});

test("determinism grep (contract §5.4.4 (8)): no clock, randomness or typed float32 under ts/src", () => {
  const banned = ["Date", "Math.random", "Float32Array", "Math.fround"];
  const offenders: string[] = [];
  for (const file of src_files()) {
    const text = code_only(read_text(file));
    for (const s of banned) if (new RegExp(`\\b${s.replace(".", "\\.")}\\b`).test(text)) offenders.push(`${file}: ${s}`);
  }
  assert.deepEqual(offenders, []);
});

import {
  COND_MAX, centred_conic, circle_matrix, classify, classify_and_condition, condition_number, ellipse_params,
  is_sampled, jacobi_eigenvalues_3, sample_count, sub_arcs_where_nonnegative, transform_conic,
} from "../src/conics.js";

function affine(a: number, b: number, alpha: number, tx: number, ty: number): number[][] {
  const c = Math.cos(alpha), s = Math.sin(alpha);
  return [[c * a, -s * b, tx], [s * a, c * b, ty], [0, 0, 1]];
}

test("ellipse_params: a circle within rounding has rotation 0, whatever the ulp noise (as conics.py, M7 review)", () => {
  const noisy: [number, number, number][] = [
    [-0.0032653061224489806, 1.27e-20, -0.0032653061224489793], // numpy/BLAS values of the on-axis sphere
    [-0.0032653061224489793, -1.27e-20, -0.0032653061224489806],
    [-0.00326530612244898, 0.0, -0.00326530612244898],            // exact tie (the port's fixed-order sums)
  ];
  for (const [p, q, r] of noisy) {
    const res = ellipse_params([[p, q, 0], [q, r, 0], [0, 0, 1]]);
    assert.ok(res !== null);
    assert.equal(res[2], 0);
    assert.ok(res[1][0] >= res[1][1] && Math.abs(res[1][0] - 17.5) <= 1e-11 && Math.abs(res[1][1] - 17.5) <= 1e-11);
  }
  const ell = ellipse_params([[-(1 + 2e-6), 0, 0], [0, -1, 0], [0, 0, 1]]);  // above the band: major axis along y
  assert.ok(ell !== null && Math.abs(ell[2] - Math.PI / 2) <= 1e-12 && ell[1][0] > ell[1][1]);
});

test("sort grep (contract §5.4.4 (8)): every sort under ts/src has an explicit comparator", () => {
  const offenders: string[] = [];
  for (const file of src_files()) {
    const lines = code_only(read_text(file)).split("\n");
    lines.forEach((l, i) => { if (/\.(sort|toSorted)\(\s*\)/.test(l)) offenders.push(`${file}:${i + 1}`); });
  }
  assert.deepEqual(offenders, []);
});

test("catch grep: no bare catch under ts/src (only the named degenerate-contact error is turned into a fallback)", () => {
  const offenders: string[] = [];
  for (const file of src_files()) {
    const lines = code_only(read_text(file)).split("\n");
    lines.forEach((l, i) => { if (/catch\s*\{/.test(l)) offenders.push(`${file}:${i + 1}`); });
  }
  assert.deepEqual(offenders, []);
});

test("jacobi_eigenvalues_3 and the condition number (contract §5.4.4 (5))", () => {
  const ev = jacobi_eigenvalues_3([[1, 0, 0], [0, 1e-9, 0], [0, 0, 1]]).map(Math.abs);
  assert.ok(Math.max(...ev) / Math.min(...ev) > COND_MAX);
  const sorted = jacobi_eigenvalues_3([[2, 1, 0], [1, 2, 0], [0, 0, 3]]).sort((x, y) => x - y);
  sorted.forEach((x, i) => assert.ok(Math.abs(x - ([1, 3, 3][i] as number)) <= 1e-14));
  const s3 = jacobi_eigenvalues_3([[4, -2, 1], [-2, 5, 3], [1, 3, -6]]);
  const trace = s3[0] + s3[1] + s3[2];
  assert.ok(Math.abs(trace - 3) <= 1e-12);
  assert.ok(Math.abs(s3[0] * s3[1] * s3[2] - (4 * (5 * -6 - 9) + 2 * (-2 * -6 - 3) + 1 * (-6 - 5))) <= 1e-9);
});

test("a 0.3 m circle 50 m away classifies as a healthy ellipse, not sampled (contract §2.6)", () => {
  for (const dist of [0.0, 50.0, 500.0, 5000.0]) {
    const C = transform_conic(circle_matrix(0.3), affine(1, 1, 0, dist, 0.3 * dist));
    assert.equal(classify(C), "ellipse");
    assert.ok(condition_number(C) < 1e8);
    assert.ok(!is_sampled(C));
    const [kind, cond] = classify_and_condition(C);
    assert.equal(kind, "ellipse");
    assert.ok(cond < 1e8);
    const [, centre] = centred_conic(C);
    assert.ok(centre !== null && Math.abs(centre[0] - dist) <= 1e-6 * Math.max(1, dist));
    const params = ellipse_params(C);
    assert.ok(params !== null && Math.abs(params[1][0] - 0.3) <= 1e-6 && Math.abs(params[1][1] - 0.3) <= 1e-6);
  }
  assert.equal(classify([[0, 0, 0], [0, 0, 0], [0, 0, 1]]), "degenerate");
});

test("sample_count table and sub-arcs", () => {
  assert.equal(sample_count(0, Math.PI), 32);
  assert.equal(sample_count(0, 0.1), 8);
  assert.equal(sample_count(0, 2 * Math.PI), 64);
  assert.deepEqual(sub_arcs_where_nonnegative(0, 0, 1), [[0, 2 * Math.PI]]);
  assert.deepEqual(sub_arcs_where_nonnegative(0, 0, -1), []);
  const iv = sub_arcs_where_nonnegative(1, 0, 0);       // cos θ > 0: one seam-merged interval
  assert.equal(iv.length, 1);
  assert.ok(Math.abs((iv[0] as number[])[0]! - 1.5 * Math.PI) <= 1e-12 && Math.abs((iv[0] as number[])[1]! - 2.5 * Math.PI) <= 1e-12);
});

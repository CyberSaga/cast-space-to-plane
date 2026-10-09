/** Tests of the plane-equation field (`web/src/equation.ts`; spec-v0.2 §5.6, §7.1 "方程式解析"; contract §5.7.8 item 12
 * and §5.7.13): the grammar, the valid and invalid sets, the (f, g) of the quick equations and the rig conversion. */

import assert from "node:assert/strict";
import { test } from "node:test";

import type { Vec3 } from "castplane";

import { EquationError, QUICK_EQUATIONS, applyEquation, normalizeEquationText, parseEquation } from "../src/equation.js";
import { equation, pan, planeConst, setLockLevel, setRoll, sync } from "../src/rig.js";
import type { RigState } from "../src/rig.js";

const P0: Vec3 = [0.15, 5.9, 0.9];
const initial = (P: Vec3 = P0): RigState => ({ f: [0, 1, 0], up: null, g: P[1] - 2, D: 4, a: 0, b: 0, roll_deg: 0, focal: 20, P });
const S = Math.SQRT1_2;

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}

function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}

const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;

test("valid equations: unit normal n and constant d of n·X = d", () => {
  const cases: [string, Vec3, number][] = [
    ["x=1", [1, 0, 0], 1],
    ["y = -2.5", [0, 1, 0], -2.5],
    ["y=2", [0, 1, 0], 2],
    ["z=3", [0, 0, 1], 3],
    ["2x - y + 3 = 0", [2 / Math.sqrt(5), -1 / Math.sqrt(5), 0], -3 / Math.sqrt(5)],
    ["x + y = 2", [S, S, 0], 2 * S],
    [".5x=1", [1, 0, 0], 2],
    ["3.x = 6", [1, 0, 0], 2],
    ["2*y = 4", [0, 1, 0], 2],
    ["-x = 1", [-1, 0, 0], 1],
    ["+z = -1", [0, 0, 1], -1],
    ["1 = x", [-1, 0, 0], -1],
    ["x + 1 = 2y - 3 + z", [1 / Math.sqrt(6), -2 / Math.sqrt(6), -1 / Math.sqrt(6)], -4 / Math.sqrt(6)],
    ["X + Y = 3", [S, S, 0], 3 * S],
    ["x − 1 = 0", [1, 0, 0], 1], // U+2212 minus
    ["x – y = 0", [S, -S, 0], 0], // en dash
    ["ｙ＝2".replace("ｙ", "y").replace("＝", "="), [0, 1, 0], 2],
    ["x ＋ y = 2", [S, S, 0], 2 * S], // full-width plus
    ["y －2 = 0", [0, 1, 0], 2], // full-width minus
    ["  2 x   =  4  ", [1, 0, 0], 2],
    ["x + x = 4", [1, 0, 0], 2],
    ["0x + y = 1", [0, 1, 0], 1],
  ];
  for (const [text, n, d] of cases) {
    const q = parseEquation(text);
    close3(q.n, n, 1e-15, `${text} n`);
    close(q.d, d, 1e-14, `${text} d`);
    close(Math.hypot(...q.n), 1, 1e-15, `${text} |n|`);
    for (const c of q.n) assert.equal(Object.is(c, -0), false, `${text}: no negative zero`);
  }
  assert.equal(normalizeEquationText(" x − 1 ＋ y — 2 – z － 3 "), "x-1+y-2-z-3");
});

test("invalid equations: syntax errors and no variable keep the plane", () => {
  const syntax = ["x==1", "=1", "x=", "", "x", "xy=1", "x^2=1", "2(x)=1", "x+=1", "x=1=2", "1e3x=1", "x/2=1", "a=1", "x y = 1",
    "x..=1", "--x=1", "x*y=1", "1.2.3=x", "9".repeat(400) + "x=1"];
  for (const text of syntax) {
    assert.throws(() => parseEquation(text), (e: unknown) => e instanceof EquationError && e.code === "syntax", `"${text.slice(0, 20)}" syntax`);
  }
  for (const text of ["2=3", "0x = 1", "x - x = 1", "1 = 1"]) {
    assert.throws(() => parseEquation(text), (e: unknown) => e instanceof EquationError && e.code === "no_variable", `"${text}" no variable`);
  }
  const rig = initial();
  assert.throws(() => applyEquation(rig, "x=="), EquationError);
  assert.deepEqual(rig, initial(), "the rig is not mutated");
});

test("(f, g) of y=2, x=1, z=3, y=-3 (D = 4, scene-centre pivot): the plane passes through Q", () => {
  const rig0 = initial();
  const want: [string, Vec3, number, string][] = [
    ["y=2", [0, 1, 0], P0[1] - 2, "y = 2.00"],
    ["x=1", [-1, 0, 0], 1 - P0[0], "x = 1.00"],
    ["z=3", [0, 0, -1], 3 - P0[2], "z = 3.00"],
    ["y=-3", [0, 1, 0], P0[1] + 3, "y = -3.00"],
  ];
  for (const [text, f, g, eq] of want) {
    const r = applyEquation(rig0, text);
    assert.deepEqual(r.f, f, `${text} f`);
    close(r.g, g, 1e-12, `${text} g`);
    assert.equal(equation(r), eq);
    const { n, d } = parseEquation(text);
    const Q = sync(r).Q;
    close(dot(n, Q), d, 1e-9, `${text}: Q on the plane`);
    // the board lies between the eye and the pivot
    const E = sync(r).E;
    assert.ok((dot(n, E) - d) * (dot(n, r.P) - d) < 0, `${text}: the plane separates the eye and the pivot`);
    close(Math.abs(dot(n, E) - d), r.D, 1e-9, `${text}: the eye is D behind the board`);
  }
  // y=2 gives the demo start: eye at y = −2 straight behind the pivot
  close3(sync(applyEquation(rig0, "y=2")).E, [P0[0], -2, P0[2]], 1e-12, "y=2 eye");
  // x=1 looks from the +x side
  assert.ok(sync(applyEquation(rig0, "x=1")).E[0] > 1, "x=1: eye on the +x side");
  // z=3 looks down
  assert.ok(sync(applyEquation(rig0, "z=3")).E[2] > 3, "z=3: eye above");
});

test("g + D outside [0.8, 40] is rejected and the plane is kept", () => {
  const rig0 = initial();
  assert.throws(() => applyEquation(rig0, "y = 50"), (e: unknown) => e instanceof EquationError && e.code === "too_far");
  assert.throws(() => applyEquation(rig0, "y = -40"), (e: unknown) => e instanceof EquationError && e.code === "too_far");
  // 39.9 m to the pivot: allowed
  const ok = applyEquation(rig0, `y = ${P0[1] - 35.9}`);
  close(ok.g + ok.D, 39.9, 1e-9, "R");
  const near = { ...rig0, D: 0.5 };
  assert.throws(() => applyEquation(near, `y = ${P0[1] - 0.1}`), (e: unknown) => e instanceof EquationError && e.code === "too_near");
  for (const code of ["syntax", "no_variable", "too_far", "too_near"] as const) {
    assert.throws(() => {
      throw new EquationError(code, "x");
    }, EquationError);
  }
});

test("pan and roll are kept; up = null under lock, the new u₀ in free mode", () => {
  const busy = setRoll(pan(initial(), 30, -12, 480, 24), 25);
  const r = applyEquation(busy, "x + y = 3");
  assert.equal(r.a, busy.a);
  assert.equal(r.b, busy.b);
  assert.equal(r.roll_deg, 25);
  assert.equal(r.up, null);
  close(dot([S, S, 0], sync(r).Q), 3 * S, 1e-9, "Q on x + y = 3");
  close(planeConst(r), 3 * S, 1e-12, "c");
  assert.equal(equation(r), "0.707x + 0.707y = 2.121");
  const free = applyEquation(setLockLevel(busy, false), "z = 3");
  assert.deepEqual(free.f, [0, 0, -1]);
  assert.deepEqual(free.up, [0, 1, 0]);
});

test("quick buttons are valid equations", () => {
  assert.deepEqual([...QUICK_EQUATIONS], ["x=1", "y=2", "y=-3", "z=3", "x+y=3"]);
  for (const q of QUICK_EQUATIONS) applyEquation(initial(), q);
});

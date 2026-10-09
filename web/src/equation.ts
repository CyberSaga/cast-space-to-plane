/**
 * The plane-equation field of plane mode (spec-v0.2 §5.6; contract §5.7.8 item 12) — pure, DOM-free, unit-tested
 * (`web/test/equation.test.ts`).
 *
 * Grammar, after removing all white space and mapping `− – — －` to `-` and `＋` to `+`:
 *
 *     equation := side "=" side                       (exactly one "=")
 *     side     := ["+" | "-"] term (("+" | "-") term)*
 *     term     := coef? "*"? var | number
 *     coef     := digits ("." digits?)? | "." digits   (an empty coefficient is 1)
 *     number   := digits ("." digits?)? | "." digits
 *     var      := x | y | z | X | Y | Z
 *
 * No exponents, no products of variables. Both sides are collected into `a·X = k`; `n = a/|a|`, `d = k/|a|` (plane
 * `n·X = d`). {@link applyEquation} then converts the plane to the rig with `planeToRig` and rejects `g + D` outside
 * `[0.8, 40]`.
 */

import type { Vec3 } from "castplane";

import { applyPlane } from "./rig.js";
import type { RigState } from "./rig.js";

export type EquationErrorCode = "syntax" | "no_variable" | "too_far" | "too_near";

/** A rejected equation: the field turns red with `message`; the plane is kept. */
export class EquationError extends Error {
  constructor(readonly code: EquationErrorCode, message: string) {
    super(message);
    this.name = "EquationError";
  }
}

export const EQUATION_MESSAGES: Readonly<Record<EquationErrorCode, string>> = {
  syntax: "只接受 x、y、z 的一次式，例如 x=1、2x-y+3=0",
  no_variable: "式子裡要有 x、y 或 z",
  too_far: "平面離場景太遠（眼睛到旋轉中心需 ≤ 40 m）",
  too_near: "平面離場景太近（眼睛到旋轉中心需 ≥ 0.8 m）",
};

/** The equation field's quick buttons. */
export const QUICK_EQUATIONS: readonly string[] = ["x=1", "y=2", "y=-3", "z=3", "x+y=3"];

const NUMBER = String.raw`(?:\d+(?:\.\d*)?|\.\d+)`;
const TERM_VAR = new RegExp(String.raw`^(${NUMBER})?\*?([xyzXYZ])$`);
const TERM_NUM = new RegExp(String.raw`^${NUMBER}$`);

function fail(code: EquationErrorCode): never {
  throw new EquationError(code, EQUATION_MESSAGES[code]);
}

/** `[a_x, a_y, a_z, k]` of one side (`a·X + k`). */
function parseSide(side: string): [number, number, number, number] {
  const out: [number, number, number, number] = [0, 0, 0, 0];
  if (side === "") fail("syntax");
  const terms = side.match(/[+-]?[^+-]+/g);
  if (terms === null || terms.join("") !== side) fail("syntax");
  for (const t of terms) {
    const sg = t[0] === "-" ? -1 : 1;
    const body = t.replace(/^[+-]/, "");
    const m = TERM_VAR.exec(body);
    if (m !== null) {
      const k = m[1] === undefined ? 1 : parseFloat(m[1]);
      out["xyz".indexOf(m[2]!.toLowerCase())]! += sg * k;
      continue;
    }
    if (TERM_NUM.test(body)) {
      out[3] += sg * parseFloat(body);
      continue;
    }
    fail("syntax");
  }
  return out;
}

/** Normalise the typed text: drop white space, map Unicode minus / dashes and full-width plus. */
export function normalizeEquationText(text: string): string {
  return text.replace(/\s+/g, "").replace(/[−–—－]/g, "-").replace(/＋/g, "+");
}

/**
 * Parse a linear equation in `x`, `y`, `z` (terms on both sides) into the unit normal `n` and constant `d` of the
 * plane `n·X = d`. Throws {@link EquationError} (`"syntax"`, `"no_variable"`).
 */
export function parseEquation(text: string): { n: Vec3; d: number } {
  const s = normalizeEquationText(text);
  const parts = s.split("=");
  if (parts.length !== 2) fail("syntax");
  const L = parseSide(parts[0]!), R = parseSide(parts[1]!);
  const a: Vec3 = [L[0] - R[0], L[1] - R[1], L[2] - R[2]];
  const k = R[3] - L[3];
  if (![...a, k].every(Number.isFinite)) fail("syntax");
  const nl = Math.hypot(a[0], a[1], a[2]);
  if (!(nl >= 1e-9)) fail("no_variable");
  const n = a.map((v) => (v / nl === 0 ? 0 : v / nl)) as Vec3;
  return { n, d: k / nl + 0 };
}

/**
 * Parse `text` and apply the plane to the rig (spec-v0.2 §5.6): `f`, `g` from `planeToRig`; pan and roll kept;
 * `up = null` (lock) or the new `u₀` (free). Throws {@link EquationError} on a syntax error, no variable, or
 * `g + D` outside `[0.8, 40]`; the caller keeps the old plane.
 */
export function applyEquation(rig: RigState, text: string): RigState {
  const { n, d } = parseEquation(text);
  const r = applyPlane(rig, n, d);
  if ("error" in r) fail(r.error);
  return r.rig;
}

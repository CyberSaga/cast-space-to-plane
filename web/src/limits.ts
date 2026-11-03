/**
 * D86 joint limits (contract §5.8 notes; spec-v0.3 §10) — pure, DOM-free and three-free, unit-tested
 * (`web/test/limits.test.ts`).
 *
 * A part P with a resolved D85 parent Q may carry the web-only key `joint_limit = {axis, min_deg?, max_deg?}`
 * (`links.ts::parse_joint_limit`). Its angle is the **twist** about the unit axis `a` (written in Q's local frame) of the
 * rotation of P relative to Q, `D = R_Qᵀ·R_P` (both the current `transform_frame` rotations): `φ = 0` when P's local frame
 * is aligned with Q's, and any rotation applied to both P and Q (a group drag, an ancestor drag) leaves `D` unchanged.
 * Nothing is stored: the angle is read from the two transforms, so *Download scene* + reload keeps it.
 *
 * A ring drag of P is clamped at the bound ahead in closed form ({@link clamp_drag_angle}); a numeric 套用 beyond it is
 * refused by `main.ts` (never clamped). The texts of the panel line are here too.
 */

import { transform_frame } from "castplane";
import type { Mat3, Transform, Vec3 } from "castplane";

import { wrap_angle } from "./object_rotate.js";

/** Decisions only (never a written value): an angle within this of a bound is at the bound (degrees). */
export const LIMIT_EPS_DEG = 1e-9;
/** A drag whose gesture constant `|κ|` is at most this does not change `φ` (no clamp). */
export const KAPPA_EPS = 1e-9;

const DEG = Math.PI / 180;

/** A resolved joint limit (`LinkForest.limits`): the written axis (readout, file), its unit `a` (Q's local frame), the
 * bounds with ±180 for an absent one, and which bounds were written (the range text). */
export interface Limit {
  axis: Vec3;
  a: Vec3;
  min: number;
  max: number;
  min_written: boolean;
  max_written: boolean;
}

/** The state of an angle against a limit. */
export type LimitState = "inside" | "at_max" | "at_min" | "above" | "below";

const dot3 = (a: readonly number[], b: readonly number[]): number => a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;
const cross3 = (a: readonly number[], b: readonly number[]): Vec3 =>
  [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];
const z0 = (x: number): number => x + 0;

/** A deep copy of a limit. */
export function clone_limit(l: Limit): Limit {
  return { axis: [l.axis[0], l.axis[1], l.axis[2]], a: [l.a[0], l.a[1], l.a[2]], min: l.min, max: l.max,
    min_written: l.min_written, max_written: l.max_written };
}

// ------------------------------------------------------------------------------------------------ the measure

/**
 * The unit quaternion `[w, x, y, z]` of the rotation matrix `R` with `w ≥ 0` (Shepperd: the largest of `4w², 4x², 4y²,
 * 4z²` from the diagonal is taken first, so the result is exact also at 180° rotations; negated when `w < 0`).
 */
export function quat_from_matrix(R: Mat3): [number, number, number, number] {
  const tr = R[0][0] + R[1][1] + R[2][2];
  let w: number, x: number, y: number, z: number;
  if (tr >= R[0][0] && tr >= R[1][1] && tr >= R[2][2]) {
    w = Math.sqrt(1 + tr) / 2;
    const f = 4 * w;
    x = (R[2][1] - R[1][2]) / f;
    y = (R[0][2] - R[2][0]) / f;
    z = (R[1][0] - R[0][1]) / f;
  } else if (R[0][0] >= R[1][1] && R[0][0] >= R[2][2]) {
    x = Math.sqrt(Math.max(0, 1 + R[0][0] - R[1][1] - R[2][2])) / 2;
    const f = 4 * x;
    w = (R[2][1] - R[1][2]) / f;
    y = (R[0][1] + R[1][0]) / f;
    z = (R[0][2] + R[2][0]) / f;
  } else if (R[1][1] >= R[2][2]) {
    y = Math.sqrt(Math.max(0, 1 - R[0][0] + R[1][1] - R[2][2])) / 2;
    const f = 4 * y;
    w = (R[0][2] - R[2][0]) / f;
    x = (R[0][1] + R[1][0]) / f;
    z = (R[1][2] + R[2][1]) / f;
  } else {
    z = Math.sqrt(Math.max(0, 1 - R[0][0] - R[1][1] + R[2][2])) / 2;
    const f = 4 * z;
    w = (R[1][0] - R[0][1]) / f;
    x = (R[0][2] + R[2][0]) / f;
    y = (R[1][2] + R[2][1]) / f;
  }
  return w < 0 ? [z0(-w), z0(-x), z0(-y), z0(-z)] : [z0(w), z0(x), z0(y), z0(z)];
}

/**
 * The twist of the rotation `D` about the unit axis `a` (degrees, `(−180, 180]`, no `-0`): `wrap(2·atan2(a·v, w))` with
 * `(w, v)` the quaternion of `D` ({@link quat_from_matrix}). `φ = θ` for `D = Rot(a, θ)`, 0 for a rotation about an axis
 * ⟂ `a`, and the same for `Rot(a, θ)·S` and `S·Rot(a, θ)` with `S` a swing about an axis ⟂ `a`. The one singular rotation
 * (180° about an axis exactly ⟂ `a`, `atan2(0, 0)`) reads 0.
 */
export function twist_deg(D: Mat3, a: readonly number[]): number {
  const [w, x, y, z] = quat_from_matrix(D);
  return wrap_angle((2 * Math.atan2(a[0]! * x + a[1]! * y + a[2]! * z, w)) / DEG);
}

/** The rotation of P relative to its parent Q, `D = R_Qᵀ·R_P` (both from `transform_frame`; written in Q's local frame). */
export function relative_rotation(tP: Transform, tQ: Transform): Mat3 {
  const [RP] = transform_frame(tP), [RQ] = transform_frame(tQ);
  const out = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) out[i][j] = RQ[0][i] * RP[0][j] + RQ[1][i] * RP[1][j] + RQ[2][i] * RP[2][j];
  return out;
}

/** The angle `φ` of part P at transform `tP` under limit `lim` against its parent at `tQ`. */
export function limit_angle(lim: Limit, tP: Transform, tQ: Transform): number {
  return twist_deg(relative_rotation(tP, tQ), lim.a);
}

/** `φ` with the one identification `+180 ≡ −180` applied (D86 review R1): when `min = −180` an angle within ε of +180
 * is the pose at the lower bound, so it reads `−180`. Every decision and the readout use this value. */
export function canonical_angle(phi: number, lim: Limit): number {
  return lim.min === -180 && phi >= 180 - LIMIT_EPS_DEG ? -180 : phi;
}

/** The state of `φ` against `lim` (after {@link canonical_angle}): `at_max` / `at_min` within ε of a bound (the
 * difference wrapped, so `+180` and `−180` meet), `inside` within `[min, max]`, else `above` (`φ > max`) or `below`. */
export function limit_state(phi: number, lim: Limit): LimitState {
  const p = canonical_angle(phi, lim);
  if (Math.abs(wrap_angle(p - lim.max)) <= LIMIT_EPS_DEG) return "at_max";
  if (Math.abs(wrap_angle(p - lim.min)) <= LIMIT_EPS_DEG) return "at_min";
  if (p >= lim.min && p <= lim.max) return "inside";
  return p > lim.max ? "above" : "below";
}

/** Whether `φ` is in the range (a bound included within ε). */
export function inside(phi: number, lim: Limit): boolean {
  const s = limit_state(phi, lim);
  return s === "inside" || s === "at_max" || s === "at_min";
}

// ------------------------------------------------------------------------------------------------ the drag clamp

/** The gesture data of a ring drag of P: the half-angle coefficients of `num(t) = a·v(t)` and `den(t) = w(t)` for
 * `D(t) = Rot(e′, t)·D₀`, and `κ = α₂β₁ − α₁β₂` (`dφ/dt = κ / (num² + den²)`). */
export interface DragGesture {
  alpha1: number;
  beta1: number;
  alpha2: number;
  beta2: number;
  kappa: number;
}

/** The gesture data of `D₀` (the relative rotation at pointer-down) dragged about the unit axis `e_parent` (the ring's
 * world axis in Q's local frame, `R_Qᵀ·e`) under the limit axis `a`. */
export function drag_gesture(D0: Mat3, e_parent: readonly number[], a: readonly number[]): DragGesture {
  const [w0, x0, y0, z0_] = quat_from_matrix(D0);
  const v0: Vec3 = [x0, y0, z0_];
  const alpha1 = dot3(a, v0), alpha2 = w0;
  const beta1 = w0 * dot3(a, e_parent) + dot3(a, cross3(e_parent, v0));
  const beta2 = -dot3(e_parent, v0);
  return { alpha1, beta1, alpha2, beta2, kappa: alpha2 * beta1 - alpha1 * beta2 };
}

/** `φ(t)` of a gesture (degrees, wrapped). */
export function gesture_angle(g: DragGesture, t_deg: number): number {
  const h = (t_deg * DEG) / 2, c = Math.cos(h), s = Math.sin(h);
  return wrap_angle((2 * Math.atan2(g.alpha1 * c + g.beta1 * s, g.alpha2 * c + g.beta2 * s)) / DEG);
}

/**
 * The clamped drag angle (D86, closed form): `θ` (degrees, already snapped) of a drag of `D₀` about `e_parent` becomes
 * `θ*`, the largest part of `θ` in its direction that keeps `φ` from crossing the bound ahead:
 * 1. `θ = 0` or `|κ| ≤ KAPPA_EPS` → `θ` (the drag does not change `φ`).
 * 2. `σ = sign(θ)·sign(κ)` (the direction `φ` moves); the bound ahead `B` is `max` for `σ > 0`, else `min`.
 * 3. `φ₀ = canonical_angle(φ(0))`. At the bound ahead (`|wrap(φ₀ − B)| ≤ ε`) or beyond it (`σ·(φ₀ − B) > 0`): 0 (nothing
 *    moves). A pose at `max` can always be dragged back (the test looks at the moving direction only).
 * 4. Else the wall: `φ(t) = B ⟺ A·cos(t/2) + B_c·sin(t/2) = 0` with `A = α₁cos(B/2) − α₂sin(B/2)`, `B_c = β₁cos(B/2) −
 *    β₂sin(B/2)`, so `t ≡ τ = 2·atan2(−A, B_c)` (mod 360°); `t_B = ((τ % 360) + 360) % 360` in `(0, 360]` (0 → 360) for
 *    `θ > 0`, its negative counterpart in `[−360, 0)` for `θ < 0` (JS `%` keeps the sign of `τ`; D86 review R6). `φ` is
 *    monotone along the drag and takes each value once per 360° of `t`, so this is the bound ahead.
 * 5. `θ* = sign(θ)·min(|θ|, |t_B|)`.
 */
export function clamp_drag_angle(theta: number, g: DragGesture, lim: Limit): number {
  if (theta === 0 || Math.abs(g.kappa) <= KAPPA_EPS) return theta;
  const s = theta > 0 ? 1 : -1, sigma = s * (g.kappa > 0 ? 1 : -1);
  const B = sigma > 0 ? lim.max : lim.min;
  const phi0 = canonical_angle(wrap_angle((2 * Math.atan2(g.alpha1, g.alpha2)) / DEG), lim);
  if (Math.abs(wrap_angle(phi0 - B)) <= LIMIT_EPS_DEG || sigma * (phi0 - B) > 0) return 0;
  const hb = (B * DEG) / 2, cb = Math.cos(hb), sb = Math.sin(hb);
  const A = g.alpha1 * cb - g.alpha2 * sb, Bc = g.beta1 * cb - g.beta2 * sb;
  const tau = (2 * Math.atan2(-A, Bc)) / DEG;
  let tb: number;
  if (s > 0) {
    tb = ((tau % 360) + 360) % 360;
    if (tb === 0) tb = 360;
  } else {
    tb = -((((-tau) % 360) + 360) % 360);
    if (tb === 0) tb = -360;
  }
  return s * Math.min(Math.abs(theta), Math.abs(tb));
}

/** The clamp closure of one gesture (fixed at pointer-down): `θ ↦ clamp_drag_angle(θ, drag_gesture(D₀, e′, a), lim)`. */
export function drag_clamp(D0: Mat3, e_parent: readonly number[], lim: Limit): (theta: number) => number {
  const g = drag_gesture(D0, e_parent, lim.a), l = clone_limit(lim);
  return (theta) => clamp_drag_angle(theta, g, l);
}

// ------------------------------------------------------------------------------------------------ texts (§4)

/** An angle with `d` decimals, no wrap (`-180.0` stays), `-0.0…` → `0.0…`; hyphen-minus (what `toFixed` writes). */
export function format_deg(x: number, d = 1): string {
  const t = x.toFixed(d);
  return /^-0\.?0*$/.test(t) ? t.slice(1) : t;
}

/** {@link format_deg} with one decimal. */
export function format_deg1(x: number): string {
  return format_deg(x, 1);
}

/** An axis component: `toFixed(3)` with trailing zeros and the point stripped, `-0` → `0`. */
export function format_axis_component(x: number): string {
  const t = x.toFixed(3).replace(/\.?0+$/, "");
  return t === "-0" ? "0" : t;
}

/** The written axis as `(x, y, z)`. */
export function format_axis(axis: readonly number[]): string {
  return `(${axis.map(format_axis_component).join(", ")})`;
}

/** The range text by the written bounds: `-30.0°～11.0°`, `≤ 11.0°` or `≥ -30.0°`. */
export function range_text(lim: Limit): string {
  if (lim.min_written && lim.max_written) return `${format_deg1(lim.min)}°～${format_deg1(lim.max)}°`;
  return lim.max_written ? `≤ ${format_deg1(lim.max)}°` : `≥ ${format_deg1(lim.min)}°`;
}

const SUFFIX: Record<LimitState, string> = {
  inside: "", at_max: "（已達上限）", at_min: "（已達下限）", above: "（超出上限，只能往回轉）", below: "（超出下限，只能往回轉）",
};

/** The panel line: 「關節限制：繞 <parent> 的 (x, y, z) 軸 <range>，目前 <φ>°」 and the suffix of the state. */
export function limit_text(lim: Limit, phi: number, parent_id: string): string {
  return `關節限制：繞 ${parent_id} 的 ${format_axis(lim.axis)} 軸 ${range_text(lim)}，目前 ${format_deg1(canonical_angle(phi, lim))}°`
    + SUFFIX[limit_state(phi, lim)];
}

/**
 * The refusal of a 套用 whose target `φ` is outside: 「套用被拒：繞 <parent> 的 (x, y, z) 軸會轉到 <φ>°，超出上限 <max>°」
 * (or 「低於下限 <min>°」). D86 review R7: when the angle and the bound print alike with one decimal, both are printed
 * with 3 (then 9) decimals, so the text never reads 「會轉到 11.0°，超出上限 11.0°」. Empty for an angle inside.
 */
export function refusal_text(lim: Limit, phi: number, parent_id: string): string {
  const st = limit_state(phi, lim);
  if (st !== "above" && st !== "below") return "";
  const p = canonical_angle(phi, lim), b = st === "above" ? lim.max : lim.min;
  let d = 1;
  for (const k of [1, 3, 9]) {
    d = k;
    if (format_deg(p, k) !== format_deg(b, k)) break;
  }
  return `套用被拒：繞 ${parent_id} 的 ${format_axis(lim.axis)} 軸會轉到 ${format_deg(p, d)}°，`
    + `${st === "above" ? "超出上限" : "低於下限"} ${format_deg(b, d)}°`;
}

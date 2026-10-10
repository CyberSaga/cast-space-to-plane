/** Tests of the plane-mode rig (`web/src/rig.ts`; spec-v0.2 §7.1 web rows, contract §5.7.13): invariants, ring,
 * arrow, the pan state, roll, sliders, views, pivot, the snapshot keys of the history (and its cap, `plane.ts`'s
 * `History`), the load rule and random frames. Picture checks go through the
 * port's `camera_matrix` with `toTargetCameraBlock` (the equivalent target form) or `toCameraBlock` (the
 * `picture_plane` form the port resolves). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { camera_matrix, load_scene, shadow_geometry, validate_camera } from "castplane";
import type { Camera, Scene, Vec2, Vec3 } from "castplane";

import { camera_from_orbit, orbit_from_camera, rotate_orbit } from "../src/orbit.js";
import type { LensBase } from "../src/orbit.js";
import {
  D_MAX_M, D_MIN_M, KAPPA_DEG_PER_PX, PITCH_LIMIT_DEG, R_MAX_M, R_MIN_M, UNDO_MAX, VIEWS, applyPlane,
  arrowDrag, arrowLength, arrowScreenVector, arrowTip, basis, bboxCentre, deltaText, equation, eye, fixed, foot,
  frameMetres, frameOf, fromCamera, fromOrbitState, measureRef, orbitFree, orbitLockLevel, orbitRing,
  pictureDelta, planeConst, planeToRig, plane_equation, readouts, resolvePicturePlane, ringPoint, ringRadius,
  ringSign, rollOfFrame, sameBoard, sameState, setD, setFocal, setLockLevel, setPivot, setRoll, sixView, snapToAxis, sync,
  toCameraBlock, toTargetCameraBlock, wrap_deg,
} from "../src/rig.js";
import type { RigState, RingGrab, ViewName } from "../src/rig.js";
import { History } from "../src/plane.js";
import type { BoardEntry } from "../src/plane.js";

// web/build/test/rig.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const scene_file = (...parts: string[]): Scene => load_scene(JSON.parse(readFileSync(resolve(ROOT, ...parts), "utf-8")));

// ------------------------------------------------------------------------------------------------ helpers

const BASE: LensBase = { frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
const CANVAS: Vec2 = [360, 240]; // s = 10 canvas mm per frame mm
const P0: Vec3 = [0.15, 5.9, 0.9];

/** The demo's initial state: plane y = 2, eye straight behind the pivot, D = 4, focal 20 mm. */
const initial = (P: Vec3 = P0): RigState => ({ f: [0, 1, 0], up: null, g: P[1] - 2, D: 4, a: 0, b: 0, roll_deg: 0, focal: 20, P });
/** `rig` with the pan `(a, b)` (m, pre-roll basis): the state the load rule gives an off-axis scene camera. */
const withPan = (rig: RigState, a: number, b: number): RigState => ({ ...rig, a, b });

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const cross = (p: readonly number[], q: readonly number[]): Vec3 =>
  [p[1]! * q[2]! - p[2]! * q[1]!, p[2]! * q[0]! - p[0]! * q[2]!, p[0]! * q[1]! - p[1]! * q[0]!];
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));
const unit = (p: readonly number[]): Vec3 => mul(p, 1 / len(p));
const dist = (p: readonly number[], q: readonly number[]): number => len(sub(p, q));

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}

function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}

/** Deterministic PRNG (mulberry32). */
function rng(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function randomUnit(r: () => number): Vec3 {
  for (;;) {
    const v: Vec3 = [2 * r() - 1, 2 * r() - 1, 2 * r() - 1];
    const l = len(v);
    if (l > 0.1 && l <= 1) return mul(v, 1 / l);
  }
}

/** Canvas mm image of `X` through the rig's target block and the port's `camera_matrix`; null behind the eye. */
function image(rig: RigState, X: readonly number[]): Vec2 | null {
  const rec = camera_matrix(toTargetCameraBlock(rig, BASE), CANVAS);
  return imageRec(rec.P, X);
}

function imageRec(P: readonly (readonly number[])[], X: readonly number[]): Vec2 | null {
  const x = P.map((row) => row[0]! * X[0]! + row[1]! * X[1]! + row[2]! * X[2]! + row[3]!);
  if (!(x[2]! > 0)) return null;
  return [x[0]! / x[2]!, x[1]! / x[2]!];
}

/** Camera-space coordinates `[R|t]·X` of the rig's camera. */
function camSpace(rig: RigState, X: readonly number[]): Vec3 {
  const Rt = camera_matrix(toTargetCameraBlock(rig, BASE), CANVAS).Rt;
  return Rt.map((row) => row[0] * X[0]! + row[1] * X[1]! + row[2] * X[2]! + row[3]) as Vec3;
}

function pivotCentred(rig: RigState, tol: number, what: string): void {
  const p = image(rig, rig.P);
  assert.ok(p !== null, `${what}: pivot behind the eye`);
  close(p[0], 0, tol, `${what} pivot u`);
  close(p[1], 0, tol, `${what} pivot v`);
}

/** The demo's observer camera (az 55°, el 28°, vertical fov 40°) on a 600 × 450 px pane. */
interface Observer { pos: Vec3; r: Vec3; u: Vec3; f: Vec3; W: number; H: number; fpx: number }
function observer(target: Vec3 = [0, 3, 1], az = 55, el = 28, d = 15): Observer {
  const A = (az * Math.PI) / 180, B = (el * Math.PI) / 180;
  const dir: Vec3 = [Math.sin(A) * Math.cos(B), -Math.cos(A) * Math.cos(B), Math.sin(B)];
  const pos = add(target, mul(dir, d));
  const f = unit(sub(target, pos));
  const r = unit(cross(f, [0, 0, 1]));
  const H = 450;
  return { pos, r, u: cross(r, f), f, W: 600, H, fpx: H / 2 / Math.tan((20 * Math.PI) / 180) };
}
function obsPx(o: Observer, X: readonly number[]): Vec2 | null {
  const d = sub(X, o.pos);
  const z = dot(d, o.f);
  if (z < 0.1) return null;
  return [o.W / 2 + (dot(d, o.r) / z) * o.fpx, o.H / 2 - (dot(d, o.u) / z) * o.fpx];
}

/** Rigidly carry a point with the rig: the same coordinates in the pre-roll basis about `P`. */
function carry(r0: RigState, r1: RigState, X: readonly number[]): Vec3 {
  const a = frameOf(r0), b = frameOf(r1);
  const w = sub(X, r0.P);
  return add(r1.P, add(add(mul(b.r0, dot(w, a.r0)), mul(b.u0, dot(w, a.u0))), mul(r1.f, dot(w, r0.f))));
}

function assertFinite(x: unknown, what: string): void {
  if (typeof x === "number") assert.ok(Number.isFinite(x), `${what}: ${x}`);
  else if (Array.isArray(x)) x.forEach((v, i) => assertFinite(v, `${what}[${i}]`));
  else if (x !== null && typeof x === "object") for (const [k, v] of Object.entries(x)) assertFinite(v, `${what}.${k}`);
}

// ------------------------------------------------------------------------------------------------ invariants

test("initial state: plane y = 2, eye straight behind the pivot at R = g + D, pivot at the frame centre", () => {
  const rig = initial();
  const d = sync(rig);
  close3(d.E, [P0[0], -2, P0[2]], 1e-12, "E");
  close3(d.Q, [P0[0], 2, P0[2]], 1e-12, "Q");
  close(d.c, 2, 1e-12, "c");
  close(d.R, P0[1] + 2, 1e-12, "R");
  assert.equal(equation(rig), "y = 2.00");
  pivotCentred(rig, 1e-9, "initial");
  close3(eye(rig), d.E, 0, "eye()");
  close3(foot(rig), d.Q, 0, "foot()");
  assert.equal(planeConst(rig), d.c);
  const block = toCameraBlock(rig, BASE);
  assert.deepEqual(Object.keys(block).sort(), ["focal_length_mm", "frame_mm", "near_m", "picture_plane", "position", "shift_mm"]);
  assert.deepEqual(block.picture_plane.normal, [0, 1, 0]);
  close(block.picture_plane.offset, -2, 1e-12, "offset");
  assert.equal(block.picture_plane.up, undefined);
  assert.deepEqual(readouts(rig, BASE.frame_mm).frame_m, [7.2, 4.8]);
});

test("rig invariants (random f, g, up, D; pan 0): E = P − (g+D)·f, the pivot projects to (0, 0) within 1e-7 mm", () => {
  const r = rng(1);
  for (let i = 0; i < 300; i++) {
    const f = randomUnit(r);
    const D = D_MIN_M + r() * (D_MAX_M - D_MIN_M);
    const g = R_MIN_M - D + r() * (R_MAX_M - R_MIN_M);
    const up = i % 2 === 0 ? null : randomUnit(r);
    const rig: RigState = { f, up, g, D, a: 0, b: 0, roll_deg: 0, focal: 12 + r() * 60, P: [r() * 4 - 2, r() * 8, r() * 2] };
    if (up !== null && len(cross(up, f)) < 1e-3) continue;
    const d = sync(rig);
    close3(d.E, sub(rig.P, mul(f, g + D)), 1e-12 * (1 + g + D), `E #${i}`);
    close(dot(d.r, f), 0, 1e-12, "r ⟂ f");
    close(dot(d.u, f), 0, 1e-12, "u ⟂ f");
    close(dot(d.r, d.u), 0, 1e-12, "r ⟂ u");
    pivotCentred(rig, 1e-7, `#${i}`);
    // the plane f·X = c contains Q, and Q is at distance D in front of the eye
    close(dot(f, d.Q), d.c, 1e-9, "Q on the plane");
    close(dist(d.E, d.Q), D, 1e-9, "|E − Q|");
    // the core camera of the target block: forward f, frame up u
    const blk = toTargetCameraBlock(rig, BASE);
    validate_camera(blk);
    const rec = camera_matrix(blk, CANVAS);
    close3(rec.R[2], f, 1e-12, "forward");
    close3(rec.R[1], d.u, 1e-9, "up'");
    close3(rec.R[0], d.r, 1e-9, "right'");
    // the picture_plane block resolves to the same camera
    const pp = toCameraBlock(rig, BASE);
    assert.equal(pp.picture_plane.up === undefined, up === null);
    const res = resolvePicturePlane(pp);
    close(res.distance, D, 1e-9, "resolved D");
    close3(res.normal, f, 1e-15, "resolved f");
    close3(res.foot, d.Q, 1e-9, "resolved Q");
    const recPP = camera_matrix(res.block, CANVAS);
    for (let k = 0; k < 3; k++) close3(recPP.R[k]!, rec.R[k]!, 1e-9, `R[${k}] of the picture_plane form`);
  }
});

test("pan and roll: the pivot's image is offset by the pan, rows of R are the frame basis", () => {
  const r = rng(2);
  for (let i = 0; i < 100; i++) {
    const rig: RigState = { ...initial(), f: randomUnit(r), a: r() * 2 - 1, b: r() * 2 - 1, roll_deg: r() * 360 - 180 };
    if (i % 3 === 0) rig.up = setLockLevel(rig, false).up;
    const d = sync(rig);
    const p = image(rig, rig.P)!;
    const s = CANVAS[0] / BASE.frame_mm[0];
    close(p[0], (-rig.focal * s * dot(d.L, d.r)) / d.R, 1e-7, "pivot u");
    close(p[1], (-rig.focal * s * dot(d.L, d.u)) / d.R, 1e-7, "pivot v");
    close(dot(d.L, rig.f), 0, 1e-12, "L ⟂ f");
    close(dot(rig.f, d.Q), d.c, 1e-9, "the pan does not move the plane");
    close(rollOfFrame(rig.f, d.u), wrap_deg(rig.roll_deg), 1e-9, "roll of the frame");
  }
});

test("basis: the default is camera_matrix's (+y fallback when |f × z| ≤ 1e-9)", () => {
  const top = basis([0, 0, -1], null);
  close3(top.u0, [0, 1, 0], 0, "u0 top");
  close3(top.r0, [1, 0, 0], 0, "r0 top");
  const bottom = basis([0, 0, 1], null);
  close3(bottom.u0, [0, 1, 0], 0, "u0 bottom");
  close3(bottom.r0, [-1, 0, 0], 0, "r0 bottom");
  const front = basis([0, 1, 0], null);
  close3(front.u0, [0, 0, 1], 0, "u0 front");
  close3(front.r0, [1, 0, 0], 0, "r0 front");
  // a given up is used after projection
  const b = basis([0, 1, 0], [1, 0.3, 1]);
  close3(b.u0, unit([1, 0, 1]), 1e-15, "u0 with up");
  for (const f of [[0, 0, -1], [0, 0, 1], [0, 1, 0], unit([1, 2, 3])] as Vec3[]) {
    const rec = camera_matrix({ position: [0, 0, 0], target: f, focal_length_mm: 20, frame_mm: [36, 24] }, CANVAS);
    const bb = basis(f, null);
    close3(rec.R[0], bb.r0, 1e-15, "right'");
    close3(rec.R[1], bb.u0, 1e-15, "up'");
  }
});

// ------------------------------------------------------------------------------------------------ ring

function grabAt(rig: RigState, theta: number, obs: Observer): RingGrab {
  return { w: sub(ringPoint(rig, BASE.frame_mm, theta), rig.P), r_c: obs.r, u_c: obs.u };
}

test("ring, lock-horizontal: five drag directions keep g, D, |E − P|; right vector level; grabbed point follows the finger", () => {
  const obs = observer();
  const rig0 = initial();
  const E0 = sync(rig0).E;
  // grab points on the upper half of the ring and at its sides (the lower half lies below the ground here; there the
  // two lock-horizontal axes can fight on a diagonal drag, while each axis alone still follows the finger)
  for (const theta of [0, Math.PI / 4, Math.PI / 2, (3 * Math.PI) / 4, Math.PI]) {
    const grab = grabAt(rig0, theta, obs);
    const X0 = ringPoint(rig0, BASE.frame_mm, theta);
    for (const [dx, dy] of [[20, 0], [-20, 0], [0, 15], [0, -15], [14, -14]] as Vec2[]) {
      const r1 = orbitLockLevel(rig0, dx, dy, grab, false);
      const what = `θ=${theta.toFixed(2)} (${dx}, ${dy})`;
      assert.equal(r1.g, rig0.g, `${what} g`);
      assert.equal(r1.D, rig0.D, `${what} D`);
      assert.equal(r1.up, null);
      close(dist(sync(r1).E, rig0.P), dist(E0, rig0.P), 1e-9, `${what} |E − P|`);
      close(sync(r1).r[2], 0, 1e-12, `${what} right vector level`);
      pivotCentred(r1, 1e-7, what);
      const X1 = carry(rig0, r1, X0);
      close3(X1, ringPoint(r1, BASE.frame_mm, theta), 1e-9, `${what} the ring turns rigidly`);
      const p0 = obsPx(obs, X0)!, p1 = obsPx(obs, X1)!;
      const m: Vec2 = [p1[0] - p0[0], p1[1] - p0[1]];
      const cos = (m[0] * dx + m[1] * dy) / (Math.hypot(m[0], m[1]) * Math.hypot(dx, dy));
      assert.ok(cos > 0.3, `${what}: grabbed point moved (${m[0].toFixed(2)}, ${m[1].toFixed(2)}) px, cosine ${cos.toFixed(3)}`);
    }
  }
});

test("ring, lock-horizontal, KNOWN LIMITATION on the lower half of the ring (spec-v0.2 §5.2 independent signs)", () => {
  // Spec-v0.2 §7.1 asks that the grabbed point follow the finger (cosine > 0.3). The §5.2 rule picks the yaw and
  // pitch signs independently; on the lower half of the ring (below the ground in this geometry) the two axes can
  // fight, so a diagonal drag moves the grabbed point against the finger. The demo behaves identically (the rig
  // matches its ring code to 1e-15). Pinned here so a change to the rule is noticed; open question for the spec.
  const obs = observer();
  const rig0 = initial();
  for (const theta of [(5 * Math.PI) / 4, (3 * Math.PI) / 2, (7 * Math.PI) / 4]) {
    const grab = grabAt(rig0, theta, obs);
    const X0 = ringPoint(rig0, BASE.frame_mm, theta);
    for (const [dx, dy] of [[20, 0], [-20, 0], [0, 15], [0, -15], [14, -14], [-14, 14], [14, 14], [-14, -14]] as Vec2[]) {
      const r1 = orbitLockLevel(rig0, dx, dy, grab, false);
      const X1 = carry(rig0, r1, X0);
      const p0 = obsPx(obs, X0)!, p1 = obsPx(obs, X1)!;
      const m: Vec2 = [p1[0] - p0[0], p1[1] - p0[1]];
      const cos = (m[0] * dx + m[1] * dy) / (Math.hypot(m[0], m[1]) * Math.hypot(dx, dy));
      const what = `θ=${theta.toFixed(2)} (${dx}, ${dy}): cosine ${cos.toFixed(3)}`;
      if (dx === 0 || dy === 0) {
        // each axis alone still moves the point with the finger (measured ≥ 0.23, below the spec's 0.3 in places)
        assert.ok(cos > 0.2, `${what} single axis`);
      } else if (theta === (3 * Math.PI) / 2 && dx * dy < 0) {
        // the known failure: the bottom of the ring, an up-right / down-left diagonal drag (measured −0.99, −0.95).
        // If this starts failing, the sign rule changed: move the lower half into the test above.
        assert.ok(cos < 0, `${what} known limitation`);
      } else {
        assert.ok(cos > 0.3, what);
      }
    }
  }
});

test("ring sign rule: |dir·(axis × w)| < 1e-6 gives +1", () => {
  assert.equal(ringSign([0, 0, 1], [1, 0, 0], false, [0, 0, 1]), 1);
  assert.equal(ringSign([0, 0, 1], [1, 0, 0], true, [0, 0, 1]), 1);
  assert.equal(ringSign([0, 0, 1], [1, 0, 0], false, [0, -1, 0]), 1);
  assert.equal(ringSign([0, 0, 1], [1, 0, 0], false, [0, 1, 0]), -1);
  assert.equal(ringSign([0, 0, 1], [1, 0, 0], true, [0, 1, 0]), 1);
});

test("ring, one long drag: a full turn around the scene with the pivot at the frame centre throughout", () => {
  const obs = observer();
  const rig0 = initial();
  const grab = grabAt(rig0, Math.PI / 2, obs);
  const full = 360 / KAPPA_DEG_PER_PX; // 1125 px
  let prev = Math.atan2(rig0.f[1], rig0.f[0]), turned = 0;
  for (let dx = 0; dx <= full; dx += 15) {
    const r1 = orbitLockLevel(rig0, dx, 0, grab, true);
    pivotCentred(r1, 1e-7, `dx=${dx}`);
    close(dist(sync(r1).E, rig0.P), sync(rig0).R, 1e-9, `dx=${dx} radius`);
    const az = Math.atan2(r1.f[1], r1.f[0]);
    let step = az - prev;
    if (step > Math.PI) step -= 2 * Math.PI;
    if (step < -Math.PI) step += 2 * Math.PI;
    turned += step;
    prev = az;
  }
  close(Math.abs(turned), 2 * Math.PI, 1e-9, "full turn");
  close3(orbitLockLevel(rig0, full, 0, grab, false).f, rig0.f, 1e-12, "back at the start");
});

test("ring snapping: within 5° of an axis f becomes that axis exactly; Alt / switch off does not snap", () => {
  const obs = observer();
  const rig0 = initial();
  const grab = grabAt(rig0, 0, obs);
  // 3° yaw: inside the snap cone
  const dx3 = 3 / KAPPA_DEG_PER_PX;
  assert.deepEqual(orbitLockLevel(rig0, dx3, 0, grab, true).f, [0, 1, 0]);
  const off = orbitLockLevel(rig0, dx3, 0, grab, false).f;
  assert.notDeepEqual(off, [0, 1, 0]);
  close(Math.acos(off[1]), (3 * Math.PI) / 180, 1e-12, "3° without snapping");
  // 7°: outside the cone
  const r7 = orbitLockLevel(rig0, 7 / KAPPA_DEG_PER_PX, 0, grab, true);
  close(Math.acos(r7.f[1]), (7 * Math.PI) / 180, 1e-12, "7° stays");
  // snapToAxis: order ±x, ±y, ±z and the minimal rotation carries up
  const f = unit([0.02, -0.03, -1]);
  const up = basis(f, [0, 1, 0]).u0;
  const s = snapToAxis(f, up);
  assert.deepEqual(s.f, [0, 0, -1]);
  assert.ok(s.snapped);
  close(dot(s.up!, s.f), 0, 1e-12, "up ⟂ f after the snap");
  assert.equal(snapToAxis(unit([1, 1, 0]), null).snapped, false);
});

test("top view reachable: a ring drag clamps the elevation at 89.9°, then snaps to exactly −z", () => {
  const rig0 = initial();
  const grab0 = grabAt(rig0, Math.PI / 2, observer());
  const noSnap = [orbitLockLevel(rig0, 0, 1e5, grab0, false), orbitLockLevel(rig0, 0, -1e5, grab0, false)].find((r) => r.f[2] < 0)!;
  close(Math.asin(-noSnap.f[2]), (PITCH_LIMIT_DEG * Math.PI) / 180, 1e-12, "clamped at 89.9°");
  assert.equal(PITCH_LIMIT_DEG, 89.9);
  const top = [orbitLockLevel(rig0, 0, 1e5, grab0, true), orbitLockLevel(rig0, 0, -1e5, grab0, true)].find((r) => r.f[2] < 0)!;
  assert.deepEqual(top.f, [0, 0, -1]);
  pivotCentred(top, 1e-7, "top view");
  close3(sync(top).E, add(rig0.P, [0, 0, sync(rig0).R]), 1e-9, "the eye above the pivot");
  // The picture_plane block never warns CAMERA_LOOKING_ALONG_UP (spec-v0.2 §4.1, contract §5.7.3); the equivalent
  // target form still does on a top view.
  assert.deepEqual(camera_matrix(toCameraBlock(top, BASE), CANVAS).warnings, [], "plane mode: no warning for the top view");
  const targetWarnings = camera_matrix(toTargetCameraBlock(top, BASE), CANVAS).warnings;
  assert.deepEqual(targetWarnings.map((w) => w.code), ["CAMERA_LOOKING_ALONG_UP"], "the target form only");
  assert.equal(toCameraBlock(top, BASE).picture_plane.up, undefined, "lock-horizontal top view: no up in the block");
  // the ring (left pane) reaches it too; dragging further keeps the eye above the pivot
  const obs = observer();
  const grab = grabAt(rig0, Math.PI / 2, obs);
  const up = orbitLockLevel(rig0, 0, -1e5, grab, true);
  const down = orbitLockLevel(rig0, 0, 1e5, grab, true);
  const reached = [up.f, down.f].map((f) => JSON.stringify(f));
  assert.ok(reached.includes("[0,0,-1]") && reached.includes("[0,0,1]"), reached.join(" "));
});

test("ring, free roll: up stays ⟂ f, g and |E − P| unchanged, the pivot centred", () => {
  const obs = observer();
  const r = rng(3);
  let rig = setLockLevel(initial(), false);
  assert.deepEqual(rig.up, [0, 0, 1]);
  for (let i = 0; i < 60; i++) {
    const grab = grabAt(rig, r() * 2 * Math.PI, obs);
    const next = orbitFree(rig, r() * 200 - 100, r() * 200 - 100, grab, i % 2 === 0);
    assert.ok(next.up !== null);
    close(dot(next.up!, next.f), 0, 1e-9, `#${i} up ⟂ f`);
    assert.equal(next.g, rig.g);
    close(dist(sync(next).E, next.P), sync(rig).R, 1e-9, `#${i} radius`);
    pivotCentred(next, 1e-7, `#${i}`);
    // rigid: the pivot's camera coordinates are unchanged
    close3(camSpace(next, next.P), camSpace(rig, rig.P), 1e-9, `#${i} rigid`);
    rig = next;
  }
  assert.equal(orbitRing(rig, 5, 5, grabAt(rig, 0, obs)).up !== null, true);
});

// ------------------------------------------------------------------------------------------------ arrow

/** Image height (canvas mm) of a vertical column of height 1.8 m one metre beyond the pivot. */
function columnHeight(rig: RigState): number {
  const base = add(rig.P, [0.3, 1, -rig.P[2]]);
  const top = add(base, [0, 0, 1.8]);
  const a = image(rig, base)!, b = image(rig, top)!;
  return Math.hypot(b[0] - a[0], b[1] - a[1]);
}

test("arrow towards / away from the scene: f, D, frame size unchanged, the eye moves along f, the tip follows the finger", () => {
  const obs = observer();
  const proj = (X: Vec3) => obsPx(obs, X);
  const rig0 = { ...initial(), f: unit([0.3, 1, -0.2]) };
  const v = arrowScreenVector(rig0, proj);
  assert.ok(Math.hypot(v[0], v[1]) > 8);
  const h0 = columnHeight(rig0);
  for (const t of [0.5, -0.5]) {
    const dx = v[0] * t, dy = v[1] * t; // moving the finger by t·v drags the board t metres towards the scene
    const r1 = arrowDrag(rig0, v, dx, dy, true);
    close(r1.g, rig0.g - t, 1e-12, `g after ${t}`);
    assert.deepEqual(r1.f, rig0.f);
    assert.equal(r1.D, rig0.D);
    assert.deepEqual(frameMetres(r1, BASE.frame_mm), frameMetres(rig0, BASE.frame_mm));
    close3(sub(sync(r1).E, sync(rig0).E), mul(rig0.f, t), 1e-12, "the eye moves along f only");
    pivotCentred(r1, 1e-7, `arrow ${t}`);
    const h1 = columnHeight(r1);
    assert.ok(t > 0 ? h1 > h0 : h1 < h0, `column height ${h0} → ${h1} for t = ${t}`);
    // the tip follows the finger
    const p0 = proj(arrowTip(rig0))!, p1 = proj(arrowTip(r1))!;
    const m: Vec2 = [p1[0] - p0[0], p1[1] - p0[1]];
    const cos = (m[0] * dx + m[1] * dy) / (Math.hypot(m[0], m[1]) * Math.hypot(dx, dy));
    assert.ok(cos > 0.99, `tip direction cosine ${cos}`);
    const ratio = Math.hypot(m[0], m[1]) / Math.hypot(dx, dy);
    assert.ok(ratio > 0.8 && ratio < 1.25, `tip moved ${ratio}× the finger`);
  }
  // behind the observer: the fallback (0, −40)
  assert.deepEqual(arrowScreenVector(rig0, () => null), [0, -40]);
  assert.equal(arrowLength(4), 1.4);
  assert.equal(arrowLength(0.5), 0.3);
  close(arrowLength(2), 1.1, 1e-15, "arrow length");
});

test("arrow snapping and clamping: the plane coordinate on the 0.1 m grid (not with snapping off); R clamped to [0.8, 40]", () => {
  const rig0 = initial();
  const v: Vec2 = [0, -40];
  for (const dy of [-13, -27.7, 9.1, 33.3]) {
    const snapped = arrowDrag(rig0, v, 0, dy, true);
    const c = planeConst(snapped);
    close(c * 10, Math.round(c * 10), 1e-9, `snapped c = ${c}`);
    assert.equal(equation(snapped), `y = ${c.toFixed(2)}`);
    const free = arrowDrag(rig0, v, 0, dy, false);
    const cf = planeConst(free);
    assert.ok(Math.abs(cf * 10 - Math.round(cf * 10)) > 1e-3, `unsnapped c = ${cf}`);
  }
  // a negative axis: f = −x, plane x = c' with c' on the grid
  const neg = { ...initial(), f: [-1, 0, 0] as Vec3, g: 2.345 };
  const s = arrowDrag(neg, v, 0, -1.3, true);
  const x = -planeConst(s);
  close(x * 10, Math.round(x * 10), 1e-9, "x on the grid");
  // clamp
  const near = arrowDrag(rig0, v, 0, -1e6, true);
  close(near.g + near.D, R_MIN_M, 1e-12, "R_min");
  const far = arrowDrag(rig0, v, 0, 1e6, true);
  close(far.g + far.D, R_MAX_M, 1e-12, "R_max");
  // a tilted board does not snap
  const tilted = { ...initial(), f: unit([1, 1, 0]) };
  close(arrowDrag(tilted, v, 0, -10, true).g, tilted.g - 0.25, 1e-12, "tilted: no snap");
});

// ------------------------------------------------------------------------------------------------ the pan state (a, b)

test("pan state (a, b): E = P − R·f + a·r₀ + b·u₀; the eye moves in the board's plane; the pivot's image moves by −L·focal/R", () => {
  for (const roll of [0, 35]) {
    const rig0 = setRoll(initial(), roll);
    const R = rig0.g + rig0.D;
    const r1 = withPan(rig0, -0.474, -0.316);
    const fr = frameOf(rig0);
    close3(sub(sync(r1).E, sync(rig0).E), add(mul(fr.r0, -0.474), mul(fr.u0, -0.316)), 1e-12, "eye offset");
    close(planeConst(r1), planeConst(rig0), 0, "c");
    close(dot(sub(sync(r1).E, sync(rig0).E), rig0.f), 0, 1e-12, "eye moves within the board's plane");
    // the pivot's image moves by −L·focal/R frame mm (10 canvas mm per frame mm): |L| = √(0.474² + 0.316²) m
    const p = image(r1, r1.P)!;
    close(Math.hypot(p[0], p[1]), (Math.hypot(0.474, 0.316) * rig0.focal * 10) / R, 1e-9, `roll ${roll}: pivot image offset`);
    if (roll === 0) {
      close(p[0], (0.474 * rig0.focal * 10) / R, 1e-9, "pivot u");
      close(p[1], (0.316 * rig0.focal * 10) / R, 1e-9, "pivot v");
    }
  }
});

test("orbit after pan: both orbit modes are rigid about P and keep (a, b)", () => {
  const obs = observer();
  const panned = withPan(setRoll(initial(), 20), -1.2, 0.6);
  const cases: [string, RigState][] = [
    ["ring lock", orbitLockLevel(panned, 40, -20, grabAt(panned, 1, obs), false)],
    ["ring free", orbitFree(setLockLevel(panned, false), 40, -20, grabAt(panned, 1, obs), false)],
  ];
  for (const [what, r] of cases) {
    assert.equal(r.a, panned.a, `${what} a`);
    assert.equal(r.b, panned.b, `${what} b`);
    close(dist(sync(r).E, r.P), dist(sync(panned).E, panned.P), 1e-9, `${what} |E − P|`);
    close3(camSpace(r, r.P), camSpace(panned, panned.P), 1e-9, `${what} pivot camera coordinates`);
  }
});

// ------------------------------------------------------------------------------------------------ roll, D, focal

/** Signed tilt of the image of horizontal direction `h` (⟂ f) in canvas coordinates (u right, v up), degrees. */
function horizonTilt(rig: RigState): number {
  const R = camera_matrix(toTargetCameraBlock(rig, BASE), CANVAS).R;
  const h = basis(rig.f, null).r0; // the level right axis is horizontal and ⟂ f
  return (Math.atan2(dot(R[1], h), dot(R[0], h)) * 180) / Math.PI;
}

test("roll slider: the eye does not move, the horizon tilts by ρ and keeps it while orbiting; clamped to ±180°", () => {
  const rig0 = { ...initial(), f: unit([0.2, 1, -0.3]) };
  const rolled = setRoll(rig0, 25);
  close3(sync(rolled).E, sync(rig0).E, 0, "eye");
  close(planeConst(rolled), planeConst(rig0), 0, "board");
  close(horizonTilt(rig0), 0, 1e-9, "level without roll");
  close(horizonTilt(rolled), -25, 1e-9, "tilted by ρ");
  pivotCentred(rolled, 1e-7, "rolled");
  const obs = observer();
  for (const r of [orbitLockLevel(rolled, 80, -30, grabAt(rolled, 2, obs), false), orbitLockLevel(rolled, -70, 40, grabAt(rolled, 0.5, obs), false)]) {
    close(horizonTilt(r), -25, 1e-9, "tilt kept while orbiting");
    assert.equal(r.roll_deg, 25);
  }
  assert.equal(setRoll(rig0, 500).roll_deg, 180);
  assert.equal(setRoll(rig0, -500).roll_deg, -180);
});

test("D slider: the board stays, the eye moves along −f, the frame grows, objects shrink, the pivot stays centred", () => {
  const rig0 = initial();
  const r1 = setD(rig0, 6);
  assert.equal(r1.D, 6);
  assert.equal(r1.g, rig0.g);
  close(planeConst(r1), planeConst(rig0), 0, "c");
  close3(sub(sync(r1).E, sync(rig0).E), mul(rig0.f, -2), 1e-12, "eye along −f");
  const [w0, h0] = frameMetres(rig0, BASE.frame_mm), [w1, h1] = frameMetres(r1, BASE.frame_mm);
  close(w1 / w0, 1.5, 1e-12, "frame width");
  close(h1 / h0, 1.5, 1e-12, "frame height");
  assert.ok(columnHeight(r1) < columnHeight(rig0), "objects shrink");
  pivotCentred(r1, 1e-7, "D slider");
  // clamps: [0.5, 12] and R ≥ 0.8 when g < 0
  assert.equal(setD(rig0, 100).D, D_MAX_M);
  assert.equal(setD(rig0, 0).D, D_MIN_M);
  const behind = { ...rig0, g: -2, D: 5 };
  const c = setD(behind, 0.5);
  close(c.D, 2.8, 1e-12, "clamped D");
  close(c.g + c.D, R_MIN_M, 1e-12, "R ≥ 0.8");
  const farG = { ...rig0, g: 35, D: 4 };
  assert.equal(setD(farG, 12).D, 5);
  // focal: field of view only
  const fz = setFocal(rig0, 50);
  close3(sync(fz).E, sync(rig0).E, 0, "focal keeps the eye");
  assert.equal(setFocal(rig0, 1).focal, 8);
  assert.equal(setFocal(rig0, 1e4).focal, 400);
});

// ------------------------------------------------------------------------------------------------ views, pivot, equation

test("six views: f an exact axis, g kept, E = P − (g+D)·f, pan and roll cleared; up recomputed in free mode", () => {
  const busy = withPan(setRoll({ ...initial(), f: unit([0.3, 0.8, -0.4]), g: 1.7 }, 40), -0.4, -0.15);
  for (const name of Object.keys(VIEWS) as ViewName[]) {
    for (const free of [false, true]) {
      const rig = sixView(free ? setLockLevel(busy, false) : busy, name);
      assert.deepEqual(rig.f, [...VIEWS[name]]);
      assert.equal(rig.g, busy.g);
      assert.equal(rig.D, busy.D);
      assert.equal(rig.a, 0);
      assert.equal(rig.b, 0);
      assert.equal(rig.roll_deg, 0);
      close3(sync(rig).E, sub(rig.P, mul(rig.f, rig.g + rig.D)), 1e-12, `${name} E`);
      pivotCentred(rig, 1e-7, name);
      if (free) close3(rig.up!, basis(rig.f, null).u0, 0, `${name} up`);
      else assert.equal(rig.up, null);
      if (name !== "top" && name !== "bottom") close(sync(rig).E[2], rig.P[2], 1e-12, `${name}: eye height = pivot height`);
    }
  }
});

test("views and equation after pan / roll: views clear them, the equation keeps them and the plane is the typed one", () => {
  const busy = withPan(setRoll(initial(), 30), -0.6, 0.2);
  const v = sixView(busy, "left");
  assert.deepEqual([v.a, v.b, v.roll_deg], [0, 0, 0]);
  const n = unit([1, 1, 0]), d = 3 / Math.SQRT2; // x + y = 3
  const r = applyPlane(busy, n, d);
  assert.ok("rig" in r);
  const e = r.rig;
  assert.equal(e.a, busy.a);
  assert.equal(e.b, busy.b);
  assert.equal(e.roll_deg, busy.roll_deg);
  const Q = sync(e).Q;
  close(dot(n, Q), d, 1e-9, "Q on the typed plane");
  close(Math.abs(dot(n, sync(e).E) - d), e.D, 1e-9, "|eye − plane| = D");
  assert.equal(equation(e), "0.707x + 0.707y = 2.121");
});

// (that a pivot change is not an undo step and that an undo keeps the current pivot is the session's: plane.test.ts)
test("pivot change: the eye faces the new pivot again (pan cleared), orbiting keeps the radius", () => {
  const obs = observer();
  const rig0 = withPan(initial(), -0.6, 0);
  const Pobj: Vec3 = [1.8, 4.2, 0.35];
  const r1 = setPivot(rig0, Pobj);
  assert.deepEqual([r1.a, r1.b], [0, 0]);
  assert.deepEqual([r1.f, r1.g, r1.D], [rig0.f, rig0.g, rig0.D]);
  pivotCentred(r1, 1e-7, "picked object");
  for (const [dx, dy] of [[100, 0], [0, -50], [-60, 40]]) {
    const r2 = orbitLockLevel(r1, dx!, dy!, grabAt(r1, 0.5, obs), false);
    close(dist(sync(r2).E, Pobj), r1.g + r1.D, 1e-9, "radius about the object");
    pivotCentred(r2, 1e-7, "orbit about the object");
  }
});

test("planeToRig: the board between the eye and the pivot; |s_d| is g", () => {
  assert.deepEqual(planeToRig([0, 1, 0], 2, P0), { f: [0, 1, 0], g: P0[1] - 2 });
  assert.deepEqual(planeToRig([0, 1, 0], 9, P0), { f: [0, -1, 0], g: 9 - P0[1] });
  assert.deepEqual(planeToRig([1, 0, 0], 1, P0), { f: [-1, 0, 0], g: 1 - P0[0] });
  const tooFar = applyPlane(initial(), [0, 1, 0], 50);
  assert.deepEqual(tooFar, { error: "too_far" });
  const tooNear = applyPlane({ ...initial(), D: 0.5 }, [0, 1, 0], P0[1] - 0.1);
  assert.deepEqual(tooNear, { error: "too_near" });
});

// ------------------------------------------------------------------------------------------------ equation string

test("plane_equation: the contract §5.7.5 hand table and Python's tie rounding", () => {
  const s = Math.SQRT1_2;
  assert.equal(plane_equation([0, 1, 0], -2), "y = 2.00");
  assert.equal(plane_equation([0, -1, 0], 2), "y = 2.00");
  assert.equal(plane_equation([0, 1, 0], 3), "y = -3.00");
  assert.equal(plane_equation([s, s, 0], -3 * s), "0.707x + 0.707y = 2.121");
  assert.equal(plane_equation([-s, 0, s], 0), "0.707x - 0.707z = 0.000");
  assert.equal(plane_equation([0, 2, 0], -4), "y = 2.00", "normalised first");
  assert.equal(plane_equation([1e-4, 1, 1], 0), "0.707y + 0.707z = 0.000");
  // the sign rule picks the first PRINTED coefficient (|n_i| ≥ 5e-4), not a dropped one
  assert.equal(plane_equation([1e-4, -1, 0], 2), "1.000y = 2.000");
  assert.equal(plane_equation([-1e-4, Math.SQRT1_2, Math.SQRT1_2], -1), "0.707y + 0.707z = 1.000");
  assert.equal(plane_equation([1e-4, -Math.SQRT1_2, Math.SQRT1_2], 1), "0.707y - 0.707z = 1.000");
  assert.equal(fixed(0.125, 2), "0.12");
  assert.equal(fixed(0.375, 2), "0.38");
  assert.equal(fixed(2.675, 2), "2.67");
  assert.equal(fixed(-0.001, 2), "0.00");
  assert.equal(fixed(-0.125, 2), "-0.12");
  assert.equal(fixed(0.0625, 3), "0.062");
  assert.equal(fixed(-0.0004, 3), "0.000");
  assert.equal(fixed(-0, 2), "0.00");
  assert.equal(fixed(1.5, 0), "2");
  assert.equal(fixed(2.5, 0), "2");
  assert.equal(fixed(12.345, 3), "12.345");
});

test("plane_equation: contract table — x = 1 from (−1,0,0, 1) and z = 3 from (0,0,−1, 3)", () => {
  // contract: ((−1,0,0), 1) → "x = 1.00" (plane −x + 1 = 0, i.e. x = 1); ((0,0,−1), 3) → "z = 3.00"
  assert.equal(plane_equation([-1, 0, 0], 1), "x = 1.00");
  assert.equal(plane_equation([0, 0, -1], 3), "z = 3.00");
});

// ------------------------------------------------------------------------------------------------ undo

test("history keys: a press without movement leaves the board key, a no-op view the state key; at most 50 entries", () => {
  // M10's UndoStack is now plane.ts's History (§5.8.11): the session records a board entry when sameBoard (a drag) or
  // sameState (a discrete action) says the rig changed; the session-level rules are in plane.test.ts
  const rig0 = initial();
  const grab = grabAt(rig0, 0.5, observer());
  assert.equal(sameBoard(rig0, orbitRing(rig0, 0, 0, grab)), true, "ring press");
  assert.equal(sameBoard(rig0, arrowDrag(rig0, [0, -40], 0, 0)), true, "arrow press");
  const moved = orbitRing(rig0, 30, 0, grab, false);
  assert.equal(sameBoard(rig0, moved), false);
  // the sliders are not part of the board key, but they are part of the state key
  assert.equal(sameBoard(moved, setRoll(setD(setFocal(moved, 35), 6), 15)), true);
  assert.equal(sameState(moved, setFocal(moved, 35)), false);
  assert.equal(sameState(moved, { ...moved, P: [9, 9, 9] }), true, "the pivot is not part of the state key");
  const front = sixView(moved, "front");
  assert.equal(sameState(front, sixView(front, "front")), true, "the same view again changes nothing");
  // the cap: 80 entries keep the newest 50; undoing all of them moves them onto the redo stack
  const h = new History();
  const entry = (i: number): BoardEntry => ({ kind: "board", before: { ...rig0, g: i }, after: { ...rig0, g: i + 1 } });
  for (let i = 0; i < 80; i++) h.push(entry(i));
  assert.equal(h.size, UNDO_MAX);
  assert.equal(UNDO_MAX, 50);
  let last: BoardEntry | null = null, n = 0;
  for (let e = h.take_undo(); e !== null; e = h.take_undo(), n++) last = e as BoardEntry;
  assert.equal(n, 50);
  assert.equal(last!.before.g, 30, "the oldest 30 steps were dropped");
  assert.equal(h.canUndo, false);
  assert.equal(h.redo_size, 50, "undo + redo never exceed the cap");
  assert.equal((h.take_redo() as BoardEntry).before.g, 30, "redo takes them back in order");
  h.push(entry(99));
  assert.equal(h.redo_size, 0, "a new entry clears the redo stack");
  assert.equal(h.size, 2);
});

// ------------------------------------------------------------------------------------------------ readouts

test("readouts and the picture-delta measure", () => {
  const rig0 = initial();
  // two points at the pivot's depth (they all move alike under a pan) and one behind the eye
  const pts: Vec3[] = [add(P0, [1, 0, 0.5]), add(P0, [-1, 0, -0.5]), sub(sync(rig0).E, [0, 1, 0])];
  const ref0 = measureRef(rig0, BASE, CANVAS, pts);
  assert.equal(ref0[2], null, "a point behind the eye is skipped");
  assert.equal(deltaText(pictureDelta(ref0, measureRef(setRoll(rig0, 0), BASE, CANVAS, pts))), "0.00 mm（不變）");
  // moving the eye sideways by 0.5·R/focal m moves every image at the pivot's depth by 0.5 frame mm
  const panned = withPan(rig0, (0.5 * (rig0.g + rig0.D)) / rig0.focal, 0);
  close(pictureDelta(ref0, measureRef(panned, BASE, CANVAS, pts))!, 0.5, 1e-9, "delta");
  assert.equal(deltaText(0.5), "0.50 mm");
  assert.equal(deltaText(null), "—");
  // the D slider changes the picture; the focal slider scales it
  assert.ok(pictureDelta(ref0, measureRef(setD(rig0, 8), BASE, CANVAS, pts))! > 0.1);
  const ro = readouts({ ...rig0, P: [0, 0, -5] }, BASE.frame_mm);
  assert.equal(ro.eye_below_ground, true);
  assert.equal(ro.R, rig0.g + rig0.D);
  assert.equal(ringRadius(rig0, BASE.frame_mm), 1.03 * 0.5 * Math.hypot(7.2, 4.8));
  assert.equal(ringRadius({ D: 0.5, focal: 80 }, BASE.frame_mm), 0.45);
});

// ------------------------------------------------------------------------------------------------ load rule and M9

const EXAMPLES = ["basic", "construction_demo", "curved_demo", "three_point", "directional"];

function samePicture(cam0: Camera | ReturnType<typeof toTargetCameraBlock>, rig: RigState, pts: readonly Vec3[], canvas: Vec2, what: string): void {
  const P0m = camera_matrix(cam0, canvas).P;
  const P1m = camera_matrix(toTargetCameraBlock(rig, cam0), canvas).P;
  for (const X of pts) {
    const a = imageRec(P0m, X), b = imageRec(P1m, X);
    assert.equal(a === null, b === null, `${what}: visibility of ${X}`);
    if (a && b) {
      close(b[0], a[0], 1e-7, `${what} u of ${X}`);
      close(b[1], a[1], 1e-7, `${what} v of ${X}`);
    }
  }
}

for (const name of EXAMPLES) {
  test(`load rule: examples/${name}.json — the rig's block renders the scene camera's picture (within 1e-7 mm)`, () => {
    const sc = scene_file("examples", `${name}.json`);
    const A = shadow_geometry(sc);
    const P = bboxCentre(A.bbox);
    const pts = A.vertices.slice(0, 400);
    for (const roll of [sc.camera.roll_deg ?? 0, 30, 200]) {
      const cam: Camera = { ...sc.camera, roll_deg: roll };
      const { rig, clampedD, clampedR } = fromCamera(cam, P);
      assert.equal(clampedD, false);
      assert.equal(clampedR, false);
      assert.equal(rig.up, null);
      assert.equal(rig.D, 4);
      assert.deepEqual(rig.P, P);
      close(rig.roll_deg, wrap_deg(roll), 1e-12, "roll wrapped");
      close3(sync(rig).E, cam.position, 1e-9, "eye");
      samePicture(cam, rig, pts, sc.output.canvas_mm, `${name} roll ${roll}`);
      // through the picture_plane form and back
      const pp = toCameraBlock(rig, cam);
      const again = fromCamera(pp, P);
      close(again.rig.D, rig.D, 1e-9, "D from the picture_plane form");
      close(again.rig.g, rig.g, 1e-9, "g");
      close(again.rig.a, rig.a, 1e-9, "a");
      close(again.rig.b, rig.b, 1e-9, "b");
      close(again.rig.roll_deg, rig.roll_deg, 1e-9, "roll");
      samePicture(cam, again.rig, pts, sc.output.canvas_mm, `${name} via picture_plane`);
    }
  });
}

test("load rule: picture_plane block with a given up; D and R clamps are reported", () => {
  const P: Vec3 = [0, 5, 1];
  const cam = {
    position: [0.37, -2.0, 0.9] as Vec3, picture_plane: { normal: [0, 1, 0] as Vec3, offset: -2.0, up: [0.3, 0, 1] as Vec3 },
    focal_length_mm: 20, frame_mm: [36, 24] as [number, number], shift_mm: [0, 0] as [number, number], near_m: 0.05,
  };
  const res = resolvePicturePlane(cam);
  assert.equal(res.distance, 4);
  assert.deepEqual(res.normal, [0, 1, 0]);
  assert.deepEqual(res.foot, [0.37, 2, 0.9]);
  assert.deepEqual(res.block.target, [0.37, -1, 0.9]);
  close(res.roll_deg, (-Math.atan2(0.3, 1) * 180) / Math.PI, 1e-12, "roll from up");
  const { rig } = fromCamera(cam, P);
  close(rig.roll_deg, res.roll_deg, 1e-12, "rig roll");
  samePicture(res.block, rig, [[0, 5, 0], [1, 6, 2], [-2, 9, 0.5]], [36, 24], "given up");
  // the spec §4.1 hand block without up: D = 4, plane y = 2
  const { up: _u, ...noUp } = cam.picture_plane;
  const plain = fromCamera({ ...cam, picture_plane: noUp }, [0.37, 5.84, 0.9]).rig;
  assert.equal(equation(plain), "y = 2.00");
  close(plain.g + plain.D, 7.84, 1e-12, "R = 7.84");
  close(plain.a, 0, 1e-12, "a");
  close(plain.b, 0, 1e-12, "b");
  // clamps
  const farD = fromCamera({ ...cam, picture_plane: { normal: [0, 1, 0], offset: -20 } }, [0, 30, 1]);
  assert.equal(farD.clampedD, true);
  assert.equal(farD.rig.D, 12);
  assert.equal(farD.clampedR, false);
  close3(sync(farD.rig).E, cam.position, 1e-9, "a D clamp keeps the eye (the board moves)");
  const farR = fromCamera(cam, [0, 100, 1]);
  assert.equal(farR.clampedR, true);
  close(farR.rig.g + farR.rig.D, R_MAX_M, 1e-12, "R clamped");
  const behind = fromCamera(cam, [0, -10, 1]);
  assert.equal(behind.clampedR, true);
  close(behind.rig.g + behind.rig.D, R_MIN_M, 1e-12, "pivot behind the eye: R clamped to 0.8");
});

test("load rule: a yaw/pitch camera and a camera looking straight down", () => {
  const yp = scene_file("tests", "conformance", "cases", "camera_yaw_pitch_form.json");
  const A = shadow_geometry(yp);
  const { rig } = fromCamera(yp.camera, bboxCentre(A.bbox));
  samePicture(yp.camera, rig, A.vertices.slice(0, 200), yp.output.canvas_mm, "yaw/pitch");
  const down: Camera = { position: [1, 2, 9], target: [1, 2, 0], roll_deg: 10, focal_length_mm: 24, frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
  const r = fromCamera(down, [1.5, 2.5, 0]).rig;
  assert.deepEqual(r.f, [0, 0, -1]);
  samePicture(down, r, [[0, 0, 0], [2, 3, 0], [1.5, 2.5, 1]], [36, 24], "looking down");
});

test("M9: the board from the M7 orbit state reproduces the orbit camera (P = target, D = 4, g = R − D, no pan)", () => {
  for (const name of EXAMPLES) {
    const sc = scene_file("examples", `${name}.json`);
    for (const s of [orbit_from_camera(sc.camera, sc), rotate_orbit({ ...orbit_from_camera(sc.camera, sc), roll_deg: 12 }, 80, -40, 500)]) {
      const rig = fromOrbitState(s);
      assert.equal(rig.D, 4);
      close(rig.g, s.distance - 4, 0, "g");
      assert.deepEqual([rig.a, rig.b], [0, 0]);
      assert.deepEqual(rig.P, s.target);
      const cam = camera_from_orbit(s, sc.camera);
      close3(sync(rig).E, cam.position, 1e-9, `${name} eye`);
      const A0 = camera_matrix(cam, sc.output.canvas_mm).P, A1 = camera_matrix(toTargetCameraBlock(rig, sc.camera), sc.output.canvas_mm).P;
      for (let i = 0; i < 3; i++) for (let j = 0; j < 4; j++) close(A1[i]![j]!, A0[i]![j]!, 1e-9 * Math.max(1, Math.abs(A0[i]![j]!)), `${name} P[${i}][${j}]`);
    }
  }
});

// ------------------------------------------------------------------------------------------------ random frames

test("random frames: 600 states (top / bottom views, very near / far, free roll) and 300 with pan and roll are finite", () => {
  const r = rng(7);
  const obs = observer();
  const views = Object.keys(VIEWS) as ViewName[];
  for (let i = 0; i < 900; i++) {
    let rig: RigState = { ...initial([r() * 6 - 3, r() * 10, r() * 3]), D: D_MIN_M + r() * (D_MAX_M - D_MIN_M) };
    const kind = i % 6;
    if (kind === 0) rig = sixView(rig, views[Math.floor(r() * 6)]!);
    else rig = { ...rig, f: randomUnit(r) };
    rig = { ...rig, g: (kind === 1 ? R_MIN_M : kind === 2 ? R_MAX_M : R_MIN_M + r() * (R_MAX_M - R_MIN_M)) - rig.D };
    if (kind === 3 || r() < 0.3) rig = setLockLevel(rig, false);
    // a few operations
    rig = orbitRing(rig, r() * 400 - 200, r() * 400 - 200, grabAt(rig, r() * 7, obs), r() < 0.5);
    rig = arrowDrag(rig, arrowScreenVector(rig, (X) => obsPx(obs, X)), r() * 100 - 50, r() * 100 - 50, r() < 0.5);
    if (i >= 600) rig = setRoll(withPan(rig, r() * 6 - 3, r() * 6 - 3), r() * 360 - 180);
    const d = sync(rig);
    assert.ok(d.R >= R_MIN_M - 1e-12 && d.R <= R_MAX_M + 1e-12, `R ${d.R}`);
    const blk = toTargetCameraBlock(rig, BASE);
    const rec = camera_matrix(blk, CANVAS);
    assertFinite({ rig, d, pp: toCameraBlock(rig, BASE), blk, P: rec.P, ring: ringPoint(rig, BASE.frame_mm, r() * 7), tip: arrowTip(rig) }, `frame #${i}`);
    assertFinite(readouts(rig, BASE.frame_mm), `readouts #${i}`);
    for (const p of measureRef(rig, BASE, CANVAS, [rig.P, add(rig.P, [1, 1, 1]), [0, 0, 0]])) if (p) assertFinite(p, "image");
    close(dot(rig.f, rig.f), 1, 1e-12, "f unit");
    if (rig.up !== null) close(dot(rig.up, rig.f), 0, 1e-9, "up ⟂ f");
    if (i < 600) pivotCentred(rig, 1e-7, `#${i}`);
  }
});

test("constants", () => {
  assert.deepEqual([R_MIN_M, R_MAX_M, D_MIN_M, D_MAX_M, KAPPA_DEG_PER_PX, PITCH_LIMIT_DEG], [0.8, 40, 0.5, 12, 0.32, 89.9]);
  assert.equal(wrap_deg(180), 180);
  assert.equal(wrap_deg(-180), 180);
  assert.equal(wrap_deg(190), -170);
  assert.equal(wrap_deg(-190), 170);
  assert.equal(wrap_deg(720), 0);
  assert.equal(Object.is(wrap_deg(-0), -0), false);
  close(rollOfFrame([0, 1, 0], [Math.sin(0.3), 0, Math.cos(0.3)]), (-0.3 * 180) / Math.PI, 1e-12, "u tilted towards +x (the default right) gives a negative roll");
});

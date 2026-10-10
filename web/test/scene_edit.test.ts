/** Tests of the M11 scene-editing maths (`web/src/scene_edit.ts`; contract §5.8.1, §5.8.3, §5.8.4, §5.8.8–§5.8.11,
 * §5.8.17 rows "horizontal drag", "grazing fallback", "vertical handle", "ids", "placement and avoidance", "undo and
 * redo" and "random stress"). */

import assert from "node:assert/strict";
import { readFileSync, readdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { build_object, dumps, load_scene, render, shadow_geometry } from "castplane";
import type { Scene, SceneObject, Vec2, Vec3 } from "castplane";

import { PRESETS, make_object } from "../src/library.js";
import { OBSERVER_NEAR_M, initial_view, observer_project_with } from "../src/observer.js";
import { PLANE_GRID_M as RIG_GRID, UNDO_MAX, basis } from "../src/rig.js";
import {
  DRAG_MAX_T_M, GRAZE_DEG, GROUND_SNAP_M, HANDLE_LEN_K, HANDLE_LEN_MAX_M, HANDLE_LEN_MIN_M, HANDLE_MAX_M, HANDLE_MIN_PX,
  NOTICE_KEEP_ONE, PLACE_GAP_M, PLACE_MAX_T_M, PLACE_MIN_F_Z, PLACE_STEP_EXTRA_M, PLACE_TRIES, PLANE_GRID_M, PREVIEW_MS,
  ROUND_M, TARGET_MS, XY_LIMIT_M, Z_LIMIT_M, add_object, add_with_entry, apply_entry, box_centre, can_delete,
  candidate_bbox, delete_with_entry, display_name, drag_begin, drag_position, finish_coord, finish_position, finish_z,
  focal_px, footprints_overlap, handle_L36, index_of, insert_object, invert_entry, label_text, line_param, move_entry,
  move_object, next_id, place_object, place_target, remove_object, round4, snap_grid, step_direction, undo_entry,
  used_ids, vertical_begin, vertical_handle, vertical_z, with_position, world_bbox,
} from "../src/scene_edit.js";
import type { Box, CameraFrame, ObjectEntry, Ray } from "../src/scene_edit.js";
import { observer_frame } from "../src/selection.js";

// web/build/test/scene_edit.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const read_json = (...p: string[]): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, ...p), "utf-8"));

/** The bundled examples the core loads directly (a mesh example that needs `expand_scene` is skipped). */
function examples(): [string, Record<string, unknown>][] {
  const out: [string, Record<string, unknown>][] = [];
  for (const f of readdirSync(resolve(ROOT, "examples")).filter((f) => f.endsWith(".json")).sort()) {
    const data = read_json("examples", f);
    try {
      load_scene(data);
      out.push([f, data]);
    } catch {
      /* needs the loader */
    }
  }
  return out;
}
function cases(): [string, Record<string, unknown>][] {
  const dir = resolve(ROOT, "tests", "conformance", "cases");
  return readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) => [f, read_json("tests", "conformance", "cases", f)]);
}

const DEG = Math.PI / 180;
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const norm = (p: readonly number[]): number => Math.sqrt(dot(p, p));
const unit = (p: readonly number[]): Vec3 => mul(p, 1 / norm(p));

/** A seeded generator (mulberry32). */
function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** A camera frame looking along `f` with roll `rho` (§2.2 convention, as `rig.frameOf`). */
function rolled_frame(pos: Vec3, f: Vec3, rho: number, H = 600): CameraFrame {
  const { r0, u0 } = basis(f, null);
  const c = Math.cos(rho), s = Math.sin(rho);
  return { pos, f, r: add(mul(r0, c), mul(u0, s)), u: add(mul(r0, -s), mul(u0, c)), f_px: focal_px(H) };
}

/** The ray from the frame's position through the world point `X`. */
const ray_to = (cam: { pos: Vec3 }, X: readonly number[]): Ray => ({ e: cam.pos, d: unit(sub(X, cam.pos)) });

/** The image of `X` (px offsets from the centre, y up) in a frame. */
function image(cam: CameraFrame, X: readonly number[]): Vec2 {
  const q = sub(X, cam.pos), z = dot(q, cam.f);
  return [(cam.f_px * dot(q, cam.r)) / z, (cam.f_px * dot(q, cam.u)) / z];
}

function on_grid(v: number): boolean {
  const dec = String(v).split(".")[1];
  return dec === undefined || dec.length <= 1;
}

// ------------------------------------------------------------------------------------------------ constants and rounding

test("constants follow §5.8.15", () => {
  assert.equal(GRAZE_DEG, 5);
  assert.equal(DRAG_MAX_T_M, 200);
  assert.equal(XY_LIMIT_M, 50);
  assert.equal(Z_LIMIT_M, 50);
  assert.equal(GROUND_SNAP_M, 0.02);
  assert.equal(PLANE_GRID_M, 0.1);
  assert.equal(PLANE_GRID_M, RIG_GRID);
  assert.equal(ROUND_M, 1e-4);
  assert.deepEqual([HANDLE_LEN_K, HANDLE_LEN_MIN_M, HANDLE_LEN_MAX_M], [0.6, 0.3, 1.0]);
  assert.equal(HANDLE_MIN_PX, 36);
  assert.equal(HANDLE_MAX_M, 1e3);
  assert.equal(PLACE_MIN_F_Z, Math.sin(2 * DEG));
  assert.equal(PLACE_MAX_T_M, 40);
  assert.deepEqual([PLACE_GAP_M, PLACE_STEP_EXTRA_M, PLACE_TRIES], [0.1, 0.2, 8]);
  assert.deepEqual([PREVIEW_MS, TARGET_MS], [50, 33]);
  assert.equal(UNDO_MAX, 50);
  assert.equal(NOTICE_KEEP_ONE, "場景至少要有一個物件");
});

test("snap_grid / round4 never leave float noise; finish_coord clamps after rounding and never prints -0", () => {
  assert.equal(snap_grid(0.3), 0.3);
  assert.equal(snap_grid(0.29), 0.3);
  assert.equal(snap_grid(0.1 + 0.2), 0.3);
  assert.notEqual(Math.round(0.3 / 0.1) * 0.1, 0.3); // the formula the contract forbids
  assert.equal(round4(1.23456), 1.2346);
  assert.ok(Object.is(finish_coord(-0.04, 0, true), 0));
  assert.ok(Object.is(finish_coord(-0.00004, 0, false), 0));
  assert.ok(Object.is(finish_coord(-0, 0, false), 0));
  // the clamp range is [min(−50, v₀), max(50, v₀)]
  assert.equal(finish_coord(73.2, 3, true), 50);
  assert.equal(finish_coord(-73.2, 3, false), -50);
  assert.equal(finish_coord(80, 60, true), 60); // loaded outside: not pushed further out
  assert.equal(finish_coord(55, 60, true), 55); // but pulled inwards
  // the grid exception: an off-grid v₀ outside ±50 pushed outwards with snapping on finishes at v₀ itself
  assert.equal(finish_coord(50.2, 50.03, true), 50.03);
  assert.equal(finish_coord(-50.2, -50.03, true), -50.03);
  // the accuracy bound of round4 (contract example)
  assert.ok(Math.abs(round4(-45.90005) - -45.90005) <= 5e-5 + 1e-12);
});

// ------------------------------------------------------------------------------------------------ horizontal drag (§5.8.3)

test("horizontal drag: the grabbed point stays under the pointer within 1e-6 m (observer and random rolled frames)", () => {
  const R = rng(11);
  let normal = 0;
  for (let i = 0; i < 400; i++) {
    let cam: CameraFrame;
    const h0: Vec3 = [(R() - 0.5) * 20, (R() - 0.5) * 20, R() * 3];
    if (i % 2 === 0) {
      const view = { target: [h0[0], h0[1], 0] as Vec3, dist: 4 + R() * 40, az_deg: R() * 360, el_deg: 6 + R() * 79 };
      cam = observer_frame(view, 300 + R() * 600);
    } else {
      const pos: Vec3 = [h0[0] + (R() - 0.5) * 30, h0[1] + (R() - 0.5) * 30, h0[2] + 1 + R() * 20];
      cam = rolled_frame(pos, unit(sub(h0, pos)), (R() - 0.5) * 2 * Math.PI);
    }
    const p0: Vec3 = [h0[0] + (R() - 0.5) * 1.6, h0[1] + (R() - 0.5) * 1.6, (R() - 0.3) * 2];
    const st = drag_begin(p0, h0, ray_to(cam, h0), cam);
    if (st.fallback) continue;
    normal++;
    for (let j = 0; j < 4; j++) {
      const s: Vec3 = [(R() - 0.5) * 8, (R() - 0.5) * 8, 0];
      const xy = drag_position(st, ray_to(cam, add(h0, s)), 999, -999); // (dx, dy) is unused in the normal mode
      if (xy === null) continue;
      assert.ok(Math.abs(xy[0] - (p0[0] + s[0])) < 1e-6 && Math.abs(xy[1] - (p0[1] + s[1])) < 1e-6, `case ${i}: ${xy} vs ${add(p0, s)}`);
      for (const snap of [true, false]) {
        const fin = finish_position(xy, p0, snap);
        assert.ok(Object.is(fin[2], p0[2]), "z_b is copied bit for bit");
        for (let k = 0; k < 2; k++) {
          const v = fin[k]!;
          assert.ok(!Object.is(v, -0));
          const inside = Math.abs(xy[k]!) < 49.9;
          if (!inside) continue;
          if (snap) assert.ok(Math.abs(v * 10 - Math.round(v * 10)) < 1e-9 && on_grid(v), `${v} not on the 0.1 m grid`);
          else assert.ok(Math.abs(v - xy[k]!) <= 5e-5 + 1e-12, `${v} vs ${xy[k]}`);
        }
      }
    }
  }
  assert.ok(normal > 300, `only ${normal} normal-mode cases`);
});

test("horizontal drag: z_b and rotation_deg bit-identical; the record is new and shares the other keys", () => {
  const obj: SceneObject = { id: "w", type: "prism", polygon: [[0, 0], [2, 0], [2, 0.2], [0.2, 0.2], [0.2, 1.5], [0, 1.5]], height: 1.1,
    transform: { position: [0.1, 0.2, 0.30000000000000004], rotation_deg: [0, 0, 17.5] } };
  const xy: Vec2 = [3.04449, -7.95551];
  const fin = finish_position(xy, obj.transform.position, false);
  const moved = with_position(obj, fin);
  assert.notEqual(moved, obj);
  assert.equal(moved.polygon, obj.polygon);
  assert.equal(moved.transform.rotation_deg, obj.transform.rotation_deg);
  assert.ok(Object.is(moved.transform.position[2], 0.30000000000000004));
  assert.deepEqual(moved.transform.position, [3.0445, -7.9555, 0.30000000000000004]);
  assert.deepEqual(obj.transform.position, [0.1, 0.2, 0.30000000000000004], "the input is not mutated");
  const objs = [obj, { ...obj, id: "v" }];
  const out = move_object(objs, 0, fin);
  assert.notEqual(out, objs);
  assert.equal(out[1], objs[1]);
  assert.equal(objs[0], obj);
});

test("horizontal drag: the mode is decided at pointer-down; the 200 m and t ≤ 0 guards skip the update", () => {
  const view = { target: [0, 0, 0] as Vec3, dist: 12, az_deg: 55, el_deg: 28 };
  const cam = observer_frame(view, 600);
  const h0: Vec3 = [0.3, -0.2, 0.5];
  const st = drag_begin([0, 0, 0], h0, ray_to(cam, h0), cam);
  assert.equal(st.fallback, false);
  // a later ray almost parallel to the plane: t > 200 → skipped (the mode does not switch to the fallback)
  const graze: Ray = { e: cam.pos, d: unit([cam.f[0], cam.f[1], -1e-4]) };
  assert.equal(drag_position(st, graze, 10, 0), null);
  assert.equal(st.fallback, false);
  // a ray pointing up from above the plane: t < 0 → skipped
  assert.equal(drag_position(st, { e: cam.pos, d: unit([cam.f[0], cam.f[1], 0.5]) }, 10, 0), null);
  // parallel ray: t infinite → skipped
  assert.equal(drag_position(st, { e: cam.pos, d: unit([cam.f[0], cam.f[1], 0]) }, 10, 0), null);
  // t = 199 is accepted, t = 201 skipped
  for (const [t, ok] of [[199, true], [201, false]] as const) {
    const sinp = (st.z_g - cam.pos[2]) / t;
    const c = Math.sqrt(1 - sinp * sinp);
    const d: Vec3 = [c * Math.SQRT1_2, c * Math.SQRT1_2, sinp];
    assert.equal(drag_position(st, { e: cam.pos, d }, 0, 0) !== null, ok, `t = ${t}`);
  }

  // a fallback start keeps the fallback when later rays are steep
  const low = observer_frame({ target: [0, 0, 0], dist: 12, az_deg: 55, el_deg: 2 }, 600);
  const g0: Vec3 = add(low.pos, mul(unit(add(low.f, mul(low.u, 0.02))), 10));
  const sf = drag_begin([g0[0], g0[1], 0], g0, ray_to(low, g0), low);
  assert.equal(sf.fallback, true);
  const steep: Ray = { e: low.pos, d: unit([0.1, 0.1, -1]) };
  const a = drag_position(sf, steep, 12, 0)!, b = drag_position(sf, ray_to(low, g0), 12, 0)!;
  assert.deepEqual(a, b, "the fallback ignores the ray");
});

test("grazing fallback: finite, k·(Δx'·r_g + Δv'·f_g) with the camera depth, signs, |det| = 1 at every roll", () => {
  const R = rng(5);
  const seen = { all: 0, zero: 0, ninety: 0 };
  for (let i = 0; i < 200; i++) {
    const pos: Vec3 = [(R() - 0.5) * 10, (R() - 0.5) * 10, 0.5 + R() * 3];
    const az = R() * 2 * Math.PI, el = (R() - 0.5) * 2 * 4 * DEG; // |f_z| < sin 4°
    const f: Vec3 = [Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el)];
    const rho = i < 40 ? 0 : i < 80 ? 30 * DEG : i < 120 ? 90 * DEG : (R() - 0.5) * 2 * Math.PI;
    const cam = rolled_frame(pos, f, rho);
    // a grabbed point near the axis (within the grazing band)
    const off = mul(add(mul(cam.r, R() - 0.5), mul(cam.u, (R() - 0.5) * 0.05)), 0.3);
    const dirh = unit(add(f, off));
    const h0 = add(pos, mul(dirh, 2 + R() * 20));
    const ray0 = ray_to(cam, h0);
    if (!(Math.abs(ray0.d[2]) < Math.sin(GRAZE_DEG * DEG))) continue;
    const p0: Vec3 = [h0[0] + 0.2, h0[1] - 0.1, 0];
    const st = drag_begin(p0, h0, ray0, cam);
    assert.equal(st.fallback, true);
    const k = dot(sub(h0, pos), f) / cam.f_px;
    assert.ok(Math.abs(st.k - k) <= 1e-15 * Math.max(1, k));
    const { r0, u0 } = basis(f, null);
    const r_g: Vec2 = [r0[0], r0[1]];
    const fh = Math.hypot(f[0], f[1]);
    const f_g: Vec2 = [f[0] / fh, f[1] / fh];
    const dx = (R() - 0.5) * 400, dy = (R() - 0.5) * 400;
    const xy = drag_position(st, ray0, dx, dy)!;
    assert.ok(Number.isFinite(xy[0]) && Number.isFinite(xy[1]));
    const ddx = dx * Math.cos(rho) + dy * Math.sin(rho), ddv = dx * Math.sin(rho) - dy * Math.cos(rho);
    const ex = p0[0] + k * (ddx * r_g[0] + ddv * f_g[0]), ey = p0[1] + k * (ddx * r_g[1] + ddv * f_g[1]);
    assert.ok(Math.abs(xy[0] - ex) < 1e-9 && Math.abs(xy[1] - ey) < 1e-9, `${xy} vs ${[ex, ey]}`);
    // the 2 × 2 map from (Δx, Δy) to (along r_g, along f_g), in units of k
    const m = (ddx_: number, ddy_: number): Vec2 => {
      const q = drag_position(st, ray0, ddx_, ddy_)!;
      const v: Vec2 = [(q[0] - p0[0]) / k, (q[1] - p0[1]) / k];
      return [v[0] * r_g[0] + v[1] * r_g[1], v[0] * f_g[0] + v[1] * f_g[1]];
    };
    const c1 = m(1, 0), c2 = m(0, 1);
    assert.ok(Math.abs(Math.abs(c1[0] * c2[1] - c1[1] * c2[0]) - 1) < 1e-12, `det at roll ${rho}`);
    if (rho === 0) {
      assert.ok(c1[0] > 0.999 && Math.abs(c1[1]) < 1e-9, "right drag moves along +r_g");
      assert.ok(c2[1] < -0.999 && Math.abs(c2[0]) < 1e-9, "down drag moves along −f_g");
    }
    if (rho === 90 * DEG) {
      assert.ok(c1[1] > 0.999 && Math.abs(c1[0]) < 1e-9, "ρ = 90°: right drag moves along +f_g");
      assert.ok(c2[0] > 0.999 && Math.abs(c2[1]) < 1e-9, "ρ = 90°: down drag moves along +r_g");
    }
    assert.ok(r0 !== undefined && u0 !== undefined);
    seen.all++;
    if (rho === 0) seen.zero++;
    if (rho === 90 * DEG) seen.ninety++;
  }
  assert.ok(seen.all > 100 && seen.zero > 20 && seen.ninety > 20, JSON.stringify(seen));
});

test("grazing fallback at ρ = 0: a right drag moves the image of an off-axis grabbed point by exactly Δx px", () => {
  const cam = observer_frame({ target: [0, 0, 0], dist: 12, az_deg: 55, el_deg: 1 }, 640);
  let n = 0;
  for (const theta of [15, 30]) {
    for (const alpha of [0, 40, 90, 160, 250]) {
      const dir = unit(add(mul(cam.f, Math.cos(theta * DEG)),
        mul(add(mul(cam.r, Math.cos(alpha * DEG)), mul(cam.u, Math.sin(alpha * DEG) * 0.03)), Math.sin(theta * DEG))));
      const h0 = add(cam.pos, mul(dir, 9));
      const st = drag_begin([h0[0], h0[1], 0], h0, ray_to(cam, h0), cam);
      if (!st.fallback) continue;
      for (const dx of [7, -33, 120]) {
        const xy = drag_position(st, ray_to(cam, h0), dx, 0)!;
        const h1: Vec3 = [h0[0] + (xy[0] - h0[0]), h0[1] + (xy[1] - h0[1]), h0[2]];
        const i0 = image(cam, h0), i1 = image(cam, h1);
        assert.ok(Math.abs(i1[0] - i0[0] - dx) <= 1e-9 * Math.abs(dx), `θ ${theta}: ${i1[0] - i0[0]} vs ${dx}`);
        assert.ok(Math.abs(i1[1] - i0[1]) <= 1e-9 * Math.abs(dx));
        n++;
      }
    }
  }
  assert.ok(n >= 24, `only ${n} cases`);
});

test("horizontal drag at the default observer view: every press takes the normal mode (top edge 8° below the horizon)", () => {
  const view = initial_view();
  const cam = observer_frame(view, 500);
  const top = unit(add(cam.f, mul(cam.u, Math.tan(20 * DEG))));
  assert.ok(Math.abs(top[2]) > Math.sin(GRAZE_DEG * DEG));
  assert.ok(Math.abs(Math.asin(-top[2]) / DEG - 8) < 1e-9);
});

// ------------------------------------------------------------------------------------------------ vertical handle (§5.8.4)

test("line_param equals an independent 2 × 2 least-squares solve; orthogonality residuals; degenerate rays skip", () => {
  const R = rng(3);
  let n = 0;
  for (let i = 0; i < 500; i++) {
    const e: Vec3 = [(R() - 0.5) * 40, (R() - 0.5) * 40, (R() - 0.2) * 20];
    const d = unit([R() - 0.5, R() - 0.5, (R() - 0.5) * 1.6]);
    const a: Vec3 = [(R() - 0.5) * 40, (R() - 0.5) * 40, 0];
    const w0 = sub(a, e);
    // normal equations of [d, −ẑ]·[t, s] = a − e
    const A11 = dot(d, d), A12 = -d[2], A22 = 1, b1 = dot(d, w0), b2 = -w0[2];
    const det = A11 * A22 - A12 * A12;
    const t_ref = (b1 * A22 - A12 * b2) / det, s_ref = (A11 * b2 - A12 * b1) / det;
    const lp = line_param({ e, d }, a);
    if (t_ref <= 0) {
      assert.equal(lp, null);
      continue;
    }
    n++;
    assert.ok(lp !== null);
    const tol = 1e-9 * Math.max(1, norm(w0));
    assert.ok(Math.abs(lp.s - s_ref) <= tol && Math.abs(lp.t - t_ref) <= tol, `${[lp.s, lp.t]} vs ${[s_ref, t_ref]}`);
    const gap = sub(add(a, [0, 0, lp.s]), add(e, mul(d, lp.t)));
    assert.ok(Math.abs(dot(gap, d)) <= tol && Math.abs(gap[2]) <= tol);
  }
  assert.ok(n > 100);
  assert.equal(line_param({ e: [0, 0, 5], d: [0, 0, -1] }, [1, 0, 0]), null, "vertical ray");
  assert.equal(line_param({ e: [0, 0, 5], d: unit([1e-4, 0, -1]) }, [1, 0, 0]), null, "nearly vertical ray");
  assert.equal(line_param({ e: [0, 0, 5], d: [1, 0, 0] }, [-3, 0, 0]), null, "closest point behind the eye");
});

test("vertical drag: only z_b changes; clamp to [min(0, z₀), max(50, z₀)]; the ground is sticky in every mode", () => {
  const cam = observer_frame(initial_view(), 600);
  const box: Box = [[-0.5, -0.5, 0], [0.5, 0.5, 1]];
  const tip: Vec3 = [0, 0, 1.6];
  const p0: Vec3 = [0.123456789, -0.987654321, 0];
  const st = vertical_begin(p0, box, ray_to(cam, tip))!;
  assert.ok(st !== null);
  const at = (dz: number, snap: boolean): Vec3 | null => vertical_z(st, ray_to(cam, add(tip, [0, 0, dz])), snap);
  const up = at(0.73, false)!;
  assert.ok(Object.is(up[0], p0[0]) && Object.is(up[1], p0[1]));
  assert.ok(Math.abs(up[2] - 0.73) <= 5e-5 + 1e-9);
  assert.equal(at(0.73, true)![2], 0.7);
  assert.equal(at(-5, false)![2], 0, "clamped at the ground");
  assert.equal(at(80, true)![2], 50, "clamped at 50 m");
  for (const snap of [true, false]) {
    assert.ok(Object.is(at(0.015, snap)![2], 0), "ground snap (Alt included)");
    assert.ok(Object.is(at(-0.015, snap)![2], 0));
  }
  // a buried start: not pushed to 0 at pointer-down; pulled up it may cross 0
  const buried: Vec3 = [0, 0, -0.7331];
  const sb = vertical_begin(buried, [[-0.5, -0.5, -0.7331], [0.5, 0.5, 0.2669]], ray_to(cam, [0, 0, 0.9]))!;
  assert.equal(vertical_z(sb, ray_to(cam, [0, 0, 0.9]), false)![2], -0.7331);
  assert.equal(vertical_z(sb, ray_to(cam, [0, 0, 0.9 - 3]), false)![2], -0.7331, "not pushed further down");
  assert.equal(finish_z(-0.8, -0.7331, true), -0.7331, "grid exception for z");
  assert.equal(finish_z(-0.75, -0.7331, true), -0.7, "inwards from a buried start: on the grid");
  assert.equal(finish_z(50.3, 50.03, true), 50.03);
  assert.equal(finish_z(-0.01, -0.5, false), 0);
  // a degenerate start does nothing
  const above = { e: [0, 0, 10] as Vec3, d: [0, 0, -1] as Vec3 };
  assert.equal(vertical_begin(p0, box, above), null);
  assert.equal(vertical_z(st, above, false), null, "a nearly vertical ray skips the update");
});

test("vertical drag: the handle's line (box centre) keeps the tip under the pointer for an off-centre anchor", () => {
  const wedge: SceneObject = { id: "w", type: "prism", polygon: [[0, 0], [1.6, 0], [1.6, 0.9]], height: 0.8,
    transform: { position: [2, 3, 0], rotation_deg: [0, 0, 0] } };
  const box = world_bbox(wedge, build_object(wedge));
  const c = box_centre(box);
  assert.ok(Math.hypot(c[0] - 2, c[1] - 3) > 0.5, "the anchor is off the box centre");
  let drift = 0;
  for (const el of [12, 28, 45, 70]) {
    const cam = observer_frame({ target: [2, 3, 0], dist: 6, az_deg: 35, el_deg: el }, 600);
    const h = vertical_handle(box, cam);
    const st = vertical_begin(wedge.transform.position, box, ray_to(cam, h.tip))!;
    // move the pointer so that the ray passes through the tip raised by 0.4321 m
    const dz = 0.4321;
    const p = vertical_z(st, ray_to(cam, add(h.tip, [0, 0, dz])), false)!;
    assert.ok(Math.abs(p[2] - dz) <= 5e-5 + 1e-9, `elevation ${el}: ${p[2]}`);
    const tip1 = add(h.tip, [0, 0, p[2]]);
    const i_ptr = image(cam, add(h.tip, [0, 0, dz])), i_tip = image(cam, tip1);
    assert.ok(Math.hypot(i_ptr[0] - i_tip[0], i_ptr[1] - i_tip[1]) < 0.05, "the tip stays under the pointer");
    // on the anchor's line the tip would drift
    const dz_anchor = line_param(ray_to(cam, add(h.tip, [0, 0, dz])), [2, 3, 0])!.s - line_param(ray_to(cam, h.tip), [2, 3, 0])!.s;
    const i_anchor = image(cam, add(h.tip, [0, 0, dz_anchor]));
    drift = Math.max(drift, Math.hypot(i_ptr[0] - i_anchor[0], i_ptr[1] - i_anchor[1]));
  }
  assert.ok(drift > 1, `the anchor's line would keep the tip within ${drift} px`);
});

test("handle length: L₃₆ projects to exactly 36 px; the cap and the near-plane limit apply when m → 0", () => {
  const R = rng(9);
  let exact = 0;
  for (const el of [0, 28, 45, -1, -2, -3]) {
    for (let i = 0; i < 40; i++) {
      const e = el >= 0 ? el : 85 * R();
      const view = { target: [(R() - 0.5) * 6, (R() - 0.5) * 6, R()] as Vec3, dist: 4 + R() * 50, az_deg: R() * 360, el_deg: e };
      const cam = observer_frame(view, 600);
      const lo: Vec3 = [(R() - 0.5) * 8, (R() - 0.5) * 8, R() * 0.5];
      const box: Box = [lo, add(lo, [0.1 + R(), 0.1 + R(), 0.05 + R() * 2])];
      const h = vertical_handle(box, cam);
      const first = Math.min(Math.max(0.6 * h.height, 0.3), 1.0);
      assert.equal(h.len, Math.max(first, h.L36));
      assert.deepEqual(h.base, [(box[0][0] + box[1][0]) / 2, (box[0][1] + box[1][1]) / 2, box[1][2]]);
      assert.deepEqual(h.tip, [h.base[0], h.base[1], h.base[2] + h.len]);
      const tip_depth = dot(sub(h.tip, cam.pos), cam.f);
      if (h.L36 > first && h.L36 < HANDLE_MAX_M && tip_depth > 2 * OBSERVER_NEAR_M) {
        // the handle is the L₃₆ segment: its image (the pane's own projection) is 36 px
        const pa = observer_project_with(cam, 800, 600, h.base)!, pb = observer_project_with(cam, 800, 600, h.tip)!;
        const px = Math.hypot(pa[0] - pb[0], pa[1] - pb[1]);
        assert.ok(Math.abs(px - 36) <= 1e-9, `elevation ${e}: ${px} px`);
        exact++;
      } else if (h.L36 > 0 && h.L36 < HANDLE_MAX_M && tip_depth > 2 * OBSERVER_NEAR_M) {
        // the first term wins: the L₃₆ segment itself is still exactly 36 px
        const t = add(h.base, [0, 0, h.L36]);
        const pa = observer_project_with(cam, 800, 600, h.base)!, pb = observer_project_with(cam, 800, 600, t)!;
        assert.ok(Math.abs(Math.hypot(pa[0] - pb[0], pa[1] - pb[1]) - 36) <= 1e-9);
        assert.ok(h.len >= h.L36);
        exact++;
      }
    }
  }
  assert.ok(exact > 60, `only ${exact} exact cases`);
  // m → 0, looking straight down at the base: the near-plane limit
  const down: CameraFrame = { pos: [1, 2, 10], r: [1, 0, 0], u: [0, 1, 0], f: [0, 0, -1], f_px: 800 };
  assert.ok(Math.abs(handle_L36([1, 2, 1], down) - (9 - OBSERVER_NEAR_M)) < 1e-12);
  // m → 0, looking straight up at the base: no finite length reaches 36 px → the cap
  const upcam: CameraFrame = { pos: [1, 2, -10], r: [1, 0, 0], u: [0, -1, 0], f: [0, 0, 1], f_px: 800 };
  assert.equal(handle_L36([1, 2, 1], upcam), HANDLE_MAX_M);
  // the base behind the camera: L₃₆ = 0 and the first term is used
  const behind: CameraFrame = { pos: [0, 0, 1], r: [1, 0, 0], u: [0, 0, 1], f: [0, -1, 0], f_px: 800 };
  assert.equal(handle_L36([0, 5, 1], behind), 0);
  assert.equal(vertical_handle([[-0.1, 4.9, 0], [0.1, 5.1, 1]], behind).len, 0.6);
  // the simpler 36·depth/f_px is short at 28°: about 32.5 px
  const cam28 = observer_frame({ target: [0, 0, 0], dist: 12, az_deg: 55, el_deg: 28 }, 600);
  const b0: Vec3 = [0, 0, 0];
  const depth = dot(sub(b0, cam28.pos), cam28.f);
  const simple = add(b0, [0, 0, (36 * depth) / cam28.f_px]);
  const s0 = observer_project_with(cam28, 800, 600, b0)!, s1 = observer_project_with(cam28, 800, 600, simple)!;
  assert.ok(Math.abs(Math.hypot(s0[0] - s1[0], s0[1] - s1[1]) - 32.5) < 0.1);
});

// ------------------------------------------------------------------------------------------------ ids (§5.8.9)

test("next_id: the smallest free n over objects, lights and receivers; a freed number is reused; reserved words", () => {
  assert.equal(next_id("box", new Set()), "box_1");
  const scene = {
    objects: [{ id: "box_1" }], lights: [{ id: "box_2" }], receivers: [{ id: "box_3" }],
  } as unknown as Pick<Scene, "objects" | "lights" | "receivers">;
  assert.equal(next_id("box", used_ids(scene)), "box_4");
  assert.equal(next_id("box", ["box_1", "box_3"]), "box_2");
  assert.equal(next_id("box", ["Box_1"]), "box_1", "case-sensitive");
  assert.equal(next_id("prism", ["prism_1", "prism_2", "box_1"]), "prism_3");
  // freed and reused
  const used = new Set(["box_1", "box_2"]);
  used.delete("box_1");
  assert.equal(next_id("box", used), "box_1");
  assert.throws(() => next_id("a.b", []));
  assert.throws(() => next_id("", []));
  for (const prefix of ["box", "cylinder", "sphere", "cone", "prism"]) {
    const u = new Set<string>();
    for (let n = 1; n <= 100; n++) {
      const id = next_id(prefix, u);
      assert.equal(id, `${prefix}_${n}`);
      assert.ok(!id.includes(".") && !["hidden", "core", "umbra"].includes(id));
      u.add(id);
    }
  }
});

test("display names: a side table; the id when there is none", () => {
  const names = new Map([["box_1", "木箱"]]);
  assert.equal(display_name("box_1", names), "木箱");
  assert.equal(display_name("crate", names), "crate");
  assert.equal(label_text("box_1", names), "木箱（box_1）");
  assert.equal(label_text("crate", names), "crate");
});

// ------------------------------------------------------------------------------------------------ placement (§5.8.8)

test("placement target: the ground point of the line of sight when f_z < −sin 2° and 0 < t ≤ 40, else under P", () => {
  const P: Vec3 = [3, 4, 1.2];
  const E: Vec3 = [0, 0, 1.5];
  const f = unit([0, 5, -0.5]);
  const T = place_target(E, f, P);
  assert.equal(T[2], 0);
  assert.ok(Math.abs(T[1] - 15) < 1e-12 && T[0] === 0);
  const flat = unit([0, 1, -Math.tan(1.9 * DEG)]);
  assert.deepEqual(place_target(E, flat, P), [3, 4, 0]);
  assert.deepEqual(place_target(E, unit([0, 1, 0.3]), P), [3, 4, 0]);
  const far = unit([0, 1, -Math.tan(2.05 * DEG)]); // t ≈ 41.9 m > 40
  assert.ok(-E[2] / far[2] > 40);
  assert.deepEqual(place_target(E, far, P), [3, 4, 0]);
  assert.deepEqual(place_target([0, 0, -1], unit([0, 1, -1]), P), [3, 4, 0], "eye below the ground: t < 0");
  const fifty = unit([0, 1, -Math.tan(3 * DEG)]);
  const t = -E[2] / fifty[2];
  assert.ok(t > 0 && t <= 40);
  assert.ok(Math.abs(place_target(E, fifty, P)[1] - t * fifty[1]) < 1e-12);
});

test("placement avoidance: steps of w_u + 0.2 along r₀, at most 8, the last position kept; snap then ±50 clamp", () => {
  const cube = make_object(PRESETS[0]!, "box_9", [0, 0, 0]);
  const E: Vec3 = [0, 0, 1.5], P: Vec3 = [0, 0, 0];
  const f = unit([0, 5, -0.5]); // T = (0, 15, 0)
  const r0 = basis(f, null).r0;
  // free spot
  let pl = place_object(cube, { E, f, P, r0, existing: [], snap: true });
  assert.deepEqual(pl.position, [0, 15, 0]);
  assert.equal(pl.steps, 0);
  // one obstacle on T: one step of 1.0 + 0.2 along u = (1, 0, 0)
  const obstacle: Box = [[-0.3, 14.7, 0], [0.3, 15.3, 5]];
  pl = place_object(cube, { E, f, P, r0, existing: [obstacle], snap: true });
  assert.equal(pl.steps, 1);
  assert.deepEqual(pl.position, [1.2, 15, 0]);
  assert.ok(!pl.overlapping);
  // a gap of exactly 0.1 is not an overlap; just below is
  assert.equal(footprints_overlap([[0, 0, 0], [1, 1, 1]], [[1.1, 0, 0], [2, 1, 1]]), false);
  assert.equal(footprints_overlap([[0, 0, 0], [1, 1, 1]], [[1.09, 0, 0], [2, 1, 1]]), true);
  assert.equal(footprints_overlap([[0, 0, 0], [1, 1, 1]], [[0.5, 0.5, 9], [2, 2, 10]]), true, "heights ignored");
  // a long wall: 8 moves, then the last position is kept
  const wall: Box = [[-1, 14, 0], [40, 16, 3]];
  pl = place_object(cube, { E, f, P, r0, existing: [wall], snap: false });
  assert.equal(pl.steps, 8);
  assert.ok(pl.overlapping);
  assert.deepEqual(pl.position, [round4(8 * 1.2), 15, 0]);
  // the width along a diagonal u
  const rd = unit([1, 1, 0]);
  const wood = make_object(PRESETS[1]!, "box_9", [0, 0, 0]); // 1.2 × 0.9
  pl = place_object(wood, { E, f, P, r0: rd, existing: [[[-0.1, 14.9, 0], [0.1, 15.1, 1]]], snap: false });
  const wu = Math.SQRT1_2 * 1.2 + Math.SQRT1_2 * 0.9 + 0.2;
  assert.equal(pl.steps, 1);
  assert.deepEqual(pl.position, [round4(wu * Math.SQRT1_2), round4(15 + wu * Math.SQRT1_2), 0]);
  // the step direction ignores a vertical r₀
  assert.deepEqual(step_direction([0, 0, 1]), [1, 0, 0]);
  // snap then clamp to ±50
  pl = place_object(cube, { E: [60.04, 0, 1], f: [0, 0, -1], P: [60.04, 0, 0], r0: [1, 0, 0], existing: [], snap: true });
  assert.deepEqual(pl.position, [50, 0, 0]);
  pl = place_object(cube, { E: [0.04, -0.06, 1], f: [0, 0, -1], P, r0: [1, 0, 0], existing: [], snap: true });
  assert.ok(Object.is(pl.position[0], 0) && Object.is(pl.position[1], -0.1));
  pl = place_object(cube, { E: [-0.00001, 0, 1], f: [0, 0, -1], P, r0: [1, 0, 0], existing: [], snap: false });
  assert.ok(Object.is(pl.position[0], 0), "no -0");
});

test("closed-form footprints equal build_object(...).bbox within 5 mm for every preset", () => {
  for (const preset of PRESETS) {
    for (const pos of [[0, 0, 0], [1.37, -2.5, 0], [-12, 30.1, 0.4]] as Vec3[]) {
      const obj = make_object(preset, "x_1", pos);
      const cf = candidate_bbox(obj), ref = build_object(obj).bbox;
      for (let k = 0; k < 3; k++) {
        assert.ok(Math.abs(cf[0][k]! - ref[0][k]!) <= 5e-3 && Math.abs(cf[1][k]! - ref[1][k]!) <= 5e-3, `${preset.name} axis ${k}`);
      }
    }
  }
  // a rotated or mesh object falls back to the port's record
  const rot: SceneObject = { id: "r", type: "box", size: [2, 1, 1], transform: { position: [0, 0, 0], rotation_deg: [0, 0, 90] } };
  const bb = candidate_bbox(rot);
  assert.ok(Math.abs(bb[1][0] - 0.5) < 1e-12 && Math.abs(bb[1][1] - 1) < 1e-12);
});

// ------------------------------------------------------------------------------------------------ arrays and entries (§5.8.10, §5.8.11)

const render_text = (scene: Scene, objects: readonly SceneObject[]): { json: string; svg: string } => {
  const s = load_scene({ ...scene, objects });
  const out = render(s);
  return { json: dumps(out.geometry), svg: out.svg };
};

test("array operations return new arrays and keep the order of the others", () => {
  const a = { id: "a" } as SceneObject, b = { id: "b" } as SceneObject, c = { id: "c" } as SceneObject;
  const objs = [a, b];
  const added = add_object(objs, c);
  assert.deepEqual(added.map((o) => o.id), ["a", "b", "c"]);
  assert.deepEqual(objs.map((o) => o.id), ["a", "b"]);
  assert.deepEqual(remove_object(added, 1).map((o) => o.id), ["a", "c"]);
  assert.deepEqual(insert_object(objs, 1, c).map((o) => o.id), ["a", "c", "b"]);
  assert.equal(index_of(added, "c"), 2);
  assert.equal(index_of(added, "z"), -1);
});

test("keep one object: a delete is refused with one object left (meshes count)", () => {
  const mesh = { id: "m", type: "mesh" } as SceneObject;
  assert.equal(can_delete([mesh]), false);
  assert.equal(delete_with_entry([mesh], 0), null);
  assert.equal(can_delete([mesh, mesh]), true);
  assert.equal(delete_with_entry([mesh, { id: "n" } as SceneObject], 2), null, "out of range");
});

test("entries: add, delete and move are one entry each; undo / redo restore and the selection follows the object", () => {
  const scene = load_scene(read_json("examples", "basic.json"));
  const base = scene.objects;
  const names = new Map<string, string>();
  const tile = PRESETS[1]!;
  const obj = make_object(tile, next_id(tile.prefix, used_ids(scene)), [0.4, 3.1, 0]);
  assert.equal(obj.id, "box_1");
  const added = add_with_entry(base, obj, tile.name, names);
  assert.deepEqual(added.entry, { kind: "add", index: 2, obj, name: "木箱" });
  assert.equal(added.selected, "box_1");
  assert.equal(added.names.get("box_1"), "木箱");
  // undo of the add removes it and clears the selection; redo puts it back and selects it
  const u = undo_entry(added.objects, added.entry, added.names)!;
  assert.deepEqual(u.objects, base);
  assert.equal(u.selected, null);
  assert.equal(u.names.has("box_1"), false);
  const r = apply_entry(u.objects, added.entry, u.names)!;
  assert.equal(r.objects[2], obj);
  assert.equal(r.selected, "box_1");
  assert.equal(r.names.get("box_1"), "木箱");
  // delete carries the name; its undo restores the same record at the original index and selects it
  const del = delete_with_entry(r.objects, 2, r.names)!;
  assert.deepEqual(del.entry, { kind: "delete", index: 2, obj, name: "木箱" });
  assert.equal(del.names.has("box_1"), false);
  assert.equal(del.selected, null);
  const ud = undo_entry(del.objects, del.entry, del.names)!;
  assert.equal(ud.objects[2], obj);
  assert.equal(ud.selected, "box_1");
  assert.equal(ud.names.get("box_1"), "木箱");
  // a move: before / after by reference; a no-change move records nothing
  const before = ud.objects[0]!;
  const after = with_position(before, [2.5, 4, 0]);
  assert.equal(move_entry(0, before, with_position(before, before.transform.position)), null);
  const mv = move_entry(0, before, after)!;
  const moved = apply_entry(ud.objects, mv, ud.names)!;
  assert.equal(moved.objects[0], after);
  assert.equal(moved.selected, before.id);
  const back = undo_entry(moved.objects, mv, moved.names)!;
  assert.equal(back.objects[0], before);
  assert.equal(back.selected, before.id);
  // invert twice is the identity
  for (const e of [added.entry, del.entry, mv] as ObjectEntry[]) assert.deepEqual(invert_entry(invert_entry(e)), e);
});

test("entries: the LIFO checks reject an entry applied to the wrong array", () => {
  const a = { id: "a", transform: { position: [0, 0, 0] } } as unknown as SceneObject;
  const b = { id: "b", transform: { position: [1, 0, 0] } } as unknown as SceneObject;
  const a2 = with_position(a, [5, 0, 0]);
  const mv = move_entry(0, a, a2)!;
  assert.equal(undo_entry([a, b], mv), null, "undo of a move needs objects[index] === after");
  assert.equal(apply_entry([a2, b], mv), null, "redo of a move needs objects[index] === before");
  const del = { kind: "delete", index: 1, obj: b, name: null } as const;
  assert.equal(undo_entry([a, b], del), null, "the id is already there");
  assert.equal(undo_entry([], del), null, "index > length");
  assert.equal(apply_entry([b, a], del), null, "objects[index].id differs");
  const add = { kind: "add", index: 1, obj: b, name: null } as const;
  assert.equal(undo_entry([a], add), null);
});

test("undo of a delete is byte-identical (document and SVG) on the examples and every multi-object v8 case", () => {
  let checked = 0, differs = 0;
  for (const [name, data] of [...examples(), ...cases()]) {
    const scene = load_scene(data);
    if (scene.objects.length < 2) continue;
    const ref = render_text(scene, scene.objects);
    for (const index of new Set([0, 1, scene.objects.length - 1])) {
      const del = delete_with_entry(scene.objects, index)!;
      const back = undo_entry(del.objects, del.entry)!;
      assert.equal(back.objects[index], scene.objects[index]);
      const got = render_text(scene, back.objects);
      assert.equal(got.json, ref.json, `${name} [${index}]: document text`);
      assert.equal(got.svg, ref.svg, `${name} [${index}]: SVG text`);
      // redo, then undo again: still identical
      const again = undo_entry(apply_entry(back.objects, del.entry)!.objects, del.entry)!;
      assert.equal(render_text(scene, again.objects).svg, ref.svg);
      checked++;
      // the end-of-list insert differs whenever the order changes
      if (index < scene.objects.length - 1) {
        const tail = add_object(del.objects, scene.objects[index]!);
        if (render_text(scene, tail).json !== ref.json) differs++;
      }
    }
  }
  assert.ok(checked >= 30, `only ${checked} cases`);
  assert.ok(differs > 0, "re-inserting at the end must change the bytes of some multi-object scene");
});

// ------------------------------------------------------------------------------------------------ random stress (§5.8.17)

test("random stress: 200 steps of add, delete, move, undo and redo keep every number finite and the ids unique", () => {
  const R = rng(20251010);
  const scene = load_scene(read_json("examples", "basic.json"));
  const view = initial_view();
  const H = 600;
  const cam = observer_frame(view, H);
  const E = scene.camera.position;
  const f = unit(sub(scene.camera.target as Vec3, E));
  const r0 = basis(f, null).r0;
  let objects: SceneObject[] = scene.objects.slice();
  let names = new Map<string, string>();
  const undo: ObjectEntry[] = [], redo: ObjectEntry[] = [];
  const push = (e: ObjectEntry): void => {
    undo.push(e);
    if (undo.length + redo.length > UNDO_MAX) undo.shift();
    redo.length = 0;
  };
  const finite = (xs: readonly number[], what: string): void => {
    for (const x of xs) assert.ok(Number.isFinite(x), `${what}: ${xs}`);
  };
  for (let step = 0; step < 200; step++) {
    const op = R();
    const A = shadow_geometry(load_scene({ ...scene, objects }));
    if (op < 0.22 && objects.length < 14) {
      const preset = PRESETS[Math.floor(R() * PRESETS.length)]!;
      const id = next_id(preset.prefix, used_ids({ ...scene, objects }));
      const cand = make_object(preset, id, [0, 0, 0]);
      const P: Vec3 = [(R() - 0.5) * 6, 2 + R() * 8, 0];
      const pl = place_object(cand, { E, f: R() < 0.5 ? f : [0, 0, -1], P, r0, existing: A.objects.map((o) => o.bbox), snap: R() < 0.5 });
      finite(pl.position, "placement");
      const res = add_with_entry(objects, make_object(preset, id, pl.position), preset.name, names);
      objects = res.objects;
      names = res.names;
      push(res.entry);
    } else if (op < 0.37) {
      const res = delete_with_entry(objects, Math.floor(R() * objects.length), names);
      if (res !== null) {
        objects = res.objects;
        names = res.names;
        push(res.entry);
      } else assert.equal(objects.length, 1);
    } else if (op < 0.7) {
      const index = Math.floor(R() * objects.length);
      const obj = objects[index]!;
      const box = world_bbox(obj, A.objects[index]);
      const hnd = vertical_handle(box, cam);
      finite([...hnd.base, ...hnd.tip, hnd.len], "handle");
      let pos: Vec3 | null;
      if (R() < 0.6) {
        const c = box_centre(box);
        const h0: Vec3 = [c[0], c[1], box[1][2]];
        const st = drag_begin(obj.transform.position, h0, { e: cam.pos, d: unit(sub(h0, cam.pos)) }, cam);
        const target: Vec3 = [h0[0] + (R() - 0.5) * 30, h0[1] + (R() - 0.5) * 30, h0[2]];
        const xy = drag_position(st, { e: cam.pos, d: unit(sub(target, cam.pos)) }, (R() - 0.5) * 300, (R() - 0.5) * 300);
        pos = xy === null ? null : finish_position(xy, obj.transform.position, R() < 0.5);
      } else {
        const st = vertical_begin(obj.transform.position, box, { e: cam.pos, d: unit(sub(hnd.tip, cam.pos)) });
        pos = st === null ? null : vertical_z(st, { e: cam.pos, d: unit(sub(add(hnd.tip, [0, 0, (R() - 0.4) * 6]), cam.pos)) }, R() < 0.5);
      }
      if (pos !== null) {
        finite(pos, "move");
        const after = with_position(obj, pos);
        const e = move_entry(index, obj, after);
        if (e !== null) {
          objects = apply_entry(objects, e, names)!.objects;
          push(e);
        }
      }
    } else if (op < 0.88) {
      const e = undo.pop();
      if (e !== undefined) {
        const res = undo_entry(objects, e, names);
        assert.ok(res !== null, `LIFO violated at step ${step}`);
        objects = res.objects;
        names = res.names;
        redo.push(e);
      }
    } else {
      const e = redo.pop();
      if (e !== undefined) {
        const res = apply_entry(objects, e, names);
        assert.ok(res !== null, `LIFO violated at step ${step}`);
        objects = res.objects;
        names = res.names;
        undo.push(e);
      }
    }
    assert.ok(undo.length + redo.length <= UNDO_MAX);
    const ids = objects.map((o) => o.id);
    assert.equal(new Set(ids).size, ids.length, "unique ids");
    assert.ok(objects.length >= 1);
    for (const o of objects) finite(o.transform.position, o.id);
    for (const id of names.keys()) assert.ok(ids.includes(id), "names only for present objects");
    // the drag-mode frame: validate, A, B, C and the SVG with umbra and hidden lines off
    const s = load_scene({ ...scene, objects });
    const out = render(s, undefined, false, null, false);
    const json = dumps(out.geometry);
    assert.ok(!/NaN|Infinity/.test(json) && !/NaN|Infinity/.test(out.svg), `non-finite output at step ${step}`);
    finite([...s.camera.position, ...(s.camera.target ?? [])], "camera block");
  }
});

/** Camera model of the port (contract §2.2, §5.4.13): the roll vector, `det R = −1`, yaw/pitch == target form,
 * near / rectangle clips, horizon; plus the construction helpers of §2.7. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { camera_matrix, clip_polygon_rect_h, clip_segment_near, divide, horizon, nu, project, vanishing_point } from "../src/camera.js";
import { clip_segments_uv, covering_segments, extended_segments, self_check, special_point_image } from "../src/construction.js";
import { validate_camera } from "../src/scene.js";
import { degrees } from "../src/transform.js";
import type { Mat3 } from "../src/types.js";

function det3(R: Mat3): number {
  const [[a, b, c], [d, e, f], [g, h, i]] = R;
  return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
}

test("roll vector: +10° roll moves the image of a point above the target to u = 35·sin10°·0.2 > 0", () => {
  const cam = camera_matrix(validate_camera({
    position: [0, 0, 1.5], target: [0, 5, 1.5], roll_deg: 10, focal_length_mm: 35, frame_mm: [36, 24],
  }), [36, 24]);
  const [u, v] = divide(project(cam, [0, 5, 2.5, 1]));
  assert.ok(Math.abs(u - 1.2155372436685123) <= 1e-9, String(u));
  assert.ok(u > 0);
  assert.ok(v > 0);
  assert.ok(Math.abs(det3(cam.R) + 1) <= 1e-12);
});

test("yaw/pitch form equals the target form (camera of analytic_unit_box_point_light_overhead)", () => {
  const base = { position: [4, -8, 5], focal_length_mm: 35, frame_mm: [36, 24] };
  const a = camera_matrix(validate_camera({ ...base, target: [0, 0, 0.5] }), [360, 240]);
  const f = a.forward;
  assert.deepEqual(f.map((x) => Math.round(x * 1e15) / 1e15), [-0.399500935551138, 0.799001871102276, -0.44943855249503]);
  const yaw = degrees(Math.atan2(-f[0], f[1])), pitch = degrees(Math.asin(f[2]));
  assert.ok(Math.abs(yaw - 26.56505117707799) <= 1e-9);
  assert.ok(Math.abs(pitch - -26.7076677665586) <= 1e-9);
  const b = camera_matrix(validate_camera({ ...base, yaw_deg: yaw, pitch_deg: pitch }), [360, 240]);
  for (let i = 0; i < 3; i++) {
    for (let j = 0; j < 4; j++) {
      const x = a.P[i]![j]!, y = b.P[i]![j]!;
      assert.ok(Math.abs(x - y) <= 1e-12 * Math.max(1, Math.abs(x)), `P[${i}][${j}] ${x} vs ${y}`);
    }
  }
  assert.ok(Math.abs(det3(a.R) + 1) <= 1e-12);
});

test("near functional, near clip, rectangle clip, horizon", () => {
  const cam = camera_matrix(validate_camera({
    position: [0, 0, 1.5], target: [0, 5, 1.0], focal_length_mm: 35, frame_mm: [36, 24],
  }), [273, 182]);
  const f = cam.forward;
  assert.ok(Math.abs(nu(cam, [0.05 * f[0], 0.05 * f[1], 1.5 + 0.05 * f[2], 1])) < 1e-12);
  const seg = clip_segment_near(cam, [0, -5, 0, 1], [0, 5, 0, 1]);
  assert.ok(seg !== null && Math.abs(nu(cam, seg[0])) <= 1e-12);
  assert.equal(clip_segment_near(cam, [0, -5, 0, 1], [1, -5, 0, 1]), null);
  const big = clip_polygon_rect_h([[-1e4, -1e4, 1], [1e4, -1e4, 1], [1e4, 1e4, 1], [-1e4, 1e4, 1]], cam.rect);
  assert.equal(big.length, 4);
  const hz = horizon(cam);
  assert.ok(hz.v_mm !== null && hz.segment !== null);
  assert.equal(hz.vanishing_points.x, null);
  const vy = vanishing_point(cam, [0, 1, 0]);
  assert.ok(vy !== null && Math.abs(vy[1] - (hz.v_mm as number)) <= 1e-9);
});

test("construction helpers: covering / extended segments, rectangle clip of mm segments, self-check", () => {
  const [s] = covering_segments([0, 10], [[0, 0]], [[0, 5]]);
  assert.deepEqual(s, [[0, 0], [0, 10]]);
  const [t] = covering_segments([[0, -1]], [[0, 0]], [[0, 0]]);
  assert.deepEqual(t, [[0, 0], [0, -1]]);
  assert.deepEqual(extended_segments([[0, 0]], [[10, 0]])[0], [[-2, 0], [12, 0]]);
  const clipped = clip_segments_uv([[[0, 0], [1000, 0]], [[0, 0], [0, 0]]], [-100, 100, -50, 50]);
  assert.deepEqual(clipped[0], [[0, 0], [100, 0]]);
  assert.equal(clipped[1], null);
  // L' = (0, 10), F' = (10, 0); P' = (0, 0) on L'S', Q' = (5, 0) on F'S'... S' = (0, 0)? use S' = intersection
  const { err, skipped } = self_check([0, 10, 1], [[0, 4, 1]], [10, 0, 1], [[4, 0, 1]], [[0, 0, 1]], 1e-9);
  assert.deepEqual(skipped, [false]);
  assert.ok((err[0] as number) <= 1e-12);
  const cam = camera_matrix(validate_camera({ position: [0, 0, 1], target: [0, 1, 1], focal_length_mm: 35, frame_mm: [36, 24] }), [36, 24]);
  const at_cam = special_point_image(cam, [0, 0, 1, 1], 1e-9);
  assert.equal(at_cam.undefined, true);
  const side = special_point_image(cam, [1, 0, 0, 0], 1e-9);
  assert.deepEqual(side.at_infinity, [1, 0]);
});

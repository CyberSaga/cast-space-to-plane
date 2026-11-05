import assert from "node:assert/strict";
import { test } from "node:test";

import { LAYER_IDS, camera_matrix, compose, load_scene, project_scene, shadow_geometry, unproject_to_plane } from "castplane";
import type { Camera, Scene } from "castplane";

import { art_frame_matrix, art_transferables, pack_art } from "../src/art_buffers.js";
import { DRAWING_OFFSET_M, line_art } from "../src/observer.js";

const scene: Scene = load_scene({
  version: "0.1", units: "m", up: "z",
  objects: [{ id: "crate", type: "box", size: [1, 1, 1], transform: { position: [0, 0, 0], rotation_deg: [0, 0, 30] } },
    { id: "ball", type: "sphere", radius: 0.5, transform: { position: [2, 1, 0], rotation_deg: [0, 0, 0] } }],
  lights: [{ id: "lamp", type: "point", position: [2, -3, 5] }],
  receivers: [{ id: "ground", type: "plane", normal: [0, 0, 1], offset: 0 }],
  camera: { position: [4, -8, 5], target: [0, 0, 0.5], roll_deg: 0, focal_length_mm: 35, frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 },
  output: { canvas_mm: [180, 120], layers: [...LAYER_IDS] },
});

const mul = (M: readonly number[], p: readonly number[]): number[] => [
  M[0]! * p[0]! + M[4]! * p[1]! + M[8]! * p[2]! + M[12]!,
  M[1]! * p[0]! + M[5]! * p[1]! + M[9]! * p[2]! + M[13]!,
  M[2]! * p[0]! + M[6]! * p[1]! + M[10]! * p[2]! + M[14]!,
];

test("pack_art keeps every segment and fill of line_art in order, by style of first appearance", () => {
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const doc = compose(scene, B, true);
  const art = line_art(doc, B.camera, 4, new Set(LAYER_IDS));
  const packed = pack_art(art);
  assert.ok(art.segments.length > 0 && art.fills.length > 0);
  const total = packed.lines.reduce((n, l) => n + l.uv.length / 4, 0);
  assert.equal(total, art.segments.length);
  const styles = [...new Set(art.segments.map((s) => s.style))];
  assert.deepEqual(packed.lines.map((l) => l.style), styles);
  for (const l of packed.lines) {
    const own = art.segments.filter((s) => s.style === l.style);
    own.forEach((s, i) => {
      assert.deepEqual([...l.uv.subarray(4 * i, 4 * i + 4)], [s.uv[0][0], s.uv[0][1], s.uv[1][0], s.uv[1][1]].map(Math.fround));
    });
  }
  assert.equal(packed.fills.length, art.fills.length);
  packed.fills.forEach((f, i) => {
    assert.equal(f.style, art.fills[i]!.style);
    assert.deepEqual([...f.uv], art.fills[i]!.uv.flatMap((p) => [Math.fround(p[0]), Math.fround(p[1])]));
  });
  assert.equal(art_transferables(packed).length, packed.lines.length + packed.fills.length);
});

test("art_frame_matrix maps canvas mm to unproject_to_plane within 1e-9 m, for random cameras and depths", () => {
  let seed = 7;
  const rnd = () => (seed = (seed * 48271) % 2147483647) / 2147483647;
  for (let i = 0; i < 100; i++) {
    const block: Camera = { position: [8 * rnd() - 4, -10 * rnd() - 1, 6 * rnd()], target: [2 * rnd() - 1, 2 * rnd() - 1, rnd()],
      roll_deg: 360 * rnd() - 180, focal_length_mm: 8 + 392 * rnd(), frame_mm: [36, 24], shift_mm: [6 * rnd() - 3, 6 * rnd() - 3], near_m: 0.05 };
    const rec = camera_matrix(block, [180, 120]);
    const depth = 0.05 + 12 * rnd() - DRAWING_OFFSET_M;
    const M = art_frame_matrix(rec, depth);
    // right-handed: the z column is r' × u' up to scale, so the determinant is positive
    const det = M[0]! * (M[5]! * M[10]! - M[6]! * M[9]!) - M[4]! * (M[1]! * M[10]! - M[2]! * M[9]!) + M[8]! * (M[1]! * M[6]! - M[2]! * M[5]!);
    assert.ok(det > 0, `camera ${i}: determinant ${det}`);
    for (const uv of [[0, 0], [90, 60], [-90, -60], [37.5, -11.25], [-70, 55]]) {
      const X = unproject_to_plane(rec, uv, depth), Y = mul(M, [uv[0]!, uv[1]!, 0]);
      for (let k = 0; k < 3; k++) assert.ok(Math.abs(X[k]! - Y[k]!) < 1e-9, `camera ${i} uv ${uv}: ${X} vs ${Y}`);
    }
  }
});

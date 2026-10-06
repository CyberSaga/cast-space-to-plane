/** Validation table of contract §2.0 in the port (§5.4.3, §5.4.13): every row with its field path, defaults,
 * the clockwise prism reversed, the port-only rows of `load_scene_text`. Ported from `tests/test_scene.py`. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SceneError } from "../src/errors.js";
import { LAYER_IDS, load_camera, load_scene, load_scene_text, polygon_is_simple, validate_scene } from "../src/scene.js";
import { read_json, repo_path } from "./helpers.js";

function base_scene(): any {
  return read_json(repo_path("examples", "basic.json"));
}

function mutate(path: (string | number)[], value: unknown, del = false): any {
  const scene = base_scene();
  let node = scene;
  for (const key of path.slice(0, -1)) node = node[key];
  const last = path[path.length - 1] as string | number;
  if (del) delete node[last];
  else node[last] = value;
  return scene;
}

function expect_error(scene: unknown, field: string): SceneError {
  try {
    validate_scene(scene);
  } catch (e) {
    assert.ok(e instanceof SceneError, String(e));
    assert.equal(e.field, field, `${e.field}: ${e.detail}`);
    assert.ok(e.message.includes(field));
    return e;
  }
  assert.fail(`no SceneError for ${field}`);
}

function prism(poly: unknown): any {
  return mutate(["objects", 1], { id: "p", type: "prism", polygon: poly, height: 1.0 });
}

test("valid example loads; defaults", () => {
  const scene = load_scene(base_scene());
  assert.equal(scene.objects[0]?.id, "crate");
  assert.equal(scene.camera.near_m, 0.05);
});

test("version, units, up", () => {
  expect_error(mutate(["version"], "0.2"), "version");
  expect_error(mutate(["version"], null, true), "version");
  expect_error(mutate(["units"], "cm"), "units");
  expect_error(mutate(["up"], "y"), "up");
  const scene = mutate(["units"], null, true);
  delete scene.up;
  const out = validate_scene(scene);
  assert.equal(out.units, "m");
  assert.equal(out.up, "z");
});

test("unknown keys ignored and input not mutated", () => {
  const scene = base_scene();
  scene.comment = "ignored";
  scene.objects[0].colour = "red";
  const before = JSON.stringify(scene);
  const out: any = validate_scene(scene);
  assert.ok(!("comment" in out) && !("colour" in out.objects[0]));
  assert.equal(JSON.stringify(scene), before);
});

test("objects rows", () => {
  expect_error(mutate(["objects"], []), "objects");
  expect_error(mutate(["objects"], { id: "x" }), "objects");
  expect_error(mutate(["objects", 1, "id"], "crate"), "objects[1].id");
  expect_error(mutate(["objects", 0, "id"], ""), "objects[0].id");
  expect_error(mutate(["objects", 0, "id"], "a.b"), "objects[0].id");
  expect_error(mutate(["objects", 0, "id"], 3), "objects[0].id");
  expect_error(mutate(["objects", 0, "type"], "torus"), "objects[0].type");
  expect_error(mutate(["objects", 0, "type"], null, true), "objects[0].type");
  expect_error(mutate(["objects", 0, "size"], [1.0, 0.8]), "objects[0].size");
  expect_error(mutate(["objects", 0, "size"], [1.0, 0.0, 0.6]), "objects[0].size[1]");
  expect_error(mutate(["objects", 0, "size"], [1.0, -1, 0.6]), "objects[0].size[1]");
  expect_error(mutate(["objects", 0, "size"], [1.0, true, 0.6]), "objects[0].size[1]");   // booleans are not numbers
  expect_error(mutate(["objects", 0, "size"], null, true), "objects[0].size");
  expect_error(mutate(["objects", 1, "radius"], 0), "objects[1].radius");
  expect_error(mutate(["objects", 1, "height"], -2), "objects[1].height");
  expect_error(mutate(["objects", 1, "height"], null, true), "objects[1].height");
  expect_error(mutate(["objects", 1, "radius"], NaN), "objects[1].radius");
  assert.equal(validate_scene(mutate(["objects", 1], { id: "s", type: "sphere", radius: 0.5 })).objects[1]?.radius, 0.5);
  expect_error(mutate(["objects", 1], { id: "s", type: "sphere" }), "objects[1].radius");
  expect_error(mutate(["objects", 1], { id: "c", type: "cone", radius: 0.5 }), "objects[1].height");
});

test("prism polygon rules; clockwise input reversed", () => {
  expect_error(prism([[0, 0], [1, 0]]), "objects[1].polygon");
  expect_error(prism([[0, 0], [1, 1], [2, 2]]), "objects[1].polygon");
  const e = expect_error(prism([[0, 0], [1, 1], [1, 0], [0, 1]]), "objects[1].polygon");
  assert.ok(e.detail.includes("self-intersecting") && e.detail.includes("collinear"));
  assert.equal(expect_error(prism([[0, 0], [2, 0], [2, 2], [0, 2], [2, 1]]), "objects[1].polygon").detail,
    "polygon is self-intersecting");
  expect_error(prism([[0, 0], [1, 0], [1, 0], [0, 1]]), "objects[1].polygon[1]");
  expect_error(prism([[0, 0], [1, 0, 0], [0, 1]]), "objects[1].polygon[1]");
  assert.deepEqual(validate_scene(prism([[0, 0], [1, 0], [0, 1]])).objects[1]?.polygon, [[0, 0], [1, 0], [0, 1]]);
  assert.deepEqual(validate_scene(prism([[0, 0], [0, 1], [1, 0]])).objects[1]?.polygon, [[1, 0], [0, 1], [0, 0]]);
  assert.ok(validate_scene(prism([[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]])));
  const spur = [[0.0, 0.0], [500.0, 0.0], [500.0, 500.0], [-1e-7, 0.0]];
  const touch = [[0.0, 0.0], [4.0, 0.0], [4.0, 4.0], [2.0, 0.0], [0.0, 4.0]];
  const bowtie = [[0.0, 0.0], [1.0, 1.0], [1.0, 0.0], [0.0, 1.0]];
  for (const k of [1e-3, 1.0, 1e3]) {
    for (const [poly, simple] of [[spur, true], [touch, false], [bowtie, false]] as [number[][], boolean][]) {
      const scaled = poly.map(([x, y]) => [k * (x as number), k * (y as number)]);
      let extent = 0;
      for (const p of scaled) for (const c of p) extent = Math.max(extent, Math.abs(c as number));
      assert.equal(polygon_is_simple(scaled, 1e-12 * extent * extent, 1e-12 * extent), simple);
      if (simple) assert.ok(validate_scene(prism(scaled)));
      else expect_error(prism(scaled), "objects[1].polygon");
    }
  }
});

test("transform rules", () => {
  expect_error(mutate(["objects", 0, "transform", "scale"], [1, 1, 1]), "objects[0].transform.scale");
  expect_error(mutate(["objects", 0, "transform", "position"], [1, 2]), "objects[0].transform.position");
  expect_error(mutate(["objects", 0, "transform", "rotation_deg"], "x"), "objects[0].transform.rotation_deg");
  expect_error(mutate(["objects", 0, "transform"], 5), "objects[0].transform");
  assert.deepEqual(validate_scene(mutate(["objects", 0, "transform"], null, true)).objects[0]?.transform,
    { position: [0, 0, 0], rotation_deg: [0, 0, 0] });
  assert.deepEqual(validate_scene(mutate(["objects", 0, "transform"], { position: [1, 2, 3] })).objects[0]?.transform.rotation_deg,
    [0, 0, 0]);
});

test("lights rows (phase 1: exactly one)", () => {
  expect_error(mutate(["lights"], []), "lights");
  const scene = base_scene();
  scene.lights.push({ id: "l2", type: "point", position: [0, 0, 1] });
  expect_error(scene, "lights");
  expect_error(mutate(["lights", 0, "type"], "spot"), "lights[0].type");
  expect_error(mutate(["lights", 0, "position"], null, true), "lights[0].position");
  expect_error(mutate(["lights", 0, "id"], null, true), "lights[0].id");
  expect_error(mutate(["lights", 0, "id"], "a.b"), "lights[0].id");
  expect_error(mutate(["lights", 0, "id"], ""), "lights[0].id");
  expect_error(mutate(["lights", 0], { id: "sun", type: "directional", direction: [0, 0, 2] }), "lights[0].direction");
  expect_error(mutate(["lights", 0], { id: "sun", type: "directional" }), "lights[0].direction");
  assert.deepEqual(validate_scene(mutate(["lights", 0], { id: "sun", type: "directional", direction: [0.6, 0.0, 0.8] }))
    .lights[0]?.direction, [0.6, 0.0, 0.8]);
});

test("receivers rows", () => {
  expect_error(mutate(["receivers"], []), "receivers");
  expect_error(mutate(["receivers", 0, "type"], "sphere"), "receivers[0].type");
  expect_error(mutate(["receivers", 0, "normal"], [0, 1, 0]), "receivers[0].normal");
  expect_error(mutate(["receivers", 0, "normal"], [0, 0, 2]), "receivers[0].normal");
  expect_error(mutate(["receivers", 0, "offset"], 0.5), "receivers[0].offset");
  assert.equal(validate_scene(mutate(["receivers", 0, "offset"], null, true)).receivers[0]?.offset, 0.0);
});

test("camera rows: both forms given -> SceneError('camera')", () => {
  expect_error(mutate(["camera", "position"], [0, 0]), "camera.position");
  expect_error(mutate(["camera", "target"], null, true), "camera");
  const both = expect_error(mutate(["camera", "yaw_deg"], 10.0), "camera");
  assert.equal(both.detail, "give either target or yaw_deg + pitch_deg, not both");
  expect_error(mutate(["camera", "target"], [0.0, 0.0, 1.5]), "camera.target");
  const scene = mutate(["camera", "target"], null, true);
  scene.camera.yaw_deg = 10.0;
  expect_error(scene, "camera");
  scene.camera.pitch_deg = -5.0;
  const out = validate_scene(scene);
  assert.equal(out.camera.yaw_deg, 10.0);
  assert.ok(!("target" in out.camera));
  expect_error(mutate(["camera", "focal_length_mm"], 0), "camera.focal_length_mm");
  expect_error(mutate(["camera", "frame_mm"], [36, 0]), "camera.frame_mm[1]");
  expect_error(mutate(["camera", "frame_mm"], null, true), "camera.frame_mm");
  expect_error(mutate(["camera", "near_m"], -0.1), "camera.near_m");
  expect_error(mutate(["camera", "shift_mm"], [1]), "camera.shift_mm");
  expect_error(mutate(["camera", "roll_deg"], "0"), "camera.roll_deg");
  const s2 = base_scene();
  for (const key of ["roll_deg", "shift_mm", "near_m"]) delete s2.camera[key];
  const cam = validate_scene(s2).camera;
  assert.equal(cam.roll_deg, 0.0);
  assert.deepEqual(cam.shift_mm, [0.0, 0.0]);
  assert.equal(cam.near_m, 0.05);
  assert.equal(load_camera({ camera: base_scene().camera }).focal_length_mm, base_scene().camera.focal_length_mm);
});

test("output rows: the spec's own [257, 182] example rejected; empty layers rejected", () => {
  const e = expect_error(mutate(["output", "canvas_mm"], [257, 182]), "output.canvas_mm");
  assert.ok(e.detail.includes("257/182 = 1.412") && e.detail.includes("36/24 = 1.5") && e.detail.includes("[273, 182]"), e.detail);
  expect_error(mutate(["output", "canvas_mm"], [0, 1]), "output.canvas_mm[0]");
  expect_error(mutate(["output", "canvas_mm"], null, true), "output.canvas_mm");
  expect_error(mutate(["output"], null, true), "output");
  expect_error(mutate(["output", "layers"], ["horizon", "shadows"]), "output.layers[1]");
  expect_error(mutate(["output", "layers"], []), "output.layers");
  expect_error(mutate(["output", "layers"], ["horizon", "horizon"]), "output.layers");
  expect_error(mutate(["output", "png_dpi"], 0), "output.png_dpi");
  const scene = base_scene();
  delete scene.output.layers;
  delete scene.output.png_dpi;
  const out = validate_scene(scene).output;
  assert.deepEqual(out.layers, [...LAYER_IDS]);
  assert.equal(out.png_dpi, 300);
  assert.deepEqual(validate_scene(mutate(["output", "layers"], ["labels", "horizon"])).output.layers, ["horizon", "labels"]);
});

test("load_scene_text: invalid JSON and a non-object root", () => {
  try {
    load_scene_text("{not json");
    assert.fail("no error");
  } catch (e) {
    assert.ok(e instanceof SceneError);
    assert.equal(e.field, "");
    assert.ok(e.detail.startsWith("invalid JSON: "));
  }
  try {
    load_scene_text("[1, 2]");
    assert.fail("no error");
  } catch (e) {
    assert.ok(e instanceof SceneError);
    assert.equal(e.field, "scene");
    assert.equal(e.detail, "must be an object");
  }
  assert.equal(load_scene_text(JSON.stringify(base_scene())).objects.length, base_scene().objects.length);
});

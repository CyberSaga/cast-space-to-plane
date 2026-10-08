/** Validation table of contract §2.0 in the port (§5.4.3, §5.4.13): every row with its field path, defaults,
 * the clockwise prism reversed, the port-only rows of `load_scene_text`. Ported from `tests/test_scene.py`. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { SceneError } from "../src/errors.js";
import {
  LAYER_IDS, LOADER_TYPES, OBJECT_TYPES, load_camera, load_scene, load_scene_text, polygon_is_simple, to_z_up, validate_scene,
} from "../src/scene.js";
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

test("lights rows (phase 2: a non-empty list of any length)", () => {
  expect_error(mutate(["lights"], []), "lights");
  expect_error(mutate(["lights"], { id: "l2" }), "lights");
  const scene = base_scene();
  scene.lights.push({ id: "l2", type: "point", position: [0, 0, 1] });
  assert.deepEqual(validate_scene(scene).lights.map((lt) => lt.id), ["lamp", "l2"]);
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

test("receivers rows (contract §5.1.1: any plane; unbounded only for the ground at index 0)", () => {
  expect_error(mutate(["receivers"], []), "receivers");
  expect_error(mutate(["receivers", 0, "type"], "sphere"), "receivers[0].type");
  expect_error(mutate(["receivers", 0, "normal"], [0, 1, 0]), "receivers[0].bounds");
  expect_error(mutate(["receivers", 0, "normal"], [0, 0, 2]), "receivers[0].normal");
  expect_error(mutate(["receivers", 0, "offset"], 0.5), "receivers[0].bounds");
  assert.equal(validate_scene(mutate(["receivers", 0, "offset"], null, true)).receivers[0]?.offset, 0.0);
});

// --- M4: bounded receivers (contract §5.1.1, §5.0.1), ported from tests/test_scene.py -----------------------------
const WALL = { id: "wall", type: "plane", normal: [0, -1, 0], offset: 6, bounds: [[-3, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]] };

function with_receivers(extra: any[], first: any = null): any {
  const scene = base_scene();
  if (first !== null) scene.receivers = [first];
  scene.receivers = [...scene.receivers, ...extra.map((r) => JSON.parse(JSON.stringify(r)))];
  return scene;
}

function expect_detail(scene: unknown, field: string, fragment: string): void {
  assert.ok(expect_error(scene, field).detail.includes(fragment));
}

test("M4: a wall receiver validates and keeps its plane; the ground gets bounds null", () => {
  const out = validate_scene(with_receivers([WALL]));
  const [ground, wall] = out.receivers;
  assert.deepEqual(ground, { id: ground?.id, type: "plane", bounds: null, normal: [0.0, 0.0, 1.0], offset: 0.0 });
  assert.deepEqual(wall?.normal, [0.0, -1.0, 0.0]);
  assert.equal(wall?.offset, 6.0);
  assert.deepEqual(wall?.bounds, [[-3.0, 6.0, 0.0], [3.0, 6.0, 0.0], [3.0, 6.0, 2.5], [-3.0, 6.0, 2.5]]);
});

test("M4: clockwise bounds are reversed silently", () => {
  const cw = { ...WALL, bounds: [...WALL.bounds].reverse() };
  const out = validate_scene(with_receivers([cw]));
  assert.deepEqual(out.receivers[1]?.bounds, [[-3.0, 6.0, 0.0], [3.0, 6.0, 0.0], [3.0, 6.0, 2.5], [-3.0, 6.0, 2.5]]);
});

test("M4: receivers list and ids (unique, no '.', disjoint from objects and lights, not reserved)", () => {
  expect_error(with_receivers([{ ...WALL, id: "a.b" }]), "receivers[1].id");
  expect_error(with_receivers([{ ...WALL, id: "" }]), "receivers[1].id");
  expect_error(with_receivers([{ ...WALL, id: "ground" }]), "receivers[1].id");
  expect_error(with_receivers([{ ...WALL, id: "crate" }]), "receivers[1].id");
  expect_error(with_receivers([{ ...WALL, id: "lamp" }]), "receivers[1].id");
  expect_detail(with_receivers([{ ...WALL, id: "hidden" }]), "receivers[1].id", "reserved id");
  expect_error(mutate(["objects", 0, "id"], "hidden"), "objects[0].id");
  expect_error(mutate(["lights", 0, "id"], "hidden"), "lights[0].id");
});

test("M4: unbounded only for the ground at receivers[0]; a bounded receivers[0] is valid", () => {
  const { bounds: _b, ...no_bounds } = WALL;
  expect_error(with_receivers([no_bounds]), "receivers[1].bounds");
  expect_error(with_receivers([{ id: "g2", type: "plane", normal: [0, 0, 1], offset: 0 }]), "receivers[1].bounds");
  const out = validate_scene(with_receivers([], JSON.parse(JSON.stringify(WALL))));
  assert.deepEqual(out.receivers.map((r) => r.id), ["wall"]);
  assert.notEqual(out.receivers[0]?.bounds, null);
});

test("M4: bounds rules (coplanar, distinct, strictly convex, simple, above the ground)", () => {
  const bad = (bounds: unknown, field: string): SceneError => expect_error(with_receivers([{ ...WALL, bounds }]), field);
  bad([[-3, 6, 0], [3, 6, 0]], "receivers[1].bounds");
  bad("square", "receivers[1].bounds");
  bad([[-3, 6, 0], [3, 6, 0], [3, 6.01, 2.5], [-3, 6, 2.5]], "receivers[1].bounds[2]");
  bad([[-3, 6, 0], [3, 6, 0], [3, 6, 0], [-3, 6, 2.5]], "receivers[1].bounds[1]");
  bad([[-3, 6, 0], [0, 6, 1], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]], "receivers[1].bounds");
  bad([[-3, 6, 0], [0, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]], "receivers[1].bounds");
  bad([[-3, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5], [-3, 6, 1, 2]], "receivers[1].bounds[4]");
  const star = [0, 1, 2, 3, 4].map((k) => [3 * Math.cos((90 + 144 * k) * (Math.PI / 180)), 6,
    3 + 3 * Math.sin((90 + 144 * k) * (Math.PI / 180))]);
  assert.ok(bad(star, "receivers[1].bounds").detail.includes("strictly convex"));
  const low = [[-3, 6, -0.5], [3, 6, -0.5], [3, 6, 2.5], [-3, 6, 2.5]];
  assert.ok(bad(low, "receivers[1].bounds[0]").detail.includes("below the ground receiver"));
  assert.deepEqual(validate_scene(with_receivers([], { ...WALL, bounds: low })).receivers[0]?.bounds?.[0], [-3.0, 6.0, -0.5]);
});

test("M4: any unit normal and offset", () => {
  const tilted = { id: "ramp", type: "plane", normal: [0, -0.6, 0.8], offset: 0.0, bounds: [[-1, 0, 0], [1, 0, 0], [1, 4, 3], [-1, 4, 3]] };
  assert.deepEqual(validate_scene(with_receivers([tilted])).receivers[1]?.normal, [0.0, -0.6, 0.8]);
  expect_error(with_receivers([{ ...tilted, normal: [0, -0.6, 0.9] }]), "receivers[1].normal");
  expect_error(with_receivers([{ ...tilted, offset: "x" }]), "receivers[1].offset");
});

test("M4: output.hidden_lines / hidden_style", () => {
  const out = validate_scene(base_scene()).output;
  assert.equal(out.hidden_lines, false);
  assert.equal(out.hidden_style, "dashed");
  assert.equal(validate_scene(mutate(["output", "hidden_lines"], true)).output.hidden_lines, true);
  assert.equal(validate_scene(mutate(["output", "hidden_style"], "omit")).output.hidden_style, "omit");
  expect_error(mutate(["output", "hidden_lines"], 1), "output.hidden_lines");
  expect_error(mutate(["output", "hidden_lines"], "yes"), "output.hidden_lines");
  expect_error(mutate(["output", "hidden_style"], "dotted"), "output.hidden_style");
});

// --- M5: the mesh object type (contract §5.2.1, §5.0.1) -----------------------------------------------------------
const CUBE_V = [[-.5, -.5, 0], [.5, -.5, 0], [.5, .5, 0], [-.5, .5, 0], [-.5, -.5, 1], [.5, -.5, 1], [.5, .5, 1], [-.5, .5, 1]];
const CUBE_F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];

function mesh_scene(keys: Record<string, unknown> = {}): any {
  const obj = { id: "m", type: "mesh", data: { vertices: JSON.parse(JSON.stringify(CUBE_V)), faces: JSON.parse(JSON.stringify(CUBE_F)) }, ...keys };
  return mutate(["objects"], [obj]);
}

test("M5: mesh object validated form and defaults; OBJECT_TYPES", () => {
  assert.deepEqual([...OBJECT_TYPES], ["box", "cylinder", "sphere", "cone", "prism", "mesh"]);
  const o = validate_scene(mesh_scene()).objects[0];
  assert.deepEqual(o, {
    id: "m", type: "mesh", path: null, node: null,
    data: { vertices: CUBE_V, faces: CUBE_F, smooth_groups: [0, 0, 0, 0, 0, 0] },
    up: "z", scale: 1.0, weld_tolerance: 1e-6, smooth_angle_deg: 30.0,
    transform: { position: [0.0, 0.0, 0.0], rotation_deg: [0.0, 0.0, 0.0] },
  });
  const o2 = validate_scene(mesh_scene({ path: "box.obj", node: 2 })).objects[0];
  assert.equal(o2?.path, "box.obj");
  assert.equal(o2?.node, 2);
});

test("M5: a path-only mesh must be expanded first; data required; the loader type step (contract §5.0.1)", () => {
  const scene = mesh_scene({ path: "box.obj" });
  delete scene.objects[0].data;
  assert.ok(expect_error(scene, "objects[0].path").detail.includes("expand_scene"));
  const s2 = mesh_scene();
  delete s2.objects[0].data;
  expect_error(s2, "objects[0].data");
  expect_error(mesh_scene({ path: "" }), "objects[0].path");
  expect_error(mesh_scene({ data: [1, 2] }), "objects[0].data");
  assert.deepEqual([...LOADER_TYPES], ["step"]);
  // the exact message of castplane/scene.py::validate_object since the M8 merge (identical to the reference)
  assert.equal(expect_error(mutate(["objects", 0], { id: "s", type: "step", path: "a.step" }), "objects[0].type").detail,
    "loader object type 'step' must be expanded first (castplane.io.expand_scene or 'castplane import')");
});

test("M5: mesh data rules", () => {
  expect_error(mesh_scene({ data: { vertices: CUBE_V.slice(0, 2), faces: [[0, 1, 0]] } }), "objects[0].data.vertices");
  expect_error(mesh_scene({ data: { vertices: [[0, 0, 0], [1, 0, 0], [0, NaN, 0]], faces: [[0, 1, 2]] } }), "objects[0].data.vertices[2][1]");
  expect_error(mesh_scene({ data: { vertices: [[0, 0, 0], [1, 0, 0], [0, 0]], faces: [[0, 1, 2]] } }), "objects[0].data.vertices[2]");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: [] } }), "objects[0].data.faces");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: [[0, 1]] } }), "objects[0].data.faces[0]");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: [[0, 1, 8]] } }), "objects[0].data.faces[0]");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: [[0, 1, true]] } }), "objects[0].data.faces[0]");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: [[0, 1, 2.5]] } }), "objects[0].data.faces[0]");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: CUBE_F, smooth_groups: [0] } }), "objects[0].data.smooth_groups");
  expect_error(mesh_scene({ data: { vertices: CUBE_V, faces: CUBE_F, smooth_groups: [0, 0, 0, 0, 0, -1] } }), "objects[0].data.smooth_groups[5]");
  assert.deepEqual(validate_scene(mesh_scene({ data: { vertices: CUBE_V, faces: CUBE_F, smooth_groups: [1, 1, 2, 2, 0, 0] } }))
    .objects[0]?.data?.smooth_groups, [1, 1, 2, 2, 0, 0]);
});

test("M5: mesh optional keys and the exact Y-up axis map", () => {
  expect_error(mesh_scene({ up: "x" }), "objects[0].up");
  expect_error(mesh_scene({ scale: 0 }), "objects[0].scale");
  expect_error(mesh_scene({ weld_tolerance: -1e-9 }), "objects[0].weld_tolerance");
  expect_error(mesh_scene({ smooth_angle_deg: 180.5 }), "objects[0].smooth_angle_deg");
  expect_error(mesh_scene({ smooth_angle_deg: -1 }), "objects[0].smooth_angle_deg");
  expect_error(mesh_scene({ node: -1 }), "objects[0].node");
  expect_error(mesh_scene({ node: 1.5 }), "objects[0].node");
  expect_error(mesh_scene({ transform: { scale: [1, 1, 1] } }), "objects[0].transform.scale");
  const o = validate_scene(mesh_scene({ scale: 0.001, weld_tolerance: 0, smooth_angle_deg: 0, node: "Cube" })).objects[0];
  assert.deepEqual([o?.scale, o?.weld_tolerance, o?.smooth_angle_deg, o?.node], [0.001, 0.0, 0.0, "Cube"]);
  assert.deepEqual(to_z_up([[1, 0, 2]]), [[1.0, -2.0, 0.0]]);
  assert.ok(Object.is(to_z_up([[0.0, 0.0, 0.0]])[0]?.[1], 0));
  const y_up = CUBE_V.map(([x, y, z]) => [x, z, -(y as number)]);
  const oy = validate_scene(mesh_scene({ up: "y", data: { vertices: y_up, faces: CUBE_F } })).objects[0];
  assert.equal(oy?.up, "z");
  assert.deepEqual(oy?.data?.vertices, CUBE_V);
});

// --- M6: multiple lights (contract §5.3.0, §5.0.1) -----------------------------------------------------------------
function two_lights(second: Record<string, unknown> = {}): any {
  const scene = base_scene();
  scene.lights.push({ id: "l2", type: "point", position: [2, 0, 3], ...second });
  return scene;
}

test("M6: lights of any length in scene order; duplicate ids", () => {
  const scene = two_lights();
  scene.lights.push({ id: "sun", type: "directional", direction: [0.6, 0.0, 0.8] });
  assert.deepEqual(validate_scene(scene).lights.map((lt) => lt.id), ["lamp", "l2", "sun"]);
  expect_error(two_lights({ type: "spot" }), "lights[1].type");
  expect_error(two_lights({ id: "a.b" }), "lights[1].id");
  expect_detail(two_lights({ id: "lamp" }), "lights[1].id", "lamp");
});

test("M6: reserved light ids umbra / core and object id core only in multi-light scenes", () => {
  for (const rid of ["umbra", "core"]) {
    assert.equal(expect_error(two_lights({ id: rid }), "lights[1].id").detail, "reserved id in a multi-light scene");
    const scene = two_lights();
    scene.lights[0].id = rid;
    expect_error(scene, "lights[0].id");
    assert.equal(validate_scene(mutate(["lights", 0, "id"], rid)).lights[0]?.id, rid);
  }
  expect_error(two_lights({ id: "hidden" }), "lights[1].id");
  const scene = two_lights();
  scene.objects[0].id = "core";
  assert.equal(expect_error(scene, "objects[0].id").detail, "reserved id");
  assert.equal(validate_scene(mutate(["objects", 0, "id"], "core")).objects[0]?.id, "core");
  const s2 = two_lights();
  s2.objects[0].id = "umbra";
  assert.equal(validate_scene(s2).objects[0]?.id, "umbra");
  expect_error(two_lights({ id: "ground" }), "receivers[0].id");
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

test("the phase-2 names of the §5.4.2 table are re-exported from the package entry point (part 1 review)", async () => {
  const pkg: Record<string, unknown> = await import("../src/index.js");
  for (const name of ["LOADER_TYPES", "validate_bounds", "validate_hidden_output", "validate_mesh_data", "validate_mesh_object",
    "validate_receivers_in_scene", "validate_lights_in_scene", "to_z_up", "receiver_frame", "bounds_functionals",
    "clip_polygon_bounds", "plate_loop", "construction_block", "multilight"]) {
    assert.ok(name in pkg && pkg[name] !== undefined, name);
  }
  const ml = pkg.multilight as Record<string, unknown>;
  for (const name of ["is_multi", "is_light_dependent_stem", "curved_stem_name"]) assert.equal(typeof ml[name], "function", name);
});

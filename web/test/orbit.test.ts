/** Tests of the DOM-free web modules (contract §5.4.13 `web/test/orbit.test.ts`): the §5.4.10 hand example, the
 * orbit round trip for both camera forms, the input mapping bounds and the download names / MIME types. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import {
  LAYER_ORDER, camera_matrix, compose, load_scene, load_scene_text, project_scene, shadow_geometry, transform_frame,
  validate_camera,
} from "castplane";
import type { Scene } from "castplane";

import {
  DISTANCE_MAX, DISTANCE_MIN, FOCAL_MAX_MM, FOCAL_MIN_MM, PITCH_LIMIT_DEG, camera_from_orbit, focal_from_slider,
  orbit_from_camera, pan_orbit, rotate_orbit, set_focal, set_roll, slider_from_focal, zoom_orbit,
} from "../src/orbit.js";
import type { OrbitState } from "../src/orbit.js";
import { camera_block_text, json_blob, ordered_layers, scene_blob, svg_blob } from "../src/download.js";
import { mesh_positions } from "../src/mesh3d.js";

// web/build/test/orbit.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const scene_file = (...parts: string[]): Scene => load_scene(JSON.parse(readFileSync(resolve(ROOT, ...parts), "utf-8")));
const example = (name: string) => scene_file("examples", `${name}.json`);
const conformance_case = (name: string) => scene_file("tests", "conformance", "cases", `${name}.json`);

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}

function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}

test("hand example: the camera of analytic_unit_box_point_light_overhead (§5.4.10)", () => {
  const scene = conformance_case("analytic_unit_box_point_light_overhead");
  assert.deepEqual(scene.camera.position, [4, -8, 5]);
  assert.deepEqual(scene.camera.target, [0, 0, 0.5]);
  const s = orbit_from_camera(scene.camera, scene);
  close(s.distance, Math.sqrt(100.25), 1e-12, "distance");
  close(s.distance, 10.012492197250394, 1e-12, "distance");
  close(s.yaw_deg, 26.56505117707799, 1e-9, "yaw_deg");
  close(s.pitch_deg, -26.7076677665586, 1e-9, "pitch_deg");
  assert.deepEqual(s.target, [0, 0, 0.5]);
  assert.equal(s.focal_length_mm, 35);
  // forward = the third row of P of that case
  const P = camera_matrix(scene.camera, scene.output.canvas_mm).P;
  close3(P[2], [-0.39950093555113786, 0.7990018711022757, -0.44943855249503006], 1e-15, "P[2]");
  const cam = camera_from_orbit(s, scene.camera);
  close3(cam.position, [4, -8, 5], 1e-9, "position");
  assert.deepEqual(cam.target, [0, 0, 0.5]);
  assert.deepEqual(Object.keys(cam).sort(), ["focal_length_mm", "frame_mm", "near_m", "position", "roll_deg", "shift_mm", "target"]);
  validate_camera(cam);
});

for (const [label, scene] of [
  ["examples/basic.json (target form)", () => example("basic")],
  ["examples/construction_demo.json (target form)", () => example("construction_demo")],
  ["examples/curved_demo.json (target form)", () => example("curved_demo")],
  ["examples/three_point.json (target form)", () => example("three_point")],
  ["examples/directional.json (yaw/pitch form)", () => example("directional")],
  ["case camera_yaw_pitch_form (yaw/pitch form)", () => conformance_case("camera_yaw_pitch_form")],
] as const) {
  test(`orbit round trip: ${label}`, () => {
    const sc = scene();
    const cam0 = sc.camera;
    const s = orbit_from_camera(cam0, sc);
    const cam = camera_from_orbit(s, cam0);
    close3(cam.position, cam0.position, 1e-9, "position");
    assert.equal(cam.roll_deg, cam0.roll_deg);
    assert.equal(cam.focal_length_mm, cam0.focal_length_mm);
    assert.deepEqual(cam.frame_mm, cam0.frame_mm);
    assert.deepEqual(cam.shift_mm, cam0.shift_mm);
    assert.equal(cam.near_m, cam0.near_m);
    const checked = validate_camera(cam);
    assert.equal(checked.yaw_deg, undefined);
    // the produced block is the same camera: P within 1e-12 of the scene camera's
    const P0 = camera_matrix(cam0, sc.output.canvas_mm).P, P1 = camera_matrix(cam, sc.output.canvas_mm).P;
    for (let i = 0; i < 3; i++) for (let j = 0; j < 4; j++) close(P1[i]![j]!, P0[i]![j]!, 1e-9 * Math.max(1, Math.abs(P0[i]![j]!)), `P[${i}][${j}]`);
    // a second round trip is stable
    const s2 = orbit_from_camera(checked, sc);
    close3(s2.target, s.target, 1e-9, "target");
    close(s2.distance, s.distance, 1e-9, "distance");
    close(s2.yaw_deg, s.yaw_deg, 1e-9, "yaw");
    close(s2.pitch_deg, s.pitch_deg, 1e-9, "pitch");
    // stage B accepts it on every frame
    const A = shadow_geometry(sc);
    compose(sc, project_scene(sc, A, cam));
  });
}

test("yaw/pitch form: target where the view axis meets the ground, distance 5 when it never does", () => {
  const sc = example("directional");
  const s = orbit_from_camera(sc.camera, sc);
  close(s.target[2], 0, 1e-12, "target z");
  close(s.pitch_deg, -5, 1e-12, "pitch");
  close(s.yaw_deg, 0, 1e-12, "yaw");
  close(s.distance, 1.6 / Math.sin((5 * Math.PI) / 180), 1e-9, "distance");
  const up = orbit_from_camera({ ...sc.camera, pitch_deg: 10 }, sc);
  assert.equal(up.distance, 5);
  close(up.pitch_deg, 10, 1e-12, "pitch");
});

const base_state = (): OrbitState => orbit_from_camera(conformance_case("analytic_unit_box_point_light_overhead").camera);

test("drag: yaw −= dx·180/H, pitch −= dy·180/H (DOM dy, down positive), pitch clamped to ±89.5°", () => {
  const s = base_state();
  const r = rotate_orbit(s, 10, -20, 600);
  close(r.yaw_deg, s.yaw_deg - 3, 1e-12, "yaw");
  close(r.pitch_deg, s.pitch_deg + 6, 1e-12, "pitch");
  assert.equal(rotate_orbit(s, 0, 1e6, 600).pitch_deg, -PITCH_LIMIT_DEG);
  assert.equal(rotate_orbit(s, 0, -1e6, 600).pitch_deg, PITCH_LIMIT_DEG);
  assert.equal(PITCH_LIMIT_DEG, 89.5);
  // at the clamp the camera never looks along the up axis
  for (const dy of [1e6, -1e6]) {
    const cam = camera_from_orbit(rotate_orbit(s, 0, dy, 600), conformance_case("analytic_unit_box_point_light_overhead").camera);
    assert.deepEqual(camera_matrix(cam, [360, 240]).warnings, []);
  }
  assert.deepEqual(base_state(), s); // inputs are not mutated
});

test("drag sense: grab-the-world on both axes like OrbitControls and the pan (down lifts the camera, right moves it left)", () => {
  const s = base_state();
  const base = conformance_case("analytic_unit_box_point_light_overhead").camera;
  const p0 = camera_from_orbit(s, base).position as number[];
  // the review example: dy = +100 px on a 500 px canvas from (4, −8, 5) must not drop the camera below the ground
  const down = camera_from_orbit(rotate_orbit(s, 0, 100, 500), base).position as number[];
  close(rotate_orbit(s, 0, 100, 500).pitch_deg, s.pitch_deg - 36, 1e-12, "pitch");
  assert.ok(down[2] > p0[2], `camera z ${down[2]} after a downward drag, was ${p0[2]}`);
  const up = camera_from_orbit(rotate_orbit(s, 0, -20, 500), base).position as number[];
  assert.ok(up[2] < p0[2] && up[2] > 0, `camera z ${up[2]} after an upward drag`);
  // dragging right moves the camera to its left (−right′ component), as OrbitControls and the pan do
  const right = camera_matrix(base, [360, 240]).R[0] as number[];
  const moved = camera_from_orbit(rotate_orbit(s, 20, 0, 500), base).position as number[];
  const along = (moved[0] - p0[0]) * right[0] + (moved[1] - p0[1]) * right[1] + (moved[2] - p0[2]) * right[2];
  assert.ok(along < 0, `right-component ${along}`);
});

test("pan: target moves along right' / up' by k = distance·(frame_h / f) / H_px per pixel", () => {
  const sc = conformance_case("analytic_unit_box_point_light_overhead");
  const s = orbit_from_camera(sc.camera, sc);
  const H = 480;
  const k = (s.distance * (sc.camera.frame_mm[1] / s.focal_length_mm)) / H;
  const R = camera_matrix(camera_from_orbit(s, sc.camera), sc.output.canvas_mm).R;
  const p = pan_orbit(s, 12, -7, H, sc.camera, sc.output.canvas_mm);
  for (let i = 0; i < 3; i++) close(p.target[i]!, s.target[i]! - 12 * k * R[0][i]! - 7 * k * R[1][i]!, 1e-12, `target[${i}]`);
  assert.equal(p.distance, s.distance);
  assert.equal(p.yaw_deg, s.yaw_deg);
  // panning keeps the screen position of the target point: it moves by exactly (dx, dy) pixels
  const before = camera_matrix(camera_from_orbit(s, sc.camera), sc.output.canvas_mm);
  const after = camera_matrix(camera_from_orbit(p, sc.camera), sc.output.canvas_mm);
  const proj = (P: number[][], X: readonly number[]) => {
    const x = P.map((row) => row[0]! * X[0]! + row[1]! * X[1]! + row[2]! * X[2]! + row[3]!);
    return [x[0]! / x[2]!, x[1]! / x[2]!];
  };
  const a = proj(before.P, s.target), b = proj(after.P, s.target);
  assert.deepEqual(a.map((x) => Math.abs(x) < 1e-9), [true, true]);
  const px_per_mm = H / sc.output.canvas_mm[1];
  close((b[0]! - a[0]!) * px_per_mm, 12, 1e-9, "dx px");
  close(-(b[1]! - a[1]!) * px_per_mm, -7, 1e-9, "dy px"); // canvas v is up, screen y is down
});

test("zoom, roll and focal bounds", () => {
  const s = base_state();
  close(zoom_orbit(s, 100).distance, s.distance * Math.exp(0.1), 1e-12, "zoom");
  assert.equal(zoom_orbit(s, 1e9).distance, DISTANCE_MAX);
  assert.equal(zoom_orbit(s, -1e9).distance, DISTANCE_MIN);
  assert.deepEqual([DISTANCE_MIN, DISTANCE_MAX], [0.05, 1e4]);
  assert.equal(set_roll(s, 500).roll_deg, 180);
  assert.equal(set_roll(s, -500).roll_deg, -180);
  assert.equal(set_roll(s, 12.5).roll_deg, 12.5);
  assert.equal(set_focal(s, 1).focal_length_mm, FOCAL_MIN_MM);
  assert.equal(set_focal(s, 1e4).focal_length_mm, FOCAL_MAX_MM);
  assert.deepEqual([FOCAL_MIN_MM, FOCAL_MAX_MM], [8, 400]);
  close(focal_from_slider(0), 8, 1e-12, "slider 0");
  close(focal_from_slider(1), 400, 1e-9, "slider 1");
  close(focal_from_slider(0.5), Math.sqrt(8 * 400), 1e-9, "slider 0.5 (logarithmic)");
  for (const f of [8, 24, 35, 50, 135, 400]) close(focal_from_slider(slider_from_focal(f)), f, 1e-9, `focal ${f}`);
  assert.equal(slider_from_focal(1), 0);
  assert.equal(slider_from_focal(1e6), 1);
});

test("downloads: names, MIME types, layer order and contents", () => {
  const sc = example("basic");
  const A = shadow_geometry(sc);
  const s = rotate_orbit(orbit_from_camera(sc.camera, sc), 40, 10, 500);
  const cam = camera_from_orbit(s, sc.camera);
  const doc = compose(sc, project_scene(sc, A, cam));
  assert.deepEqual(ordered_layers(["labels", "objects", "bogus", "horizon"]), ["horizon", "objects", "labels"]);
  assert.deepEqual(ordered_layers(LAYER_ORDER), [...LAYER_ORDER]);
  const svg = svg_blob(doc, ["labels", "objects"], "basic");
  assert.equal(svg.filename, "basic.svg");
  assert.equal(svg.type, "image/svg+xml");
  assert.ok(svg.text.startsWith('<?xml version="1.0" encoding="UTF-8"?>\n<svg '), svg.text.slice(0, 80));
  assert.ok(svg.text.endsWith("</svg>\n"));
  const groups = [...svg.text.matchAll(/^<g id="([a-z_]+)"/gm)].map((m) => m[1]);
  assert.deepEqual(groups, ["objects", "labels"]);
  const json = json_blob(doc, "basic");
  assert.equal(json.filename, "basic.json");
  assert.equal(json.type, "application/json");
  assert.ok(json.text.endsWith("}\n"));
  assert.deepEqual(Object.keys(JSON.parse(json.text)).sort(), Object.keys(doc).sort());
  const sb = scene_blob(sc, cam, "basic");
  assert.equal(sb.filename, "basic.scene.json");
  assert.equal(sb.type, "application/json");
  const again = load_scene_text(sb.text);
  assert.deepEqual(again.camera.position, cam.position);
  assert.deepEqual(again.camera.target, cam.target);
  assert.equal(again.objects.length, sc.objects.length);
  assert.ok(camera_block_text(cam).endsWith("}\n"));
  assert.deepEqual(validate_camera(JSON.parse(camera_block_text(cam))).position, cam.position);
});

test("scene_blob of a yaw/pitch scene carries one camera form only and re-validates", () => {
  const sc = example("directional");
  const cam = camera_from_orbit(orbit_from_camera(sc.camera, sc), sc.camera);
  const text = scene_blob(sc, cam, "directional").text;
  const raw = JSON.parse(text);
  assert.equal(raw.camera.yaw_deg, undefined);
  assert.equal(raw.camera.pitch_deg, undefined);
  const again = load_scene_text(text);
  close3(again.camera.position, sc.camera.position, 1e-9, "position");
});

test("hidden lines in the downloads (phase 2 of §5.4.10): the scene's switch and style round-trip", () => {
  const sc = example("wall_and_ground");
  assert.equal(sc.output.hidden_lines, true);
  const A = shadow_geometry(sc);
  const cam = camera_from_orbit(orbit_from_camera(sc.camera, sc), sc.camera);
  const on = compose(sc, project_scene(sc, A, cam), true);
  const dashed = svg_blob(on, LAYER_ORDER, "wall_and_ground").text;
  assert.ok(dashed.includes('<g id="objects.hidden" stroke="#111" stroke-width="0.15" stroke-dasharray="0.5 0.5" fill="none">'));
  const omit = svg_blob(on, LAYER_ORDER, "wall_and_ground", "omit").text;
  assert.ok(omit.includes('<g id="objects.hidden.crate"/>') && !dashed.includes('<g id="objects.hidden.crate"/>'));
  // the checkbox state is written as output.hidden_lines, so the Python CLI reproduces the picture
  assert.equal(load_scene_text(scene_blob(sc, cam, "wall_and_ground", false).text).output.hidden_lines, false);
  assert.equal(load_scene_text(scene_blob(sc, cam, "wall_and_ground", true).text).output.hidden_lines, true);
  assert.equal(load_scene_text(scene_blob(sc, cam, "wall_and_ground").text).output.hidden_lines, true);
  const off = compose(sc, project_scene(sc, A, cam), false);
  assert.ok(!svg_blob(off, LAYER_ORDER, "wall_and_ground").text.includes(".hidden"));
});

test("mesh scenes (phase 2 of §5.4.10): an expanded mesh scene renders and orbits; a path-only one is a SceneError", () => {
  // the core reads expanded scenes only (§5.4.0): the bundled example names its OBJ file and shows the expand-first
  // error; its Python expansion (the port's test fixture) renders, and the scene download re-validates
  assert.throws(() => example("mesh_demo"), (e: any) => e.field === "objects[0].path" && /expanded first/.test(e.message));
  const sc = scene_file("ts", "test", "fixtures", "mesh_demo.expanded.json");
  const A = shadow_geometry(sc);
  const house = A.objects[0] as any;
  assert.equal(house.type, "mesh");
  assert.equal(house.triangles.length, 16); // scene3d's BufferGeometry: 5 quads and 2 pentagons as fans
  const cam = camera_from_orbit(orbit_from_camera(sc.camera, sc), sc.camera);
  const doc = compose(sc, project_scene(sc, A, cam));
  assert.ok(doc.edges.some((e: any) => e.object === "house" && "camera_silhouette" in e));
  const again = load_scene_text(scene_blob(sc, cam, "mesh_demo").text);
  assert.deepEqual(again.objects[0]!.data, sc.objects[0]!.data);
});

test("mesh scenes: the 3D view reuses stage A's triangles (world frame) instead of preprocessing again", () => {
  const sc = scene_file("ts", "test", "fixtures", "mesh_demo.expanded.json");
  const A = shadow_geometry(sc);
  const obj = sc.objects[0]!;
  const rec = A.objects[0]!;
  const from_a = mesh_positions(obj, rec);
  const local = mesh_positions(obj);
  assert.equal(from_a.world, true);
  assert.equal(local.world, false);
  assert.equal(from_a.positions.length, 16 * 9);
  assert.equal(local.positions.length, from_a.positions.length);
  // the same triangles: the local soup placed by transform_frame is the world soup (float32 rounding)
  const [R, p] = transform_frame(obj.transform);
  for (let k = 0; k < local.positions.length; k += 3) {
    const x = [local.positions[k]!, local.positions[k + 1]!, local.positions[k + 2]!];
    const w = [0, 1, 2].map((a) => R[a]![0]! * x[0]! + R[a]![1]! * x[1]! + R[a]![2]! * x[2]! + p[a]!);
    close3(w, [from_a.positions[k]!, from_a.positions[k + 1]!, from_a.positions[k + 2]!], 1e-5, `vertex ${k / 3}`);
  }
  // a record of another object is not used
  assert.equal(mesh_positions(obj, { ...rec, id: "other" }).world, false);
});

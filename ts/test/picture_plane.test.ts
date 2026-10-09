/** M10 core of the port: the `picture_plane` camera form (spec-v0.2 §4.1, §4.3; contract §5.7.13), mirroring
 * `tests/test_picture_plane.py`: equivalence with the hand-written target camera, translation invariance, input errors
 * with their field paths, no `CAMERA_LOOKING_ALONG_UP`, the `unproject_to_plane` round trip (< 1e-9 mm), the equation
 * strings (Python `format` rounding, exact ties to even) and the document key of this form only. */

import assert from "node:assert/strict";
import { test } from "node:test";

import { camera_forward, camera_matrix, divide, project } from "../src/camera.js";
import type { CameraRecord } from "../src/camera.js";
import { SceneError } from "../src/errors.js";
import { dumps } from "../src/output/geometry_json.js";
import { fixed, plane_equation, resolve_picture_plane, unproject_to_plane } from "../src/picture_plane.js";
import { render } from "../src/pipeline.js";
import { py_fixed } from "../src/pyfloat.js";
import { load_scene, validate_camera, validate_scene } from "../src/scene.js";
import type { Camera } from "../src/scene.js";
import type { Vec3 } from "../src/types.js";
import { read_example, read_json, repo_path } from "./helpers.js";

const CANDIDATE_NAMES = ["camera_picture_plane_vertical", "camera_picture_plane_tilted", "camera_picture_plane_horizontal"];
const EXAMPLES = ["basic", "construction_demo", "curved_demo", "directional", "three_point", "two_lights", "mesh_demo",
  "wall_and_ground"];
const DOC_KEYS = ["distance", "equation", "foot", "frame_m", "normal", "offset", "up"];
const TOL_MM = 1e-9;

function load_candidate(name: string): any {
  return read_json(repo_path("tests", "fixtures", "v8_candidates", `${name}.json`));
}

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x)) as T;
}

function lens(cam: any): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const k of ["focal_length_mm", "frame_mm", "shift_mm", "near_m"]) if (cam[k] !== undefined) out[k] = clone(cam[k]);
  return out;
}

function dot(a: readonly number[], b: readonly number[]): number {
  return a[0]! * b[0]! + a[1]! * b[1]! + a[2]! * b[2]!;
}

function cross(a: readonly number[], b: readonly number[]): Vec3 {
  return [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];
}

function norm(a: readonly number[]): number {
  return Math.sqrt(dot(a, a));
}

function unit(a: readonly number[]): Vec3 {
  const n = norm(a);
  return [a[0]! / n, a[1]! / n, a[2]! / n];
}

/** Independent derivation of the rows (right', up', forward): forward from the eye to the plane, up' = `up` (or world
 * z, +y when the plane is horizontal) projected onto the plane, right' = forward × up'. No roll angle involved. */
function expected_rows(position: readonly number[], normal: readonly number[], offset: number, up?: readonly number[]) {
  const n = unit(normal);
  const off = offset / norm(normal);
  const s = dot(n, position) + off;
  const sg = s > 0 ? -1 : 1;
  const f: Vec3 = [sg * n[0], sg * n[1], sg * n[2]];
  const a = up ?? (norm(cross(f, [0, 0, 1])) > 1e-9 ? [0, 0, 1] : [0, 1, 0]);
  const k = dot(a, f);
  const u = unit([a[0]! - k * f[0], a[1]! - k * f[1], a[2]! - k * f[2]]);
  return { rows: [cross(f, u), u, f], D: Math.abs(s), f };
}

/** The hand-written target camera of a picture_plane block (target far along the derived forward, roll from the
 * derived up). */
function hand_target_camera(cam: any): any {
  const pp = cam.picture_plane;
  const { rows, D, f } = expected_rows(cam.position, pp.normal, pp.offset, pp.up);
  const E = cam.position as number[];
  const target = [E[0]! + 3 * D * f[0], E[1]! + 3 * D * f[1], E[2]! + 3 * D * f[2]];
  const world_up = norm(cross(f, [0, 0, 1])) > 1e-9 ? [0, 0, 1] : [0, 1, 0];
  const r0 = unit(cross(f, world_up));
  const u0 = cross(r0, f);
  const rho = Math.atan2(-dot(rows[1]!, r0), dot(rows[1]!, u0)) * (180 / Math.PI);
  return { position: [...E], target, roll_deg: rho, ...lens(cam) };
}

/** Every numeric leaf within 1e-9 (absolute; relative above 1), identical structure and strings. */
function compare_docs(a: unknown, b: unknown, path = ""): void {
  if (Array.isArray(a)) {
    assert.ok(Array.isArray(b) && a.length === b.length, `${path}: length`);
    a.forEach((x, i) => compare_docs(x, (b as unknown[])[i], `${path}[${i}]`));
  } else if (a !== null && typeof a === "object") {
    assert.ok(b !== null && typeof b === "object" && !Array.isArray(b), `${path}: object`);
    assert.deepEqual(Object.keys(a).sort(), Object.keys(b as object).sort(), `${path}: keys`);
    for (const k of Object.keys(a)) compare_docs((a as any)[k], (b as any)[k], `${path}.${k}`);
  } else if (typeof a === "number") {
    assert.ok(typeof b === "number", `${path}: ${a} vs ${String(b)}`);
    assert.ok(Math.abs(a - b) <= TOL_MM * Math.max(1, Math.abs(a), Math.abs(b)), `${path}: ${a} vs ${b}`);
  } else {
    assert.equal(a, b, path);
  }
}

function polygon_area(p: readonly (readonly number[])[]): number {
  let s = 0;
  for (let i = 0; i < p.length; i++) {
    const q = p[i]!, r = p[(i + 1) % p.length]!; // pyimod-free: i >= 0
    s += q[0]! * r[1]! - r[0]! * q[1]!;
  }
  return 0.5 * s;
}

/** Equivalence of two documents of the same scene: `camera.picture_plane` aside, everything within 1e-9. */
function assert_same_picture(doc_pp: any, doc_t: any, ignore_codes: readonly string[] = []): void {
  const a = clone(doc_pp), b = clone(doc_t);
  assert.deepEqual(Object.keys(a.camera.picture_plane).sort(), DOC_KEYS);
  delete a.camera.picture_plane;
  for (const d of [a, b]) {
    // umbra: the region agrees, the piece split can move with the last bits of R (CLAUDE.md gotcha): compare areas
    for (const u of d.umbra ?? []) u.polygons = (u.polygons as number[][][]).reduce((s, p) => s + polygon_area(p), 0);
    d.warnings = (d.warnings as { code: string; ids: string[] }[])
      .filter((w) => !ignore_codes.includes(w.code)).map((w) => `${w.code}:${w.ids.join(",")}`).sort();
  }
  compare_docs(a, b);
}

function pp_from_camera(cam: Camera, D = 3.0, flip = false): any {
  const rec = camera_matrix(cam, [36, 24]);
  const f = rec.forward;
  let n: number[] = [...f], off = -(dot(f, cam.position) + D);
  if (flip) {
    n = n.map((v) => -v);
    off = -off;
  }
  return { position: [...cam.position], picture_plane: { normal: n, offset: off, up: [...rec.R[1]] }, ...lens(cam) };
}

/** Deterministic PRNG (mulberry32). */
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

function uniform(r: () => number, lo: number, hi: number): number {
  return lo + (hi - lo) * r();
}

/** `a` equals `b` component-wise within `tol` (no sign-of-zero distinction, numpy `assert_allclose`). */
function assert_vec(a: readonly number[], b: readonly number[], tol = 0, msg = ""): void {
  assert.equal(a.length, b.length, msg);
  for (let i = 0; i < a.length; i++) assert.ok(Math.abs(a[i]! - b[i]!) <= tol, `${msg} [${i}]: ${a[i]} vs ${b[i]}`);
}

function image(rec: CameraRecord, X: readonly number[]): [number, number] {
  return divide(project(rec, [X[0]!, X[1]!, X[2]!, 1]));
}

// ------------------------------------------------------------------------------------------------- equivalence

for (const name of CANDIDATE_NAMES) {
  test(`equivalence: ${name} equals its hand-written target camera`, () => {
    const scene = load_scene(load_candidate(name));
    const doc_pp = render(scene).geometry;
    const doc_t = render(scene, hand_target_camera(scene.camera)).geometry;
    assert_same_picture(doc_pp, doc_t, ["CAMERA_LOOKING_ALONG_UP"]);
    assert.ok(!doc_pp.warnings.some((w) => w.code === "CAMERA_LOOKING_ALONG_UP"));
  });
}

for (const name of EXAMPLES) {
  test(`equivalence: examples/${name}.json equals its picture_plane twin (both normal signs)`, () => {
    const scene = load_scene(read_example(`${name}.json`));
    const doc_t = render(scene).geometry;
    for (const flip of [false, true]) {
      const doc_pp = render(scene, pp_from_camera(scene.camera, 3.0, flip)).geometry;
      assert_same_picture(doc_pp, doc_t);
      const pp = doc_pp.camera.picture_plane!;
      assert.ok(Math.abs(pp.distance - 3.0) < 1e-12);
      const P2 = doc_t.camera.P[2]!.slice(0, 3);
      const want = unit(P2);
      for (let i = 0; i < 3; i++) assert.ok(Math.abs(pp.normal[i]! - want[i]!) <= 1e-12);
    }
  });
}

test("horizontal candidate looks straight down without CAMERA_LOOKING_ALONG_UP; the target form still warns", () => {
  const scene = load_scene(load_candidate("camera_picture_plane_horizontal"));
  const rec = camera_matrix(scene.camera, scene.output.canvas_mm);
  assert.deepEqual(rec.warnings, []);
  assert.deepEqual(rec.forward, [0, 0, -1]);
  assert_vec(rec.R[1], [0, 1, 0]); // the +y fallback, exactly
  const doc = render(scene).geometry;
  assert.equal(doc.horizon.segment, null);
  assert.equal(doc.horizon.v_mm, null);
  assert.equal(doc.camera.picture_plane!.equation, "z = 3.00");
  const t = { position: [0.2, 5.0, 7.0], target: [0.2, 5.0, 6.0], focal_length_mm: 24, frame_mm: [36, 24] };
  assert.deepEqual(camera_matrix(validate_camera(t), [36, 24]).warnings.map((w) => w.code), ["CAMERA_LOOKING_ALONG_UP"]);
});

for (const normal of [[0, 0, 1], [0, 0, -1], [0, 0, 2.5]]) {
  for (const above of [true, false]) {
    test(`horizontal plane normal ${JSON.stringify(normal)} (eye ${above ? "above" : "below"}) never warns`, () => {
      const E = [1.0, 2.0, above ? 5.0 : -1.0];
      const cam = validate_camera({ position: E, picture_plane: { normal, offset: -2.0 * normal[2]! }, focal_length_mm: 20,
        frame_mm: [36, 24] });
      const rec = camera_matrix(cam, [36, 24]);
      assert.deepEqual(rec.warnings, []);
      assert.deepEqual(rec.forward, [0, 0, above ? -1 : 1]);
      assert.equal(rec.picture_plane!.equation, "z = 2.00");
      assert.equal(rec.picture_plane!.distance, 3.0);
    });
  }
}

test("resolve_picture_plane returns the target form (spec-v0.2 §4.1 hand values)", () => {
  const cam = validate_camera({ position: [0.37, -2.0, 0.9], picture_plane: { normal: [0, 1, 0], offset: -2.0 },
    focal_length_mm: 20, frame_mm: [36, 24], near_m: 0.05 });
  const [tcam, roll, info] = resolve_picture_plane(cam);
  assert.equal(tcam.picture_plane, undefined);
  assert.deepEqual(tcam.target, [0.37, -1.0, 0.9]);
  assert.equal(roll, 0);
  assert.deepEqual({ position: tcam.position, focal_length_mm: tcam.focal_length_mm, frame_mm: tcam.frame_mm,
    shift_mm: tcam.shift_mm, near_m: tcam.near_m },
  { position: [0.37, -2.0, 0.9], focal_length_mm: 20, frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 });
  assert.deepEqual(info, { normal: [0, 1, 0], offset: -2.0, distance: 4.0, foot: [0.37, 2.0, 0.9] });
  assert.deepEqual(camera_forward(cam), [0, 1, 0]);
  assert.deepEqual(camera_matrix(cam, [36, 24]).picture_plane, {
    normal: [0, 1, 0], offset: -2.0, up: [0, 0, 1], distance: 4.0, foot: [0.37, 2.0, 0.9], frame_m: [7.2, 4.8],
    equation: "y = 2.00",
  });
});

test("the sign and the length of the normal do not matter", () => {
  const recs: CameraRecord[] = [];
  for (const [n, off] of [[[1, 2, -0.5], 3.0], [[-1, -2, 0.5], -3.0], [[10, 20, -5], 30.0]] as [number[], number][]) {
    const cam = validate_camera({ position: [0.5, -1.0, 2.0], focal_length_mm: 28, frame_mm: [36, 24],
      picture_plane: { normal: n, offset: off, up: [0.2, 0.0, 1.0] } });
    recs.push(camera_matrix(cam, [36, 24]));
  }
  const r0 = recs[0]!;
  for (const r of recs.slice(1)) {
    for (let i = 0; i < 3; i++) for (let j = 0; j < 4; j++) assert.ok(Math.abs(r.P[i]![j]! - r0.P[i]![j]!) <= 1e-12);
    assert.equal(r.picture_plane!.equation, r0.picture_plane!.equation);
    assert.ok(Math.abs(r.picture_plane!.distance - r0.picture_plane!.distance) < 1e-12);
  }
});

test("translation invariance: another offset along the same f changes only the plane keys", () => {
  const raw = load_candidate("camera_picture_plane_tilted");
  const scene = load_scene(raw);
  const docs = [1.4, 3.0, 9.5, -0.5].map((off) => {
    const c = clone(raw.camera);
    c.picture_plane.offset = off;
    return render(scene, c).geometry;
  });
  const ref = docs[0]!;
  for (const d of docs.slice(1)) {
    const a = clone(d) as any, b = clone(ref) as any;
    const pa = a.camera.picture_plane, pb = b.camera.picture_plane;
    delete a.camera.picture_plane;
    delete b.camera.picture_plane;
    assert.equal(dumps(a), dumps(b));
    assert.deepEqual(pa.normal, pb.normal);
    assert.deepEqual(pa.up, pb.up);
    for (const k of ["distance", "foot", "offset", "frame_m", "equation"]) assert.notDeepEqual(pa[k], pb[k], k);
    const ratio = pa.distance / pb.distance;
    for (let i = 0; i < 2; i++) assert.ok(Math.abs(pa.frame_m[i] / pb.frame_m[i] - ratio) <= 1e-12 * ratio);
  }
});

// ------------------------------------------------------------------------------------------------- input errors

function pp_cam(pp: Record<string, unknown> = {}): any {
  return { position: [0.0, -2.0, 1.0], picture_plane: { normal: [0, 1, 0], offset: -2.0, ...pp }, focal_length_mm: 20,
    frame_mm: [36, 24] };
}

const ERROR_ROWS: [string, (c: any) => void, string][] = [
  ["plane through E", (c) => { c.picture_plane.offset = 2.0; }, "camera.picture_plane.offset"],
  ["plane within 1e-9 of E", (c) => { c.picture_plane.offset = 2.0 + 5e-10; }, "camera.picture_plane.offset"],
  ["scaled plane through E", (c) => { c.picture_plane.normal = [0, 4, 0]; c.picture_plane.offset = 8.0; }, "camera.picture_plane.offset"],
  ["up parallel to n", (c) => { c.picture_plane.up = [0, 1, 0]; }, "camera.picture_plane.up"],
  ["up nearly parallel", (c) => { c.picture_plane.up = [0, -3, 1e-10]; }, "camera.picture_plane.up"],
  ["zero up", (c) => { c.picture_plane.up = [0, 0, 0]; }, "camera.picture_plane.up"],
  ["short up", (c) => { c.picture_plane.up = [0, 1]; }, "camera.picture_plane.up"],
  ["infinite up", (c) => { c.picture_plane.up = [0, Infinity, 1]; }, "camera.picture_plane.up[1]"],
  ["zero normal", (c) => { c.picture_plane.normal = [0, 0, 0]; }, "camera.picture_plane.normal"],
  ["tiny normal", (c) => { c.picture_plane.normal = [0, 1e-13, 0]; }, "camera.picture_plane.normal"],
  ["NaN normal", (c) => { c.picture_plane.normal = [0, NaN, 0]; }, "camera.picture_plane.normal[1]"],
  ["string normal", (c) => { c.picture_plane.normal = "y"; }, "camera.picture_plane.normal"],
  ["string offset", (c) => { c.picture_plane.offset = "2"; }, "camera.picture_plane.offset"],
  ["infinite offset", (c) => { c.picture_plane.offset = Infinity; }, "camera.picture_plane.offset"],
  ["missing normal", (c) => { delete c.picture_plane.normal; }, "camera.picture_plane.normal"],
  ["missing offset", (c) => { delete c.picture_plane.offset; }, "camera.picture_plane.offset"],
  ["not an object", (c) => { c.picture_plane = [0, 1, 0, -2]; }, "camera.picture_plane"],
  ["with target", (c) => { c.target = [0, 5, 1]; }, "camera"],
  ["with yaw/pitch", (c) => { c.yaw_deg = 0.0; c.pitch_deg = 0.0; }, "camera"],
  ["with yaw", (c) => { c.yaw_deg = 0.0; }, "camera"],
  ["with pitch", (c) => { c.pitch_deg = 0.0; }, "camera"],
  ["with roll_deg 10", (c) => { c.roll_deg = 10.0; }, "camera.roll_deg"],
  ["with roll_deg 0", (c) => { c.roll_deg = 0; }, "camera.roll_deg"],
  ["missing position", (c) => { delete c.position; }, "camera.position"],
];

for (const [label, mutate, field] of ERROR_ROWS) {
  test(`input error (${label}) names ${field}`, () => {
    const cam = pp_cam();
    mutate(cam);
    const s = load_candidate("camera_picture_plane_vertical");
    s.camera = cam;
    assert.throws(() => validate_scene(s), (e: unknown) => e instanceof SceneError && e.field === field);
    const scene = load_scene(load_candidate("camera_picture_plane_vertical"));
    assert.throws(() => render(scene, cam), (e: unknown) => e instanceof SceneError && e.field === field);
  });
}

test("error messages equal the Python reference", () => {
  const msg = (f: () => unknown) => {
    try {
      f();
    } catch (e) {
      if (e instanceof SceneError) return e.detail;
      throw e;
    }
    assert.fail("no SceneError");
  };
  assert.equal(msg(() => validate_camera({ ...pp_cam(), target: [0, 5, 1] })),
    "give exactly one of target, yaw_deg + pitch_deg or picture_plane");
  assert.equal(msg(() => validate_camera({ position: [0, 0, 1], focal_length_mm: 20, frame_mm: [36, 24] })),
    "needs target, yaw_deg + pitch_deg or picture_plane");
  assert.equal(msg(() => validate_camera({ ...pp_cam(), roll_deg: 5 })),
    "must not be given with picture_plane (the roll is carried by picture_plane.up)");
  assert.equal(msg(() => validate_camera(pp_cam({ offset: 2.0 }))),
    "the plane passes through camera.position (|n̂·position + offset| <= 1e-09 after normalising the normal)");
  assert.equal(msg(() => validate_camera(pp_cam({ up: [0, 2, 0] }))),
    "must not be parallel to picture_plane.normal (its projection onto the plane is zero)");
  assert.equal(msg(() => validate_camera(pp_cam({ up: [0, 0, 0] }))), "must be a nonzero vector");
  assert.equal(msg(() => validate_camera(pp_cam({ normal: [0, 0, 0] }))), "must be a nonzero vector (|normal| > 1e-12)");
  assert.equal(msg(() => validate_camera({ position: [0, 0, 1], target: [0, 1, 1], yaw_deg: 0, pitch_deg: 0,
    focal_length_mm: 20, frame_mm: [36, 24] })), "give either target or yaw_deg + pitch_deg, not both");
});

test("a plane just off the eye is accepted (s > 0: f = −n)", () => {
  const cam = validate_camera(pp_cam({ offset: 2.0 + 2e-9 }));
  assert.equal(cam.picture_plane!.offset, 2.0 + 2e-9);
  const rec = camera_matrix(cam, [36, 24]);
  assert_vec(rec.forward, [0, -1, 0]);
  assert.deepEqual(rec.warnings, []);
});

test("the validated block keeps the raw plane, has no roll_deg and validates again unchanged", () => {
  const cam = validate_camera({ position: [1, 2, 3], picture_plane: { normal: [0, 3, 4], offset: 10, up: [0, 0, 2] },
    focal_length_mm: 20, frame_mm: [36, 24] });
  assert.deepEqual(cam.picture_plane, { normal: [0, 3, 4], offset: 10, up: [0, 0, 2] });
  for (const k of ["roll_deg", "target", "yaw_deg"]) assert.ok(!(k in cam), k);
  assert.deepEqual(validate_camera(clone(cam)), cam);
  const no_up = validate_camera({ position: [1, 2, 3], picture_plane: { normal: [0, 1, 0], offset: 1 }, focal_length_mm: 20,
    frame_mm: [36, 24] });
  assert.ok(!("up" in no_up.picture_plane!));
});

test("validate_camera is a fixed point on floats (500 random planes)", () => {
  const r = rng(11);
  let n_checked = 0;
  for (let i = 0; i < 500; i++) {
    const n = [uniform(r, -1, 1), uniform(r, -1, 1), uniform(r, -1, 1)];
    const E = [uniform(r, -5, 5), uniform(r, -5, 5), uniform(r, -5, 5)];
    const off = uniform(r, -3, 3);
    if (norm(n) < 0.1 || Math.abs(dot(unit(n), E) + off / norm(n)) < 1e-3) continue;
    const once = validate_camera({ position: E, picture_plane: { normal: n, offset: off, up: [0.1, 0.2, 1.0] },
      focal_length_mm: 20, frame_mm: [36, 24] });
    assert.deepEqual(validate_camera(clone(once)), once);
    n_checked++;
  }
  assert.ok(n_checked > 400);
});

test("a camera override renders the same bytes as the scene camera", () => {
  const raw = load_candidate("camera_picture_plane_tilted");
  raw.camera.picture_plane.normal = [-0.35, -1.0, 0.2];
  const scene = load_scene(raw);
  const a = dumps(render(scene).geometry);
  assert.equal(dumps(render(scene, scene.camera).geometry), a);
  assert.equal(dumps(render(scene, clone(raw.camera)).geometry), a);
});

test("the frame fallback is decided on f itself; forward and R[2] are the document normal bit for bit", () => {
  const cam = validate_camera({ position: [0.37, -2.0, 0.9], picture_plane: { normal: [1e-9, 0.0, 1.0], offset: -3.0 },
    focal_length_mm: 20, frame_mm: [36, 24] });
  const rec = camera_matrix(cam, [36, 24]);
  assert.deepEqual(rec.warnings, []);
  assert.deepEqual(rec.picture_plane!.normal, [1e-9, 0.0, 1.0]);
  assert.deepEqual(rec.R[2], rec.picture_plane!.normal);
  assert.deepEqual(rec.forward, rec.picture_plane!.normal);
  assert_vec(rec.R[1], [0, 1, 0], 1e-15);
  assert.deepEqual(camera_forward(cam), rec.forward);
  for (const name of CANDIDATE_NAMES) {
    const scene = load_scene(load_candidate(name));
    const r = camera_matrix(scene.camera, scene.output.canvas_mm);
    assert.deepEqual(r.R[2], r.picture_plane!.normal);
  }
});

// ------------------------------------------------------------------------------------------------- document

test("camera.picture_plane exists only for the picture_plane form", () => {
  for (const name of ["basic", "directional"]) {
    const doc = render(load_scene(read_example(`${name}.json`))).geometry;
    assert.deepEqual(Object.keys(doc.camera).sort(), ["C", "P", "horizon_line", "principal_point"]);
  }
  const doc = render(load_scene(load_candidate("camera_picture_plane_tilted"))).geometry;
  assert.deepEqual(Object.keys(doc.camera).sort(), ["C", "P", "horizon_line", "picture_plane", "principal_point"]);
  const pp = doc.camera.picture_plane!;
  assert.deepEqual(Object.keys(pp).sort(), DOC_KEYS);
  const f = pp.normal, u = pp.up, Q = pp.foot, C = doc.camera.C;
  assert.ok(Math.abs(norm(f) - 1) < 1e-15 && Math.abs(norm(u) - 1) < 1e-15 && Math.abs(dot(f, u)) < 1e-15);
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(C[i]! + pp.distance * f[i]! - Q[i]!) <= 1e-12);
  assert.ok(Math.abs(dot(f, Q) + pp.offset) < 1e-12);
  assert.ok(dot(f, C) + pp.offset < 0);
  assert.ok(Math.abs(pp.frame_m[0] - 36 * pp.distance / 28) <= 1e-15 * pp.frame_m[0]);
  assert.ok(Math.abs(pp.frame_m[1] - 24 * pp.distance / 28) <= 1e-15 * pp.frame_m[1]);
  assert.equal(pp.equation, "0.322x + 0.919y - 0.230z = 1.286");
  const { rows, D } = expected_rows([-2.9, -1.2, 3.0], [-0.35, -1.0, 0.25], 1.4, [0.15, 0.0, 1.0]);
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(u[i]! - rows[1]![i]!) <= 1e-15);
  assert.ok(Math.abs(D - pp.distance) < 1e-15);
  assert.ok(!JSON.stringify(pp).includes("-0.0"));
});

for (const name of CANDIDATE_NAMES) {
  test(`${name} renders deterministically`, () => {
    const a = render(load_scene(load_candidate(name)));
    const b = render(load_scene(load_candidate(name)));
    assert.equal(dumps(a.geometry), dumps(b.geometry));
    assert.equal(a.svg, b.svg);
  });
}

test("candidate documents: equation, distance and frame_m", () => {
  const want: [string, string, number, [number, number]][] = [
    ["camera_picture_plane_vertical", "y = 2.00", 4.0, [7.2, 4.8]],
    ["camera_picture_plane_horizontal", "z = 3.00", 4.0, [6.0, 4.0]],
  ];
  for (const [name, eq, D, frame] of want) {
    const doc = render(load_scene(load_candidate(name))).geometry;
    const pp = doc.camera.picture_plane!;
    assert.equal(pp.equation, eq);
    assert.equal(pp.distance, D);
    for (let i = 0; i < 2; i++) assert.ok(Math.abs(pp.frame_m[i]! - frame[i]!) <= 1e-15 * frame[i]!);
    assert.ok(!doc.warnings.some((w) => w.code === "CAMERA_LOOKING_ALONG_UP"));
  }
});

// ------------------------------------------------------------------------------------------------- plane equation

const S2 = Math.sqrt(0.5);

const EQUATIONS: [number[], number, string][] = [
  [[0, 1, 0], -2.0, "y = 2.00"],
  [[0, -1, 0], 2.0, "y = 2.00"],
  [[0, -2, 0], 4.0, "y = 2.00"],
  [[1, 0, 0], 1.0, "x = -1.00"],
  [[-1, 0, 0], 1.0, "x = 1.00"],
  [[0, 0, -1], 3.0, "z = 3.00"],
  [[0, 0, 1], -3.0, "z = 3.00"],
  [[0, 1, 0], 3.0, "y = -3.00"],
  [[0, 0, 1], 0.0, "z = 0.00"],
  [[0, 0, -1], 0.0, "z = 0.00"],
  [[0, 0, 1], 0.001, "z = 0.00"],
  [[0, 0, -1], -0.004, "z = 0.00"],
  [[0, 0, 1], -0.006, "z = 0.01"],
  [[1, 0, 0], -1.005, "x = 1.00"],
  [[0, 1, 0], -0.125, "y = 0.12"],
  [[0, 1, 0], -0.375, "y = 0.38"],
  [[0, 1, 0], 0.125, "y = -0.12"],
  [[S2, S2, 0], -1.2, "0.707x + 0.707y = 1.200"],
  [[-S2, -S2, 0], 1.2, "0.707x + 0.707y = 1.200"],
  [[1, 1, 0], -1.2 * Math.sqrt(2), "0.707x + 0.707y = 1.200"],
  [[S2, S2, 0], 1.2, "0.707x + 0.707y = -1.200"],
  [[S2, S2, 0], -3 * S2, "0.707x + 0.707y = 2.121"],
  [[S2, -S2, 0], 0.0, "0.707x - 0.707y = 0.000"],
  [[-S2, S2, 0], 0.0, "0.707x - 0.707y = 0.000"],
  [[-S2, 0, S2], 0.0, "0.707x - 0.707z = 0.000"],
  [[S2, -S2, 0], 1e-4, "0.707x - 0.707y = 0.000"],
  [[0, -0.6, 0.8], 2.0, "0.600y - 0.800z = 2.000"],
  [[0, 0.6, 0.8], -0.0625, "0.600y + 0.800z = 0.062"],
  [[1e-4, 0.6, -0.8], 0.0, "0.600y - 0.800z = 0.000"],
  [[-1e-4, 0.6, -0.8], 0.0, "0.600y - 0.800z = 0.000"],
  [[-0.0004, 0, 1], -1.0, "1.000z = 1.000"],
  [[0.0004, 0, -1], 1.0, "1.000z = 1.000"],
  [[0.0004, 0, 1], -1.0, "1.000z = 1.000"],
  [[-0.0003, -0.6, 0.8], 2.0, "0.600y - 0.800z = 2.000"],
  [[0.0006, -0.6, 0.8], 2.0, "0.001x - 0.600y + 0.800z = -2.000"],
  [[1e-10, -0.6, 0.8], 0.0, "0.600y - 0.800z = 0.000"],
  [[0.3, 0.4, -Math.sqrt(0.75)], -5.0, "0.300x + 0.400y - 0.866z = 5.000"],
  [[0.0, 1.0, 1e-4], -2.0, "1.000y = 2.000"],
];

test("plane_equation: the table of tests/test_picture_plane.py and contract §5.7.5", () => {
  for (const [normal, offset, text] of EQUATIONS) assert.equal(plane_equation(normal, offset), text, `${JSON.stringify(normal)}, ${offset}`);
});

test("F2 / F3 round as Python format (exact ties to even), -0.00 loses its sign", () => {
  assert.equal(fixed(0.125, 2), "0.12");
  assert.equal(fixed(0.375, 2), "0.38");
  assert.equal(fixed(2.675, 2), "2.67");
  assert.equal(fixed(-0.001, 2), "0.00");
  assert.equal(fixed(0.0625, 3), "0.062");
  assert.equal(fixed(-0.125, 2), "-0.12");
  assert.equal(fixed(-0.0, 3), "0.000");
  assert.equal(py_fixed(-0.001, 2), "-0.00");
  assert.equal(py_fixed(2.5, 0), "2");
  assert.equal(py_fixed(3.5, 0), "4");
  // every exact tie of 2 and 3 decimals below 4 (x = j / 2^(d+1), j odd) against the integer rule
  for (const d of [2, 3]) {
    const q = 2 ** (d + 1);
    for (let j = 1; j < 4 * q; j += 2) {
      const x = j / q;
      const scaled = x * 10 ** d; // n + 0.5 exactly
      const n = Math.floor(scaled);
      const m = n % 2 === 0 ? n : n + 1; // pyimod-free: n >= 0
      const want = (m / 10 ** d).toFixed(d);
      assert.equal(py_fixed(x, d), want, `${x}`);
      assert.equal(py_fixed(-x, d), `-${want}`, `${-x}`);
    }
  }
});

// ------------------------------------------------------------------------------------------------- unproject

test("unproject_to_plane: the principal point is the foot; the canvas corners span frame_m along r' and u'", () => {
  const scene = load_scene(load_candidate("camera_picture_plane_tilted"));
  const rec = camera_matrix(scene.camera, scene.output.canvas_mm);
  const pp = rec.picture_plane!;
  const D = pp.distance;
  const Q = unproject_to_plane(rec, [rec.u0, rec.v0], D);
  for (let i = 0; i < 3; i++) assert.ok(Math.abs(Q[i] - pp.foot[i]!) <= 1e-14);
  const [W, H] = rec.canvas_mm;
  const c = unproject_to_plane(rec, [[-W / 2, -H / 2], [W / 2, -H / 2], [W / 2, H / 2]], D);
  assert.equal(c.length, 3);
  const e0 = [0, 1, 2].map((i) => c[1]![i]! - c[0]![i]!), e1 = [0, 1, 2].map((i) => c[2]![i]! - c[1]![i]!);
  assert.ok(Math.abs(norm(e0) - pp.frame_m[0]) <= 1e-14 * pp.frame_m[0]);
  assert.ok(Math.abs(norm(e1) - pp.frame_m[1]) <= 1e-14 * pp.frame_m[1]);
  for (let i = 0; i < 3; i++) {
    assert.ok(Math.abs(e0[i]! / pp.frame_m[0] - rec.R[0][i]!) <= 1e-14);
    assert.ok(Math.abs(e1[i]! / pp.frame_m[1] - pp.up[i]!) <= 1e-14);
  }
});

test("unproject_to_plane round trip with shift: < 1e-9 mm, on the plane within 1e-12", () => {
  const cam = validate_camera({ position: [0.3, -4.0, 2.2], picture_plane: { normal: [0.2, 1, -0.3], offset: 1.0,
    up: [0.1, 0.2, 1.0] }, focal_length_mm: 50, frame_mm: [36, 24], shift_mm: [2.0, -1.5] });
  const rec = camera_matrix(cam, [273, 182]);
  const pp = rec.picture_plane!;
  const r = rng(7);
  for (let i = 0; i < 200; i++) {
    const uv: [number, number] = [uniform(r, -180, 180), uniform(r, -120, 120)];
    const X = unproject_to_plane(rec, uv, pp.distance);
    const back = image(rec, X);
    assert.ok(Math.abs(back[0] - uv[0]) < TOL_MM && Math.abs(back[1] - uv[1]) < TOL_MM, `${uv} -> ${back}`);
    assert.ok(Math.abs(dot(X, pp.normal) + pp.offset) < 1e-12);
  }
});

// ------------------------------------------------------------------------------------------------- random cameras

/** A random picture_plane camera (the hypothesis strategy `pp_cameras` of the Python suite, seeded). */
function random_pp_camera(r: () => number): any {
  const E = [uniform(r, -20, 20), uniform(r, -20, 20), uniform(r, -20, 20)];
  const axis = Math.floor(r() * 4) - 1;
  let n: number[];
  if (axis < 0) {
    do n = [uniform(r, -1, 1), uniform(r, -1, 1), uniform(r, -1, 1)];
    while (norm(n) <= 0.1 || norm(cross(unit(n), [0, 0, 1])) <= 1e-3);
  } else {
    n = [0, 0, 0];
    n[axis] = [-1.0, 1.0, 2.5][Math.floor(r() * 3)]!;
  }
  const scale = [1.0, 0.25, 7.0][Math.floor(r() * 3)]!;
  n = n.map((v) => v * scale);
  const D = uniform(r, 0.05, 30);
  const side = r() < 0.5 ? -1 : 1;
  const offset = (-dot(unit(n), E) + side * D) * norm(n);
  const block: any = { normal: n, offset };
  if (r() < 0.6) {
    let up: number[];
    do up = [uniform(r, -1, 1), uniform(r, -1, 1), uniform(r, -1, 1)];
    while (norm(up) <= 0.1 || norm(cross(unit(up), unit(n))) <= 1e-3);
    block.up = up;
  }
  return { position: E, picture_plane: block, focal_length_mm: [12, 20, 35, 80][Math.floor(r() * 4)]!, frame_mm: [36, 24],
    shift_mm: r() < 0.5 ? [0, 0] : [3, -2] };
}

test("random cameras: independent rows, the hand-written target camera's picture, translation invariance, round trip", () => {
  const r = rng(2024);
  for (let k = 0; k < 200; k++) {
    const c = random_pp_camera(r);
    const rec = camera_matrix(validate_camera(c), [360, 240]);
    assert.deepEqual(rec.warnings, []);
    const { rows, D } = expected_rows(c.position, c.picture_plane.normal, c.picture_plane.offset, c.picture_plane.up);
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) assert.ok(Math.abs(rec.R[i]![j]! - rows[i]![j]!) <= 1e-12, `case ${k}`);
    assert.ok(Math.abs(rec.picture_plane!.distance - D) <= 1e-12 * Math.max(1, D));
    const t = camera_matrix(validate_camera(hand_target_camera(c)), [360, 240]);
    for (let p = 0; p < 40; p++) {
      const depth = uniform(r, 0.5, 40), a = uniform(r, -0.5, 0.5) * depth, b = uniform(r, -0.5, 0.5) * depth;
      const X = [0, 1, 2].map((i) => rec.C[i]! + depth * rec.R[2][i]! + a * rec.R[0][i]! + b * rec.R[1][i]!);
      const ia = image(rec, X), ib = image(t, X);
      assert.ok(Math.abs(ia[0] - ib[0]) < TOL_MM && Math.abs(ia[1] - ib[1]) < TOL_MM, `case ${k}: ${ia} vs ${ib}`);
    }
    const c2 = clone(c);
    const s = dot(unit(c.picture_plane.normal), c.position) + c.picture_plane.offset / norm(c.picture_plane.normal);
    c2.picture_plane.offset = c.picture_plane.offset + 0.5 * s * norm(c.picture_plane.normal);
    const rec2 = camera_matrix(validate_camera(c2), [360, 240]);
    assert.deepEqual(rec2.P, rec.P);
    assert.deepEqual(rec2.picture_plane!.normal, rec.picture_plane!.normal);
    for (let q = 0; q < 8; q++) {
      const uv: [number, number] = [uniform(r, -270, 270), uniform(r, -180, 180)];
      const X = unproject_to_plane(rec, uv, rec.picture_plane!.distance);
      const back = image(rec, X);
      assert.ok(Math.abs(back[0] - uv[0]) < TOL_MM && Math.abs(back[1] - uv[1]) < TOL_MM, `case ${k}: ${uv} -> ${back}`);
    }
    assert.equal(rec.picture_plane!.equation, plane_equation(rec.picture_plane!.normal, rec.picture_plane!.offset));
  }
});

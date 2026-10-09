/** Tests of the M9 observer's pure part (`web/src/observer.ts`; contract §5.6.8): the `unproject_to_plane` round
 * trip through the port's `camera_matrix`, the board derived from target / yaw-pitch / `picture_plane` scene cameras,
 * the frame corners, framing, the drawing on the frame, vertex rays, finite numbers over random cameras, and the
 * switch-off identity (the document is only read). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { LAYER_IDS, camera_matrix, compose, dumps, load_scene, project_scene, shadow_geometry, unproject_to_plane, write_svg } from "castplane";
import type { Camera, CameraRecord, GeometryDocument, Scene, Vec2, Vec3 } from "castplane";

import { camera_from_orbit, orbit_from_camera } from "../src/orbit.js";
import type { OrbitState } from "../src/orbit.js";
import {
  DRAWING_OFFSET_M, FRAMING_MAX_M, FRAMING_MIN_M, FRUSTUM_EXTEND, OBSERVER_DIST_MAX_M, OBSERVER_DIST_MIN_M,
  OBSERVER_EL_MAX_DEG, OBSERVER_EL_MIN_DEG, OBSERVER_D_M, board_labels, canvas_corners, clip_polygon, clip_segment,
  derive_board, dist_point_segment, document_drawables, first_inside, frame_view, framing_points, frustum, hit_point, hit_polyline,
  initial_view, line_art, observer_D, observer_basis, observer_project, orbit_camera, orbit_view, pinch_view,
  sample_arc, sample_ellipse, scene_centre, vertex_rays, zoom_view,
} from "../src/observer.js";
import type { Board } from "../src/observer.js";

// web/build/test/observer.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const raw = (name: string): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8"));
const example = (name: string): Scene => load_scene(raw(name));
/** The five examples of §5.6.9 (phase 1 of §5.4.10). */
const FIVE = ["basic", "construction_demo", "curved_demo", "directional", "three_point"];

const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}
function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < a.length; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
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

/** Canvas mm image of `X` through a camera record (`null` behind the eye). */
function image(rec: Pick<CameraRecord, "P">, X: readonly number[]): Vec2 | null {
  const x = rec.P.map((row) => row[0]! * X[0]! + row[1]! * X[1]! + row[2]! * X[2]! + row[3]!);
  if (!(x[2]! > 0)) return null;
  return [x[0]! / x[2]!, x[1]! / x[2]!];
}

/** Every number reachable from `x` is finite. */
function assertFinite(x: unknown, what: string): void {
  if (typeof x === "number") assert.ok(Number.isFinite(x), `${what}: ${x}`);
  else if (Array.isArray(x)) x.forEach((v, i) => assertFinite(v, `${what}[${i}]`));
  else if (x !== null && typeof x === "object") for (const [k, v] of Object.entries(x)) assertFinite(v, `${what}.${k}`);
}

/** A validated `picture_plane` camera in the given scene (the scene's lens fields otherwise). */
function pp_scene(name: string, cam: Record<string, unknown>): Scene {
  const data = raw(name);
  data["camera"] = cam;
  return load_scene(data);
}

/** The frame's record: the orbit's target-form block through the port's `camera_matrix` (as `main.ts` renders it). */
function frame_rec(scene: Scene, orbit: OrbitState): CameraRecord {
  return camera_matrix(camera_from_orbit(orbit, scene.camera), scene.output.canvas_mm);
}

function render(scene: Scene, cam: Camera | ReturnType<typeof camera_from_orbit>): { doc: GeometryDocument; rec: CameraRecord } {
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A, cam);
  return { doc: compose(scene, B), rec: B.camera };
}

// ------------------------------------------------------------------------------------------------ unproject round trip

test("unproject_to_plane round trip through camera_matrix < 1e-9 mm, at depth D (random cameras, roll, shift, focal)", () => {
  const r = rng(9);
  const CANVAS: Vec2 = [360, 240];
  for (let k = 0; k < 300; k++) {
    const form = k % 3;
    const position: Vec3 = [20 * r() - 10, 20 * r() - 10, 10 * r() - 2];
    const lens = { focal_length_mm: 8 * Math.pow(50, r()), frame_mm: [36, 24] as Vec2,
      shift_mm: [10 * r() - 5, 8 * r() - 4] as Vec2, near_m: 0.05 };
    let cam: Record<string, unknown>;
    if (form === 0) cam = { position, target: add(position, [2 * r() - 1, 2 * r() - 1, 2 * r() - 1]), roll_deg: 360 * r() - 180, ...lens };
    else if (form === 1) cam = { position, yaw_deg: 360 * r() - 180, pitch_deg: 170 * r() - 85, roll_deg: 360 * r() - 180, ...lens };
    else cam = { position, picture_plane: { normal: [2 * r() - 1, 2 * r() - 1, 2 * r() - 1], offset: 10 * r() - 5 }, ...lens };
    let rec: CameraRecord;
    try {
      rec = camera_matrix(cam as unknown as Camera, CANVAS);
    } catch {
      continue; // a degenerate random camera (e.g. a forward along the default up's fallback edge)
    }
    // the extended canvas rectangle (§2.2 step 3): the canvas plus the shift
    for (let j = 0; j < 10; j++) {
      const uv: Vec2 = [(r() - 0.5) * CANVAS[0] * 1.2, (r() - 0.5) * CANVAS[1] * 1.2];
      const D = 0.05 * Math.pow(2000, r());
      const X = unproject_to_plane(rec, uv, D);
      const back = image(rec, X)!;
      close(back[0], uv[0], 1e-9, `round trip u (${k}, ${j})`);
      close(back[1], uv[1], 1e-9, `round trip v (${k}, ${j})`);
      close(dot(rec.forward, sub(X, rec.C)), D, 1e-9 * Math.max(1, D), `depth (${k}, ${j})`);
    }
  }
});

// ------------------------------------------------------------------------------------------------ board derivation

test("board from the §5.4.10 hand camera: R = |target − position|, g = R − 4, Q = E + 4·forward, corners on the plane", () => {
  const scene = example("basic");
  const cam: Camera = { ...scene.camera, position: [4, -8, 5], target: [0, 0, 0.5], roll_deg: 0 };
  delete (cam as Partial<Camera>).yaw_deg;
  const orbit = orbit_from_camera(orbit_camera(cam, [0, 0, 0]), scene);
  close(orbit.distance, 10.012492197250394, 1e-12, "R");
  const rec = frame_rec(scene, orbit);
  const D = observer_D(cam, scene.output.canvas_mm);
  assert.equal(D, OBSERVER_D_M);
  const b = derive_board(rec, orbit, D);
  close(b.R, 10.012492197250394, 1e-12, "board R");
  close(b.g, 10.012492197250394 - 4, 1e-12, "g");
  close3(b.Q, add(rec.C, mul(rec.forward, 4)), 1e-12, "Q");
  close3(b.P, [0, 0, 0.5], 1e-9, "pivot");
  const W = scene.output.canvas_mm;
  b.corners.forEach((c, i) => {
    close(dot(b.f, c), dot(b.f, b.Q), 1e-9, `corner ${i} on the plane f·X = f·Q`);
    close3(image(rec, c)!, canvas_corners(W)[i]!, 1e-9, `corner ${i} reprojects to the canvas corner`);
  });
  const k = rec.K[0][0];
  close(b.frame_m[0], (W[0] * 4) / k, 1e-12, "frame width (m)");
  close(len(sub(b.corners[1]!, b.corners[0]!)), b.frame_m[0], 1e-9, "frame width from the corners");
  close(len(sub(b.corners[3]!, b.corners[0]!)), b.frame_m[1], 1e-9, "frame height from the corners");
  // frame size = frame_mm · D / focal
  close(b.frame_m[0], (scene.camera.frame_mm[0] * 4) / scene.camera.focal_length_mm, 1e-9, "frame_mm·D/focal");
});

test("board from a yaw/pitch scene camera (directional): the orbit's target / distance, corners reproject", () => {
  const scene = example("directional");
  const orbit = orbit_from_camera(orbit_camera(scene.camera, [0, 0, 0]), scene);
  const rec = frame_rec(scene, orbit);
  const b = derive_board(rec, orbit, observer_D(scene.camera, scene.output.canvas_mm));
  close3(b.P, orbit.target, 0, "pivot = orbit target");
  close(b.g, orbit.distance - 4, 0, "g");
  b.corners.forEach((c, i) => close3(image(rec, c)!, canvas_corners(scene.output.canvas_mm)[i]!, 1e-9, `corner ${i}`));
});

test("picture_plane scene camera (spec-v0.2 §4.1 block): orbit target = scene centre, R = 7.84, D = 4, g = 3.84, Q", () => {
  const block = { position: [0.37, -2, 0.9], picture_plane: { normal: [0, 1, 0], offset: -2 }, focal_length_mm: 20,
    frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
  const scene = pp_scene("basic", block);
  const centre: Vec3 = scene_centre({ bbox: [[-0.63, 4.84, 0], [1.37, 6.84, 1.8]] });
  close3(centre, [0.37, 5.84, 0.9], 1e-12, "bbox centre");
  const cam = orbit_camera(scene.camera, centre);
  assert.equal(cam.picture_plane, undefined);
  close3(cam.target!, [0.37, 5.84, 0.9], 1e-12, "orbit block target");
  const orbit = orbit_from_camera(cam, scene);
  close3(orbit.target, [0.37, 5.84, 0.9], 1e-9, "orbit target");
  close(orbit.distance, 7.84, 1e-9, "orbit distance R");
  const rec = frame_rec(scene, orbit);
  const D = observer_D(scene.camera, scene.output.canvas_mm);
  close(D, 4, 1e-12, "D");
  const b = derive_board(rec, orbit, D);
  close(b.g, 3.84, 1e-9, "g");
  close3(b.Q, [0.37, 2, 0.9], 1e-9, "Q");
  assert.equal(b.equation, "y = 2.00");
  // the picture is kept: the scene camera's record and the orbit frame's record agree
  const rec0 = camera_matrix(scene.camera, scene.output.canvas_mm);
  for (const X of [[0, 5, 0], [1, 7, 1.5], [-2, 4, 0.3]]) close3(image(rec, X)!, image(rec0, X)!, 1e-7, `picture of ${X}`);
  // offset −1: plane y = 1, D = 3, g = 4.84
  const scene1 = pp_scene("basic", { ...block, picture_plane: { normal: [0, 1, 0], offset: -1 } });
  const orbit1 = orbit_from_camera(orbit_camera(scene1.camera, centre), scene1);
  const D1 = observer_D(scene1.camera, scene1.output.canvas_mm);
  close(D1, 3, 1e-12, "D (offset −1)");
  const b1 = derive_board(frame_rec(scene1, orbit1), orbit1, D1);
  close(b1.g, 4.84, 1e-9, "g (offset −1)");
  close3(b1.Q, [0.37, 1, 0.9], 1e-9, "Q (offset −1)");
});

test("picture_plane D is clamped into [0.5, 12] m; the orbit pivot depth into [0.8, 40] m", () => {
  const lens = { focal_length_mm: 20, frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
  const far = pp_scene("basic", { position: [0, -30, 1], picture_plane: { normal: [0, 1, 0], offset: 0 }, ...lens });
  close(observer_D(far.camera, far.output.canvas_mm), 12, 0, "D clamped to 12");
  const near = pp_scene("basic", { position: [0, -0.1, 1], picture_plane: { normal: [0, 1, 0], offset: 0 }, ...lens });
  close(observer_D(near.camera, near.output.canvas_mm), 0.5, 0, "D clamped to 0.5");
  const behind = orbit_camera(near.camera, [0, -5, 1]); // the scene centre behind the eye
  close(len(sub(behind.target!, behind.position)), 0.8, 1e-12, "pivot depth clamped to 0.8");
});

// ------------------------------------------------------------------------------------------------ frustum, framing, view

test("frustum: E to each corner, continued to E + 1.9·(corner − E)", () => {
  const scene = example("basic");
  const orbit = orbit_from_camera(scene.camera, scene);
  const b = derive_board(frame_rec(scene, orbit), orbit, 4);
  const fr = frustum(b);
  assert.equal(fr.solid.length, 4);
  fr.dotted.forEach(([c, far], i) => {
    close3(c, b.corners[i]!, 0, `dotted start ${i}`);
    close3(far, add(b.E, mul(sub(b.corners[i]!, b.E), FRUSTUM_EXTEND)), 1e-12, `dotted end ${i}`);
  });
});

test("framing: centroid target, dist = clamp(2.3 · max radius, 6, 60), direction kept", () => {
  const v0 = { ...initial_view(), az_deg: 12, el_deg: 33 };
  const small = frame_view(v0, [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]);
  close3(small.target, [0.5, 0.5, 0], 1e-15, "centroid");
  assert.equal(small.dist, FRAMING_MIN_M);
  assert.equal(small.az_deg, 12);
  assert.equal(small.el_deg, 33);
  const mid = frame_view(v0, [[0, 0, 0], [10, 0, 0]]);
  close(mid.dist, 2.3 * 5, 1e-12, "2.3 · radius");
  const huge = frame_view(v0, [[0, 0, 0], [100, 0, 0]]);
  assert.equal(huge.dist, FRAMING_MAX_M);
  // the points of §5.6.4: E, Q, scene centre, point lights, ground point, four corners
  const scene = example("basic");
  const A = shadow_geometry(scene);
  const orbit = orbit_from_camera(scene.camera, scene);
  const b = derive_board(frame_rec(scene, orbit), orbit, 4);
  const c = scene_centre(A);
  const pts = framing_points(b, scene, c);
  assert.equal(pts.length, 3 + 1 + 1 + 4);
  close3(pts[3]!, scene.lights[0]!.position as Vec3, 0, "the point light");
  close3(pts[4]!, [c[0], c[1], 0], 0, "the ground point");
  const dirScene = example("directional");
  assert.equal(framing_points(b, dirScene, c).length, 3 + 1 + 4, "a directional light contributes no point");
  const v = frame_view(initial_view(), pts);
  assert.ok(v.dist >= FRAMING_MIN_M && v.dist <= FRAMING_MAX_M);
});

test("observer camera: drag, wheel and pinch bounds; projection of the target is the pane centre", () => {
  let v = initial_view();
  v = orbit_view(v, 100, 1000);
  assert.equal(v.el_deg, OBSERVER_EL_MAX_DEG);
  close(v.az_deg, 55 - 40, 1e-12, "az −= dx · 0.4°");
  v = orbit_view(v, 0, -5000);
  assert.equal(v.el_deg, OBSERVER_EL_MIN_DEG);
  assert.equal(zoom_view(v, 1e5).dist, OBSERVER_DIST_MAX_M);
  assert.equal(zoom_view(v, -1e5).dist, OBSERVER_DIST_MIN_M);
  close(zoom_view({ ...v, dist: 10 }, 100).dist, 10 * Math.exp(0.1), 1e-12, "dist · exp(0.001 · deltaY)");
  close(pinch_view({ ...v, dist: 10 }, 100, 200).dist, 5, 1e-12, "pinch out halves the distance");
  close(pinch_view({ ...v, dist: 10 }, 100, 1).dist, 60, 1e-12, "pinch: d ≥ 10 px, clamped");
  const w = { target: [1, 2, 3] as Vec3, dist: 10, az_deg: 55, el_deg: 28 };
  close3(observer_project(w, 600, 400, w.target)!, [300, 200], 1e-9, "target at the centre");
  const { pos, r, u, f } = observer_basis(w);
  close(len(sub(pos, w.target)), 10, 1e-12, "distance");
  close(dot(r, f), 0, 1e-15, "r ⊥ f");
  close(dot(u, f), 0, 1e-15, "u ⊥ f");
  assert.ok(u[2] > 0, "up is up");
  assert.equal(observer_project(w, 600, 400, add(pos, mul(f, -1))), null, "behind the observer");
  // the initial direction (§5.6.4): from 28° above, az 55° with the camera at target + dist·(sin az cos el, −cos az cos el, sin el)
  const i0 = observer_basis({ ...initial_view(), target: [0, 0, 0], dist: 1 });
  close3(i0.pos, [Math.sin(55 * Math.PI / 180) * Math.cos(28 * Math.PI / 180), -Math.cos(55 * Math.PI / 180) * Math.cos(28 * Math.PI / 180),
    Math.sin(28 * Math.PI / 180)], 1e-15, "initial direction");
});

test("hit-test helpers", () => {
  close(dist_point_segment([0, 1], [-1, 0], [1, 0]), 1, 0, "perpendicular");
  close(dist_point_segment([3, 0], [-1, 0], [1, 0]), 2, 0, "past the end");
  close(dist_point_segment([3, 4], [0, 0], [0, 0]), 5, 0, "degenerate segment");
  assert.equal(hit_point([null, [10, 10], [12, 10]], [11.6, 10], 3), 2);
  assert.equal(hit_point([[10, 10]], [20, 10], 3), -1);
  assert.ok(hit_polyline([[0, 0], [10, 0], null, [20, 20]], [5, 2], 3));
  assert.ok(!hit_polyline([[0, 0], [10, 0], null, [20, 20]], [15, 10], 3));
  // label anchors: the first one inside the pane (with margins), else the first one's projection
  const v = { target: [0, 0, 0] as Vec3, dist: 10, az_deg: 0, el_deg: 0 };
  const basis = observer_basis(v);
  const far_left = add([0, 0, 0], mul(basis.r, -100)), centre: Vec3 = [0, 0, 0];
  close3(first_inside(basis, 600, 400, [far_left, centre], [4, 170, 4, 24])!, [300, 200], 1e-9, "second anchor");
  const p = first_inside(basis, 600, 400, [far_left], [4, 170, 4, 24])!;
  assert.ok(p[0] < 0, "fallback: the first anchor");
});

// ------------------------------------------------------------------------------------------------ the drawing on the frame

test("clipping to the canvas rectangle", () => {
  assert.deepEqual(clip_segment([0, 0], [1, 1], 2, 2), [[0, 0], [1, 1]]);
  assert.equal(clip_segment([3, 3], [4, 4], 2, 2), null);
  const c = clip_segment([-4, 0], [4, 0], 2, 1)!;
  close3([...c[0], ...c[1]], [-2, 0, 2, 0], 1e-15, "clipped");
  const poly = clip_polygon([[-3, -3], [3, -3], [3, 3], [-3, 3]], 1, 2);
  assert.equal(poly.length, 4);
  for (const p of poly) assert.ok(Math.abs(p[0]) <= 1 && Math.abs(p[1]) <= 2);
  assert.equal(clip_polygon([[5, 5], [6, 5], [6, 6]], 1, 1).length, 0);
});

test("SVG arcs and ellipses are sampled in the v-up frame (sweep = counter-clockwise)", () => {
  const h = Math.SQRT1_2;
  const ccw = sample_arc({ start: [1, 0], end: [0, 1], rx: 1, ry: 1, rotation_deg: 0, large_arc: 0, sweep: 1 }, 2);
  close3([...ccw[1]!], [h, h], 1e-12, "short counter-clockwise quarter");
  const cw = sample_arc({ start: [1, 0], end: [0, 1], rx: 1, ry: 1, rotation_deg: 0, large_arc: 1, sweep: 0 }, 2);
  close3([...cw[1]!], [-h, -h], 1e-12, "long clockwise three quarters");
  // a rotated ellipse arc: every sample on the ellipse, the ends exact
  const e = { centre: [2, -1], rx: 3, ry: 1, rotation_deg: 30 };
  const pts = sample_ellipse(e, 12);
  const phi = (30 * Math.PI) / 180;
  const on = (p: readonly number[]): number => {
    const x = p[0]! - 2, y = p[1]! + 1;
    const a = x * Math.cos(phi) + y * Math.sin(phi), b = -x * Math.sin(phi) + y * Math.cos(phi);
    return (a * a) / 9 + b * b;
  };
  for (const p of pts) close(on(p), 1, 1e-12, "ellipse sample");
  const arc = sample_arc({ start: pts[1]!, end: pts[5]!, rx: 3, ry: 1, rotation_deg: 30, large_arc: 0, sweep: 1 });
  assert.deepEqual(arc[0], pts[1]);
  assert.deepEqual(arc.at(-1), pts[5]);
  for (const p of arc) close(on(p), 1, 1e-9, "arc sample");
  close3([...arc[16]!], [...pts[3]!], 1e-9, "the arc runs counter-clockwise through the middle sample");
});

test("the document's conic arcs sample onto their conics (curved_demo, basic)", () => {
  for (const name of ["curved_demo", "basic"]) {
    const scene = example(name);
    const { doc } = render(scene, scene.camera);
    let n = 0;
    for (const o of doc.outlines) {
      for (const c of o.conics) {
        for (const a of c.arcs) {
          for (const p of sample_arc(a)) {
            const x = [p[0], p[1], 1];
            let q = 0, s = 0;
            for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) {
              q += x[i]! * c.conic[i]![j]! * x[j]!;
              s += Math.abs(x[i]! * c.conic[i]![j]! * x[j]!);
            }
            assert.ok(Math.abs(q) <= 1e-6 * s, `${name}: arc sample off its conic (${q} / ${s})`);
            n++;
          }
        }
      }
    }
    assert.ok(n > 0, `${name}: no arc sampled`);
  }
});

test("the drawing on the frame reprojects onto the document drawables (< 1e-6 mm), at depth D − 0.012", () => {
  for (const name of FIVE) {
    const scene = example(name);
    const orbit = orbit_from_camera(scene.camera, scene);
    const cam = camera_from_orbit(orbit, scene.camera);
    const { doc, rec } = render(scene, cam);
    const D = 4;
    const art = line_art(doc, rec, D, new Set(LAYER_IDS));
    assert.ok(art.segments.length > 0 && art.fills.length > 0, `${name}: empty drawing`);
    const hw = scene.output.canvas_mm[0] / 2 + 1e-9, hh = scene.output.canvas_mm[1] / 2 + 1e-9;
    for (const s of art.segments) {
      for (let i = 0; i < 2; i++) {
        close3(image(rec, s.world[i]!)!, s.uv[i]!, 1e-6, `${name} ${s.style} reprojection`);
        close(dot(rec.forward, sub(s.world[i]!, rec.C)), D - DRAWING_OFFSET_M, 1e-9, `${name} depth`);
        assert.ok(Math.abs(s.uv[i]![0]) <= hw && Math.abs(s.uv[i]![1]) <= hh, `${name}: outside the canvas`);
      }
    }
    for (const f of art.fills) f.world.forEach((X, i) => close3(image(rec, X)!, f.uv[i]!, 1e-6, `${name} fill reprojection`));
    // an edge inside the canvas is drawn unchanged: its document segment is one of the frame's segments
    const inside = doc.edges.filter((e) => e.segment !== null && e.segment.every((p) => Math.abs(p[0]) < hw && Math.abs(p[1]) < hh));
    for (const e of inside) {
      const hit = art.segments.some((s) => s.layer === "objects" && s.uv.every((p, i) => p[0] === e.segment![i]![0] && p[1] === e.segment![i]![1]));
      assert.ok(hit, `${name}: edge ${e.from}-${e.to} missing on the frame`);
    }
    // the layers filter the drawing
    const only = line_art(doc, rec, D, new Set(["objects"]));
    assert.ok(only.segments.every((s) => s.layer === "objects") && only.fills.length === 0, `${name}: layer filter`);
    assert.equal(line_art(doc, rec, D, new Set()).segments.length, 0);
    // horizon: the document's segment, on the horizon layer
    const hz = doc.horizon.segment;
    const hz_in = hz !== null && clip_segment(hz[0], hz[1], hw, hh) !== null;
    assert.equal(art.segments.some((s) => s.style === "horizon"), hz_in, `${name}: horizon on the frame iff it crosses the canvas`);
  }
});

test("document_drawables covers every SVG layer with geometry (multi-light, hidden lines)", () => {
  const scene = example("two_lights");
  const { doc } = render(scene, scene.camera);
  const layers = new Set(document_drawables(doc).map((d) => d.layer));
  for (const l of ["horizon", "objects", "form_shadow", "cast_shadow", "construction"]) assert.ok(layers.has(l), `two_lights: ${l}`);
  const wall = example("wall_and_ground");
  const A = shadow_geometry(wall);
  const docH = compose(wall, project_scene(wall, A), true);
  const styles = new Set(document_drawables(docH).map((d) => d.style));
  assert.ok(styles.has("hidden"), "wall_and_ground: hidden runs drawn in the hidden style");
});

// ------------------------------------------------------------------------------------------------ vertex rays

test("vertex rays: the focus object's sight lines, crossings on the board, light rays through the vertex", () => {
  const scene = example("basic");
  const orbit = orbit_from_camera(scene.camera, scene);
  const { doc, rec } = render(scene, camera_from_orbit(orbit, scene.camera));
  const b = derive_board(rec, orbit, 4);
  const rays = vertex_rays(doc, scene, b, rec.near);
  const focus = scene.objects[0]!.id;
  const vertices = Object.keys(doc.points).filter((n) => new RegExp(`^${focus}\\.v\\d+$`).test(n));
  assert.equal(rays.sight.length, vertices.length);
  assert.ok(rays.crossings.length > 0);
  for (const c of rays.crossings) close(dot(b.f, sub(c, b.E)), 4, 1e-9, "P′ on the board");
  // each crossing images where its vertex does
  for (const [i, n] of vertices.entries()) {
    const P = (doc.points[n] as { world: Vec3 }).world;
    if (dot(b.f, sub(P, b.E)) > rec.near) {
      const c = rays.crossings[rays.sight.slice(0, i + 1).filter(([, X]) => dot(b.f, sub(X, b.E)) > rec.near).length - 1]!;
      close3(image(rec, c)!, image(rec, P)!, 1e-9, `P′ of ${n}`);
    }
  }
  const lightRays = doc.construction.rays.filter(([k, n]) => k === "L" && vertices.includes(n));
  assert.equal(rays.light.length, lightRays.length);
  assert.ok(rays.light.length > 0);
  // L, P, S collinear
  const L = scene.lights[0]!.position as Vec3;
  rays.light.forEach(([a, S], i) => {
    close3(a, L, 0, "starts at L");
    const P = (doc.points[lightRays[i]![1]] as { world: Vec3 }).world;
    const u = sub(P, L), v = sub(S, L);
    const cr = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
    assert.ok(len(cr) <= 1e-9 * len(u) * len(v), "L, P, S collinear");
  });
  assert.equal(rays.shadow_sight.length, rays.light.length);
  for (const c of rays.shadow_crossings) close(dot(b.f, sub(c, b.E)), 4, 1e-9, "S′ on the board");
  // a directional light: S → S + k·|P − S|·l̂ passes the vertex
  const dir = example("directional");
  const o2 = orbit_from_camera(dir.camera, dir);
  const r2 = render(dir, camera_from_orbit(o2, dir.camera));
  const rays2 = vertex_rays(r2.doc, dir, derive_board(r2.rec, o2, 4), r2.rec.near);
  assert.ok(rays2.light.length > 0, "directional: light rays");
  const l = dir.lights[0]!.direction as Vec3;
  for (const [S, T] of rays2.light) {
    const d = sub(T, S);
    close(dot(d, l) / (len(d) * len(l)), 1, 1e-12, "along the light direction (towards the light)");
  }
});

// ------------------------------------------------------------------------------------------------ finite numbers, identity

function all_geometry(doc: GeometryDocument, scene: Scene, rec: CameraRecord, orbit: { target: Vec3; distance: number }, D: number,
  centre: Vec3): unknown {
  const b = derive_board(rec, orbit, D);
  return { b, fr: frustum(b), art: line_art(doc, rec, D, new Set(LAYER_IDS)), rays: vertex_rays(doc, scene, b, rec.near),
    view: frame_view(initial_view(), framing_points(b, scene, centre)), labels: board_labels(b) };
}

test("every number finite: the five examples and 200 random cameras (incl. horizontal boards and roll)", () => {
  const r = rng(77);
  for (const name of FIVE) {
    const scene = example(name);
    const A = shadow_geometry(scene);
    const centre = scene_centre(A);
    const orbit0 = orbit_from_camera(orbit_camera(scene.camera, centre), scene);
    {
      const B = project_scene(scene, A, camera_from_orbit(orbit0, scene.camera));
      assertFinite(all_geometry(compose(scene, B), scene, B.camera, orbit0, 4, centre), `${name} scene camera`);
    }
    for (let k = 0; k < 40; k++) {
      let cam: Camera | ReturnType<typeof camera_from_orbit>;
      let orbit: { target: Vec3; distance: number };
      if (k % 5 === 4) {
        // a picture_plane camera with a horizontal board (looking straight down) and a rolled frame up
        const position: Vec3 = [centre[0] + 2 * r() - 1, centre[1] + 2 * r() - 1, 6 + 4 * r()];
        const roll = 2 * Math.PI * r();
        cam = { position, picture_plane: { normal: [0, 0, 1], offset: -(position[2] - 0.5 - 3 * r()), up: [Math.cos(roll), Math.sin(roll), 0] },
          focal_length_mm: 12 + 60 * r(), frame_mm: scene.camera.frame_mm, shift_mm: scene.camera.shift_mm, near_m: scene.camera.near_m };
        orbit = { target: [position[0], position[1], 0], distance: position[2] };
        const B = project_scene(scene, A, cam as Camera);
        const doc = compose(scene, B);
        assert.equal(doc.horizon.segment, null, "a horizontal board has no horizon on the frame");
        const D = observer_D(cam as Camera, scene.output.canvas_mm);
        assertFinite(all_geometry(doc, scene, B.camera, orbit, D, centre), `${name} horizontal ${k}`);
        continue;
      }
      const o: OrbitState = { ...orbit0, yaw_deg: 360 * r() - 180, pitch_deg: 178 * r() - 89, roll_deg: 360 * r() - 180,
        focal_length_mm: 8 * Math.pow(50, r()), distance: orbit0.distance * (0.3 + 2 * r()) };
      cam = camera_from_orbit(o, scene.camera);
      orbit = o;
      const B = project_scene(scene, A, cam);
      assertFinite(all_geometry(compose(scene, B), scene, B.camera, orbit, 4, centre), `${name} random ${k}`);
    }
  }
});

test("switch-off identity: building the observer geometry leaves the document and its SVG / JSON unchanged", () => {
  for (const name of [...FIVE, "two_lights"]) {
    const scene = example(name);
    const A = shadow_geometry(scene);
    const B = project_scene(scene, A, scene.camera);
    const doc = compose(scene, B);
    const before = structuredClone(doc);
    const svg0 = write_svg(doc, LAYER_IDS), json0 = dumps(doc);
    const orbit = orbit_from_camera(orbit_camera(scene.camera, scene_centre(A)), scene);
    all_geometry(doc, scene, B.camera, orbit, observer_D(scene.camera, scene.output.canvas_mm), scene_centre(A));
    assert.deepEqual(doc, before, `${name}: document mutated`);
    assert.equal(write_svg(doc, LAYER_IDS), svg0, `${name}: SVG changed`);
    assert.equal(dumps(doc), json0, `${name}: JSON changed`);
    // the same camera with and without the observer renders the same strings
    const doc2 = compose(scene, project_scene(scene, A, scene.camera));
    assert.equal(dumps(doc2), json0, `${name}: re-render differs`);
  }
});

test("labels: E with its coordinates, D, g, pivot, equation at a patch corner", () => {
  const scene = example("basic");
  const orbit = orbit_from_camera(scene.camera, scene);
  const b: Board = derive_board(frame_rec(scene, orbit), orbit, 4);
  const labels = board_labels(b);
  assert.deepEqual(labels.map((l) => l.id), ["E", "D", "g", "pivot", "equation"]);
  assert.ok(labels[0]!.text.startsWith("E（讀數）("));
  assert.equal(labels[1]!.text, "D = 4.00 m");
  assert.ok(labels[2]!.text.startsWith("板子離場景 g = "));
  assert.equal(labels[4]!.text, b.equation);
  close3(labels[4]!.at, b.patch[3]!, 0, "equation anchor");
  // the patch encloses the frame
  for (const c of b.corners) {
    const x = dot(sub(c, b.Q), b.r), y = dot(sub(c, b.Q), b.u);
    assert.ok(Math.abs(x) <= dot(sub(b.patch[1]!, b.Q), b.r) + 1e-9 && Math.abs(y) <= dot(sub(b.patch[2]!, b.Q), b.u) + 1e-9);
  }
});

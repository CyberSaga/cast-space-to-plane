/** Tests of plane mode's session and gestures (`web/src/plane.ts`) and the observer's M10 handles and hit test
 * (`web/src/observer.ts`; contract §5.7.8, §5.7.9, §5.7.10, §5.7.13): the right pane's gesture → rig mapping, the undo
 * stack driven through the session (drags, wheel bursts, views, equation, lock, sliders, pivot, undo, reset), the
 * "unedited scene camera" block, the readouts and notices, the picture-delta readout, and the handle hit test (arrow
 * tip > ring, the eye never). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { LAYER_IDS, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, validate_camera, write_svg } from "castplane";
import type { Scene, StageA, Vec2, Vec3 } from "castplane";

import {
  ARROW_LABEL, HIT_PX_MOUSE, HIT_PX_TOUCH, LABEL_GAP_PX, LABEL_H_PX, LABEL_OFFSET_PX, RING_HIT_FACTOR, RING_SEGMENTS, board_labels,
  derive_board, first_inside, frame_view, framing_points, handles_of, hit_handles, initial_view, label_width, layout_labels,
  observer_basis, observer_project, observer_project_with, scene_centre,
} from "../src/observer.js";
import type { ObserverView } from "../src/observer.js";
import {
  NOTICE_D_CLAMPED, NOTICE_EYE_BELOW_GROUND, NOTICE_R_CLAMPED, PlaneSession, RightPaneGesture, arrow_drag, object_centres,
  readout_lines, ring_drag, ring_grab,
} from "../src/plane.js";
import type { SessionScene } from "../src/plane.js";
import {
  KAPPA_DEG_PER_PX, arrowLength, arrowScreenVector, arrowTip, clone, foot, orbitRightPane, orbitRing, pan, ringRadius, sync,
  toCameraBlock, twoFinger, wheel,
} from "../src/rig.js";
import { OBJECT_ID_KEY, RECEIVER_ID_KEY, object_id_of } from "../src/helpers3d.js";
import type { TaggedNode } from "../src/helpers3d.js";

// web/build/test/plane.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const raw = (name: string): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8"));

const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const len = (p: readonly number[]): number => Math.sqrt(dot(p, p));

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}
function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}

interface Loaded { scene: Scene; A: StageA; ss: SessionScene }

function load(data: Record<string, unknown>): Loaded {
  const scene = load_scene(data);
  const A = shadow_geometry(scene);
  return { scene, A, ss: { camera: scene.camera, canvas_mm: scene.output.canvas_mm, centre: scene_centre(A),
    object_centres: object_centres(A.objects), vertices: A.vertices } };
}

const BASIC = load(raw("basic"));
const session = (l: Loaded = BASIC): PlaneSession => new PlaneSession(l.ss);
const CTX = { H_px: 480, frame_h: 24, snap: true };

/** The SVG text of `scene` rendered through `cam` (all layers). */
function svg_of(l: Loaded, cam: Scene["camera"] | ReturnType<typeof toCameraBlock>): string {
  return write_svg(compose(l.scene, project_scene(l.scene, l.A, cam)), l.scene.output.layers);
}

// ------------------------------------------------------------------------------------------------ session: load and block

test("load: the scene camera is rendered as it is until the first change; the rig's block has the same picture", () => {
  const s = session();
  assert.equal(s.scene_block, true);
  assert.equal(s.block(), BASIC.scene.camera, "the scene's own block (the CLI's document)");
  assert.deepEqual(s.load_notices, []);
  assert.equal(s.undo.size, 0);
  // the rig's picture_plane block: same images within 1e-7 mm (contract §5.7.7 load rule)
  const P0 = project_scene(BASIC.scene, BASIC.A, BASIC.scene.camera).camera.P;
  const P1 = project_scene(BASIC.scene, BASIC.A, s.rig_block()).camera.P;
  for (const X of BASIC.A.vertices) {
    const a = P0.map((r) => r[0] * X[0] + r[1] * X[1] + r[2] * X[2] + r[3]), b = P1.map((r) => r[0] * X[0] + r[1] * X[1] + r[2] * X[2] + r[3]);
    close(b[0]! / b[2]!, a[0]! / a[2]!, 1e-7, "u");
    close(b[1]! / b[2]!, a[1]! / a[2]!, 1e-7, "v");
  }
  // any change switches to the rig's picture_plane block
  assert.equal(s.set_roll(0), false, "a no-op keeps the scene block");
  assert.equal(s.scene_block, true);
  assert.equal(s.set_D(5), true);
  assert.equal(s.scene_block, false);
  const b = s.block() as ReturnType<typeof toCameraBlock>;
  assert.ok(b.picture_plane !== undefined && !("target" in b) && !("roll_deg" in b), "picture_plane form");
  assert.equal(b.picture_plane.up, undefined, "lock-horizontal and roll 0: up omitted");
  s.set_roll(10);
  assert.ok(Array.isArray((s.block() as ReturnType<typeof toCameraBlock>).picture_plane.up), "roll ≠ 0: up written");
  // the block validates as it is (Download scene / Copy camera block)
  assert.deepEqual(validate_camera(s.block()), validate_camera(validate_camera(s.block())));
});

test("load rule clamps: R and D out of range give notices and the rig's block from the start", () => {
  const data = raw("basic");
  // looking away from the scene: R = f·(P − E) < 0.8
  data["camera"] = { ...(data["camera"] as object), position: [0, 10, 1.5], target: [0, 20, 1.5] };
  const far = session(load(data));
  assert.deepEqual(far.load_notices, [NOTICE_R_CLAMPED]);
  assert.equal(far.scene_block, false);
  close(sync(far.rig).R, 0.8, 1e-12, "R clamped");
  const data2 = raw("basic");
  data2["camera"] = { position: [0, -20, 1.5], picture_plane: { normal: [0, 1, 0], offset: 0.5 }, focal_length_mm: 35,
    frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
  const dD = session(load(data2));
  assert.deepEqual(dD.load_notices, [NOTICE_D_CLAMPED]);
  assert.equal(dD.rig.D, 12);
  assert.equal(dD.scene_block, false);
  // a reset keeps the rig's block when the load clamped
  dD.set_D(4);
  dD.reset();
  assert.equal(dD.scene_block, false);
  assert.equal(dD.rig.D, 12);
});

// ------------------------------------------------------------------------------------------------ session: undo integration

test("drags: one undo step per gesture that changed the board; a press without change records nothing", () => {
  const s = session();
  s.begin();
  assert.equal(s.end(), false, "press without movement");
  assert.equal(s.undo.size, 0);
  s.begin();
  const rig0 = clone(s.rig);
  s.drag(orbitRightPane(rig0, 10, 0));
  s.drag(orbitRightPane(rig0, 30, 5));
  assert.equal(s.end(), true);
  assert.equal(s.undo.size, 1);
  // a drag that comes back to its start records nothing
  s.begin();
  const rig1 = clone(s.rig);
  s.drag(pan(rig1, 20, 0, 480, 24));
  s.drag(clone(rig1));
  assert.equal(s.end(), false);
  assert.equal(s.undo.size, 1);
  const r = s.undo_step();
  assert.ok(r.changed && r.framing);
  assert.deepEqual(s.rig.f, rig0.f);
  // cancel (a second finger on a handle drag) restores the pointer-down state without a step
  s.begin();
  const rig2 = clone(s.rig);
  s.drag(pan(rig2, 30, 10, 480, 24));
  s.cancel();
  assert.deepEqual(s.rig, rig2);
  assert.equal(s.undo.size, 0);
});

test("wheel: R ← R·exp(0.001·ΔY), never the focal length; a burst (≤ 400 ms) is one step", () => {
  const s = session();
  const R0 = sync(s.rig).R, focal = s.rig.focal;
  s.wheel(100, 1000);
  s.wheel(100, 1300);
  s.wheel(-50, 1650);
  close(sync(s.rig).R, R0 * Math.exp(0.15), 1e-12, "R");
  assert.equal(s.rig.focal, focal);
  assert.equal(s.undo.size, 1, "one burst");
  s.wheel(100, 2100); // 450 ms later: a new burst
  assert.equal(s.undo.size, 2);
  s.undo_step();
  close(sync(s.rig).R, R0 * Math.exp(0.15), 1e-12, "undo of the second burst");
  s.undo_step();
  close(sync(s.rig).R, R0, 1e-12, "undo of the first burst");
  assert.deepEqual(s.rig, wheel(s.rig, 0));
});

test("discrete actions: views, equation (and its errors), lock on; sliders and pivot are not undo steps", () => {
  const s = session();
  const v = s.view("top");
  assert.ok(v.changed && v.framing);
  assert.deepEqual(s.rig.f, [0, 0, -1]);
  assert.equal(s.undo.size, 1);
  assert.equal(s.view("top").changed, false, "the same view again records nothing");
  assert.equal(s.undo.size, 1);
  const bad = s.apply_equation("x==1");
  assert.ok(bad.error !== null && !bad.result.changed);
  assert.deepEqual(s.rig.f, [0, 0, -1], "the plane is kept");
  const ok = s.apply_equation("y=2");
  assert.equal(ok.error, null);
  assert.ok(ok.result.framing);
  assert.equal(s.undo.size, 2);
  close(sync(s.rig).E[1], -2, 1e-9, "y=2 with D = 4: the eye at y = −2");
  // sliders: no step
  s.set_D(6);
  s.set_roll(20);
  s.set_focal(50);
  assert.equal(s.undo.size, 2);
  // lock off: no step (nothing visible changes); lock on from free: one step
  s.set_lock_level(false);
  assert.ok(s.rig.up !== null);
  assert.equal(s.undo.size, 2);
  s.set_lock_level(true);
  assert.equal(s.rig.up, null);
  assert.equal(s.undo.size, 3);
  // pivot: object mode keeps the scene centre until a pick; a pick clears the pan, no step, re-frames
  const before = clone(s.rig);
  s.set_pivot_mode("object");
  assert.deepEqual(s.rig.P, BASIC.ss.centre);
  const id = BASIC.scene.objects[0]!.id;
  const r = s.pick_object(id);
  assert.ok(r.changed && r.framing);
  assert.deepEqual(s.rig.P, BASIC.ss.object_centres.get(id));
  assert.equal(s.rig.a, 0);
  assert.equal(s.rig.b, 0);
  assert.deepEqual(s.rig.f, before.f);
  assert.equal(s.rig.g, before.g);
  assert.equal(s.undo.size, 3, "a pivot change is not an undo step");
  assert.equal(s.pick_object("no such object").changed, false);
  s.set_pivot_mode("scene");
  assert.equal(s.pick_object(id).changed, false, "picking needs object mode");
  assert.deepEqual(s.rig.P, BASIC.ss.centre);
});

test("undo keeps the current pivot; reset restores the load state, the scene pivot and the scene camera's block", () => {
  const s = session();
  const init = clone(s.rig);
  s.view("left");
  s.set_pivot_mode("object");
  s.pick_object(BASIC.scene.objects[0]!.id);
  const P = clone(s.rig).P;
  s.undo_step();
  assert.deepEqual(s.rig.f, init.f);
  assert.deepEqual(s.rig.P, P, "undo keeps the picked pivot");
  s.set_focal(80);
  s.set_lock_level(false);
  const r = s.reset();
  assert.ok(r.framing);
  assert.deepEqual(s.rig, init);
  assert.deepEqual(s.pivot, { mode: "scene", object_id: null });
  assert.equal(s.scene_block, true);
  assert.equal(s.block(), BASIC.scene.camera);
  assert.ok(s.undo.size >= 1, "reset is an undo step");
  s.undo_step();
  assert.equal(s.rig.focal, 80, "undo of the reset");
});

// ------------------------------------------------------------------------------------------------ readouts

test("readouts: the spec-v0.2 §5.8 lines, the picture delta of a gesture, the eye-below-ground notice", () => {
  const s = session();
  const lines = s.readout_lines();
  assert.equal(lines.length, 7);
  assert.ok(lines[0]!.startsWith("投影平面："));
  assert.equal(lines.at(-1), "這次拖動右窗畫面變動：—");
  // a gesture that only rolls back to the start reads "unchanged"
  s.begin();
  const rig0 = clone(s.rig);
  s.drag(pan(rig0, 10, 0, 480, 24));
  s.drag(clone(rig0));
  s.end();
  assert.equal(s.readout_lines().at(-1), "這次拖動右窗畫面變動：0.00 mm（不變）");
  // a pan of 10 px in a 480 px pane moves every image by k = R·(24/focal)/480 per px, i.e. at the pivot's depth
  // 10·24/480 = 0.5 frame mm; nearer points move more
  s.begin();
  s.drag(pan(clone(s.rig), 10, 0, 480, 24));
  s.end();
  assert.ok(s.delta! >= 0.5 - 1e-9, `delta ${s.delta}`);
  // eye below the ground: the plane z = 0.5 under the pivot (z ≈ 1.2) is seen from below
  assert.equal(s.apply_equation("z=0.5").error, null);
  assert.ok(sync(s.rig).E[2] < 0);
  assert.ok(s.notices().includes(NOTICE_EYE_BELOW_GROUND));
  assert.deepEqual(readout_lines(s.rig, [36, 24], 0.004).at(-1), "這次拖動右窗畫面變動：0.00 mm（不變）");
});

// ------------------------------------------------------------------------------------------------ right-pane gestures

test("right pane: left drag = ring mapping from the pointer-down state and the total displacement", () => {
  const rig = session().rig;
  const g = new RightPaneGesture();
  assert.equal(g.down({ id: 1, x: 100, y: 100, button: 0 }, rig), "start");
  assert.equal(g.active, "orbit");
  const a = g.move({ id: 1, x: 110, y: 95 }, CTX)!;
  const b = g.move({ id: 1, x: 140, y: 120 }, CTX)!;
  assert.deepEqual(a, orbitRightPane(rig, 10, -5));
  assert.deepEqual(b, orbitRightPane(rig, 40, 20), "total displacement, not incremental");
  // −Δx·κ about z; dragging down raises the eye; g and R unchanged
  const yaw = Math.atan2(b.f[1], b.f[0]) - Math.atan2(rig.f[1], rig.f[0]);
  close(yaw, (-40 * KAPPA_DEG_PER_PX * Math.PI) / 180, 1e-12, "yaw");
  assert.ok(sync(b).E[2] > sync(a).E[2]);
  assert.equal(b.g, rig.g);
  assert.equal(g.move({ id: 2, x: 0, y: 0 }, CTX), null, "another pointer is not part of the gesture");
  assert.equal(g.up(1), true);
  assert.equal(g.active, null);
  // Alt (snap off) passes through
  g.down({ id: 3, x: 0, y: 0, button: 0 }, rig);
  assert.deepEqual(g.move({ id: 3, x: 5, y: 0 }, { ...CTX, snap: false }), orbitRightPane(rig, 5, 0, false));
  g.up(3);
});

test("right pane: right drag and Shift drag pan; the middle button is ignored; a mouse never starts two fingers", () => {
  const rig = session().rig;
  for (const p of [{ button: 2 }, { button: 0, shift: true }]) {
    const g = new RightPaneGesture();
    assert.equal(g.down({ id: 1, x: 0, y: 0, ...p }, rig), "start");
    assert.equal(g.active, "pan");
    const r = g.move({ id: 1, x: 30, y: -12 }, CTX)!;
    assert.deepEqual(r, pan(rig, 30, -12, CTX.H_px, CTX.frame_h));
    assert.deepEqual(r.P, rig.P, "the pivot never changes");
    assert.equal(g.down({ id: 2, x: 5, y: 5, type: "mouse" }, rig), "ignored");
    assert.equal(g.up(1), true);
  }
  assert.equal(new RightPaneGesture().down({ id: 1, x: 0, y: 0, button: 1 }, rig), "ignored");
});

test("right pane: two fingers = pinch (R·d₀/d) and pan of the midpoint; the whole gesture is one undo step", () => {
  const s = session();
  const g = new RightPaneGesture();
  assert.equal(g.down({ id: 1, x: 100, y: 100, type: "touch" }, s.rig), "start");
  s.begin();
  const one = g.move({ id: 1, x: 110, y: 100, type: "touch" }, CTX)!;
  s.drag(one);
  assert.equal(g.down({ id: 2, x: 210, y: 100, type: "touch" }, s.rig), "two");
  const base = clone(s.rig); // re-based on the state when the second finger arrived
  const two = g.move({ id: 2, x: 260, y: 120, type: "touch" }, CTX)!;
  // fingers at (110, 100) and (260, 120): d = √(150² + 20²), midpoint (185, 110); start d₀ = 100, midpoint (160, 100)
  assert.deepEqual(two, twoFinger(base, 100, Math.hypot(150, 20), [160, 100], [185, 110], CTX.H_px, CTX.frame_h));
  close(sync(two).R, (sync(base).R * 100) / Math.hypot(150, 20), 1e-12, "R scales by d₀/d");
  s.drag(two);
  assert.equal(g.up(2), false, "one finger lifted: the gesture goes on");
  assert.equal(g.move({ id: 1, x: 300, y: 300, type: "touch" }, CTX), null, "the remaining finger is frozen");
  assert.equal(g.up(1), true);
  assert.equal(s.end(), true);
  assert.equal(s.undo.size, 1, "one undo step for the whole gesture");
  assert.equal(g.down({ id: 4, x: 0, y: 0, type: "touch" }, s.rig), "start", "a new gesture after the release");
});

// ------------------------------------------------------------------------------------------------ observer handles

const VIEW: ObserverView = { target: [0.4, 4.8, 1.2], dist: 14, az_deg: 55, el_deg: 28 };
const W = 640, H = 760;

test("handles: the ring (72 points, radius of the frame, around Q in the frame's plane) and the arrow tip", () => {
  const s = session();
  const h = handles_of(s.rig, BASIC.scene.camera.frame_mm);
  const d = sync(s.rig);
  assert.equal(h.ring.length, RING_SEGMENTS);
  const rr = ringRadius(s.rig, BASIC.scene.camera.frame_mm);
  for (const X of h.ring) {
    close(len(sub(X, h.Q)), rr, 1e-12, "ring radius");
    close(dot(sub(X, h.Q), s.rig.f), 0, 1e-12, "ring on the board");
  }
  close3(h.Q, foot(s.rig), 0, "Q");
  close3(h.tip, arrowTip(s.rig), 0, "tip");
  close(len(sub(h.tip, h.Q)), arrowLength(s.rig.D), 1e-12, "arrow length");
  assert.ok(dot(sub(h.tip, h.Q), sub(d.E, h.Q)) > 0, "the arrow points from Q towards the eye");
  // labels: the arrow tip and a picked pivot object
  const rec = project_scene(BASIC.scene, BASIC.A, s.rig_block()).camera;
  const board = derive_board(rec, { target: s.rig.P, distance: d.R }, s.rig.D);
  const labels = board_labels(board, { pivot_id: "crate", tip: h.tip });
  assert.deepEqual(labels.map((l) => l.id), ["E", "D", "g", "pivot", "equation", "arrow"]);
  assert.equal(labels[3]!.text, "旋轉中心：crate");
  assert.equal(labels[5]!.text, ARROW_LABEL);
  assert.equal(board_labels(board).length, 5, "M9 labels without extras");
});

test("hit test: arrow tip > ring (0.8 × radius); touch radius 26 px; the eye is never returned", () => {
  const s = session();
  const h = handles_of(s.rig, BASIC.scene.camera.frame_mm);
  const basis = observer_basis(VIEW);
  const px = (X: readonly number[]): Vec2 => observer_project_with(basis, W, H, X)!;
  const tip = px(h.tip);
  assert.deepEqual(hit_handles(basis, W, H, tip, false, h), { kind: "arrow" });
  assert.deepEqual(hit_handles(basis, W, H, [tip[0] + HIT_PX_MOUSE - 0.5, tip[1]], false, h)?.kind, "arrow");
  // a ring point: hit, with the index of the nearer end of the nearest segment
  const k = 10, Rk = px(h.ring[k]!);
  assert.deepEqual(hit_handles(basis, W, H, Rk, false, h), { kind: "ring", index: k });
  // beyond 0.8 × 14 px from the ring (and the tip): nothing for a mouse, the ring for touch (0.8 × 26 px)
  const A = px(h.ring[k]!), B = px(h.ring[k + 1]!);
  const t: Vec2 = [B[0] - A[0], B[1] - A[1]];
  const tl = Math.hypot(t[0], t[1]);
  const nrm: Vec2 = [-t[1] / tl, t[0] / tl];
  const centre = px(h.Q);
  const out = Math.sign((A[0] - centre[0]) * nrm[0] + (A[1] - centre[1]) * nrm[1]) || 1;
  const at = (dpx: number): Vec2 => [(A[0] + B[0]) / 2 + out * nrm[0] * dpx, (A[1] + B[1]) / 2 + out * nrm[1] * dpx];
  assert.equal(hit_handles(basis, W, H, at(HIT_PX_MOUSE * RING_HIT_FACTOR + 1), false, h), null);
  assert.equal(hit_handles(basis, W, H, at(HIT_PX_TOUCH * RING_HIT_FACTOR - 1), true, h)?.kind, "ring");
  // the eye: never a handle (here it lies far from both handles, so the test returns null: an observer orbit)
  const E = px(sync(s.rig).E);
  assert.equal(hit_handles(basis, W, H, E, false, h), null);
  assert.equal(hit_handles(basis, W, H, E, true, h), null);
  // the arrow wins where the tip and the ring overlap
  const s2 = session();
  s2.set_D(0.5); // short arrow (0.3 m): the tip lies inside the ring's band in the picture
  const h2 = handles_of(s2.rig, BASIC.scene.camera.frame_mm);
  const tip2 = observer_project(VIEW, W, H, h2.tip)!;
  assert.deepEqual(hit_handles(basis, W, H, tip2, true, h2), { kind: "arrow" });
});

test("left-pane drags: ring and arrow mappings from the pointer-down state (the eye moves rigidly / along f)", () => {
  const s = session();
  const rig0 = clone(s.rig);
  const h = handles_of(rig0, BASIC.scene.camera.frame_mm);
  const basis = observer_basis(VIEW);
  const grab = ring_grab(h.ring[18]!, rig0.P, basis.r, basis.u);
  close3(grab.w, sub(h.ring[18]!, rig0.P), 0, "w");
  const r1 = ring_drag(rig0, grab, 30, -10, false);
  assert.deepEqual(r1, orbitRing(rig0, 30, -10, grab, false));
  close(len(sub(sync(r1).E, rig0.P)), len(sub(sync(rig0).E, rig0.P)), 1e-9, "|E − P|");
  assert.equal(r1.g, rig0.g);
  const v = arrowScreenVector(rig0, (X) => observer_project(VIEW, W, H, X));
  const r2 = arrow_drag(rig0, v, v[0] * 0.5, v[1] * 0.5, false); // half a metre along +f on screen: the board moves 0.5 m towards the scene
  close(r2.g, rig0.g - 0.5, 1e-12, "g");
  assert.deepEqual(r2.f, rig0.f);
  close3(sub(sync(r2).E, sync(rig0).E), rig0.f.map((x) => x * 0.5), 1e-12, "the eye moves along f");
});

// ------------------------------------------------------------------------------------------------ Download scene round trip

test("Download scene: the rig's picture_plane block reloads to the same SVG (scene camera rendered as it is)", () => {
  const s = session();
  s.view("left");
  s.set_roll(12);
  s.set_D(5.3);
  const block = s.block();
  const text = dumps({ ...BASIC.scene, camera: block });
  const l2 = load(JSON.parse(text));
  const s2 = session(l2);
  assert.equal(s2.scene_block, true);
  assert.equal(svg_of(l2, s2.block()), svg_of(BASIC, block));
  assert.equal(load_scene_text(text).camera.picture_plane !== undefined, true);
  // the reloaded rig reproduces the state (load rule of a picture_plane block)
  close3(s2.rig.f, s.rig.f, 1e-12, "f");
  close(s2.rig.g, s.rig.g, 1e-9, "g");
  close(s2.rig.D, s.rig.D, 1e-12, "D");
  close(s2.rig.roll_deg, 12, 1e-9, "roll");
});

// ------------------------------------------------------------------------------------------------ M10 review fixes

test("wheel inside an open drag gesture is ignored: the gesture stays one undo step and the move is not undone", () => {
  const s = session();
  const rig0 = clone(s.rig);
  s.begin();
  s.drag(orbitRightPane(rig0, 20, 0));
  const mid = clone(s.rig);
  assert.equal(s.wheel(300, 1000), false, "no wheel step during a drag");
  assert.deepEqual(s.rig, mid);
  s.drag(orbitRightPane(rig0, 40, 0));
  assert.equal(s.end(), true);
  assert.equal(s.undo.size, 1, "one physical gesture, one undo step");
  s.undo_step();
  assert.deepEqual(s.rig, rig0);
  assert.equal(s.undo.size, 0);
  // after the release the wheel works again
  assert.equal(s.wheel(300, 2000), true);
});

test("a gesture held across a scene load does not reach the new session", () => {
  const old = session();
  const g = new RightPaneGesture();
  assert.equal(g.down({ id: 1, x: 100, y: 100, button: 0 }, old.rig), "start");
  old.begin();
  // the page loads another scene: a new session, the held gesture is dropped
  const fresh = session(load(raw("curved_demo")));
  const rig = clone(fresh.rig);
  g.reset();
  assert.equal(g.active, null);
  assert.equal(g.move({ id: 1, x: 140, y: 100 }, CTX), null, "the old pointer moves nothing");
  assert.equal(g.up(1), false, "its release ends nothing");
  // even a state computed from the old scene's pointer-down rig is ignored outside a gesture of this session
  assert.equal(fresh.drag(orbitRightPane(old.rig, 40, 0)), false);
  assert.deepEqual(fresh.rig, rig);
  assert.equal(fresh.scene_block, true);
});

test("switching the pivot mode without a pick keeps the pan (the pivot point did not change)", () => {
  const s = session();
  s.begin();
  s.drag(pan(clone(s.rig), 30, 10, 480, 24));
  s.end();
  const panned = clone(s.rig);
  assert.ok(panned.a !== 0 || panned.b !== 0);
  const r = s.set_pivot_mode("object");
  assert.deepEqual(r, { changed: false, framing: false });
  assert.deepEqual(s.rig, panned);
  // an explicit pick re-centres the picked object (pan cleared), also when it is picked again after a pan
  const id = BASIC.scene.objects[0]!.id;
  assert.ok(s.pick_object(id).changed);
  s.begin();
  s.drag(pan(clone(s.rig), 30, 10, 480, 24));
  s.end();
  const again = s.pick_object(id);
  assert.ok(again.changed && again.framing);
  assert.equal(s.rig.a, 0);
  assert.equal(s.rig.b, 0);
  // back to the scene centre: a real pivot change clears the pan
  s.begin();
  s.drag(pan(clone(s.rig), 30, 10, 480, 24));
  s.end();
  const back = s.set_pivot_mode("scene");
  assert.ok(back.changed && back.framing);
  assert.deepEqual(s.rig.P, BASIC.ss.centre);
  assert.equal(s.rig.a, 0);
});

test("object picking identifies objects by their userData tag, whatever their id (an id may contain ':')", () => {
  const node = (userData: Record<string, unknown>, parent: TaggedNode | null): TaggedNode => ({ userData, parent });
  const group = node({}, null);
  const crate = node({ [OBJECT_ID_KEY]: "crate:1" }, group);
  const tricky = node({ [OBJECT_ID_KEY]: "receiver:x" }, group);
  const ground = node({ [RECEIVER_ID_KEY]: "ground" }, group);
  const light = node({}, group);
  assert.equal(object_id_of(crate, group), "crate:1");
  assert.equal(object_id_of(tricky, group), "receiver:x");
  assert.equal(object_id_of(node({}, crate), group), "crate:1", "a nested child climbs to its object");
  assert.equal(object_id_of(ground, group), null);
  assert.equal(object_id_of(light, group), null);
  assert.equal(object_id_of(group, group), null);
  // scene3d.ts tags every object mesh and every receiver plate (the browser smoke picks an object named "crate:1")
  const src = readFileSync(resolve(ROOT, "web", "src", "scene3d.ts"), "utf-8");
  assert.ok(src.includes("mesh.userData[OBJECT_ID_KEY] = obj.id;"));
  assert.equal(src.match(/userData\[RECEIVER_ID_KEY\] = rec\.id;/g)?.length, 2);
});

test("no element id of the page equals an id of the SVG overlay (layers, sub-layers)", () => {
  const html = readFileSync(resolve(ROOT, "web", "index.html"), "utf-8");
  const page = [...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]!);
  const svgIds = new Set<string>(LAYER_IDS);
  for (const name of ["basic", "two_lights", "wall_and_ground"]) {
    const l = load(raw(name));
    for (const m of svg_of(l, l.scene.camera).matchAll(/\bid="([^"]+)"/g)) svgIds.add(m[1]!);
  }
  assert.deepEqual(page.filter((id) => svgIds.has(id)), []);
});

test("observer labels never overlap: the default basic state (D next to 板子距離, 旋轉中心 next to g) is laid apart", () => {
  const boxOverlap = (a: { x: number; y: number; w: number; h: number }, b: typeof a): boolean =>
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
  let raw_overlaps = 0;
  for (const [name, aspect] of [["basic", 640 / 480], ["basic", 480 / 640], ["curved_demo", 640 / 480], ["three_point", 1]] as const) {
    const l = load(raw(name));
    const s = session(l);
    const d = sync(s.rig);
    const rec = project_scene(l.scene, l.A, s.block()).camera;
    const board = derive_board(rec, { target: s.rig.P, distance: d.R }, s.rig.D);
    const h = handles_of(s.rig, l.scene.camera.frame_mm);
    const labels = board_labels(board, { tip: h.tip });
    const Hp = 480, Wp = Math.round(Hp * aspect);
    const view = frame_view(initial_view(), framing_points(board, l.scene, l.ss.centre), Wp / Hp);
    const basis = observer_basis(view);
    const items = labels.map((lb) => ({ id: lb.id, text: lb.text,
      p: first_inside(basis, Wp, Hp, [lb.at, ...(lb.alt ?? [])], lb.alt !== undefined ? [4, 170, 4, 24] : [0, 0, 0, 0]) }));
    // without the layout rule (each box at its anchor plus its offset)
    const naive = items.map((it) => it.p === null ? null : { x: it.p[0] + (LABEL_OFFSET_PX[it.id]?.[0] ?? 10),
      y: it.p[1] + (LABEL_OFFSET_PX[it.id]?.[1] ?? -18), w: label_width(it.text), h: LABEL_H_PX });
    const boxes = layout_labels(items);
    for (let i = 0; i < boxes.length; i++) {
      assert.ok(boxes[i] !== null, `${name}: label ${labels[i]!.id} shown`);
      assert.equal(boxes[i]!.x, naive[i]!.x, "labels only move vertically");
      for (let j = 0; j < i; j++) {
        if (boxOverlap(naive[i]!, naive[j]!)) raw_overlaps++;
        assert.ok(!boxOverlap(boxes[i]!, boxes[j]!), `${name} ${aspect}: ${labels[i]!.id} overlaps ${labels[j]!.id}`);
      }
    }
  }
  assert.ok(raw_overlaps > 0, "the cases exercise the rule");
  // the rule itself: a later label moves below the earlier one, gap included; a hidden anchor blocks nothing
  const b = layout_labels([{ id: "x", p: [0, 0], text: "abc" }, { id: "y", p: null, text: "abc" }, { id: "z", p: [5, 4], text: "abc" }]);
  assert.equal(b[1], null);
  assert.equal(b[2]!.y, b[0]!.y + LABEL_H_PX + LABEL_GAP_PX);
});

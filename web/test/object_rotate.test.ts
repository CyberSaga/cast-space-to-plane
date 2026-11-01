/** Tests of M11 single-object rotation (`web/src/object_rotate.ts`; spec-v0.3 §2, §3, §5; contract §5.8.8): the
 * matrix round trip of the Z-Y-X decomposition (incl. gimbal lock), the fixed pivot under repeated rotations (cone and
 * prism included, checked against stage A), the pivot's independence of the load pose, numeric entry ≡ drag, the
 * rotation about z modulo 360, the ring geometry and drag angle, snapping, the fields' parsing, the ground translation
 * and the `ObjectDrag` state machine. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { curved, euler_zyx_matrix, load_scene, shadow_geometry, transform_frame } from "castplane";
import type { Mat3, Scene, StageA, Transform, Vec3 } from "castplane";

import {
  EDGE_ON_EPS, LIVE_STAGE_A_MS, OBJECT_RING_MIN_M, OBJECT_RING_SEGMENTS, OBJECT_SNAP_DEG, ObjectDrag, axis_rotation,
  clone_transform, euler_zyx_from_matrix, format_angle, ground_transform, local_bbox, local_centre, matmul, object_rings,
  parse_angle, ring_drag_angle, ring_points, ring_radius, rotate_about_world_axis, same_transform, set_rotation, snap_angle,
  world_centre, wrap_angle,
} from "../src/object_rotate.js";
import type { Axis, ObjectDragEffects } from "../src/object_rotate.js";
import { KAPPA_DEG_PER_PX } from "../src/rig.js";

// web/build/test/object_rotate.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const raw = (name: string): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8"));

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}
function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}
function closeM(A: Mat3, B: Mat3, tol: number, what: string): void {
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) close(A[i][j], B[i][j], tol, `${what}[${i}][${j}]`);
}
/** `(a − b) mod 360` in `(−180, 180]`. */
const angle_diff = (a: number, b: number): number => wrap_angle(a - b);

/** A deterministic pseudo-random stream in [0, 1). */
function rng(seed: number): () => number {
  let s = seed;
  return () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
}

/** Rodrigues' rotation about the unit axis `k` by `deg`. */
function rodrigues(k: Vec3, deg: number): Mat3 {
  const a = (deg * Math.PI) / 180, c = Math.cos(a), s = Math.sin(a), v = 1 - c;
  const [x, y, z] = k;
  return [
    [c + x * x * v, x * y * v - z * s, x * z * v + y * s],
    [y * x * v + z * s, c + y * y * v, y * z * v - x * s],
    [z * x * v - y * s, z * y * v + x * s, c + z * z * v],
  ];
}

/** A scene of `basic` with its objects replaced by `objects` (raw JSON objects). */
function scene_with(objects: unknown[]): Scene {
  const data = raw("basic");
  data["objects"] = objects;
  return load_scene(data);
}

const PRISM = { id: "wedge", type: "prism", polygon: [[0, 0], [1.2, 0], [0.3, 0.7], [-0.2, 0.4]], height: 0.9 };
const CONE = { id: "spike", type: "cone", radius: 0.35, height: 1.4 };

/** Stage A's world vertices of object `id`. */
const vertices_of = (A: StageA, id: string): Vec3[] => A.objects.find((o) => o.id === id)!.mesh.vertices;

/** The scene with object `id` at pose `t` (the old scene is not mutated). */
const with_pose = (scene: Scene, id: string, t: Transform): Scene =>
  ({ ...scene, objects: scene.objects.map((o) => o.id === id ? { ...o, transform: clone_transform(t) } : o) });

// ------------------------------------------------------------------------------------------------ Euler decomposition

test("matrix round trip: random R (Euler and axis-angle) and gimbal lock ry = ±90°, < 1e-12 per element", () => {
  const r = rng(4242);
  for (let i = 0; i < 400; i++) {
    const e: Vec3 = [360 * r() - 180, 180 * r() - 90, 360 * r() - 180];
    const R = euler_zyx_matrix(e);
    const back = euler_zyx_from_matrix(R);
    closeM(euler_zyx_matrix(back), R, 1e-12, `Euler ${e}`);
    assert.ok(back[1] >= -90 && back[1] <= 90, "ry in [−90, 90]");
    assert.ok(back[0] > -180 && back[0] <= 180 && back[2] > -180 && back[2] <= 180, "rx, rz in (−180, 180]");
    let k: Vec3 = [2 * r() - 1, 2 * r() - 1, 2 * r() - 1];
    const l = Math.hypot(...k);
    if (l < 1e-3) continue;
    k = [k[0] / l, k[1] / l, k[2] / l];
    const Rk = rodrigues(k, 360 * r() - 180);
    closeM(euler_zyx_matrix(euler_zyx_from_matrix(Rk)), Rk, 1e-12, `axis-angle ${k}`);
  }
  // gimbal lock: ry = ±90° with any rx, rz (rx and rz turn about the same axis: rx = 0 is chosen)
  for (const ry of [90, -90]) {
    for (const [rx, rz] of [[0, 0], [30, 0], [0, 45], [25, -70], [170, 160], [-120, 33]]) {
      const R = euler_zyx_matrix([rx!, ry, rz!]);
      const back = euler_zyx_from_matrix(R);
      assert.equal(back[0], 0, "gimbal lock: rx = 0");
      close(back[1], ry, 1e-12, "ry");
      closeM(euler_zyx_matrix(back), R, 1e-12, `gimbal ${[rx, ry, rz]}`);
    }
  }
  // exact matrices: the identity and the axis quarter turns
  assert.deepEqual(euler_zyx_from_matrix(euler_zyx_matrix([0, 0, 0])), [0, 0, 0]);
  closeM(euler_zyx_matrix(euler_zyx_from_matrix(axis_rotation(0, 90))), axis_rotation(0, 90), 1e-15, "x 90");
});

test("wrap_angle: (−180, 180], no −0; format_angle 0.1° and parse_angle of the fields", () => {
  assert.equal(wrap_angle(180), 180);
  assert.equal(wrap_angle(-180), 180);
  assert.equal(wrap_angle(200), -160);
  assert.equal(wrap_angle(540), 180);
  assert.equal(Object.is(wrap_angle(-0), -0), false);
  assert.equal(wrap_angle(-360), 0);
  assert.equal(format_angle(30), "30.0");
  assert.equal(format_angle(-0.04), "0.0");
  assert.equal(format_angle(200), "-160.0");
  assert.equal(format_angle(-179.97), "180.0");
  assert.equal(format_angle(12.345), "12.3");
  assert.equal(parse_angle(" 45 "), 45);
  assert.equal(parse_angle("−12.5"), -12.5);
  assert.equal(parse_angle("30°"), 30);
  for (const bad of ["", "  ", "abc", "NaN", "Infinity", "-Infinity", "1e999", "1,5"]) assert.equal(parse_angle(bad), null, bad);
});

// ------------------------------------------------------------------------------------------------ pivot

test("pivot fixed: ten 37° rotations about each world axis (box, cylinder, cone, prism), c_w within 1e-9 m against stage A", () => {
  const scene0 = scene_with([
    { id: "crate", type: "box", size: [1.0, 0.8, 0.6], transform: { position: [2.0, 4.0, 0.0], rotation_deg: [0, 0, 30] } },
    { id: "pillar", type: "cylinder", radius: 0.3, height: 2.4, transform: { position: [-1.5, 6.0, 0.0] } },
    { ...CONE, transform: { position: [0.5, 5.0, 0.0], rotation_deg: [10, -20, 40] } },
    { ...PRISM, transform: { position: [-0.4, 3.5, 0.0], rotation_deg: [0, 0, 50] } },
  ]);
  const A0 = shadow_geometry(scene0);
  for (const obj of scene0.objects) {
    const c_local = local_centre(obj.transform, vertices_of(A0, obj.id));
    const c0 = world_centre(obj.transform, c_local);
    for (const axis of [0, 1, 2] as Axis[]) {
      let t = clone_transform(obj.transform);
      for (let k = 0; k < 10; k++) {
        t = rotate_about_world_axis(t, c_local, axis, 37);
        close3(world_centre(t, c_local), c0, 1e-9, `${obj.id} axis ${axis} step ${k}`);
      }
      // stage A of the rotated scene: its local bounding box centre is the same pivot
      const A = shadow_geometry(with_pose(scene0, obj.id, t));
      const c_again = local_centre(t, vertices_of(A, obj.id));
      close3(c_again, c_local, 1e-9, `${obj.id} axis ${axis}: c_local from the rotated stage A`);
      close3(world_centre(t, c_again), c0, 1e-9, `${obj.id} axis ${axis}: c_w from the rotated stage A`);
    }
  }
});

test("pivot independent of the load pose: the same prism loaded with rz = 0 and rz = 50° has the same c_local (< 1e-12)", () => {
  const pose = (rz: number) => ({ ...PRISM, transform: { position: [0.7, 4.2, 0.0], rotation_deg: [0, 0, rz] } });
  const s0 = scene_with([pose(0)]), s50 = scene_with([pose(50)]);
  const c0 = local_centre(s0.objects[0]!.transform, vertices_of(shadow_geometry(s0), "wedge"));
  const c50 = local_centre(s50.objects[0]!.transform, vertices_of(shadow_geometry(s50), "wedge"));
  close3(c50, c0, 1e-12, "c_local");
  // the polygon's own bounding box: x ∈ [−0.2, 1.2], y ∈ [0, 0.7], z ∈ [0, 0.9]
  close3(c0, [0.5, 0.35, 0.45], 1e-12, "c_local of the prism");
  // a tilted cone, too (asymmetric about its pivot)
  const cone = (r: Vec3) => scene_with([{ ...CONE, transform: { position: [1, 5, 0], rotation_deg: r } }]);
  const a = cone([0, 0, 0]), b = cone([25, -40, 70]);
  close3(local_centre(b.objects[0]!.transform, vertices_of(shadow_geometry(b), "spike")),
    local_centre(a.objects[0]!.transform, vertices_of(shadow_geometry(a), "spike")), 1e-12, "cone c_local");
  // and half its diagonal (the ring radius)
  const h0 = local_bbox(s0.objects[0]!.transform, vertices_of(shadow_geometry(s0), "wedge")).half_diagonal;
  close(h0, Math.hypot(1.4, 0.7, 0.9) / 2, 1e-12, "half diagonal");
});

// ------------------------------------------------------------------------------------------------ drag and numeric entry

test("drag: R′ = Q·R and p′ = c_w + Q·(p − c_w); numeric entry of the same angles gives the same R′ and p′", () => {
  const r = rng(77);
  const c_local: Vec3 = [0.1, -0.2, 0.45];
  for (let i = 0; i < 60; i++) {
    const t0: Transform = { position: [4 * r() - 2, 4 * r() + 2, r()], rotation_deg: [360 * r() - 180, 160 * r() - 80, 360 * r() - 180] };
    const axis = (i % 3) as Axis, theta = 360 * r() - 180;
    const [R, p] = transform_frame(t0);
    const Q = axis_rotation(axis, theta);
    const t1 = rotate_about_world_axis(t0, c_local, axis, theta);
    closeM(euler_zyx_matrix(t1.rotation_deg), matmul(Q, R), 1e-12, `R′ axis ${axis}`);
    const c = world_centre(t0, c_local);
    const q = [p[0] - c[0], p[1] - c[1], p[2] - c[2]];
    const p1 = [0, 1, 2].map((k) => c[k]! + Q[k]![0] * q[0]! + Q[k]![1] * q[1]! + Q[k]![2] * q[2]!);
    close3(t1.position, p1, 1e-12, "p′");
    // numeric entry: the drag's resulting Euler angles typed in
    const t2 = set_rotation(t0, c_local, t1.rotation_deg);
    assert.deepEqual(t2.rotation_deg, t1.rotation_deg);
    closeM(euler_zyx_matrix(t2.rotation_deg), euler_zyx_matrix(t1.rotation_deg), 0, "same R′");
    close3(t2.position, t1.position, 1e-12, "numeric p′ = drag p′");
    close3(world_centre(t2, c_local), c, 1e-12, "numeric entry keeps c_w");
  }
});

test("rotation about z by θ: (rz − rz₀ − θ) mod 360 ≈ 0 incl. 170° + 30° → −160°; rx and ry unchanged", () => {
  const c_local: Vec3 = [0, 0, 0.3];
  const cases: [Vec3, number][] = [[[0, 0, 170], 30], [[0, 0, 30], 30], [[12, -34, -170], -25], [[-150, 80, 179], 2], [[40, 10, 0], 359],
    [[5, 5, 5], -720.5]];
  for (const [rot, theta] of cases) {
    const t0: Transform = { position: [1, 2, 0], rotation_deg: rot };
    const t1 = rotate_about_world_axis(t0, c_local, 2, theta);
    close(angle_diff(t1.rotation_deg[2], rot[2] + theta), 0, 1e-9, `rz of ${rot} + ${theta}`);
    assert.equal(t1.rotation_deg[0], rot[0], "rx unchanged");
    assert.equal(t1.rotation_deg[1], rot[1], "ry unchanged");
    assert.ok(t1.rotation_deg[2] > -180 && t1.rotation_deg[2] <= 180, "rz in (−180, 180]");
    // the decomposition of Q·R agrees (ry within (−90, 90), rx within (−180, 180]): the same angles modulo 360
    const d = euler_zyx_from_matrix(matmul(axis_rotation(2, theta), euler_zyx_matrix(rot)));
    close(angle_diff(d[2], rot[2] + theta), 0, 1e-9, "decomposed rz");
    close(angle_diff(d[0], rot[0]), 0, 1e-9, "decomposed rx");
    close(d[1], rot[1], 1e-9, "decomposed ry");
  }
  const t = rotate_about_world_axis({ position: [0, 0, 0], rotation_deg: [0, 0, 170] }, c_local, 2, 30);
  assert.equal(t.rotation_deg[2], -160);
  assert.equal(format_angle(t.rotation_deg[2]), "-160.0");
});

test("snap: θ to multiples of 15° when on; unchanged when off (Alt or the checkbox)", () => {
  assert.equal(OBJECT_SNAP_DEG, 15);
  assert.equal(snap_angle(7.4, true), 0);
  assert.equal(snap_angle(7.6, true), 15);
  assert.equal(snap_angle(-22.6, true), -30);
  assert.equal(snap_angle(37.3, false), 37.3);
  assert.equal(Object.is(snap_angle(-3, true), -0), false);
});

// ------------------------------------------------------------------------------------------------ rings

test("rings: 72 points each, radius 1.2 × ½ diagonal (≥ 0.3 m), each in the plane perpendicular to its axis", () => {
  assert.equal(ring_radius(1), 1.2);
  assert.equal(ring_radius(0.1), OBJECT_RING_MIN_M);
  const c: Vec3 = [1, 2, 0.5];
  const rings = object_rings("crate", c, 0.9);
  assert.equal(rings.id, "crate");
  rings.rings.forEach((ring, axis) => {
    assert.equal(ring.length, OBJECT_RING_SEGMENTS);
    for (const q of ring) {
      close(Math.hypot(q[0] - c[0], q[1] - c[1], q[2] - c[2]), 0.9, 1e-12, "radius");
      assert.equal(q[axis], c[axis], "perpendicular to the axis");
    }
  });
  assert.deepEqual(ring_points(c, 0.9, 2)[0], [1.9, 2, 0.5]);
});

test("ring drag angle: κ·(Δ·t_s), positive along the screen tangent axis × w; edge-on ring → t_s = (1, 0)", () => {
  // observer looking along +y (right +x, up +z); the z ring grabbed at w = +x: tangent z × x = +y is along the view
  // (edge-on: fallback (1, 0)); the y ring grabbed at w = +x: tangent y × x = −z, on screen (0, +1) (downwards)
  const r_c: Vec3 = [1, 0, 0], u_c: Vec3 = [0, 0, 1];
  close(ring_drag_angle(1, [1, 0, 0], r_c, u_c, 0, 50), KAPPA_DEG_PER_PX * 50, 1e-12, "down along the tangent");
  close(ring_drag_angle(1, [1, 0, 0], r_c, u_c, 0, -50), -KAPPA_DEG_PER_PX * 50, 1e-12, "against the tangent");
  close(ring_drag_angle(1, [1, 0, 0], r_c, u_c, 80, 0), 0, 1e-12, "across the tangent");
  assert.ok(Math.hypot(0, 0) < EDGE_ON_EPS);
  close(ring_drag_angle(2, [1, 0, 0], r_c, u_c, 40, 30), KAPPA_DEG_PER_PX * 40, 1e-12, "edge-on: Δx");
  // the grabbed point follows the finger: rotating w by θ moves its image along the drag direction
  const w: Vec3 = [0.3, 0, 0.4];
  const theta = ring_drag_angle(1, w, r_c, u_c, 30, -10);
  const w1 = [0, 1, 2].map((k) => axis_rotation(1, theta)[k]!.reduce((s, x, j) => s + x * w[j]!, 0));
  const dx = w1[0]! - w[0], dy = -(w1[2]! - w[2]);
  assert.ok(dx * 30 + dy * -10 > 0, "the image moves with the pointer");
});

// ------------------------------------------------------------------------------------------------ ground

test("ground (落地): after a tilt, translating by −min along the normal puts the exact surface on the ground", () => {
  const scene0 = scene_with([
    { id: "pillar", type: "cylinder", radius: 0.3, height: 2.4, transform: { position: [-1.5, 6.0, 0.0] } },
    { id: "crate", type: "box", size: [1.0, 0.8, 0.6], transform: { position: [2.0, 4.0, 0.0], rotation_deg: [0, 0, 30] } },
  ]);
  const A0 = shadow_geometry(scene0);
  const n = scene0.receivers[0]!.normal, pi = [n[0], n[1], n[2], scene0.receivers[0]!.offset];
  for (const id of ["pillar", "crate"]) {
    const obj = scene0.objects.find((o) => o.id === id)!;
    const c = local_centre(obj.transform, vertices_of(A0, id));
    const tilted = rotate_about_world_axis(obj.transform, c, 0, 25);
    const sT = with_pose(scene0, id, tilted);
    const AT = shadow_geometry(sT);
    assert.ok(AT.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), `${id}: the tilt goes through the ground (expected)`);
    const rec = AT.objects.find((o) => o.id === id)!;
    const dmin = rec.analytic !== null ? curved.plane_min(rec.analytic, pi)
      : Math.min(...rec.mesh.vertices.map((v) => n[0] * v[0] + n[1] * v[1] + n[2] * v[2]));
    assert.ok(dmin < 0);
    const grounded = ground_transform(tilted, dmin, n);
    assert.deepEqual(grounded.rotation_deg, tilted.rotation_deg);
    const AG = shadow_geometry(with_pose(scene0, id, grounded));
    assert.ok(!AG.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), `${id}: on the ground after 落地`);
    const recG = AG.objects.find((o) => o.id === id)!;
    const dG = recG.analytic !== null ? curved.plane_min(recG.analytic, pi)
      : Math.min(...recG.mesh.vertices.map((v) => n[0] * v[0] + n[1] * v[1] + n[2] * v[2]));
    close(dG, 0, 1e-12, `${id}: minimum distance 0`);
  }
});

// ------------------------------------------------------------------------------------------------ ObjectDrag

interface Log {
  applied: Transform[];
  proxied: Transform[];
  restored: { t0: Transform; scene0: string; A0: string }[];
}

/** An ObjectDrag over string "scenes" whose effects are logged; `fail` makes `apply` report a stage-A exception. */
function drag_harness(fail = false): { d: ObjectDrag<string, string>; log: Log } {
  const log: Log = { applied: [], proxied: [], restored: [] };
  const fx: ObjectDragEffects<string, string> = {
    apply: (_id, t) => {
      log.applied.push(clone_transform(t));
      return !fail;
    },
    proxy: (_id, t) => {
      log.proxied.push(clone_transform(t));
    },
    restore: (_id, t0, scene0, A0) => {
      log.restored.push({ t0: clone_transform(t0), scene0, A0 });
    },
  };
  return { d: new ObjectDrag(fx), log };
}

const T0: Transform = { position: [2, 4, 0], rotation_deg: [0, 0, 30] };
const C_LOCAL: Vec3 = [0, 0, 0.3];

test("ObjectDrag: move only stores the candidate; one stage A per frame; end without a frame commits the last candidate", () => {
  const { d, log } = drag_harness();
  d.begin("crate", T0, "scene0", "A0", 1, { axis: 2, c_local: C_LOCAL });
  assert.equal(d.active, true);
  assert.equal(d.seq, 1);
  d.move(10);
  d.move(20);
  assert.equal(log.applied.length, 0, "move runs no stage A");
  // move then immediate end (no frame): the last candidate is committed and the step is due
  const res = d.end()!;
  assert.equal(log.applied.length, 1, "end runs stage A once");
  assert.equal(res.ok, true);
  assert.equal(res.changed, true);
  assert.ok(same_transform(res.t, rotate_about_world_axis(T0, C_LOCAL, 2, 20)), "the last candidate (20°), not an older one");
  assert.ok(same_transform(log.applied[0]!, res.t));
  assert.equal(d.active, false);
  // with frames: at most one stage A per frame, none when nothing new is pending
  const h = drag_harness();
  h.d.begin("crate", T0, "s", "a", 2, { axis: 0, c_local: C_LOCAL });
  h.d.move(5);
  h.d.move(9);
  assert.equal(h.d.frame(), true);
  assert.equal(h.log.applied.length, 1);
  assert.equal(h.d.frame(), false, "nothing pending");
  h.d.move(9);
  assert.equal(h.d.frame(), false, "the same candidate again: no stage A");
  h.d.move(12);
  assert.equal(h.d.frame(), true);
  const r2 = h.d.end()!;
  assert.equal(h.log.applied.length, 2, "end after the frame applied the candidate: no extra stage A");
  assert.ok(same_transform(r2.t, rotate_about_world_axis(T0, C_LOCAL, 0, 12)));
});

test("ObjectDrag: a candidate equal to the committed pose records nothing; a press without movement records nothing", () => {
  const { d, log } = drag_harness();
  d.begin("crate", T0, "s", "a", 1, { axis: 2, c_local: C_LOCAL });
  const r = d.end()!;
  assert.equal(r.changed, false);
  assert.equal(log.applied.length, 0);
  d.begin("crate", T0, "s", "a", 2, { axis: 2, c_local: C_LOCAL });
  d.move(15);
  d.frame();
  d.move(0); // back to the start
  const r2 = d.end()!;
  assert.equal(r2.ok, true);
  assert.equal(r2.changed, false, "back at t0: no step");
  assert.ok(same_transform(r2.t, T0));
});

test("ObjectDrag: cancel restores scene0 / A0 / t0 and a stale sequence number applies nothing", () => {
  const { d, log } = drag_harness();
  d.begin("crate", T0, "scene0", "A0", 7, { axis: 1, c_local: C_LOCAL });
  d.move(30);
  d.frame(7);
  assert.equal(log.applied.length, 1);
  d.move(45);
  d.cancel();
  assert.equal(d.active, false);
  assert.deepEqual(log.restored, [{ t0: T0, scene0: "scene0", A0: "A0" }]);
  assert.equal(d.frame(7), false, "the cancelled gesture's frame applies nothing");
  assert.equal(d.end(), null);
  // a later gesture: a frame scheduled with the old number is rejected, the current one applies
  d.begin("crate", T0, "scene1", "A1", 8, { axis: 1, c_local: C_LOCAL });
  d.move(10);
  assert.equal(d.frame(7), false, "stale sequence number rejected");
  assert.equal(log.applied.length, 1);
  assert.equal(d.frame(8), true);
  assert.equal(log.applied.length, 2);
  d.abandon();
  assert.equal(d.active, false);
  assert.equal(log.restored.length, 1, "abandon restores nothing");
});

test("ObjectDrag: slow scene — moves and frames only move the 3D proxy, end runs stage A once", () => {
  assert.equal(LIVE_STAGE_A_MS, 150);
  const { d, log } = drag_harness();
  d.begin("crate", T0, "s", "a", 1, { live: false, axis: 2, c_local: C_LOCAL });
  for (const th of [5, 10, 15, 20]) {
    d.move(th);
    assert.equal(d.frame(), false);
  }
  assert.equal(log.applied.length, 0, "no stage A during the drag");
  assert.equal(log.proxied.length, 4, "the 3D proxy follows");
  const r = d.end()!;
  assert.equal(log.applied.length, 1, "one stage A at release");
  assert.ok(r.ok && r.changed);
  assert.ok(same_transform(r.t, rotate_about_world_axis(T0, C_LOCAL, 2, 20)));
});

test("ObjectDrag: a stage-A exception at release keeps nothing (restored to t0, ok false, no step)", () => {
  const { d, log } = drag_harness(true);
  d.begin("crate", T0, "scene0", "A0", 3, { axis: 0, c_local: C_LOCAL });
  d.move(40);
  assert.equal(d.frame(), true, "the frame tried stage A");
  const r = d.end()!;
  assert.equal(r.ok, false);
  assert.equal(r.changed, false);
  assert.ok(same_transform(r.t, T0));
  assert.equal(log.applied.length, 2, "the frame's try and the release's retry");
  assert.deepEqual(log.restored, [{ t0: T0, scene0: "scene0", A0: "A0" }]);
});

test("rotate about x then y keeps the matrix consistent with the Euler angles written (full doubles)", () => {
  let t: Transform = clone_transform(T0);
  let R = transform_frame(t)[0];
  for (const [axis, th] of [[0, 20], [1, -35], [0, 95], [2, 170], [1, 90]] as [Axis, number][]) {
    t = rotate_about_world_axis(t, C_LOCAL, axis, th);
    R = matmul(axis_rotation(axis, th), R);
    closeM(euler_zyx_matrix(t.rotation_deg), R, 1e-12, `after axis ${axis} by ${th}`);
  }
});

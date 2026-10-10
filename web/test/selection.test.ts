/** Tests of selection, hit testing and the key helpers (`web/src/selection.ts`; contract §5.8.2, §5.8.10, §5.8.11,
 * §5.8.13, §5.8.17 rows "selection", "delete", "Esc", "preview is read-only", "overlays" (the pure part) and "two
 * fingers" (the pure part)). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { build_object, compose, dumps, load_scene, point_inside_solid, project_scene, render, shadow_geometry, transform_frame } from "castplane";
import type { SceneObject, Vec2, Vec3 } from "castplane";

import { CLICK_PX, HIT_PX_MOUSE, HIT_PX_TOUCH, initial_view, observer_basis, observer_project, observer_project_with } from "../src/observer.js";
import type { Handles, ObserverView } from "../src/observer.js";
import {
  NON_TEXT_INPUT_TYPES, PressTracker, after_history, cancel_press, clear_selection, empty_selection, end_press,
  escape_action, focus_kind, focus_object_id, frame_ray, hit_order, hit_radius, hit_vertical, is_typing_target,
  nearest_hit, observer_frame, observer_ray, outline_polylines, press_select, press_target, prune_selection, ray_object_t,
  select_added, shortcut_action, svg_point, wire_segments,
} from "../src/selection.js";
import type { KeyLike, ObjectHit, ShortcutContext, TargetLike } from "../src/selection.js";
import { apply_entry, delete_with_entry, undo_entry, with_position, move_entry } from "../src/scene_edit.js";
import type { Ray } from "../src/scene_edit.js";

// web/build/test/selection.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const read_json = (...p: string[]): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, ...p), "utf-8"));

const DEG = Math.PI / 180;
const sub = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! - q[0]!, p[1]! - q[1]!, p[2]! - q[2]!];
const add = (p: readonly number[], q: readonly number[]): Vec3 => [p[0]! + q[0]!, p[1]! + q[1]!, p[2]! + q[2]!];
const mul = (p: readonly number[], s: number): Vec3 => [p[0]! * s, p[1]! * s, p[2]! * s];
const dot = (p: readonly number[], q: readonly number[]): number => p[0]! * q[0]! + p[1]! * q[1]! + p[2]! * q[2]!;
const cross = (p: readonly number[], q: readonly number[]): Vec3 =>
  [p[1]! * q[2]! - p[2]! * q[1]!, p[2]! * q[0]! - p[0]! * q[2]!, p[0]! * q[1]! - p[1]! * q[0]!];
const unit = (p: readonly number[]): Vec3 => mul(p, 1 / Math.sqrt(dot(p, p)));

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

const obj = (id: string, type: string, extra: Record<string, unknown>, position: Vec3 = [0, 0, 0], rotation_deg: Vec3 = [0, 0, 0]): SceneObject =>
  ({ id, type, ...extra, transform: { position, rotation_deg } }) as SceneObject;

/** Möller–Trumbore over the triangulated faces of a world mesh: every crossing `t > 0`. */
function mesh_ts(ray: Ray, m: { vertices: readonly (readonly number[])[]; faces: readonly (readonly number[])[] }): number[] {
  const out: number[] = [];
  for (const f of m.faces) {
    for (let k = 1; k + 1 < f.length; k++) {
      const a = m.vertices[f[0]!]!, b = m.vertices[f[k]!]!, c = m.vertices[f[k + 1]!]!;
      const e1 = sub(b, a), e2 = sub(c, a), p = cross(ray.d, e2), det = dot(e1, p);
      if (Math.abs(det) < 1e-15) continue;
      const s = sub(ray.e, a), u = dot(s, p) / det;
      if (u < -1e-12 || u > 1 + 1e-12) continue;
      const q = cross(s, e1), v = dot(ray.d, q) / det;
      if (v < -1e-12 || u + v > 1 + 1e-12) continue;
      const t = dot(e2, q) / det;
      if (t > 0) out.push(t);
    }
  }
  return out.sort((x, y) => x - y);
}

/** An independent inside test of a primitive in its local frame (closed solids, anchor conventions of §5.8.1). */
function inside_local(o: SceneObject, x: readonly number[], eps = 0): boolean {
  const [R, pos] = transform_frame(o.transform);
  const d = sub(x, pos);
  const l: Vec3 = [0, 1, 2].map((k) => R[0][k]! * d[0] + R[1][k]! * d[1] + R[2][k]! * d[2]) as Vec3;
  const r = o.radius as number, h = o.height as number;
  switch (o.type) {
    case "cylinder":
      return l[2] >= -eps && l[2] <= h + eps && Math.hypot(l[0], l[1]) <= r + eps;
    case "cone":
      return l[2] >= -eps && l[2] <= h + eps && Math.hypot(l[0], l[1]) <= (r * (h - l[2])) / h + eps;
    case "sphere":
      return Math.hypot(l[0], l[1], l[2] - r) <= r + eps;
    default:
      throw new Error(o.type);
  }
}

const W = 900, H = 600;

// ------------------------------------------------------------------------------------------------ selection state

test("selection transitions: press selects at once, a cancel restores, a click or drag keeps; add, delete, load", () => {
  let s = empty_selection();
  assert.equal(s.selected, null);
  s = press_select(s, "a");
  assert.equal(s.selected, "a");
  s = end_press(s);
  assert.deepEqual(s, { selected: "a", pending: null });
  s = press_select(s, "b");
  assert.equal(s.selected, "b");
  s = cancel_press(s);
  assert.deepEqual(s, { selected: "a", pending: null }, "a cancelled press restores the old selection");
  assert.deepEqual(cancel_press(s), s, "nothing pending: unchanged");
  assert.deepEqual(clear_selection(s), { selected: null, pending: null }, "blank click, Esc, delete, load");
  assert.deepEqual(select_added("box_1"), { selected: "box_1", pending: null });
  assert.deepEqual(prune_selection({ selected: "x", pending: null }, [{ id: "a" }]), { selected: null, pending: null });
  assert.deepEqual(prune_selection(s, [{ id: "a" }]), s);
});

test("after undo / redo the selection follows the object the entry acted on; board entries keep it", () => {
  const scene = load_scene(read_json("examples", "basic.json"));
  const [a, b] = scene.objects as [SceneObject, SceneObject];
  const sel = { selected: "pillar", pending: null };
  const del = delete_with_entry(scene.objects, 0)!;
  const und = undo_entry(del.objects, del.entry)!;
  assert.equal(after_history(clear_selection(), und.selected, und.objects).selected, a.id, "undo of a delete selects the restored object");
  const red = apply_entry(und.objects, del.entry)!;
  assert.equal(after_history(sel, red.selected, red.objects).selected, null, "redo of a delete clears");
  const mv = move_entry(1, b, with_position(b, [0, 9, 0]))!;
  const m = apply_entry(scene.objects, mv)!;
  assert.equal(after_history(clear_selection(), m.selected, m.objects).selected, b.id, "move selects the moved object");
  assert.equal(after_history(sel, undefined, scene.objects).selected, "pillar", "a board or reset entry keeps the selection");
  assert.equal(after_history({ selected: "gone", pending: null }, undefined, scene.objects).selected, null, "a missing id is cleared");
});

test("focus object of the vertex rays: the selection if it exists, else objects[0]", () => {
  const objs = [{ id: "a" }, { id: "b" }];
  assert.equal(focus_object_id("b", objs), "b");
  assert.equal(focus_object_id(null, objs), "a");
  assert.equal(focus_object_id("zz", objs), "a");
  assert.equal(focus_object_id(null, []), null);
});

// ------------------------------------------------------------------------------------------------ observer ray

test("observer_ray reprojects to the pointer within 1e-9 px", () => {
  const R = rng(1);
  for (let i = 0; i < 300; i++) {
    const view: ObserverView = { target: [(R() - 0.5) * 10, (R() - 0.5) * 10, R() * 2], dist: 4 + R() * 56,
      az_deg: R() * 360, el_deg: -5 + R() * 90 };
    const w = 200 + R() * 1200, h = 150 + R() * 900;
    const p: Vec2 = [R() * w, R() * h];
    const ray = observer_ray(view, w, h, p);
    assert.ok(Math.abs(Math.hypot(...ray.d) - 1) < 1e-14);
    assert.deepEqual(ray.e, observer_basis(view).pos);
    const q = observer_project(view, w, h, add(ray.e, mul(ray.d, 0.5 + R() * 80)))!;
    assert.ok(Math.abs(q[0] - p[0]) < 1e-9 && Math.abs(q[1] - p[1]) < 1e-9, `${q} vs ${p}`);
  }
});

// ------------------------------------------------------------------------------------------------ exact hits

test("box and prism hits equal Möller–Trumbore on the core's mesh (rotated, convex and concave)", () => {
  const R = rng(2);
  // a concave polygon's reference is the union of its convex pieces (the first entry is the least piece entry);
  // fan-triangulating a concave cap would be wrong
  const L: Vec2[] = [[0, 0], [2, 0], [2, 0.3], [0.3, 0.3], [0.3, 1.6], [0, 1.6]];
  const L_pieces: Vec2[][] = [[[0, 0], [2, 0], [2, 0.3], [0, 0.3]], [[0, 0.3], [0.3, 0.3], [0.3, 1.6], [0, 1.6]]];
  const cw: Vec2[] = [[0, 0], [0, 1.2], [0.25, 1.2], [0.25, 0.25], [1.5, 0.25], [1.5, 0]]; // clockwise
  const cw_pieces: Vec2[][] = [[[0, 0], [1.5, 0], [1.5, 0.25], [0, 0.25]], [[0, 0.25], [0.25, 0.25], [0.25, 1.2], [0, 1.2]]];
  const hex: Vec2[] = [[0.4, 0], [0.2, 0.3464], [-0.2, 0.3464], [-0.4, 0], [-0.2, -0.3464], [0.2, -0.3464]];
  const shapes: { make: (p: Vec3, r: Vec3) => SceneObject; pieces: Vec2[][] | null; h: number }[] = [
    { make: (p, r) => obj("b", "box", { size: [1.2, 0.7, 0.9] }, p, r), pieces: null, h: 0 },
    { make: (p, r) => obj("l", "prism", { polygon: L, height: 1.1 }, p, r), pieces: L_pieces, h: 1.1 },
    { make: (p, r) => obj("c", "prism", { polygon: cw, height: 0.8 }, p, r), pieces: cw_pieces, h: 0.8 },
    { make: (p, r) => obj("h", "prism", { polygon: hex, height: 1 }, p, r), pieces: null, h: 0 },
  ];
  let hits = 0, misses = 0, concave = 0;
  for (let i = 0; i < 1600; i++) {
    const sh = shapes[i % shapes.length]!;
    const pos: Vec3 = [(R() - 0.5) * 4, (R() - 0.5) * 4, (R() - 0.5)];
    const rot: Vec3 = i % 3 === 0 ? [0, 0, 0] : [(R() - 0.5) * 90, (R() - 0.5) * 90, R() * 360];
    const o = sh.make(pos, rot);
    const rec = build_object(o);
    const c = [0, 1, 2].map((k) => (rec.bbox[0][k]! + rec.bbox[1][k]!) / 2) as Vec3;
    const e: Vec3 = add(c, mul(unit([R() - 0.5, R() - 0.5, R() - 0.5]), 6 + R() * 10));
    const aim = add(c, [(R() - 0.5) * 2.5, (R() - 0.5) * 2.5, (R() - 0.5) * 1.5]);
    const ray: Ray = { e, d: unit(sub(aim, e)) };
    let ref: number[];
    if (sh.pieces === null) ref = mesh_ts(ray, rec.mesh);
    else {
      ref = sh.pieces.map((pc) => mesh_ts(ray, build_object(obj("p", "prism", { polygon: pc, height: sh.h }, pos, rot)).mesh)[0])
        .filter((t): t is number => t !== undefined).sort((x, y) => x - y);
    }
    const t = ray_object_t(ray, o, { near: 0 });
    if (ref.length === 0) {
      assert.equal(t, null, `case ${i}: hit without a crossing`);
      misses++;
    } else {
      assert.ok(t !== null, `case ${i}: missed (reference crossing at ${ref[0]})`);
      assert.ok(Math.abs(t - ref[0]!) < 1e-9, `case ${i}: ${t} vs ${ref[0]}`);
      hits++;
      if (sh.pieces !== null) concave++;
      // just before the hit the point is outside the solid (the core's own inside test)
      assert.ok(!point_inside_solid(rec, add(e, mul(ray.d, t - 1e-6))));
    }
  }
  assert.ok(hits > 400 && misses > 100 && concave > 150, `hits ${hits}, misses ${misses}, concave ${concave}`);
});

test("concave prism: a ray through the notch misses the near arm and hits the far one", () => {
  const L = obj("wall", "prism", { polygon: [[0, 0], [3, 0], [3, 0.3], [0.3, 0.3], [0.3, 2], [0, 2]], height: 1 });
  // from +x,+y looking towards −x at y = 1, z = 0.5: passes through the notch (x from 3 to 0.3) and enters at x = 0.3
  const ray: Ray = { e: [5, 1, 0.5], d: [-1, 0, 0] };
  assert.ok(Math.abs(ray_object_t(ray, L, { near: 0 })! - 4.7) < 1e-12);
  // a convex hull test would hit at x = 3
  const ray2: Ray = { e: [5, 0.15, 0.5], d: [-1, 0, 0] };
  assert.ok(Math.abs(ray_object_t(ray2, L, { near: 0 })! - 2) < 1e-12);
  // from above into the notch: misses
  assert.equal(ray_object_t({ e: [1.5, 1.2, 5], d: [0, 0, -1] }, L, { near: 0 }), null);
  // from above onto the arm: the top face
  assert.ok(Math.abs(ray_object_t({ e: [0.15, 1.2, 5], d: [0, 0, -1] }, L, { near: 0 })! - 4) < 1e-12);
});

test("curved primitives are hit exactly (on the quadric, the first entry), rotated or not", () => {
  const R = rng(4);
  const kinds = [
    (p: Vec3, r: Vec3) => obj("cy", "cylinder", { radius: 0.3 + R(), height: 0.5 + 2 * R() }, p, r),
    (p: Vec3, r: Vec3) => obj("co", "cone", { radius: 0.3 + R(), height: 0.5 + 2 * R() }, p, r),
    (p: Vec3, r: Vec3) => obj("sp", "sphere", { radius: 0.2 + R() }, p, r),
  ];
  let hits = 0;
  for (let i = 0; i < 1500; i++) {
    const o = kinds[i % 3]!([(R() - 0.5) * 4, (R() - 0.5) * 4, R()], i % 2 === 0 ? [0, 0, 0] : [(R() - 0.5) * 120, (R() - 0.5) * 120, R() * 360]);
    const rec = build_object(o);
    const c = [0, 1, 2].map((k) => (rec.bbox[0][k]! + rec.bbox[1][k]!) / 2) as Vec3;
    const e = add(c, mul(unit([R() - 0.5, R() - 0.5, R() - 0.5]), 5 + R() * 10));
    const ray: Ray = { e, d: unit(sub(add(c, [(R() - 0.5) * 2, (R() - 0.5) * 2, (R() - 0.5) * 2]), e)) };
    const t = ray_object_t(ray, o, { near: 0 });
    // march along the ray: the first inside sample must agree with t
    let first: number | null = null;
    for (let s = 0; s < 30; s += 0.002) if (inside_local(o, add(e, mul(ray.d, s)))) { first = s; break; }
    if (t === null) {
      assert.equal(first, null, `case ${i}: missed an inside sample at ${first}`);
      continue;
    }
    hits++;
    const X = add(e, mul(ray.d, t));
    assert.ok(inside_local(o, X, 1e-9), `case ${i}: the hit is on the surface`);
    assert.ok(!inside_local(o, add(e, mul(ray.d, t - 1e-6))), `case ${i}: outside just before`);
    if (first !== null) assert.ok(first >= t - 1e-9 && first - t <= 0.0021, `case ${i}: first sample ${first} vs ${t}`);
  }
  assert.ok(hits > 500, `only ${hits} hits`);
});

test("mesh objects: hit on the world mesh (either side), equal to Möller–Trumbore", () => {
  const tet = obj("m", "mesh", { data: { vertices: [[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]], faces: [[0, 2, 1], [0, 1, 3], [0, 3, 2], [1, 2, 3]] } },
    [2, 1, 0], [10, 20, 30]);
  const scene = load_scene({ ...read_json("examples", "basic.json"), objects: [tet] });
  const o = scene.objects[0]!;
  const rec = build_object(o);
  const R = rng(6);
  let hits = 0;
  for (let i = 0; i < 300; i++) {
    const e: Vec3 = [2 + (R() - 0.5) * 8, 1 + (R() - 0.5) * 8, 0.5 + (R() - 0.5) * 8];
    const ray: Ray = { e, d: unit(sub([2.3 + (R() - 0.5), 1.3 + (R() - 0.5), 0.3 + (R() - 0.5) * 0.6], e)) };
    const ref = mesh_ts(ray, rec.mesh);
    const t = ray_object_t(ray, o, { near: 0 }, rec.mesh);
    const t2 = ray_object_t(ray, o, { near: 0 });
    assert.equal(t, t2, "the stage-A mesh and the port's build_object agree");
    if (ref.length === 0) assert.equal(t, null);
    else {
      assert.ok(t !== null && Math.abs(t - ref[0]!) < 1e-9);
      hits++;
    }
  }
  assert.ok(hits > 50);
  // from inside: the back face is hit (meshes are drawn double-sided)
  const inside: Ray = { e: [2.1, 1.1, 0.1], d: [0, 0, 1] };
  assert.ok(ray_object_t(inside, o, { near: 0 }, rec.mesh) !== null);
});

test("nearest hit wins whatever the array order; hits at depth ≤ OBSERVER_NEAR_M are ignored", () => {
  const near_box = obj("near", "box", { size: [1, 1, 1] }, [0, 3, 0]);
  const far_box = obj("far", "box", { size: [3, 3, 3] }, [0, 8, 0]);
  const ray: Ray = { e: [0, 0, 0.5], d: [0, 1, 0] };
  for (const objs of [[near_box, far_box], [far_box, near_box]]) {
    const h = nearest_hit(ray, objs)!;
    assert.equal(h.id, "near");
    assert.ok(Math.abs(h.t - 2.5) < 1e-12);
    assert.deepEqual(h.point, [0, 2.5, 0.5]);
    assert.equal(h.index, objs.indexOf(near_box));
  }
  assert.equal(nearest_hit({ e: [0, 0, 0.5], d: [0, -1, 0] }, [near_box, far_box]), null, "blank");
  // the near box's face at depth 0.04 (≤ 0.05) is cut away by the near plane: the far box is hit
  const close: Ray = { e: [0, 2.46, 0.5], d: [0, 1, 0] };
  assert.equal(nearest_hit(close, [near_box, far_box], { f: [0, 1, 0], near: 0.05 })!.id, "far");
  assert.equal(nearest_hit(close, [near_box, far_box], { f: [0, 1, 0], near: 0.03 })!.id, "near");
  // depth is measured along the camera axis: an oblique ray with t = 0.07 but depth 0.035 is ignored
  const ob: Ray = { e: [0, 2.465, 0.5], d: unit([Math.sqrt(3), 1, 0]) };
  const t = ray_object_t(ob, near_box, { near: 0 })!;
  assert.ok(Math.abs(t - 0.07) < 1e-12);
  assert.equal(ray_object_t(ob, near_box, { f: [0, 1, 0], near: 0.05 }), null);
  // the camera inside a primitive sees no front face of it
  assert.equal(ray_object_t({ e: [0, 3, 0.5], d: [0, 1, 0] }, near_box, { near: 0 }), null);
});

// ------------------------------------------------------------------------------------------------ hit priority

test("hit order: tip > ring > handle > object > blank", () => {
  const hit: ObjectHit = { id: "a", index: 0, t: 1, point: [0, 0, 0] };
  assert.deepEqual(hit_order({ handle: { kind: "arrow" }, vertical: "a", object: hit }), { kind: "arrow" });
  assert.deepEqual(hit_order({ handle: { kind: "ring", index: 3 }, vertical: "a", object: hit }), { kind: "ring", index: 3 });
  assert.deepEqual(hit_order({ handle: null, vertical: "a", object: hit }), { kind: "handle", id: "a" });
  assert.deepEqual(hit_order({ handle: null, vertical: null, object: hit }), { kind: "object", hit });
  assert.deepEqual(hit_order({ handle: null, vertical: null, object: null }), { kind: "blank" });
  assert.equal(hit_radius("mouse"), HIT_PX_MOUSE);
  assert.equal(hit_radius("touch"), HIT_PX_TOUCH);
  assert.equal(hit_radius("pen"), HIT_PX_TOUCH);
});

test("press_target with real geometry: the ring wins over an object, the handle needs a selection, blank", () => {
  const view: ObserverView = { ...initial_view(), target: [0, 0, 0.5], dist: 10 };
  const basis = observer_basis(view);
  const box = obj("box_1", "box", { size: [2, 2, 1] });
  const centre = observer_project(view, W, H, [0, 0, 0.5])!;
  // a fake ring through the box's centre, a tip far away
  const ring: Vec3[] = [];
  for (let i = 0; i < 72; i++) ring.push(add([0, 0, 0.5], mul([Math.cos((i * 5) * DEG), Math.sin((i * 5) * DEG), 0], 0.001)));
  const handles: Handles = { ring, Q: [0, 0, 0.5], tip: [30, 30, 30] };
  const base = { view, W, H, touch: false, selected: null, vertical_tip: null, objects: [box] };
  assert.equal(press_target({ ...base, p: centre, handles }).kind, "ring", "the ring drawn over an object wins");
  const t = press_target({ ...base, p: centre, handles: null });
  assert.equal(t.kind, "object");
  assert.equal(t.kind === "object" ? t.hit.id : "", "box_1");
  // the tip of the board arrow
  const tipp = observer_project(view, W, H, [1.5, -1.5, 3])!;
  assert.equal(press_target({ ...base, p: tipp, handles: { ...handles, tip: [1.5, -1.5, 3] } }).kind, "arrow");
  // the vertical handle: only for the selected object, a disc of the hit radius around its tip
  const vtip: Vec3 = [0, 0, 1.6];
  const vp = observer_project(view, W, H, vtip)!;
  const off: Vec2 = [vp[0] + 10, vp[1]];
  assert.deepEqual(press_target({ ...base, p: off, handles: null, selected: "box_1", vertical_tip: vtip }), { kind: "handle", id: "box_1" });
  assert.equal(press_target({ ...base, p: off, handles: null, selected: null, vertical_tip: vtip }).kind, "blank");
  assert.equal(press_target({ ...base, p: [vp[0] + 20, vp[1]], handles: null, selected: "box_1", vertical_tip: vtip }).kind, "blank");
  assert.equal(press_target({ ...base, p: [vp[0] + 20, vp[1]], touch: true, handles: null, selected: "box_1", vertical_tip: vtip }).kind, "handle");
  assert.ok(hit_vertical(basis, W, H, vp, false, vtip));
  // blank
  assert.equal(press_target({ ...base, p: [5, 5], handles }).kind, "blank");
  // the frame-based ray agrees with the view-based one
  const r1 = observer_ray(view, W, H, [123, 456]), r2 = frame_ray(observer_frame(view, H), W, H, [123, 456]);
  assert.deepEqual(r1, r2);
  assert.ok(observer_project_with(basis, W, H, add(r1.e, r1.d)) !== null);
});

// ------------------------------------------------------------------------------------------------ click vs drag, two fingers

test("PressTracker: the maximum excursion decides (4.9 px click, 5 px drag); no movement before 5 px", () => {
  assert.equal(CLICK_PX, 5);
  const a = new PressTracker("object", 100, 100);
  assert.equal(a.move(104.9, 100).dragging, false);
  assert.equal(a.release(), "click");
  const b = new PressTracker("object", 100, 100);
  assert.equal(b.move(103, 104).dragging, true, "5 px exactly is a drag");
  assert.equal(b.release(), "drag");
  const c = new PressTracker("object", 0, 0);
  c.move(6, 0);
  const back = c.move(0.5, 0);
  assert.equal(back.dragging, true, "the maximum, not the net distance");
  assert.deepEqual([back.dx, back.dy], [0.5, 0], "the displacement is the total since pointer-down");
  assert.equal(c.release(), "drag");
  const d = new PressTracker("object", 0, 0);
  d.move(3, 3);
  assert.equal(d.moved, Math.hypot(3, 3));
  assert.equal(d.dragging, false);
});

test("two fingers: an object press moved < 5 px is cancelled (selection restored, no entry), ≥ 5 px ignores it", () => {
  let sel = { selected: "a", pending: null } as ReturnType<typeof empty_selection>;
  const p = new PressTracker("object", 10, 10);
  sel = press_select(sel, "b");
  p.move(12, 13);
  assert.equal(p.second_pointer(), "cancel");
  sel = cancel_press(sel);
  assert.equal(sel.selected, "a");
  const q = new PressTracker("object", 10, 10);
  q.move(20, 10);
  assert.equal(q.second_pointer(), "ignore");
  for (const k of ["arrow", "ring", "handle"] as const) {
    const h = new PressTracker(k, 0, 0);
    assert.equal(h.second_pointer(), "cancel");
    h.move(40, 0);
    assert.equal(h.second_pointer(), "cancel", `${k}: cancelled as in M10`);
  }
  assert.equal(new PressTracker("blank", 0, 0).second_pointer(), "pinch");
});

// ------------------------------------------------------------------------------------------------ keys

test("is_typing_target: text-like targets take the keys; range, checkbox, button, select and file do not", () => {
  const rows: [TargetLike | null, boolean][] = [
    [{ tag: "TEXTAREA" }, true],
    [{ tag: "div", editable: true }, true],
    [{ tag: "INPUT", type: "text" }, true],
    [{ tag: "input", type: "search" }, true],
    [{ tag: "input", type: "number" }, true],
    [{ tag: "input", type: "email" }, true],
    [{ tag: "input", type: "url" }, true],
    [{ tag: "input", type: "tel" }, true],
    [{ tag: "input", type: "password" }, true],
    [{ tag: "input" }, true],
    [{ tag: "input", type: null }, true],
    [{ tag: "input", type: "something-new" }, true],
    [{ tag: "input", type: "range" }, false],
    [{ tag: "input", type: "checkbox" }, false],
    [{ tag: "input", type: "button" }, false],
    [{ tag: "input", type: "file" }, false],
    [{ tag: "input", type: "RADIO" }, false],
    [{ tag: "select" }, false],
    [{ tag: "button" }, false],
    [{ tag: "body" }, false],
    [null, false],
  ];
  for (const [t, want] of rows) assert.equal(is_typing_target(t), want, JSON.stringify(t));
  assert.ok(NON_TEXT_INPUT_TYPES.includes("range"));
  assert.equal(focus_kind({ tag: "input", type: "text" }, true), "equation");
  assert.equal(focus_kind({ tag: "input", type: "text" }, false), "text");
  assert.equal(focus_kind({ tag: "input", type: "range" }, false), "other");
});

const K = (key: string, mods: Partial<KeyLike> = {}): KeyLike => ({ key, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...mods });

test("shortcut_action table: Delete, Backspace, Ctrl / ⌘ + Z, Ctrl / ⌘ + Shift + Z, Ctrl / ⌘ + Shift + L", () => {
  const edit: ShortcutContext = { has_selection: true, previewing: false };
  const rows: [KeyLike, ShortcutContext, string | null][] = [
    [K("Delete"), edit, "delete"],
    [K("Backspace"), edit, "delete"],
    [K("Delete", { shiftKey: true }), edit, "delete"],
    [K("Delete"), { ...edit, has_selection: false }, null],
    [K("Delete", { ctrlKey: true }), edit, null],
    [K("Delete", { metaKey: true }), edit, null],
    [K("Backspace", { altKey: true }), edit, null],
    [K("Delete", { isComposing: true }), edit, null],
    [K("Delete"), { ...edit, focus: "text" }, null],
    [K("Delete"), { ...edit, focus: "equation" }, null],
    [K("Delete"), { ...edit, gesture_open: true }, null],
    [K("z", { ctrlKey: true }), edit, "undo"],
    [K("z", { metaKey: true }), edit, "undo"],
    [K("Z", { ctrlKey: true, shiftKey: true }), edit, "redo"],
    [K("Z", { metaKey: true, shiftKey: true }), edit, "redo"],
    [K("я", { ctrlKey: true, code: "KeyZ" }), edit, "undo"],
    [K("z", { ctrlKey: true, altKey: true }), edit, null],
    [K("z"), edit, null],
    [K("y", { ctrlKey: true }), edit, null],
    [K("z", { ctrlKey: true }), { ...edit, has_selection: false }, "undo"],
    [K("z", { ctrlKey: true }), { ...edit, focus: "text" }, null],
    [K("z", { ctrlKey: true }), { ...edit, gesture_open: true }, null],
    [K("z", { ctrlKey: true, isComposing: true }), edit, null],
    [K("L", { ctrlKey: true, shiftKey: true }), edit, "toggle_library"],
    [K("L", { metaKey: true, shiftKey: true }), edit, "toggle_library"],
    [K("l", { ctrlKey: true }), edit, null],
    [K("L", { ctrlKey: true, shiftKey: true, altKey: true }), edit, null],
    [K("L", { ctrlKey: true, shiftKey: true }), { ...edit, focus: "equation" }, null],
    [K("L", { ctrlKey: true, shiftKey: true }), { ...edit, has_selection: false }, "toggle_library"],
    [K("a"), edit, null],
  ];
  for (const [ev, ctx, want] of rows) assert.equal(shortcut_action(ev, ctx), want, `${JSON.stringify(ev)} ${JSON.stringify(ctx)}`);
});

test("preview is read-only: no shortcut acts or is intercepted while previewing except Esc (leave 預覽)", () => {
  const prev: ShortcutContext = { has_selection: true, previewing: true };
  for (const ev of [K("Delete"), K("Backspace"), K("z", { ctrlKey: true }), K("z", { metaKey: true }), K("Z", { ctrlKey: true, shiftKey: true }),
    K("Z", { metaKey: true, shiftKey: true }), K("L", { ctrlKey: true, shiftKey: true }), K("L", { metaKey: true, shiftKey: true })]) {
    assert.equal(shortcut_action(ev, prev), null, JSON.stringify(ev));
  }
  assert.equal(shortcut_action(K("Escape"), prev), "leave_preview");
  assert.equal(shortcut_action(K("Escape"), { ...prev, has_selection: false }), "leave_preview");
});

test("Esc table: equation field > drag (nothing) > previewing > selection > nothing; never the library", () => {
  assert.equal(escape_action({ focus: "equation", previewing: true, has_selection: true }), "field");
  assert.equal(escape_action({ focus: "equation", previewing: false, has_selection: false }), "field");
  assert.equal(escape_action({ previewing: true, has_selection: true }), "leave_preview");
  assert.equal(escape_action({ previewing: false, has_selection: true }), "clear_selection");
  assert.equal(escape_action({ previewing: false, has_selection: false }), null);
  assert.equal(escape_action({ previewing: false, has_selection: true, gesture_open: true }), null, "Esc during a drag does nothing");
  assert.equal(escape_action({ previewing: true, has_selection: true, gesture_open: true }), null);
  assert.equal(escape_action({ focus: "text", previewing: false, has_selection: true }), "clear_selection");
  // the window handler: the field's own Esc is not intercepted; nothing toggles the library
  for (const previewing of [true, false]) {
    for (const has_selection of [true, false]) {
      for (const focus of ["equation", "text", "other"] as const) {
        for (const gesture_open of [true, false]) {
          const a = shortcut_action(K("Escape"), { previewing, has_selection, focus, gesture_open });
          assert.notEqual(a, "toggle_library");
          if (focus === "equation" || gesture_open) assert.equal(a, null);
        }
      }
    }
  }
});

// the rows of the former web/test/keys.test.ts (M11 step 1), on the single key helpers of selection.ts

/** A keydown as the page describes it: the focus kind is derived from the target as `main.ts` does. */
const KT = (k: string, mods: Partial<KeyLike> = {}, target: TargetLike = { tag: "BODY" }): [KeyLike, ShortcutContext["focus"]] =>
  [{ key: k, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, isComposing: false, ...mods }, focus_kind(target, false)];

test("is_typing_target (step 1 table): text-like inputs keep their keys whatever the case of the type", () => {
  for (const type of ["text", "search", "number", "email", "url", "tel", "password", "", null, undefined, "weird", "TEXT", "date"]) {
    assert.equal(is_typing_target({ tag: "INPUT", type }), true, `input type ${String(type)}`);
  }
  for (const type of ["range", "checkbox", "radio", "button", "submit", "reset", "file", "color", "image", "hidden", "Range"]) {
    assert.equal(is_typing_target({ tag: "INPUT", type }), false, `input type ${type}`);
  }
  assert.equal(is_typing_target({ tag: "DIV", editable: false }), false);
  for (const tag of ["SELECT", "BUTTON", "BODY", "CANVAS", "SECTION"]) assert.equal(is_typing_target({ tag }), false, tag);
});

test("shortcut_action (step 1 table): Ctrl / ⌘+Z undo, Ctrl / ⌘+Shift+Z redo; modifiers, IME, focus, preview", () => {
  const EDIT = { has_selection: true, previewing: false };
  const act = (k: string, mods: Partial<KeyLike> = {}, target?: TargetLike, ctx: Omit<ShortcutContext, "focus"> = EDIT) => {
    const [ev, focus] = KT(k, mods, target);
    return shortcut_action(ev, { ...ctx, focus });
  };
  assert.equal(act("z", { ctrlKey: true }), "undo");
  assert.equal(act("z", { metaKey: true }), "undo", "⌘Z");
  assert.equal(act("Z", { ctrlKey: true, shiftKey: true }), "redo");
  assert.equal(act("Z", { metaKey: true, shiftKey: true }), "redo", "⌘⇧Z");
  assert.equal(act("z", { ctrlKey: true, shiftKey: true }), "redo", "lower-case key with Shift");
  assert.equal(act("Z", { ctrlKey: true }, undefined, { has_selection: false, previewing: false }), "undo", "Caps Lock; no selection needed");
  // not bound
  assert.equal(act("z"), null, "plain z");
  assert.equal(act("y", { ctrlKey: true }), null, "Ctrl+Y is not bound");
  assert.equal(act("z", { ctrlKey: true, altKey: true }), null, "Ctrl+Alt+Z");
  assert.equal(act("z", { metaKey: true, altKey: true }), null, "⌘⌥Z");
  assert.equal(act("z", { ctrlKey: true, metaKey: true }), null, "Ctrl+⌘+Z");
  assert.equal(act("L", { ctrlKey: true, metaKey: true, shiftKey: true }), null, "Ctrl+⌘+Shift+L");
  assert.equal(act("z", { altKey: true }), null, "Alt+Z");
  assert.equal(act("z", { shiftKey: true }), null, "Shift+Z");
  // IME composition and text-like targets: left to the browser
  assert.equal(act("z", { ctrlKey: true, isComposing: true }), null, "IME");
  assert.equal(act("z", { ctrlKey: true }, { tag: "INPUT", type: "text" }), null, "a text field");
  assert.equal(act("Z", { metaKey: true, shiftKey: true }, { tag: "TEXTAREA" }), null);
  assert.equal(act("z", { ctrlKey: true }, { tag: "SPAN", editable: true }), null);
  // non-text targets take it: a focused button, slider, checkbox, select
  for (const target of [{ tag: "BUTTON" }, { tag: "INPUT", type: "range" }, { tag: "INPUT", type: "checkbox" }, { tag: "SELECT" }]) {
    assert.equal(act("z", { ctrlKey: true }, target), "undo", JSON.stringify(target));
  }
  // previewing: no shortcut acts (board entries included, §5.8.14)
  for (const [k, mods] of [["z", { ctrlKey: true }], ["z", { metaKey: true }], ["Z", { ctrlKey: true, shiftKey: true }], ["Z", { metaKey: true, shiftKey: true }]] as const) {
    assert.equal(act(k, mods, undefined, { has_selection: true, previewing: true }), null);
    assert.equal(act(k, mods, undefined, { has_selection: false, previewing: true }), null);
  }
});

test("escape_action (step 1 table): the equation field's own Esc > nothing during a drag > leave 預覽 > clear > nothing (Q3)", () => {
  const all = [true, false];
  for (const gesture_open of all) for (const previewing of all) for (const has_selection of all) {
    assert.equal(escape_action({ focus: "equation", gesture_open, previewing, has_selection }), "field");
    const want = gesture_open ? null : previewing ? "leave_preview" : has_selection ? "clear_selection" : null;
    assert.equal(escape_action({ focus: "other", gesture_open, previewing, has_selection }), want,
      JSON.stringify({ gesture_open, previewing, has_selection }));
  }
});

// ------------------------------------------------------------------------------------------------ outputs

test("outputs are byte-identical with and without a selection (the selection is not in the scene JSON)", () => {
  const scene = load_scene(read_json("examples", "basic.json"));
  const before = JSON.stringify(scene);
  const r0 = render(scene);
  let sel = press_select(empty_selection(), scene.objects[0]!.id);
  sel = end_press(sel);
  const target = press_target({ view: initial_view(), W, H, p: [W / 2, H / 2], touch: false, handles: null, selected: sel.selected,
    vertical_tip: null, objects: scene.objects });
  assert.ok(target.kind === "object" || target.kind === "blank");
  assert.equal(JSON.stringify(scene), before, "selection and hit tests do not touch the scene");
  const r1 = render(scene);
  assert.equal(dumps(r1.geometry), dumps(r0.geometry));
  assert.equal(r1.svg, r0.svg);
  assert.equal(focus_object_id(sel.selected, scene.objects), "crate");
});

// ------------------------------------------------------------------------------------------------ overlays (wiring, §5.8.2, §5.8.12)

test("outline_polylines: the selected object's edges, generators and conics only (canvas mm), nothing for an unknown id", () => {
  const scene = load_scene(read_json("examples", "basic.json"));
  const A = shadow_geometry(scene);
  const doc = compose(scene, project_scene(scene, A));
  const crate = outline_polylines(doc, "crate");
  const segs = doc.edges.filter((e) => e.object === "crate" && e.segment !== null);
  assert.ok(segs.length > 0);
  assert.equal(crate.length, segs.length, "a box: one polyline per drawn edge");
  segs.forEach((e, i) => assert.deepEqual(crate[i], e.segment!.map((q) => [q[0], q[1]])));
  const pillar = outline_polylines(doc, "pillar");
  const o = doc.outlines.find((x) => x.object === "pillar")!;
  assert.ok(pillar.length >= o.generators.filter((g) => g.segment !== null).length + o.conics.length, "a cylinder: generators and conics");
  for (const pl of pillar) for (const q of pl) assert.ok(Number.isFinite(q[0]) && Number.isFinite(q[1]));
  assert.deepEqual(outline_polylines(doc, "nope"), []);
});

test("wire_segments: stage-A edges through the camera record (equal to the document's edges), shifted, near-clipped", () => {
  const scene = load_scene(read_json("examples", "basic.json"));
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const doc = compose(scene, B);
  const i = scene.objects.findIndex((o) => o.id === "crate");
  const m = A.objects[i]!.mesh;
  const segs = wire_segments([m], [], B.camera);
  assert.equal(segs.length, m.edges.length, "every edge of the box is in front of the camera");
  // every drawn document edge of the box is one of them (same projection, to rounding)
  for (const e of doc.edges.filter((x) => x.object === "crate" && x.segment !== null)) {
    const [a, b] = e.segment!;
    const best = Math.min(...segs.map(([p, q]) => Math.min(
      Math.hypot(p[0] - a![0]!, p[1] - a![1]!) + Math.hypot(q[0] - b![0]!, q[1] - b![1]!),
      Math.hypot(p[0] - b![0]!, p[1] - b![1]!) + Math.hypot(q[0] - a![0]!, q[1] - a![1]!))));
    assert.ok(best < 1e-6, `edge ${e.from}-${e.to}: ${best}`);
  }
  // a shift is the projection of the translated vertices (the dragged object of the preview)
  const d: Vec3 = [0.7, -0.3, 0.2];
  const moved = { ...m, vertices: m.vertices.map((v) => add(v, d)) };
  assert.deepEqual(wire_segments([m], [d], B.camera), wire_segments([moved], [], B.camera));
  // smooth edges of an imported mesh are left out; an edge with an end behind the near plane too
  assert.equal(wire_segments([{ ...m, edge_smooth: m.edges.map(() => true) }], [], B.camera).length, 0);
  const behind = { vertices: [sub(scene.camera.position, [0, 1, 0]), sub(scene.camera.position, [0, 2, 0])], edges: [[0, 1]] as [number, number][] };
  assert.equal(wire_segments([behind], [], B.camera).length, 0);
});

test("svg_point: canvas mm (u, v) to the writer's user units x = u + W/2, y = H/2 − v", () => {
  assert.deepEqual(svg_point([0, 0], [300, 200]), [150, 100]);
  assert.deepEqual(svg_point([10, 20], [300, 200]), [160, 80]);
  assert.deepEqual(svg_point([-150, -100], [300, 200]), [0, 200]);
});

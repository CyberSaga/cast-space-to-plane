/** Tests of D84 groups of parts (`web/src/groups.ts`, the group maths of `web/src/object_rotate.ts`, the group frames
 * and group undo steps of `web/src/plane.ts` / `web/src/rig.ts`, the `group` key of `web/src/download.ts::scene_blob`):
 * parsing (malformed values, a singleton group), the click cycle, the dropdown encoding, a group's rigid rotation
 * about its fixed `c` (checked against stage A), numeric entry ≡ the equivalent drags, the display Euler round trip,
 * 還原 and 落地 of a group, the group pivot, and undo of group steps interleaved with board and part steps. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { curved, euler_zyx_matrix, load_scene, load_scene_text, shadow_geometry, transform_frame } from "castplane";
import type { Mat3, Scene, StageA, Vec3 } from "castplane";

import { display_colours } from "../src/colours.js";
import { scene_blob } from "../src/download.js";
import {
  GROUP_VALUE_PREFIX, group_members, group_of, group_option_label, is_group_name, next_selection, object_groups,
  object_groups_text, same_selection, selection_of_value, selection_text, selection_value,
} from "../src/groups.js";
import type { Selection } from "../src/groups.js";
import { scene_centre } from "../src/observer.js";
import {
  UnitDrag, clone_pose, euler_zyx_from_matrix, identity3, local_bbox, matmul, ring_radius, rotate_about_world_axis,
  rotate_group_pose, same_pose, set_group_rotation, single_pose, translate_pose, world_bbox,
} from "../src/object_rotate.js";
import type { Axis, UnitPose } from "../src/object_rotate.js";
import { PlaneSession, object_centres } from "../src/plane.js";
import { clone } from "../src/rig.js";

// web/build/test/groups.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const FIXTURE = resolve(ROOT, "web", "test", "fixtures", "basic_grouped.json");
const fixture_text = (): string => readFileSync(FIXTURE, "utf-8");
const fixture = (): Record<string, unknown> => JSON.parse(fixture_text());

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}
function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}
function closeM(A: Mat3, B: Mat3, tol: number, what: string): void {
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) close(A[i][j], B[i][j], tol, `${what}[${i}][${j}]`);
}

interface Loaded {
  scene: Scene;
  A: StageA;
  groups: Map<string, string>;
  members: Map<string, string[]>;
  session: PlaneSession;
}

/** A raw scene loaded as `main.ts::load` does: the validated scene, stage A, the groups and a session with frames. */
function load(data: Record<string, unknown>): Loaded {
  const scene = load_scene(data);
  const A = shadow_geometry(scene);
  const groups = object_groups(data);
  const members = group_members(groups, scene.objects.map((o) => o.id));
  const recs = new Map(A.objects.map((o) => [o.id, o]));
  const session = new PlaneSession({ camera: scene.camera, canvas_mm: scene.output.canvas_mm, centre: scene_centre(A),
    object_centres: object_centres(A.objects), vertices: A.vertices,
    object_poses: scene.objects.map((o) => ({ id: o.id, transform: o.transform, vertices: recs.get(o.id)!.mesh.vertices })),
    groups: members });
  return { scene, A, groups, members, session };
}

/** The scene with the transforms of `pose` (the old scene is not mutated). */
const with_pose = (scene: Scene, pose: UnitPose): Scene => ({ ...scene, objects: scene.objects.map((o) => {
  const t = pose.transforms.get(o.id);
  return t === undefined ? o : { ...o, transform: t };
}) });

/** Group `name`'s pose in `l` at load. */
function group_pose(l: Loaded, name: string): UnitPose {
  const ids = l.members.get(name)!;
  return { transforms: new Map(ids.map((id) => [id, l.scene.objects.find((o) => o.id === id)!.transform])), group: l.session.group_frame(name) };
}

const vertices_of = (A: StageA, id: string): Vec3[] => A.objects.find((o) => o.id === id)!.mesh.vertices;

// ------------------------------------------------------------------------------------------------ parsing

test("object_groups: valid iff a non-empty, non-whitespace string, kept verbatim; malformed entries skipped silently", () => {
  const raw = { objects: [
    { id: "a", group: "miki" }, { id: "b", group: " miki " }, { id: "c", group: "" }, { id: "d", group: "   " },
    { id: "e", group: 3 }, { id: "f", group: null }, { id: "g", group: ["x"] }, { id: "h", group: { n: 1 } }, { id: "i" },
    { group: "orphan" }, { id: 7, group: "x" }, null, "text", [1, 2], { id: "j", group: "\t" }, { id: "k", group: "中文 群組" },
    { id: "m", group: "\ud800" }, { id: "n", group: "x\udc00" }, { id: "o", group: "\udc00\ud800" }, { id: "q", group: "😀" },
  ] };
  assert.deepEqual([...object_groups(raw)], [["a", "miki"], ["b", " miki "], ["k", "中文 群組"], ["q", "😀"]]);
  // D84 review: a lone surrogate (valid JSON via "\ud800") is not a group name: the downloaded scene could not encode it
  assert.equal(object_groups_text('{"objects": [{"id": "m", "group": "\\ud800x"}]}').size, 0);
  assert.ok(!is_group_name("\ud800") && !is_group_name("a\udfff") && is_group_name("\ud83d\ude00"));
  for (const bad of [null, 3, "x", [], {}, { objects: 3 }, { objects: null }]) assert.equal(object_groups(bad).size, 0);
  assert.equal(object_groups_text("{not json").size, 0);
  assert.deepEqual([...object_groups_text(fixture_text())], [["crate", "g"], ["pillar", "g"]]);
  assert.ok(is_group_name("x") && !is_group_name(" ") && !is_group_name("") && !is_group_name(1));
  // the validator drops the key: the core never sees it and a malformed value never fails a load
  const data = fixture();
  (data["objects"] as Record<string, unknown>[])[2]!["group"] = 12;
  const sc = load_scene(data);
  assert.ok(sc.objects.every((o) => !("group" in o)));
});

test("group_members: groups with ≥ 2 members in scene order; a singleton group behaves as ungrouped", () => {
  const groups = new Map([["a", "G"], ["b", "H"], ["c", "G"], ["d", "G"], ["zz", "G"]]);
  const members = group_members(groups, ["d", "a", "b", "c", "e"]);
  assert.deepEqual([...members], [["G", ["d", "a", "c"]]], "H has one member; zz is not in the scene");
  assert.equal(group_of("a", groups, members), "G");
  assert.equal(group_of("b", groups, members), null, "singleton");
  assert.equal(group_of("e", groups, members), null, "ungrouped");
  // a singleton's object clicks as an ungrouped one
  assert.deepEqual(next_selection(null, "b", groups, members), { kind: "part", id: "b" });
});

// ------------------------------------------------------------------------------------------------ click cycle

test("next_selection: the click cycle table (whole → part → whole, other part, other group, ungrouped)", () => {
  const groups = new Map([["a1", "A"], ["a2", "A"], ["b1", "B"], ["b2", "B"], ["s", "S"]]);
  const members = group_members(groups, ["a1", "a2", "b1", "b2", "s", "u"]);
  const G = (g: string): Selection => ({ kind: "group", group: g });
  const P = (id: string): Selection => ({ kind: "part", id });
  const rows: [Selection, string, Selection, string][] = [
    [null, "a1", G("A"), "first click on a grouped object: the whole group"],
    [G("A"), "a1", P("a1"), "second click: the clicked part"],
    [P("a1"), "a1", G("A"), "third click on the same part: the whole group again"],
    [G("A"), "a2", P("a2"), "group selected, click on another member: that part"],
    [P("a1"), "a2", P("a2"), "part focus, click on another part of the same model: focus moves"],
    [G("B"), "a1", G("A"), "another group selected: the clicked object's whole group"],
    [P("b1"), "a1", G("A"), "a part of another group: the clicked object's whole group"],
    [P("u"), "a1", G("A"), "an ungrouped object selected: the whole group"],
    [P("s"), "a1", G("A"), "a singleton-group object selected: the whole group"],
    [null, "u", P("u"), "ungrouped: the object (D83)"],
    [P("u"), "u", P("u"), "ungrouped again: unchanged (D83)"],
    [G("A"), "u", P("u"), "ungrouped while a group is selected"],
    [P("a1"), "u", P("u"), "ungrouped while a part is selected"],
    [null, "s", P("s"), "singleton group: as ungrouped"],
    [G("A"), "s", P("s"), "singleton group while a group is selected"],
  ];
  for (const [cur, clicked, want, what] of rows) assert.deepEqual(next_selection(cur, clicked, groups, members), want, what);
  // three clicks cycle and come back
  let sel: Selection = null;
  const seq: Selection[] = [];
  for (let k = 0; k < 5; k++) seq.push(sel = next_selection(sel, "b2", groups, members));
  assert.deepEqual(seq, [G("B"), P("b2"), G("B"), P("b2"), G("B")]);
});

test("selection value encoding (group.<name>, never an object id), labels and equality", () => {
  assert.equal(GROUP_VALUE_PREFIX, "group.");
  const cases: Selection[] = [null, { kind: "part", id: "crate" }, { kind: "group", group: "miki" }, { kind: "group", group: "a.b c" },
    { kind: "group", group: "" }];
  for (const s of cases) assert.deepEqual(selection_of_value(selection_value(s)), s);
  assert.equal(selection_value({ kind: "group", group: "miki" }), "group.miki");
  assert.ok(same_selection(null, null) && !same_selection(null, { kind: "part", id: "x" }));
  assert.ok(same_selection({ kind: "group", group: "x" }, { kind: "group", group: "x" }));
  assert.ok(!same_selection({ kind: "group", group: "x" }, { kind: "part", id: "x" }));
  assert.equal(group_option_label("miki", 18), "miki（整組，18 個部件）");
  const groups = new Map([["arm_l", "miki"], ["head", "miki"]]);
  const members = group_members(groups, ["arm_l", "head", "crate"]);
  assert.equal(selection_text({ kind: "group", group: "miki" }, groups, members), "已選：miki（整組）");
  assert.equal(selection_text({ kind: "part", id: "arm_l" }, groups, members), "已選：arm_l（miki 的部件）");
  assert.equal(selection_text({ kind: "part", id: "crate" }, groups, members), "已選：crate");
  assert.equal(selection_text(null, groups, members), "");
});

// ------------------------------------------------------------------------------------------------ group maths

test("group frame at load: G = I, c the centre of the members' world bbox (stage-A vertices), rings larger than a part's", () => {
  const l = load(fixture());
  assert.deepEqual([...l.session.groups], [["g", ["crate", "pillar"]]]);
  const f = l.session.group_frame("g")!;
  assert.deepEqual(f.G, identity3());
  const b = world_bbox([vertices_of(l.A, "crate"), vertices_of(l.A, "pillar")]);
  assert.deepEqual(f.c, b.centre);
  assert.deepEqual(l.session.initial_group_frame("g"), f);
  assert.equal(l.session.group_frame("nope"), null);
  const hd = l.session.group_loads.get("g")!.half_diagonal;
  for (const id of ["crate", "pillar"]) {
    assert.ok(ring_radius(hd) > ring_radius(l.session.local_half_diagonals.get(id)!), `${id}: the group's ring is larger`);
  }
  // a load-time bbox computed directly
  const all = [...vertices_of(l.A, "crate"), ...vertices_of(l.A, "pillar")];
  for (let k = 0; k < 3; k++) {
    const xs = all.map((v) => v[k]!);
    close(f.c[k]!, (Math.min(...xs) + Math.max(...xs)) / 2, 0, `c[${k}]`);
  }
  // an object listed in groups but missing from the poses, and a group left with one member, get no frame
  const s2 = new PlaneSession({ ...l.session.scene, object_poses: l.scene.objects.map((o) => ({ id: o.id, transform: o.transform,
    vertices: vertices_of(l.A, o.id) })), groups: new Map([["g", ["crate", "ghost"]]]) });
  assert.equal(s2.groups.size, 0);
  assert.equal(s2.group_frame("g"), null);
});

test("group rotation: 10 × 37° about mixed axes keeps c fixed and every member rigid (< 1e-9, against stage A); G = ΠQ", () => {
  const l = load(fixture());
  const pose0 = group_pose(l, "g");
  const c = pose0.group!.c;
  // each member's local point that sits at c at load
  const anchor = new Map([...pose0.transforms].map(([id, t]) => {
    const [R, p] = transform_frame(t);
    const d = [c[0] - p[0], c[1] - p[1], c[2] - p[2]];
    return [id, [0, 1, 2].map((j) => R[0][j] * d[0]! + R[1][j] * d[1]! + R[2][j] * d[2]!)] as const;
  }));
  const all0 = [...vertices_of(l.A, "crate"), ...vertices_of(l.A, "pillar")];
  const axes: Axis[] = [0, 2, 1, 2, 0, 1, 1, 0, 2, 1];
  let pose = pose0, G: Mat3 = identity3();
  for (const axis of axes) {
    pose = rotate_group_pose(pose, axis, 37);
    G = matmul(axis === 0 ? euler_zyx_matrix([37, 0, 0]) : axis === 1 ? euler_zyx_matrix([0, 37, 0]) : euler_zyx_matrix([0, 0, 37]), G);
  }
  assert.deepEqual(pose.group!.c, c, "c is never changed by a rotation");
  closeM(pose.group!.G, G, 1e-12, "G = product of the Qs");
  for (const [id, t] of pose.transforms) {
    const [R, p] = transform_frame(t);
    const a = anchor.get(id)!;
    close3([0, 1, 2].map((i) => R[i][0] * a[0]! + R[i][1] * a[1]! + R[i][2] * a[2]! + p[i]!), c, 1e-9, `${id}: c fixed`);
    closeM(R, matmul(G, transform_frame(pose0.transforms.get(id)!)[0]), 1e-9, `${id}: R = G·R0`);
  }
  // stage A on the rotated scene: all pairwise distances between every member's vertices are kept (one rigid motion)
  const A1 = shadow_geometry(with_pose(l.scene, pose));
  const all1 = [...vertices_of(A1, "crate"), ...vertices_of(A1, "pillar")];
  assert.equal(all1.length, all0.length);
  let worst = 0;
  for (let i = 0; i < all0.length; i += 3) {
    for (let j = i + 1; j < all0.length; j += 5) {
      const d0 = Math.hypot(all0[i]![0] - all0[j]![0], all0[i]![1] - all0[j]![1], all0[i]![2] - all0[j]![2]);
      const d1 = Math.hypot(all1[i]![0] - all1[j]![0], all1[i]![1] - all1[j]![1], all1[i]![2] - all1[j]![2]);
      worst = Math.max(worst, Math.abs(d1 - d0));
    }
  }
  assert.ok(worst < 1e-9, `rigid: worst pairwise distance change ${worst}`);
  // the ungrouped post is untouched
  assert.deepEqual(vertices_of(A1, "post"), vertices_of(l.A, "post"));
});

test("group numeric entry = the equivalent drags (x by rx, y by ry, z by rz); display Euler round trip of G", () => {
  const l = load(fixture());
  const pose0 = group_pose(l, "g");
  for (const e of [[20, -35, 110], [0, 0, 30], [-170, 60, -45], [5, 89.5, 12]] as Vec3[]) {
    const typed = set_group_rotation(pose0, e);
    const dragged = rotate_group_pose(rotate_group_pose(rotate_group_pose(pose0, 0, e[0]), 1, e[1]), 2, e[2]);
    assert.deepEqual(typed.group!.G, euler_zyx_matrix(e), "G is the typed angles' matrix exactly");
    closeM(dragged.group!.G, typed.group!.G, 1e-12, `${e}: G`);
    for (const [id, t] of typed.transforms) {
      const u = dragged.transforms.get(id)!;
      close3(t.position, u.position, 1e-9, `${e} ${id}: position`);
      closeM(transform_frame(t)[0], transform_frame(u)[0], 1e-9, `${e} ${id}: R`);
    }
    const shown = euler_zyx_from_matrix(typed.group!.G);
    close3(shown, e, 1e-9, `${e}: the fields show the typed angles`);
    closeM(euler_zyx_matrix(shown), typed.group!.G, 1e-12, `${e}: round trip`);
    // a second entry from a rotated group: Q = G_t·Gᵀ, the result again exactly G_t
    const again = set_group_rotation(typed, [0, 0, 0]);
    assert.deepEqual(again.group!.G, identity3());
    for (const [id, t] of again.transforms) {
      const t0 = pose0.transforms.get(id)!;
      close3(t.position, t0.position, 1e-9, `${e} ${id}: back to the load position`);
      closeM(transform_frame(t)[0], transform_frame(t0)[0], 1e-9, `${e} ${id}: back to the load rotation`);
    }
  }
  // about z the members' Euler angles are exact (rz wrapped, rx and ry unchanged), as M11's rotation about z
  const z = rotate_group_pose(pose0, 2, 30);
  for (const [id, t] of z.transforms) {
    const t0 = pose0.transforms.get(id)!;
    assert.equal(t.rotation_deg[0], t0.rotation_deg[0]);
    assert.equal(t.rotation_deg[1], t0.rotation_deg[1]);
    close(t.rotation_deg[2], t0.rotation_deg[2] + 30, 1e-12, `${id}: rz`);
  }
});

test("D84 review: an unedited 套用 on a group (the shown angles) is an exact no-op and records no undo step", () => {
  const l = load(fixture());
  const s = l.session;
  const pose0 = group_pose(l, "g");
  const cases: UnitPose[] = [pose0];
  for (const [axis, deg] of [[0, 37], [1, 37], [2, 37], [0, -12.5], [1, 90], [2, 30], [0, 1e-3]] as [Axis, number][]) {
    cases.push(rotate_group_pose(pose0, axis, deg));
  }
  cases.push(set_group_rotation(pose0, [20, -35, 110]));
  for (const p of cases) {
    const again = set_group_rotation(p, euler_zyx_from_matrix(p.group!.G));
    assert.ok(same_pose(p, again), "the same pose bit for bit");
    assert.notEqual(again.transforms, p.transforms, "a copy, not the same maps");
    const before = s.undo.size;
    assert.equal(s.record_objects(p.transforms, p.group, again.transforms, again.group), false);
    assert.equal(s.undo.size, before, "no undo step");
  }
  // a changed angle still rotates
  assert.ok(!same_pose(pose0, set_group_rotation(pose0, [0, 0, 1e-9])));
});

test("還原 and 落地 of a group: the load pose and frame; one common translation along the normal (curved members exact)", () => {
  const l = load(fixture());
  const pose0 = group_pose(l, "g");
  const tilted = rotate_group_pose(pose0, 0, 25);
  const scene1 = with_pose(l.scene, tilted);
  const A1 = shadow_geometry(scene1);
  assert.ok(A1.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), "the tilt goes through the ground (expected)");
  const r0 = l.scene.receivers[0]!, n = r0.normal, pi = [n[0], n[1], n[2], r0.offset];
  const dmin_of = (A: StageA): number => Math.min(...["crate", "pillar"].map((id) => {
    const rec = A.objects.find((o) => o.id === id)!;
    return rec.analytic !== null ? curved.plane_min(rec.analytic, pi)
      : Math.min(...rec.mesh.vertices.map((v) => n[0] * v[0] + n[1] * v[1] + n[2] * v[2] + r0.offset));
  }));
  const dmin = dmin_of(A1);
  assert.ok(dmin < 0);
  const grounded = translate_pose(tilted, [-dmin * n[0], -dmin * n[1], -dmin * n[2]]);
  const A2 = shadow_geometry(with_pose(l.scene, grounded));
  assert.ok(!A2.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), "on the ground after 落地");
  close(dmin_of(A2), 0, 1e-12, "the lowest point of the whole group touches");
  for (const [id, t] of grounded.transforms) {
    const u = tilted.transforms.get(id)!;
    assert.deepEqual(t.rotation_deg, u.rotation_deg, `${id}: rotation kept`);
    close3([t.position[0] - u.position[0], t.position[1] - u.position[1], t.position[2] - u.position[2]], [0, 0, -dmin], 1e-12, `${id}: common shift`);
  }
  close3(grounded.group!.c, [tilted.group!.c[0], tilted.group!.c[1], tilted.group!.c[2] - dmin], 1e-12, "c moves with the group");
  assert.deepEqual(grounded.group!.G, tilted.group!.G, "G unchanged by 落地");
  // 還原: every member back to its load transform, G = I, c = c0
  const init: UnitPose = { transforms: new Map([...grounded.transforms.keys()].map((id) => [id, l.session.initial_transform(id)!])),
    group: l.session.initial_group_frame("g") };
  assert.ok(same_pose(init, pose0));
  assert.ok(!same_pose(init, grounded));
});

test("a part of a group turns alone about its own pivot; the group frame is untouched", () => {
  const l = load(fixture());
  const t0 = l.scene.objects.find((o) => o.id === "crate")!.transform;
  const c_local = l.session.local_centres.get("crate")!;
  const drag = new UnitDrag<string, string>({ apply: () => true, proxy: () => {}, restore: () => {} });
  drag.begin(single_pose("crate", t0), "s", "A", 1, { axis: 0, c_locals: new Map([["crate", c_local]]) });
  const cand = drag.move(40)!;
  assert.deepEqual(cand.transforms.get("crate"), rotate_about_world_axis(t0, c_local, 0, 40), "as M11");
  assert.equal(cand.group, null);
  const res = drag.end()!;
  assert.ok(res.ok && res.changed);
  assert.deepEqual(l.session.group_frame("g"), l.session.initial_group_frame("g"));
  // the part's own pivot is the M11 one
  assert.deepEqual(c_local, local_bbox(t0, vertices_of(l.A, "crate")).centre);
});

test("UnitDrag on a group: frames apply the whole pose, end commits it, cancel restores pose, frame, scene0 and A0", () => {
  const l = load(fixture());
  const pose0 = group_pose(l, "g");
  const applied: UnitPose[] = [], restored: { pose: UnitPose; scene0: string; A0: string }[] = [];
  const d = new UnitDrag<string, string>({
    apply: (p) => (applied.push(clone_pose(p)), true),
    proxy: () => {},
    restore: (p, scene0, A0) => restored.push({ pose: clone_pose(p), scene0, A0 }),
  });
  d.begin(pose0, "scene0", "A0", 7, { axis: 2 });
  d.move(10);
  d.move(25);
  assert.equal(applied.length, 0, "moves only store the candidate");
  assert.equal(d.frame(6), false, "a stale sequence number applies nothing");
  assert.equal(d.frame(), true);
  assert.equal(applied.length, 1);
  assert.ok(same_pose(applied[0]!, rotate_group_pose(pose0, 2, 25)));
  d.move(30);
  const res = d.end()!;
  assert.equal(applied.length, 2, "end applies the last candidate synchronously");
  assert.ok(res.ok && res.changed && same_pose(res.pose, rotate_group_pose(pose0, 2, 30)) && same_pose(res.pose0, pose0));
  d.begin(pose0, "scene0", "A0", 8, { axis: 1 });
  d.move(15);
  d.frame();
  d.cancel();
  assert.equal(restored.length, 1);
  assert.ok(same_pose(restored[0]!.pose, pose0) && restored[0]!.scene0 === "scene0" && restored[0]!.A0 === "A0");
  // a press without movement records nothing
  d.begin(pose0, "scene0", "A0", 9, { axis: 0 });
  const still = d.end()!;
  assert.ok(still.ok && !still.changed);
});

// ------------------------------------------------------------------------------------------------ pivot and undo

test("pivot 點選物體: pick_group puts P on the group's c; switching the mode keeps it; unknown groups are ignored", () => {
  const l = load(fixture());
  const s = l.session;
  assert.deepEqual(s.pick_group("g"), { changed: false, framing: false }, "scene mode: no pick");
  s.set_pivot_mode("object");
  const r = s.pick_group("g");
  assert.ok(r.changed && r.framing);
  assert.deepEqual(s.pivot, { mode: "object", object_id: "group.g" });
  assert.deepEqual(s.rig.P, s.group_frame("g")!.c);
  assert.deepEqual(s.pivot_point(), s.group_frame("g")!.c);
  assert.equal(s.pick_group("nope").changed, false);
  assert.deepEqual(s.pivot.object_id, "group.g");
  s.pick_object("post");
  assert.deepEqual(s.rig.P, s.scene.object_centres.get("post"));
  s.pick_group("g");
  s.set_pivot_mode("scene");
  s.set_pivot_mode("object");
  assert.deepEqual(s.rig.P, s.scene.centre, "object mode with the pivot id cleared by the scene mode: the scene centre");
});

test("undo of group steps: every member and G / c restored exactly; LIFO with board and part steps; nothing for no change", () => {
  const l = load(fixture());
  const s = l.session;
  const pose0 = group_pose(l, "g");
  const crate0 = pose0.transforms.get("crate")!;
  // board step, group drag, part step, group numeric entry, board step
  s.view("top");
  const g1 = rotate_group_pose(pose0, 2, 30);
  s.begin_objects(pose0.transforms, pose0.group);
  assert.equal(s.end_objects(g1.transforms, g1.group), true);
  s.set_group_frame(g1.group!);
  const crate2 = rotate_about_world_axis(g1.transforms.get("crate")!, s.local_centres.get("crate")!, 1, 15);
  assert.equal(s.record_object("crate", g1.transforms.get("crate")!, crate2), true);
  const p2: UnitPose = { transforms: new Map([["crate", crate2], ["pillar", g1.transforms.get("pillar")!]]), group: g1.group };
  const g3 = set_group_rotation(p2, [0, 0, -10]);
  assert.equal(s.record_objects(p2.transforms, p2.group, g3.transforms, g3.group), true);
  s.set_group_frame(g3.group!);
  const rig_top = clone(s.rig);
  s.view("front");
  // nothing recorded for no change (the same poses and frame), for a press without change, or a cancelled drag
  assert.equal(s.record_objects(g3.transforms, g3.group, clone_pose(g3).transforms, clone_pose(g3).group), false);
  s.begin_objects(g3.transforms, g3.group);
  assert.equal(s.end_objects(clone_pose(g3).transforms, clone_pose(g3).group), false);
  s.begin_objects(g3.transforms, g3.group);
  s.cancel_object();
  // a frame-only change (all members already at their poses, G differs) is a step
  const frame_only = { ...g3.group!, G: identity3() };
  assert.equal(s.record_objects(g3.transforms, g3.group, g3.transforms, frame_only), true);
  assert.equal(s.undo.size, 6);
  // undo, newest first: frame-only, board, group numeric, part, group drag, board
  const u1 = s.undo_step();
  assert.ok(u1.objects !== undefined && u1.object === undefined);
  assert.deepEqual(u1.objects!.group, g3.group);
  s.pop_object_step();
  const u2 = s.undo_step();
  assert.ok(u2.object === undefined && u2.objects === undefined && u2.changed);
  assert.deepEqual(s.rig.f, rig_top.f, "the board step undone");
  const u3 = s.undo_step();
  assert.deepEqual(u3.objects, { transforms: p2.transforms, group: p2.group }, "the group numeric step: members and frame exactly");
  assert.equal(s.undo.size, 4, "peeked, not popped");
  s.pop_object_step();
  const u4 = s.undo_step();
  assert.deepEqual(u4.object, { id: "crate", transform: g1.transforms.get("crate") }, "the part step: that part only");
  s.pop_object_step();
  const u5 = s.undo_step();
  assert.deepEqual(u5.objects, { transforms: pose0.transforms, group: pose0.group }, "the group drag: the load poses and frame");
  assert.deepEqual(u5.objects!.transforms.get("crate"), crate0);
  s.pop_object_step();
  const u6 = s.undo_step();
  assert.ok(u6.changed && u6.objects === undefined);
  assert.deepEqual(s.rig.f, s.initial.f);
  assert.equal(s.undo.size, 0);
  // the step is a copy: mutating the returned maps never reaches the stack
  s.record_objects(pose0.transforms, pose0.group, g1.transforms, g1.group);
  const peek = s.undo_step();
  peek.objects!.transforms.get("crate")!.position[0] = 99;
  peek.objects!.group!.c[0] = 99;
  assert.deepEqual(s.undo_step().objects, { transforms: pose0.transforms, group: pose0.group });
});

test("the undo stack stays capped at 50 with group steps (oldest dropped)", () => {
  const l = load(fixture());
  const s = l.session;
  let pose = group_pose(l, "g");
  for (let i = 0; i < 60; i++) {
    const next = rotate_group_pose(pose, 2, 1);
    s.record_objects(pose.transforms, pose.group, next.transforms, next.group);
    pose = next;
  }
  assert.equal(s.undo.size, 50);
});

// ------------------------------------------------------------------------------------------------ download

test("scene_blob writes each object's group back verbatim; the reloaded file has the same groups and the same scene", () => {
  const data = fixture();
  (data["objects"] as Record<string, unknown>[])[0]!["group"] = " g ";
  (data["objects"] as Record<string, unknown>[])[1]!["group"] = " g ";
  (data["objects"] as Record<string, unknown>[])[2]!["group"] = "   "; // malformed: not written back
  const l = load(data);
  const cam = l.session.block();
  const text = scene_blob(l.scene, cam as Parameters<typeof scene_blob>[1], "basic_grouped", undefined, undefined, display_colours(data), l.groups).text;
  const parsed = JSON.parse(text) as { objects: Record<string, unknown>[] };
  assert.deepEqual(parsed.objects.map((o) => o["group"] ?? null), [" g ", " g ", null]);
  assert.deepEqual([...object_groups(parsed)], [...l.groups]);
  assert.deepEqual(load_scene_text(text).objects, l.scene.objects, "the core ignores the key");
  // without groups the text is the one before D84 (no group key)
  const plain = scene_blob(l.scene, cam as Parameters<typeof scene_blob>[1], "basic_grouped").text;
  assert.doesNotMatch(plain, /"group"/);
});

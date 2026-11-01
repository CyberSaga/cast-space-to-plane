/** Tests of D85 linked parts (`web/src/links.ts`, the subtree maths of `web/src/object_rotate.ts`, the resolved links
 * and part helpers of `web/src/plane.ts`, the carried count of `web/src/groups.ts::selection_text`, the `parent` /
 * `joint` keys of `web/src/download.ts::scene_blob`) on `web/test/fixtures/basic_linked.json`: parsing (malformed
 * values), resolution (unknown id, self, cross-group, singleton group, cycles, scene order), the subtree order, the
 * attachment invariant of a subtree drag about the joint (checked against stage A), the D84 regression of joint-less
 * parts, numeric entry ≡ the equivalent drags with the G4 no-op, G3 還原 relative to the parent, 落地 of a subtree, undo
 * of subtree steps interleaved with board, part and group steps, the download round trip, malformed scenes behaving as
 * D84, and the panel text / caches. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { curved, euler_zyx_matrix, load_scene, load_scene_text, shadow_geometry, transform_frame } from "castplane";
import type { Mat3, Scene, StageA, Transform, Vec3 } from "castplane";

import { display_colours } from "../src/colours.js";
import { scene_blob } from "../src/download.js";
import { group_members, object_groups, selection_text } from "../src/groups.js";
import { JOINT_KEY, PARENT_KEY, object_links, object_links_text, parse_joint, parse_parent, resolve_links, subtree } from "../src/links.js";
import type { LinkForest, RawLink } from "../src/links.js";
import { scene_centre } from "../src/observer.js";
import {
  RESTORE_EPS, UnitDrag, clone_transform, near_transform, restore_part_pose, rigid_map,
  rotate_about_world_axis, rotate_by_matrix, rotate_group_pose, rotate_unit, same_pose, same_transform, set_part_rotation,
  set_rotation, single_pose, translate_pose, world_centre,
} from "../src/object_rotate.js";
import type { Axis, UnitDragResult, UnitPose } from "../src/object_rotate.js";
import { PlaneSession, object_centres } from "../src/plane.js";
import { clone } from "../src/rig.js";

// web/build/test/links.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const FIXTURE = resolve(ROOT, "web", "test", "fixtures", "basic_linked.json");
const D84_FIXTURE = resolve(ROOT, "web", "test", "fixtures", "basic_grouped.json");
type Raw = Record<string, unknown> & { objects: Record<string, unknown>[] };
const fixture = (): Raw => JSON.parse(readFileSync(FIXTURE, "utf-8"));
/** The fixture with `patch` applied to its raw objects (by id). */
function patched(patch: (obj: (id: string) => Record<string, unknown>, data: Raw) => void): Raw {
  const data = fixture();
  patch((id) => data.objects.find((o) => o["id"] === id)!, data);
  return data;
}

const IDS = ["base", "mast", "arm", "flag", "lamp", "post"];
const LINKED_PARENT: [string, string][] = [["mast", "base"], ["arm", "mast"], ["flag", "arm"], ["lamp", "mast"]];
const LINKED_CHILDREN: [string, string[]][] = [["base", ["mast"]], ["mast", ["arm", "lamp"]], ["arm", ["flag"]]];
const LINKED_JOINTS: [string, Vec3][] = [["base", [0, 0, 0]], ["mast", [0, 0, 0]], ["arm", [-0.3, 0, 0]], ["flag", [0, 0, 0]]];

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}
function close3(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  for (let i = 0; i < 3; i++) close(a[i]!, b[i]!, tol, `${what}[${i}]`);
}
function closeM(A: Mat3, B: Mat3, tol: number, what: string): void {
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) close(A[i][j], B[i][j], tol, `${what}[${i}][${j}]`);
}
function closeT(a: Transform, b: Transform, tol: number, what: string): void {
  close3(a.position, b.position, tol, `${what}: position`);
  closeM(transform_frame(a)[0], transform_frame(b)[0], tol, `${what}: R`);
}

/** `W_q⁻¹·W_d`: the pose of `d` in the frame of `q` (`R = R_qᵀR_d`, `p = R_qᵀ(p_d − p_q)`). */
function relative(q: Transform, d: Transform): { R: Mat3; p: Vec3 } {
  const [Rq, pq] = transform_frame(q), [Rd, pd] = transform_frame(d);
  const R = [[0, 0, 0], [0, 0, 0], [0, 0, 0]] as Mat3;
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) R[i][j] = Rq[0][i] * Rd[0][j] + Rq[1][i] * Rd[1][j] + Rq[2][i] * Rd[2][j];
  const v = [pd[0] - pq[0], pd[1] - pq[1], pd[2] - pq[2]];
  const p: Vec3 = [0, 1, 2].map((i) => Rq[0][i] * v[0]! + Rq[1][i] * v[1]! + Rq[2][i] * v[2]!) as Vec3;
  return { R, p };
}
function close_rel(a: { R: Mat3; p: Vec3 }, b: { R: Mat3; p: Vec3 }, tol: number, what: string): void {
  closeM(a.R, b.R, tol, `${what}: relative R`);
  close3(a.p, b.p, tol, `${what}: relative p`);
}

interface Loaded {
  data: Raw;
  scene: Scene;
  A: StageA;
  groups: Map<string, string>;
  members: Map<string, string[]>;
  links: Map<string, RawLink>;
  session: PlaneSession;
}

/** A raw scene loaded as `main.ts::load` does (D84's helper of groups.test.ts, with the links). */
function load(data: Raw): Loaded {
  const scene = load_scene(data);
  const A = shadow_geometry(scene);
  const groups = object_groups(data);
  const members = group_members(groups, scene.objects.map((o) => o.id));
  const links = object_links(data);
  const recs = new Map(A.objects.map((o) => [o.id, o]));
  const session = new PlaneSession({ camera: scene.camera, canvas_mm: scene.output.canvas_mm, centre: scene_centre(A),
    object_centres: object_centres(A.objects), vertices: A.vertices,
    object_poses: scene.objects.map((o) => ({ id: o.id, transform: o.transform, vertices: recs.get(o.id)!.mesh.vertices })),
    groups: members, links });
  return { data, scene, A, groups, members, links, session };
}

/** The scene with the transforms of `pose` (the old scene is not mutated). */
const with_pose = (scene: Scene, pose: UnitPose): Scene => ({ ...scene, objects: scene.objects.map((o) => {
  const t = pose.transforms.get(o.id);
  return t === undefined ? o : { ...o, transform: clone_transform(t) };
}) });

const vertices_of = (A: StageA, id: string): Vec3[] => A.objects.find((o) => o.id === id)!.mesh.vertices;

/**
 * The page's object state as `main.ts` keeps it: the current scene and stage A, committed like `apply_pose` (stage A on
 * a copy, `update_scene`, the group frame only for a group pose); drags and discrete actions record undo steps as
 * design §4 says (one object → `begin_object` / `record_object`, several → `begin_objects` / `record_objects`).
 */
class Page {
  scene: Scene;
  A: StageA;
  private seq = 0;

  constructor(readonly l: Loaded) {
    this.scene = l.scene;
    this.A = l.A;
  }

  get s(): PlaneSession {
    return this.l.session;
  }

  readonly current = (id: string): Transform | null => {
    const o = this.scene.objects.find((x) => x.id === id);
    return o === undefined ? null : clone_transform(o.transform);
  };

  t(id: string): Transform {
    return this.current(id)!;
  }

  apply(pose: UnitPose): boolean {
    const scene1 = with_pose(this.scene, pose);
    const A1 = shadow_geometry(scene1);
    this.scene = scene1;
    this.A = A1;
    this.s.update_scene(A1.objects, A1);
    if (pose.group !== null) this.s.set_group_frame(pose.group);
    return true;
  }

  /** A ring drag of part `id` about `axis` by `deg` (`start_unit_drag` → `UnitDrag` → `finish_object_drag`). */
  drag(id: string, axis: Axis, deg: number): UnitDragResult {
    const s = this.s;
    const pose0 = s.part_pose(id, this.current)!;
    const c_locals = new Map<string, Vec3>([...pose0.transforms.keys()].map((k) => [k, s.local_centres.get(k)!]));
    const pivot = s.part_pivot(id, pose0.transforms.get(id)!);
    const d = new UnitDrag<Scene, StageA>({
      apply: (p) => this.apply(p),
      proxy: () => {},
      restore: (_p0, scene0, A0) => {
        this.scene = scene0;
        this.A = A0;
        s.update_scene(A0.objects, A0);
      },
    });
    this.seq += 1;
    d.begin(pose0, this.scene, this.A, this.seq, { axis, c_locals, pivot });
    const one = pose0.transforms.size === 1;
    if (one) s.begin_object(id, pose0.transforms.get(id)!);
    else s.begin_objects(pose0.transforms, pose0.group);
    d.move(deg / 2);
    d.frame();
    d.move(deg);
    const res = d.end()!;
    if (res.ok && res.changed) {
      if (one) s.end_object(res.pose.transforms.get(id)!);
      else s.end_objects(res.pose.transforms, res.pose.group);
    } else s.cancel_object();
    return res;
  }

  /** A discrete action (`main.ts::unit_action`): applied and recorded when it changes a pose; returns whether a step
   * was recorded. */
  action(after: UnitPose): boolean {
    const before = new Map<string, Transform>([...after.transforms.keys()].map((k) => [k, this.t(k)]));
    const frame_before = after.group === null ? null : this.s.group_frame(after.group.name);
    if (same_pose({ transforms: before, group: frame_before }, after)) return false;
    this.apply(after);
    if (after.group === null && after.transforms.size === 1) {
      const [k, t] = [...after.transforms][0]!;
      return this.s.record_object(k, before.get(k)!, t);
    }
    return this.s.record_objects(before, frame_before, after.transforms, after.group);
  }

  /** 復原 (`main.ts`'s #undo): an object step is applied and popped; returns the entry's kind and ids. */
  undo(): { kind: string; ids: string[]; group: string | null } {
    const r = this.s.undo_step();
    if (r.object !== undefined) {
      this.apply(single_pose(r.object.id, r.object.transform));
      this.s.pop_object_step();
      return { kind: "object", ids: [r.object.id], group: null };
    }
    if (r.objects !== undefined) {
      this.apply({ transforms: r.objects.transforms, group: r.objects.group });
      this.s.pop_object_step();
      return { kind: "objects", ids: [...r.objects.transforms.keys()], group: r.objects.group?.name ?? null };
    }
    return { kind: "rig", ids: [], group: null };
  }
}

// ------------------------------------------------------------------------------------------------ parsing

test("object_links: parent a non-empty UTF-8 string (verbatim), joint three finite numbers (-0 → 0); malformed keys absent", () => {
  const raw = { objects: [
    { id: "a", parent: "b", joint: [1, 2, 3] }, { id: "b", parent: " b " }, { id: "c", parent: "" }, { id: "d", parent: 3, joint: [0, 0, 0] },
    { id: "e", parent: null }, { id: "f", parent: ["x"] }, { id: "g", parent: "\ud800" }, { id: "h", parent: "x\udc00", joint: [0, 0] },
    { id: "i", joint: [0, "1", 0] }, { id: "j", joint: [NaN, 0, 0] }, { id: "k", joint: [0, Infinity, 0] }, { id: "l", joint: null },
    { id: "m", joint: [[0], [0], [0]] }, { id: "n", joint: [0, 0, 0, 0] }, { id: "o", joint: [-0, 0, -0] },
    { id: "p", joint: { 0: 1, 1: 2, 2: 3, length: 3 } }, { id: "q", parent: "😀", joint: [1e-300, -2.5, 7] }, { parent: "orphan" },
    { id: 7, parent: "x" }, null, "text", [1, 2], { id: "r", joint: "0,0,0" }, { id: "s", joint: [true, 0, 0] },
    { id: "t", parent: { id: "a" }, joint: [-Infinity, 0, 0] }, { id: "u", parent: "\udc00\ud800" }, { id: "v", joint: [] },
  ] };
  const got = object_links(raw);
  assert.deepEqual([...got], [
    ["a", { parent: "b", joint: [1, 2, 3] }], ["b", { parent: " b " }], ["d", { joint: [0, 0, 0] }], ["o", { joint: [0, 0, 0] }],
    ["q", { parent: "😀", joint: [1e-300, -2.5, 7] }],
  ]);
  const o = got.get("o")!.joint!;
  assert.ok(Object.is(o[0], 0) && Object.is(o[2], 0), "-0 is stored as 0");
  assert.ok(!("joint" in got.get("b")!) && !("parent" in got.get("d")!), "a malformed or missing key is absent, not undefined-valued");
  // the parsers
  assert.equal(parse_parent("x"), "x");
  assert.equal(parse_parent(" "), " ", "whitespace is kept (it can never equal an object id)");
  for (const bad of ["", "\ud800", "a\udfff", 1, null, undefined, ["x"], {}]) assert.equal(parse_parent(bad), null, String(bad));
  assert.equal(parse_parent("😀"), "😀", "a surrogate pair is fine");
  assert.deepEqual(parse_joint([1, -0, 2.5]), [1, 0, 2.5]);
  for (const bad of [[0, 0], [0, 0, 0, 0], [0, "0", 0], [NaN, 0, 0], [0, 0, Infinity], null, [[0], [0], [0]], "000", {}, [0, null, 0]]) {
    assert.equal(parse_joint(bad), null, JSON.stringify(bad));
  }
  // non-scenes, non-JSON, JSON-only cases (a lone surrogate escape, a number that overflows to Infinity)
  for (const bad of [null, 3, "x", [], {}, { objects: 3 }, { objects: null }]) assert.equal(object_links(bad).size, 0);
  assert.equal(object_links_text("{not json").size, 0);
  assert.equal(object_links_text('{"objects": [{"id": "m", "parent": "\\ud800x"}]}').size, 0);
  assert.equal(object_links_text('{"objects": [{"id": "m", "joint": [1e999, 0, 0]}]}').size, 0);
  // the fixture
  const fx = object_links(fixture());
  assert.deepEqual([...fx], [
    ["base", { joint: [0, 0, 0] }], ["mast", { parent: "base", joint: [0, 0, 0] }], ["arm", { parent: "mast", joint: [-0.3, 0, 0] }],
    ["flag", { parent: "arm", joint: [0, 0, 0] }], ["lamp", { parent: "mast" }],
  ]);
  assert.deepEqual(object_links_text(readFileSync(FIXTURE, "utf-8")), fx);
  assert.equal(PARENT_KEY, "parent");
  assert.equal(JOINT_KEY, "joint");
  // the validator drops both keys: the core never sees them and a malformed value never fails a load
  for (const data of [fixture(), patched((obj) => {
    obj("arm")["parent"] = 12;
    obj("flag")["joint"] = "x";
    obj("post")["joint"] = [NaN];
  })]) {
    const sc = load_scene(data);
    assert.equal(sc.objects.length, 6);
    assert.ok(sc.objects.every((x) => !("parent" in x) && !("joint" in x) && !("group" in x)));
  }
});

// ------------------------------------------------------------------------------------------------ resolution

/** The resolved forest of a patched fixture (through `PlaneSession`, as `main.ts::load` builds it). */
const forest_of = (data: Raw): LinkForest => load(data).session.links;
const pairs = (f: LinkForest): { parent: [string, string][]; children: [string, string[]][] } =>
  ({ parent: [...f.parent], children: [...f.children] });

test("resolve_links: the fixture's forest; unknown id, self, cross-group, singleton group and cycles dropped silently", () => {
  const f0 = forest_of(fixture());
  assert.deepEqual(pairs(f0), { parent: LINKED_PARENT, children: LINKED_CHILDREN });
  assert.deepEqual([...f0.joints], LINKED_JOINTS);
  const arm_root = { parent: [["mast", "base"], ["flag", "arm"], ["lamp", "mast"]] as [string, string][],
    children: [["base", ["mast"]], ["mast", ["lamp"]], ["arm", ["flag"]]] as [string, string[]][] };
  const rows: [string, (obj: (id: string) => Record<string, unknown>) => void, ReturnType<typeof pairs>][] = [
    ["unknown parent id", (obj) => { obj("arm")["parent"] = "nope"; }, arm_root],
    ["self", (obj) => { obj("arm")["parent"] = "arm"; }, arm_root],
    ["cross-group: a part's parent is the ungrouped post", (obj) => { obj("arm")["parent"] = "post"; }, arm_root],
    ["cross-group: the ungrouped post's parent is a part", (obj) => { obj("post")["parent"] = "mast"; },
      { parent: LINKED_PARENT, children: LINKED_CHILDREN }],
    ["a case-different id does not resolve", (obj) => { obj("arm")["parent"] = "Mast"; }, arm_root],
    ["singleton group: lamp alone in group h", (obj) => { obj("lamp")["group"] = "h"; },
      { parent: [["mast", "base"], ["arm", "mast"], ["flag", "arm"]], children: [["base", ["mast"]], ["mast", ["arm"]], ["arm", ["flag"]]] }],
    ["another ≥ 2 group: post → lamp inside h; lamp → mast across groups dropped", (obj) => {
      obj("lamp")["group"] = "h";
      obj("post")["group"] = "h";
      obj("post")["parent"] = "lamp";
    }, { parent: [["mast", "base"], ["arm", "mast"], ["flag", "arm"], ["post", "lamp"]],
      children: [["base", ["mast"]], ["mast", ["arm"]], ["arm", ["flag"]], ["lamp", ["post"]]] }],
    ["ungrouped child", (obj) => { delete obj("flag")["group"]; },
      { parent: [["mast", "base"], ["arm", "mast"], ["lamp", "mast"]], children: [["base", ["mast"]], ["mast", ["arm", "lamp"]]] }],
    ["2-cycle base ↔ mast: both links dropped, the trees hanging off mast kept", (obj) => { obj("base")["parent"] = "mast"; },
      { parent: [["arm", "mast"], ["flag", "arm"], ["lamp", "mast"]], children: [["mast", ["arm", "lamp"]], ["arm", ["flag"]]] }],
    ["3-cycle mast → flag → arm → mast: every cycle link dropped, lamp → mast kept", (obj) => { obj("mast")["parent"] = "flag"; },
      { parent: [["lamp", "mast"]], children: [["mast", ["lamp"]]] }],
    ["malformed parent values", (obj) => {
      obj("arm")["parent"] = 3;
      obj("flag")["parent"] = "";
      obj("lamp")["parent"] = "\ud800";
    }, { parent: [["mast", "base"]], children: [["base", ["mast"]]] }],
  ];
  for (const [what, patch, want] of rows) {
    const f = forest_of(patched(patch));
    assert.deepEqual(pairs(f), want, what);
    // joints are independent of parent validity and of grouping
    assert.deepEqual([...f.joints], LINKED_JOINTS, `${what}: joints`);
  }
  // scene order: children follow the order of the objects, whatever the order of the parent keys
  const reordered = fixture();
  const lamp = reordered.objects.splice(4, 1)[0]!;
  reordered.objects.splice(2, 0, lamp);
  assert.deepEqual(pairs(forest_of(reordered)).children, [["base", ["mast"]], ["mast", ["lamp", "arm"]], ["arm", ["flag"]]]);
  // a joint on an ungrouped object is honoured (a root's own joint); a malformed joint is absent
  const fj = forest_of(patched((obj) => {
    obj("post")["joint"] = [0, 0, 0.35];
    obj("arm")["joint"] = [0, 0];
  }));
  assert.deepEqual([...fj.joints], [["base", [0, 0, 0]], ["mast", [0, 0, 0]], ["flag", [0, 0, 0]], ["post", [0, 0, 0.35]]]);
  // links of ids that are not in the scene are ignored
  const ghost = resolve_links(new Map([["ghost", { parent: "base", joint: [1, 2, 3] as Vec3 }], ["base", { parent: "ghost" }]]), IDS, () => "g");
  assert.deepEqual(pairs(ghost), { parent: [], children: [] });
  assert.equal(ghost.joints.size, 0);
});

test("resolve_links: the cycle rule does not depend on the scene order (pure; tails off a cycle kept)", () => {
  // a → b → c → a (3-cycle), d → a, e → d (tail), f ↔ g (2-cycle), h → f, i root
  const raw = new Map<string, RawLink>([["a", { parent: "b" }], ["b", { parent: "c" }], ["c", { parent: "a" }], ["d", { parent: "a" }],
    ["e", { parent: "d" }], ["f", { parent: "g" }], ["g", { parent: "f" }], ["h", { parent: "f" }]]);
  const ids = ["a", "b", "c", "d", "e", "f", "g", "h", "i"];
  const want = [["d", "a"], ["e", "d"], ["h", "f"]];
  const orders = [ids, [...ids].reverse()];
  for (let k = 1; k < ids.length; k++) orders.push([...ids.slice(k), ...ids.slice(0, k)]);
  for (const order of orders) {
    const f = resolve_links(raw, order, () => "G");
    assert.deepEqual([...f.parent].sort(), want, order.join(""));
    for (const [c, p] of f.parent) assert.ok(f.children.get(p)!.includes(c));
  }
  // no group (null for every id) → no link at all; joints still kept
  const nog = resolve_links(new Map([["a", { parent: "b", joint: [1, 2, 3] as Vec3 }]]), ["a", "b"], () => null);
  assert.equal(nog.parent.size, 0);
  assert.deepEqual([...nog.joints], [["a", [1, 2, 3]]]);
  // the joints map holds copies
  const j: Vec3 = [1, 2, 3];
  const fc = resolve_links(new Map([["a", { joint: j }]]), ["a"], () => null);
  j[0] = 99;
  assert.deepEqual(fc.joints.get("a"), [1, 2, 3]);
});

test("subtree: preorder with the part first, siblings in scene order; PlaneSession's helpers agree", () => {
  const l = load(fixture());
  const f = l.session.links;
  const want: [string, string[]][] = [["base", ["base", "mast", "arm", "flag", "lamp"]], ["mast", ["mast", "arm", "flag", "lamp"]],
    ["arm", ["arm", "flag"]], ["flag", ["flag"]], ["lamp", ["lamp"]], ["post", ["post"]], ["zz", ["zz"]]];
  for (const [id, ids] of want) {
    const st = subtree(f, id);
    assert.deepEqual(st, ids, id);
    assert.equal(st[0], id, `${id}: P first`);
    assert.deepEqual(l.session.subtree(id), ids);
    // preorder: every member's parent comes before it
    for (let k = 1; k < st.length; k++) assert.ok(st.indexOf(f.parent.get(st[k]!)!) < k, `${id}: ${st[k]} after its parent`);
  }
  assert.equal(l.session.parent_of("arm"), "mast");
  assert.equal(l.session.parent_of("base"), null);
  assert.equal(l.session.parent_of("zz"), null);
  assert.deepEqual(l.session.children_of("mast"), ["arm", "lamp"]);
  assert.deepEqual(l.session.children_of("flag"), []);
  assert.deepEqual(l.session.joint("arm"), [-0.3, 0, 0]);
  assert.equal(l.session.joint("lamp"), null);
  assert.deepEqual(l.session.pivot_local("arm"), [-0.3, 0, 0], "a joint is the pivot");
  assert.deepEqual(l.session.pivot_local("lamp"), l.session.local_centres.get("lamp"), "no joint: c_local (D82)");
  close3(l.session.pivot_local("lamp")!, [0, 0, 0.12], 1e-12, "the sphere's c_local");
  assert.equal(l.session.pivot_local("zz"), null);
  for (const [id, linked] of [["base", true], ["mast", true], ["arm", true], ["flag", true], ["lamp", false], ["post", false]] as const) {
    assert.equal(l.session.linked(id), linked, id);
  }
  // copies: mutating what the helpers return never reaches the cache
  l.session.joint("arm")![0] = 5;
  l.session.pivot_local("lamp")![2] = 5;
  assert.deepEqual(l.session.joint("arm"), [-0.3, 0, 0]);
  close3(l.session.pivot_local("lamp")!, [0, 0, 0.12], 1e-12, "c_local kept");
  // scene order of siblings
  const reordered = fixture();
  reordered.objects.splice(2, 0, reordered.objects.splice(4, 1)[0]!);
  assert.deepEqual(load(reordered).session.subtree("mast"), ["mast", "lamp", "arm", "flag"]);
});

// ------------------------------------------------------------------------------------------------ the attachment invariant

test("attachment invariant: 7 subtree drags about the joint keep every descendant on its parent (< 1e-9, against stage A)", () => {
  const axes: Axis[] = [0, 2, 1, 1, 0, 2, 1];
  const degs = [37, -12.5, 90, 37, -12.5, 90, 37];
  for (const P of ["base", "mast", "arm"]) {
    const page = new Page(load(fixture()));
    const s = page.s;
    const load_t = (id: string): Transform => s.initial_transform(id)!;
    const S = s.subtree(P), desc = S.slice(1), others = IDS.filter((id) => !S.includes(id));
    const j_w0 = world_centre(load_t(P), s.joint(P)!);
    const rel0 = new Map(desc.map((d) => [d, relative(load_t(s.parent_of(d)!), load_t(d))]));
    const verts0 = new Map(IDS.map((id) => [id, vertices_of(page.A, id)]));
    const frame0 = s.initial_group_frame("g");
    for (let k = 0; k < axes.length; k++) {
      const what = `${P} drag ${k} (axis ${axes[k]}, ${degs[k]}°)`;
      const res = page.drag(P, axes[k]!, degs[k]!);
      assert.ok(res.ok && res.changed, what);
      assert.equal(res.pose.group, null, `${what}: a part pose`);
      assert.deepEqual([...res.pose.transforms.keys()], S, `${what}: exactly the subtree, P first`);
      for (const d of desc) close_rel(relative(page.t(s.parent_of(d)!), page.t(d)), rel0.get(d)!, 1e-9, `${what}: ${d} on its parent`);
      for (const o of others) assert.ok(same_transform(page.t(o), load_t(o)), `${what}: ${o} untouched`);
      assert.deepEqual(s.group_frame("g"), frame0, `${what}: G and c untouched`);
      close3(world_centre(page.t(P), s.joint(P)!), j_w0, 1e-9, `${what}: the joint stays`);
    }
    assert.equal(s.undo.size, axes.length, `${P}: one step per drag`);
    assert.equal(s.peek_undo()!.kind, "objects");
    assert.ok(!same_transform(page.t(P), load_t(P)), `${P} moved`);
    // stage A: all pairwise distances between the subtree's vertices are kept (one rigid motion)
    const all0 = S.flatMap((id) => verts0.get(id)!), all1 = S.flatMap((id) => vertices_of(page.A, id));
    assert.equal(all1.length, all0.length);
    let worst = 0;
    for (let i = 0; i < all0.length; i += 3) {
      for (let j = i + 1; j < all0.length; j += 7) {
        const d0 = Math.hypot(all0[i]![0] - all0[j]![0], all0[i]![1] - all0[j]![1], all0[i]![2] - all0[j]![2]);
        const d1 = Math.hypot(all1[i]![0] - all1[j]![0], all1[i]![1] - all1[j]![1], all1[i]![2] - all1[j]![2]);
        worst = Math.max(worst, Math.abs(d1 - d0));
      }
    }
    assert.ok(worst < 1e-9, `${P}: rigid, worst pairwise distance change ${worst}`);
    // ancestors, siblings (lamp for arm) and the ungrouped post: stage-A vertices bit for bit
    for (const o of others) assert.deepEqual(vertices_of(page.A, o), verts0.get(o), `${P}: ${o} vertices`);
  }
});

// ------------------------------------------------------------------------------------------------ D84 regression

test("D84 regression: a joint-less part takes the M11 path bit for bit (drag pivot, numeric entry, rigid_map ≡ rotate_by_matrix)", () => {
  const l = load(fixture());
  const s = l.session;
  const poses: Transform[] = [s.initial_transform("lamp")!, s.initial_transform("post")!,
    { position: [0.6, 7.5, 0.2], rotation_deg: [10, -20, 30] }, { position: [-1, 2, 3], rotation_deg: [170, 89.5, -45] }];
  for (const id of ["lamp", "post"]) {
    const c_local = s.local_centres.get(id)!;
    assert.equal(s.part_pivot(id, s.initial_transform(id)!), null, `${id}: no linked pivot`);
    for (const t of poses) {
      const pose = single_pose(id, t), cl = new Map([[id, c_local]]);
      for (const axis of [0, 1, 2] as Axis[]) {
        for (const deg of [37, -12.5, 90, 1e-3]) {
          const via_pivot = rotate_unit(pose, axis, deg, cl, world_centre(t, c_local));
          assert.deepEqual(via_pivot, rotate_unit(pose, axis, deg, cl, null), `${id} ${axis} ${deg}: pivot = c_w ≡ M11`);
          assert.deepEqual(via_pivot, rotate_unit(pose, axis, deg, cl), "the default");
          assert.deepEqual(via_pivot.transforms.get(id), rotate_about_world_axis(t, c_local, axis, deg));
        }
      }
      for (const r of [[20, -35, 110], [0, 0, 30], [-170, 60, -45], [5, 89.5, 12]] as Vec3[]) {
        assert.deepEqual(set_part_rotation(pose, id, c_local, r), single_pose(id, set_rotation(t, c_local, r)), `${id} ${r}: ≡ set_rotation`);
      }
    }
    // the session's dispatch: the M11 numeric path and a single-object pose
    const cur = (k: string): Transform | null => s.initial_transform(k);
    assert.deepEqual(s.part_pose(id, cur), single_pose(id, s.initial_transform(id)!));
    assert.deepEqual(s.part_numeric_pose(id, [10, 20, 30], cur), single_pose(id, set_rotation(s.initial_transform(id)!, c_local, [10, 20, 30])));
  }
  // a UnitDrag without a pivot (absent or null) is M11's
  const lamp0 = s.initial_transform("lamp")!, cl = new Map([["lamp", s.local_centres.get("lamp")!]]);
  for (const pivot of [undefined, null]) {
    const d = new UnitDrag<string, string>({ apply: () => true, proxy: () => {}, restore: () => {} });
    d.begin(single_pose("lamp", lamp0), "s", "A", 1, pivot === undefined ? { axis: 0, c_locals: cl } : { axis: 0, c_locals: cl, pivot });
    assert.deepEqual(d.move(40)!.transforms.get("lamp"), rotate_about_world_axis(lamp0, cl.get("lamp")!, 0, 40));
  }
  // rigid_map(t, Q, c, c) is rotate_by_matrix(t, c, Q) byte for byte
  for (const t of poses) {
    for (const [e, c] of [[[20, -35, 110], [1, 2, 3]], [[0, 0, 30], [0, 0, 0]], [[-170, 60, -45], [-0.3, 4.1, 1.25]]] as [Vec3, Vec3][]) {
      const Q = euler_zyx_matrix(e);
      assert.deepEqual(rigid_map(t, Q, c, c), rotate_by_matrix(t, c, Q));
    }
  }
  // a D84 scene (no links): every object takes the D84 path
  const d84 = JSON.parse(readFileSync(D84_FIXTURE, "utf-8")) as Raw;
  const l84 = load(d84);
  assert.equal(l84.links.size, 0);
  const cur84 = (k: string): Transform | null => l84.session.initial_transform(k);
  for (const o of l84.scene.objects) {
    const s84 = l84.session;
    assert.ok(!s84.linked(o.id) && s84.parent_of(o.id) === null);
    assert.deepEqual(s84.subtree(o.id), [o.id]);
    assert.deepEqual(s84.part_pose(o.id, cur84), single_pose(o.id, o.transform));
    assert.equal(s84.part_pivot(o.id, o.transform), null);
    assert.deepEqual(s84.part_numeric_pose(o.id, [1, 2, 3], cur84), single_pose(o.id, set_rotation(o.transform, s84.local_centres.get(o.id)!, [1, 2, 3])));
    // 還原 of a lone part: its load transform exactly (a turned one), a copy of the pose when unchanged
    const turned = rotate_about_world_axis(o.transform, s84.local_centres.get(o.id)!, 1, 33);
    const back = s84.part_restore_pose(o.id, (k) => k === o.id ? turned : cur84(k))!;
    assert.deepEqual(back, single_pose(o.id, o.transform));
    assert.ok(same_pose(s84.part_restore_pose(o.id, cur84)!, single_pose(o.id, o.transform)));
  }
});

// ------------------------------------------------------------------------------------------------ numeric entry

test("numeric entry of a linked part = the x, y, z drags about its joint for P and its descendants; G4: unedited is a copy", () => {
  const l = load(fixture());
  const s = l.session;
  const cur = (k: string): Transform | null => s.initial_transform(k);
  for (const P of ["base", "mast", "arm", "flag"]) {
    const pose0 = s.part_pose(P, cur)!;
    const c = s.part_pivot(P, pose0.transforms.get(P)!)!, pl = s.pivot_local(P)!;
    const cl = new Map([...pose0.transforms.keys()].map((k) => [k, s.local_centres.get(k)!]));
    for (const e of [[20, -35, 110], [0, 0, 30], [-170, 60, -45], [5, 89.5, 12]] as Vec3[]) {
      const typed = set_part_rotation(pose0, P, pl, e);
      assert.deepEqual(s.part_numeric_pose(P, e, cur), typed, `${P} ${e}: the session's dispatch`);
      assert.deepEqual(typed.transforms.get(P)!.rotation_deg, e, `${P} ${e}: the typed angles verbatim`);
      assert.deepEqual([...typed.transforms.keys()], s.subtree(P));
      assert.equal(typed.group, null);
      const dragged = rotate_unit(rotate_unit(rotate_unit(pose0, 0, e[0], cl, c), 1, e[1], cl, c), 2, e[2], cl, c);
      for (const [id, t] of typed.transforms) closeT(t, dragged.transforms.get(id)!, 1e-9, `${P} ${e} ${id}`);
      close3(world_centre(typed.transforms.get(P)!, pl), c, 1e-9, `${P} ${e}: the joint stays`);
      // a second entry from the rotated pose: back to the load poses
      const again = set_part_rotation(typed, P, pl, [0, 0, 0]);
      for (const [id, t] of again.transforms) closeT(t, pose0.transforms.get(id)!, 1e-9, `${P} ${e} ${id}: back`);
    }
    // G4: angles equal to P's rotation_deg return the pose unchanged (a copy) and record no undo step
    const cases: UnitPose[] = [pose0, set_part_rotation(pose0, P, pl, [20, -35, 110])];
    for (const [axis, deg] of [[0, 37], [1, -12.5], [2, 90], [0, 1e-3]] as [Axis, number][]) cases.push(rotate_unit(pose0, axis, deg, cl, c));
    for (const p of cases) {
      const r = [...p.transforms.get(P)!.rotation_deg];
      const again = set_part_rotation(p, P, pl, r);
      assert.ok(same_pose(p, again), `${P}: bit for bit`);
      assert.notEqual(again.transforms, p.transforms, "a copy");
      assert.notEqual(again.transforms.get(P), p.transforms.get(P), "copied transforms");
      const before = s.undo.size;
      assert.equal(s.record_objects(p.transforms, null, again.transforms, null), false);
      assert.equal(s.undo.size, before, "no undo step");
      // a changed angle still rotates the subtree
      r[2] = r[2]! + 1e-6;
      assert.ok(!same_pose(p, set_part_rotation(p, P, pl, r)));
    }
  }
  assert.throws(() => set_part_rotation({ transforms: new Map(), group: null }, "x", [0, 0, 0], [0, 0, 0]));
});

// ------------------------------------------------------------------------------------------------ 還原 (G3)

test("G3 還原 of a part: back relative to its parent's current pose, subtree carried; carried-only parts are no action", () => {
  const page = new Page(load(fixture()));
  const s = page.s;
  const load_t = (id: string): Transform => s.initial_transform(id)!;
  const rel_load = (q: string, d: string) => relative(load_t(q), load_t(d));
  const restore = (id: string): UnitPose => s.part_restore_pose(id, page.current)!;
  // rotate the mast 30° about x: arm, flag and lamp are carried
  page.drag("mast", 0, 30);
  const steps = s.undo.size;
  for (const id of ["arm", "flag", "lamp"]) {
    const pose = s.part_pose(id, page.current)!, init = restore(id);
    assert.ok(same_pose(pose, init), `${id}: carried only → the pose unchanged (initial_pose == unit_pose disables 還原)`);
    assert.notEqual(init.transforms, pose.transforms);
    assert.equal(page.action(init), false, `${id}: no step`);
  }
  assert.equal(s.undo.size, steps);
  // the naive world load pose would detach the arm from the mast's top (the discriminating case)
  const mast_top = world_centre(page.t("mast"), [0, 0, 1]);
  assert.ok(Math.hypot(...[0, 1, 2].map((k) => world_centre(load_t("arm"), s.joint("arm")!)[k]! - mast_top[k]!)) > 0.1);
  close3(world_centre(page.t("arm"), s.joint("arm")!), mast_top, 1e-9, "the arm's joint is on the mast's top");
  // a 0.32° adjustment of the arm is a real step; 還原 puts it back relative to the mast, the flag carried
  page.drag("arm", 2, 0.32);
  const flag_rel = relative(page.t("arm"), page.t("flag"));
  const back = restore("arm");
  assert.deepEqual([...back.transforms.keys()], ["arm", "flag"]);
  assert.equal(page.action(back), true, "a real step");
  close_rel(relative(page.t("mast"), page.t("arm")), rel_load("mast", "arm"), 1e-9, "arm relative to the mast = load");
  close_rel(relative(page.t("arm"), page.t("flag")), flag_rel, 1e-9, "flag carried");
  close3(world_centre(page.t("arm"), s.joint("arm")!), mast_top, 1e-9, "still on the mast's top");
  assert.ok(same_pose(restore("arm"), s.part_pose("arm", page.current)!), "a second 還原 is no action");
  // a descendant's own adjustment is kept: turn the flag about its joint, then the arm, then 還原 the arm
  page.drag("flag", 1, 20);
  page.drag("arm", 2, 15);
  const flag_own = relative(page.t("arm"), page.t("flag"));
  assert.equal(page.action(restore("arm")), true);
  close_rel(relative(page.t("mast"), page.t("arm")), rel_load("mast", "arm"), 1e-9, "arm back relative to the mast");
  close_rel(relative(page.t("arm"), page.t("flag")), flag_own, 1e-9, "the flag's own turn kept");
  // the lamp (a parent, no joint): its own M11 drag about c_w, then 還原 relative to the turned mast
  page.drag("lamp", 1, 40);
  assert.equal(page.action(restore("lamp")), true);
  close_rel(relative(page.t("mast"), page.t("lamp")), rel_load("mast", "lamp"), 1e-9, "lamp back relative to the mast");
  // the group frame is never written by a part action
  assert.deepEqual(s.group_frame("g"), s.initial_group_frame("g"));
});

test("G3 還原 of a root part writes its load transform verbatim; a part whose parent is at its load pose too", () => {
  const page = new Page(load(fixture()));
  const s = page.s;
  const load_t = (id: string): Transform => s.initial_transform(id)!;
  page.drag("base", 1, 25);
  page.drag("arm", 0, -12.5);
  const r = s.part_restore_pose("base", page.current)!;
  assert.deepEqual([...r.transforms.keys()], s.subtree("base"));
  assert.deepEqual(r.transforms.get("base"), load_t("base"), "root: the load transform exactly");
  assert.equal(page.action(r), true);
  for (const id of ["mast", "lamp"]) closeT(page.t(id), load_t(id), 1e-9, `${id} back with the base`);
  assert.ok(!near_transform(page.t("arm"), load_t("arm"), 1e-6), "the arm keeps its own turn relative to the mast");
  // the mast (the arm's parent) is back within ulps of its load pose (bit-equal or not): the arm's 還原 is a real one
  const ra = s.part_restore_pose("arm", page.current)!;
  assert.equal(page.action(ra), true);
  closeT(page.t("arm"), load_t("arm"), 1e-9, "arm back");
  // a lamp turned alone while the mast is exactly at its load pose: its load transform verbatim
  const p2 = new Page(load(fixture()));
  p2.drag("lamp", 2, 33);
  const rl = p2.s.part_restore_pose("lamp", p2.current)!;
  assert.deepEqual(rl, single_pose("lamp", p2.s.initial_transform("lamp")!));
  // restore_part_pose directly: a near pose with a parent is no action, the same pose without a parent is a write
  const t_load = load_t("arm"), nudged: Transform = { position: [t_load.position[0] + 1e-12, t_load.position[1], t_load.position[2]],
    rotation_deg: [...t_load.rotation_deg] as Vec3 };
  const pose = single_pose("arm", nudged);
  assert.ok(same_pose(restore_part_pose(pose, "arm", t_load, { now: load_t("mast"), load: load_t("mast") }), pose), "near → copy");
  assert.deepEqual(restore_part_pose(pose, "arm", t_load, null), single_pose("arm", t_load), "root: exact compare, verbatim write");
  assert.equal(RESTORE_EPS, 1e-9);
  assert.ok(near_transform(nudged, t_load, RESTORE_EPS) && !near_transform(nudged, t_load, 1e-13));
  // near_transform compares matrices, not angles: 180° and −180° are the same rotation
  assert.ok(near_transform({ position: [0, 0, 0], rotation_deg: [0, 0, 180] }, { position: [0, 0, 0], rotation_deg: [0, 0, -180] }, 1e-12));
  assert.ok(!near_transform({ position: [0, 0, 0], rotation_deg: [0, 0, 0] }, { position: [0, 0, 0], rotation_deg: [0, 0, 1e-6] }, 1e-12));
});

// ------------------------------------------------------------------------------------------------ 落地

test("落地 of a subtree: one common translation, the minimum over every member (the sphere exact)", () => {
  const page = new Page(load(fixture()));
  const s = page.s;
  page.drag("base", 0, 25);
  assert.ok(page.A.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), "tilted through the ground about its joint");
  const r0 = page.scene.receivers[0]!, n = r0.normal, pi = [n[0], n[1], n[2], r0.offset];
  const S = s.subtree("base");
  const dmin_of = (A: StageA): number => Math.min(...S.map((id) => {
    const rec = A.objects.find((o) => o.id === id)!;
    return rec.analytic !== null ? curved.plane_min(rec.analytic, pi)
      : Math.min(...rec.mesh.vertices.map((v) => n[0] * v[0] + n[1] * v[1] + n[2] * v[2] + r0.offset));
  }));
  const dmin = dmin_of(page.A);
  assert.ok(dmin < 0);
  const pose = s.part_pose("base", page.current)!;
  const grounded = translate_pose(pose, [-dmin * n[0], -dmin * n[1], -dmin * n[2]]);
  assert.equal(grounded.group, null);
  const rel0 = new Map(S.slice(1).map((d) => [d, relative(page.t(s.parent_of(d)!), page.t(d))]));
  assert.equal(page.action(grounded), true);
  assert.ok(!page.A.warnings.some((w) => w.code === "OBJECT_BELOW_RECEIVER"), "on the ground after 落地");
  close(dmin_of(page.A), 0, 1e-12, "the lowest point of the subtree touches");
  for (const [id, t] of grounded.transforms) {
    const u = pose.transforms.get(id)!;
    assert.deepEqual(t.rotation_deg, u.rotation_deg, `${id}: rotation kept`);
    close3([t.position[0] - u.position[0], t.position[1] - u.position[1], t.position[2] - u.position[2]], [0, 0, -dmin], 1e-12, `${id}: common shift`);
  }
  for (const [d, r] of rel0) close_rel(relative(page.t(s.parent_of(d)!), page.t(d)), r, 1e-12, `${d} still attached`);
  assert.ok(same_transform(page.t("post"), s.initial_transform("post")!));
  assert.deepEqual(s.group_frame("g"), s.initial_group_frame("g"), "c is not moved by a part's 落地");
  // the button is shown only for a root part (design §3): base is one, mast is not
  assert.equal(s.parent_of("base"), null);
  assert.equal(s.parent_of("mast"), "base");
});

// ------------------------------------------------------------------------------------------------ undo

test("undo: subtree drag and subtree numeric steps (objects, no frame) interleaved with board, part and group steps (LIFO)", () => {
  const page = new Page(load(fixture()));
  const s = page.s;
  const load_t = (id: string): Transform => s.initial_transform(id)!;
  // board step
  s.view("top");
  const rig_top = clone(s.rig);
  // subtree drag: begin_objects(…, null) / end_objects(…, null)
  const r1 = page.drag("mast", 2, 30);
  assert.ok(r1.changed);
  const after_drag = new Map(IDS.map((id) => [id, page.t(id)]));
  // a leaf part's numeric step (M11 path: one object)
  const leaf = s.part_numeric_pose("lamp", [0, 0, 45], page.current)!;
  assert.equal(leaf.transforms.size, 1);
  assert.equal(page.action(leaf), true);
  const after_leaf = new Map(IDS.map((id) => [id, page.t(id)]));
  // a group step: every member and the frame
  const members = page.l.members.get("g")!;
  const gp: UnitPose = { transforms: new Map(members.map((id) => [id, page.t(id)])), group: s.group_frame("g") };
  assert.equal(page.action(rotate_group_pose(gp, 2, 15)), true);
  const after_group = new Map(IDS.map((id) => [id, page.t(id)]));
  const frame_group = s.group_frame("g")!;
  // a subtree numeric step
  const num = s.part_numeric_pose("arm", [0, 10, 0], page.current)!;
  assert.deepEqual([...num.transforms.keys()], ["arm", "flag"]);
  assert.equal(page.action(num), true);
  // nothing for an unedited entry or a press without change
  assert.equal(page.action(s.part_numeric_pose("arm", [...page.t("arm").rotation_deg], page.current)!), false);
  s.begin_objects(s.part_pose("mast", page.current)!.transforms, null);
  assert.equal(s.end_objects(s.part_pose("mast", page.current)!.transforms, null), false);
  assert.equal(s.undo.size, 5);
  // a copy: mutating a peeked step never reaches the stack
  const peek = s.undo_step();
  peek.objects!.transforms.get("arm")!.position[0] = 99;
  assert.equal(s.undo.size, 5, "peeked, not popped");
  // undo, newest first
  const same_all = (want: Map<string, Transform>, what: string): void => {
    for (const id of IDS) assert.ok(same_transform(page.t(id), want.get(id)!), `${what}: ${id}`);
  };
  assert.deepEqual(page.undo(), { kind: "objects", ids: ["arm", "flag"], group: null }, "subtree numeric");
  same_all(after_group, "after undoing the subtree numeric step");
  assert.deepEqual(s.group_frame("g"), frame_group);
  assert.deepEqual(page.undo(), { kind: "objects", ids: members, group: "g" }, "group step");
  same_all(after_leaf, "after undoing the group step");
  assert.deepEqual(s.group_frame("g"), s.initial_group_frame("g"));
  assert.deepEqual(page.undo(), { kind: "object", ids: ["lamp"], group: null }, "leaf part");
  same_all(after_drag, "after undoing the leaf step");
  assert.deepEqual(page.undo(), { kind: "objects", ids: ["mast", "arm", "flag", "lamp"], group: null }, "subtree drag");
  for (const id of IDS) assert.ok(same_transform(page.t(id), load_t(id)), `${id}: back to load exactly`);
  assert.deepEqual(s.rig.f, rig_top.f, "the board untouched by object undos");
  assert.equal(page.undo().kind, "rig", "board step");
  assert.deepEqual(s.rig.f, s.initial.f);
  assert.equal(s.undo.size, 0);
});

// ------------------------------------------------------------------------------------------------ download

test("download round trip: parent / joint written back verbatim; the reload gives the same links, scene and world joints", () => {
  const data = patched((obj) => {
    obj("post")["parent"] = "lamp"; // parse-valid, dropped by resolution (ungrouped): written back, dropped again
    obj("post")["joint"] = [0, 0, 0.35];
    obj("lamp")["joint"] = [0, "x", 0]; // malformed: not written back
  });
  const page = new Page(load(data));
  const l = page.l;
  page.drag("arm", 1, 25);
  page.drag("mast", 0, -12.5);
  const cam = l.session.block() as Parameters<typeof scene_blob>[1];
  const text = scene_blob(page.scene, cam, "basic_linked", undefined, undefined, display_colours(data), l.groups, l.links).text;
  const parsed = JSON.parse(text) as Raw;
  const want: Record<string, { parent?: string; joint?: number[] }> = {
    base: { joint: [0, 0, 0] }, mast: { parent: "base", joint: [0, 0, 0] }, arm: { parent: "mast", joint: [-0.3, 0, 0] },
    flag: { parent: "arm", joint: [0, 0, 0] }, lamp: { parent: "mast" }, post: { parent: "lamp", joint: [0, 0, 0.35] },
  };
  for (const o of parsed.objects) {
    const w = want[o["id"] as string]!;
    assert.deepEqual(o[PARENT_KEY], w.parent, `${o["id"]}: parent`);
    assert.deepEqual(o[JOINT_KEY], w.joint, `${o["id"]}: joint`);
  }
  assert.deepEqual(object_links(parsed), l.links);
  assert.deepEqual(load_scene_text(text).objects, page.scene.objects, "the core ignores the keys");
  const l2 = load(parsed);
  assert.deepEqual(l2.session.links, l.session.links, "the same forest (post → lamp dropped again)");
  assert.equal(l2.session.parent_of("post"), null);
  for (const o of l2.scene.objects) {
    assert.deepEqual(o.transform, page.t(o.id), `${o.id}: the moved pose`);
    const j = l2.session.joint(o.id);
    if (j !== null) close3(world_centre(o.transform, j), world_centre(page.t(o.id), l.session.joint(o.id)!), 1e-9, `${o.id}: world joint`);
  }
  close3(world_centre(page.t("arm"), [-0.3, 0, 0]), world_centre(page.t("mast"), [0, 0, 1]), 1e-9, "still attached in the file");
  // without links the text is D84's (no parent / joint keys); an empty map adds nothing
  const plain = scene_blob(page.scene, cam, "basic_linked", undefined, undefined, display_colours(data), l.groups).text;
  assert.doesNotMatch(plain, /"parent"|"joint"/);
  assert.equal(scene_blob(page.scene, cam, "basic_linked", undefined, undefined, display_colours(data), l.groups, new Map()).text, plain);
  assert.equal(scene_blob(page.scene, cam, "basic_linked", undefined, undefined, display_colours(data), l.groups, undefined).text, plain);
});

// ------------------------------------------------------------------------------------------------ malformed → D84

test("malformed links and joints: the part behaves as D84 (single pose, M11 drag about c_w, M11 numeric entry)", () => {
  const variants: [string, (obj: (id: string) => Record<string, unknown>) => void][] = [
    ["unknown parent, short joint", (obj) => { obj("flag")["parent"] = "nope"; obj("flag")["joint"] = [0, 0]; }],
    ["self parent, string element", (obj) => { obj("flag")["parent"] = "flag"; obj("flag")["joint"] = [0, "0", 0]; }],
    ["cross-group parent, NaN", (obj) => { obj("flag")["parent"] = "post"; obj("flag")["joint"] = [NaN, 0, 0]; }],
    ["non-string parent, null joint", (obj) => { obj("flag")["parent"] = 3; obj("flag")["joint"] = null; }],
    ["empty parent, nested joint", (obj) => { obj("flag")["parent"] = ""; obj("flag")["joint"] = [[0], [0], [0]]; }],
    ["lone-surrogate parent, Infinity", (obj) => { obj("flag")["parent"] = "\ud800"; obj("flag")["joint"] = [Infinity, 0, 0]; }],
    ["2-cycle flag ↔ lamp", (obj) => { obj("flag")["parent"] = "lamp"; obj("lamp")["parent"] = "flag"; delete obj("flag")["joint"]; }],
    ["ungrouped", (obj) => { delete obj("flag")["group"]; delete obj("flag")["joint"]; }],
    ["singleton group", (obj) => { obj("flag")["group"] = "h"; delete obj("flag")["joint"]; }],
  ];
  for (const [what, patch] of variants) {
    const l = load(patched(patch));
    const s = l.session;
    const t = s.initial_transform("flag")!, c_local = s.local_centres.get("flag")!;
    const cur = (k: string): Transform | null => s.initial_transform(k);
    assert.deepEqual(s.subtree("flag"), ["flag"], what);
    assert.equal(s.parent_of("flag"), null, what);
    assert.ok(!s.linked("flag"), what);
    assert.equal(s.part_pivot("flag", t), null, what);
    assert.deepEqual(s.part_pose("flag", cur), single_pose("flag", t), `${what}: single_pose`);
    assert.deepEqual(s.pivot_local("flag"), c_local, `${what}: c_local`);
    const cl = new Map([["flag", c_local]]);
    for (const axis of [0, 1, 2] as Axis[]) {
      const d = new UnitDrag<string, string>({ apply: () => true, proxy: () => {}, restore: () => {} });
      d.begin(s.part_pose("flag", cur)!, "s", "A", 1, { axis, c_locals: cl, pivot: s.part_pivot("flag", t) });
      const cand = d.move(37)!;
      assert.deepEqual(cand, rotate_unit(single_pose("flag", t), axis, 37, cl), `${what}: rotate_unit`);
      assert.deepEqual(cand.transforms.get("flag"), rotate_about_world_axis(t, c_local, axis, 37), `${what}: M11`);
    }
    assert.deepEqual(s.part_numeric_pose("flag", [5, 6, 7], cur), single_pose("flag", set_rotation(t, c_local, [5, 6, 7])), `${what}: numeric`);
    const turned = rotate_about_world_axis(t, c_local, 2, 20);
    assert.deepEqual(s.part_restore_pose("flag", (k) => k === "flag" ? turned : cur(k)), single_pose("flag", t), `${what}: 還原 verbatim`);
    // the scene is the D84 scene for the core: stage A unchanged
    assert.deepEqual(l.A.objects.map((o) => o.mesh.vertices), load(fixture()).A.objects.map((o) => o.mesh.vertices), `${what}: stage A`);
  }
});

// ------------------------------------------------------------------------------------------------ text, caches

test("panel text carries the count; update_scene keeps the links and joints; part poses are copies", () => {
  const page = new Page(load(fixture()));
  const { groups, members, session: s } = page.l;
  const text = (id: string): string => selection_text({ kind: "part", id }, groups, members, s.subtree(id).length - 1);
  assert.equal(text("arm"), "已選：arm（g 的部件，帶動 1 個部件）");
  assert.equal(text("base"), "已選：base（g 的部件，帶動 4 個部件）");
  assert.equal(text("mast"), "已選：mast（g 的部件，帶動 3 個部件）");
  assert.equal(text("flag"), "已選：flag（g 的部件）", "a leaf: the D84 string");
  assert.equal(text("lamp"), "已選：lamp（g 的部件）");
  assert.equal(text("post"), "已選：post", "ungrouped");
  assert.equal(selection_text({ kind: "part", id: "post" }, groups, members, 3), "已選：post", "no group: the count is ignored");
  assert.equal(selection_text({ kind: "group", group: "g" }, groups, members, 5), "已選：g（整組）");
  assert.equal(selection_text(null, groups, members, 2), "");
  assert.equal(selection_text({ kind: "part", id: "arm" }, groups, members), "已選：arm（g 的部件）", "default 0: D84");
  // update_scene (after a rotation) keeps the forest, the joints and the local pivots
  const links0 = s.links, frozen = JSON.stringify({ p: [...s.links.parent], c: [...s.links.children], j: [...s.links.joints] });
  const lc0 = new Map(s.local_centres);
  page.drag("mast", 0, 30);
  assert.equal(s.links, links0, "the same object");
  assert.equal(JSON.stringify({ p: [...s.links.parent], c: [...s.links.children], j: [...s.links.joints] }), frozen);
  assert.deepEqual(new Map(s.local_centres), lc0);
  assert.deepEqual(s.joint("arm"), [-0.3, 0, 0]);
  assert.deepEqual(s.subtree("mast"), ["mast", "arm", "flag", "lamp"]);
  // part poses hold copies: mutating them never reaches the scene
  const pose = s.part_pose("mast", page.current)!;
  pose.transforms.get("arm")!.position[0] = 99;
  assert.notEqual(page.t("arm").position[0], 99);
  // a pivot copied at begin: mutating the caller's array after begin changes nothing
  const pv = s.part_pivot("arm", page.t("arm"))!, pv0 = [...pv];
  const d = new UnitDrag<string, string>({ apply: () => true, proxy: () => {}, restore: () => {} });
  const p0 = s.part_pose("arm", page.current)!;
  d.begin(p0, "s", "A", 1, { axis: 2, pivot: pv });
  pv[0] = 99;
  assert.deepEqual(d.move(10), rotate_unit(p0, 2, 10, new Map(), pv0));
  // the drag pivot is the world joint
  assert.deepEqual(s.part_pivot("arm", page.t("arm")), world_centre(page.t("arm"), [-0.3, 0, 0]));
});

test("a part with children but no joint turns its subtree about its own c_w (D82 pivot), carrying the children", () => {
  const page = new Page(load(patched((obj) => { delete obj("arm")["joint"]; })));
  const s = page.s;
  assert.equal(s.joint("arm"), null);
  assert.ok(s.linked("arm"), "descendants make it linked");
  const t0 = page.t("arm"), c_local = s.local_centres.get("arm")!;
  assert.deepEqual(s.pivot_local("arm"), c_local);
  assert.deepEqual(s.part_pivot("arm", t0), world_centre(t0, c_local));
  const rel0 = relative(t0, page.t("flag"));
  const res = page.drag("arm", 1, 37);
  assert.deepEqual([...res.pose.transforms.keys()], ["arm", "flag"]);
  close_rel(relative(page.t("arm"), page.t("flag")), rel0, 1e-9, "flag carried");
  close3(world_centre(page.t("arm"), c_local), world_centre(t0, c_local), 1e-9, "c_w stays");
  assert.ok(same_transform(page.t("mast"), s.initial_transform("mast")!) && same_transform(page.t("lamp"), s.initial_transform("lamp")!));
  // numeric entry about c_w: the arm's angles verbatim, the flag by the same Q
  const typed = s.part_numeric_pose("arm", [0, 0, 20], page.current)!;
  assert.deepEqual(typed, set_part_rotation(s.part_pose("arm", page.current)!, "arm", c_local, [0, 0, 20]));
  assert.deepEqual(typed.transforms.get("arm"), set_rotation(page.t("arm"), c_local, [0, 0, 20]));
  close_rel(relative(typed.transforms.get("arm")!, typed.transforms.get("flag")!), rel0, 1e-9, "flag carried by the entry");
});

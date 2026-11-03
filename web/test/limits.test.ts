/** Tests of D86 joint limits (`web/src/limits.ts`, the `joint_limit` key of `web/src/links.ts`, the clamp option of
 * `web/src/object_rotate.ts::UnitDrag`, the limit helpers of `web/src/plane.ts`, the key in
 * `web/src/download.ts::scene_blob`) on `web/test/fixtures/basic_limited.json` (`basic_linked.json` plus limits on
 * `arm`, `lamp`, an ungrouped `post`, a malformed one on `flag`, and a group `h` whose parent `pole` and child `tip`
 * load at `rz = 50°`): the parse and resolve tables, the twist (random, 180°, the singular point), the relative rotation
 * `D = R_Qᵀ·R_P` and its invariance, the parent-local axis, the closed-form clamp against dense sampling, the ±180 wall
 * (review R1), a blocked drag leaving `pose0` bit for bit (R2), the page-level drags, 套用 accepted at the bound and
 * refused beyond it, a part loaded outside its range and the reload that keeps the angle (R3), the strings (R7) and the
 * download round trip. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { euler_zyx_matrix, load_scene, load_scene_text, shadow_geometry, transform_frame } from "castplane";
import type { Mat3, Scene, StageA, Transform, Vec3 } from "castplane";

import { display_colours } from "../src/colours.js";
import { scene_blob } from "../src/download.js";
import { group_members, object_groups } from "../src/groups.js";
import { LIMIT_KEY, limit_for_file, object_links, object_links_text, parse_joint_limit } from "../src/links.js";
import type { RawLink } from "../src/links.js";
import {
  KAPPA_EPS, LIMIT_EPS_DEG, canonical_angle, clamp_drag_angle, drag_clamp, drag_gesture, format_axis, format_axis_component,
  format_deg1, gesture_angle, inside, limit_angle, limit_state, limit_text, quat_from_matrix, range_text, refusal_text,
  relative_rotation, twist_deg,
} from "../src/limits.js";
import type { Limit } from "../src/limits.js";
import { scene_centre } from "../src/observer.js";
import {
  UnitDrag, clone_transform, matmul, rotate_by_matrix, rotate_group_pose, rotate_unit, same_pose, same_transform,
  single_pose, snap_angle, wrap_angle, world_centre,
} from "../src/object_rotate.js";
import type { Axis, UnitDragResult, UnitPose } from "../src/object_rotate.js";
import { PlaneSession, object_centres } from "../src/plane.js";

// web/build/test/limits.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const FIXTURE = resolve(ROOT, "web", "test", "fixtures", "basic_limited.json");
type Raw = Record<string, unknown> & { objects: Record<string, unknown>[] };
const fixture = (): Raw => JSON.parse(readFileSync(FIXTURE, "utf-8"));
function patched(patch: (obj: (id: string) => Record<string, unknown>) => void): Raw {
  const data = fixture();
  patch((id) => data.objects.find((o) => o["id"] === id)!);
  return data;
}

const DEG = Math.PI / 180;

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}

/** A seeded uniform generator in [0, 1). */
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

function unit(v: readonly number[]): Vec3 {
  const n = Math.hypot(v[0]!, v[1]!, v[2]!);
  return [v[0]! / n, v[1]! / n, v[2]! / n];
}
const rand_unit = (r: () => number): Vec3 => {
  for (;;) {
    const v: Vec3 = [2 * r() - 1, 2 * r() - 1, 2 * r() - 1];
    const n = Math.hypot(...v);
    if (n > 0.1 && n <= 1) return unit(v);
  }
};
const cross = (a: readonly number[], b: readonly number[]): Vec3 =>
  [a[1]! * b[2]! - a[2]! * b[1]!, a[2]! * b[0]! - a[0]! * b[2]!, a[0]! * b[1]! - a[1]! * b[0]!];
/** A unit vector ⟂ `a`. */
const perp = (a: Vec3, r: () => number): Vec3 => unit(cross(a, rand_unit(r)));

/** The rotation about the unit axis `k` by `deg` (Rodrigues). */
function rodrigues(k: readonly number[], deg: number): Mat3 {
  const t = deg * DEG, c = Math.cos(t), s = Math.sin(t), v = 1 - c;
  const [x, y, z] = [k[0]!, k[1]!, k[2]!];
  return [
    [c + x * x * v, x * y * v - z * s, x * z * v + y * s],
    [y * x * v + z * s, c + y * y * v, y * z * v - x * s],
    [z * x * v - y * s, z * y * v + x * s, c + z * z * v],
  ];
}
const I3 = (): Mat3 => [[1, 0, 0], [0, 1, 0], [0, 0, 1]];

/** A limit record. */
function lim(a: readonly number[], min: number | null, max: number | null): Limit {
  return { axis: [a[0]!, a[1]!, a[2]!], a: unit(a), min: min ?? -180, max: max ?? 180, min_written: min !== null, max_written: max !== null };
}

interface Loaded {
  data: Raw;
  scene: Scene;
  A: StageA;
  groups: Map<string, string>;
  links: Map<string, RawLink>;
  session: PlaneSession;
}

/** A raw scene loaded as `main.ts::load` does. */
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
  return { data, scene, A, groups, links, session };
}

const with_pose = (scene: Scene, pose: UnitPose): Scene => ({ ...scene, objects: scene.objects.map((o) => {
  const t = pose.transforms.get(o.id);
  return t === undefined ? o : { ...o, transform: clone_transform(t) };
}) });

/** The page's object state as `main.ts` keeps it (the helper of links.test.ts), with the D86 clamp on part drags and
 * the 套用 refusal. */
class Page {
  scene: Scene;
  A: StageA;
  applies = 0;
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

  phi(id: string): number {
    return this.s.part_limit_angle(id, this.current)!.phi;
  }

  state(id: string): string {
    return this.s.part_limit_angle(id, this.current)!.state;
  }

  apply(pose: UnitPose): boolean {
    this.applies += 1;
    const scene1 = with_pose(this.scene, pose);
    const A1 = shadow_geometry(scene1);
    this.scene = scene1;
    this.A = A1;
    this.s.update_scene(A1.objects, A1);
    if (pose.group !== null) this.s.set_group_frame(pose.group);
    return true;
  }

  /** A ring drag of part `id` about `axis` by `deg` (`main.ts::start_unit_drag` with the D86 clamp → `UnitDrag` →
   * `finish_object_drag`); `moves` the intermediate angles before `deg`. */
  drag(id: string, axis: Axis, deg: number, moves: number[] = [deg / 2]): UnitDragResult {
    const s = this.s;
    const pose0 = s.part_pose(id, this.current)!;
    const c_locals = new Map<string, Vec3>([...pose0.transforms.keys()].map((k) => [k, s.local_centres.get(k)!]));
    const t0 = pose0.transforms.get(id)!;
    const pivot = s.part_pivot(id, t0), clamp = s.part_drag_clamp(id, axis, t0, this.current);
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
    d.begin(pose0, this.scene, this.A, this.seq, { axis, c_locals, pivot, clamp });
    const one = pose0.transforms.size === 1;
    if (one) s.begin_object(id, pose0.transforms.get(id)!);
    else s.begin_objects(pose0.transforms, pose0.group);
    for (const m of moves) {
      d.move(m);
      d.frame();
    }
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

  /** 套用 of `r` on part `id` (`main.ts::apply_object_rotation`): refused when the target is outside the limit (no
   * action), else the action. Returns `{ok, refused, phi}`. */
  set_rotation(id: string, r: readonly number[]): { ok: boolean; refused: boolean; phi: number | null } {
    const after = this.s.part_numeric_pose(id, r, this.current)!;
    const chk = this.s.part_limit_check(id, after, this.current), now = this.s.part_pose(id, this.current)!;
    if (chk !== null && !chk.inside && !same_pose(now, after)) return { ok: false, refused: true, phi: chk.phi };
    this.action(after);
    return { ok: true, refused: false, phi: chk?.phi ?? null };
  }

  undo(): void {
    const r = this.s.undo_step();
    if (r.object !== undefined) this.apply(single_pose(r.object.id, r.object.transform));
    else if (r.objects !== undefined) this.apply({ transforms: r.objects.transforms, group: r.objects.group });
    else return;
    this.s.pop_object_step();
  }

  /** Every object's transform (copies, scene order). */
  snapshot(): Transform[] {
    return this.scene.objects.map((o) => clone_transform(o.transform));
  }
}

// ------------------------------------------------------------------------------------------------ parsing

test("parse_joint_limit: axis three finite numbers of non-zero finite length, bounds finite in [-180, 180], one at least, min ≤ max", () => {
  assert.equal(LIMIT_KEY, "joint_limit");
  const ok: [unknown, unknown][] = [
    [{ axis: [0, 1, 0], max_deg: 11 }, { axis: [0, 1, 0], max_deg: 11 }],
    [{ axis: [0, 0, 2], min_deg: -30, max_deg: 30 }, { axis: [0, 0, 2], min_deg: -30, max_deg: 30 }],
    [{ axis: [-0, 1, -0], min_deg: -0 }, { axis: [0, 1, 0], min_deg: 0 }],
    [{ axis: [1, 0, 0], min_deg: -180, max_deg: 180 }, { axis: [1, 0, 0], min_deg: -180, max_deg: 180 }],
    [{ axis: [1, 0, 0], min_deg: 5, max_deg: 5 }, { axis: [1, 0, 0], min_deg: 5, max_deg: 5 }],
    [{ axis: [1, 0, 0], max_deg: 1, extra: "x", min_deg: undefined }, { axis: [1, 0, 0], max_deg: 1 }],
    [{ axis: [1e-300, 0, 0], max_deg: 1 }, { axis: [1e-300, 0, 0], max_deg: 1 }],
  ];
  for (const [v, want] of ok) {
    const got = parse_joint_limit(v);
    assert.deepEqual(got, want, JSON.stringify(v));
    assert.ok(got !== null && !("extra" in got) && got.axis.every((x) => !Object.is(x, -0)), "no -0, no extra property");
    if (got !== null && got.min_deg !== undefined) assert.ok(!Object.is(got.min_deg, -0));
  }
  assert.ok(!("min_deg" in parse_joint_limit({ axis: [1, 0, 0], max_deg: 1, min_deg: undefined })!), "an undefined bound is absent");
  const bad: unknown[] = [
    null, undefined, 3, "x", [], [{ axis: [0, 1, 0], max_deg: 11 }], {}, { max_deg: 11 }, { axis: [0, 0, 0], max_deg: 11 },
    { axis: [1.5e308, 1.5e308, 0], max_deg: 11 }, { axis: [0, 1], max_deg: 11 }, { axis: [0, 1, 0, 0], max_deg: 11 },
    { axis: [0, "1", 0], max_deg: 11 }, { axis: [0, NaN, 0], max_deg: 11 }, { axis: [0, 1, 0], max_deg: NaN },
    { axis: [0, 1, 0], max_deg: Infinity }, { axis: [0, 1, 0], max_deg: 181 }, { axis: [0, 1, 0], min_deg: -180.5 },
    { axis: [0, 1, 0], min_deg: 20, max_deg: 10 }, { axis: [0, 1, 0] }, { axis: [0, 1, 0], min_deg: null, max_deg: 11 },
    { axis: [0, 1, 0], max_deg: "11" }, { axis: "0,1,0", max_deg: 11 }, { axis: { 0: 0, 1: 1, 2: 0, length: 3 }, max_deg: 11 },
  ];
  for (const v of bad) assert.equal(parse_joint_limit(v), null, JSON.stringify(v) ?? String(v));
  // object_links of the fixture: arm, lamp, post (parse-valid) and tip carry a limit; flag's (min > max) is absent
  const links = object_links(fixture());
  const limits = [...links].filter(([, l]) => l.joint_limit !== undefined).map(([id, l]) => [id, l.joint_limit]);
  assert.deepEqual(limits, [
    ["arm", { axis: [0, 1, 0], max_deg: 11 }], ["lamp", { axis: [0, 0, 1], min_deg: -30, max_deg: 30 }],
    ["post", { axis: [1, 0, 0], max_deg: 20 }], ["tip", { axis: [1, 0, 0], min_deg: -20, max_deg: 20 }],
  ]);
  assert.deepEqual(links.get("flag"), { parent: "arm", joint: [0, 0, 0] }, "the malformed limit is simply absent");
  // a limit alone makes an entry; the text reader; the core never sees the key
  assert.deepEqual([...object_links({ objects: [{ id: "a", joint_limit: { axis: [0, 0, 1], min_deg: -5 } }] })],
    [["a", { joint_limit: { axis: [0, 0, 1], min_deg: -5 } }]]);
  assert.deepEqual([...object_links_text('{"objects": [{"id": "a", "joint_limit": {"axis": [0, 0, 1], "max_deg": 1e999}}]}')], []);
  assert.deepEqual([...object_links_text("not json")], []);
  for (const o of load_scene(fixture()).objects) assert.ok(!(LIMIT_KEY in o), `${o.id}: the validator drops the key`);
});

test("resolve: a limit only on a part with a resolved parent (unit axis, ±180 defaults); dropped with its link; update_scene keeps it", () => {
  const l = load(fixture());
  assert.deepEqual(l.session.limit("arm"), { axis: [0, 1, 0], a: [0, 1, 0], min: -180, max: 11, min_written: false, max_written: true });
  assert.deepEqual(l.session.limit("lamp"), { axis: [0, 0, 1], a: [0, 0, 1], min: -30, max: 30, min_written: true, max_written: true });
  assert.deepEqual(l.session.limit("tip"), { axis: [1, 0, 0], a: [1, 0, 0], min: -20, max: 20, min_written: true, max_written: true });
  for (const id of ["post", "flag", "base", "mast", "pole", "nope"]) assert.equal(l.session.limit(id), null, id);
  assert.deepEqual([...l.session.links.limits.keys()], ["arm", "lamp", "tip"]);
  const copy = l.session.limit("arm")!;
  copy.a[0] = 9;
  assert.equal(l.session.limit("arm")!.a[0], 0, "limit() returns a copy");
  // a non-unit axis is normalised, the written one kept
  const l2 = load(patched((o) => { o("arm")["joint_limit"] = { axis: [0, 3, 4], max_deg: 11 }; }));
  assert.deepEqual(l2.session.limit("arm")!.a, [0, 0.6, 0.8]);
  assert.deepEqual(l2.session.limit("arm")!.axis, [0, 3, 4]);
  // the link dropped (unknown, self, cross-group, a cycle) drops the limit; object_links still lists it
  const variants: [string, (o: (id: string) => Record<string, unknown>) => void][] = [
    ["unknown parent", (o) => { o("arm")["parent"] = "nope"; }],
    ["self", (o) => { o("arm")["parent"] = "arm"; }],
    ["cross-group", (o) => { o("arm")["parent"] = "post"; }],
    ["2-cycle", (o) => { o("mast")["parent"] = "arm"; }],
    ["ungrouped", (o) => { delete o("arm")["group"]; }],
  ];
  for (const [what, patch] of variants) {
    const lv = load(patched(patch));
    assert.equal(lv.session.limit("arm"), null, what);
    assert.deepEqual(lv.links.get("arm")?.joint_limit, { axis: [0, 1, 0], max_deg: 11 }, `${what}: still parsed`);
  }
  // a whole-circle range is no limit
  const lc = load(patched((o) => { o("arm")["joint_limit"] = { axis: [0, 1, 0], min_deg: -180, max_deg: 180 }; }));
  assert.equal(lc.session.limit("arm"), null);
  // update_scene after a drag keeps the limits (the same map)
  const page = new Page(load(fixture()));
  const before = page.s.links.limits;
  page.drag("arm", 1, 5);
  assert.equal(page.s.links.limits, before);
  assert.deepEqual(page.s.limit("arm"), { axis: [0, 1, 0], a: [0, 1, 0], min: -180, max: 11, min_written: false, max_written: true });
});

// ------------------------------------------------------------------------------------------------ the measure

test("twist_deg: φ = θ about the axis, 0 about a perpendicular axis, order independent; 180° exact; Shepperd w ≥ 0", () => {
  const r = rng(86);
  for (let k = 0; k < 500; k++) {
    const a = rand_unit(r), th = 359.98 * r() - 179.99;
    close(twist_deg(rodrigues(a, th), a), th, 1e-9, `twist(Rot(a, ${th}))`);
    const b = perp(a, r), sw = 359.98 * r() - 179.99;
    close(twist_deg(rodrigues(b, sw), a), 0, 1e-9, "a swing has no twist");
    const S = rodrigues(b, 170 * r() - 85);
    close(twist_deg(matmul(rodrigues(a, th), S), a), th, 1e-9, "Rot(a, θ)·S");
    close(twist_deg(matmul(S, rodrigues(a, th)), a), th, 1e-9, "S·Rot(a, θ)");
  }
  assert.equal(twist_deg(I3(), [0, 1, 0]), 0);
  assert.ok(!Object.is(twist_deg(I3(), [0, 1, 0]), -0));
  close(twist_deg(rodrigues([0, 1, 0], 180), [0, 1, 0]), 180, 1e-12, "Rot(y, 180)");
  close(Math.abs(twist_deg(rodrigues([0, 1, 0], -180), [0, 1, 0])), 180, 1e-12, "Rot(y, -180) is the same pose");
  assert.equal(twist_deg(rodrigues([0, 1, 0], -180), [0, 1, 0]), twist_deg(rodrigues([0, 1, 0], 180), [0, 1, 0]), "wrapped to (-180, 180]");
  assert.equal(twist_deg([[1, 0, 0], [0, -1, 0], [0, 0, -1]], [0, 1, 0]), 0, "the singular point: 180° about x reads 0");
  for (let k = 0; k < 200; k++) {
    const a = rand_unit(r), th = 360 * r() - 180, R = rodrigues(a, th);
    const [w, x, y, z] = quat_from_matrix(R);
    assert.ok(w >= 0, "w ≥ 0");
    close(Math.hypot(w, x, y, z), 1, 1e-12, "unit");
    // back to the matrix
    const M: Mat3 = [
      [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
      [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
      [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
    ];
    for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) close(M[i]![j]!, R[i]![j]!, 1e-12, `quat round trip [${i}][${j}]`);
  }
  // wrap range of twist
  for (let k = 0; k < 200; k++) {
    const v = twist_deg(rodrigues(rand_unit(r), 720 * r() - 360), rand_unit(r));
    assert.ok(v > -180 && v <= 180, `${v} in (-180, 180]`);
  }
});

test("D = R_Qᵀ·R_P: invariant under group and ancestor turns, 0 when aligned with the parent, the axis read in the parent's frame", () => {
  const page = new Page(load(fixture()));
  assert.equal(page.phi("arm"), 0);
  assert.equal(page.phi("tip"), 0, "tip loads with the pole's rotation: aligned, φ = 0");
  page.drag("arm", 1, 7);
  close(page.phi("arm"), 7, 1e-9, "about y");
  page.drag("arm", 0, 30);
  close(page.phi("arm"), 7, 1e-9, "then about world x (a swing S·Rot(y, 7): the twist is kept)");
  const phi_arm = page.phi("arm");
  // a group turn, an ancestor drag (mast, then base): φ unchanged
  const gp: UnitPose = { transforms: new Map([...page.s.groups.get("g")!].map((id) => [id, page.t(id)])), group: page.s.group_frame("g") };
  page.apply(rotate_group_pose(gp, 2, 40));
  close(page.phi("arm"), phi_arm, 1e-9, "group turn");
  page.drag("mast", 0, 25);
  close(page.phi("arm"), phi_arm, 1e-9, "parent turn");
  page.drag("base", 1, 33);
  close(page.phi("arm"), phi_arm, 1e-9, "grandparent turn");
  // 還原 puts the arm back aligned with the mast: φ = 0 (the load relative rotation, the identity here)
  page.action(page.s.part_restore_pose("arm", page.current)!);
  close(page.phi("arm"), 0, 1e-9, "還原");
  // the parent-local frame: tip under the pole at rz = 50; the limit axis x is the pole's local x
  const p2 = new Page(load(fixture()));
  const Rpole = transform_frame(p2.t("pole"))[0];
  const xw: Vec3 = [Rpole[0][0], Rpole[1][0], Rpole[2][0]];
  close(xw[0], Math.cos(50 * DEG), 1e-12, "pole x");
  const tip_pivot = world_centre(p2.t("tip"), p2.s.pivot_local("tip")!);
  const turned = rotate_by_matrix(p2.t("tip"), tip_pivot, rodrigues(xw, 12));
  close(limit_angle(p2.s.limit("tip")!, turned, p2.t("pole")), 12, 1e-9, "a turn about the pole's own x counts in full");
  // a drag about world x: e′ = R_poleᵀ·x, κ = cos 50° at rest; the angle is the twist of Rot(e′, 12), less than 12
  const e1: Vec3 = [Rpole[0][0], Rpole[0][1], Rpole[0][2]];
  const g0 = drag_gesture(relative_rotation(p2.t("tip"), p2.t("pole")), e1, [1, 0, 0]);
  close(g0.kappa, Math.cos(50 * DEG), 1e-12, "κ at rest is a·e′");
  p2.drag("tip", 0, 12);
  const want = twist_deg(rodrigues(e1, 12), [1, 0, 0]);
  close(p2.phi("tip"), want, 1e-9, "world-x drag");
  assert.ok(want < 12 - 1, `${want} < 12`);
  // the world-x wall: max 20 is reached at t_B ≠ 20
  const tB = clamp_drag_angle(100, g0, p2.s.limit("tip")!);
  close(twist_deg(rodrigues(e1, tB), [1, 0, 0]), 20, 1e-9, "the wall angle");
  assert.ok(tB > 25, `t_B = ${tB}`);
});

// ------------------------------------------------------------------------------------------------ the clamp

test("clamp_drag_angle: closed form against dense sampling (inside kept, monotone, the wall within 1e-9, never early)", () => {
  const r = rng(1086);
  let clamped = 0;
  for (let k = 0; k < 300; k++) {
    const D0 = k % 3 === 0 ? I3() : rodrigues(rand_unit(r), 120 * r() - 60);
    const e = rand_unit(r), a = rand_unit(r);
    const phi0 = twist_deg(D0, a);
    const lo = k % 3 === 1 ? null : Math.max(-180, phi0 - 90 * r());
    const hi = k % 3 === 2 ? null : Math.min(180, phi0 + 90 * r());
    if (lo === null && hi === null) continue;
    const L = lim(a, lo, hi);
    assert.ok(inside(phi0, L), "starts inside");
    const theta = 1400 * r() - 700;
    const g = drag_gesture(D0, e, a);
    const ts = clamp_drag_angle(theta, g, L);
    assert.ok(Math.sign(ts) === Math.sign(theta) || ts === 0, "same direction");
    assert.ok(Math.abs(ts) <= Math.abs(theta), "never longer");
    const phi_at = (t: number) => twist_deg(matmul(rodrigues(e, t), D0), a);
    let prev = phi_at(0), dir = 0;
    for (let i = 1; i <= 1200; i++) {
      const p = phi_at((ts * i) / 1200);
      assert.ok(inside(p, L), `case ${k}: φ(${(ts * i) / 1200}) = ${p} inside [${L.min}, ${L.max}]`);
      const d = wrap_angle(p - prev);
      if (Math.abs(d) > 1e-12) {
        const sgn = Math.sign(d);
        assert.ok(dir === 0 || sgn === dir, `case ${k}: monotone`);
        dir = sgn;
      }
      prev = p;
      close(wrap_angle(gesture_angle(g, (ts * i) / 1200) - p), 0, 1e-9, "the half-angle form equals the matrix twist (mod 360)");
    }
    if (Math.abs(ts) < Math.abs(theta)) {
      clamped += 1;
      const pe = phi_at(ts);
      assert.ok(Math.min(Math.abs(wrap_angle(pe - L.max)), Math.abs(wrap_angle(pe - L.min))) < 1e-9, `case ${k}: at a wall (${pe})`);
      assert.ok(!inside(phi_at(ts + Math.sign(theta) * 1e-3), L), `case ${k}: the first wall (a little further is outside)`);
    }
  }
  assert.ok(clamped > 100, `${clamped} clamped`);
  // κ = 0 and θ = 0
  const L = lim([0, 1, 0], null, 11);
  const gk = drag_gesture(I3(), [1, 0, 0], [0, 1, 0]);
  assert.ok(Math.abs(gk.kappa) <= KAPPA_EPS);
  assert.equal(clamp_drag_angle(200, gk, L), 200, "κ = 0: free");
  assert.equal(clamp_drag_angle(0, drag_gesture(I3(), [0, 1, 0], [0, 1, 0]), L), 0);
  // the pinned cases of design §3.2 (arm-like, from rest unless said)
  const cy = drag_clamp(I3(), [0, 1, 0], L);
  close(cy(15), 11, 1e-12, "+15 → 11");
  close(cy(-200), -180, 1e-9, "−200 → −180 (min absent)");
  close(drag_clamp(I3(), [0, -1, 0], lim([0, -1, 0], null, 11))(15), 11, 1e-12, "the mirrored axis");
  close(drag_clamp(I3(), [0, 1, 0], lim([0, -1, 0], null, 11))(-15), -11, 1e-12, "arm_r about world −y");
  close(drag_clamp(rodrigues([1, 0, 0], -90), [0, 1, 0], L)(30), 11, 1e-9, "forward then y: still the twist about parent y");
  const out = drag_clamp(rodrigues([0, 1, 0], 30), [0, 1, 0], L);
  assert.equal(out(5), 0, "outside: further out moves nothing");
  assert.equal(out(-50), -50, "outside: back is free");
  const wall = drag_clamp(rodrigues([0, 1, 0], 11 + 1e-13), [0, 1, 0], L);
  assert.equal(wall(1), 0, "at the wall: +1 → 0");
  assert.equal(wall(-1), -1, "at the wall: −1 free (no sticking)");
  assert.equal(LIMIT_EPS_DEG, 1e-9);
});

test("the ±180 wall (review R1): a second outward drag past −180 is blocked, inward is free; the state reads at_min −180", () => {
  const L = lim([0, 1, 0], null, 11);
  // the pure clamp at the stored pose φ₀ = +180 (≡ −180)
  const D180 = rodrigues([0, 1, 0], 180);
  close(twist_deg(D180, [0, 1, 0]), 180, 1e-12, "stored as +180");
  assert.equal(canonical_angle(180, L), -180);
  assert.equal(canonical_angle(180, lim([0, 1, 0], -179, 11)), 180, "only when min = −180");
  assert.equal(limit_state(180, L), "at_min");
  assert.ok(inside(180, L) && !inside(180, lim([0, 1, 0], -179, 11)));
  assert.equal(drag_clamp(D180, [0, 1, 0], L)(-30), 0);
  assert.equal(drag_clamp(D180, [0, 1, 0], L)(-190), 0);
  assert.equal(drag_clamp(D180, [0, 1, 0], L)(30), 30);
  // on the page: the real storage path through rotate_about_point and transform_frame
  const page = new Page(load(fixture()));
  const r1 = page.drag("arm", 1, -200);
  assert.ok(r1.changed);
  close(Math.abs(page.phi("arm")), 180, 1e-9, "stopped straight up");
  assert.equal(page.state("arm"), "at_min");
  assert.equal(page.s.part_limit_angle("arm", page.current)!.inside, true);
  const snap = page.snapshot(), u = page.s.undo.size;
  const r2 = page.drag("arm", 1, -30);
  assert.ok(!r2.changed && page.s.undo.size === u, "drag −200 then −30: θ* = 0, no step");
  assert.deepEqual(page.snapshot(), snap, "bit for bit");
  page.drag("arm", 1, -190);
  assert.deepEqual(page.snapshot(), snap, "drag −190: still nothing (never the long way round)");
  const r3 = page.drag("arm", 1, 30);
  assert.ok(r3.changed && page.s.undo.size === u + 1, "drag +30 is free");
  close(page.phi("arm"), -150, 1e-9, "−180 + 30");
});

test("UnitDrag: without a clamp the D85 path bit for bit; a clamped 0 gives pose0 itself on a non-trivial pose (review R2)", () => {
  const l = load(fixture());
  const s = l.session;
  const cur = (id: string) => clone_transform(l.scene.objects.find((o) => o.id === id)!.transform);
  const fx = { apply: () => true, proxy: () => {}, restore: () => {} };
  for (const id of ["arm", "lamp", "base"]) {
    const pose0 = s.part_pose(id, cur)!;
    const c_locals = new Map([...pose0.transforms.keys()].map((k) => [k, s.local_centres.get(k)!]));
    const pivot = s.part_pivot(id, pose0.transforms.get(id)!);
    const a = new UnitDrag<null, null>(fx), b = new UnitDrag<null, null>(fx);
    a.begin(pose0, null, null, 1, { axis: 1, c_locals, pivot });
    b.begin(pose0, null, null, 1, { axis: 1, c_locals, pivot, clamp: null });
    const want = rotate_unit(pose0, 1, 40, c_locals, pivot);
    assert.ok(same_pose(a.move(40)!, want) && same_pose(b.move(40)!, want), `${id}: no clamp, the D85 pose`);
    const c = new UnitDrag<null, null>(fx);
    c.begin(pose0, null, null, 1, { axis: 1, c_locals, pivot, clamp: (t) => Math.min(t, 11) });
    assert.ok(same_pose(c.move(40)!, rotate_unit(pose0, 1, 11, c_locals, pivot)), `${id}: the clamped angle`);
    c.move(5);
    assert.ok(c.end()!.changed);
  }
  // rotate_unit by 0 is not always the identity to the last bit on a non-trivial pose (the reason for R2) ...
  const r = rng(2086);
  let drift = 0, tried = 0;
  for (let k = 0; k < 400 && drift < 20; k++) {
    tried += 1;
    const t: Transform = { position: [4 * r() - 2, 4 * r() - 2, 2 * r()], rotation_deg: [340 * r() - 170, 170 * r() - 85, 340 * r() - 170] };
    const pose0 = single_pose("x", t), c_locals = new Map([["x", [0.1, -0.2, 0.3] as Vec3]]);
    const axis = (k % 2) as Axis;
    if (!same_pose(rotate_unit(pose0, axis, 0, c_locals, null), pose0)) {
      drift += 1;
      // ... so a clamp returning 0 must give pose0 itself: no stage A, end() unchanged
      let applies = 0;
      const d = new UnitDrag<null, null>({ apply: () => { applies += 1; return true; }, proxy: () => {}, restore: () => {} });
      d.begin(pose0, null, null, 1, { axis, c_locals, clamp: () => 0 });
      assert.ok(same_pose(d.move(3)!, pose0), "the pending candidate is pose0");
      assert.equal(d.frame(), false);
      const res = d.end()!;
      assert.ok(!res.changed && res.ok && same_pose(res.pose, pose0) && applies === 0, "no step, no stage A");
      // inside first, then back to a blocked 0: pose0 applied again, end() still unchanged
      const d2 = new UnitDrag<null, null>({ apply: () => true, proxy: () => {}, restore: () => {} });
      d2.begin(pose0, null, null, 1, { axis, c_locals, clamp: (th) => (th > 0 ? 0 : th) });
      d2.move(-5);
      assert.ok(d2.frame());
      d2.move(4);
      d2.frame();
      assert.equal(d2.end()!.changed, false);
    }
  }
  assert.ok(drift > 0, `rotate_unit by 0 changed ${drift} of ${tried} poses`);
  // on the page: the arm at the wall from a non-trivial pose; a further outward drag leaves every transform bit for bit
  const page = new Page(load(fixture()));
  page.drag("arm", 0, 37.3);
  page.drag("arm", 2, -14.3);
  page.drag("arm", 1, 40);
  close(page.phi("arm"), 11, 1e-9, "at the wall");
  const snap = page.snapshot(), u = page.s.undo.size, applies = page.applies;
  for (const deg of [5, 0.001, 90, 200]) {
    const res = page.drag("arm", 1, deg, [deg / 3, deg / 2]);
    assert.ok(!res.changed, `+${deg}: no change`);
  }
  assert.deepEqual(page.snapshot(), snap, "bit for bit");
  assert.equal(page.s.undo.size, u, "no step");
  assert.equal(page.applies, applies, "no stage A");
});

test("page drags: clamped to the bound with one step, no step at the wall, back free, snap then clamp; a D84-path part; undo", () => {
  const page = new Page(load(fixture()));
  const s0 = page.snapshot(), u0 = page.s.undo.size, mast0 = page.t("mast");
  const rel = (q: Transform, d: Transform) => {
    const [Rq, pq] = transform_frame(q), [Rd, pd] = transform_frame(d);
    return [0, 1, 2].flatMap((i) => [0, 1, 2].map((j) => Rq[0][i] * Rd[0][j] + Rq[1][i] * Rd[1][j] + Rq[2][i] * Rd[2][j]))
      .concat([0, 1, 2].map((i) => Rq[0][i] * (pd[0] - pq[0]) + Rq[1][i] * (pd[1] - pq[1]) + Rq[2][i] * (pd[2] - pq[2])));
  };
  const af0 = rel(page.t("arm"), page.t("flag"));
  const r = page.drag("arm", 1, 15);
  close(page.phi("arm"), 11, 1e-9, "+15 → 11");
  assert.equal(page.state("arm"), "at_max");
  assert.ok(r.changed && page.s.undo.size === u0 + 1 && page.s.peek_undo()!.kind === "objects", "one objects step (arm + flag)");
  rel(page.t("arm"), page.t("flag")).forEach((x, i) => close(x, af0[i]!, 1e-9, "the flag carried"));
  const jw = world_centre(page.t("arm"), [-0.3, 0, 0]), top = world_centre(page.t("mast"), [0, 0, 1]);
  for (let i = 0; i < 3; i++) close(jw[i]!, top[i]!, 1e-9, "the joint on the mast");
  assert.ok(same_transform(page.t("mast"), mast0), "the parent untouched");
  const s1 = page.snapshot();
  assert.ok(!page.drag("arm", 1, 5).changed && page.s.undo.size === u0 + 1, "at the wall: +5 → no step");
  assert.deepEqual(page.snapshot(), s1, "bit for bit");
  page.drag("arm", 1, -20);
  close(page.phi("arm"), -9, 1e-9, "back free: 11 − 20");
  assert.equal(page.state("arm"), "inside");
  // snap before the clamp: 13° snaps to 15, clamped to 11 (the wall wins, never re-snapped to 0 or 15)
  const p2 = new Page(load(fixture()));
  p2.drag("arm", 1, snap_angle(13, true));
  close(p2.phi("arm"), 11, 1e-9, "snap 13 → 15, clamp → 11");
  // lamp: a part with a parent and no joint (the M11 c_w pivot), about z (rz exact)
  const rz0 = p2.t("lamp").rotation_deg[2];
  p2.drag("lamp", 2, 45);
  close(p2.phi("lamp"), 30, 1e-9, "lamp +45 → 30");
  assert.equal(p2.state("lamp"), "at_max");
  close(p2.t("lamp").rotation_deg[2], wrap_angle(rz0 + 30), 1e-9, "rz exact");
  p2.drag("lamp", 2, -80);
  close(p2.phi("lamp"), -30, 1e-9, "lamp −80 → −30");
  assert.equal(p2.state("lamp"), "at_min");
  // undo of each step restores bit for bit; the group frame untouched
  const G0 = p2.s.group_frame("g");
  for (let k = 0; k < 3; k++) p2.undo();
  assert.deepEqual(p2.snapshot(), s0);
  assert.deepEqual(p2.s.group_frame("g"), G0);
  for (let k = 0; k < 2; k++) page.undo();
  assert.deepEqual(page.snapshot(), s0, "the first page back too");
});

test("套用: accepted at the bound (verbatim), refused beyond it (no action), the Euler wrap, below the minimum", () => {
  const page = new Page(load(fixture()));
  const s0 = page.snapshot(), u0 = page.s.undo.size, ap0 = page.applies;
  const refused = (r: ReturnType<Page["set_rotation"]>) => r.refused && !r.ok;
  const a1 = page.set_rotation("arm", [0, 11 + 1e-7, 0]);
  assert.ok(refused(a1), "11 + 1e-7 refused");
  close(a1.phi!, 11.0000001, 1e-12, "the target angle");
  assert.deepEqual(page.snapshot(), s0, "a refusal changes nothing");
  assert.ok(page.s.undo.size === u0 && page.applies === ap0, "no step, no stage A");
  assert.ok(refused(page.set_rotation("arm", [0, -185, 0])), "−185: the Euler wraps to 175, above");
  const ok = page.set_rotation("arm", [0, 11, 0]);
  assert.ok(ok.ok && page.s.undo.size === u0 + 1, "exactly at the bound: accepted, one step");
  assert.deepEqual(page.t("arm").rotation_deg, [0, 11, 0], "written verbatim");
  assert.equal(page.state("arm"), "at_max");
  assert.ok(page.set_rotation("arm", [0, -170, 0]).ok, "−170: min absent (−180)");
  assert.ok(page.set_rotation("lamp", [0, 0, 30]).ok);
  assert.ok(refused(page.set_rotation("lamp", [0, 0, 30.5])), "lamp 30.5 refused");
  const b = page.set_rotation("lamp", [0, 0, -31]);
  assert.ok(refused(b) && limit_state(b.phi!, page.s.limit("lamp")!) === "below", "lamp −31: below");
  // a swing about an axis ⟂ the limit axis is free (φ unchanged)
  assert.ok(page.set_rotation("lamp", [40, 0, 30]).ok, "rx 40 with rz 30: still at the bound");
  // parts without a limit are never checked
  assert.ok(page.set_rotation("post", [0, 0, 170]).ok && page.set_rotation("flag", [0, 90, 0]).ok);
});

test("loaded outside the range (review R3): reported, outward drags move nothing, inward free, 套用 refused until inside; 還原 unchecked", () => {
  // the arm loaded at 30° about the parent's y with max 11: above
  const page = new Page(load(patched((o) => { (o("arm")["transform"] as Record<string, unknown>)["rotation_deg"] = [0, 30, 0]; })));
  close(page.phi("arm"), 30, 1e-9, "the loaded angle");
  assert.equal(page.state("arm"), "above");
  assert.ok(!page.s.part_limit_angle("arm", page.current)!.inside);
  const s0 = page.snapshot(), u0 = page.s.undo.size;
  assert.ok(!page.drag("arm", 1, 5).changed, "further out: nothing");
  assert.deepEqual(page.snapshot(), s0, "bit for bit");
  assert.ok(page.set_rotation("arm", [0, 20, 0]).refused, "套用 to a pose still outside: refused");
  assert.equal(page.s.undo.size, u0);
  page.drag("arm", 1, -10);
  close(page.phi("arm"), 20, 1e-9, "inward is free");
  page.drag("arm", 1, -40);
  close(page.phi("arm"), -20, 1e-9, "and may cross the bound into the range");
  assert.ok(page.set_rotation("arm", [0, 5, 0]).ok, "inside: accepted");
  // 還原此物體 is never checked: back to the load pose relative to the mast, outside again
  page.action(page.s.part_restore_pose("arm", page.current)!);
  close(page.phi("arm"), 30, 1e-9, "還原 → the loaded 30°");
  assert.equal(page.state("arm"), "above");
  // a range that excludes 0 at an aligned load: below
  const p2 = new Page(load(patched((o) => { o("arm")["joint_limit"] = { axis: [0, 1, 0], min_deg: 20, max_deg: 30 }; })));
  assert.equal(p2.state("arm"), "below");
  const s2 = p2.snapshot();
  assert.ok(!p2.drag("arm", 1, -5).changed);
  assert.deepEqual(p2.snapshot(), s2);
  p2.drag("arm", 1, 50);
  close(p2.phi("arm"), 30, 1e-9, "inward crosses min and stops at max");
  assert.ok(p2.set_rotation("arm", [0, 10, 0]).refused && p2.set_rotation("arm", [0, 25, 0]).ok);
});

test("Download scene + reload keeps the angle (review R3): the arm saved at 11° reloads at_max and cannot be pushed further", () => {
  const page = new Page(load(fixture()));
  page.drag("arm", 1, 15);
  close(page.phi("arm"), 11, 1e-9, "at the bound");
  const l = page.l, cam = l.session.block() as Parameters<typeof scene_blob>[1];
  const text = scene_blob(page.scene, cam, "basic_limited", undefined, undefined, display_colours(l.data), l.groups, l.links).text;
  const p2 = new Page(load(JSON.parse(text) as Raw));
  close(p2.phi("arm"), 11, 1e-9, "the reload keeps the angle (no stacking)");
  assert.equal(p2.state("arm"), "at_max");
  const s = p2.snapshot();
  assert.ok(!p2.drag("arm", 1, 11).changed, "a further outward drag after the reload: nothing");
  assert.deepEqual(p2.snapshot(), s);
  assert.ok(p2.set_rotation("arm", [0, 12, 0]).refused);
});

// ------------------------------------------------------------------------------------------------ strings, download

test("strings: the panel line (range forms, states), the refusal (R7 decimals), the number formats (hyphen-minus)", () => {
  const arm = lim([0, 1, 0], null, 11), lamp = lim([0, 0, 1], -30, 30), low = lim([1, 0, 0], -30, null);
  assert.equal(range_text(arm), "≤ 11.0°");
  assert.equal(range_text(lamp), "-30.0°～30.0°");
  assert.equal(range_text(low), "≥ -30.0°");
  assert.equal(limit_text(arm, 8.3, "blouse"), "關節限制：繞 blouse 的 (0, 1, 0) 軸 ≤ 11.0°，目前 8.3°");
  assert.equal(limit_text(arm, 11 - 1e-12, "mast"), "關節限制：繞 mast 的 (0, 1, 0) 軸 ≤ 11.0°，目前 11.0°（已達上限）");
  assert.equal(limit_text(arm, 180, "mast"), "關節限制：繞 mast 的 (0, 1, 0) 軸 ≤ 11.0°，目前 -180.0°（已達下限）");
  assert.equal(limit_text(lamp, 0, "mast"), "關節限制：繞 mast 的 (0, 0, 1) 軸 -30.0°～30.0°，目前 0.0°");
  assert.equal(limit_text(lamp, -0.04, "mast"), "關節限制：繞 mast 的 (0, 0, 1) 軸 -30.0°～30.0°，目前 0.0°");
  assert.equal(limit_text(arm, 30, "mast"), "關節限制：繞 mast 的 (0, 1, 0) 軸 ≤ 11.0°，目前 30.0°（超出上限，只能往回轉）");
  assert.equal(limit_text(lim([0, 1, 0], 20, 30), 0, "mast"), "關節限制：繞 mast 的 (0, 1, 0) 軸 20.0°～30.0°，目前 0.0°（超出下限，只能往回轉）");
  assert.equal(refusal_text(arm, 37, "blouse"), "套用被拒：繞 blouse 的 (0, 1, 0) 軸會轉到 37.0°，超出上限 11.0°");
  assert.equal(refusal_text(lim([0, 0, 1], -30, 30), -45, "mast"), "套用被拒：繞 mast 的 (0, 0, 1) 軸會轉到 -45.0°，低於下限 -30.0°");
  assert.equal(refusal_text(arm, 11.03, "blouse"), "套用被拒：繞 blouse 的 (0, 1, 0) 軸會轉到 11.030°，超出上限 11.000°", "R7");
  assert.equal(refusal_text(arm, 11.0000001, "blouse"), "套用被拒：繞 blouse 的 (0, 1, 0) 軸會轉到 11.000000100°，超出上限 11.000000000°");
  assert.equal(refusal_text(arm, 5, "blouse"), "", "inside: no refusal");
  assert.equal(format_deg1(-180), "-180.0", "no wrap");
  assert.equal(format_deg1(-0.04), "0.0");
  assert.equal(format_deg1(-0), "0.0");
  assert.equal(format_axis([0, 1, 0]), "(0, 1, 0)");
  assert.equal(format_axis([0.12345, -1, 0.5]), "(0.123, -1, 0.5)");
  assert.equal(format_axis([-0, 0, 1]), "(0, 0, 1)");
  assert.equal(format_axis_component(-0.0001), "0");
  assert.equal(format_axis_component(10), "10");
  assert.equal(format_axis_component(2.5), "2.5");
});

test("download round trip: joint_limit written back as parsed (also a dropped one), not a malformed one; the reload resolves the same", () => {
  const page = new Page(load(fixture()));
  const l = page.l;
  page.drag("arm", 1, 6);
  page.drag("lamp", 2, -12);
  const cam = l.session.block() as Parameters<typeof scene_blob>[1];
  const text = scene_blob(page.scene, cam, "basic_limited", undefined, undefined, display_colours(l.data), l.groups, l.links).text;
  const parsed = JSON.parse(text) as Raw;
  const want: Record<string, unknown> = {
    arm: { axis: [0, 1, 0], max_deg: 11 }, lamp: { axis: [0, 0, 1], max_deg: 30, min_deg: -30 }, post: { axis: [1, 0, 0], max_deg: 20 },
    tip: { axis: [1, 0, 0], max_deg: 20, min_deg: -20 },
  };
  for (const o of parsed.objects) assert.deepEqual(o[LIMIT_KEY], want[o["id"] as string], `${o["id"]}`);
  assert.match(text, /"joint_limit": \{\n {4}"axis": \[\n {5}0\.0,\n {5}1\.0,\n {5}0\.0\n {4}\],\n {4}"max_deg": 11\.0\n {3}\}/, "Python-repr doubles, sorted keys");
  assert.deepEqual(object_links(parsed), l.links);
  assert.deepEqual(load_scene_text(text).objects, page.scene.objects, "the core ignores the key");
  const l2 = load(parsed);
  assert.deepEqual(l2.session.links, l.session.links, "the same forest and limits");
  close(l2.session.part_limit_angle("arm", (id) => clone_transform(l2.scene.objects.find((o) => o.id === id)!.transform))!.phi, 6, 1e-9, "arm");
  assert.deepEqual(limit_for_file({ axis: [1, 2, 3], min_deg: -1 }), { axis: [1, 2, 3], min_deg: -1 });
  // without limits the text is D85's
  const plain = load(JSON.parse(readFileSync(resolve(ROOT, "web", "test", "fixtures", "basic_linked.json"), "utf-8")) as Raw);
  const t2 = scene_blob(plain.scene, plain.session.block() as Parameters<typeof scene_blob>[1], "basic_linked", undefined, undefined,
    display_colours(plain.data), plain.groups, plain.links).text;
  assert.doesNotMatch(t2, /"joint_limit"/);
  // a matrix-only sanity: the rotation the reload sees equals the saved Euler
  const R = euler_zyx_matrix(page.t("arm").rotation_deg);
  const R2 = transform_frame(l2.scene.objects.find((o) => o.id === "arm")!.transform)[0];
  for (let i = 0; i < 3; i++) for (let j = 0; j < 3; j++) close(R[i]![j]!, R2[i]![j]!, 0, "same doubles");
});

/** The Miki model's D86 arm limit on the real web code (model branch only): `examples/miki.json` writes `joint_limit`
 * on `arm_l` (axis +y) and `arm_r` (axis −y), `max_deg` 11 (tools/miki_model/assemble.py `ARM_INWARD_MAX_DEG`); both
 * arms hang from the blouse and every transform loads as the identity, so both read φ = 0 at load. A ring drag about
 * world y inward (`arm_l` +, `arm_r` −: tools/miki_model/poses.py) stops at exactly 11°, outward is free, 套用 is
 * refused beyond 11°, and after a bow the limit still reads the arm against the bowed blouse. The page helper is the
 * load / drag / 套用 path of `limits.test.ts` (`main.ts::load`, `start_unit_drag` with the clamp, `UnitDrag`,
 * `apply_object_rotation`), cut down to what these tests use. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { load_scene, shadow_geometry } from "castplane";
import type { Scene, StageA, Transform, Vec3 } from "castplane";

import { group_members, object_groups } from "../src/groups.js";
import { object_links } from "../src/links.js";
import { scene_centre } from "../src/observer.js";
import { UnitDrag, clone_transform, same_pose } from "../src/object_rotate.js";
import type { Axis, UnitDragResult, UnitPose } from "../src/object_rotate.js";
import { PlaneSession, object_centres } from "../src/plane.js";

// web/build/test/miki_limit.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
type Raw = Record<string, unknown> & { objects: Record<string, unknown>[] };
const raw = (): Raw => JSON.parse(readFileSync(resolve(ROOT, "examples", "miki.json"), "utf-8"));

function close(a: number, b: number, tol: number, what: string): void {
  assert.ok(Math.abs(a - b) <= tol, `${what}: ${a} vs ${b} (tolerance ${tol})`);
}

/** The page's object state as `main.ts` keeps it, with the D86 clamp on ring drags and the 套用 refusal. */
class Page {
  scene: Scene;
  A: StageA;
  readonly s: PlaneSession;
  private seq = 0;

  constructor(readonly data: Raw) {
    this.scene = load_scene(data);
    this.A = shadow_geometry(this.scene);
    const members = group_members(object_groups(data), this.scene.objects.map((o) => o.id));
    const recs = new Map(this.A.objects.map((o) => [o.id, o]));
    this.s = new PlaneSession({ camera: this.scene.camera, canvas_mm: this.scene.output.canvas_mm,
      centre: scene_centre(this.A), object_centres: object_centres(this.A.objects), vertices: this.A.vertices,
      object_poses: this.scene.objects.map((o) => ({ id: o.id, transform: o.transform, vertices: recs.get(o.id)!.mesh.vertices })),
      groups: members, links: object_links(data) });
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

  apply(pose: UnitPose): void {
    this.scene = { ...this.scene, objects: this.scene.objects.map((o) => {
      const t = pose.transforms.get(o.id);
      return t === undefined ? o : { ...o, transform: clone_transform(t) };
    }) };
    this.A = shadow_geometry(this.scene);
    this.s.update_scene(this.A.objects, this.A);
  }

  /** A ring drag of part `id` about world `axis` by `deg` through one intermediate angle. */
  drag(id: string, axis: Axis, deg: number): UnitDragResult {
    const s = this.s;
    const pose0 = s.part_pose(id, this.current)!;
    const c_locals = new Map<string, Vec3>([...pose0.transforms.keys()].map((k) => [k, s.local_centres.get(k)!]));
    const t0 = pose0.transforms.get(id)!;
    const pivot = s.part_pivot(id, t0), clamp = s.part_drag_clamp(id, axis, t0, this.current);
    const d = new UnitDrag<Scene, StageA>({
      apply: (p) => { this.apply(p); return true; },
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
    if (one) s.begin_object(id, t0);
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

  /** 套用 of `r` on part `id`: refused (nothing applied) when the target is outside the limit. */
  set_rotation(id: string, r: readonly number[]): { ok: boolean; phi: number | null } {
    const after = this.s.part_numeric_pose(id, r, this.current)!;
    const chk = this.s.part_limit_check(id, after, this.current), now = this.s.part_pose(id, this.current)!;
    if (chk !== null && !chk.inside && !same_pose(now, after)) return { ok: false, phi: chk.phi };
    this.apply(after);
    return { ok: true, phi: chk?.phi ?? null };
  }

  snapshot(): Transform[] {
    return this.scene.objects.map((o) => clone_transform(o.transform));
  }
}

const page = new Page(raw());

test("miki: both arms carry the inward limit (axis ±y in the blouse's frame, max 11), load at φ = 0", () => {
  const data = raw();
  for (const [id, y] of [["arm_l", 1], ["arm_r", -1]] as const) {
    const o = data.objects.find((x) => x["id"] === id)!;
    assert.deepEqual(o["joint_limit"], { axis: [0, y, 0], max_deg: 11 }, id);
    assert.equal(o["parent"], "blouse", id);
    const l = page.s.limit(id)!;
    assert.deepEqual([l.a, l.min, l.max, l.min_written, l.max_written], [[0, y, 0], -180, 11, false, true], id);
    assert.equal(page.phi(id), 0, id);
    assert.equal(page.state(id), "inside", id);
  }
  assert.ok(data.objects.every((o) => o["transform"] === undefined), "no transform key: every object loads as the identity");
  for (const id of ["arm_l", "arm_r", "blouse"]) {
    assert.deepEqual([page.t(id).position, page.t(id).rotation_deg], [[0, 0, 0], [0, 0, 0]], id);
  }
  const limited = data.objects.filter((o) => page.s.limit(o["id"] as string) !== null).map((o) => o["id"]);
  assert.deepEqual(limited, ["arm_l", "arm_r"]);
});

test("miki: a ring drag inward about world y stops at exactly 11° (arm_l +y, arm_r −y); outward is free", () => {
  for (const [id, inward] of [["arm_l", 1], ["arm_r", -1]] as const) {
    const p = new Page(raw());
    const r = p.drag(id, 1, inward * 15);
    assert.ok(r.ok && r.changed, `${id}: the drag moved`);
    close(p.phi(id), 11, 1e-9, `${id} inward 15 → 11`);
    assert.equal(p.state(id), "at_max", id);
    close(p.t(id).rotation_deg[1], inward * 11, 1e-9, `${id}: ry (the blouse is the identity)`);
    const s1 = p.snapshot();
    assert.ok(!p.drag(id, 1, inward * 5).changed, `${id}: at the wall a further inward drag moves nothing`);
    assert.deepEqual(p.snapshot(), s1, `${id}: bit for bit`);
    p.drag(id, 1, -inward * 30);
    close(p.phi(id), -19, 1e-9, `${id}: back out by 30 is free`);
    assert.equal(p.state(id), "inside", id);
    p.drag(id, 1, -inward * 60);
    close(p.phi(id), -79, 1e-9, `${id}: further outward (raised sideways) is not limited`);
  }
});

test("miki: 套用 accepts 11° inward and refuses 11.5°; outward angles are accepted", () => {
  for (const [id, inward] of [["arm_l", 1], ["arm_r", -1]] as const) {
    const p = new Page(raw());
    const s0 = p.snapshot();
    const no = p.set_rotation(id, [0, inward * 11.5, 0]);
    assert.ok(!no.ok, `${id}: 11.5 refused`);
    close(no.phi!, 11.5, 1e-9, id);
    assert.deepEqual(p.snapshot(), s0, `${id}: a refusal changes nothing`);
    assert.ok(p.set_rotation(id, [0, inward * 11, 0]).ok, `${id}: 11 accepted`);
    assert.equal(p.state(id), "at_max", id);
    assert.ok(p.set_rotation(id, [0, -inward * 60, 0]).ok, `${id}: 60 outward accepted`);
    close(p.phi(id), -60, 1e-9, id);
  }
});

test("miki: after a bow the limit reads the arm against the bowed blouse (the stop is relative, not world ry)", () => {
  const p = new Page(raw());
  assert.equal(p.s.limit("blouse"), null, "the blouse has no limit");
  p.drag("blouse", 0, 10);
  close(p.phi("arm_l"), 0, 1e-9, "carried by the blouse: still 0");
  p.drag("arm_l", 1, 15);
  close(p.phi("arm_l"), 11, 1e-9, "stopped at 11 relative to the blouse");
  assert.equal(p.state("arm_l"), "at_max");
});

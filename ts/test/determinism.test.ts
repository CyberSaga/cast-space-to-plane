/**
 * Determinism and camera independence (contract §5.4.4 (8), §5.4.7, §5.4.13): every example rendered twice from fresh
 * objects gives identical `dumps` / `write_svg` strings; the camera-free blocks are byte-identical for two cameras;
 * stage A never reads `scene.camera`; `project_scene` + `compose` never mutate a deep-frozen `A`.
 */

import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { test } from "node:test";

import { dumps } from "../src/output/geometry_json.js";
import { write_svg } from "../src/output/svg.js";
import { compose, construction_block, project_scene, render, shadow_geometry } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import type { Scene } from "../src/scene.js";
import { camera_override, deep_freeze, read_example, read_json, repo_path } from "./helpers.js";

const EXAMPLES = repo_path("examples");
const examples = readdirSync(EXAMPLES).filter((f) => f.endsWith(".json")).sort();
/** Examples whose geometry belongs to a phase-2 part that has not landed yet (contract §5.4.0): run as node:test
 * `todo`; each part shrinks this list and the final part leaves it empty. */
const TODO_EXAMPLES: ReadonlySet<string> = new Set<string>([]);
const todo = (file: string): { todo: string | false } => ({ todo: TODO_EXAMPLES.has(file) ? "phase 2 part not yet landed" : false });

const CAMERA_CODES = new Set([
  "CAMERA_LOOKING_ALONG_UP", "LIGHT_BEHIND_CAMERA", "LIGHT_POINT_AT_INFINITY", "SHADOW_VP_AT_INFINITY", "POINT_BEHIND_CAMERA",
  "CONSTRUCTION_CHECK_SKIPPED",
]);
const OG = /\.og\d+\.(base|top)$/;

function pick(o: any, keys: string[]): any {
  const out: any = {};
  for (const k of keys) out[k] = o[k];
  return out;
}

/** The camera-free blocks of a document (contract §5.4.7 / §5.0.3, see the implementation notes of §5.4 for
 * the shadow conic entries: `conic` is the image of the ground conic under `P M E` and is left out; `kind` and `arc`
 * are camera dependent only in principle and are equal for the five examples and the test camera). */
function camera_free(doc: any, rays = true): string {
  const points: any = {};
  for (const name of Object.keys(doc.points)) {
    if (OG.test(name)) continue;
    points[name] = pick(doc.points[name], ["world", "direction", "at_infinity"].filter((k) => k in doc.points[name]));
  }
  return dumps({
    hidden_lines: doc.hidden_lines,
    receivers: doc.receivers,
    points,
    edges: doc.edges.map((e: any) => pick(e, ["object", "from", "to", "silhouette"])),
    shadows: doc.shadows.map((s: any) => ({
      ...pick(s, ["light", "receiver", "object", "outline", "loops", "unbounded"]),
      conics: s.conics.map((c: any) => pick(c, ["kind", "arc", "circle", "map", "which"])),
    })),
    form_shadow: doc.form_shadow.map((f: any) => ({
      ...pick(f, ["object", "faces"]),
      terminator: f.terminator.filter((t: any) => "segment" in t).map((t: any) => t.segment),
    })),
    outlines: doc.outlines.map((o: any) => o.object),
    // rays are camera-free only without POINT_BEHIND_CAMERA: the nu >= 0 row filter of §2.7 / §5.1.5 is a camera
    // predicate (§5.4 implementation notes, qualifying the §5.0.3 list)
    rays: rays ? doc.construction.rays : null,
    per_receiver_rays: rays
      ? Object.keys(doc.construction.per_receiver).sort().map((r) => [r, doc.construction.per_receiver[r].rays]) : null,
    warnings: doc.warnings.filter((w: any) => !CAMERA_CODES.has(w.code)).map((w: any) => [w.code, w.ids]),
  });
}

const rays_camera_free = (...docs: any[]): boolean =>
  !docs.some((d) => d.warnings.some((w: any) => w.code === "POINT_BEHIND_CAMERA"));

test("rays are camera-dependent when a point is behind the camera (§5.1.5 nu >= 0 rule; part 1 review)", () => {
  const scene = load_scene(read_json(repo_path("tests", "conformance", "cases", "receiver_unlit_wall.json")));
  const d1 = render(scene).geometry as any;
  const d2 = render(scene, camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5], 3)).geometry as any;
  assert.ok(!rays_camera_free(d1, d2));
  assert.equal(d1.construction.rays.length, 16); // the Python reference gives 16 / 20 as well
  assert.equal(d2.construction.rays.length, 20);
  assert.equal(camera_free(d1, false), camera_free(d2, false));
});

for (const file of examples) {
  test(`deterministic render: ${file}`, todo(file), () => {
    const a = render(load_scene(read_example(file)));
    const b = render(load_scene(read_example(file)));
    assert.equal(dumps(a.geometry), dumps(b.geometry));
    assert.equal(a.svg, b.svg);
    assert.equal(write_svg(a.geometry), write_svg(b.geometry));
  });

  test(`camera-free blocks are identical for two cameras: ${file}`, todo(file), () => {
    const scene = load_scene(read_example(file));
    const other = camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5], 3);
    const d1 = render(scene).geometry as any;
    const d2 = render(scene, other).geometry as any;
    const k1 = Object.keys(d1.points).filter((n) => !OG.test(n)).sort();
    const k2 = Object.keys(d2.points).filter((n) => !OG.test(n)).sort();
    assert.deepEqual(k1, k2);
    assert.equal(camera_free(d1, rays_camera_free(d1, d2)), camera_free(d2, rays_camera_free(d1, d2)));
    assert.notEqual(dumps(d1.camera), dumps(d2.camera));
  });

  test(`stage A never reads scene.camera and A is never mutated: ${file}`, todo(file), () => {
    const scene = load_scene(read_example(file));
    const trap = new Proxy({}, { get() { throw new Error("stage A read scene.camera"); } });
    const A_free = shadow_geometry({ ...scene, camera: trap } as unknown as Scene);
    const A = deep_freeze(shadow_geometry(scene));
    const d1 = dumps(compose(scene, project_scene(scene, A)));
    const d2 = dumps(compose(scene, project_scene(scene, A, camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5], 3))));
    const d3 = dumps(compose(scene, project_scene(scene, A)));
    assert.equal(d1, d3);
    assert.notEqual(d1, d2);
    assert.equal(dumps(compose(scene, project_scene(scene, A_free))), d1);
  });
}

test("the yaw/pitch example is among the examples (regression test of the explicit-override rule)", () => {
  assert.ok(examples.includes("directional.json"));
  const scene = load_scene(read_json(`${EXAMPLES}/directional.json`));
  assert.ok(scene.camera.yaw_deg !== undefined && scene.camera.target === undefined);
});

test("construction_block (contract §5.4.14 (c)) builds the construction block of a light from its shadow records", () => {
  const scene = load_scene(read_json(`${EXAMPLES}/basic.json`));
  const B = project_scene(scene, shadow_geometry(scene));
  const lt = B.lights[0];
  assert.ok(lt !== undefined && B.construction !== null);
  assert.deepEqual(construction_block(lt, B.shadows.filter((s) => s.light === lt.id)), B.construction);
  assert.ok(B.construction.segments.length > 0);
  assert.deepEqual(construction_block(lt, []).segments, []);
});

test("stage B shares the camera-free point lists of stage A by reference (contract §5.4.7, M7 review)", () => {
  for (const f of examples) {
    if (TODO_EXAMPLES.has(f)) continue;
    const scene = load_scene(read_example(f));
    const A = shadow_geometry(scene);
    const B = project_scene(scene, A);
    assert.equal(B.shadows.length, A.shadows.length);
    A.shadows.forEach((a, i) => {
      const b = B.shadows[i] as (typeof B.shadows)[number];
      assert.ok(b.S_lists === a.S_lists && b.Q_lists === a.Q_lists && b.G_lists === a.G_lists, `${f} shadow ${i}`);
    });
  }
});

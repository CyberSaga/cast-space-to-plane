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
import { camera_override, deep_freeze, read_json, repo_path } from "./helpers.js";

const EXAMPLES = repo_path("examples");
const examples = readdirSync(EXAMPLES).filter((f) => f.endsWith(".json")).sort();

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

/** The camera-free blocks of a v1 document (contract §5.4.7 / §5.0.3, see the implementation notes of §5.4 for
 * the shadow conic entries: `conic` is the image of the ground conic under `P M E` and is left out; `kind` and `arc`
 * are camera dependent only in principle and are equal for the five examples and the test camera). */
function camera_free(doc: any): string {
  const points: any = {};
  for (const name of Object.keys(doc.points)) {
    if (OG.test(name)) continue;
    points[name] = pick(doc.points[name], ["world", "direction", "at_infinity"].filter((k) => k in doc.points[name]));
  }
  return dumps({
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
    rays: doc.construction.rays,
    warnings: doc.warnings.filter((w: any) => !CAMERA_CODES.has(w.code)).map((w: any) => [w.code, w.ids]),
  });
}

for (const file of examples) {
  test(`deterministic render: ${file}`, () => {
    const a = render(load_scene(read_json(`${EXAMPLES}/${file}`)));
    const b = render(load_scene(read_json(`${EXAMPLES}/${file}`)));
    assert.equal(dumps(a.geometry), dumps(b.geometry));
    assert.equal(a.svg, b.svg);
    assert.equal(write_svg(a.geometry), write_svg(b.geometry));
  });

  test(`camera-free blocks are identical for two cameras: ${file}`, () => {
    const scene = load_scene(read_json(`${EXAMPLES}/${file}`));
    const other = camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5], 3);
    const d1 = render(scene).geometry as any;
    const d2 = render(scene, other).geometry as any;
    const k1 = Object.keys(d1.points).filter((n) => !OG.test(n)).sort();
    const k2 = Object.keys(d2.points).filter((n) => !OG.test(n)).sort();
    assert.deepEqual(k1, k2);
    assert.equal(camera_free(d1), camera_free(d2));
    assert.notEqual(dumps(d1.camera), dumps(d2.camera));
  });

  test(`stage A never reads scene.camera and A is never mutated: ${file}`, () => {
    const scene = load_scene(read_json(`${EXAMPLES}/${file}`));
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

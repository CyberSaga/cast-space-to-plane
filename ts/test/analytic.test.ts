/**
 * The hand-computable acceptance cases of spec §10 (M7 row) run through the port alone and checked against hand
 * values, independently of the expected files (contract §5.4.13).
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { render } from "../src/pipeline.js";
import { load_scene } from "../src/scene.js";
import { read_json, repo_path } from "./helpers.js";

const CASES = repo_path("tests", "conformance", "cases");

function close(a: readonly number[], b: readonly number[], tol: number, what: string): void {
  assert.equal(a.length, b.length, what);
  a.forEach((x, i) => assert.ok(Math.abs(x - (b[i] as number)) <= tol, `${what}: ${JSON.stringify(a)} vs ${JSON.stringify(b)}`));
}

test("analytic_unit_box_point_light_overhead: shadows x1.5, outline, construction hand values", () => {
  const doc = render(load_scene(read_json(`${CASES}/analytic_unit_box_point_light_overhead.json`))).geometry as any;
  const P = doc.points;
  close(P["cube.v4.shadow.lamp"].world, [-0.75, -0.75, 0], 1e-12, "v4");
  close(P["cube.v5.shadow.lamp"].world, [0.75, -0.75, 0], 1e-12, "v5");
  close(P["cube.v6.shadow.lamp"].world, [0.75, 0.75, 0], 1e-12, "v6");
  close(P["cube.v7.shadow.lamp"].world, [-0.75, 0.75, 0], 1e-12, "v7");
  assert.deepEqual(doc.shadows[0].outline, ["cube.v4.shadow.lamp", "cube.v5.shadow.lamp", "cube.v6.shadow.lamp", "cube.v7.shadow.lamp"]);
  assert.equal(doc.shadows[0].unbounded, false);
  assert.deepEqual(doc.warnings, []);
  close(P["F.lamp"].world, [0, 0, 0], 0, "F");
  // the vertical plane through the camera and its target contains the z axis: L' and F' have u = 0
  assert.ok(Math.abs(doc.construction.light_point[0]) <= 1e-9);
  assert.ok(Math.abs(doc.construction.shadow_vp[0]) <= 1e-9);
  // depth of L = forward·(L − C) = 1.5980037422045514 + 6.392014968818206 + 0.8988771049900601
  assert.ok(Math.abs(P["L.lamp"].depth - 8.888895816012818) <= 1e-9, String(P["L.lamp"].depth));
  close(doc.construction.light_point, [0, 87.93525754212652], 1e-6, "light_point");
  close(doc.construction.shadow_vp, [0, -15.270708139022979], 1e-6, "shadow_vp");
  assert.ok(Math.abs(doc.horizon.v_mm - 176.09035322810843) <= 1e-6);
  assert.ok(doc.construction.checks.length > 0);
  for (const c of doc.construction.checks) assert.ok(c.max_error_mm <= 1e-9, JSON.stringify(c));
  assert.equal(doc.edges.length, 12);
  assert.equal(Object.keys(P).length, 18);
});

test("analytic_sun_45deg_box: every top-vertex shadow is displaced horizontally by exactly the vertex height", () => {
  const doc = render(load_scene(read_json(`${CASES}/analytic_sun_45deg_box.json`))).geometry as any;
  const P = doc.points;
  let n = 0;
  for (const name of Object.keys(P)) {
    const m = /^post\.(v\d+)\.shadow\.sun$/.exec(name);
    if (m === null) continue;
    const top = P[`post.${m[1]}`].world as number[];
    const S = P[name].world as number[];
    assert.equal(S[2], 0);
    const d = Math.hypot(S[0] - (top[0] as number), S[1] - (top[1] as number));
    if ((top[2] as number) > 0) {
      assert.ok(Math.abs(d - (top[2] as number)) <= 1e-12, `${name}: |S − Q| = ${d}, h = ${top[2]}`);
      n++;
    }
  }
  assert.ok(n >= 2, "no top-vertex shadow checked");
  assert.deepEqual(doc.warnings, []);
});

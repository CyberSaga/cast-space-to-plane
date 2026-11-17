/** Tests of `web/src/doc_summary.ts`: the counts the status line and the `doc_summary` hook show, computed from the
 * document (the core worker sends only these), and their structured-clone round trip. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { compose, load_scene, project_scene, shadow_geometry } from "castplane";

import { doc_summary_of, ray_count, umbra_count } from "../src/doc_summary.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const example = (name: string) => load_scene(JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8")));

test("doc summary: the counts of the document, umbra null without the key, hidden runs, constructions", () => {
  for (const name of ["basic", "two_lights", "wall_and_ground"]) {
    const scene = example(name);
    const A = shadow_geometry(scene);
    for (const [umbra, hidden] of [[true, true], [false, false]] as const) {
      const doc = compose(scene, project_scene(scene, A, undefined, umbra), hidden);
      const s = doc_summary_of(doc);
      assert.equal(s.points, Object.keys(doc.points).length);
      assert.equal(s.edges, doc.edges.length);
      assert.equal(s.rays, ray_count(doc));
      assert.equal(s.umbra_pieces, doc.umbra === undefined ? null : umbra_count(doc));
      assert.equal(s.hidden_lines, doc.hidden_lines);
      assert.equal(s.hidden_edge_runs, doc.edges.reduce((n, e) => n + e.runs.filter((r) => !r.visible).length, 0));
      assert.deepEqual(s.receivers, doc.receivers.map((r) => r.id));
      assert.deepEqual(s.constructions, doc.constructions === undefined ? [] : Object.keys(doc.constructions));
      assert.deepEqual(structuredClone(s), s);
    }
  }
  const two = example("two_lights");
  const doc = compose(two, project_scene(two, shadow_geometry(two)));
  assert.ok(doc_summary_of(doc).constructions.length >= 2 && (doc_summary_of(doc).umbra_pieces ?? 0) > 0, "two_lights: per-light blocks, umbra");
  const wall = example("wall_and_ground");
  assert.ok(doc_summary_of(compose(wall, project_scene(wall, shadow_geometry(wall)), true)).hidden_edge_runs > 0, "wall: hidden runs");
});

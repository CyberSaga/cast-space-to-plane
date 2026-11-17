/** Tests of the core worker's engine (`web/src/core_engine.ts`) in Node: on a structured-cloned scene it gives the
 * synchronous path's documents byte for byte (SVG, JSON downloads, the packed drawing, the ray points), in two phases at
 * rest; a newer request drops a pending final phase; a pose re-runs stage A on an equal scene; stale gens are answered
 * as such. */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { LAYER_IDS, compose, load_scene, project_scene, shadow_geometry, write_svg } from "castplane";
import type { Scene } from "castplane";

import { pack_art } from "../src/art_buffers.js";
import type { ArtReply, DownloadedReply, FromWorker, RenderMessage, RenderedReply } from "../src/core_client.js";
import { CoreEngine } from "../src/core_engine.js";
import { doc_summary_of } from "../src/doc_summary.js";
import { json_blob, ordered_layers, svg_blob } from "../src/download.js";
import { line_art, vertex_ray_points } from "../src/observer.js";
import { camera_from_orbit, orbit_from_camera } from "../src/orbit.js";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const example = (name: string): Scene => load_scene(JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8")));

function harness() {
  const out: FromWorker[] = [];
  const later: { fn: () => void; live: boolean }[] = [];
  const engine = new CoreEngine((m) => out.push(structuredClone(m)), (fn) => {
    const job = { fn, live: true };
    later.push(job);
    return () => { job.live = false; };
  });
  const run_later = () => {
    for (const j of later.splice(0)) if (j.live) j.fn();
  };
  return { engine, out, run_later, later };
}

const render_msg = (req: number, gen: number, block: unknown, over: Partial<RenderMessage> = {}): RenderMessage => ({
  type: "render", req, gen, block, hidden: true, umbra: true, layers: null, quick_layers: ordered_layers(LAYER_IDS),
  img_threshold: 250_000, hidden_style: "dashed", two_phase: true, art_layers: [...LAYER_IDS], dragging: false, ...over,
});

test("core engine: two phases at rest give the synchronous documents byte for byte; art, rays and summary match", () => {
  for (const name of ["basic", "two_lights", "wall_and_ground"]) {
    const scene = example(name);
    const A = shadow_geometry(scene);
    const block = camera_from_orbit(orbit_from_camera(scene.camera, scene), scene.camera);
    const { engine, out, run_later } = harness();
    engine.handle({ type: "scene", gen: 1, scene: structuredClone(scene) });
    engine.handle(render_msg(1, 1, block));
    assert.equal(out.length, 1);
    const quick = out[0] as RenderedReply;
    assert.equal(quick.phase, "quick");
    const Bq = project_scene(scene, A, block, false), dq = compose(scene, Bq, false);
    assert.equal(quick.svg, write_svg(dq, LAYER_IDS, "dashed"), `${name}: quick SVG`);
    assert.equal(quick.img, false);
    assert.ok(engine.final_waiting);
    run_later();
    const fin = out[1] as RenderedReply;
    assert.equal(fin.phase, "final");
    const B = project_scene(scene, A, block, true), doc = compose(scene, B, true);
    assert.equal(fin.svg, write_svg(doc, LAYER_IDS, "dashed"), `${name}: final SVG`);
    assert.deepEqual(fin.warnings, doc.warnings);
    assert.deepEqual(fin.summary, doc_summary_of(doc));
    assert.deepEqual(fin.rec, structuredClone(B.camera));
    assert.deepEqual(fin.art, pack_art(line_art(doc, B.camera, 1, new Set(LAYER_IDS))), `${name}: packed drawing`);
    assert.deepEqual(fin.ray_points, vertex_ray_points(doc, scene));
    assert.equal(fin.stage_a_ran, false, "the load's stage A is the main thread's");
    // downloads: the texts of download.ts on the same resting document
    engine.handle({ type: "download", req: 2, gen: 1, kind: "svg", layers: ["objects", "construction"], hidden_style: "dashed",
      hidden: true, umbra: true, block, scene_name: name });
    engine.handle({ type: "download", req: 3, gen: 1, kind: "json", layers: [], hidden_style: "dashed", hidden: true, umbra: true,
      block, scene_name: name });
    const [dsvg, djson] = out.slice(2) as DownloadedReply[];
    const fsvg = svg_blob(doc, ["objects", "construction"], name, "dashed"), fjson = json_blob(doc, name);
    assert.deepEqual([dsvg!.text, dsvg!.filename, dsvg!.mime], [fsvg.text, fsvg.filename, fsvg.type], `${name}: SVG download`);
    assert.deepEqual([djson!.text, djson!.filename, djson!.mime], [fjson.text, fjson.filename, fjson.type], `${name}: JSON download`);
    // art with another layer set: the last document re-packed
    engine.handle({ type: "art", req: 4, gen: 1, art_layers: ["objects"] });
    const art = out[4] as ArtReply;
    assert.equal(art.type, "art");
    assert.deepEqual(art.art, pack_art(line_art(doc, B.camera, 1, new Set(["objects"]))));
  }
});

test("core engine: a newer render drops the pending final; art / download run it first; drag renders are single-phase", () => {
  const scene = example("basic");
  const A = shadow_geometry(scene);
  const b0 = scene.camera, b1 = camera_from_orbit({ ...orbit_from_camera(scene.camera, scene), yaw_deg: 30 }, scene.camera);
  const { engine, out, run_later } = harness();
  engine.handle({ type: "scene", gen: 1, scene: structuredClone(scene) });
  engine.handle(render_msg(1, 1, b0));
  engine.handle(render_msg(2, 1, b1, { two_phase: false, hidden: false, umbra: false, dragging: true }));
  run_later();
  assert.deepEqual(out.map((m) => m.type === "rendered" ? `${m.req}${m.phase}` : m.type), ["1quick", "2final"], "final of 1 dropped");
  assert.equal((out[1] as RenderedReply).svg, write_svg(compose(scene, project_scene(scene, A, b1, false), false), LAYER_IDS, "dashed"));
  // a download while a final is pending: the final runs first (then its document is reused)
  engine.handle(render_msg(3, 1, b1));
  engine.handle({ type: "download", req: 4, gen: 1, kind: "json", layers: [], hidden_style: "dashed", hidden: true, umbra: true, block: b1,
    scene_name: "basic" });
  run_later();
  assert.deepEqual(out.slice(2).map((m) => m.type === "rendered" ? `${m.req}${m.phase}` : m.type), ["3quick", "3final", "downloaded"]);
  assert.equal((out[4] as DownloadedReply).text, json_blob(compose(scene, project_scene(scene, A, b1, true), true), "basic").text);
  // a download for another block than the last document's renders that block's resting document
  engine.handle({ type: "download", req: 5, gen: 1, kind: "json", layers: [], hidden_style: "dashed", hidden: false, umbra: true, block: b0,
    scene_name: "basic" });
  assert.equal((out[5] as DownloadedReply).text, json_blob(compose(scene, project_scene(scene, A, b0, true), false), "basic").text);
});

test("core engine: a pose re-runs stage A on an equal scene (reported once); stale gens; a long quick SVG goes to <img>", () => {
  const scene = example("basic");
  const { engine, out } = harness();
  engine.handle({ type: "scene", gen: 1, scene: structuredClone(scene) });
  const id = scene.objects[0]!.id;
  const t = { position: [0.25, -0.5, 0] as [number, number, number], rotation_deg: [0, 0, 37.5] as [number, number, number] };
  engine.handle({ type: "pose", gen: 2, transforms: scene.objects.map((o) => [o.id, o.id === id ? t : o.transform]) });
  const scene1: Scene = { ...scene, objects: scene.objects.map((o) => o.id === id ? { ...o, transform: t } : o) };
  const A1 = shadow_geometry(scene1);
  engine.handle(render_msg(1, 1, scene.camera));
  assert.deepEqual(out[0], { type: "stale", req: 1 }, "a render of the old gen");
  engine.handle(render_msg(2, 2, scene.camera, { two_phase: false, dragging: true, hidden: false, umbra: false }));
  const r = out[1] as RenderedReply;
  assert.equal(r.svg, write_svg(compose(scene1, project_scene(scene1, A1, scene.camera, false), false), LAYER_IDS, "dashed"));
  assert.ok(r.stage_a_ran && typeof r.stage_a_ms === "number");
  engine.handle(render_msg(3, 2, scene.camera, { two_phase: false, dragging: true, hidden: false, umbra: false, layers: ["objects"] }));
  const r2 = out[2] as RenderedReply;
  assert.ok(!r2.stage_a_ran && r2.stage_a_ms === null, "reported once");
  assert.ok(r2.img, "a layer subset is the <img> mode");
  assert.equal(r2.svg, write_svg(compose(scene1, project_scene(scene1, A1, scene.camera, false), false), ["objects"], "dashed"));
  // a resting quick SVG longer than the threshold: written with the checked layers for the <img> overlay
  engine.handle(render_msg(4, 2, scene.camera, { img_threshold: 0, quick_layers: ["objects", "labels"] }));
  const q = out[3] as RenderedReply;
  assert.ok(q.phase === "quick" && q.img);
  assert.equal(q.svg, write_svg(compose(scene1, project_scene(scene1, A1, scene.camera, false), false), ["objects", "labels"], "dashed"));
  // an art request of an old gen is stale
  engine.handle({ type: "art", req: 5, gen: 1, art_layers: [] });
  assert.equal(out.at(-1)!.type, "stale");
  // an exception is an error reply, never a throw
  engine.handle(render_msg(6, 2, { position: "nope" }, { two_phase: false }));
  assert.equal(out.at(-1)!.type, "error");
});

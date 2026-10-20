// Usage: node tools/web_frame_bench.mjs SCENE.json [REPS]
// Times the TypeScript port the way the web UI uses it: stage A once (scene load), then "drag frames"
// (project_scene with umbra off + compose without hidden lines + write_svg) and "still frames" (compose with
// hidden lines on). Prints the medians, the drag-frame SVG size and the document's warnings as JSON.
// Needs the port built first (`npm run -w ts build`). Targets for a heavy example scene (many meshes, hidden lines
// on): stage A <= 1.5 s, drag frame <= 120 ms, still frame <= 1.5 s. Timings depend on the machine: compare against
// a baseline measured in the same container.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const mod = (p) => pathToFileURL(resolve(REPO, p)).href;
const { load_scene, shadow_geometry, project_scene, compose } = await import(mod("ts/build/src/index.js"));
const { write_svg } = await import(mod("ts/build/src/output/svg.js"));

const file = process.argv[2];
if (!file) {
  console.error("usage: node tools/web_frame_bench.mjs SCENE.json [REPS]");
  process.exit(2);
}
const reps = Number(process.argv[3] ?? 3);
const scene = load_scene(JSON.parse(readFileSync(file, "utf-8")));
const median = (xs) => [...xs].sort((a, b) => a - b)[Math.floor(xs.length / 2)];

let t = performance.now();
const A = shadow_geometry(scene);
const stage_a = performance.now() - t;
const drag = [], still = [];
let svg_chars = 0, doc = null;
for (let r = 0; r < reps; r++) {
  t = performance.now();
  const d = compose(scene, project_scene(scene, A, undefined, false), false);
  svg_chars = write_svg(d).length;
  drag.push(performance.now() - t);
}
for (let r = 0; r < reps; r++) {
  t = performance.now();
  doc = compose(scene, project_scene(scene, A, undefined, true), true);
  write_svg(doc);
  still.push(performance.now() - t);
}
console.log(JSON.stringify({
  stageA_ms: +stage_a.toFixed(1),
  drag_frame_ms_median: +median(drag).toFixed(1),
  still_frame_hidden_ms_median: +median(still).toFixed(1),
  svg_chars_drag: svg_chars,
  warnings: doc.warnings.map((w) => `${w.code} ${JSON.stringify(w.ids)}`),
}, null, 1));

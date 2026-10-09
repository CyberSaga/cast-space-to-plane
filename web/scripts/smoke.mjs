// Dev helper (not a CI step, not a dependency): browser smoke check and `core ms` / `dom ms` measurement of the
// built web UI with Playwright + Chromium, using a Playwright installed outside the repository (global npm root).
//
//   npm run -w web build && (cd web && npx vite preview --port 4173 --strictPort) &
//   node web/scripts/smoke.mjs http://localhost:4173/ out/ [screenshot.png] [benchmarks/scenes/benchmark_100.json]
//   node web/scripts/smoke.mjs http://localhost:4173/ out/ --shots docs/images      # + the phase-2 screenshots
//
// Checks: the page loads the default example and renders the six overlay groups; every example's scene-camera
// SVG / JSON through the bundled core is written to out/<name>.svg / .json (compare them with the Python
// reference); a 30-step drag per example records the drag frames' `core ms` / `dom ms` and overlay mode
// (web/README.md); the optional scene file is loaded through the file picker and dragged likewise; a page-wide
// drop loads a scene; the three downloads are saved to out/; a non-JSON file and an invalid scene show the error
// panel. Phase 2 (contract §5.4.10): an example that fails to load (the path-only `mesh_demo`, the core has no loader)
// is reported and loaded instead from its Python expansion (`ts/test/fixtures/<name>.expanded.json`) through the file
// picker; the phase-2 checks load `wall_and_ground` (hidden lines on: the hidden sub-groups in the overlay, the
// "omit" style, the wall plate in the 3D view), `mesh_demo` (the house mesh) and `two_lights` (two light helpers, the
// per-light construction blocks, umbra pieces at rest and none during a drag), and with `--shots DIR` save
// DIR/web_ui_<name>.png for each. M9 (contract §5.6.9): for the five phase-1 examples (and the optional scene file)
// the "旁觀視角" switch is turned on and off: the writer's SVG text, the overlay markup and the SVG / JSON downloads
// must be identical with the switch on and off for the same camera; a 30-step drag of the drawing camera with the
// switch on records `core ms` + `dom ms` + `obs ms` per frame (< 100 ms for the five examples); an observer drag must
// not change the drawing; the narrow (< 880 px) layout stacks the panes; switching off restores the drawing pane's
// size. With `--shots DIR` it also saves DIR/web_ui_observer.png. Prints one JSON record. Exit 1 on a page error or a
// failed check.
import { execSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(join(execSync("npm root -g", { encoding: "utf-8" }).trim(), "/"));
const { chromium } = require("playwright");

const argv = process.argv.slice(2);
const shotsAt = argv.indexOf("--shots");
const shotsDir = shotsAt >= 0 ? argv[shotsAt + 1] : undefined;
if (shotsAt >= 0) argv.splice(shotsAt, 2);
const [url, outdir, shot, sceneFile] = argv;
if (!url || !outdir || (shotsAt >= 0 && !shotsDir)) {
  console.error("usage: node web/scripts/smoke.mjs URL OUTDIR [SCREENSHOT.png] [SCENE.json] [--shots DIR]");
  process.exit(2);
}
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
mkdirSync(outdir, { recursive: true });

const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
const logs = [];
page.on("console", (m) => logs.push(`${m.type()}: ${m.text()}`));
page.on("pageerror", (e) => logs.push(`pageerror: ${e.message}`));

const frames2 = () => page.evaluate(() => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))));
const median = (xs) => {
  const s = [...xs].sort((a, b) => a - b), n = s.length;
  return n === 0 ? NaN : n % 2 ? s[(n - 1) / 2] : (s[n / 2 - 1] + s[n / 2]) / 2;
};

async function drag(steps, selector = "#stage") {
  const box = await page.locator(selector).boundingBox();
  const x0 = box.x + box.width / 2, y0 = box.y + box.height / 2;
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(x0 + i * 3, y0 + i * 0.7);
    await frames2();
  }
  await page.mouse.up();
  await frames2();
}

async function drag_stats() {
  await drag(30);
  const frames = await page.evaluate(() => window.castplane_web.frames);
  const d = frames.filter((f) => f.dragging), rest = frames.filter((f) => !f.dragging);
  return {
    drag_frames: d.length,
    core_ms: { min: Math.min(...d.map((f) => f.core_ms)), median: median(d.map((f) => f.core_ms)) },
    dom_ms: { min: Math.min(...d.map((f) => f.dom_ms)), median: median(d.map((f) => f.dom_ms)) },
    drag_modes: [...new Set(d.map((f) => f.mode))],
    resting_dom_ms: rest.map((f) => f.dom_ms),
    svg_chars: rest.at(-1)?.svg_bytes,
  };
}

await page.goto(url);
await page.waitForFunction(() => document.getElementById("status").textContent.includes("core ms"), null, { timeout: 30000 });
const first = await page.evaluate(() => ({
  status: document.getElementById("status").textContent,
  groups: [...document.querySelectorAll("svg.overlay > g")].map((g) => g.id),
  elements: document.querySelectorAll("svg.overlay *").length,
  examples: window.castplane_web.examples,
}));
if (shot) {
  await page.waitForTimeout(300);
  await page.screenshot({ path: shot });
}

/** Load a scene file through the file picker under the name `<name>.json` and wait for its first frame. */
async function load_file_as(name, path) {
  await page.setInputFiles("#file", { name: `${name}.json`, mimeType: "application/json", buffer: readFileSync(path) });
  await page.waitForFunction((s) => document.getElementById("status").textContent.startsWith(`${s}:`), name, { timeout: 120000 });
  await frames2();
}

const rows = {};
const load_errors = {};
for (const name of first.examples) {
  const ok = await page.evaluate((n) => window.castplane_web.load_example(n), name);
  if (!ok) {
    // the core reads expanded scenes only (§5.4.0): the example's Python expansion, through the file picker
    load_errors[name] = await page.locator("#error").textContent();
    const expanded = join(ROOT, "ts", "test", "fixtures", `${name}.expanded.json`);
    if (!existsSync(expanded)) continue;
    await load_file_as(name, expanded);
  }
  await frames2();
  const ref = await page.evaluate(() => window.castplane_web.reference_render());
  if (ref.name !== name) throw new Error(`reference_render rendered ${ref.name}, not ${name}`);
  writeFileSync(join(outdir, `${name}.svg`), ref.svg);
  writeFileSync(join(outdir, `${name}.json`), ref.json + "\n");
  rows[name] = await drag_stats();
}

// phase 2 (§5.4.10): receivers, mesh objects, several lights, the hidden-line switch and style
const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); };
const overlay_ids = () => page.evaluate(() => [...document.querySelectorAll("svg.overlay g[id]")].map((g) => g.id));
const ui = () => page.evaluate(() => ({ names: window.castplane_web.scene3d_names, doc: window.castplane_web.doc_summary,
  hidden: window.castplane_web.hidden, status: document.getElementById("status").textContent }));
async function shoot(name) {
  if (!shotsDir) return null;
  mkdirSync(shotsDir, { recursive: true });
  const path = join(shotsDir, `web_ui_${name}.png`);
  await page.waitForTimeout(300);
  await page.screenshot({ path });
  return path;
}
const phase2 = {};
{
  await page.evaluate(() => window.castplane_web.load_example("wall_and_ground"));
  await frames2();
  const s = await ui();
  const ids = await overlay_ids();
  check(s.hidden.lines === true && s.hidden.style === "dashed", "wall_and_ground: hidden lines on, dashed (from the scene)");
  check(s.doc.hidden_lines === true && s.doc.hidden_edge_runs > 0, "wall_and_ground: hidden runs in the document");
  check(ids.includes("objects.hidden") && ids.includes("objects.hidden.crate"), "wall_and_ground: objects.hidden sub-groups");
  check(s.names.includes("receiver:ground") && s.names.includes("grid:ground"), "wall_and_ground: the ground plane and grid");
  check(s.names.includes("receiver:wall") && s.names.includes("outline:wall") && !s.names.includes("grid:wall"),
    "wall_and_ground: the wall as a bounded plate");
  check(JSON.stringify(s.doc.receivers) === '["ground","wall"]', "wall_and_ground: receivers in the document");
  const dashed = await page.evaluate(() => ({
    dasharray: document.querySelector('svg.overlay g[id="objects.hidden"]')?.getAttribute("stroke-dasharray") ?? null,
    elements: document.querySelectorAll('svg.overlay [id^="objects.hidden."] > *').length,
  }));
  check(dashed.dasharray === "0.5 0.5" && dashed.elements > 0, "wall_and_ground: dashed hidden runs in the overlay");
  const shot_path = await shoot("wall_and_ground");
  await page.evaluate(() => window.castplane_web.set_hidden(true, "omit"));
  await frames2();
  const omit_ids = await overlay_ids();
  const omit_hidden_children = await page.evaluate(() => document.querySelectorAll('svg.overlay [id^="objects.hidden."] > *').length);
  check(omit_hidden_children === 0, "wall_and_ground: the omit style draws no hidden runs");
  await page.evaluate(() => window.castplane_web.set_hidden(false));
  await frames2();
  const off = await ui();
  check(off.doc.hidden_lines === false && !(await overlay_ids()).includes("objects.hidden"), "wall_and_ground: switch off");
  phase2.wall_and_ground = { names: s.names, overlay_groups: ids.length, dashed, omit_groups: omit_ids.length,
    hidden_edge_runs: s.doc.hidden_edge_runs, status: s.status, screenshot: shot_path };
}
{
  const ok = await page.evaluate(() => window.castplane_web.load_example("mesh_demo"));
  check(!ok, "mesh_demo: the path-only example is the expand-first error");
  await load_file_as("mesh_demo", join(ROOT, "ts", "test", "fixtures", "mesh_demo.expanded.json"));
  const s = await ui();
  check(s.names.includes("house") && s.names.includes("tank"), "mesh_demo: the house mesh and the tank in the 3D view");
  const house_edges = await page.evaluate(() => document.querySelectorAll('svg.overlay [id="objects.house"] > *').length);
  check(house_edges > 0, "mesh_demo: the house's edges in the overlay");
  phase2.mesh_demo = { names: s.names, house_elements: house_edges, status: s.status, screenshot: await shoot("mesh_demo") };
}
{
  await page.evaluate(() => window.castplane_web.load_example("two_lights"));
  await frames2();
  const s = await ui();
  const ids = await overlay_ids();
  check(s.names.includes("light:left") && s.names.includes("light:right"), "two_lights: one helper per light");
  check(JSON.stringify(s.doc.constructions) === '["left","right"]', "two_lights: per-light construction blocks");
  check(s.doc.umbra_pieces > 0 && ids.includes("cast_shadow.umbra"), "two_lights: umbra at rest");
  const shot_path = await shoot("two_lights");
  // during a drag the umbra is skipped (§5.4.11), the resting frame recomputes it
  const box = await page.locator("#stage").boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 + 4);
  await frames2();
  const during = await ui();
  await page.mouse.up();
  await frames2();
  const after = await ui();
  check(during.doc.umbra_pieces === 0 && after.doc.umbra_pieces > 0, "two_lights: umbra skipped during a drag only");
  phase2.two_lights = { names: s.names, umbra_pieces: s.doc.umbra_pieces, umbra_pieces_drag: during.doc.umbra_pieces,
    umbra_pieces_after: after.doc.umbra_pieces, overlay_groups: ids, status: s.status, screenshot: shot_path };
}
if (sceneFile) {
  const stem = sceneFile.replace(/^.*\//, "").replace(/\.json$/, "");
  await page.setInputFiles("#file", sceneFile);
  await page.waitForFunction((s) => document.getElementById("status").textContent.startsWith(s), stem, { timeout: 120000 });
  await frames2();
  rows[stem] = await drag_stats();
}

// M9 (contract §5.6.9): the observer switch
const observer = { rows: {} };
const PHASE1 = ["basic", "construction_demo", "curved_demo", "directional", "three_point"];
const drawing = () => page.evaluate(() => ({
  svg: window.castplane_web.svg,
  overlay: document.querySelector("svg.overlay").innerHTML,
  dl: window.castplane_web.download_texts(),
  camera: JSON.stringify(window.castplane_web.camera),
  stage: (({ width, height }) => ({ width, height }))(document.getElementById("stage").getBoundingClientRect()),
}));
const same_drawing = (a, b) => a.svg === b.svg && a.overlay === b.overlay && a.dl.svg === b.dl.svg && a.dl.json === b.dl.json
  && a.camera === b.camera;
async function observer_check(name, load) {
  await page.evaluate(() => window.castplane_web.set_observer(false));
  await load();
  await frames2();
  const off = await drawing();
  await page.evaluate(() => window.castplane_web.set_observer(true));
  await frames2();
  await frames2();
  const on = await drawing();
  const obs = await page.evaluate(() => window.castplane_web.observer);
  check(same_drawing(off, on), `${name}: SVG / overlay / downloads identical with the observer on and off`);
  check(obs.on && obs.names.includes("board:frame") && obs.names.includes("dots:E") && obs.names.includes("frustum")
    && obs.names.includes("d-line") && obs.names.includes("g-line") && obs.art_objects > 0, `${name}: observer elements`);
  check(obs.labels.length === 5 && obs.labels[0].startsWith("E（讀數）"), `${name}: observer labels`);
  // a drag of the drawing camera with the observer on: per-frame core + dom + obs
  await page.evaluate(() => { window.castplane_web.frames.length = 0; });
  await drag(30);
  const frames = (await page.evaluate(() => window.castplane_web.frames)).filter((f) => f.dragging);
  const totals = frames.map((f) => f.core_ms + f.dom_ms + (f.obs_ms ?? 0));
  const row = {
    drag_frames: frames.length,
    obs_ms: { min: Math.min(...frames.map((f) => f.obs_ms)), median: median(frames.map((f) => f.obs_ms)), max: Math.max(...frames.map((f) => f.obs_ms)) },
    total_ms: { min: Math.min(...totals), median: median(totals), max: Math.max(...totals) },
  };
  check(frames.length > 0 && frames.every((f) => typeof f.obs_ms === "number"), `${name}: obs ms recorded during the drag`);
  // the observer follows the drawing camera
  const moved = await page.evaluate(() => window.castplane_web.observer.labels[0]);
  // an observer drag (and wheel) changes only the observer view
  const before = await drawing();
  const view0 = (await page.evaluate(() => window.castplane_web.observer)).view;
  await drag(10, "#observer");
  const obox = await page.locator("#observer").boundingBox();
  await page.mouse.move(obox.x + obox.width / 2, obox.y + obox.height / 2);
  await page.mouse.wheel(0, 120);
  await frames2();
  const view1 = (await page.evaluate(() => window.castplane_web.observer)).view;
  const after = await drawing();
  check(same_drawing(before, after), `${name}: an observer drag leaves the drawing unchanged`);
  check(view1.az_deg !== view0.az_deg && view1.dist !== view0.dist, `${name}: the observer drag / wheel moves the observer`);
  // switching off restores the §5.4.10 page: the drawing pane's size and the same drawing
  await page.evaluate(() => window.castplane_web.set_observer(false));
  await frames2();
  const off2 = await drawing();
  const hidden = await page.evaluate(() => document.getElementById("observer").hidden
    && document.getElementById("observer-controls").hidden && !document.getElementById("status").textContent.includes("obs ms"));
  check(hidden, `${name}: switch off hides the observer pane, its controls and obs ms`);
  check(same_drawing(before, off2) && off2.stage.width === off.stage.width && off2.stage.height === off.stage.height,
    `${name}: switch off restores the drawing pane`);
  row.followed = moved !== obs.labels[0];
  check(row.followed, `${name}: the observer follows the drawing camera`);
  observer.rows[name] = row;
  for (const f of frames) {
    if (PHASE1.includes(name) && f.core_ms + f.dom_ms + f.obs_ms >= 100) {
      failures.push(`${name}: a drag frame took ${(f.core_ms + f.dom_ms + f.obs_ms).toFixed(1)} ms with the observer on`);
      break;
    }
  }
}
for (const name of PHASE1) {
  await observer_check(name, () => page.evaluate((n) => window.castplane_web.load_example(n), name));
}
if (sceneFile) {
  const stem = sceneFile.replace(/^.*\//, "").replace(/\.json$/, "");
  await observer_check(stem, () => load_file_as(stem, sceneFile));
}
if (sceneFile) {
  // after a drag in the <img> mode (a large scene), a small scene's resting overlay is the DOM one: the stale image
  // must not stay on top
  await page.evaluate(() => window.castplane_web.load_example("basic"));
  await frames2();
  const img = await page.evaluate(() => getComputedStyle(document.querySelector("img.overlay")).display);
  check(img === "none", "the <img> overlay of a drag frame is not displayed at rest");
}
{
  // a picture_plane scene camera (spec-v0.2 §4.1): loads through the M7 orbit with the picture kept
  const data = JSON.parse(readFileSync(join(ROOT, "examples", "basic.json"), "utf-8"));
  data.camera = { position: [0.37, -2, 0.9], picture_plane: { normal: [0, 1, 0], offset: -2 }, focal_length_mm: 20,
    frame_mm: [36, 24], shift_mm: [0, 0], near_m: 0.05 };
  await page.evaluate((text) => window.castplane_web.load_text("picture_plane", text), JSON.stringify(data));
  await page.evaluate(() => window.castplane_web.set_observer(true));
  await frames2();
  await frames2();
  const pp = await page.evaluate(() => ({ obs: window.castplane_web.observer, ref: window.castplane_web.reference_render(),
    svg: window.castplane_web.svg }));
  check(pp.obs.labels.includes("y = 2.00") && pp.obs.labels.includes("D = 4.00 m"), "picture_plane: board y = 2.00, D = 4.00 m");
  observer.picture_plane = { labels: pp.obs.labels, same_as_scene_camera: pp.svg === pp.ref.svg };
  await page.evaluate(() => window.castplane_web.set_observer(false));
}
{
  // the narrow layout: below 880 px the panes stack, observer on top
  await page.evaluate(() => window.castplane_web.load_example("basic"));
  await page.evaluate(() => window.castplane_web.set_observer(true));
  await page.setViewportSize({ width: 820, height: 900 });
  await frames2();
  await frames2();
  const o = await page.locator("#observer").boundingBox(), v = await page.locator("#viewport").boundingBox();
  check(o.y + o.height <= v.y + 1 && Math.abs(o.x - v.x) < 1, "narrow page: observer stacked above the drawing pane");
  observer.narrow = { observer: o, viewport: v };
  await page.setViewportSize({ width: 1500, height: 900 });
  await frames2();
  const o2 = await page.locator("#observer").boundingBox(), v2 = await page.locator("#viewport").boundingBox();
  check(o2.x + o2.width <= v2.x + 1 && Math.abs(o2.width - v2.width) < 2, "wide page: observer left, equal width");
  if (shotsDir) {
    await page.setViewportSize({ width: 1800, height: 1000 });
    await frames2();
    await page.evaluate(() => window.castplane_web.frame_observer());
    const ob = await page.locator("#observer").boundingBox();
    await page.mouse.move(ob.x + ob.width / 2, ob.y + ob.height / 2);
    await page.mouse.wheel(0, 260);
    await frames2();
    mkdirSync(shotsDir, { recursive: true });
    observer.screenshot = join(shotsDir, "web_ui_observer.png");
    await page.waitForTimeout(300);
    await page.screenshot({ path: observer.screenshot });
    await page.setViewportSize({ width: 1500, height: 900 });
  }
  await page.evaluate(() => window.castplane_web.set_observer(false));
  await frames2();
}

// page-wide drop, then the three downloads
const dropped = readFileSync(join(ROOT, "examples", "curved_demo.json"), "utf-8");
await page.evaluate((text) => {
  const dt = new DataTransfer();
  dt.items.add(new File([text], "dropped_curved.json", { type: "application/json" }));
  document.body.dispatchEvent(new DragEvent("dragover", { dataTransfer: dt, bubbles: true, cancelable: true }));
  document.body.dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
}, dropped);
await page.waitForFunction(() => document.getElementById("status").textContent.startsWith("dropped_curved"), null, { timeout: 30000 });
const downloads = [];
for (const id of ["dl-svg", "dl-json", "dl-scene"]) {
  const [dl] = await Promise.all([page.waitForEvent("download"), page.click(`#${id}`)]);
  await dl.saveAs(join(outdir, dl.suggestedFilename()));
  downloads.push(dl.suggestedFilename());
}

// the error panel
await page.setInputFiles("#file", { name: "notes.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
const not_json = await page.locator("#error").textContent();
await page.setInputFiles("#file", { name: "bad.json", mimeType: "application/json", buffer: Buffer.from('{"version": "0.1", "objects": 3}') });
await page.waitForFunction(() => document.getElementById("error").textContent.includes("SceneError"), null, { timeout: 30000 });
const scene_error = await page.locator("#error").textContent();

const engine = { chromium: browser.version() };
console.log(JSON.stringify({ engine, first, rows, load_errors, phase2, observer, failures, downloads, errors: { not_json, scene_error }, logs }, null, 1));
await browser.close();
process.exitCode = logs.some((l) => l.startsWith("pageerror")) || failures.length > 0 ? 1 : 0;

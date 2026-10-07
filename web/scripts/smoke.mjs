// Dev helper (not a CI step, not a dependency): browser smoke check and `core ms` / `dom ms` measurement of the
// built web UI with Playwright + Chromium, using a Playwright installed outside the repository (global npm root).
//
//   npm run -w web build && (cd web && npx vite preview --port 4173 --strictPort) &
//   node web/scripts/smoke.mjs http://localhost:4173/ out/ [screenshot.png] [benchmarks/scenes/benchmark_100.json]
//
// Checks: the page loads the default example and renders the six overlay groups; every example's scene-camera
// SVG / JSON through the bundled core is written to out/<name>.svg / .json (compare them with the Python
// reference); a 30-step drag per example records the drag frames' `core ms` / `dom ms` and overlay mode
// (web/README.md); the optional scene file is loaded through the file picker and dragged likewise; a page-wide
// drop loads a scene; the three downloads are saved to out/; a non-JSON file and an invalid scene show the error
// panel. Prints one JSON record. Exit 1 on a page error.
import { execSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(join(execSync("npm root -g", { encoding: "utf-8" }).trim(), "/"));
const { chromium } = require("playwright");

const [url, outdir, shot, sceneFile] = process.argv.slice(2);
if (!url || !outdir) {
  console.error("usage: node web/scripts/smoke.mjs URL OUTDIR [SCREENSHOT.png] [SCENE.json]");
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

async function drag(steps) {
  const box = await page.locator("#stage").boundingBox();
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

const rows = {};
for (const name of first.examples) {
  await page.evaluate((n) => window.castplane_web.load_example(n), name);
  await frames2();
  const ref = await page.evaluate(() => window.castplane_web.reference_render());
  writeFileSync(join(outdir, `${name}.svg`), ref.svg);
  writeFileSync(join(outdir, `${name}.json`), ref.json + "\n");
  rows[name] = await drag_stats();
}
if (sceneFile) {
  const stem = sceneFile.replace(/^.*\//, "").replace(/\.json$/, "");
  await page.setInputFiles("#file", sceneFile);
  await page.waitForFunction((s) => document.getElementById("status").textContent.startsWith(s), stem, { timeout: 120000 });
  await frames2();
  rows[stem] = await drag_stats();
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
console.log(JSON.stringify({ engine, first, rows, downloads, errors: { not_json, scene_error }, logs }, null, 1));
await browser.close();
process.exitCode = logs.some((l) => l.startsWith("pageerror")) ? 1 : 0;

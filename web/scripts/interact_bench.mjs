// Dev helper (not a CI step, not a dependency): interaction-latency measurement of the built web UI with Playwright +
// Chromium (a Playwright installed outside the repository, as web/scripts/smoke.mjs). Loads a scene, clicks an object in
// the observer pane (its rings), drags one of its rings, drags the board ring, and reports long tasks, animation-frame
// gaps, the frame records and the hook timings. `--nogl` skips the WebGL draw calls (`castplane_web.set_gl(false)`) so
// a run on a software renderer measures the page JavaScript.
//
//   npm run -w web build && (cd web && npx vite preview --port 4173 --strictPort) &
//   node web/scripts/interact_bench.mjs http://localhost:4173/ examples/basic.json crate [--nogl] [--json out.json]
import { createRequire } from "node:module";
import { readFileSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
const require = createRequire(import.meta.url);
let pw;
try { pw = require("playwright"); } catch { pw = require(execSync("npm root -g").toString().trim() + "/playwright"); }
const { chromium } = pw;
const [url, scenePath, ...rest] = process.argv.slice(2);
const objArg = rest.find((a) => !a.startsWith("--"));
const jsonOut = rest.includes("--json") ? rest[rest.indexOf("--json") + 1] : null;
const nogl = rest.includes("--nogl");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const q = (a, p) => { const s = [...a].sort((x, y) => x - y); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : null; };
const stats = (a) => a.length ? { n: a.length, min: +Math.min(...a).toFixed(1), med: +q(a, 0.5).toFixed(1), p90: +q(a, 0.9).toFixed(1), max: +Math.max(...a).toFixed(1) } : null;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM || "/opt/pw-browsers/chromium", args: ["--no-sandbox"] });
const page = await browser.newPage({ viewport: { width: 1500, height: 900 } });
page.on("pageerror", (e) => console.log("PAGE ERROR", e.message));
await page.goto(url);
await page.waitForFunction(() => window.castplane_web?.svg_length > 0);
// instrumentation: rAF timestamps + long tasks
await page.evaluate(() => {
  window.__raf = []; window.__lt = [];
  const tick = (t) => { window.__raf.push(t); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  new PerformanceObserver((l) => { for (const e of l.getEntries()) window.__lt.push([e.startTime, e.duration]); }).observe({ entryTypes: ["longtask"] });
});
const mark = () => page.evaluate(() => ({ t: performance.now(), raf: window.__raf.length, lt: window.__lt.length }));
const since = (m) => page.evaluate((m) => {
  const raf = window.__raf.slice(m.raf), lt = window.__lt.slice(m.lt);
  const gaps = []; for (let i = 1; i < raf.length; i++) gaps.push(raf[i] - raf[i - 1]);
  return { gaps, lt: lt.map(([s, d]) => +d.toFixed(0)), t: performance.now() - m.t };
}, m);
const settle = async (ms = 400) => { await sleep(ms); };

const out = { url, scene: scenePath };
// ---- load
const text = readFileSync(scenePath, "utf8");
let m = await mark();
const t0 = Date.now();
if (nogl) await page.evaluate(() => window.castplane_web.set_gl?.(false));
const ok = await page.evaluate((args) => window.castplane_web.load_text(args.name, args.text), { name: "bench", text });
await page.waitForFunction(() => window.__raf.length > 0);
await settle(1500);
let r = await since(m);
out.load = { ok, wall_ms: Date.now() - t0, longtasks: r.lt, timings: await page.evaluate(() => window.castplane_web.timings) };
console.log("load:", JSON.stringify(out.load));

// ---- click an object
const obox = await page.locator("#observer").boundingBox();
const objs = await page.evaluate(() => window.castplane_web.objects_px);
let target = null;
const ids = objArg ? [objArg, ...Object.keys(objs)] : Object.keys(objs);
for (const id of ids) {
  const p = objs[id]; if (!p) continue;
  const hit = await page.evaluate((p) => window.castplane_web.pick_at(p[0], p[1]), p);
  if (hit !== null) { target = { id: hit, p }; break; }
}
if (target === null) { console.log("no pickable object"); process.exit(1); }
await page.mouse.move(obox.x + target.p[0], obox.y + target.p[1]);
await settle(300);
m = await mark();
const nf0 = await page.evaluate(() => window.castplane_web.frames.length);
const tc0 = Date.now();
await page.mouse.down(); await page.mouse.up();
// wait until rings appear
await page.waitForFunction(() => window.castplane_web.object_rings_px !== null, null, { timeout: 30000 });
const rings_wall = Date.now() - tc0;
await settle(1500);
r = await since(m);
const clickFrames = await page.evaluate((n) => window.castplane_web.frames.slice(n).map((f) => [f.phase ?? "?", f.dragging, +f.core_ms.toFixed(0), +f.dom_ms.toFixed(0), f.obs_ms === null ? null : +f.obs_ms.toFixed(0), f.overlay ?? null]), nf0);
out.click = { id: target.id, rings_wall_ms: rings_wall, longtasks: r.lt, raf_gaps: stats(r.gaps), core_frames_during_click: clickFrames, selection: await page.evaluate(() => window.castplane_web.selection()) };
console.log("click:", JSON.stringify(out.click));

// ---- second click (part focus, for grouped scenes) to see the cost again
m = await mark(); const tc1 = Date.now();
await page.mouse.down(); await page.mouse.up();
await page.waitForFunction(() => window.castplane_web.object_rings_px !== null, null, { timeout: 30000 });
const rings_wall2 = Date.now() - tc1;
await settle(1500);
r = await since(m);
out.click2 = { rings_wall_ms: rings_wall2, longtasks: r.lt, selection: await page.evaluate(() => window.castplane_web.selection()) };
console.log("click2:", JSON.stringify(out.click2));

// ---- ring drag: find a hit-testable ring point
const rings = await page.evaluate(() => window.castplane_web.object_rings_px);
let grab = null;
for (let axis = 0; axis < 3 && grab === null; axis++) {
  for (const pt of rings.rings[axis]) {
    if (pt === null) continue;
    const [W, H] = rings.size;
    if (pt[0] < 40 || pt[0] > W - 120 || pt[1] < 40 || pt[1] > H - 120) continue;
    const hit = await page.evaluate((pt) => window.castplane_web.hit_at(pt[0], pt[1]), pt);
    if (hit !== null && hit.kind === "object_ring") { grab = { axis: hit.axis, pt }; break; }
  }
}
if (grab === null) { console.log("no ring point"); process.exit(1); }
const sel = await page.evaluate(() => window.castplane_web.selection());
const movedId = sel.kind === "part" ? sel.id : sel.members[0];
const mat0 = await page.evaluate((id) => window.castplane_web.object_matrices(id).observer, movedId);
await page.mouse.move(obox.x + grab.pt[0], obox.y + grab.pt[1]);
await settle(300);
m = await mark();
const td0 = Date.now();
await page.mouse.down();
const down_wall = Date.now() - td0;
await page.keyboard.down("Alt"); // 吸附 off: the proxy moves at the first pointer move
// pointer moves at ~8 ms cadence; record when the proxy first moves
let firstMoveWall = null, firstStageA = null;
const runs0 = (await page.evaluate(() => window.castplane_web.timings)).stage_a_runs;
const tm0 = Date.now();
const STEPS = 40;
for (let i = 1; i <= STEPS; i++) {
  await page.mouse.move(obox.x + grab.pt[0] + i * 3, obox.y + grab.pt[1] + i * 1);
  if (firstMoveWall === null) {
    const mat = await page.evaluate((id) => window.castplane_web.object_matrices(id).observer, movedId);
    if (mat.some((v, k) => v !== mat0[k])) firstMoveWall = Date.now() - tm0;
  }
  if (firstStageA === null) {
    const runs = (await page.evaluate(() => window.castplane_web.timings)).stage_a_runs;
    if (runs > runs0) firstStageA = Date.now() - tm0;
  }
  await sleep(8);
}
const drag_wall = Date.now() - tm0;
const rd = await since(m);
const mu = await mark();
const tu0 = Date.now();
await page.mouse.up();
const up_wall = Date.now() - tu0;
await page.keyboard.up("Alt");
await settle(2500);
const ru = await since(mu);
const frames = await page.evaluate(() => window.castplane_web.frames);
const dragFrames = frames.filter((f) => f.dragging);
out.drag_frame_list = dragFrames.map((f) => [f.phase, +f.dom_ms.toFixed(1), f.overlay]);
out.drag = { axis: grab.axis, down_wall_ms: down_wall, first_proxy_move_ms: firstMoveWall, first_stage_a_ms: firstStageA, drag_wall_ms: drag_wall,
  raf_gaps: stats(rd.gaps), longtasks: rd.lt, drag_frames: dragFrames.length, overlays_applied: dragFrames.filter((f) => f.overlay !== false).length,
  core_ms: stats(dragFrames.map((f) => f.core_ms)), dom_ms: stats(dragFrames.map((f) => f.dom_ms)), obs_ms: stats(dragFrames.map((f) => f.obs_ms ?? 0)),
  mode: [...new Set(dragFrames.map((f) => f.mode))], stage_a_runs: (await page.evaluate(() => window.castplane_web.timings)).stage_a_runs - runs0,
  release: { up_wall_ms: up_wall, longtasks: ru.lt, raf_gaps: stats(ru.gaps) }, undo: (await page.evaluate(() => window.castplane_web.rig)).undo };
console.log("drag:", JSON.stringify(out.drag));

// ---- board ring drag (camera) for reference
const h = await page.evaluate(() => window.castplane_web.handles_px);
let bq = null;
if (h) for (const pt of h.ring) { if (pt === null) continue; const hit = await page.evaluate((pt) => window.castplane_web.hit_at(pt[0], pt[1]), pt); if (hit !== null && hit.kind === "ring") { bq = pt; break; } }
if (bq !== null) {
  await page.mouse.move(obox.x + bq[0], obox.y + bq[1]); await settle(300);
  m = await mark();
  await page.mouse.down();
  for (let i = 1; i <= 30; i++) { await page.mouse.move(obox.x + bq[0] + i * 3, obox.y + bq[1] + i * 0.7); await sleep(8); }
  const rb = await since(m); const mb = await mark();
  await page.mouse.up(); await settle(2500);
  const rbu = await since(mb);
  const fr = (await page.evaluate(() => window.castplane_web.frames)).filter((f) => f.dragging);
  out.camera_drag = { raf_gaps: stats(rb.gaps), longtasks: rb.lt, core_ms: stats(fr.map((f) => f.core_ms)), dom_ms: stats(fr.map((f) => f.dom_ms)), obs_ms: stats(fr.map((f) => f.obs_ms ?? 0)), release_longtasks: rbu.lt };
  console.log("camera_drag:", JSON.stringify(out.camera_drag));
}
out.status = await page.evaluate(() => document.getElementById("status").textContent);
console.log(out.status);
if (jsonOut) writeFileSync(jsonOut, JSON.stringify(out, null, 1));
await browser.close();

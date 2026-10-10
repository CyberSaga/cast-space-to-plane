// Dev helper (not a CI step, not a dependency): browser smoke check and `core ms` / `dom ms` measurement of the
// built web UI with Playwright + Chromium, using a Playwright installed outside the repository (global npm root).
//
//   npm run -w web build && (cd web && npx vite preview --port 4173 --strictPort) &
//   node web/scripts/smoke.mjs http://localhost:4173/ out/ [screenshot.png] [benchmarks/scenes/benchmark_100.json]
//   node web/scripts/smoke.mjs http://localhost:4173/ out/ --shots docs/images      # + the phase-2 screenshots
//
// Checks: the page loads the default example and renders the six overlay groups; the view toggles start at their
// defaults (horizon, objects, form_shadow, cast_shadow, labels and Hidden lines checked; construction / 作圖線 and
// 3D view unchecked, the three.js canvas hidden and never drawn) and keep the user's choices across example loads;
// every example's scene-camera SVG / JSON through the bundled core is written to out/<name>.svg / .json (compare them
// with the Python reference); a 30-step drag per example (a ring drag in the observer pane: the drawing pane is
// view-only) records the drag frames' `core ms` / `dom ms` and overlay mode (web/README.md); the optional scene file
// is loaded through the file picker and dragged likewise; a page-wide
// drop loads a scene; the three downloads are saved to out/; a non-JSON file and an invalid scene show the error
// panel. Phase 2 (contract §5.4.10): an example that fails to load (the path-only `mesh_demo`, the core has no loader)
// is reported and loaded instead from its Python expansion (`ts/test/fixtures/<name>.expanded.json`) through the file
// picker; the phase-2 checks load `wall_and_ground` (hidden lines on: the hidden sub-groups in the overlay, the
// "omit" style, the wall plate in the 3D view), `mesh_demo` (the house mesh) and `two_lights` (two light helpers, the
// per-light construction blocks, umbra pieces at rest and none during a drag), and with `--shots DIR` save
// DIR/web_ui_<name>.png for each. D80: the page opens in the edit view (observer pane shown, no 旁觀視角 checkbox);
// "預覽" hides the pane and widens the drawing pane without changing the drawing or the downloads, toggles back on a
// second click and on Esc, and a reload opens in the edit view whatever was stored. M9 (contract §5.6.9): for the
// five phase-1 examples (and the optional scene file) the observer pane is hidden and shown (預覽 pressed and
// released): the writer's SVG text, the overlay markup and the SVG / JSON downloads must be identical with the pane
// hidden and shown for the same camera; a 30-step ring drag of the drawing camera with
// the pane shown records `core ms` + `dom ms` + `obs ms` per frame (< 100 ms for the five examples); an observer drag must
// not change the drawing; the narrow (< 880 px) layout stacks the panes; switching off restores the drawing pane's
// size; framing keeps the eye and the frame in the pane; a right or middle drag does not move the observer; the three
// v8 `picture_plane` cases render the scene camera's document until an arrow drag (and again after "重設視角"); a frame
// below the ground is drawn. With `--shots DIR` it also saves DIR/web_ui_observer.png. M10 (contract §5.7.13, plane
// mode): the ring drag changes f and keeps g, D and |E − P|; the arrow drag changes g only; the drawing pane is
// view-only (a left, right, middle and Shift drag and the wheel there change neither the camera block, the readouts,
// the undo availability nor the drawing, show no error, and leave the wheel / pointer events' default actions to the
// browser: no preventDefault, default touch-action and cursor); the roll slider
// keeps the eye; the six views give exact axes; y=2 with D = 4 puts the eye at y = −2; a bad equation turns the field
// red and keeps the plane; undo and reset restore f, g, up (and the sliders); the eye is not draggable; the D slider
// keeps the board; an object click sets the pivot; Download scene writes the picture_plane form and reloads to the
// same SVG; the overlay is identical with the observer pane shown and hidden (預覽) for the same edited camera; 900 random rig
// states render finite. M11 step 1 (contract §5.8.5, §5.8.6, §5.8.11): the 重設視角 / 重做 / 重新取中心 buttons; undo and
// redo by button and by Ctrl / ⌘+Z and Ctrl / ⌘+Shift+Z (not in the equation field, not while previewing, Ctrl+Y unbound);
// a click selects an object and Esc clears it, Esc in 預覽 leaves it and keeps the selection; an object move (the
// `move_object` hook) and its undo / redo move neither P, E nor the observer and restore the same SVG; 整體顯示 frames
// the edited box; 重新取中心 per mode; 重設視角 takes the current centre, keeps the selection, and its undo restores P and the
// selector; a load clears the selection and the history. With `--shots DIR` it also saves DIR/web_ui_plane_mode.png. Prints one JSON record. Exit 1 on
// a page error or a failed check.
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

/** A point of the observer pane (pane px) near its centre that is not on a handle (M10: a drag there orbits the
 * observer). */
async function observer_blank() {
  return page.evaluate(() => {
    const el = document.getElementById("observer");
    const W = el.clientWidth, H = el.clientHeight;
    for (let k = 0; k < 400; k++) {
      const x = W / 2 + ((k % 20) - 10) * 18, y = H / 2 + (Math.floor(k / 20) - 10) * 18;
      if (window.castplane_web.hit_at(x, y) === null) return [x, y];
    }
    return [W / 2, H / 2];
  });
}

const failures = [];
const check = (ok, what) => { if (!ok) failures.push(what); };

/** A mouse drag of `steps` steps of `step` px from pane px `p` of `selector` (the observer: its centre region off the
 * handles when `p` is omitted, i.e. an observer orbit); `mid` runs after the first step with the button held. */
async function drag(steps, selector = "#observer", step = [3, 0.7], p = null, mid = null) {
  const box = await page.locator(selector).boundingBox();
  let x0 = box.x + box.width / 2, y0 = box.y + box.height / 2;
  if (p !== null) {
    x0 = box.x + p[0];
    y0 = box.y + p[1];
  } else if (selector === "#observer") {
    const [bx, by] = await observer_blank();
    x0 = box.x + bx;
    y0 = box.y + by;
  }
  await page.mouse.move(x0, y0);
  await page.mouse.down();
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(x0 + i * step[0], y0 + i * step[1]);
    await frames2();
    if (i === 1 && mid !== null) await mid();
  }
  await page.mouse.up();
  await frames2();
}

/** Observer-pane px of a hit-testable ring point with room for a `room` px drag to the right (null when none). */
async function ring_px(room = 100) {
  return page.evaluate((room) => {
    const h = window.castplane_web.handles_px;
    if (h === null) return null;
    const [W, H] = h.size;
    for (const q of h.ring) {
      if (q === null || q[0] < 60 || q[0] > W - room - 20 || q[1] < 60 || q[1] > H - 60) continue;
      if (Math.hypot(q[0] - h.tip[0], q[1] - h.tip[1]) < 40) continue;
      const hit = window.castplane_web.hit_at(q[0], q[1]);
      if (hit !== null && hit.kind === "ring") return q;
    }
    return null;
  }, room);
}

/** Switch the observer on (when off) for `body`, then back to the previous state. */
async function with_observer(body) {
  const was_on = await page.evaluate(() => window.castplane_web.observer?.on === true);
  if (!was_on) {
    await page.evaluate(() => window.castplane_web.set_observer(true));
    await frames2();
    await frames2();
  }
  try {
    return await body();
  } finally {
    if (!was_on) {
      await page.evaluate(() => window.castplane_web.set_observer(false));
      await frames2();
    }
  }
}

/** A drag of the drawing camera: the orange ring in the observer pane (the drawing pane is view-only), `steps` steps
 * of `step` px; `mid` runs after the first step with the button held. */
async function camera_drag(steps, step = [3, 0.7], mid = null) {
  await with_observer(async () => {
    const q = await ring_px(Math.abs(steps * step[0]));
    check(q !== null, "a ring point is hit-testable for a camera drag");
    if (q !== null) await drag(steps, "#observer", step, q, mid);
  });
}

/** An arrow drag in the observer pane: from the tip by `k` arrow lengths towards Q (k > 0: the board towards the
 * scene, g decreases), at least 30 px, in `n` steps. */
async function arrow_push(k, n = 8) {
  const h = await page.evaluate(() => window.castplane_web.handles_px);
  let dx = (h.Q[0] - h.tip[0]) * k, dy = (h.Q[1] - h.tip[1]) * k;
  const l = Math.hypot(dx, dy);
  if (l < 30) {
    const s = 30 / Math.max(l, 1e-9);
    [dx, dy] = l < 1e-9 ? [0, 30 * Math.sign(k)] : [dx * s, dy * s];
  }
  await drag(n, "#observer", [dx / n, dy / n], h.tip);
}

async function drag_stats() {
  await camera_drag(30);
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

// the view toggles are page-level: their defaults at page load, kept (not reset from the scene) across loads
const toggles = () => page.evaluate(() => {
  const gl = document.getElementById("gl");
  // the three.js canvas was never drawn while "3D view" is off: its buffer is still fully transparent
  const c = document.createElement("canvas");
  c.width = gl.width;
  c.height = gl.height;
  const g = c.getContext("2d");
  g.drawImage(gl, 0, 0);
  const d = g.getImageData(0, 0, c.width, c.height).data;
  let blank = true;
  for (let i = 3; i < d.length; i += 4 * 61) if (d[i] !== 0) { blank = false; break; }
  const constr = document.querySelector('svg.overlay g[id="construction"]');
  return {
    layers: Object.fromEntries([...document.querySelectorAll("#layers input[data-layer]")].map((b) => [b.dataset.layer, b.checked])),
    construction_lines: document.getElementById("construction-lines").checked,
    hidden_lines: document.getElementById("hidden-lines").checked,
    hidden_style_enabled: !document.getElementById("hidden-style").disabled,
    view3d: document.getElementById("view3d").checked,
    canvas_hidden: gl.classList.contains("hidden") && getComputedStyle(gl).visibility === "hidden",
    gl_blank: blank,
    doc_hidden_lines: window.castplane_web.doc_summary?.hidden_lines ?? null,
    construction_shown: constr !== null && getComputedStyle(constr).display !== "none",
  };
});
const DEFAULT_LAYERS = { horizon: true, objects: true, form_shadow: true, cast_shadow: true, construction: false, labels: true };
const is_default = (t) => JSON.stringify(t.layers) === JSON.stringify(DEFAULT_LAYERS) && !t.construction_lines && t.hidden_lines
  && t.hidden_style_enabled && !t.view3d && t.canvas_hidden && !t.construction_shown && t.doc_hidden_lines === true;
const toggle_checks = {};
{
  toggle_checks.page_load = await toggles();
  check(is_default(toggle_checks.page_load), `toggles: the page-load defaults (${JSON.stringify(toggle_checks.page_load)})`);
  check(toggle_checks.page_load.gl_blank, "toggles: with 3D view off the three.js canvas is never drawn");
  // the user's choices survive a load: labels off, construction on (through 作圖線), hidden lines off, 3D view on;
  // wall_and_ground's own output has hidden_lines true and all six layers
  await page.click('#layers input[data-layer="labels"]');
  await page.click("#construction-lines");
  await page.click("#hidden-lines");
  await page.click("#view3d");
  await page.evaluate(() => window.castplane_web.load_example("wall_and_ground"));
  await frames2();
  await frames2();
  const kept = toggle_checks.user_choice_after_load = await toggles();
  check(!kept.layers.labels && kept.layers.construction && kept.construction_lines && kept.construction_shown && !kept.hidden_lines
    && !kept.hidden_style_enabled && kept.view3d && !kept.canvas_hidden && !kept.gl_blank && kept.doc_hidden_lines === false,
  `toggles: a load keeps the user's choices (${JSON.stringify(kept)})`);
  // back to the defaults, then a scene whose output differs (basic: no hidden_lines) does not reset them either
  await page.click('#layers input[data-layer="labels"]');
  await page.click("#construction-lines");
  await page.click("#hidden-lines");
  await page.click("#view3d");
  await page.evaluate(() => window.castplane_web.load_example("basic"));
  await frames2();
  await frames2();
  const back = toggle_checks.after_another_example = await toggles();
  check(is_default(back), `toggles: the defaults after loading another example (${JSON.stringify(back)})`);
}

// D80: the page opens in the edit view (the observer pane shown); "預覽" hides the pane (the drawing pane takes the
// full width, the drawing unchanged) and toggles back on a second click or Esc; nothing is remembered across visits
const preview_state = () => page.evaluate(() => {
  const b = document.getElementById("preview");
  return {
    observer_shown: !document.getElementById("observer").hidden,
    controls_shown: !document.getElementById("observer-controls").hidden,
    pressed: b.getAttribute("aria-pressed"), label: b.textContent,
    obs_ms: document.getElementById("status").textContent.includes("obs ms"),
    no_checkbox: document.getElementById("observer-on") === null,
    stage_w: document.getElementById("stage").getBoundingClientRect().width,
    svg: window.castplane_web.svg, dl: JSON.stringify(window.castplane_web.download_texts()),
  };
});
const edit_view = (s) => s.observer_shown && s.controls_shown && s.pressed === "false" && s.label === "預覽" && s.obs_ms
  && s.no_checkbox;
const preview_view = (s) => !s.observer_shown && !s.controls_shown && s.pressed === "true" && s.label === "返回編輯"
  && !s.obs_ms && s.no_checkbox;
const preview_checks = {};
{
  const brief = (s) => ({ ...s, svg: s.svg.length, dl: s.dl.length });
  const edit0 = await preview_state();
  preview_checks.page_load = brief(edit0);
  check(edit_view(edit0), `preview: the page opens in the edit view (${JSON.stringify(brief(edit0))})`);
  await page.click("#preview");
  await frames2();
  await frames2();
  const pv = await preview_state();
  preview_checks.preview = brief(pv);
  check(preview_view(pv) && pv.stage_w > edit0.stage_w, `preview: 預覽 hides the observer pane, the drawing widens (${JSON.stringify(brief(pv))})`);
  check(pv.svg === edit0.svg && pv.dl === edit0.dl, "preview: the drawing and the downloads are unchanged by 預覽");
  await page.keyboard.press("Escape");
  await frames2();
  await frames2();
  const esc = await preview_state();
  check(edit_view(esc) && esc.stage_w === edit0.stage_w && esc.svg === edit0.svg, "preview: Esc returns to the edit view");
  await page.click("#preview");
  await frames2();
  await page.click("#preview");
  await frames2();
  await frames2();
  check(edit_view(await preview_state()), "preview: a second click (返回編輯) returns to the edit view");
  // the old stored switch state is ignored: a visit that left the observer off still opens in the edit view
  await page.evaluate(() => localStorage.setItem("castplane.observer", "0"));
  await page.click("#preview");
  await page.reload();
  await page.waitForFunction(() => document.getElementById("status").textContent.includes("core ms"), null, { timeout: 30000 });
  await frames2();
  await frames2();
  const again = await preview_state();
  preview_checks.after_reload = brief(again);
  check(edit_view(again), `preview: a reload opens in the edit view whatever was stored (${JSON.stringify(brief(again))})`);
  check(is_default(await toggles()), "preview: the toggles are the defaults after a reload");
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
toggle_checks.after_every_example = await toggles();
check(is_default(toggle_checks.after_every_example), "toggles: still the defaults after loading every example");

// phase 2 (§5.4.10): receivers, mesh objects, several lights, the hidden-line switch and style
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
  check(s.hidden.lines === true && s.hidden.style === "dashed", "wall_and_ground: hidden lines on (page default), dashed (from the scene)");
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
  check(s.hidden.lines === false && s.doc.hidden_lines === false, "mesh_demo: hidden lines stay off after the user switched them off");
  await page.evaluate(() => window.castplane_web.set_hidden(true)); // back to the page default
  await frames2();
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
  // during a drag (the ring in the observer pane) the umbra is skipped (§5.4.11), the resting frame recomputes it
  let during = null;
  await camera_drag(2, [10, 2], async () => { during = await ui(); });
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
  check(obs.labels.length === 6 && obs.labels[0].startsWith("E（讀數）") && obs.labels[5] === "板子距離", `${name}: observer labels`);
  {
    // aspect-aware framing (§5.6 implementation notes): after the load the eye and the frame corners are in the pane
    const [W, H] = obs.size;
    const inside = (p) => p !== null && p[0] >= 0 && p[0] <= W && p[1] >= 0 && p[1] <= H;
    check(obs.px !== null && inside(obs.px.E) && obs.px.corners.every(inside), `${name}: framing keeps E and the frame in the ${W}x${H} pane`);
  }
  // a drag of the drawing camera (the ring) with the observer on: per-frame core + dom + obs
  await page.evaluate(() => { window.castplane_web.frames.length = 0; });
  await camera_drag(30);
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
  {
    // the observer has a left drag only (§5.6.4): a right or middle drag leaves its view unchanged
    for (const button of ["right", "middle"]) {
      const v0 = JSON.stringify((await page.evaluate(() => window.castplane_web.observer)).view);
      const x0 = obox.x + obox.width / 2, y0 = obox.y + obox.height / 2;
      await page.mouse.move(x0, y0);
      await page.mouse.down({ button });
      for (let i = 1; i <= 5; i++) {
        await page.mouse.move(x0 + 16 * i, y0 + 6 * i);
        await frames2();
      }
      await page.mouse.up({ button });
      await frames2();
      const v1 = JSON.stringify((await page.evaluate(() => window.castplane_web.observer)).view);
      check(v0 === v1, `${name}: a ${button} drag in the observer does not move it`);
    }
  }
  // switching off restores the §5.4.10 page: the drawing pane's size and the same drawing
  await page.evaluate(() => window.castplane_web.set_observer(false));
  await frames2();
  const off2 = await drawing();
  const hidden = await page.evaluate(() => document.getElementById("observer").hidden
    && document.getElementById("observer-controls").hidden && !document.getElementById("status").textContent.includes("obs ms"));
  check(hidden, `${name}: 預覽 hides the observer pane, its controls and obs ms`);
  check(same_drawing(before, off2) && off2.stage.width === off.stage.width && off2.stage.height === off.stage.height,
    `${name}: 預覽 restores the drawing pane`);
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
  // the comparisons with the scene camera's document below use the scenes' own hidden_lines (off): the page-level
  // "Hidden lines" checkbox (on by default) is switched off for them and back on at the end
  await page.evaluate(() => window.castplane_web.set_hidden(false));
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
  check(observer.picture_plane.same_as_scene_camera, "picture_plane: the scene camera's SVG");
  // the three v8 cases: until the drawing camera is edited the scene's own block is rendered, so the document and the
  // warnings are the CLI's (no CAMERA_LOOKING_ALONG_UP for the horizontal board); after a drag the rig's
  // picture_plane block (M10); 重設視角 returns to the scene's block (§5.6, §5.7 implementation notes)
  observer.picture_plane_cases = {};
  for (const name of ["camera_picture_plane_horizontal", "camera_picture_plane_vertical", "camera_picture_plane_tilted"]) {
    const text = readFileSync(join(ROOT, "tests", "conformance", "cases", `${name}.json`), "utf-8");
    await page.evaluate(([n, t]) => window.castplane_web.load_text(n, t), [name, text]);
    await frames2();
    await frames2();
    const snap = () => page.evaluate(() => ({ ref: window.castplane_web.reference_render(), dl: window.castplane_web.download_texts(),
      svg: window.castplane_web.svg, camera: window.castplane_web.camera,
      rows: [...document.querySelectorAll("#warnings tbody tr")].map((tr) => tr.textContent) }));
    const a = await snap();
    const expected = JSON.parse(readFileSync(join(ROOT, "tests", "conformance", "expected", `${name}.json`), "utf-8"));
    const doc = JSON.parse(a.dl.json);
    check(a.dl.json === a.ref.json + "\n" && a.svg === a.ref.svg, `${name}: the loaded page renders the scene camera's document`);
    check(JSON.stringify(doc.warnings) === JSON.stringify(expected.warnings) && doc.camera.picture_plane !== undefined
      && a.camera.picture_plane !== undefined && !a.rows.some((r) => r.includes("CAMERA_LOOKING_ALONG_UP")),
    `${name}: warnings and camera.picture_plane as in the expected file`);
    await arrow_push(0.5); // the arrow (g changes, so the eye moves whatever the board's direction)
    const b = await snap();
    check(b.camera.target === undefined && b.camera.picture_plane !== undefined
      && JSON.stringify(b.camera.position) !== JSON.stringify(a.camera.position), `${name}: a drag switches to the rig's picture_plane block`);
    await page.click("#reset");
    await frames2();
    await frames2();
    const c = await snap();
    check(c.dl.json === a.dl.json && c.camera.picture_plane !== undefined, `${name}: 重設視角 returns to the scene's block`);
    observer.picture_plane_cases[name] = { warnings: doc.warnings.map((w) => w.code), after_drag: JSON.parse(b.dl.json).warnings.map((w) => w.code) };
  }
  // a frame below the ground (E at z = 0.3 looking down): the receiver plates do not hide the board (§5.6.5)
  const low = JSON.parse(readFileSync(join(ROOT, "examples", "basic.json"), "utf-8"));
  low.camera.position = [0, -1, 0.3];
  low.camera.target = [0, 3, -2];
  await page.evaluate((text) => window.castplane_web.load_text("frame_below_ground", text), JSON.stringify(low));
  await frames2();
  await frames2();
  const lowObs = await page.evaluate(() => window.castplane_web.observer);
  const [c0, c1] = lowObs.px.corners;
  const blue = await page.evaluate(([x, y]) => {
    const gl = document.getElementById("obs-gl");
    const k = gl.width / gl.clientWidth;
    const c = document.createElement("canvas");
    c.width = gl.width;
    c.height = gl.height;
    const g = c.getContext("2d");
    g.drawImage(gl, 0, 0);
    const d = g.getImageData(Math.round(x * k) - 4, Math.round(y * k) - 4, 9, 9).data;
    let best = -255;
    for (let i = 0; i < d.length; i += 4) best = Math.max(best, d[i + 2] - d[i]);
    return best;
  }, [(c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2]);
  observer.below_ground = { frame_bottom_mid_blue_minus_red: blue };
  check(blue > 50, `frame below the ground: the frame's bottom edge is drawn (blue − red ${blue})`);
  await page.evaluate(() => window.castplane_web.set_observer(false));
  await page.evaluate(() => window.castplane_web.set_hidden(true));
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

// M10 (contract §5.7.13): plane mode
const plane = {};
{
  const rig = () => page.evaluate(() => window.castplane_web.rig);
  const near = (a, b, tol) => Math.abs(a - b) <= tol;
  const near3 = (a, b, tol) => a.every((x, i) => near(x, b[i], tol));
  const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
  await page.evaluate(() => window.castplane_web.load_example("basic"));
  await page.evaluate(() => window.castplane_web.set_observer(true));
  await frames2();
  await frames2();
  const ob = await page.locator("#observer").boundingBox();
  /** A mouse drag in the observer pane from pane px `p` by `(dx, dy)` in `n` steps. */
  async function obs_drag(p, dx, dy, n = 8, opts = {}) {
    await page.mouse.move(ob.x + p[0], ob.y + p[1]);
    await page.mouse.down(opts);
    for (let i = 1; i <= n; i++) {
      await page.mouse.move(ob.x + p[0] + (dx * i) / n, ob.y + p[1] + (dy * i) / n);
      await frames2();
    }
    await page.mouse.up(opts);
    await frames2();
  }
  const sbox = await page.locator("#stage").boundingBox();
  /** A mouse drag on the drawing pane (view-only) by `(dx, dy)` in 8 steps. */
  async function stage_drag(dx, dy, opts = {}, shift = false) {
    const x0 = sbox.x + sbox.width / 2, y0 = sbox.y + sbox.height / 2;
    if (shift) await page.keyboard.down("Shift");
    await page.mouse.move(x0, y0);
    await page.mouse.down(opts);
    for (let i = 1; i <= 8; i++) {
      await page.mouse.move(x0 + (dx * i) / 8, y0 + (dy * i) / 8);
      await frames2();
    }
    await page.mouse.up(opts);
    if (shift) await page.keyboard.up("Shift");
    await frames2();
  }
  const r0 = await rig();
  check(r0.scene_block && r0.undo === 0 && r0.up === null, "plane: the loaded scene renders its own camera, lock-horizontal");
  {
    // ring: grab a visible ring point inside the pane, drag 60 px right
    const h = await page.evaluate(() => window.castplane_web.handles_px);
    const [Wp, Hp] = h.size;
    let k = -1;
    for (let i = 0; i < h.ring.length; i++) {
      const q = h.ring[i];
      if (q === null || q[0] < 60 || q[0] > Wp - 100 || q[1] < 60 || q[1] > Hp - 60) continue;
      if (Math.hypot(q[0] - h.tip[0], q[1] - h.tip[1]) < 40) continue;
      const hit = await page.evaluate(([x, y]) => window.castplane_web.hit_at(x, y), q);
      if (hit !== null && hit.kind === "ring") { k = i; break; }
    }
    check(k >= 0, "plane: a ring point is hit-testable");
    const svg0 = await page.evaluate(() => window.castplane_web.svg);
    await obs_drag(h.ring[k], 60, 0);
    const r1 = await rig();
    plane.ring = { from: r0.f, to: r1.f, g: [r0.g, r1.g], undo: r1.undo };
    check(!near3(r1.f, r0.f, 1e-6) && r1.g === r0.g && r1.D === r0.D && near(dist(r1.E, r1.P), dist(r0.E, r0.P), 1e-9)
      && r1.undo === 1 && !r1.scene_block, "plane: the ring drag changes f, keeps g, D and |E − P| (one undo step)");
    check(svg0 !== await page.evaluate(() => window.castplane_web.svg), "plane: the ring drag changes the drawing");
    check(r1.readouts.at(-1).startsWith("這次拖動右窗畫面變動：") && r1.delta > 0.005, "plane: the picture-delta readout");
    // arrow: the tip, dragged 40 px up-right
    const h2 = await page.evaluate(() => window.castplane_web.handles_px);
    const hit = await page.evaluate(([x, y]) => window.castplane_web.hit_at(x, y), h2.tip);
    check(hit !== null && hit.kind === "arrow", "plane: the arrow tip wins the hit test");
    await obs_drag(h2.tip, 30, -25);
    const r2 = await rig();
    plane.arrow = { g: [r1.g, r2.g], E: [r1.E, r2.E] };
    check(r2.g !== r1.g && near3(r2.f, r1.f, 0) && r2.D === r1.D && r2.a === r1.a && r2.b === r1.b && r2.roll_deg === r1.roll_deg
      && r2.undo === 2, "plane: the arrow drag changes g only (one undo step)");
    const dE = [r2.E[0] - r1.E[0], r2.E[1] - r1.E[1], r2.E[2] - r1.E[2]];
    const along = dE[0] * r1.f[0] + dE[1] * r1.f[1] + dE[2] * r1.f[2];
    check(near(Math.hypot(...dE), Math.abs(along), 1e-9), "plane: the arrow moves the eye along f only");
    // the eye is never a handle: a drag on it orbits the observer and leaves the rig alone
    const h3 = await page.evaluate(() => window.castplane_web.handles_px);
    check(await page.evaluate(([x, y]) => window.castplane_web.hit_at(x, y), h3.E) === null, "plane: the hit test never returns E");
    const v0 = (await page.evaluate(() => window.castplane_web.observer)).view;
    await obs_drag(h3.E, 25, 10);
    const r3 = await rig();
    const v1 = (await page.evaluate(() => window.castplane_web.observer)).view;
    check(JSON.stringify(r3) === JSON.stringify(r2) && v1.az_deg !== v0.az_deg, "plane: a drag on the eye orbits the observer only");
  }
  {
    // the drawing pane is view-only: a left, right, middle and Shift drag and the wheel there change nothing (camera
    // block, rig, readouts, undo availability, drawing), show no error or notice, and do not take the browser's default
    // actions (no preventDefault on wheel / pointer / contextmenu; default touch-action and cursor)
    const view_state = () => page.evaluate(() => ({
      camera: JSON.stringify(window.castplane_web.camera), rig: JSON.stringify(window.castplane_web.rig),
      readouts: document.getElementById("readouts").textContent, notices: document.getElementById("notices").textContent,
      undo_disabled: document.getElementById("undo").disabled, svg: window.castplane_web.svg,
      error_hidden: document.getElementById("error").hidden, error: document.getElementById("error").textContent,
      frames: window.castplane_web.frames.length,
    }));
    const a = await view_state();
    check(!a.undo_disabled, "plane: undo is available before the drawing-pane checks (the ring and arrow drags)");
    const n_logs = logs.length;
    const gestures = [["left drag", () => stage_drag(50, 20)], ["right drag", () => stage_drag(40, -20, { button: "right" })],
      ["middle drag", () => stage_drag(-30, 15, { button: "middle" })], ["Shift drag", () => stage_drag(-30, 15, {}, true)],
      ["wheel", async () => {
        await page.mouse.move(sbox.x + sbox.width / 2, sbox.y + sbox.height / 2);
        await page.mouse.wheel(0, 300);
        await frames2();
        await page.mouse.wheel(0, -300);
        await frames2();
      }]];
    plane.view_only = {};
    for (const [what, run] of gestures) {
      await run();
      await frames2();
      const b = await view_state();
      const same = ["camera", "rig", "readouts", "notices", "undo_disabled", "svg", "error_hidden", "error"].every((k) => a[k] === b[k]);
      plane.view_only[what] = same;
      check(same && b.frames === a.frames, `plane: a ${what} on the drawing pane changes nothing`);
    }
    check(logs.length === n_logs, `plane: the drawing-pane gestures log nothing (${logs.slice(n_logs).join(" | ")})`);
    // default actions stay with the browser; the stage keeps the default touch-action and cursor
    const defaults = await page.evaluate(() => {
      const st = document.getElementById("stage");
      const fire = (ev) => { st.dispatchEvent(ev); return ev.defaultPrevented; };
      return {
        wheel: fire(new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true })),
        pointerdown: fire(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 })),
        contextmenu: fire(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, button: 2 })),
        touch_action: getComputedStyle(st).touchAction, cursor: getComputedStyle(st).cursor,
        observer_touch_action: getComputedStyle(document.getElementById("observer")).touchAction,
      };
    });
    plane.view_only.defaults = defaults;
    check(!defaults.wheel && !defaults.pointerdown && !defaults.contextmenu, `plane: no preventDefault on the drawing pane (${JSON.stringify(defaults)})`);
    check(defaults.touch_action === "auto" && defaults.cursor === "auto" && defaults.observer_touch_action === "none",
      `plane: the drawing pane keeps the default touch-action and cursor (${JSON.stringify(defaults)})`);
    const c = await view_state();
    check(c.camera === a.camera && c.rig === a.rig, "plane: synthetic events on the drawing pane change nothing");
  }
  {
    // roll slider: the eye does not move; not an undo step
    const a = await rig();
    await page.evaluate(() => { const el = document.getElementById("roll"); el.value = "30"; el.dispatchEvent(new Event("input")); });
    await frames2();
    const b = await rig();
    check(b.roll_deg === 30 && near3(b.E, a.E, 1e-9) && b.undo === a.undo, "plane: the roll slider keeps the eye, no undo step");
    const cam = await page.evaluate(() => window.castplane_web.camera);
    check(cam.picture_plane !== undefined && Array.isArray(cam.picture_plane.up), "plane: with roll the block carries up");
    // D slider: the board stays, the eye moves along −f
    await page.evaluate(() => { const el = document.getElementById("dist"); el.value = "6"; el.dispatchEvent(new Event("input")); });
    await frames2();
    const c = await rig();
    check(c.D === 6 && c.g === b.g && near(c.c, b.c, 1e-12) && c.undo === b.undo && near(dist(c.E, b.E), 2, 1e-9),
      "plane: the D slider keeps the board (g, c), moves the eye by ΔD, no undo step");
    await page.evaluate(() => { const el = document.getElementById("dist"); el.value = "4"; el.dispatchEvent(new Event("input")); });
    await page.evaluate(() => { const el = document.getElementById("roll"); el.value = "0"; el.dispatchEvent(new Event("input")); });
    await frames2();
    const cam2 = await page.evaluate(() => window.castplane_web.camera);
    check(cam2.picture_plane.up === undefined, "plane: lock-horizontal and roll 0 omit up");
  }
  {
    // six views: exact axes, g kept, E = P − (g + D)·f
    const axes = { front: [0, 1, 0], back: [0, -1, 0], left: [1, 0, 0], right: [-1, 0, 0], top: [0, 0, -1], bottom: [0, 0, 1] };
    plane.views = {};
    for (const [name, ax] of Object.entries(axes)) {
      const a = await rig();
      await page.click(`#views button[data-view="${name}"]`);
      await frames2();
      const b = await rig();
      const E = [0, 1, 2].map((i) => b.P[i] - (b.g + b.D) * b.f[i]);
      plane.views[name] = b.equation;
      check(JSON.stringify(b.f) === JSON.stringify(ax) && b.g === a.g && near3(b.E, E, 1e-9) && b.a === 0 && b.b === 0,
        `plane: view ${name} gives f = ${ax}`);
    }
  }
  {
    // equation: y=2 with D = 4 and the scene-centre pivot: the eye at y = −2
    const a = await rig();
    await page.fill("#equation", "y=2");
    await page.press("#equation", "Enter");
    await frames2();
    const b = await rig();
    plane.equation = { E: b.E, equation: b.equation };
    check(b.D === 4 && b.pivot.mode === "scene" && near(b.E[1], -2, 1e-9) && b.equation === "y = 2.00" && b.undo === a.undo + 1,
      "plane: y=2 with D = 4 puts the eye at y = −2");
    await page.fill("#equation", "x==1");
    await page.press("#equation", "Enter");
    await frames2();
    const c = await rig(), fld = await page.evaluate(() => window.castplane_web.equation_field);
    check(fld.bad && fld.error !== null && c.equation === b.equation && c.undo === b.undo, "plane: a bad equation turns red, the plane is kept");
    // 「套用」 applies the typed text (the field keeps it until the click)
    await page.fill("#equation", "y = -2.5");
    await page.click("#equation-apply");
    await frames2();
    const c2 = await rig();
    check(c2.equation === "y = -2.50" && c2.undo === c.undo + 1, "plane: 「套用」 applies the typed equation");
    await page.click('#quick-equations button[data-eq="x=1"]');
    await frames2();
    const d = await rig(), fld2 = await page.evaluate(() => window.castplane_web.equation_field);
    check(d.equation === "x = 1.00" && !fld2.bad, "plane: the quick button x=1 applies its own text");
    // undo restores f, g, up and the sliders; reset restores the loaded state
    await page.click("#undo");
    await frames2();
    const e = await rig();
    check(JSON.stringify(e.f) === JSON.stringify(c2.f) && e.g === c2.g && e.up === c2.up && e.equation === "y = -2.50",
      "plane: undo restores f, g, up");
    await page.evaluate(() => { const el = document.getElementById("focal"); el.value = "0.8"; el.dispatchEvent(new Event("input")); });
    await page.click("#lock-level");
    await frames2();
    const f2 = await rig();
    check(f2.up !== null && f2.focal !== r0.focal, "plane: lock off, focal changed");
    await page.click("#reset");
    await frames2();
    const g2 = await rig();
    const ui_focal = await page.evaluate(() => document.getElementById("focal-out").value);
    check(JSON.stringify(g2.f) === JSON.stringify(r0.f) && g2.g === r0.g && g2.up === null && g2.focal === r0.focal && g2.D === r0.D
      && g2.scene_block && ui_focal === `${r0.focal.toFixed(1)} mm` && await page.evaluate(() => document.getElementById("lock-level").checked),
    "plane: reset restores f, g, up, focal, D, the sliders and the scene camera's block");
  }
  {
    // object pivot: pick an object with a click in the observer; not an undo step; the eye faces it (pan cleared)
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    const a = await rig();
    const objs = await page.evaluate(() => window.castplane_web.objects_px);
    const [id, px] = Object.entries(objs).find(([, p]) => p !== null);
    await page.mouse.click(ob.x + px[0], ob.y + px[1]);
    await frames2();
    await frames2();
    const b = await rig();
    plane.pivot = { clicked: id, picked: b.pivot.object_id };
    check(b.pivot.object_id !== null && b.a === 0 && b.b === 0 && b.undo === a.undo && b.f.join() === a.f.join() && b.g === a.g,
      "plane: a click picks the object pivot (pan cleared, no undo step)");
    const labels = (await page.evaluate(() => window.castplane_web.observer)).labels;
    check(labels.includes(`旋轉中心：${b.pivot.object_id}`), "plane: the pivot label names the object");
    await page.selectOption("#pivot-mode", "scene");
    await frames2();
  }
  {
    // M10 review fixes. A scene loaded while a ring drag is held: the held drag does not reach the new scene
    const q = await ring_px(60);
    check(q !== null, "plane: a ring point for the held drag");
    await page.mouse.move(ob.x + q[0], ob.y + q[1]);
    await page.mouse.down();
    await page.mouse.move(ob.x + q[0] + 25, ob.y + q[1] + 5);
    await frames2();
    await page.evaluate(() => window.castplane_web.load_example("curved_demo"));
    await frames2();
    const c0 = await rig();
    await page.mouse.move(ob.x + q[0] + 60, ob.y + q[1] + 10);
    await frames2();
    await page.mouse.up();
    await frames2();
    const c1 = await rig();
    check(c0.scene_block && JSON.stringify(c1) === JSON.stringify(c0), "plane: a drag held across a scene load leaves the new scene alone");
    // an object whose id contains ':' can be picked as the pivot
    const data = JSON.parse(readFileSync(join(ROOT, "examples", "basic.json"), "utf-8"));
    data.objects[0].id = "crate:1";
    await page.evaluate((t) => window.castplane_web.load_text("basic_colon", t), JSON.stringify(data));
    await frames2();
    await frames2();
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    const px = (await page.evaluate(() => window.castplane_web.objects_px))["crate:1"];
    await page.mouse.click(ob.x + px[0], ob.y + px[1]);
    await frames2();
    check((await rig()).pivot.object_id === "crate:1", "plane: an object id with ':' is pickable");
    // switching the pivot mode alone keeps the pan (the pivot point did not move); basic's load rule gives a pan
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await frames2();
    await frames2();
    const p0 = await rig();
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    const p1 = await rig();
    check((p0.a !== 0 || p0.b !== 0) && p1.a === p0.a && p1.b === p0.b && near3(p1.E, p0.E, 0),
      "plane: switching to object mode without a pick keeps the pan and the eye");
    await page.selectOption("#pivot-mode", "scene");
    await frames2();
    // a rejected equation: leaving the field restores the plane's text and clears the error
    await page.fill("#equation", "x==1");
    await page.press("#equation", "Enter");
    await page.evaluate(() => document.getElementById("equation").blur());
    await frames2();
    const fld = await page.evaluate(() => ({ ...window.castplane_web.equation_field,
      aria: document.getElementById("equation").getAttribute("aria-invalid"),
      msg: document.getElementById("equation-error").textContent }));
    check(!fld.bad && fld.error === null && fld.aria === "false" && fld.msg === "" && fld.value === (await rig()).equation,
      "plane: blurring a rejected equation clears its error");
    // a D slider dragged into its clamped range: the thumb goes to the clamped value at release (the arrow first
    // pulls the board towards the scene until R hits its 0.8 m clamp)
    await arrow_push(5, 10);
    const q0 = await rig();
    const dbox = await page.locator("#dist").boundingBox();
    await page.mouse.move(dbox.x + dbox.width / 2, dbox.y + dbox.height / 2);
    await page.mouse.down();
    await page.mouse.move(dbox.x - 20, dbox.y + dbox.height / 2, { steps: 6 });
    await page.mouse.up();
    await frames2();
    const q1 = await rig();
    const thumb = await page.evaluate(() => document.getElementById("dist").value);
    plane.d_clamp = { R: q0.R, D: q1.D, thumb };
    check(q0.R < 1 && q1.D > 0.5 && Number(thumb) === q1.D, "plane: the D slider's thumb shows the clamped value after a drag");
    // hovering the arrow tip shows the pointer cursor on the canvas under the mouse
    await page.click("#reset");
    await frames2();
    await frames2();
    const h = await page.evaluate(() => window.castplane_web.handles_px);
    await page.mouse.move(ob.x + h.tip[0], ob.y + h.tip[1]);
    await frames2();
    const cur = await page.evaluate(([x, y]) => getComputedStyle(document.elementFromPoint(x, y)).cursor, [ob.x + h.tip[0], ob.y + h.tip[1]]);
    check(cur === "pointer", `plane: hovering the arrow tip shows the pointer cursor (${cur})`);
    await page.mouse.move(ob.x + 4, ob.y + 4);
    // observer labels do not overlap (spec-v0.2 §3: each label readable)
    const overlaps = await page.evaluate(() => {
      const r = [...document.querySelectorAll(".obs-label")].filter((e) => !e.hidden).map((e) => [e.textContent, e.getBoundingClientRect()]);
      const out = [];
      for (let i = 0; i < r.length; i++) for (let j = 0; j < i; j++) {
        const [ta, a] = r[i], [tb, b] = r[j];
        if (a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom) out.push([ta, tb]);
      }
      return out;
    });
    plane.label_overlaps = overlaps;
    check(overlaps.length === 0, `plane: the observer labels do not overlap (${JSON.stringify(overlaps)})`);
  }
  {
    // M11 step 1 (contract §5.8.5, §5.8.6, §5.8.11): 重設視角, 重新取中心, redo and the shortcuts, Esc and the
    // selection, the pivot as a value (an object edit moves neither P nor the observer)
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await frames2();
    await frames2();
    const m11 = {};
    plane.m11 = m11;
    const btn = () => page.evaluate(() => Object.fromEntries(["undo", "redo", "reset", "recenter"].map((id) => {
      const el = document.getElementById(id);
      return [id, { text: el.textContent, disabled: el.disabled }];
    })));
    const ui0 = await btn();
    const beside = await page.evaluate(() => document.getElementById("recenter").previousElementSibling.contains(document.getElementById("pivot-mode")));
    m11.buttons = ui0;
    check(ui0.reset.text === "重設視角" && ui0.redo.text === "重做" && ui0.recenter.text === "重新取中心" && beside,
      "m11: the buttons 重設視角 (id reset), 重做 and 重新取中心 beside the pivot selector");
    check(ui0.undo.disabled && ui0.redo.disabled && !ui0.reset.disabled && !ui0.recenter.disabled, "m11: undo and redo disabled on load");
    // a board step; undo and redo by button
    const s0 = await rig();
    await page.click('#views button[data-view="top"]');
    await frames2();
    const s1 = await rig();
    await page.click("#undo");
    await frames2();
    const s2 = await rig(), ui2 = await btn();
    check(s2.f.join() === s0.f.join() && s2.undo === 0 && s2.redo === 1 && !ui2.redo.disabled && ui2.undo.disabled, "m11: undo moves the step to redo");
    await page.click("#redo");
    await frames2();
    const s3 = await rig();
    check(s3.f.join() === s1.f.join() && s3.undo === 1 && s3.redo === 0, "m11: redo re-applies the board step");
    // the shortcuts: Ctrl+Z, Ctrl+Shift+Z and their ⌘ forms; not with the focus in the equation field
    const keyed = [];
    for (const [combo, want] of [["Control+z", [0, 1]], ["Control+Shift+Z", [1, 0]], ["Meta+z", [0, 1]], ["Meta+Shift+Z", [1, 0]]]) {
      await page.keyboard.press(combo);
      await frames2();
      const r = await rig();
      keyed.push([combo, r.undo, r.redo]);
      check(r.undo === want[0] && r.redo === want[1], `m11: ${combo} (${r.undo}/${r.redo})`);
    }
    m11.keys = keyed;
    await page.focus("#equation");
    await page.keyboard.press("Control+z");
    await frames2();
    const s4 = await rig();
    check(s4.undo === 1 && s4.redo === 0 && s4.f.join() === s1.f.join(), "m11: Ctrl+Z in the equation field is the field's (no undo)");
    await page.evaluate(() => document.getElementById("equation").blur());
    await page.keyboard.press("Control+y");
    await frames2();
    check((await rig()).undo === 1, "m11: Ctrl+Y is not bound");
    // the selection: a click on an object selects it (P not taken in 場景中心); Esc clears it
    const objs = await page.evaluate(() => window.castplane_web.objects_px);
    const click_obj = async (id) => {
      const p = (await page.evaluate(() => window.castplane_web.objects_px))[id];
      await page.mouse.click(ob.x + p[0], ob.y + p[1]);
      await frames2();
    };
    check(objs["crate"] !== null && objs["pillar"] !== null, "m11: the objects are in the observer pane");
    const pa = await rig();
    await click_obj("crate");
    const pb = await rig();
    check(await page.evaluate(() => window.castplane_web.selected) === "crate" && near3(pb.P, pa.P, 0) && pb.undo === pa.undo,
      "m11: a click selects the object; P is not taken in 場景中心; not an undo step");
    await page.keyboard.press("Escape");
    await frames2();
    check(await page.evaluate(() => window.castplane_web.selected) === null, "m11: Esc clears the selection");
    // 預覽: undo and redo disabled, the shortcuts do nothing; Esc leaves 預覽 and keeps the selection
    await click_obj("crate");
    await page.click("#undo");
    await frames2();
    await page.click("#preview");
    await frames2();
    const pv0 = await rig(), uip = await btn();
    check(uip.undo.disabled && uip.redo.disabled && !uip.reset.disabled && !uip.recenter.disabled,
      "m11: undo and redo are disabled while previewing (重設視角 and 重新取中心 are not)");
    for (const combo of ["Control+z", "Control+Shift+Z", "Meta+z", "Meta+Shift+Z"]) await page.keyboard.press(combo);
    await frames2();
    const pv1 = await rig();
    check(pv1.undo === pv0.undo && pv1.redo === pv0.redo && pv1.f.join() === pv0.f.join(), "m11: the shortcuts do nothing while previewing");
    await page.keyboard.press("Escape");
    await frames2();
    await frames2();
    const back = await page.evaluate(() => ({ on: window.castplane_web.observer.on, sel: window.castplane_web.selected }));
    check(back.on && back.sel === "crate", "m11: Esc in 預覽 returns to the edit view and keeps the selection");
    // the pivot is a value: moving the selected object (the drag's release, through the test hook) moves neither P, E nor
    // the observer camera; its undo and redo neither; the selection follows the moved object
    const before = await rig();
    const view0 = JSON.stringify((await page.evaluate(() => window.castplane_web.observer)).view);
    const geo0 = await page.evaluate(() => window.castplane_web.scene_geometry);
    const svg0 = await page.evaluate(() => window.castplane_web.svg);
    check(await page.evaluate(() => window.castplane_web.move_object("crate", [9, 1, 0])), "m11: the move hook moved the crate");
    await frames2();
    await frames2();
    const mv = await rig(), geo1 = await page.evaluate(() => window.castplane_web.scene_geometry);
    const view1 = JSON.stringify((await page.evaluate(() => window.castplane_web.observer)).view);
    m11.move = { bbox: [geo0.bbox, geo1.bbox], P: mv.P };
    check(near3(mv.P, before.P, 0) && near3(mv.E, before.E, 0) && mv.undo === before.undo + 1 && mv.redo === 0,
      "m11: an object move moves neither P nor E; one undo step; redo cleared");
    check(view1 === view0, "m11: an object edit does not re-frame the observer");
    check(geo1.bbox[1][0] > geo0.bbox[1][0] && svg0 !== await page.evaluate(() => window.castplane_web.svg), "m11: the scene and the drawing changed");
    await page.keyboard.press("Control+z");
    await frames2();
    await frames2();
    const un = await rig(), geo2 = await page.evaluate(() => window.castplane_web.scene_geometry);
    check(JSON.stringify(geo2.bbox) === JSON.stringify(geo0.bbox) && svg0 === await page.evaluate(() => window.castplane_web.svg)
      && near3(un.P, before.P, 0) && JSON.stringify((await page.evaluate(() => window.castplane_web.observer)).view) === view0
      && await page.evaluate(() => window.castplane_web.selected) === "crate",
    "m11: undoing the move restores the scene and the drawing (same SVG), keeps P and the observer, selects the object");
    await page.keyboard.press("Control+Shift+Z");
    await frames2();
    await frames2();
    check(JSON.stringify((await page.evaluate(() => window.castplane_web.scene_geometry)).bbox) === JSON.stringify(geo1.bbox)
      && near3((await rig()).P, before.P, 0), "m11: redoing the move");
    // 整體顯示 frames on the eight corners of the current box: the moved crate comes into view
    await page.evaluate(() => window.castplane_web.frame_observer());
    await frames2();
    const fr = await page.evaluate(() => ({ px: window.castplane_web.objects_px, size: window.castplane_web.observer.size }));
    const inside = (q) => q !== null && q[0] >= 0 && q[0] <= fr.size[0] && q[1] >= 0 && q[1] <= fr.size[1];
    check(inside(fr.px["crate"]) && inside(fr.px["pillar"]), "m11: 整體顯示 frames the edited scene's box");
    // 重新取中心 (場景中心): P becomes the current box centre; not an undo step
    const rc0 = await rig();
    await page.click("#recenter");
    await frames2();
    const rc1 = await rig(), b1 = geo1.bbox;
    const c1 = [0, 1, 2].map((i) => (b1[0][i] + b1[1][i]) / 2);
    check(near3(rc1.P, c1, 0) && !near3(rc1.P, before.P, 1e-9) && rc1.undo === rc0.undo && rc1.a === 0 && rc1.b === 0,
      "m11: 重新取中心 takes the current scene centre (pan cleared), not an undo step");
    // 點選物體 keeps P; 重新取中心 there takes the selected object's centre
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    check(near3((await rig()).P, rc1.P, 0), "m11: switching to 點選物體 keeps P");
    await page.click("#recenter");
    await frames2();
    const rc2 = await rig();
    check(rc2.pivot.object_id === "crate" && !near3(rc2.P, rc1.P, 1e-9), "m11: 重新取中心 in 點選物體 takes the selected object");
    // 重設視角: the load rule at the current centre, the selection kept, one undo step that restores P and the selector
    const rs0 = await rig();
    await page.click("#reset");
    await frames2();
    const rs1 = await rig();
    const sel1 = await page.evaluate(() => ({ sel: window.castplane_web.selected, mode: document.getElementById("pivot-mode").value }));
    check(near3(rs1.P, c1, 0) && rs1.pivot.mode === "scene" && sel1.mode === "scene" && sel1.sel === "crate" && rs1.scene_block
      && rs1.undo === rs0.undo + 1, "m11: 重設視角 takes the current centre, keeps the selection, one undo step");
    await page.click("#undo");
    await frames2();
    const rs2 = await rig();
    check(near3(rs2.P, rs0.P, 0) && rs2.pivot.object_id === "crate" && await page.evaluate(() => document.getElementById("pivot-mode").value) === "object",
      "m11: undoing 重設視角 restores P and the pivot selector");
    await page.click("#redo");
    await frames2();
    check(near3((await rig()).P, c1, 0) && await page.evaluate(() => document.getElementById("pivot-mode").value) === "scene",
      "m11: redoing 重設視角 re-applies its P");
    // a load clears the selection and both stacks
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await frames2();
    const ld = await rig();
    check(ld.undo === 0 && ld.redo === 0 && await page.evaluate(() => window.castplane_web.selected) === null, "m11: a load clears the selection and the history");
  }
  {
    // the overlay is the same with the observer pane shown and hidden (預覽) for the same (edited) camera; Download scene writes
    // the picture_plane form and reloads to the same SVG
    await page.click('#views button[data-view="left"]');
    await page.evaluate(() => { const el = document.getElementById("roll"); el.value = "12"; el.dispatchEvent(new Event("input")); });
    await frames2();
    await frames2();
    const on = await drawing();
    await page.evaluate(() => window.castplane_web.set_observer(false));
    await frames2();
    await frames2();
    const off = await drawing();
    check(same_drawing(on, off), "plane: the drawing is identical with the observer on and off (edited camera)");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#dl-scene")]);
    const path = join(outdir, "plane_mode.scene.json");
    await dl.saveAs(path);
    const saved = JSON.parse(readFileSync(path, "utf-8"));
    check(saved.camera.picture_plane !== undefined && saved.camera.target === undefined && saved.camera.roll_deg === undefined
      && Array.isArray(saved.camera.picture_plane.up), "plane: Download scene writes the picture_plane form (with up)");
    await page.evaluate((t) => window.castplane_web.load_text("plane_mode", t), readFileSync(path, "utf-8"));
    await frames2();
    const re = await page.evaluate(() => ({ svg: window.castplane_web.svg, rig: window.castplane_web.rig }));
    check(re.svg === off.svg && re.rig.scene_block, "plane: the downloaded scene reloads to the same SVG");
    plane.download = { camera: saved.camera };
    await page.evaluate(() => window.castplane_web.set_observer(true));
    await frames2();
  }
  {
    // 900 random rig states (600 incl. top / bottom views, very near / far, free roll; 300 with pan and roll)
    const res = await page.evaluate(() => {
      let s = 12345;
      const rnd = () => ((s = (s * 1103515245 + 12345) % 2147483648) / 2147483648);
      const unit = () => { for (;;) { const v = [2 * rnd() - 1, 2 * rnd() - 1, 2 * rnd() - 1]; const l = Math.hypot(...v); if (l > 0.1 && l <= 1) return v.map((x) => x / l); } };
      const base = window.castplane_web.rig;
      const P = base.P;
      const bad = [];
      for (let i = 0; i < 900; i++) {
        let f = unit();
        if (i % 10 === 0) f = [0, 0, -1];
        if (i % 10 === 1) f = [0, 0, 1];
        const D = 0.5 + 11.5 * rnd();
        const R = i % 7 === 0 ? 0.8 : i % 7 === 1 ? 40 : 0.8 + 39.2 * rnd();
        const free = i % 3 === 0;
        let up = null;
        if (free) { const w = unit(); const k = w[0] * f[0] + w[1] * f[1] + w[2] * f[2]; up = [w[0] - k * f[0], w[1] - k * f[1], w[2] - k * f[2]]; if (Math.hypot(...up) < 1e-3) up = null; }
        const pr = i >= 600;
        const rig = { f, up, g: R - D, D, a: pr ? 6 * rnd() - 3 : 0, b: pr ? 6 * rnd() - 3 : 0, roll_deg: pr ? 360 * rnd() - 180 : 0,
          focal: 8 * Math.pow(50, rnd()), P };
        const out = window.castplane_web.probe_rig(rig);
        if (out === null || out.length > 0) bad.push([i, out]);
      }
      return bad;
    });
    plane.random = { failures: res.slice(0, 5) };
    check(res.length === 0, `plane: 900 random rig states render finite (${res.length} failures)`);
  }
  if (shotsDir) {
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await page.setViewportSize({ width: 1800, height: 1050 });
    await frames2();
    await page.fill("#equation", "y=2");
    await page.press("#equation", "Enter");
    await frames2();
    const h = await page.evaluate(() => window.castplane_web.handles_px);
    const ob2 = await page.locator("#observer").boundingBox();
    let k = h.ring.findIndex((q) => q !== null && q[1] < h.Q[1] - 20 && q[0] > h.Q[0]);
    if (k < 0) k = 0;
    await page.mouse.move(ob2.x + h.ring[k][0], ob2.y + h.ring[k][1]);
    await page.mouse.down();
    for (let i = 1; i <= 8; i++) {
      await page.mouse.move(ob2.x + h.ring[k][0] - 5 * i, ob2.y + h.ring[k][1] - 2 * i);
      await frames2();
    }
    await page.mouse.up();
    // turn the observer a little towards the board's face, then frame it
    const [bx, by] = await observer_blank();
    await page.mouse.move(ob2.x + bx, ob2.y + by);
    await page.mouse.down();
    for (let i = 1; i <= 6; i++) {
      await page.mouse.move(ob2.x + bx + 8 * i, ob2.y + by);
      await frames2();
    }
    await page.mouse.up();
    await page.evaluate(() => window.castplane_web.frame_observer());
    await frames2();
    mkdirSync(shotsDir, { recursive: true });
    plane.screenshot = join(shotsDir, "web_ui_plane_mode.png");
    await page.waitForTimeout(300);
    await page.screenshot({ path: plane.screenshot });
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
console.log(JSON.stringify({ engine, first, toggles: toggle_checks, preview: preview_checks, rows, load_errors, phase2, observer, plane, failures, downloads, errors: { not_json, scene_error }, logs }, null, 1));
await browser.close();
process.exitCode = logs.some((l) => l.startsWith("pageerror")) || failures.length > 0 ? 1 : 0;

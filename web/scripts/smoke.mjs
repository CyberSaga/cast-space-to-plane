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
// selector; a load clears the selection and the history. With `--shots DIR` it also saves DIR/web_ui_plane_mode.png. M11
// step 3 (contract §5.8.17): the library (collapsed and inert at load, Ctrl / ⌘+Shift+L, the tab and #lib-close, Esc
// leaves it, no canvas box changes, the aria labels, each preset added with one undo step, Enter / Space, the narrow
// rules), select by click, the horizontal drag (the grabbed point under the pointer), the vertical handle (its tip under
// the pointer, the sticky ground), Alt, no entry for a click or a drag back, Esc during a drag, delete by Delete /
// Backspace / the chip and not in the equation field, the last object kept, undo / redo of add, delete and move (undo
// of a delete byte-identical), 預覽 read-only, the drawing pane inert on objects, the Esc order, two fingers (synthetic
// touch), outputs identical with and without a selection, and the drag budget of a 10-primitive scene plus the forced
// wireframe preview; the M11 review fixes (a press that selects keeps the observer pane's size and the grab point under
// the pointer, also with one object and when the pane is resized mid-drag; the preview decision per drag with a heavy
// mesh deleted; Esc during a pending press; QWERTZ Ctrl+Y; a blank press held across 預覽). With `--m11-shots DIR` it
// saves DIR/1_library_open.png … 4_after_delete.png at 1440 × 900.
// Prints one JSON record. Exit 1 on a page error or a failed check.
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
const m11At = argv.indexOf("--m11-shots");
const m11ShotsDir = m11At >= 0 ? argv[m11At + 1] : undefined;
if (m11At >= 0) argv.splice(m11At, 2);
const [url, outdir, shot, sceneFile] = argv;
if (!url || !outdir || (shotsAt >= 0 && !shotsDir)) {
  console.error("usage: node web/scripts/smoke.mjs URL OUTDIR [SCREENSHOT.png] [SCENE.json] [--shots DIR] [--m11-shots DIR]");
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
  /** A mouse drag in the observer pane from pane px `p` by `(dx, dy)` in `n` steps (`mid` runs after the first step). */
  async function obs_drag(p, dx, dy, n = 8, opts = {}, mid = null) {
    await page.mouse.move(ob.x + p[0], ob.y + p[1]);
    await page.mouse.down(opts);
    for (let i = 1; i <= n; i++) {
      await page.mouse.move(ob.x + p[0] + (dx * i) / n, ob.y + p[1] + (dy * i) / n);
      await frames2();
      if (i === Math.min(n, 3) && mid !== null) await mid();
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
    // M11 step 3 (contract §5.8): the library, selection, the horizontal and vertical drags, delete, undo / redo of the
    // object entries, read-only 預覽, the inert drawing pane, Esc, two fingers, overlays and the drag budget
    const s3 = {};
    plane.m11_edit = s3;
    const cw = (expr, arg) => page.evaluate(expr, arg);
    const lib = () => cw(() => window.castplane_web.library);
    const objs = () => cw(() => window.castplane_web.objects);
    const sel = () => cw(() => window.castplane_web.selected);
    const objs_json = () => cw(() => window.castplane_web.scene_objects_json);
    const view_of = async () => JSON.stringify((await cw(() => window.castplane_web.observer)).view);
    const canvas_boxes = () => cw(() => [...document.querySelectorAll("canvas")].map((c) => {
      const r = c.getBoundingClientRect();
      return [r.x, r.y, r.width, r.height, c.width, c.height].join(",");
    }).join(";"));
    const settle = async () => { await frames2(); await frames2(); };
    /** A click on object `id` in the observer pane (a failure when no pane point grabs it). */
    const click_obj = async (id) => {
      const p = await cw((i) => window.castplane_web.object_px(i), id);
      check(p !== null, `m11e: object ${id} is grabbable in the observer pane`);
      if (p === null) return;
      const b = await page.locator("#observer").boundingBox();
      await page.mouse.click(b.x + p[0], b.y + p[1]);
      await settle();
    };
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await settle();
    // the library: collapsed at load, the tab's shortcut and the collapse button's label
    const l0 = await lib();
    const attrs = await cw(() => ({ keys: document.getElementById("lib-tab").getAttribute("aria-keyshortcuts"),
      controls: document.getElementById("lib-tab").getAttribute("aria-controls"),
      close: document.getElementById("lib-close").getAttribute("aria-label"),
      labels: [...document.querySelectorAll("#lib-grid button.tile")].map((b) => b.getAttribute("aria-label")) }));
    s3.library_attrs = attrs;
    check(!l0.open && l0.inert && !l0.tab_hidden && l0.expanded === "false" && l0.tiles === 8, `m11e: the library is collapsed and inert at load (${JSON.stringify(l0)})`);
    check(attrs.keys.split(" ").includes("Control+Shift+L") && attrs.controls === "lib" && attrs.close === "收合物件庫",
      "m11e: the tab carries aria-keyshortcuts Control+Shift+L and #lib-close an aria-label");
    check(JSON.stringify(attrs.labels) === JSON.stringify(["方塊", "木箱", "高柱", "圓柱", "球", "圓錐", "三角柱", "六角柱"].map((n) => `加入：${n}`)),
      "m11e: the tiles' aria-labels are 加入：名稱");
    const boxes0 = await canvas_boxes();
    await page.keyboard.press("Control+Shift+L");
    await page.waitForTimeout(300);
    const l1 = await lib();
    check(l1.open && !l1.inert && l1.tab_hidden && l1.expanded === "true", "m11e: Ctrl+Shift+L opens the library");
    check(await canvas_boxes() === boxes0, "m11e: opening the library changes no canvas box");
    await page.keyboard.press("Escape");
    await settle();
    check((await lib()).open, "m11e: Esc leaves the library open");
    await page.keyboard.press("Control+Shift+L");
    await settle();
    check(!(await lib()).open && (await lib()).inert, "m11e: Ctrl+Shift+L closes the library");
    await page.keyboard.press("Meta+Shift+L");
    await settle();
    check((await lib()).open, "m11e: ⌘⇧L opens the library");
    await page.click("#lib-close");
    await settle();
    check(!(await lib()).open && await cw(() => document.activeElement?.id) === "lib-tab", "m11e: #lib-close closes it and the focus returns to the tab");
    const prevented = await cw(() => {
      const ev = new KeyboardEvent("keydown", { key: "L", code: "KeyL", ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true });
      document.body.dispatchEvent(ev);
      const out = ev.defaultPrevented && window.castplane_web.library.open;
      const ev2 = new KeyboardEvent("keydown", { key: "L", code: "KeyL", ctrlKey: true, shiftKey: true, bubbles: true, cancelable: true });
      document.body.dispatchEvent(ev2);
      return out && ev2.defaultPrevented && !window.castplane_web.library.open;
    });
    check(prevented, "m11e: the library shortcut calls preventDefault and toggles");
    await page.focus("#equation");
    await page.keyboard.press("Control+Shift+L");
    await settle();
    check(!(await lib()).open, "m11e: Ctrl+Shift+L in the equation field is the field's");
    await page.evaluate(() => document.getElementById("equation").blur());
    await page.click("#lib-tab");
    await settle();
    check((await lib()).open && await cw(() => document.activeElement?.classList.contains("tile")), "m11e: the tab opens the library (focus on the first tile)");
    // add each preset: one add entry each, the new object selected, P, E and the observer camera unchanged
    const r0 = await rig(), v0 = await view_of();
    const adds = [];
    for (const name of ["方塊", "木箱", "高柱", "圓柱", "球", "圓錐", "三角柱", "六角柱"]) {
      const before = await objs();
      await page.click(`#lib-grid button.tile[aria-label="加入：${name}"]`);
      await settle();
      const after = await objs(), r = await rig(), chip = await cw(() => window.castplane_web.chip);
      const added = after.at(-1);
      adds.push([name, added.id, added.position]);
      check(after.length === before.length + 1 && await sel() === added.id && r.undo === r0.undo + adds.length && r.redo === 0
        && chip.name === `${name}（${added.id}）` && !chip.hidden, `m11e: tile ${name} adds ${added.id}, selected, one undo step`);
      check(near3(r.P, r0.P, 0) && near3(r.E, r0.E, 0) && await view_of() === v0, `m11e: adding ${name} moves neither P, E nor the observer`);
    }
    s3.adds = adds;
    check(adds.map((a) => a[1]).join() === "box_1,box_2,box_3,cylinder_1,sphere_1,cone_1,prism_1,prism_2", `m11e: the id rule (${adds.map((a) => a[1])})`);
    check((await lib()).open, "m11e: on a wide screen the library stays open after an add");
    // Enter and Space activate a focused tile
    await page.focus('#lib-grid button.tile[aria-label="加入：方塊"]');
    await page.keyboard.press("Enter");
    await settle();
    await page.keyboard.press(" ");
    await settle();
    const ks = await objs();
    check(ks.length === 12 && ks.at(-2).id === "box_4" && ks.at(-1).id === "box_5", "m11e: Enter and Space on a tile add the object");
    await page.click("#undo");
    await page.click("#undo");
    await settle();
    check((await objs()).length === 10 && (await rig()).redo === 2, "m11e: undo of two adds");
    await page.click("#redo");
    await settle();
    check((await objs()).length === 11 && await sel() === "box_4", "m11e: redo of an add re-inserts and selects it");
    await page.click("#undo");
    await settle();
    check(await sel() === null, "m11e: undo of an add clears the selection");
    await page.click("#lib-close");
    await settle();
    // the 10-primitive scene: the drag budget (§5.8.12; recorded, not gated)
    {
      await page.uncheck("#snap"); // every pointer move is a new position (one edit frame each)
      const p = await cw(() => window.castplane_web.object_px("crate"));
      const n0 = (await cw(() => window.castplane_web.frames)).length;
      await obs_drag(p, -90, 30, 40);
      await page.check("#snap");
      const fr = (await cw(() => window.castplane_web.frames)).slice(n0).filter((f) => f.edit && f.dragging);
      const tot = fr.map((f) => f.core_ms + f.dom_ms + (f.obs_ms ?? 0));
      const sorted = [...tot].sort((a, b) => a - b);
      s3.budget_10 = { frames: fr.length, max_ms: Math.max(...tot), median_ms: median(tot), p90_ms: sorted[Math.floor(0.9 * (sorted.length - 1))],
        over_33: tot.filter((t) => t >= 33).length, core_median: median(fr.map((f) => f.core_ms)),
        dom_median: median(fr.map((f) => f.dom_ms)), obs_median: median(fr.map((f) => f.obs_ms ?? 0)), objects: (await objs()).length };
      check(fr.length >= 30, `m11e: ≥ 30 drag frames measured (${fr.length})`);
      check(fr.every((f) => !f.preview), "m11e: a 10-primitive drag is not in the preview mode");
      await page.click("#undo");
      await settle();
    }
    // the forced preview: a > 50 ms drag-mode cost switches the gesture to the wireframe; release is a complete frame
    {
      await page.evaluate(() => window.castplane_web.force_edit_ms(80));
      const svg_a = await cw(() => window.castplane_web.svg), dl_a = await cw(() => window.castplane_web.download_texts());
      const p = await cw(() => window.castplane_web.object_px("crate"));
      let mid = null;
      await obs_drag(p, -60, 20, 10, {}, async () => {
        mid = await cw(() => ({ press: window.castplane_web.press, svg: window.castplane_web.svg, dl: window.castplane_web.download_texts(),
          wire: document.getElementById("stage").classList.contains("wire"), ov: window.castplane_web.sel_overlay,
          delta: window.castplane_web.rig.delta }));
      });
      const after = await cw(() => ({ svg: window.castplane_web.svg, wire: document.getElementById("stage").classList.contains("wire"),
        frames: window.castplane_web.frames.slice(-3) }));
      s3.preview = { press: mid?.press, wire: mid?.wire, delta: mid?.delta };
      check(mid !== null && mid.press?.preview === true && mid.wire && mid.ov.includes('class="wire"') && mid.svg === svg_a
        && mid.dl.svg === dl_a.svg && mid.dl.json === dl_a.json && mid.delta > 0, "m11e: a forced > 50 ms frame gives the wireframe preview (outputs keep the last frame; the delta follows)");
      check(!after.wire && after.svg !== svg_a && after.frames.at(-1).preview === false && after.frames.at(-1).dragging === false,
        "m11e: release runs one complete frame");
      await page.evaluate(() => window.castplane_web.force_edit_ms(null));
      await page.click("#undo");
      await settle();
    }
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await settle();
    // select by click; outputs are byte-identical with and without the selection
    const plain = await drawing();
    const pc = await cw(() => window.castplane_web.object_px("pillar"));
    await page.mouse.click(ob.x + pc[0], ob.y + pc[1]);
    await settle();
    const withSel = await drawing();
    check(await sel() === "pillar" && (await rig()).undo === 0, "m11e: a click selects the object (not an undo step)");
    check(same_drawing(plain, withSel) && (await cw(() => window.castplane_web.sel_overlay)).includes('class="sel"')
      && (await cw(() => window.castplane_web.selection_names)).includes("selection:outline"),
      "m11e: the selection is outlined in both panes and the SVG / overlay / downloads are byte-identical");
    // the horizontal drag keeps the grabbed point under the pointer (snapping off)
    await page.uncheck("#snap");
    {
      const p = await cw(() => window.castplane_web.object_px("crate"));
      const h0 = await cw(([x, y]) => window.castplane_web.hit_point(x, y), p);
      const a0 = (await objs()).find((o) => o.id === "crate").position;
      const r1 = await rig(), v1 = await view_of();
      await obs_drag(p, 70, 25, 10);
      const a1 = (await objs()).find((o) => o.id === "crate").position;
      const q = await cw((X) => window.castplane_web.project_observer(X), [h0.point[0] + a1[0] - a0[0], h0.point[1] + a1[1] - a0[1], h0.point[2]]);
      const err = Math.hypot(q[0] - (p[0] + 70), q[1] - (p[1] + 25));
      const r2 = await rig();
      s3.horizontal = { from: a0, to: a1, grab_error_px: err };
      check(h0.id === "crate" && err < 0.5 && a1[2] === a0[2] && await sel() === "crate", `m11e: the grabbed point stays under the pointer (${err.toFixed(3)} px)`);
      check(r2.undo === r1.undo + 1 && near3(r2.P, r1.P, 0) && near3(r2.E, r1.E, 0) && await view_of() === v1,
        "m11e: one move entry; P, E and the observer camera unchanged");
    }
    // the vertical handle: only z changes; its tip stays under the pointer
    {
      const t = await cw(() => window.castplane_web.vertical_px);
      const hit = await cw(([x, y]) => window.castplane_web.hit_at(x, y), t);
      const a0 = (await objs()).find((o) => o.id === "crate").position;
      // move the pointer 40 px up along the image of the handle's vertical line
      const tip3 = await cw(() => window.castplane_web.vertical_tip);
      const low = await cw((X) => window.castplane_web.project_observer(X), [tip3[0], tip3[1], tip3[2] - 0.5]);
      const dl = Math.hypot(t[0] - low[0], t[1] - low[1]), ux = (t[0] - low[0]) / dl, uy = (t[1] - low[1]) / dl;
      let t_held = null; // the tip before the release (the handle keeps its length during the drag, §5.8.4)
      await page.mouse.move(ob.x + t[0], ob.y + t[1]);
      await page.mouse.down();
      for (let i = 1; i <= 8; i++) { await page.mouse.move(ob.x + t[0] + 5 * i * ux, ob.y + t[1] + 5 * i * uy); await frames2(); }
      await settle();
      t_held = await cw(() => window.castplane_web.vertical_px);
      await page.mouse.up();
      await settle();
      const a1 = (await objs()).find((o) => o.id === "crate").position;
      const t1 = await cw(() => window.castplane_web.vertical_px);
      const err = Math.hypot(t_held[0] - (t[0] + 40 * ux), t_held[1] - (t[1] + 40 * uy));
      s3.vertical = { from: a0, to: a1, tip_error_px: err };
      check(hit?.kind === "handle" && a1[0] === a0[0] && a1[1] === a0[1] && a1[2] > a0[2] && err < 2, `m11e: the vertical handle lifts the object (tip error ${err.toFixed(3)} px)`);
      await obs_drag(t1, 0, 200, 8);
      check((await objs()).find((o) => o.id === "crate").position[2] === 0, "m11e: the ground is sticky (z = 0 after a drag down)");
    }
    await page.check("#snap");
    // Alt pauses snapping
    {
      const p = await cw(() => window.castplane_web.object_px("pillar"));
      await obs_drag(p, 37, 11, 6);
      const snapped = (await objs()).find((o) => o.id === "pillar").position;
      const p2 = await cw(() => window.castplane_web.object_px("pillar"));
      await page.keyboard.down("Alt");
      await obs_drag(p2, 23, 7, 6);
      await page.keyboard.up("Alt");
      const free = (await objs()).find((o) => o.id === "pillar").position;
      const on_grid = (v) => Math.abs(v * 10 - Math.round(v * 10)) < 1e-9;
      s3.snap = { snapped, free };
      check(snapped.slice(0, 2).every(on_grid) && !free.slice(0, 2).every(on_grid), "m11e: snapping on the 0.1 m grid; Alt pauses it");
    }
    // a drag that comes back to its start records nothing; a click records nothing (snapping off: no rounding onto the grid)
    {
      await page.uncheck("#snap");
      const u0 = (await rig()).undo;
      const p = await cw(() => window.castplane_web.object_px("pillar"));
      await page.mouse.move(ob.x + p[0], ob.y + p[1]);
      await page.mouse.down();
      for (const [dx, dy] of [[20, 0], [40, 5], [0, 0]]) { await page.mouse.move(ob.x + p[0] + dx, ob.y + p[1] + dy); await frames2(); }
      await page.mouse.up();
      await settle();
      await page.mouse.click(ob.x + p[0], ob.y + p[1]);
      await settle();
      check((await rig()).undo === u0, "m11e: a drag back to its start and a click record nothing");
      await page.check("#snap");
    }
    // Esc during a drag does nothing
    {
      const u0 = (await rig()).undo;
      const p = await cw(() => window.castplane_web.object_px("crate"));
      let mid = null;
      await obs_drag(p, 30, 10, 6, {}, async () => {
        await page.keyboard.press("Escape");
        mid = await cw(() => ({ press: window.castplane_web.press, sel: window.castplane_web.selected }));
      });
      check(mid?.press?.started === true && mid.sel === "crate" && (await rig()).undo === u0 + 1, "m11e: Esc during a drag does nothing (the drag goes on)");
    }
    // undo / redo of a move: the selection follows the object
    {
      const before = await objs_json();
      await page.click("#undo");
      await settle();
      const back = await objs_json();
      await page.click("#redo");
      await settle();
      check(back !== before && await objs_json() === before && await sel() === "crate", "m11e: undo and redo of a move (the selection follows)");
    }
    // review M11-2 (1): a press on an unselected object shows the chip (with one object, also the keep-one text) without
    // resizing the observer pane, so the drag (pointer-down's frame) keeps the grabbed point under the pointer; a pane
    // resized during a drag is re-read (snapping off)
    const basic_json = JSON.parse(readFileSync(join(ROOT, "examples", "basic.json"), "utf-8"));
    {
      const obs_h = () => cw(() => +document.getElementById("obs-gl").getBoundingClientRect().height.toFixed(2));
      /** Drag object `id` by (dx, dy) in `n` steps (`mid(i)` after step i): the grab error in px and the pane heights. */
      const grab_drag = async (id, dx, dy, n = 10, mid = null) => {
        const box = await page.locator("#observer").boundingBox();
        const p = await cw((i) => window.castplane_web.object_px(i), id);
        const h0 = await cw(([x, y]) => window.castplane_web.hit_point(x, y), p);
        const a0 = (await objs()).find((o) => o.id === id).position;
        const hs = new Set([await obs_h()]);
        await page.mouse.move(box.x + p[0], box.y + p[1]);
        await page.mouse.down();
        await frames2();
        hs.add(await obs_h());
        for (let i = 1; i <= n; i++) {
          await page.mouse.move(box.x + p[0] + (dx * i) / n, box.y + p[1] + (dy * i) / n);
          await frames2();
          if (mid !== null) await mid(i);
          hs.add(await obs_h());
        }
        await frames2();
        const a1 = (await objs()).find((o) => o.id === id).position;
        const box2 = await page.locator("#observer").boundingBox();
        const q = await cw((X) => window.castplane_web.project_observer(X), [h0.point[0] + a1[0] - a0[0], h0.point[1] + a1[1] - a0[1], h0.point[2]]);
        const err = Math.hypot(box2.x + q[0] - (box.x + p[0] + dx), box2.y + q[1] - (box.y + p[1] + dy));
        await page.mouse.up();
        await settle();
        return { hit: h0?.id ?? null, err, heights: [...hs] };
      };
      await page.uncheck("#snap");
      const id = basic_json.objects[0].id;
      const one = { ...basic_json, objects: basic_json.objects.slice(0, 1) };
      const rows = {};
      for (const [name, load] of [["several objects", () => cw(() => window.castplane_web.load_example("basic"))],
        ["one object", () => cw((t) => window.castplane_web.load_text("one_object", t), JSON.stringify(one))]]) {
        await load();
        await settle();
        const sel0 = await sel();
        const r = await grab_drag(id, 60, -25);
        const chip = await cw(() => window.castplane_web.chip);
        rows[name] = { ...r, hint_shown: !chip.hint_hidden };
        check(sel0 === null && r.hit === id && await sel() === id && r.heights.length === 1 && r.err < 0.5
          && chip.hint_hidden === (name !== "one object"),
          `m11e: ${name}: a press that selects keeps the observer pane's size and the grabbed point under the pointer (${r.err.toFixed(3)} px, heights ${r.heights.join("/")})`);
      }
      // the pane shrinks in the middle of a drag (the window is resized): the frame is re-read
      await cw(() => window.castplane_web.load_example("basic"));
      await settle();
      const r = await grab_drag(id, -70, 20, 10, async (i) => {
        if (i === 4) {
          await page.setViewportSize({ width: 1500, height: 820 });
          await frames2();
        }
      });
      await page.setViewportSize({ width: 1500, height: 900 });
      await settle();
      rows["resized mid-drag"] = r;
      s3.grab_on_select = rows;
      check(r.heights.length === 2 && r.err < 0.5, `m11e: a pane resized during a drag keeps the grabbed point under the pointer (${r.err.toFixed(3)} px, heights ${r.heights.join("/")})`);
      await page.check("#snap");
    }
    // review M11-2 (2): the wireframe-preview decision is taken per drag: with a heavy mesh (a UV sphere of 9 662 vertices,
    // 9 800 faces) drags are previews, the second from its first frame; after the mesh is deleted drags run complete frames
    {
      const NL = 70, NO = 140, R = 0.6, r6 = (x) => Math.round(x * 1e6) / 1e6 + 0;
      const V = [[0, 0, -R]], F = [];
      for (let i = 1; i < NL; i++) {
        const ph = (Math.PI * i) / NL;
        for (let j = 0; j < NO; j++) {
          const th = (2 * Math.PI * j) / NO;
          V.push([r6(R * Math.sin(ph) * Math.cos(th)), r6(R * Math.sin(ph) * Math.sin(th)), r6(-R * Math.cos(ph))]);
        }
      }
      V.push([0, 0, R]);
      const ring = (i) => 1 + (i - 1) * NO, top = V.length - 1;
      for (let j = 0; j < NO; j++) F.push([0, 1 + ((j + 1) % NO), 1 + j]);
      for (let i = 1; i < NL - 1; i++) for (let j = 0; j < NO; j++) F.push([ring(i) + j, ring(i) + ((j + 1) % NO), ring(i + 1) + ((j + 1) % NO), ring(i + 1) + j]);
      for (let j = 0; j < NO; j++) F.push([top, ring(NL - 1) + j, ring(NL - 1) + ((j + 1) % NO)]);
      const heavy = { ...basic_json, objects: [...basic_json.objects,
        { id: "blob", type: "mesh", data: { vertices: V, faces: F }, transform: { position: [-3, 8, 0.6], rotation_deg: [0, 0, 0] } }] };
      check(await cw((t) => window.castplane_web.load_text("heavy_mesh", t), JSON.stringify(heavy)), "m11e: the heavy mesh scene loads");
      await settle();
      const box = await page.locator("#observer").boundingBox();
      const mode_of = async (id, dx) => {
        const p = await cw((i) => window.castplane_web.object_px(i), id);
        const n0 = (await cw(() => window.castplane_web.frames)).length;
        let at_start = null;
        await page.mouse.move(box.x + p[0], box.y + p[1]);
        await page.mouse.down();
        for (let i = 1; i <= 6; i++) {
          await page.mouse.move(box.x + p[0] + (dx * i) / 6, box.y + p[1] + 2 * i);
          await frames2();
          if (i === 1) at_start = (await cw(() => window.castplane_web.press))?.preview ?? null;
        }
        const pv = (await cw(() => window.castplane_web.press))?.preview ?? null;
        await page.mouse.up();
        await settle();
        const fr = (await cw(() => window.castplane_web.frames)).slice(n0).filter((f) => f.edit && f.dragging);
        return { at_start, preview: pv, frames: fr.map((f) => (f.preview ? "wire" : `${Math.round(f.core_ms)} ms`)) };
      };
      const d1 = await mode_of("crate", 60);
      const d2 = await mode_of("crate", -60);
      const pb = await cw(() => window.castplane_web.object_px("blob"));
      await page.mouse.click(box.x + pb[0], box.y + pb[1]);
      await settle();
      const picked = await sel();
      await page.keyboard.press("Delete");
      await settle();
      const gone = !(await objs()).some((o) => o.id === "blob");
      const d3 = await mode_of("crate", 60);
      const d4 = await mode_of("crate", -60);
      s3.preview_per_drag = { d1, d2, deleted: picked === "blob" && gone, d3, d4 };
      check(d1.preview === true && d2.at_start === true && d2.frames.every((f) => f === "wire"),
        `m11e: heavy mesh: the drags are previews, the second from its first frame (${JSON.stringify([d1, d2])})`);
      check(picked === "blob" && gone && d3.preview === false && d4.preview === false
        && [...d3.frames, ...d4.frames].every((f) => f !== "wire") && d3.frames.length > 0,
        `m11e: after the heavy mesh is deleted the drags run complete frames again (${JSON.stringify([d3, d4])})`);
    }
    // review M11-2 (3): Esc during a press that has not yet become a drag does nothing; the drag then moves the selection
    {
      await cw(() => window.castplane_web.load_example("basic"));
      await settle();
      const box = await page.locator("#observer").boundingBox();
      const p = await cw(() => window.castplane_web.object_px("crate"));
      const u0 = (await rig()).undo, a0 = (await objs()).find((o) => o.id === "crate").position;
      await page.mouse.move(box.x + p[0], box.y + p[1]);
      await page.mouse.down();
      await frames2();
      await page.keyboard.press("Escape");
      await frames2();
      const s1 = { sel: await sel(), press: await cw(() => window.castplane_web.press) };
      for (let i = 1; i <= 8; i++) { await page.mouse.move(box.x + p[0] + 8 * i, box.y + p[1] + 3 * i); await frames2(); }
      const s2 = { sel: await sel(), press: await cw(() => window.castplane_web.press), chip: (await cw(() => window.castplane_web.chip)).hidden };
      await page.mouse.up();
      await settle();
      const a1 = (await objs()).find((o) => o.id === "crate").position;
      s3.esc_pending = { s1, s2 };
      check(s1.sel === "crate" && s1.press?.started === false && s2.sel === "crate" && s2.press?.started === true && !s2.chip
        && await sel() === "crate" && (await rig()).undo === u0 + 1 && a1.join() !== a0.join(),
        `m11e: Esc during a pending press keeps the selection; the drag moves the selected object (${JSON.stringify(s3.esc_pending)})`);
      // review M11-2 (5): shortcuts follow the layout's letter: QWERTZ Ctrl+Y (key "y" on code KeyZ) does not undo, its
      // Ctrl+Z (key "z" on code KeyY) does
      const kd = (key, code) => cw(([k, c]) => window.dispatchEvent(new KeyboardEvent("keydown", { key: k, code: c, ctrlKey: true, bubbles: true, cancelable: true })), [key, code]);
      await kd("y", "KeyZ");
      await settle();
      const uy = (await rig()).undo;
      await kd("z", "KeyY");
      await settle();
      const uz = (await rig()).undo;
      check(uy === u0 + 1 && uz === u0, `m11e: QWERTZ: Ctrl+Y does not undo, Ctrl+Z does (${u0 + 1} → ${uy} → ${uz})`);
    }
    // review M11-2 (4): a blank press held in the observer while 預覽 is entered by the keyboard: its release changes
    // nothing (the selection survives the round trip)
    {
      const box = await page.locator("#observer").boundingBox();
      const pc = await cw(() => window.castplane_web.object_px("crate"));
      await page.mouse.click(box.x + pc[0], box.y + pc[1]);
      await settle();
      let blank = null;
      for (let y = 20; y < 300 && blank === null; y += 10) {
        for (let x = 20; x < 500 && blank === null; x += 10) if (await cw(([a, b]) => window.castplane_web.hit_at(a, b), [x, y]) === null) blank = [x, y];
      }
      check(blank !== null, "m11e: a blank point of the observer pane");
      s3.preview_blank = {};
      // released where it was pressed (a click) and after a 30 px move (an orbit)
      for (const dx of blank === null ? [] : [0, 30]) {
        const v0 = await view_of();
        await cw(() => document.getElementById("preview").focus());
        await page.mouse.move(box.x + blank[0], box.y + blank[1]);
        await page.mouse.down();
        await page.keyboard.press("Enter");
        await frames2();
        const mid = { on: (await cw(() => window.castplane_web.observer)).on, sel: await sel() };
        if (dx !== 0) await page.mouse.move(box.x + blank[0] + dx, box.y + blank[1] + dx / 3);
        await page.mouse.up();
        await settle();
        const after = await sel();
        await page.keyboard.press("Escape");
        await settle();
        const back = { on: (await cw(() => window.castplane_web.observer)).on, sel: await sel(), view: await view_of() };
        const row = { mid, after, back: { on: back.on, sel: back.sel }, view_kept: back.view === v0 };
        s3.preview_blank[dx === 0 ? "click" : "drag"] = row;
        check(!mid.on && mid.sel === "crate" && after === "crate" && back.on && back.sel === "crate" && row.view_kept,
          `m11e: a blank press held across 預覽 (${dx === 0 ? "released in place" : "moved"}) neither changes the selection nor orbits the observer (${JSON.stringify(row)})`);
      }
    }
    // delete: Delete, Backspace and the chip button; not with the focus in the equation field; undo is byte-identical
    {
      await page.evaluate(() => window.castplane_web.load_example("basic"));
      await settle();
      await page.click("#lib-tab");
      await settle();
      for (const name of ["方塊", "球", "圓錐"]) await page.click(`#lib-grid button.tile[aria-label="加入：${name}"]`);
      await page.click("#lib-close");
      await page.evaluate(() => window.castplane_web.frame_observer()); // 整體顯示: the added objects come into view (adds do not re-frame)
      await settle();
      const ref = { json: await objs_json(), draw: await drawing() };
      const pc2 = await cw(() => window.castplane_web.object_px("crate"));
      await page.mouse.click(ob.x + pc2[0], ob.y + pc2[1]);
      await settle();
      await page.focus("#equation");
      await page.keyboard.press("Delete");
      await page.keyboard.press("Backspace");
      await settle();
      check((await objs()).length === 5 && await sel() === "crate", "m11e: Delete / Backspace in the equation field delete nothing");
      await page.evaluate(() => document.getElementById("equation").blur());
      const P0 = (await rig()).P;
      await page.keyboard.press("Delete");
      await settle();
      const d1 = await objs();
      check(d1.length === 4 && !d1.some((o) => o.id === "crate") && await sel() === null && near3((await rig()).P, P0, 0),
        "m11e: Delete deletes the selection (cleared; P unchanged)");
      await page.keyboard.press("Control+z");
      await settle();
      const und = { json: await objs_json(), draw: await drawing() };
      check(und.json === ref.json && same_drawing(und.draw, ref.draw) && await sel() === "crate", "m11e: undo of a delete is byte-identical (scene JSON, SVG, overlay, downloads) and selects it");
      await page.keyboard.press("Control+Shift+Z");
      await settle();
      check((await objs()).length === 4, "m11e: redo of a delete");
      await page.keyboard.press("Control+z");
      await settle();
      await click_obj("sphere_1");
      check(await sel() === "sphere_1" && (await cw(() => window.castplane_web.chip)).name === "球（sphere_1）", "m11e: the chip names a library object");
      await page.keyboard.press("Backspace");
      await settle();
      check(!(await objs()).some((o) => o.id === "sphere_1"), "m11e: Backspace deletes");
      await click_obj("box_1");
      await page.click("#sel-delete");
      await settle();
      check(!(await objs()).some((o) => o.id === "box_1") && await sel() === null, "m11e: the chip's 刪除 button deletes");
      s3.after_deletes = (await objs()).map((o) => o.id);
    }
    // the last object cannot be deleted (wall_and_ground has one)
    {
      await page.evaluate(() => window.castplane_web.load_example("wall_and_ground"));
      await settle();
      const id = (await objs())[0].id;
      const p = await cw((i) => window.castplane_web.object_px(i), id);
      await page.mouse.click(ob.x + p[0], ob.y + p[1]);
      await settle();
      const chip = await cw(() => window.castplane_web.chip);
      check(await sel() === id && chip.delete_disabled && !chip.hint_hidden
        && await cw(() => getComputedStyle(document.getElementById("sel-hint")).display !== "none"), "m11e: one object left: the button is disabled and 場景至少要有一個物件 is visible");
      await page.keyboard.press("Delete");
      await settle();
      check((await objs()).length === 1 && (await rig()).undo === 0
        && (await cw(() => document.getElementById("notices").textContent)).includes("場景至少要有一個物件"), "m11e: Delete on the last object deletes nothing and shows the notice");
    }
    // 預覽 is read-only; Esc returns and the selection survives; the drawing pane is inert on objects
    {
      await page.evaluate(() => window.castplane_web.load_example("basic"));
      await settle();
      const p = await cw(() => window.castplane_web.object_px("crate"));
      await page.mouse.click(ob.x + p[0], ob.y + p[1]);
      await settle();
      await page.click("#lib-tab");
      await settle();
      await page.click("#preview");
      await settle();
      const json0 = await objs_json(), r0p = await rig();
      const st = await cw(() => ({ lib: window.castplane_web.library, chip: window.castplane_web.chip.hidden, undo: document.getElementById("undo").disabled,
        redo: document.getElementById("redo").disabled, notices: document.getElementById("notices").textContent }));
      check(!st.lib.open && st.lib.inert && st.lib.tab_hidden && st.chip && st.undo && st.redo && st.notices.includes("預覽中無法編輯物件"),
        `m11e: 預覽 collapses the library, hides the tab and the chip, disables 復原 / 重做 (${JSON.stringify(st)})`);
      for (const combo of ["Delete", "Backspace", "Control+z", "Control+Shift+Z", "Meta+z", "Control+Shift+L", "Meta+Shift+L"]) await page.keyboard.press(combo);
      await page.evaluate(() => { for (const b of document.querySelectorAll("#lib-grid button.tile, #sel-delete, #lib-tab")) b.click(); });
      await settle();
      const r1p = await rig();
      check(await objs_json() === json0 && await sel() === "crate" && r1p.undo === r0p.undo && r1p.redo === r0p.redo && !(await lib()).open,
        "m11e: in 預覽 no key, tile, tab or delete button edits the scene or the selection");
      // the drawing pane: a click, a drag and a press on an object change nothing
      const sp = await cw(() => window.castplane_web.stage_object_px("pillar"));
      const sb = await page.locator("#stage").boundingBox();
      await page.mouse.click(sb.x + sp[0], sb.y + sp[1]);
      await page.mouse.move(sb.x + sp[0], sb.y + sp[1]);
      await page.mouse.down();
      for (let i = 1; i <= 6; i++) { await page.mouse.move(sb.x + sp[0] + 8 * i, sb.y + sp[1]); await frames2(); }
      await page.mouse.up();
      await settle();
      check(await objs_json() === json0 && await sel() === "crate", "m11e: the drawing pane is inert on objects (預覽)");
      await page.keyboard.press("Escape");
      await settle();
      const bk = await cw(() => ({ on: window.castplane_web.observer.on, sel: window.castplane_web.selected, lib: window.castplane_web.library,
        chip: window.castplane_web.chip.hidden }));
      check(bk.on && bk.sel === "crate" && !bk.lib.open && !bk.lib.tab_hidden && !bk.chip, "m11e: Esc returns to the edit view; the selection survives; the tab and chip are back");
      const sp2 = await cw(() => window.castplane_web.stage_object_px("pillar"));
      const sb2 = await page.locator("#stage").boundingBox();
      await page.mouse.click(sb2.x + sp2[0], sb2.y + sp2[1]);
      await page.mouse.move(sb2.x + sp2[0], sb2.y + sp2[1]);
      await page.mouse.down();
      for (let i = 1; i <= 6; i++) { await page.mouse.move(sb2.x + sp2[0] - 8 * i, sb2.y + sp2[1]); await frames2(); }
      await page.mouse.up();
      await settle();
      check(await objs_json() === json0 && await sel() === "crate", "m11e: the drawing pane is inert on objects (edit view)");
    }
    // Esc order: the equation field's own > 預覽 > the selection; never the library
    {
      await page.click("#lib-tab");
      await settle();
      const eq0 = await cw(() => document.getElementById("equation").value);
      await page.focus("#equation");
      await page.keyboard.type("x=");
      await page.keyboard.press("Escape");
      await settle();
      const a = await cw(() => ({ sel: window.castplane_web.selected, lib: window.castplane_web.library.open, field: document.getElementById("equation").value }));
      check(a.sel === "crate" && a.lib && a.field === eq0, "m11e: Esc in the equation field drops the typed text only (selection and library kept)");
      await page.evaluate(() => document.body.focus());
      await page.keyboard.press("Escape");
      await settle();
      check(await sel() === null && (await lib()).open, "m11e: Esc in the edit view clears the selection; the library stays open");
      await page.keyboard.press("Escape");
      await settle();
      check((await lib()).open, "m11e: Esc with nothing selected does nothing");
      await page.click("#lib-close");
    }
    // two fingers (touch, observer pane): before 5 px the press is cancelled (0 steps) and the pinch zooms; after 5 px the
    // second finger is ignored
    {
      await page.evaluate(() => window.castplane_web.load_example("basic"));
      await settle();
      const p = await cw(() => window.castplane_web.object_px("crate", true));
      check(p !== null, "m11e: the crate is grabbable by touch");
      const touch = (type, id, x, y) => cw(([type, id, x, y]) => {
        const el = document.getElementById("obs-gl"), b = document.getElementById("observer").getBoundingClientRect();
        el.dispatchEvent(new PointerEvent(type, { pointerId: id, pointerType: "touch", isPrimary: id % 10 === 1, clientX: b.left + x, clientY: b.top + y,
          bubbles: true, cancelable: true, button: 0, buttons: type === "pointerup" ? 0 : 1 }));
      }, [type, id, x, y]);
      const json0 = await objs_json(), v0t = (await cw(() => window.castplane_web.observer)).view, u0 = (await rig()).undo;
      await touch("pointerdown", 11, p[0], p[1]);
      await touch("pointermove", 11, p[0] + 3, p[1]);
      const mid = await sel();
      await touch("pointerdown", 12, p[0] + 80, p[1] + 40);
      await touch("pointermove", 12, p[0] + 140, p[1] + 80);
      await touch("pointermove", 12, p[0] + 180, p[1] + 110);
      await touch("pointerup", 12, p[0] + 180, p[1] + 110);
      await touch("pointerup", 11, p[0] + 3, p[1]);
      await settle();
      const v1t = (await cw(() => window.castplane_web.observer)).view;
      check(mid === "crate" && await sel() === null && await objs_json() === json0 && (await rig()).undo === u0 && v1t.dist !== v0t.dist,
        "m11e: a second finger before 5 px cancels the object press (selection back, 0 steps) and pinches the observer");
      const q = await cw(() => window.castplane_web.object_px("crate", true)); // the pinch zoomed the observer
      await touch("pointerdown", 21, q[0], q[1]);
      for (let i = 1; i <= 4; i++) { await touch("pointermove", 21, q[0] + 10 * i, q[1]); await frames2(); }
      await touch("pointerdown", 22, q[0] + 100, q[1] + 100);
      await touch("pointermove", 22, q[0] + 160, q[1] + 160);
      await touch("pointermove", 21, q[0] + 60, q[1]);
      await frames2();
      await touch("pointerup", 22, q[0] + 160, q[1] + 160);
      await touch("pointerup", 21, q[0] + 60, q[1]);
      await settle();
      const v2t = (await cw(() => window.castplane_web.observer)).view;
      check(await objs_json() !== json0 && (await rig()).undo === u0 + 1 && v2t.dist === v1t.dist && await sel() === "crate",
        "m11e: after 5 px the second finger is ignored (one move entry, no pinch)");
    }
    if (m11ShotsDir) {
      mkdirSync(m11ShotsDir, { recursive: true });
      await page.setViewportSize({ width: 1440, height: 900 });
      await page.evaluate(() => window.castplane_web.load_example("basic"));
      await settle();
      const ob3 = await page.locator("#observer").boundingBox();
      await page.click("#lib-tab");
      await page.click('#lib-grid button.tile[aria-label="加入：木箱"]');
      await page.click('#lib-grid button.tile[aria-label="加入：圓錐"]');
      await page.evaluate(() => window.castplane_web.frame_observer());
      await settle();
      await page.waitForTimeout(300);
      await page.screenshot({ path: join(m11ShotsDir, "1_library_open.png") });
      await page.click("#lib-close");
      const p = await cw(() => window.castplane_web.object_px("crate"));
      await page.mouse.click(ob3.x + p[0], ob3.y + p[1]);
      await settle();
      await page.waitForTimeout(300);
      await page.screenshot({ path: join(m11ShotsDir, "2_selected.png") });
      const p2 = await cw(() => window.castplane_web.object_px("crate"));
      await page.mouse.move(ob3.x + p2[0], ob3.y + p2[1]);
      await page.mouse.down();
      for (let i = 1; i <= 8; i++) { await page.mouse.move(ob3.x + p2[0] - 9 * i, ob3.y + p2[1] - 4 * i); await frames2(); }
      await page.screenshot({ path: join(m11ShotsDir, "3_dragging.png") });
      await page.mouse.up();
      await settle();
      await click_obj("cone_1");
      await page.keyboard.press("Delete");
      await settle();
      await page.waitForTimeout(300);
      await page.screenshot({ path: join(m11ShotsDir, "4_after_delete.png") });
      s3.screenshots = ["1_library_open.png", "2_selected.png", "3_dragging.png", "4_after_delete.png"].map((n) => join(m11ShotsDir, n));
      await page.setViewportSize({ width: 1500, height: 900 });
      await settle();
    }
    // narrow screen: an add closes the sidebar; an outside tap closes it and is consumed
    {
      await page.setViewportSize({ width: 800, height: 900 });
      await page.evaluate(() => window.castplane_web.load_example("basic"));
      await settle();
      await page.click("#lib-tab");
      await settle();
      const w = await cw(() => document.getElementById("lib").getBoundingClientRect().width);
      await page.click('#lib-grid button.tile[aria-label="加入：球"]');
      await settle();
      check(!(await lib()).open && (await objs()).length === 3 && w <= 280, `m11e: narrow screen: an add closes the sidebar (width ${w})`);
      await page.click("#lib-tab");
      await settle();
      const s0 = await sel(), json0 = await objs_json(), v0n = await view_of();
      const ob4 = await page.locator("#observer").boundingBox();
      const pn = [ob4.width - 40, ob4.height / 2]; // right of the sidebar: an orbit, if it were not consumed
      await page.mouse.move(ob4.x + pn[0], ob4.y + pn[1]);
      await page.mouse.down();
      for (let i = 1; i <= 5; i++) { await page.mouse.move(ob4.x + pn[0] + 10 * i, ob4.y + pn[1]); await frames2(); }
      await page.mouse.up();
      await settle();
      check(!(await lib()).open && await sel() === s0 && await objs_json() === json0 && await view_of() === v0n,
        "m11e: narrow screen: an outside tap closes the sidebar and is consumed (no selection, no drag)");
      await page.setViewportSize({ width: 1500, height: 900 });
      await settle();
    }
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

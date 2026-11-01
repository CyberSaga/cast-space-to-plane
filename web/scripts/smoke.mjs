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
// v8 `picture_plane` cases render the scene camera's document until an arrow drag (and again after "重設"); a frame
// below the ground is drawn. With `--shots DIR` it also saves DIR/web_ui_observer.png. M10 (contract §5.7.13, plane
// mode): the ring drag changes f and keeps g, D and |E − P|; the arrow drag changes g only; the drawing pane is
// view-only (a left, right, middle and Shift drag and the wheel there change neither the camera block, the readouts,
// the undo availability nor the drawing, show no error, and leave the wheel / pointer events' default actions to the
// browser: no preventDefault, default touch-action and cursor); the roll slider
// keeps the eye; the six views give exact axes; y=2 with D = 4 puts the eye at y = −2; a bad equation turns the field
// red and keeps the plane; undo and reset restore f, g, up (and the sliders); the eye is not draggable; the D slider
// keeps the board; an object click sets the pivot; Download scene writes the picture_plane form and reloads to the
// same SVG; the overlay is identical with the observer pane shown and hidden (預覽) for the same edited camera; 900 random rig
// states render finite. With `--shots DIR` it also saves DIR/web_ui_plane_mode.png. M11 (contract §5.8.8, one object
// rotated with the camera and the board fixed): basic's crate about z by 30° and directional's spire (cone) about x by
// 20° keep the camera block, the rig and scene_block, keep the other objects' stage-A vertices value for value and
// change the rotated one's (pivot fixed); undo gives the byte-identical SVG; the downloaded rotated scene rendered by
// the Python CLI equals download_texts().svg; the x rotation reports OBJECT_BELOW_RECEIVER and 落地 clears it; a ring
// drag records drag frames and live stage-A runs; a
// pointerdown → one move → pointerup with no frame in between commits (one undo step); a second finger cancels (pose,
// vertices, SVG and undo as before the press); a bad numeric field turns red and changes nothing; the numeric fields,
// 還原此物體 and the panel in 預覽 work; angles typed into several fields apply together (套用, or Tab and Enter), Escape
// drops them, a drag with a focused field refreshes it, and 復原 is off while a board or ring drag is held. D83
// (modeless): no selection after a load (also with one object); a real click on an object selects it with no mode
// button, its rings drawn with the board's handles (hover shows the pointer), a blank click clears it, 點選物體 + a click
// also picks the pivot; the 「板子」 checkbox hides the observer's board group, its labels and handles (not hit) with the
// page SVG, overlay and downloads byte-identical, a click still selects and a ring drag still rotates, and a change
// during a held board-ring drag is ignored. D84 (groups of parts, the fixture web/test/fixtures/basic_grouped.json): the
// dropdown lists the group first; real clicks cycle whole group → part → whole group, blank space clears, another
// part after part focus takes the focus, an ungrouped object selects as in D83; the group's rings are larger and a
// real drag on them turns every member; rotate_group keeps c, the camera block, the rig and scene_block, changes every
// member and not the ungrouped object, and undo restores the SVG byte for byte; the fields and 還原此物體 act on the
// whole group (an unedited 套用 records no step); 點選物體 puts the pivot on the group's c; Download scene keeps the group keys. Prints one JSON record.
// Exit 1 on a page error or a failed check.
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
  // picture_plane block (M10); 重設 returns to the scene's block (§5.6, §5.7 implementation notes)
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
    check(c.dl.json === a.dl.json && c.camera.picture_plane !== undefined, `${name}: 重設 returns to the scene's block`);
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
    // M11 review: 復原 is off while a board drag is held (an object step popped mid-drag would drop the drag's step)
    const held = await page.evaluate(() => ({ disabled: document.getElementById("undo").disabled, undo: window.castplane_web.rig.undo }));
    check(held.disabled && held.undo > 0, `plane: 復原 is off while a ring drag is held (${JSON.stringify(held)})`);
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

// M11 (contract §5.8.8): single-object rotation, camera and board fixed
const objrot = {};
{
  const api = (fn, ...args) => page.evaluate(([fn, args]) => window.castplane_web[fn](...args), [fn, args]);
  const get = (key) => page.evaluate((key) => window.castplane_web[key], key);
  const near = (a, b, tol) => Math.abs(a - b) <= tol;
  const wrap = (x) => { const w = x - 360 * Math.ceil((x - 180) / 360); return w <= -180 ? w + 360 : w; };
  /** The fixed environment: camera block, the rig without its undo depth and readouts, scene_block. */
  const env = async () => {
    const r = await get("rig");
    return { camera: JSON.stringify(await get("camera")), scene_block: r.scene_block,
      rig: JSON.stringify({ f: r.f, up: r.up, g: r.g, D: r.D, a: r.a, b: r.b, roll_deg: r.roll_deg, focal: r.focal, P: r.P, E: r.E, Q: r.Q,
        pivot: r.pivot }) };
  };
  const verts = async (ids) => Object.fromEntries(await Promise.all(ids.map(async (id) => [id, JSON.stringify(await api("object_vertices", id))])));
  const warning_codes = () => page.evaluate(() => [...document.querySelectorAll("#warnings tbody tr td:first-child")].map((td) => td.textContent));
  const undo_size = async () => (await get("rig")).undo;
  /** Render a scene file with the Python CLI; its SVG text. */
  const cli_svg = (path) => {
    const out = join(outdir, "m11_cli");
    mkdirSync(out, { recursive: true });
    execSync(`python3 -c "import sys; from castplane.cli import main; sys.exit(main(sys.argv[1:]))" render ${JSON.stringify(path)} -o ${JSON.stringify(out)} --formats svg`,
      { cwd: ROOT, stdio: "pipe" });
    return readFileSync(join(out, path.split("/").at(-1).replace(/\.json$/, ".svg")), "utf-8");
  };
  await page.evaluate(() => window.castplane_web.set_observer(true));
  await page.evaluate(() => window.castplane_web.load_example("basic"));
  await frames2();
  await frames2();
  {
    // basic: the crate about z by 30°
    const e0 = await env(), v0 = await verts(["crate", "pillar"]), svg0 = await get("svg"), u0 = await undo_size();
    const t0 = await api("object_transform", "crate"), c0 = await api("object_centre", "crate");
    const t1 = await api("rotate_object", "crate", 2, 30);
    await frames2();
    const e1 = await env(), v1 = await verts(["crate", "pillar"]), svg1 = await get("svg"), c1 = await api("object_centre", "crate");
    objrot.basic = { t0, t1 };
    check(t1 !== null && near(wrap(t1.rotation_deg[2] - t0.rotation_deg[2] - 30), 0, 1e-9) && t1.rotation_deg[0] === t0.rotation_deg[0]
      && t1.rotation_deg[1] === t0.rotation_deg[1], `M11: crate about z by 30° (${JSON.stringify(t1)})`);
    check(JSON.stringify(e1) === JSON.stringify(e0), "M11: basic: camera block, rig and scene_block unchanged");
    check(v1.pillar === v0.pillar && v1.crate !== v0.crate, "M11: basic: the pillar's vertices identical, the crate's changed");
    check(c0.every((x, i) => near(x, c1[i], 1e-9)), "M11: the crate's pivot c_w is fixed");
    check(svg1 !== svg0 && await undo_size() === u0 + 1, "M11: the drawing changes; one undo step");
    // download the rotated scene: the Python CLI renders the same SVG as the page (all layers checked, as the file's)
    await page.click("#construction-lines");
    await frames2();
    const page_svg = (await page.evaluate(() => window.castplane_web.download_texts())).svg;
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#dl-scene")]);
    const path = join(outdir, "m11_basic_rotated.scene.json");
    await dl.saveAs(path);
    const saved = JSON.parse(readFileSync(path, "utf-8"));
    const crate = saved.objects.find((o) => o.id === "crate");
    check(JSON.stringify(crate.transform.rotation_deg) === JSON.stringify(t1.rotation_deg)
      && JSON.stringify(crate.transform.position) === JSON.stringify(t1.position), "M11: Download scene writes the rotated transform");
    let cli = null;
    try {
      cli = cli_svg(path);
    } catch (e) {
      objrot.cli_error = String(e.stderr ?? e);
    }
    objrot.cli = { same: cli === page_svg, cli_chars: cli?.length ?? null, page_chars: page_svg.length };
    check(cli !== null && cli === page_svg, "M11: the downloaded rotated scene through the Python CLI gives download_texts().svg");
    await page.click("#construction-lines");
    await frames2();
    // undo: the SVG byte-identical to the one before the rotation
    await page.click("#undo");
    await frames2();
    const t2 = await api("object_transform", "crate");
    check(JSON.stringify(t2) === JSON.stringify(t0) && await get("svg") === svg0 && JSON.stringify(await verts(["crate", "pillar"])) === JSON.stringify(v0)
      && await undo_size() === u0, "M11: undo restores the pose, the vertices and the byte-identical SVG");
  }
  {
    // D83 (modeless): no selection after load; a real click on an object selects it (no mode button) and its rings are
    // drawn together with the board's handles; a ring drag with frames is live; a click on blank space clears it
    const ob = await page.locator("#observer").boundingBox();
    /** Pane px where a click lands on object `id` (not on a handle), or null. */
    const click_px = (id) => page.evaluate((id) => {
      const w = window.castplane_web, c = w.objects_px?.[id];
      if (!c) return null;
      for (let k = 0; k < 81; k++) {
        const x = c[0] + ((k % 9) - 4) * 4, y = c[1] + (Math.floor(k / 9) - 4) * 4;
        if (w.hit_at(x, y) === null && w.pick_at(x, y) === id) return [x, y];
      }
      return null;
    }, id);
    /** Pane px of blank space: no handle and no object under it. */
    const blank_px = () => page.evaluate(() => {
      const w = window.castplane_web, [W, H] = w.observer.size;
      for (let k = 0; k < 400; k++) {
        const x = 20 + (k % 20) * (W - 40) / 19, y = 20 + Math.floor(k / 20) * (H - 40) / 19;
        if (w.hit_at(x, y) === null && w.pick_at(x, y) === null) return [x, y];
      }
      return null;
    });
    const sel0 = await get("rotate");
    check(sel0.id === null && await get("object_rings_px") === null && await page.evaluate(() => document.getElementById("obj-select").value) === ""
      && await page.evaluate(() => document.getElementById("rotate-mode")) === null,
    `D83: basic loads with no selection and there is no 轉動物體 button (${JSON.stringify(sel0.id)})`);
    const cp = await click_px("crate");
    check(cp !== null, "D83: a clickable point on the crate");
    if (cp !== null) {
      await page.mouse.click(ob.x + cp[0], ob.y + cp[1]);
      await frames2();
      await frames2();
    }
    const rot = await get("rotate");
    const names = (await get("observer")).names;
    check(rot.id === "crate" && await get("object_rings_px") !== null && await get("handles_px") !== null
      && await page.evaluate(() => document.getElementById("obj-select").value) === "crate",
    "D83: a real click on the crate selects it (dropdown synced); its rings and the board's handles are both drawn");
    check(["object-ring:x", "object-ring:y", "object-ring:z", "handle:ring", "handle:arrow"].every((n) => names.includes(n)),
      "D83: the three object rings and the board's ring and arrow are drawn together");
    /** A hit-testable point of the selected object's ring `axis` with room around it (pane px), or null. */
    const ring_point = (axis, touch = false) => page.evaluate(([axis, touch]) => {
      const r = window.castplane_web.object_rings_px;
      if (r === null) return null;
      const [W, H] = r.size;
      for (const q of r.rings[axis]) {
        if (q === null || q[0] < 80 || q[0] > W - 80 || q[1] < 80 || q[1] > H - 80) continue;
        const hit = window.castplane_web.hit_at(q[0], q[1]);
        if (hit !== null && hit.kind === "object_ring" && hit.axis === axis) return q;
      }
      return null;
    }, [axis, touch]);
    // hovering an object ring shows the pointer cursor (the on-handle state covers the object rings)
    const qh = await ring_point(2);
    if (qh !== null) {
      await page.mouse.move(ob.x + qh[0], ob.y + qh[1]);
      await frames2();
      const cur = await page.evaluate(([x, y]) => getComputedStyle(document.elementFromPoint(x, y)).cursor, [ob.x + qh[0], ob.y + qh[1]]);
      check(cur === "pointer", `D83: hovering an object ring shows the pointer cursor (${cur})`);
    }
    const q = await ring_point(2);
    check(q !== null, "M11: a z-ring point is hit-testable");
    if (q !== null) {
      const t0 = await api("object_transform", "crate"), u0 = await undo_size();
      const n0 = (await get("frames")).length, runs0 = (await get("timings")).stage_a_runs;
      await page.click("#snap"); // snapping off: every step is a new pose (15° steps would repeat the same one)
      await page.mouse.move(ob.x + q[0], ob.y + q[1]);
      await page.mouse.down();
      for (let i = 1; i <= 8; i++) {
        await page.mouse.move(ob.x + q[0] + 6 * i, ob.y + q[1] + 4 * i);
        await frames2();
      }
      const mid = await get("timings");
      const undo_held = await page.evaluate(() => document.getElementById("undo").disabled);
      await page.mouse.up();
      await frames2();
      await page.click("#snap");
      const fr = (await get("frames")).slice(n0), t1 = await api("object_transform", "crate");
      objrot.drag = { drag_frames: fr.filter((f) => f.dragging).length, stage_a_runs: [runs0, mid.stage_a_runs], stage_a_ms: mid.stage_a_ms };
      check(fr.filter((f) => f.dragging).length >= 3 && mid.stage_a_runs >= runs0 + 3 && typeof mid.stage_a_ms === "number",
        `M11: a ring drag records drag frames with live stage-A runs (${JSON.stringify(objrot.drag)})`);
      check(JSON.stringify(t1) !== JSON.stringify(t0) && t1.rotation_deg[0] === t0.rotation_deg[0] && t1.rotation_deg[1] === t0.rotation_deg[1]
        && await undo_size() === u0 + 1, "M11: the z-ring drag (no mode button) turns rz only, one undo step");
      check(undo_held && !(await page.evaluate(() => document.getElementById("undo").disabled)), "M11: 復原 is off while a ring drag is held, on after it");
      await page.click("#undo");
      await frames2();
    }
    // fast drag: pointerdown → one pointermove → pointerup in one task (no frame in between)
    const q2 = await ring_point(2);
    if (q2 !== null) {
      const t0 = await api("object_transform", "crate"), u0 = await undo_size(), runs0 = (await get("timings")).stage_a_runs;
      const fast = await page.evaluate(([x, y]) => {
        const el = document.getElementById("observer"), b = el.getBoundingClientRect();
        const ev = (type, dx, dy) => new PointerEvent(type, { bubbles: true, cancelable: true, pointerId: 1, pointerType: "mouse",
          isPrimary: true, button: 0, buttons: type === "pointerup" ? 0 : 1, clientX: b.left + x + dx, clientY: b.top + y + dy });
        let frames = 0;
        const id = requestAnimationFrame(() => { frames += 1; });
        el.dispatchEvent(ev("pointerdown", 0, 0));
        el.dispatchEvent(ev("pointermove", 45, 30));
        el.dispatchEvent(ev("pointerup", 45, 30));
        const out = { frames, t: window.castplane_web.object_transform("crate"), undo: window.castplane_web.rig.undo,
          runs: window.castplane_web.timings.stage_a_runs };
        cancelAnimationFrame(id);
        return out;
      }, q2);
      objrot.fast = fast;
      check(fast.frames === 0 && JSON.stringify(fast.t) !== JSON.stringify(t0) && fast.undo === u0 + 1 && fast.runs === runs0 + 1,
        `M11: pointerdown → one move → pointerup without a frame commits the last pose (${JSON.stringify(fast)})`);
      await frames2();
      await page.click("#undo");
      await frames2();
    } else check(false, "M11: a ring point for the fast drag");
    // second-finger cancel (touch): pose, vertices, SVG and undo as before the press
    const q3 = await ring_point(2, true);
    if (q3 !== null) {
      const t0 = await api("object_transform", "crate"), v0 = await verts(["crate"]), svg0 = await get("svg"), u0 = await undo_size();
      const cdp = await page.context().newCDPSession(page);
      const X = ob.x + q3[0], Y = ob.y + q3[1];
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: X, y: Y, id: 1 }] });
      for (let i = 1; i <= 4; i++) {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x: X + 10 * i, y: Y + 6 * i, id: 1 }] });
        await frames2();
      }
      const moved = await api("object_transform", "crate");
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x: X + 40, y: Y + 24, id: 1 }, { x: X - 120, y: Y + 80, id: 2 }] });
      await frames2();
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await frames2();
      await frames2();
      await cdp.detach();
      const t1 = await api("object_transform", "crate");
      objrot.cancel = { moved: JSON.stringify(moved) !== JSON.stringify(t0), restored: JSON.stringify(t1) === JSON.stringify(t0) };
      check(objrot.cancel.moved, "M11: the touch ring drag moved the crate before the second finger");
      check(JSON.stringify(t1) === JSON.stringify(t0) && JSON.stringify(await verts(["crate"])) === JSON.stringify(v0)
        && await get("svg") === svg0 && await undo_size() === u0, "M11: a second finger cancels (pose, vertices, SVG, undo as before)");
    } else check(false, "M11: a ring point for the touch drag");
    // with 旋轉中心 = 場景中心 a click on the pillar selects it and leaves the pivot alone
    const pivot0 = (await get("rig")).pivot;
    const pp = await click_px("pillar");
    check(pp !== null, "D83: a clickable point on the pillar");
    if (pp !== null) {
      await page.mouse.click(ob.x + pp[0], ob.y + pp[1]);
      await frames2();
      const r = await get("rotate");
      check(r.id === "pillar" && JSON.stringify((await get("rig")).pivot) === JSON.stringify(pivot0)
        && await page.evaluate(() => document.getElementById("obj-select").value) === "pillar",
      "D83: a click on the pillar selects it (dropdown synced); the scene-centre pivot unchanged");
    }
    // with 旋轉中心 = 點選物體 the same click also picks the pivot (no undo step)
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    const u_p = await undo_size();
    const cp2 = await click_px("crate");
    if (cp2 !== null) {
      await page.mouse.click(ob.x + cp2[0], ob.y + cp2[1]);
      await frames2();
      await frames2();
    }
    const rp = await get("rig"), sp = await get("rotate");
    objrot.pivot_click = { pivot: rp.pivot, selected: sp.id };
    check(cp2 !== null && rp.pivot.mode === "object" && rp.pivot.object_id === "crate" && sp.id === "crate" && rp.undo === u_p,
      `D83: pivot 點選物體 + a click on the crate sets the pivot and selects it (${JSON.stringify(objrot.pivot_click)})`);
    // D83 review: a second click on the selected crate (re-picking the pivot) keeps an unapplied typed angle
    // (the point is taken again now that the crate's rings are drawn, so the click is not on a ring)
    const cp3 = await click_px("crate");
    check(cp3 !== null, "D83 review: a clickable point on the selected crate");
    if (cp3 !== null) {
      const t_re = await api("object_transform", "crate"), u_re = await undo_size();
      await page.fill("#obj-rx", "30");
      await page.mouse.click(ob.x + cp3[0], ob.y + cp3[1]);
      await frames2();
      await frames2();
      const re = { rx: await page.evaluate(() => document.getElementById("obj-rx").value), id: (await get("rotate")).id,
        active: await page.evaluate(() => document.activeElement?.id ?? null) };
      objrot.reclick_typed = re;
      check(re.rx === "30" && re.id === "crate" && JSON.stringify(await api("object_transform", "crate")) === JSON.stringify(t_re)
        && await undo_size() === u_re, `D83 review: a click on the selected object keeps the typed rx text (${JSON.stringify(re)})`);
      await page.press("#obj-rx", "Escape");
      await frames2();
      check((await page.evaluate(() => document.getElementById("obj-rx").value)) !== "30", "D83 review: Escape then drops the typed rx text");
    }
    await page.selectOption("#pivot-mode", "scene");
    await frames2();
    // a click on blank space clears the selection (rings gone, dropdown "—"); the board's handles stay
    const bp = await blank_px();
    check(bp !== null, "D83: a blank point in the observer pane");
    if (bp !== null) {
      await page.mouse.click(ob.x + bp[0], ob.y + bp[1]);
      await frames2();
      await frames2();
    }
    check((await get("rotate")).id === null && await get("object_rings_px") === null && await get("handles_px") !== null
      && await page.evaluate(() => document.getElementById("obj-select").value) === ""
      && !(await get("observer")).names.includes("object-ring:x"),
    "D83: a click on blank space clears the selection (rings gone), the board's handles stay");
  }
  {
    // D83: the left pane's 「板子」 checkbox hides the board group and its labels there only; the page SVG is unchanged;
    // the board handles are not hit; a click on an object still selects it; object rings stay usable
    const ob = await page.locator("#observer").boundingBox();
    const h0 = await get("handles_px"), o0 = await get("observer");
    const svg0 = await get("svg"), dl0 = await api("download_texts"), cam0 = JSON.stringify(await get("camera")), u0 = await undo_size();
    const overlay0 = await page.evaluate(() => document.querySelector("svg.overlay")?.outerHTML ?? null);
    check(o0.board_shown && o0.labels_shown > 0 && await page.evaluate(() => document.getElementById("observer-board").checked),
      "D83: 板子 is checked by default, the board and its labels shown");
    await page.click("#observer-board");
    await frames2();
    await frames2();
    const o1 = await get("observer");
    const tip_hit = await page.evaluate(([x, y]) => window.castplane_web.hit_at(x, y), h0.tip);
    const ring_q = h0.ring.find((p) => p !== null);
    const ring_hit = await page.evaluate(([x, y]) => window.castplane_web.hit_at(x, y), ring_q);
    objrot.board_off = { board_shown: o1.board_shown, labels_shown: o1.labels_shown, names: o1.names, tip_hit, ring_hit };
    check(!o1.board_shown && o1.labels_shown === 0 && !o1.names.includes("board:frame") && !o1.names.includes("handle:ring")
      && !o1.names.includes("dots:E") && !(await api("board_visible")), `D83: 板子 unchecked hides the board group and its labels (${JSON.stringify({ shown: o1.board_shown, labels: o1.labels_shown })})`);
    check(await get("handles_px") === null && tip_hit === null && (ring_hit === null || ring_hit.kind === "object_ring"),
      `D83: 板子 unchecked: handles_px null, the board's tip and ring are not hit (${JSON.stringify({ tip_hit, ring_hit })})`);
    check(o1.names.includes("rays:sight") === o0.names.includes("rays:sight"), "D83: the 視線 rays follow their own checkbox");
    await page.mouse.move(ob.x + h0.tip[0], ob.y + h0.tip[1]);
    await frames2();
    const cur = await page.evaluate(([x, y]) => getComputedStyle(document.elementFromPoint(x, y)).cursor, [ob.x + h0.tip[0], ob.y + h0.tip[1]]);
    check(cur !== "pointer", `D83: the hidden arrow tip is not hover-highlighted (${cur})`);
    await page.mouse.move(ob.x + 4, ob.y + 4);
    const overlay1 = await page.evaluate(() => document.querySelector("svg.overlay")?.outerHTML ?? null);
    check(await get("svg") === svg0 && JSON.stringify(await api("download_texts")) === JSON.stringify(dl0) && overlay1 === overlay0
      && JSON.stringify(await get("camera")) === cam0 && await undo_size() === u0,
    "D83: 板子 unchecked: the page SVG, overlay, downloads, camera block and undo are byte-identical");
    // a real click on an object still selects it, and its rings are drawn and usable
    const objs = await get("objects_px");
    let cp = null;
    if (objs.crate !== null) {
      cp = await page.evaluate((c) => {
        const w = window.castplane_web;
        for (let k = 0; k < 81; k++) {
          const x = c[0] + ((k % 9) - 4) * 4, y = c[1] + (Math.floor(k / 9) - 4) * 4;
          if (w.hit_at(x, y) === null && w.pick_at(x, y) === "crate") return [x, y];
        }
        return null;
      }, objs.crate);
    }
    if (cp !== null) {
      await page.mouse.click(ob.x + cp[0], ob.y + cp[1]);
      await frames2();
      await frames2();
    }
    const o2 = await get("observer");
    check(cp !== null && (await get("rotate")).id === "crate" && await get("object_rings_px") !== null && o2.names.includes("object-ring:z")
      && !o2.board_shown && o2.labels_shown === 0, "D83: 板子 unchecked: a real click on the crate selects it, its rings drawn");
    const t0 = await api("object_transform", "crate");
    const zr = await page.evaluate(() => {
      const r = window.castplane_web.object_rings_px, [W, H] = r.size;
      for (const q of r.rings[2]) {
        if (q === null || q[0] < 80 || q[0] > W - 80 || q[1] < 80 || q[1] > H - 80) continue;
        const hit = window.castplane_web.hit_at(q[0], q[1]);
        if (hit !== null && hit.kind === "object_ring" && hit.axis === 2) return q;
      }
      return null;
    });
    if (zr !== null) await drag(6, "#observer", [8, 5], zr);
    check(zr !== null && JSON.stringify(await api("object_transform", "crate")) !== JSON.stringify(t0) && await undo_size() === u0 + 1,
      "D83: 板子 unchecked: an object-ring drag rotates the crate (one undo step)");
    await page.click("#undo");
    await frames2();
    await page.click("#observer-board");
    await frames2();
    await frames2();
    const o3 = await get("observer");
    check(o3.board_shown && o3.labels_shown > 0 && await get("handles_px") !== null && await get("svg") === svg0,
      "D83: 板子 checked again: the board, its labels and handles are back, the SVG unchanged");
    // a toggle while a board-ring drag is held is ignored (the checkbox stays checked)
    await api("select_object", null);
    await frames2();
    const rq = await ring_px(60);
    check(rq !== null, "D83: a board-ring point for the held drag");
    if (rq !== null) {
      await page.mouse.move(ob.x + rq[0], ob.y + rq[1]);
      await page.mouse.down();
      await page.mouse.move(ob.x + rq[0] + 20, ob.y + rq[1] + 4);
      await frames2();
      const res = await api("set_board_visible", false);
      const held = { res, checked: await page.evaluate(() => document.getElementById("observer-board").checked),
        shown: (await get("observer")).board_shown };
      await page.mouse.up();
      await frames2();
      objrot.board_toggle_held = held;
      check(held.res === true && held.checked && held.shown && await api("board_visible"),
        `D83: a 板子 change during a held board-ring drag is ignored (${JSON.stringify(held)})`);
      await page.click("#undo");
      await frames2();
    }
  }
  {
    // D83: no selection after a load, also for a single-object scene
    const data = JSON.parse(readFileSync(join(ROOT, "examples", "basic.json"), "utf-8"));
    data.objects = data.objects.filter((o) => o.id === "crate");
    await api("select_object", "crate");
    await page.evaluate((t) => window.castplane_web.load_text("basic_single", t), JSON.stringify(data));
    await frames2();
    await frames2();
    const single = { id: (await get("rotate")).id, rings: await get("object_rings_px"), select: await page.evaluate(() => document.getElementById("obj-select").value),
      options: await page.evaluate(() => document.getElementById("obj-select").options.length) };
    check(single.id === null && single.rings === null && single.select === "" && single.options === 2,
      `D83: a single-object scene loads with no selection (${JSON.stringify(single)})`);
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await frames2();
    await frames2();
  }
  {
    // D84: groups of parts. The fixture is basic with the crate and the pillar in group "g" plus an ungrouped post
    // (web/test/fixtures/basic_grouped.json; examples/ is not touched). Real clicks run the cycle whole → part → whole;
    // blank space clears; another part after part focus moves the focus; rotate_group turns every member about c
    // with the camera fixed and undo gives the byte-identical SVG; the dropdown, fields, 還原 and the download keep groups.
    const ob = await page.locator("#observer").boundingBox();
    const text = readFileSync(join(ROOT, "web", "test", "fixtures", "basic_grouped.json"), "utf-8");
    const loaded = await page.evaluate((t) => window.castplane_web.load_text("basic_grouped", t), text);
    await frames2();
    await frames2();
    const d84 = (objrot.d84 = {});
    const sel = () => api("selection");
    const click_px = (id) => page.evaluate((id) => {
      const w = window.castplane_web, c = w.objects_px?.[id];
      if (!c) return null;
      for (let k = 0; k < 225; k++) {
        const x = c[0] + ((k % 15) - 7) * 3, y = c[1] + (Math.floor(k / 15) - 7) * 3;
        if (w.hit_at(x, y) === null && w.pick_at(x, y) === id) return [x, y];
      }
      return null;
    }, id);
    const blank_px = () => page.evaluate(() => {
      const w = window.castplane_web, [W, H] = w.observer.size;
      for (let k = 0; k < 400; k++) {
        const x = 20 + (k % 20) * (W - 40) / 19, y = 20 + Math.floor(k / 20) * (H - 40) / 19;
        if (w.hit_at(x, y) === null && w.pick_at(x, y) === null) return [x, y];
      }
      return null;
    });
    /** A real click on object `id` (a point that is on the object and on no handle); false when none was found. */
    const click_on = async (id) => {
      const p = await click_px(id);
      if (p === null) return false;
      await page.mouse.click(ob.x + p[0], ob.y + p[1]);
      await frames2();
      await frames2();
      return true;
    };
    const opts = await page.evaluate(() => [...document.getElementById("obj-select").options].map((o) => [o.value, o.textContent]));
    const groups = await api("object_groups");
    d84.load = { loaded, opts, groups };
    check(loaded && JSON.stringify(groups.units) === JSON.stringify({ g: ["crate", "pillar"] }) && groups.groups.post === undefined
      && (await sel()) === null, `D84: the grouped fixture loads with group g = crate + pillar and no selection (${JSON.stringify(groups)})`);
    check(JSON.stringify(opts) === JSON.stringify([["", "—"], ["group.g", "g（整組，2 個部件）"], ["crate", "crate"], ["pillar", "pillar"], ["post", "post"]]),
      `D84: the 物體 dropdown lists the group first, then every object (${JSON.stringify(opts)})`);
    // the click cycle with real mouse clicks
    const cycle = [];
    const step = async (id) => {
      const ok = id === null ? await (async () => {
        const bp = await blank_px();
        if (bp === null) return false;
        await page.mouse.click(ob.x + bp[0], ob.y + bp[1]);
        await frames2();
        await frames2();
        return true;
      })() : await click_on(id);
      const s = await sel();
      cycle.push({ click: id, ok, sel: s, text: (await get("rotate")).selected_text, value: await page.evaluate(() => document.getElementById("obj-select").value) });
      return s;
    };
    const s1 = await step("crate");
    const rings_g = await get("object_rings_px");
    const s2 = await step("crate");
    const rings_p = await get("object_rings_px");
    const s3 = await step("crate");
    const s4 = await step(null);
    const rings_blank = await get("object_rings_px");
    await step("crate");
    const s6 = await step("crate");
    const s7 = await step("pillar");
    const s8 = await step("post");
    const s9 = await step("pillar");
    d84.cycle = cycle;
    check(cycle.every((c) => c.ok), `D84: every cycle click found a point on its object off the rings (${JSON.stringify(cycle.map((c) => c.ok))})`);
    check(s1?.kind === "group" && s1.group === "g" && JSON.stringify(s1.members) === JSON.stringify(["crate", "pillar"])
      && cycle[0].text === "已選：g（整組）" && cycle[0].value === "group.g", `D84: the first click on the crate selects the whole group (${JSON.stringify(cycle[0])})`);
    check(s2?.kind === "part" && s2.id === "crate" && s2.group === "g" && cycle[1].text === "已選：crate（g 的部件）" && cycle[1].value === "crate",
      `D84: the second click focuses the crate as a part (${JSON.stringify(cycle[1])})`);
    check(s3?.kind === "group" && s3.group === "g", `D84: the third click returns to the whole group (${JSON.stringify(s3)})`);
    check(s4 === null && cycle[3].value === "" && cycle[3].text === "" && rings_blank === null,
      "D84: a click on blank space clears the selection (rings gone)");
    check(s6?.kind === "part" && s6.id === "crate" && s7?.kind === "part" && s7.id === "pillar",
      `D84: after part focus a click on the other part moves the focus to it (${JSON.stringify([s6, s7])})`);
    check(s8?.kind === "part" && s8.id === "post" && s8.group === null && s9?.kind === "group" && s9.group === "g",
      `D84: an ungrouped object selects as in D83; from it a grouped click selects the whole group (${JSON.stringify([s8, s9])})`);
    const radius = (r) => r === null ? 0 : Math.max(...r.rings[2].filter((q) => q !== null).map((q) => Math.hypot(q[0] - r.centre[0], q[1] - r.centre[1])));
    check(rings_g?.id === "group.g" && rings_p?.id === "crate" && radius(rings_g) > radius(rings_p),
      `D84: the group's rings are larger than the part's (${radius(rings_g).toFixed(1)} vs ${radius(rings_p).toFixed(1)} px)`);
    // rotate_group 30° about z: every member changes, the post and the camera do not; undo is byte-identical
    const e0 = await env(), v0 = await verts(["crate", "pillar", "post"]), svg0 = await get("svg"), u0 = await undo_size();
    const c0 = await api("group_centre", "g");
    const rg = await api("rotate_group", "g", 2, 30);
    await frames2();
    const e1 = await env(), v1 = await verts(["crate", "pillar", "post"]), c1 = await api("group_centre", "g"), gr = await api("group_rotation", "g");
    d84.rotate = { rg, gr, c0, c1 };
    check(rg !== null && v1.crate !== v0.crate && v1.pillar !== v0.pillar && v1.post === v0.post,
      "D84: rotate_group changes every member's vertices, not the ungrouped post's");
    check(JSON.stringify(e1) === JSON.stringify(e0), "D84: rotate_group keeps the camera block, the rig and scene_block");
    check(JSON.stringify(c1) === JSON.stringify(c0) && near(gr[2], 30, 1e-9) && near(gr[0], 0, 1e-9) && near(gr[1], 0, 1e-9)
      && await undo_size() === u0 + 1 && await get("svg") !== svg0, `D84: c fixed, the group shows rz = 30, one undo step (${JSON.stringify(gr)})`);
    await page.click("#undo");
    await frames2();
    check(await get("svg") === svg0 && JSON.stringify(await verts(["crate", "pillar", "post"])) === JSON.stringify(v0)
      && JSON.stringify(await api("group_rotation", "g")) === JSON.stringify([0, 0, 0]) && await undo_size() === u0,
    "D84: undo of the group step restores every member, G and the SVG byte for byte");
    // the panel: the dropdown's group entry, a typed rz for the whole group, 還原此物體 for the whole group
    await page.selectOption("#obj-select", "group.g");
    await frames2();
    const s10 = await sel();
    // D84 review: 套用 with no field edited is a no-op on a group (no undo step, no ulp drift of the members)
    await page.click("#obj-apply");
    await frames2();
    check(await undo_size() === u0 && await get("svg") === svg0 && JSON.stringify(await verts(["crate", "pillar", "post"])) === JSON.stringify(v0),
      "D84 review: an unedited 套用 on the whole group records no undo step and keeps every member");
    await page.fill("#obj-rz", "45");
    await page.press("#obj-rz", "Enter");
    await frames2();
    const gr45 = await api("group_rotation", "g"), v45 = await verts(["crate", "pillar", "post"]);
    const fields45 = (await get("rotate")).fields.map((f) => f.value);
    await page.click("#obj-restore");
    await frames2();
    d84.panel = { s10, gr45, fields45 };
    check(s10?.kind === "group" && near(gr45[2], 45, 1e-9) && v45.crate !== v0.crate && v45.pillar !== v0.pillar && v45.post === v0.post
      && JSON.stringify(fields45) === JSON.stringify(["0.0", "0.0", "45.0"]),
    `D84: the dropdown selects the group; a typed rz turns the whole group (${JSON.stringify(d84.panel)})`);
    check(await get("svg") === svg0 && JSON.stringify(await verts(["crate", "pillar", "post"])) === JSON.stringify(v0)
      && JSON.stringify(await api("group_rotation", "g")) === JSON.stringify([0, 0, 0]) && await undo_size() === u0 + 2,
    "D84: 還原此物體 on the group restores every member (one more undo step)");
    await page.click("#undo");
    await frames2();
    await page.click("#undo");
    await frames2();
    check(await get("svg") === svg0 && await undo_size() === u0, "D84: two undos restore the SVG byte for byte");
    // a real ring drag on the group's z ring: every member turns, one undo step; interior clicks still pick parts
    const zr = await page.evaluate(() => {
      const r = window.castplane_web.object_rings_px, [W, H] = r.size;
      for (const q of r.rings[2]) {
        if (q === null || q[0] < 80 || q[0] > W - 80 || q[1] < 80 || q[1] > H - 80) continue;
        const hit = window.castplane_web.hit_at(q[0], q[1]);
        if (hit !== null && hit.kind === "object_ring" && hit.axis === 2) return q;
      }
      return null;
    });
    if (zr !== null) await drag(6, "#observer", [8, 5], zr);
    const v2 = await verts(["crate", "pillar", "post"]);
    check(zr !== null && v2.crate !== v0.crate && v2.pillar !== v0.pillar && v2.post === v0.post && await undo_size() === u0 + 1
      && (await sel())?.kind === "group", "D84: a real drag on the group's z ring turns every member (one undo step, selection kept)");
    await page.click("#obj-apply"); // unedited fields after a drag (G ≠ I): still no step, no drift
    await frames2();
    check(await undo_size() === u0 + 1 && JSON.stringify(await verts(["crate", "pillar", "post"])) === JSON.stringify(v2),
      "D84 review: an unedited 套用 after a group drag records no undo step and keeps every member");
    await page.click("#undo");
    await frames2();
    // 旋轉中心 = 點選物體: a click selecting the whole group puts the pivot on its c (no undo step)
    await step(null);
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    await click_on("pillar");
    const rp = await get("rig");
    d84.pivot = { pivot: rp.pivot, P: rp.P, c: c0 };
    check(rp.pivot.object_id === "group.g" && rp.P.every((x, i) => near(x, c0[i], 1e-12)) && rp.undo === u0,
      `D84: 點選物體 + a click selecting the group puts the pivot on its centre (${JSON.stringify(d84.pivot)})`);
    const labels = (await get("observer")).labels;
    check(labels.includes("旋轉中心：g（整組）"), `D84: the pivot label names the group (${JSON.stringify(labels)})`);
    await page.selectOption("#pivot-mode", "scene");
    await frames2();
    // select_object keeps meaning "select as a part"; select_group; the download keeps the group keys
    await api("select_object", "pillar");
    const s11 = await sel();
    await api("select_group", "g");
    const s12 = await sel();
    check(s11?.kind === "part" && s11.id === "pillar" && s12?.kind === "group", "D84: select_object selects a part, select_group the group");
    const [dl] = await Promise.all([page.waitForEvent("download"), page.click("#dl-scene")]);
    const path = join(outdir, "d84_basic_grouped.scene.json");
    await dl.saveAs(path);
    const saved = JSON.parse(readFileSync(path, "utf-8"));
    d84.download = saved.objects.map((o) => [o.id, o.group ?? null]);
    check(JSON.stringify(d84.download) === JSON.stringify([["crate", "g"], ["pillar", "g"], ["post", null]]),
      `D84: Download scene keeps the group keys (${JSON.stringify(d84.download)})`);
    // D84 review: a lone-surrogate group name (valid JSON "\ud800x") is no group, so Download scene still writes
    const lone = text.replace(/"group": "g"/g, '"group": "\\ud800x"');
    const loaded_lone = await page.evaluate((t) => window.castplane_web.load_text("basic_lone", t), lone);
    await frames2();
    const units_lone = (await api("object_groups")).units;
    const [dl_lone] = await Promise.all([page.waitForEvent("download"), page.click("#dl-scene")]);
    const path_lone = join(outdir, "d84_lone_surrogate.scene.json");
    await dl_lone.saveAs(path_lone);
    const saved_lone = JSON.parse(readFileSync(path_lone, "utf-8"));
    check(lone !== text && loaded_lone && JSON.stringify(units_lone) === "{}" && saved_lone.objects.every((o) => o.group === undefined),
      `D84 review: a lone-surrogate group is ignored and Download scene still works (${JSON.stringify(units_lone)})`);
    await page.evaluate(() => window.castplane_web.load_example("basic"));
    await frames2();
    await frames2();
    check((await sel()) === null && JSON.stringify((await api("object_groups")).units) === "{}", "D84: loading basic replaces the groups and clears the selection");
  }
  {
    // the panel: a bad field turns red and changes nothing; numeric entry; 還原此物體
    await api("select_object", "crate");
    await frames2();
    const t0 = await api("object_transform", "crate"), u0 = await undo_size();
    await page.fill("#obj-rz", "abc");
    await page.press("#obj-rz", "Enter");
    await frames2();
    const bad = await get("rotate");
    check(bad.fields[2].bad && JSON.stringify(await api("object_transform", "crate")) === JSON.stringify(t0) && await undo_size() === u0,
      "M11: a non-finite field turns red, the pose is kept");
    await page.fill("#obj-rz", "75");
    await page.press("#obj-rz", "Enter");
    await frames2();
    const t1 = await api("object_transform", "crate");
    check(t1.rotation_deg[2] === 75 && t1.rotation_deg[0] === 0 && !(await get("rotate")).fields[2].bad && await undo_size() === u0 + 1,
      "M11: Enter in the rz field applies rz = 75 (one undo step)");
    await page.click("#obj-restore");
    await frames2();
    check(JSON.stringify(await api("object_transform", "crate")) === JSON.stringify(t0) && await undo_size() === u0 + 2,
      "M11: 還原此物體 returns to the load pose (one undo step)");
    // M11 review: the three fields are one entry: typed rx and ry both survive the focus moving on and apply together
    const fields = async () => (await get("rotate")).fields.map((f) => f.value);
    await page.fill("#obj-rx", "10");
    await page.fill("#obj-ry", "20");
    const typed = await fields();
    await page.click("#obj-apply");
    await frames2();
    const tf = await api("object_transform", "crate");
    objrot.fields = { typed, after: tf.rotation_deg };
    check(typed[0] === "10" && typed[1] === "20" && near(tf.rotation_deg[0], 10, 1e-9) && near(tf.rotation_deg[1], 20, 1e-9)
      && near(tf.rotation_deg[2], t0.rotation_deg[2], 1e-9) && await undo_size() === u0 + 3,
    `M11: rx and ry typed in turn, then 套用: both applied as one step (${JSON.stringify(objrot.fields)})`);
    await page.click("#undo");
    await frames2();
    // the same with keystrokes: rx, Tab, ry, Enter
    await page.focus("#obj-rx");
    await page.keyboard.press("Control+A");
    await page.keyboard.type("5");
    await page.keyboard.press("Tab");
    const tab_to = await page.evaluate(() => document.activeElement?.id ?? null);
    await page.keyboard.press("Control+A");
    await page.keyboard.type("15");
    const typed_k = await fields();
    await page.keyboard.press("Enter");
    await frames2();
    const tk = await api("object_transform", "crate");
    check(tab_to === "obj-ry" && typed_k[0] === "5" && near(tk.rotation_deg[0], 5, 1e-9) && near(tk.rotation_deg[1], 15, 1e-9)
      && await undo_size() === u0 + 3, `M11: rx, Tab, ry, Enter applies both (${JSON.stringify({ tab_to, typed_k, r: tk.rotation_deg })})`);
    await page.click("#undo");
    await frames2();
    // Escape drops the typed angles; the fields show the pose again
    const shown0 = await fields();
    await page.fill("#obj-rx", "33");
    await page.press("#obj-rx", "Escape");
    await frames2();
    check(JSON.stringify(await fields()) === JSON.stringify(shown0) && JSON.stringify(await api("object_transform", "crate")) === JSON.stringify(t0)
      && await undo_size() === u0 + 2, "M11: Escape in a field drops the typed angles, the pose kept");
    // a focused, unedited field follows a drag (the drag takes the focus and rewrites the fields)
    await page.focus("#obj-rx");
    const td = await api("rotate_object", "crate", 0, 12);
    await frames2();
    const fd = await fields(), active_d = await page.evaluate(() => document.activeElement?.id ?? null);
    objrot.focused_drag = { fields: fd, rx: td.rotation_deg[0], active: active_d };
    check(fd.every((v, i) => near(Number(v), wrap(td.rotation_deg[i]), 0.0501)) && Math.abs(td.rotation_deg[0]) > 1 && active_d !== "obj-rx",
      `M11: a drag with the rx field focused refreshes the fields (${JSON.stringify(objrot.focused_drag)})`);
    await page.click("#undo");
    await frames2();
    // D83: the object-pivot hint asks for a click on an object (no mode to switch off); the API has no set_rotate_mode
    await page.selectOption("#pivot-mode", "object");
    await frames2();
    const hint = await page.evaluate(() => document.getElementById("notices").textContent);
    const no_mode = await page.evaluate(() => !("set_rotate_mode" in window.castplane_web) && !("on" in window.castplane_web.rotate));
    await page.selectOption("#pivot-mode", "scene");
    await frames2();
    check(hint.includes("請點一下左窗的物體") && !hint.includes("轉動物體") && no_mode,
      `D83: the object-pivot hint names no mode and the hooks have no rotate mode (${hint})`);
    // 預覽: the observer is hidden, the panel still works
    await page.evaluate(() => window.castplane_web.set_preview(true));
    await frames2();
    await page.fill("#obj-rx", "10");
    await page.click("#obj-apply");
    await frames2();
    const tp = await api("object_transform", "crate");
    check(tp.rotation_deg[0] === 10 && await undo_size() === u0 + 3, "M11: in 預覽 the panel's 套用 works");
    await page.evaluate(() => window.castplane_web.set_preview(false));
    await frames2();
  }
  {
    // directional: the spire (cone) about x by 20°: the other three objects unchanged, OBJECT_BELOW_RECEIVER, 落地
    await page.evaluate(() => window.castplane_web.load_example("directional"));
    await frames2();
    await frames2();
    const others = ["post", "crate", "ball"];
    const e0 = await env(), v0 = await verts([...others, "spire"]), svg0 = await get("svg"), c0 = await api("object_centre", "spire");
    check(!(await warning_codes()).includes("OBJECT_BELOW_RECEIVER"), "M11: directional loads without OBJECT_BELOW_RECEIVER");
    const t1 = await api("rotate_object", "spire", 0, 20);
    await frames2();
    const e1 = await env(), v1 = await verts([...others, "spire"]), c1 = await api("object_centre", "spire");
    const codes = await warning_codes();
    objrot.directional = { t1, codes };
    check(t1 !== null && JSON.stringify(e1) === JSON.stringify(e0), "M11: directional: camera block, rig and scene_block unchanged");
    check(others.every((id) => v1[id] === v0[id]) && v1.spire !== v0.spire, "M11: directional: the other objects' vertices identical, the cone's changed");
    check(c0.every((x, i) => near(x, c1[i], 1e-9)), "M11: the cone's pivot c_w is fixed");
    check(codes.includes("OBJECT_BELOW_RECEIVER"), `M11: the x rotation reports OBJECT_BELOW_RECEIVER (expected) (${codes})`);
    await api("select_object", "spire");
    await frames2();
    const g = await get("rotate");
    check(g.ground_shown, "M11: 落地 is shown for the unbounded ground");
    await page.click("#obj-ground");
    await frames2();
    const tg = await api("object_transform", "spire");
    check(!(await warning_codes()).includes("OBJECT_BELOW_RECEIVER") && JSON.stringify(tg.rotation_deg) === JSON.stringify(t1.rotation_deg)
      && tg.position[2] > t1.position[2], "M11: 落地 lifts the cone onto the ground (warning gone, rotation kept)");
    await page.click("#undo");
    await frames2();
    await page.click("#undo");
    await frames2();
    check(await get("svg") === svg0 && JSON.stringify(await verts([...others, "spire"])) === JSON.stringify(v0), "M11: directional: two undos restore the SVG byte for byte");
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
console.log(JSON.stringify({ engine, first, toggles: toggle_checks, preview: preview_checks, rows, load_errors, phase2, observer, plane, objrot, failures, downloads, errors: { not_json, scene_error }, logs }, null, 1));
await browser.close();
process.exitCode = logs.some((l) => l.startsWith("pageerror")) || failures.length > 0 ? 1 : 0;

/** Tests of the 3D views' per-object colours (`web/src/colours.ts`; contract §5.4.10, §5.4 notes): parsing the optional
 * `objects[i].display_color` of a raw scene, the per-object choice with its palette fallback, the scene download
 * keeping the key, and the core ignoring it (§2.0: the same document, SVG and warnings with and without it). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { LAYER_ORDER, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { Scene } from "castplane";

import {
  DISPLAY_COLOR_KEY, PALETTE, display_color_text, display_colours, display_colours_text, object_colour, parse_display_color,
} from "../src/colours.js";
import { scene_blob } from "../src/download.js";
import { camera_from_orbit, orbit_from_camera } from "../src/orbit.js";

// web/build/test/colours.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
type Raw = Record<string, unknown> & { objects: Record<string, unknown>[] };
const raw = (name: string): Raw => JSON.parse(readFileSync(resolve(ROOT, "examples", `${name}.json`), "utf-8"));

/** `raw` with `display_color` set per object id (a deep copy). */
function coloured(r: Raw, colours: Record<string, unknown>): Raw {
  const out = JSON.parse(JSON.stringify(r)) as Raw;
  for (const o of out.objects) if (typeof o.id === "string" && o.id in colours) o[DISPLAY_COLOR_KEY] = colours[o.id];
  return out;
}

/** The scene camera's document text, SVG text (all layers and the scene's own) and warnings. */
function render(scene: Scene): { json: string; svg: string; svg_all: string; warnings: string } {
  const doc = compose(scene, project_scene(scene, shadow_geometry(scene)));
  return {
    json: dumps(doc),
    svg: write_svg(doc, scene.output.layers, scene.output.hidden_style ?? "dashed"),
    svg_all: write_svg(doc, LAYER_ORDER),
    warnings: JSON.stringify(doc.warnings),
  };
}

test("parse_display_color: '#rrggbb' in either case; other lengths, no '#', bad digits and non-strings are null", () => {
  assert.equal(parse_display_color("#e8667a"), 0xe8667a);
  assert.equal(parse_display_color("#E8667A"), 0xe8667a);
  assert.equal(parse_display_color("#b9C3e6"), 0xb9c3e6);
  assert.equal(parse_display_color("#000000"), 0);
  assert.equal(parse_display_color("#ffffff"), 0xffffff);
  for (const bad of ["e8667a", "#e8667", "#e8667a0", "#fff", "#e8667g", " #e8667a", "#e8667a ", "#e8667a\n", "",
    "0xe8667a", "#-12345", "rgb(1,2,3)", "red"]) {
    assert.equal(parse_display_color(bad), null, JSON.stringify(bad));
  }
  for (const bad of [0xe8667a, null, undefined, true, ["#e8667a"], { r: 1 }]) assert.equal(parse_display_color(bad), null);
});

test("display_color_text: lower-case '#rrggbb', zero-padded; round-trips with parse_display_color", () => {
  assert.equal(display_color_text(0xe8667a), "#e8667a");
  assert.equal(display_color_text(0x00000f), "#00000f");
  assert.equal(display_color_text(0), "#000000");
  for (const c of [0, 0x0a0b0c, 0xb9c3e6, 0xffffff]) assert.equal(parse_display_color(display_color_text(c)), c);
});

test("display_colours: valid entries by object id; invalid, wrong-typed and malformed entries are skipped", () => {
  const m = display_colours({
    objects: [
      { id: "arm_l", type: "box", display_color: "#e8667a" },
      { id: "arm_r", type: "box", display_color: "#E8667A" },
      { id: "plain", type: "box" },
      { id: "short", display_color: "#fff" },
      { id: "number", display_color: 0xe8667a },
      { id: "nulled", display_color: null },
      { id: 7, display_color: "#123456" },
      { display_color: "#123456" },
      null, "#123456", 42, ["#123456"],
      { id: "ghost", display_color: "#abcdef" },
    ],
  });
  assert.deepEqual([...m.entries()], [["arm_l", 0xe8667a], ["arm_r", 0xe8667a], ["ghost", 0xabcdef]]);
  // no objects array (or not an object at all): empty, never a throw
  for (const bad of [null, undefined, 3, "x", [], {}, { objects: null }, { objects: {} }, { objects: "a" }]) {
    assert.equal(display_colours(bad).size, 0, JSON.stringify(bad));
  }
  // the bundled examples carry no display colours
  for (const name of ["basic", "two_lights", "three_point"]) assert.equal(display_colours(raw(name)).size, 0, name);
});

test("display_colours_text: the parsed text's colours; text that is not JSON gives an empty map", () => {
  const text = JSON.stringify(coloured(raw("basic"), { crate: "#F6C453" }));
  assert.deepEqual([...display_colours_text(text)], [["crate", 0xf6c453]]);
  assert.equal(display_colours_text("{ not json").size, 0);
  assert.equal(display_colours_text("").size, 0);
});

test("object_colour: the display colour when the map has the id, else the palette colour of the index (cycled)", () => {
  assert.equal(PALETTE.length, 8);
  for (let i = 0; i < 20; i++) assert.equal(object_colour(`o${i}`, i), PALETTE[i % 8]);
  const colours = display_colours({ objects: [{ id: "arm_l", display_color: "#e8667a" }, { id: "x", display_color: "#bad" }] });
  assert.equal(object_colour("arm_l", 9, colours), 0xe8667a);
  assert.equal(object_colour("arm_r", 11, colours), PALETTE[11 % 8]); // absent → palette by index, as without the key
  assert.equal(object_colour("x", 2, colours), PALETTE[2]); // invalid → palette
  assert.equal(object_colour("arm_r", 3, new Map()), PALETTE[3]);
  // per object of a coloured scene: the coloured ones take their colour, the others keep their index's palette colour
  const sc = coloured(raw("two_lights"), { crate: "#4b3434", ball: "nope" });
  const m = display_colours(sc);
  assert.deepEqual(load_scene(sc).objects.map((o, i) => object_colour(o.id, i, m)), [0x4b3434, PALETTE[1], PALETTE[2]]);
});

test("the core ignores display_color (§2.0): same validated scene, document, SVG and warnings with and without it", () => {
  for (const name of ["basic", "two_lights", "three_point"]) {
    const r = raw(name);
    const ids = r.objects.map((o) => o.id as string);
    // valid colours on every object, and invalid values of every kind: the validator still ignores the key
    const valid = coloured(r, Object.fromEntries(ids.map((id, i) => [id, i % 2 === 0 ? "#E8667A" : "#b9c3e6"])));
    const invalid = coloured(r, Object.fromEntries(ids.map((id, i) => [id, [42, "#fff", null, { x: 1 }][i % 4]])));
    const base = load_scene(r);
    for (const variant of [valid, invalid]) {
      const sc = load_scene(variant);
      for (const o of sc.objects) assert.ok(!(DISPLAY_COLOR_KEY in o), `${name}: the validated scene drops the key`);
      assert.equal(dumps(sc), dumps(base), `${name}: validated scene`);
      assert.deepEqual(render(sc), render(base), `${name}: document / SVG / warnings`);
      assert.deepEqual(render(load_scene_text(JSON.stringify(variant))), render(base), `${name}: from text`);
    }
  }
});

test("scene_blob keeps display_color for the objects that had a valid one; the reload has the same colours and output", () => {
  const r = coloured(raw("two_lights"), { crate: "#E8667A", ball: "#zzzzzz" });
  const colours = display_colours(r);
  colours.set("ghost", 0x123456); // an id the scene does not have is never written
  const sc = load_scene(r);
  const cam = camera_from_orbit(orbit_from_camera(sc.camera, sc), sc.camera);
  const text = scene_blob(sc, cam, "two_lights", undefined, undefined, colours).text;
  const out = JSON.parse(text) as Raw;
  assert.deepEqual(out.objects.map((o) => o[DISPLAY_COLOR_KEY]), ["#e8667a", undefined, undefined]);
  assert.ok(!text.includes("ghost") && !text.includes("#123456"));
  // the reload: the same colours (normalised to lower case), and the core output of the file without the key
  assert.deepEqual([...display_colours_text(text)], [["crate", 0xe8667a]]);
  const plain = scene_blob(sc, cam, "two_lights").text;
  assert.ok(!plain.includes(DISPLAY_COLOR_KEY));
  assert.equal(scene_blob(sc, cam, "two_lights", undefined, undefined, new Map()).text, plain);
  assert.deepEqual(render(load_scene_text(text)), render(load_scene_text(plain)));
  // only the key differs between the two files
  const stripped = JSON.parse(text) as Raw;
  for (const o of stripped.objects) delete o[DISPLAY_COLOR_KEY];
  assert.equal(dumps(stripped) + "\n", plain);
});

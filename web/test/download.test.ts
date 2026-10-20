/** Tests of the scene download of mesh scenes (`web/src/download.ts::scene_blob`; contract §5.4.10, §5.2.1): the file
 * must be one the Python CLI accepts, so mesh `data.faces` / `data.smooth_groups` (and an integer `node`) are JSON
 * integers (`dumps` writes every other number as a Python float, `26.0`, which `castplane.scene._is_index` rejects), and
 * the validated loader keys `path` / `node` are left out when null; the TS core re-validates the file to the same scene
 * and the same SVG. A scene without mesh objects downloads as before (`dumps({...scene, objects, camera, output})`). */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { LAYER_ORDER, compose, dumps, load_scene, load_scene_text, project_scene, shadow_geometry, write_svg } from "castplane";
import type { Camera, Scene } from "castplane";

import { display_colours } from "../src/colours.js";
import { scene_blob } from "../src/download.js";
import { camera_from_orbit, orbit_from_camera } from "../src/orbit.js";
import type { TargetCamera } from "../src/orbit.js";

// web/build/test/download.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
type Raw = Record<string, unknown> & { objects: Record<string, unknown>[] };
const read = (...parts: string[]): Raw => JSON.parse(readFileSync(resolve(ROOT, ...parts), "utf-8"));
const MESH_SCENES: [string, () => Raw][] = [
  ["mesh_demo (expanded)", () => read("ts", "test", "fixtures", "mesh_demo.expanded.json")],
];
const NON_MESH = ["basic", "construction_demo", "curved_demo", "directional", "three_point", "two_lights", "wall_and_ground"];

/** The UI's camera at load: the explicit target form of the scene camera (`camera_from_orbit`). */
const ui_camera = (sc: Scene): TargetCamera => camera_from_orbit(orbit_from_camera(sc.camera, sc), sc.camera);

/** The text of every value of `"key": [...]` in `text` (bracket-balanced; `dumps` writes no brackets inside numbers). */
function array_texts(text: string, key: string): string[] {
  const out: string[] = [];
  const head = `"${key}": [`;
  for (let at = text.indexOf(head); at >= 0; at = text.indexOf(head, at + 1)) {
    let depth = 0, k = at + head.length - 1;
    for (; k < text.length; k++) {
      if (text[k] === "[") depth++;
      else if (text[k] === "]" && --depth === 0) break;
    }
    out.push(text.slice(at + head.length - 1, k + 1));
  }
  return out;
}

/** The SVG the CLI writes for a scene file (`castplane render`: the scene's layers and hidden style). */
function cli_svg(sc: Scene, cam?: TargetCamera | Camera): string {
  const doc = compose(sc, project_scene(sc, shadow_geometry(sc), cam));
  return write_svg(doc, sc.output.layers, sc.output.hidden_style ?? "dashed");
}

for (const [name, get] of MESH_SCENES) {
  test(`scene_blob of ${name}: mesh faces / smooth_groups are JSON integers, no null loader keys, same scene on reload`, () => {
    const raw = get();
    const sc = load_scene(raw);
    const meshes = sc.objects.filter((o) => o.type === "mesh");
    assert.ok(meshes.length >= 1);
    const cam = ui_camera(sc);
    const text = scene_blob(sc, cam, name, undefined, undefined, display_colours(raw)).text;
    const faces = array_texts(text, "faces"), groups = array_texts(text, "smooth_groups");
    assert.equal(faces.length, meshes.length);
    assert.equal(groups.length, meshes.length);
    for (const t of [...faces, ...groups]) assert.match(t, /^[[\]\s,0-9]+$/, `not integers: ${t.slice(0, 60)}`);
    // the layout is Python's json.dumps(indent=1) at the depth of `data.faces` (4: root, objects, object, data)
    meshes.forEach((m, i) => {
      const at_depth = (v: unknown): string => JSON.stringify(v, null, 1).replace(/\n/g, "\n" + " ".repeat(4));
      assert.equal(faces[i], at_depth(m.data!.faces), `${m.id}: faces layout`);
      assert.equal(groups[i], at_depth(m.data!.smooth_groups), `${m.id}: smooth_groups layout`);
    });
    assert.doesNotMatch(text, /"(node|path)": null/);
    const parsed = JSON.parse(text) as Raw;
    parsed.objects.forEach((o, i) => {
      const m = sc.objects[i]!;
      if (m.type !== "mesh") return;
      if (m.path === null) assert.ok(!("path" in o), `objects[${i}].path`);
      else assert.equal(o.path, m.path);
      if (m.node === null) assert.ok(!("node" in o), `objects[${i}].node`);
      assert.deepEqual((o.data as Record<string, unknown>).faces, m.data!.faces);
      assert.deepEqual((o.data as Record<string, unknown>).smooth_groups, m.data!.smooth_groups);
    });
    // the TS core re-validates the file to the same scene (camera: the downloaded block), and the download of the
    // reloaded scene is the same text
    const again = load_scene_text(text);
    const want = load_scene({ ...sc, camera: cam });
    assert.deepEqual(again, want);
    assert.equal(scene_blob(again, cam, name, undefined, undefined, display_colours(parsed)).text, text);
  });
}

test("scene_blob of mesh_demo (expanded): the reloaded file draws the same SVG (scene camera and an orbited one)", () => {
  const sc = load_scene(read("ts", "test", "fixtures", "mesh_demo.expanded.json"));
  const orbit = orbit_from_camera(sc.camera, sc);
  for (const cam of [ui_camera(sc), camera_from_orbit({ ...orbit, yaw_deg: orbit.yaw_deg + 35, pitch_deg: orbit.pitch_deg - 8 }, sc.camera)]) {
    const again = load_scene_text(scene_blob(sc, cam, "mesh_demo").text);
    assert.equal(cli_svg(again), cli_svg(sc, cam));
    const doc = compose(again, project_scene(again, shadow_geometry(again)));
    assert.equal(write_svg(doc, LAYER_ORDER), write_svg(compose(sc, project_scene(sc, shadow_geometry(sc), cam)), LAYER_ORDER));
  }
});

test("scene_blob of a mesh object with a file source: path kept, an integer node written as an integer", () => {
  const raw = read("ts", "test", "fixtures", "mesh_demo.expanded.json");
  const house = raw.objects.find((o) => o.type === "mesh")!;
  house.node = 3;
  const sc = load_scene(raw);
  const text = scene_blob(sc, sc.camera, "mesh_demo").text;
  assert.match(text, /\n {3}"node": 3,\n/);
  assert.match(text, /\n {3}"path": "meshes\/house\.obj",\n/);
  house.node = "Body";
  const named = scene_blob(load_scene(raw), sc.camera, "mesh_demo").text;
  assert.match(named, /\n {3}"node": "Body",\n/);
  assert.deepEqual(load_scene_text(text).objects, sc.objects);
  // a display colour on a mesh object (web-display-color) is written next to the integer data
  const coloured = scene_blob(sc, sc.camera, "mesh_demo", undefined, undefined, new Map([["house", 0xe8667a]])).text;
  assert.match(coloured, /\n {3}"display_color": "#e8667a",\n/);
  assert.deepEqual([...display_colours(JSON.parse(coloured) as Raw)], [["house", 0xe8667a]]);
  assert.deepEqual(array_texts(coloured, "faces"), array_texts(text, "faces"));
  assert.deepEqual(load_scene_text(coloured), load_scene_text(text));
});

test("scene_blob of a scene without mesh objects is dumps({...scene, objects, camera, output}) as before", () => {
  for (const name of NON_MESH) {
    const raw = read("examples", `${name}.json`);
    const sc = load_scene(raw);
    assert.ok(sc.objects.every((o) => o.type !== "mesh"), name);
    for (const cam of [sc.camera, ui_camera(sc)]) {
      assert.equal(scene_blob(sc, cam, name).text, dumps({ ...sc, camera: cam }) + "\n", name);
      const output = { ...sc.output, hidden_lines: true, hidden_style: "omit" as const };
      assert.equal(scene_blob(sc, cam, name, true, "omit").text, dumps({ ...sc, camera: cam, output }) + "\n", name);
    }
  }
});

test("scene_blob refuses a mesh scene whose text holds the integer placeholder (an object id equal to it)", () => {
  for (const id of ['a"\u0000castplane-int:0', "\u0000castplane-int:0"]) {
    const raw = read("ts", "test", "fixtures", "mesh_demo.expanded.json");
    raw.objects[0]!.id = id;
    const sc = load_scene(raw);
    assert.throws(() => scene_blob(sc, sc.camera, "mesh_demo"), /reserved placeholder/, JSON.stringify(id));
  }
});

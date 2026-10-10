/** Tests of the object library (`web/src/library.ts`; contract §5.8.7, §5.8.9, §5.8.17 row "library"): the preset
 * table, `make_object`, the polygons, the thumbnails, every preset against the port's `validate_scene` and renderer on
 * every bundled example and v8 case, the id rule against the validator, and (when Python and numpy are available)
 * byte parity of the SVG text and the warnings with the Python core. */

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { load_scene, polygon_is_simple, polygon_signed_area, render, shadow_geometry, validate_scene } from "castplane";
import type { Scene, SceneObject, Vec2, Vec3 } from "castplane";

import {
  HEXAGON, LIB_NARROW_PX, LIB_W_PX, PRESETS, THUMBNAILS, THUMB_PX, TILE_NAME_MAX, TRIANGLE, make_object, tile_label,
} from "../src/library.js";
import { basis } from "../src/rig.js";
import { next_id, place_object, used_ids } from "../src/scene_edit.js";

// web/build/test/library.test.js -> repository root
const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const read_json = (...p: string[]): Record<string, unknown> => JSON.parse(readFileSync(resolve(ROOT, ...p), "utf-8"));

function examples(): [string, Record<string, unknown>][] {
  const out: [string, Record<string, unknown>][] = [];
  for (const f of readdirSync(resolve(ROOT, "examples")).filter((f) => f.endsWith(".json")).sort()) {
    const data = read_json("examples", f);
    try {
      load_scene(data);
      out.push([f, data]);
    } catch {
      /* a mesh example that needs expand_scene */
    }
  }
  return out;
}
function cases(): [string, Record<string, unknown>][] {
  const dir = resolve(ROOT, "tests", "conformance", "cases");
  return readdirSync(dir).filter((f) => f.endsWith(".json")).sort().map((f) => [f, read_json("tests", "conformance", "cases", f)]);
}

const unit = (p: readonly number[]): Vec3 => {
  const l = Math.hypot(p[0]!, p[1]!, p[2]!);
  return [p[0]! / l, p[1]! / l, p[2]! / l];
};

/** The preset placed as the page places it (§5.8.8): target from the scene camera, avoidance against stage A. */
function placed(scene: Scene, preset: (typeof PRESETS)[number], snap = true): SceneObject {
  const id = next_id(preset.prefix, used_ids(scene));
  const E = scene.camera.position;
  const f = scene.camera.target !== undefined ? unit([0, 1, 2].map((k) => scene.camera.target![k]! - E[k]!)) : unit([0, 1, -0.3]);
  const A = shadow_geometry(scene);
  const P: Vec3 = [(A.bbox[0][0] + A.bbox[1][0]) / 2, (A.bbox[0][1] + A.bbox[1][1]) / 2, (A.bbox[0][2] + A.bbox[1][2]) / 2];
  const pl = place_object(make_object(preset, id, [0, 0, 0]), { E, f, P, r0: basis(f, null).r0, existing: A.objects.map((o) => o.bbox), snap });
  return make_object(preset, id, pl.position);
}

// ------------------------------------------------------------------------------------------------ the table

test("PRESETS has exactly the 8 rows of §5.8.7", () => {
  const rows = PRESETS.map((p) => ({ name: p.name, type: p.type, params: p.params, prefix: p.prefix }));
  assert.deepEqual(rows, [
    { name: "方塊", type: "box", params: { size: [1.0, 1.0, 1.0] }, prefix: "box" },
    { name: "木箱", type: "box", params: { size: [1.2, 0.9, 0.7] }, prefix: "box" },
    { name: "高柱", type: "box", params: { size: [0.6, 0.6, 1.8] }, prefix: "box" },
    { name: "圓柱", type: "cylinder", params: { radius: 0.3, height: 1.2 }, prefix: "cylinder" },
    { name: "球", type: "sphere", params: { radius: 0.5 }, prefix: "sphere" },
    { name: "圓錐", type: "cone", params: { radius: 0.4, height: 1.0 }, prefix: "cone" },
    { name: "三角柱", type: "prism", params: { polygon: [[0.5774, 0.0], [-0.2887, 0.5], [-0.2887, -0.5]], height: 1.0 }, prefix: "prism" },
    { name: "六角柱", type: "prism", params: {
      polygon: [[0.4, 0.0], [0.2, 0.3464], [-0.2, 0.3464], [-0.4, 0.0], [-0.2, -0.3464], [0.2, -0.3464]], height: 1.0 }, prefix: "prism" },
  ]);
  assert.equal(THUMBNAILS.length, 8);
  assert.deepEqual([LIB_W_PX, LIB_NARROW_PX, THUMB_PX, TILE_NAME_MAX], [232, 880, 64, 6]);
});

test("make_object: {id, type, params, transform} in that order, params deep-copied, rotation zero", () => {
  const obj = make_object(PRESETS[1]!, "box_1", [0.4, 3.1, 0.0]);
  assert.equal(JSON.stringify(obj),
    '{"id":"box_1","type":"box","size":[1.2,0.9,0.7],"transform":{"position":[0.4,3.1,0],"rotation_deg":[0,0,0]}}');
  assert.notEqual(obj.size, PRESETS[1]!.params.size);
  const tri = make_object(PRESETS[6]!, "prism_1", [1, 2, 0]);
  assert.deepEqual(Object.keys(tri), ["id", "type", "polygon", "height", "transform"]);
  (tri.polygon as Vec2[])[0]![0] = 99;
  assert.equal(PRESETS[6]!.params.polygon![0]![0], 0.5774, "the table is not shared");
  assert.deepEqual(make_object(PRESETS[4]!, "sphere_1", [0, 0]).transform.position, [0, 0, 0]);
});

test("polygons: the 1e-4 literals, counter-clockwise, simple, centroid at the origin within 1e-12; apex on +x", () => {
  for (const poly of [TRIANGLE, HEXAGON]) {
    assert.ok(polygon_signed_area(poly as Vec2[]) > 0, "counter-clockwise");
    assert.ok(polygon_is_simple(poly as Vec2[], 1e-12));
    // area centroid
    let a = 0, cx = 0, cy = 0;
    for (let i = 0; i < poly.length; i++) {
      const p = poly[i]!, q = poly[(i + 1) % poly.length]!;
      const w = p[0] * q[1] - q[0] * p[1];
      a += w;
      cx += (p[0] + q[0]) * w;
      cy += (p[1] + q[1]) * w;
    }
    assert.ok(Math.abs(cx / (3 * a)) < 1e-12 && Math.abs(cy / (3 * a)) < 1e-12);
    for (const p of poly) for (const v of p) assert.equal(Math.round(v * 1e4) / 1e4, v, "a 1e-4 literal");
  }
  assert.deepEqual(TRIANGLE[0], [0.5774, 0.0]);
  for (let i = 0; i < 3; i++) {
    const p = TRIANGLE[i]!, q = TRIANGLE[(i + 1) % 3]!;
    assert.ok(Math.abs(Math.hypot(p[0] - q[0], p[1] - q[1]) - 1) < 1e-4, "side 1.0");
  }
  for (const p of HEXAGON) assert.ok(Math.abs(Math.hypot(p[0], p[1]) - 0.4) < 1e-4, "circumradius 0.4");
  assert.deepEqual(HEXAGON[0], [0.4, 0.0]);
});

test("names: at most 6 characters; the tile label is 加入：name", () => {
  for (const p of PRESETS) {
    assert.ok([...p.name].length <= TILE_NAME_MAX, p.name);
    assert.equal(tile_label(p), `加入：${p.name}`);
  }
});

/** A minimal XML well-formedness check: balanced tags, quoted attributes, no text outside the root. */
function parse_xml(s: string): { tags: string[]; attrs: Record<string, string>[] } {
  const stack: string[] = [];
  const tags: string[] = [];
  const attrs: Record<string, string>[] = [];
  let i = 0;
  const re = /<(\/?)([a-zA-Z][\w:-]*)((?:\s+[\w:-]+="[^"<>]*")*)\s*(\/?)>/y;
  while (i < s.length) {
    re.lastIndex = i;
    const m = re.exec(s);
    assert.ok(m !== null, `malformed markup at ${i}: ${s.slice(i, i + 40)}`);
    const [all, close, name, at, self] = m;
    if (close === "/") {
      assert.equal(stack.pop(), name, `unbalanced </${name}>`);
    } else {
      tags.push(name!);
      const rec: Record<string, string> = {};
      for (const a of at!.matchAll(/([\w:-]+)="([^"]*)"/g)) {
        assert.ok(!(a[1]! in rec), `duplicate attribute ${a[1]}`);
        rec[a[1]!] = a[2]!;
      }
      attrs.push(rec);
      if (self !== "/") stack.push(name!);
    }
    i += all.length;
    if (stack.length === 0) assert.equal(i, s.length, "text after the root");
  }
  assert.equal(stack.length, 0, "unclosed tags");
  return { tags, attrs };
}

test("thumbnails: well-formed SVG, viewBox 0 0 64 64, currentColor, no colour literal, no script", () => {
  const seen = new Set<string>();
  for (const p of PRESETS) {
    const svg = p.thumbnail;
    const { tags, attrs } = parse_xml(svg);
    assert.equal(tags[0], "svg");
    assert.equal(attrs[0]!["viewBox"], "0 0 64 64");
    assert.equal(attrs[0]!["stroke"], "currentColor");
    assert.equal(attrs[0]!["fill"], "none");
    assert.ok(tags.length >= 2);
    for (const t of tags) assert.ok(["svg", "path", "ellipse"].includes(t), `unexpected <${t}>`);
    for (const a of attrs) {
      for (const [k, v] of Object.entries(a)) {
        assert.ok(!/^on/i.test(k), "no event handler");
        if (k === "fill" || k === "stroke") assert.ok(v === "none" || v === "currentColor", `${k}="${v}"`);
        if (k === "fill-opacity") assert.ok(Number(v) <= 0.12);
        if (k === "d") assert.ok(/^[MLZ0-9 .-]+$/.test(v), "path data");
      }
    }
    assert.ok(!/script|#[0-9a-f]{3,6}\b|rgb\(|hsl\(/i.test(svg), "no script and no hard-coded colour");
    // every coordinate inside the 64 px box
    for (const m of svg.matchAll(/[ML](-?[\d.]+) (-?[\d.]+)/g)) {
      assert.ok(Number(m[1]) >= 0 && Number(m[1]) <= 64 && Number(m[2]) >= 0 && Number(m[2]) <= 64, `${p.name}: ${m[0]}`);
    }
    seen.add(svg);
  }
  assert.equal(seen.size, 8, "eight different drawings");
  assert.equal(PRESETS.map((p) => p.thumbnail).join(), THUMBNAILS.join());
});

// ------------------------------------------------------------------------------------------------ against the core

test("every preset appended to each bundled example and each v8 case passes validate_scene and renders", () => {
  let n = 0;
  for (const [name, data] of [...examples(), ...cases()]) {
    const scene = load_scene(data);
    for (const preset of PRESETS) {
      const obj = placed(scene, preset);
      const edited = { ...scene, objects: [...scene.objects, obj] };
      const s = validate_scene(edited);
      assert.deepEqual(s.objects.at(-1), obj, `${name} + ${preset.name}: the validator keeps the record`);
      assert.deepEqual(validate_scene(s), s, "idempotent");
      const out = render(s, undefined, false, null, false);
      assert.ok(out.svg.includes("<svg") && !/NaN|Infinity/.test(out.svg), `${name} + ${preset.name}`);
      n++;
    }
  }
  assert.ok(n >= 8 * 60, `only ${n} renders`);
});

test("prefix_n for n = 1 … 100 passes validate_scene (also in a multi-light scene) and is never reserved", () => {
  const two = load_scene(read_json("examples", "two_lights.json"));
  assert.ok(two.lights.length >= 2);
  for (const preset of PRESETS.filter((p, i, all) => all.findIndex((q) => q.prefix === p.prefix) === i)) {
    let scene: Scene = two;
    for (let n = 1; n <= 100; n++) {
      const id = next_id(preset.prefix, used_ids(scene));
      assert.equal(id, `${preset.prefix}_${n}`);
      assert.ok(!["hidden", "core", "umbra"].includes(id) && !id.includes("."));
      const obj = make_object(preset, id, [(n % 10) * 2 - 10, Math.floor(n / 10) * 2 + 20, 0]);
      scene = { ...scene, objects: [...scene.objects, obj] };
    }
    validate_scene(scene);
  }
});

test("Python parity: each preset appended to examples/basic.json gives the same SVG text and warnings (needs python3 + numpy)", (t) => {
  const probe = spawnSync("python3", ["-c", "import castplane, numpy"], { cwd: ROOT, encoding: "utf-8" });
  if (probe.status !== 0) {
    t.skip("python3 with castplane and numpy is not available");
    return;
  }
  const base = load_scene(read_json("examples", "basic.json"));
  const scenes = PRESETS.flatMap((preset) => [placed(base, preset), make_object(preset, next_id(preset.prefix, used_ids(base)), [0.4, 3.1, 0])])
    .map((obj) => ({ ...base, objects: [...base.objects, obj] }));
  const dir = mkdtempSync(join(tmpdir(), "castplane-lib-"));
  try {
    const file = join(dir, "scenes.json");
    writeFileSync(file, JSON.stringify(scenes));
    const py = [
      "import json, sys",
      "from castplane import load_scene, render",
      "out = []",
      "for s in json.load(open(sys.argv[1], encoding='utf-8')):",
      "    r = render(load_scene(s))",
      "    out.append({'svg': r['svg'], 'warnings': [[w['code'], list(w['ids'])] for w in r['geometry']['warnings']]})",
      "sys.stdout.write(json.dumps(out))",
    ].join("\n");
    const res = spawnSync("python3", ["-c", py, file], { cwd: ROOT, encoding: "utf-8", maxBuffer: 256 * 1024 * 1024 });
    assert.equal(res.status, 0, res.stderr);
    const ref = JSON.parse(res.stdout) as { svg: string; warnings: [string, string[]][] }[];
    assert.equal(ref.length, scenes.length);
    scenes.forEach((s, i) => {
      const out = render(load_scene(s));
      assert.equal(out.svg, ref[i]!.svg, `scene ${i} (${s.objects.at(-1)!.id} at ${s.objects.at(-1)!.transform.position}): SVG text`);
      const w = (out.geometry.warnings as { code: string; ids: string[] }[]).map((x) => [x.code, [...x.ids]]);
      assert.deepEqual(w, ref[i]!.warnings, `scene ${i}: warnings`);
      for (const [code] of w) assert.equal(code, "CONSTRUCTION_CHECK_SKIPPED", "only the benign positional warning");
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

// Pose fixtures of the Miki model from the built web code (milestone 2, tools/miki_model/README.md "Poses").
//
// Applies every pose of tools/miki_model/poses.py::POSES (the table is repeated below; tests/test_miki_poses.py
// checks that both list the same steps) to examples/miki.json through the web UI's own D85 ring-drag path:
// links resolved with web/src/links.ts::resolve_links (the >= 2 groups of web/src/groups.ts), each step's subtree
// from links.ts::subtree, its pivot the object's CURRENT world joint world_centre(T, joint) (as
// PlaneSession.part_pivot at pointer-down), and web/src/object_rotate.ts::rotate_unit(pose, axis, deg, c_locals,
// pivot) over the subtree.  Writes every object's final transform (position, rotation_deg and the matrix of
// castplane's transform_frame) to tests/fixtures/miki_poses.json.  The Euler-entry path (set_part_rotation) is a
// second semantic and is not covered.
//
// Run from the repository root (node >= 20.19), after building the TypeScript port and the web test tree:
//
//   npm ci
//   npm run build -w ts
//   (cd web && npx tsc -p tsconfig.test.json)
//   node tools/miki_model/pose_fixtures.mjs
//
// The script imports the COMPILED modules web/build/src/{links,groups,object_rotate}.js and
// ts/build/src/index.js by file URL (web/src/*.ts cannot be imported by node); the web modules resolve their bare
// `castplane` import through the workspace's node_modules.

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
const load = (p) => import(pathToFileURL(resolve(ROOT, p)).href);
const { object_links, resolve_links, subtree } = await load("web/build/src/links.js");
const { object_groups, group_members, group_of } = await load("web/build/src/groups.js");
const { rotate_unit, world_centre } = await load("web/build/src/object_rotate.js");
const { transform_frame } = await load("ts/build/src/index.js");

// tools/miki_model/poses.py::POSES: [name, steps [object, axis, "+" | "-" | fixed degrees], sweeps]
const POSES = [
  ["head-turn", [["head", "z", "+"]], [10, -10, 20, -20, 30, -30]],
  ["head-nod", [["head", "x", "+"]], [15, -10]],
  ["arms-raised", [["arm_l", "y", "-"], ["arm_r", "y", "+"]], [30, 60, 90]],
  ["arms-forward", [["arm_l", "x", "+"], ["arm_r", "x", "+"]], [-30, -60]],
  ["step", [["legs", "x", "+"]], [15, -15, 25, -25]],
  ["bow", [["blouse", "x", "+"]], [10, 20]],
  ["bow-head-turn", [["blouse", "x", 10], ["head", "z", "+"]], [20]],
];
const AXES = { x: 0, y: 1, z: 2 };
const angle_key = (a) => (a >= 0 ? "+" : "-") + String(Math.abs(a));

const scene_path = resolve(ROOT, "examples", "miki.json");
const raw = JSON.parse(readFileSync(scene_path, "utf-8"));
const ids = raw.objects.map((o) => o.id);
const groups = object_groups(raw);
const members = group_members(groups, ids);
const forest = resolve_links(object_links(raw), ids, (id) => group_of(id, groups, members));
const identity = () => ({ position: [0, 0, 0], rotation_deg: [0, 0, 0] });
const load_t = new Map(raw.objects.map((o) => [o.id, o.transform ?? identity()]));

const cases = {};
for (const [name, steps, sweeps] of POSES) {
  cases[name] = {};
  for (const angle of sweeps) {
    const T = new Map([...load_t].map(([id, t]) => [id, { position: [...t.position], rotation_deg: [...t.rotation_deg] }]));
    const done = [];
    for (const [obj, axis, d] of steps) {
      const deg = d === "+" ? angle : d === "-" ? -angle : d;
      const joint = forest.joints.get(obj);
      if (joint === undefined) throw new Error(`${obj} has no joint`);
      const pivot = world_centre(T.get(obj), joint);        // PlaneSession.part_pivot at the current transform
      const ids_moved = subtree(forest, obj);
      const pose = { transforms: new Map(ids_moved.map((id) => [id, T.get(id)])), group: null };
      const next = rotate_unit(pose, AXES[axis], deg, new Map(), pivot);
      for (const [id, t] of next.transforms) T.set(id, t);
      done.push({ object: obj, axis, degrees: deg, pivot, moved: ids_moved });
    }
    const objects = {};
    for (const id of ids) {
      const t = T.get(id);
      const [R, p] = transform_frame(t);
      objects[id] = { position: p, rotation_deg: t.rotation_deg, matrix: R };
    }
    cases[name][angle_key(angle)] = { steps: done, objects };
  }
}

const out = {
  about: "Miki pose fixtures: every object's final transform after each pose of tools/miki_model/poses.py, from the "
    + "built web code (links.ts resolve_links / subtree, object_rotate.ts rotate_unit about world_centre(T, joint)); "
    + "written by tools/miki_model/pose_fixtures.mjs",
  scene: "examples/miki.json",
  joints: Object.fromEntries(ids.map((id) => [id, forest.joints.get(id) ?? null])),
  parents: Object.fromEntries(ids.map((id) => [id, forest.parent.get(id) ?? null])),
  poses: cases,
};
const target = resolve(ROOT, "tests", "fixtures", "miki_poses.json");
// one line per number list (the rows of a matrix included), so the committed file stays short and diffable
const text = JSON.stringify(out, null, 1).replace(/\[\s*(-?[0-9][^\[\]{}"]*?)\s*\]/g, (_m, body) => `[${body.split(/\s*,\s*/).join(", ")}]`);
writeFileSync(target, text + "\n");
console.log(`wrote ${target}: ${Object.values(cases).reduce((n, c) => n + Object.keys(c).length, 0)} pose cases`);

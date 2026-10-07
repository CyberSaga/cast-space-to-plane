/**
 * The `mesh` object kind through stages A / B / C of the port (contract §5.2.3 step 8, §5.2.4, §5.2.5, §5.2.12,
 * §5.2.13; the port of `tests/test_mesh_pipeline.py` without its Python-only verification layers — the ray-cast and
 * raster references and the loaders): acceptance 1 (the welded split box equals the parametric box but for the two
 * mesh keys) and acceptance 2 (the open-bottom box fallback numbers), smooth edges, the ray cap, determinism, camera
 * independence and meshes on bounded receivers.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import { sphere_mesh } from "../src/mesh.js";
import { dumps } from "../src/output/geometry_json.js";
import { compose, project_scene, render, shadow_geometry } from "../src/pipeline.js";
import { build_object, local_mesh, point_inside_solid, prepared_mesh } from "../src/primitives.js";
import { load_scene } from "../src/scene.js";
import { CUBE_F, CUBE_V, SPLIT_F, SPLIT_V } from "./mesh_fixtures.js";
import { read_json, repo_path } from "./helpers.js";

const OPEN_BOTTOM_F = [[4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];
const clone = <T>(x: T): T => JSON.parse(JSON.stringify(x)) as T;

function analytic_box_scene(): any {
  return read_json(repo_path("tests", "conformance", "cases", "analytic_unit_box_point_light_overhead.json"));
}

/** `analytic_unit_box_point_light_overhead` with the box replaced by an inline mesh `cube`. */
function mesh_box_scene(vertices: number[][] = SPLIT_V, faces: number[][] = SPLIT_F, keys: Record<string, unknown> = {}): any {
  const scene = analytic_box_scene();
  scene.objects = [{ id: "cube", type: "mesh", data: { vertices: clone(vertices), faces: clone(faces) }, ...keys }];
  return scene;
}

const doc_of = (scene: unknown, camera: unknown = null): any => render(load_scene(scene), camera).geometry;

function strip_mesh_keys(doc: any): any {
  for (const e of doc.edges) {
    delete e.smooth;
    delete e.camera_silhouette;
  }
  return doc;
}

const warning_set = (doc: any): string[] => doc.warnings.map((w: any) => `${w.code}:${w.ids.join(",")}`).sort();
const pairs = (edges: any[]): string[] => edges.map((e) => `${e.from}-${e.to}`).sort();
const close = (a: readonly number[], b: readonly number[], tol: number, msg = ""): void => {
  assert.equal(a.length, b.length, msg);
  a.forEach((x, i) => assert.ok(Math.abs(x - (b[i] as number)) <= tol, `${msg} ${a} vs ${b}`));
};

// --- object records --------------------------------------------------------------------------------------------------

test("mesh record keys (contract §5.2.3 step 8)", () => {
  const scene = load_scene(mesh_box_scene());
  const obj = scene.objects[0] as any;
  const rec = build_object(obj);
  assert.equal(rec.type, "mesh");
  assert.equal(rec.analytic, null);
  assert.equal(rec.fallback, false);
  assert.deepEqual(rec.prep_warnings, []);
  assert.deepEqual(rec.smooth_groups, [0, 0, 0, 0, 0, 0]);
  assert.equal(rec.triangles?.length, 12);
  assert.deepEqual(rec.mesh.vertices, CUBE_V);
  assert.deepEqual(rec.mesh.faces, CUBE_F);
  assert.deepEqual(rec.mesh.edge_smooth, new Array(12).fill(false));
  assert.deepEqual(rec.point_names, [...Array(8).keys()].map((k) => `cube.v${k}`));
  assert.ok(rec.edge_templates.every((t) => t.smooth === false));
  assert.deepEqual(local_mesh(obj).faces, CUBE_F);
  assert.equal(prepared_mesh(obj).scale_A, 1.0);
});

test("primitive records gain only the switch-off keys", () => {
  const rec = build_object(load_scene(analytic_box_scene()).objects[0] as any);
  assert.equal(rec.fallback, false);
  assert.deepEqual(rec.prep_warnings, []);
  assert.deepEqual(rec.mesh.edge_smooth, new Array(12).fill(false));
  assert.ok(!("triangles" in rec) && !("smooth_groups" in rec));
  assert.ok(rec.edge_templates.every((t) => !("smooth" in t)));
});

test("mesh scale and transform are applied like the parametric box's", () => {
  const transform = { position: [1.0, 2.0, 0.0], rotation_deg: [0.0, 0.0, 90.0] };
  const rec = build_object(load_scene(mesh_box_scene(CUBE_V, CUBE_F, { scale: 2.0, transform })).objects[0] as any);
  const ref = build_object(load_scene({ ...analytic_box_scene(), objects: [{ id: "cube", type: "box", size: [2, 2, 2], transform }] })
    .objects[0] as any);
  assert.deepEqual(rec.mesh.vertices, ref.mesh.vertices);
  assert.deepEqual(rec.mesh.face_normals, ref.mesh.face_normals);
});

test("point_inside_solid: the mesh branch (winding number; a fallback mesh has no inside)", () => {
  const rec = build_object(load_scene(mesh_box_scene(SPLIT_V, SPLIT_F, { transform: { position: [3.0, 0.0, 0.0] } })).objects[0] as any);
  assert.ok(point_inside_solid(rec, [3.0, 0.0, 0.5], 1e-9));
  assert.ok(!point_inside_solid(rec, [0.0, 0.0, 0.5], 1e-9));
  assert.ok(!point_inside_solid(rec, [3.0, 0.0, 1.0], 1e-9));
  const fb = build_object(load_scene(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F)).objects[0] as any);
  assert.equal(fb.fallback, true);
  assert.deepEqual(fb.prep_warnings.map((w) => w.code), ["MESH_NON_MANIFOLD"]);
  assert.ok(!point_inside_solid(fb, [0.0, 0.0, 0.5], 1e-9));
});

test("validation: the usable-face guard and the expand-first row (contract §5.2.1)", () => {
  const bad = mesh_box_scene(CUBE_V, CUBE_F, { weld_tolerance: 10.0 });
  assert.throws(() => load_scene(bad), (e: any) => e.field === "objects[0].data.faces" && /no usable face/.test(e.message));
  const path_only = analytic_box_scene();
  path_only.objects = [{ id: "cube", type: "mesh", path: "box.obj" }];
  assert.throws(() => load_scene(path_only), (e: any) => e.field === "objects[0].path" && /expanded first/.test(e.message));
});

// --- acceptance 1 (contract §5.2.12) ---------------------------------------------------------------------------------

test("acceptance 1: the welded split box equals the parametric box but for the two mesh keys", () => {
  const ref = doc_of(analytic_box_scene());
  const doc = doc_of(mesh_box_scene());
  assert.equal(doc.edges.length, 12);
  assert.ok(doc.edges.every((e: any) => e.smooth === false));
  // camera silhouette edges are drawn like every feature edge; the key is camera dependent
  assert.deepEqual(pairs(doc.edges.filter((e: any) => e.camera_silhouette)),
    ["cube.v0-cube.v1", "cube.v0-cube.v4", "cube.v1-cube.v2", "cube.v2-cube.v6", "cube.v4-cube.v7", "cube.v6-cube.v7"]);
  // the hand values of contract §5.2.12
  assert.deepEqual(pairs(doc.edges.filter((e: any) => e.silhouette)), ["cube.v4-cube.v5", "cube.v4-cube.v7", "cube.v5-cube.v6", "cube.v6-cube.v7"]);
  const sh = doc.shadows[0];
  assert.deepEqual(sh.outline, [4, 5, 6, 7].map((k) => `cube.v${k}.shadow.lamp`));
  assert.deepEqual(sh.outline.map((n: string) => doc.points[n].world), [[-.75, -.75, 0.0], [.75, -.75, 0.0], [.75, .75, 0.0], [-.75, .75, 0.0]]);
  const con = doc.construction;
  close(con.light_point, [0, 87.93525754212652], 1e-9, "L'");
  close(con.shadow_vp, [0, -15.270708139022979], 1e-9, "F'");
  const images = [[-35.43926206447239, -21.040388381248047], [12.57114643641712, -33.69048944708911],
    [33.42375900867301, -9.829161370289384], [-10.541723693318392, 0.17547618657507147]];
  sh.outline.forEach((n: string, k: number) => close(doc.points[n].image, images[k] as number[], 1e-9, n));
  assert.deepEqual(con.rays, [4, 5, 6, 7].flatMap((v) => [["L", `cube.v${v}`], ["F", `cube.v${v}.foot`]]));
  assert.equal(con.checks.length, 4);
  assert.ok(con.checks.every((c: any) => c.max_error_mm <= 1e-9));
  assert.equal(doc.form_shadow[0].faces.length, 5);
  assert.deepEqual(doc.warnings, []);
  assert.equal(dumps(strip_mesh_keys(doc)), dumps(ref));
});

test("acceptance 1: inside-out and one-flipped split boxes (winding repair, then the merge)", () => {
  const ref = dumps(doc_of(analytic_box_scene()));
  const flip = (f: number[]): number[] => [f[0] as number, ...f.slice(1).reverse()];
  const one = clone(SPLIT_F);
  one[4] = flip(one[4] as number[]);
  for (const F of [SPLIT_F.map(flip), one]) {
    const doc = doc_of(mesh_box_scene(SPLIT_V, F));
    assert.deepEqual(doc.warnings.map((w: any) => w.code), ["MESH_WINDING_FIXED"]);
    assert.equal(doc.edges.length, 12);
    assert.equal(doc.form_shadow[0].faces.length, 5);
    doc.warnings = [];
    assert.equal(dumps(strip_mesh_keys(doc)), ref);
  }
});

/** `φ`: `<obj>.v<k>[.rest]` -> `<obj>|<world of v<k>>|<rest>` (the renaming of contract §5.2.13). */
function mapper(doc: any): (name: unknown) => string {
  const world = new Map<string, string>(Object.entries(doc.points).filter(([, p]: [string, any]) => "world" in p)
    .map(([n, p]: [string, any]) => [n, JSON.stringify(p.world)] as const));
  return (name: unknown): string => {
    if (typeof name !== "string") return JSON.stringify(name);
    const parts = name.split(".");
    if (parts.length >= 2 && /^v\d+$/.test(parts[1] as string)) return `${parts[0]}|${world.get(parts.slice(0, 2).join("."))}|${parts.slice(2).join(".")}`;
    return name;
  };
}

function cyclic_key(seq: readonly string[]): [string, number] {
  let best = -1, key = "";
  for (let k = 0; k < seq.length; k++) {
    const rot = JSON.stringify([...seq.slice(k), ...seq.slice(0, k)]);
    if (best < 0 || rot < key) [best, key] = [k, rot];
  }
  return [key, Math.max(best, 0)];
}

/** The equality criteria of contract §5.2.13 (a)–(h) (`world` exact, image values within `atol`). */
function assert_equal_by_world(a: any, b: any, atol = 1e-9): void {
  const pa = mapper(a), pb = mapper(b);
  const pts = (doc: any, phi: (n: unknown) => string): Map<string, any> => new Map(Object.entries(doc.points).map(([n, p]) => [phi(n), p] as const));
  const va = pts(a, pa), vb = pts(b, pb);
  assert.deepEqual([...va.keys()].sort(), [...vb.keys()].sort());
  for (const [k, p] of va) {
    const q = vb.get(k);
    assert.deepEqual([p.world, p.direction], [q.world, q.direction], k);
    assert.equal(p.image === null, q.image === null, k);
    if (p.image !== null) close(p.image, q.image, atol, k);
    if ("depth" in p) assert.ok(Math.abs(p.depth - q.depth) <= atol, k);
  }
  const edge_map = (doc: any, phi: (n: unknown) => string): Map<string, any> => new Map(doc.edges.map((e: any) => {
    const ends = [phi(e.from), phi(e.to)].sort();
    const seg = e.segment === null ? null : [...e.segment].sort((x: number[], y: number[]) => x[0]! - y[0]! || x[1]! - y[1]!);
    return [JSON.stringify(ends), [e.silhouette, e.back, e.smooth ?? false, seg]] as const;
  }));
  const ea = edge_map(a, pa), eb = edge_map(b, pb);
  assert.deepEqual([...ea.keys()].sort(), [...eb.keys()].sort());
  for (const [k, [s, bk, sm, seg]] of ea) {
    const [s2, bk2, sm2, seg2] = eb.get(k);
    assert.deepEqual([s, bk, sm], [s2, bk2, sm2], k);
    assert.equal(seg === null, seg2 === null, k);
    if (seg !== null) close(seg.flat(), seg2.flat(), atol, k);
  }
  const cyc_map = (names: string[][], polys: number[][][], phi: (n: unknown) => string): Map<string, number[][]> => {
    const out = new Map<string, number[][]>();
    names.forEach((loop, i) => {
      const [key, rot] = cyclic_key(loop.map(phi));
      const poly = polys[i] as number[][];
      out.set(key, poly.length === loop.length ? [...poly.slice(rot), ...poly.slice(0, rot)] : poly);
    });
    return out;
  };
  const cmp_maps = (x: Map<string, number[][]>, y: Map<string, number[][]>): void => {
    assert.deepEqual([...x.keys()].sort(), [...y.keys()].sort());
    for (const [k, poly] of x) close(poly.flat(), (y.get(k) as number[][]).flat(), atol, k);
  };
  const faces = (doc: any, phi: (n: unknown) => string): Map<string, number[][]> => {
    const out = new Map<string, number[][]>();
    for (const f of doc.form_shadow) for (const [k, v] of cyc_map(f.faces, f.polygons, phi)) out.set(k, v);
    return out;
  };
  cmp_maps(faces(a, pa), faces(b, pb));
  assert.equal(a.shadows.length, b.shadows.length);
  a.shadows.forEach((s1: any, i: number) => {
    const s2 = b.shadows[i];
    assert.equal(s1.unbounded, s2.unbounded);
    cmp_maps(cyc_map(s1.loops, s1.polygons, pa), cyc_map(s2.loops, s2.polygons, pb));
  });
  const ca = a.construction, cb = b.construction;
  const ray_set = (rays: string[][], phi: (n: unknown) => string): string[] => rays.map(([k, n]) => `${k}:${phi(n)}`).sort();
  assert.deepEqual(ray_set(ca.rays, pa), ray_set(cb.rays, pb));
  assert.deepEqual(ca.checks.map((c: any) => pa(c.point)).sort(), cb.checks.map((c: any) => pb(c.point)).sort());
  assert.ok([...ca.checks, ...cb.checks].every((c: any) => c.max_error_mm <= 1e-9));
  const seg_map = (segs: any[], phi: (n: unknown) => string): Map<string, number[][]> => new Map(segs.map((s) => [`${s.kind}:${phi(s.point)}`, s.points] as const));
  cmp_maps(seg_map(ca.segments, pa), seg_map(cb.segments, pb));
  assert.deepEqual(warning_set(a), warning_set(b));
  assert.deepEqual([a.horizon, a.camera], [b.horizon, b.camera]);
}

test("acceptance 1: a shuffled vertex and face order equals the parametric box by the §5.2.13 criteria", () => {
  // a fixed permutation (the Python test draws one from a seeded generator; any permutation must pass)
  const perm = [17, 3, 22, 9, 0, 14, 6, 20, 11, 1, 19, 8, 23, 4, 15, 12, 2, 21, 7, 16, 10, 5, 18, 13];
  const inv = new Array<number>(24);
  perm.forEach((old, pos) => {
    inv[old] = pos;
  });
  const V = perm.map((k) => SPLIT_V[k] as number[]);
  let F = SPLIT_F.map((f) => f.map((v) => inv[v] as number));
  F = [5, 2, 11, 0, 7, 9, 3, 1, 10, 6, 4, 8].map((k) => F[k] as number[]);
  F = F.map((f, k) => {
    const r = k % 3;
    return [...f.slice(r), ...f.slice(0, r)];
  });
  const shuffled = doc_of(mesh_box_scene(V, F));
  const ref = doc_of(analytic_box_scene());
  assert.deepEqual(shuffled.warnings, []);
  const names = [...Array(8).keys()].map((k) => `cube.v${k}`);
  assert.notDeepEqual(names.map((n) => shuffled.points[n].world), names.map((n) => ref.points[n].world));
  assert_equal_by_world(ref, shuffled);
  assert_equal_by_world(doc_of(mesh_box_scene()), shuffled);
});

// --- acceptance 2 (contract §5.2.12): the open-bottom box fallback ---------------------------------------------------

const shoelace = (pts: number[][]): number => {
  let s = 0;
  pts.forEach((p, k) => {
    const q = pts[(k + 1) % pts.length] as number[];
    s += (p[0] as number) * (q[1] as number) - (q[0] as number) * (p[1] as number);
  });
  return 0.5 * s;
};

test("acceptance 2: the open-bottom box fallback (5 loops, union = the ±0.75 square, no rays)", () => {
  const doc = doc_of(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F));
  assert.deepEqual(warning_set(doc), ["MESH_NON_MANIFOLD:cube"]);
  const sh = doc.shadows[0];
  assert.equal(sh.loops.length, 5);
  assert.equal(sh.unbounded, false);
  assert.deepEqual(sh.outline, sh.loops[0]);
  const pts = doc.points;
  const loops_xy: number[][][] = sh.loops.map((loop: string[]) => loop.map((n) => pts[n].world.slice(0, 2)));
  assert.deepEqual(sh.loops[0], [4, 5, 6, 7].map((k) => `cube.v${k}.shadow.lamp`));
  assert.deepEqual(loops_xy[0], [[-.75, -.75], [.75, -.75], [.75, .75], [-.75, .75]]);
  assert.deepEqual(sh.loops[1], [0, 4, 5, 1].map((k) => `cube.v${k}.shadow.lamp`)); // front, unlit: reversed
  assert.deepEqual(loops_xy[1], [[-.5, -.5], [-.75, -.75], [.75, -.75], [.5, -.5]]);
  assert.ok(Math.abs(shoelace(loops_xy[0] as number[][]) - 2.25) <= 1e-12);
  assert.deepEqual(loops_xy[2], [[.5, -.5], [.75, -.75], [.75, .75], [.5, .5]]);
  for (const xy of loops_xy.slice(1)) {
    assert.ok(Math.abs(shoelace(xy) - 0.3125) <= 1e-12); // CCW, shoelace sum +0.625
    assert.ok(xy.every(([x, y]) => Math.abs(x as number) <= 0.75 && Math.abs(y as number) <= 0.75)); // inside the top's square
  }
  assert.equal(doc.edges.length, 12);
  assert.ok(doc.edges.every((e: any) => e.smooth === false && e.segment !== null));
  assert.deepEqual(pairs(doc.edges.filter((e: any) => e.silhouette)), ["cube.v4-cube.v5", "cube.v4-cube.v7", "cube.v5-cube.v6", "cube.v6-cube.v7"]);
  assert.deepEqual(doc.form_shadow[0].faces, OPEN_BOTTOM_F.slice(1).map((f) => f.map((k) => `cube.v${k}`)));
  for (let k = 0; k < 8; k++) assert.ok(`cube.v${k}.shadow.lamp` in pts && `cube.v${k}.foot` in pts);
  for (let k = 0; k < 4; k++) assert.deepEqual(pts[`cube.v${k}.foot`].world, pts[`cube.v${k}`].world);
  assert.deepEqual([doc.construction.rays, doc.construction.checks, doc.construction.segments], [[], [], []]);
  // one <path> per shadow entry, nonzero fill: the drawn region is the union of the five loops
  const svg = render(load_scene(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F))).svg;
  const cast = svg.slice(svg.indexOf('<g id="cast_shadow"'), svg.indexOf('<g id="construction"'));
  assert.equal((cast.match(/<path /g) ?? []).length, 1);
  assert.equal((cast.match(/ Z/g) ?? []).length, 5);
});

test("fallback VERTEX_NOT_BELOW_LIGHT only for vertices that reach a loop", () => {
  let scene = mesh_box_scene([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], [[0, 1, 2, 3]]);
  scene.lights[0].position = [0.5, 0.0, 0.5]; // in the plane of the quad, below its top
  let doc = doc_of(scene);
  assert.deepEqual(doc.warnings.map((w: any) => w.code), ["FACE_PARALLEL_TO_LIGHT", "MESH_NON_MANIFOLD"]);
  assert.deepEqual(doc.shadows[0].loops, []);
  scene = mesh_box_scene(CUBE_V, OPEN_BOTTOM_F);
  scene.lights[0].position = [0.0, 0.0, 0.5]; // inside the open box, below the top face
  doc = doc_of(scene);
  assert.ok(warning_set(doc).includes("VERTEX_NOT_BELOW_LIGHT:cube"));
});

test("a buried open box: one crossing point per crossed edge, shared by two faces", () => {
  const doc = doc_of(mesh_box_scene(CUBE_V, OPEN_BOTTOM_F, { transform: { position: [0.0, 0.0, -0.5] } }));
  assert.deepEqual(warning_set(doc), ["MESH_NON_MANIFOLD:cube", "OBJECT_BELOW_RECEIVER:cube"]);
  const is_ground = (n: string): boolean => /^cube\.s\d+\.lamp$/.test(n);
  const ground = Object.keys(doc.points).filter(is_ground).sort();
  assert.deepEqual(ground, [0, 1, 2, 3].map((k) => `cube.s${k}.lamp`));
  assert.deepEqual(ground.map((n) => doc.points[n].world).sort(), [[-.5, -.5, 0.0], [-.5, .5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0]]);
  const sh = doc.shadows[0];
  assert.equal(sh.loops.length, 5);
  for (const loop of sh.loops.slice(1)) assert.equal(loop.filter(is_ground).length, 2);
  for (let k = 0; k < 4; k++) assert.ok(!(`cube.v${k}.shadow.lamp` in doc.points));
  assert.deepEqual(doc.construction.rays, []);
});

// --- smooth edges and the ray cap (contract §5.2.4) ------------------------------------------------------------------

function prism_data(n: number, r = 0.5, h = 1.0): [number[][], number[][]] {
  const ring = [...Array(n).keys()].map((k) => [r * Math.cos(2 * Math.PI * k / n), r * Math.sin(2 * Math.PI * k / n)] as [number, number]);
  const V = [...ring.map(([x, y]) => [x, y, 0.0]), ...ring.map(([x, y]) => [x, y, h])];
  const F = [[...Array(n).keys()].reverse(), [...Array(n).keys()].map((k) => n + k)];
  for (let k = 0; k < n; k++) F.push([k, (k + 1) % n, n + (k + 1) % n, n + k]);
  return [V, F];
}

test("a smooth 16-gon prism draws two lateral edges (the camera silhouettes)", () => {
  const [V, F] = prism_data(16);
  const doc = doc_of(mesh_box_scene(V, F));
  const idx = (n: string): number => Number(n.split(".v")[1]);
  const lateral = doc.edges.filter((e: any) => Math.abs(idx(e.from) - idx(e.to)) === 16);
  const caps = doc.edges.filter((e: any) => !lateral.includes(e));
  assert.equal(lateral.length, 16);
  assert.equal(caps.length, 32);
  assert.ok(lateral.every((e: any) => e.smooth) && caps.every((e: any) => !e.smooth));
  const drawn = lateral.filter((e: any) => e.segment !== null);
  assert.equal(drawn.length, 2);
  assert.ok(drawn.every((e: any) => e.camera_silhouette));
  assert.ok(lateral.filter((e: any) => !e.camera_silhouette).every((e: any) => e.segment === null && e.visibility === "visible"));
  assert.ok(caps.every((e: any) => e.segment !== null));
  const svg = render(load_scene(mesh_box_scene(V, F))).svg;
  const body = svg.slice(svg.indexOf('<g id="objects.cube">'), svg.indexOf('<g id="form_shadow"'));
  assert.equal((body.match(/<line/g) ?? []).length, 34); // 32 cap edges + 2 lateral silhouettes
});

test("the ray cap: 64 feature silhouette vertices in loop order, MESH_RAYS_CAPPED, emission ascending", () => {
  const [V, F] = prism_data(100);
  for (const smooth of [0.0, 30.0]) {
    const doc = doc_of(mesh_box_scene(V, F, { smooth_angle_deg: smooth }));
    assert.ok(warning_set(doc).includes("MESH_RAYS_CAPPED:cube"));
    const sh = doc.shadows[0];
    assert.equal(sh.loops.length, 1);
    assert.equal(sh.outline.length, 100);
    const loop_vertices: string[] = sh.outline.map((n: string) => n.slice(0, -".shadow.lamp".length));
    const selected = new Set(loop_vertices.slice(0, 64));
    const L = doc.construction.rays.filter(([k]: string[]) => k === "L").map(([, n]: string[]) => n);
    assert.deepEqual(new Set(L), selected);
    const order = L.map((n: string) => Number(n.split(".v")[1]));
    assert.deepEqual(order, [...order].sort((a, b) => a - b));
    assert.equal(order.length, 64);
    assert.equal(doc.construction.checks.length, 64);
    assert.ok(loop_vertices.every((n) => `${n}.shadow.lamp` in doc.points));
  }
  const [V2, F2] = prism_data(32);
  const doc = doc_of(mesh_box_scene(V2, F2));
  assert.ok(!doc.warnings.some((w: any) => w.code === "MESH_RAYS_CAPPED"));
  assert.equal(doc.construction.rays.filter(([k]: string[]) => k === "L").length, 32);
});

test("rays only for vertices of feature silhouette edges (a smooth UV sphere mesh)", () => {
  const sm = sphere_mesh(0.5);
  const doc = doc_of(mesh_box_scene(sm.vertices.map((v) => [...v]), sm.faces));
  assert.ok(doc.edges.every((e: any) => e.smooth));
  const sil = new Set<string>(doc.edges.filter((e: any) => e.silhouette).flatMap((e: any) => [e.from, e.to]));
  assert.ok(sil.size > 20);
  assert.deepEqual([doc.construction.rays, doc.construction.checks], [[], []]);
  for (const n of sil) assert.ok(`${n}.shadow.lamp` in doc.points && `${n}.foot` in doc.points);
  const doc0 = doc_of(mesh_box_scene(sm.vertices.map((v) => [...v]), sm.faces, { smooth_angle_deg: 0.0 }));
  assert.deepEqual(new Set(doc0.construction.rays.filter(([k]: string[]) => k === "L").map(([, n]: string[]) => n)), sil);
  const drawn = doc.edges.filter((e: any) => e.segment !== null);
  assert.ok(drawn.length > 0 && drawn.every((e: any) => e.camera_silhouette));
});

// --- determinism and camera independence -----------------------------------------------------------------------------

const SCENES = (): any[] => [mesh_box_scene(), mesh_box_scene(CUBE_V, OPEN_BOTTOM_F), mesh_box_scene(...prism_data(16))];

test("render twice is bit-identical (mesh scenes)", () => {
  for (const scene of SCENES()) {
    const a = render(load_scene(scene)), b = render(load_scene(clone(scene)));
    assert.equal(dumps(a.geometry), dumps(b.geometry));
    assert.equal(a.svg, b.svg);
  }
});

test("stage A is camera independent with meshes", () => {
  const cam2 = { position: [-6.0, -4.0, 7.0], target: [0.0, 3.0, 0.0], roll_deg: 15.0, focal_length_mm: 20.0, frame_mm: [36, 24],
    shift_mm: [1.0, -2.0], near_m: 0.1 };
  const pick = (d: any): string => JSON.stringify([
    d.edges.map((e: any) => [e.from, e.to, e.silhouette, e.smooth]),
    Object.entries(d.points).map(([n, p]: [string, any]) => [n, p.world ?? null]),
    d.shadows.map((x: any) => x.loops), d.form_shadow.map((f: any) => f.faces), d.construction.rays,
  ]);
  for (const raw of SCENES()) {
    const s = load_scene(raw);
    const A1 = shadow_geometry(s);
    const A2 = shadow_geometry({ ...s, camera: null as any });
    assert.equal(dumps(A1.shadows.map((r) => [r.loops.map((l) => l.entries), r.S_lists, r.Q_lists, r.G_lists, r.ray_vertices ?? null])),
      dumps(A2.shadows.map((r) => [r.loops.map((l) => l.entries), r.S_lists, r.Q_lists, r.G_lists, r.ray_vertices ?? null])));
    assert.equal(pick(compose(s, project_scene(s, A1))), pick(compose(s, project_scene(s, A1, cam2))));
  }
});

// --- hidden lines: the generic closed-mesh occluder of a mesh record is its triangles (§5.2.7, §5.1.6.2) ---------------

test("hidden lines with a mesh crate equal the parametric crate (the welded fans occlude like the box)", () => {
  const box = analytic_box_scene();
  box.objects.push({ id: "post", type: "box", size: [0.2, 0.2, 2.0], transform: { position: [1.5, 1.5, 0.0] } });
  const mesh = mesh_box_scene();
  mesh.objects.push(clone(box.objects[1]));
  for (const scene of [box, mesh]) scene.output = { ...scene.output, hidden_lines: true };
  const ref = doc_of(box), doc = doc_of(mesh);
  assert.equal(doc.hidden_lines, true);
  assert.ok(ref.edges.some((e: any) => e.visibility !== "visible"));
  assert.deepEqual(doc.edges.map((e: any) => [e.from, e.to, e.visibility]), ref.edges.map((e: any) => [e.from, e.to, e.visibility]));
});

// --- meshes on bounded receivers (the M4 / M5 merge note) ------------------------------------------------------------

function wall_mesh_scene(faces: number[][], vertices: number[][] = CUBE_V, floor = false): any {
  const scene: any = {
    version: "0.1", units: "m", up: "z",
    objects: [{ id: "crate", type: "mesh", data: { vertices: clone(vertices), faces: clone(faces) }, transform: { position: [0, 4.5, 0] } }],
    lights: [{ id: "lamp", type: "point", position: [0, 2, 3] }],
    receivers: [{ id: "ground", type: "plane", normal: [0, 0, 1], offset: 0 },
      { id: "wall", type: "plane", normal: [0, -1, 0], offset: 6, bounds: [[-3, 6, 0], [3, 6, 0], [3, 6, 2.5], [-3, 6, 2.5]] }],
    camera: { position: [0, -1, 1.6], target: [0, 6, 0.8], focal_length_mm: 35, frame_mm: [36, 24] },
    output: { canvas_mm: [273, 182] },
  };
  if (floor) {
    scene.receivers = [{ id: "floor", type: "plane", normal: [0, 0, 1], offset: 0, bounds: [[-2, 2, 0], [2, 2, 0], [2, 5.5, 0], [-2, 5.5, 0]] },
      scene.receivers[1]];
  }
  return scene;
}

for (const floor of [false, true]) {
  const label = floor ? "floor+wall" : "ground+wall";
  test(`a fallback mesh on bounded receivers (${label}): never cut, per-face loops inside each plate, no rays`, () => {
    const scene = load_scene(wall_mesh_scene(OPEN_BOTTOM_F, CUBE_V, floor));
    const A = shadow_geometry(scene);
    const obj = A.objects[0] as any;
    assert.equal(obj.fallback, true);
    assert.equal(obj.ground_mesh, null);
    assert.ok(obj.clipped.size > 0 && [...obj.clipped.values()].every((c: unknown) => c === null));
    const doc = render(scene).geometry as any;
    assert.deepEqual(warning_set(doc), ["MESH_NON_MANIFOLD:crate"]);
    for (const rid of floor ? ["floor", "wall"] : ["wall"]) {
      const sh = doc.shadows.find((s: any) => s.receiver === rid && s.object === "crate");
      assert.ok(sh.loops.length > 0 && sh.unbounded === false);
      assert.deepEqual(sh.outline, sh.loops[0]);
      const sfx = rid === scene.receivers[0]!.id ? "" : `.${rid}`;
      const rcv = scene.receivers.find((r) => r.id === rid)!;
      const B = rcv.bounds as number[][];
      for (const loop of sh.loops) {
        assert.ok(loop.length >= 3);
        for (const name of loop) {
          assert.ok(name.startsWith("crate.") && name.endsWith(`.lamp${sfx}`), name);
          const X = doc.points[name].world as number[];
          const n = rcv.normal as number[];
          assert.ok(Math.abs(n[0]! * X[0]! + n[1]! * X[1]! + n[2]! * X[2]! + rcv.offset) <= 1e-9, name);
          for (let k = 0; k < 3; k++) {
            assert.ok(X[k]! >= Math.min(...B.map((b) => b[k]!)) - 1e-9 && X[k]! <= Math.max(...B.map((b) => b[k]!)) + 1e-9, name);
          }
        }
      }
    }
    const con = doc.construction;
    const rays = [...con.rays, ...Object.values(con.per_receiver).flatMap((pr: any) => pr.rays)];
    const checks = [...con.checks, ...Object.values(con.per_receiver).flatMap((pr: any) => pr.checks)];
    assert.ok(!JSON.stringify([rays, checks]).includes("crate"));
    assert.equal(dumps(render(scene).geometry), dumps(doc));
  });

  test(`a manifold mesh crate on bounded receivers (${label}) equals the parametric crate`, () => {
    const mesh_scene = wall_mesh_scene(SPLIT_F, SPLIT_V, floor);
    const ref_scene = clone(mesh_scene);
    ref_scene.objects = [{ id: "crate", type: "box", size: [1, 1, 1], transform: { position: [0, 4.5, 0] } }];
    const ref = doc_of(ref_scene), doc = doc_of(mesh_scene);
    assert.ok(ref.construction.per_receiver.wall.rays.length > 0);
    assert.equal(dumps(strip_mesh_keys(doc)), dumps(ref));
  });
}

test("a buried manifold mesh selects the parametric box's rays on the clipped loop mesh", () => {
  const box = analytic_box_scene();
  box.objects[0].transform = { position: [0.0, 0.0, -0.5] };
  const ref = doc_of(box);
  const doc = doc_of(mesh_box_scene(SPLIT_V, SPLIT_F, { transform: { position: [0.0, 0.0, -0.5] } }));
  assert.ok(warning_set(doc).includes("OBJECT_BELOW_RECEIVER:cube"));
  assert.ok(doc.construction.rays.length > 0);
  assert.deepEqual(doc.construction.rays, ref.construction.rays);
  assert.equal(dumps(strip_mesh_keys(doc)), dumps(ref));
});

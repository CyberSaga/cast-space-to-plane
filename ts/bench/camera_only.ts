/**
 * The spec §8 benchmark on the TypeScript side (contract §5.4.9; mirrors `benchmarks/bench.py`).
 *
 *   node ts/build/bench/camera_only.js [--reps N] [--gate both|full|camera|none] [--json] [--scene path]
 *
 * Scene: `benchmarks/scenes/benchmark_100.json` (the committed file `benchmarks/bench.py` also reads by default).
 * Protocol: `load_scene`; `other_camera = camera_override(scene.camera, [6, -28, 12], [0, 0, 0.5], 3)` (§5.4.7);
 * 3 warm-up full renders (JIT); then `reps` (default 20) timings with `performance.now()` of the full render
 * (`shadow_geometry + project_scene + compose + write_svg(scene.output.layers) + dumps`), the camera-only path
 * (`project_scene(scene, A, other_camera) + compose + write_svg`), stage A alone, `write_svg` alone and `dumps`
 * alone; min and median are reported. Targets: full render < 1 s, camera-only < 100 ms (minimum over reps).
 * `--gate` picks which targets decide the exit status (default `both`; `camera` gates the camera-only target
 * alone; `none` always exits 0). `--json` prints the record of `bench.py --json` (same field names) plus
 * `engine: {node, v8}`.
 */

import { readFileSync } from "node:fs";
import { performance } from "node:perf_hooks";

import { load_scene } from "../src/scene.js";
import { compose, project_scene, shadow_geometry } from "../src/pipeline.js";
import type { StageA } from "../src/pipeline.js";
import type { Scene } from "../src/scene.js";
import { dumps } from "../src/output/geometry_json.js";
import { write_svg } from "../src/output/svg.js";
import { camera_override, repo_path } from "../test/helpers.js";

export const TARGET_FULL_S = 1.0;
export const TARGET_CAMERA_S = 0.1;
export const GATES = ["both", "full", "camera", "none"] as const;
export type Gate = (typeof GATES)[number];
export const WARMUP = 3;
export const DEFAULT_REPS = 20;

/** Exit status for a gate (contract §5.4.9): `both` needs both targets, `full` / `camera` one, `none` never fails. */
export function exit_status(ok_full: boolean, ok_cam: boolean, gate: Gate): number {
  switch (gate) {
    case "both":
      return ok_full && ok_cam ? 0 : 1;
    case "full":
      return ok_full ? 0 : 1;
    case "camera":
      return ok_cam ? 0 : 1;
    case "none":
      return 0;
  }
}

function median(xs: readonly number[]): number {
  const s = [...xs].sort((a, b) => a - b);
  const n = s.length;
  return n % 2 === 1 ? s[(n - 1) / 2]! : (s[n / 2 - 1]! + s[n / 2]!) / 2;
}

function timeit(fn: () => unknown, reps: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < reps; i++) {
    const t0 = performance.now();
    fn();
    out.push((performance.now() - t0) / 1000);
  }
  return out;
}

function full_render(scene: Scene): { doc: ReturnType<typeof compose>; svg: string; text: string } {
  const A = shadow_geometry(scene);
  const B = project_scene(scene, A);
  const doc = compose(scene, B);
  const svg = write_svg(doc, scene.output.layers);
  const text = dumps(doc);
  return { doc, svg, text };
}

function camera_render(scene: Scene, A: StageA, camera: unknown): string {
  const B = project_scene(scene, A, camera);
  const doc = compose(scene, B);
  return write_svg(doc, scene.output.layers);
}

interface Args {
  reps: number;
  gate: Gate;
  json: boolean;
  scene: string;
}

function usage(msg: string): never {
  process.stderr.write(`camera_only: ${msg}\nusage: node ts/build/bench/camera_only.js [--reps N] [--gate ${GATES.join("|")}] [--json] [--scene path]\n`);
  process.exit(2);
}

function parse_args(argv: readonly string[]): Args {
  const args: Args = { reps: DEFAULT_REPS, gate: "both", json: false, scene: repo_path("benchmarks", "scenes", "benchmark_100.json") };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    const value = (): string => {
      const v = argv[++i];
      if (v === undefined) usage(`${a} needs a value`);
      return v;
    };
    if (a === "--reps" || a === "-n") {
      const n = Number(value());
      if (!Number.isInteger(n) || n < 1) usage("--reps must be a positive integer");
      args.reps = n;
    } else if (a === "--gate") {
      const g = value();
      if (!(GATES as readonly string[]).includes(g)) usage(`unknown gate ${JSON.stringify(g)}`);
      args.gate = g as Gate;
    } else if (a === "--json") {
      args.json = true;
    } else if (a === "--scene") {
      args.scene = value();
    } else if (a === "-h" || a === "--help") {
      process.stdout.write(`usage: node ts/build/bench/camera_only.js [--reps N] [--gate ${GATES.join("|")}] [--json] [--scene path]\n`);
      process.exit(0);
    } else {
      usage(`unknown argument ${JSON.stringify(a)}`);
    }
  }
  return args;
}

function main(): number {
  const args = parse_args(process.argv.slice(2));
  const scene = load_scene(JSON.parse(readFileSync(args.scene, "utf-8")));
  const other_camera = camera_override(scene.camera, [6.0, -28.0, 12.0], [0.0, 0.0, 0.5], 3.0);

  // warm-up (JIT) and the cached stage A of the camera-only path
  let first = full_render(scene);
  for (let i = 1; i < WARMUP; i++) first = full_render(scene);
  const { doc, svg, text } = first;
  const A = shadow_geometry(scene);
  const mesh_edges = A.objects.reduce((n, o) => n + o.mesh.edges.length, 0);

  const t_full = timeit(() => full_render(scene), args.reps);
  const t_cam = timeit(() => camera_render(scene, A, other_camera), args.reps);
  const t_stage_a = timeit(() => shadow_geometry(scene), args.reps);
  const t_svg = timeit(() => write_svg(doc, scene.output.layers), args.reps);
  const t_json = timeit(() => dumps(doc), args.reps);

  const stat = (t: number[]) => ({ min: Math.min(...t), median: median(t) });
  const ok_full = Math.min(...t_full) < TARGET_FULL_S;
  const ok_cam = Math.min(...t_cam) < TARGET_CAMERA_S;
  const result = {
    objects: scene.objects.length,
    mesh_edges,
    document_edges: doc.edges.length,
    points: Object.keys(doc.points).length,
    svg_bytes: svg.length,
    json_bytes: text.length,
    warnings: [...new Set(doc.warnings.map((w: { code: string }) => w.code))].sort(),
    reps: args.reps,
    full_render_s: { ...stat(t_full), target: TARGET_FULL_S },
    camera_only_s: { ...stat(t_cam), target: TARGET_CAMERA_S },
    stage_a_s: stat(t_stage_a),
    svg_s: stat(t_svg),
    json_s: stat(t_json),
    pass: { full_render: ok_full, camera_only: ok_cam },
    gate: args.gate,
    engine: { node: process.versions.node, v8: process.versions.v8 },
  };
  const status = exit_status(ok_full, ok_cam, args.gate);

  if (args.json) {
    process.stdout.write(JSON.stringify(result, null, 1) + "\n");
    return status;
  }
  const ms = (x: number) => (x * 1e3).toFixed(1).padStart(8);
  const lines = [
    `benchmark scene: ${args.scene}`,
    `  ${result.objects} primitives, ${mesh_edges} mesh edges (${result.document_edges} drawn edges, ${result.points} named points), ` +
      `SVG ${Math.round(svg.length / 1024)} kB, JSON ${Math.round(text.length / 1024)} kB, warnings [${result.warnings.join(", ")}]`,
    `engine: node ${result.engine.node}, v8 ${result.engine.v8}; warm-up ${WARMUP} full renders; repetitions: ${args.reps}`,
  ];
  const row = (name: string, t: number[], target?: number) => {
    let line = `  ${name.padEnd(34)} min ${ms(Math.min(...t))} ms   median ${ms(median(t))} ms`;
    if (target !== undefined) {
      line += `   target < ${String(target * 1e3).padStart(6)} ms   ${Math.min(...t) < target ? "PASS" : "FAIL"}`;
    }
    lines.push(line);
  };
  row("full render (A+B+C+SVG+JSON)", t_full, TARGET_FULL_S);
  row("camera-only re-render (B+C+SVG)", t_cam, TARGET_CAMERA_S);
  row("  stage A only", t_stage_a);
  row("  SVG writer only", t_svg);
  row("  JSON dumps only", t_json);
  lines.push(`RESULT: ${status === 0 ? "PASS" : "FAIL"} (gate: ${args.gate})`);
  process.stdout.write(lines.join("\n") + "\n");
  return status;
}

process.exitCode = main();

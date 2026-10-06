/** Node-only test helpers (contract §5.4.1): repository paths, JSON reading, the geometry file writer and the
 * explicit camera override of §5.4.7. */

import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { dumps } from "../src/output/geometry_json.js";

/** The repository root: this file is emitted to `ts/build/test/helpers.js`. */
export function repo_root(): string {
  return resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
}

export function repo_path(...parts: string[]): string {
  return join(repo_root(), ...parts);
}

export function read_text(path: string): string {
  return readFileSync(path, "utf-8");
}

export function read_json(path: string): any {
  return JSON.parse(readFileSync(path, "utf-8"));
}

/** Sorted `*.json` stems of a directory. */
export function json_stems(dir: string): string[] {
  return readdirSync(dir).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5)).sort();
}

/** `dumps(doc) + "\n"` written as UTF-8 (the Python `write_geometry_json`). */
export function write_geometry_json(doc: unknown, path: string): void {
  writeFileSync(path, dumps(doc) + "\n", "utf-8");
}

export interface CameraBase {
  focal_length_mm: number;
  frame_mm: number[];
  shift_mm: number[];
  near_m: number;
}

/** A camera override built explicitly from the lens fields (contract §5.4.7): never `{...base, position, target}`,
 * which would carry `yaw_deg` + `target` for a yaw/pitch scene and be rejected by `validate_camera`. */
export function camera_override(base: CameraBase, position: number[], target: number[], roll_deg: number) {
  return {
    position: [...position],
    target: [...target],
    roll_deg,
    focal_length_mm: base.focal_length_mm,
    frame_mm: [...base.frame_mm],
    shift_mm: [...base.shift_mm],
    near_m: base.near_m,
  };
}

/** Recursively freeze plain data (arrays / objects / Maps are left structurally intact). */
export function deep_freeze<T>(obj: T, seen = new Set<unknown>()): T {
  if (obj === null || typeof obj !== "object" || seen.has(obj)) return obj;
  seen.add(obj);
  if (obj instanceof Map) {
    for (const [k, v] of obj) {
      deep_freeze(k, seen);
      deep_freeze(v, seen);
    }
  } else if (obj instanceof Set) {
    for (const v of obj) deep_freeze(v, seen);
  } else {
    for (const v of Object.values(obj as object)) deep_freeze(v, seen);
  }
  return Object.freeze(obj);
}

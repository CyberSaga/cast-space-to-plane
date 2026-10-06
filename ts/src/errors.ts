/**
 * Input errors and structured warnings (port of `castplane/errors.py`; spec §5.8, §8; contract §2.8, §2.9).
 *
 * `SceneError` is thrown for malformed input and carries the JSON field path (contract §2.0). Geometric
 * degeneracies never throw: they are reported as warning records `{code, ids, message}` built with
 * `make_warning` from the closed code table of contract §2.9 / §5.0.5.
 */

import { cmp_code_points } from "./pyfloat.js";

export class SceneError extends Error {
  /** JSON path of the offending field (e.g. `objects[1].size`). */
  readonly field: string;
  /** The bare message (Python `SceneError.message`). */
  readonly detail: string;

  constructor(field: string, detail: string) {
    super(`${field}: ${detail}`);
    this.name = "SceneError";
    this.field = field;
    this.detail = detail;
  }
}

/** Closed list of warning codes (contract §2.9, phase 1: 13 codes) -> default message. */
export const WARNING_CODES: Readonly<Record<string, string>> = Object.freeze({
  CAMERA_LOOKING_ALONG_UP: "camera forward is parallel to world up; using (0,1,0) as up",
  LIGHT_BEHIND_CAMERA: "finite light is behind the camera; L' is the anti-light point",
  LIGHT_POINT_AT_INFINITY: "light point L' is at infinity; construction rays are parallel",
  SHADOW_VP_AT_INFINITY: "shadow vanishing point F' is at infinity",
  DIRECTIONAL_HORIZONTAL: "directional light is parallel to the receiver; no shadows",
  LIGHT_BELOW_RECEIVER: "light is on the back side of the receiver; no shadows",
  VERTEX_NOT_BELOW_LIGHT: "a silhouette vertex is not below the light; shadow outline is unbounded",
  OBJECT_BELOW_RECEIVER: "object has vertices below the receiver; silhouette clipped to the ground",
  POINT_BEHIND_CAMERA: "some drawn point is behind the near plane; image is null or clipped",
  FACE_PARALLEL_TO_LIGHT: "a face is parallel to the light direction; treated as unlit",
  LIGHT_INSIDE_OBJECT: "point light is inside the sphere; no shadow or terminator",
  CONIC_SAMPLED: "conic is degenerate or ill-conditioned; emitted as a sampled polyline",
  CONSTRUCTION_CHECK_SKIPPED: "construction self-check skipped for a degenerate point",
});

export interface Warning {
  code: string;
  ids: string[];
  message: string;
}

/** Build a warning record (contract §2.8 / §2.9); `code` must belong to `WARNING_CODES`. */
export function make_warning(code: string, ids: readonly string[] = [], message?: string | null): Warning {
  if (!Object.prototype.hasOwnProperty.call(WARNING_CODES, code)) {
    throw new Error(`unknown warning code '${code}'`);
  }
  return {
    code,
    ids: ids.map((i) => String(i)),
    message: message === undefined || message === null ? (WARNING_CODES[code] as string) : String(message),
  };
}

/** Python tuple order of `(code, ids)`: code by code points, then ids element-wise, a shorter prefix first. */
export function cmp_warning_keys(a: { code: string; ids: readonly string[] }, b: { code: string; ids: readonly string[] }): number {
  const c = cmp_code_points(a.code, b.code);
  if (c !== 0) return c;
  const n = Math.min(a.ids.length, b.ids.length);
  for (let i = 0; i < n; i++) {
    const d = cmp_code_points(a.ids[i] as string, b.ids[i] as string);
    if (d !== 0) return d;
  }
  return a.ids.length - b.ids.length;
}

/** Concatenate warning lists, deduplicate on `(code, ids)` (first message wins) and sort by code then ids. */
export function merge_warnings(...lists: ReadonlyArray<readonly Warning[] | null | undefined>): Warning[] {
  const seen = new Map<string, Warning>();
  for (const lst of lists) {
    if (!lst) continue;
    for (const w of lst) {
      const key = JSON.stringify([w.code, w.ids]);
      if (!seen.has(key)) seen.set(key, { code: w.code, ids: [...w.ids], message: w.message });
    }
  }
  return [...seen.values()].sort(cmp_warning_keys);
}

/** Set of codes present in a warning list. */
export function warning_codes(warnings: readonly Warning[]): Set<string> {
  return new Set(warnings.map((w) => w.code));
}

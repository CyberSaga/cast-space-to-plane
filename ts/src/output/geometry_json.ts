/**
 * §6.2 geometry document serialisation (port of `castplane/output/geometry_json.py`; contract §2.8, §3.1, §5.4.5).
 *
 * `dumps(doc)` reproduces `json.dumps(canonical(doc), sort_keys=True, indent=1, ensure_ascii=False,
 * allow_nan=False)` exactly: keys sorted by Unicode code points, one member / element per line indented by one space
 * per level, strings as `JSON.stringify` writes them, floats in Python `repr` notation (`py_repr`) and the numbers
 * under `INT_KEYS` as integers. A NaN / Infinity throws (spec §7.1 row 6), like Python's `ValueError`.
 * `write_geometry_json` (= `dumps(doc) + "\n"` to a file) lives in `ts/test/helpers.ts`: nothing under src/ touches
 * a file system.
 */

import { cmp_code_points } from "../pyfloat.js";

export { cmp_code_points };

/** The only keys whose numbers are written as integers (contract §5.4.5; == rules.json `int_keys`). */
export const INT_KEYS: ReadonlySet<string> = new Set(["large_arc", "sweep"]);

/** Python `repr(float)` of a finite double (contract §5.4.5): shortest round-trip digits, exponential iff
 * `decpt <= -4 || decpt > 16`. */
export function py_repr(value: number): string {
  if (!Number.isFinite(value)) throw new Error(`Out of range float values are not JSON compliant: ${value}`);
  const x = value + 0;
  if (x === 0) return "0.0";
  const ax = Math.abs(x);
  if (ax >= 1e-4 && ax < 1e16) {
    // JS writes these in fixed notation with the same shortest digits; Python adds ".0" to integral values
    const s = String(x);
    return s.includes(".") ? s : s + ".0";
  }
  const t = ax.toExponential();
  const epos = t.indexOf("e");
  const mant = t.slice(0, epos);
  const e = Number(t.slice(epos + 1));
  const digits = mant.replace(".", "");
  const n = digits.length;
  const decpt = e + 1;
  let s: string;
  if (decpt <= -4 || decpt > 16) {
    const ae = Math.abs(e);
    s = digits[0] + (n > 1 ? "." + digits.slice(1) : "") + "e" + (e < 0 ? "-" : "+") + (ae < 10 ? "0" + ae : String(ae));
  } else if (decpt <= 0) {
    s = "0." + "0".repeat(-decpt) + digits;
  } else if (decpt >= n) {
    s = digits + "0".repeat(decpt - n) + ".0";
  } else {
    s = digits.slice(0, decpt) + "." + digits.slice(decpt);
  }
  return x < 0 ? "-" + s : s;
}

/** Deep copy with canonical numbers (`x + 0`, no `-0`); throws on non-finite numbers (contract §2.8). */
export function canonical<T>(obj: T): T {
  return canon(obj) as T;
}

function canon(obj: unknown): unknown {
  if (typeof obj === "number") {
    if (!Number.isFinite(obj)) throw new Error(`Out of range float values are not JSON compliant: ${obj}`);
    return obj + 0;
  }
  if (obj === null || typeof obj === "string" || typeof obj === "boolean") return obj;
  if (Array.isArray(obj)) return obj.map(canon);
  if (typeof obj === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(obj as object)) out[k] = canon((obj as Record<string, unknown>)[k]);
    return out;
  }
  throw new Error(`not JSON-serialisable: ${typeof obj}`);
}

const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

function encode_string(s: string): string {
  if (LONE_SURROGATE.test(s)) throw new Error("string contains a lone surrogate (not encodable as UTF-8)");
  return JSON.stringify(s);
}

function encode(v: unknown, key: string | null, depth: number, out: string[]): void {
  if (v === null) {
    out.push("null");
    return;
  }
  switch (typeof v) {
    case "number":
      if (key !== null && INT_KEYS.has(key)) {
        if (!Number.isFinite(v)) throw new Error(`Out of range float values are not JSON compliant: ${v}`);
        out.push(String(Math.trunc(v) + 0));
      } else {
        out.push(py_repr(v));
      }
      return;
    case "string":
      out.push(encode_string(v));
      return;
    case "boolean":
      out.push(v ? "true" : "false");
      return;
    case "object": {
      const inner = "\n" + " ".repeat(depth + 1);
      if (Array.isArray(v)) {
        if (v.length === 0) {
          out.push("[]");
          return;
        }
        out.push("[");
        for (let i = 0; i < v.length; i++) {
          out.push(i === 0 ? inner : "," + inner);
          encode(v[i], key, depth + 1, out);
        }
        out.push("\n" + " ".repeat(depth) + "]");
        return;
      }
      const o = v as Record<string, unknown>;
      const keys = Object.keys(o).sort(cmp_code_points);
      if (keys.length === 0) {
        out.push("{}");
        return;
      }
      out.push("{");
      for (let i = 0; i < keys.length; i++) {
        const k = keys[i] as string;
        out.push((i === 0 ? inner : "," + inner) + encode_string(k) + ": ");
        encode(o[k], k, depth + 1, out);
      }
      out.push("\n" + " ".repeat(depth) + "}");
      return;
    }
    default:
      throw new Error(`Object of type ${typeof v} is not JSON serializable`);
  }
}

/** Serialise a geometry document deterministically (contract §3.1, §5.4.5); no trailing newline. */
export function dumps(doc: unknown): string {
  const out: string[] = [];
  encode(doc, null, 0, out);
  return out.join("");
}

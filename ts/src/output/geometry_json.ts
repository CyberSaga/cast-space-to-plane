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
export const INT_KEYS: ReadonlySet<string> = new Set(["large_arc", "sweep", "interval"]);

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

const SURROGATE = /[\uD800-\uDFFF]/;
const LONE_SURROGATE = /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

function encode_string(s: string): string {
  if (SURROGATE.test(s) && LONE_SURROGATE.test(s)) throw new Error("string contains a lone surrogate (not encodable as UTF-8)");
  return JSON.stringify(s);
}

/** `"key": ` of the object keys, cached (a document repeats a few dozen keys hundreds of thousands of times). */
const KEY_CACHE = new Map<string, string>();

function encode_key(k: string): string {
  let e = KEY_CACHE.get(k);
  if (e === undefined) {
    e = encode_string(k) + ": ";
    if (KEY_CACHE.size < 4096) KEY_CACHE.set(k, e);
  }
  return e;
}

const INDENTS: string[] = ["\n"];

/** `"\n"` + `depth` spaces (cached). */
function newline(depth: number): string {
  let s = INDENTS[depth];
  if (s === undefined) {
    for (let d = INDENTS.length; d <= depth; d++) INDENTS.push("\n" + " ".repeat(d));
    s = INDENTS[depth] as string;
  }
  return s;
}

/** UTF-16 code-unit order (what `sort()` without a comparator does), spelled out per §5.4.4 (8). */
function cmp_code_units(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Keys in Unicode code point order: code-unit order is the same unless a key holds a surrogate (fast path). */
function sorted_keys(o: object): string[] {
  const keys = Object.keys(o);
  for (const k of keys) if (SURROGATE.test(k)) return keys.sort(cmp_code_points);
  return keys.sort(cmp_code_units);
}

function encode(v: unknown, key: string | null, depth: number): string {
  if (v === null) return "null";
  switch (typeof v) {
    case "number":
      if (key !== null && INT_KEYS.has(key)) {
        if (!Number.isFinite(v)) throw new Error(`Out of range float values are not JSON compliant: ${v}`);
        return String(Math.trunc(v) + 0);
      }
      return py_repr(v);
    case "string":
      return encode_string(v);
    case "boolean":
      return v ? "true" : "false";
    case "object": {
      const inner = newline(depth + 1);
      if (Array.isArray(v)) {
        const n = v.length;
        if (n === 0) return "[]";
        let out = "[" + inner + encode(v[0], key, depth + 1);
        for (let i = 1; i < n; i++) out += "," + inner + encode(v[i], key, depth + 1);
        return out + newline(depth) + "]";
      }
      const o = v as Record<string, unknown>;
      const keys = sorted_keys(o);
      if (keys.length === 0) return "{}";
      let out = "{";
      for (let i = 0; i < keys.length; i++) {
        const k = keys[i] as string;
        out += (i === 0 ? inner : "," + inner) + encode_key(k) + encode(o[k], k, depth + 1);
      }
      return out + newline(depth) + "}";
    }
    default:
      throw new Error(`Object of type ${typeof v} is not JSON serializable`);
  }
}

/** Serialise a geometry document deterministically (contract §3.1, §5.4.5); no trailing newline. */
export function dumps(doc: unknown): string {
  return encode(doc, null, 0);
}

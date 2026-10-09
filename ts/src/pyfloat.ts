/**
 * Python float / int semantics that JavaScript lacks (contract §5.4.4 (4)).
 *
 * - `pymod(a, m)`: CPython `float_rem` (the result takes the sign of `m`); replaces every float `%` of the Python code.
 * - `pyimod(a, n)`: Python's non-negative integer modulo for a possibly negative left operand.
 * - `py_round(x)`: round half to even (`int(round(x))`).
 * - `cmp_code_points(a, b)`: string order by Unicode code points (Python compares `str` that way; JS `<` compares
 *   UTF-16 code units, which differs for astral characters against U+E000..U+FFFF).
 */

export function pymod(a: number, m: number): number {
  let r = a % m;
  if (r !== 0) {
    if ((r < 0) !== (m < 0)) r += m;
  } else {
    r = m < 0 ? -0 : 0;
  }
  return r;
}

export function pyimod(a: number, n: number): number {
  return ((a % n) + n) % n;
}

export function py_round(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  if (d < 0.5) return f;
  if (d > 0.5) return f + 1;
  return f % 2 === 0 ? f : f + 1;
}

/** Map a UTF-16 code unit so that unit order equals code point order (surrogates sort above U+FFFF). */
function fixup(c: number): number {
  if (c >= 0xe000) return c - 0x800;
  if (c >= 0xd800) return c + 0x2000;
  return c;
}

export function cmp_code_points(a: string, b: string): number {
  if (a === b) return 0;
  const n = Math.min(a.length, b.length);
  for (let i = 0; i < n; i++) {
    const ca = a.charCodeAt(i);
    const cb = b.charCodeAt(i);
    if (ca !== cb) {
      if (ca >= 0xd800 && cb >= 0xd800) return fixup(ca) - fixup(cb);
      return ca - cb;
    }
  }
  return a.length - b.length;
}

/**
 * Python `format(x, ".<d>f")` for `0 <= d <= 20`: correctly rounded from the exact binary value with exact ties to
 * even (contract §5.7.5). JS `toFixed` is also exact but rounds an exact tie away from zero; a tie at `d` decimals is
 * `x = j / 2^(d+1)` with `j` odd (`x·10^d = j·5^d / 2`), rounded here with integer arithmetic as `fmt` does at four
 * decimals (§5.4.6). From `|x| >= 1e21` on, `toFixed` switches to exponent notation; every such double is an integer
 * (`>= 2^53`), so its exact digits come from `BigInt` (`"10000000000000000000000.00"` for `1e22`, as Python). The sign
 * of a negative value is kept, negative zero included (`"-0.00"` for `-0.001` and for `-0.0`), as Python does.
 */
export function py_fixed(x: number, d: number): string {
  const v = x + 0;
  if (!Number.isFinite(v)) return Number.isNaN(v) ? "nan" : v > 0 ? "inf" : "-inf";
  const y = v * 2 ** (d + 1);
  if (Math.abs(v) < 1e21 && Number.isInteger(y) && Math.abs(y) % 2 === 1) { // pyimod-free: absolute value
    const n2 = BigInt(Math.abs(y)) * 5n ** BigInt(d); // = 2·x·10^d, odd
    const f = n2 / 2n;
    const m = f % 2n === 0n ? f : f + 1n; // pyimod-free: BigInt f >= 0
    const scale = 10n ** BigInt(d);
    const frac = d > 0 ? "." + (m % scale).toString().padStart(d, "0") : ""; // pyimod-free: BigInt m >= 0
    return (v < 0 ? "-" : "") + (m / scale).toString() + frac;
  }
  if (Math.abs(v) >= 1e21) return BigInt(v).toString() + (d > 0 ? "." + "0".repeat(d) : "");
  if (Object.is(x, -0)) return "-" + (0).toFixed(d); // toFixed drops the sign of -0
  return v.toFixed(d);
}

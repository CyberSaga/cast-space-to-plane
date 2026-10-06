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

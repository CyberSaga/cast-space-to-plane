"""§6.2 geometry document serialisation (contract §2.8, §3.1).

Deterministic: every float is canonicalised with ``x + 0.0`` (no ``-0.0``),
numpy values become plain Python, and ``json.dumps(doc, sort_keys=True,
indent=1, ensure_ascii=False, allow_nan=False)`` writes shortest round-trip floats.
A NaN / Infinity is a contract violation (spec §7.1 row 6) and makes :func:`dumps`
raise ``ValueError`` instead of writing the token ``NaN`` (contract §5.4.5, the same
failure as the TypeScript writer's).

Speed (spec §8): on CPython >= 3.13 the stdlib C encoder indents and does all the work.
Before 3.13 it cannot indent, so :func:`dumps` lets it write the compact text and
:func:`_reindent` turns that into the ``indent=1`` text with one vectorised NumPy pass.
"""

from __future__ import annotations

import json

import numpy as np


def canonical(obj):
    """Recursively convert to JSON-native types with canonical floats (contract §2.8)."""
    t = type(obj)
    if t is float:
        return obj + 0.0
    if t is str or t is bool or t is int or obj is None:
        return obj
    if t is dict:
        return {str(k): canonical(v) for k, v in obj.items()}
    if t is list or t is tuple:
        return [canonical(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return canonical((obj + 0.0).tolist() if obj.dtype.kind == "f" else obj.tolist())
    if isinstance(obj, (bool, np.bool_)):
        return bool(obj)
    if isinstance(obj, (int, np.integer)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return float(obj) + 0.0
    if isinstance(obj, dict):
        return {str(k): canonical(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [canonical(v) for v in obj]
    return obj


# ---------------------------------------------------------------------------
# serialisation (spec §8): the stdlib's C encoder when it can indent, else the C encoder's compact
# text re-indented by NumPy, and the pure-Python encoder for the inputs neither can take
# ---------------------------------------------------------------------------

_REFERENCE_KW = {"sort_keys": True, "indent": 1, "ensure_ascii": False, "allow_nan": False}


def _reference_dumps(doc) -> str:
    return json.dumps(canonical(doc), **_REFERENCE_KW)


def _make_c_encoder():
    """The C accelerated encoder configured like ``json.dumps(**_REFERENCE_KW)``, or ``None``.

    ``json.dumps`` only uses the C encoder when ``indent`` is ``None`` and otherwise falls back to
    the pure-Python generator encoder, which is several times slower on a 10 MB document.  On
    interpreters whose C encoder implements indentation (checked here on a probe document that
    exercises nesting, empty containers, sorting and non-ASCII text) we call it directly;
    numpy values go through ``canonical`` as the ``default`` hook.
    """
    c_make_encoder = getattr(json.encoder, "c_make_encoder", None)
    if c_make_encoder is None:
        return None
    try:
        # (markers, default, encoder, indent, key_separator, item_separator, sort_keys, skipkeys, allow_nan)
        enc = c_make_encoder(None, canonical, json.encoder.encode_basestring, " ", ": ", ",", True, False, False)
        probe = {"b": [1, 2.5, [], {}, [[-1.0, 0.0]], {"y": None, "x": [True, "中文 \"q\""]}], "a": {}, "c": []}
        if "".join(enc(probe, 0)) != json.dumps(probe, **_REFERENCE_KW):
            return None
        return enc
    except Exception:  # pragma: no cover - depends on the interpreter build
        return None


_C_ENCODER = _make_c_encoder()

#: ``json.dumps(**_REFERENCE_KW)`` without the indentation: what the C encoder writes on every CPython.
_COMPACT_KW = {"sort_keys": True, "separators": (",", ":"), "ensure_ascii": False, "allow_nan": False}

# The bytes of the compact text that matter to the re-indentation (all ASCII, so in UTF-8 they never
# occur inside a multi-byte sequence: the non-ASCII text that ``ensure_ascii=False`` keeps raw is safe).
_QUOTE, _BACKSLASH, _COMMA, _COLON = 0x22, 0x5C, 0x2C, 0x3A
_OPENERS, _CLOSERS = (0x5B, 0x7B), (0x5D, 0x7D)   # "[", "{" / "]", "}"


def _reindent(compact: str) -> str:
    """The ``indent=1`` text of a compact (``_COMPACT_KW``) JSON text, byte for byte.

    ``json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False)`` is the compact text of the same
    object with whitespace inserted at structural characters only (``json.encoder._make_iterencode``):

    * after a non-empty ``[`` / ``{`` and after each ``,``: a newline and one space per depth inside;
    * before a non-empty ``]`` / ``}``: a newline and one space per depth outside;
    * after each ``:`` (a key separator -- outside strings ``:`` is nothing else): one space;
    * an empty ``[]`` / ``{}`` stays as it is, and so does everything inside a string literal.

    So the work is finding the structural characters.  A ``"`` opens or closes a string unless it is
    escaped, i.e. preceded by an odd run of backslashes (the encoder writes ``\\"`` for a quote and
    ``\\\\`` for a backslash, and a backslash never occurs outside a string); a character is outside
    every string when an even number of real quotes precedes it.  Only the positions of the candidate
    characters (about a fifth of a geometry document) are handled one by one; the output is then built
    with one ``np.repeat`` of a keep / insert pattern over the segments between insertion points.
    """
    # "surrogatepass": a lone surrogate in a string (which ``ensure_ascii=False`` keeps raw) survives the
    # round trip as three bytes >= 0x80, like any other non-ASCII text
    raw = compact.encode("utf-8", "surrogatepass")
    b = np.frombuffer(raw, dtype=np.uint8)
    cand = np.flatnonzero((b == _QUOTE) | (b == _COMMA) | (b == _COLON) | (b == _OPENERS[0])
                          | (b == _OPENERS[1]) | (b == _CLOSERS[0]) | (b == _CLOSERS[1]))
    cb = b[cand]
    quote = cb == _QUOTE
    real_quote = quote
    if b"\\" in raw:
        # a run of k backslashes ending at e escapes the character at e + 1 when k is odd
        bpos = np.flatnonzero(b == _BACKSLASH)
        brk = np.flatnonzero(np.diff(bpos) != 1)
        starts = np.concatenate((bpos[:1], bpos[brk + 1]))
        ends = np.concatenate((bpos[brk], bpos[-1:]))
        escaped = ends[(ends - starts) % 2 == 0] + 1
        if escaped.size:
            at = np.minimum(np.searchsorted(escaped, cand), escaped.size - 1)
            real_quote = quote & (escaped[at] != cand)
    # structural: outside every string (an even count of real quotes up to here) and not a quote itself
    structural = ((np.cumsum(real_quote) & 1) == 0) & ~quote
    s, sb = cand[structural], cb[structural]
    opener = (sb == _OPENERS[0]) | (sb == _OPENERS[1])
    closer = (sb == _CLOSERS[0]) | (sb == _CLOSERS[1])
    depth = np.cumsum(opener.astype(np.int64) - closer)     # depth just after each structural character
    empty_open = np.zeros(s.size, dtype=bool)                # "[" / "{" immediately followed by its closer
    empty_open[:-1] = opener[:-1] & closer[1:] & (s[1:] == s[:-1] + 1)
    empty_close = np.zeros(s.size, dtype=bool)
    empty_close[1:] = empty_open[:-1]
    before = closer & ~empty_close                           # newline + indent inserted before the character
    newline = (opener & ~empty_open) | (sb == _COMMA) | before
    insert = newline | (sb == _COLON)
    if not insert.any():                                     # a scalar, "[]", "{}"
        return compact
    before, newline = before[insert], newline[insert]
    # Insertion point k goes into the gap ``gap[k]`` of the compact text (before byte gap[k]).  The gaps
    # strictly increase: two insertions could only share a gap if a "," / ":" / non-empty opener were
    # directly followed by a non-empty closer, which valid JSON never has.
    gap = np.where(before, s[insert], s[insert] + 1)
    length = np.where(newline, depth[insert] + 1, 1)          # "\n" + depth spaces, or the ": " space
    counts = np.empty(2 * gap.size + 1, dtype=np.int64)       # kept segment, inserted run, ..., last segment
    counts[0:-1:2] = np.diff(gap, prepend=0)
    counts[1::2] = length
    counts[-1] = b.size - gap[-1]
    keep_pattern = np.zeros(counts.size, dtype=bool)
    keep_pattern[0::2] = True
    keep = np.repeat(keep_pattern, counts)
    out = np.full(keep.size, ord(" "), dtype=np.uint8)
    out[keep] = b
    out[(gap + np.cumsum(length) - length)[newline]] = ord("\n")
    return out.tobytes().decode("utf-8", "surrogatepass")


def _has_negative_zero(compact: str) -> bool:
    """Whether a compact text may carry the number ``-0.0`` (conservatively: the token followed by
    ``,`` / ``]`` / ``}`` or ending the text; a string that happens to contain it is a false alarm)."""
    return ("-0.0," in compact or "-0.0]" in compact or "-0.0}" in compact
            or compact.endswith("-0.0"))


def _compact_dumps(doc) -> str:
    """:func:`dumps` for interpreters whose C encoder cannot indent (CPython < 3.13).

    The C encoder writes the compact text, configured like ``_C_ENCODER`` but for the indentation
    (``canonical`` as the ``default`` hook, ``sort_keys``, ``ensure_ascii=False``, ``allow_nan=False``),
    and :func:`_reindent` inserts the whitespace; the result is the text the 3.13+ path writes.  If the
    text may hold a ``-0.0`` the canonical document is encoded instead, and an input the C encoder
    rejects (NaN / infinity, an unsupported type, a cycle) goes to the reference encoder, so that the
    exception is the reference's own.
    """
    try:
        out = json.dumps(doc, default=canonical, **_COMPACT_KW)
        if _has_negative_zero(out):
            out = json.dumps(canonical(doc), **_COMPACT_KW)
    except (TypeError, ValueError, OverflowError):
        return _reference_dumps(doc)
    return _reindent(out)


def dumps(doc: dict) -> str:
    """Serialise a geometry document deterministically (contract §3.1).

    The result is exactly ``json.dumps(canonical(doc), sort_keys=True, indent=1,
    ensure_ascii=False, allow_nan=False)`` -- a NaN or an infinity raises ``ValueError``
    (contract §5.4.5) -- and when the interpreter's C encoder can indent it does the work
    (numpy values are converted by :func:`canonical` on the way).  A negative zero that the
    C path would print as ``-0.0`` is impossible in a document produced by ``compose`` (every
    float is canonical), and any other input that could carry one is re-encoded through
    :func:`canonical` so that the two paths never differ.  Before CPython 3.13 the C encoder
    writes the compact text and NumPy indents it (:func:`_compact_dumps`), the same bytes.
    """
    if _C_ENCODER is None:
        return _compact_dumps(doc)
    try:
        out = "".join(_C_ENCODER(doc, 0))
    except (TypeError, ValueError, OverflowError):
        return _reference_dumps(doc)
    if "-0.0," not in out and "-0.0\n" not in out:
        return out
    return _reference_dumps(doc)


def write_geometry_json(doc: dict, path) -> None:
    """Write :func:`dumps` output to ``path`` (UTF-8, trailing newline)."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(doc))
        fh.write("\n")

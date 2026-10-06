"""§6.2 geometry document serialisation (contract §2.8, §3.1).

Deterministic: every float is canonicalised with ``x + 0.0`` (no ``-0.0``),
numpy values become plain Python, and ``json.dumps(doc, sort_keys=True,
indent=1, ensure_ascii=False, allow_nan=False)`` writes shortest round-trip floats.
A NaN / Infinity is a contract violation (spec §7.1 row 6) and makes :func:`dumps`
raise ``ValueError`` instead of writing the token ``NaN`` (contract §5.4.5, the same
failure as the TypeScript writer's).
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
# serialisation (spec §8): the stdlib's C encoder when it can indent, else the pure-Python one
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


def dumps(doc: dict) -> str:
    """Serialise a geometry document deterministically (contract §3.1).

    The result is exactly ``json.dumps(canonical(doc), sort_keys=True, indent=1,
    ensure_ascii=False, allow_nan=False)`` -- a NaN or an infinity raises ``ValueError``
    (contract §5.4.5) -- and when the interpreter's C encoder can indent it does the work
    (numpy values are converted by :func:`canonical` on the way).  A negative zero that the
    C path would print as ``-0.0`` is impossible in a document produced by ``compose`` (every
    float is canonical), and any other input that could carry one is re-encoded through
    :func:`canonical` so that the two paths never differ.
    """
    if _C_ENCODER is not None:
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

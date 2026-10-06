"""§6.2 geometry document serialisation (contract §2.8, §3.1).

Deterministic: every float is canonicalised with ``x + 0.0`` (no ``-0.0``),
numpy values become plain Python, and ``json.dumps(doc, sort_keys=True,
indent=1, ensure_ascii=False)`` writes shortest round-trip floats.
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


def dumps(doc: dict) -> str:
    """Serialise a geometry document deterministically (contract §3.1)."""
    return json.dumps(canonical(doc), sort_keys=True, indent=1, ensure_ascii=False)


def write_geometry_json(doc: dict, path) -> None:
    """Write :func:`dumps` output to ``path`` (UTF-8, trailing newline)."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dumps(doc))
        fh.write("\n")

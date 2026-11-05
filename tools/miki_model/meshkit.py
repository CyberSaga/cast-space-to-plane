"""Mesh toolkit of the Miki model: a re-export of :mod:`charmodel.meshkit` (the shared, character-free toolkit).

The code lives in ``tools/charmodel/meshkit.py``; this module keeps ``from miki_model import meshkit as mk`` (the
part builders, ``tests/test_miki_model.py``) working.  The classes are the same objects (``mk.Part is
charmodel.meshkit.Part``), so parts built here pass ``charmodel.assembly``'s checks.
"""

from __future__ import annotations

from charmodel.meshkit import *  # noqa: F401,F403
from charmodel.meshkit import __all__  # noqa: F401
from charmodel.meshkit import (  # noqa: F401  (private helpers some builders and the docs refer to)
    _below_fan, _best_fan_start, _dome_rings, _grid_normals, _group_table, _nested_first_vertices, _outward,
    _param, _parse_cap, _rmf, _shell_labels, _shell_tris, _signed_volume, _spow,
)

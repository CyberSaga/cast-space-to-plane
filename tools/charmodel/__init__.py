"""Shared, character-free toolkit of the castplane character model generators (``tools/<name>_model/``).

Modules: :mod:`meshkit` (mesh type, closed-shell builders, validation, nesting fix, ray count),
:mod:`assembly` (a :class:`~charmodel.assembly.Character` description; parts -> compact castplane objects,
statistics, budget), :mod:`export` (scene JSON, OBJ + MTL, GLB writers), :mod:`preview` (shaded z-buffer
renders, castplane line renders, contact sheets, camera presets) and :mod:`cli` (the ``make_<name>_model.py``
command line).  ``meshkit``, ``assembly`` and ``export`` import numpy and the standard library only; ``preview``
imports Pillow and cairosvg lazily, and the castplane imports are lazy too.  No module holds character content:
names, numbers, colours and texts come from the character package (``README.md`` in this directory).
"""

"""Generator of the Hanabishi Miki drawing-reference model for castplane (``tools/make_miki_model.py``).

Modules: :mod:`meshkit` (mesh type, closed-shell builders, validation), :mod:`rig` (all proportions),
:mod:`mannequin` (placeholder parts for every region), :mod:`head` / :mod:`hair` / :mod:`body` /
:mod:`limbs` (the detailed parts; ``build(rig)`` returns ``None`` until written), :mod:`assemble`
(parts -> the ten castplane objects), :mod:`export` (scene JSON, OBJ + MTL, GLB) and :mod:`preview`
(shaded and castplane line renders).  Geometry modules import numpy and the standard library only.
"""

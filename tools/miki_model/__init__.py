"""Generator of the Hanabishi Miki drawing-reference model for castplane (``tools/make_miki_model.py``).

Miki's character content on top of the shared toolkit :mod:`charmodel` (``tools/charmodel/``): :mod:`rig` (all
proportions), :mod:`mannequin` (placeholder parts for every region), :mod:`head` / :mod:`hair` / :mod:`body` /
:mod:`limbs` (the detailed parts; ``build(rig)`` returns ``None`` until written), :mod:`assemble` (her objects,
materials and region map: the :class:`~charmodel.assembly.Character` of the 18 compact castplane objects),
:mod:`export` (her scene settings, description and copyright texts for the scene JSON, OBJ + MTL and GLB
writers) and :mod:`preview` (her camera presets for the shaded and castplane line renders).  :mod:`meshkit`
re-exports :mod:`charmodel.meshkit`.  Geometry modules import numpy and the standard library only.
"""

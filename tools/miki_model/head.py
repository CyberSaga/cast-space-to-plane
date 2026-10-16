"""Head, face, ears, eyes, eyebrows and mouth of the Miki model (owner: head agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS` (each part's ``region`` should name one of them, so ``--only`` can filter), or ``None``
while the module is not written yet: ``assemble`` then uses the mannequin parts of those regions.
Part names are unique across the model.
Objects / materials (``Part(name, material, mesh, region, obj=...)``, see ``assemble.OBJECTS``): head + face ->
head (skin; no ears); sclera, highlight -> eyes (eye_white), iris -> eyes (iris), pupil -> eyes (pupil); brows,
lid bands, lower-lid marks, mouth -> face_marks (face_marks).
Every part mesh must be closed shells that pass ``meshkit.validate``.
"""

from __future__ import annotations

from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The mannequin regions this module replaces.
REGIONS = ("head", "eyes", "face_marks")


def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``, or ``None`` (not implemented: use the mannequin)."""
    return None

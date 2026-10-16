"""Hair cap, bangs, sidelocks, the stray strand, back hair and the headband of the Miki model (owner: head agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS` (each part's ``region`` should name one of them, so ``--only`` can filter), or ``None``
while the module is not written yet: ``assemble`` then uses the mannequin parts of those regions.
Part names are unique across the model.
Objects / materials (``Part(name, material, mesh, region, obj=...)``, see ``assemble.OBJECTS``): dome, bangs,
strand -> hair (hair); sidelocks -> ``obj="sidelocks"`` (hair); curtain + back sheet -> ``obj="back_hair"``
(hair); band -> headband (headband), its pink ridge -> headband (uniform).
Every part mesh must be closed shells that pass ``meshkit.validate``.
"""

from __future__ import annotations

from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The mannequin regions this module replaces.
REGIONS = ("hair", "headband")


def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``, or ``None`` (not implemented: use the mannequin)."""
    return None

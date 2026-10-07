"""STL / PLY (and every other format trimesh reads) through the optional extra ``mesh``
(``pip install 'castplane[mesh]'``, ``trimesh>=4``; contract §5.2.8).

trimesh is used purely as a reader of the stored vertices and faces: ``trimesh.load(...,
force="mesh", process=False)``; no merging, normal fixing or reordering (those are
version-dependent and would break bit-determinism; the preprocessing pipeline of
``castplane.meshprep`` does the welding).  trimesh is imported lazily, so importing this module
never needs it; a missing trimesh is ``ImportError("install castplane[mesh]")`` (CLI exit 3).
"""

from __future__ import annotations

import os

import numpy as np

from ..errors import SceneError

__all__ = ["load_trimesh"]


def load_trimesh(path, node=None) -> dict:
    """The raw mesh ``{vertices, faces, smooth_groups}`` of a file read by trimesh (file axes,
    file units, faces as stored)."""
    try:
        import trimesh
    except ImportError as exc:
        raise ImportError("install castplane[mesh]") from exc
    if node is not None:
        raise SceneError("node", "node selection needs an OBJ or glTF file")
    ext = os.path.splitext(str(path))[1].lower().lstrip(".")
    with open(path, "rb") as fh:
        try:
            mesh = trimesh.load(fh, file_type=ext, force="mesh", process=False)
        except Exception as exc:  # trimesh raises a variety of exception types for bad input
            raise SceneError("", f"trimesh cannot read the file: {exc}") from None
    V = np.asarray(getattr(mesh, "vertices", np.zeros((0, 3))), dtype=np.float64).reshape(-1, 3)
    F = np.asarray(getattr(mesh, "faces", np.zeros((0, 3))), dtype=np.int64).reshape(-1, 3)
    if len(F) == 0:
        raise SceneError("", "the file holds no face")
    if not np.all(np.isfinite(V)):
        raise SceneError("", "vertex coordinates must be finite")
    return {"vertices": (V + 0.0).tolist(), "faces": F.tolist(), "smooth_groups": [0] * len(F)}

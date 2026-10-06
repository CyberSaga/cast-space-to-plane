"""castplane: perspective shadow construction drawing (cast-space-to-plane).

Public API (contract §3)::

    scene = castplane.load_scene(path_or_dict)
    A     = castplane.shadow_geometry(scene)
    B     = castplane.project_scene(scene, A, camera=None)
    doc   = castplane.compose(scene, B)
    svg   = castplane.output.svg.write_svg(doc, layers=None)
    png   = castplane.output.png.write_png(svg, dpi)
    out   = castplane.render(scene, camera=None)   # {"geometry": doc, "svg": str}
"""

from . import construction, curved, output  # noqa: F401
from .errors import SceneError, make_warning, merge_warnings
from .pipeline import compose, project_scene, render, shadow_geometry
from .scene import load_scene, validate_scene

__version__ = "0.1.0"

__all__ = [
    "SceneError",
    "__version__",
    "compose",
    "construction",
    "curved",
    "load_scene",
    "make_warning",
    "merge_warnings",
    "output",
    "project_scene",
    "render",
    "shadow_geometry",
    "validate_scene",
]

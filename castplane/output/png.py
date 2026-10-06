"""§6.3 PNG rasterisation (contract §2.10): cairosvg if importable, else the resvg CLI.

Transparent background; pixel size ``round(canvas_mm · dpi / 25.4)``.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile

_SIZE_RE = re.compile(r'<svg[^>]*\swidth="([0-9.eE+-]+)mm"[^>]*\sheight="([0-9.eE+-]+)mm"')


def png_size(svg_str: str, dpi: float):
    """``(width_px, height_px) = round(canvas_mm · dpi / 25.4)`` from the SVG's mm size (contract §2.10)."""
    m = _SIZE_RE.search(svg_str)
    if not m:
        raise ValueError("SVG root must carry width/height in mm")
    w_mm, h_mm = float(m.group(1)), float(m.group(2))
    return int(round(w_mm * dpi / 25.4)), int(round(h_mm * dpi / 25.4))


def write_png(svg_str: str, dpi: float = 300) -> bytes:
    """Rasterise an SVG string to PNG bytes (§6.3).  Raises ``ImportError`` when no backend exists."""
    w_px, h_px = png_size(svg_str, dpi)
    try:
        import cairosvg  # optional extra `png`
    except ImportError:
        cairosvg = None
    if cairosvg is not None:
        return cairosvg.svg2png(bytestring=svg_str.encode("utf-8"), output_width=w_px, output_height=h_px,
                                dpi=dpi)
    resvg = shutil.which("resvg")
    if resvg is not None:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "in.svg")
            dst = os.path.join(tmp, "out.png")
            with open(src, "w", encoding="utf-8") as fh:
                fh.write(svg_str)
            subprocess.run([resvg, "--width", str(w_px), "--height", str(h_px), src, dst], check=True)
            with open(dst, "rb") as fh:
                return fh.read()
    raise ImportError("PNG output needs cairosvg (pip install 'castplane[png]') or the resvg CLI on PATH")

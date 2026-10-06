"""Nonzero-winding polygon rasterizer and IoU for the ray-casting comparison (spec §7.3,
contract §1).  Shares no code with ``castplane``.  Vectorised with numpy."""

from __future__ import annotations

import numpy as np


def winding_numbers(loops, xs, ys) -> np.ndarray:
    """Winding number of every grid point ``(xs[ix], ys[iy])`` with respect to the union of
    the closed 2-D loops (each an ``(k, 2)`` array, implicitly closed).  Returns an int
    grid of shape ``(len(ys), len(xs))``; counter-clockwise loops contribute ``+1``."""
    xs = np.asarray(xs, dtype=np.float64).reshape(-1)
    ys = np.asarray(ys, dtype=np.float64).reshape(-1)
    X, Y = np.meshgrid(xs, ys)
    wn = np.zeros(X.shape, dtype=np.int64)
    for loop in loops:
        P = np.asarray(loop, dtype=np.float64).reshape(-1, 2)
        k = P.shape[0]
        if k < 3:
            continue
        for i in range(k):
            x0, y0 = P[i]
            x1, y1 = P[(i + 1) % k]
            if y0 == y1:
                continue
            # signed area of (p0, p1, point) > 0  <=>  point left of the directed edge
            left = (x1 - x0) * (Y - y0) - (X - x0) * (y1 - y0)
            upward = (y0 <= Y) & (Y < y1)
            downward = (y1 <= Y) & (Y < y0)
            wn += (upward & (left > 0)).astype(np.int64)
            wn -= (downward & (left < 0)).astype(np.int64)
    return wn


def rasterize_polygons(loops, xs, ys) -> np.ndarray:
    """Bool grid ``(len(ys), len(xs))`` of the region covered by the loops under the
    **nonzero** winding rule (contract §2.5: cast shadows are filled with ``nonzero``)."""
    return winding_numbers(loops, xs, ys) != 0


def iou(a, b) -> float:
    """Intersection over union of two bool masks; ``1.0`` when both are empty."""
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    union = int(np.count_nonzero(a | b))
    if union == 0:
        return 1.0
    return float(np.count_nonzero(a & b)) / union

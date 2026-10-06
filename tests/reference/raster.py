"""Nonzero-winding polygon rasterizer and IoU for the ray-casting comparison (spec §7.3,
contract §1), plus the reconstruction of ground polygons from the §6.2 shadow loops of a
geometry document (named points -> their world coordinates; direction entries of unbounded
outlines -> a point far away along the direction).  Shares no code with ``castplane``.
Vectorised with numpy."""

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


# --------------------------------------------------------------------------- §6.2 loops -> ground polygons
def loop_entries_to_ground(doc: dict, loop, centre, far: float) -> np.ndarray:
    """World ground ``(x, y)`` polygon of one §6.2 loop: named points are looked up in
    ``doc["points"]`` (they must lie on the receiver), direction entries become the point
    ``centre + far · d`` (``far`` large against the compared window: the chord then deviates
    from the true ray by ``O(window / far)`` inside the window)."""
    out = []
    for entry in loop:
        if isinstance(entry, str):
            p = doc["points"][entry]
            assert "world" in p, f"{entry} is not a finite point"
            w = p["world"]
            assert abs(w[2]) <= 1e-9, f"shadow point {entry} is not on the ground: z = {w[2]}"
            out.append([w[0], w[1]])
        elif isinstance(entry, dict) and "direction" in entry:
            d = np.asarray(entry["direction"], dtype=np.float64)
            assert abs(d[2]) <= 1e-9, f"direction entry {entry} is not in the ground plane"
            n = float(np.hypot(d[0], d[1]))
            assert n > 0.0
            out.append([centre[0] + far * d[0] / n, centre[1] + far * d[1] / n])
        elif isinstance(entry, dict) and "world" in entry:
            w = entry["world"]
            out.append([w[0], w[1]])
        else:  # pragma: no cover - an entry kind this harness does not know
            raise AssertionError(f"unknown §6.2 loop entry {entry!r}")
    return np.asarray(out, dtype=np.float64).reshape(-1, 2)


def doc_ground_loops(doc: dict, centre, far: float, objects=None) -> list:
    """Every §6.2 shadow loop of the document (of the given ``objects`` when not None) as a ground
    polygon; loops with fewer than three vertices are skipped."""
    loops = []
    for sh in doc["shadows"]:
        if objects is not None and sh["object"] not in objects:
            continue
        for loop in sh["loops"]:
            poly = loop_entries_to_ground(doc, loop, centre, far)
            if poly.shape[0] >= 3:
                loops.append(poly)
    return loops

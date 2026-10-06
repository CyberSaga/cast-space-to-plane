"""Independent ray-casting reference for cast shadows (spec §7.3, contract §1).

This module shares **no code** with ``castplane``: it only reads the validated scene
dict format of spec §4 and re-implements the object placement (position + Z-Y-X
``rotation_deg``) and exact analytic ray/solid intersection for the five primitives.

A ground sample point ``G = (x, y, 0)`` is in shadow when the open segment from ``G``
towards the light (``t in (0, 1)`` for a point light, ``t > 0`` for a directional
light) meets any object.  Each primitive is a closed bounded solid; the segment meets
the solid iff it crosses its boundary surface (the light is assumed outside every
object, the segment's far end is then outside; its near end may lie inside a buried
part).

All tests are vectorised over the sample grid with numpy.
"""

from __future__ import annotations

import math

import numpy as np

T_EPS = 1e-9        # parameters t <= T_EPS count as the ray origin itself (ignored)
GEOM_EPS = 1e-9     # inclusive tolerance for "on the finite surface" tests


# --------------------------------------------------------------------------- placement
def rotation_matrix(rotation_deg) -> np.ndarray:
    """``R = Rz(rz) Ry(ry) Rx(rx)`` for ``rotation_deg = [rx, ry, rz]`` (spec §4, Z-Y-X order),
    each a right-handed rotation about its axis; ``world = R local + position``."""
    rx, ry, rz = (math.radians(float(v)) for v in rotation_deg)
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]], dtype=np.float64)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], dtype=np.float64)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]], dtype=np.float64)
    return Rz @ Ry @ Rx


def object_frame(obj: dict) -> tuple[np.ndarray, np.ndarray]:
    """``(R, position)`` of an object from its optional ``transform`` block."""
    tr = obj.get("transform") or {}
    pos = np.asarray(tr.get("position", [0.0, 0.0, 0.0]), dtype=np.float64).reshape(3)
    R = rotation_matrix(tr.get("rotation_deg", [0.0, 0.0, 0.0]))
    return R, pos


def to_local(obj: dict, origins: np.ndarray, dirs: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Transform world rays into the object's local frame (``local = R^T (world - position)``)."""
    R, pos = object_frame(obj)
    o = (origins - pos[None, :]) @ R        # (R^T x)^T = x^T R
    d = dirs @ R
    return o, d


# --------------------------------------------------------------------------- helpers
def _in_range(t: np.ndarray, tmax: np.ndarray | float) -> np.ndarray:
    """``T_EPS < t < tmax`` (tmax may be inf)."""
    return (t > T_EPS) & (t < tmax)


def _safe_div(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    """``num / den`` with ``den == 0`` giving ``nan`` (never a warning)."""
    out = np.full(np.broadcast(num, den).shape, np.nan, dtype=np.float64)
    ok = den != 0.0
    np.divide(num, den, out=out, where=ok)
    return out


def _quadratic_roots(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Real roots of ``a t^2 + b t + c = 0`` per element; ``nan`` where none.
    Linear equations (``a == 0``) return their single root in both slots."""
    disc = b * b - 4.0 * a * c
    lin = np.abs(a) <= 1e-14 * np.maximum(1.0, np.abs(b) + np.abs(c))
    sq = np.sqrt(np.where(disc >= 0.0, disc, np.nan))
    with np.errstate(divide="ignore", invalid="ignore"):
        q = -0.5 * (b + np.sign(b + (b == 0.0)) * sq)   # numerically stable form
        t1 = np.where(a != 0.0, q / np.where(a != 0.0, a, 1.0), np.nan)
        t2 = np.where(q != 0.0, c / np.where(q != 0.0, q, 1.0), np.nan)
        tlin = _safe_div(-c, b)
    t1 = np.where(lin, tlin, t1)
    t2 = np.where(lin, tlin, t2)
    lo = np.fmin(t1, t2)
    hi = np.fmax(t1, t2)
    return lo, hi


def point_in_polygon(px: np.ndarray, py: np.ndarray, polygon) -> np.ndarray:
    """Even-odd (crossing number) point-in-polygon test, vectorised over points; points
    on an edge count as inside within ``GEOM_EPS``."""
    poly = np.asarray(polygon, dtype=np.float64).reshape(-1, 2)
    n = poly.shape[0]
    inside = np.zeros(px.shape, dtype=bool)
    on_edge = np.zeros(px.shape, dtype=bool)
    for i in range(n):
        x0, y0 = poly[i]
        x1, y1 = poly[(i + 1) % n]
        cond = (y0 > py) != (y1 > py)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = x0 + (py - y0) * (x1 - x0) / (y1 - y0)
        inside ^= cond & (px < xint)
        # distance to the segment for the on-edge test
        ex, ey = x1 - x0, y1 - y0
        ee = ex * ex + ey * ey
        s = np.clip(((px - x0) * ex + (py - y0) * ey) / ee, 0.0, 1.0) if ee > 0 else 0.0
        dx = px - (x0 + s * ex)
        dy = py - (y0 + s * ey)
        on_edge |= (dx * dx + dy * dy) <= GEOM_EPS * GEOM_EPS
    return inside | on_edge


# --------------------------------------------------------------------------- primitives
def hit_box(obj: dict, o: np.ndarray, d: np.ndarray, tmax) -> np.ndarray:
    """Slab test in the local frame: box spans ``[-sx/2, sx/2] x [-sy/2, sy/2] x [0, sz]``."""
    sx, sy, sz = (float(v) for v in obj["size"])
    lo = np.array([-sx / 2, -sy / 2, 0.0])
    hi = np.array([sx / 2, sy / 2, sz])
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / d
        t0 = (lo[None, :] - o) * inv
        t1 = (hi[None, :] - o) * inv
    # rays parallel to a slab: inside -> (-inf, inf), outside -> empty
    par = d == 0.0
    inside_slab = (o >= lo[None, :] - GEOM_EPS) & (o <= hi[None, :] + GEOM_EPS)
    tn = np.where(par, np.where(inside_slab, -np.inf, np.inf), np.fmin(t0, t1))
    tf = np.where(par, np.where(inside_slab, np.inf, -np.inf), np.fmax(t0, t1))
    t_near = np.max(tn, axis=1)
    t_far = np.min(tf, axis=1)
    enter = np.maximum(t_near, T_EPS)
    leave = np.minimum(t_far, tmax)
    return (t_near <= t_far) & (enter < leave)


def hit_sphere(obj: dict, o: np.ndarray, d: np.ndarray, tmax) -> np.ndarray:
    """Sphere of radius ``r`` centred at local ``(0, 0, r)``; the line meets the solid in
    ``[t1, t2]`` and the segment is shadowed when that meets ``(0, tmax)``."""
    r = float(obj["radius"])
    oc = o - np.array([0.0, 0.0, r])[None, :]
    a = np.einsum("ij,ij->i", d, d)
    b = 2.0 * np.einsum("ij,ij->i", d, oc)
    c = np.einsum("ij,ij->i", oc, oc) - r * r
    t1, t2 = _quadratic_roots(a, b, c)
    ok = ~np.isnan(t1)
    enter = np.maximum(t1, T_EPS)
    leave = np.minimum(t2, tmax)
    return ok & (enter < leave)


def _lateral_hits(a, b, c, o, d, tmax, zlo, zhi) -> np.ndarray:
    """Roots of the quadratic lateral surface with hit height in ``[zlo, zhi]``."""
    t1, t2 = _quadratic_roots(a, b, c)
    hit = np.zeros(o.shape[0], dtype=bool)
    for t in (t1, t2):
        z = o[:, 2] + t * d[:, 2]
        hit |= (~np.isnan(t)) & _in_range(t, tmax) & (z >= zlo - GEOM_EPS) & (z <= zhi + GEOM_EPS)
    return hit


def _disc_hit(o, d, tmax, z_plane, radius) -> np.ndarray:
    t = _safe_div(z_plane - o[:, 2], d[:, 2])
    x = o[:, 0] + t * d[:, 0]
    y = o[:, 1] + t * d[:, 1]
    return (~np.isnan(t)) & _in_range(t, tmax) & (x * x + y * y <= radius * radius * (1 + 1e-9) + GEOM_EPS)


def hit_cylinder(obj: dict, o: np.ndarray, d: np.ndarray, tmax) -> np.ndarray:
    """Finite cylinder: lateral ``x^2 + y^2 = r^2`` with ``0 <= z <= h`` plus both caps."""
    r = float(obj["radius"])
    h = float(obj["height"])
    a = d[:, 0] ** 2 + d[:, 1] ** 2
    b = 2.0 * (o[:, 0] * d[:, 0] + o[:, 1] * d[:, 1])
    c = o[:, 0] ** 2 + o[:, 1] ** 2 - r * r
    hit = _lateral_hits(a, b, c, o, d, tmax, 0.0, h)
    hit |= _disc_hit(o, d, tmax, 0.0, r)
    hit |= _disc_hit(o, d, tmax, h, r)
    return hit


def hit_cone(obj: dict, o: np.ndarray, d: np.ndarray, tmax) -> np.ndarray:
    """Finite cone: apex at local ``(0, 0, h)``, base disc radius ``r`` at ``z = 0``;
    lateral ``x^2 + y^2 = (r (h - z) / h)^2`` with ``0 <= z <= h``, plus the base disc."""
    r = float(obj["radius"])
    h = float(obj["height"])
    k = r / h
    hz = h - o[:, 2]
    a = d[:, 0] ** 2 + d[:, 1] ** 2 - k * k * d[:, 2] ** 2
    b = 2.0 * (o[:, 0] * d[:, 0] + o[:, 1] * d[:, 1] + k * k * hz * d[:, 2])
    c = o[:, 0] ** 2 + o[:, 1] ** 2 - k * k * hz * hz
    hit = _lateral_hits(a, b, c, o, d, tmax, 0.0, h)
    hit |= _disc_hit(o, d, tmax, 0.0, r)
    return hit


def hit_prism(obj: dict, o: np.ndarray, d: np.ndarray, tmax) -> np.ndarray:
    """Extruded simple polygon: vertical side quads plus the two caps (point in polygon)."""
    poly = np.asarray(obj["polygon"], dtype=np.float64).reshape(-1, 2)
    h = float(obj["height"])
    n = poly.shape[0]
    hit = np.zeros(o.shape[0], dtype=bool)
    for i in range(n):
        p0 = poly[i]
        p1 = poly[(i + 1) % n]
        e = p1 - p0
        ee = float(e @ e)
        if ee == 0.0:
            continue
        nrm = np.array([e[1], -e[0]])          # horizontal normal of the side plane
        denom = d[:, 0] * nrm[0] + d[:, 1] * nrm[1]
        num = (p0[0] - o[:, 0]) * nrm[0] + (p0[1] - o[:, 1]) * nrm[1]
        t = _safe_div(num, denom)
        x = o[:, 0] + t * d[:, 0]
        y = o[:, 1] + t * d[:, 1]
        z = o[:, 2] + t * d[:, 2]
        s = ((x - p0[0]) * e[0] + (y - p0[1]) * e[1]) / ee
        hit |= ((~np.isnan(t)) & _in_range(t, tmax)
                & (z >= -GEOM_EPS) & (z <= h + GEOM_EPS)
                & (s >= -GEOM_EPS) & (s <= 1.0 + GEOM_EPS))
    for z_plane in (0.0, h):
        t = _safe_div(z_plane - o[:, 2], d[:, 2])
        x = o[:, 0] + t * d[:, 0]
        y = o[:, 1] + t * d[:, 1]
        ok = (~np.isnan(t)) & _in_range(t, tmax)
        if np.any(ok):
            hit[ok] |= point_in_polygon(x[ok], y[ok], poly)
    return hit


HITTERS = {
    "box": hit_box,
    "sphere": hit_sphere,
    "cylinder": hit_cylinder,
    "cone": hit_cone,
    "prism": hit_prism,
}


# --------------------------------------------------------------------------- scene level
def rays_to_light(light: dict, origins: np.ndarray) -> tuple[np.ndarray, np.ndarray | float]:
    """Ray directions towards the light and the parameter upper bound (``1`` for a point
    light: the segment ends at the light; ``inf`` for a directional light)."""
    if light["type"] == "point":
        pos = np.asarray(light["position"], dtype=np.float64).reshape(3)
        return pos[None, :] - origins, 1.0
    if light["type"] == "directional":
        d = np.asarray(light["direction"], dtype=np.float64).reshape(3)
        return np.broadcast_to(d[None, :], origins.shape).copy(), np.inf
    raise ValueError("unknown light type %r" % (light["type"],))


def occluded(scene: dict, light: dict, origins: np.ndarray) -> np.ndarray:
    """Bool per origin: the segment/ray from the origin towards the light meets any object."""
    origins = np.asarray(origins, dtype=np.float64).reshape(-1, 3)
    dirs, tmax = rays_to_light(light, origins)
    hit = np.zeros(origins.shape[0], dtype=bool)
    for obj in scene["objects"]:
        o, d = to_local(obj, origins, dirs)
        hit |= HITTERS[obj["type"]](obj, o, d, tmax)
    return hit


def shadow_mask(scene: dict, light: dict, xs, ys) -> np.ndarray:
    """Shadow mask of the ground ``z = 0`` on the grid ``xs x ys``: ``mask[iy, ix]`` is True
    when the ground point ``(xs[ix], ys[iy], 0)`` is shadowed by some object."""
    xs = np.asarray(xs, dtype=np.float64).reshape(-1)
    ys = np.asarray(ys, dtype=np.float64).reshape(-1)
    X, Y = np.meshgrid(xs, ys)
    origins = np.stack([X.ravel(), Y.ravel(), np.zeros(X.size)], axis=1)
    return occluded(scene, light, origins).reshape(len(ys), len(xs))

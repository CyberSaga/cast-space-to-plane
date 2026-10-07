"""Sampled hidden-line removal, stage C (contract §5.1.6; spec §9 隱藏線消除, spec §11.1 取樣法先行).

Core module: numpy only, no file access, pure functions of the document, the camera-free stage A
(occluder geometry) and the stage-B camera / drawable records.  Entry point::

    classify_document(doc, A, B)     # called by pipeline.compose when doc["hidden_lines"] is true

It fills ``visibility`` / ``runs`` of every subject drawable (§5.1.6.1), ``polygon_edges`` of every
shadow record, conic ``runs`` / ``hidden_polylines`` and restricts conic ``arcs`` / ``ellipses`` /
``polylines`` to the visible runs.  Every list it assigns is a fresh object; nothing is written into
``A`` or ``B`` (dicts shared with them, e.g. the plate edges, are replaced by copies).

Pieces (all public, contract names first):

* constants ``HLR_SPACING_MM``, ``HLR_MIN_SAMPLES``, ``HLR_MAX_SAMPLES``, ``HLR_BISECTIONS``,
  ``HLR_RAY_EPS`` and :func:`hlr_sample_count` / :func:`hlr_tol_mm` (§5.1.6.4);
* occluders (§5.1.6.2): :func:`occluder` dispatches on the record kind -- box (slab test in the
  local frame), prism (side quads + caps with point-in-polygon, exact for concave prisms), cylinder /
  cone (lateral quadric with the height range + discs), sphere (quadric), every bounded receiver as
  an opaque convex plate, the unbounded ground as an opaque plane, and **any other kind** through
  the generic closed-mesh occluder (``rec["triangles"]`` on the welded vertices when present,
  ``obj["mesh"]`` faces otherwise; nothing raises).  :func:`first_hit` returns the smallest
  boundary-crossing parameter ``t > eps`` of rays ``O + t D`` (``inf`` when none);
* :func:`occluded` -- the predicate of §5.1.6.3: some occluder has ``first_hit(C, X - C) < 1 - eps``;
  :func:`image_bounds` -- the result-identical image-space cull (projected bounding rectangle and
  depth range from the occluder's hull points; ``None`` = no cull);
* :func:`classify_curve` -- the deterministic midpoint sampling + 6-step bisection rule of
  §5.1.6.4 for one parametrised curve (:func:`_classify_batch` is the same rule batched over many
  curves, which is what the document classification uses);
* :func:`drawn_segment_4d` / :func:`drawn_segments_4d` -- the 4-D endpoints of a drawn segment (near
  clip, then the rectangle functionals evaluated on ``P X``); :func:`clip_polygon_4d` -- the same for a
  shadow polygon, with edge provenance; :func:`runs_straight` / :func:`runs_conic` -- the document
  run records of §5.1.7.

Hull points used by :func:`image_bounds` (contract: "extremal points"): the vertices of boxes,
prisms, plates and generic meshes; the eight corners of the local bounding box of a cylinder / cone
(both rim squares) and of a sphere (the cube around it) -- point sets whose convex hull contains the
solid, so the cull never removes a possible hit.
"""

from __future__ import annotations

import math

import numpy as np

from .camera import clip_segments_near, nu, project, rect_functionals
from .conics import ellipse_arc_params, sample_arc, sample_count
from .homogeneous import clip_segments_halfspace, row_max_abs, ZERO_REL

#: Sampling constants of contract §5.1.6.4 (fixed by the contract; never adapted).
HLR_SPACING_MM = 1.0
HLR_MIN_SAMPLES = 8
HLR_MAX_SAMPLES = 4096
HLR_BISECTIONS = 6
#: Classification band of the ray parameter (relative to the ray length; contract §5.1.6.3, D26).
HLR_RAY_EPS = 1e-5

#: Inclusive band (relative to the solid's size) of the "on the finite surface" tests of the exact
#: occluders (height range, disc radius, side-quad extent): a ray through a rim or a side edge is
#: counted by both adjacent pieces instead of slipping between them.
_SURFACE_BAND = 1e-9

_INF = math.inf


def hlr_sample_count(length_mm) -> int:
    """``N = min(HLR_MAX_SAMPLES, max(HLR_MIN_SAMPLES, ceil(l / HLR_SPACING_MM - 1e-9)))`` (contract §5.1.6.4)."""
    return int(min(HLR_MAX_SAMPLES, max(HLR_MIN_SAMPLES, math.ceil(float(length_mm) / HLR_SPACING_MM - 1e-9))))


def _sample_counts(lengths) -> np.ndarray:
    """Vectorised :func:`hlr_sample_count`."""
    lengths = np.asarray(lengths, dtype=np.float64).reshape(-1)
    n = np.ceil(lengths / HLR_SPACING_MM - 1e-9)
    return np.minimum(HLR_MAX_SAMPLES, np.maximum(HLR_MIN_SAMPLES, n)).astype(np.int64)


def hlr_tol_mm(length_mm) -> float:
    """Stated boundary tolerance ``max(1/64, l/262144)`` mm of a drawable of image length ``l`` (§5.1.6.4)."""
    return max(1.0 / 64.0, float(length_mm) / 262144.0)


# ---------------------------------------------------------------------------
# occluders (contract §5.1.6.2)
# ---------------------------------------------------------------------------

def _box_corners(lo, hi) -> np.ndarray:
    return np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
                    dtype=np.float64)


def _local_to_world(points_local, R, origin) -> np.ndarray:
    return np.asarray(points_local, dtype=np.float64) @ np.asarray(R, dtype=np.float64).T + origin


def occluder(rec: dict) -> dict:
    """Occluder of a stage-A object record or a stage-A receiver record (contract §5.1.6.2).

    Returns ``{"kind", "id", "points" (hull points, world) | None, ...}`` with the kind's exact data:
    ``box`` / ``prism`` (local frame ``R``, ``origin`` and the shape), ``cylinder`` / ``cone`` / ``sphere``
    (the analytic frame), ``plate`` (``n``, ``d``, ``psi``), ``ground`` (the unbounded plane) or ``mesh``
    (generic closed mesh: ``triangles`` ``(k, 3, 3)`` world corners and / or ``faces`` polygon list).
    Never raises for a record of an unknown kind."""
    if "pi" in rec and "mesh" not in rec:                                  # a receiver record
        pi = np.asarray(rec["pi"], dtype=np.float64).reshape(4)
        if rec.get("bounded"):
            return {"kind": "plate", "id": rec["id"], "n": pi[:3].copy(), "d": float(pi[3]),
                    "psi": np.asarray(rec["psi"], dtype=np.float64).reshape(-1, 4),
                    "points": np.asarray(rec["bounds"], dtype=np.float64).reshape(-1, 3)}
        return {"kind": "ground", "id": rec["id"], "n": pi[:3].copy(), "d": float(pi[3]), "points": None}
    typ = rec.get("type")
    shape = rec.get("shape") or {}
    an = rec.get("analytic")
    if typ == "box" and "size" in shape and rec.get("frame") is not None:
        R, pos = rec["frame"]
        sx, sy, sz = (float(v) for v in shape["size"])
        lo, hi = np.array([-sx / 2.0, -sy / 2.0, 0.0]), np.array([sx / 2.0, sy / 2.0, sz])
        return {"kind": "box", "id": rec["id"], "R": np.asarray(R, dtype=np.float64),
                "origin": np.asarray(pos, dtype=np.float64), "lo": lo, "hi": hi,
                "band": _SURFACE_BAND * max(sx, sy, sz),
                "points": np.asarray(rec["mesh"]["vertices"], dtype=np.float64)}
    if typ == "prism" and "polygon" in shape and rec.get("frame") is not None:
        R, pos = rec["frame"]
        poly = np.asarray(shape["polygon"], dtype=np.float64).reshape(-1, 2)
        h = float(shape["height"])
        ext = float(max(h, float(np.max(np.abs(poly))) if poly.size else 0.0))
        return {"kind": "prism", "id": rec["id"], "R": np.asarray(R, dtype=np.float64),
                "origin": np.asarray(pos, dtype=np.float64), "polygon": poly, "height": h,
                "band": _SURFACE_BAND * max(ext, 1e-300),
                "points": np.asarray(rec["mesh"]["vertices"], dtype=np.float64)}
    if an is not None and an.get("kind") in ("cylinder", "cone", "sphere"):
        e1, e2, ax = (np.asarray(an[k], dtype=np.float64) for k in ("e1", "e2", "axis"))
        R = np.stack([e1, e2, ax], axis=1)                                 # columns: local axes
        base = np.asarray(an["base"], dtype=np.float64)
        r = float(an["radius"])
        if an["kind"] == "sphere":
            lo, hi = np.array([-r, -r, 0.0]), np.array([r, r, 2.0 * r])
            return {"kind": "sphere", "id": rec["id"], "centre": np.asarray(an["centre"], dtype=np.float64),
                    "radius": r, "points": _local_to_world(_box_corners(lo, hi), R, base)}
        h = float(an["height"])
        lo, hi = np.array([-r, -r, 0.0]), np.array([r, r, h])
        return {"kind": an["kind"], "id": rec["id"], "R": R, "origin": base, "radius": r, "height": h,
                "band": _SURFACE_BAND * max(r, h), "points": _local_to_world(_box_corners(lo, hi), R, base)}
    return _mesh_occluder(rec)


def _mesh_occluder(rec: dict) -> dict:
    """The generic closed-mesh occluder (contract §5.1.6.2, [decision, synthesis] C8): ``rec["triangles"]``
    on the welded vertices when the record carries that key (M5 mesh records), otherwise the faces of
    ``rec["mesh"]`` (contract §2.4 guarantees ``vertices`` / ``faces``)."""
    mesh = rec.get("mesh") or {}
    V = np.asarray(mesh.get("vertices", np.zeros((0, 3))), dtype=np.float64).reshape(-1, 3)
    tris, polys = [], []
    if rec.get("triangles") is not None:
        T = np.asarray(rec["triangles"], dtype=np.int64).reshape(-1, 3)
        tris = [V[T]] if T.shape[0] else []
    else:
        for f in mesh.get("faces", []) or []:
            f = [int(i) for i in f]
            if len(f) == 3:
                tris.append(V[f][None, :, :])
            elif len(f) > 3:
                polys.append(V[f])
    T3 = np.concatenate(tris, axis=0) if tris else np.zeros((0, 3, 3))
    ext = float(np.max(np.abs(V))) if V.size else 1.0
    return {"kind": "mesh", "id": rec.get("id"), "triangles": T3, "faces": polys,
            "band": _SURFACE_BAND * max(ext, 1.0), "points": V if V.shape[0] else None}


def _first_of_interval(t_in, t_out, eps):
    """First crossing ``> eps`` of a ray with a convex solid met on ``[t_in, t_out]`` (``inf`` when none)."""
    ok = t_in <= t_out
    t = np.where(t_in > eps, t_in, np.where(t_out > eps, t_out, _INF))
    return np.where(ok, t, _INF)


def _valid_min(cands: list, eps) -> np.ndarray:
    """Element-wise minimum of the candidate crossings ``> eps`` (nan / masked -> ``inf``)."""
    best = None
    for t in cands:
        t = np.where(np.isfinite(t) & (t > eps), t, _INF)
        best = t if best is None else np.minimum(best, t)
    return best


def _quadratic_roots(a, b, c):
    """Real roots ``(lo, hi)`` of ``a t^2 + b t + c`` per element (``nan`` where none; a linear equation
    gives its single root in both slots)."""
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        disc = b * b - 4.0 * a * c
        sq = np.sqrt(np.where(disc >= 0.0, disc, np.nan))
        q = -0.5 * (b + np.where(b >= 0.0, 1.0, -1.0) * sq)
        t1 = np.where(a != 0.0, q / np.where(a != 0.0, a, 1.0), np.nan)
        t2 = np.where(q != 0.0, c / np.where(q != 0.0, q, 1.0), np.nan)
        lin = a == 0.0
        tl = np.where(b != 0.0, -c / np.where(b != 0.0, b, 1.0), np.nan)
    t1 = np.where(lin, tl, t1)
    t2 = np.where(lin, tl, t2)
    return np.fmin(t1, t2), np.fmax(t1, t2)


def _to_local(occ, O, D):
    R = occ["R"]
    return (O - occ["origin"]) @ R, D @ R


def _first_box(occ, O, D, eps):
    o, d = _to_local(occ, O, D)
    lo, hi = occ["lo"][None, :], occ["hi"][None, :]
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / d
        t0 = (lo - o) * inv
        t1 = (hi - o) * inv
    par = d == 0.0
    inside = (o >= lo) & (o <= hi)
    tn = np.where(par, np.where(inside, -_INF, _INF), np.fmin(t0, t1))
    tf = np.where(par, np.where(inside, _INF, -_INF), np.fmax(t0, t1))
    return _first_of_interval(np.max(tn, axis=1), np.min(tf, axis=1), eps)


def _first_sphere(occ, O, D, eps):
    oc = O - occ["centre"][None, :]
    a = np.einsum("ij,ij->i", D, D)
    b = 2.0 * np.einsum("ij,ij->i", D, oc)
    c = np.einsum("ij,ij->i", oc, oc) - occ["radius"] ** 2
    t1, t2 = _quadratic_roots(a, b, c)
    ok = ~np.isnan(t1)
    return np.where(ok, _first_of_interval(np.where(ok, t1, 0.0), np.where(ok, t2, -1.0), eps), _INF)


def _disc(o, d, z_plane, radius, band):
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(d[:, 2] != 0.0, (z_plane - o[:, 2]) / np.where(d[:, 2] != 0.0, d[:, 2], 1.0), np.nan)
    x = o[:, 0] + t * d[:, 0]
    y = o[:, 1] + t * d[:, 1]
    return np.where(x * x + y * y <= (radius + band) ** 2, t, np.nan)


def _first_cylinder(occ, O, D, eps):
    o, d = _to_local(occ, O, D)
    r, h, band = occ["radius"], occ["height"], occ["band"]
    a = d[:, 0] ** 2 + d[:, 1] ** 2
    b = 2.0 * (o[:, 0] * d[:, 0] + o[:, 1] * d[:, 1])
    c = o[:, 0] ** 2 + o[:, 1] ** 2 - r * r
    cands = []
    for t in _quadratic_roots(a, b, c):
        z = o[:, 2] + t * d[:, 2]
        cands.append(np.where((z >= -band) & (z <= h + band), t, np.nan))
    cands.append(_disc(o, d, 0.0, r, band))
    cands.append(_disc(o, d, h, r, band))
    return _valid_min(cands, eps)


def _first_cone(occ, O, D, eps):
    o, d = _to_local(occ, O, D)
    r, h, band = occ["radius"], occ["height"], occ["band"]
    k = r / h
    hz = h - o[:, 2]
    a = d[:, 0] ** 2 + d[:, 1] ** 2 - k * k * d[:, 2] ** 2
    b = 2.0 * (o[:, 0] * d[:, 0] + o[:, 1] * d[:, 1] + k * k * hz * d[:, 2])
    c = o[:, 0] ** 2 + o[:, 1] ** 2 - k * k * hz * hz
    cands = []
    for t in _quadratic_roots(a, b, c):
        z = o[:, 2] + t * d[:, 2]
        cands.append(np.where((z >= -band) & (z <= h + band), t, np.nan))
    cands.append(_disc(o, d, 0.0, r, band))
    return _valid_min(cands, eps)


def _even_odd(px, py, poly) -> np.ndarray:
    """Crossing-number point-in-polygon test of points ``(px, py)`` (``(n,)``) against ``poly`` ``(k, 2)``."""
    x0, y0 = poly[:, 0][None, :], poly[:, 1][None, :]
    nxt = np.roll(np.arange(poly.shape[0]), -1)
    x1, y1 = poly[nxt, 0][None, :], poly[nxt, 1][None, :]
    X, Y = px[:, None], py[:, None]
    cond = (y0 > Y) != (y1 > Y)
    with np.errstate(divide="ignore", invalid="ignore"):
        xint = x0 + (Y - y0) * (x1 - x0) / np.where(y1 != y0, y1 - y0, 1.0)
    return (np.sum(cond & (X < xint), axis=1) % 2) == 1


def _first_prism(occ, O, D, eps):
    o, d = _to_local(occ, O, D)
    poly, h, band = occ["polygon"], occ["height"], occ["band"]
    k = poly.shape[0]
    nxt = np.roll(np.arange(k), -1)
    p0, e = poly, poly[nxt] - poly
    ee = np.einsum("ij,ij->i", e, e)
    nrm = np.stack([e[:, 1], -e[:, 0]], axis=1)                      # horizontal normal of each side plane
    denom = d[:, :2] @ nrm.T                                         # (n, k)
    num = np.einsum("ij,ij->i", p0, nrm)[None, :] - o[:, :2] @ nrm.T
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(denom != 0.0, num / np.where(denom != 0.0, denom, 1.0), np.nan)
    x = o[:, 0:1] + t * d[:, 0:1]
    y = o[:, 1:2] + t * d[:, 1:2]
    z = o[:, 2:3] + t * d[:, 2:3]
    s = ((x - p0[None, :, 0]) * e[None, :, 0] + (y - p0[None, :, 1]) * e[None, :, 1]) / np.where(ee > 0, ee, 1.0)
    rel = band / np.sqrt(np.where(ee > 0, ee, 1.0))
    ok = (ee[None, :] > 0) & (z >= -band) & (z <= h + band) & (s >= -rel[None, :]) & (s <= 1.0 + rel[None, :])
    side = np.where(ok, t, np.nan)
    side = np.where(np.isfinite(side) & (side > eps), side, _INF)
    best = np.min(side, axis=1) if k else np.full(o.shape[0], _INF)
    for z_plane in (0.0, h):
        with np.errstate(divide="ignore", invalid="ignore"):
            tc = np.where(d[:, 2] != 0.0, (z_plane - o[:, 2]) / np.where(d[:, 2] != 0.0, d[:, 2], 1.0), np.nan)
        cand = np.isfinite(tc) & (tc > eps) & (tc < best)
        if np.any(cand):
            idx = np.nonzero(cand)[0]
            inside = _even_odd(o[idx, 0] + tc[idx] * d[idx, 0], o[idx, 1] + tc[idx] * d[idx, 1], poly)
            best[idx[inside]] = tc[idx[inside]]
    return best


def _first_plane(n, dd, O, D, eps):
    denom = D @ n
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(denom != 0.0, -(O @ n + dd) / np.where(denom != 0.0, denom, 1.0), np.nan)
    return t


def _first_plate(occ, O, D, eps):
    t = _first_plane(occ["n"], occ["d"], O, D, eps)
    X = O + np.where(np.isfinite(t), t, 0.0)[:, None] * D
    f = X @ occ["psi"][:, :3].T + occ["psi"][None, :, 3]
    inside = np.all(f >= 0.0, axis=1)
    return np.where(np.isfinite(t) & (t > eps) & inside, t, _INF)


def _first_ground(occ, O, D, eps):
    t = _first_plane(occ["n"], occ["d"], O, D, eps)
    return np.where(np.isfinite(t) & (t > eps), t, _INF)


#: Rays x triangles per Möller–Trumbore block of the generic mesh occluder.
_MT_BLOCK = 1 << 21


def _first_mesh(occ, O, D, eps):
    n = O.shape[0]
    best = np.full(n, _INF)
    T = occ["triangles"]
    band = 1e-12
    if T.shape[0]:
        v0, e1, e2 = T[:, 0], T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
        step = max(1, _MT_BLOCK // max(1, T.shape[0]))
        for a in range(0, n, step):
            o, d = O[a:a + step, None, :], D[a:a + step, None, :]
            p = np.cross(d, e2[None, :, :])
            det = np.einsum("ijk,jk->ij", p, e1)
            ok = det != 0.0
            inv = 1.0 / np.where(ok, det, 1.0)
            s = o - v0[None, :, :]
            u = np.einsum("ijk,ijk->ij", s, p) * inv
            q = np.cross(s, e1[None, :, :])
            v = np.einsum("ijk,ijk->ij", d, q) * inv
            t = np.einsum("ijk,jk->ij", q, e2) * inv
            hit = ok & (u >= -band) & (v >= -band) & (u + v <= 1.0 + band) & (t > eps)
            best[a:a + step] = np.minimum(best[a:a + step], np.min(np.where(hit, t, _INF), axis=1))
    for F in occ["faces"]:
        nrm = np.cross(F[1] - F[0], F[2] - F[0])
        for k in range(3, F.shape[0]):                                # Newell-like accumulation of the fan
            nrm = nrm + np.cross(F[k - 1] - F[0], F[k] - F[0])
        if not np.any(nrm):
            continue
        t = _first_plane(nrm, -float(nrm @ F[0]), O, D, eps)
        cand = np.isfinite(t) & (t > eps) & (t < best)
        if not np.any(cand):
            continue
        idx = np.nonzero(cand)[0]
        X = O[idx] + t[idx, None] * D[idx]
        drop = int(np.argmax(np.abs(nrm)))
        keep = [i for i in range(3) if i != drop]
        inside = _even_odd(X[:, keep[0]], X[:, keep[1]], F[:, keep])
        best[idx[inside]] = t[idx[inside]]
    return best


_FIRST_HIT = {
    "box": _first_box, "prism": _first_prism, "cylinder": _first_cylinder, "cone": _first_cone,
    "sphere": _first_sphere, "plate": _first_plate, "ground": _first_ground, "mesh": _first_mesh,
}


def first_hit(occ: dict, O, D, eps: float = HLR_RAY_EPS) -> np.ndarray:
    """Smallest boundary-crossing parameter ``t > eps`` of the rays ``O + t D`` with the occluder
    (``inf`` when none; contract §5.1.6.2).  ``O`` is ``(n, 3)`` or one point ``(3,)``, ``D`` ``(n, 3)``."""
    D = np.asarray(D, dtype=np.float64).reshape(-1, 3)
    O = np.broadcast_to(np.asarray(O, dtype=np.float64).reshape(-1, 3), D.shape)
    if D.shape[0] == 0:
        return np.zeros(0)
    return _FIRST_HIT[occ["kind"]](occ, np.ascontiguousarray(O), D, float(eps))


def image_bounds(occ: dict, cam: dict):
    """Image-space cull data of an occluder (contract §5.1.6.4): ``(u_min, u_max, v_min, v_max,
    depth_min)`` of its hull points, or ``None`` ("no cull") for the unbounded ground and whenever some
    hull point has ``nu <= 0``.  Every point of the solid lies in the hull, so a ray ``C -> X`` whose
    image point is outside the rectangle, or whose ``X`` is not deeper than ``depth_min``, cannot meet the
    occluder before ``X``."""
    pts = occ.get("points")
    if pts is None or len(pts) == 0:
        return None
    X4 = np.concatenate([pts, np.ones((pts.shape[0], 1))], axis=1)
    if bool(np.any(nu(cam, X4) <= 0.0)):
        return None
    x = project(cam, X4)
    u, v = x[:, 0] / x[:, 2], x[:, 1] / x[:, 2]
    return (float(u.min()), float(u.max()), float(v.min()), float(v.max()), float(x[:, 2].min()))


def occluded(occs: list, C, X, eps: float = HLR_RAY_EPS, cam: dict | None = None, bounds=None) -> np.ndarray:
    """Bool per world point ``X`` ``(n, 3)``: hidden from the camera centre ``C`` (contract §5.1.6.3), i.e.
    some occluder has ``first_hit(occ, C, X - C, eps) < 1 - eps``.  ``bounds`` (one :func:`image_bounds`
    result per occluder, with ``cam``) enables the result-identical cull; points already found hidden
    are not tested against the remaining occluders (``any`` is order independent)."""
    X = np.asarray(X, dtype=np.float64).reshape(-1, 3)
    C = np.asarray(C, dtype=np.float64).reshape(3)
    n = X.shape[0]
    hidden = np.zeros(n, dtype=bool)
    if n == 0 or not occs:
        return hidden
    D = X - C[None, :]
    img = None
    if bounds is not None and cam is not None and any(b is not None for b in bounds):
        x = project(cam, np.concatenate([X, np.ones((n, 1))], axis=1))
        with np.errstate(divide="ignore", invalid="ignore"):
            img = (x[:, 0] / x[:, 2], x[:, 1] / x[:, 2], x[:, 2])
    limit = 1.0 - eps
    for k, occ in enumerate(occs):
        sel = ~hidden
        b = bounds[k] if (img is not None and bounds is not None) else None
        if b is not None:
            u, v, depth = img
            u0, u1, v0, v1, dmin = b
            mu = 1e-6 + 1e-9 * max(abs(u0), abs(u1))
            mv = 1e-6 + 1e-9 * max(abs(v0), abs(v1))
            # cull only where the ray provably misses: image point outside the hull's rectangle, or the
            # whole hull at least as deep as X (every hit then has t >= 1); undecidable rows are tested
            cull = (depth > 0.0) & ((u < u0 - mu) | (u > u1 + mu) | (v < v0 - mv) | (v > v1 + mv)
                                    | (dmin >= depth * (1.0 + 1e-9)))
            sel &= ~cull
        idx = np.nonzero(sel)[0]
        if idx.shape[0] == 0:
            continue
        t = first_hit(occ, C, D[idx], eps)
        hidden[idx] |= t < limit
    return hidden


def scene_occluders(A: dict) -> list:
    """All occluders of a stage A: every object, every bounded receiver (plate) and the unbounded ground
    (``receivers[0]`` without bounds; no ground receiver -> no ground occluder)."""
    occs = [occluder(o) for o in A.get("objects", [])]
    for rcv in A.get("receivers", []):
        if rcv.get("bounded") or rcv.get("index", 0) == 0:
            occs.append(occluder(rcv))
    return occs


# ---------------------------------------------------------------------------
# sampling and bisection (contract §5.1.6.4)
# ---------------------------------------------------------------------------

def classify_curve(visible_at, p0: float, p1: float, length_mm: float):
    """The deterministic rule of contract §5.1.6.4 for one curve parametrised on ``[p0, p1]`` with image
    length ``length_mm``: ``N = hlr_sample_count(length_mm)`` midpoint samples
    ``p_i = p0 + (p1 - p0)(i + 1/2)/N``; ``visible_at(p array) -> bool array``.  Returns ``(visibility,
    runs)`` with ``runs = [(pa, pb, visible), ...]`` contiguous from ``p0`` to ``p1`` (empty unless
    ``"partial"``).  Each state change between neighbouring samples is bisected exactly
    ``HLR_BISECTIONS`` times (keep ``[lo, m]`` iff ``v(m) != v(lo)``); the boundary is the midpoint of the
    final bracket."""
    out = _classify_batch(np.array([float(p0)]), np.array([float(p1)]), np.array([float(length_mm)]),
                          lambda sub, p: np.asarray(visible_at(p), dtype=bool))
    return out[0]


def _classify_batch(p0, p1, lengths, visible_at):
    """:func:`classify_curve` for ``S`` curves at once: ``visible_at(subject index array, p array) -> bool``.
    Returns one ``(visibility, runs)`` per curve."""
    p0 = np.asarray(p0, dtype=np.float64).reshape(-1)
    p1 = np.asarray(p1, dtype=np.float64).reshape(-1)
    S = p0.shape[0]
    if S == 0:
        return []
    N = _sample_counts(lengths)
    offs = np.concatenate([[0], np.cumsum(N)])
    sub = np.repeat(np.arange(S), N)
    i = np.arange(int(offs[-1])) - offs[:-1][sub]
    p = p0[sub] + (p1[sub] - p0[sub]) * (i + 0.5) / N[sub]
    v = np.asarray(visible_at(sub, p), dtype=bool)
    same = sub[:-1] == sub[1:]
    trans = np.nonzero(same & (v[:-1] != v[1:]))[0]
    lo, hi = p[trans], p[trans + 1]
    v_lo = v[trans]
    tsub = sub[trans]
    for _step in range(HLR_BISECTIONS):
        if trans.shape[0] == 0:
            break
        m = (lo + hi) / 2.0
        vm = np.asarray(visible_at(tsub, m), dtype=bool)
        left = vm != v_lo                       # keep [lo, m] iff v(m) != v(lo), else [m, hi]
        hi = np.where(left, m, hi)
        lo = np.where(left, lo, m)
    boundary = (lo + hi) / 2.0
    first_state = v[offs[:-1]]
    last_state = v[offs[1:] - 1]
    tb = np.searchsorted(tsub, np.arange(S + 1)) if trans.shape[0] else np.zeros(S + 1, dtype=np.int64)
    out = []
    bl, fl, ll = boundary.tolist(), first_state.tolist(), last_state.tolist()
    vlo = v_lo.tolist()
    p0l, p1l = p0.tolist(), p1.tolist()
    for s in range(S):
        a, b = int(tb[s]), int(tb[s + 1])
        if a == b:
            out.append(("visible" if fl[s] else "hidden", []))
            continue
        runs, start, state = [], p0l[s], fl[s]
        for k in range(a, b):
            runs.append((start, bl[k], bool(vlo[k])))
            start, state = bl[k], not vlo[k]
        runs.append((start, p1l[s], bool(ll[s])))
        out.append(("partial", runs))
    return out


# ---------------------------------------------------------------------------
# drawn 4-D geometry (contract §5.1.6.4)
# ---------------------------------------------------------------------------

def drawn_segments_4d(cam: dict, A4, B4):
    """4-D endpoints of drawn segments ``(m, 4)``: the near clip of contract §2.2 step 1 (the stage-B
    call), then the four extended-canvas functionals **evaluated on** ``P X`` (``rect_row . (P X)``) with the
    4-D interpolation.  Returns ``(A', B', keep)``; ``P A'``, ``P B'`` equal the drawn endpoints up to one
    rounding of ``P X``.  Endpoints may be directions (``w = 0``)."""
    A4 = np.asarray(A4, dtype=np.float64).reshape(-1, 4)
    B4 = np.asarray(B4, dtype=np.float64).reshape(-1, 4)
    if A4.shape[0] == 0:
        return A4.copy(), B4.copy(), np.zeros(0, dtype=bool)
    A, B, keep = clip_segments_near(cam, A4, B4)
    # the projected 3-vectors are carried and interpolated exactly as clip_segments_rect_h does on the
    # stage-B call (same floats, hence the same in/out decisions and the same interpolation parameters);
    # the 4-D endpoints follow with the same (fa, fb) and the keep mask is the 2-D one
    xa, xb = project(cam, A), project(cam, B)
    for row in rect_functionals(cam["rect"]):
        fa, fb = xa @ row, xb @ row
        xa, xb, k = clip_segments_halfspace(xa, xb, fa, fb)
        A, B, _k4 = clip_segments_halfspace(A, B, fa, fb)
        keep = keep & k
    return A, B, keep


def drawn_segment_4d(cam: dict, A4, B4):
    """One segment of :func:`drawn_segments_4d`: ``(A', B')`` or ``None`` when nothing is drawn."""
    A, B, keep = drawn_segments_4d(cam, np.asarray(A4, dtype=np.float64)[None, :],
                                   np.asarray(B4, dtype=np.float64)[None, :])
    return (A[0], B[0]) if bool(keep[0]) else None


def _clip_step(pts: np.ndarray, ids: list, vals: np.ndarray, extra: np.ndarray | None = None):
    """One Sutherland–Hodgman step of :func:`homogeneous.clip_polygon_halfspace` (same formulas, same
    zero-row filter) on ``pts`` carrying the outgoing-edge provenance: a kept vertex keeps its id, a
    crossing-out vertex starts a clip edge (``None``), a crossing-in vertex continues the original edge.
    ``extra`` (same row count, e.g. the 4-D points of the projected 3-vectors ``pts``) is interpolated with
    the same ``(fa, fb)`` and filtered with the mask of ``pts``.  Returns ``(pts, ids)`` or
    ``(pts, ids, extra)``."""
    n = pts.shape[0]
    if n == 0 or np.all(vals >= 0.0):
        res = (pts.copy(), list(ids))
        return res if extra is None else res + (extra.copy(),)
    if np.all(vals < 0.0):
        res = (np.zeros((0, pts.shape[1])), [])
        return res if extra is None else res + (np.zeros((0, extra.shape[1])),)
    out, oid, ext = [], [], []
    for i in range(n):
        j = (i + 1) % n
        a, b = pts[i], pts[j]
        fa, fb = vals[i], vals[j]
        a_in, b_in = fa >= 0.0, fb >= 0.0
        if a_in:
            out.append(a)
            oid.append(ids[i])
            if extra is not None:
                ext.append(extra[i])
        if a_in != b_in:
            out.append((fa * b - fb * a) / (fa - fb))
            oid.append(None if a_in else ids[i])
            if extra is not None:
                ext.append((fa * extra[j] - fb * extra[i]) / (fa - fb))
    out = np.array(out, dtype=np.float64).reshape(-1, pts.shape[1])
    keep = row_max_abs(out) > ZERO_REL * float(np.max(np.abs(pts)))
    res = (out[keep], [x for x, k in zip(oid, keep.tolist()) if k])
    if extra is None:
        return res
    return res + (np.array(ext, dtype=np.float64).reshape(-1, extra.shape[1])[keep],)


def clip_polygon_4d(cam: dict, V4):
    """The 4-D path of a shadow polygon through the drawing pipeline (contract §5.1.6.4): near clip, then
    the four rectangle functionals evaluated on ``P X``, each a Sutherland–Hodgman step with provenance.
    Returns ``(points (k, 4), ids)`` where ``ids[j]`` is the index of the original polygon edge on which the
    drawn edge ``j -> j + 1`` lies, or ``None`` for an edge created by a clip; empty when fewer than three
    vertices survive any step (as the drawn polygon)."""
    pts = np.asarray(V4, dtype=np.float64).reshape(-1, 4)
    ids = list(range(pts.shape[0]))
    if pts.shape[0] < 3:
        return np.zeros((0, 4)), []
    pts, ids = _clip_step(pts, ids, nu(cam, pts))
    if pts.shape[0] < 3:
        return np.zeros((0, 4)), []
    # the rectangle steps run on the projected 3-vectors exactly as project_polygons does (every in/out
    # decision and the zero-row filter are bit-identical to the drawn polygon's, so the vertex counts
    # always agree); the 4-D points are interpolated with the same (fa, fb)
    X = project(cam, pts)
    for row in rect_functionals(cam["rect"]):
        X, ids, pts = _clip_step(X, ids, X @ row, pts)
        if pts.shape[0] < 3:
            return np.zeros((0, 4)), []
    return pts, ids


# ---------------------------------------------------------------------------
# run records (contract §5.1.7)
# ---------------------------------------------------------------------------

def _t_of_s(s, a3: float, b3: float):
    """4-D segment parameter of the image fraction ``s``: ``t = s a3 / ((1 - s) b3 + s a3)``."""
    return s * a3 / ((1.0 - s) * b3 + s * a3)


def runs_straight(result, a3: float, b3: float, length_mm: float) -> tuple[str, list]:
    """Document form of a straight drawable's classification ``(visibility, [(s0, s1, visible)])``:
    ``(visibility, [{s, t, mm, visible}, ...])`` (``mm`` measured from the drawn segment's start)."""
    visibility, runs = result
    out = []
    for s0, s1, vis in runs:
        t0 = 0.0 if s0 == 0.0 else 1.0 if s0 == 1.0 else _t_of_s(s0, a3, b3)
        t1 = 0.0 if s1 == 0.0 else 1.0 if s1 == 1.0 else _t_of_s(s1, a3, b3)
        out.append({"s": [s0 + 0.0, s1 + 0.0], "t": [float(t0) + 0.0, float(t1) + 0.0],
                    "mm": [s0 * length_mm + 0.0, (length_mm if s1 == 1.0 else s1 * length_mm) + 0.0],
                    "visible": bool(vis)})
    return visibility, out


def _theta_of_m(m, cum: np.ndarray, th: np.ndarray):
    """Piecewise-linear map polyline length -> circle parameter (contract §5.1.6.4)."""
    m = np.asarray(m, dtype=np.float64)
    n = cum.shape[0] - 1
    j = np.clip(np.searchsorted(cum, m, side="right") - 1, 0, n - 1)
    seg = cum[j + 1] - cum[j]
    frac = np.where(seg > 0.0, (m - cum[j]) / np.where(seg > 0.0, seg, 1.0), 0.0)
    return th[j] + frac * (th[j + 1] - th[j])


def runs_conic(interval: int, runs: list, cum: np.ndarray, th: np.ndarray, lo=None, hi=None) -> list:
    """Document run records ``{interval, theta, mm, visible}`` of one visible interval's classification
    (``runs`` = ``[(m0, m1, visible)]``; the interval's own endpoints map to its exact ``theta`` ends ``lo`` /
    ``hi``, default the first / last polyline node)."""
    length = float(cum[-1])
    lo = float(th[0]) if lo is None else float(lo)
    hi = float(th[-1]) if hi is None else float(hi)
    out = []
    for m0, m1, vis in runs:
        a = lo if m0 == 0.0 else hi if m0 == length else float(_theta_of_m(m0, cum, th))
        b = lo if m1 == 0.0 else hi if m1 == length else float(_theta_of_m(m1, cum, th))
        out.append({"interval": int(interval), "theta": [a + 0.0, b + 0.0], "mm": [m0 + 0.0, m1 + 0.0],
                    "visible": bool(vis)})
    return out


def _cut_polyline(uv: np.ndarray, cum: np.ndarray, m0: float, m1: float) -> list:
    """The piece ``[m0, m1]`` of a polyline (cut at the boundary points, never resampled)."""
    def at(m):
        if m <= cum[0]:
            return uv[0]
        if m >= cum[-1]:
            return uv[-1]
        j = int(np.clip(np.searchsorted(cum, m, side="right") - 1, 0, cum.shape[0] - 2))
        seg = cum[j + 1] - cum[j]
        f = (m - cum[j]) / seg if seg > 0.0 else 0.0
        return uv[j] + f * (uv[j + 1] - uv[j])
    inner = np.nonzero((cum > m0) & (cum < m1))[0]
    pts = np.vstack([at(m0)[None, :], uv[inner], at(m1)[None, :]])
    return (pts + 0.0).tolist()


# ---------------------------------------------------------------------------
# the document (contract §5.1.6.5)
# ---------------------------------------------------------------------------

class _Subjects:
    """Accumulator of the subject drawables of one document: straight ones (4-D drawn endpoints) and conic
    intervals (polyline tables), classified together by :func:`_classify_batch`."""

    def __init__(self):
        self.lines = []          # (A4, B4, a3, b3, length, sink)
        self.conics = []         # (TE, rho, cum, th, length, sink)

    def add_line(self, A4, B4, a3, b3, length, sink):
        self.lines.append((A4, B4, a3, b3, length, sink))

    def add_conic(self, TE, rho, cum, th, sink):
        self.conics.append((np.asarray(TE, dtype=np.float64), float(rho), cum, th, float(cum[-1]), sink))

    def classify(self, occs, C, cam, bounds):
        nl, nc = len(self.lines), len(self.conics)
        if nl + nc == 0:
            return
        A4 = np.array([x[0] for x in self.lines], dtype=np.float64).reshape(-1, 4)
        B4 = np.array([x[1] for x in self.lines], dtype=np.float64).reshape(-1, 4)
        a3 = np.array([x[2] for x in self.lines], dtype=np.float64)
        b3 = np.array([x[3] for x in self.lines], dtype=np.float64)
        p1 = np.concatenate([np.ones(nl), np.array([x[4] for x in self.conics], dtype=np.float64)])
        lengths = np.concatenate([np.array([x[4] for x in self.lines], dtype=np.float64), p1[nl:]])
        conics = self.conics

        def world(sub, p):
            X = np.zeros((sub.shape[0], 3))
            is_line = sub < nl
            if np.any(is_line):
                k = sub[is_line]
                s = p[is_line]
                t = _t_of_s(s, a3[k], b3[k])
                X4 = (1.0 - t)[:, None] * A4[k] + t[:, None] * B4[k]
                X[is_line] = X4[:, :3] / X4[:, 3:4]
            if np.any(~is_line):
                rows = np.nonzero(~is_line)[0]
                ks = sub[rows] - nl
                order = np.argsort(ks, kind="stable")
                rows, ks = rows[order], ks[order]
                cuts = np.nonzero(np.diff(ks))[0] + 1
                for grp in np.split(np.arange(rows.shape[0]), cuts):
                    TE, rho, cum, th, _len, _sink = conics[int(ks[grp[0]])]
                    theta = _theta_of_m(p[rows[grp]], cum, th)
                    local = np.stack([rho * np.cos(theta), rho * np.sin(theta), np.ones_like(theta)], axis=-1)
                    X4 = local @ TE.T
                    X[rows[grp]] = X4[:, :3] / X4[:, 3:4]
            return X

        def visible_at(sub, p):
            return ~occluded(occs, C, world(sub, p), HLR_RAY_EPS, cam, bounds)

        results = _classify_batch(np.zeros(nl + nc), p1, lengths, visible_at)
        for k, res in enumerate(results[:nl]):
            _A, _B, a, b, length, sink = self.lines[k]
            sink(runs_straight(res, a, b, length))
        for k, res in enumerate(results[nl:]):
            sink = self.conics[k][5]
            sink(res)


def _line_subject(subjects: _Subjects, cam: dict, A4, B4, seg, sink) -> None:
    """Register a straight drawable (4-D drawn endpoints ``A4``, ``B4``; drawn segment ``seg`` in mm)."""
    xa, xb = project(cam, A4), project(cam, B4)
    du = float(seg[1][0]) - float(seg[0][0])
    dv = float(seg[1][1]) - float(seg[0][1])
    length = math.sqrt(du * du + dv * dv)
    subjects.add_line(A4, B4, float(xa[2]), float(xb[2]), length, sink)


def _world4(points: dict, name: str):
    w = points[name]["world"]
    return np.array([w[0], w[1], w[2], 1.0], dtype=np.float64)


class _ConicResult:
    """Collects the per-interval classifications of one conic entry and writes the entry (§5.1.7)."""

    def __init__(self, entry: dict, a: dict, tables: list):
        self.entry, self.a, self.tables = entry, a, tables
        self.results = [None] * len(tables)

    def sink(self, k):
        def put(res):
            self.results[k] = res
            if all(r is not None for r in self.results):
                self.write()
        return put

    def write(self):
        entry, a = self.entry, self.a
        states = []
        for vis, runs in self.results:
            if vis == "partial":
                states.extend(r[2] for r in runs)
            else:
                states.append(vis == "visible")
        if all(states):
            entry["visibility"], entry["runs"], entry["hidden_polylines"] = "visible", [], []
            return
        H, rho = a["H"], a["rho"]
        healthy = a["kind"] == "ellipse" and not a["sampled"]
        visibility = "hidden" if not any(states) else "partial"
        runs, hidden_pl, polylines, arcs = [], [], [], []
        for k, ((vis, rr), (uv, cum, th, lo, hi)) in enumerate(zip(self.results, self.tables)):
            length = float(cum[-1])
            pieces = rr if vis == "partial" else [(0.0, length, vis == "visible")]
            if visibility == "partial":
                runs.extend(runs_conic(k, pieces, cum, th, lo, hi))
            for m0, m1, v in pieces:
                if not v:
                    hidden_pl.append(_cut_polyline(uv, cum, m0, m1))
                    continue
                ta = lo if m0 == 0.0 else float(_theta_of_m(m0, cum, th))
                tb = hi if m1 == length else float(_theta_of_m(m1, cum, th))
                p = ellipse_arc_params(H, rho, ta, tb) if healthy else None
                if p is not None:
                    arcs.append({"start": (p["start"] + 0.0).tolist(), "end": (p["end"] + 0.0).tolist(),
                                 "rx": p["axes"][0] + 0.0, "ry": p["axes"][1] + 0.0,
                                 "rotation_deg": math.degrees(p["rotation"]) + 0.0,
                                 "large_arc": p["large_arc"], "sweep": p["sweep"], "theta": [ta + 0.0, tb + 0.0]})
                else:
                    polylines.append(_cut_polyline(uv, cum, m0, m1))
        entry["visibility"] = visibility
        entry["runs"] = runs
        entry["hidden_polylines"] = hidden_pl
        entry["polylines"] = polylines
        entry["arcs"] = arcs
        entry["ellipses"] = []


def _conic_subject(subjects: _Subjects, entry: dict, a: dict) -> None:
    """Register every visible interval of a conic entry (its §2.6 polyline is the parametrisation)."""
    visible = a.get("visible") or []
    if not visible or "TE" not in a:
        return
    H, rho = a["H"], a["rho"]
    tables = []
    for lo, hi in visible:
        n = sample_count(lo, hi)
        pts = sample_arc(H, rho, lo, hi, n)                               # the _arc_drawables samples
        uv = pts[:, :2] / pts[:, 2:3]
        d = np.diff(uv, axis=0)
        cum = np.concatenate([[0.0], np.cumsum(np.sqrt(d[:, 0] * d[:, 0] + d[:, 1] * d[:, 1]))])
        th = lo + (hi - lo) * np.arange(n + 1, dtype=np.float64) / max(1, int(n))
        tables.append((uv + 0.0, cum, th, float(lo), float(hi)))
    res = _ConicResult(entry, a, tables)
    for k, (_uv, cum, th, _lo, _hi) in enumerate(tables):
        subjects.add_conic(a["TE"], rho, cum, th, res.sink(k))


def _set(target: dict):
    def put(res):
        target["visibility"], target["runs"] = res
    return put


def _curved_pairs(doc: dict, B: dict):
    """Pair the document's curved drawables with their stage-B records (same order as ``compose``):
    yields ``("generator", doc_entry, gen_edge)``, ``("conic", doc_entry, arc_record)`` and
    ``("terminator_segment", doc_entry, item)``."""
    curved = [rec for rec in B.get("objects", []) if rec.get("analytic")]
    outlines = doc.get("outlines", [])
    for rec, out in zip(curved, outlines):
        for g_doc, g_b in zip(out.get("generators", []), rec.get("gen_edges", [])):
            yield "generator", g_doc, g_b
        for c_doc, a in zip(out.get("conics", []), rec.get("outline_arcs", [])):
            yield "conic", c_doc, a
    terms = {}
    for entry in doc.get("form_shadow", []):
        if entry.get("terminator") and entry["object"] not in terms:
            terms[entry["object"]] = entry
    for rec in curved:
        items = [it for its in rec.get("terminator", {}).values() for it in its]
        entry = terms.get(rec["id"])
        if entry is None:
            continue
        for t_doc, it in zip(entry["terminator"], items):
            yield ("terminator_segment" if "segment" in it else "conic"), t_doc, it
    by_id = {rec["id"]: rec for rec in curved}
    for sh in doc.get("shadows", []):
        rec = by_id.get(sh["object"])
        if rec is None or not sh.get("conics"):
            continue
        for c_doc, a in zip(sh["conics"], rec.get("shadow_arcs", {}).get((sh["light"], sh["receiver"]), [])):
            yield "conic", c_doc, a


def classify_document(doc: dict, A: dict, B: dict, cull: bool = True) -> dict:
    """Sampled hidden-line removal of a composed document (contract §5.1.6.5).  ``A`` is the camera-free
    stage A (occluders), ``B`` the stage B it was composed from (``B["camera"]``, the curved drawable
    records).  Fills ``visibility`` / ``runs`` of ``edges[]``, ``outlines[].generators[]`` and
    ``form_shadow[].terminator[]`` segment entries, conic ``visibility`` / ``runs`` / ``hidden_polylines``
    (drawables restricted to the visible runs) and ``shadows[].polygon_edges``.  ``cull`` toggles the
    result-identical image-space cull (a test compares both).  Returns ``doc``."""
    cam = B["camera"]
    C = np.asarray(cam["C"], dtype=np.float64)
    occs = scene_occluders(A)
    bounds = [image_bounds(o, cam) for o in occs] if cull else None
    points = doc.get("points", {})
    subjects = _Subjects()

    # edges[] (objects and receiver bounds edges): fresh dicts (plate edges are shared with B)
    edges = [dict(e) for e in doc.get("edges", [])]
    doc["edges"] = edges
    drawn = [e for e in edges if e.get("segment") is not None]
    for e in edges:
        e["visibility"], e["runs"] = "visible", []
    if drawn:
        A4 = np.array([_world4(points, e["from"]) for e in drawn])
        B4 = np.array([_world4(points, e["to"]) for e in drawn])
        Ad, Bd, keep = drawn_segments_4d(cam, A4, B4)
        for e, a4, b4, k in zip(drawn, Ad, Bd, keep.tolist()):
            if k:
                _line_subject(subjects, cam, a4, b4, e["segment"], _set(e))

    # curved drawables: outline generators / cap conics, terminator, cast-shadow conics
    gens = []
    for kind, d_entry, b_rec in _curved_pairs(doc, B):
        if kind == "conic":
            _conic_subject(subjects, d_entry, b_rec)
        elif kind == "generator":
            d_entry["visibility"], d_entry["runs"] = "visible", []
            if d_entry.get("segment") is not None:
                gens.append((d_entry, _world4(points, d_entry["from"]), _world4(points, d_entry["to"]),
                             d_entry["segment"]))
        else:
            d_entry["visibility"], d_entry["runs"] = "visible", []
            if d_entry.get("polylines") and "X4" in b_rec:
                A4s, B4s = b_rec["X4"]
                gens.append((d_entry, np.asarray(A4s, dtype=np.float64), np.asarray(B4s, dtype=np.float64),
                             d_entry["polylines"][0]))
    if gens:
        Ad, Bd, keep = drawn_segments_4d(cam, np.array([g[1] for g in gens]), np.array([g[2] for g in gens]))
        for (d_entry, _a, _b, seg), a4, b4, k in zip(gens, Ad, Bd, keep.tolist()):
            if k:
                _line_subject(subjects, cam, a4, b4, seg, _set(d_entry))

    # shadows[].polygon_edges: one run record per drawn polygon edge, parallel to polygons
    a_shadows = A.get("shadows", [])
    for sh, a_sh in zip(doc.get("shadows", []), a_shadows):
        per_poly = []
        loops = a_sh.get("loops", [])
        for j, poly in enumerate(sh.get("polygons", [])):
            if len(poly) < 3:
                per_poly.append([])
                continue
            recs = [{"visibility": "visible", "runs": []} for _ in poly]
            per_poly.append(recs)
            if j >= len(loops):
                continue
            pts4, ids = clip_polygon_4d(cam, loops[j]["vertices"])
            if pts4.shape[0] != len(poly):          # unreachable: the rectangle steps run on the drawn
                continue                            # polygon's own 3-vectors (defensive: never raise)
            n = len(poly)
            for e in range(n):
                f = (e + 1) % n
                if ids[e] is None or (pts4[e, 3] == 0.0 and pts4[f, 3] == 0.0):
                    continue
                _line_subject(subjects, cam, pts4[e], pts4[f], [poly[e], poly[f]], _set(recs[e]))
        sh["polygon_edges"] = per_poly

    subjects.classify(occs, C, cam, bounds)
    return doc

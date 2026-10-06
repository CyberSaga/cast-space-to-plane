"""Curved primitives: silhouettes, terminators and conic cast shadows (spec §5.6;
contract §2.6, §2.7, §2.10).

Everything here is a pure function of the ``analytic`` record produced by
``castplane.primitives.build_object`` (``{kind, base, axis, e1, e2, radius, height,
centre}`` in world coordinates, ``(e1, e2, axis)`` the rotated local frame) and of a
homogeneous 4-vector ``L = (l, w)``: the light vector (point ``w = 1``, directional
``w = 0``) **or** the camera position ``(C, 1)`` -- the same routine serves both
(contract §2.6).  Only numpy is used; nothing is sampled except in
:func:`shadow_polygon_h`, which produces the homogeneous ground polygon that the
drawing pipeline consumes.

Tolerances (contract §2.8): ``tol`` is the length-valued ``1e-9 * scene_scale`` for a
point light / the camera, ``tol_dir = 1e-9`` for a directional light; every predicate is
``> tol`` and the band counts as the degenerate side.

How stage A / B / C (M2) should call this module
------------------------------------------------

Stage A (``shadow_geometry``, camera independent), per curved object ``obj`` with
``an = obj["analytic"]``, light ``L = light_vector(light)``, ``pi = (0, 0, 1, 0)``,
``M = shadow_matrix(pi, L)``, ``tol_L = tol if L[3] != 0 else tol_dir``::

    sil  = silhouette(an, L, tol_L)                 # loop, generators, arcs, cap_lit, warnings
    term = terminator(an, L, tol_L)                 # image-side drawables of the same loop
    out  = shadow_outline(an, L, M, pi, tol, tol_dir)   # ground pieces (+ direction vertices)
    poly = shadow_polygon_h(out)                    # (n, 4) oriented homogeneous ground polygon
    pts  = construction_points(an, L, tol_L, obj_id=obj["id"])   # §2.7 named 4-vectors
    cam_out = camera_outline(an, cam["C"], tol)     # stage B (needs the camera position only)

``sil["warnings"]`` / ``out["warnings"]`` carry ``LIGHT_INSIDE_OBJECT``,
``VERTEX_NOT_BELOW_LIGHT`` and ``OBJECT_BELOW_RECEIVER`` with ``ids == []``: the caller
re-emits them with ``ids=[obj_id]``, keeping the message
(``make_warning(w["code"], [obj_id], w["message"])``; the ``LIGHT_INSIDE_OBJECT`` text
names the primitive kind).  ``camera_outline`` never returns warnings: a camera inside
the object is only the ``camera_inside`` flag (contract §2.9 has no code for it).

``L`` may be any non-zero homogeneous representative of the light / camera: every entry
point canonicalises it (:func:`canonical_light`: ``w = +1`` for a finite point, unit
direction for ``w = 0``, contract §2.1), so all results are invariant under positive
scaling of ``L`` (spec §7.1 row 5).  The caller's ``M`` may be built from the scaled
``L`` as well (it scales with it; direction vertices are normalised).

Buried objects (contract §2.3 ground clip): the part of the silhouette loop below the
receiver is removed and the two ground crossings are joined by a straight chord, exactly
like the Sutherland-Hodgman clip of polyhedra.  For a sphere or cylinder that is partly
below the ground the true boundary of the unlit ground region is the ground
cross-section of the object (a circle / ellipse), of which the chord keeps only the two
end points; the drawn shadow therefore omits the circular segment of that cross-section
on the light side.  This is the contract's rule (the §7.3 ray-cast reference treats the
cross-section as occluded, so the two disagree there by design); random §7.3 scenes keep
objects above the ground.  Replacing the chord by the cross-section curve would be a
further ``conic_arc`` piece if exactness is wanted later.

Stage B / C drawing rules (contract §2.6):

* **Terminator** (``form_shadow`` layer): every ``{"segment": (A4, B4)}`` goes through the
  normal segment pipeline (near clip -> ``P`` -> rectangle clip -> divide).  Every
  ``{"circle_arc": {"circle", "theta0", "theta1", "full"}}`` is drawn with
  ``H = P @ circle_embedding(circle)`` (3x3) and ``T = I``: the §3.1 ``conics`` entry is
  ``conics.conic_entry(circle, H, arc=None if full else (theta0, theta1), map="image")``.
  Near clipping of the arc is closed form: with ``E = circle_embedding(circle)``,
  ``f_nu = (forward, -(forward . C + near))`` (so that ``f_nu . X == nu(X)``), the
  coefficients ``A, B, C = conics.functional_coeffs(f_nu, E, circle["radius"])`` give
  ``nu(X(theta)) = A cos theta + B sin theta + C``; the visible sub-arcs are
  ``conics.sub_arcs_where_nonnegative(A, B, C, theta0, theta1, tol)``.  A full ellipse
  ``<ellipse>`` may be emitted only when the whole circle is in front
  (``C - sqrt(A^2 + B^2) >= 0``) and ``kind == "ellipse"`` and not ``sampled``; otherwise
  each visible sub-arc is drawn as ``<path d="M ... A rx ry rot large sweep x y">`` with
  the flags of ``conics.ellipse_arc_params(H, rho, a, b)`` (flip ``sweep`` for the SVG
  ``y``-down frame), or as a sampled polyline (``conics.sample_arc(H, rho, a, b,
  conics.sample_count(a, b))`` -> homogeneous 2-D points, rectangle-clipped as a
  polyline, divided last) for parabola / hyperbola / degenerate / ``sampled`` conics.
* **Objects layer** (``camera_outline``): the ``generators`` are drawn as segments
  (front); the ``cap_arcs`` are drawn like terminator arcs with the ``back`` flag choosing
  the dashed style (contract §2.10); a sphere draws its ``circle`` (the camera silhouette).
* **Cast shadow** (``cast_shadow`` layer): ``shadow_outline`` pieces are drawn with
  ``H = P @ M @ E`` (``T = M``) -- the §3.1 ``conics`` entry of a ``conic_arc`` piece is
  ``conics.conic_entry(piece["circle"], P @ piece["T"] @ piece["E"], arc=(theta0, theta1)
  sorted, map="shadow")``; the filled region is ``shadow_polygon_h(out)["vertices"]``
  through the full drawing pipeline (near clip -> ``P`` -> homogeneous rectangle clip ->
  divide), exactly like a polyhedral ``shadow_loop`` result (``unbounded`` flag, direction
  vertices with ``w == 0``).  A hyperbola / parabola polyline never crosses ``w = 0``
  because ``shadow_outline`` already drops the ``w_S <= tol`` parts of every arc and
  replaces the crossings by direction vertices (§2.5 rule).  Bounded ellipse shadows may
  additionally be written as ``<ellipse>`` / arc paths from the ``conics`` entries.
* **Construction** (``construction`` layer): the 4-vectors of ``construction_points`` are
  the ``P`` of the §2.7 rays (``<obj>.c``, ``<obj>.sil.k``, ``<obj>.g0.base`` ...); their
  shadows are ``M @ X`` (names ``<name>.shadow.<light>``) and feet ``foot(pi, X)``
  (``<name>.foot``), handled like polyhedral vertices.

Loop orientation (contract §2.5 / §2.6): every ``loop`` is traversed with the lit
surface on the left as seen from ``L``; under ``M`` it maps to a polygon that is
counter-clockwise in ground ``(x, y)`` (verified in ``tests/test_curved.py``).  Arc
pieces are traversed from ``theta0`` to ``theta1`` and ``theta1 < theta0`` means a
clockwise traversal in the circle frame; the unordered ``arcs`` lists and the
``terminator`` entries always use ``theta0 < theta1`` (CCW ranges, contract §2.6).
"""

from __future__ import annotations

import math

import numpy as np

from .conics import (TWO_PI, circle_embedding, circle_frame, circle_record, conic_point,
                     functional_coeffs, sample_count, sub_arcs_where_nonnegative)
from .errors import make_warning
from .light import lit
from .shadow import ARC_STEP_DEG, foot

__all__ = [
    "silhouette",
    "terminator",
    "shadow_outline",
    "shadow_polygon_h",
    "construction_points",
    "camera_outline",
    "loop_pieces_4d",
    "canonical_light",
    "canonical_factor",
]


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _vec3(v) -> np.ndarray:
    return np.asarray(v, dtype=np.float64).reshape(3)


def _point4(p) -> np.ndarray:
    p = _vec3(p)
    return np.array([p[0], p[1], p[2], 1.0], dtype=np.float64)


def _u_theta(e1: np.ndarray, e2: np.ndarray, theta: float) -> np.ndarray:
    """Outward radial unit vector ``u_theta = cos theta e1 + sin theta e2`` (contract §2.6)."""
    return math.cos(theta) * e1 + math.sin(theta) * e2


def canonical_factor(L) -> float:
    """The scalar ``s`` with ``L / s`` canonical (contract §2.1): ``w`` for a finite point
    (so a negative ``w`` is mapped back to ``w = +1``), ``|l|`` for a direction, ``1`` for
    the zero vector."""
    L = np.asarray(L, dtype=np.float64).reshape(4)
    w = float(L[3])
    if w != 0.0:
        return w
    norm = float(np.linalg.norm(L[:3]))
    if norm > 0.0 and math.isfinite(norm):
        return norm
    return 1.0


def canonical_light(L) -> np.ndarray:
    """Canonical representative of a homogeneous light / camera vector (contract §2.1,
    spec §7.1 row 5): a finite point is returned as ``(l, 1)`` (``L / w``, so any non-zero
    scalar multiple -- including a negative ``w`` -- maps to the same point light), a
    direction as ``(l / |l|, 0)`` (unit length, as validation requires of a directional
    light).  The zero vector is returned unchanged.

    Every length-valued predicate of this module (``|l - c| - r``, ``|q_perp| - r``,
    ``q . a`` against ``tol``) is evaluated on this representative, which makes the
    silhouette, terminator, shadow outline and construction points invariant under
    positive homogeneous scaling of ``L``."""
    L = np.asarray(L, dtype=np.float64).reshape(4)
    return L / canonical_factor(L)


#: ``LIGHT_INSIDE_OBJECT`` message per primitive kind (the default text of
#: ``errors.WARNING_CODES`` names the sphere only; contract §2.9).
_INSIDE_MESSAGE = "point light is inside the %s; no shadow or terminator"


def _empty_result(kind: str) -> dict:
    return {
        "kind": kind,
        "lit_interval": None,
        "theta_l": None,
        "alpha": None,
        "generators": [],
        "arcs": [],
        "cap_lit": {"base": False, "top": False},
        "loop": [],
        "circle": None,
        "cap_circles": {},
        "light_inside": False,
        "warnings": [],
    }


def _arc_piece(circle: dict, theta0: float, theta1: float, which: str) -> dict:
    return {"arc": {"circle": circle, "theta0": float(theta0), "theta1": float(theta1), "which": which}}


def _segment_piece(a, b, theta: float | None, ends: tuple[str, str], which: str = "generator") -> dict:
    return {"segment": {"from": _vec3(a).copy(), "to": _vec3(b).copy(), "theta": theta,
                        "ends": ends, "which": which}}


def _ccw_range(theta0: float, theta1: float) -> tuple[float, float]:
    """The CCW parameter range ``(lo, hi)``, ``hi > lo``, covered by a traversal from
    ``theta0`` to ``theta1`` (in either direction)."""
    return (theta0, theta1) if theta1 >= theta0 else (theta1, theta0)


# ---------------------------------------------------------------------------
# silhouettes (contract §2.6)
# ---------------------------------------------------------------------------

def _sphere_silhouette(an: dict, L: np.ndarray, tol: float) -> dict:
    """Contract §2.6 sphere: silhouette circle centre ``c + (r^2/|v|^2) v``, radius
    ``r sqrt(1 - r^2/|v|^2)``, normal ``v/|v|`` with ``v = l - w c``; for a directional
    light the great circle through ``c`` with normal ``l``.  ``|v| <= r`` (point light)
    -> ``LIGHT_INSIDE_OBJECT`` and no silhouette."""
    res = _empty_result("sphere")
    c = _vec3(an["centre"])
    r = float(an["radius"])
    l, w = L[:3], float(L[3])
    v = l - w * c
    dist = float(np.linalg.norm(v))
    if w != 0.0:
        if dist - r <= tol:
            res["light_inside"] = True
            res["warnings"].append(make_warning("LIGHT_INSIDE_OBJECT", [], _INSIDE_MESSAGE % "sphere"))
            return res
        k = r * r / (dist * dist)
        centre = c + k * v
        radius = r * math.sqrt(max(0.0, 1.0 - k))
    else:
        if dist <= tol:
            return res
        centre = c
        radius = r
    n = v / dist
    e1, e2 = circle_frame(n)
    circle = circle_record(centre, e1, e2, radius)
    circle["normal"] = n
    res["circle"] = circle
    res["lit_interval"] = "all"
    arc = _arc_piece(circle, 0.0, TWO_PI, "silhouette")
    res["arcs"] = [dict(arc["arc"])]
    res["loop"] = [arc]
    return res


def _axis_setup(an: dict, L: np.ndarray, origin: np.ndarray):
    """``q = l - w origin``, ``q_perp``, ``d = |q_perp|``, ``theta_l`` (contract §2.6)."""
    a = _vec3(an["axis"])
    e1, e2 = _vec3(an["e1"]), _vec3(an["e2"])
    l, w = L[:3], float(L[3])
    q = l - w * origin
    qa = float(q @ a)
    q_perp = q - qa * a
    d = float(np.linalg.norm(q_perp))
    theta_l = math.atan2(float(q_perp @ e2), float(q_perp @ e1))
    return a, e1, e2, q, qa, q_perp, d, theta_l


def _cylinder_silhouette(an: dict, L: np.ndarray, tol: float) -> dict:
    """Contract §2.6 cylinder: lit interval of the lateral surface centred on ``theta_l``
    with half-width ``alpha = acos(r/d)`` (point light; ``d <= r + tol`` -> nothing lit)
    or ``pi/2`` (directional; ``d <= tol`` -> nothing lit); caps tested with ``lit`` at
    their centres; loop = base arc + generator + top arc + generator."""
    res = _empty_result("cylinder")
    b = _vec3(an["base"])
    r = float(an["radius"])
    h = float(an["height"])
    a, e1, e2, q, qa, q_perp, d, theta_l = _axis_setup(an, L, b)
    w = float(L[3])
    top_c = b + h * a
    cap_base = lit(-a, b, L, tol)
    cap_top = lit(a, top_c, L, tol)
    res["cap_lit"] = {"base": bool(cap_base), "top": bool(cap_top)}
    base_circle = circle_record(b, e1, e2, r)
    top_circle = circle_record(top_c, e1, e2, r)
    res["cap_circles"] = {"base": base_circle, "top": top_circle}
    res["theta_l"] = theta_l
    if w != 0.0:
        alpha = None if d <= r + tol else math.acos(min(1.0, r / d))
    else:
        alpha = None if d <= tol else 0.5 * math.pi
    if alpha is None:
        # lateral surface wholly unlit: silhouette = each lit cap's full circle
        if cap_top:
            arc = _arc_piece(top_circle, 0.0, TWO_PI, "top")          # CCW about +a (light side)
            res["arcs"] = [dict(arc["arc"])]
            res["loop"] = [arc]
        elif cap_base:
            arc = _arc_piece(base_circle, TWO_PI, 0.0, "base")        # CW in the frame: CCW seen from -a
            res["arcs"] = [{"circle": base_circle, "theta0": 0.0, "theta1": TWO_PI, "which": "base"}]
            res["loop"] = [arc]
        elif w != 0.0:
            res["light_inside"] = True
            res["warnings"].append(make_warning("LIGHT_INSIDE_OBJECT", [], _INSIDE_MESSAGE % "cylinder"))
        return res
    res["alpha"] = alpha
    th0, th1 = theta_l - alpha, theta_l + alpha
    res["lit_interval"] = [th0, th1]
    u0, u1 = _u_theta(e1, e2, th0), _u_theta(e1, e2, th1)
    g0 = {"theta": th0, "base": b + r * u0, "top": top_c + r * u0}
    g1 = {"theta": th1, "base": b + r * u1, "top": top_c + r * u1}
    res["generators"] = [g0, g1]
    # base arc from th0 to th1: through the lit interval (CCW) when the base cap is unlit,
    # through the unlit complement (CW) when it is lit (silhouette = cap-lit != lateral-lit)
    base_arc = _arc_piece(base_circle, th0, th1 if not cap_base else th1 - TWO_PI, "base")
    # top arc from th1 back to th0: through the complement (CCW) when the top is lit
    top_arc = _arc_piece(top_circle, th1, th0 + TWO_PI if cap_top else th0, "top")
    res["loop"] = [
        base_arc,
        _segment_piece(g1["base"], g1["top"], th1, ("base", "top")),
        top_arc,
        _segment_piece(g0["top"], g0["base"], th0, ("top", "base")),
    ]
    for piece in (base_arc, top_arc):
        lo, hi = _ccw_range(piece["arc"]["theta0"], piece["arc"]["theta1"])
        res["arcs"].append({"circle": piece["arc"]["circle"], "theta0": lo, "theta1": hi,
                            "which": piece["arc"]["which"]})
    return res


def _cone_silhouette(an: dict, L: np.ndarray, tol: float) -> dict:
    """Contract §2.6 cone (apex ``v = b + h a``): ``lit(theta) <=> h (q_perp . u_theta)
    + r (q . a) > 0`` with ``q = l - w v``; lit interval centred on ``theta_l`` with
    ``alpha = acos(-r (q.a) / (h |q_perp|))`` (argument ``< -1`` -> all lit, ``> 1`` -> all
    unlit; ``|q_perp| <= tol`` -> all lit iff ``r (q.a) > tol`` else none).  Loop = base
    arc + generator + apex + generator."""
    res = _empty_result("cone")
    b = _vec3(an["base"])
    r = float(an["radius"])
    h = float(an["height"])
    a = _vec3(an["axis"])
    apex = b + h * a
    a, e1, e2, q, qa, q_perp, d, theta_l = _axis_setup(an, L, apex)
    w = float(L[3])
    cap_base = lit(-a, b, L, tol)
    res["cap_lit"] = {"base": bool(cap_base), "top": False}
    base_circle = circle_record(b, e1, e2, r)
    res["cap_circles"] = {"base": base_circle}
    res["apex"] = apex
    res["theta_l"] = theta_l
    if d <= tol:
        # on the axis: all generators lit iff q . a > tol (the contract's r (q.a) > tol with
        # r > 0 guaranteed by validation, written as a plain length comparison, §2.8)
        state = "all" if qa > tol else "none"
        alpha = None
    else:
        arg = -r * qa / (h * d)
        if arg <= -1.0:
            state, alpha = "all", None
        elif arg >= 1.0:
            state, alpha = "none", None
        else:
            state, alpha = "partial", math.acos(arg)
    if state == "all":
        res["lit_interval"] = "all"
        if not cap_base:
            arc = _arc_piece(base_circle, 0.0, TWO_PI, "base")          # light on the +a side
            res["arcs"] = [dict(arc["arc"])]
            res["loop"] = [arc]
        return res
    if state == "none":
        if cap_base:
            arc = _arc_piece(base_circle, TWO_PI, 0.0, "base")          # light on the -a side
            res["arcs"] = [{"circle": base_circle, "theta0": 0.0, "theta1": TWO_PI, "which": "base"}]
            res["loop"] = [arc]
        elif w != 0.0:
            res["light_inside"] = True
            res["warnings"].append(make_warning("LIGHT_INSIDE_OBJECT", [], _INSIDE_MESSAGE % "cone"))
        return res
    res["alpha"] = alpha
    th0, th1 = theta_l - alpha, theta_l + alpha
    res["lit_interval"] = [th0, th1]
    u0, u1 = _u_theta(e1, e2, th0), _u_theta(e1, e2, th1)
    g0 = {"theta": th0, "base": b + r * u0, "top": apex.copy()}
    g1 = {"theta": th1, "base": b + r * u1, "top": apex.copy()}
    res["generators"] = [g0, g1]
    base_arc = _arc_piece(base_circle, th0, th1 if not cap_base else th1 - TWO_PI, "base")
    res["loop"] = [
        base_arc,
        _segment_piece(g1["base"], apex, th1, ("base", "apex")),
        _segment_piece(apex, g0["base"], th0, ("apex", "base")),
    ]
    lo, hi = _ccw_range(base_arc["arc"]["theta0"], base_arc["arc"]["theta1"])
    res["arcs"] = [{"circle": base_circle, "theta0": lo, "theta1": hi, "which": "base"}]
    return res


def silhouette(analytic: dict, L, tol: float = 0.0) -> dict:
    """Silhouette of a curved primitive with respect to the homogeneous 4-vector ``L``
    (light vector or camera position ``(C, 1)``; spec §5.6, contract §2.6).

    Returns::

        {"kind": "sphere" | "cylinder" | "cone",
         "lit_interval": [theta_l - alpha, theta_l + alpha] | None | "all",
         "theta_l": float | None, "alpha": float | None,
         "generators": [{"theta", "base": (3,), "top": (3,)}]   (top = apex for a cone; 0 or 2 entries,
                                                                 ordered theta_l - alpha, theta_l + alpha),
         "arcs": [{"circle": {centre, e1, e2, radius}, "theta0" < "theta1", "which": base|top|silhouette}],
         "cap_lit": {"base": bool, "top": bool},
         "loop": ordered closed loop of {"arc": {circle, theta0, theta1, which}} (traversed theta0 -> theta1)
                 and {"segment": {"from", "to", "theta", "ends", "which"}} pieces, lit side on the left as
                 seen from L (sphere: one full circle); [] when there is no silhouette,
         "circle": the sphere's silhouette circle (with "normal") | None,
         "cap_circles": {"base": circle, "top": circle} for cylinders / {"base": circle} for cones,
         "apex": (3,) for cones,
         "light_inside": bool, "warnings": [warning dicts with empty ids]}

    ``tol`` is the point-light / camera length tolerance or ``tol_dir`` for a directional
    light (contract §2.8).  ``L`` may be any non-zero homogeneous representative: it is
    canonicalised first (:func:`canonical_light`, contract §2.1), so the result is
    invariant under positive scaling of ``L`` (spec §7.1 row 5).
    """
    L = canonical_light(L)
    kind = analytic["kind"]
    if kind == "sphere":
        return _sphere_silhouette(analytic, L, tol)
    if kind == "cylinder":
        return _cylinder_silhouette(analytic, L, tol)
    if kind == "cone":
        return _cone_silhouette(analytic, L, tol)
    raise ValueError(f"unknown curved primitive kind {kind!r}")


# ---------------------------------------------------------------------------
# terminator (image side, contract §2.6)
# ---------------------------------------------------------------------------

def terminator(analytic: dict, L, tol: float = 0.0) -> list:
    """The light silhouette as image-side drawables (``form_shadow`` layer, drawn with
    ``H = P E``, contract §2.6): a list of ``{"segment": (A4, B4), "which": "generator",
    "theta"}`` and ``{"circle_arc": {"circle", "theta0" < "theta1", "which", "full": bool}}``
    entries in loop order.  Empty when there is no silhouette (see
    :func:`silhouette` for the warnings)."""
    sil = silhouette(analytic, L, tol)
    out = []
    for piece in sil["loop"]:
        if "segment" in piece:
            seg = piece["segment"]
            out.append({"segment": (_point4(seg["from"]), _point4(seg["to"])),
                        "which": seg["which"], "theta": seg["theta"]})
        else:
            arc = piece["arc"]
            lo, hi = _ccw_range(arc["theta0"], arc["theta1"])
            out.append({"circle_arc": {"circle": arc["circle"], "theta0": lo, "theta1": hi,
                                       "which": arc["which"], "full": hi - lo >= TWO_PI - 1e-12}})
    return out


# ---------------------------------------------------------------------------
# loop clipping by a linear functional (ground clip §2.3, w_S clip §2.6)
# ---------------------------------------------------------------------------

def loop_pieces_4d(sil: dict) -> list:
    """The ``loop`` of :func:`silhouette` as 4-D pieces: ``{"segment": (A4, B4), ...}`` and
    ``{"arc": {"E": 4x3, "rho", "theta0", "theta1", "circle", "which"}}``."""
    out = []
    for piece in sil["loop"]:
        if "segment" in piece:
            seg = piece["segment"]
            out.append({"segment": (_point4(seg["from"]), _point4(seg["to"])), "which": seg["which"],
                        "theta": seg["theta"]})
        else:
            arc = piece["arc"]
            out.append({"arc": {"E": circle_embedding(arc["circle"]), "rho": float(arc["circle"]["radius"]),
                                "theta0": float(arc["theta0"]), "theta1": float(arc["theta1"]),
                                "circle": arc["circle"], "which": arc["which"]}})
    return out


def _piece_start(piece: dict) -> np.ndarray:
    if "segment" in piece:
        return piece["segment"][0]
    arc = piece["arc"]
    return conic_point(arc["E"], arc["theta0"], arc["rho"])


def _piece_end(piece: dict) -> np.ndarray:
    if "segment" in piece:
        return piece["segment"][1]
    arc = piece["arc"]
    return conic_point(arc["E"], arc["theta1"], arc["rho"])


def _clip_piece(piece: dict, f: np.ndarray, level: float) -> list:
    """Sub-pieces of ``piece`` where ``f . X > level`` (crossings placed at ``f . X == level``),
    each tagged with ``cut_start`` / ``cut_end``.  Segments interpolate homogeneous
    coordinates (contract §2.2 / §2.5); arcs use the closed-form sub-arcs of
    ``A cos theta + B sin theta + C > level`` (contract §2.6)."""
    if "segment" in piece:
        A, B = piece["segment"]
        fa, fb = float(f @ A) - level, float(f @ B) - level
        if fa > 0.0 and fb > 0.0:
            return [dict(piece, cut_start=False, cut_end=False)]
        if fa <= 0.0 and fb <= 0.0:
            return []
        X = (fa * B - fb * A) / (fa - fb)           # f . X == level
        if fa > 0.0:
            return [dict(piece, segment=(A, X), cut_start=False, cut_end=True)]
        return [dict(piece, segment=(X, B), cut_start=True, cut_end=False)]
    arc = piece["arc"]
    t0, t1 = arc["theta0"], arc["theta1"]
    lo, hi = _ccw_range(t0, t1)
    cA, cB, cC = functional_coeffs(f, arc["E"], arc["rho"])
    intervals = sub_arcs_where_nonnegative(cA, cB, cC, lo, hi, tol=level)
    eps = 1e-12
    out = []
    for a, b in intervals:
        if b > hi + eps:
            # seam-merged interval [a, b] of a full-turn range (b <= a + 2 pi): both ends
            # are interior crossings
            cut_a = cut_b = True
        else:
            cut_a = a > lo + eps
            cut_b = b < hi - eps
        sub = dict(piece)
        sub["arc"] = dict(arc, theta0=a, theta1=b)
        sub["cut_start"], sub["cut_end"] = cut_a, cut_b
        out.append(sub)
    if t0 > t1:  # traversal is clockwise: reverse the order and the direction of each sub-arc
        rev = []
        for sub in reversed(out):
            s = dict(sub)
            s["arc"] = dict(sub["arc"], theta0=sub["arc"]["theta1"], theta1=sub["arc"]["theta0"])
            s["cut_start"], s["cut_end"] = sub["cut_end"], sub["cut_start"]
            rev.append(s)
        out = rev
    return out


def _clip_loop(pieces: list, f, level: float) -> tuple[list, bool]:
    """Clip a closed loop of 4-D pieces to ``f . X > level``.  Returns ``(items, any_cut)``
    with ``items`` the kept sub-pieces in loop order interleaved with ``{"gap": (X_exit,
    X_entry)}`` markers wherever a part of the loop was removed (``X_exit`` / ``X_entry``
    are the crossing points with ``f . X == level``)."""
    f = np.asarray(f, dtype=np.float64).reshape(4)
    kept: list = []
    dropped_before: list = []        # number of dropped original pieces before each kept piece
    dropped = 0
    any_cut = False
    for piece in pieces:
        subs = _clip_piece(piece, f, level)
        if not subs:
            dropped += 1
            any_cut = True
            continue
        for sub in subs:
            kept.append(sub)
            dropped_before.append(dropped)
            dropped = 0
            any_cut = any_cut or sub["cut_start"] or sub["cut_end"]
    if not kept:
        return [], any_cut
    dropped_before[0] += dropped      # wrap-around
    n = len(kept)
    items: list = []
    for i in range(n):
        items.append(kept[i])
        j = (i + 1) % n
        if kept[i]["cut_end"] or kept[j]["cut_start"] or dropped_before[j] > 0:
            items.append({"gap": (_piece_end(kept[i]), _piece_start(kept[j]))})
    return items, any_cut


def _direction_from(S: np.ndarray, fallback_from: np.ndarray | None, finite_hint: np.ndarray | None) -> np.ndarray:
    """Contract §2.5 direction vertex: ``S`` is the shadow of the ``w_S = 0`` crossing;
    its ``w`` is zeroed and the ground direction normalised.  When the crossing is the
    light itself (``M L = 0``) the shadow ray from the light foot through the finite
    neighbour is used instead."""
    D = np.array([S[0], S[1], S[2], 0.0], dtype=np.float64)
    norm = float(np.linalg.norm(D[:3]))
    if norm > 1e-300 and math.isfinite(norm):
        return D / norm
    if fallback_from is not None and finite_hint is not None and finite_hint[3] != 0.0:
        d = finite_hint[:3] / finite_hint[3] - fallback_from[:3]
        norm = float(np.linalg.norm(d))
        if norm > 1e-300 and math.isfinite(norm):
            return np.array([d[0], d[1], d[2], 0.0]) / norm
    return np.array([1.0, 0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# ground shadow outline (contract §2.6 "unbounded curved shadows")
# ---------------------------------------------------------------------------

def shadow_outline(analytic: dict, L, M, pi, tol: float = 0.0, tol_dir: float = 1e-9) -> dict:
    """Oriented ground shadow outline of the light silhouette loop (spec §5.6, contract
    §2.3 / §2.5 / §2.6).

    ``M`` is ``shadow_matrix(pi, L)`` for the same representative of ``L``; both are
    canonicalised together (:func:`canonical_factor`), so a positively scaled ``L`` (and
    its ``M``) gives the same outline.

    Steps: (1) :func:`silhouette`; (2) ground clip of every loop piece to ``pi^T X >= -tol``
    (crossings on the ground are their own shadows and are joined by a straight ground
    chord, like the Sutherland-Hodgman clip of §2.3); (3) ``w_S`` clip: ``w_S(X) = M[3] . X``
    is ``A cos theta + B sin theta + C`` along an arc and linear along a segment; the parts
    with ``w_S <= tol_w`` are dropped (``tol_w = tol`` for a point light, ``tol_dir`` for a
    directional one) and the crossings become direction vertices with the §2.5 rule
    (``D = M X*``, ``w := 0``, normalised); (4) every surviving piece is mapped by ``M``.

    Returns ``{"pieces": [...], "unbounded": bool, "below_ground": bool, "empty": bool,
    "silhouette": sil, "warnings": [...]}`` with the pieces in loop order, each one of::

        {"segment": [S_a (4,), S_b (4,)], "which": "generator" | "ground"}     both w_S > tol_w
        {"conic_arc": {"E": 4x3, "rho": float, "T": M (4x4), "theta0", "theta1", "circle", "which"}}
                       ground conic = transform_conic(circle_matrix(rho), H), H = P @ T @ E (any P);
                       traversed theta0 -> theta1 (theta1 < theta0 = clockwise in the circle frame)
        {"direction": D (4,), "role": "out" | "in"}                             w == 0 exactly

    Warnings (ids empty, caller adds the object id): ``LIGHT_INSIDE_OBJECT``,
    ``VERTEX_NOT_BELOW_LIGHT`` (some part of the loop has ``w_S <= tol_w`` -> unbounded),
    ``OBJECT_BELOW_RECEIVER`` (some part of the loop was below the receiver).
    """
    # canonical representatives (contract §2.1): shadow_matrix is linear in L, so the M of
    # a scaled L is the scaled M; dividing both by the same factor keeps the w_S > tol_w
    # band -- and with it every vertex -- invariant under positive scaling of L
    factor = canonical_factor(L)
    L = np.asarray(L, dtype=np.float64).reshape(4) / factor
    M = np.asarray(M, dtype=np.float64).reshape(4, 4) / factor
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    tol_w = tol if L[3] != 0.0 else tol_dir
    sil = silhouette(analytic, L, tol_w)
    warnings = list(sil["warnings"])
    result = {"pieces": [], "unbounded": False, "below_ground": False, "empty": True,
              "silhouette": sil, "warnings": warnings}
    pieces = loop_pieces_4d(sil)
    if not pieces:
        return result
    # (2) ground clip, contract §2.3: keep pi^T X > -tol, chords across the removed parts
    items, cut = _clip_loop(pieces, pi, -tol)
    if cut:
        result["below_ground"] = True
        warnings.append(make_warning("OBJECT_BELOW_RECEIVER", []))
    pieces = []
    for it in items:
        if "gap" in it:
            X_exit, X_entry = it["gap"]
            pieces.append({"segment": (X_exit, X_entry), "which": "ground", "theta": None})
        else:
            pieces.append(it)
    if not pieces:
        return result
    # (3) w_S clip, contract §2.5 / §2.6: keep w_S > tol_w, direction vertices at the crossings
    items, cut = _clip_loop(pieces, M[3], tol_w)
    if cut:
        warnings.append(make_warning("VERTEX_NOT_BELOW_LIGHT", []))
    if not items:
        # the whole loop is at w_S <= tol_w: no shadow at all (contract §2.5), not an
        # unbounded one -- same convention as shadow.shadow_loop
        return result
    result["unbounded"] = cut
    F = foot(pi, L)
    F = F / F[3] if abs(F[3]) > 1e-300 else None
    out = []
    for idx, it in enumerate(items):
        if "gap" in it:
            X_exit, X_entry = it["gap"]
            prev_piece = items[idx - 1]
            next_piece = items[(idx + 1) % len(items)]
            hint_prev = M @ _piece_start(prev_piece) if "gap" not in prev_piece else None
            hint_next = M @ _piece_end(next_piece) if "gap" not in next_piece else None
            out.append({"direction": _direction_from(M @ X_exit, F, hint_prev), "role": "out"})
            out.append({"direction": _direction_from(M @ X_entry, F, hint_next), "role": "in"})
        elif "segment" in it:
            A, B = it["segment"]
            out.append({"segment": [M @ A, M @ B], "which": it["which"], "theta": it.get("theta")})
        else:
            arc = it["arc"]
            out.append({"conic_arc": {"E": arc["E"], "rho": arc["rho"], "T": M,
                                      "theta0": arc["theta0"], "theta1": arc["theta1"],
                                      "circle": arc["circle"], "which": arc["which"]}})
    result["pieces"] = out
    result["empty"] = False
    return result


def shadow_polygon_h(outline, samples_per_circle: int = 64) -> dict:
    """Oriented homogeneous ground polygon of a :func:`shadow_outline` (contract §2.5 /
    §2.6): finite samples of the conic arcs (``samples_per_circle`` segments per full
    circle, proportionally fewer per arc, minimum 8), the segment endpoints and the
    direction vertices, with the §2.5 counter-clockwise arc-at-infinity subdivision
    (``ceil(delta / 60 deg)`` steps) between each outgoing and the following incoming
    direction.  The endpoint of a piece that was cut at ``w_S = tol`` is *replaced* by
    its direction vertex (it is never emitted as a finite vertex).

    ``outline`` is the dict of :func:`shadow_outline` or its ``pieces`` list.  Returns
    ``{"vertices": (n, 4), "unbounded": bool, "sources": per-vertex provenance:
    ("segment", i, 0|1), ("arc", i, k), ("dir", i, role), ("inf", i, s)}``, ready for the
    drawing pipeline exactly like ``castplane.shadow.shadow_loop``'s result."""
    pieces = outline["pieces"] if isinstance(outline, dict) else list(outline)
    n = len(pieces)
    verts: list[np.ndarray] = []
    sources: list = []
    unbounded = False
    if n == 0:
        return {"vertices": np.zeros((0, 4), dtype=np.float64), "unbounded": False, "sources": []}

    def is_dir(k, role):
        p = pieces[k % n]
        return "direction" in p and p["role"] == role

    for i, piece in enumerate(pieces):
        skip_start = is_dir(i - 1, "in")
        if "segment" in piece:
            if not skip_start:
                verts.append(np.asarray(piece["segment"][0], dtype=np.float64))
                sources.append(("segment", i, 0))
        elif "conic_arc" in piece:
            arc = piece["conic_arc"]
            th0, th1 = arc["theta0"], arc["theta1"]
            m = sample_count(th0, th1, samples_per_circle)
            th = th0 + (th1 - th0) * np.arange(m, dtype=np.float64) / m       # k = 0 .. m-1 (end excluded)
            X = conic_point(arc["E"], th, arc["rho"])                           # (m, 4) world points
            S = X @ np.asarray(arc["T"], dtype=np.float64).T                   # S = M X
            start = 1 if skip_start else 0
            for k in range(start, m):
                verts.append(S[k])
                sources.append(("arc", i, k))
        else:
            D = np.asarray(piece["direction"], dtype=np.float64)
            verts.append(D)
            sources.append(("dir", i, piece["role"]))
            unbounded = True
            if piece["role"] == "out":
                # contract §2.5: sweep CCW in ground (x, y) from D_out to the next D_in
                nxt = pieces[(i + 1) % n]
                if "direction" not in nxt or nxt["role"] != "in":
                    raise AssertionError("an outgoing direction must be followed by an incoming one")
                d_in = nxt["direction"]
                th0 = math.atan2(D[1], D[0])
                th1 = math.atan2(d_in[1], d_in[0])
                delta = (th1 - th0) % TWO_PI
                if not math.isfinite(delta) or delta <= 1e-12:
                    delta = TWO_PI
                steps = max(1, int(math.ceil(delta / math.radians(ARC_STEP_DEG) - 1e-12)))
                for s in range(1, steps):
                    t = th0 + delta * s / steps
                    verts.append(np.array([math.cos(t), math.sin(t), 0.0, 0.0]))
                    sources.append(("inf", i, s - 1))
    vertices = np.array(verts, dtype=np.float64).reshape(-1, 4)
    return {"vertices": vertices, "unbounded": unbounded, "sources": sources}


# ---------------------------------------------------------------------------
# construction points (contract §2.7)
# ---------------------------------------------------------------------------

def construction_points(analytic: dict, L, tol: float = 0.0, obj_id: str = "obj") -> dict:
    """Named homogeneous 4-vectors (``w = 1``) of the silhouette vertices that get
    construction rays (contract §2.7): sphere -> ``<obj>.c`` (centre) and
    ``<obj>.sil.0..3`` (silhouette circle centre ``+e1, -e1, +e2, -e2`` times its radius);
    cylinder -> ``<obj>.g0.base``, ``<obj>.g0.top``, ``<obj>.g1.base``, ``<obj>.g1.top``;
    cone -> ``<obj>.g0.base``, ``<obj>.g1.base``, ``<obj>.apex``.  Only the points that
    exist for this ``L`` are returned (no generators when the silhouette is a full cap
    circle; nothing when the light is inside the sphere).  Insertion order is the order
    listed here."""
    sil = silhouette(analytic, L, tol)
    pts: dict = {}
    if sil["kind"] == "sphere":
        if sil["light_inside"]:
            return pts
        pts[f"{obj_id}.c"] = _point4(analytic["centre"])
        circ = sil["circle"]
        if circ is not None:
            c, rs = circ["centre"], circ["radius"]
            for k, v in enumerate((circ["e1"], -circ["e1"], circ["e2"], -circ["e2"])):
                pts[f"{obj_id}.sil.{k}"] = _point4(c + rs * v)
        return pts
    gens = sil["generators"]
    if not gens:
        return pts
    if sil["kind"] == "cylinder":
        for k, g in enumerate(gens):
            pts[f"{obj_id}.g{k}.base"] = _point4(g["base"])
            pts[f"{obj_id}.g{k}.top"] = _point4(g["top"])
    else:
        for k, g in enumerate(gens):
            pts[f"{obj_id}.g{k}.base"] = _point4(g["base"])
        pts[f"{obj_id}.apex"] = _point4(sil["apex"])
    return pts


# ---------------------------------------------------------------------------
# camera outline (contract §2.6 / §2.10)
# ---------------------------------------------------------------------------

def camera_outline(analytic: dict, C, tol: float = 0.0) -> dict:
    """Outline of a curved object as seen from the camera position ``C`` (the silhouette
    with ``L = (C, 1)``, contract §2.6) plus the cap-circle arcs split at the outline
    generators with a ``back`` flag (contract §2.10: an arc is back when both adjacent
    surfaces -- the cap and the lateral surface along it -- are unlit with the camera as
    light; the arc on the camera side of the lateral surface is always front).

    Returns ``{"silhouette": sil, "generators": [...], "circle": sphere outline circle | None,
    "cap_arcs": [{"which": base|top, "circle", "theta0" < "theta1", "back": bool, "full": bool}],
    "camera_inside": bool}``.

    ``camera_inside`` (the camera position is inside or on the object: no outline) is a
    flag only -- contract §2.9 has no warning code for it, so the returned ``silhouette``
    carries an empty ``warnings`` list (the ``LIGHT_INSIDE_OBJECT`` warning the shared
    routine would raise for a light is not a light condition here and is dropped)."""
    C = _vec3(C)
    L = np.array([C[0], C[1], C[2], 1.0], dtype=np.float64)
    sil = dict(silhouette(analytic, L, tol), warnings=[])
    out = {"silhouette": sil, "generators": sil["generators"], "circle": sil["circle"],
           "cap_arcs": [], "camera_inside": bool(sil["light_inside"])}
    if sil["kind"] == "sphere":
        return out
    gens = sil["generators"]
    lateral_all = sil["lit_interval"] == "all"
    for which, circle in sil["cap_circles"].items():
        cap_lit = sil["cap_lit"][which]
        if gens:
            th0, th1 = gens[0]["theta"], gens[1]["theta"]
            out["cap_arcs"].append({"which": which, "circle": circle, "theta0": th0, "theta1": th1,
                                    "back": False, "full": False})
            out["cap_arcs"].append({"which": which, "circle": circle, "theta0": th1, "theta1": th0 + TWO_PI,
                                    "back": not cap_lit, "full": False})
        else:
            out["cap_arcs"].append({"which": which, "circle": circle, "theta0": 0.0, "theta1": TWO_PI,
                                    "back": not cap_lit and not lateral_all, "full": True})
    return out

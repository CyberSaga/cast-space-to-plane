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

How stage A / B / C (M2) call this module
-----------------------------------------

The pipeline hooks are :func:`stage_a_object` (stage A: silhouette, terminator,
construction points, shadow outline / polygon and the shadow record of every light,
stored on the object as ``obj["curved"][<light id>]``) and :func:`stage_b_objects`
(stage B of all curved objects of a scene at once, :func:`stage_b_object` for one: camera
outline, terminator drawables, cast-shadow conic arcs and the named points, all near- and
rectangle-clipped in closed form through :func:`arc_record`);
stage C (``pipeline.compose``) turns the arc records into drawables.  In terms of the
primitives below, stage A per curved object ``obj`` with
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
receiver is removed, exactly like the Sutherland-Hodgman clip of polyhedra, and each
removed part is replaced by the boundary of the object's **ground cross-section** between
the two ground crossings (:func:`_ground_chain`): the solid cut by the receiver has an
unlit cut face whose lit-side boundary is a silhouette edge, so the drawn shadow is
exactly that of the part above the ground (spec §2.3 / §7.3).  The chain is the
counter-clockwise (ground ``(x, y)``) boundary path of the convex cross-section from the
exit crossing to the entry crossing, i.e. the part of the cross-section curve adjacent to
the lit lateral surface (lit cap chords are straight and need no interior point).  It is
emitted as ground ``segment`` pieces (``which == "ground"``) between sampled points of the
cross-section curve (64 per full turn of the base-circle parameter, contract §2.6 rule):
the chain is therefore a polyline, not a ``conic_arc`` piece, and does not appear in the
``conics`` entries of the document.  The straight chord of §2.3 remains the fallback when
the cross-section is degenerate (no area) or when no cross-section point is on the lit
side (a lit cap chord, which the chord reproduces exactly).

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

from .conics import (TWO_PI, circle_embedding, circle_frame, circle_record, conic_entry, conic_point,
                     functional_coeffs, sample_count, sub_arcs_where_nonnegative)
from .errors import make_warning
from .homogeneous import TOL_DIR
from .light import lit
from .shadow import ARC_STEP_DEG, clip_polygon_bounds, foot, shadow_w

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
    "stage_a_object",
    "stage_b_object",
    "stage_b_objects",
    "arc_record",
    "near_functional",
    "plane_min",
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


def _segment_piece(a, b, theta: float | None, ends: tuple[str, str], which: str = "generator",
                   gen: int | None = None) -> dict:
    """A straight loop piece.  ``ends`` names the construction points at its two ends
    (``base`` / ``top`` of generator ``gen``, or ``apex``; contract §2.7)."""
    return {"segment": {"from": _vec3(a).copy(), "to": _vec3(b).copy(), "theta": theta,
                        "ends": ends, "which": which, "gen": gen}}


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
    # fallback frame (light along world z): the sphere's rotated local axes, so that the sampled
    # outline rotates with the scene (contract §2.6 fallback ``n x x`` for an unrotated sphere)
    e1, e2 = circle_frame(n, fallback=(an["e1"], an["e2"]))
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
        _segment_piece(g1["base"], g1["top"], th1, ("base", "top"), gen=1),
        top_arc,
        _segment_piece(g0["top"], g0["base"], th0, ("top", "base"), gen=0),
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
        _segment_piece(g1["base"], apex, th1, ("base", "apex"), gen=1),
        _segment_piece(apex, g0["base"], th0, ("apex", "base"), gen=0),
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
                        "theta": seg["theta"], "ends": seg.get("ends"), "gen": seg.get("gen")})
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


def _zero_shift(cA: float, cB: float, cC: float, level: float) -> float | None:
    """Parameter offset from a crossing of ``A cos theta + B sin theta + C == level`` to the
    zero crossing of the same lobe (contract §2.5: direction vertices sit at the exact
    ``w_S = 0`` point, while the parts kept by a clip are those with ``w_S > tol``).

    With ``R = sqrt(A^2 + B^2)`` and ``phi = atan2(B, A)`` the function exceeds ``level`` on
    ``(phi - d1, phi + d1)`` with ``d1 = acos((level - C) / R)`` and is positive on
    ``(phi - d0, phi + d0)`` with ``d0 = acos(-C / R)``; the start crossing ``a`` of a kept
    interval has its zero at ``a - (d0 - d1)``, the end crossing ``b`` at ``b + (d0 - d1)``.
    Returns ``None`` when no zero crossing exists (the lobe never reaches zero)."""
    R = math.hypot(cA, cB)
    if R <= 0.0:
        return None
    c0 = -cC / R
    c1 = (level - cC) / R
    if abs(c0) >= 1.0 or abs(c1) > 1.0:
        return None
    return math.acos(c0) - math.acos(c1)


def _clip_piece(piece: dict, f: np.ndarray, level: float) -> list:
    """Sub-pieces of ``piece`` where ``f . X > level`` (crossings placed at ``f . X == level``),
    each tagged with ``cut_start`` / ``cut_end``.  Segments interpolate homogeneous
    coordinates (contract §2.2 / §2.5); arcs use the closed-form sub-arcs of
    ``A cos theta + B sin theta + C > level`` (contract §2.6).

    Every end cut in this pass also carries ``zero_start`` / ``zero_end``: the point of the
    piece where ``f . X == 0`` exactly (the §2.5 interpolation ``t* = w_a / (w_a - w_b)`` for
    a segment, the closed-form zero crossing of :func:`_zero_shift` for an arc), which the
    loop clip uses for its gap markers (direction vertices at ``w_S = 0``, ground crossings
    at ``pi^T X = 0``); ``None`` when the piece does not reach zero on that lobe."""
    if "segment" in piece:
        A, B = piece["segment"]
        fa0, fb0 = float(f @ A), float(f @ B)
        fa, fb = fa0 - level, fb0 - level
        was_start, was_end = piece.get("cut_start", False), piece.get("cut_end", False)
        if fa > 0.0 and fb > 0.0:
            return [dict(piece, cut_start=was_start, cut_end=was_end, _cut_now=(False, False),
                         zero_start=None, zero_end=None)]
        if fa <= 0.0 and fb <= 0.0:
            return []
        X = (fa * B - fb * A) / (fa - fb)           # f . X == level
        zero = None
        if (fa0 > 0.0) != (fb0 > 0.0) and fa0 != fb0:
            zero = (fa0 * B - fb0 * A) / (fa0 - fb0)  # f . X == 0 (contract §2.5 t*)
        if fa > 0.0:
            return [dict(piece, segment=(A, X), cut_start=was_start, cut_end=True, _cut_now=(False, True),
                         zero_start=None, zero_end=zero)]
        return [dict(piece, segment=(X, B), cut_start=True, cut_end=was_end, _cut_now=(True, False),
                     zero_start=zero, zero_end=None)]
    arc = piece["arc"]
    t0, t1 = arc["theta0"], arc["theta1"]
    lo, hi = _ccw_range(t0, t1)
    cA, cB, cC = functional_coeffs(f, arc["E"], arc["rho"])
    intervals = sub_arcs_where_nonnegative(cA, cB, cC, lo, hi, tol=level)
    shift = _zero_shift(cA, cB, cC, level)
    eps = 1e-12
    was_start, was_end = piece.get("cut_start", False), piece.get("cut_end", False)
    if t0 > t1:  # the stored flags refer to the traversal direction; here we work in CCW order
        was_start, was_end = was_end, was_start
    out = []
    for a, b in intervals:
        if b > hi + eps:
            # seam-merged interval [a, b] of a full-turn range (b <= a + 2 pi): both ends
            # are interior crossings
            now_a = now_b = True
        else:
            now_a = a > lo + eps
            now_b = b < hi - eps
        sub = dict(piece)
        sub["arc"] = dict(arc, theta0=a, theta1=b)
        # cut_start / cut_end accumulate over successive clips (an end cut by an earlier pass stays
        # cut); _cut_now holds the crossings of this pass only (used for the gap markers)
        sub["cut_start"], sub["cut_end"] = now_a or (not now_a and was_start), now_b or (not now_b and was_end)
        sub["_cut_now"] = (now_a, now_b)
        sub["zero_start"] = conic_point(arc["E"], a - shift, arc["rho"]) if now_a and shift is not None else None
        sub["zero_end"] = conic_point(arc["E"], b + shift, arc["rho"]) if now_b and shift is not None else None
        out.append(sub)
    if t0 > t1:  # traversal is clockwise: reverse the order and the direction of each sub-arc
        rev = []
        for sub in reversed(out):
            s = dict(sub)
            s["arc"] = dict(sub["arc"], theta0=sub["arc"]["theta1"], theta1=sub["arc"]["theta0"])
            s["cut_start"], s["cut_end"] = sub["cut_end"], sub["cut_start"]
            s["_cut_now"] = (sub["_cut_now"][1], sub["_cut_now"][0])
            s["zero_start"], s["zero_end"] = sub["zero_end"], sub["zero_start"]
            rev.append(s)
        out = rev
    return out


def _cut_point(piece: dict, end: int) -> np.ndarray:
    """The gap-marker point at one end of a kept piece: its exact zero crossing when that end
    was cut in the current pass (and the zero exists), else the piece's end point itself."""
    zero = piece.get("zero_end" if end else "zero_start")
    if piece["_cut_now"][end] and zero is not None:
        return np.asarray(zero, dtype=np.float64)
    return _piece_end(piece) if end else _piece_start(piece)


def _clip_loop(pieces: list, f, level: float) -> tuple[list, bool]:
    """Clip a closed loop of 4-D pieces to ``f . X > level``.  Returns ``(items, any_cut)``
    with ``items`` the kept sub-pieces in loop order interleaved with ``{"gap": (X_exit,
    X_entry)}`` markers wherever a part of the loop was removed (``X_exit`` / ``X_entry``
    are the exact crossing points with ``f . X == 0`` of the cut pieces, contract §2.5;
    the kept pieces themselves end at ``f . X == level``, see :func:`_cut_point`)."""
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
            any_cut = any_cut or sub["_cut_now"][0] or sub["_cut_now"][1]
    if not kept:
        return [], any_cut
    dropped_before[0] += dropped      # wrap-around
    n = len(kept)
    items: list = []
    for i in range(n):
        items.append(kept[i])
        j = (i + 1) % n
        if kept[i]["_cut_now"][1] or kept[j]["_cut_now"][0] or dropped_before[j] > 0:
            items.append({"gap": (_cut_point(kept[i], 1), _cut_point(kept[j], 0))})
    return items, any_cut


def _direction_from(S: np.ndarray, fallback_from: np.ndarray | None, finite_hint: np.ndarray | None,
                    frame=None) -> np.ndarray:
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
    if frame is not None:   # contract §5.1.2: the last resort is (e1, 0) of the receiver frame
        e1 = np.asarray(frame[0], dtype=np.float64).reshape(3)
        return np.array([e1[0], e1[1], e1[2], 0.0])
    return np.array([1.0, 0.0, 0.0, 0.0])


# ---------------------------------------------------------------------------
# ground cross-section of a buried primitive (contract §2.3 ground clip, spec §7.3)
# ---------------------------------------------------------------------------

#: Relative margin (fraction of the cross-section size) within which a cross-section sample
#: counts as one of the gap's own end points and is not repeated.
_CHAIN_MARGIN = 1e-7

#: Number of geometric refinement samples (``1/2, 1/4, ...`` of the last parameter step)
#: inserted by :func:`shadow_polygon_h` next to a direction vertex.
ASYMPTOTE_REFINE = 4


def _theta_lit(sil: dict, theta: float) -> bool:
    """Lit state of the lateral surface along the generator at ``theta`` (strictly inside
    the lit interval ``[theta_l - alpha, theta_l + alpha]`` of :func:`silhouette`; the
    tangent generators themselves are the parallel band and count as unlit)."""
    iv = sil["lit_interval"]
    if iv == "all":
        return True
    if iv is None:
        return False
    th0, th1 = float(iv[0]), float(iv[1])
    k = (theta - th0) % TWO_PI
    return 0.0 < k < th1 - th0


def _lateral_intervals(E_base: np.ndarray, rho: float, conditions: list) -> list:
    """Base-circle parameter intervals where every linear condition ``f . X(theta) >= 0``
    holds (closed form, contract §2.6); ``conditions`` are 4-vectors applied to the base
    circle point ``X(theta) = E_base (rho cos theta, rho sin theta, 1)``."""
    intervals = [[0.0, TWO_PI]]
    for f in conditions:
        A, B, C = functional_coeffs(f, E_base, rho)
        intervals = _intersect_arcs(intervals, A, B, C, 0.0)
    return intervals


def _plane_uv(P, frame=None) -> np.ndarray:
    """In-plane coordinates of ``(n, 3)`` receiver points: ``P[:, :2]`` on the ground (``frame is None``,
    the literal v2 expression), ``(P·e1, P·e2)`` in the receiver frame otherwise (contract §5.1.2)."""
    P = np.asarray(P, dtype=np.float64).reshape(-1, 3)
    if frame is None:
        return P[:, :2]
    e1, e2 = (np.asarray(e, dtype=np.float64).reshape(3) for e in frame)
    return np.stack([P @ e1, P @ e2], axis=1)


def _ground_section(analytic: dict, sil: dict, L: np.ndarray, pi: np.ndarray, tol_lit: float,
                    tol: float, samples_per_circle: int = 64, frame=None) -> dict | None:
    """Sampled boundary of the receiver cross-section of a curved primitive (the cut face
    of contract §2.3) with the lit state of the adjacent lateral surface at each sample.

    The cross-section of a convex solid with the receiver plane is convex; its boundary is
    the receiver trace of the lateral surface (a conic: the base circle mapped along the
    axis for a cylinder, through the apex for a cone; a circle for a sphere) closed by the
    chords of the cap discs.  Lateral samples are taken uniformly in the base-circle
    parameter ``theta`` on the closed-form intervals where the generator at ``theta``
    crosses the receiver between its two ends (contract §2.6 sampling rule, end points
    included, so every cap chord end point is a sample); cap chords are straight and need
    no interior sample.  A sample is ``lit`` when the lateral surface along it is lit by
    ``L`` (:func:`_theta_lit`; the sphere normal for a sphere), which is exactly the
    condition for the cross-section curve to be a silhouette edge of the cut solid (the
    cut face is unlit, contract §2.3).

    Returns ``{"points": (n, 3) receiver points, "lit": (n,) bool, "centre": (2,)}`` with
    ``centre`` an interior point of the convex cross-section used to order the boundary
    by angle, or ``None`` when the cross-section has no area (the solid touches the
    receiver or does not cross it) or the configuration is degenerate."""
    kind = analytic["kind"]
    r = float(analytic["radius"])
    n = pi[:3]
    if kind == "sphere":
        c = _vec3(analytic["centre"])
        depth = float(n @ c) + float(pi[3])                     # signed distance of the centre
        if r - abs(depth) <= tol:
            return None
        rs = math.sqrt(r * r - depth * depth)
        e1, e2 = circle_frame(n)
        centre = c - depth * n
        th = TWO_PI * np.arange(samples_per_circle, dtype=np.float64) / samples_per_circle
        pts = centre[None, :] + rs * (np.cos(th)[:, None] * e1[None, :] + np.sin(th)[:, None] * e2[None, :])
        lit_mask = np.array([lit((p - c) / r, p, L, tol_lit) for p in pts], dtype=bool)
        return {"points": pts, "lit": lit_mask,
                "centre": centre[:2].copy() if frame is None else _plane_uv(centre, frame)[0].copy()}
    a = _vec3(analytic["axis"])
    b = _vec3(analytic["base"])
    h = float(analytic["height"])
    e1, e2 = _vec3(analytic["e1"]), _vec3(analytic["e2"])
    base_circle = circle_record(b, e1, e2, r)
    E_base = circle_embedding(base_circle)
    pts: list = []
    lit_list: list = []

    def add(theta, X):
        pts.append(np.asarray(X, dtype=np.float64).reshape(3))
        lit_list.append(_theta_lit(sil, float(theta)))

    def sample_intervals(intervals, mapper):
        for lo, hi in intervals:
            m = sample_count(lo, hi, samples_per_circle)
            last = m if hi - lo < TWO_PI - 1e-12 else m - 1       # a full turn repeats its start
            for k in range(last + 1):
                theta = lo + (hi - lo) * k / m
                add(theta, mapper(theta))

    na = float(n @ a)
    if kind == "cylinder":
        if abs(na) <= TOL_DIR:
            # lateral surface parallel to the receiver: the trace is two generator lines
            amp = math.hypot(float(n @ e1), float(n @ e2))
            depth = float(n @ b) + float(pi[3])
            if amp <= TOL_DIR or abs(depth) >= r * amp * (1.0 - 1e-12):
                return None
            phi = math.atan2(float(n @ e2), float(n @ e1))
            d = math.acos(max(-1.0, min(1.0, -depth / (r * amp))))
            for theta in (phi - d, phi + d):
                B = b + r * _u_theta(e1, e2, theta)
                add(theta, B)
                add(theta, B + h * a)
        else:
            top = circle_embedding(circle_record(b + h * a, e1, e2, r))
            sign = 1.0 if na > 0.0 else -1.0
            # the generator at theta crosses the receiver between its ends: base on the far
            # side (sign * pi^T B <= 0) and top on the near side (sign * pi^T T >= 0)
            intervals = _lateral_intervals(E_base, r, [-sign * pi])
            A_t, B_t, C_t = functional_coeffs(sign * pi, top, r)       # sign * pi^T T(theta), same theta
            intervals = _intersect_arcs(intervals, A_t, B_t, C_t, 0.0)

            def mapper(theta):
                B = b + r * _u_theta(e1, e2, theta)
                return B - ((float(n @ B) + float(pi[3])) / na) * a

            sample_intervals(intervals, mapper)
    else:  # cone
        apex = b + h * a
        depth_v = float(n @ apex) + float(pi[3])
        if abs(depth_v) <= tol:
            # apex on the receiver: the cross-section is the triangle apex + base chord
            intervals = _lateral_intervals(E_base, r, [-pi])
            ends = [theta for lo, hi in intervals for theta in (lo, hi)]
            if not ends:
                return None
            for theta in ends:
                add(theta, b + r * _u_theta(e1, e2, theta))
            pts.append(apex.copy())
            lit_list.append(any(_theta_lit(sil, theta) for theta in ends))
        else:
            sign = 1.0 if depth_v > 0.0 else -1.0
            intervals = _lateral_intervals(E_base, r, [-sign * pi])

            def mapper(theta):
                B = b + r * _u_theta(e1, e2, theta)
                depth_b = float(n @ B) + float(pi[3])
                return (depth_v * B - depth_b * apex) / (depth_v - depth_b)

            sample_intervals(intervals, mapper)
    if len(pts) < 3:
        return None
    P = np.array(pts, dtype=np.float64).reshape(-1, 3)
    uv = _plane_uv(P, frame)
    centre = uv.mean(axis=0)
    rel = uv - centre[None, :]
    size = float(np.max(np.hypot(rel[:, 0], rel[:, 1])))
    if not (size > tol):
        return None
    return {"points": P, "lit": np.array(lit_list, dtype=bool), "centre": centre}


def _ground_chain(section: dict | None, X_exit: np.ndarray, X_entry: np.ndarray, single_gap: bool,
                  frame=None) -> list:
    """Interior points (homogeneous, ``w = 1``) of the cross-section boundary path replacing
    the straight chord ``X_exit -> X_entry`` of a ground-clip gap (contract §2.3, see the
    module docstring): the lit samples of :func:`_ground_section` lying on the
    counter-clockwise (ground ``(x, y)``) boundary path from the exit to the entry
    crossing, in path order.  The path of a gap is on the right of its chord (the convex
    cross-section lies on the left of its counter-clockwise boundary), so a sample on the
    left is a contradiction and makes the chain fall back to the chord.  When the chord is
    degenerate (the two crossings coincide) the angular range is ambiguous -- the chain is
    either empty (a tiny dip of the loop below the receiver) or the whole lit boundary (the
    loop touches the receiver from below) -- and the lit samples alone decide, provided the
    gap is the only one of the loop.  Returns ``[]`` for the plain chord."""
    if section is None:
        return []
    P, lit_mask, I = section["points"], section["lit"], section["centre"]
    e = np.asarray(X_exit, dtype=np.float64)
    n_ = np.asarray(X_entry, dtype=np.float64)
    if frame is None:
        e = e[:2] / e[3]
        n_ = n_[:2] / n_[3]
        uv = P[:, :2]
    else:     # contract §5.1.2: counter-clockwise about n in the receiver frame
        e = _plane_uv(e[:3], frame)[0] / e[3]
        n_ = _plane_uv(n_[:3], frame)[0] / n_[3]
        uv = _plane_uv(P, frame)
    rel = uv - I[None, :]
    size = float(np.max(np.hypot(rel[:, 0], rel[:, 1])))
    delta = _CHAIN_MARGIN * size
    phi_e = math.atan2(e[1] - I[1], e[0] - I[0])
    phi_n = math.atan2(n_[1] - I[1], n_[0] - I[0])
    span = (phi_n - phi_e) % TWO_PI
    chord = n_ - e
    chord_len = float(math.hypot(chord[0], chord[1]))
    degenerate = chord_len <= delta or span <= _CHAIN_MARGIN or span >= TWO_PI - _CHAIN_MARGIN
    if degenerate:
        if not single_gap:
            return []
        span = TWO_PI
    keys = (np.arctan2(rel[:, 1], rel[:, 0]) - phi_e) % TWO_PI
    d_e = np.hypot(uv[:, 0] - e[0], uv[:, 1] - e[1])
    d_n = np.hypot(uv[:, 0] - n_[0], uv[:, 1] - n_[1])
    sel = lit_mask & (keys > _CHAIN_MARGIN) & (keys < span - _CHAIN_MARGIN) & (d_e > delta) & (d_n > delta)
    if not np.any(sel):
        return []
    if not degenerate:
        left = chord[0] * (uv[sel, 1] - e[1]) - chord[1] * (uv[sel, 0] - e[0])
        if float(np.max(left)) > delta * chord_len:
            return []
    order = np.argsort(keys[sel], kind="stable")
    chosen = P[sel][order]
    return [np.array([p[0], p[1], p[2], 1.0], dtype=np.float64) for p in chosen]


def _ground_ring(section: dict | None, frame=None) -> list:
    """The lit cross-section boundary as a closed counter-clockwise ring of homogeneous
    ground points (``w = 1``), used when the whole silhouette loop lies below the receiver
    (contract §2.3): the part above the receiver then has no silhouette of its own, so it
    is wholly lit -- its shadow is its footprint -- or wholly unlit (no shadow).  Fewer
    than three lit samples give ``[]``."""
    if section is None:
        return []
    P, lit_mask, I = section["points"], section["lit"], section["centre"]
    if int(np.count_nonzero(lit_mask)) < 3:
        return []
    rel = _plane_uv(P[lit_mask], frame) - I[None, :]
    order = np.argsort(np.arctan2(rel[:, 1], rel[:, 0]), kind="stable")
    chosen = P[lit_mask][order]
    return [np.array([p[0], p[1], p[2], 1.0], dtype=np.float64) for p in chosen]


# ---------------------------------------------------------------------------
# ground shadow outline (contract §2.6 "unbounded curved shadows")
# ---------------------------------------------------------------------------

def shadow_outline(analytic: dict, L, M, pi, tol: float = 0.0, tol_dir: float = 1e-9, frame=None) -> dict:
    """Oriented ground shadow outline of the light silhouette loop (spec §5.6, contract
    §2.3 / §2.5 / §2.6).

    ``M`` is ``shadow_matrix(pi, L)`` for the same representative of ``L``; both are
    canonicalised together (:func:`canonical_factor`), so a positively scaled ``L`` (and
    its ``M``) gives the same outline.

    Steps: (1) :func:`silhouette`; (2) ground clip of every loop piece to ``pi^T X >= -tol``
    (like the Sutherland-Hodgman clip of §2.3; the exact ground crossings ``pi^T X = 0``
    are their own shadows and are joined by the lit boundary of the ground cross-section,
    :func:`_ground_chain`, as a chain of ground ``segment`` pieces -- a single straight
    chord when the cross-section has no lit boundary there); (3) ``w_S`` clip:
    ``w_S(X) = M[3] . X`` is ``A cos theta + B sin theta + C`` along an arc and linear along
    a segment; the parts with ``w_S <= tol_w`` are dropped (``tol_w = tol`` for a point
    light, ``tol_dir`` for a directional one) and the exact ``w_S = 0`` crossings become
    direction vertices with the §2.5 rule (``D = M X*``, ``w := 0``, normalised); (4) every
    surviving piece is mapped by ``M``.

    Returns ``{"pieces": [...], "unbounded": bool, "below_ground": bool, "empty": bool,
    "silhouette": sil, "warnings": [...]}`` with the pieces in loop order, each one of::

        {"segment": [S_a (4,), S_b (4,)], "which": "generator" | "ground", "ends", "gen",
                     "cut": (start_cut, end_cut)}                                    both w_S > tol_w
        {"conic_arc": {"E": 4x3, "rho": float, "T": M (4x4), "theta0", "theta1", "circle", "which",
                       "cut": (start_cut, end_cut)}}
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
    gaps = [it for it in items if "gap" in it]
    section = _ground_section(analytic, sil, L, pi, tol_w, tol, frame=frame) if cut else None
    for it in items:
        if "gap" in it:
            X_exit, X_entry = it["gap"]
            chain = [X_exit] + _ground_chain(section, X_exit, X_entry, len(gaps) == 1, frame) + [X_entry]
            for A, B in zip(chain[:-1], chain[1:]):
                pieces.append({"segment": (A, B), "which": "ground", "theta": None})
        else:
            pieces.append(it)
    if not items and cut:
        # the whole silhouette loop is below the receiver: the part above it has no silhouette
        # of its own and is wholly lit (or wholly unlit); its shadow is the lit cross-section
        ring = _ground_ring(section, frame)
        for A, B in zip(ring, ring[1:] + ring[:1]):
            pieces.append({"segment": (A, B), "which": "ground", "theta": None})
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
            out.append({"direction": _direction_from(M @ X_exit, F, hint_prev, frame), "role": "out"})
            out.append({"direction": _direction_from(M @ X_entry, F, hint_next, frame), "role": "in"})
        elif "segment" in it:
            A, B = it["segment"]
            out.append({"segment": [M @ A, M @ B], "which": it["which"], "theta": it.get("theta"),
                        "ends": it.get("ends"), "gen": it.get("gen"),
                        "cut": (bool(it.get("cut_start", False)), bool(it.get("cut_end", False)))})
        else:
            arc = it["arc"]
            out.append({"conic_arc": {"E": arc["E"], "rho": arc["rho"], "T": M,
                                      "theta0": arc["theta0"], "theta1": arc["theta1"],
                                      "circle": arc["circle"], "which": arc["which"],
                                      "cut": (bool(it.get("cut_start", False)), bool(it.get("cut_end", False)))}})
    result["pieces"] = out
    result["empty"] = False
    return result


def shadow_polygon_h(outline, samples_per_circle: int = 64, frame=None) -> dict:
    """Oriented homogeneous ground polygon of a :func:`shadow_outline` (contract §2.5 /
    §2.6): finite samples of the conic arcs (``samples_per_circle`` segments per full
    circle, proportionally fewer per arc, minimum 8), the segment endpoints and the
    direction vertices, with the §2.5 counter-clockwise arc-at-infinity subdivision
    (``ceil(delta / 60 deg)`` steps) between each outgoing and the following incoming
    direction.  The endpoint of a piece that was cut at ``w_S = tol`` is *replaced* by
    its direction vertex (it is never emitted as a finite vertex); on the way to such an
    end the arc is additionally sampled at ``1/2, 1/4, ... 1/2**ASYMPTOTE_REFINE`` of the
    last parameter step (``sources`` ``("arc", i, k)`` with fractional ``k``), because the
    shadow of the arc is a hyperbola branch whose curvature concentrates towards the
    asymptote: with uniform steps alone the polygon would leave the hyperbola a whole step
    before the crossing and close to the direction vertex with a straight chord (a visible
    kink).

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
            ks = list(range(1 if skip_start else 0, m))                        # k = 0 .. m-1 (end excluded)
            # an end cut at w_S = tol (replaced by a direction vertex) is approached geometrically:
            # the shadow is a hyperbola branch there, and uniform steps would leave the last finite
            # sample a whole step short of the asymptote (see the docstring)
            if skip_start:
                ks = [2.0 ** -j for j in range(ASYMPTOTE_REFINE, 0, -1)] + ks
            if is_dir(i + 1, "out"):
                ks = ks + [m - 2.0 ** -j for j in range(1, ASYMPTOTE_REFINE + 1)]
            th = th0 + (th1 - th0) * np.array(ks, dtype=np.float64) / m
            X = conic_point(arc["E"], th, arc["rho"])                           # (n, 4) world points
            S = X @ np.asarray(arc["T"], dtype=np.float64).T                   # S = M X
            for row, k in enumerate(ks):
                verts.append(S[row])
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
                if frame is None:   # the ground: literal v2 expressions (contract §5.1.2 [decision])
                    th0 = math.atan2(D[1], D[0])
                    th1 = math.atan2(d_in[1], d_in[0])
                else:               # counter-clockwise about n in the receiver frame
                    e1, e2 = (np.asarray(e, dtype=np.float64).reshape(3) for e in frame)
                    th0 = math.atan2(float(D[:3] @ e2), float(D[:3] @ e1))
                    th1 = math.atan2(float(np.asarray(d_in)[:3] @ e2), float(np.asarray(d_in)[:3] @ e1))
                delta = (th1 - th0) % TWO_PI
                if not math.isfinite(delta) or delta <= 1e-12:
                    delta = TWO_PI
                steps = max(1, int(math.ceil(delta / math.radians(ARC_STEP_DEG) - 1e-12)))
                for s in range(1, steps):
                    t = th0 + delta * s / steps
                    if frame is None:
                        verts.append(np.array([math.cos(t), math.sin(t), 0.0, 0.0]))
                    else:
                        v = math.cos(t) * e1 + math.sin(t) * e2
                        verts.append(np.array([v[0], v[1], v[2], 0.0]))
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


# ---------------------------------------------------------------------------
# pipeline hooks (M2 integration): stage A and stage B of a curved object
# ---------------------------------------------------------------------------

def plane_min(analytic: dict, pi) -> float:
    """Minimum of ``pi^T X`` over the solid primitive (contract §2.3 / §2.9
    ``OBJECT_BELOW_RECEIVER`` predicate ``pi^T P < -tol`` applied to the exact surface
    instead of the approximate mesh).  For a circle of radius ``r`` with unit normal ``a``
    the extreme value of ``n . x`` is ``n . c -/+ r sqrt(1 - (n . a)^2)``."""
    pi = np.asarray(pi, dtype=np.float64).reshape(4)
    n, d = pi[:3], float(pi[3])
    nn = float(np.linalg.norm(n))
    r = float(analytic["radius"])
    if analytic["kind"] == "sphere":
        return float(n @ analytic["centre"]) + d - r * nn
    a = _vec3(analytic["axis"])
    b = _vec3(analytic["base"])
    na = float(n @ a)
    circle_drop = r * math.sqrt(max(0.0, nn * nn - na * na))
    values = [float(n @ b) + d - circle_drop]
    top = b + float(analytic["height"]) * a
    if analytic["kind"] == "cylinder":
        values.append(float(n @ top) + d - circle_drop)
    else:
        values.append(float(n @ top) + d)
    return min(values)


def _cap_parallel(analytic: dict, L, tol: float) -> bool:
    """Spec §5.7 row 6 for the caps of a cylinder / cone: ``|n . (l - w p)| <= tol`` for
    the base (normal ``-a``) or the top (normal ``+a``) cap -> ``FACE_PARALLEL_TO_LIGHT``."""
    if analytic["kind"] == "sphere":
        return False
    a = _vec3(analytic["axis"])
    b = _vec3(analytic["base"])
    L = np.asarray(L, dtype=np.float64).reshape(4)
    caps = [(-a, b)]
    if analytic["kind"] == "cylinder":
        caps.append((a, b + float(analytic["height"]) * a))
    for n, p in caps:
        v = float(n @ (L[:3] - L[3] * p))
        if abs(v) <= tol:
            return True
    return False


def _empty_shadow_record(oid: str, lid: str, receiver_id: str) -> dict:
    return {"light": lid, "receiver": receiver_id, "object": oid, "kind": "curved",
            "vertex_ids": np.zeros(0, dtype=np.int64), "keep": np.zeros(0, dtype=bool),
            "P_world": np.zeros((0, 3)), "S_world": np.zeros((0, 3)), "Q_world": np.zeros((0, 3)),
            "w_S": np.zeros(0), "shadow_names": [], "foot_names": [], "vertex_names": [],
            "ground_points": [], "loops": [], "unbounded": False, "pieces": []}


_SIL_INDEX = {0: 0, 1: 2, 2: 1, 3: 3}   # quarter turn k (theta = k pi/2) -> <obj>.sil.<index> (+e1, +e2, -e1, -e2)


def _loop_entries(poly: dict, pieces: list, oid: str, lid: str, keep_names: set, samples_per_circle: int,
                  suffix: str = "") -> tuple:
    """Contract §3.1 outline entries of a curved shadow polygon (see the pipeline docstring):
    direction vertices inline, the uncut shadows of generator endpoints / apex / silhouette
    quarter points by their construction-point shadow name, every other finite vertex as a
    ground point ``<obj>.s<k>.<light>`` (its own shadow and foot, no construction ray).
    Returns ``(entries, ground_points)`` with ``ground_points = [(name, xyz), ...]``.

    M4 (contract §5.1.3.3 / §5.1.4): ``suffix`` (``".<receiver id>"`` for receivers other than
    ``receivers[0]``) ends every shadow / ground-point name, and the ``("bounds", ...)`` rows of the
    bounds clip are ground points of the receiver."""
    V = poly["vertices"]
    n = len(pieces)
    ground: list = []
    entries: list = []

    def ground_name(row):
        X = V[row]
        name = f"{oid}.s{len(ground)}.{lid}{suffix}"
        ground.append((name, X[:3] / X[3]))
        return name

    def end_name(piece, end):
        if "segment" not in piece or piece.get("which") != "generator" or piece.get("ends") is None:
            return None
        if piece["cut"][end]:
            return None
        e = piece["ends"][end]
        pname = f"{oid}.apex" if e == "apex" else f"{oid}.g{piece['gen']}.{e}"
        return f"{pname}.shadow.{lid}{suffix}" if pname in keep_names else None

    for row, src in enumerate(poly["sources"]):
        kind = src[0]
        if kind == "bounds":          # a bounds-clip crossing or anchor: a point of the receiver
            entries.append(ground_name(row))
            continue
        if kind in ("dir", "inf"):
            D = V[row]
            entries.append({"direction": [float(D[0]) + 0.0, float(D[1]) + 0.0, float(D[2]) + 0.0]})
            continue
        name = None
        if kind == "segment":
            name = end_name(pieces[src[1]], src[2])
        else:  # ("arc", i, k): sample k of conic arc i
            i, k = src[1], src[2]
            arc = pieces[i]["conic_arc"]
            if k == 0 and not arc["cut"][0]:
                name = end_name(pieces[(i - 1) % n], 1)
            if name is None and arc["which"] == "silhouette":
                th0, th1 = arc["theta0"], arc["theta1"]
                m = sample_count(th0, th1, samples_per_circle)
                theta = th0 + (th1 - th0) * k / m                  # same formula as shadow_polygon_h
                q = theta / (0.5 * math.pi)
                qi = int(round(q))
                if abs(q - qi) <= 1e-12:
                    pname = f"{oid}.sil.{_SIL_INDEX[qi % 4]}"
                    if pname in keep_names:
                        name = f"{pname}.shadow.{lid}{suffix}"
        entries.append(name if name is not None else ground_name(row))
    return entries, ground


def _bounds_clip_pieces(pieces: list, psi, tol: float) -> list:
    """Contract §5.1.4: the ``conic_arc`` pieces of a shadow outline restricted, in closed form, to the
    bounds of a receiver: each row ``psi_k`` gives ``psi_k . X(theta) = A cos theta + B sin theta + C``
    (``functional_coeffs(psi_k, T E, rho)``) and the surviving sub-arcs are those where every row is
    non-negative (``sub_arcs_where_nonnegative(A, B, C, theta0, theta1, tol)``); a piece may split into
    several pieces, each with its own arc (stored counter-clockwise, ``theta0 < theta1``).  Only the
    arc pieces are returned: they are what stage B draws as ``shadows[].conics`` (the filled polygon is
    the bounds-clipped ``shadow_polygon_h``)."""
    out = []
    Psi = np.asarray(psi, dtype=np.float64).reshape(-1, 4)
    for piece in pieces:
        if "conic_arc" not in piece:
            continue
        ca = piece["conic_arc"]
        TE = np.asarray(ca["T"], dtype=np.float64) @ ca["E"]
        intervals = [list(_ccw_range(float(ca["theta0"]), float(ca["theta1"])))]
        for row in Psi:
            A, B, C = functional_coeffs(row, TE, ca["rho"])
            intervals = _intersect_arcs(intervals, A, B, C, tol)
            if not intervals:
                break
        for a, b in intervals:
            out.append({"conic_arc": dict(ca, theta0=float(a), theta1=float(b))})
    return out


def stage_a_object(obj: dict, lights: list, receiver: dict, tol: float, warnings: list) -> list:
    """Stage A of one curved object on one receiver (spec §5.6, contract §2.6 / §2.7 / §3 / §5.1.4): per
    light the silhouette, terminator, construction points and the shadow record consumed by the
    pipeline's ``_project_shadow`` / ``compose`` exactly like a polyhedral record.  Called once per
    receiver, in receiver order.

    ``lights`` are the pipeline's light records of that receiver (``{id, L, M, F, active, tol_lit,
    tol_w}``), ``receiver`` the stage-A receiver record (``{id, pi, bounded, frame, bounds, psi,
    suffix}``), ``tol`` the stage-A length tolerance.  Camera-independent per-(receiver, light) data is
    stored on the object as ``obj["curved"][<receiver id>][<light id>]``::

        {"silhouette": silhouette(...), "terminator": terminator(...),
         "points": {name: X4} (construction_points), "outline": shadow_outline(...) | None,
         "polygon": shadow_polygon_h(...) | None (bounds-clipped on a bounded receiver),
         "conic_pieces": the outline's conic arcs (bounds-clipped on a bounded receiver) | None}

    so that :func:`stage_b_object` can build the image maps ``H = P E`` / ``H = P M E``.
    Warnings (``LIGHT_INSIDE_OBJECT``, ``VERTEX_NOT_BELOW_LIGHT``, ``OBJECT_BELOW_RECEIVER``,
    ``FACE_PARALLEL_TO_LIGHT``) are appended with ``ids == [obj id]``; on a bounded receiver the two
    ground codes are dropped (the clip to the receiver's half-space is silent, contract §5.1.3).
    Returns the list of shadow records (one per light)."""
    an = obj["analytic"]
    oid = obj["id"]
    rid = receiver["id"]
    pi = np.asarray(receiver["pi"], dtype=np.float64).reshape(4)
    frame = receiver.get("frame")
    bounded = bool(receiver.get("bounded"))
    sfx = receiver.get("suffix", "")
    store = obj.setdefault("curved", {})
    per = store.setdefault(rid, {})
    records = []
    if not bounded and plane_min(an, pi) < -tol:
        warnings.append(make_warning("OBJECT_BELOW_RECEIVER", [oid]))
    for lt in lights:
        lid = lt["id"]
        L = np.asarray(lt["L"], dtype=np.float64)
        tol_L = lt["tol_lit"]
        sil = silhouette(an, L, tol_L)
        pts = construction_points(an, L, tol_L, oid)
        term = terminator(an, L, tol_L)
        if _cap_parallel(an, L, tol_L):
            warnings.append(make_warning("FACE_PARALLEL_TO_LIGHT", [oid]))
        for w in sil["warnings"]:
            warnings.append(make_warning(w["code"], [oid], w["message"]))
        cd = {"silhouette": sil, "terminator": term, "points": pts, "outline": None, "polygon": None,
              "conic_pieces": None}
        per[lid] = cd
        rec = _empty_shadow_record(oid, lid, rid)
        records.append(rec)
        if not lt["active"]:
            continue
        out = shadow_outline(an, L, lt["M"], pi, tol, TOL_DIR, frame=frame)
        if not bounded:
            for w in out["warnings"]:
                warnings.append(make_warning(w["code"], [oid], w["message"]))
        else:
            for w in out["warnings"]:
                if w["code"] not in ("OBJECT_BELOW_RECEIVER", "VERTEX_NOT_BELOW_LIGHT"):
                    warnings.append(make_warning(w["code"], [oid], w["message"]))
        poly = shadow_polygon_h(out, frame=frame)
        conic_pieces = out["pieces"]
        if bounded:
            V, src = clip_polygon_bounds(poly["vertices"], poly["sources"], receiver["psi"], receiver["bounds"], tol)
            poly = {"vertices": V, "unbounded": False, "sources": src}
            conic_pieces = _bounds_clip_pieces(out["pieces"], receiver["psi"], tol)
        cd["outline"], cd["polygon"], cd["conic_pieces"] = out, poly, conic_pieces
        names = list(pts)
        P4 = np.array([pts[nm] for nm in names], dtype=np.float64).reshape(-1, 4)
        w_S = np.asarray(shadow_w(pi, L, P4), dtype=np.float64).reshape(-1)
        finite = w_S > lt["tol_w"]
        above = (P4 @ pi) >= -tol
        keep = finite & above
        if not bounded and names and not bool(np.all(finite)):
            warnings.append(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]))
        S4 = P4 @ np.asarray(lt["M"], dtype=np.float64).T                 # S = M P, spec §5.2
        w_safe = np.where(keep, w_S, 1.0)
        S_world = np.where(keep[:, None], S4[:, :3] / w_safe[:, None], 0.0)
        Q4 = foot(pi, P4) if names else np.zeros((0, 4))                  # Q, spec §5.3
        Q_world = Q4[:, :3] / Q4[:, 3:4] if names else np.zeros((0, 3))
        keep_names = {nm for nm, k in zip(names, keep.tolist()) if k}
        loops = []
        ground: list = []
        if poly["vertices"].shape[0] >= 3:
            entries, ground = _loop_entries(poly, out["pieces"], oid, lid, keep_names, 64, suffix=sfx)
            loops.append({"vertices": poly["vertices"], "sources": poly["sources"], "entries": entries,
                          "unbounded": bool(poly["unbounded"])})
        rec.update({
            "keep": keep,
            "P_world": P4[:, :3].copy(),
            "S_world": S_world,
            "Q_world": Q_world,
            "w_S": w_S,
            "shadow_names": [f"{nm}.shadow.{lid}{sfx}" for nm in names],
            "foot_names": [f"{nm}.foot{sfx}" for nm in names],
            "vertex_names": names,
            "ground_points": ground,
            "loops": loops,
            "unbounded": bool(poly["unbounded"]) if loops else False,
            "pieces": out["pieces"],
        })
        if bounded:   # rays / checks only for shadow points inside the bounds (contract §5.1.3.3)
            inside = np.all(S4 @ np.asarray(receiver["psi"]).T >= -tol * np.abs(S4[:, 3:4]), axis=1) \
                if names else np.zeros(0, dtype=bool)
            rec["ray_keep"] = keep & inside
    return records


def near_functional(cam: dict) -> np.ndarray:
    """``f_nu`` with ``f_nu . X == nu(X)`` (contract §2.2): ``(forward, -(forward . C + near))``."""
    fwd = np.asarray(cam["forward"], dtype=np.float64)
    return np.append(fwd, -(float(fwd @ cam["C"]) + float(cam["near"])))


def _intersect_arcs(intervals: list, A: float, B: float, C: float, tol: float) -> list:
    """Restrict a list of parameter intervals to ``A cos theta + B sin theta + C > tol``."""
    out = []
    for a, b in intervals:
        out.extend(sub_arcs_where_nonnegative(A, B, C, a, b, tol))
    return out


def arc_record(circle: dict, theta0: float, theta1: float, full: bool, T, cam: dict, f_nu, rect_rows,
               map: str, which: str, back: bool = False) -> dict | None:
    """Stage-B record of one circle arc drawn through the map ``H = P T E`` (``T = M`` for a
    ground shadow, ``None`` = identity for an image circle; contract §2.6).

    Near clipping is closed form: ``nu(X(theta)) = A cos theta + B sin theta + C`` with
    ``(A, B, C) = functional_coeffs(f_nu, T E, rho)``; the visible sub-arcs (``nu >= 0``) are
    then restricted to the extended canvas rectangle, also in closed form, with the four
    rectangle functionals on ``H``.  Returns ``None`` when nothing of the arc is in front of
    the near plane, otherwise::

        {"conic": 3x3 list, "kind", "arc": {theta0, theta1} | None, "circle", "map", "sampled",
         "which", "back", "H": 3x3, "rho", "whole_circle": bool (full circle, wholly in front),
         "near_cut": bool, "visible": [[a, b], ...] (after the rectangle clip),
         "front": [[a, b], ...] (after the near clip only)}
    """
    E = circle_embedding(circle)
    rho = float(circle["radius"])
    TE = E if T is None else np.asarray(T, dtype=np.float64) @ E
    H = np.asarray(cam["P"], dtype=np.float64) @ TE
    lo, hi = _ccw_range(float(theta0), float(theta1))
    A, B, C = functional_coeffs(f_nu, TE, rho)
    front = sub_arcs_where_nonnegative(A, B, C, lo, hi, 0.0)
    if not front:
        return None
    eps = 1e-12
    whole_front = len(front) == 1 and front[0][0] <= lo + eps and front[0][1] >= hi - eps
    near_cut = not whole_front
    is_full = bool(full) and hi - lo >= TWO_PI - eps and whole_front
    entry = conic_entry(circle, H, None if is_full else (front[0][0], front[-1][1]) if len(front) == 1 else None,
                        map)
    if len(front) > 1:  # two visible sub-arcs: report the CCW range of their union (hull), draw each
        entry["arc"] = {"theta0": float(front[0][0]) + 0.0, "theta1": float(front[-1][1]) + 0.0}
    visible = list(front)
    for row in rect_rows:
        A2, B2, C2 = functional_coeffs(row, H, rho)
        visible = _intersect_arcs(visible, A2, B2, C2, 0.0)
    entry.pop("cond", None)
    entry.update({
        "which": which, "back": bool(back), "H": H, "rho": rho,
        "TE": TE,       # M4 (contract §5.1.6.4): the 4-D map X(theta) = T E (rho cos, rho sin, 1) for stage C
        "whole_circle": is_full, "near_cut": near_cut,
        "visible": [[float(a), float(b)] for a, b in visible],
        "front": [[float(a), float(b)] for a, b in front],
    })
    return entry


def _project_points(cam: dict, names: list, X4: np.ndarray) -> dict:
    """Image points and near-plane flags of ``(n, 4)`` named points through the spec §9 camera
    interface (``camera.project`` / ``camera.nu``), never re-implemented here."""
    from .camera import nu, project
    return {"names": names, "world": X4[:, :3].copy(), "image_h": project(cam, X4), "behind": nu(cam, X4) < 0.0}


def _project_segments(cam: dict, A4: np.ndarray, B4: np.ndarray, rect) -> tuple:
    """Drawing pipeline of contract §2.2 for ``(m, 4)`` segment endpoints -> ``(seg_h (m,2,3), keep, behind)``."""
    from .camera import clip_segments_near, clip_segments_rect_h, nu, project
    if A4.shape[0] == 0:
        return np.zeros((0, 2, 3)), np.zeros(0, dtype=bool), np.zeros(0, dtype=bool)
    behind = (nu(cam, A4) < 0.0) | (nu(cam, B4) < 0.0)
    A, B, keep = clip_segments_near(cam, A4, B4)
    A2, B2 = project(cam, A), project(cam, B)
    A3, B3, keep_rect = clip_segments_rect_h(A2, B2, rect)
    return np.stack([A3, B3], axis=1), keep & keep_rect, behind


def _stage_b_prepare(obj: dict, cam: dict, tol: float) -> dict:
    """Everything of :func:`stage_b_object` except the projection of the named points and of the
    straight segments, which :func:`_stage_b_finish` receives from one batched call for all curved
    objects of the scene (spec §8).  Returns the job: the arc records, the point names / 4-vectors
    and the segment endpoints with the slots they belong to."""
    from .camera import rect_functionals
    an = obj["analytic"]
    oid = obj["id"]
    f_nu = near_functional(cam)
    rect_rows = rect_functionals(cam["rect"])
    behind_any = False
    sampled_any = False
    names: list = []
    X4: list = []

    def add_point(name, X):
        if name not in names:
            names.append(name)
            X4.append(np.asarray(X, dtype=np.float64).reshape(4))

    seg_A, seg_B, slots = [], [], []          # straight segments: endpoints and (target dict) per row

    # --- objects layer: camera outline (contract §2.10)
    co = camera_outline(an, cam["C"], tol)
    gen_edges = []
    for k, g in enumerate(co["generators"]):
        a_name = f"{oid}.og{k}.base"
        b_name = f"{oid}.og{k}.top"          # the apex for a cone (both generators end there)
        add_point(a_name, _point4(g["base"]))
        add_point(b_name, _point4(g["top"]))
        edge = {"from": a_name, "to": b_name, "segment_h": None, "keep": False}
        gen_edges.append(edge)
        seg_A.append(_point4(g["base"]))
        seg_B.append(_point4(g["top"]))
        slots.append(edge)
    outline_arcs = []
    if co["circle"] is not None:
        a = arc_record(co["circle"], 0.0, TWO_PI, True, None, cam, f_nu, rect_rows, "image", "silhouette")
        if a is None:
            behind_any = True
        else:
            outline_arcs.append(a)
    for arc in co["cap_arcs"]:
        a = arc_record(arc["circle"], arc["theta0"], arc["theta1"], arc["full"], None, cam, f_nu, rect_rows,
                       "image", arc["which"], back=arc["back"])
        if a is None:
            behind_any = True
        else:
            outline_arcs.append(a)
    # --- per light: construction points, terminator (receiver independent: taken from the first
    # receiver's records); per (light, receiver): cast-shadow conics (contract §5.1.4)
    terminator_out: dict = {}
    shadow_arcs: dict = {}
    curved = obj.get("curved", {})
    rids = list(curved)
    for lid, cd in (curved[rids[0]].items() if rids else ()):
        for nm, X in cd["points"].items():
            add_point(nm, X)
        items = []
        for t in cd["terminator"]:
            if "segment" in t:
                A4, B4 = t["segment"]
                it = {"segment": _terminator_segment_names(oid, t, cd["silhouette"]), "segment_h": None, "keep": False,
                      "X4": (A4, B4)}   # M4 (contract §5.1.6.4): the stage-A world endpoints for stage C
                items.append(it)
                seg_A.append(A4)
                seg_B.append(B4)
                slots.append(it)
            else:
                ca = t["circle_arc"]
                a = arc_record(ca["circle"], ca["theta0"], ca["theta1"], ca["full"], None, cam, f_nu, rect_rows,
                               "image", ca["which"])
                if a is None:
                    behind_any = True
                else:
                    items.append(a)
        terminator_out[lid] = items
    for rid, lid, cd in ((rid, lid, cd) for rid in rids for lid, cd in curved[rid].items()):
        arcs = []
        out = cd["outline"]
        if out is not None:
            pieces = cd.get("conic_pieces")
            for piece in (out["pieces"] if pieces is None else pieces):
                if "conic_arc" not in piece:
                    continue
                ca = piece["conic_arc"]
                lo, hi = _ccw_range(ca["theta0"], ca["theta1"])
                a = arc_record(ca["circle"], lo, hi, hi - lo >= TWO_PI - 1e-12, ca["T"], cam, f_nu, rect_rows,
                               "shadow", ca["which"])
                if a is None:
                    behind_any = True
                else:
                    arcs.append(a)
        shadow_arcs[(lid, rid)] = arcs
    for group in ([outline_arcs] + list(terminator_out.values()) + list(shadow_arcs.values())):
        for a in group:
            if "segment" in a:
                continue
            behind_any = behind_any or a["near_cut"]
            sampled_any = sampled_any or a["sampled"]
    return {
        "id": oid, "names": names, "X4": np.array(X4, dtype=np.float64).reshape(-1, 4),
        "seg_A": np.array(seg_A, dtype=np.float64).reshape(-1, 4), "seg_B": np.array(seg_B, dtype=np.float64).reshape(-1, 4),
        "slots": slots, "gen_edges": gen_edges, "outline_arcs": outline_arcs, "terminator": terminator_out,
        "shadow_arcs": shadow_arcs, "camera_inside": bool(co["camera_inside"]),
        "behind_any": behind_any, "sampled_any": sampled_any,
    }


def _stage_b_finish(job: dict, rec: dict, pts: dict, seg_h, keep, behind, warnings: list) -> None:
    """Fill the stage-B record from a job and its projected points / segments (see :func:`_stage_b_prepare`)."""
    behind_any = job["behind_any"] or bool(np.any(pts["behind"])) or bool(np.any(behind))
    keep_list = keep.tolist()
    for k, slot in enumerate(job["slots"]):
        slot["segment_h"], slot["keep"] = seg_h[k], keep_list[k]
    if behind_any:
        warnings.append(make_warning("POINT_BEHIND_CAMERA", [job["id"]]))
    if job["sampled_any"]:
        warnings.append(make_warning("CONIC_SAMPLED", [job["id"]]))
    rec.update({
        "point_names": job["names"],
        "world": pts["world"],
        "image_h": pts["image_h"],
        "depth": pts["image_h"][:, 2],
        "behind": pts["behind"],
        "gen_edges": job["gen_edges"],
        "outline_arcs": job["outline_arcs"],
        "terminator": job["terminator"],
        "shadow_arcs": job["shadow_arcs"],
        "camera_inside": job["camera_inside"],
        "form_faces": [],
        "form_polygons": [],
    })


def stage_b_objects(objs: list, recs: list, cam: dict, tol: float, warnings: list) -> None:
    """Stage B of several curved objects at once (spec §8): :func:`stage_b_object` for each of
    ``objs`` into the matching ``recs``, with the named points and the straight segments
    (outline generators, terminator generators) of all objects projected in one batched call."""
    if not objs:
        return
    jobs = [_stage_b_prepare(obj, cam, tol) for obj in objs]
    X4 = np.concatenate([job["X4"] for job in jobs], axis=0)
    pts = _project_points(cam, None, X4)
    seg_h, keep, behind = _project_segments(cam, np.concatenate([job["seg_A"] for job in jobs], axis=0),
                                            np.concatenate([job["seg_B"] for job in jobs], axis=0), cam["rect"])
    p0 = s0 = 0
    for job, rec in zip(jobs, recs):
        p1, s1 = p0 + job["X4"].shape[0], s0 + job["seg_A"].shape[0]
        sub = {"names": job["names"], "world": pts["world"][p0:p1], "image_h": pts["image_h"][p0:p1],
               "behind": pts["behind"][p0:p1]}
        _stage_b_finish(job, rec, sub, seg_h[s0:s1], keep[s0:s1], behind[s0:s1], warnings)
        p0, s0 = p1, s1


def stage_b_object(obj: dict, rec: dict, cam: dict, tol: float, warnings: list) -> None:
    """Stage B of one curved object (contract §2.2 / §2.6 / §2.7 / §2.10): adds to ``rec``
    (the pipeline's per-object stage-B record) in place::

        point_names, world, image_h, depth, behind   named points: the §2.7 construction points of
                                                     every light plus the camera outline generator
                                                     endpoints <obj>.og<k>.base / .top (a cone's .top
                                                     is its apex; these names are camera dependent)
        gen_edges     [{"from", "to", "segment_h": (2, 3), "keep": bool}]   camera outline generators
        outline_arcs  [arc_record ...]   cap arcs (split at the outline generators, back flag) /
                                         sphere outline circle, map "image"
        terminator    {light id: [{"segment": [name, name], "segment_h", "keep"} | arc_record]}
        shadow_arcs   {light id: [arc_record ...]}   cast-shadow conic arcs, H = P M E, map "shadow"

    Every arc is near-clipped and rectangle-clipped in closed form (:func:`arc_record`);
    every segment goes through the normal segment pipeline.  Warnings: ``POINT_BEHIND_CAMERA``
    (a named point, a generator endpoint or part of a drawn circle behind the near plane) and
    ``CONIC_SAMPLED`` (some conic degenerate or ill-conditioned), ids ``[obj id]``.
    The pipeline calls :func:`stage_b_objects`, which does the same for all curved objects of
    a scene with the segment and point projections batched."""
    stage_b_objects([obj], [rec], cam, tol, warnings)


def _terminator_segment_names(oid: str, t: dict, sil: dict) -> list:
    """Names of the two construction points at the ends of a terminator generator entry."""
    theta = t.get("theta")
    gen = None
    for k, g in enumerate(sil["generators"]):
        if theta is not None and g["theta"] == theta:
            gen = k
            break
    A4, B4 = t["segment"]
    if gen is None:
        return [f"{oid}.g0.base", f"{oid}.g0.top"]

    def end_of(X):
        g = sil["generators"][gen]
        # numpy.allclose verdict (|a - b| <= 1e-8 + 1e-5 |b| per component) in plain scalar arithmetic
        if all(abs(float(x) - float(b)) <= 1e-8 + 1e-5 * abs(float(b)) for x, b in zip(X[:3], g["base"])):
            return f"{oid}.g{gen}.base"
        return f"{oid}.apex" if sil["kind"] == "cone" else f"{oid}.g{gen}.top"
    return [end_of(A4), end_of(B4)]

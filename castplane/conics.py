"""3x3 conic mathematics for curved primitives (spec §5.6, contract §2.6).

A conic is a symmetric 3x3 matrix ``C`` with the points ``x = (x, y, 1)`` satisfying
``x^T C x = 0``.  A circle of radius ``rho`` in its own plane is ``C = diag(1, 1, -rho^2)``
in local coordinates ``(x, y, 1)``; the embedding ``E = [e1 e2 c; 0 0 1]`` (4x3) maps
local circle coordinates to homogeneous world points.  Any projective map ``H`` (3x3)
sends the circle to the conic ``C' = adj(H)^T C adj(H)`` (adjugate instead of inverse, so
a singular ``H`` never raises; the result is then degenerate).

All helpers are pure numpy functions; sampling is only used by the output stage.
"""

from __future__ import annotations

import math

import numpy as np

__all__ = [
    "circle_matrix",
    "embed_circle",
    "adjugate3",
    "transform_conic",
    "ground_conic_map",
    "normalize_conic",
    "centred_conic",
    "classify",
    "classify_and_condition",
    "condition_number",
    "is_sampled",
    "ellipse_params",
    "conic_point",
    "sample_arc",
    "sample_count",
    "functional_coeffs",
    "sub_arcs_where_nonnegative",
    "arc_svg_flags",
    "circle_frame",
    "circle_record",
    "circle_embedding",
    "circle_point",
    "conic_entry",
    "ellipse_arc_params",
    "TWO_PI",
    "ARC_MIN_SPAN",
    "SAMPLES_PER_CIRCLE",
    "MIN_ARC_SAMPLES",
    "COND_MAX",
    "CLASSIFY_TOL",
]

TWO_PI = 2.0 * math.pi

# sub-arcs shorter than this (radians) are numerically meaningless and are dropped
# (they would become zero-length SVG arcs); see sub_arcs_where_nonnegative.
ARC_MIN_SPAN = 1e-12

#: Contract §2.6 sampling rule (output stage only): 64 segments per full circle,
#: proportionally fewer for arcs, minimum 8.
SAMPLES_PER_CIRCLE = 64
MIN_ARC_SAMPLES = 8
#: Contract §2.6 / spec §11.3: condition number above which a conic is emitted as a
#: sampled polyline (``CONIC_SAMPLED``).
COND_MAX = 1e8
#: Contract §2.6: threshold on the normalised determinants used by :func:`classify`.
CLASSIFY_TOL = 1e-12


def circle_matrix(rho: float) -> np.ndarray:
    """Spec §5.6 / contract §2.6: circle of radius ``rho`` in local ``(x, y, 1)``,
    ``C = diag(1, 1, -rho^2)``."""
    rho = float(rho)
    return np.diag([1.0, 1.0, -rho * rho]).astype(np.float64)


def embed_circle(centre, e1, e2) -> np.ndarray:
    """Contract §2.6: embedding ``E = [e1 e2 c; 0 0 1]`` (4x3) of the circle plane with
    orthonormal basis ``e1, e2`` and centre ``c`` into homogeneous world coordinates:
    ``X = E (x, y, 1)``."""
    c = np.asarray(centre, dtype=np.float64).reshape(3)
    e1 = np.asarray(e1, dtype=np.float64).reshape(3)
    e2 = np.asarray(e2, dtype=np.float64).reshape(3)
    E = np.zeros((4, 3), dtype=np.float64)
    E[:3, 0] = e1
    E[:3, 1] = e2
    E[:3, 2] = c
    E[3, 2] = 1.0
    return E


def adjugate3(H) -> np.ndarray:
    """Adjugate of a 3x3 matrix in closed form (``adj(H) = det(H) H^{-1}`` when
    invertible; always defined)."""
    H = np.asarray(H, dtype=np.float64).reshape(3, 3)
    a, b, c = H[0]
    d, e, f = H[1]
    g, h, i = H[2]
    return np.array([
        [e * i - f * h, -(b * i - c * h), b * f - c * e],
        [-(d * i - f * g), a * i - c * g, -(a * f - c * d)],
        [d * h - e * g, -(a * h - b * g), a * e - b * d],
    ], dtype=np.float64)


def transform_conic(C, H) -> np.ndarray:
    """Spec §5.6 ``C' = H^{-T} C H^{-1}`` written with the adjugate (contract §2.6):
    ``C' = adj(H)^T C adj(H)``, which equals ``det(H)^2 H^{-T} C H^{-1}`` when ``H`` is
    invertible and never raises otherwise.  The result is symmetrised."""
    C = np.asarray(C, dtype=np.float64).reshape(3, 3)
    A = adjugate3(H)
    Cp = A.T @ C @ A
    return 0.5 * (Cp + Cp.T)


def ground_conic_map(M, E) -> np.ndarray:
    """3x3 map from circle coordinates to ground ``(x, y, w)`` coordinates for the ground
    receiver ``z = 0``: the rows ``x, y, w`` of ``M E`` (the ``z`` row of ``M E`` is zero
    because ``pi^T M = 0``).  Used for ground-plane shadow conics; the image conic uses
    ``H = P M E`` (contract §2.6)."""
    ME = np.asarray(M, dtype=np.float64).reshape(4, 4) @ np.asarray(E, dtype=np.float64).reshape(4, 3)
    return ME[[0, 1, 3], :]


def normalize_conic(C) -> np.ndarray:
    """Contract §2.6: symmetrise and divide by the max-|entry| so that entry becomes +1
    (first occurrence in row-major order on ties).  The zero matrix is returned as is."""
    C = np.asarray(C, dtype=np.float64).reshape(3, 3)
    C = 0.5 * (C + C.T)
    flat = np.abs(C).ravel()
    idx = int(np.argmax(flat))
    m = C.ravel()[idx]
    if m == 0.0 or not math.isfinite(m):
        return C.copy()
    return C / m


def _parabola_vertex(A: np.ndarray, b: np.ndarray, c: float):
    """Vertex of the parabola ``x^T A x + 2 b^T x + c = 0`` (``A`` singular, rank 1).

    With ``n`` the unit eigenvector of the non-zero eigenvalue ``lam`` of ``A`` and ``m``
    the axis direction (``A m = 0``), write ``x = alpha n + beta m``.  The gradient
    ``A x + b = (lam alpha + b.n) n + (b.m) m`` is parallel to the axis at the vertex, so
    ``alpha = -(b.n) / lam``, and the vertex lies on the conic, so
    ``beta = -(lam alpha^2 + 2 (b.n) alpha + c) / (2 b.m)``.  Returns ``None`` when
    ``|b.m| <= CLASSIFY_TOL`` (no linear term along the axis: the conic is a pair of
    parallel lines or empty, i.e. degenerate, and has no vertex)."""
    p, q, r = float(A[0, 0]), float(A[0, 1]), float(A[1, 1])
    half = 0.5 * (p + r)
    rad = math.hypot(0.5 * (p - r), q)
    lam1, lam2 = half + rad, half - rad
    lam = lam1 if abs(lam1) >= abs(lam2) else lam2
    if lam == 0.0:
        return None
    if abs(q) > 1e-15 * max(1.0, abs(p), abs(r)):
        n = np.array([q, lam - p], dtype=np.float64)
    elif abs(p) >= abs(r):
        n = np.array([1.0, 0.0])
    else:
        n = np.array([0.0, 1.0])
    n = n / float(np.linalg.norm(n))
    m = np.array([-n[1], n[0]], dtype=np.float64)
    bn, bm = float(b @ n), float(b @ m)
    if abs(bm) <= CLASSIFY_TOL:
        return None
    alpha = -bn / lam
    beta = -(lam * alpha * alpha + 2.0 * bn * alpha + c) / (2.0 * bm)
    return alpha * n + beta * m


def centred_conic(C, normalized: bool = False):
    """Contract §2.6: the conic translated to its own centre, ``C_c = T^T C T`` with
    ``T = [[I, centre], [0, 1]]`` and ``centre = -A^{-1} C[0:2, 2]`` (``A`` the upper-left
    2x2 block), then max-normalised.  When ``A`` is singular within ``CLASSIFY_TOL``
    (a parabola) the conic has no centre and is translated to its **vertex** instead
    (:func:`_parabola_vertex`), which keeps the verdict translation invariant for
    parabolas too (contract §2.6 **[decision]**: classification must be translation
    invariant; a parabola far from the origin would otherwise read as degenerate /
    ill-conditioned because its entries grow with the square of the distance).  When no
    translation point exists (zero 2x2 block, or a parabola without a linear term along
    its axis -- both degenerate) the normalised conic itself is returned.

    Returns ``(C_c (3x3), point (2,) | None)`` with ``point`` the centre (ellipse /
    hyperbola), the vertex (parabola) or ``None`` when no translation was applied.
    Degeneracy and conditioning are judged on ``C_c`` so that the verdict is translation
    invariant (a 0.3 m circle 50 m from the origin is a healthy ellipse).  ``normalized``
    says that ``C`` already is the output of :func:`normalize_conic` (idempotent, so the
    flag only saves the call)."""
    N = C if normalized else normalize_conic(C)
    if not np.all(np.isfinite(N)):
        return N, None
    A = N[:2, :2]
    b = N[:2, 2]
    amax = float(np.max(np.abs(A)))
    if amax == 0.0:
        return N, None
    An = A / amax
    det_n = float(An[0, 0] * An[1, 1] - An[0, 1] * An[1, 0])
    if abs(det_n) <= CLASSIFY_TOL:
        point = _parabola_vertex(A, b, float(N[2, 2]))
        if point is None or not np.all(np.isfinite(point)):
            return N, None
    else:
        detA = float(A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0])
        point = -np.array([A[1, 1] * b[0] - A[0, 1] * b[1],
                           -A[1, 0] * b[0] + A[0, 0] * b[1]], dtype=np.float64) / detA
    T = np.array([[1.0, 0.0, point[0]], [0.0, 1.0, point[1]], [0.0, 0.0, 1.0]], dtype=np.float64)
    Cc = T.T @ N @ T
    return normalize_conic(Cc), point


def classify(C, tol: float = CLASSIFY_TOL) -> str:
    """Contract §2.6 (translation-invariant classification): let ``A`` be the upper-left
    2x2 block of the max-normalised conic, itself normalised by its max-|entry|;
    ``kind`` is ``parabola`` when ``|det A| <= tol``, otherwise ``ellipse`` / ``hyperbola``
    by the sign of ``det A``.  Degeneracy is judged on the conic translated to its centre
    (its vertex for a parabola, :func:`centred_conic`): ``|det C_c| <= tol`` ->
    ``degenerate``.  A zero 2x2 block (a line or an empty conic) is ``degenerate`` too."""
    N = normalize_conic(C)
    if not np.all(np.isfinite(N)):
        return "degenerate"
    A = N[:2, :2]
    amax = float(np.max(np.abs(A)))
    if amax == 0.0:
        return "degenerate"
    An = A / amax
    det2 = float(An[0, 0] * An[1, 1] - An[0, 1] * An[1, 0])
    Cc, _centre = centred_conic(N)
    det3 = float(np.linalg.det(Cc))
    if not math.isfinite(det3) or abs(det3) <= tol:
        return "degenerate"
    if abs(det2) <= tol:
        return "parabola"
    return "ellipse" if det2 > 0.0 else "hyperbola"


def classify_and_condition(C, tol: float = CLASSIFY_TOL, normalized: bool = False) -> tuple[str, float]:
    """:func:`classify` and :func:`condition_number` from a single centred conic (same results);
    ``normalized`` as in :func:`centred_conic`."""
    N = C if normalized else normalize_conic(C)
    if not np.all(np.isfinite(N)):
        return "degenerate", math.inf
    A = N[:2, :2]
    amax = float(np.max(np.abs(A)))
    if amax == 0.0:
        return "degenerate", condition_number(N)
    An = A / amax
    det2 = float(An[0, 0] * An[1, 1] - An[0, 1] * An[1, 0])
    Cc, _centre = centred_conic(N, normalized=True)
    if not np.all(np.isfinite(Cc)):
        return "degenerate", math.inf
    det3 = float(np.linalg.det(Cc))
    sv = np.linalg.svd(Cc, compute_uv=False)
    cond = math.inf if sv[-1] <= 0.0 else float(sv[0] / sv[-1])
    if not math.isfinite(det3) or abs(det3) <= tol:
        return "degenerate", cond
    if abs(det2) <= tol:
        return "parabola", cond
    return ("ellipse" if det2 > 0.0 else "hyperbola"), cond


def condition_number(C) -> float:
    """2-norm condition number of the conic translated to its centre (vertex for a
    parabola; contract §2.6: ``> 1e8`` -> ``CONIC_SAMPLED``, spec §11.3).  Returns ``inf``
    for a singular matrix."""
    Cc, _centre = centred_conic(C)
    if not np.all(np.isfinite(Cc)):
        return math.inf
    s = np.linalg.svd(Cc, compute_uv=False)
    if s[-1] <= 0.0:
        return math.inf
    return float(s[0] / s[-1])


def is_sampled(C, cond_max: float = COND_MAX) -> bool:
    """Contract §2.6 / §2.9 ``CONIC_SAMPLED`` predicate: the conic is degenerate or its
    (centred) condition number exceeds ``cond_max``; such conics are emitted as sampled
    polylines instead of ``<ellipse>`` elements."""
    return classify(C) == "degenerate" or condition_number(C) > cond_max


def ellipse_params(C):
    """Centre, semi-axes and rotation of a real ellipse ``x^T C x = 0``.

    Returns ``(centre (2,), (a, b), rotation)`` with ``a >= b > 0`` the semi-major /
    semi-minor axes and ``rotation`` the angle (radians, in ``[0, pi)``) of the major axis
    measured from the ``+x`` axis.  Returns ``None`` when the conic is not a real,
    non-degenerate ellipse (so callers never see an exception; contract §2.8).

    Derivation: with ``C = [[A, b], [b^T, c]]``, the centre is ``x0 = -A^{-1} b`` and in
    centred coordinates ``y^T A y = k`` with ``k = b^T A^{-1} b - c``; the semi-axes are
    ``sqrt(k / lambda_i)`` along the eigenvectors of ``A``.
    """
    C = normalize_conic(C)
    if not np.all(np.isfinite(C)):
        return None
    A = C[:2, :2]
    b = C[:2, 2]
    c = float(C[2, 2])
    detA = float(A[0, 0] * A[1, 1] - A[0, 1] * A[1, 0])
    if detA <= 1e-300:
        return None
    Ainv = np.array([[A[1, 1], -A[0, 1]], [-A[1, 0], A[0, 0]]]) / detA
    centre = -(Ainv @ b)
    k = float(b @ Ainv @ b) - c
    if k == 0.0:
        return None
    # closed-form symmetric 2x2 eigen-decomposition (deterministic)
    p, q, r = float(A[0, 0]), float(A[0, 1]), float(A[1, 1])
    half = 0.5 * (p + r)
    rad = math.hypot(0.5 * (p - r), q)
    lam1 = half + rad
    lam2 = half - rad
    ratio1 = k / lam1 if lam1 != 0.0 else -1.0
    ratio2 = k / lam2 if lam2 != 0.0 else -1.0
    if ratio1 <= 0.0 or ratio2 <= 0.0:
        return None
    s1 = math.sqrt(ratio1)  # along eigenvector of lam1
    s2 = math.sqrt(ratio2)  # along eigenvector of lam2
    # eigenvector of lam1: (q, lam1 - p) or (lam1 - r, q)
    if abs(q) > 1e-15 * max(1.0, abs(p), abs(r)):
        v1 = np.array([q, lam1 - p])
    elif p >= r:
        v1 = np.array([1.0, 0.0])
    else:
        v1 = np.array([0.0, 1.0])
    if rad <= 1e-12 * max(abs(p), abs(r)):
        # a circle within rounding: the axis direction is undefined and the exact tests below would
        # pick it from ulp noise (90 deg vs 0 deg between implementations); fix it at +x (M7 review,
        # contract §5.4 implementation notes)
        major, minor, v = max(s1, s2), min(s1, s2), np.array([1.0, 0.0])
    elif s1 >= s2:
        major, minor, v = s1, s2, v1
    else:
        major, minor, v = s2, s1, np.array([-v1[1], v1[0]])
    rot = math.atan2(float(v[1]), float(v[0])) % math.pi
    if rot >= math.pi - 1e-15:
        rot = 0.0
    return np.asarray(centre, dtype=np.float64), (major, minor), rot


def conic_point(H, theta, rho: float = 1.0) -> np.ndarray:
    """Rational parametrisation (contract §2.6): ``X(theta) = H (rho cos theta, rho sin theta, 1)``.
    ``H`` may be ``(k, 3)`` for any ``k`` (3x3 image/ground map, or 4x3 ``T E`` for 4-D
    points).  ``theta`` scalar -> ``(k,)``; array ``(n,)`` -> ``(n, k)``."""
    H = np.asarray(H, dtype=np.float64)
    th = np.asarray(theta, dtype=np.float64)
    local = np.stack([rho * np.cos(th), rho * np.sin(th), np.ones_like(th)], axis=-1)
    return local @ H.T


def sample_arc(H, rho: float, theta0: float, theta1: float, n: int) -> np.ndarray:
    """``n`` equal parameter steps from ``theta0`` to ``theta1`` -> ``(n + 1, k)`` homogeneous
    points ``H (rho cos theta, rho sin theta, 1)`` (contract §2.6 sampling; the output
    stage chooses ``n``: 64 per full circle, proportionally fewer for arcs, minimum 8)."""
    n = max(1, int(n))
    th = theta0 + (theta1 - theta0) * np.arange(n + 1, dtype=np.float64) / n
    return conic_point(H, th, rho)


def sample_count(theta0: float, theta1: float, per_circle: int = SAMPLES_PER_CIRCLE,
                 minimum: int = MIN_ARC_SAMPLES) -> int:
    """Contract §2.6 sampling rule: number of segments for the arc ``[theta0, theta1]``,
    ``max(minimum, round(per_circle * |theta1 - theta0| / (2 pi)))`` (proportionally fewer
    segments for arcs).  Rounding to the nearest integer (instead of ``ceil``) keeps the count
    stable when an arc span sits at an exact fraction of the circle -- a half circle under a
    directional light stays 32 segments when the same scene is lit by a point light 10^6 m
    away (spec §7.1 row 3) or rotated rigidly (row 4), where ``ceil`` would flip on rounding
    noise."""
    span = abs(float(theta1) - float(theta0))
    return max(int(minimum), int(math.floor(per_circle * span / TWO_PI + 0.5)))


def functional_coeffs(f, H, rho: float = 1.0) -> tuple[float, float, float]:
    """Coefficients ``(A, B, C)`` of a linear functional ``f`` along the parametrised
    circle: ``f . X(theta) = A cos theta + B sin theta + C`` with
    ``X(theta) = H (rho cos theta, rho sin theta, 1)`` (contract §2.6: the near
    functional ``nu`` and the shadow ``w_S`` are both of this form)."""
    f = np.asarray(f, dtype=np.float64).reshape(-1)
    H = np.asarray(H, dtype=np.float64).reshape(f.shape[0], 3)
    g = f @ H
    return float(rho * g[0]), float(rho * g[1]), float(g[2])


def sub_arcs_where_nonnegative(A: float, B: float, C: float,
                               theta0: float = 0.0, theta1: float = TWO_PI,
                               tol: float = 0.0) -> list[list[float]]:
    """Closed-form solution of ``A cos theta + B sin theta + C > tol`` on the
    parameter range ``[theta0, theta1]`` (``theta1 > theta0``, at most one full turn
    long; the default is the full circle ``[0, 2 pi]``).  Contract §2.6: near clipping
    of conics and ``w_S`` crossings of curved shadows.

    Tolerance convention (contract §2.8, same as ``shadow_loop``'s ``w > tol``): the
    band ``|value| <= tol`` counts as the *degenerate* side and is **dropped**, so every
    returned endpoint has ``value >= tol`` (never a negative value).  Callers pass the
    same ``tol`` / ``tol_dir`` they use for the polygon predicates.

    Returns a list of ``[a, b]`` intervals, ``a < b``, in increasing order of ``a``.
    On a full-turn range a region that straddles the seam ``theta0 + 2 pi`` is
    returned as **one** interval ``[a, b]`` with ``theta0 <= a < theta1 < b <= a + 2 pi``
    (no splitting at the seam); otherwise ``theta0 <= a < b <= theta1``.  Intervals
    shorter than :data:`ARC_MIN_SPAN` radians are dropped (they would become
    zero-length arcs).

    With ``R = sqrt(A^2 + B^2)`` and ``phi = atan2(B, A)`` the function is
    ``R cos(theta - phi) + C``; it exceeds ``tol`` on ``(phi - delta, phi + delta)``
    (mod ``2 pi``) with ``delta = acos((tol - C) / R)``.
    """
    A = float(A)
    B = float(B)
    C = float(C) - float(tol)           # drop the band |value| <= tol (contract §2.8)
    theta0 = float(theta0)
    theta1 = float(theta1)
    if theta1 <= theta0:
        return []
    R = math.hypot(A, B)
    if R <= 1e-300 * max(1.0, abs(C)) or R == 0.0:
        return [[theta0, theta1]] if C > 0.0 else []
    if C >= R:
        return [[theta0, theta1]]
    if C <= -R:
        return []
    phi = math.atan2(B, A)
    delta = math.acos(max(-1.0, min(1.0, -C / R)))
    lo, hi = phi - delta, phi + delta
    # shift the base interval by multiples of 2 pi to cover [theta0, theta1]
    k0 = math.floor((theta0 - hi) / TWO_PI)
    k1 = math.ceil((theta1 - lo) / TWO_PI)
    out: list[list[float]] = []
    for k in range(k0, k1 + 1):
        a = max(theta0, lo + k * TWO_PI)
        b = min(theta1, hi + k * TWO_PI)
        if b > a:
            if out and a <= out[-1][1] + 1e-15:
                out[-1][1] = max(out[-1][1], b)
            else:
                out.append([a, b])
    # seam merge on a full-turn range: [theta0, b_first] + [a_last, theta1] -> [a_last, b_first + 2 pi]
    full_turn = theta1 - theta0 >= TWO_PI - ARC_MIN_SPAN
    if full_turn and len(out) >= 2 and out[0][0] <= theta0 and out[-1][1] >= theta1:
        merged = [out[-1][0], out[0][1] + TWO_PI]
        out = out[1:-1] + [merged]
    return [iv for iv in out if iv[1] - iv[0] > ARC_MIN_SPAN]


def arc_svg_flags(centre, axes, rotation: float, p_start, p_mid, p_end) -> tuple[int, int]:
    """SVG ``A`` command flags ``(large_arc, sweep)`` for the ellipse arc from ``p_start``
    to ``p_end`` that passes through ``p_mid`` (contract §2.6: flags decided by the arc
    midpoint).  ``centre, axes=(a, b), rotation`` are :func:`ellipse_params` of the
    ellipse; all points are 2-D in the same frame.

    ``sweep = 1`` means the arc runs in the increasing-angle direction of that frame
    (counter-clockwise when ``y`` is up).  When the drawing frame mirrors ``y`` (SVG,
    ``y_svg = H/2 - v``) the caller flips the sweep flag.
    """
    centre = np.asarray(centre, dtype=np.float64).reshape(2)
    a, b = float(axes[0]), float(axes[1])
    cr, sr = math.cos(rotation), math.sin(rotation)

    def param(p):
        d = np.asarray(p, dtype=np.float64).reshape(2) - centre
        x = cr * d[0] + sr * d[1]
        y = -sr * d[0] + cr * d[1]
        return math.atan2(y / b if b != 0.0 else y, x / a if a != 0.0 else x)

    ps, pm, pe = param(p_start), param(p_mid), param(p_end)
    ccw_end = (pe - ps) % TWO_PI
    ccw_mid = (pm - ps) % TWO_PI
    if ccw_end <= 1e-15:
        ccw_end = TWO_PI
    if ccw_mid < ccw_end:
        sweep = 1
        span = ccw_end
    else:
        sweep = 0
        span = TWO_PI - ccw_end
    large = 1 if span > math.pi else 0
    return large, sweep


# ---------------------------------------------------------------------------
# circle records (contract §2.6) and output-stage helpers
# ---------------------------------------------------------------------------

def circle_frame(normal, tol: float = 1e-9, fallback=None) -> tuple[np.ndarray, np.ndarray]:
    """Contract §2.6 frame of a silhouette circle with unit normal ``n``:
    ``e1 = normalize(n x z)`` (fallback ``n x x`` when ``|n x z| <= tol``), ``e2 = n x e1``.
    ``(e1, e2, n)`` is right-handed, so ``theta`` increasing is counter-clockwise about ``n``.

    ``fallback`` optionally replaces the world ``x`` axis of the fallback by a sequence of
    directions tried in order (the first one not parallel to ``n`` wins): the sphere
    silhouette passes the object's rotated local axes ``(e1, e2)`` so that the frame of a
    horizontal circle rotates with the scene (spec §7.1 row 4) instead of being pinned to
    world ``x``; for an unrotated object this is exactly the contract's ``n x x``."""
    n = np.asarray(normal, dtype=np.float64).reshape(3)
    n = n / float(np.linalg.norm(n))
    e1 = np.cross(n, np.array([0.0, 0.0, 1.0]))
    if float(np.linalg.norm(e1)) <= tol:
        candidates = [np.array([1.0, 0.0, 0.0])] if fallback is None else list(fallback)
        for cand in candidates:
            e1 = np.cross(n, np.asarray(cand, dtype=np.float64).reshape(3))
            if float(np.linalg.norm(e1)) > tol:
                break
    e1 = e1 / float(np.linalg.norm(e1))
    e2 = np.cross(n, e1)
    return e1, e2


def circle_record(centre, e1, e2, radius: float) -> dict:
    """The ``circle`` dict of contract §2.6 outputs: ``{"centre": (3,), "e1": (3,),
    "e2": (3,), "radius": float}`` as float64 arrays.  ``theta`` parametrises the circle
    as ``centre + radius (cos theta e1 + sin theta e2)``."""
    return {
        "centre": np.asarray(centre, dtype=np.float64).reshape(3).copy(),
        "e1": np.asarray(e1, dtype=np.float64).reshape(3).copy(),
        "e2": np.asarray(e2, dtype=np.float64).reshape(3).copy(),
        "radius": float(radius),
    }


def circle_embedding(circle: dict) -> np.ndarray:
    """``E = [e1 e2 c; 0 0 1]`` (4x3) of a :func:`circle_record` (contract §2.6)."""
    return embed_circle(circle["centre"], circle["e1"], circle["e2"])


def circle_point(circle: dict, theta) -> np.ndarray:
    """Homogeneous world point(s) ``X(theta) = E (rho cos theta, rho sin theta, 1)`` of a
    :func:`circle_record` (``w = 1``); ``theta`` scalar -> ``(4,)``, array -> ``(n, 4)``."""
    return conic_point(circle_embedding(circle), theta, circle["radius"])


def _circle_lists(circle: dict) -> dict:
    return {
        "centre": (np.asarray(circle["centre"], dtype=np.float64).reshape(3) + 0.0).tolist(),
        "e1": (np.asarray(circle["e1"], dtype=np.float64).reshape(3) + 0.0).tolist(),
        "e2": (np.asarray(circle["e2"], dtype=np.float64).reshape(3) + 0.0).tolist(),
        "radius": float(circle["radius"]) + 0.0,
    }


def conic_entry(circle: dict, H, arc=None, map: str = "image") -> dict:
    """Build a contract §2.6 / §3.1 ``conics`` entry for the circle mapped by the 3x3
    projective map ``H`` (``H = P E`` for image circles, ``H = P M E`` for ground
    shadows)::

        {"conic": 3x3 (max-normalised, +1 max entry), "kind": ellipse|parabola|hyperbola|degenerate,
         "arc": {"theta0", "theta1"} | None, "circle": {centre, e1, e2, radius},
         "map": "shadow" | "image", "sampled": bool, "cond": float}

    ``arc`` is the circle-parameter range (radians, CCW in the circle frame,
    ``theta1 > theta0``); ``None`` is the full conic.  ``sampled`` is the
    ``CONIC_SAMPLED`` predicate (degenerate or condition number ``> 1e8``); the caller
    emits the warning with the object id.  Every float is canonical (``+ 0.0``)."""
    C = normalize_conic(transform_conic(circle_matrix(circle["radius"]), H))
    kind, cond = classify_and_condition(C, normalized=True)
    if arc is not None:
        a, b = float(arc[0]) if not isinstance(arc, dict) else float(arc["theta0"]), \
            float(arc[1]) if not isinstance(arc, dict) else float(arc["theta1"])
        lo, hi = (a, b) if a <= b else (b, a)
        arc_out = {"theta0": lo + 0.0, "theta1": hi + 0.0}
    else:
        arc_out = None
    return {
        "conic": (C + 0.0).tolist(),
        "kind": kind,
        "arc": arc_out,
        "circle": _circle_lists(circle),
        "map": str(map),
        "sampled": bool(kind == "degenerate" or cond > COND_MAX),
        "cond": float(cond) if math.isfinite(cond) else math.inf,
    }


def ellipse_arc_params(H, rho: float, theta0: float, theta1: float):
    """Image-space ellipse parameters of the arc ``[theta0, theta1]`` of the circle of
    radius ``rho`` under the 3x3 map ``H`` (contract §2.6 ``<path d="M ... A ...">``
    output).  Requires the mapped conic to be a real ellipse and the three sample points
    (start, midpoint, end) to have ``x3 > 0`` (i.e. the arc was near-clipped first);
    returns ``None`` otherwise.

    Returns ``{"centre": (2,), "axes": (a, b), "rotation": radians, "start": (2,),
    "end": (2,), "large_arc": 0|1, "sweep": 0|1}`` in the same ``(u, v)`` frame as ``H``
    (``v`` up).  ``sweep = 1`` is the increasing-angle direction of that frame; an SVG
    writer that mirrors ``v`` flips the flag (see :func:`arc_svg_flags`)."""
    H = np.asarray(H, dtype=np.float64).reshape(3, 3)
    C = transform_conic(circle_matrix(rho), H)
    params = ellipse_params(C)
    if params is None:
        return None
    centre, axes, rot = params
    pts = conic_point(H, np.array([theta0, 0.5 * (theta0 + theta1), theta1], dtype=np.float64), rho)
    if np.any(pts[:, 2] <= 0.0):
        return None
    uv = pts[:, :2] / pts[:, 2:3]
    large, sweep = arc_svg_flags(centre, axes, rot, uv[0], uv[1], uv[2])
    return {
        "centre": centre, "axes": (float(axes[0]), float(axes[1])), "rotation": float(rot),
        "start": uv[0], "end": uv[2], "large_arc": int(large), "sweep": int(sweep),
    }

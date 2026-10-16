"""Hair cap, bangs, sidelocks, the stray strand, back hair and the headband of the Miki model (owner: head agent).

Part contract (see ``assemble.py`` and the toolkit guide): :func:`build` takes the
:class:`~miki_model.rig.Rig` and returns a list of :class:`~miki_model.meshkit.Part` covering **all** of
:data:`REGIONS` (each part's ``region`` names one of them, so ``--only`` can filter).
Objects / materials (``Part(name, material, mesh, region, obj=...)``, see ``assemble.OBJECTS``): dome, bangs,
strand -> hair (hair); sidelocks -> ``obj="sidelocks"`` (hair); curtain + back sheet -> ``obj="back_hair"``
(hair); band -> headband (headband), its pink ridge -> headband (uniform).

How it is built (spec ``miki_spec.md`` §C):

* **H1 dome**: the §C top-hair ellipsoid from the crown down to a bottom boundary that runs along the headband's
  centreline in front (the band covers the dome's edge; the bangs come out from under it) and at
  :data:`DOME_BACK_BOTTOM_Z` around the sides and back (inside the side curtain).  Closed underneath by a fan
  to a point inside the skull.  One smooth group: it draws as the head's silhouette only.
* **Headband** (§C.1): a 8 mm x 3 mm band swept along the spec centreline, its inner face sunk into the dome
  mesh (ray cast) and the pink centre ridge as a separate raised shell (material ``uniform``).  Both are
  classified slabs (see :func:`head.classify_rims`): the band's edges and the ridge's two borders are feature
  lines or robust silhouettes at a cost of a few construction rays.
* **H3 bangs** (§C.2): a slab of even thickness on the forehead, from under the band's lower edge to the flat
  cut at ``bangs_cut_z``, six strips (five strand lines), the bottom 4 mm curling in, the cut face and the end
  faces in their own groups.
* **H4 sidelocks** (§C.3): sharp-edged lens-section ribbons swept through the spec's edge table, their roots
  rising into the dome under the band; the cut face, a central strand crease and the outer edge are feature
  lines, the inner edge draws only as a silhouette.
* **H5 strand** (§C.4): one thin swept strand on her left.
* **H2 side curtain + back sheet** (§C.6): one slab from inside the dome down to five uneven clumps on a
  convex-down hem; the curtain's front edges taper and end just behind the sidelocks' front (round 3: in
  profile the lock is the front-most hair, the curtain covers only its back edge), the front end faces and the
  lateral faces share the outer surface's groups (silhouette-only), the clump ends are rims, and three
  strand lines (group boundaries + shallow grooves) end at the notches nearest the middle.

Round 1 of the review changed rig values (now in ``rig.py``) and the dome / sidelock /
H2 construction; every quad of the dome, sidelocks and H2 uses its valley diagonal
(:func:`meshkit.inscribed_fan`), which closes the gaps in castplane's hidden-line outlines.
"""

from __future__ import annotations

import functools
import math

import numpy as np

from . import body as _body
from . import mannequin as _mannequin
from . import meshkit as mk
from .head import SUN, SkinSurface, head_section, oriented, skin_surface, slab, slab_faces
from .meshkit import Part
from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The mannequin regions this module replaces.
REGIONS = ("hair", "headband")

SIDES = (1, -1)
#: Round 3 (tech F1 / F2): quads of the dome, sidelocks and H2 whose two fan triangles differ by more than this
#: (degrees) become two triangles (:func:`meshkit.split_twisted`): castplane takes a polygon's facing from its
#: Newell normal but hides lines with its triangles, so on a twisted quad at the outline a piece of the outline
#: was hidden by the quad's own other triangle (the 2.3 mm gap in the back hair's outline at az 210).
TWIST_SPLIT_DEG = 1.0

def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _smoothstep(e0: float, e1: float, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _catmull_rom(points, n: int) -> np.ndarray:
    """``n`` points along a centripetal-free (uniform) Catmull-Rom spline through ``points`` (ends kept),
    resampled at equal arc length."""
    P = np.asarray(points, dtype=np.float64)
    Q = np.concatenate([2 * P[:1] - P[1:2], P, 2 * P[-1:] - P[-2:-1]])
    dense = []
    for i in range(1, len(Q) - 2):
        p0, p1, p2, p3 = Q[i - 1], Q[i], Q[i + 1], Q[i + 2]
        for t in np.linspace(0.0, 1.0, 24, endpoint=False):
            t2, t3 = t * t, t * t * t
            dense.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
                                + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    dense.append(P[-1])
    return mk.resample_polyline(np.array(dense), n)


def _radial_hit(mesh: mk.Mesh, origin, direction):
    """First intersection (largest t > 0 is not needed: the shells are star-shaped about ``origin``) of the
    ray ``origin + t * direction`` with ``mesh`` (Moller-Trumbore over all triangles); returns the point."""
    tris, _ = mesh.triangles()
    V = mesh.vertices
    A, B, C = V[tris[:, 0]], V[tris[:, 1]], V[tris[:, 2]]
    o = np.asarray(origin, dtype=np.float64)
    d = np.asarray(direction, dtype=np.float64)
    e1, e2 = B - A, C - A
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)
    ok = np.abs(det) > 1e-15
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = o - A
    u = np.einsum("ij,ij->i", s, p) * inv
    q = np.cross(s, e1)
    v = (q @ d) * inv
    t = np.einsum("ij,ij->i", e2, q) * inv
    hit = ok & (u >= -1e-9) & (v >= -1e-9) & (u + v <= 1 + 1e-9) & (t > 0)
    if not hit.any():
        raise mk.MeshError("radial ray misses the mesh")
    return o + float(t[hit].max()) * d


# ---------------------------------------------------------------------------------------------------------
# H1 dome
# ---------------------------------------------------------------------------------------------------------
#: Azimuths (degrees, counter-clockwise from her left, +X; 270 = the front) of the dome's ring points: denser
#: over the front, where the bangs, band and face silhouette are.
#: Round 1 (F16): 26 azimuths (was 24), still densest over the front; the quads use their valley diagonals
#: (:func:`meshkit.inscribed_fan`), which closes the crown outline's gaps.
#: Round 2 (F3 tech / F5): the azimuths of the front half (180 ... 360 degrees: 12-degree steps, 10 over the
#: face); the back half (0 ... 180) uses the side curtain's column angles (:func:`_dome_azimuths`), so the
#: curtain's top rows run parallel to the dome's facets and the curtain covers the dome's rim at a constant
#: small offset (no sawtooth seam where they cross, no piece of the rim poking through).
DOME_FRONT_AZIMUTHS = tuple(range(192, 241, 12)) + (250, 260, 270, 280, 290) + tuple(range(300, 360, 12))
#: Rings: constant-z rings over the crown (clean silhouettes), then rings blending down to the bottom boundary.
DOME_FLAT_THETA = (8.0, 18.0, 28.0, 38.5, 49.0)   # constant-z rings (polar angle, degrees)
#: Round 1 (F3 / F16): the blend rings lie at these heights behind the band (constant z there, so the
#: curtain, whose rows sit at 1.458 and 1.452, crosses the dome along a level seam); in front they blend to
#: the band line.  The last one is the bottom boundary.
#: Round 2 (F5): behind the band's visible span the dome now reaches its equator (DOME_BACK_BOTTOM_Z), where
#: the curtain comes out from under it tangentially (rig.curtain_top_rows).
DOME_BLEND_BACK_Z = (1.466, 1.436, 1.405)
#: Round 3 (tech F1 / F10): the blend rings sink this far (along the dome normal) inside the dome surface where
#: the side curtain covers them (behind the curtain's front edge, :data:`CURTAIN_FRONT_Y`), so below ~1.445
#: the dome is >= 1.5 mm inside the curtain and only the curtain's outline survives (was: both within 1 mm,
#: each hiding the other's outline in turns).
DOME_BACK_INSET = (0.0, 0.003, 0.005)
#: Bottom of the dome behind the headband's visible span (inside the side curtain; round 1: 1.452, the
#: curtain row that stands 2.5 mm out, so no piece of the dome's rim pokes through the curtain's chords).
DOME_BACK_BOTTOM_Z = 1.405
#: ... reached DOME_BOTTOM_RAMP_DEG (azimuth) behind the end of the band's visible span (smoothstep from the
#: band line).
DOME_BOTTOM_RAMP_DEG = 25.0
#: The dome ends along the band line over |x| <= DOME_BAND_SPAN_X (just past the bangs' ends, BANGS_END_X).
DOME_BAND_SPAN_X = 0.073
#: In front the dome ends this far below the band centreline (under the band's lower half).
DOME_BAND_DROP = 0.002
#: The fan closing the dome underneath ends here (inside the skull).
DOME_CAP_APEX = (0.0, 0.020, 1.440)
#: Round 1 (F2): the dome's vertical sections are superellipses of this exponent at the sides (x), plain
#: ellipses at the front and back (exponent 2 + (DOME_SIDE_EXPONENT - 2) cos^2(azimuth)); the extra fullness
#: fades in between the polar angles DOME_SIDE_FADE (degrees), so the crown top stays round: the outline
#: is a rounded rectangle that flows into the side hair.
#: Round 4 (F6): exponent 2.8 (was 2.6) faded in from 28 to 55 degrees (was 30 ... 60): the crown is ~3 mm
#: fuller at z 1.48 (hw 0.0925 -> ~0.096), a rounded rectangle rather than a gothic arch over the side hair.
DOME_SIDE_EXPONENT = 2.8
DOME_SIDE_FADE = (28.0, 55.0)
#: Round 1 (F4): the band ends here (was y -0.005) ...
BAND_END_Y = -0.013                 # round 2 (F6 tech): 2 mm further into the hair (was -0.015)
#: ... and from ``rig.band_tuck_y`` back to its end it dives this much deeper into the hair (its end is
#: buried >= 4 mm under the hair surface, no end cap shows).
BAND_DIVE = 0.0075


def _band_line(rig: Rig) -> np.ndarray:
    """The headband centreline from her right end to her left end (spec points mirrored, ending at
    :data:`BAND_END_Y`)."""
    cl = np.array(rig.band_centreline)
    cl = cl[cl[:, 1] <= BAND_END_Y + 1e-9]
    return np.concatenate([cl[:0:-1] * np.array([-1.0, 1.0, 1.0]), cl])


def _dome_exponent(theta: float, phi: float) -> float:
    fade = float(_smoothstep(math.radians(DOME_SIDE_FADE[0]), math.radians(DOME_SIDE_FADE[1]), theta))
    return 2.0 + (DOME_SIDE_EXPONENT - 2.0) * fade * math.cos(phi) ** 2


def _ellipsoid(rig: Rig, theta, phi) -> np.ndarray:
    """Point of the H1 dome at polar angle ``theta`` (from +Z) and azimuth ``phi`` (radians): the §C
    top-hair ellipsoid made fuller at the sides (:data:`DOME_SIDE_EXPONENT`)."""
    c = np.array(rig.dome_center)
    ax, ayf, az = rig.dome_radii
    ay = rig.dome_back_radius if math.sin(phi) > 0 else ayf
    ct = math.cos(theta)
    e = _dome_exponent(theta, phi)
    r = max(0.0, 1.0 - abs(ct) ** e) ** (1.0 / e)
    return c + np.array([ax * r * math.cos(phi), ay * r * math.sin(phi), az * ct])


def _dome_angles(rig: Rig, p):
    """``(theta, phi)`` of the dome point ``p`` (inverse of :func:`_ellipsoid` for points on it)."""
    c = np.array(rig.dome_center)
    ax, ayf, az = rig.dome_radii
    d = np.asarray(p, dtype=np.float64) - c
    ay = rig.dome_back_radius if d[1] > 0 else ayf
    return math.acos(float(np.clip(d[2] / az, -1.0, 1.0))), math.atan2(d[1] / ay, d[0] / ax)


def _ellipsoid_normal(rig: Rig, p) -> np.ndarray:
    """Outward unit normal of the dome surface at (or near) ``p`` (numerical)."""
    th, ph = _dome_angles(rig, p)
    h = 1e-4
    dt = _ellipsoid(rig, th + h, ph) - _ellipsoid(rig, th - h, ph)
    dp = _ellipsoid(rig, th, ph + h) - _ellipsoid(rig, th, ph - h)
    n = np.cross(dt, dp)
    n /= np.linalg.norm(n)
    c = np.array(rig.dome_center)
    return n if n @ (np.asarray(p) - c) > 0 else -n


def _dome_section_point(rig: Rig, z: float, psi: float):
    """Point of the dome's horizontal section at height ``z`` at the crescent angle ``psi`` (0 = straight
    back, +pi/2 = her left side, past pi/2 towards the front; negative = her right) and the section's
    outward horizontal unit normal there."""
    c = np.array(rig.dome_center)
    th = math.acos(float(np.clip((z - c[2]) / rig.dome_radii[2], -1.0, 1.0)))

    def pt(a):
        return _ellipsoid(rig, th, math.pi / 2 - a)

    p = pt(psi)
    h = 1e-4
    t = pt(psi + h) - pt(psi - h)
    n = np.array([t[1], -t[0], 0.0])
    n /= np.linalg.norm(n)
    if n @ (p - np.array([0.0, c[1], p[2]])) < 0:
        n = -n
    return p, n


def _dome_bottom_z(rig: Rig, phi: float) -> float:
    """z of the dome's bottom boundary at azimuth ``phi``: the band centre over the bangs (round 2: up to
    :data:`DOME_BAND_SPAN_X`; the bangs come out from under the band there), then down to
    :data:`DOME_BACK_BOTTOM_Z` (the dome covers the temple, where the sidelock's root comes out through its
    surface, and the curtain's top)."""
    c = np.array(rig.dome_center)
    band = _band_line(rig)
    band = band[np.abs(band[:, 0]) <= DOME_BAND_SPAN_X + 1e-9]
    az_band = np.unwrap(np.arctan2(band[:, 1] - c[1], band[:, 0]))      # her right end ... her left end
    a = math.atan2(math.sin(phi), math.cos(phi))
    # bring a into the band's azimuth range (around -pi/2)
    while a > az_band.max() + math.pi:
        a -= 2 * math.pi
    while a < az_band.min() - math.pi:
        a += 2 * math.pi
    lo, hi = min(az_band[0], az_band[-1]), max(az_band[0], az_band[-1])
    order = np.argsort(az_band)
    if lo <= a <= hi:
        return float(np.interp(a, az_band[order], band[order, 2])) - DOME_BAND_DROP
    d_lo = (lo - a) % (2 * math.pi)
    d_hi = (a - hi) % (2 * math.pi)
    edge = lo if d_lo < d_hi else hi
    z_edge = float(np.interp(edge, az_band[order], band[order, 2])) - DOME_BAND_DROP
    k = float(_smoothstep(0.0, math.radians(DOME_BOTTOM_RAMP_DEG), min(d_lo, d_hi)))
    return z_edge + k * (DOME_BACK_BOTTOM_Z - z_edge)


def _dome_azimuths(rig: Rig):
    """Dome ring azimuths (degrees, ascending): the curtain's back columns (crescent angle psi = |S| /
    CRESCENT_SIDE_S * 90 degrees, azimuth 90 - psi) and :data:`DOME_FRONT_AZIMUTHS`."""
    S = _clump_columns(rig)[0]
    back = [round(90.0 - float(s) / CRESCENT_SIDE_S * 90.0, 6) for s in S if abs(s) <= CRESCENT_SIDE_S + 1e-9]
    return tuple(sorted(set(back))) + DOME_FRONT_AZIMUTHS


def _dome(rig: Rig) -> mk.Mesh:
    c = np.array(rig.dome_center)
    az = rig.dome_radii[2]
    phis = np.radians(_dome_azimuths(rig))
    theta_b = []
    for phi in phis:
        zb = _dome_bottom_z(rig, phi)
        theta_b.append(math.acos(np.clip((zb - c[2]) / az, -1.0, 1.0)))
    rings = []
    th0 = math.radians(DOME_FLAT_THETA[-1])
    th_back = math.acos(np.clip((DOME_BACK_BOTTOM_Z - c[2]) / az, -1.0, 1.0))
    for th in DOME_FLAT_THETA:
        rings.append(np.array([_ellipsoid(rig, math.radians(th), phi) for phi in phis]))
    for zb, inset in zip(DOME_BLEND_BACK_Z, DOME_BACK_INSET):
        t = (math.acos(np.clip((zb - c[2]) / az, -1.0, 1.0)) - th0) / (th_back - th0)
        ring = []
        for tb, phi in zip(theta_b, phis):
            p = _ellipsoid(rig, th0 + t * (tb - th0), phi)
            if inset > 0.0:
                yf = _front_y(float(p[2]))
                w = float(_smoothstep(yf + 0.002, yf + 0.008, p[1]))
                p = p - inset * w * _ellipsoid_normal(rig, p)
            ring.append(p)
        rings.append(np.array(ring))
    top = c + np.array([0.0, 0.0, az])
    dome = mk.inscribed_fan(mk.loft(rings, ("pole", top), ("pole", DOME_CAP_APEX), groups=1, cap_groups=(1, 1)))
    return mk.split_twisted(dome, TWIST_SPLIT_DEG)


# ---------------------------------------------------------------------------------------------------------
# headband (§C.1)
# ---------------------------------------------------------------------------------------------------------
BAND_POINTS = 15                    # along the band (her right end ... her left end)
RIDGE_SINK = 0.0002                 # the ridge's base sits this far inside the band's outer face
HEADBAND_SHRINK = 0.25              # the inner face is this fraction of the band width (undercut walls)
RIDGE_SHRINK = 0.05


def _band_frames(rig: Rig, dome: mk.Mesh):
    """Points on the dome under the band centreline, the outward normals there and the across direction
    (pointing up the head), ``(P, N, Bx)`` each ``(BAND_POINTS, 3)``."""
    c = np.array(rig.dome_center)
    path = _catmull_rom(_band_line(rig), BAND_POINTS)
    P, N = [], []
    for p in path:
        d = p - c
        q = _radial_hit(dome, c, d / np.linalg.norm(d))
        P.append(q)
        N.append(_ellipsoid_normal(rig, q))
    P, N = np.array(P), np.array(N)
    T = np.gradient(P, axis=0)
    T /= np.linalg.norm(T, axis=1)[:, None]
    Bx = np.cross(N, T)
    Bx /= np.linalg.norm(Bx, axis=1)[:, None]
    if np.mean(Bx[:, 2]) < 0:
        Bx = -Bx
    return P, N, Bx


def _band_slab(F, B, shrink: float, single: bool) -> mk.Mesh:
    """Band slab between ``(U, 2, 3)`` grids ``F`` (outer face) and ``B`` (inner face), the inner face
    narrowed to ``shrink`` of its width (undercut walls).  ``single``: one smooth group (the borders draw as
    camera silhouettes, robust thanks to the undercut; no feature edge, no ray); otherwise the outer face is
    group 1 and the walls, ends and inner face group 2, so both borders of the outer face are feature lines
    in every view (the unlit wall costs its border's vertices in construction rays) and no hidden edge is a
    feature line."""
    mid = B.mean(axis=1, keepdims=True)
    B = mid + shrink * (B - mid)
    return slab(F, B, (1, 1, 1, 1, 1, 1) if single else (1, 2, 2, 2, 2, 2))


def _band_embed(rig: Rig, P) -> np.ndarray:
    """Depth of the band's inner face under the dome at the points ``P``: ``rig.band_embed`` over the
    visible span, diving :data:`BAND_DIVE` deeper from ``rig.band_tuck_y`` back to the ends."""
    return rig.band_embed + BAND_DIVE * _smoothstep(rig.band_tuck_y, BAND_END_Y, P[:, 1])


def _headband(rig: Rig, dome: mk.Mesh):
    P, N, Bx = _band_frames(rig, dome)
    base = P - _band_embed(rig, P)[:, None] * N
    w = 0.5 * rig.band_width
    F = np.stack([base - w * Bx + rig.band_thickness * N, base + w * Bx + rig.band_thickness * N], axis=1)
    Bk = np.stack([base - w * Bx, base + w * Bx], axis=1)
    band = _band_slab(F, Bk, HEADBAND_SHRINK, single=False)
    # pink ridge along the band, ending one path point before the band's buried ends.  Round 4 (F7): that
    # point was only ~1 mm under the dome, so the ridge's flat end showed as a cut end in front of the side
    # hair at az +-50; the ridge now runs to the band's ends, buried with them (BAND_DIVE).
    outer = base + rig.band_thickness * N
    keep = np.ones(len(P), dtype=bool)
    k0, k1 = int(np.nonzero(keep)[0][0]), int(np.nonzero(keep)[0][-1])
    o, n, b = outer[k0:k1 + 1], N[k0:k1 + 1], Bx[k0:k1 + 1]
    rw = 0.5 * rig.band_ridge_width
    top = o + rig.band_ridge_height * n
    bot = o - RIDGE_SINK * n
    F = np.stack([top - rw * b, top + rw * b], axis=1)
    Bk = np.stack([bot - rw * b, bot + rw * b], axis=1)
    ridge = _band_slab(F, Bk, RIDGE_SHRINK, single=True)
    return band, ridge


# ---------------------------------------------------------------------------------------------------------
# H3 bangs (§C.2)
# ---------------------------------------------------------------------------------------------------------
BANGS_STRIP_COLS = 1                # quads per strand strip across (round 1: 1, flat facets per strand)
#: The bangs' outer surface starts just in front of the band's lower inner corner (the block comes out from
#: under the band flush with it and hides the corner), leans forward to the curl start and curls back in
#: (``rig.bangs_curl``) to the flat cut; the top row continues ``rig.bangs_top_extension`` up under the band.
BANGS_UNDER_BAND = 0.0005
BANGS_END_X = 0.072                 # vertical end faces (= rig.bangs_half_width)
#: Round 1 (F15): relative widths of the strips, her right to her left (irregular strand lines).
BANGS_STRIP_WEIGHTS = (1.0, 0.7, 1.2, 0.8, 1.1, 0.9, 1.3, 0.8)


def _band_x_frames(rig: Rig, dome: mk.Mesh):
    """Interpolators over x of the band's lower inner corner, its outward normal and across direction."""
    P, N, Bx = _band_frames(rig, dome)
    corner = P - _band_embed(rig, P)[:, None] * N - 0.5 * rig.band_width * Bx
    order = np.argsort(P[:, 0])
    xs = P[order, 0]

    def at(arr, x):
        return np.array([np.interp(x, xs, arr[order, k]) for k in range(3)])

    return (lambda x: at(corner, x)), (lambda x: at(N, x)), (lambda x: at(Bx, x))


def _bangs(rig: Rig, dome: mk.Mesh) -> mk.Mesh:
    surf = skin_surface(rig)
    T = rig.bangs_thickness
    cut = rig.bangs_cut_z
    curl_h, curl_d = rig.bangs_curl
    corner_at, normal_at, across_at = _band_x_frames(rig, dome)
    xmax = 0.97 * head_section(rig, cut)[0]

    def cut_frame(xs):
        """Forehead point at the cut and the horizontal offset direction there (turning to -Y at the ends,
        so the end faces are the planes x = +-BANGS_END_X)."""
        p, n = surf.hit(float(np.clip(xs, -xmax, xmax)), cut)
        end = float(_smoothstep(0.55, 1.0, abs(xs) / BANGS_END_X))
        m = np.array([n[0] * (1.0 - end), n[1], 0.0])
        return p, m / np.linalg.norm(m)

    def outer_cut(xs):
        p, m = cut_frame(xs)
        return p + (rig.bangs_skin_gap + T) * m, m

    def column_at(x_target):
        """Skin parameter whose outer cut point has x = ``x_target`` (bisection; monotone)."""
        lo, hi = -BANGS_END_X - 0.01, BANGS_END_X + 0.01
        for _ in range(60):
            mid = 0.5 * (lo + hi)
            if outer_cut(mid)[0][0] < x_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    # strip borders at the BANGS_STRIP_WEIGHTS fractions of arc length along the outer cut line, each strip
    # split into BANGS_STRIP_COLS equal columns
    dense = np.linspace(-BANGS_END_X, BANGS_END_X, 145)
    pts = np.array([outer_cut(column_at(x))[0] for x in dense])
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    ncol = rig.bangs_strips * BANGS_STRIP_COLS + 1
    wts = np.array(BANGS_STRIP_WEIGHTS[:rig.bangs_strips] if len(BANGS_STRIP_WEIGHTS) >= rig.bangs_strips
                   else (1.0,) * rig.bangs_strips, dtype=np.float64)
    borders = np.concatenate([[0.0], np.cumsum(wts)]) / wts.sum()
    fr = np.concatenate([np.linspace(borders[k], borders[k + 1], BANGS_STRIP_COLS + 1)[:-1]
                         for k in range(len(wts))] + [[1.0]])
    xs = np.interp(fr * s[-1], s, dense)
    xs[0], xs[-1] = -BANGS_END_X, BANGS_END_X
    rows = 4                                                  # under-band top, band edge, curl start, cut
    F = np.zeros((ncol, rows, 3))
    Bk = np.zeros((ncol, rows, 3))
    for i, x in enumerate(xs):
        oc, m = outer_cut(column_at(x))
        top = corner_at(x) + BANGS_UNDER_BAND * np.array([m[0], m[1], 0.0])
        top[0] = x
        lean_cut = oc + curl_d * m                            # where the cut would be without the curl
        zc = cut + curl_h

        def lean(z):
            t = (top[2] - z) / (top[2] - lean_cut[2])
            return top + t * (lean_cut - top)

        ext = corner_at(x) + rig.bangs_top_extension * across_at(x) + 0.001 * normal_at(x)
        ext[0] = x
        outer = [ext, top, lean(zc), oc]
        for j, o in enumerate(outer):
            F[i, j] = o
            Bk[i, j] = o - T * m
    front = np.zeros((ncol - 1, rows - 1), dtype=np.int64)
    for i in range(ncol - 1):
        front[i, :] = 1 + i // BANGS_STRIP_COLS               # strips 1..6: 5 strand lines
    nstrip = rig.bangs_strips
    g_back, g_cut = nstrip + 1, nstrip + 2
    # rims: v0 = top (hidden under the band), v1 = the cut, u0 / u1 = the end faces in their strip's group
    # (round 1, T5: they draw only as silhouettes, no hook at the ends)
    return slab(F, Bk, (front, g_back, g_back, g_cut, 1, nstrip))


# ---------------------------------------------------------------------------------------------------------
# Fit to the outfit (merge step): the hair rests on the collar / scarf that body.py builds
# ---------------------------------------------------------------------------------------------------------
#: body.py parts the sidelocks must stay in front of / the back sheet behind (probed along y).
OUTFIT_FRONT = ("body.collar", "body.collar_stripe", "body.dickey", "body.bib", "body.blouse",
                "body.scarf_ribbon_l", "body.scarf_ribbon_r", "body.scarf_tip_l", "body.scarf_tip_r", "body.ring")
OUTFIT_BACK = ("body.collar", "body.collar_stripe", "body.blouse")
OUTFIT_PROBE_STEPS = 8              # samples per span between two loft rows when checking the chords
SIDELOCK_FIT_TOP_Z = 1.25           # sidelock rows below this are moved forward off the collar / scarf


@functools.lru_cache(maxsize=4)
def _outfit_triangles(rig: Rig, names: tuple) -> np.ndarray:
    """Triangles ``(T, 3, 3)`` of the outfit parts ``names`` (body.py, or the mannequin's torso/collar/scarf
    when body.py is not written)."""
    parts = _body.build(rig)
    if parts is None:                  # mannequin: every torso / collar / scarf part
        parts = _mannequin.build(rig, ["torso", "collar", "scarf"])
    else:
        parts = [p for p in parts if p.name in names]
    tris = []
    for p in parts:
        V = np.asarray(p.mesh.vertices, dtype=np.float64)
        tris.extend(V[[f[0], f[k], f[k + 1]]] for f in p.mesh.faces for k in range(1, len(f) - 1))
    T = np.array(tris)
    T.flags.writeable = False          # lru_cache shares this array between callers: keep it read-only
    return T


def _outfit_y(T: np.ndarray, x: float, z: float, front: bool):
    """Most forward (``front``: smallest y < 0) or most backward (largest y > 0) crossing of the line
    ``(x, *, z)`` with the triangles ``T``; ``None`` when the line misses them."""
    a, b, c = T[:, 0], T[:, 1], T[:, 2]
    d = (b[:, 0] - a[:, 0]) * (c[:, 2] - a[:, 2]) - (b[:, 2] - a[:, 2]) * (c[:, 0] - a[:, 0])
    w0 = (c[:, 0] - b[:, 0]) * (z - b[:, 2]) - (c[:, 2] - b[:, 2]) * (x - b[:, 0])
    w1 = (a[:, 0] - c[:, 0]) * (z - c[:, 2]) - (a[:, 2] - c[:, 2]) * (x - c[:, 0])
    w2 = (b[:, 0] - a[:, 0]) * (z - a[:, 2]) - (b[:, 2] - a[:, 2]) * (x - a[:, 0])
    ok = np.abs(d) > 1e-14
    s = np.where(d < 0, -1.0, 1.0)
    m = ok & (w0 * s >= 0) & (w1 * s >= 0) & (w2 * s >= 0)
    if not m.any():
        return None
    y = (w0[m] * a[m, 1] + w1[m] * b[m, 1] + w2[m] * c[m, 1]) / d[m]
    y = y[y < 0] if front else y[y > 0]
    if not len(y):
        return None
    return float(y.min()) if front else float(y.max())


def _fit_rows(rows, deficit, movable, axis_sign, across: int = 0):
    """Shift loft rows along y so ``deficit(p) <= 0`` holds at every row point and along the chords
    between consecutive rows (:data:`OUTFIT_PROBE_STEPS` samples per span) and, with ``across > 0``, at
    ``across`` samples between neighbouring columns too (a non-periodic sheet).

    ``rows`` is a list of ``(K, 3)`` point arrays (per-column shifts), ``movable[r]`` says whether row
    ``r`` may move and ``axis_sign`` is the y direction of a positive shift (-1 forward for the sidelocks,
    +1 backward for the back sheet).  Returns the shifts ``(R, K)`` (>= 0, in the ``axis_sign``
    direction).  A deficit inside a cell is shared by its corners by their bilinear weights, or carried by
    the movable row alone."""
    R = len(rows)
    K = len(rows[0])
    total = np.zeros((R, K))
    ts = np.linspace(0.0, 1.0, OUTFIT_PROBE_STEPS + 1)
    us = np.linspace(0.0, 1.0, across + 2)[:-1] if across else np.zeros(1)
    dy = np.array([0.0, 1.0, 0.0])
    for _ in range(60):
        cur = [rows[r] + axis_sign * total[r][:, None] * dy for r in range(R)]
        shift = np.zeros((R, K))
        worst = 0.0
        for r in range(R - 1):
            if not (movable[r] or movable[r + 1]):
                continue
            for t in ts:
                P = (1.0 - t) * cur[r] + t * cur[r + 1]
                for k in range(K):
                    for u in us:
                        if u > 0.0 and k == K - 1:
                            continue
                        q = P[k] if u == 0.0 else (1.0 - u) * P[k] + u * P[k + 1]
                        d = deficit(q)
                        if d <= 0.0:
                            continue
                        worst = max(worst, d)
                        d += 1e-4
                        for kk, wu in ((k, 1.0 - u), (k + 1, u)):
                            if wu <= 0.0:
                                continue
                            if movable[r] and movable[r + 1]:
                                shift[r, kk] = max(shift[r, kk], d * (1.0 - t) * wu)
                                shift[r + 1, kk] = max(shift[r + 1, kk], d * t * wu)
                            elif movable[r + 1]:
                                shift[r + 1, kk] = max(shift[r + 1, kk], d * wu / max(t, 0.25))
                            else:
                                shift[r, kk] = max(shift[r, kk], d * wu / max(1.0 - t, 0.25))
        if worst <= 0.0:
            break
        total += shift
    return total


# ---------------------------------------------------------------------------------------------------------
# H4 sidelocks (§C.3)
# ---------------------------------------------------------------------------------------------------------
#: Root row added above the spec table (round 1, T3): the lock rises into the dome under the band to
#: SIDELOCK_ROOT_Z, its edges SIDELOCK_ROOT_INSET inside the dome surface (the root cap never shows).
SIDELOCK_ROOT_Z = 1.466
SIDELOCK_ROOT_INSET = 0.005
#: Round 1 (F1): a sharp-edged lens section, ``(u across the width -1..1 (1 = outer edge), front side?)``;
#: front v = SIDELOCK_FRONT_SHARE * thickness * (1 - u^2)^SIDELOCK_FULLNESS, back the rest.  The edges are
#: real ridges (~60 degrees), so in front-ish views the silhouette runs along the edge itself: one line per
#: edge instead of an edge wall plus its silhouette.
SIDELOCK_PROFILE = ((1.0, True), (0.6, True), (0.0, True), (-0.6, True), (-1.0, True), (0.0, False))
SIDELOCK_FRONT_SHARE = 0.58
SIDELOCK_FULLNESS = 0.8
SIDELOCK_ROOT_THICKNESS = 0.5       # the root row is this fraction of the lock thickness (it hides in the dome)


def _sidelock_root_row(rig: Rig):
    """``(z, x_in, y_in, x_out, y_out)`` of the root row: the first table row's edges carried up to
    :data:`SIDELOCK_ROOT_Z` along their dome azimuths, :data:`SIDELOCK_ROOT_INSET` inside the dome."""
    c = np.array(rig.dome_center)
    z0, xi, yi, xo, yo = rig.sidelock_rows[0]
    out = [SIDELOCK_ROOT_Z]
    for x, y in ((xi, yi), (xo, yo)):
        psi = math.atan2(x, y - c[1])
        p, n = _dome_section_point(rig, SIDELOCK_ROOT_Z, psi)
        q = p - SIDELOCK_ROOT_INSET * n
        out += [float(q[0]), float(q[1])]
    return tuple(out)


def _sidelock(rig: Rig, side: int) -> mk.Mesh:
    rows = np.array((_sidelock_root_row(rig),) + tuple(rig.sidelock_rows))
    n_root = 1
    inner = np.stack([rows[:, 1], rows[:, 2], rows[:, 0]], axis=1)
    outer = np.stack([rows[:, 3], rows[:, 4], rows[:, 0]], axis=1)
    k = len(inner)
    mid = 0.5 * (inner + outer)
    d = outer - inner
    width = np.linalg.norm(d, axis=1)
    acr = d / width[:, None]
    # thickness direction: horizontal, perpendicular to the edge-to-edge direction, pointing forward
    nrm = np.stack([acr[:, 1], -acr[:, 0], np.zeros(k)], axis=1)
    nrm /= np.linalg.norm(nrm, axis=1)[:, None]
    nrm[nrm[:, 1] > 0] *= -1.0
    th = np.full(k, rig.sidelock_thickness)
    th[:n_root] *= SIDELOCK_ROOT_THICKNESS
    pu = np.array([u for u, _ in SIDELOCK_PROFILE])
    share = np.array([SIDELOCK_FRONT_SHARE if f else SIDELOCK_FRONT_SHARE - 1.0 for _, f in SIDELOCK_PROFILE])
    pv = share * (1.0 - pu ** 2) ** SIDELOCK_FULLNESS     # x thickness: front > 0, back < 0, 0 at the edges
    rings = []
    for i in range(k):
        rings.append(mid[i] + (pu * 0.5 * width[i])[:, None] * acr[i] + (pv * th[i])[:, None] * nrm[i])
    # fit (merge step): the lower rows lie on the lapel / scarf, so move them forward until the lock stays
    # rig.hair_outfit_gap in front of the outfit; checked on both sides (the locks stay mirror images)
    T = _outfit_triangles(rig, OUTFIT_FRONT)

    def deficit(p):
        ys = [_outfit_y(T, sx * p[0], p[2], True) for sx in (1.0, -1.0)]
        ys = [y for y in ys if y is not None]
        return p[1] - (min(ys) - rig.hair_outfit_gap) if ys else 0.0

    movable = [bool(r[0, 2] < SIDELOCK_FIT_TOP_Z) for r in rings]
    shift = _fit_rows(rings, deficit, movable, -1.0)
    rings = [r - np.array([0.0, 1.0, 0.0]) * shift[i].max() for i, r in enumerate(rings)]   # rigid per row
    # groups: front inner half + back 1, front outer half 2: the central crease and the (sharp) outer edge
    # are feature lines, the inner edge draws only as a silhouette
    m = len(SIDELOCK_PROFILE)
    G = np.ones((k - 1, m), dtype=np.int64)
    for j in range(m):
        (u0, f0), (u1, f1) = SIDELOCK_PROFILE[j], SIDELOCK_PROFILE[(j + 1) % m]
        if f0 and f1 and min(u0, u1) >= 0.0:                  # front, outer half
            G[:, j] = 2
    # the crease starts at sidelock_crease_top_z: above it both front halves share group 1
    zq = 0.5 * (mid[:-1, 2] + mid[1:, 2])
    G[(zq > rig.sidelock_crease_top_z)[:, None] & (G == 2)] = 1
    mesh = mk.loft(rings, "flat", "flat", groups=G, cap_groups=(1, 3))       # root cap smooth (buried)
    if side < 0:
        mesh = mesh.mirror_x()
    return mk.split_twisted(mk.inscribed_fan(mesh), TWIST_SPLIT_DEG)


# ---------------------------------------------------------------------------------------------------------
# H5 stray strand (§C.4)
# ---------------------------------------------------------------------------------------------------------
STRAND_POINTS = 9
STRAND_SIDES = 4
#: Round 4 (tech F4): lateral (x) shift of the rig's strand points P0 ... P6: P4 / P5 move out 3 / 4.5 mm, so
#: the strand passes outside the (shortened) brow's outer end and the lid's outer corner (spec I.12) instead of
#: crossing them.  Wanted as a rig change (``strand_points``).
STRAND_DX = (0.0, 0.0, 0.0, 0.001, 0.003, 0.0045, 0.0)


def _strand(rig: Rig, lock_l: mk.Mesh) -> mk.Mesh:
    pts = [np.array(p) + np.array([dx, 0.0, 0.0]) for p, dx in zip(rig.strand_points, STRAND_DX)]
    # the tip lies on the sidelock's front face (§C.4 P6): find that face along +y
    tip = pts[-1]
    lock = SkinSurface(lock_l)
    y = lock.y(tip[0], tip[2])
    if y is not None:
        tip = np.array([tip[0], y - 0.5 * rig.strand_thickness - 0.0005, tip[2]])
        pts[-1] = tip
    path = _catmull_rom(np.array(pts), STRAND_POINTS)
    L = float(np.sum(np.linalg.norm(np.diff(path, axis=0), axis=1)))
    taper = rig.strand_taper_length / L

    def width(s):
        return rig.strand_width * float(np.clip((1.0 - s) / taper, 0.12, 1.0))

    def thick(s):
        return rig.strand_thickness * float(np.clip((1.0 - s) / taper, 0.25, 1.0))

    c = np.array(rig.dome_center)
    return mk.sweep(path, width=width, thickness=thick, profile=mk.profile_ellipse(STRAND_SIDES, 45.0),
                    normals=path - c, start="round", end="pointed", groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------------
# H2 side curtain + back sheet (§C.6)
# ---------------------------------------------------------------------------------------------------------
#: The curtain starts inside the dome and emerges from under it above the headband's buried ends:
#: ``rig.curtain_top_rows`` replace the spec's first curtain row.
BACK_GROOVE_DEPTH = 0.002
BACK_STRAND_LINES = True            # the grooves are also group boundaries (strand lines on the back)
BACK_BOTTOM_ROW_Z = 0.885           # last straight row above the clumps
BACK_PLATE_ROWS = (1.180, 1.100)   # 1.100: the spec row over the collar flap (merge fit); round 3 (perf F3):
#                                   the 1.010 row dropped (the plate hangs straight from 1.10 to 0.885)
BACK_CURVE = 0.025                  # the plate curves forward by this at its lateral edges (s = +-1)
#: Round 1 (F8 / T4): the hem.  Clumps of these relative widths (her right to her left) over the notch-row
#: half-width HEM_HALF_WIDTH; each tip is a single vertex on a convex-down hem (z rig.clump_tip_z at the middle, HEM_TIP_OUTER_Z at the outer clumps, quadratic in x);
#: the notches stand NOTCH_DEPTHS above the higher of their two tips; the lateral edges come in to
#: EDGE_BOTTOM (x, z).  (The review asked for 3 mm blunt tips; a tip pair costs two H2 columns, ~0.04 s of
#: the TS still frame for all five, so the tips are single vertices on shallow 25-35 degree slopes.)
CLUMP_WEIGHTS = (0.9, 1.15, 1.0, 1.2, 0.85)
HEM_HALF_WIDTH = 0.146             # round 2 (F12): the lateral edges taper in over the last 10 cm
HEM_TIP_OUTER_Z = 0.842          # tip z of the outer clumps (the middle one: rig.clump_tip_z)
NOTCH_DEPTHS = (0.010, 0.014, 0.012, 0.009)
EDGE_BOTTOM = (0.137, 0.851)
#: Round 2 (F12): the plate's outer surface is this much prouder at the midline than at the lateral edges (a
#: rounded cross-section; the thickness grows by it at the midline, quadratic in S).
BACK_ROUND = 0.004
#: Round 1 (T2): the column whose crescent point is at psi = +-90 degrees (the extreme-x vertex of every
#: curtain row whose front edge comes forward past the side).  Round 3 (perf F3): no extra column at
#: S = +-0.95 any more: the curtain's front edge now ends ~10-15 degrees past the side (CURTAIN_FRONT_Y).
CRESCENT_SIDE_S = 0.90
#: Round 1 (F1): the curtain thins to CURTAIN_END_THICKNESS over the last CURTAIN_TAPER_DEG of its crescent
#: (the end face is in the outer surface's group).
CURTAIN_END_THICKNESS = 0.006
CURTAIN_TAPER_DEG = 30.0
#: Curtain rows at or above this height take their front edge from CURTAIN_FRONT_Y (rounds 1-2: they ended
#: inside the sidelock, no further forward than y -0.038).
CURTAIN_TUCK_MIN_Z = 1.28
#: Round 3 (F1): those rows no longer end inside the sidelock (the curtain, outside the lock, then hid it in
#: profile from 1.37 to 1.27 and framed the face like a hood): their front edge
#: ``y_end`` is this table ``(z, y)`` (linear in z), ~3 mm in front of the lock's back (outer) edge (the
#: curtain lies outside the lock, so in profile it covers the lock's back 3 mm and no skin shows between
#: them): the lock is the front-most hair from the band to its cut with the side hair behind it.
CURTAIN_FRONT_Y = ((1.290, -0.014), (1.340, -0.015), (1.405, -0.029), (1.425, -0.031), (1.452, -0.034))
#: Round 4 (tech F1): the lateral strips' twisted quads are split down to the plate row at this height.
PLATE_SPLIT_MIN_Z = 1.17
#: Thickness of the plate's lateral edges (fraction of the row thickness; round 1, T2: was 0.4).
BACK_EDGE_TAPER = 0.7


def _clump_columns(rig: Rig):
    """Columns of H2: ``(S, bottom (U, 2), notch_s, notch_cols)``: the column parameters ``S`` (-1 = her right
    edge ... +1 = her left edge; ``x = S * hw`` on the plate rows), the ``(x, z)`` of each column on the
    bottom (hem) row, and the S of the notches."""
    W = HEM_HALF_WIDTH
    w = np.array(CLUMP_WEIGHTS[:rig.hair_clumps] if len(CLUMP_WEIGHTS) >= rig.hair_clumps
                 else (1.0,) * rig.hair_clumps, dtype=np.float64)
    b = -W + 2.0 * W * np.concatenate([[0.0], np.cumsum(w)]) / w.sum()      # clump borders (notches)
    centres = 0.5 * (b[1:] + b[:-1])
    edge_x = centres[-1] if abs(centres[-1]) > abs(centres[0]) else -centres[0]

    def tip_z(x):
        return rig.clump_tip_z + (HEM_TIP_OUTER_Z - rig.clump_tip_z) * (x / edge_x) ** 2

    pts = [(-EDGE_BOTTOM[0], EDGE_BOTTOM[1]), (EDGE_BOTTOM[0], EDGE_BOTTOM[1])]
    for xc in centres:
        pts.append((xc, tip_z(xc)))
    notches = b[1:-1]
    depths = (NOTCH_DEPTHS + (NOTCH_DEPTHS[-1],) * len(notches))[:len(notches)]
    for k, xn in enumerate(notches):
        pts.append((xn, max(tip_z(centres[k]), tip_z(centres[k + 1])) + depths[k]))
    key = sorted(pts)
    kx = np.array([p[0] for p in key])
    kz = np.array([p[1] for p in key])
    ks = np.array([p[0] / W for p in key])
    ks[0], ks[-1] = -1.0, 1.0
    S = list(ks)
    S += [CRESCENT_SIDE_S, -CRESCENT_SIDE_S]
    S = np.array(sorted(set(round(float(s), 9) for s in S)))
    bx = np.interp(S, ks, kx)                  # the extra columns keep their order between the key points
    bz = np.interp(bx, kx, kz)
    return S, np.stack([bx, bz], axis=1), notches / W


def _blouse_back(rig: Rig, x: float, z: float) -> float:
    """Back surface y of the blouse at ``(x, z)`` (the collar is probed on its mesh, see
    :func:`_fit_back_rows`)."""
    hw, yf, yb = rig.blouse_section(z)
    e = rig.torso_exponent
    u = min(1.0, abs(x) / hw)
    return yb * (1.0 - u ** e) ** (1.0 / e)


def _fit_back_rows(rig: Rig, rows, n_fixed: int):
    """Move the plate rows (after the first ``n_fixed`` crescent rows) back until the inner surface stays
    ``rig.back_sheet_gap`` off the blouse and ``rig.hair_outfit_gap`` off the collar flap and its stripe (their
    meshes), at the rows and along the chords between them; the outer surface moves with it."""
    T = _outfit_triangles(rig, OUTFIT_BACK)

    def deficit(p):
        need = _blouse_back(rig, p[0], p[2]) + rig.back_sheet_gap
        for sx in (1.0, -1.0):                     # both sides: the sheet stays symmetric
            y = _outfit_y(T, sx * p[0], p[2], False)
            if y is not None:
                need = max(need, y + rig.hair_outfit_gap)
        return need - p[1]

    inner = [i for _, i in rows]
    movable = [r >= n_fixed for r in range(len(rows))]
    shift = _fit_rows(inner, deficit, movable, 1.0, across=2)
    dy = np.array([0.0, 1.0, 0.0])
    return [(o + shift[r][:, None] * dy, i + shift[r][:, None] * dy) for r, (o, i) in enumerate(rows)]


def _crescent_psi(S, psi_end: float) -> np.ndarray:
    """Crescent angle of each column: ``|S| <= CRESCENT_SIDE_S`` spans 0..90 degrees and the rest
    90 degrees..``psi_end`` when the row's front edge comes forward past the side; else linear in S."""
    a = np.abs(S)
    if psi_end > 0.5 * math.pi + 1e-9:
        p = np.where(a <= CRESCENT_SIDE_S, a / CRESCENT_SIDE_S * 0.5 * math.pi,
                     0.5 * math.pi + (a - CRESCENT_SIDE_S) / (1.0 - CRESCENT_SIDE_S) * (psi_end - 0.5 * math.pi))
    else:
        p = a * psi_end
    return np.sign(S) * p


def _crescent_thickness(t: float, psi, psi_end: float) -> np.ndarray:
    """Thickness along a crescent row: ``t``, thinning to :data:`CURTAIN_END_THICKNESS` over the last
    :data:`CURTAIN_TAPER_DEG` before a front edge that comes forward past the side."""
    if psi_end <= 0.5 * math.pi + 1e-9:
        return np.full(len(psi), t)
    span = min(math.radians(CURTAIN_TAPER_DEG), psi_end - 0.5 * math.pi)
    k = _smoothstep(psi_end - span, psi_end, np.abs(psi))
    return t - (t - min(t, CURTAIN_END_THICKNESS)) * k


def _psi_at_y(f, y_end: float) -> float:
    """Crescent angle (past the side, 90 ... 170 degrees) at which the outline ``f(psi, 0)`` reaches
    ``y = y_end`` (bisection)."""
    lo, hi = math.radians(90.0), math.radians(170.0)
    if f(lo, 0.0)[1] <= y_end:
        return lo
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if f(mid, 0.0)[1] > y_end:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _front_y(z: float) -> float:
    zs, ys = zip(*CURTAIN_FRONT_Y)
    return float(np.interp(z, zs, ys))


def _back_hair(rig: Rig, dome: mk.Mesh) -> mk.Mesh:
    """H2: one slab from inside the dome (the curtain crescents) through the back sheet plate to the
    clumps."""
    S, bottom, notch_s = _clump_columns(rig)
    U = len(S)

    def ellipse_fn(cy, axc, by):
        def f(psi, inset):
            return np.array([(axc - inset) * math.sin(psi), cy + (by - inset) * math.cos(psi)])
        return f

    def dome_fn(z, off):
        def f(psi, inset):
            p, n = _dome_section_point(rig, z, psi)
            return (p + (off - inset) * n)[:2]
        return f

    # crescent rows (z, outline(psi, inset), t, psi_end): the rows emerging from the dome, then the table
    table = [tuple(r) for r in rig.curtain_rows[1:]]
    cres = []
    for z, cy, axc, yb_o, t, y_end in table:
        f = ellipse_fn(cy, axc, yb_o - cy)
        if z >= CURTAIN_TUCK_MIN_Z:
            pe = _psi_at_y(f, _front_y(z))
        else:
            pe = math.acos(float(np.clip((y_end - cy) / (yb_o - cy), -1.0, 1.0)))
        cres.append((z, f, t, pe))
    top = []
    for z, off, t in rig.curtain_top_rows:
        f = dome_fn(z, off)
        top.append((z, f, t, _psi_at_y(f, _front_y(z))))
    rows = []
    for z, f, t, pe in top + cres:
        psi = _crescent_psi(S, pe)
        tt = _crescent_thickness(t, psi, pe)
        o = np.array([f(p, 0.0) for p in np.abs(psi)])
        i = np.array([f(p, ti) for p, ti in zip(np.abs(psi), tt)])
        o[:, 0] *= np.sign(S)
        i[:, 0] *= np.sign(S)
        rows.append((np.column_stack([o, np.full(U, z)]), np.column_stack([i, np.full(U, z)])))
    # plate rows: x = s * hw, curving forward at the edges, kept off the body
    sheet = np.array(rig.back_sheet_rows)

    def plate_row(z, zs_row=None, xs_row=None):
        hw = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 1]))
        yi = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 2]))
        yo = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 3]))
        zz = np.full(U, z) if zs_row is None else zs_row
        x = S * hw if xs_row is None else xs_row
        curve = BACK_CURVE * S ** 2
        y_in = yi - curve
        y_out = yo - curve + BACK_ROUND * (1.0 - S ** 2)
        for k in range(U):
            need = _blouse_back(rig, x[k], zz[k]) + rig.back_sheet_gap
            if y_in[k] < need:
                y_out[k] += need - y_in[k]
                y_in[k] = need
        return (np.stack([x, y_out, zz], axis=1), np.stack([x, y_in, zz], axis=1))

    n_fixed = len(rows)
    rows += [plate_row(z) for z in BACK_PLATE_ROWS + (BACK_BOTTOM_ROW_Z,)]
    rows.append(plate_row(rig.clump_notch_z, bottom[:, 1], bottom[:, 0]))
    rows = _fit_back_rows(rig, rows, n_fixed)
    groove_s = sorted(notch_s, key=lambda s: (abs(s), s))[:rig.hair_grooves]
    gcols = sorted(int(np.argmin(np.abs(S - s))) for s in groove_s)
    n_cres = len(top) + len(cres)
    return _h2_slab(rig, rows, gcols, n_cres)


def _h2_slab(rig: Rig, rows, gcols, n_cres: int) -> mk.Mesh:
    """Slab through H2 rows ``[(outer (U, 3), inner (U, 3)), ...]`` with the strand grooves at the columns
    ``gcols`` (2 mm deep below ``groove_top_z``) and the outer strips between them in their own groups.  The
    first ``n_cres`` rows are curtain crescents (their end columns are the front edges, already tapered)."""
    Fo = np.stack([o for o, _ in rows], axis=1)               # (U, V, 3)
    Bi = np.stack([i for _, i in rows], axis=1)
    U, V = Fo.shape[:2]
    for k in (0, U - 1):                                      # plate: thinner lateral edges
        for j in range(n_cres, V):
            Fo[k, j] = Bi[k, j] + BACK_EDGE_TAPER * (Fo[k, j] - Bi[k, j])
    for j in range(V):
        z = Fo[0, j, 2]
        depth = BACK_GROOVE_DEPTH * float(_smoothstep(rig.groove_top_z, rig.groove_top_z - 0.08, z))
        if depth <= 0:
            continue
        for gc in gcols:
            nrm = Fo[gc, j] - Bi[gc, j]
            nrm /= np.linalg.norm(nrm)
            Fo[gc, j] = Fo[gc, j] - depth * nrm
    front = np.zeros((U - 1, V - 1), dtype=np.int64)
    edges = [0] + (list(gcols) if BACK_STRAND_LINES else []) + [U - 1]
    for k in range(len(edges) - 1):
        front[edges[k]:edges[k + 1], :] = 1 + k
    nstrips = len(edges) - 1
    g_in = nstrips + 1
    rims = _rims_by_light(Fo, Bi, front, g_in, nstrips + 2)
    # round 1 (F1 / T2): the front end faces of the curtain and the plate's lateral faces are in the outer
    # surface's group: they draw only as silhouettes (no blunt end lines, one continuous outer edge)
    u0 = [int(front[0][v]) for v in range(V - 1)]
    u1 = [int(front[U - 2][v]) for v in range(V - 1)]
    mesh = mk.inscribed_fan(slab(Fo, Bi, (front, g_in, rims["v0"], rims["v1"], u0, u1)))
    # the outer surface down to the last tucked row (below it, behind the jaw and the shoulder, the curtain's
    # front strip folds sharply and its split diagonals would draw as a fan of outlines)
    _faces, kinds = slab_faces(U, V)
    only = [k[0] == "front" and Fo[0, k[2] + 1, 2] >= CURTAIN_TUCK_MIN_Z for k in kinds]
    # round 4 (tech F1): ... and every face of the plate's lateral strips (the outer and inner faces of the
    # first / last column and the lateral faces) from the crescent rows into the plate (row z >= PLATE_SPLIT_MIN_Z),
    # where the crescent turns into the plate and those quads twist by up to 105 degrees: a twisted lateral quad
    # hid a 1.4 mm piece of the back hair's outline at the shoulder (az 120 / 240).
    for i, k in enumerate(kinds):
        if k[0] == "front" or k[0] == "back" and k[1] in (0, U - 2) or k[0] in ("u0", "u1"):
            v = k[2] if k[0] in ("front", "back") else k[1]
            if Fo[0, v + 1, 2] >= PLATE_SPLIT_MIN_Z and Fo[0, v, 2] < CURTAIN_TUCK_MIN_Z:
                only[i] = True
    return mk.split_twisted(mesh, TWIST_SPLIT_DEG, only=only)



def _rims_by_light(F, B, front, g_back: int, g_rim: int) -> dict:
    """Groups of the ``v1`` / ``u0`` / ``u1`` rim faces of the slab between ``F`` (outer, groups ``front``
    ``(U-1, V-1)``) and ``B`` (inner, ``g_back``): a rim face takes the group of the big face it borders whose
    lit state differs from its own (that edge is smooth: no construction ray, no hidden feature edge), so only
    the other border is a feature line; ``g_rim`` when both borders share its lit state."""
    U, V = F.shape[:2]
    faces, kinds = slab_faces(U, V)
    probe = oriented(mk.Mesh(np.concatenate([F.reshape(-1, 3), B.reshape(-1, 3)]), faces, 1))
    fn, _ = mk.face_normals(probe)
    lit = {k: bool(fn[i] @ SUN > 0.0) for i, k in enumerate(kinds)}
    adj = {"v0": lambda i: (i, 0), "v1": lambda i: (i, V - 2), "u0": lambda i: (0, i), "u1": lambda i: (U - 2, i)}
    out = {}
    for which, count in (("v0", U - 1), ("v1", U - 1), ("u0", V - 1), ("u1", V - 1)):
        groups = []
        for i in range(count):
            u, v = adj[which](i)
            r = lit[(which, i)]
            if r != lit[("front", u, v)]:
                groups.append(int(front[u][v]))
            elif r != lit[("back", u, v)]:
                groups.append(g_back)
            else:
                groups.append(g_rim)
        out[which] = groups
    return out


# ---------------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """Parts of :data:`REGIONS` for ``rig``."""
    dome = _dome(rig)
    band, ridge = _headband(rig, dome)
    bangs = _bangs(rig, dome)
    lock_l = _sidelock(rig, 1)
    lock_r = _sidelock(rig, -1)
    strand = _strand(rig, lock_l)
    back = _back_hair(rig, dome)
    return [
        Part("hair.dome", "hair", dome, "hair"),
        Part("hair.bangs", "hair", bangs, "hair"),
        Part("hair.strand", "hair", strand, "hair"),
        Part("hair.headband", "headband", band, "headband"),
        Part("hair.headband_ridge", "uniform", ridge, "headband"),
        Part("hair.sidelock_l", "hair", lock_l, "hair", obj="sidelocks"),
        Part("hair.sidelock_r", "hair", lock_r, "hair", obj="sidelocks"),
        Part("hair.back", "hair", back, "hair", obj="back_hair"),
    ]

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
* **H4 sidelocks** (§C.3): lens-section ribbons swept through the spec's edge table, their roots rising into
  the dome under the band; the cut face and a central strand crease are feature lines.
* **H5 strand** (§C.4): one thin swept strand on her left.
* **H2 side curtain + back sheet** (§C.6): one slab from inside the dome down to seven pointed clumps; the
  curtain's front edges, the lateral edges and the clump ends are rims in their own groups, and four strand
  lines (group boundaries + shallow grooves) end at the notches between the middle clumps.
"""

from __future__ import annotations

import math

import numpy as np

from . import meshkit as mk
from .head import SkinSurface, classify_rims, head_section, skin_surface, slab
from .meshkit import Part
from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The mannequin regions this module replaces.
REGIONS = ("hair", "headband")

SIDES = (1, -1)


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
DOME_AZIMUTHS = (0, 15, 30, 45, 60, 75, 90, 105, 120, 135, 150, 165, 180, 192, 204, 216, 228, 240, 250, 260, 270,
                 280, 290, 300, 312, 324, 336, 348)
#: Rings: constant-z rings over the crown (clean silhouettes), then rings blending down to the bottom boundary.
DOME_FLAT_THETA = (6.0, 12.5, 19.0, 26.0, 33.0, 40.0, 47.0, 53.5)   # constant-z rings (polar angle, deg)
DOME_BLEND = (0.4, 0.75, 1.0)       # then rings blending from the last flat ring to the bottom boundary
#: Bottom of the dome behind the headband's ends (inside the side curtain, which starts at z 1.45).
DOME_BACK_BOTTOM_Z = 1.445
#: In front the dome ends this far below the band centreline (under the band's lower half).
DOME_BAND_DROP = 0.002
#: The fan closing the dome underneath ends here (inside the skull).
DOME_CAP_APEX = (0.0, 0.020, 1.440)


def _band_line(rig: Rig) -> np.ndarray:
    """The headband centreline from her right end to her left end (spec points mirrored)."""
    cl = np.array(rig.band_centreline)
    return np.concatenate([cl[:0:-1] * np.array([-1.0, 1.0, 1.0]), cl])


def _ellipsoid(rig: Rig, theta, phi) -> np.ndarray:
    """Point of the §C top-hair ellipsoid at polar angle ``theta`` (from +Z) and azimuth ``phi`` (radians)."""
    c = np.array(rig.dome_center)
    ax, ayf, az = rig.dome_radii
    ay = rig.dome_back_radius if math.sin(phi) > 0 else ayf
    s = math.sin(theta)
    return c + np.array([ax * s * math.cos(phi), ay * s * math.sin(phi), az * math.cos(theta)])


def _ellipsoid_normal(rig: Rig, p) -> np.ndarray:
    c = np.array(rig.dome_center)
    ax, ayf, az = rig.dome_radii
    d = np.asarray(p, dtype=np.float64) - c
    r = np.array([ax, rig.dome_back_radius if d[1] > 0 else ayf, az])
    n = d / r ** 2
    return n / np.linalg.norm(n)


def _dome_bottom_z(rig: Rig, phi: float) -> float:
    """z of the dome's bottom boundary at azimuth ``phi``: the band centre in front, else
    :data:`DOME_BACK_BOTTOM_Z`."""
    c = np.array(rig.dome_center)
    band = _band_line(rig)
    az_band = np.unwrap(np.arctan2(band[:, 1] - c[1], band[:, 0]))      # her right end ... her left end
    a = math.atan2(math.sin(phi), math.cos(phi))
    # bring a into the band's azimuth range (around -pi/2)
    while a > az_band.max() + math.pi:
        a -= 2 * math.pi
    while a < az_band.min() - math.pi:
        a += 2 * math.pi
    lo, hi = min(az_band[0], az_band[-1]), max(az_band[0], az_band[-1])
    if not lo <= a <= hi:
        return DOME_BACK_BOTTOM_Z
    order = np.argsort(az_band)
    return float(np.interp(a, az_band[order], band[order, 2])) - DOME_BAND_DROP


def _dome(rig: Rig) -> mk.Mesh:
    c = np.array(rig.dome_center)
    az = rig.dome_radii[2]
    phis = np.radians(DOME_AZIMUTHS)
    theta_b = []
    for phi in phis:
        zb = _dome_bottom_z(rig, phi)
        theta_b.append(math.acos(np.clip((zb - c[2]) / az, -1.0, 1.0)))
    rings = []
    th0 = math.radians(DOME_FLAT_THETA[-1])
    for th in DOME_FLAT_THETA:
        rings.append(np.array([_ellipsoid(rig, math.radians(th), phi) for phi in phis]))
    for t in DOME_BLEND:
        rings.append(np.array([_ellipsoid(rig, th0 + t * (tb - th0), phi) for tb, phi in zip(theta_b, phis)]))
    top = c + np.array([0.0, 0.0, az])
    return mk.loft(rings, ("pole", top), ("pole", DOME_CAP_APEX), groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------------
# headband (§C.1)
# ---------------------------------------------------------------------------------------------------------
BAND_POINTS = 25                    # along the band (her right end ... her left end)
RIDGE_SINK = 0.0002                 # the ridge's base sits this far inside the band's outer face
BAND_SHRINK = 0.25                  # the inner face is this fraction of the band width (undercut walls)
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


def _classified(F, B, shrink: float) -> mk.Mesh:
    """Band slab between ``(U, 2, 3)`` grids ``F`` (outer face) and ``B`` (inner face): the inner face is
    narrowed to ``shrink`` of its width (undercut walls: the outer face's two borders are camera silhouettes
    from the whole front half space) and the rims are grouped by :func:`head.classify_rims` (feature lines
    where they cost no construction ray)."""
    mid = B.mean(axis=1, keepdims=True)
    B = mid + shrink * (B - mid)
    groups, _undercut = classify_rims(F, B)
    return slab(F, B, (1, 2, *groups))


def _headband(rig: Rig, dome: mk.Mesh):
    P, N, Bx = _band_frames(rig, dome)
    base = P - rig.band_embed * N
    w = 0.5 * rig.band_width
    F = np.stack([base - w * Bx + rig.band_thickness * N, base + w * Bx + rig.band_thickness * N], axis=1)
    Bk = np.stack([base - w * Bx, base + w * Bx], axis=1)
    band = _classified(F, Bk, BAND_SHRINK)
    # pink ridge over the visible span
    outer = base + rig.band_thickness * N
    xs = P[:, 0]
    keep = np.abs(xs) <= rig.band_visible_x
    k0, k1 = int(np.nonzero(keep)[0][0]), int(np.nonzero(keep)[0][-1])
    o, n, b = outer[k0:k1 + 1], N[k0:k1 + 1], Bx[k0:k1 + 1]
    rw = 0.5 * rig.band_ridge_width
    top = o + rig.band_ridge_height * n
    bot = o - RIDGE_SINK * n
    F = np.stack([top - rw * b, top + rw * b], axis=1)
    Bk = np.stack([bot - rw * b, bot + rw * b], axis=1)
    ridge = _classified(F, Bk, RIDGE_SHRINK)
    return band, ridge


# ---------------------------------------------------------------------------------------------------------
# H3 bangs (§C.2)
# ---------------------------------------------------------------------------------------------------------
BANGS_STRIP_COLS = 3                # quads per strand strip across
#: The bangs' outer surface starts just in front of the band's lower inner corner (the block comes out from
#: under the band flush with it and hides the corner), leans forward to the curl start and curls back in
#: (``rig.bangs_curl``) to the flat cut; the top row continues ``rig.bangs_top_extension`` up under the band.
BANGS_UNDER_BAND = 0.0005
BANGS_END_X = 0.072                 # vertical end faces (= rig.bangs_half_width)


def _band_x_frames(rig: Rig, dome: mk.Mesh):
    """Interpolators over x of the band's lower inner corner, its outward normal and across direction."""
    P, N, Bx = _band_frames(rig, dome)
    corner = P - rig.band_embed * N - 0.5 * rig.band_width * Bx
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

    # columns at equal arc length along the outer cut line
    dense = np.linspace(-BANGS_END_X, BANGS_END_X, 145)
    pts = np.array([outer_cut(column_at(x))[0] for x in dense])
    s = np.concatenate([[0.0], np.cumsum(np.linalg.norm(np.diff(pts, axis=0), axis=1))])
    ncol = rig.bangs_strips * BANGS_STRIP_COLS + 1
    xs = np.interp(np.linspace(0.0, s[-1], ncol), s, dense)
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
    g_back, g_cut, g_end = nstrip + 1, nstrip + 2, nstrip + 3
    # rims: v0 = top (hidden under the band), v1 = the cut, u0 / u1 = the end faces
    return slab(F, Bk, (front, g_back, g_back, g_cut, g_end, g_end))


# ---------------------------------------------------------------------------------------------------------
# H4 sidelocks (§C.3)
# ---------------------------------------------------------------------------------------------------------
#: Root rows added above the spec table: the lock rises into the dome under the band, narrowing,
#: ``(z, x_in, y_in, x_out, y_out)`` for her left.
SIDELOCK_ROOT_ROWS = ((1.463, 0.063, -0.051, 0.076, -0.034),)
SIDELOCK_PROFILE = 8                # lens points (edges at 0 and 4, crease vertex at 2 on the front face)
SIDELOCK_INSERT_AFTER = (5, 6)      # Catmull-Rom rows inserted after these table rows (the shoulder bend)
SIDELOCK_ROOT_THICKNESS = 0.5       # the root row is this fraction of the lock thickness (it hides in the dome)


def _cr_insert(P, after):
    """Rows ``P`` with a Catmull-Rom midpoint inserted after each index in ``after`` (sorted)."""
    P = np.asarray(P, dtype=np.float64)
    Q = np.concatenate([2 * P[:1] - P[1:2], P, 2 * P[-1:] - P[-2:-1]])
    out = []
    for i in range(len(P)):
        out.append(P[i])
        if i in after:
            p0, p1, p2, p3 = Q[i], Q[i + 1], Q[i + 2], Q[i + 3]
            out.append(0.5 * p1 + 0.5 * p2 + 0.125 * (p1 - p0) - 0.125 * (p3 - p2))
    return np.array(out)


def _sidelock(rig: Rig, side: int) -> mk.Mesh:
    rows = np.array(SIDELOCK_ROOT_ROWS + tuple(rig.sidelock_rows))
    n_root = len(SIDELOCK_ROOT_ROWS)
    ins = [n_root + k for k in SIDELOCK_INSERT_AFTER]
    inner = _cr_insert(np.stack([rows[:, 1], rows[:, 2], rows[:, 0]], axis=1), ins)
    outer = _cr_insert(np.stack([rows[:, 3], rows[:, 4], rows[:, 0]], axis=1), ins)
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
    m = SIDELOCK_PROFILE
    t = 2.0 * np.pi * np.arange(m) / m
    prof = np.stack([np.cos(t), np.sign(np.sin(t)) * np.abs(np.sin(t)) ** 0.6], axis=1)   # lens
    rings = []
    for i in range(k):
        rings.append(mid[i] + prof[:, :1] * (0.5 * width[i]) * acr[i] + prof[:, 1:2] * (0.5 * th[i]) * nrm[i])
    # groups: front face halves 1 (inner half) / 2 (outer half) -> the strand crease; back 3
    G = np.zeros((k - 1, m), dtype=np.int64)
    for j in range(m):
        a = t[j] + np.pi / m                                  # mid angle of quad j
        if math.sin(a) > 0:                                   # front (profile +y = nrm)
            G[:, j] = 2 if math.cos(a) > 0 else 1
        else:
            G[:, j] = 3
    # the crease starts at sidelock_crease_top_z: above it both front halves share group 1
    zq = 0.5 * (mid[:-1, 2] + mid[1:, 2])
    G[(zq > rig.sidelock_crease_top_z)[:, None] & (G == 2)] = 1
    mesh = mk.loft(rings, "flat", "flat", groups=G, cap_groups=(1, 4))       # root cap smooth (buried)
    if side < 0:
        mesh = mesh.mirror_x()
    return mesh


# ---------------------------------------------------------------------------------------------------------
# H5 stray strand (§C.4)
# ---------------------------------------------------------------------------------------------------------
STRAND_POINTS = 12
STRAND_SIDES = 4


def _strand(rig: Rig, lock_l: mk.Mesh) -> mk.Mesh:
    pts = [np.array(p) for p in rig.strand_points]
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
#: Rows replacing the spec's first curtain row: the curtain starts inside the dome and emerges from under it
#: above the headband's buried ends, ``(z, offset from the dome section, thickness)`` (the spec row at z 1.45
#: stands 6-8 mm outside the dome and would leave a ledge).
CURTAIN_TOP_ROWS = ((1.482, -0.002, 0.010), (1.465, 0.0025, 0.016), (1.450, 0.005, 0.020))
BACK_GROOVE_DEPTH = 0.002
BACK_BOTTOM_ROW_Z = 0.885           # last straight row above the clumps
BACK_PLATE_ROWS = (1.180, 1.060, 0.950)
BACK_CURVE = 0.025                  # the plate curves forward by this at its lateral edges (s = +-1)
BACK_BODY_GAP = 0.008               # inner surface at least this far off the blouse / collar back
COLLAR_LAYER = 0.005                # collar gap + thickness on the blouse back (spec D.2)


def _clump_columns(rig: Rig):
    """Column parameters ``s`` (-1 = her right edge ... +1 = her left edge) and the bottom-row ``z`` of
    each: edges, the 7 clump tips and the 6 notches between them."""
    hw = rig.back_sheet_rows[-1][1]
    tips = np.array(rig.clump_tip_x)
    notches = 0.5 * (tips[1:] + tips[:-1])
    xs = np.concatenate([[-hw], tips, notches, [hw]])
    zs = np.concatenate([[rig.clump_notch_z], np.full(len(tips), rig.clump_tip_z),
                         np.full(len(notches), rig.clump_notch_z), [rig.clump_notch_z]])
    order = np.argsort(xs)
    return xs[order] / hw, zs[order], notches / hw


def _blouse_back(rig: Rig, x: float, z: float) -> float:
    """Back surface y of the blouse (+ the collar where the back flap covers it) at ``(x, z)``."""
    hw, yf, yb = rig.blouse_section(z)
    e = rig.torso_exponent
    u = min(1.0, abs(x) / hw)
    y = yb * (1.0 - u ** e) ** (1.0 / e)
    o1, o2 = rig.collar_outer[0], rig.collar_outer[1]
    if o1[2] <= z <= rig.collar_inner[0][2] + 0.01 and abs(x) <= o2[0]:
        y += COLLAR_LAYER
    return y


def _back_hair(rig: Rig, dome: mk.Mesh) -> mk.Mesh:
    S, zbot, notch_s = _clump_columns(rig)
    U = len(S)
    c = np.array(rig.dome_center)
    ax_d, ayf_d, az_d = rig.dome_radii
    ayb_d = rig.dome_back_radius

    def dome_section(z):
        q = max(0.0, 1.0 - ((z - c[2]) / az_d) ** 2)
        r = math.sqrt(q)
        return ax_d * r, ayb_d * r

    # crescent rows (z, cy, ax, back y, t, y_end): the rows emerging from the dome, then the spec table
    cres = []
    first = rig.curtain_rows[0]
    for z, off, t in CURTAIN_TOP_ROWS:
        hwd, byd = dome_section(z)
        y_end = first[5] + (0.004 if off < 0 else 0.0)
        cres.append((z, c[1], hwd + off, c[1] + byd + off, t, y_end))
    cres += [tuple(r) for r in rig.curtain_rows[1:]]
    outer_rows, inner_rows = [], []
    for z, cy, axc, yb_o, t, y_end in cres:
        by = yb_o - cy
        psi_end = math.acos(np.clip((y_end - cy) / by, -1.0, 1.0))
        psi = S * psi_end
        o = np.stack([axc * np.sin(psi), cy + by * np.cos(psi), np.full(U, z)], axis=1)
        i = np.stack([(axc - t) * np.sin(psi), cy + (by - t) * np.cos(psi), np.full(U, z)], axis=1)
        outer_rows.append(o)
        inner_rows.append(i)
    # plate rows: x = s * hw, curving forward at the edges, kept off the body
    sheet = np.array(rig.back_sheet_rows)

    def plate_row(z, zs_row=None):
        hw = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 1]))
        yi = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 2]))
        yo = float(np.interp(z, sheet[::-1, 0], sheet[::-1, 3]))
        zz = np.full(U, z) if zs_row is None else zs_row
        x = S * hw
        curve = BACK_CURVE * S ** 2
        y_in = yi - curve
        y_out = yo - curve
        for k in range(U):
            need = _blouse_back(rig, x[k], zz[k]) + BACK_BODY_GAP
            if y_in[k] < need:
                y_out[k] += need - y_in[k]
                y_in[k] = need
        return (np.stack([x, y_out, zz], axis=1), np.stack([x, y_in, zz], axis=1))

    for z in BACK_PLATE_ROWS + (BACK_BOTTOM_ROW_Z,):
        o, i = plate_row(z)
        outer_rows.append(o)
        inner_rows.append(i)
    o, i = plate_row(rig.clump_notch_z, zbot)
    outer_rows.append(o)
    inner_rows.append(i)
    Fo = np.stack(outer_rows, axis=1)                         # (U, V, 3)
    Bi = np.stack(inner_rows, axis=1)
    V = Fo.shape[1]
    # grooves: the notch columns between the middle clumps sink into the outer surface below groove_top_z
    groove_s = [s for s in notch_s if abs(s) < 0.5]
    gcols = [int(np.argmin(np.abs(S - s))) for s in groove_s]
    for j in range(V):
        z = Fo[0, j, 2]
        depth = BACK_GROOVE_DEPTH * float(_smoothstep(rig.groove_top_z, rig.groove_top_z - 0.08, z))
        if depth <= 0:
            continue
        for gc in gcols:
            nrm = Fo[gc, j] - Bi[gc, j]
            nrm /= np.linalg.norm(nrm)
            Fo[gc, j] = Fo[gc, j] - depth * nrm
    # outer strips between the strand lines (the groove columns) in their own groups
    front = np.zeros((U - 1, V - 1), dtype=np.int64)
    edges = [0] + gcols + [U - 1]
    for k in range(len(edges) - 1):
        front[edges[k]:edges[k + 1], :] = 1 + k
    nstrips = len(edges) - 1
    g_in, g_edge, g_clump = nstrips + 1, nstrips + 2, nstrips + 3
    return slab(Fo, Bi, (front, g_in, g_in, g_clump, g_edge, g_edge))


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

"""Neck, top and dress of the Reiya model (SPEC.md §D.1-§D.5): regions ``neck``, ``top``, ``dress`` and ``buttons``.

Regions and the objects they fill (SPEC.md §G, module -> regions mapping):

* ``neck`` -> object ``neck``: the elliptic skin neck the head's jaw turns into (§D.1);
* ``top`` -> object ``top``: the white mock-neck top (``top``): one shell for the mock neck with its lettuce-edge rim
  and the shoulders / upper chest (§D.2); the two white sleeve tubes (``TOP_SLEEVE_TUBES``, off since the finishing
  pass: the balloon sleeves always cover them) set ``obj="arm_l"`` / ``obj="arm_r"``: each lies inside the
  cardigan's balloon sleeve on its side, so it joins that compact arm object;
* ``dress`` -> object ``bodice``: the navy jumper bodice (``dress``) as one solid from the square neckline to the
  high-waist seam, and the two straps (§D.3); the skirt sets ``obj="skirt"``: the long fluted A-line skirt with its
  hem rim, inner facing and ceiling, and the eight flute-valley line stripes (§D.4);
* ``buttons`` -> object ``buttons``: the 17 gold teardrop buttons down the centre front (``buttons``) (§D.5); the
  cardigan's round button (cardigan.py) on the same centre line joins them.

How the lines come out (castplane draws feature edges always and smooth edges only on the camera silhouette;
SPEC.md §F; the sun is ``rig.SUN_TOWARDS``, and a feature edge between a lit and an unlit face costs construction
rays):

* neck, sleeve tubes, straps, stripes and buttons are single-group shells: outlines only, no rays;
* the top: the mock neck's outer wall is group 1; the rim's top face, the inner wall and the dent's floor are group 2,
  so the wavy outer rim edge is a feature line (and the inner edge shows as a silhouette from above); the shoulders and
  chest are group 3, so the fold where the mock neck meets the shoulders draws too (the sheet draws it in the front,
  side and back views; both faces there face up, so it costs almost no rays);
* the bodice: group 1 with the placket strip between x = +-placket_x as group 2 (the two placket lines, real creases
  of 6-7 degrees), its level top ledge (from the edge into the top) and the cap inside the top group 3 (the square
  neckline / top edge) and its bottom cap group 4 (the high-waist seam: the bodice's lower edge laps over the skirt);
* the skirt: group 1 with the placket strip group 2 (the placket lines run on from the seam to the hem), the hem rim,
  the inner facing and the ceiling group 3 (the wavy hem is a feature line; inside, nothing draws but silhouettes),
  the hidden top cap group 1.  The flute valleys draw as thin floating stripes (a group boundary cannot end at
  ``flute_line_top_z`` in the middle of the smooth skirt without a horizontal line).  The outer surface is written as
  triangles (each quad's two fan triangles on its ridge diagonal), so the flank outline follows the triangles' facing
  and crosses each strip once (:func:`_skirt`).

Where the jumper and the cardigan always cover them (v2 finishing pass), the top's lower back and the bodice's back are
coarser (:func:`_top_lower`, :func:`_bodice`): an id z-buffer scan of 864 cameras round her (azimuth every 10 deg,
elevation -60 to 89, at 0.9 and 2.5 m) saw none of the faces they replace, the new faces lie inside the old shells,
and they face the sun as the old ones did, so every object's light silhouette, which castplane draws as its
ground-shadow outline, keeps its edges: the line renders are byte-identical.  Hidden faces are not free otherwise:
castplane draws every shell's light-silhouette loop in the cast-shadow layer, hidden or not.
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The regions this module builds (``--only body`` selects all of them).
REGIONS = ("neck", "top", "dress", "buttons")

SIDES = (1, -1)                       # her left (+X), her right (-X)

# ---------------------------------------------------------------------------------------------------
# Module constants: resolutions and shape factors (every dimension is a Rig field)
# ---------------------------------------------------------------------------------------------------
NECK_POINTS = 16                      # points per neck ring
RIM_SAMPLES_PER_WAVE = 4              # lettuce rim: one scallop per wave, a rounded hump between cusp troughs as
#                                       drawn (4 x lettuce_waves points: 2 |sin| - 1 of half the wave phase, -1, 0.41,
#                                       1, 0.41); the top's torso has lettuce_waves columns, one under every trough
TOP_SLEEVE_POINTS = 8                 # white sleeve tube section points
BODICE_T_STEP = 15.0                  # bodice columns every this many degrees of the section angle (+ the placket) ...
BODICE_FINE_T = (-52.5, -37.5, -22.5)  # ... and between these on her left front side (mirrored), where the section
#                                        turns and the straps tuck in (15 deg facets there sag 1.6 mm)
STRAP_COLUMNS = 3                     # strap slab columns across (the edges and the middle: it follows the shoulder)
#: The top's fill below its shoulder row fans out from the shoulder row point this many points along its loop (which
#: starts one column before the first left-out point): a point near the centre back, from where every fill face faces
#: away from the sun, like the faces it replaces (from the left side's points some would face it and add edges to the
#: top's light silhouette, which castplane draws as its ground-shadow outline)
TOP_FILL_APEX = 4
# -- v2 finishing pass: optional cuts (they change the drawing; the body agent's report measures each) -----------------
# The merge took options B (STRAP_HIDDEN_BACK_STATIONS, TOP_SLEEVE_TUBES) and F (TOP_FLOOR_POINTS_PER_WAVE), not S.
#: Floor points of the mock neck's dent per lettuce wave (RIM_SAMPLES_PER_WAVE: one under every rim column; 1 frees
#: 120 triangles and adds 20 polygons, but the dent's inner wall shows beside the neck from 10 deg up, and its contour
#: lines move up to 4 px in the head close-ups, its shadow outline too; in the scene camera no pixel changes by more
#: than 40 grey levels at 2400 px: option F, taken)
TOP_FLOOR_POINTS_PER_WAVE = 1
#: The strap slab keeps these columns of its outer face and of its inner face ((0, 2) on the inner face frees 32
#: triangles per strap, but the inner face shows under the strap's edges: edge lines change in 15 of 43 views) ...
STRAP_OUTER_COLUMNS = (0, 1, 2)
STRAP_INNER_COLUMNS = (0, 1, 2)
#: ... and drops this many stations at its back end (2: the last path station and the extension, never seen under the
#: cardigan, 24 triangles per strap; the objects' lines stay, but the strap's ground-shadow outline loses its end;
#: taken by the finishing pass's merge, option B)
STRAP_HIDDEN_BACK_STATIONS = 2
#: The white sleeve tubes inside the cardigan's balloon sleeves (no camera of the scan sees them; False frees 60
#: triangles, but each arm's ground-shadow outline loses the tube's loop, 10 strokes inside the sleeve's own shadow;
#: False since the finishing pass's merge, option B: the balloon sleeves cover the upper arm all round)
TOP_SLEEVE_TUBES = False
STRAP_CAST_REACH = 0.12               # bisection range of the strap's cast rays (from inside the shoulder)
STRAP_MAX_SAG = 0.0012                # strap path segments whose chord sags more than this get a midpoint station
STRAP_LAY_PASSES = 8                  # lay-clear passes of the strap's inner face over the top ...
#: ... tested at these bilinear points of every quad (centre, edge midpoints, quarter points)
STRAP_LAY_SAMPLES = ((0.5, 0.5), (0.5, 0.0), (1.0, 0.5), (0.5, 1.0), (0.0, 0.5), (0.25, 0.25), (0.75, 0.25),
                     (0.75, 0.75), (0.25, 0.75))
#: Skirt columns of one flute, as fractions of the flute pitch from its crest (0) through its valley (+-0.5); the front
#: flute replaces its two mid columns with the placket columns (x = +-placket_x).
FLUTE_COLUMNS = (0.0, 0.25, 0.5, 0.75)
#: Teardrop button outline (pointed end up) in units of (width, height) about the button centre, and the dome apex
#: (over the bulb centre): a bulb of the full width tangent to two lines from the tip.
BUTTON_OUTLINE = ((0.0, 0.5), (0.5, -0.118), (0.45, -0.377), (0.0, -0.5), (-0.45, -0.377), (-0.5, -0.118))
BUTTON_APEX_V = -0.224
SOLVE_STEPS = 60                      # bisection steps of the column solvers (deterministic)


def _s(side: int) -> str:
    return "l" if side > 0 else "r"


# ---------------------------------------------------------------------------------------------------
# Small deterministic geometry helpers (scalar arithmetic; no BLAS reductions)
# ---------------------------------------------------------------------------------------------------

def _dot(a, b) -> float:
    return float(a[0] * b[0] + a[1] * b[1] + a[2] * b[2])


def _unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / math.sqrt(_dot(v, v))


def _polar(section, z: float, phi_deg: float, ef: float, eb: float) -> np.ndarray:
    """Point of the section ``(hw, yf, yb)`` (superellipse halves with exponents ``ef`` / ``eb`` about the mid depth) on
    the ray from its centre at azimuth ``phi`` (0 front -Y, 90 her left +X, 180 back), at height ``z``."""
    hw, yf, yb = section
    c = 0.5 * (yf + yb)
    p = math.radians(phi_deg)
    sx, cy = math.sin(p), -math.cos(p)
    back = cy > 0.0
    semi = (yb - c) if back else (c - yf)
    e = eb if back else ef
    if abs(sx) < 1e-12:
        r = semi
    elif abs(cy) < 1e-12:
        r = hw
    else:
        r = 1.0 / ((abs(sx) / hw) ** e + (abs(cy) / semi) ** e) ** (1.0 / e)
    return np.array([r * sx, c + r * cy, z])


def _grown(section, d: float):
    """Section ``(hw, yf, yb)`` grown outward by ``d`` (shrunk for ``d < 0``)."""
    hw, yf, yb = section
    return hw + d, yf - d, yb + d


def _radial_inset(p, c_y: float, d: float) -> np.ndarray:
    """``p`` moved ``d`` towards the vertical axis through ``(0, c_y)`` (horizontally)."""
    dx, dy = float(p[0]), float(p[1]) - c_y
    r = math.sqrt(dx * dx + dy * dy)
    k = 1.0 - d / r
    return np.array([dx * k, c_y + dy * k, float(p[2])])


def _section_normal(section_fn, ef: float, eb: float, p, h: float = 1e-5) -> np.ndarray:
    """Outward unit normal at ``p`` of the surface whose horizontal sections are ``section_fn(z) = (hw, yf, yb)``
    (superellipse halves): central differences of the section measure."""
    def f(q):
        hw, yf, yb = section_fn(q[2])
        c = 0.5 * (yf + yb)
        back = q[1] > c
        semi = (yb - c) if back else (c - yf)
        e = eb if back else ef
        return (abs(q[0]) / hw) ** e + (abs(q[1] - c) / semi) ** e

    p = np.asarray(p, dtype=np.float64)
    g = np.zeros(3)
    for k in range(3):
        d = np.zeros(3)
        d[k] = h
        g[k] = (f(p + d) - f(p - d)) / (2.0 * h)
    return _unit(g)


def _bisect(fn, lo: float, hi: float) -> float:
    """Root of ``fn`` (increasing on ``[lo, hi]``) by :data:`SOLVE_STEPS` bisection steps."""
    for _ in range(SOLVE_STEPS):
        mid = 0.5 * (lo + hi)
        if fn(mid) < 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _interp_profile(zs, ys, z: float) -> float:
    """Piecewise linear ``y(z)`` through the points ``(zs[i], ys[i])`` (``zs`` decreasing)."""
    if z >= zs[0]:
        return ys[0]
    for i in range(len(zs) - 1):
        if zs[i + 1] <= z <= zs[i]:
            t = (zs[i] - z) / (zs[i] - zs[i + 1])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]


class _Shell:
    """A closed shell built as a strip of rings joined in order: consecutive rings of equal point counts by quad bands
    (``[a_j, a_j+1, b_j+1, b_j]``, the :func:`meshkit.loft` convention), or of counts ``k : 1`` by reducing bands (per
    sparse segment: triangles to its first point, a quad (odd ``k``) or a triangle on the sparse segment (even ``k``)
    from the dense middle point, triangles to its second point, so each segment is mirror-symmetric; point ``k j`` of
    the dense ring above sparse point ``j``); flat caps at both ends.  :meth:`mesh` orients the result outward by its
    signed volume and fans every quad on its valley diagonal."""

    def __init__(self):
        self.V, self.faces, self.groups, self.rings = [], [], [], []

    def ring(self, pts) -> int:
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        base = len(self.V)
        self.V.extend(pts)
        self.rings.append((base, len(pts)))
        return len(self.rings) - 1

    def band(self, ra: int, rb: int, groups):
        """Join ring ``ra`` to ring ``rb``; ``groups`` is an int or one group per segment of the denser ring."""
        (a0, na), (b0, nb) = self.rings[ra], self.rings[rb]
        n = max(na, nb)
        g = [int(groups)] * n if np.ndim(groups) == 0 else [int(x) for x in groups]

        def A(i):
            return a0 + i % na

        def B(i):
            return b0 + i % nb

        if na == nb:
            for j in range(na):
                self.faces.append([A(j), A(j + 1), B(j + 1), B(j)])
                self.groups.append(g[j])
        elif na % nb == 0:                            # a dense, b sparse
            k = na // nb
            for j in range(nb):
                for i in range(k):
                    s = k * j + i
                    if i < k // 2:
                        self.faces.append([A(s), A(s + 1), B(j)])
                    elif i == k // 2 and k % 2:
                        self.faces.append([A(s), A(s + 1), B(j + 1), B(j)])
                    else:
                        if i == k // 2:                   # even k: the middle triangle, then the second half
                            self.faces.append([A(s), B(j + 1), B(j)])
                            self.groups.append(g[s])
                        self.faces.append([A(s), A(s + 1), B(j + 1)])
                    self.groups.append(g[s])
        elif nb % na == 0:                            # a sparse, b dense
            k = nb // na
            for j in range(na):
                for i in range(k):
                    s = k * j + i
                    if i < k // 2:
                        self.faces.append([A(j), B(s + 1), B(s)])
                    elif i == k // 2 and k % 2:
                        self.faces.append([A(j), A(j + 1), B(s + 1), B(s)])
                    else:
                        if i == k // 2:                   # even k: the middle triangle, then the second half
                            self.faces.append([A(j), A(j + 1), B(s)])
                            self.groups.append(g[s])
                        self.faces.append([A(j + 1), B(s + 1), B(s)])
                    self.groups.append(g[s])
        else:
            raise mk.MeshError(f"band: ring counts {na} and {nb} are not multiples")

    def cap(self, r: int, group: int, start: bool):
        b0, n = self.rings[r]
        ring = [b0 + j for j in range(n)]
        self.faces.append(ring[::-1] if start else ring)
        self.groups.append(int(group))

    def mesh(self, triangles=()) -> mk.Mesh:
        """The shell oriented outward, every quad fanned on its valley diagonal (:func:`meshkit.inscribed_fan`): the
        shells' quads twist (up to 10 degrees on the skirt, 35 on the top), and on the ridge diagonal one fan triangle
        of a quad hides the quad's own silhouette edge, so the hidden-line pass dropped 45-85 px pieces of the skirt's
        flank outline.  The quads whose face indices are in ``triangles`` are instead fanned on their *ridge* diagonal
        (:func:`meshkit.fan_fold`) and written as those two fan triangles (same group), as :func:`meshkit.split_twisted`
        does but for every listed quad, however little it twists: as separate triangles they cannot hide their own
        edge, and the ridge keeps a convex surface convex (a valley crease there folds the contour into an S where a
        strip is seen at a grazing angle, and both of the strip's long edges draw; review r4-L4).  Ring points no
        face uses (where a builder leaves hidden faces out) are dropped, the others keep their order."""
        used = sorted(set(i for f in self.faces for i in f))
        if len(used) < len(self.V):
            index = {v: k for k, v in enumerate(used)}
            V = np.array([self.V[i] for i in used])
            faces = [[index[i] for i in f] for f in self.faces]
        else:
            V, faces = np.array(self.V), self.faces
        mesh = mk.inscribed_fan(mk._outward(mk.Mesh(V, faces, self.groups)))
        if not triangles:
            return mesh
        split = [False] * len(mesh.faces)
        for k in triangles:
            split[k] = True
        mesh = mk.fan_fold(mesh, split)
        faces, groups = [], []
        for f, g, cut in zip(mesh.faces, mesh.groups, split):
            if cut and len(f) == 4:
                faces += [[f[0], f[1], f[2]], [f[0], f[2], f[3]]]
                groups += [g, g]
            else:
                faces.append(list(f))
                groups.append(g)
        return mk.Mesh(mesh.vertices, faces, groups)


# ---------------------------------------------------------------------------------------------------
# D.1 neck (object neck, skin)
# ---------------------------------------------------------------------------------------------------

def _neck(rig: Rig) -> mk.Mesh:
    """Elliptic cylinder from inside the mock neck to inside the head, one smooth group (outline only)."""
    hw, yf, yb = rig.neck_section(rig.neck_z_mid)
    rings = [mk.ellipse_ring(hw, 0.5 * (yb - yf), NECK_POINTS, (0.0, 0.5 * (yf + yb), z), 90.0)
             for z in rig.neck_z]
    return mk.loft(rings, "flat", "flat", groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------
# D.2 white mock-neck top (object top)
# ---------------------------------------------------------------------------------------------------

def _rim_z(rig: Rig, i: int) -> float:
    """z of rim column ``i`` (lettuce edge, scallops ``2 |sin| - 1`` of half the wave phase sampled
    :data:`RIM_SAMPLES_PER_WAVE` times: the cusp trough on every first column, the front centre included).  The
    amplitude is ``lettuce_amplitude`` at the centre front and back and ``lettuce_side_amplitude`` of it at her sides
    (blended by cos^2 of the azimuth; review r4-T1: where a view sees the rim edge-on, the steeper waves folded the
    mock neck's outer wall into two parallel outlines)."""
    k = i % RIM_SAMPLES_PER_WAVE
    c = math.cos(2.0 * math.pi * i / (RIM_SAMPLES_PER_WAVE * rig.lettuce_waves))
    s = rig.lettuce_side_amplitude
    amplitude = rig.lettuce_amplitude * (s + (1.0 - s) * c * c)
    return rig.mock_neck_z + amplitude * (2.0 * abs(math.sin(math.pi * k / RIM_SAMPLES_PER_WAVE)) - 1.0)


def _flare_point(rig: Rig, phi_deg: float, z_row: float, z_mid: float) -> np.ndarray:
    """Point at azimuth ``phi`` of the ``top_rows`` row at ``z_row`` on the mock neck's flare, from the straight tube's
    end ``z_mid`` (weight 0) to the fold at ``top_fold_z`` (weight 1, the fold itself): the row dips ``weight *
    top_fold_dip * cos^2 phi`` (the fold at the centre front and back, level at her sides: a soft U, review r1-L14;
    the flare slides down with it, so its bands keep their height round the neck) and lies on the top's surface there,
    its section's exponent blended from the mock neck's to the torso's (review r2-L11: with the torso's exponent on the
    flare rows, a near-tangent facet of the band above the fold turned the 3/4 views' outline into the fold, where it
    hid: a 3-4 mm gap)."""
    w = (z_mid - z_row) / (z_mid - rig.top_fold_z)
    if w >= 1.0:
        e = rig.body_exponent
    else:
        e = rig.mock_neck_exponent + (rig.body_exponent - rig.mock_neck_exponent) * w
    c = math.cos(math.radians(phi_deg))
    z = z_row - w * rig.top_fold_dip * c * c
    return _polar(rig.top_section(z), z, phi_deg, e, e)


def _top_shell(rig: Rig) -> mk.Mesh:
    """Mock neck and torso of the top as one shell: the dent's floor (inside the mock neck, round the neck,
    ``mock_neck_thickness`` inside the tube) -> the inner wall, flaring out to -> the wavy rim (its top face
    ``lettuce_rim_width`` wide, inward from the lip turned out ``lettuce_flare``; review r4-T1: a 4.5 mm face seen
    edge-on at the sides drew its radial edges as a stack of 3-4 boxes, 1 mm draws one short curl) -> the
    outer wall, from the rim's ``RIM_SAMPLES_PER_WAVE * n`` columns to the torso's ``n = lettuce_waves``, flaring out
    over the ``top_rows`` above ``top_fold_z`` (review r2-L11: one 47 degree chamfer onto a 17 degree ledge read as a
    lampshade) -> the fold into the shoulders (``top_fold_z``) -> the shoulders and chest down to the bodice's top
    edge -> a shrunk end ring and cap buried in the bodice."""
    if all(r[0] != rig.top_fold_z for r in rig.top_rows):
        raise ValueError(f"top_fold_z {rig.top_fold_z} is not the z of a top_rows row")
    n = rig.lettuce_waves
    m = RIM_SAMPLES_PER_WAVE * n
    e_m = rig.mock_neck_exponent
    e_t = rig.body_exponent
    zr = rig.mock_neck_z
    t = rig.mock_neck_thickness
    sec_rim = rig.mock_neck_section(zr)
    sh = _Shell()
    z_floor = zr - rig.mock_neck_inner_depth
    nf = n * TOP_FLOOR_POINTS_PER_WAVE
    floor = sh.ring([_polar(_grown(rig.mock_neck_section(z_floor), -t), z_floor, 360.0 * j / nf, e_m, e_m)
                     for j in range(nf)])
    lip = rig.lettuce_flare - rig.lettuce_rim_width
    inner = sh.ring([_polar(_grown(sec_rim, lip), _rim_z(rig, i), 360.0 * i / m, e_m, e_m) for i in range(m)])
    outer = sh.ring([_polar(_grown(sec_rim, rig.lettuce_flare), _rim_z(rig, i), 360.0 * i / m, e_m, e_m)
                     for i in range(m)])
    sh.cap(floor, 2, start=True)
    sh.band(floor, inner, 2)                                  # inner wall
    sh.band(inner, outer, 2)                                  # rim top face
    prev = outer
    z_mid = rig.mock_neck_rows[1][0]                          # the mock neck straight down to here ...
    rows = [(z_mid, rig.mock_neck_section(z_mid), e_m)]
    for r in rig.top_rows:                                    # ... then the neck's flare, the shoulders and the chest
        if r[0] >= rig.neckline_z[0] - rig.top_bodice_inset and r[0] not in rig.top_skip_rows:   # down to the
            rows.append((r[0], r[1:], e_t))                                                      # bodice's top edge
    end = _grown(rig.top_section(rig.top_torso_end_z), -rig.top_bodice_inset)
    rows.append((rig.top_torso_end_z, end, e_t))              # ... and a buried end ring inside the bodice
    z_cut = rig.top_back_cut[0]
    if [z for z, _s, _e in rows][-3] != z_cut:
        raise ValueError(f"top_back_cut z {z_cut} is not the third-last row of the top "
                         f"{[z for z, _s, _e in rows]}")
    rings = []
    for z, sec, e in rows:                                    # the mock neck's outer wall (group 1) down to its fold
        if rig.top_fold_z <= z < z_mid:                       # into the shoulders, then the torso (group 3): the
            cur = sh.ring([_flare_point(rig, 360.0 * j / n, z, z_mid) for j in range(n)])   # flare and the fold
        else:
            cur = sh.ring([_polar(sec, z, 360.0 * j / n, e, e) for j in range(n)])
        rings.append(cur)
        if z >= z_cut:
            sh.band(prev, cur, 1 if z >= rig.top_fold_z else 3)
        prev = cur
    _top_lower(rig, sh, *rings[-3:])
    return sh.mesh()


def _top_lower(rig: Rig, sh: _Shell, r_sh: int, r_nk: int, r_end: int):
    """The top below its shoulder-point row ``r_sh`` (v2 finishing pass): the neckline row ``r_nk`` and the buried end
    ring ``r_end`` leave out their points at azimuths ``top_back_cut[1]`` .. ``top_back_cut[2]`` (round the back:
    the faces there lie under the cardigan's back panel and in the bodice, and an id z-buffer scan of 864 cameras round
    her saw none of them), and the end ring's cap goes with them.  The opening closes with a fan from the shoulder row
    point :data:`TOP_FILL_APEX` columns past the first left-out one: it runs inside the old torso (level on the shoulder
    row at the back, then down to the end ring in front), and every one of its faces faces away from the sun, like all
    the faces it replaces, so the top's light silhouette (its drawn ground-shadow outline) keeps every edge.  The range
    stops one column short of her right back side, where that silhouette runs down the torso."""
    b_sh, n = sh.rings[r_sh]
    b_nk, b_end = sh.rings[r_nk][0], sh.rings[r_end][0]
    _z, p0, p1 = rig.top_back_cut
    drop = [j for j in range(n) if p0 - 1e-9 <= 360.0 * j / n <= p1 + 1e-9]
    ja, jb = drop[0], drop[-1]
    if not (drop == list(range(ja, jb + 1)) and 1 < ja and jb < n - 2):
        raise ValueError(f"top_back_cut {rig.top_back_cut}: unexpected points {drop}")

    def S(j):
        return b_sh + j % n

    def K(j):
        return b_nk + j % n

    def E(j):
        return b_end + j % n

    for r0, r1 in ((S, K), (K, E)):                           # the bands' kept quads (the band convention)
        for j in range(n):
            if not (ja - 1 <= j <= jb):
                sh.faces.append([r0(j), r0(j + 1), r1(j + 1), r1(j)])
                sh.groups.append(3)
    loop = [S(j) for j in range(ja - 1, jb + 2)] + [K(jb + 1)]   # the shoulder row across the back, down her right,
    loop += [E(j) for j in range(jb + 1, ja + n)] + [K(ja - 1)]  # the end ring round the front, up her left (the
    k0 = TOP_FILL_APEX                                           # bands' edges reversed: one consistent shell)
    loop = loop[k0:] + loop[:k0]
    for k in range(1, len(loop) - 1):
        sh.faces.append([loop[0], loop[k], loop[k + 1]])
        sh.groups.append(3)


def _arm_axis(rig: Rig, side: int, position: float) -> np.ndarray:
    """:meth:`Rig.arm_point` extended before the shoulder joint (negative positions) along the upper arm."""
    if position >= 0.0:
        return rig.arm_point(side, position)
    s, e = rig.shoulder_joint(side), rig.elbow(side)
    return s + (e - s) * position


def _top_sleeve(rig: Rig, side: int) -> mk.Mesh:
    """White sleeve tube of the top along the upper arm, from a point inside the torso to ``top_sleeve_end`` (inside
    the cardigan sleeve), one smooth group."""
    pos = (rig.top_sleeve_start, 0.0, rig.top_sleeve_end)
    qs, rs = zip(*rig.top_sleeve_radii)
    radii = [float(np.interp(max(p, 0.0), qs, rs)) for p in pos]
    path = np.array([_arm_axis(rig, side, p) for p in pos])
    return mk.sweep(path, width=2.0 * np.array(radii), profile=mk.profile_ellipse(TOP_SLEEVE_POINTS),
                    start="pointed", end="flat", groups=1, cap_groups=(1, 1))


# ---------------------------------------------------------------------------------------------------
# D.3 bodice and straps (object bodice, dress)
# ---------------------------------------------------------------------------------------------------

def _bodice_columns(rig: Rig, section):
    """Section angles (degrees, the :meth:`Rig.section_point` parameter: -90 front, 0 her left side, 90 back) of the
    bodice ring columns for ``section``: every :data:`BODICE_T_STEP` degrees plus the placket columns at
    x = +-placket_x; index 0 is the front centre, then her left half to the back centre, then her right half."""
    hw = section[0]
    e = rig.bodice_front_exponent
    tp = -math.degrees(math.acos((rig.placket_x / hw) ** (0.5 * e)))
    k = int(round(90.0 / BODICE_T_STEP))
    left = [-90.0, tp] + sorted([-90.0 + BODICE_T_STEP * i for i in range(1, 2 * k + 1)] + list(BODICE_FINE_T))
    right = [180.0 - a for a in reversed(left[1:-1])]
    return left + right


def _bodice_point(rig: Rig, z: float, t_deg: float) -> np.ndarray:
    hw, yf, yb = rig.bodice_section(z)
    x, y = Rig.section_point(hw, yf, yb, math.radians(t_deg), rig.bodice_front_exponent, rig.bodice_back_exponent)
    return np.array([x, y, z])


def _neckline_z(rig: Rig, t_deg: float) -> float:
    """z of the bodice's top edge at section angle ``t`` (SPEC.md §D.3): level at the square neckline out to just past
    the strap's outer edge (where the strap tucks under it), dropping (a cosine ease) round the side to the armpit, then
    linear to the hidden back."""
    z_front, z_side, z_back = rig.neckline_z
    a = t_deg if -90.0 <= t_deg <= 90.0 else 180.0 - t_deg  # mirrored to her left: -90 front ... 90 back
    if a >= 0.0:                                               # the back half
        return z_side + (z_back - z_side) * (a / 90.0)
    hw = rig.bodice_section(z_front)[0]
    x_level = rig.strap_x[1] + rig.strap_thickness             # level a strap thickness past the strap's outer edge
    ts = -math.degrees(math.acos(min(1.0, (x_level / hw) ** (0.5 * rig.bodice_front_exponent))))
    if a <= ts:
        return z_front
    f = (a - ts) / (0.0 - ts)
    return z_front + (z_side - z_front) * 0.5 * (1.0 - math.cos(math.pi * f))


def _bodice(rig: Rig):
    """The bodice as one solid: its top is a level ledge from the edge (the square neckline, the armhole drop, the back)
    to ``bodice_tuck`` inside the top, closed by a cap inside the top (group 3); the outer surface (group 1, the placket
    strip group 2); its bottom cap at the high-waist seam is the ledge over the skirt (group 4).
    Returns ``(mesh, centre_profile)``: the front centre column's ``(z, y)`` points (for the buttons)."""
    cols = _bodice_columns(rig, rig.bodice_section(rig.neckline_z[0]))
    n = len(cols)
    strip = [1] * n
    strip[0] = strip[n - 1] = 2                               # front centre <-> the placket columns
    sh = _Shell()
    edge = [_bodice_point(rig, _neckline_z(rig, t), t) for t in cols]
    ledge = []                                                # the ledge's inner ring, bodice_tuck inside the top
    for p in edge:
        z = float(p[2])
        hw, yf, yb = rig.top_section(z)
        c = 0.5 * (yf + yb)
        phi = math.degrees(math.atan2(float(p[0]), c - float(p[1])))
        ledge.append(_polar(_grown((hw, yf, yb), -rig.bodice_tuck), z, phi, rig.body_exponent, rig.body_exponent))
    inner = sh.ring(ledge)
    top = sh.ring(edge)
    profile = [(rig.neckline_z[0], float(sh.V[sh.rings[top][0]][1]))]
    rings = [inner, top]
    zs = [z for z in rig.bodice_ring_z] + [rig.seam_z]
    for z in zs:
        cs = _bodice_columns(rig, rig.bodice_section(z))
        rings.append(sh.ring([_bodice_point(rig, z, t) for t in cs]))
        profile.append((z, float(sh.V[sh.rings[rings[-1]][0]][1])))
    # v2 finishing pass: the back under the cardigan's back panel (never seen) keeps the top edge (the neckline line and
    # its rays) and the rows from 1.116 down; the ledge's inner ring and the next two rows leave out their columns in
    # bodice_back_cut, and fans close the hole inside the old solid
    cut = {r: [False] * n for r in rings}
    for r, (t0, t1) in zip((inner, rings[2], rings[3]), rig.bodice_back_cut):
        cut[r] = [t0 - 1e-9 <= t <= t1 + 1e-9 for t in cols]
    for a, b in zip(rings, rings[1:]):                        # the ledge (group 3: the neckline line at its outer
        g = [3] * n if a == inner else strip                  # edge), then the outer surface down to the seam
        A, B = sh.rings[a][0], sh.rings[b][0]
        for j in range(n):
            if not (cut[a][j] or cut[a][(j + 1) % n] or cut[b][j] or cut[b][(j + 1) % n]):
                sh.faces.append([A + j, A + (j + 1) % n, B + (j + 1) % n, B + j])
                sh.groups.append(g[j])
    sh.cap(rings[-1], 4, start=False)
    I, T, R, Q, P = (sh.rings[r][0] for r in rings[:5])
    ci, cr, cq = ([j for j in range(n) if cut[r][j]] for r in (inner, rings[2], rings[3]))
    lo, hi = cr[0], cr[-1]
    if not (cr == list(range(lo, hi + 1)) and ci == list(range(lo, hi + 2)) and cq == list(range(lo + 1, hi + 1))
            and lo > 2 and hi < n - 3):
        raise ValueError(f"bodice_back_cut {rig.bodice_back_cut}: unexpected cut columns {ci} {cr} {cq} (expected the "
                         "inner ring's one column past the 1.225 row's on her right, the 1.185 row's one short on her "
                         "left)")
    # the ledge and its cap: the kept inner ring as a fan from its centre front (like the old cap) closed by the chord
    # between the two inner points next to the cut, and behind that chord a fan from her left one to the top edge across
    # the back (the loops run the kept faces' edges backwards); every face faces the sun like the faces it replaces
    cap = [I] + [I + j for j in range(n - 1, hi + 1, -1)] + [I + j for j in range(lo - 1, 0, -1)]
    back = [I + lo - 1, I + hi + 2] + [T + j for j in range(hi + 2, lo - 2, -1)]
    for ring in (cap, back):
        for k in range(1, len(ring) - 1):
            sh.faces.append([ring[0], ring[k], ring[k + 1]])
            sh.groups.append(3)
    # the outer back: quads from the top edge straight down to the 1.116 row (chords inside the convex back), and at
    # each side the columns next to the kept faces in triangles; every face faces away from the sun like the faces
    # it replaces, so the bodice's light silhouette (its ground-shadow outline) and the neckline's rays keep every edge
    a = lo - 1
    tris = [(T + lo, R + a, T + a), (T + lo, Q + a, R + a), (T + lo, Q + lo, Q + a),
            (T + lo + 1, P + lo + 1, P + lo), (T + lo + 1, P + lo, Q + lo), (T + lo + 1, Q + lo, T + lo),
            (T + hi, T + hi + 1, R + hi + 1), (T + hi, R + hi + 1, Q + hi + 1), (T + hi, Q + hi + 1, P + hi + 1),
            (T + hi, P + hi + 1, P + hi)]
    for f in tris:
        sh.faces.append(list(f))
        sh.groups.append(1)
    for j in range(lo + 1, hi):
        sh.faces.append([T + j, T + j + 1, P + j + 1, P + j])
        sh.groups.append(1)
    return sh.mesh(), profile


def _top_measure(rig: Rig, q) -> float:
    """Section measure of the top's torso at ``q`` (1 on its surface, smaller inside)."""
    hw, yf, yb = rig.top_section(float(q[2]))
    c = 0.5 * (yf + yb)
    semi = (yb - c) if q[1] > c else (c - yf)
    e = rig.body_exponent
    return (abs(float(q[0])) / hw) ** e + (abs(float(q[1]) - c) / semi) ** e


def _top_normal(rig: Rig, p) -> np.ndarray:
    return _section_normal(rig.top_section, rig.body_exponent, rig.body_exponent, p)


def _top_clearance(rig: Rig, q) -> float:
    """Approximate signed distance of ``q`` above the top's surface: its radial distance outside the section at its
    azimuth, times the horizontal part of the surface normal there (the distance to the local tangent plane)."""
    z = float(q[2])
    hw, yf, yb = rig.top_section(z)
    c = 0.5 * (yf + yb)
    phi = math.degrees(math.atan2(float(q[0]), c - float(q[1])))
    p = _polar((hw, yf, yb), z, phi, rig.body_exponent, rig.body_exponent)
    rq = math.hypot(float(q[0]), float(q[1]) - c)
    rs = math.hypot(float(p[0]), float(p[1]) - c)
    n = _top_normal(rig, p)
    return (rq - rs) * math.hypot(float(n[0]), float(n[1]))


def _refined_path(P):
    """``P`` with the 4-point subdivision midpoint ``(-a + 9 b + 9 c - d) / 16`` inserted into every segment ``b c``
    whose chord deviates from it by more than :data:`STRAP_MAX_SAG` (the stations then follow the shoulder's curve
    closely, so the strap's lay-clear pass needs to lift it little)."""
    out = [P[0]]
    n = len(P)
    for i in range(n - 1):
        a = P[i - 1] if i > 0 else 2.0 * P[0] - P[1]
        d = P[i + 2] if i + 2 < n else 2.0 * P[-1] - P[-2]
        m = (9.0 * (P[i] + P[i + 1]) - a - d) / 16.0
        dev = m - 0.5 * (P[i] + P[i + 1])
        if math.sqrt(_dot(dev, dev)) > STRAP_MAX_SAG:
            out.append(m)
        out.append(P[i + 1])
    return out


def _strap(rig: Rig, side: int) -> mk.Mesh:
    """A strap over the shoulder: a slab (single group) laid on the top's surface between x = strap_x[0] and strap_x[1]
    (:data:`STRAP_COLUMNS` columns across, cast in the planes x = const from inside the shoulder) along the stations of
    ``strap_path``; its inner face ``strap_lift`` over the surface, diving to ``strap_tuck_offset`` at both ends
    (``strap_tuck_length``) and running on ``strap_tuck_extension`` into the bodice, so the bodice's top edge (the
    neckline line, the back edge) runs across it."""
    P = _refined_path([np.array(p, dtype=np.float64) for p in rig.strap_path])
    ext = rig.strap_tuck_extension
    yz = [(float(p[1]), float(p[2])) for p in P]
    d0, d1 = _unit(P[0] - P[1]), _unit(P[-1] - P[-2])
    yz = [(yz[0][0] + ext * d0[1], yz[0][1] + ext * d0[2])] + yz + [(yz[-1][0] + ext * d1[1], yz[-1][1] + ext * d1[2])]
    seg = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(yz[1:-1], yz[2:-1])]
    s = [0.0]
    for L in seg:
        s.append(s[-1] + L)
    offs = [rig.strap_tuck_offset]
    for sk in s:
        f = min(1.0, min(sk, s[-1] - sk) / rig.strap_tuck_length)
        w = 0.5 * (1.0 - math.cos(math.pi * f))
        offs.append(rig.strap_tuck_offset + (rig.strap_lift - rig.strap_tuck_offset) * w)
    offs.append(rig.strap_tuck_offset)
    # cast in the planes x = const from a centre inside the shoulder whose height runs from the front end's to the back
    # end's along the path: both end sections are level (they tuck under the bodice's level top edge) and the stations
    # stay in order across the strap
    y_ref = 0.5 * (yz[0][0] + yz[-1][0])
    z_front, z_back = yz[1][1], yz[-2][1]
    ls = [0.0]
    for a, b in zip(yz, yz[1:]):
        ls.append(ls[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    # the columns: strap_x from the front over the shoulder top (the path's highest station), then moving in to
    # strap_back_x at the back end (the back is narrower than the chest)
    U = len(yz)
    top_i = max(range(U), key=lambda i: (yz[i][1], -i))
    cols = []
    for i in range(U):
        f = 0.0 if i <= top_i else min(1.0, (ls[i] - ls[top_i]) / (ls[-2] - ls[top_i]))
        x0 = rig.strap_x[0] + (rig.strap_back_x[0] - rig.strap_x[0]) * f
        x1 = rig.strap_x[1] + (rig.strap_back_x[1] - rig.strap_x[1]) * f
        cols.append([x0 + (x1 - x0) * j / (STRAP_COLUMNS - 1.0) for j in range(STRAP_COLUMNS)])
    S = np.zeros((U, STRAP_COLUMNS, 3))                       # the surface points under the grid ...
    N = np.zeros((U, STRAP_COLUMNS, 3))                       # ... their normals
    rays = []                                                 # (origin y, origin z, direction) per station
    for i in range(1, U - 1):
        y, z = yz[i]
        f = (ls[i] - ls[1]) / (ls[-2] - ls[1])
        z_ref = z_front + (z_back - z_front) * f
        rays.append((y_ref, z_ref, _unit((0.0, y - y_ref, z - z_ref))))
    # the extensions: the end stations' rays moved on along the path's end directions
    rays = ([(rays[0][0] + ext * d0[1], rays[0][1] + ext * d0[2], rays[0][2])] + rays
            + [(rays[-1][0] + ext * d1[1], rays[-1][1] + ext * d1[2], rays[-1][2])])
    for i, (oy, oz, D) in enumerate(rays):
        for j, x in enumerate(cols[i]):
            org = np.array([x, oy, oz])
            lam = _bisect(lambda t, o=org, d=D: _top_measure(rig, o + t * d) - 1.0, 0.0, STRAP_CAST_REACH)
            S[i, j] = org + lam * D
            N[i, j] = _top_normal(rig, S[i, j])
    off = np.array([[o] * STRAP_COLUMNS for o in offs])
    full = off >= rig.strap_lift - 1e-12                      # outside the dives: keep the whole face strap_lift clear
    for _ in range(STRAP_LAY_PASSES):                         # of the convex shoulder (the chords sag)
        grid = S + off[..., None] * N
        bump = np.zeros_like(off)
        for i in range(U - 1):
            for j in range(STRAP_COLUMNS - 1):
                quad = ((i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1))
                if not all(full[a, b] for a, b in quad):
                    continue
                for u, v in STRAP_LAY_SAMPLES:
                    q = ((1 - u) * (1 - v) * grid[i, j] + u * (1 - v) * grid[i + 1, j] + u * v * grid[i + 1, j + 1]
                         + (1 - u) * v * grid[i, j + 1])
                    d = rig.strap_lift - _top_clearance(rig, q)
                    if d > 0.0:
                        for a, b in quad:
                            bump[a, b] = max(bump[a, b], d)
        if not np.any(bump > 1e-7):
            break
        off = off + bump
    grid = S + off[..., None] * N
    z_ref = 0.5 * (z_front + z_back)
    centre = (0.5 * sum(rig.strap_x), y_ref, z_ref)
    _full, sides = mk.thicken(grid, rig.strap_thickness, offset="outward", away_from=centre, groups="single",
                              return_sides=True)
    strap = _strap_slab(sides["front"], sides["back"])
    return strap if side > 0 else strap.mirror_x()


def _strap_slab(F, B) -> mk.Mesh:
    """The strap's closed slab (single group) from :func:`meshkit.thicken`'s two vertex grids ``F`` (the outer face)
    and ``B`` (the inner face, on the top): with the defaults exactly thicken's slab (vertices, faces and their order);
    the v2 options keep only the stations before the last :data:`STRAP_HIDDEN_BACK_STATIONS` and the columns
    :data:`STRAP_OUTER_COLUMNS` / :data:`STRAP_INNER_COLUMNS` (the kept faces stay thicken's, vertex for vertex).  The
    quads twist up to 50 degrees where the strap turns over the shoulder and dives: the outer face and the rims fold on
    their valley diagonals (on the ridge diagonal a quad's own fan triangle hides its outline edge), the inner face on
    its ridge diagonal, so both faces fold the same way and stay strap_thickness apart (valley diagonals on both faces
    cross inside the thin slab and show back faces)."""
    U = F.shape[0] - STRAP_HIDDEN_BACK_STATIONS
    co, ci = STRAP_OUTER_COLUMNS, STRAP_INNER_COLUMNS
    if co[0] != 0 or ci[0] != 0 or co[-1] != F.shape[1] - 1 or ci[-1] != F.shape[1] - 1:
        raise ValueError("the strap keeps both edge columns on both faces")
    no, ni = len(co), len(ci)
    V = np.concatenate([F[:U][:, list(co)].reshape(-1, 3), B[:U][:, list(ci)].reshape(-1, 3)])

    def f(u, k):
        return u * no + k

    def b(u, k):
        return U * no + u * ni + k

    faces, ridge = [], []
    for u in range(U - 1):                                    # thicken's face order: per station the two faces'
        for k in range(max(no, ni) - 1):                      # quads column by column, then the two rims
            if k < no - 1:
                faces.append([f(u, k), f(u + 1, k), f(u + 1, k + 1), f(u, k + 1)])
                ridge.append(False)
            if k < ni - 1:
                faces.append([b(u, k), b(u, k + 1), b(u + 1, k + 1), b(u + 1, k)])
                ridge.append(True)
        faces.append([f(u + 1, 0), f(u, 0), b(u, 0), b(u + 1, 0)])
        faces.append([f(u, no - 1), f(u + 1, no - 1), b(u + 1, ni - 1), b(u, ni - 1)])
        ridge += [False, False]
    L = U - 1                                                 # the end caps (inside the bodice / under the cardigan)
    if co == ci:                                              # thicken's quads ...
        for k in range(no - 1):
            faces.append([f(0, k), f(0, k + 1), b(0, k + 1), b(0, k)])
            faces.append([f(L, k + 1), f(L, k), b(L, k), b(L, k + 1)])
            ridge += [False, False]
    else:                                                     # ... or a fan from the outer face's middle point (the
        for u, rev in ((0, False), (L, True)):                # outer face's points are near collinear)
            ring = [f(u, k) for k in range(no)] + [b(u, k) for k in range(ni - 1, -1, -1)]
            m = no // 2
            ring = ring[m:] + ring[:m]
            for k in range(1, len(ring) - 1):
                c = [ring[0], ring[k], ring[k + 1]]
                faces.append(c[::-1] if rev else c)
                ridge.append(False)
    mesh = mk._outward(mk.Mesh(V, faces, 1))
    return mk.fan_fold(mesh, ridge)


# ---------------------------------------------------------------------------------------------------
# D.4 skirt (object skirt, dress)
# ---------------------------------------------------------------------------------------------------

def _skirt_columns(rig: Rig):
    """``[(kind, azimuth or placket side)]`` round the ring from the front centre (counter-clockwise from above): per
    flute a crest, a mid, a valley and a mid (:data:`FLUTE_COLUMNS`); the front flute's mids are the placket columns."""
    pitch = 360.0 / rig.skirt_flutes
    cols = []
    for k in range(rig.skirt_flutes):
        for f in FLUTE_COLUMNS:
            phi = pitch * (k + f)
            if k == 0 and f == FLUTE_COLUMNS[1]:
                cols.append(("placket", 1))
            elif k == rig.skirt_flutes - 1 and f == FLUTE_COLUMNS[-1]:
                cols.append(("placket", -1))
            else:
                cols.append(("valley" if f == 0.5 else "flute", phi))
    return cols


def _placket_phi(rig: Rig, z: float, side: int) -> float:
    """Azimuth of the skirt surface point at height ``z`` whose x is ``side * placket_x``."""
    half = 0.5 * 360.0 / rig.skirt_flutes
    a = _bisect(lambda phi: float(rig.skirt_point(z, phi)[0]) - rig.placket_x, 0.0, half)
    return a if side > 0 else 360.0 - a


def _skirt_ring(rig: Rig, cols, z, inset: float = 0.0) -> np.ndarray:
    """Outer skirt ring at ``z`` (``None``: the hem, each column at :meth:`Rig.skirt_hem_at`), moved ``inset``
    radially inward."""
    out = []
    for kind, v in cols:
        zz = z
        phi = _placket_phi(rig, rig.hem_z if z is None else z, v) if kind == "placket" else v
        if z is None:
            zz = rig.skirt_hem_at(phi)
        p = rig.skirt_point(zz, phi)
        if inset:
            _hw, yf, yb = rig.skirt_section(zz)
            p = _radial_inset(p, 0.5 * (yf + yb), inset)
        out.append(p)
    return np.array(out)


def _skirt(rig: Rig):
    """The skirt shell and its valley stripes.  Returns ``(shell, stripes, centre_profile)``.

    The outer surface's quads are written as their two fan triangles (:meth:`_Shell.mesh`; round 3, r3-T3).  They
    twist 0.2-9.7 degrees (the flutes grow from 0 at ``flute_top_z`` to ``flute_depth`` at the hem, and the section
    changes over the hip), and near the flank outline castplane classified a quad as facing the camera by its Newell
    normal while one of its fan triangles faced away and hid the quad's outline edge: the flank line broke for 9-13 mm
    in back and side 3/4 views (az 115-145, 170-190, 215-245, 350-010) and 5 mm at the front hip (az 100 / 260).  As
    triangles the facing and the occluders agree, and a fan diagonal draws where it is the outline (+192 polygons, 0
    triangles, no rays: the diagonals join faces of one group).  Round 4 (r4-L4) moved the fan to the ridge diagonal:
    on the valley diagonal each strip had a concave crease in the convex hip and crests, so where a strip was seen at a
    grazing angle its two triangles faced opposite ways and both of its long edges drew, a doubled flank stroke 1-2 mm
    apart (4 strips in the scene camera, 187 over 72 azimuths); with convex creases the contour crosses each strip
    once.  The ridge surface lies at most 2.2 mm outside the valley one (where the flutes start, 1.4 mm at the hip),
    the smooth surface between the two."""
    cols = _skirt_columns(rig)
    n = len(cols)
    strip = [1] * n
    strip[0] = strip[n - 1] = 2                               # the placket strip round the front crest
    th = rig.skirt_thickness
    sh = _Shell()
    rings, ring_z = [], []
    for z in rig.skirt_ring_z:
        rings.append(sh.ring(_skirt_ring(rig, cols, z)))
        ring_z.append(z)
    hem = sh.ring(_skirt_ring(rig, cols, None))
    rings.append(hem)
    inner_hem = sh.ring(_skirt_ring(rig, cols, None, th))
    # the ceiling: the faceted outer surface at skirt_ceiling_z (between the two rings round it), th inside
    zc = rig.skirt_ceiling_z
    k = max(i for i, z in enumerate(ring_z) if z >= zc)
    za, zb = ring_z[k], ring_z[k + 1]
    Pa = np.array(sh.V[sh.rings[rings[k]][0]:sh.rings[rings[k]][0] + n])
    Pb = np.array(sh.V[sh.rings[rings[k + 1]][0]:sh.rings[rings[k + 1]][0] + n])
    f = (za - zc) / (za - zb)
    _hw, yf, yb = rig.skirt_section(zc)
    ceiling = sh.ring([_radial_inset(Pa[j] + f * (Pb[j] - Pa[j]), 0.5 * (yf + yb), th) for j in range(n)])
    sh.cap(rings[0], 1, start=True)                           # hidden in the bodice
    outer = len(sh.faces)
    for a, b in zip(rings, rings[1:]):
        sh.band(a, b, strip)
    outer = range(outer, len(sh.faces))                       # the outer surface's quads: written as triangles
    sh.band(hem, inner_hem, 3)                                # the hem rim (the wavy hem line)
    sh.band(inner_hem, ceiling, 3)                            # the inner facing
    sh.cap(ceiling, 3, start=False)
    shell = sh.mesh(outer)
    profile = [(z, float(sh.V[sh.rings[r][0]][1])) for z, r in zip(ring_z, rings[:-1])]
    profile.append((float(sh.V[sh.rings[hem][0]][2]), float(sh.V[sh.rings[hem][0]][1])))
    stripes = _valley_stripes(rig, sh, cols, rings)
    return shell, stripes, profile


def _valley_stripes(rig: Rig, sh: _Shell, cols, rings):
    """One thin ridge stripe per flute valley from the hem up to ``flute_line_top_z`` (single group: both borders draw
    as silhouettes and cost no rays): at each station (the valley column's vertices from the hem up, and the point at
    the top end on the valley edge) the borders lie ``valley_stripe[0]`` (hem) ... ``[1]`` (top end) along the two
    valley walls and float ``valley_stripe[2]`` above them; the ridge stands ``valley_stripe[3]`` above the valley."""
    w0, w1, flo, rel = rig.valley_stripe
    n = len(cols)
    ztop = rig.flute_line_top_z
    out = []
    for c, (kind, _v) in enumerate(cols):
        if kind != "valley":
            continue

        def vlr(r, c=c):
            base = sh.rings[r][0]
            return tuple(np.array(sh.V[base + (c + d) % n]) for d in (0, -1, 1))

        stations = [vlr(rings[-1])]                               # the hem first, then upwards
        for r in rings[-2::-1]:
            V, L, R = vlr(r)
            if V[2] < ztop:
                stations.append((V, L, R))
                continue
            Vb, Lb, Rb = stations[-1]
            f = (ztop - Vb[2]) / (V[2] - Vb[2])
            stations.append((Vb + f * (V - Vb), Lb + f * (L - Lb), Rb + f * (R - Rb)))
            break
        m = len(stations)
        A, Rg, B = [], [], []
        for i, (V, L, R) in enumerate(stations):
            T = _unit(stations[min(i + 1, m - 1)][0] - stations[max(i - 1, 0)][0])
            _hw, yf, yb = rig.skirt_section(float(V[2]))
            radial = np.array([V[0], V[1] - 0.5 * (yf + yb), 0.0])
            walls = []
            for Q in (L, R):
                d = _unit(Q - V)
                nw = _unit(np.cross(d, T))
                if _dot(nw, radial) < 0.0:
                    nw = -nw
                walls.append((d, nw))
            w = w0 + (w1 - w0) * (i / (m - 1.0))
            (dl, nl), (dr, nr) = walls
            A.append(V + w * dl + flo * nl)
            B.append(V + w * dr + flo * nr)
            Rg.append(V + rel * _unit(nl + nr))
        faces = []
        for j in range(m - 1):                                    # meshkit.ridge_band's faces (open ends)
            k = j + 1
            faces += [[j, k, m + k, m + j], [m + j, m + k, 2 * m + k, 2 * m + j], [2 * m + j, 2 * m + k, k, j]]
        faces += [[0, m, 2 * m], [m - 1, 3 * m - 1, 2 * m - 1]]
        out.append(mk._outward(mk.Mesh(np.array(A + Rg + B), faces, 1)))
    return out


# ---------------------------------------------------------------------------------------------------
# D.5 dress buttons (object buttons)
# ---------------------------------------------------------------------------------------------------

def _buttons(rig: Rig, bodice_profile, skirt_profile):
    """17 teardrops, pointed end up, on the centre front: a flat back floating ``button_float`` over the dress
    surface (the faceted centre column of the bodice / skirt) and a low pyramid dome over the bulb, ``button_relief``
    high on the bodice and ``button_skirt_relief`` on the skirt (its front crest is the side views' outline), one smooth
    group each."""
    bw, bh = rig.button_size
    out = []
    for z in rig.button_positions():
        on_bodice = z >= rig.seam_z
        prof = bodice_profile if on_bodice else skirt_profile
        relief = rig.button_relief if on_bodice else rig.button_skirt_relief
        zs = [p[0] for p in prof]
        ys = [p[1] for p in prof]
        y_lo = _interp_profile(zs, ys, z - 0.5 * bh)
        y_hi = _interp_profile(zs, ys, z + 0.5 * bh)
        T = _unit((0.0, y_hi - y_lo, bh))                       # up along the surface
        nrm = np.array([0.0, -T[2], T[1]])                      # forward (x cross T)
        C = np.array([0.0, _interp_profile(zs, ys, z), z])
        # the back plane clears every surface point under the button (the profile's vertices inside it too)
        samples = [z - 0.5 * bh, z, z + 0.5 * bh] + [q for q in zs if z - 0.5 * bh < q < z + 0.5 * bh]
        lift = max(_dot(np.array([0.0, _interp_profile(zs, ys, q), q]) - C, nrm) for q in samples)
        back = C + (lift + rig.button_float) * nrm
        ex = np.array([1.0, 0.0, 0.0])
        ring = [back + u * bw * ex + v * bh * T for u, v in BUTTON_OUTLINE]
        apex = C + (lift + relief) * nrm + BUTTON_APEX_V * bh * T
        V = np.array(ring + [apex])
        k = len(ring)
        faces = [[k, j, (j + 1) % k] for j in range(k)] + [list(range(k))[::-1]]
        out.append(mk._outward(mk.Mesh(V, faces, 1)))
    return out


# ---------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """The parts of :data:`REGIONS` for ``rig``."""
    parts = [Part("body.neck", "skin", _neck(rig), "neck"),
             Part("body.top", "top", _top_shell(rig), "top")]
    if TOP_SLEEVE_TUBES:
        for side in SIDES:
            parts.append(Part(f"body.top_sleeve_{_s(side)}", "top", _top_sleeve(rig, side), "top",
                              obj=f"arm_{_s(side)}"))
    bodice, bodice_profile = _bodice(rig)
    parts.append(Part("body.bodice", "dress", bodice, "dress"))
    for side in SIDES:
        parts.append(Part(f"body.strap_{_s(side)}", "dress", _strap(rig, side), "dress"))
    skirt, stripes, skirt_profile = _skirt(rig)
    parts.append(Part("body.skirt", "dress", skirt, "dress", obj="skirt"))
    for k, s in enumerate(stripes):
        parts.append(Part(f"body.skirt_valley{k}", "dress", s, "dress", obj="skirt"))
    for k, b in enumerate(_buttons(rig, bodice_profile, skirt_profile)):
        parts.append(Part(f"body.button{k:02d}", "buttons", b, "buttons"))
    return parts

"""Hair of the Reiya model (SPEC.md §C): regions ``hair``, ``tufts`` and ``braids``.

Regions and the objects they fill (SPEC.md §G, module -> regions mapping):

* ``hair`` -> object ``hair``: the dome H1; the parts with ``obj="fringe"``: the fringe H2 (the swept lock SL and the
  wide locks A-D) swept to her left from a parting on her right (§C.1, §C.2); the bob H3 (the side curtains and the
  back bell with their layered locks, slits and strand lines) as three shells cut along its outer back strand lines
  (:data:`BOB_SPLIT_STRAND`): ``obj="bob_l"`` her left side, ``obj="bob"`` the back, ``obj="bob_r"`` her right
  side; ``obj="hair_under"``: the lavender under-layer H4
  (``hair_inner``: the two lining strips and the two under-lock plates) (§C.3).  Each is a compact object of its own:
  the hidden-line pass then tests the face's lines only against the hair that can hide them;
* ``tufts`` -> object ``tufts`` (``objects[0]``, the observer pane's sight rays): the two ear-shaped hair tufts H5 with
  their lighter inner-face decals (``tuft_inner``) (§C.4);
* ``braids`` -> objects ``braid_l`` / ``braid_r``: the two thin three-strand braids H6 (lobes, tie, three-lock end
  tuft) (§C.5).

How it is built (the bare section numbers are SPEC.md's):

* **H1 dome** (§C.1): a loft of rings from the crown pole down to a bottom ring, closed by a fan to a point inside the
  skull.  Each ring point lies at an azimuth on the hair silhouette (``rig.hair_section``, the sheet's outline) blended,
  over the face, towards the scalp: there the dome is the skin moved out by :data:`DOME_FRONT_THICKNESS` above the
  hairline and dives into the skin below it (the hairline is ``rig.hairline_right`` on her right, the fringe roots
  across the front and ``rig.hairline_left`` under lock D), so the forehead triangle on her right shows skin and the
  fringe locks lie over a dome that disappears behind them.  At the sides and the back the three lowest rings take the
  bob's own contour columns at its rows (:data:`DOME_SEAM_MATCH`), :data:`DOME_SEAM_TUCK` inside its outer surface,
  whose top rows lie inside the dome: the two shells' facets are parallel where they cross, along a straight seam in
  every column (no edge of either shows); the rings above zip onto them by angle (:func:`_zip_loft`), or, with the
  switchable dome step :data:`DOME_SMOOTH`, carry the bob's columns all the way up (plus :data:`DOME_SMOOTH_RINGS`
  over the temples).  The first ring is the second one scaled towards the crown pole (:data:`DOME_CROWN_SCALE`,
  lifted :data:`DOME_CROWN_LIFT`), so the crown is convex and its quads planar.  One smooth group: it draws as
  silhouettes only.
* **H2 fringe** (§C.2): every lock is its own flat closed plate (``meshkit.strip_plate``) between its two edge
  polylines, drawn in the front view (root -> tip, full width down to ``fringe_taper`` of its length, then tapering to
  the tip) and put on the face: near its root the lock lies :data:`LOCK_PROUD` in front of the dome (the fringe
  continues the hair's silhouette), over :data:`LOCK_BLEND` below the root it comes in to ``fringe_gap`` (3 mm at the
  root -> 5 mm at the tip) plus ``fringe_thickness`` (4 mm) off the skin; the root end sinks into the dome.  Each
  plate is one smooth group, so its outline draws as the strand lines; neighbours alternate ``fringe_stagger`` in
  depth.  Lock D is two plates side by side (the strand line between), blunt along ``fringe_lower_edge``.
* **H3 bob** (§C.3, finishing pass): one closed shell in two zones.  The **bell** (above ``rig.bob_slit_top_z``)
  has rows :data:`BOB_BELL_ROWS` (those above :data:`BOB_BELL_SURFACE_Z` shrunk into the dome by one ratio to the
  height fraction's :data:`BOB_BELL_INSET_POWER`, :data:`BOB_TOP_INSET` at the top row's tightest) on columns round
  the bob: each curtain's inner edge (the face-window line, kept :data:`BOB_EDGE_GAP` off the skin),
  :data:`BOB_BELL_FACE` column across its flat front face, the outer corner, :data:`BOB_BELL_CONTOUR` contour columns
  per side (at even turning of the section's tangent, :data:`BOB_BELL_TURN`) and the back centre.  ``bob_rows`` are
  read through a monotone cubic (:class:`_BobFrame`: no kink at the table's rows; the front face's depth also averaged
  over :data:`BOB_FRONT_SMOOTH`, its lean above the dome's edge eased by :data:`BOB_FACE_TOP_LEAN`; above the table
  the hair silhouette's rows).  The column and row counts (:data:`BOB_BELL_CONTOUR`, :data:`BOB_BELL_ROWS`,
  :data:`BOB_LOCK_ROW_STEP`, :data:`BOB_FRONT_ROW_STEP`, :data:`BOB_LOCK_STRIPS`) are the triangle budget's knobs.
  Below it the **lock zone**, ``rig.bob_lock_columns``:
  long layered locks whose tips sit at their inner (face-side or nape-side) ends and whose lower edges rise outward,
  as the sheet draws them; a step (a lock ending on its neighbour's column above that column's tip) between locks,
  the strip of each lock thinning to :data:`BOB_TIP_THIN` below :data:`BOB_LOCK_MID_Z` (the back locks already by
  :data:`BOB_LOCK_PRE_THIN` above it) and curling in at its edge (:data:`BOB_TIP_CURL`).  Two slits per side
  (``rig.bob_slit_x``) separate the side lock from the curtain's front locks and the back locks; the side lock's inner
  face is flat (``bob_slit_x[1]``), so the front and back views see background through the slits, the sheet's
  standing-off outer strand; each slit closes to a narrow V at the top (:data:`BOB_SLIT_V`).  The lock ends are
  leaf-shaped (leaf pass): inserted columns (``rig.bob_leaf_columns``, at stable fractional positions between the
  table's columns) put the back locks' lower edges on the sheet's convex curves, the back step lock's tip closes to one
  vertex (:data:`BOB_CLOSED_TIPS`), the side lock's front corner is an arc of :data:`BOB_SIDE_CORNER_SEGMENTS`
  chords (:data:`BOB_SIDE_CORNER_STEPS`) and its back corner a point (``rig.bob_side_corner_radius``,
  ``rig.bob_side_back_tip``).  Beside the back slit the inserted columns lie on the contour itself (kind ``backc``,
  V4 pass: the first where the 3/4 views graze the surface, so it is their silhouette and no strip there is seen
  edge-on), and the leaf's flank does not curl in (:data:`BOB_LEAF_NO_CURL`).  A strip of triangles joins the
  bell's last row to the lock zone's top row (:func:`_zip_param`: each triangle the one whose diagonal spans less of
  the row); under the bell's side, behind the side lock, a flat ceiling closes the shell.  The inner surface lies
  the bob's thickness behind the front faces (mapped round the inner corner, :data:`BOB_INNER_CORNER_SPAN`), inside
  the contour, and keeps :data:`BOB_FACE_GAP` off the head and the neck.  Groups: each curtain's front face, the
  contour strips between the
  strand lines (:data:`BOB_STRANDS`: from the top down to two of the back locks' notches), the inner surface; the
  rims and walls each join the neighbour whose lit side differs (no construction ray), then settle by a descent
  (:func:`_settle_rim_groups`) that weighs castplane's rays against folds inside a group (:data:`RIM_FOLD_WEIGHT`).
  The curtains' inner rims lean :data:`BOB_EDGE_UNDERCUT` outward (they clear the head's hidden cheek bulge).
  Finally the shell is cut along the outer back strand lines (:data:`BOB_SPLIT_STRAND`, :func:`_split_bob`) into
  three closed shells (her left side, the back, her right side) for the hidden-line pass; each cut is closed by a cap
  inside the hair.
* **H4 under-layer** (§C.3, Decision 7): the lining is a thin closed strip per side on the inner face of the curtain's
  long front lock (by the jaw, where the sheet shows the lavender), straight along the lock's lower edge
  (:data:`LINING_STATIONS`) over ``bob_under_depth``, standing :data:`LINING_OFF` off the inner face, its ends tapered
  to points; the under-locks are one flat lock per side from inside the head's lower back down to one point between
  ``under_lock_tips`` (the sheet's lavender spike between the jaw and the braid).  One group each.
* **H5 ear tufts** (§C.4): a loft of curved plate sections (the cup face concave by ``tuft_cup_depth``) from a base
  sunk into the dome to the tip, thickness and cup tapering to the point (:data:`TUFT_TAPER`); the section's ends are
  inset so the back face starts on the straight inner edge and the cup ends on ``tuft_front_outline``.  One smooth
  group (silhouettes only).  The lighter inner face is a decal slab on the cup's outer half: its inner border and top
  (their own group) draw the one inner-ear line, its outer border sinks under the cup near the rim (no second
  contour).
* **H6 braids** (§C.5): per braid five slender pointed lobes (the first under the hair) leaning
  ``braid_lobe_tilt_deg`` alternately off the path and pitched :data:`BRAID_LOBE_PITCH_DEG` (each comes out from
  under the one above: the lobe edges draw the three-strand chevron), the tie (a short cylinder) and three swept
  pointed locks sagging between the tie and their tips (a crescent brush); every shell one group.

Every hair shell's quads are fan-triangulated on their valley diagonal (``meshkit.inscribed_fan``) and the twisted ones
split (:data:`TWIST_SPLIT_DEG`), so the outlines stay whole.
"""

from __future__ import annotations

import math

import numpy as np

from charmodel import meshkit as mk
from charmodel.meshkit import Part

from . import head as _head
from .rig import Rig

__all__ = ["REGIONS", "build"]

#: The regions this module builds (``--only hair`` selects all of them).
REGIONS = ("hair", "tufts", "braids")

SIDES = (1, -1)


def _side_name(side: int) -> str:
    return "l" if side > 0 else "r"


def _smoothstep(e0: float, e1: float, x):
    t = np.clip((np.asarray(x, dtype=np.float64) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _sstep(e0: float, e1: float, x: float) -> float:
    return float(_smoothstep(e0, e1, x))


def _norm3(v) -> float:
    return math.sqrt(float(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]))


def _unit3(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / _norm3(v)


# ---------------------------------------------------------------------------------------------------------------------
# section helpers
# ---------------------------------------------------------------------------------------------------------------------

def _polar(hw: float, yf: float, yb: float, phi_deg: float, ef: float, eb: float, c=None):
    """``(x, y)`` of the section ``(hw, yf, yb)`` on the ray from ``(0, c)`` at azimuth ``phi`` (0 front -Y, 90 her
    left +X, 180 back): front half superellipse ``(hw, c - yf)`` exponent ``ef``, back half ``(hw, yb - c)``
    exponent ``eb`` (``c`` the mid depth by default)."""
    cc = 0.5 * (yf + yb) if c is None else c
    p = math.radians(phi_deg)
    sx, cy = math.sin(p), -math.cos(p)
    back = cy > 0.0
    semi = (yb - cc) if back else (cc - yf)
    e = eb if back else ef
    if hw <= 0.0:
        return 0.0, cc
    if abs(sx) < 1e-12:
        r = semi
    elif abs(cy) < 1e-12:
        r = hw
    else:
        r = 1.0 / ((abs(sx) / hw) ** e + (abs(cy) / semi) ** e) ** (1.0 / e)
    return r * sx, cc + r * cy


def _sil_point(rig: Rig, z: float, phi: float) -> np.ndarray:
    """Point of the hair silhouette (``rig.hair_section``) at height ``z`` and azimuth ``phi``."""
    hw, yf, yb = rig.hair_section(z)
    ef, eb = rig.hair_exponent
    x, y = _polar(hw, yf, yb, phi, ef, eb)
    return np.array([x, y, z])


def _sil_normal(rig: Rig, z: float, phi: float) -> np.ndarray:
    """Outward horizontal unit normal of the hair silhouette section at ``(z, phi)`` (finite differences)."""
    a = _sil_point(rig, z, phi - 0.5)
    b = _sil_point(rig, z, phi + 0.5)
    t = b - a
    n = np.array([t[1], -t[0], 0.0])                  # phi grows counter-clockwise seen from +Z: (t_y, -t_x) is out
    return n / _norm3(n)


def _skin_point(rig: Rig, z: float, phi: float) -> np.ndarray:
    """Point of the skin head's section at ``(z, phi)`` (polar round the section's widest point ``(0, c)``)."""
    hw, yf, yb, c = rig.head_section(z)
    if yb is None:
        yb = c + 0.5 * (c - yf)
    x, y = _polar(hw, yf, yb, phi, rig.face_front_exponent, 2.0, c)
    return np.array([x, y, z])


# ---------------------------------------------------------------------------------------------------------------------
# hairline (front view, TRUE x): where the dome dives into the skin
# ---------------------------------------------------------------------------------------------------------------------

def _hairline(rig: Rig):
    """``(xs, zs)`` of the hairline in the front view (TRUE x, ascending): ``rig.hairline_right`` from her right temple
    to the parting, the fringe locks' roots across the front, ``rig.hairline_left`` down her left temple."""
    pts = [tuple(p) for p in rig.hairline_right]
    px = rig.parting[0]
    for lk in rig.fringe_locks:
        if lk[0] > px + 1e-9:
            pts.append((lk[0], lk[1]))
    pts += [tuple(p) for p in rig.hairline_left if p[0] > pts[-1][0] + 1e-9]
    pts.sort()
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])


def _hairline_z(rig: Rig, x: float) -> float:
    xs, zs = _hairline(rig)
    if x <= xs[0]:
        return float(zs[0] + (x - xs[0]) * (zs[1] - zs[0]) / (xs[1] - xs[0]))
    if x >= xs[-1]:
        return float(zs[-1] + (x - xs[-1]) * (zs[-1] - zs[-2]) / (xs[-1] - xs[-2]))
    return float(np.interp(x, xs, zs))


# ---------------------------------------------------------------------------------------------------------------------
# H1 dome
# ---------------------------------------------------------------------------------------------------------------------
#: Ring azimuths (degrees, counter-clockwise from her right back, 0 = the front): dense over the face and the fringe.
DOME_FRONT_AZIMUTHS = (-62.0, -52.0, -42.0, -32.0, -22.0, -12.0, -4.0, 4.0, 12.0, 22.0, 32.0, 42.0, 52.0, 62.0)
#: Constant-z rings of the dome (the hair rows, plus 1.596 / 1.587 between them: the crown's facets stay small, so the
#: head-top outline is whole from every azimuth), then two rings blending from the last one to the bottom ring.
DOME_RING_Z = (1.604, 1.600, 1.596, 1.592, 1.587, 1.582, 1.573, 1.563, 1.548, 1.533, 1.518)
DOME_BLEND = (0.5, 1.0)
#: The bottom ring: z over the face (buried in the skin), ``rig.dome_bottom_z`` at the sides and the back (inside the
#: bob), smoothstep between the two azimuths.
DOME_FRONT_BOTTOM_Z = 1.488
DOME_BOTTOM_PHI = (50.0, 75.0)
#: Over the face (weight 1 within DOME_FRONT_PHI[0] of the front, 0 beyond [1]) and below DOME_FRONT_Z[0] (0 above
#: [1]) the dome hugs the scalp, DOME_FRONT_THICKNESS off the skin (the temple hair beside the fringe); elsewhere it
#: is the hair silhouette.
DOME_FRONT_PHI = (45.0, 65.0)
DOME_FRONT_Z = (1.552, 1.578)
DOME_FRONT_THICKNESS = 0.014
#: Below the hairline the dome dives into the skin (DOME_BURY inside it): from DOME_DIVE[0] above the hairline to
#: DOME_DIVE[1] below it; it dives the same way over DOME_DIVE_BOTTOM above the bottom ring (the temples).
DOME_DIVE = (0.002, 0.012)
DOME_DIVE_BOTTOM = 0.012
DOME_BURY = 0.0025
#: At the sides and the back the dome's lower rows tuck this far inside the bob's outer surface (from the last hair row,
#: DOME_TUCK_Z, down to the bottom ring).
DOME_TUCK = 0.004
DOME_TUCK_Z = 1.505
#: ... and end this far under ``rig.dome_bottom_z`` (inside the bob, whose top rows lie inside the dome: the two
#: shells cross along a level seam; behind DOME_SEAM_FRONT_PHI the lowest rings follow the bob, DOME_SEAM_TUCK).
DOME_SIDE_DROP = 0.012
#: Below DOME_FRONT_TUCK_Z[0] (fully by [1]) the temple hair thins from DOME_EDGE_FADE[0] to DOME_EDGE_FADE[1] inside
#: the bob's inner edge (buried there), and lateral of the inner edge the dome tucks DOME_TUCK behind the bob's front
#: face.
DOME_EDGE_FADE = (0.012, 0.003)
DOME_FRONT_TUCK_Z = (1.535, 1.515)
#: The fan closing the dome underneath ends here (inside the skull).
DOME_CAP_APEX = (0.0, -0.010, 1.535)


def _front_weight(phi: float, z: float) -> float:
    a = abs(phi)
    return _sstep(DOME_FRONT_PHI[1], DOME_FRONT_PHI[0], a) * _sstep(DOME_FRONT_Z[1], DOME_FRONT_Z[0], z)


def _bottom_z(rig: Rig, phi: float) -> float:
    k = _sstep(DOME_BOTTOM_PHI[0], DOME_BOTTOM_PHI[1], abs(phi))
    return DOME_FRONT_BOTTOM_Z + k * (rig.dome_bottom_z - DOME_SIDE_DROP - DOME_FRONT_BOTTOM_Z)


def _skin_frame(rig: Rig, z: float, phi: float):
    """Skin section point at ``(z, phi)`` and its outward horizontal unit normal."""
    S = _skin_point(rig, z, phi)
    a = _skin_point(rig, z, phi - 0.5)
    b = _skin_point(rig, z, phi + 0.5)
    t = b - a
    n = np.array([t[1], -t[0], 0.0])
    return S, n / _norm3(n)


def dome_point(rig: Rig, phi: float, z: float, z_bottom: float | None = None, dive: bool = True) -> np.ndarray:
    """Point of the dome's outer surface at azimuth ``phi`` and height ``z`` (the analytic surface the mesh inscribes);
    ``dive=False`` leaves out the dive into the skin below the hairline (the surface the fringe lies on)."""
    zb = _bottom_z(rig, phi) if z_bottom is None else z_bottom
    P = _sil_point(rig, z, phi)
    tuck = DOME_TUCK * _sstep(DOME_TUCK_Z, zb, z) if zb < DOME_TUCK_Z else 0.0
    P = P - tuck * _sil_normal(rig, z, phi)
    if abs(phi) >= DOME_FRONT_PHI[1] or rig.head_section(z)[0] <= 0.0:
        return P
    S, n = _skin_frame(rig, z, phi)
    w = _front_weight(phi, z)
    fx, fy = rig.bob_row(z)[2], rig.bob_row(z)[3]
    kz = _sstep(DOME_FRONT_TUCK_Z[0], DOME_FRONT_TUCK_Z[1], z)
    if w > 0.0:
        # the temple hair thins out towards the face's side and dives into the skin just inside the bob's inner edge
        edge = _sstep(fx - DOME_EDGE_FADE[0], fx - DOME_EDGE_FADE[1], abs(float(S[0]))) * kz
        h = DOME_FRONT_THICKNESS - edge * (DOME_FRONT_THICKNESS + DOME_BURY)
        P = P + w * (S + h * n - P)
    # lateral of the bob's inner edge the dome's lower front tucks DOME_TUCK behind the bob's front face (the curtain's
    # front comes out from under it)
    k = _sstep(fx - DOME_EDGE_FADE[1], fx, abs(float(P[0]))) * kz
    if k > 0.0 and float(P[1]) < fy + DOME_TUCK:
        P = P.copy()
        P[1] += k * (fy + DOME_TUCK - float(P[1]))
    if dive:
        q = max(_sstep(_hairline_z(rig, float(S[0])) + DOME_DIVE[0], _hairline_z(rig, float(S[0])) - DOME_DIVE[1], z),
                _sstep(zb + DOME_DIVE_BOTTOM, zb, z))
        q *= _sstep(DOME_FRONT_PHI[1], DOME_FRONT_PHI[0], abs(phi))
        if q > 0.0:
            P = P + q * (S - DOME_BURY * n - P)
    return P


def dome_front_y(rig: Rig, x: float, z: float, dive: bool = True) -> float:
    """y of the dome's analytic front surface at the front-view point ``(x, z)`` (bisection on the azimuth)."""
    lo, hi = -89.0, 89.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if dome_point(rig, mid, z, dive=dive)[0] < x:
            lo = mid
        else:
            hi = mid
    return float(dome_point(rig, 0.5 * (lo + hi), z, dive=dive)[1])


def dome_azimuths(rig: Rig):
    """The dome's ring azimuths (degrees, ascending from her right back round the front): over the face
    :data:`DOME_FRONT_AZIMUTHS`, at the sides and the back the bob's contour columns at its second row (so the two
    shells' facets run parallel where they cross)."""
    pc = _bob_corner_phi(rig, BOB_ROW_Z[1])
    back = [round(_contour_phi(pc, k), 6) for k in range(1, BOB_CONTOUR_COLUMNS + 1)]
    return tuple([-a for a in back[::-1]] + list(DOME_FRONT_AZIMUTHS) + back + [180.0])


def _dome(rig: Rig) -> mk.Mesh:
    rings = []
    azimuths = dome_azimuths(rig)
    keys = [("d", float(a)) for a in azimuths]
    if DOME_SEAM_MATCH and DOME_SMOOTH:
        front = [a for a in azimuths if abs(a) <= DOME_SEAM_FRONT_PHI]
        back = _dome_bob_azimuths(rig)
        azimuths = [-a for a in back[::-1]] + front + back + [180.0]
        keys = ([("b", -k) for k in range(len(back), 0, -1)] + [("d", float(a)) for a in front]
                + [("b", k) for k in range(1, len(back) + 1)] + [("d", 180.0)])
    ring_z = sorted(DOME_RING_Z + (DOME_SMOOTH_RINGS if DOME_SMOOTH else ()), reverse=True)
    for z in ring_z:
        rings.append(np.array([dome_point(rig, phi, z) for phi in azimuths]))
    z0 = ring_z[-1]
    for t in DOME_BLEND:
        ring = []
        for phi in azimuths:
            zb = _bottom_z(rig, phi)
            ring.append(dome_point(rig, phi, z0 + t * (zb - z0), zb))
        rings.append(np.array(ring))
    crown = rig.hair_rows[0]
    apex = np.array([0.0, crown[2], crown[0]])
    # the first ring is the second one scaled towards the crown pole and lifted a little: its quads are planar
    # trapezoids and the crown is convex (a ring sampled on the narrower section at its height twists the quads, and
    # their valley folds hide pieces of the head-top outline)
    rings[0] = apex + DOME_CROWN_SCALE * (rings[1] - apex) + np.array([0.0, 0.0, DOME_CROWN_LIFT])
    if DOME_SEAM_MATCH:
        mesh = _zip_loft(_seam_rings(rig, rings, keys), apex, np.asarray(DOME_CAP_APEX, dtype=np.float64))
    else:
        mesh = mk.loft(rings, ("pole", tuple(apex)), ("pole", DOME_CAP_APEX), groups=1, cap_groups=(1, 1))
    return mk.split_twisted(mk.inscribed_fan(mesh), DOME_TWIST_SPLIT_DEG)


#: The seam with the bob: the dome's three lowest rings (where the bob dives under it) take the bob's own contour
#: columns at the bob's rows BOB_BELL_ROWS[1:4] behind DOME_SEAM_FRONT_PHI, DOME_SEAM_TUCK inside the bob's outer
#: contour (before its top rows shrink into the dome): the two shells' facets are parallel there, so the seam is
#: straight in every column (on the dome's own coarser columns the two surfaces, within 2 mm of each other over 15 mm
#: of height, crossed back and forth: a crenellated seam in the shaded views).  The upper rings zip onto them by angle.
DOME_SEAM_MATCH = True
DOME_SEAM_FRONT_PHI = 52.0
DOME_SEAM_TUCK = (0.0, 0.003, 0.005)
#: ... a bob column within this angle (degrees) of the last front point is left out.
DOME_SEAM_MIN_DEG = 3.0
#: The dome step (switchable, off: the triangle budget): every ring of the dome takes the bob's contour columns
#: behind DOME_SEAM_FRONT_PHI (at the dome's own azimuths through the bob's columns at the seam's top row), so the
#: rings above the seam need no zip (its fans pleat the dome's side above the seam) and the dome's back is as fine
#: as the bell; and the rings DOME_SMOOTH_RINGS split the fold where the dome turns from the silhouette onto the
#: scalp over the temples (DOME_FRONT_Z), a kink in its 3/4 outline.
DOME_SMOOTH = False
DOME_SMOOTH_RINGS = (1.5775,)


def _dome_bob_azimuths(rig: Rig):
    """The dome's azimuths (her left) through the bob's contour columns at BOB_BELL_ROWS[1] (angles about the bob's
    polar centre, bisection on the dome's own azimuth)."""
    bf = _BobFrame(rig)
    z = BOB_BELL_ROWS[1]
    out = []
    for phi in _bell_phis(bf, z):
        P = bf.contour(z, phi)
        th = math.atan2(float(P[0]), bf.c - float(P[1]))
        lo, hi = DOME_SEAM_FRONT_PHI, 179.9
        for _ in range(50):
            mid = 0.5 * (lo + hi)
            D = dome_point(rig, mid, z)
            if math.atan2(float(D[0]), bf.c - float(D[1])) < th:
                lo = mid
            else:
                hi = mid
        out.append(0.5 * (lo + hi))
    return out


def _seam_rings(rig: Rig, rings, keys):
    """The dome's rings as ``[(key, angle, point), ...]`` (ascending angle about the bob's polar centre, the back
    centre last; ``keys`` the columns' keys, ``("d", azimuth)`` or ``("b", bob column)``), the lowest three with the
    bob's contour columns behind DOME_SEAM_FRONT_PHI (:data:`DOME_SEAM_MATCH`)."""
    bf = _BobFrame(rig)
    c = bf.c

    def ang(P):
        return math.degrees(math.atan2(float(P[0]), c - float(P[1])))

    out = []
    n = len(rings)
    for r, ring in enumerate(rings):
        cols = [(key, 180.0 if key == ("d", 180.0) else ang(P), np.asarray(P, dtype=np.float64))
                for key, P in zip(keys, ring)]
        s = r - (n - len(DOME_SEAM_TUCK))
        if s >= 0:
            z, tuck = BOB_BELL_ROWS[1 + s], DOME_SEAM_TUCK[s]
            front = [col for col in cols if col[0][0] == "d" and abs(col[0][1]) <= DOME_SEAM_FRONT_PHI]
            lim = max(col[1] for col in front)
            back = []
            for k, phi in enumerate(_bell_phis(bf, z), 1):
                P = bf.contour(z, phi) - tuck * bf.normal(z, phi)
                if ang(P) > lim + DOME_SEAM_MIN_DEG:
                    back.append((("b", k), ang(P), P))
            P = bf.contour(z, 180.0) - tuck * bf.normal(z, 180.0)
            P[0] = 0.0
            mirrored = [(("b", -key[1]), -a, np.array([-P_[0], P_[1], P_[2]])) for key, a, P_ in back[::-1]]
            cols = mirrored + front + back + [(("d", 180.0), 180.0, P)]
        out.append(cols)
    return out


def _zip_loft(rings, apex_top, apex_bottom) -> mk.Mesh:
    """Closed shell (group 1) through closed rings ``[(key, angle, point), ...]`` (ascending angle, each ending on the
    same key at 180 degrees): between two rings a quad where the keys match, else a triangle zipped by angle; pole
    fans at both ends."""
    V, ids = [], []
    for ring in rings:
        ids.append(list(range(len(V), len(V) + len(ring))))
        V.extend(P for _k, _a, P in ring)
    faces = []
    for A, B, ia, ib in zip(rings, rings[1:], ids, ids[1:]):
        a, b = ia[-1], ib[-1]
        i = j = 0
        while i < len(A) or j < len(B):
            if i < len(A) and j < len(B) and A[i][0] == B[j][0]:
                faces.append([a, ia[i], ib[j], b])
                a, b = ia[i], ib[j]
                i, j = i + 1, j + 1
            elif j == len(B) or (i < len(A) and A[i][1] < B[j][1]):
                faces.append([a, ia[i], b])
                a = ia[i]
                i += 1
            else:
                faces.append([a, ib[j], b])
                b = ib[j]
                j += 1
    top = len(V)
    V.append(np.asarray(apex_top, dtype=np.float64))
    r0 = ids[0]
    for j in range(len(r0)):
        faces.append([top, r0[(j + 1) % len(r0)], r0[j]])
    bot = len(V)
    V.append(np.asarray(apex_bottom, dtype=np.float64))
    rl = ids[-1]
    for j in range(len(rl)):
        faces.append([bot, rl[j], rl[(j + 1) % len(rl)]])
    return _head.oriented(mk.Mesh(np.array(V), faces, 1))


#: The dome's first ring is its second ring scaled this far from the crown pole (hw 0.040 -> 0.024) and lifted
#: DOME_CROWN_LIFT over that cone (z 1.6032; at most ~1 mm, or the front's fold at the second ring turns concave).
DOME_CROWN_SCALE = 0.6
DOME_CROWN_LIFT = 0.0008


#: Quads of the hair shells whose two fan triangles differ by more than this become two triangles.
TWIST_SPLIT_DEG = 6.0
#: ... the dome's (its outline over the temples in the 3/4 views runs along quads twisted by 4.5-6 degrees).
DOME_TWIST_SPLIT_DEG = 4.5


# ---------------------------------------------------------------------------------------------------------------------
# H2 fringe
# ---------------------------------------------------------------------------------------------------------------------
#: Stations along a lock (fractions of root -> tip; the first one is the root end inside the dome, LOCK_ROOT_EXT above
#: the root along the lock's direction).
LOCK_STATIONS = (0.0, 0.18, 0.38, 0.58, 0.72, 0.86, 1.0)
LOCK_ROOT_EXT = 0.006
#: Where the dome is thicker than the fringe's gap, the lock's outer face stands this far in front of it.
LOCK_PROUD = 0.0015


def _lock_frame(rig: Rig, x: float, z: float):
    """``(point, outward unit normal)`` of the smooth face (the forehead) at the front-view point ``(x, z)``."""
    return _head.smooth_face(rig, x, z)


def _lock_y(rig: Rig, x: float, z: float, s: float, stagger: float, root_z: float) -> float:
    """y of a lock's outer face at the front-view point ``(x, z)``, ``s`` along the lock (< 0: the root end, sunk
    LOCK_SINK into the dome).  Near its root the lock lies on the dome (LOCK_PROUD in front of it, so the fringe
    continues the hair's silhouette); over LOCK_BLEND below the root it comes in to the spec's gap off the skin
    (``fringe_gap`` at the root -> at the tip, plus ``fringe_thickness``), never closer, and it stays in
    front of the dome where the dome is thick (the temple hair under the swept lock and lock D)."""
    on_dome = dome_front_y(rig, x, z, dive=False)
    if s < 0.0:
        return on_dome + LOCK_SINK + stagger
    g0, g1 = rig.fringe_gap
    gap = g0 + (g1 - g0) * min(1.0, s)                 # linear, root -> tip
    p, n = _lock_frame(rig, x, z)
    spec = float(p[1]) - (gap + rig.fringe_thickness) / max(0.3, -float(n[1]))
    b = _sstep(root_z, root_z - LOCK_BLEND, z)
    y = (on_dome - LOCK_PROUD) + b * (spec - (on_dome - LOCK_PROUD))
    y = min(y, spec, dome_front_y(rig, x, z) - LOCK_PROUD)
    return y + stagger


#: The lock's root end sinks this far behind the dome's surface; the lock comes in from the dome to the spec gap over
#: this height below its root.
LOCK_SINK = 0.006
LOCK_BLEND = 0.045


def _lock_edges(rig: Rig, k: int):
    """``(a (n, 2), b (n, 2), pointed)``: the two edge polylines of fringe lock ``k`` (TRUE x, front view), root end ->
    tip; ``a`` is the edge towards -x."""
    rx, rz, tx, tz, wr, wt = rig.fringe_locks[k]
    root, tip = np.array([rx, rz]), np.array([tx, tz])
    d = tip - root
    L = math.hypot(float(d[0]), float(d[1]))
    u = d / L
    perp = np.array([-u[1], u[0]])                    # towards +x for a lock hanging down
    if perp[0] < 0:
        perp = -perp
    taper = rig.fringe_taper
    a, b = [], []
    for s in LOCK_STATIONS:
        ws = wr if s <= 1.0 - taper else wr + (wt - wr) * (s - (1.0 - taper)) / taper
        if k == 0:                                    # SL: its inner (+x) edge is the hairline on her right
            c_in = _hairline_point(rig, s)
            c = c_in - 0.5 * ws * perp
        else:
            c = root + s * d
        if s == 0.0:
            c = c - LOCK_ROOT_EXT * u
        a.append(c - 0.5 * ws * perp)
        b.append(c + 0.5 * ws * perp)
    return np.array(a), np.array(b), wt <= 0.0


def _hairline_point(rig: Rig, s: float) -> np.ndarray:
    """Point at the fraction ``s`` (by arc length) of ``rig.hairline_right`` from the parting to its lower end."""
    pts = np.array(rig.hairline_right, dtype=np.float64)
    return mk.polyline_at(pts, [s])[0]


def _lock_d_edges(rig: Rig):
    """Lock D as two plates side by side (``fringe_lock_d_split`` across it, a strand line between): ``[(a, b), ...]``
    with blunt ends along ``fringe_lower_edge`` (from its lower-inner corner)."""
    rx, rz, tx, tz, wr, _wt = rig.fringe_locks[4]
    lower = [tuple(p) for p in rig.fringe_lower_edge]
    tops = [np.array([rx - 0.5 * wr, rz]), np.array([rx, rz]), np.array([rx + 0.5 * wr, rz])]
    bots = [np.array(lower[0]), np.array(lower[2]), np.array(lower[-1])]
    out = []
    for (t0, t1), (b0, b1) in zip(((tops[0], tops[1]), (tops[1], tops[2])), ((bots[0], bots[1]), (bots[1], bots[2]))):
        A, B = [], []
        for s in LOCK_STATIONS:
            ea, eb = t0 + s * (b0 - t0), t1 + s * (b1 - t1)
            if s == 0.0:
                ua = _unit2(b0 - t0)
                ub = _unit2(b1 - t1)
                ea, eb = ea - LOCK_ROOT_EXT * ua, eb - LOCK_ROOT_EXT * ub
            A.append(ea)
            B.append(eb)
        out.append((np.array(A), np.array(B)))
    return out


def _unit2(v) -> np.ndarray:
    v = np.asarray(v, dtype=np.float64)
    return v / math.hypot(float(v[0]), float(v[1]))


def _lock_plate(rig: Rig, a2, b2, pointed: bool, stagger: float, root_z: float) -> mk.Mesh:
    """The closed plate of a lock from its front-view edges: the outer face on :func:`_lock_y`, ``fringe_thickness``
    deep along the face normal."""
    A3, B3, N = [], [], []
    for i, s in enumerate(LOCK_STATIONS):
        ss = -1.0 if i == 0 else s
        for P2, out in ((a2[i], A3), (b2[i], B3)):
            x, z = float(P2[0]), float(P2[1])
            out.append(np.array([x, _lock_y(rig, x, z, ss, stagger, root_z), z]))
        c = 0.5 * (a2[i] + b2[i])
        N.append(_lock_frame(rig, float(c[0]), float(c[1]))[1])
    A3, B3 = np.array(A3), np.array(B3)
    if pointed:
        tip = 0.5 * (A3[-1] + B3[-1])
        A3[-1] = tip
        B3[-1] = tip
    return mk.strip_plate(A3, B3, np.array(N), rig.fringe_thickness, offset="inward", tip=pointed)


def _fringe(rig: Rig):
    """The swept lock SL and locks A, B, C (one plate each) and lock D (two plates)."""
    parts = []
    names = ("sl", "a", "b", "c")
    st = rig.fringe_stagger
    for k, nm in enumerate(names):
        a, b, pointed = _lock_edges(rig, k)
        stagger = (0.0, st, -st, st)[k]
        parts.append(Part(f"hair.lock_{nm}", "hair", _lock_plate(rig, a, b, pointed, stagger,
                                                                       rig.fringe_locks[k][1]), "hair", obj="fringe"))
    for j, (a, b) in enumerate(_lock_d_edges(rig)):
        parts.append(Part(f"hair.lock_d{j + 1}", "hair", _lock_plate(rig, a, b, False, (-st, st)[j],
                                                                            rig.fringe_locks[4][1]), "hair",
                          obj="fringe"))
    return parts


# ---------------------------------------------------------------------------------------------------------------------
# H3 bob (objects bob_l, bob, bob_r) and the H4 lavender under-layer
# ---------------------------------------------------------------------------------------------------------------------
#: The dome's ring azimuths at the sides and the back follow the first bob's contour columns at its second row
#: (BOB_CONTOUR_COLUMNS per side behind the corner, column BOB_SIDE_COLUMN at 90 degrees; :func:`dome_azimuths`).
BOB_ROW_Z = (1.540, 1.495)
BOB_CONTOUR_COLUMNS = 5
BOB_SIDE_COLUMN = 2
#: The bob's top row starts this far inside the dome (its edge is never seen); the inner surface keeps this far off the
#: face and the skull.
BOB_TOP_INSET = 0.008
BOB_FACE_GAP = 0.003
#: The curtain's inner rim (between its front face and its inner surface) leans this far outward over the bob's
#: thickness, so the front views see only the face-window line, not the rim beside it, and the rim clears the head's
#: cheek bulge (``rig.cheek_bulge``) behind the edge by >= 3 mm.
BOB_EDGE_UNDERCUT = 0.008
#: Centre of the bob's sections (the hair section's at the eye line) for the column azimuths.
BOB_CENTRE_Z = 1.459


def _bob_outer_section(rig: Rig, z: float):
    """``(hw, yf, yb, c)`` of the bob's outer contour at ``z``: ``bob_rows`` hw / yb, the front half the hair
    section's (clamped at the eye line), polar centre ``c`` fixed at the eye line's."""
    hw, yb = rig.bob_row(z)[0], rig.bob_row(z)[1]
    yf = rig.hair_section(max(z, BOB_CENTRE_Z))[1]
    _hw, yf0, yb0 = rig.hair_section(BOB_CENTRE_Z)
    return hw, yf, yb, 0.5 * (yf0 + yb0)


def _bob_contour(rig: Rig, z: float, phi: float) -> np.ndarray:
    hw, yf, yb, c = _bob_outer_section(rig, z)
    ef, eb = rig.hair_exponent
    x, y = _polar(hw, yf, yb, phi, ef, eb, c)
    return np.array([x, y, z])


def _bob_corner_phi(rig: Rig, z: float) -> float:
    """Azimuth of the outer corner (where the outer contour reaches the front face's plane ``y = front_y``)."""
    hw, yf, yb, c = _bob_outer_section(rig, z)
    fy = rig.bob_row(z)[3]
    ef, _eb = rig.hair_exponent
    x = rig.section_half_width_at(hw, yf, yb, fy, ef, rig.hair_exponent[1], c)
    return math.degrees(math.atan2(x, c - fy))


def _contour_phi(pc: float, k: int) -> float:
    """Azimuth of contour column ``k`` (1 .. BOB_CONTOUR_COLUMNS) behind the corner at ``pc``: evenly spaced from the
    corner to the side column BOB_SIDE_COLUMN at 90 degrees (the bell's widest point is a column), then evenly to the
    back centre."""
    if k <= BOB_SIDE_COLUMN:
        return pc + k / BOB_SIDE_COLUMN * (90.0 - pc)
    return 90.0 + (k - BOB_SIDE_COLUMN) / (BOB_CONTOUR_COLUMNS + 1 - BOB_SIDE_COLUMN) * 90.0


def _push_off_head(rig: Rig, P, gap: float) -> np.ndarray:
    """``P`` moved out (horizontally, away from the head's axis) until it is ``gap`` outside the skin head (or the
    neck below the head's last back row)."""
    P = np.array(P, dtype=np.float64)
    z = float(P[2])
    hw, yf, yb, c = rig.head_section(min(z, rig.head_profile[0][0]))
    if yb is None or hw <= 0.0:
        hw, yf, yb = rig.neck_section(z)
        c = 0.5 * (yf + yb)
        ef, eb = 2.0, 2.0
    else:
        ef, eb = rig.face_front_exponent, 2.0
    d = np.array([P[0], P[1] - c])
    r = math.hypot(float(d[0]), float(d[1]))
    if r < 1e-9:
        return P
    phi = math.degrees(math.atan2(float(d[0]), -float(d[1])))
    sx, sy = _polar(hw + gap, yf - gap, yb + gap, phi, ef, eb, c)
    rs = math.hypot(sx, sy - c)
    if r < rs:
        P[0], P[1] = sx, sy
    return P


def _dome_along(rig: Rig, z: float, theta: float, centre) -> np.ndarray:
    """The dome's (undived) surface point at height ``z`` on the ray from ``centre`` ``(x, y)`` at the angle ``theta``
    (radians, from -Y towards +X): bisection on the dome's own azimuth."""
    def ang(phi):
        D = dome_point(rig, phi, z, dive=False)
        return math.atan2(float(D[0] - centre[0]), float(centre[1] - D[1]))
    lo, hi = -179.0, 179.0
    for _ in range(50):
        mid = 0.5 * (lo + hi)
        if ang(mid) < theta:
            lo = mid
        else:
            hi = mid
    return dome_point(rig, 0.5 * (lo + hi), z, dive=False)


#: The bob's bell (above ``rig.bob_slit_top_z``): its outer rows (the top one starts BOB_TOP_INSET inside the dome)
#: and the rows of its inner surface (the face-window edge column keeps every outer row: its rim pairs them).
BOB_BELL_ROWS = (1.540, 1.517, 1.495, 1.481, 1.466)
BOB_BELL_INNER_ROWS = (1.540, 1.517, 1.495, 1.481, 1.466)
#: Rows above BOB_BELL_SURFACE_Z lie inside the dome: shrunk towards the section's centre, fully (the top row's ratio)
#: at BOB_BELL_ROWS[0], not at all at BOB_BELL_SURFACE_Z, by the height fraction to BOB_BELL_INSET_POWER between (no
#: crease where the bell leaves the dome).
BOB_BELL_SURFACE_Z = 1.495
BOB_BELL_INSET_POWER = 2.0
#: Above BOB_BELL_SURFACE_Z (under the dome's edge) the curtain's front face leans forward this fraction of the
#: table's lean (the '(' sweep carries on up to 27 degrees forward, and the face has to turn back into the dome: at
#: the full lean it folds 27 degrees at the second row, where it shows beside the dome).
BOB_FACE_TOP_LEAN = 0.5
#: The bell's hw / yb above ``bob_rows`` follow the hair silhouette's rows more than this above the table's top row.
BOB_HAIR_KNOT_GAP = 0.005
#: The top rim (inside the dome) slopes down inward by this much, so it folds sharply off the outer surface.
BOB_TOP_RIM_DROP = 0.004
#: The bell's contour columns per side between the curtain's outer corner and the back centre (BOB_BELL_WARP spreads
#: them so the section's normal turns about evenly from column to column), and its columns across the curtain's
#: front face between the inner edge and the outer corner.
BOB_BELL_CONTOUR = 13
BOB_BELL_WARP = 0.18
#: ... blended this far (0 .. 1) towards columns at even turning of the section's tangent (the back half's
#: superellipse turns twice as fast at its diagonals as at the side), measured on this many chords.
BOB_BELL_TURN = 1.0
BOB_BELL_TURN_SAMPLES = 240
BOB_BELL_FACE = 1
#: The lock zone's rows: about one per BOB_LOCK_ROW_STEP of a column's height (BOB_LOCK_STRIPS at least / at most),
#: spaced closer towards the lock's lower edge (BOB_LOCK_EASE), where the bell curls in.
BOB_LOCK_ROW_STEP = 0.018
#: Every lock reaching below it has a row here (its inner surface too: above it the inner surface is a regular
#: strip under the bell, below it each lock's inner face thins to its edge).
BOB_LOCK_MID_Z = 1.428
#: The curtain's front locks have rows this close under the bell (their face turns from back to forward there: the
#: '(' sweep of the face-window edge in profile).
BOB_FRONT_ROW_STEP = 0.008
BOB_LOCK_STRIPS = (2, 5)
#: A lock reaching more than this below BOB_LOCK_MID_Z (the nape's) keeps every row on its inner surface too, which
#: then follows the back's curl (a straight inner face would cut out through it).
BOB_DEEP_LOCK = 0.03
BOB_LOCK_EASE = 1.35
#: Below BOB_LOCK_MID_Z a lock thins to BOB_TIP_THIN of the bob's thickness at its lower edge; its last BOB_TIP_CURL_H
#: curl in by BOB_TIP_CURL (towards the head: a lock's end tucks in, no flare).
BOB_TIP_THIN = 0.2
BOB_TIP_CURL = 0.001
BOB_TIP_CURL_H = 0.010
#: The side lock's outer edges stand this far outside its flat inner face (``rig.bob_slit_x[1]``): a narrow end
#: strip, never a knife edge.
BOB_SIDE_EDGE = 0.0006
#: The slits close to a V at the top: over their top BOB_SLIT_V their inner side comes to BOB_SLIT_TOP_GAP from the
#: side lock's flat face (negative: past it).  The front slit's V closes on the face lock's top point, see :func:`_bob`.
BOB_SLIT_V = 0.008
BOB_SLIT_TOP_GAP = -0.0002
#: ... and its front edge follows the curtain's corner where that lies outside, eased over this width into the
#: constant x below (no kink where the corner sweeps in past the slit).
BOB_SIDE_EASE = 0.003
#: Behind the curtain's outer corner the front face's last part maps onto the inner face's last BOB_INNER_CORNER_SPAN
#: before the inner corner (no two inner points collapse onto the mitre).
BOB_INNER_CORNER_SPAN = 0.012
#: ... and the contour's first degrees behind the outer corner map onto this arc (degrees) of the inner contour
#: behind the inner corner.
BOB_INNER_CORNER_ARC = 1.0
#: Half-width (in z) of the triangular average that smooths the curtain's front face's depth (y) from ``bob_rows``.
BOB_FRONT_SMOOTH = 0.030
#: The face-window edge stays at least this far outside the skin head's section.
BOB_EDGE_GAP = 0.0012
#: Azimuths of the inner surface's points on the top row of the lock zone between the two slits (the ceiling of the
#: room under the bell's side, behind the side lock).
BOB_SIDE_INNER_PHI = (86.0, 96.0, 106.0)
#: Strand lines (group boundaries on the bob's outer surface): from the bell's top down to the notch of these lock
#: columns (indices into ``rig.bob_lock_columns``), per side; the rest of the outer surface is one smooth group per
#: strip, the curtains' front faces one group each.
BOB_STRANDS = (15, 18)
#: The bob is cut along this strand line (one of :data:`BOB_STRANDS`: the outer back strand, |x| 0.092 at its notch)
#: on each side into three closed shells: her left side (the curtain, the side lock and the back locks out to the
#: strand), the back between the two cuts (with the nape) and her right side, each an object of its own (``bob_l``,
#: ``bob``, ``bob_r``; finishing pass, merge).  castplane's hidden-line pass tests a sample only against the objects
#: whose image rectangle contains it (and that reach nearer than the sample), and the one-shell bob (1292 triangles)
#: was tested by every line of the face, the head, the dome and the braids: the cut takes the cost model of the web
#: still frame from 23.7 to 19.3 M ray-triangle tests.  The cut follows the strand line, which draws anyway, from the
#: bell's top (inside the dome) down to the lock's notch; the cap that closes each shell (a strip between the outer
#: and the inner surface, inside the hair, :data:`BOB_CUT_TUCK`) is a group of its own.  What it adds to the drawing:
#: the cut's inner edge, a line on the bob's underside behind the side lock, seen from below (``low_angle``,
#: ``head_low``) and in a few mm under the bob in the front views; a few strokes inside the head's ground shadow.  The
#: scene camera's and the 3/4 views' object lines are pixel-identical.  ``None``: one shell.  (The inner strand, 18,
#: was tried first: its inner edge runs beside the neck and drew a stroke in the scene camera and the 3/4 views.)
BOB_SPLIT_STRAND = 15
#: The three bob shells share no vertex and no face (:func:`_split_bob`): the shell whose lock ends at the cut's notch
#: (the back, for strand 15) has its own copies of the cut's outer and inner column moved BOB_CUT_TUCK past the cut
#: into the neighbouring shell and BOB_CUT_TUCK into the hair (0.107 mm each on the final model, 0.152 mm in all), so
#: its cut edges and cap lie inside the neighbour and the neighbour's cap inside it, both inside the hair.  The
#: neighbour's cut edges stay on the strand line, which is drawn once, where it was (as by the one-shell bob), and
#: the outer surface has no slit.  With coinciding caps the whole OBJ, imported as one castplane mesh (it welds
#: vertices closer than 1e-6 m across shells), had 44 edges with three or more faces (``MESH_NON_MANIFOLD``); a
#: setback of each cap into its own shell instead opened a 0.23 mm slit and drew the strand line twice, about a pixel
#: apart in the head close-ups.  Vertices of different shells stay 0.147 mm apart or more after the 0.01 mm rounding
#: (rule 6).
BOB_CUT_TUCK = 0.00011
#: Lock columns (indices into ``rig.bob_lock_columns``) whose tip closes to one vertex: the lock's inner surface meets
#: its outer one at the tip (a leaf's point, no rim across the lock's thickness there), so the step wall above the tip
#: and the lower edge meet in the outline as one sharp point (the rim between the outer and the inner tip drew a
#: 48-53 degree corner beside it, seen obliquely).
BOB_CLOSED_TIPS = (15,)
#: The lock zone's first front-face column starts this far from the face-window edge (the edge's inner rim leans
#: BOB_EDGE_UNDERCUT outward), the others evenly between it and the front slit.
BOB_LOCK_FIRST_GAP = 0.015


def _softmax(a: float, b: float, w: float) -> float:
    """A smooth maximum of ``a`` and ``b`` (equal to the larger one when they differ by more than ``w``)."""
    d = a - b
    if d >= w:
        return a
    if d <= -w:
        return b
    return b + (d + w) ** 2 / (4.0 * w)


def _pchip(xs, ys, x: float) -> float:
    """Monotone cubic (Fritsch-Carlson) interpolation through ``(xs, ys)`` (``xs`` ascending), clamped outside."""
    n = len(xs)
    if x <= xs[0]:
        return float(ys[0])
    if x >= xs[-1]:
        return float(ys[-1])
    h = [xs[k + 1] - xs[k] for k in range(n - 1)]
    d = [(ys[k + 1] - ys[k]) / h[k] for k in range(n - 1)]
    m = [0.0] * n
    m[0], m[-1] = d[0], d[-1]
    for k in range(1, n - 1):
        if d[k - 1] * d[k] > 0.0:
            w1, w2 = 2.0 * h[k] + h[k - 1], h[k] + 2.0 * h[k - 1]
            m[k] = (w1 + w2) / (w1 / d[k - 1] + w2 / d[k])
    k = 0
    while x > xs[k + 1]:
        k += 1
    t = (x - xs[k]) / h[k]
    h00, h10 = 2 * t ** 3 - 3 * t ** 2 + 1, t ** 3 - 2 * t ** 2 + t
    h01, h11 = -2 * t ** 3 + 3 * t ** 2, t ** 3 - t ** 2
    return float(h00 * ys[k] + h10 * h[k] * m[k] + h01 * ys[k + 1] + h11 * h[k] * m[k + 1])


class _BobFrame:
    """The bob's outer surface as functions of height: ``bob_rows`` interpolated by a monotone cubic (no kink at the
    table's rows), the outer contour (front half the hair section's), the curtain's front face and its outer corner,
    the inner surface (the bob's thickness inside)."""

    def __init__(self, rig: Rig):
        self.rig = rig
        rows = sorted(rig.bob_rows)                    # ascending z
        self.zs = [r[0] for r in rows]
        self.cols = [[r[k] for r in rows] for k in range(1, 6)]
        # hw / yb above the table's top row: the hair silhouette's rows (the bell's top rows tuck into the dome,
        # which narrows above it)
        top = [h for h in sorted(rig.hair_rows) if h[0] > self.zs[-1] + BOB_HAIR_KNOT_GAP and h[1] > 0.0]
        self.zs_hw = self.zs + [h[0] for h in top]
        self.cols_hw = [self.cols[0] + [h[1] for h in top], self.cols[1] + [h[3] for h in top]]
        _hw, yf0, yb0 = rig.hair_section(BOB_CENTRE_Z)
        self.c = 0.5 * (yf0 + yb0)
        self.ef, self.eb = rig.hair_exponent
        self._rows = {}

    def row(self, z: float):
        """``(hw, yb, front_x, front_y, t)`` at ``z``; the front edge's y averaged over BOB_FRONT_SMOOTH (the
        table's '(' sweep turns 35 degrees within 2 cm at the eye line: a crease across the curtain's front)."""
        key = round(z, 9)
        if key not in self._rows:
            out = [_pchip(self.zs, col, z) for col in self.cols]
            out[0], out[1] = (_pchip(self.zs_hw, col, z) for col in self.cols_hw)
            for k in (3,):
                acc = wsum = 0.0
                for j in range(-4, 5):
                    w = 5.0 - abs(j)
                    acc += w * _pchip(self.zs, self.cols[k], z + j * BOB_FRONT_SMOOTH / 4.0)
                    wsum += w
                out[k] = acc / wsum
            if z > BOB_BELL_SURFACE_Z and BOB_FACE_TOP_LEAN != 1.0:
                y0 = self.row(BOB_BELL_SURFACE_Z)[3]
                out[3] = y0 + BOB_FACE_TOP_LEAN * (out[3] - y0)
            self._rows[key] = tuple(out)
        return self._rows[key]

    def section(self, z: float):
        hw, yb = self.row(z)[0], self.row(z)[1]
        yf = self.rig.hair_section(max(z, BOB_CENTRE_Z))[1]
        return hw, yf, yb, self.c

    def contour(self, z: float, phi: float) -> np.ndarray:
        hw, yf, yb, c = self.section(z)
        x, y = _polar(hw, yf, yb, phi, self.ef, self.eb, c)
        return np.array([x, y, z])

    def normal(self, z: float, phi: float) -> np.ndarray:
        """Outward horizontal unit normal of the contour at ``(z, phi)``."""
        a, b = self.contour(z, phi - 0.25), self.contour(z, phi + 0.25)
        n = np.array([float(b[1] - a[1]), -float(b[0] - a[0]), 0.0])
        return n / _norm3(n)

    def corner(self, z: float):
        """``(x, phi)`` of the curtain's outer corner (where the contour meets the front face's plane)."""
        hw, yf, yb, c = self.section(z)
        fy = self.row(z)[3]
        x = self.rig.section_half_width_at(hw, yf, yb, fy, self.ef, self.eb, c)
        return x, math.degrees(math.atan2(x, c - fy))

    def phi_at_x(self, z: float, x: float, back: bool) -> float:
        """Azimuth of the contour point with half-width ``x`` (front half: between the corner and 90 degrees)."""
        lo, hi = (90.0, 180.0) if back else (self.corner(z)[1], 90.0)
        for _ in range(48):
            mid = 0.5 * (lo + hi)
            if (float(self.contour(z, mid)[0]) < x) == back:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)

    def face(self, z: float, x: float) -> np.ndarray:
        return np.array([x, self.row(z)[3], z])

    def edge(self, z: float) -> np.ndarray:
        """The curtain's inner edge (the face-window line) at ``z``, kept BOB_EDGE_GAP outside the skin head's
        section (between the table's rows the interpolated edge would cut in towards the temple)."""
        return _push_off_head(self.rig, self.face(z, self.row(z)[2]), BOB_EDGE_GAP)

    def p_of(self, z: float, P) -> float:
        """Position along the row (her left half): 0 the face-window edge, 1 the outer corner, 2 the back centre."""
        fx, fy = self.row(z)[2], self.row(z)[3]
        xc, pc = self.corner(z)
        if abs(float(P[1]) - fy) < 1e-7 and float(P[0]) <= xc + 1e-9:
            return (float(P[0]) - fx) / (xc - fx)
        phi = math.degrees(math.atan2(float(P[0]), self.c - float(P[1])))
        return 1.0 + (phi - pc) / (180.0 - pc)

    def thickness(self, z: float) -> float:
        return self.row(z)[4]

    def inner_contour(self, z: float, phi: float, t: float) -> np.ndarray:
        """Inner point behind the contour point at ``phi`` (front half: from the outer corner, 0 .. 180 degrees):
        ``t`` inside along the normal, the azimuths from the outer corner to the back centre stretched onto those
        from the inner corner (where the inset meets the inner face) to the back centre, so the inner points do not
        crowd behind the corner (the inset compresses the arc there and folds back past the inner corner)."""
        xc, pc = self.corner(z)
        fy = self.row(z)[3]

        def inset(f):
            return self.contour(z, f) - t * self.normal(z, f)
        a = abs(phi)
        if a < 180.0 - 1e-9:
            lo, hi = pc, 90.0                          # the azimuth whose inset meets the inner face (the mitre)
            if float(inset(lo)[1]) < fy + t:
                for _ in range(40):
                    mid = 0.5 * (lo + hi)
                    if float(inset(mid)[1]) < fy + t:
                        lo = mid
                    else:
                        hi = mid
                ps = hi + BOB_INNER_CORNER_ARC
                a = ps + (max(a, pc) - pc) * (180.0 - ps) / (180.0 - pc)
        return _push_off_head(self.rig, inset(a), BOB_FACE_GAP)

    def inner_face(self, z: float, x: float, t: float) -> np.ndarray:
        """Inner point behind the front-face point at ``x``: ``t`` behind the face, at most at the inner corner (the
        mitre of the face and the contour), pushed off the head."""
        fy = self.row(z)[3]
        xc, pc = self.corner(z)
        n2 = self.normal(z, pc)
        m = (np.array([0.0, -1.0, 0.0]) + n2) / (1.0 - float(n2[1]))
        xi = xc - t * float(m[0])
        xa = xi - BOB_INNER_CORNER_SPAN
        if x > xa:                                      # the face's outer part maps onto the inner face's last span
            x = xa + (x - xa) * (xi - xa) / (xc - xa)
        return _push_off_head(self.rig, np.array([x, fy + t, z]), BOB_FACE_GAP)

    def corner_inner(self, z: float, t: float) -> np.ndarray:
        return self.inner_face(z, 1.0, t)


def _bell_phis(bf: _BobFrame, z: float):
    """The bell's contour column azimuths (her left) at ``z``, corner excluded, back centre excluded: warped evenly
    spaced azimuths (BOB_BELL_WARP), blended by BOB_BELL_TURN towards even turning of the section's tangent."""
    key = ("phis", round(z, 9))
    if key in bf._rows:
        return bf._rows[key]
    pc = bf.corner(z)[1]
    out = []
    for k in range(1, BOB_BELL_CONTOUR + 1):
        s = k / (BOB_BELL_CONTOUR + 1)
        s = s + BOB_BELL_WARP * math.sin(2.0 * math.pi * s) / (2.0 * math.pi)
        out.append(pc + s * (180.0 - pc))
    if BOB_BELL_TURN > 0.0:
        n = BOB_BELL_TURN_SAMPLES
        ph = [pc + (180.0 - pc) * i / n for i in range(n + 1)]
        P = [bf.contour(z, a) for a in ph]
        d = [math.atan2(float(b[1] - a[1]), float(b[0] - a[0])) for a, b in zip(P, P[1:])]
        cum = [0.0]
        for a, b in zip(d, d[1:]):
            cum.append(cum[-1] + abs(math.remainder(b - a, 2.0 * math.pi)))
        cum.append(cum[-1])                              # chord i spans ph[i] .. ph[i + 1]; turning at its middle
        mid = [ph[0]] + [0.5 * (ph[i] + ph[i + 1]) for i in range(1, n - 1)] + [ph[-1]]
        cm = [cum[0]] + [cum[i] for i in range(1, n - 1)] + [cum[-1]]
        even = []
        for k in range(1, BOB_BELL_CONTOUR + 1):
            t = k / (BOB_BELL_CONTOUR + 1) * cm[-1]
            j = 1
            while cm[j] < t:
                j += 1
            u = (t - cm[j - 1]) / (cm[j] - cm[j - 1]) if cm[j] > cm[j - 1] else 0.0
            even.append(mid[j - 1] + u * (mid[j] - mid[j - 1]))
        out = [a + BOB_BELL_TURN * (b - a) for a, b in zip(out, even)]
    bf._rows[key] = out
    return out


def _bell_point(bf: _BobFrame, col, z: float) -> np.ndarray:
    """Outer point of bell column ``col`` = ``(kind, k)`` (her left) at ``z``."""
    kind, k = col
    fx = bf.row(z)[2]
    xc, pc = bf.corner(z)
    if kind == "edge":
        return bf.edge(z)
    if kind == "face":
        return bf.face(z, fx + k / (BOB_BELL_FACE + 1) * (xc - fx))
    if kind == "corner":
        return bf.face(z, xc)
    if kind == "centre":
        return bf.contour(z, 180.0)
    return bf.contour(z, _bell_phis(bf, z)[k - 1])


def _bell_inner(bf: _BobFrame, col, z: float, P, top: bool = False) -> np.ndarray:
    kind = col[0]
    t = bf.thickness(z) * (BOB_TOP_TAPER if top else 1.0)
    drop = np.array([0.0, 0.0, -BOB_TOP_RIM_DROP if top else 0.0])
    if top and kind in ("face", "corner"):              # the top row is inset into the dome: t behind it
        return _push_off_head(bf.rig, P + np.array([0.0, t, 0.0]) + drop, BOB_FACE_GAP)
    if kind == "edge":                                  # (the undercut only where the edge shows)
        u = (0.5 if top else 1.0) * BOB_EDGE_UNDERCUT
        return _push_off_head(bf.rig, P + np.array([u, t, 0.0]) + drop, BOB_FACE_GAP)
    if kind in ("face", "corner"):
        return bf.inner_face(z, float(P[0]), t) + drop
    phi = 180.0 if kind == "centre" else _bell_phis(bf, z)[col[1] - 1]
    if top:
        return _push_off_head(bf.rig, P - t * bf.normal(z, phi), BOB_FACE_GAP) + drop
    return bf.inner_contour(z, phi, t)


class _LockCol:
    """One column of the lock zone (her left): its rows, outer points, inner (or flat) points and its step."""

    def __init__(self, spec, index: int):
        self.kind, self.a, self.z_bot, self.step_side, self.step_z = spec
        self.index = index
        self.zs = []
        self.outer = []
        self.inner = {}               # row index -> point
        self.step_row = None
        self.inner_all = None          # inserted columns: every row's inner point


def _lock_rows(zt: float, zb: float, z_step=None, upper_step: float = 0.0):
    """Row heights from ``zt`` down to ``zb`` (with BOB_LOCK_MID_Z, where the column reaches below it, and ``z_step``
    as exact rows)."""
    def span(z0, z1, ease, step=BOB_LOCK_ROW_STEP):
        n = int(round((z0 - z1) / step))
        n = max(BOB_LOCK_STRIPS[0] if ease else 1, min(BOB_LOCK_STRIPS[1], n))
        out = []
        for k in range(1, n):
            s = k / n
            g = 1.0 - (1.0 - s) ** BOB_LOCK_EASE if ease else s
            out.append(z0 - g * (z0 - z1))
        return out + [z1]
    if zb > BOB_LOCK_MID_Z - BOB_LOCK_ROW_STEP / 2:
        return [zt] + span(zt, zb, True)
    upper = [zt] + span(zt, BOB_LOCK_MID_Z, False, upper_step or BOB_LOCK_ROW_STEP)
    if z_step is None:
        return upper + span(BOB_LOCK_MID_Z, zb, True)
    return upper + span(BOB_LOCK_MID_Z, z_step, False) + span(z_step, zb, False)


def _lock_columns(rig: Rig, bf: _BobFrame):
    """The lock zone's columns (her left, edge -> centre), with their rows and outer / inner points."""
    zt = rig.bob_slit_top_z
    xin, xflat = rig.bob_slit_x
    specs = [s for s in rig.bob_lock_columns]
    cols = []
    for i, s in enumerate(specs):
        if s[0] == "gap":
            cols.append(None)
            continue
        cols.append(_LockCol(s, i))
    # top positions: the face columns evenly between the edge and the front slit, the side lock's columns evenly in
    # azimuth between its edges, the back columns evenly in azimuth between the back slit and the centre
    fx_t = bf.row(zt)[2]
    xc_t, pc_t = bf.corner(zt)
    face = [c for c in cols if c is not None and c.kind in ("edge", "face", "facex")]
    for k, c in enumerate(face):
        x1 = fx_t + BOB_LOCK_FIRST_GAP
        c.x_top = fx_t if k == 0 else x1 + (k - 1) / (len(face) - 2) * (xin - x1)
    side = [c for c in cols if c is not None and c.kind in ("sfront", "side", "sback")]
    phi_sb = bf.phi_at_x(zt, xflat + BOB_SIDE_EDGE, True)
    for k, c in enumerate(side):
        c.phi_top = pc_t + k / (len(side) - 1) * (phi_sb - pc_t)
    back = [c for c in cols if c is not None and c.kind in ("backx", "back", "centre")]
    phi_bx = bf.phi_at_x(zt, xin, True)
    for k, c in enumerate(back):
        c.phi_top = phi_bx + k / (len(back) - 1) * (180.0 - phi_bx)
    # the side and back locks' columns start on the bell's columns (the strip joining them is then quads)
    bell = _bell_phis(bf, zt)
    used = set()
    for c in side[1:-1] + back[1:-1]:
        k = min((i for i in range(len(bell)) if i not in used), key=lambda i: abs(bell[i] - c.phi_top))
        used.add(k)
        c.phi_top = bell[k]
    # the leaf pass's inserted columns (rig.bob_leaf_columns): after + frac is only the column's stable index (its
    # place in the order and its label; the table's columns keep theirs); its points come from `a` (below)
    main = {c.index: c for c in cols if c is not None}
    entries = [(float(i), c) for i, c in enumerate(cols)]
    seen = set()
    for spec in rig.bob_leaf_columns:
        after, frac, kind, a, zb = spec[:5]
        if (not 0.0 < frac < 1.0 or after not in main or after + frac in seen or kind not in ("back", "backc")
                or len(spec) != (6 if kind == "backc" else 5)):
            raise ValueError(f"rig.bob_leaf_columns: ({after}, {frac}, {kind!r}, ...) needs a table column `after`, "
                             f"0 < frac < 1, a position after + frac not used before and kind 'back' (5 fields) or "
                             f"'backc' (6: its top azimuth last)")
        seen.add(after + frac)
        c = _LockCol((kind, a, zb, 0, 0.0), after + frac)
        if kind == "backc":
            c.phi_top = float(spec[5])
        entries.append((after + frac, c))
    cols = [c for _i, c in sorted(entries, key=lambda e: e[0])]
    tip = rig.bob_front_tip
    for c in [c for c in cols if c is not None]:
        z_bot = tip[2] if c.kind == "edge" else c.z_bot
        c.z_bot = z_bot
        c.zs = _lock_rows(zt, z_bot, c.step_z if c.step_side else None,
                          BOB_FRONT_ROW_STEP if c.kind in ("edge", "face", "facex") else 0.0)
        if c.step_side:
            c.step_row = c.zs.index(c.step_z)
        if c.index != int(c.index):                     # (an inserted column's points: the blend below)
            continue
        if c.kind in ("face",):
            f_top = (c.x_top - fx_t) / (xc_t - fx_t)
            xcb = bf.corner(z_bot)[0]
            fxb = bf.row(z_bot)[2]
            f_bot = (c.a - fxb) / (xcb - fxb)
        if c.kind in ("side", "back"):
            if c.kind == "side":
                phi_bot = c.a
            else:
                phi_bot = bf.phi_at_x(z_bot, c.a, True)
        for v, z in enumerate(c.zs):
            s = (zt - z) / (zt - z_bot)
            h = z - z_bot
            curl = BOB_TIP_CURL * _sstep(BOB_TIP_CURL_H, 0.0, h)
            if c.kind == "edge":
                P = bf.edge(z) if v < len(c.zs) - 1 else np.array(tip, dtype=np.float64)
                n_in = np.array([0.0, 1.0, 0.0])
            elif c.kind in ("face", "facex"):
                if c.kind == "facex":
                    curl = 0.0
                if c.kind == "face":
                    f = f_top + s * (f_bot - f_top)
                    fx = bf.row(z)[2]
                    x = fx + f * (bf.corner(z)[0] - fx)
                else:
                    x = _slit_x(xin, xflat, z, zt)
                P = bf.face(z, x)
                n_in = np.array([0.0, 1.0, 0.0])
            elif c.kind in ("sfront", "sback"):
                xo = xflat + BOB_SIDE_EDGE
                if c.kind == "sfront":                 # the corner where it lies outside xo, eased into x = xo
                    xs = _softmax(bf.corner(z)[0], xo, BOB_SIDE_EASE)
                    if v == 0 and bf.corner(z)[0] >= xo:
                        xs = bf.corner(z)[0]              # (the top row's corner: the curtain's outer edge line)
                    P = bf.face(z, xs) if xs <= bf.corner(z)[0] else bf.contour(z, bf.phi_at_x(z, xs, False))
                else:
                    P = bf.contour(z, bf.phi_at_x(z, xo, True))
                n_in = None
                curl = 0.0
            elif c.kind == "backx":
                xs = _slit_x(xin, xflat, z, zt) - (BOB_SLIT_END_FLARE if v == len(c.zs) - 1 else 0.0)
                phi = bf.phi_at_x(z, xs, True)
                P = bf.contour(z, phi)
                n_in = -bf.normal(z, phi)
                curl = 0.0
            else:
                phi = 180.0 if c.kind == "centre" else c.phi_top + s * (phi_bot - c.phi_top)
                P = bf.contour(z, phi)
                n_in = -bf.normal(z, phi)
                if c.kind == "side" or c.index in BOB_LEAF_NO_CURL:   # (the side lock's tip stays outside its
                    curl = 0.0                                         # flat face; the leaf's flank: see the constant)
            if curl > 0.0 and n_in is not None and c.kind != "edge":
                P = P + curl * n_in
            c.outer.append(P)
    # an inserted column lies on the surface between its two neighbours from the table (each point the blend, at the
    # column's fraction u, of the two neighbours' points at the same fraction of their height down to the end of the
    # edge between them: the bell's facets stay as they were), only its lower end moved up or down to its lock's leaf
    # curve (z_bottom) over its last BOB_LEAF_PLAN_H; its inner points blend the neighbours' inner points the same way
    # (a closed tip's inner point is its outer one: the lock thins into the point).  On the contour itself the bell's
    # curl-in under the nape (its section's depth changes 5 mm per mm of height there) swung the edge's plan back and
    # forth with the edge's heights, and the inner surface folded where the lock's thinning starts at different heights
    real = [c for c in cols if c is not None]
    mains = [c for c in real if c.index == int(c.index)]

    def end_row(c, other):
        if c.step_side and (other > c.index) == (c.step_side > 0):
            return c.step_row
        return len(c.zs) - 1

    def along(c, e, s, pts):
        z0, z1 = c.zs[0], c.zs[e]
        ss = [(z0 - c.zs[v]) / (z0 - z1) for v in range(e + 1)]
        j = 0
        while j < e - 1 and s > ss[j + 1]:
            j += 1
        t = (s - ss[j]) / (ss[j + 1] - ss[j])
        return pts[j] + t * (pts[j + 1] - pts[j])

    for c in real:
        if c.index == int(c.index):
            continue
        lo = max((d for d in mains if d.index < c.index), key=lambda d: d.index)
        hi = min((d for d in mains if d.index > c.index), key=lambda d: d.index)
        el, eh = end_row(lo, c.index), end_row(hi, c.index)
        A, B = lo.outer[el], hi.outer[eh]
        u = (c.a - float(A[0])) / (float(B[0]) - float(A[0]))   # (its fraction: its tip's x, `a`, between theirs)
        inner = []
        for d in (lo, hi):                              # (the inner surface: the rows that have an inner point)
            rows = _need_inner(d)
            q = {v: _lock_inner(rig, bf, d, v) for v in rows}
            if d.index in BOB_CLOSED_TIPS:
                q[len(d.zs) - 1] = d.outer[-1]
            inner.append([q[rows[0]]] + [q[min(r for r in rows if r >= v)] if v in q else None
                                         for v in range(1, len(d.zs))])
            for v in range(1, len(d.zs)):                # rows without an inner point: on the line between
                if inner[-1][v] is None:
                    a_ = max(r for r in rows if r < v)
                    b_ = min(r for r in rows if r > v)
                    t_ = (d.zs[a_] - d.zs[v]) / (d.zs[a_] - d.zs[b_])
                    inner[-1][v] = q[a_] + t_ * (q[b_] - q[a_])
        if c.kind == "backc":
            # on the contour (V4 pass): a back column of its own, its azimuth from `phi_top` at the top row to that
            # of x = `a` at its tip, curled in at the edge as the table's back columns are unless it is a leaf's
            # flank (BOB_LEAF_NO_CURL); its rows are a table column's (:func:`_lock_rows`), with the BOB_LOCK_MID_Z
            # row kept for a short lock end, so the zips pair it with its neighbours' rows (a row between two of
            # theirs gave a skewed quad whose split diagonal was a sliver).  Beside the back slit the chord blend
            # (the `back` kind below) lay 1.5-3 mm inside the surface, and the 3/4 views see the strips there
            # edge-on: the facets' azimuths were not monotone across the columns (a back-facing sliver among
            # front-facing neighbours drew a 5 px fold loop).  Placed on the contour where those views graze it,
            # the column is the silhouette itself and the strips on both sides face the cameras by 2.5-3 degrees.
            if c.z_bot <= BOB_LOCK_MID_Z - BOB_LOCK_ROW_STEP / 2:
                c.zs = _lock_rows(zt, c.z_bot)             # (the middle row and the eased rows below it)
            elif c.z_bot < BOB_LOCK_MID_Z - BOB_LEAF_ROW_GAP:
                c.zs = [zt, BOB_LOCK_MID_Z, c.z_bot]       # (a short lock end: the middle row still pairs the zips)
            else:
                c.zs = [zt, c.z_bot]
            inner_rows = {0, len(c.zs) - 1} | ({c.zs.index(BOB_LOCK_MID_Z)} if BOB_LOCK_MID_Z in c.zs else set())
            if c.z_bot < BOB_LOCK_MID_Z - BOB_DEEP_LOCK:
                inner_rows = set(range(len(c.zs)))
            phi_bot = bf.phi_at_x(c.z_bot, c.a, True)
            chord = (1.0 - u) * A + u * B
            dz = np.array([0.0, 0.0, c.z_bot - float(chord[2])])
            outer, inn = [], []
            for v, z in enumerate(c.zs):
                s = (zt - z) / (zt - c.z_bot)
                phi = c.phi_top + s * (phi_bot - c.phi_top)
                curl = 0.0 if c.index in BOB_LEAF_NO_CURL else BOB_TIP_CURL * _sstep(BOB_TIP_CURL_H, 0.0, z - c.z_bot)
                outer.append(bf.contour(z, phi) - curl * bf.normal(z, phi))
                # its inner points blend the neighbours' as a chord column's (below), lowered in proportion to the
                # height so the tip's rim is level (the chord column's shift over its last BOB_LEAF_PLAN_H, 3 mm
                # here, folded the inner strip 18 degrees at the slit end's thick inner tip; an inner point inset
                # from the contour by a blended thickness folded the inner strips 14 degrees beside it)
                Q = (1.0 - u) * along(lo, el, s, inner[0]) + u * along(hi, eh, s, inner[1])
                inn.append(Q + s * dz if v in inner_rows else None)
            # its eased rows (between the middle row and the tip) move along the normal into the plane of the strip
            # towards the slit: the lower neighbour's middle row and the row the zip pairs with this one, and its own
            # middle row.  The two columns drift differently with the depth (fixed x against the azimuth's blend), so
            # that quad was twisted by 0.2 mm, and both the 40 degree presets and three_quarter_back see the strip
            # edge-on: the quad's two triangles straddled one view or the other (a 6 px loop on column 14).
            if BOB_LOCK_MID_Z in c.zs and BOB_LOCK_MID_Z in lo.zs:
                m, ml = c.zs.index(BOB_LOCK_MID_Z), lo.zs.index(BOB_LOCK_MID_Z)
                for v in range(m + 1, len(c.zs) - 1):
                    z = c.zs[v]
                    w = min(range(ml + 1, len(lo.zs)), key=lambda k: abs(lo.zs[k] - z), default=None)
                    if w is None or abs(lo.zs[w] - z) > 0.35 * min(c.zs[v - 1] - z, lo.zs[w - 1] - lo.zs[w]):
                        continue                                   # (not paired: see _zip_rows)
                    N = np.cross(lo.outer[w] - lo.outer[ml], outer[m] - lo.outer[ml])
                    s = (zt - z) / (zt - c.z_bot)
                    n = bf.normal(z, c.phi_top + s * (phi_bot - c.phi_top))
                    outer[v] = outer[v] + float((lo.outer[ml] - outer[v]) @ N) / float(n @ N) * n
            c.outer, c.inner_all = outer, inn
            continue
        chord = (1.0 - u) * A + u * B
        dz = np.array([0.0, 0.0, c.z_bot - float(chord[2])])
        outer, inn = [], []
        for v, z in enumerate(c.zs):
            sv = (zt - z) / (zt - c.z_bot)
            P = (1.0 - u) * along(lo, el, sv, lo.outer) + u * along(hi, eh, sv, hi.outer)
            Q = (1.0 - u) * along(lo, el, sv, inner[0]) + u * along(hi, eh, sv, inner[1])
            w = _sstep(BOB_LEAF_PLAN_H, 0.0, float(P[2] - chord[2]))
            outer.append(P + w * dz)
            inn.append(Q + w * dz)
        c.outer, c.inner_all = outer, inn
        c.zs = [float(P[2]) for P in outer]
        c.z_bot = c.zs[-1]
    # the side lock's two lower corners (leaf pass), in each edge column's (y, z) plane: the edge's line (through its
    # rows at the top and at BOB_LOCK_MID_Z) and the lower edge's line (through the next two columns' bottoms) meet
    # at K.  The front corner (rig.bob_side_corner_radius[0] > 0) is the lock's shoulder: the edge's rows below the
    # middle row are replaced by a circular arc tangent to both lines (BOB_SIDE_CORNER_SEGMENTS segments, closer
    # towards the lower edge by BOB_SIDE_CORNER_EASE, where the 3/4 views foreshorten it), so the front edge curves
    # into the lower edge.  The back corner (radius 0) is the lock's point: the edge runs straight from its middle
    # row to a tip rig.bob_side_back_tip behind and below K, so the lower edge falls into a point at the lock's back
    # (seen from below the lock's back edge and its lower edge meet there over 60 degrees, a designed tip).  On the
    # contour itself both edges slid inwards fast where the bell's section narrows towards its foot, bending in two
    # 30-58 degree corners each.
    if rig.bob_side_corner_radius is not None:
        sl = sorted((c for c in real if c.kind in ("sfront", "side", "sback")), key=lambda c: c.index)
        xo = xflat + BOB_SIDE_EDGE
        for E, nb, nb2, R in ((sl[0], sl[1], sl[2], rig.bob_side_corner_radius[0]),
                              (sl[-1], sl[-2], sl[-3], rig.bob_side_corner_radius[1])):
            M = E.outer[E.zs.index(BOB_LOCK_MID_Z)]
            u1 = np.array([float(E.outer[0][1] - M[1]), float(E.outer[0][2] - M[2])])
            u1 = u1 / math.hypot(*u1)                   # up the edge (its row above the middle row)
            A, B = nb.outer[-1], nb2.outer[-1]
            d2 = np.array([float(A[1] - B[1]), float(A[2] - B[2])])
            # K: where the edge's line meets the lower edge's line
            den = u1[0] * d2[1] - u1[1] * d2[0]
            lam = ((float(A[1]) - float(M[1])) * d2[1] - (float(A[2]) - float(M[2])) * d2[0]) / den
            yv, zk = float(M[1]) + lam * u1[0], float(M[2]) + lam * u1[1]
            u2 = np.array([float(A[1]) - yv, float(A[2]) - zk])
            u2 = u2 / math.hypot(*u2)
            al = 0.5 * math.acos(max(-1.0, min(1.0, float(u1 @ u2))))
            K = np.array([yv, zk])
            if R <= 0.0:                                 # a point: the edge runs straight down to its tip, swept
                sweep, drop = rig.bob_side_back_tip       # back (away from the lock) and dropped below the corner
                yt = yv + sweep * (1.0 if yv > float(A[1]) else -1.0)
                keep = [v for v, z in enumerate(E.zs) if z > BOB_LOCK_MID_Z - 1e-9]
                E.zs = [E.zs[v] for v in keep] + [zk - drop]
                E.outer = [E.outer[v] for v in keep] + [np.array([xo, yt, zk - drop])]
                E.z_bot = zk - drop
                continue
            t = R / math.tan(al)
            bis = (u1 + u2) / math.hypot(*(u1 + u2))
            C = K + R / math.sin(al) * bis
            T1, T2 = K + t * u1, K + t * u2
            a1 = math.atan2(*(T1 - C)[::-1])
            a2 = math.atan2(*(T2 - C)[::-1])
            a2 = a1 + math.remainder(a2 - a1, 2.0 * math.pi)
            arc = [C + R * np.array([math.cos(a1 + (a2 - a1) * _corner_fraction(k)),
                                     math.sin(a1 + (a2 - a1) * _corner_fraction(k))])
                   for k in range(BOB_SIDE_CORNER_SEGMENTS + 1)]
            keep = [v for v, z in enumerate(E.zs) if z > float(T1[1]) + BOB_SIDE_CORNER_GAP]
            E.zs = [E.zs[v] for v in keep] + [float(p[1]) for p in arc]
            E.outer = [E.outer[v] for v in keep] + [np.array([
                _softmax(bf.corner(float(p[1]))[0], xo, BOB_SIDE_EASE) if E.kind == "sfront" else xo,
                float(p[0]), float(p[1])]) for p in arc]
            E.z_bot = E.zs[-1]
            # the next column's middle row (it has none at the arc's heights) comes in onto the line between its rows
            # above and below, in x only: bulging out past the arc, it made the low view's outline run down the arc
            # to its end and back up to it (a 3 px spur).  (The column after it then draws a stub of outline from its
            # middle row to its tip within 0.5 px of the lower edge; tucking that row in too costs H3 / H4 at the
            # front view's widest column.)
            r1, r2, r3 = nb.outer[1], nb.outer[2], nb.outer[3]
            t = (float(r1[2]) - float(r2[2])) / (float(r1[2]) - float(r3[2]))
            nb.outer[2] = np.array([float(r1[0]) + t * (float(r3[0]) - float(r1[0])), float(r2[1]), float(r2[2])])
    return cols


#: The side lock's front corner arc (:func:`_lock_columns`): its segments, their spacing (BOB_SIDE_CORNER_STEPS, the
#: angle steps as fractions of the arc's angle, one per segment, summing to 1; ``None``: steps by the power
#: BOB_SIDE_CORNER_EASE of the arc's fraction, below 1 shrinking towards the lower edge, the leaf pass's spacing),
#: and the edge's rows above the arc keep this far above its top.  The steps (V4 pass) are fitted to the three
#: review views: the 3/4 views see the arc's end along the lower edge foreshortened to 0.57 (a step's turn there
#: reads 1.4 times, its chord 1.2 px only from 9.7 degrees at the 19 mm radius) and its start on the edge nearly
#: full size, the low view the reverse, so the steps are small at the start (the low view's turn at the arc's
#: start), largest in the arc's upper half and 9-10 degrees over its last three.
BOB_SIDE_CORNER_SEGMENTS = 7
BOB_SIDE_CORNER_EASE = 0.8
BOB_SIDE_CORNER_STEPS = (0.10, 0.2262, 0.2353, 0.139, 0.0995, 0.0963, 0.1037)
BOB_SIDE_CORNER_GAP = 0.003


def _corner_fraction(k: int) -> float:
    """Fraction of the corner arc's angle at its point ``k`` of BOB_SIDE_CORNER_SEGMENTS: the sum of the first ``k``
    steps of BOB_SIDE_CORNER_STEPS, or the point's fraction of the segments to the power BOB_SIDE_CORNER_EASE."""
    if BOB_SIDE_CORNER_STEPS is not None:
        if len(BOB_SIDE_CORNER_STEPS) != BOB_SIDE_CORNER_SEGMENTS or abs(sum(BOB_SIDE_CORNER_STEPS) - 1.0) > 1e-9:
            raise ValueError("BOB_SIDE_CORNER_STEPS: one fraction per segment, summing to 1")
        return float(sum(BOB_SIDE_CORNER_STEPS[:k]))
    return (k / BOB_SIDE_CORNER_SEGMENTS) ** BOB_SIDE_CORNER_EASE


#: An inserted column's lower end moves onto its lock's leaf curve over this height (:func:`_lock_columns`).
BOB_LEAF_PLAN_H = 0.012
#: An inserted column on the contour (kind ``backc``) whose tip lies less than this below BOB_LOCK_MID_Z has no row
#: there (:func:`_lock_columns`).
BOB_LEAF_ROW_GAP = 0.002
#: Lock columns (indices) whose lower end does not curl in (BOB_TIP_CURL): the back lock's flank beside the slit,
#: where the leaf's lower edge rises steeply to the slit's end and the tips are not hanging lock ends.  A curled tip
#: 3-9 mm below the row above tilted the facet between them by 6 degrees, and the 3/4 views, which look up at the
#: head, saw that lip facing them: the outline ran along the lip's upper boundary across three columns in sub-pixel
#: zigzags beside the side lock's back edge.  Without the curl the silhouette runs down column 13.66 to its tip and
#: on to column 14's (V4 pass).
BOB_LEAF_NO_CURL = (13.66, 14, 14.51)


#: The back slit's lock end: its lower corner comes this far in from the slit's inner side (x), so the slit's wall
#: bends into the next lock's rising lower edge in two halves (the low view saw one 32 degree corner there).
BOB_SLIT_END_FLARE = 0.0012


def _slit_x(xin: float, xflat: float, z: float, zt: float) -> float:
    """x of a slit's inner side at ``z``: ``xin``, closing in to BOB_SLIT_TOP_GAP from the side lock's flat face over
    the slit's top BOB_SLIT_V (a narrow V, not a flat-topped notch)."""
    k = _sstep(zt - BOB_SLIT_V, zt, z)
    return xin + k * (xflat - BOB_SLIT_TOP_GAP - xin)


def _inner_at(bf: _BobFrame, P, z: float, phi: float, t: float) -> np.ndarray:
    """Inner point of a back lock's outer point ``P`` (on the contour at ``phi``, perhaps curled in): the stretched
    inner contour point (:meth:`_BobFrame.inner_contour`) moved by the curl too."""
    Q = bf.inner_contour(z, phi, t)
    return _push_off_head(bf.rig, Q + (P - bf.contour(z, phi)), BOB_FACE_GAP)


#: The back locks already thin by this fraction of the bob's thickness from the lock zone's top row down to
#: BOB_LOCK_MID_Z (beside the back slit, whose lock end stops above BOB_LOCK_MID_Z, the inner surface folded where
#: the next lock starts to thin, in the low views).
BOB_LOCK_PRE_THIN = 0.2


def _lock_thickness(bf: _BobFrame, c: _LockCol, v: int) -> float:
    """The bob's thickness down to BOB_LOCK_MID_Z (one smooth inner surface under the bell), thinning below it to
    BOB_TIP_THIN at the lock's lower edge."""
    z = c.zs[v]
    zt = c.zs[0]
    pre = BOB_LOCK_PRE_THIN if c.kind in ("back", "backx", "centre") else 0.0
    top = 1.0 - pre * (zt - min(z, zt)) / (zt - BOB_LOCK_MID_Z)       # (thinning from the top row to MID)
    if z >= BOB_LOCK_MID_Z - 1e-9 or c.z_bot > BOB_LOCK_MID_Z:
        return bf.thickness(z) * top
    s = (z - c.z_bot) / (BOB_LOCK_MID_Z - c.z_bot)
    m = 1.0 - pre
    return bf.thickness(z) * (BOB_TIP_THIN + (m - BOB_TIP_THIN) * s)


def _lock_inner(rig: Rig, bf: _BobFrame, c: _LockCol, v: int) -> np.ndarray:
    """Inner point of lock column ``c`` at row ``v`` (the side lock: its flat face's point)."""
    P = c.outer[v]
    z = c.zs[v]
    if c.kind in ("sfront", "sback", "side"):
        return np.array([rig.bob_slit_x[1], float(P[1]), z])
    t = _lock_thickness(bf, c, v)
    if c.kind == "edge":
        return _push_off_head(rig, P + np.array([BOB_EDGE_UNDERCUT, t, 0.0]), BOB_FACE_GAP)
    if c.kind in ("face", "facex"):
        return bf.inner_face(z, float(P[0]), t)
    phi = math.degrees(math.atan2(float(P[0]), bf.c - float(P[1])))
    if c.kind in ("back", "backx", "centre"):
        return _inner_at(bf, P, z, phi, t)
    return _push_off_head(rig, P - t * bf.normal(z, phi), BOB_FACE_GAP)


def _need_inner(c):
    """The rows of lock column ``c`` that have a point on the inner surface."""
    rows = {0, len(c.zs) - 1}
    if c.z_bot < BOB_LOCK_MID_Z - BOB_DEEP_LOCK:    # the long nape locks: every row (the back curls in)
        rows |= set(range(len(c.zs)))
    if c.kind in ("edge", "face", "facex"):        # the curtain's front: every row under the bell
        rows |= {v for v, z in enumerate(c.zs) if z >= BOB_LOCK_MID_Z - 1e-9}
    if BOB_LOCK_MID_Z in c.zs:
        rows.add(c.zs.index(BOB_LOCK_MID_Z))
    if c.inner_all is not None:                    # an inserted column: the rows given an inner point
        rows |= {v for v, q in enumerate(c.inner_all) if q is not None}
    if c.kind in ("sfront", "sback"):              # the side lock's corner arcs: every row on its flat face too
        # (up to the arc's top, which keeps BOB_SIDE_CORNER_GAP below the edge's row above it: at the 19 mm radius
        # its first point sits above BOB_LOCK_MID_Z, and without an inner point there the edge strip's face from the
        # top row to the arc's second point twisted into a tilted facet, a notch on the lock's front edge)
        rows |= {v for v, z in enumerate(c.zs) if z < BOB_LOCK_MID_Z + BOB_SIDE_CORNER_GAP}
    if c.step_side:
        rows.add(c.step_row)
    return sorted(rows)


def _zip_rows(A, B, ea: int, eb: int):
    """Faces between two columns (lists of ``(vertex id, z)``, top -> down) down to their row ``ea`` / ``eb``: quads
    where both advance together, triangles where one does."""
    faces = []
    i = j = 0
    while i < ea or j < eb:
        if i < ea and j < eb:
            za, zb = A[i + 1][1], B[j + 1][1]
            tol = 0.35 * min(A[i][1] - za, B[j][1] - zb)
            if abs(za - zb) <= tol:
                faces.append([A[i][0], B[j][0], B[j + 1][0], A[i + 1][0]])
                i += 1
                j += 1
                continue
            adv_a = za > zb
        else:
            adv_a = i < ea
        if adv_a:
            faces.append([A[i][0], B[j][0], A[i + 1][0]])
            i += 1
        else:
            faces.append([A[i][0], B[j][0], B[j + 1][0]])
            j += 1
    return faces


def _zip_param(A, B):
    """Faces between two rows (lists of ``(vertex id, p)``, p ascending; the ends are paired): a quad where both rows
    have a point at the same ``p``, triangles elsewhere, each triangle the one whose new diagonal spans less of
    ``p`` (V4 pass: advancing the row whose next point came first put a fan triangle's apex outside its base's span
    wherever two of the lock zone's columns fell between two of the bell's; the skewed facet stood 2-4 degrees
    steeper than the bell, which made the M4 dihedrals beside the back slit and the 23.6 degree one at the back
    centre).  The ceiling's rows pass y as ``p``: the same rule."""
    faces = []
    i = j = 0
    while i < len(A) - 1 or j < len(B) - 1:
        if i < len(A) - 1 and j < len(B) - 1 and abs(A[i + 1][1] - B[j + 1][1]) < 1e-7:
            faces.append([A[i][0], A[i + 1][0], B[j + 1][0], B[j][0]])
            i += 1
            j += 1
        elif j == len(B) - 1 or (i < len(A) - 1 and
                                 abs(A[i + 1][1] - B[j][1]) <= abs(A[i][1] - B[j + 1][1])):
            faces.append([A[i][0], A[i + 1][0], B[j][0]])
            i += 1
        else:
            faces.append([A[i][0], B[j + 1][0], B[j][0]])
            j += 1
    return faces


def _orient(faces):
    """``faces`` with consistent windings over each connected 2-manifold piece (breadth first)."""
    edge_faces = {}
    for k, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(k)
    out = [list(f) for f in faces]
    done = [False] * len(faces)
    for start in range(len(faces)):
        if done[start]:
            continue
        done[start] = True
        queue = [start]
        while queue:
            k = queue.pop()
            f = out[k]
            for a, b in zip(f, f[1:] + f[:1]):
                for n in edge_faces[(min(a, b), max(a, b))]:
                    if done[n]:
                        continue
                    g = out[n]
                    same = any(x == a and y == b for x, y in zip(g, g[1:] + g[:1]))
                    if same:
                        out[n] = [g[0]] + g[1:][::-1]
                    done[n] = True
                    queue.append(n)
    return out


def _bob(rig: Rig):
    """H3: one closed shell (cut into three by :func:`_split_bob`, ``info["pieces"]``).  The bell (above
    ``rig.bob_slit_top_z``): rows :data:`BOB_BELL_ROWS` on columns round the curtains and the back (each curtain's
    inner edge, its front face, the outer corner, :data:`BOB_BELL_CONTOUR` contour columns per side, the back
    centre); below it the lock zone, ``rig.bob_lock_columns``: the curtains' front locks, a slit, the side lock (its
    inner face flat at ``rig.bob_slit_x[1]``), a slit, the back locks to the nape; layered: each tip at its lock's
    inner end, steps between the locks.  Between the bell's last row and the lock zone's top row a strip of triangles
    joins their columns; under the bell's side, behind the side lock, a flat ceiling closes the shell.  Returns
    ``(mesh, info)`` (the lining needs the side lock's columns)."""
    bf = _BobFrame(rig)
    zt = rig.bob_slit_top_z
    V = []
    keys = {}

    def vid(key, P):
        if key not in keys:
            keys[key] = len(V)
            V.append(np.asarray(P, dtype=np.float64))
        return keys[key]

    def mirror(P, side):
        Q = np.array(P, dtype=np.float64)
        Q[0] *= side
        return Q

    faces, kinds = [], []

    def add(fs, kind):
        for f in fs:
            g = [x for k, x in enumerate(f) if x != f[k - 1]]     # (a closed tip's two rows are one vertex)
            if len(g) >= 3:
                faces.append(g)
                kinds.append(kind)

    # ---- the bell -------------------------------------------------------------------------------------------
    half = [("edge", 0)] + [("face", k) for k in range(1, BOB_BELL_FACE + 1)] + [("corner", 0)]
    half += [("contour", k) for k in range(1, BOB_BELL_CONTOUR + 1)]
    bcols = [(c, -1) for c in half] + [(("centre", 0), 1)] + [(c, 1) for c in half[::-1]]
    cxy = np.array([0.0, bf.c])
    # the top row: every column shrunk towards the section's centre by one ratio, so its farthest point lies
    # BOB_TOP_INSET inside the dome (one ratio: no twisted quads where the dome's inset would vary)
    ratio = 1.0
    for col in half + [("centre", 0)]:
        P = _bell_point(bf, col, BOB_BELL_ROWS[0])
        theta = math.atan2(float(P[0]), float(cxy[1] - P[1]))
        D = _dome_along(rig, BOB_BELL_ROWS[0], theta, cxy)
        rd = math.hypot(float(D[0]), float(D[1] - cxy[1])) - BOB_TOP_INSET
        ratio = min(ratio, rd / math.hypot(float(P[0]), float(P[1] - cxy[1])))
    bell_O, bell_I = [], []
    for bi, (col, side) in enumerate(bcols):
        colO, colI = [], []
        for v, z in enumerate(BOB_BELL_ROWS):
            P = _bell_point(bf, col, z)
            if z > BOB_BELL_SURFACE_Z + 1e-9:            # the top rows tuck inside the dome
                f = ((z - BOB_BELL_SURFACE_Z) / (BOB_BELL_ROWS[0] - BOB_BELL_SURFACE_Z)) ** BOB_BELL_INSET_POWER
                k = 1.0 - (1.0 - ratio) * f
                P = P.copy()
                P[0] = k * float(P[0])
                P[1] = cxy[1] + k * float(P[1] - cxy[1])
            key = ("BC",) if col[0] == "centre" else ("B", side, col)
            colO.append((vid(("O",) + key + (v,), mirror(P, side)), z))
            if col[0] == "edge" or BOB_BELL_ROWS[v] in BOB_BELL_INNER_ROWS:
                colI.append((vid(("I",) + key + (v,), mirror(_bell_inner(bf, col, z, P, v == 0), side)), z))
        bell_O.append(colO)
        bell_I.append(colI)
    for b in range(len(bcols) - 1):
        hb, sb_ = (b, -1) if b < len(half) else (2 * len(half) - 1 - b, 1)
        add(_zip_rows(bell_O[b], bell_O[b + 1], len(bell_O[b]) - 1, len(bell_O[b + 1]) - 1),
            ("out", "bell", b, hb, sb_))
        add(_zip_rows(bell_I[b], bell_I[b + 1], len(bell_I[b]) - 1, len(bell_I[b + 1]) - 1), ("in",))
        front = {bcols[b][0][0], bcols[b + 1][0][0]} <= {"edge", "face", "corner"}
        add([[bell_O[b][0][0], bell_O[b + 1][0][0], bell_I[b + 1][0][0], bell_I[b][0][0]]], ("rim", "top", front))

    # ---- the lock zone ----------------------------------------------------------------------------------------
    lcols = _lock_columns(rig, bf)
    LO, LI = {}, {}                                      # (side, index) -> [(id, z)] / {row: id}
    # The front slit's V closes on one vertex: the side lock's front strip's flat corner on the top row is the face
    # lock's slit-side top point (BOB_SLIT_TOP_GAP past the flat face).  As two points the face lock's lay 0.2 mm
    # outside the flat corner, so the lock zone's top row ran back on itself there: the joining strip's triangle
    # over the two (bell, face lock's top, flat corner) and the ceiling's (face lock's top, its inner point, flat
    # corner) were flipped slivers (180 degree folds against their neighbours) that the 3/4 and low views' outlines
    # traced as a spur at the bell's corner (V4 review, F2).
    fx_col = [c for c in lcols if c is not None and c.kind == "facex"][0]

    for side in (-1, 1):
        for c in lcols:
            if c is None:
                continue
            sk = 0 if c.kind == "centre" else side
            if (sk, c.index) in LO:
                continue
            LO[(sk, c.index)] = [(vid(("LO", sk, c.index, v), mirror(P, side)), c.zs[v])
                                 for v, P in enumerate(c.outer)]
            last = len(c.zs) - 1

            def inner_id(v, c=c, sk=sk, last=last):
                if v == last and c.index in BOB_CLOSED_TIPS:          # (a closed tip: its outer point)
                    return LO[(sk, c.index)][v][0]
                if v == 0 and c.kind == "sfront":                      # (the front slit's V: see above)
                    return LO[(sk, fx_col.index)][0][0]
                return vid(("LI", sk, c.index, v), mirror(c.inner_all[v] if c.inner_all is not None
                                                          else _lock_inner(rig, bf, c, v), side))
            LI[(sk, c.index)] = {v: inner_id(v) for v in _need_inner(c)}
    order = [(-1, c) for c in lcols[:-1]] + [(0, lcols[-1])] + [(1, c) for c in lcols[-2::-1]]
    region = {}
    for c in lcols:
        if c is None:
            continue
        region[c.index] = ("front" if c.kind in ("edge", "face", "facex") else
                           "side" if c.kind in ("sfront", "side", "sback") else "back")

    def _wall(kk, c, v0):
        """Faces between a lock column's outer rows and its inner rows from row ``v0`` down (a rim)."""
        O = [(LO[kk][v][0], c.zs[v]) for v in range(v0, len(c.zs))]
        Ii = [(LI[kk][v], c.zs[v]) for v in sorted(LI[kk]) if v >= v0]
        return _zip_rows(O, Ii, len(O) - 1, len(Ii) - 1)

    def ends(ca, cb):
        """Row indices where the interval between columns ``ca`` and ``cb`` ends on each (a step ends the lock on
        its side of the column at the step row)."""
        e = []
        for c, other in ((ca, cb), (cb, ca)):
            k = len(c.zs) - 1
            if c.step_side and (other.index > c.index) == (c.step_side > 0):
                k = c.step_row
            e.append(k)
        return e[0], e[1]

    lock_bottom_edges = []
    for k in range(len(order) - 1):
        (sa, ca), (sb, cb) = order[k], order[k + 1]
        if ca is None or cb is None:
            continue
        ka, kb = (0 if ca.kind == "centre" else sa, ca.index), (0 if cb.kind == "centre" else sb, cb.index)
        ea, eb = ends(ca, cb)
        reg = region[ca.index] if region[ca.index] == region[cb.index] else "back"
        add(_zip_rows(LO[ka], LO[kb], ea, eb), ("out", reg, min(ca.index, cb.index), 1 if sa + sb > 0 else -1))
        Ia = [(LI[ka][v], ca.zs[v]) for v in sorted(LI[ka]) if v <= ea]
        Ib = [(LI[kb][v], cb.zs[v]) for v in sorted(LI[kb]) if v <= eb]
        add(_zip_rows(Ia, Ib, len(Ia) - 1, len(Ib) - 1), ("in", "flat") if reg == "side" else ("in",))
        add([[LO[ka][ea][0], LO[kb][eb][0], LI[kb][eb], LI[ka][ea]]], ("rim", "low"))
        lock_bottom_edges.append((ka, kb, ea, eb))
        # step walls
        for c, kk, e in ((ca, ka, ea), (cb, kb, eb)):
            if c.step_side and e == c.step_row:
                add(_wall(kk, c, c.step_row), ("rim", "step"))
    # walls along the face-window edges, the slits' sides and the side lock's ends
    for (s, c) in order:
        if c is None or c.kind not in ("edge", "facex", "backx", "sfront", "sback"):
            continue
        add(_wall((s, c.index), c, 0),
            ("rim", {"edge": "wall", "sfront": "strip", "sback": "strip"}.get(c.kind, "slit")))
    # the face-window edge rims of the bell and of the joining strip
    for side, b in ((-1, 0), (1, len(bcols) - 1)):
        col = bell_O[b]
        coli = bell_I[b]
        for v in range(len(col) - 1):
            add([[col[v][0], col[v + 1][0], coli[v + 1][0], coli[v][0]]], ("rim", "wall"))
        e = (side, lcols[0].index)
        add([[col[-1][0], LO[e][0][0], LI[e][0], coli[-1][0]]], ("rim", "wall"))

    # ---- the joining strip (bell row -> lock zone top row) and the ceiling --------------------------------------
    bell_anchor = {}
    cut_bell = {}                                        # side -> (bell column, its index in the joining strip)
    for side in (-1, 1):
        bidx = list(range(len(half))) if side < 0 else list(range(len(bcols) - 1, len(bcols) - 1 - len(half), -1))
        bidx = bidx + [len(half)]                        # + the centre
        bpts = [(bell_O[b][-1][0], bf.p_of(BOB_BELL_ROWS[-1], mirror(V[bell_O[b][-1][0]], side))) for b in bidx]
        bpts_i = [(bell_I[b][-1][0], bf.p_of(BOB_BELL_ROWS[-1], mirror(V[bell_O[b][-1][0]], side))) for b in bidx]
        tops, tops_i = [], []
        for c in lcols:
            if c is None:
                continue
            sk = 0 if c.kind == "centre" else side
            P = mirror(V[LO[(sk, c.index)][0][0]], side)
            p = bf.p_of(zt, P)
            if c.kind == "sfront" and LI[(sk, c.index)][0] != tops[-1][0]:
                Fp = mirror(V[LI[(sk, c.index)][0]], side)    # the side lock's front strip: its flat corner (unless
                tops.append((LI[(sk, c.index)][0], bf.p_of(zt, Fp), c))   # it is the face lock's last top point,
            tops.append((LO[(sk, c.index)][0][0], p, c))                  # the front slit's V), then its edge

            if region[c.index] != "side":
                tops_i.append((LI[(sk, c.index)][0], p, c))
        # the inner surface's points between the slits
        bk = [c for c in lcols if c is not None and c.kind == "backx"][0]
        fk = [c for c in lcols if c is not None and c.kind == "facex"][0]
        side_in = []
        for j, phi in enumerate(BOB_SIDE_INNER_PHI):
            P = bf.inner_contour(zt, phi, bf.thickness(zt))
            side_in.append((vid(("IS", side, j), mirror(P, side)), 1.0 + (phi - bf.corner(zt)[1]) /
                            (180.0 - bf.corner(zt)[1])))
        pos = [k for k, t in enumerate(tops_i) if t[2] is fk][0]
        tops_i = tops_i[:pos + 1] + [(i, p, None) for i, p in side_in] + tops_i[pos + 1:]
        # outer strip: the front segment (edge .. corner) and the contour segment (corner .. centre), anchored at the
        # strand columns
        corner_b = len(half) - BOB_BELL_CONTOUR - 1
        sf = [k for k, t in enumerate(tops) if t[2] is not None and t[2].kind == "sfront" and
              t[0] == LO[(side, t[2].index)][0][0]][0]
        anchors = [(0, 0), (corner_b, sf)]
        for si in BOB_STRANDS:
            j = [k for k, t in enumerate(tops) if t[2] is not None and t[2].index == si][0]
            pj = tops[j][1]
            bj = min(range(corner_b + 1, len(bpts) - 1), key=lambda b: abs(bpts[b][1] - pj))
            anchors.append((bj, j))
            if si == BOB_SPLIT_STRAND:
                cut_bell[side] = (bidx[bj], bj)
        anchors.append((len(bpts) - 1, len(tops) - 1))
        anchors.sort()
        bell_anchor[side] = [b for b, _t in anchors[1:]]
        for (b0, t0), (b1, t1) in zip(anchors, anchors[1:]):
            seg_kind = ("out", "zipf" if b1 <= corner_b else "zipc", b0, side)
            add(_zip_param([(i, p) for i, p in bpts[b0:b1 + 1]], [(i, p) for i, p, _c in tops[t0:t1 + 1]]),
                seg_kind)
        ti = [(i, p) for i, p, _c in tops_i]
        if BOB_SPLIT_STRAND is None:
            add(_zip_param(bpts_i, ti), ("in",))
        else:                                           # the inner strip too has an edge on the cut's column
            bj = cut_bell[side][1]
            tj = [k for k, t in enumerate(tops_i) if t[2] is not None and t[2].index == BOB_SPLIT_STRAND][0]
            add(_zip_param(bpts_i[:bj + 1], ti[:tj + 1]), ("in",))
            add(_zip_param(bpts_i[bj:], ti[tj:]), ("in",))
        # ceiling: from the front slit's inner side round the side lock's flat face to the back slit's inner side,
        # back along the inner surface
        right = [LO[(side, fk.index)][0][0]]
        for c in lcols:
            if c is not None and region[c.index] == "side" and LI[(side, c.index)][0] != right[-1]:
                right.append(LI[(side, c.index)][0])          # (the front strip's flat corner is the V's vertex)
            if c is not None and c.kind == "sback":       # the back strip's top edge closes on the ceiling
                right.append(LO[(side, c.index)][0][0])
        right.append(LO[(side, bk.index)][0][0])
        left = [LI[(side, fk.index)][0]] + [i for i, _p in side_in] + [LI[(side, bk.index)][0]]
        R = [(i, float(V[i][1])) for i in right]
        L = [(i, float(V[i][1])) for i in left]
        add(_zip_param(R, L), ("in", "ceiling"))

    # ---- orient, groups ------------------------------------------------------------------------------------------
    faces = _orient(faces)
    mesh = _head.oriented(mk.Mesh(np.array(V), faces, 1))
    faces = mesh.faces
    fn, _ = mk.face_normals(mesh)
    L = rig_sun()
    lit = (fn[:, 0] * L[0] + fn[:, 1] * L[1] + fn[:, 2] * L[2]) > 0.0
    G_FRONT = {-1: 1, 1: 2}
    G_IN = 3
    # contour strips: split at the strand columns (bell column / lock column anchors), one strip across the back
    # centre
    lock_anchor = [c.index for c in lcols if c is not None and c.kind == "sfront"] + list(BOB_STRANDS)
    ns = len(BOB_STRANDS)

    def strip(k, side):
        return 4 + (k if side < 0 else 2 * ns - k)

    def strip_of_bell(hb, side):
        return strip(sum(1 for a in bell_anchor[side][:-1] if hb >= a) - 1 if hb >= bell_anchor[side][0] else 0,
                     side)

    def strip_of_lock(i, side):
        return strip(max(0, sum(1 for a in lock_anchor if i >= a) - 1), side)

    groups = []
    for f, kind in zip(faces, kinds):
        if kind[0] == "in":
            groups.append(G_IN)
        elif kind[0] != "out":
            groups.append(None)
        elif kind[1] in ("zipf", "front"):
            groups.append(G_FRONT[kind[-1]])
        elif kind[1] == "bell":
            ka, kb = bcols[kind[2]][0][0], bcols[kind[2] + 1][0][0]
            if {ka, kb} <= {"edge", "face", "corner"}:
                groups.append(G_FRONT[kind[4]])
            else:
                groups.append(strip_of_bell(kind[3], kind[4]))
        elif kind[1] == "zipc":
            groups.append(strip_of_bell(kind[2], kind[3]))
        else:
            groups.append(strip_of_lock(kind[2], kind[3]))
    edge_faces = {}
    for k, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(k)
    g_rim = 5 + 2 * ns
    for k, f in enumerate(faces):
        if groups[k] is not None:
            continue
        outer_n, inner_n = [], []

        for a, b in zip(f, f[1:] + f[:1]):
            for n in edge_faces[(min(a, b), max(a, b))]:
                if n != k and kinds[n][0] == "out":
                    outer_n.append(n)
                elif n != k and kinds[n][0] == "in":
                    inner_n.append(n)
        diff_o = [n for n in outer_n if lit[n] != lit[k]]
        diff_i = [n for n in inner_n if lit[n] != lit[k]]
        if diff_o:
            groups[k] = groups[diff_o[0]]
        elif diff_i:
            groups[k] = G_IN
        elif outer_n:
            groups[k] = groups[outer_n[0]]
        else:
            groups[k] = g_rim
    mesh = mk.inscribed_fan(mk.Mesh(mesh.vertices, faces, groups))
    fk = list(kinds)
    mesh, fk = _split_tracked(mesh, TWIST_SPLIT_DEG, [g != G_IN for g in mesh.groups], fk)
    mesh, fk = _split_tracked(mesh, INNER_TWIST_SPLIT_DEG, [g == G_IN for g in mesh.groups], fk)
    mesh = _settle_rim_groups(mesh, [kd[0] not in ("in", "out") for kd in fk], L)
    info = {"frame": bf, "lock_cols": lcols, "LO": LO, "LI": LI, "V": np.array(V)}
    if BOB_SPLIT_STRAND is not None:
        chains = []
        c = [c for c in lcols if c is not None and c.index == BOB_SPLIT_STRAND][0]
        last = c.step_row if c.step_side else len(c.zs) - 1   # the strand line ends at the lock's notch
        for side in (-1, 1):
            b, kk = cut_bell[side][0], (side, c.index)
            outer = list(bell_O[b]) + [(LO[kk][v][0], c.zs[v]) for v in range(last + 1)]
            inner = list(bell_I[b]) + [(LI[kk][v], c.zs[v]) for v in sorted(LI[kk]) if v <= last]
            chains.append((outer, inner))
        # the shell whose lock ends at the notch is tucked into its neighbour (c.step_side > 0: the interval towards
        # the back centre ends at the step row)
        info["pieces"] = _split_bob(mesh, chains, ("back",) if c.step_side >= 0 else ("l", "r"))
    return mesh, info


def _split_bob(mesh, chains, tucked):
    """The bob cut along ``chains`` (per cut: its outer and its inner column, ``[(vertex id, z)]`` top -> down, from
    the top rim to the lock's notch) into closed shells: ``{"l": mesh, "back": mesh, "r": mesh}``.  The faces are
    split along the two columns and the rim edges at their ends; each shell is closed by a cap, a strip zipped
    between the outer and the inner column in the rim faces' group (both cut edges are group boundaries: the strand
    line draws as before, and the shaded previews' group-smoothed normals never mix a cap into the outer or the inner
    surface).  Each shell has its own copies of the two columns' vertices; in the shells named in ``tucked`` they are
    moved :data:`BOB_CUT_TUCK` past the cut and as far into the hair (:func:`_cut_tuck`), so no vertex or face is
    shared and every cap lies inside the hair."""
    faces = [list(f) for f in mesh.faces]
    V = mesh.vertices

    def key(a, b):
        return (min(a, b), max(a, b))

    cut, caps = set(), []
    for outer, inner in chains:
        for col in (outer, inner):
            for (a, _za), (b, _zb) in zip(col, col[1:]):
                cut.add(key(a, b))
        cut.add(key(outer[0][0], inner[0][0]))
        cut.add(key(outer[-1][0], inner[-1][0]))
        caps.append(_orient(_zip_rows(outer, inner, len(outer) - 1, len(inner) - 1)))
    edge_faces = {}
    for k, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edge_faces.setdefault(key(a, b), []).append(k)
    comp = [-1] * len(faces)
    n = 0
    for s0 in range(len(faces)):
        if comp[s0] >= 0:
            continue
        comp[s0] = n
        stack = [s0]
        while stack:
            k = stack.pop()
            f = faces[k]
            for a, b in zip(f, f[1:] + f[:1]):
                e = key(a, b)
                if e in cut:
                    continue
                for m in edge_faces[e]:
                    if comp[m] < 0:
                        comp[m] = n
                        stack.append(m)
        n += 1
    if n != 3:
        raise mk.MeshError(f"hair.bob: the cuts give {n} pieces, not 3")
    xs = [float(np.mean([V[i][0] for k in range(len(faces)) if comp[k] == q for i in faces[k]])) for q in range(3)]
    order = sorted(range(3), key=lambda q: xs[q])     # her right (x < 0), the back, her left
    groups = list(mesh.groups)
    rim_group = 5 + 2 * len(BOB_STRANDS)              # the rim faces' group (as in _bob)
    out = {}
    for name, q in zip(("r", "back", "l"), order):
        fs = [k for k in range(len(faces)) if comp[k] == q]
        pf = [faces[k] for k in fs]
        pg = [groups[k] for k in fs]
        directed = {(a, b) for f in pf for a, b in zip(f, f[1:] + f[:1])}
        moved = {}
        for (outer, inner), cap in zip(chains, caps):
            a, b = outer[0][0], outer[1][0]
            if (a, b) not in directed and (b, a) not in directed:
                continue                              # this cut is not on this piece
            if name in tucked:
                for col in (outer, inner):
                    moved.update(_cut_tuck(V, pf, [i for i, _z in col], BOB_CUT_TUCK))
            cap_dir = {(x, y) for f in cap for x, y in zip(f, f[1:] + f[:1])}
            same = ((a, b) in directed and (a, b) in cap_dir) or ((b, a) in directed and (b, a) in cap_dir)
            cf = [f[::-1] for f in cap] if same else [list(f) for f in cap]
            pf += cf
            pg += [rim_group] * len(cf)
        used = sorted({i for f in pf for i in f})
        remap = {i: j for j, i in enumerate(used)}
        PV = np.array([moved.get(i, V[i]) for i in used], dtype=np.float64)
        out[name] = mk.Mesh(PV, [[remap[i] for i in f] for f in pf], pg)
    return out


def _cut_tuck(V, faces, col, d: float) -> dict:
    """New positions ``{vertex id: point}`` of a cut column ``col`` (vertex ids, top -> down) for the piece made of
    ``faces`` (outward, without its caps): each vertex moved ``d`` out of the piece past the cut, square to the column
    in the plane of the piece's faces on the column's edges at that vertex (the outer or the inner surface), and ``d``
    against those faces' outward normal (into the hair).  Plain float arithmetic (no BLAS call): the same bytes on
    every build."""
    def key(a, b):
        return (min(a, b), max(a, b))

    P = [tuple(float(c) for c in V[i]) for i in col]
    out = {}
    for j, i in enumerate(col):
        lo, hi = max(j - 1, 0), min(j + 1, len(col) - 1)
        t = [P[hi][k] - P[lo][k] for k in range(3)]
        on = {key(col[m], col[m + 1]) for m in (j - 1, j) if 0 <= m < len(col) - 1}
        n = [0.0, 0.0, 0.0]
        c = [0.0, 0.0, 0.0]
        count = 0
        for f in faces:
            if not any(key(x, y) in on for x, y in zip(f, f[1:] + f[:1])):
                continue
            Q = [tuple(float(v) for v in V[x]) for x in f]
            for (x0, y0, z0), (x1, y1, z1) in zip(Q, Q[1:] + Q[:1]):     # Newell's normal (twice the area)
                n[0] += (y0 - y1) * (z0 + z1)
                n[1] += (z0 - z1) * (x0 + x1)
                n[2] += (x0 - x1) * (y0 + y1)
            for k in range(3):
                c[k] += sum(q[k] for q in Q) / len(Q)
            count += 1
        if count == 0:
            raise mk.MeshError(f"hair.bob: cut vertex {i} has no face on its column")
        u = [n[1] * t[2] - n[2] * t[1], n[2] * t[0] - n[0] * t[2], n[0] * t[1] - n[1] * t[0]]
        lu = math.sqrt(u[0] * u[0] + u[1] * u[1] + u[2] * u[2])
        inward = sum((c[k] / count - P[j][k]) * u[k] for k in range(3))     # u's side of the piece's faces
        s = -d / lu if inward > 0.0 else d / lu
        ln = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
        out[i] = np.array([P[j][k] + s * u[k] - d / ln * n[k] for k in range(3)], dtype=np.float64)
    return out


def _split_tracked(mesh, max_deg, only, flags):
    """``mk.split_twisted(mesh, max_deg, only)`` and ``flags`` (one per face) carried to the split faces."""
    out = mk.split_twisted(mesh, max_deg, only=only)
    new_flags, j = [], 0
    for f, fl in zip(mesh.faces, flags):
        n = 2 if len(f) == 4 and len(out.faces[j]) == 3 else 1
        new_flags += [fl] * n
        j += n
    return out, new_flags


#: Passes of the rim-group descent (it settles in two or three).
RIM_GROUP_PASSES = 8
#: A rim face avoids a group whose faces meet it at a fold over these angles (degrees; over 60 it is a crease the
#: overlay leaves out), each fold weighted against one ray vertex by RIM_FOLD_WEIGHT.
RIM_FOLD_DEG = (12.0, 25.0)
RIM_FOLD_WEIGHT = (0.0, 1.2)


def _settle_rim_groups(mesh, rim, L):
    """The rim faces (``rim``: the walls and rims between the outer and the inner surface) regrouped so the light
    silhouette crosses as few group boundaries as it can: the lit-rule above picks each rim face's group from its
    own neighbours, but where the terminator runs along a run of rim faces two of them can still take different
    groups across a lit/unlit edge, and every such edge is two of castplane's rays (``MESH_RAYS_CAPPED`` at 64).
    A coordinate descent in face order: each rim face takes the neighbour group with the lowest cost, the feature
    silhouette vertices on its own corners plus :data:`RIM_FOLD_WEIGHT` per fold over :data:`RIM_FOLD_DEG` it makes
    inside one group (a fold of up to 60 degrees inside a group is a facet the shading shows), keeping its group on
    a tie; deterministic (fixed order, sorted candidates)."""
    fn, _ = mk.face_normals(mesh)
    lit = (fn[:, 0] * L[0] + fn[:, 1] * L[1] + fn[:, 2] * L[2]) > 1e-9
    faces = [list(f) for f in mesh.faces]
    groups = list(mesh.groups)
    edge_faces = {}
    for k, f in enumerate(faces):
        for a, b in zip(f, f[1:] + f[:1]):
            edge_faces.setdefault((min(a, b), max(a, b)), []).append(k)
    vert_edges = {}
    for e in edge_faces:
        vert_edges.setdefault(e[0], []).append(e)
        vert_edges.setdefault(e[1], []).append(e)

    def feature(e):
        fs = edge_faces[e]
        return len(fs) == 2 and lit[fs[0]] != lit[fs[1]] and groups[fs[0]] != groups[fs[1]]

    nbrs = []
    for k, f in enumerate(faces):
        nb = []
        for a, b in zip(f, f[1:] + f[:1]):
            for n in edge_faces[(min(a, b), max(a, b))]:
                if n != k:
                    nb.append((n, math.degrees(math.acos(max(-1.0, min(1.0, float(fn[k] @ fn[n])))))))
        nbrs.append(nb)

    def cost(k):
        # feature silhouette vertices and folds inside one group (a fold up to 60 degrees inside a group is a facet
        # that shading must hide: an overlay dihedral), weighted
        big = sum(1 for n, d in nbrs[k] if groups[n] == groups[k] and RIM_FOLD_DEG[1] < d <= 60.0)
        small = sum(1 for n, d in nbrs[k] if groups[n] == groups[k] and RIM_FOLD_DEG[0] < d <= RIM_FOLD_DEG[1])
        rays = sum(1 for v in faces[k] if any(feature(e) for e in vert_edges[v]))
        return rays + RIM_FOLD_WEIGHT[1] * big + RIM_FOLD_WEIGHT[0] * small

    for _ in range(RIM_GROUP_PASSES):
        changed = False
        for k in range(len(faces)):
            if not rim[k]:
                continue
            g0 = groups[k]
            best, best_cost = g0, cost(k)
            for c in sorted({groups[n] for n, _d in nbrs[k]}):
                if c == g0:
                    continue
                groups[k] = c
                cc = cost(k)
                if cc < best_cost:
                    best, best_cost = c, cc
            groups[k] = best
            changed = changed or best != g0
        if not changed:
            break
    return mk.Mesh(mesh.vertices, faces, groups)



#: The top row is this fraction of the bob's thickness (it tapers into the dome).
BOB_TOP_TAPER = 0.4
#: The bob's inner surface splits its quads twisted by more than this.
INNER_TWIST_SPLIT_DEG = 15.0


def rig_sun():
    from .rig import SUN_TOWARDS
    s = np.asarray(SUN_TOWARDS, dtype=np.float64)
    return s / _norm3(s)


# ---------------------------------------------------------------------------------------------------------------------
# H4 lavender under-layer (object hair_under, material hair_inner)
# ---------------------------------------------------------------------------------------------------------------------
#: The lining: a thin strip on the inner face of the curtain's long front lock (towards the jaw, where the sheet shows
#: the lavender under the side hair), along its lower edge at LINING_STATIONS (lock column positions: 1.0 = column 1,
#: 1.5 = halfway to column 2, ...), from LINING_LOW above the edge up to ``bob_under_depth`` above it (distances up the
#: inner face), its visible face LINING_OFF off the inner face (towards the head), its back LINING_BACK inside the lock;
#: its ends taper to LINING_END_TAPER (no blunt cap drawn as a tick).  LINING_OFF is 1.7 mm (finishing pass, merge:
#: at 1.5 mm the strip's front faces came within 0.445 mm of the lock's curled lower edge on the final model, under
#: rule 5's 0.5 mm; 1.7 mm gives 0.63 mm).
LINING_STATIONS = (1.0, 1.5, 2.0)
LINING_END_TAPER = 0.12
LINING_LOW = 0.002
LINING_OFF = 0.0017
LINING_BACK = 0.0015
#: The under-locks are one flat lock per side, its root edge UNDER_LOCK_ROOT_IN towards the axis and
#: UNDER_LOCK_ROOT_BACK behind its lower edge, at ``under_lock_root_z`` inside the head's lower back,
#: UNDER_LOCK_THICKNESS thick (its flat facing the front).
UNDER_LOCK_ROOT_IN = 0.002
UNDER_LOCK_ROOT_BACK = 0.012
UNDER_LOCK_THICKNESS = 0.002


def _lining(rig: Rig, info, side: int) -> mk.Mesh:
    """The lining (H4) on one side: a thin closed strip on the inner face of the curtain's front lock, along its lower
    edge (one station per LINING_STATIONS, between the lock columns' bottoms)."""
    lcols, LO, LI, V = info["lock_cols"], info["LO"], info["LI"], info["V"]

    def at(c, key):
        last = len(c.zs) - 1
        if key == "o":
            return V[LO[(side, c.index)][last][0]]
        return V[LI[(side, c.index)][last if key == "i" else 0]]

    rings = []
    for k, st in enumerate(LINING_STATIONS):
        i = int(math.floor(st))
        f = st - i
        ca, cb = (c for c in lcols if c is not None and c.index in (i, i + 1))
        bot_o = (1.0 - f) * at(ca, "o") + f * at(cb, "o")
        bot_i = (1.0 - f) * at(ca, "i") + f * at(cb, "i")
        top_i = (1.0 - f) * at(ca, "t") + f * at(cb, "t")
        up = _unit3(top_i - bot_i)
        lo = bot_i + LINING_LOW * up
        hi = bot_i + rig.bob_under_depth * up
        n = _unit3(bot_i - bot_o)                    # towards the head
        n = _unit3(n - up * float(n @ up))
        ring = np.array([lo + LINING_OFF * n, hi + LINING_OFF * n, hi - LINING_BACK * n, lo - LINING_BACK * n])
        if k in (0, len(LINING_STATIONS) - 1):
            c0 = ring.mean(axis=0)
            ring = c0 + LINING_END_TAPER * (ring - c0)
        rings.append(ring)
    mesh = _head.oriented(mk.loft(rings, "flat", "flat", groups=1, cap_groups=(1, 1)))
    return mk.split_twisted(mk.inscribed_fan(mesh), TWIST_SPLIT_DEG)


def _under_locks(rig: Rig, side: int):
    """The under-locks (H4) on one side: one flat lock UNDER_LOCK_THICKNESS thick whose top edge is buried in the
    head's lower back (``under_lock_root_z``) and whose lower edge is a V down to one point midway between
    ``under_lock_tips``, its sides UNDER_LOCK_NOTCH above the point at the two tips' x: the sheet's lavender spikes
    between the jaw and the braids read as one tapered lock (one silhouette, no inner line; review r3-T6: three teeth
    drew a W under the chin, and the finishing pass's review: two teeth still drew a zigzag from knee height)."""
    T = np.array([rig.at(tip, side) for tip in rig.under_lock_tips])
    a = T[-1] - T[0]
    a[2] = 0.0
    a = _unit3(a)                                      # across the lock (horizontal)
    mid = 0.5 * (T[0] + T[-1])
    notch = np.array([0.0, 0.0, UNDER_LOCK_NOTCH])
    lower = np.array([T[0] + notch, mid, T[-1] + notch])
    # the root line: each lower point moved UNDER_LOCK_ROOT_BACK back (and UNDER_LOCK_ROOT_IN towards the axis) up to
    # under_lock_root_z, inside the head
    upper = lower + np.array([-side * UNDER_LOCK_ROOT_IN, UNDER_LOCK_ROOT_BACK, 0.0])
    upper[:, 2] = rig.under_lock_root_z
    flare = 0.5 * (rig.under_lock_width - UNDER_LOCK_TIP_W)   # the sides widen to under_lock_width's flare
    upper[0] -= flare * a
    upper[-1] += flare * a
    F = np.stack([upper, lower], axis=1)               # (U, 2, 3)
    nrm = np.cross(a, upper[0] - lower[0])
    nrm = _unit3(nrm if float(nrm[1]) > 0.0 else -nrm)   # the thickness axis, towards the back
    lock = _head.slab(F, F + UNDER_LOCK_THICKNESS * nrm, groups=(1, 1, 1, 1, 1, 1))
    return [Part(f"hair.under_locks_{_side_name(side)}", "hair_inner", lock, "hair", obj="hair_under")]


#: The under-lock's sides widen by half of (``under_lock_width`` - UNDER_LOCK_TIP_W) from its lower edge to its root;
#: its sides end UNDER_LOCK_NOTCH above its point.
UNDER_LOCK_TIP_W = 0.003
UNDER_LOCK_NOTCH = 0.006


# ---------------------------------------------------------------------------------------------------------------------
# H5 ear tufts (object tufts, objects[0])
# ---------------------------------------------------------------------------------------------------------------------
#: Levels of the tuft's rings (0 = the notch / junction on the dome's silhouette, 1 = the tip; the first, negative one
#: is the base inside the dome; 0.38 / 0.57 / 0.77 are the arc-length fractions of ``tuft_front_outline``'s corners,
#: so the outer silhouette stays on it) and the stations across its cup side (0 = the inner rim, 1 = the outer rim;
#: the decal's stations among them, so it keeps its relief over the facets).
TUFT_LEVELS = (-0.18, 0.0, 0.38, 0.57, 0.77, 0.92)
TUFT_CUP_U = (0.0, 0.5, 0.75, 0.9, 1.0)
TUFT_BACK_U = (1.0, 0.6, 0.3, 0.0)
#: Over the top TUFT_TAPER of its height (levels) the plate's thickness and its cup sag shrink linearly to
#: TUFT_TAPER_MIN of their full value at the tip, so the point is a point (not a 7 mm roof).
TUFT_TAPER = 0.35
TUFT_TAPER_MIN = 0.15
#: The inner-face decal covers the cup between these stations (its outer half), from / to these levels; each station
#: stands TUFT_FACE_PROUD times ``tuft_inner_relief`` off the cup: the outer one sinks under the cup near the rim,
#: so only the inner border (the inner-ear line) and the top draw, not a second line along the outer contour.
TUFT_FACE_U = (0.5, 0.9)
TUFT_FACE_PROUD = (1.0, -0.5)
TUFT_FACE_LEVELS = (0.04, 0.38, 0.57, 0.77, 0.92)


def _tuft_side_y(rig: Rig, z: float, back: bool) -> float:
    """y of the tuft's side-view outline at ``z``: the front edge (``back=False``) or the back edge."""
    pts = list(rig.tuft_side_outline)
    top = max(range(len(pts)), key=lambda i: pts[i][1])
    part = pts[top:] if back else pts[:top + 1]
    part = sorted(part, key=lambda p: p[1])
    zs = [p[1] for p in part]
    ys = [p[0] for p in part]
    return float(np.interp(z, zs, ys))


def _tuft_front_points(rig: Rig, v: float):
    """``(inner (x, z), outer (x, z))`` of the tuft's front-view outline at level ``v``: the inner edge (notch -> tip,
    straight) and the convex outer contour (junction -> tip, by arc length), extended below the dome's silhouette for
    ``v < 0``."""
    tip = np.array(rig.tuft_front_outline[0])
    notch = np.array(rig.tuft_inner_notch)
    contour = np.array(rig.tuft_front_outline[::-1])           # junction -> tip
    inner = notch + v * (tip - notch)
    if v >= 0.0:
        outer = mk.polyline_at(contour, [v])[0]
    else:
        d = contour[0] - contour[1]
        outer = contour[0] + (-v) * _norm2(contour[-1] - contour[0]) * d / _norm2(d)
    return inner, outer


def _norm2(v) -> float:
    return math.hypot(float(v[0]), float(v[1]))


def _tuft_section(rig: Rig, v: float, side: int, cup_u=TUFT_CUP_U):
    """``(cup points, back points (4, 3), cup normal)`` of the tuft's section at level ``v`` (her left, then
    mirrored): a curved plate ``tuft_thickness`` thick from the inner-front end ``A`` to the outer-back end ``B``, its
    front (cup) face concave by ``tuft_cup_depth``, both tapering to the tip (:data:`TUFT_TAPER`).  The two ends are
    inset so that the back face starts on ``A`` (the inner edge, notch -> tip, stays straight) and the cup ends on
    ``B`` (the outer contour stays on ``tuft_front_outline``).  The cup points are taken at the stations ``cup_u``."""
    i2, o2 = _tuft_front_points(rig, v)
    A = np.array([i2[0], _tuft_side_y(rig, float(i2[1]), False), i2[1]])
    B = np.array([o2[0], _tuft_side_y(rig, float(o2[1]), True), o2[1]])
    d = B - A
    n = np.array([d[1], -d[0], 0.0])
    n = n / _norm3(n)                                  # horizontal, towards the front and out
    f = max(TUFT_TAPER_MIN, min(1.0, (1.0 - v) / TUFT_TAPER))
    t = 0.5 * rig.tuft_thickness * f
    sag = rig.tuft_cup_depth * f

    def mid(u):
        return A + u * d - sag * 4.0 * u * (1.0 - u) * n + t * (1.0 - 2.0 * u) * n

    cup = np.array([mid(u) + t * n for u in cup_u])
    back = np.array([mid(u) - t * n for u in TUFT_BACK_U])
    if side < 0:
        cup[:, 0] *= -1.0
        back[:, 0] *= -1.0
        n = n * np.array([-1.0, 1.0, 1.0])
    return cup, back, n


def _tuft(rig: Rig, side: int):
    """One ear tuft (a closed curved plate on the dome's upper-outer slope, its base sunk ``tuft_base_sink`` into the
    dome, its point the top-inner corner) and its lighter inner-face decal."""
    rings = []
    for v in TUFT_LEVELS:
        cup, back, n = _tuft_section(rig, v, side)
        ring = np.concatenate([cup, back])
        if v < 0.0:                                    # the base sinks into the dome (towards the head's centre)
            c = ring.mean(axis=0)
            dirn = _unit3(np.array([c[0], c[1] - rig.head_center[1], c[2] - rig.head_center[2]]))
            ring = ring - rig.tuft_base_sink * dirn
        rings.append(ring)
    tip = rig.at(rig.tuft_tip, side)
    base = rings[0].mean(axis=0) - rig.tuft_base_sink * _unit3(rings[0].mean(axis=0) - rig.head_center)
    # one smooth group: the outline draws as silhouettes only (the decal's inner border is the one inner line)
    shell = mk.loft(rings, ("pole", base), ("pole", tip), groups=1, cap_groups=(1, None))
    shell = mk.split_twisted(mk.inscribed_fan(shell), TWIST_SPLIT_DEG)
    # the inner face: a decal slab on the cup between TUFT_FACE_U, tuft_inner_relief proud
    F, B = [], []
    for v in TUFT_FACE_LEVELS:
        cup, _back, n = _tuft_section(rig, v, side, TUFT_FACE_U)
        row_f, row_b = [], []
        for p, k in zip(cup, TUFT_FACE_PROUD):
            row_f.append(p + k * rig.tuft_inner_relief * n)
            row_b.append(p - (TUFT_FACE_DEPTH + max(0.0, -k) * rig.tuft_inner_relief) * n)
        F.append(row_f)
        B.append(row_b)
    F = np.array(F).transpose(1, 0, 2)                 # (U = stations across, V = levels)
    B = np.array(B).transpose(1, 0, 2)
    mid = B.mean(axis=0, keepdims=True)
    B = mid + TUFT_FACE_SHRINK * (B - mid)             # undercut walls (the outline is a silhouette)
    # the inner wall and the top are their own group: the inner border is a feature line from every view (the cup faces
    # 55-73 degrees outward, so from the front the wall is not undercut enough to make it a silhouette)
    face = _head.slab(F, B, groups=(1, 1, 1, 2, 2, 1))
    return shell, face


#: The inner-face decal's back sinks this far into the cup; its back outline is this fraction of its front (undercut).
TUFT_FACE_DEPTH = 0.0006
TUFT_FACE_SHRINK = 0.6


# ---------------------------------------------------------------------------------------------------------------------
# H6 braids (objects braid_l / braid_r)
# ---------------------------------------------------------------------------------------------------------------------
#: Lobe centres along the braid path (fractions root -> tie; the first is under the hair), the lobe's half length
#: along its own axis (it leans braid_lobe_tilt_deg off the path) and its half width (across its own axis), its
#: tessellation.  A slender lobe 24 x 11 mm (the sheet's 20-24 x 9-11 mm), the lobes 13.3 mm apart along the 70 mm
#: path, so consecutive ones overlap.
BRAID_LOBE_AT = (0.12, 0.31, 0.50, 0.69, 0.88)
BRAID_LOBE_HALF_LENGTH = 0.012
BRAID_LOBE_HALF_WIDTH = 0.0055
BRAID_LOBE_NU, BRAID_LOBE_NV = 6, 4
BRAID_LOBE_NV_HIDDEN = 3          # the top lobe, under the hair
#: The lobe's profile exponent along its axis (``meshkit.superellipsoid``'s ``e_vert``; < 2 gives pointed ends) and
#: its pitch about its width axis: the upper end tucks back under the lobe above and the lower end comes forward over
#: the next one, so each lobe comes out from under its neighbour and the lobe edges cross the braid as a chevron
#: (review r4-L1: unpitched round lobes buried each other's edges and read as a string of beads).
BRAID_LOBE_POINT = 1.6
BRAID_LOBE_PITCH_DEG = 22.0
BRAID_TIE_N = 6
#: End-tuft locks: they start this far inside the tie (along the path) and run through stations BRAID_TUFT_STATIONS of
#: the way to their tip, sagging BRAID_TUFT_CURL (at the middle, a parabola) below the chord in its vertical plane: a
#: crescent brush whose ends curl up (the sheet's front view; review r4-L2: a 7 mm sag on 14 mm blades read as a claw;
#: review r5-L1: a 10 mm sag on 10 × 6 mm blades read as a claw from the front and as V-shaped hooks in profile).
BRAID_TUFT_START = 0.002
BRAID_TUFT_STATIONS = (0.0, 1.0 / 3.0, 2.0 / 3.0, 1.0)
BRAID_TUFT_CURL = 0.004


def _braid_frame(rig: Rig, side: int, u: float):
    """``(point, tangent (down the braid), width axis (outward, across), thickness axis)`` at ``u`` along the path."""
    p = rig.braid_point(side, u)
    a = rig.braid_point(side, max(0.0, u - 0.02))
    b = rig.braid_point(side, min(1.0, u + 0.02))
    t = _unit3(b - a)
    w = np.array([float(side), 0.0, 0.0])
    w = _unit3(w - t * float(w[0] * t[0] + w[1] * t[1] + w[2] * t[2]))
    n = np.cross(t, w)
    return p, t, w, n


def _braid(rig: Rig, side: int):
    parts = []
    s = _side_name(side)
    pitch = math.radians(BRAID_LOBE_PITCH_DEG)
    for k, u in enumerate(BRAID_LOBE_AT):
        p, t, w, n = _braid_frame(rig, side, u)
        tilt = math.radians(rig.braid_lobe_tilt_deg) * (1.0 if k % 2 == 0 else -1.0)
        ax = math.cos(tilt) * t + math.sin(tilt) * w   # the lobe's long axis (leaning across the braid) ...
        bx = -math.sin(tilt) * t + math.cos(tilt) * w  # ... and its width axis
        back = n if n[1] > 0.0 else -n                 # the thickness axis pointing back (+y)
        ax = math.cos(pitch) * ax - math.sin(pitch) * back   # ... pitched: lower end forward, upper end back
        nx = _unit3(np.cross(ax, bx))                  # right-handed frame (bx, nx, ax): the shell stays outward
        nv = BRAID_LOBE_NV if k else BRAID_LOBE_NV_HIDDEN
        lobe = mk.superellipsoid((0.0, 0.0, 0.0), (BRAID_LOBE_HALF_WIDTH, 0.5 * rig.braid_thickness,
                                                   BRAID_LOBE_HALF_LENGTH), BRAID_LOBE_NU, nv, 2.0, BRAID_LOBE_POINT)
        lobe = lobe.transform(np.stack([bx, nx, ax], axis=1), p)
        parts.append(Part(f"hair.braid_lobe{k + 1}_{s}", "hair", lobe, "braids", obj=f"braid_{s}"))
    p, t, w, n = _braid_frame(rig, side, 1.0)
    r = rig.braid_tie_radius
    L = rig.braid_tie_length
    rings = [mk.place_ring(mk.profile_ellipse(BRAID_TIE_N) * r, p + dz * t, w, n) for dz in (-0.5 * L, 0.5 * L)]
    parts.append(Part(f"hair.braid_tie_{s}", "hair", mk.loft(rings, "flat", "flat", cap_groups=(1, 1)), "braids",
                      obj=f"braid_{s}"))
    for k, tip in enumerate(rig.braid_tuft_tips):
        tp = rig.at(tip, side)
        start = p + BRAID_TUFT_START * t
        chord = tp - start
        up = np.array([0.0, 0.0, 1.0]) - _unit3(chord) * float(_unit3(chord)[2])
        up = _unit3(up)                                # perpendicular to the chord, upward
        path = np.array([start + u * chord - 4.0 * u * (1.0 - u) * BRAID_TUFT_CURL * up for u in BRAID_TUFT_STATIONS])
        lock = mk.sweep(path, width=lambda x: rig.braid_tuft_width * (1.0 - 0.7 * x),
                        thickness=lambda x: rig.braid_tuft_thickness * (1.0 - 0.6 * x),
                        profile=mk.profile_lens(4, 0.8), normals=np.tile(n, (len(path), 1)), start="flat",
                        end="pointed", groups=1, cap_groups=(1, 1))
        parts.append(Part(f"hair.braid_tuft{k + 1}_{s}", "hair", lock, "braids", obj=f"braid_{s}"))
    return parts


# ---------------------------------------------------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------------------------------------------------

def build(rig: Rig):
    """The parts of :data:`REGIONS`."""
    parts = [Part("hair.dome", "hair", _dome(rig), "hair")]
    parts += _fringe(rig)
    bob, info = _bob(rig)
    if "pieces" in info:
        for name, obj in (("l", "bob_l"), ("back", "bob"), ("r", "bob_r")):
            parts.append(Part(f"hair.bob_{name}", "hair", info["pieces"][name], "hair", obj=obj))
    else:
        parts.append(Part("hair.bob", "hair", bob, "hair", obj="bob"))
    for side in SIDES:
        parts.append(Part(f"hair.lining_{_side_name(side)}", "hair_inner", _lining(rig, info, side), "hair",
                          obj="hair_under"))
    for side in SIDES:
        parts += _under_locks(rig, side)
    for side in SIDES:
        shell, face = _tuft(rig, side)
        parts.append(Part(f"hair.tuft_{_side_name(side)}", "hair", shell, "tufts"))
        parts.append(Part(f"hair.tuft_face_{_side_name(side)}", "tuft_inner", face, "tufts"))
    for side in SIDES:
        parts += _braid(rig, side)
    return parts

"""Acceptance profile of the Miki model: the named requirements ``checks.py`` evaluates (milestone 1).

A requirement is a number a review round can pass or fail on.  Every one records its kind, the parts it reads,
how it selects faces, its metric, the required value(s) with tolerance and units, the reason it exists (the
builder constant or rig field it comes from, and the review round where one is cited) and whether it is
``required`` (it gates ``python -m tools.miki_model.checks``) or ``advisory`` (printed only).

Kinds:

* **join** -- part ``buried`` is sunk into part ``host`` on purpose (burial is the construction idiom of this
  model: the neck ends inside the torso and the head, the bib inside the neck, the leg inside the sock, the
  sidelock roots inside the dome, every decal's back under the skin ...).  The intersection curve of the two
  parts must lie inside ``zone`` (dilated by eps), and the buried ``rim`` must stay under the host's surface by
  at least ``depth`` (when the builder states one).  A pair with a join is never judged by the generic rule.
* **clear** -- faces of ``a`` must clear faces of ``b`` by ``[min, max]``.
* **proportion** -- a lofted part must match the profile table it is lofted from (gated); free-form parts get a
  width table only (``DIAGNOSTIC_WIDTHS``, never gated: no written rule exists yet).
* **pose** -- a pose that must be tested (milestone 2; a stub here, so the report can say it was not tested).
* **generic** -- every part pair without a join: any triangle-triangle crossing, coincident patch or
  containment is a FAIL (``checks.py`` adds one generic requirement per pair; they are not listed here).

Every number is read from ``rig.py`` or a builder module constant (imported, never copied).  SPEC.md is not the
reference: where the code departed from it, the code wins (``SPEC.md`` line 5).  A requirement may be calibrated
to the model as it stands only if its reason says "accepted in round N"; none in this version is.  Selector
parameters (``FACING_COS``, ``CAP_SIDES``) are part of the profile, not of the model.

Maxima: a clearance has a finite maximum only where a builder places a part a stated distance off its host (the
colour stripes' border stations, ``rig.stripe_float``).  The face decals' fronts have no stated maximum (their
``relief`` varies per decal and column and is then pushed out by the clearance pass), so no maximum is enforced
for them yet; the straps and the collar have a minimum only.

Faces are selected geometrically (``Select``), since ``Part`` has no named face groups: outward / inward
relative to a centre, a facing direction, z / y / x ranges, polygon size (the flat caps of lofts and sweeps are
single polygons) and, where a builder documents them, its part-local smooth-group ids.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from . import body, hair, head, limbs
from .rig import Rig

__all__ = ["PROFILE_VERSION", "PROFILE_NAME", "Select", "Zone", "Join", "Clear", "Proportion", "Pose",
           "DIAGNOSTIC_WIDTHS", "profile", "FACING_COS", "INNER_FACE_COS", "CAP_SIDES", "DECAL_FRONT_COS",
           "CLEAR_METRICS", "BAND_CHORD_SAMPLES"]

#: Bump when a requirement is added, removed or changed (the report records it).
PROFILE_VERSION = "2"
PROFILE_NAME = "miki"

#: A face "faces" a direction when its unit normal's dot product with it is at least this (60 degrees).
FACING_COS = 0.5
#: An undercut slab's inner (back) face against its walls: the walls of the headband (45 deg) and the ridge stay
#: below this (25 deg), the inner face is above it.
INNER_FACE_COS = 0.9
#: A face decal's front faces are within 45 degrees of the skin normal under them; the undercut walls lean
#: further (head._decal: 50 - 85 degrees) and the back faces point into the skin.
DECAL_FRONT_COS = 0.7
#: The flat caps of the lofts and sweeps (legs, socks, hands, thumbs, sidelocks) are single polygons with at least
#: this many vertices; every other face of those parts is a triangle or a quad.
CAP_SIDES = 5
#: The clearance metrics (see :class:`Clear`).
CLEAR_METRICS = ("euclid", "along", "band_chords", "band_stations")
#: Samples per border chord in ``band_chords`` (``meshkit.lift_band_borders``' default, which the strap uses).
BAND_CHORD_SAMPLES = 7

SIDES = ((1, "l"), (-1, "r"))
UP = (0.0, 0.0, 1.0)
DOWN = (0.0, 0.0, -1.0)
TOWARD_VIEWER = (0.0, -1.0, 0.0)          # the figure faces -Y: a face decal's "up"
BACKWARD = (0.0, 1.0, 0.0)
INF = float("inf")


@dataclass(frozen=True)
class Select:
    """Faces of one part; every criterion given is AND-ed, ``invert`` complements the result.

    ``groups``: part-local smooth-group ids; ``facing``: ``(direction, min_cos)``; ``outward_from`` /
    ``inward_from``: the normal points away from / toward this point (seen from the face centroid), by more than
    ``radial_cos`` (the cosine to the direction from / to the point); ``z`` / ``y``
    / ``x``: ``(lo, hi)`` on the face centroid; ``min_sides``: polygons with at least this many vertices;
    ``host_cos``: ``(part, min_cos)`` -- the normal is within ``acos(min_cos)`` of the normal of that part's
    nearest face (a decal's front against the skin); ``vz``: (rims only) keep the selected faces' vertices with
    ``lo <= z <= hi``; ``only``: (rims only) drop the vertices that an unselected face also uses."""

    groups: tuple | None = None
    facing: tuple | None = None
    outward_from: tuple | None = None
    inward_from: tuple | None = None
    radial_cos: float = 0.0
    z: tuple | None = None
    y: tuple | None = None
    x: tuple | None = None
    min_sides: int | None = None
    host_cos: tuple | None = None
    vz: tuple | None = None
    only: bool = False
    farthest: int | None = None
    invert: bool = False
    note: str = ""


ALL = Select(note="every face")


@dataclass(frozen=True)
class Zone:
    """Where a join's intersection curve may lie; a point is inside when every given test holds after dilating
    by eps.  ``z`` / ``y``: ranges; ``faces``: ``("a" | "b", Select)`` -- within eps of those faces of the buried
    (``a``) or host (``b``) part; ``inside``: inside (or within eps of) the named part; ``near``: ``(part,
    distance)`` -- within that distance of the named part's surface; ``any_of``: a tuple of
    zones, one of which must hold.  ``Zone()`` with nothing set is unconstrained (recorded as such)."""

    z: tuple | None = None
    y: tuple | None = None
    faces: tuple | None = None
    inside: str | None = None
    near: tuple | None = None
    any_of: tuple | None = None
    note: str = ""

    @property
    def unconstrained(self) -> bool:
        return all(v is None for v in (self.z, self.y, self.faces, self.inside, self.near, self.any_of))


@dataclass(frozen=True)
class Join:
    """``buried`` sunk into ``host``.  ``rim``: the buried vertices that must stay under the host's surface
    (``None``: no rim test); ``depth``: by at least this (m; ``0.0``: merely inside).  ``depth_metric``
    ``"euclid"`` measures the exact distance to the host mesh (the builder's inset is against its analytic
    surface, so the host's local facet bulge is allowed off it); ``"along"`` measures along ``direction`` below
    the front-most of the host and ``stack`` surfaces (the face decals' own metric, against the faceted mesh).
    ``also``: further parts a rim vertex may be buried in instead of the host (the deepest one counts).
    ``contact``: ``"expected"`` -- the builder makes the parts meet, so a join whose parts never meet (no
    intersection, no rim test) is INDETERMINATE (not exercised); ``"optional"`` -- the join only says where an
    intersection may lie (e.g. every decal against every layer below it), so no contact is a PASS that is reported
    as not exercised and not counted as a PASS.  ``zone_status``: ``""``; ``"exempt"`` -- the builder states no
    zone, the curve is not tested (only containment and the rim); ``"approximate"`` -- the zone is fitted by the
    profile, not stated by the builder, so a leak may be a zone-fitting artefact (it still FAILs)."""

    name: str
    buried: str
    host: str
    zone: Zone
    rim: Select | None
    depth: float
    constant: str
    reason: str
    level: str = "required"
    depth_metric: str = "euclid"
    direction: tuple | None = None
    stack: tuple = ()
    also: tuple = ()
    contact: str = "expected"
    zone_status: str = ""
    kind: str = "join"


@dataclass(frozen=True)
class Clear:
    """Faces ``faces_a`` of ``a`` clear faces ``faces_b`` of ``b`` by ``min`` .. ``max`` (m).  ``metric``:

    * ``"euclid"`` (the default, and the metric of a plain minimum gap): the exact triangle-triangle minimum
      distance between the selected faces; it measures no maximum (a finite ``max`` is INDETERMINATE);
    * ``"along"``: the height along ``direction`` above ``faces_b`` of the vertices, edge midpoints and fan
      diagonal midpoints of ``faces_a`` -- the face decals' own rule (``head._clear``: the front's grid samples, y
      against the surface under them); no maximum;
    * ``"band_chords"``: ``a`` is a ``meshkit.ridge_band``; ``samples`` points on every chord of its two borders,
      height along the interpolated station normals above ``faces_b`` -- exactly ``meshkit.lift_band_borders``;
    * ``"band_stations"``: ``a`` is a ridge band; the exact distance from its border stations (vertices) to
      ``faces_b``, min and max.  ``max_bulge``: each station's maximum grows by the host's facet bulge at its foot
      point (the builder offsets the stations off the analytic surface, which the faceted mesh lies inside).

    Whatever the metric, a crossing, contact or coincident patch between ``faces_a`` and ``faces_b`` is a gap of 0.
    ``need_overlap``: without any measurement (no sample over ``b``) the requirement is INDETERMINATE; otherwise it
    passes as "no overlap", reported as not exercised (never counted as a PASS)."""

    name: str
    a: str
    b: str
    faces_a: Select
    faces_b: Select
    min: float
    max: float
    constant: str
    reason: str
    level: str = "required"
    metric: str = "euclid"
    direction: tuple | None = None
    need_overlap: bool = True
    samples: int = BAND_CHORD_SAMPLES
    max_bulge: bool = False
    kind: str = "clear"


@dataclass(frozen=True)
class Proportion:
    """Part ``part`` lofted from a profile table: at every ``rows`` entry ``(z, hw, yf, yb)`` (``yb`` may be
    ``None``) the horizontal section's half-widths left and right, its front and its back match the table within
    ``tol[k]`` (m) for that row, and half-way between consecutive rows they match the linear interpolation."""

    name: str
    part: str
    rows: tuple
    tol: tuple
    constant: str
    reason: str
    level: str = "required"
    kind: str = "proportion"


@dataclass(frozen=True)
class Pose:
    name: str
    pose: str
    constant: str
    reason: str
    level: str = "advisory"
    kind: str = "pose"


#: Free-form parts with no written proportion rule: a width table every DIAGNOSTIC_STEP for the critic to read.
DIAGNOSTIC_WIDTHS = ("hair.dome", "hair.back", "hair.bangs", "hair.sidelock_l", "hair.sidelock_r", "body.skirt")
DIAGNOSTIC_STEP = 0.005


def _decal_layers(rig: Rig):
    """Per side, the face decals in stack order (head.build / head._eye_parts): ``(name, back depth, constant,
    the decals placed before it on the same stack)``."""
    d0, step, st = rig.eye_slab_depth, head.LAYER_DEPTH_STEP, head.STACK_DEPTH
    out = []
    for _side, s in SIDES:
        layers = [(f"head.sclera_{s}", d0, "rig.eye_slab_depth"),
                  (f"head.iris_{s}", st, "head.STACK_DEPTH"),
                  (f"head.pupil_{s}", st + step, "head.STACK_DEPTH + head.LAYER_DEPTH_STEP"),
                  (f"head.highlight_{s}", st + 2 * step, "head.STACK_DEPTH + 2 head.LAYER_DEPTH_STEP"),
                  (f"head.lid_{s}", d0 + 0.5 * step, "rig.eye_slab_depth + 0.5 head.LAYER_DEPTH_STEP"),
                  (f"head.lower_lid_{s}", d0 + 1.5 * step, "rig.eye_slab_depth + 1.5 head.LAYER_DEPTH_STEP")]
        for k, (name, depth, const) in enumerate(layers):
            out.append((name, depth, const, tuple(n for n, _, _ in layers[:k])))
        out.append((f"head.brow_{s}", d0, "rig.eye_slab_depth", ()))
    out.append(("head.mouth", d0, "rig.eye_slab_depth", ()))
    out.append(("head.nose_mark", d0, "rig.eye_slab_depth", ()))
    return out


def _decal_requirements(rig: Rig) -> list:
    front = Select(host_cos=("head.skin", DECAL_FRONT_COS), note="decal front faces (within 45 deg of the skin "
                   "normal under them)")
    not_front = Select(host_cos=("head.skin", DECAL_FRONT_COS), invert=True,
                       note="decal walls and back (everything but the front faces)")
    back = Select(host_cos=("head.skin", DECAL_FRONT_COS), invert=True, only=True,
                  note="decal back vertices (on no front face)")
    out = []
    why = ("head.py decal stack (_decal / DecalStack): the back face sits its depth behind the front-most "
           "surface under it (the skin or the decal it lies on), measured along y against the faceted mesh; "
           "the front stays clear of them")
    for name, depth, const, below in _decal_layers(rig):
        stack = tuple((b, front) for b in below)
        out.append(Join(f"join:{name}~head.skin", name, "head.skin",
                        Zone(faces=("a", not_front), note="the curve lies on the decal's walls / back, never on "
                             "its front face"),
                        back, depth, const, why, depth_metric="along", direction=BACKWARD, stack=stack))
        out.append(Clear(f"clear:{name}^head.skin", name, "head.skin", front, ALL, rig.decal_skin_clearance, INF,
                         "rig.decal_skin_clearance", "the decal front stays this far in front of the skin (README "
                         "rule 5; head.DecalStack.clear_skin)", metric="along", direction=TOWARD_VIEWER))
        for b in below:
            out.append(Join(f"join:{name}~{b}", name, b,
                            Zone(faces=("a", not_front), note="the curve lies on the upper decal's walls / back"),
                            None, 0.0, const, why + "; the depth is checked in the skin join (stack metric)",
                            contact="optional"))
            out.append(Clear(f"clear:{name}^{b}", name, b, front, front, rig.decal_layer_clearance, INF,
                             "rig.decal_layer_clearance", "a stacked decal's front stays this far in front of the "
                             "decal below it, where it lies over it (head.DecalStack.clear_layer)",
                             metric="along", direction=TOWARD_VIEWER, need_overlap=False))
    return out


def _sidelock_root_depth(rig: Rig) -> float:
    """The perpendicular depth of the sidelock root row's edges under the dome (hair._sidelock_root_row insets them
    SIDELOCK_ROOT_INSET along the horizontal section normal): inset x cos(section normal, dome normal), the smaller
    of the inner and outer edge."""
    c = rig.dome_center
    _z0, xi, yi, xo, yo = rig.sidelock_rows[0]
    cos = []
    for x, y in ((xi, yi), (xo, yo)):
        p, n = hair._dome_section_point(rig, hair.SIDELOCK_ROOT_Z, math.atan2(x, y - c[1]))
        cos.append(float(n @ hair._ellipsoid_normal(rig, p)))
    return hair.SIDELOCK_ROOT_INSET * min(cos)


def _hair_requirements(rig: Rig) -> list:
    dc = rig.dome_center
    out = []
    band_hidden = Select(groups=(2,), note="headband walls, ends and inner face (group 2, hair._band_slab)")
    band_zone = Zone(any_of=(Zone(faces=("a", band_hidden)), Zone(y=(rig.band_tuck_y, INF))),
                     note="the band's walls / ends / inner face, or anywhere behind band_tuck_y where it dives")
    band_host_zone = Zone(any_of=(Zone(faces=("b", band_hidden)), Zone(y=(rig.band_tuck_y, INF))),
                          note="the band's hidden faces, or anywhere behind band_tuck_y where it dives")
    out.append(Join(
        "join:head.skin~hair.dome", "head.skin", "hair.dome",
        Zone(z=(hair.DOME_BACK_BOTTOM_Z, head.HEAD_ROWS[0]),
             note="between the dome's lowest boundary and the skin's top row"),
        None, 0.0, "head.HEAD_ROWS[0]",
        "head.py: the skin starts at HEAD_ROWS[0], under the bangs, inside the hair (no depth: its front is under "
        "the bangs, not in the dome)"))
    out.append(Join(
        "join:hair.dome~head.skin", "hair.dome", "head.skin",
        Zone(z=(hair.DOME_BACK_BOTTOM_Z, head.HEAD_ROWS[0])),
        Select(vz=(hair.DOME_CAP_APEX[2], hair.DOME_CAP_APEX[2]), note="the dome's under-fan apex"), 0.0,
        "hair.DOME_CAP_APEX", "hair.py: the fan closing the dome underneath ends inside the skull"))
    bangs_hidden = Select(groups=tuple(range(1, rig.bangs_strips + 1)), facing=(TOWARD_VIEWER, FACING_COS),
                          invert=True, note="the bangs' top, back, cut and end faces (not the front strips)")
    out.append(Join(
        "join:hair.bangs~hair.dome", "hair.bangs", "hair.dome",
        Zone(any_of=(Zone(faces=("a", bangs_hidden)), Zone(near=("hair.headband", rig.band_thickness))),
             note="the bangs leave the dome through their hidden faces or under the band (within its thickness; "
                  "approximate: fitted by the profile, hair._bangs states no zone)"),
        Select(groups=(rig.bangs_strips + 1,), facing=(UP, FACING_COS), note="the bangs' top rim (v0)"), 0.0,
        "rig.bangs_top_extension", "hair._bangs: the top row continues bangs_top_extension up under the band "
        "into H1; the bangs come out from under the band (hair._dome_bottom_z)", also=("hair.headband",),
        zone_status="approximate"))
    out.append(Join(
        "join:hair.bangs~hair.headband", "hair.bangs", "hair.headband",
        band_host_zone, None, 0.0, "hair.BANGS_UNDER_BAND",
        "hair._bangs: the block comes out from under the band, its top row continues under it"))
    out.append(Join(
        "join:hair.headband~hair.dome", "hair.headband", "hair.dome", band_zone,
        Select(groups=(2,), inward_from=dc, radial_cos=INNER_FACE_COS, note="the band's inner face"),
        rig.band_embed, "rig.band_embed (+ hair.BAND_DIVE toward the ends)",
        "hair._headband: the inner face is band_embed into the dome over the visible span, BAND_DIVE deeper "
        "toward the ends"))
    out.append(Join(
        "join:hair.headband_ridge~hair.headband", "hair.headband_ridge", "hair.headband",
        Zone(faces=("a", Select(outward_from=dc, invert=True)),
             note="the curve lies on the ridge's walls / ends / base, never on its top"),
        Select(inward_from=dc, radial_cos=INNER_FACE_COS, note="the ridge's base"), hair.RIDGE_SINK,
        "hair.RIDGE_SINK", "hair._headband: the ridge's base sits RIDGE_SINK inside the band's outer face"))
    out.append(Join(
        "join:hair.headband_ridge~hair.dome", "hair.headband_ridge", "hair.dome",
        Zone(y=(rig.band_tuck_y, INF), note="behind band_tuck_y, where the band dives"), None, 0.0,
        "rig.band_tuck_y / hair.BAND_DIVE", "hair._headband: the ridge runs to the band's ends, buried with them "
        "(BAND_DIVE from band_tuck_y back; round 4, F7)"))
    for part in ("hair.headband", "hair.headband_ridge"):
        out.append(Join(
            f"join:{part}~hair.back", part, "hair.back", Zone(y=(rig.band_tuck_y, INF),
                                                              note="behind band_tuck_y"), None, 0.0,
            "rig.band_tuck_y", "rig.band_visible_x: from y ~ band_tuck_y back the band is under H2"))
    lock_depth = _sidelock_root_depth(rig)
    for _side, s in SIDES:
        lock = f"hair.sidelock_{s}"
        out.append(Join(
            f"join:{lock}~hair.dome", lock, "hair.dome",
            Zone(z=(hair.DOME_BACK_BOTTOM_Z, hair.SIDELOCK_ROOT_Z),
                 note="the lock comes out through the dome surface over the temple"),
            Select(vz=(hair.SIDELOCK_ROOT_Z, INF), farthest=2, note="the root row's two edges (its vertices "
                   "farthest from the row's centroid)"), lock_depth,
            "hair.SIDELOCK_ROOT_INSET x cos(dome slope)", "hair._sidelock_root_row: the root row's edges "
            "SIDELOCK_ROOT_INSET inside the dome surface at SIDELOCK_ROOT_Z (the root cap never shows; round 1, T3), "
            "along the dome section's horizontal normal (hair._dome_section_point): the perpendicular depth is the "
            "inset times the cosine between that normal and the dome's normal (hair._ellipsoid_normal), the smaller "
            "of the two edges"))
        out.append(Join(
            f"join:{lock}~hair.headband", lock, "hair.headband",
            band_host_zone, None, 0.0,
            "hair.SIDELOCK_ROOT_Z", "hair.py H4: the roots rise into the dome under the band"))
    out.append(Join(
        "join:hair.dome~hair.back", "hair.dome", "hair.back",
        Zone(z=(hair.DOME_BACK_BOTTOM_Z, rig.curtain_top_rows[0][0]),
             note="where the curtain comes out from under the dome"),
        Select(vz=(-INF, hair.DOME_BACK_BOTTOM_Z), note="the dome's bottom ring behind the band"), 0.0,
        "hair.DOME_BACK_INSET / hair.DOME_BACK_BOTTOM_Z",
        "hair.py: the blend rings sink DOME_BACK_INSET inside the dome surface where the curtain covers them "
        "(round 3, tech F1 / F10); the dome tucks inside the curtain"))
    out.append(Join(
        "join:hair.back~hair.dome", "hair.back", "hair.dome",
        Zone(z=(hair.DOME_BACK_BOTTOM_Z, rig.curtain_top_rows[0][0])),
        Select(vz=(rig.curtain_top_rows[0][0], INF), note="the curtain's top row"), 0.0,
        "rig.curtain_top_rows", "hair.py H2: the curtain starts inside the dome and emerges from under it"))
    # the hair tuck idiom between the locks and the bangs / the side curtain (the look rounds 1-4 accepted)
    x_r, x_l = hair.bangs_outer_strip_x(rig)
    g_back = rig.bangs_strips + 1
    for side, s in SIDES:
        lock, strip = f"hair.sidelock_{s}", (rig.bangs_strips if side > 0 else 1)
        outer = Select(groups=(strip, g_back), x=(x_l, INF) if side > 0 else (-INF, x_r),
                       note=f"the bangs' outermost strip (group {strip}: its front and end faces; group {g_back}: "
                            "its back and top faces), beyond the next strip's border (hair.bangs_outer_strip_x)")
        out.append(Join(
            f"join:hair.bangs~{lock}", "hair.bangs", lock,
            Zone(faces=("a", outer), note="the lock lies over the bangs' outermost strip and end only; a leak onto "
                 "the next strip fails"),
            None, 0.0, "hair.BANGS_END_X / rig.sidelock_rows / hair.bangs_outer_strip_x",
            "rig.sidelock_rows (round 2, F7): the lock's inner edge passes through the bangs' end down to the cut "
            "(no slot beside it); the lock lies over the bangs' end at the temple, the look accepted in rounds 1-4"))
    # the curtain's front edge (hair._back_hair): the rows at or above CURTAIN_TUCK_MIN_Z end at CURTAIN_FRONT_Y,
    # the next one at its table y_end, the end face linear between the rows; the zone is the end face and the
    # first CURTAIN_END_THICKNESS of the outer / inner faces behind it, in z steps of `step`
    edge = [(z, hair._front_y(z)) for z, _off, _t in rig.curtain_top_rows]
    edge += [(r[0], hair._front_y(r[0]) if r[0] >= hair.CURTAIN_TUCK_MIN_Z else r[5]) for r in rig.curtain_rows[1:]]
    edge.sort()                                                                      # ascending z

    def edge_y(z):
        for (za, ya), (zb, yb) in zip(edge[:-1], edge[1:]):
            if za <= z <= zb:
                return ya + (yb - ya) * (z - za) / (zb - za)
        raise ValueError(z)

    step, z_top = 0.005, edge[-1][0]
    zs = sorted({round(hair.CURTAIN_TUCK_MIN_Z + k * step, 9)
                 for k in range(int((z_top - hair.CURTAIN_TUCK_MIN_Z) / step) + 1)}
                | {z for z, _y in edge if z >= hair.CURTAIN_TUCK_MIN_Z} | {z_top})
    boxes = []
    for z0, z1 in zip(zs[:-1], zs[1:]):
        y0, y1 = edge_y(z0), edge_y(z1)
        boxes.append(Zone(z=(z0, z1), y=(min(y0, y1), max(y0, y1) + hair.CURTAIN_END_THICKNESS)))
    front_edge = Zone(any_of=tuple(boxes), note="the curtain's front edge: from its end face (hair.CURTAIN_FRONT_Y, "
                      "linear between the curtain rows) back by hair.CURTAIN_END_THICKNESS, z from "
                      "hair.CURTAIN_TUCK_MIN_Z to the top curtain row")
    for _side, s in SIDES:
        lock = f"hair.sidelock_{s}"
        out.append(Join(
            f"join:{lock}~hair.back", lock, "hair.back", front_edge, None, 0.0,
            "hair.CURTAIN_FRONT_Y / hair.CURTAIN_END_THICKNESS",
            "hair.CURTAIN_FRONT_Y (round 3, F1): the curtain's front edge ends ~3 mm in front of the lock's back "
            "(outer) edge, the curtain outside the lock: in profile it covers the lock's back 3 mm and the lock "
            "is the front-most hair; the lock's outer edge tucks into that front edge"))
    return out


def _body_requirements(rig: Rig) -> list:
    out = []
    torso = body.torso_model(rig)
    z_root = torso.rows[0][0]
    a, _cy, b = body._neck_section(rig, z_root)
    fit_depth = (1.0 - body.NECK_FIT ** 0.5) * min(a, b)
    out.append(Join(
        "join:body.neck~head.skin", "body.neck", "head.skin",
        Zone(z=(rig.head_profile[-1][0], body.NECK_RING_Z[-1]), note="between the chin bottom and the neck top"),
        Select(vz=(body.NECK_RING_Z[-1], INF), note="the neck's top ring"), 0.0,
        "body.NECK_RING_Z[-1] / rig.neck_z[1]", "body.py: the neck ends inside the head (and head.JUNCTION_INSET "
        "puts the head's junction points inside the neck)"))
    out.append(Join(
        "join:body.neck~body.blouse", "body.neck", "body.blouse",
        Zone(z=(body.NECK_RING_Z[0], body.NECK_RING_Z[1]), note="below the neck root (NECK_BASE_Z)"),
        Select(vz=(-INF, body.NECK_RING_Z[0]), note="the neck's bottom ring"), 0.0,
        "body.NECK_RING_Z[0] / rig.neck_z[0]", "body.py: the neck starts inside the torso"))
    out.append(Join(
        "join:body.blouse~body.neck", "body.blouse", "body.neck",
        Zone(z=(body.NECK_RING_Z[0], body.NECK_RING_Z[1])),
        Select(vz=(z_root, INF), note="the blouse's neck-root row, top ring and apex"), fit_depth,
        "body.NECK_BLOUSE_INSET / body.NECK_FIT",
        "body.torso_model: the neck-root row stays NECK_BLOUSE_INSET inside the neck and within the NECK_FIT ellipse "
        "measure (depth (1 - sqrt(NECK_FIT)) * min semi-axis); the top ring TORSO_NECK_INSET inside"))
    out.append(Join(
        "join:body.bib~body.neck", "body.bib", "body.neck",
        Zone(z=(body.NECK_RING_Z[0], body.NECK_RING_Z[2]), note="the neck's root band"),
        Select(vz=(z_root + rig.bib_lift, INF), note="the bib's top row"), body.BIB_SINK, "body.BIB_SINK",
        "body._bib: the bib's top row lies BIB_SINK inside the neck surface (no fin standing out of the neck)"))
    collar_under = Select(inward_from=body.TORSO_CENTRE, note="the collar's underside (normal toward the chest)")
    lapel_hidden = Select(groups=(2,), note="the lapels' walls and underside (group 2, body._collar)")
    bib_top = Select(outward_from=(0.0, body._neck_section(rig, z_root)[1], body.BIB_AWAY_Z),
                     note="the bib's top face (body._bib: thickened inward, away from (0, cy, BIB_AWAY_Z))")
    out.append(Clear(
        "clear:body.collar^body.bib", "body.collar", "body.bib", collar_under, bib_top,
        body.COLLAR_BIB_CLEARANCE, INF, "body.COLLAR_BIB_CLEARANCE",
        "body._inner_edge_raise: the collar's inner edge underside clears the bib's top (review r3, F4)"))
    out.append(Join(
        "join:body.dickey~body.collar", "body.dickey", "body.collar",
        Zone(faces=("b", lapel_hidden), note="the dickey meets only the lapels' walls / underside"), None, 0.0,
        "rig.dickey_corners", "body._dickey: its corners and point are tucked under the lapels"))
    for _side, s in SIDES:
        rib = f"body.scarf_ribbon_{s}"
        out.append(Join(
            f"join:{rib}~body.collar", rib, "body.collar",
            Zone(faces=("b", lapel_hidden), note="the ribbon start meets only the lapel's walls / underside"),
            None, 0.0,
            "rig.scarf_start_width / rig.scarf_tuck_z",
            "body._ribbon: the ribbon starts under the lapel (review r3, F7), S0 / S1 lowered under it"))
        cz, h, r = rig.ring_center[2], rig.ring_size[2], rig.ring_corner_radius
        out.append(Join(
            f"join:{rib}~body.ring", rib, "body.ring",
            Zone(any_of=(Zone(z=(cz + 0.5 * h - r, INF)), Zone(faces=("b", Select(facing=(BACKWARD, FACING_COS))))),
                 note="the ribbon enters the ring through its top cap or its back face"),
            None, 0.0, "rig.scarf_path[-1] / rig.ring_center", "body._ribbon: S5 stays inside the ring"))
        z_tip = (rig.scarf_tip_root if s == "l" else rig.scarf_tip_root_right)[2]
        out.append(Join(
            f"join:body.scarf_tip_{s}~body.ring", f"body.scarf_tip_{s}", "body.ring",
            Zone(z=(-INF, cz - (0.5 * h - r)), note="the tip leaves the ring through its bottom cap"),
            Select(vz=(z_tip - 1e-4, z_tip + 1e-4), note="the tip's root edge (body._tip keeps it level at root z)"),
            0.0, "rig.scarf_tip_root / rig.scarf_tip_root_right / rig.ring_size",
            "body._tip: a flat blade below the ring, its root inside the ring (the root cap is a quad: its 4 vertices "
            "lie at the root z, every other station is lower)"))
        out.append(Join(
            f"join:{rib}~body.scarf_tip_{s}", rib, f"body.scarf_tip_{s}", Zone(inside="body.ring",
                                                                             note="hidden inside the ring"),
            None, 0.0, "rig.scarf_path[-1] / rig.scarf_tip_root", "body._ribbon / _tip: both end inside the ring (they "
            "need not meet)", contact="optional"))
    out.append(Join(
        "join:body.scarf_ribbon_l~body.scarf_ribbon_r", "body.scarf_ribbon_l", "body.scarf_ribbon_r",
        Zone(inside="body.ring", note="hidden inside the ring"), None, 0.0, "rig.scarf_path[-1]",
        "body._ribbon: both ribbons' S5 stays inside the ring (they need not meet)", contact="optional"))
    hem_disc = Select(groups=(3,), note="the blouse's flat hem disc (group 3, body._blouse)")
    for part, top in (("body.skirt", rig.skirt_waist_z), ("body.underskirt", rig.underskirt_z[1])):
        out.append(Join(
            f"join:{part}~body.blouse", part, "body.blouse",
            Zone(faces=("b", hem_disc), note="the part comes out from under the blouse's hem disc"),
            Select(vz=(top, INF), note="its top"), 0.0, "rig.blouse_hem_z < rig.skirt_waist_z",
            "the blouse hangs over the skirt waist: its hem (blouse_rows[-1]) is below the waist and the "
            "under-skirt top"))
    ceiling = Select(groups=(4,), facing=(DOWN, FACING_COS), note="the skirt's ceiling (group 4, facing down)")
    out.append(Join(
        "join:body.underskirt~body.skirt", "body.underskirt", "body.skirt",
        Zone(faces=("b", ceiling), note="the under-skirt meets the skirt's ceiling only"), None, 0.0,
        "rig.skirt_ceiling_z", "body._skirt: the ceiling closes the shell level with the under-skirt's bottom"))
    for side, s in SIDES:
        leg, sock, shoe = f"limbs.leg_{s}", f"limbs.sock_{s}", f"limbs.shoe_{s}"
        out.append(Join(
            f"join:{leg}~body.underskirt", leg, "body.underskirt",
            Zone(faces=("b", Select(facing=(DOWN, FACING_COS))), note="through the under-skirt's bottom"),
            Select(min_sides=CAP_SIDES, vz=(limbs.LEG_Z[0], INF), note="the leg's top cap"), 0.0,
            "rig.leg_top_z", "rig.leg_top_z: the leg's top is inside the under-skirt block"))
        out.append(Join(
            f"join:{leg}~body.skirt", leg, "body.skirt",
            Zone(faces=("b", ceiling), note="through the skirt's ceiling"), None, 0.0, "rig.skirt_ceiling_z",
            "body._skirt: from below the legs and the under-skirt still show through the ceiling"))
        out.append(Join(
            f"join:{leg}~{sock}", leg, sock,
            Zone(faces=("b", Select(groups=(3,))), note="the leg enters the sock through its top cap only"),
            Select(min_sides=CAP_SIDES, vz=(-INF, limbs.LEG_Z[-2]), note="the leg's bottom cap"),
            rig.sock_ease, "limbs.LEG_Z[-1] / rig.sock_ease",
            "limbs.py: the leg ends inside the sock; sock = leg + sock_ease"))
        out.append(Join(
            f"join:{sock}~{shoe}", sock, shoe,
            Zone(faces=("b", Select(groups=(3,))), note="the sock enters the shoe through its opening only"),
            Select(min_sides=CAP_SIDES, vz=(-INF, limbs.SOCK_Z[1]), note="the sock's bottom cap"), 0.0,
            "limbs.SOCK_Z[0]", "limbs.py: the sock runs from inside the shoe (the opening rolls in to a floor, "
            "the sock passes through it)"))
        out.append(Clear(
            f"clear:limbs.strap_{s}^{shoe}", f"limbs.strap_{s}", shoe,
            ALL, Select(note="the whole shoe (as lift_band_borders measures it)"),
            limbs.STRAP_CLEARANCE, INF, "limbs.STRAP_CLEARANCE",
            "limbs._shoe: every chord of the strap's borders at least STRAP_CLEARANCE above the shoe, 7 samples per "
            "chord along the station normals (meshkit.lift_band_borders; review r2, F5)", metric="band_chords"))
        out.append(Clear(
            f"clear:limbs.strap_{s}^{shoe}/surface", f"limbs.strap_{s}", shoe,
            Select(note="every strap face"), Select(groups=(2,), note="the upper (group 2)"),
            limbs.STRAP_CLEARANCE, INF, "limbs.STRAP_CLEARANCE",
            "advisory: the whole strap (its bottom face too, which no builder rule covers) against the upper, by the "
            "exact distance; the gated rule is the border chords", level="advisory"))
        sleeve, hand, thumb = f"limbs.sleeve_{s}", f"limbs.hand_{s}", f"limbs.thumb_{s}"
        out.append(Join(
            f"join:{sleeve}~body.blouse", sleeve, "body.blouse",
            Zone(note="exempt: no zone in the builder -- the blouse cuts the sleeve over its round cap and on down the "
                 "inner arm (the armpit), which no builder constant bounds"),
            None, 0.0, "limbs.SLEEVE_START", "limbs._sleeve: the round sleeve cap sits inside the blouse's shoulder",
            zone_status="exempt"))
        out.append(Join(
            f"join:{hand}~{sleeve}", hand, sleeve,
            Zone(faces=("b", Select(groups=(2,))), note="the hand enters the sleeve through the cuff opening only"),
            Select(min_sides=CAP_SIDES, note="the hand's wrist cap"), 0.0, "rig.wrist_in_sleeve / limbs.HAND_WRIST",
            "limbs._hand: the hand starts wrist_in_sleeve inside the cuff (HAND_WRIST: and inside the sleeve)"))
        out.append(Join(
            f"join:{thumb}~{hand}", thumb, hand, Zone(note="exempt: no zone in the builder"),
            Select(min_sides=CAP_SIDES, note="the thumb's base cap"), 0.0, "limbs._hand",
            "limbs._hand: the thumb is a lobe from the index side of the palm base", zone_status="exempt"))
        for k in range(len(rig.cuff_stripes)):
            out.append(_stripe_clear(rig, f"limbs.cuff_stripe_{s}{k}", sleeve,
                                     "limbs._sleeve: R = rad[-1] + stripe_float"))
    for part, host, where in (("body.collar_stripe", "body.collar", "body._collar: base = top + stripe_float nrm"),
                              ("body.ring_stripe0", "body.ring", "body._ring: rounded_rect_ring(w + 2 g, ...)"),
                              ("body.ring_stripe1", "body.ring", "body._ring: rounded_rect_ring(w + 2 g, ...)")):
        out.append(_stripe_clear(rig, part, host, where))
    return out


def _stripe_clear(rig: Rig, part: str, host: str, where: str) -> Clear:
    """A colour stripe's border stations stripe_float off its host: no closer, and no farther than stripe_float plus
    the host's facet bulge there (the builder offsets them off the analytic surface)."""
    return Clear(f"clear:{part}^{host}", part, host, ALL, ALL, rig.stripe_float, rig.stripe_float, "rig.stripe_float",
                 "README rule 5: colour stripes float stripe_float above the surface, so both borders draw; the "
                 f"border stations are placed there ({where})", metric="band_stations", max_bulge=True)


def _proportions(rig: Rig) -> list:
    out = []
    rows = []
    for z in head.HEAD_ROWS:
        hw, yf, yb, _c = head.head_section(rig, z)
        rows.append((z, hw, yf - head.NOSE_BUMP.get(round(z, 4), 0.0), yb))
    out.append(Proportion(
        "proportion:head.skin", "head.skin", tuple(rows), (0.0,) * len(rows),
        "head.HEAD_ROWS / rig.head_profile (head.head_section, head.NOSE_BUMP)",
        "the skin is lofted through head_section at HEAD_ROWS: side point x = hw, midline y = yf (minus the nose "
        "bump), back point y = yb"))
    torso = body.torso_model(rig)
    tol = []
    for z, hw, yf, yb in torso.rows:
        R = torso.ring(z, body.TORSO_RING_POINTS)
        tol.append(max(abs(float(R[:, 1].min()) - yf), abs(float(R[:, 1].max()) - yb)))
    out.append(Proportion(
        "proportion:body.blouse", "body.blouse", tuple(torso.rows), tuple(tol),
        "body.torso_model rows (rig.blouse_rows, rig.blouse_shoulder_hw)",
        "the blouse is lofted through Torso.ring at its rows: x = hw exactly; front / back within the ring's "
        "angular sampling (TORSO_RING_POINTS) of yf / yb"))
    return out


def profile(rig: Rig | None = None) -> list:
    """Every requirement of the Miki acceptance profile, in a fixed order."""
    rig = Rig() if rig is None else rig
    reqs = _decal_requirements(rig) + _hair_requirements(rig) + _body_requirements(rig) + _proportions(rig)
    reqs.append(Pose("pose:rest-only", "named poses (head turn / nod, arms raised, walking step)",
                     "SILHOUETTE PLAN milestone 2",
                     "milestone 1 tests the rest pose only; the posed checks are milestone 2 (advisory until then)"))
    names = [r.name for r in reqs]
    assert len(names) == len(set(names)), "duplicate requirement names"
    return reqs

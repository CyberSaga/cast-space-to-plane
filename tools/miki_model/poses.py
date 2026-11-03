"""Named poses of the Miki model for the posed clearance checks (milestone 2: "tested clearance").

A pose is an ordered list of steps ``(object id, world axis "x" | "y" | "z", degrees)``.  Each step is the web UI's
D85 part rotation (``web/src/object_rotate.ts::rotate_unit`` with a pivot): the object's subtree under
:data:`assemble.PARENTS` (the object first, then its descendants in pre-order, children in :data:`assemble.OBJECT_IDS`
order, as ``web/src/links.ts::subtree``) turns rigidly about the object's CURRENT world joint, ``world_centre(T,
joint)`` of its current transform ``T`` and the ``joint`` key of :func:`assemble.part_links` (an object-local point;
the meshes carry identity transforms, so it is the world point at rest).  Every member goes through
``rotate_about_point``: ``R' = Q R``, ``p' = c + Q (p - c)``; about ``z`` the Euler angles are exact
(``rz' = wrap(rz + deg)``), about ``x`` / ``y`` ``R'`` is decomposed (``euler_zyx_from_matrix``).  Later steps see the
earlier ones (the joint has moved with its parent).  The maths below mirrors the TypeScript expression by expression
(``ts/src/transform.ts``, ``web/src/object_rotate.ts``), so the fixture parity (``tests/fixtures/miki_poses.json``,
written by ``pose_fixtures.mjs`` from the built web code) holds to the last few ulps.

Sign convention (right-handed rotations about the world axes, as the web's ``rotation_x / y / z``; the figure faces
-Y, her left is +X):

* ``+x``: what is above the joint tilts forward (toward -Y: a nod down, a bow); a hanging limb swings backward;
* ``+y``: a hanging limb at +X (``arm_l``) swings inward, one at -X (``arm_r``) outward;
* ``+z``: the face turns to her left (+X); an arm held forward (toward -Y) swings toward +X: inward for ``arm_r``,
  outward for ``arm_l``.

So the table's motions are: head nod down ``+15`` / up ``-10``; arms raised sideways ``arm_l`` about ``y`` by
``-angle`` and ``arm_r`` by ``+angle``; arms inward (toward the body) the mirror, ``arm_l`` by ``+angle`` and ``arm_r``
by ``-angle``; arms forward ``-angle`` about ``x`` (then inward about ``z``: ``arm_l`` by ``-angle``, ``arm_r`` by
``+angle``); bow ``+angle`` about ``x``; knee bend ``+angle`` about ``x``
(the shanks swing back at the knees).

Only the rotation matrix / pivot maths is mirrored: nothing here writes a transform into the scene, and
:func:`posed_parts` returns new meshes (the rest meshes are never modified).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import assemble as asm
from . import meshkit as mk

__all__ = ["PoseSpec", "ARM_INWARD", "POSES", "AXES", "pose_steps", "angle_key", "subtree", "pose_transforms", "transform_matrix",
           "apply_transform", "posed_parts", "moved_objects", "motion_groups"]

AXES = {"x": 0, "y": 1, "z": 2}
#: ``euler_zyx_from_matrix``'s gimbal-lock threshold (``object_rotate.ts::GIMBAL_EPS``).
GIMBAL_EPS = 1e-9
_DEG = math.pi / 180.0


@dataclass(frozen=True)
class PoseSpec:
    """One pose of the table: ``steps`` ``((object, axis, deg), ...)`` where ``deg`` is ``"+"`` / ``"-"`` (plus /
    minus the swept angle) or a number (fixed degrees); ``sweeps``: the angles tested (degrees, in test order);
    ``level``: the profile level of the pose requirement (``"required"``: every tested angle must stay clean;
    ``"advisory"``: printed only).  The angles tested are what the report lists: never a "safe range"."""

    label: str
    steps: tuple
    sweeps: tuple
    level: str = "advisory"


#: The arms' D86 inward limit (degrees), the fixed arm step of the combined poses.
ARM_INWARD = float(asm.ARM_INWARD_MAX_DEG)

#: The poses tested (milestone 2).  See the module docstring for the signs.
POSES = {
    "head-turn": PoseSpec("head turn (about z; + toward her left)", (("head", "z", "+"),),
                          (10.0, -10.0, 20.0, -20.0, 30.0, -30.0)),
    "head-nod": PoseSpec("head nod (about x; +15 down, -10 up)", (("head", "x", "+"),), (15.0, -10.0)),
    "arms-raised": PoseSpec("arms raised sideways (arm_l about y -angle, arm_r about y +angle)",
                            (("arm_l", "y", "-"), ("arm_r", "y", "+")), (30.0, 60.0, 90.0)),
    "arms-inward": PoseSpec("arms inward (arm_l about y +angle, arm_r about y -angle; toward the body)",
                            (("arm_l", "y", "+"), ("arm_r", "y", "-")), (5.0, 10.0, 11.0), level="required"),
    "arms-inward-far": PoseSpec("arms inward, beyond the tested-clean range (same steps as arms-inward)",
                                (("arm_l", "y", "+"), ("arm_r", "y", "-")), (13.0, 15.0, 20.0, 25.0), level="advisory"),
    "arms-forward": PoseSpec("arms forward (both arms about x, - swings forward)",
                             (("arm_l", "x", "+"), ("arm_r", "x", "+")), (-30.0, -60.0)),
    "step": PoseSpec("step (legs about x at the hips: both legs, one object; socks and shoes follow; - forward)",
                     (("legs", "x", "+"),), (15.0, -15.0, 25.0, -25.0)),
    "knee-bend": PoseSpec("knee bend (socks about x at the knees: both shanks, one object; the shoes follow, the sock "
                          "tops stay on the thighs; + swings the heels back)", (("socks", "x", "+"),),
                          (5.0, -5.0, 10.0, -10.0, 15.0, -15.0)),
    "bow": PoseSpec("bow (blouse about x at the waist; carries neck, head, arms, collar, scarf, ring)",
                    (("blouse", "x", "+"),), (10.0, 20.0)),
    "bow-head-turn": PoseSpec("bow 10 deg, then head turn (two steps: the head turns about its joint as carried by "
                              "the bow)", (("blouse", "x", 10.0), ("head", "z", "+")), (20.0,)),
    # The combined poses (profile v7, advisory): the D86 limit (assemble.ARM_INWARD_MAX_DEG, the twist of the arm
    # relative to the blouse about the blouse's +y / -y) is exact only for the pure inward swing; these show it
    # neither certifies a motion combined with another one nor is the edge of the clean set there.
    "bow-arms-inward": PoseSpec("bow, then both arms inward by the limit angle about world y (the arms' twist "
                                "relative to the bowed blouse stays below the limit)",
                                (("blouse", "x", "+"), ("arm_l", "y", ARM_INWARD), ("arm_r", "y", -ARM_INWARD)),
                                (10.0,)),
    "lean-arms-inward": PoseSpec("sideways lean (blouse about y; + toward her left), then both arms inward by the "
                                 "limit angle (exactly at the limit: the same world axis)",
                                 (("blouse", "y", "+"), ("arm_l", "y", ARM_INWARD), ("arm_r", "y", -ARM_INWARD)),
                                 (2.0, -2.0)),
    "arms-forward45-inward": PoseSpec("both arms forward 45 deg (about x), then inward about world z by the angle "
                                      "(arm_l -angle, arm_r +angle)",
                                      (("arm_l", "x", -45.0), ("arm_l", "z", "-"), ("arm_r", "x", -45.0),
                                       ("arm_r", "z", "+")), (30.0,)),
    "arms-forward60-inward": PoseSpec("both arms forward 60 deg (about x), then inward about world z by the angle "
                                      "(arm_l -angle, arm_r +angle)",
                                      (("arm_l", "x", -60.0), ("arm_l", "z", "-"), ("arm_r", "x", -60.0),
                                       ("arm_r", "z", "+")), (15.0,)),
}


def angle_key(angle: float) -> str:
    """The report key of a swept angle: ``"+10"``, ``"-15"``."""
    return f"{float(angle):+g}"


def pose_steps(spec: PoseSpec, angle: float) -> tuple:
    """The concrete steps ``((object, axis, degrees), ...)`` of ``spec`` at the swept ``angle``."""
    out = []
    for obj, axis, deg in spec.steps:
        if deg == "+":
            d = float(angle)
        elif deg == "-":
            d = -float(angle)
        else:
            d = float(deg)
        out.append((obj, axis, d + 0.0))
    return tuple(out)


def subtree(oid: str, parents: dict | None = None) -> list:
    """``oid`` first, then its descendants in pre-order, siblings in :data:`assemble.OBJECT_IDS` order
    (``links.ts::subtree``)."""
    parents = asm.PARENTS if parents is None else parents
    children = {}
    for c in parents:
        p = parents[c]
        if p is not None:
            children.setdefault(p, []).append(c)
    out, stack = [], [oid]
    while stack:
        x = stack.pop()
        out.append(x)
        kids = children.get(x, [])
        for k in range(len(kids) - 1, -1, -1):
            stack.append(kids[k])
    return out


def motion_groups(steps) -> dict:
    """``{object id: (step indices)}``: the steps whose subtree holds each object (``()``: not moved).  Two objects
    with the same tuple keep their rest relation (one rigid motion); any two with different tuples moved relative to
    each other (for a one-step pose: the subtree against the rest; for ``arms-raised``: also ``arm_l`` against
    ``arm_r``; for ``bow-head-turn``: the head's subtree against the rest of the bowed body)."""
    sets = [set(subtree(obj)) for obj, _axis, _deg in steps]
    return {oid: tuple(i for i, s in enumerate(sets) if oid in s) for oid in asm.OBJECT_IDS}


def moved_objects(steps) -> list:
    """The objects a pose moves (the union of its steps' subtrees), in :data:`assemble.OBJECT_IDS` order."""
    moved = set()
    for obj, _axis, _deg in steps:
        moved |= set(subtree(obj))
    return [o for o in asm.OBJECT_IDS if o in moved]


# ---------------------------------------------------------------------------------------------------------------
# the TypeScript maths, expression by expression (ts/src/transform.ts, web/src/object_rotate.ts)
# ---------------------------------------------------------------------------------------------------------------

def _radians(deg: float) -> float:
    return deg * (math.pi / 180.0)


def _rotation(axis: int, deg: float) -> list:
    c, s = math.cos(_radians(deg)), math.sin(_radians(deg))
    if axis == 0:
        return [[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]]
    if axis == 1:
        return [[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]]
    return [[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]]


def _matmul3(A, B) -> list:
    """Every entry a left-to-right 3-term sum in ``k`` order (``matmul3`` / ``object_rotate.ts::matmul``)."""
    return [[A[i][0] * B[0][j] + A[i][1] * B[1][j] + A[i][2] * B[2][j] for j in range(3)] for i in range(3)]


def _euler_zyx_matrix(r) -> list:
    return _matmul3(_matmul3(_rotation(2, r[2]), _rotation(1, r[1])), _rotation(0, r[0]))


def _mul3(R, v) -> list:
    return [R[i][0] * v[0] + R[i][1] * v[1] + R[i][2] * v[2] for i in range(3)]


def _wrap_angle(x: float) -> float:
    w = x - 360.0 * math.ceil((x - 180.0) / 360.0)
    return w + 360.0 if w <= -180.0 else w + 0.0


def _euler_zyx_from_matrix(R) -> list:
    h = math.hypot(R[0][0], R[1][0])
    ry = math.atan2(-R[2][0], h) / _DEG
    if h < GIMBAL_EPS:
        return [0.0, ry + 0.0, _wrap_angle(math.atan2(-R[0][1], R[1][1]) / _DEG)]
    return [_wrap_angle(math.atan2(R[2][1], R[2][2]) / _DEG), ry + 0.0, _wrap_angle(math.atan2(R[1][0], R[0][0]) / _DEG)]


def transform_matrix(t) -> list:
    """``R`` of the transform ``t = (position, rotation_deg)`` (``transform_frame``)."""
    return _euler_zyx_matrix(t[1])


def _world_centre(t, c_local) -> list:
    R = transform_matrix(t)
    v = _mul3(R, c_local)
    p = t[0]
    return [v[0] + p[0], v[1] + p[1], v[2] + p[2]]


def _rotate_about_point(t, c, axis: int, deg: float):
    R, p = transform_matrix(t), t[0]
    Q = _rotation(axis, deg)
    v = _mul3(Q, [p[0] - c[0], p[1] - c[1], p[2] - c[2]])
    position = [c[0] + v[0] + 0.0, c[1] + v[1] + 0.0, c[2] + v[2] + 0.0]
    r = t[1]
    rotation = [r[0], r[1], _wrap_angle(r[2] + deg)] if axis == 2 else _euler_zyx_from_matrix(_matmul3(Q, R))
    return (position, rotation)


def pose_transforms(rig, steps, links: dict | None = None, pivots: list | None = None) -> dict:
    """``{object id: (position, rotation_deg)}`` of every object after ``steps`` (lists of floats; identity at rest),
    with each step's world pivot ``world_centre(T, joint)`` on the object's current transform.  ``links``:
    :func:`assemble.part_links` (computed from ``rig`` when ``None``); ``pivots``: a list that receives each step's
    world pivot."""
    links = asm.part_links(rig) if links is None else links
    T = {oid: ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0]) for oid in asm.OBJECT_IDS}
    for obj, axis, deg in steps:
        pivot = _world_centre(T[obj], list(links[obj][1]))
        if pivots is not None:
            pivots.append(pivot)
        for k in subtree(obj):
            T[k] = _rotate_about_point(T[k], pivot, AXES[axis], float(deg))
    return T


def apply_transform(t, X) -> np.ndarray:
    """``R x + p`` for the points ``X`` ``(n, 3)`` under ``t = (position, rotation_deg)``: fixed 3-term sums per
    component (no BLAS: deterministic)."""
    R = np.asarray(transform_matrix(t), dtype=np.float64)
    p = np.asarray(t[0], dtype=np.float64)
    X = np.asarray(X, dtype=np.float64).reshape(-1, 3)
    out = np.empty_like(X)
    for i in range(3):
        out[:, i] = R[i, 0] * X[:, 0] + R[i, 1] * X[:, 1] + R[i, 2] * X[:, 2] + p[i]
    return out + 0.0


def posed_parts(parts, rig, steps, links: dict | None = None) -> dict:
    """``{part name: Mesh}`` of every part whose object ``steps`` move (:func:`moved_objects`), each the rigid image
    of its rest mesh under its object's final transform (faces and smooth groups unchanged, vertices not re-rounded).
    Parts of unmoved objects are left out (they keep their rest mesh)."""
    T = pose_transforms(rig, steps, links)
    moved = set(moved_objects(steps))
    out = {}
    for p in parts:
        if p.obj in moved:
            V = apply_transform(T[p.obj], p.mesh.vertices)
            out[p.name] = mk.Mesh(V, p.mesh.faces, p.mesh.groups)
    return out


def _check_table():
    for name, spec in POSES.items():
        assert spec.sweeps and len(set(spec.sweeps)) == len(spec.sweeps), name
        assert spec.level in ("required", "advisory"), (name, spec.level)
        for obj, axis, deg in spec.steps:
            assert obj in asm.OBJECT_IDS and axis in AXES, (name, obj, axis)
            assert deg in ("+", "-") or isinstance(deg, float), (name, deg)


_check_table()

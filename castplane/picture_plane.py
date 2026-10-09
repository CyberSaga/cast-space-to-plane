"""The ``picture_plane`` camera form (M10; spec-v0.2 §4.1, §4.3).

A camera block may give ``position`` (the eye ``E``) plus ``picture_plane = {normal, offset, up?}`` instead of a
``target`` or ``yaw_deg`` / ``pitch_deg``.  The plane is ``n·X + offset = 0`` (the receiver convention); validation
(:func:`castplane.scene.validate_picture_plane`) normalises it to ``n̂·X + off̂ = 0`` and rejects a plane through
``E`` and an ``up`` parallel to the normal.

The form is resolved **before** stage B into an ordinary ``target``-form block and then goes through the unchanged
:func:`castplane.camera.camera_matrix` (rows ``(right', up', forward)``, ``det R = -1``)::

    s = n̂·E + off̂,   D = |s|,   f = -sign(s) n̂,   Q = E - s n̂,   target = E + f

``f`` points from the eye to the plane; ``Q`` is the foot of the eye on the plane (the principal point when
``shift_mm`` is zero).  ``roll_deg`` is the signed angle, in ``camera_matrix``'s roll convention, from the default up
of ``camera_matrix`` (world z, or +y when ``|forward × z| <= 1e-9``) to the frame up (``up`` projected onto the
plane); without ``up`` it is exactly 0.  The form never emits ``CAMERA_LOOKING_ALONG_UP``: the frame up is explicit.

Only numpy.  Every scalar expression is written out left to right so that the TypeScript port
(``ts/src/picture_plane.ts``) reproduces it bit for bit.
"""

from __future__ import annotations

import math

import numpy as np

from .camera import _default_basis, camera_forward

__all__ = ["resolve_picture_plane", "picture_plane_document", "plane_equation", "unproject_to_plane"]

#: ``|(|n_i| - 1)| < AXIS_TOL`` marks a unit normal parallel to coordinate axis ``i`` (spec-v0.2 §4.3).
AXIS_TOL = 1e-9
#: ``|n_i| > NONZERO_TOL`` is a nonzero coefficient (the one made positive); ``|n_i| < DROP_TOL`` is not printed.
NONZERO_TOL = 1e-9
DROP_TOL = 5e-4


def resolve_picture_plane(cam: dict):
    """``(target_cam, roll_deg, info)`` of a validated ``picture_plane`` camera (spec-v0.2 §4.1).

    ``target_cam`` is a validated ``target``-form camera block (``position``, ``target = E + f``, ``roll_deg``
    and the lens keys); ``info = {"normal": f, "offset": -f·Q, "distance": D, "foot": Q}`` describes the plane
    with its normal pointing from the eye to the plane (``offset`` is ``-off̂`` when ``s > 0`` and ``off̂``
    otherwise: the same plane, ``f·X + offset = 0``).
    """
    pp = cam["picture_plane"]
    n = [float(v) for v in pp["normal"]]
    off = float(pp["offset"])
    E = [float(v) for v in cam["position"]]
    s = n[0] * E[0] + n[1] * E[1] + n[2] * E[2] + off
    D = abs(s)
    if s > 0.0:
        f = [-n[0] + 0.0, -n[1] + 0.0, -n[2] + 0.0]
        offset = -off + 0.0
    else:
        f = [n[0] + 0.0, n[1] + 0.0, n[2] + 0.0]
        offset = off + 0.0
    Q = [E[0] - s * n[0] + 0.0, E[1] - s * n[1] + 0.0, E[2] - s * n[2] + 0.0]
    target = [E[0] + f[0], E[1] + f[1], E[2] + f[2]]
    tcam = {"position": E, "target": target, "roll_deg": 0.0}
    for k in ("focal_length_mm", "frame_mm", "shift_mm", "near_m"):
        if k in cam:
            tcam[k] = cam[k]
    roll = 0.0
    if "up" in pp:
        up = [float(v) for v in pp["up"]]
        right0, up0, _along = _default_basis(camera_forward(tcam))
        sin_r = -(up[0] * float(right0[0]) + up[1] * float(right0[1]) + up[2] * float(right0[2]))
        cos_r = up[0] * float(up0[0]) + up[1] * float(up0[1]) + up[2] * float(up0[2])
        roll = math.degrees(math.atan2(sin_r, cos_r)) + 0.0
        tcam["roll_deg"] = roll
    return tcam, roll, {"normal": f, "offset": offset, "distance": D, "foot": Q}


def picture_plane_document(info: dict, rec: dict, focal_length_mm) -> dict:
    """The ``camera.picture_plane`` block of the geometry document (spec-v0.2 §4.1, appendix A.3):
    ``{normal, offset, up, distance, foot, frame_m, equation}``; ``up`` is the camera's final up row ``R[1]``,
    ``frame_m = [frame_w·D/focal, frame_h·D/focal]`` (metres on the plane)."""
    D = float(info["distance"])
    focal = float(focal_length_mm)
    frame = rec["frame_mm"]
    up = rec["R"][1]
    return {
        "normal": list(info["normal"]),
        "offset": info["offset"],
        "up": [float(up[0]) + 0.0, float(up[1]) + 0.0, float(up[2]) + 0.0],
        "distance": D,
        "foot": list(info["foot"]),
        "frame_m": [frame[0] * D / focal + 0.0, frame[1] * D / focal + 0.0],
        "equation": plane_equation(info["normal"], info["offset"]),
    }


def _fixed(x: float, decimals: int) -> str:
    """``x`` with ``decimals`` decimals (Python's exact round-half-even of the binary value); a result that reads
    as negative zero (``-0.00``) loses its sign."""
    t = f"{x:.{decimals}f}"
    if t[0] == "-" and t.strip("-0.") == "":
        t = t[1:]
    return t


def plane_equation(normal, offset) -> str:
    """Human-readable equation of the plane ``normal·X + offset = 0`` (spec-v0.2 §4.3).

    The normal is normalised first (``n̂ = n/|n|``, constant ``c = -offset/|n|``, plane ``n̂·X = c``).  A normal
    with ``||n̂_i| - 1| < 1e-9`` is axis ``i``: ``"y = 2.00"`` (the positive axis, value ``sign(n̂_i)·c`` with two
    decimals).  Otherwise the first coefficient with ``|n̂_i| > 1e-9`` is made positive (negating ``n̂`` and ``c``),
    coefficients with ``|n̂_i| < 5e-4`` are dropped and the rest printed with three decimals:
    ``"0.707x - 0.707y = 1.200"``.  A value that rounds to negative zero is printed without its sign."""
    n = [float(v) for v in normal]
    nn = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    n = [n[0] / nn, n[1] / nn, n[2] / nn]
    c = -float(offset) / nn
    for i in range(3):
        if abs(abs(n[i]) - 1.0) < AXIS_TOL:
            sg = 1.0 if n[i] > 0.0 else -1.0
            return f"{'xyz'[i]} = {_fixed(sg * c, 2)}"
    first = next(i for i in range(3) if abs(n[i]) > NONZERO_TOL)
    if n[first] < 0.0:
        n = [-n[0], -n[1], -n[2]]
        c = -c
    out = ""
    for i in range(3):
        v = n[i]
        if abs(v) < DROP_TOL:
            continue
        term = f"{abs(v):.3f}{'xyz'[i]}"
        if not out:
            out = ("-" if v < 0.0 else "") + term
        else:
            out += (" - " if v < 0.0 else " + ") + term
    return f"{out} = {_fixed(c, 3)}"


def unproject_to_plane(rec: dict, uv, D):
    """Canvas point(s) ``(u, v)`` (mm) -> world point(s) on the picture plane at distance ``D`` (spec-v0.2 §4.3).

    ``X = E + D·[((u - u0)/(focal·s))·r' + ((v - v0)/(focal·s))·u' + f]`` with ``r'``, ``u'``, ``f`` the rows of
    ``rec["R"]``, ``focal·s = rec["K"][0, 0]`` and ``E = rec["C"]``; evaluated as
    ``E + D·((a·r' + b·u') + f)``.  ``uv`` is one ``[u, v]`` (returns shape ``(3,)``) or an ``(n, 2)`` array
    (returns ``(n, 3)``).  Projecting the result with ``rec`` returns ``(u, v)`` within 1e-9 mm."""
    uv = np.asarray(uv, dtype=np.float64)
    fs = float(rec["K"][0, 0])
    R = rec["R"]
    a = (uv[..., 0] - rec["u0"]) / fs
    b = (uv[..., 1] - rec["v0"]) / fs
    return rec["C"] + float(D) * (a[..., None] * R[0] + b[..., None] * R[1] + R[2])

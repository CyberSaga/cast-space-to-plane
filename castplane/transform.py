"""Object transforms: Euler Z-Y-X rotation and translation (spec §4; contract §2.1).

``rotation_deg = [rx, ry, rz]`` gives ``R = Rz(rz) · Ry(ry) · Rx(rx)`` applied
to local coordinates, ``world = R · local + position``.  Each ``R*`` is a
right-handed rotation about that axis.
"""

from __future__ import annotations

import math

import numpy as np


def rotation_x(deg: float):
    """Right-handed rotation about +X by ``deg`` degrees (contract §2.1)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[1.0, 0.0, 0.0], [0.0, c, -s], [0.0, s, c]], dtype=np.float64)


def rotation_y(deg: float):
    """Right-handed rotation about +Y by ``deg`` degrees (contract §2.1)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=np.float64)


def rotation_z(deg: float):
    """Right-handed rotation about +Z by ``deg`` degrees (contract §2.1)."""
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def euler_zyx_matrix(rotation_deg):
    """``R = Rz(rz) · Ry(ry) · Rx(rx)`` for ``rotation_deg = [rx, ry, rz]`` (spec §4, contract §2.1)."""
    rx, ry, rz = (float(v) for v in rotation_deg)
    return rotation_z(rz) @ rotation_y(ry) @ rotation_x(rx)


def transform_frame(transform):
    """``(R, position)`` of a validated transform dict (``position`` and ``rotation_deg`` filled in)."""
    transform = transform or {}
    R = euler_zyx_matrix(transform.get("rotation_deg", [0.0, 0.0, 0.0]))
    position = np.asarray(transform.get("position", [0.0, 0.0, 0.0]), dtype=np.float64)
    return R, position


def apply_transform(points, transform):
    """``world = R · local + position`` for an ``(n, 3)`` array of local points (contract §2.1)."""
    R, position = transform_frame(transform)
    pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
    return pts @ R.T + position[None, :]


def apply_rotation(vectors, transform):
    """``R · v`` for an ``(n, 3)`` array of local directions / normals (no translation)."""
    R, _ = transform_frame(transform)
    vec = np.asarray(vectors, dtype=np.float64).reshape(-1, 3)
    return vec @ R.T

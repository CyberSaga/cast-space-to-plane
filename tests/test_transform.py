"""Euler Z-Y-X transform (contract §2.1)."""

import numpy as np

from castplane.transform import (apply_rotation, apply_transform, euler_zyx_matrix, rotation_x,
                                 rotation_y, rotation_z)


def test_single_axis_rotations_are_right_handed():
    np.testing.assert_allclose(rotation_z(90) @ [1, 0, 0], [0, 1, 0], atol=1e-12)
    np.testing.assert_allclose(rotation_x(90) @ [0, 1, 0], [0, 0, 1], atol=1e-12)
    np.testing.assert_allclose(rotation_y(90) @ [0, 0, 1], [1, 0, 0], atol=1e-12)


def test_rotations_are_proper_orthonormal():
    for R in (rotation_x(33), rotation_y(-71), rotation_z(190), euler_zyx_matrix([10, 20, 30])):
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-12)
        assert abs(np.linalg.det(R) - 1.0) < 1e-12


def test_euler_zyx_order():
    R = euler_zyx_matrix([10, 20, 30])
    expected = rotation_z(30) @ rotation_y(20) @ rotation_x(10)
    np.testing.assert_allclose(R, expected, atol=1e-12)
    # Z-Y-X applied to local coordinates: Rx acts first, then Ry, then Rz
    p = np.array([1.0, 0.0, 0.0])
    np.testing.assert_allclose(R @ p, rotation_z(30) @ (rotation_y(20) @ (rotation_x(10) @ p)), atol=1e-12)


def test_apply_transform_rotates_then_translates():
    t = {"position": [2.0, 4.0, 0.0], "rotation_deg": [0.0, 0.0, 30.0]}
    out = apply_transform([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], t)
    c, s = np.cos(np.radians(30)), np.sin(np.radians(30))
    np.testing.assert_allclose(out[0], [2.0 + c, 4.0 + s, 0.0], atol=1e-12)
    np.testing.assert_allclose(out[1], [2.0, 4.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(apply_rotation([[1.0, 0.0, 0.0]], t)[0], [c, s, 0.0], atol=1e-12)


def test_identity_defaults():
    out = apply_transform([[1.0, 2.0, 3.0]], None)
    np.testing.assert_allclose(out, [[1.0, 2.0, 3.0]])
    np.testing.assert_allclose(euler_zyx_matrix([0, 0, 0]), np.eye(3))

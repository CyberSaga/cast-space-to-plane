"""Proportions and landmarks of the Miki model: the single source of every number.

All builders take a :class:`Rig` and read their dimensions from it; nothing else in the package
hard-codes a body measurement.  Units are metres and degrees; the frame is castplane's world (Z up,
ground ``z = 0``), the figure stands at the origin facing ``-Y`` with her left hand on ``+X``.  A
``side`` argument is ``+1`` for her left (``+X``) and ``-1`` for her right.

The defaults describe a 1.50 m anime schoolgirl (head ≈ 1/6.1 of the height) in a relaxed A-pose.  The
numeric character spec updates them with :meth:`Rig.replace` / :func:`Rig.from_dict` (unknown keys are
an error, so a typo cannot silently fall back to a default).
"""

from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass

import numpy as np

__all__ = ["Rig", "DEFAULT_RIG"]


@dataclass(frozen=True)
class Rig:
    """Named dimensions (metres, degrees) and derived landmarks of the figure."""

    # -- overall -------------------------------------------------------------
    height: float = 1.50                 # ground to the top of the skull (hair adds a little)

    # -- head (skull + face; the head builder may refine the shape) ------------
    head_height: float = 0.245           # chin to skull top
    head_width: float = 0.165            # widest (temples / upper cheeks)
    head_depth: float = 0.190            # forehead to back of skull
    head_center_y: float = 0.005         # y of the skull centre (slightly behind the neck axis)
    eye_height_ratio: float = 0.42       # eye centres above the chin, as a fraction of head_height
    eye_spacing: float = 0.058           # distance between the two eye centres
    eye_width: float = 0.040             # one eye, outer to inner corner
    eye_height: float = 0.034            # one eye, top to bottom (tall anime eyes)
    eye_relief: float = 0.002            # eye shell thickness above the face surface
    mouth_height_ratio: float = 0.17     # mouth above the chin, fraction of head_height
    mouth_width: float = 0.016
    brow_gap: float = 0.010              # brow above the top of the eye
    ear_height_ratio: float = 0.42       # ear centre above the chin, fraction of head_height
    ear_size: float = 0.045              # ear height

    # -- neck and torso --------------------------------------------------------
    neck_radius: float = 0.034
    neck_y: float = 0.010                # neck axis y (slightly behind the body centre line)
    shoulder_z: float = 1.215            # top of the shoulder line
    shoulder_half_width: float = 0.150   # shoulder point (acromion) x
    chest_z: float = 1.110
    chest_half_width: float = 0.122
    chest_half_depth: float = 0.088
    waist_z: float = 0.975
    waist_half_width: float = 0.100
    waist_half_depth: float = 0.072
    hip_z: float = 0.855
    hip_half_width: float = 0.140
    hip_half_depth: float = 0.092
    crotch_z: float = 0.745
    torso_exponent: float = 2.6          # superellipse exponent of the torso sections (2 = ellipse)

    # -- arms (relaxed A-pose) ---------------------------------------------------
    shoulder_joint_drop: float = 0.030   # shoulder joint below shoulder_z
    shoulder_joint_inset: float = 0.012  # shoulder joint inside shoulder_half_width
    upper_arm_length: float = 0.255
    forearm_length: float = 0.225
    hand_length: float = 0.150
    hand_width: float = 0.068
    hand_thickness: float = 0.026
    upper_arm_radius: float = 0.032
    elbow_radius: float = 0.026
    wrist_radius: float = 0.020
    arm_abduction_deg: float = 17.0      # upper arm away from the body (frontal plane)
    forearm_abduction_deg: float = 4.0   # extra outward angle of the forearm
    elbow_bend_deg: float = 14.0         # forearm bent forward (towards -Y)
    sleeve_ease: float = 0.012           # sleeve radius beyond the arm
    sleeve_cuff_length: float = 0.060    # cuff zone above the wrist (two white stripes)
    sleeve_end_past_wrist: float = 0.010

    # -- legs -------------------------------------------------------------------
    hip_joint_half_width: float = 0.082
    hip_joint_z: float = 0.790
    ankle_z: float = 0.075
    ankle_half_width: float = 0.105      # feet slightly apart
    knee_ratio: float = 0.505            # knee position from hip (0) to ankle (1)
    thigh_radius: float = 0.064
    knee_radius: float = 0.043
    calf_radius: float = 0.047
    ankle_radius: float = 0.030
    foot_toe_out_deg: float = 8.0
    foot_length: float = 0.215
    foot_width: float = 0.080
    heel_back: float = 0.040             # heel behind the ankle axis
    shoe_height: float = 0.070           # sole to the top of the shoe at the ankle
    shoe_sole: float = 0.012
    sock_top_z: float = 0.390
    sock_ease: float = 0.004

    # -- skirt ------------------------------------------------------------------
    skirt_top_z: float = 1.000           # waistband
    skirt_hem_z: float = 0.560
    skirt_hem_half_width: float = 0.255
    skirt_hem_half_depth: float = 0.220
    skirt_pleats: int = 24

    # -- uniform top --------------------------------------------------------------
    top_hem_z: float = 0.930             # bottom of the sailor top (over the skirt)
    top_ease: float = 0.012              # top beyond the body
    collar_back_flap_z: float = 1.020    # bottom edge of the square back flap
    collar_flap_half_width: float = 0.135
    collar_v_z: float = 1.085            # tip of the front V
    collar_thickness: float = 0.004
    scarf_width: float = 0.050
    scarf_tip_z: float = 0.990
    scarf_ring_radius: float = 0.012

    # -- hair ---------------------------------------------------------------------
    hair_volume: float = 0.016           # hair cap thickness over the skull
    hair_back_end_z: float = 0.820       # bottom of the back hair (hip length)
    hair_back_half_width: float = 0.150  # half width of the back hair at its ends
    hair_back_thickness: float = 0.025
    bangs_cut_ratio: float = 0.62        # bang cut edge above the chin, fraction of head_height
    bangs_thickness: float = 0.014
    sidelock_end_z: float = 1.090        # bottom of the sidelocks (chest)
    sidelock_width: float = 0.034
    sidelock_thickness: float = 0.012
    strand_width: float = 0.006
    headband_angle_deg: float = 40.0     # band direction from the head centre: degrees from vertical towards the face
    headband_width: float = 0.010
    headband_thickness: float = 0.004
    headband_lift: float = 0.004         # gap between hair surface and band

    # ---------------------------------------------------------------------------
    # construction
    def replace(self, **changes) -> "Rig":
        """A copy with some fields changed (unknown names raise ``TypeError``)."""
        return dataclasses.replace(self, **changes)

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, values: dict) -> "Rig":
        """Defaults updated by ``values``; unknown keys raise ``KeyError``."""
        names = {f.name for f in dataclasses.fields(cls)}
        unknown = sorted(set(values) - names)
        if unknown:
            raise KeyError(f"unknown rig keys: {unknown}")
        return cls(**values)

    # ---------------------------------------------------------------------------
    # head landmarks
    @property
    def chin_z(self) -> float:
        return self.height - self.head_height

    @property
    def head_center(self) -> np.ndarray:
        """Centre of the head ellipsoid (midway chin–skull top)."""
        return np.array([0.0, self.head_center_y, self.height - 0.5 * self.head_height])

    @property
    def head_radii(self) -> np.ndarray:
        return np.array([0.5 * self.head_width, 0.5 * self.head_depth, 0.5 * self.head_height])

    @property
    def eye_z(self) -> float:
        return self.chin_z + self.eye_height_ratio * self.head_height

    @property
    def mouth_z(self) -> float:
        return self.chin_z + self.mouth_height_ratio * self.head_height

    @property
    def bangs_cut_z(self) -> float:
        return self.chin_z + self.bangs_cut_ratio * self.head_height

    def eye_center(self, side: int) -> np.ndarray:
        """Eye centre on the (ellipsoidal) face surface."""
        return self.head_surface_point(side * 0.5 * self.eye_spacing, self.eye_z, front=True)

    def head_surface_point(self, x: float, z: float, front: bool = True) -> np.ndarray:
        """Point of the head ellipsoid at ``(x, z)`` on the front (``-Y``) or back side."""
        c, r = self.head_center, self.head_radii
        q = 1.0 - ((x - c[0]) / r[0]) ** 2 - ((z - c[2]) / r[2]) ** 2
        y = r[1] * math.sqrt(max(q, 0.0))
        return np.array([x, c[1] - y if front else c[1] + y, z])

    # ---------------------------------------------------------------------------
    # arm landmarks
    def shoulder_joint(self, side: int) -> np.ndarray:
        return np.array([side * (self.shoulder_half_width - self.shoulder_joint_inset), 0.0,
                         self.shoulder_z - self.shoulder_joint_drop])

    def upper_arm_dir(self, side: int) -> np.ndarray:
        a = math.radians(self.arm_abduction_deg)
        return np.array([side * math.sin(a), 0.0, -math.cos(a)])

    def elbow(self, side: int) -> np.ndarray:
        return self.shoulder_joint(side) + self.upper_arm_length * self.upper_arm_dir(side)

    def forearm_dir(self, side: int) -> np.ndarray:
        a = math.radians(self.arm_abduction_deg + self.forearm_abduction_deg)
        b = math.radians(self.elbow_bend_deg)
        d = np.array([side * math.sin(a) * math.cos(b), -math.sin(b), -math.cos(a) * math.cos(b)])
        return d / np.linalg.norm(d)

    def wrist(self, side: int) -> np.ndarray:
        return self.elbow(side) + self.forearm_length * self.forearm_dir(side)

    # ---------------------------------------------------------------------------
    # leg landmarks
    def hip_joint(self, side: int) -> np.ndarray:
        return np.array([side * self.hip_joint_half_width, 0.0, self.hip_joint_z])

    def ankle(self, side: int) -> np.ndarray:
        return np.array([side * self.ankle_half_width, 0.0, self.ankle_z])

    def knee(self, side: int) -> np.ndarray:
        return self.hip_joint(side) + self.knee_ratio * (self.ankle(side) - self.hip_joint(side))

    def foot_dir(self, side: int) -> np.ndarray:
        """Horizontal unit vector heel -> toe (``-Y`` turned out by ``foot_toe_out_deg``)."""
        t = math.radians(self.foot_toe_out_deg)
        return np.array([side * math.sin(t), -math.cos(t), 0.0])


DEFAULT_RIG = Rig()

"""Three-valued per-pixel depth-buffer reference for hidden lines (contract §5.1.11, DECISIONS D29).

Shares **no code** with ``castplane``: it reads the validated scene dict (spec §4) and re-implements the
camera of spec §5.4 / contract §2.1–§2.2 (target or yaw/pitch form, roll, ``K`` with the canvas scale and the
shift, the extended canvas rectangle grown by 25 % on each side).  Depth is the camera-space ``x̃₃`` both for
the buffer and for a tested sample.

The buffer covers the extended canvas at ``PX_MM = 0.1`` mm per pixel; pixel ``(iy, ix)`` has its centre at
``u = u_min + (ix + ½)·PX_MM``, ``v = v_max − (iy + ½)·PX_MM`` and holds the nearest ray parameter of the
camera ray through that centre over every object, every plate and the ground (``first_hit_t`` versions of the
ray-cast hitters, :mod:`tests.reference.raycast`).  The ray direction is scaled so that its forward component
is 1, hence the ray parameter **is** the depth ``x̃₃``.  :class:`DepthBuffer` evaluates pixels lazily (only the
pixels a test looks at, each once, cached) -- the values are those of the full buffer, which
:meth:`DepthBuffer.full` computes for a window.

:func:`hidden_at` is the three-valued predicate: ``True`` when ``Z[px] < depth·(1 − DEPTH_BAND)``, ``False``
when ``Z[px] > depth·(1 + DEPTH_BAND)``, ``None`` (undecided) inside the band and -- the silhouette guard, an
implementation note of contract §5.1 -- when a pixel of the 3 x 3 neighbourhood lies on the other side of the
sample's depth than the centre pixel.  :func:`occluded_points` is the
point-wise ray-cast reference used at run boundaries: some boundary crossing of the segment ``C → X`` at a
parameter in ``(eps, 1 − eps)``.
"""

from __future__ import annotations

import math

import numpy as np

from tests.reference import raycast

PX_MM = 0.1
DEPTH_BAND = 0.02
RECT_GROW = 0.25
#: Band of the point-wise reference (relative to the ray length ``|X − C|``; the contract's predicate).
POINT_EPS = 1e-5


# --------------------------------------------------------------------------- camera (spec §5.4)
def camera_model(scene: dict) -> dict:
    """``{C, R (rows right', up', forward), fs, u0, v0, near, rect (u_min, u_max, v_min, v_max)}``."""
    cam = scene["camera"]
    C = np.asarray(cam["position"], dtype=np.float64).reshape(3)
    if "target" in cam:
        fwd = np.asarray(cam["target"], dtype=np.float64).reshape(3) - C
    else:
        yaw, pitch = math.radians(float(cam["yaw_deg"])), math.radians(float(cam["pitch_deg"]))
        fwd = np.array([-math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)])
    fwd = fwd / np.linalg.norm(fwd)
    up_world = np.array([0.0, 0.0, 1.0])
    if np.linalg.norm(np.cross(fwd, up_world)) <= 1e-9:
        up_world = np.array([0.0, 1.0, 0.0])
    right = np.cross(fwd, up_world)
    right = right / np.linalg.norm(right)
    up = np.cross(right, fwd)
    rho = math.radians(float(cam.get("roll_deg", 0.0)))
    right2 = math.cos(rho) * right + math.sin(rho) * up
    up2 = -math.sin(rho) * right + math.cos(rho) * up
    W, H = (float(v) for v in scene["output"]["canvas_mm"])
    s = W / float(cam["frame_mm"][0])
    shift = cam.get("shift_mm", [0.0, 0.0])
    g = 0.5 + RECT_GROW
    return {"C": C, "R": np.stack([right2, up2, fwd]), "fs": float(cam["focal_length_mm"]) * s,
            "u0": float(shift[0]) * s, "v0": float(shift[1]) * s, "near": float(cam.get("near_m", 0.05)),
            "rect": (-g * W, g * W, -g * H, g * H)}


def project(cm: dict, X) -> tuple[np.ndarray, np.ndarray]:
    """Image ``(n, 2)`` (canvas mm) and depth ``x̃₃`` ``(n,)`` of finite world points ``X`` ``(n, 3)``."""
    X = np.asarray(X, dtype=np.float64).reshape(-1, 3)
    c = (X - cm["C"][None, :]) @ cm["R"].T
    z = c[:, 2]
    with np.errstate(divide="ignore", invalid="ignore"):
        uv = np.stack([cm["fs"] * c[:, 0] / z + cm["u0"], cm["fs"] * c[:, 1] / z + cm["v0"]], axis=1)
    return uv, z


def pixel_rays(cm: dict, uv) -> np.ndarray:
    """World directions of the camera rays through the image points ``uv`` with forward component 1."""
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    cdir = np.stack([(uv[:, 0] - cm["u0"]) / cm["fs"], (uv[:, 1] - cm["v0"]) / cm["fs"], np.ones(uv.shape[0])],
                    axis=1)
    return cdir @ cm["R"]                       # R is orthonormal: R^-1 = R^T, world = R^T c


def grid_shape(cm: dict, px_mm: float = PX_MM) -> tuple[int, int]:
    u_min, u_max, v_min, v_max = cm["rect"]
    return int(math.ceil((v_max - v_min) / px_mm - 1e-9)), int(math.ceil((u_max - u_min) / px_mm - 1e-9))


def pixel_of(cm: dict, uv, px_mm: float = PX_MM) -> tuple[np.ndarray, np.ndarray]:
    """``(iy, ix)`` of the pixels containing the image points ``uv`` (clamped to the extended canvas)."""
    uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
    u_min, _u_max, _v_min, v_max = cm["rect"]
    ny, nx = grid_shape(cm, px_mm)
    ix = np.clip(np.floor((uv[:, 0] - u_min) / px_mm), 0, nx - 1).astype(np.int64)
    iy = np.clip(np.floor((v_max - uv[:, 1]) / px_mm), 0, ny - 1).astype(np.int64)
    return iy, ix


def pixel_centres(cm: dict, iy, ix, px_mm: float = PX_MM) -> np.ndarray:
    u_min, _u_max, _v_min, v_max = cm["rect"]
    return np.stack([u_min + (np.asarray(ix) + 0.5) * px_mm, v_max - (np.asarray(iy) + 0.5) * px_mm], axis=1)


# --------------------------------------------------------------------------- the buffer
class DepthBuffer:
    """Lazy per-pixel depth buffer of a validated scene: ``Z[iy, ix]`` (arrays allowed) is the nearest depth
    over objects, plates and the ground of the ray through the pixel centre (``inf`` = nothing)."""

    def __init__(self, scene: dict, px_mm: float = PX_MM):
        self.scene = scene
        self.cam = camera_model(scene)
        self.px_mm = float(px_mm)
        self.shape = grid_shape(self.cam, self.px_mm)
        self._cache: dict[int, float] = {}

    def _compute(self, iy: np.ndarray, ix: np.ndarray) -> np.ndarray:
        D = pixel_rays(self.cam, pixel_centres(self.cam, iy, ix, self.px_mm))
        O = np.broadcast_to(self.cam["C"][None, :], D.shape)
        return raycast.first_hit_t(self.scene, O, D)

    def __getitem__(self, idx) -> np.ndarray:
        iy, ix = (np.atleast_1d(np.asarray(a, dtype=np.int64)) for a in idx)
        keys = iy * self.shape[1] + ix
        uniq = np.unique(keys)
        missing = np.array([k for k in uniq.tolist() if k not in self._cache], dtype=np.int64)
        if missing.shape[0]:
            vals = self._compute(missing // self.shape[1], missing % self.shape[1])
            self._cache.update(zip(missing.tolist(), vals.tolist()))
        return np.array([self._cache[k] for k in keys.tolist()], dtype=np.float64)

    def full(self, window=None) -> np.ndarray:
        """The buffer itself over ``window = (iy0, iy1, ix0, ix1)`` (default: the whole extended canvas)."""
        iy0, iy1, ix0, ix1 = window or (0, self.shape[0], 0, self.shape[1])
        IY, IX = np.meshgrid(np.arange(iy0, iy1), np.arange(ix0, ix1), indexing="ij")
        return self._compute(IY.ravel(), IX.ravel()).reshape(IY.shape)


def hidden_states(Z: DepthBuffer, uv, depth, guard: bool = True) -> tuple[np.ndarray, np.ndarray]:
    """Vectorised :func:`hidden_at`: ``(decided, hidden)`` bool arrays.

    ``guard`` (default) also leaves a sample undecided when some pixel of the 3 x 3 neighbourhood of its pixel
    lies on the other side of the sample's depth than the centre pixel (a "hidden" centre with a neighbour
    ``Z >= depth``, a "visible" centre with a neighbour ``Z <= depth``): a depth edge then passes within
    1.5 px of the sample and the pixel-centre ray may pass on the other side of it than the sample's own ray
    -- an occluder's silhouette (the rim of a sphere, the silhouette generator of a cylinder, a face seen
    edge-on) or a surface seen at a grazing angle (the ground near the horizon), the two documented limits
    of the reference.  ``guard=False`` is the bare band rule."""
    depth = np.asarray(depth, dtype=np.float64).reshape(-1)
    iy, ix = pixel_of(Z.cam, uv, Z.px_mm)
    z = Z[iy, ix]
    hid = z < depth * (1.0 - DEPTH_BAND)
    vis = z > depth * (1.0 + DEPTH_BAND)
    decided = hid | vis
    if guard and depth.shape[0]:
        ny, nx = Z.shape
        nearer = np.zeros(depth.shape[0], dtype=bool)
        farther = np.zeros(depth.shape[0], dtype=bool)
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                zz = Z[np.clip(iy + dy, 0, ny - 1), np.clip(ix + dx, 0, nx - 1)]
                nearer |= zz <= depth
                farther |= zz >= depth
        decided &= ~((hid & farther) | (vis & nearer))
    return decided, hid & decided


def hidden_at(Z: DepthBuffer, uv, depth, guard: bool = True):
    """``True`` (hidden) when ``Z[px] < depth·(1 − 0.02)``, ``False`` when ``Z[px] > depth·(1 + 0.02)``,
    ``None`` inside the band (contract §5.1.11) -- and, with ``guard``, ``None`` on a silhouette / grazing
    pixel (see :func:`hidden_states`)."""
    decided, hid = hidden_states(Z, np.asarray(uv, dtype=np.float64).reshape(1, 2), [depth], guard)
    return bool(hid[0]) if bool(decided[0]) else None


# --------------------------------------------------------------------------- point-wise reference
def occluded_points(scene: dict, X, eps: float = POINT_EPS) -> np.ndarray:
    """Bool per world point ``X`` ``(n, 3)``: the segment from the camera centre to ``X`` crosses some
    occluder boundary at a parameter in ``(eps, 1 − eps)`` (``X`` at parameter 1)."""
    X = np.asarray(X, dtype=np.float64).reshape(-1, 3)
    C = camera_model(scene)["C"]
    O = np.broadcast_to(C[None, :], X.shape)
    return raycast.first_hit_t(scene, O, X - C[None, :], eps) < 1.0 - eps


# --------------------------------------------------------------------------- back projection helpers
def on_plane(cm: dict, uv, normal, offset) -> np.ndarray:
    """World points of the image points ``uv`` on the plane ``normal·x + offset = 0`` (``nan`` when the
    camera ray is parallel to it or meets it behind the camera)."""
    D = pixel_rays(cm, uv)
    n = np.asarray(normal, dtype=np.float64).reshape(3)
    den = D @ n
    with np.errstate(divide="ignore", invalid="ignore"):
        t = -(cm["C"] @ n + float(offset)) / den
    t = np.where((den != 0.0) & (t > 0.0), t, np.nan)
    return cm["C"][None, :] + t[:, None] * D


def on_line(cm: dict, uv, A, B) -> np.ndarray:
    """World points of the image points ``uv`` on the 3-D line ``A + λ(B − A)`` (closest point of the line to
    the camera ray through ``uv``)."""
    D = pixel_rays(cm, uv)
    A = np.asarray(A, dtype=np.float64).reshape(3)
    E = np.asarray(B, dtype=np.float64).reshape(3) - A
    w0 = A - cm["C"]
    a = float(E @ E)
    b = D @ E
    c = np.einsum("ij,ij->i", D, D)
    d = float(E @ w0)
    e = D @ w0
    with np.errstate(divide="ignore", invalid="ignore"):
        lam = (b * e - c * d) / (a * c - b * b)
    return A[None, :] + lam[:, None] * E[None, :]

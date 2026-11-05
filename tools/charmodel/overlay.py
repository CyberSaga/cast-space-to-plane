"""The overlay check of a character model against its design sheet, and mesh smoothness metrics (character-free).

**Overlay.** Each drawn view of the sheet (front, side, back, ...) is near-orthographic, so the model is rendered
**orthographically** (the limit of a very long lens: no lens scaling error) straight into the sheet's pixel grid: a
model point ``P`` (metres, Z up) is first divided by the character's figure scale (the model is built at the sheet's
scale and then scaled to its stated height, :attr:`OverlaySpec.figure_scale`), then mapped to the sheet pixel
``u = view.origin_px + (P . view.h_axis) / s``, ``v = sheet.ground_row - P_z / s`` (``s`` = :attr:`SheetSpec.scale`,
metres per pixel), and a numpy z-buffer keeps the nearest surface along ``view.depth_axis``.  Every pixel holds the
**class** of its material (:attr:`OverlaySpec.material_classes`: hair, skin, white, ...).  The sheet is read the same
way: a flood fill of its light background grid from the border of the view's box gives the figure silhouette, and a
nearest-colour classification (:attr:`SheetSpec.classes`) gives the class regions; pixels of the ink-line class take
the class of their neighbours on both images.  The metrics compare the two images row by row and column by column:

* the figure silhouette per row (left / right edge offsets, outward positive) in the character's row bands;
* per-class IoU;
* class outlines per row (e.g. the hair's outer outline, a garment's outer and inner edge, a skirt's flare);
* class lower edges per column (e.g. the tips of a hair cut, a hem);
* named landmarks (the top / bottom / leftmost / rightmost pixel of a class in a window).

Offsets are reported in **mm on the final model** (sheet pixels x ``s`` x the figure scale x 1000).  Outputs per view:
``overlay_<view>.png`` (the sheet at 50 % opacity, the class-coloured render at 50 % over it, the model's outline in
green and the sheet's silhouette in magenta), zoomed crops ``overlay_<view>_<zoom>.png``, ``diff_<view>.png`` (sheet
only red, model only blue, both of one class light grey, both but different classes orange) and ``report.md`` +
``report.json`` with every number and the pass / fail of the character's criteria.  The sheet stays outside the
repository: the images written here contain it, so :func:`run_overlay` refuses an output directory inside ``repo``.

**Smoothness.** :func:`dihedral_stats`: the angles between adjacent triangles (castplane's fan triangulation) that
share a smooth group, i.e. what shading must hide; group boundaries are designed lines and do not count.
:func:`outline_turns`: the 2D outline of one part (alone) in a perspective camera: its silhouette edges on the
boundary of its projected region, chained at shared vertices, and the turning angle between successive outline
segments; turns above ``tip_deg`` are tips (designed points or notches) and are reported apart, with the straight
flanks between successive tips (a sawtooth has straight flanks, tapered locks curved ones).

numpy only; Pillow is imported lazily (images and the sheet).
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from . import meshkit as mk

__all__ = ["SheetView", "SheetSpec", "Outline", "LowerEdge", "Landmark", "Probe", "Criterion", "OverlaySpec",
           "ViewRender", "SheetRead", "FrontView", "render_view", "read_sheet", "load_sheet", "compare_view",
           "paint_classes", "front_view", "dihedral_stats", "outline_turns", "mesh_distance", "shaded_probe",
           "evaluate_criteria", "criteria_summary", "run_overlay", "write_report"]

MODEL_LINE = (0, 200, 0)          # the model's outline on the overlay
SHEET_LINE = (230, 0, 200)        # the sheet's silhouette on the overlay
DIFF_SHEET = (225, 40, 40)        # sheet only
DIFF_MODEL = (40, 90, 230)        # model only
DIFF_BOTH = (215, 215, 215)       # both, same class
DIFF_CLASS = (250, 165, 30)       # both, different classes


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SheetView:
    """One drawn view of the sheet and its orthographic camera.

    * ``name``: the view's id (``front``, ``left``, ``back``, ...); ``title``: what the sheet calls it;
    * ``h_axis``: the world unit vector drawn towards the image's right (``(1, 0, 0)``: a front view);
    * ``origin_px``: the sheet column of ``h = 0``;
    * ``box``: ``(x0, y0, x1, y1)`` sheet pixels (end exclusive) holding this figure and nothing else;
    * ``label_boxes``: sheet-pixel boxes in which neutral greys of :attr:`SheetSpec.label_greys` count as background
      (labels and their leader lines touching the figure);
    * ``hide_materials``: materials left out of the model's render (e.g. a view without the outer garment)."""

    name: str
    h_axis: tuple
    origin_px: float
    box: tuple
    title: str = ""
    label_boxes: tuple = ()
    hide_materials: tuple = ()

    @property
    def depth_axis(self) -> np.ndarray:
        """Unit vector into the picture (``z x h``): smaller ``P . depth_axis`` is nearer the viewer."""
        h = np.asarray(self.h_axis, dtype=np.float64)
        return np.cross([0.0, 0.0, 1.0], h)


@dataclass(frozen=True)
class SheetSpec:
    """The design sheet's drawing conventions.

    * ``scale``: metres per sheet pixel at the sheet scale (one scale for every view);
    * ``ground_row``: the sheet row of ``z = 0``;
    * ``views``: the :class:`SheetView` s;
    * ``classes``: ``{class: ((r, g, b), ...)}`` representative colours, the first one paints the class; a colour
      ``(r, g, b, z_lo, z_hi)`` counts only at those heights (sheet-scale metres);
    * ``background_greys``: exact neutral grey values of the paper and its grid (flood-filled from the box border);
    * ``label_greys``: ``(lo, hi)`` neutral greys that count as background inside a view's ``label_boxes``;
    * ``line_class``: the ink-line class: its pixels take the class of a neighbour (both images), up to
      ``line_fill_px`` pixels deep; the sheet's outermost ``ring_px`` pixels (the anti-aliased silhouette line, whose
      mixed colours classify as anything) count as ink too, so they take the class inside them;
    * ``relabel``: ``((from, to, z_lo, z_hi), ...)`` reclassifies sheet pixels by height (sheet-scale metres), e.g.
      white below the knee is the socks."""

    scale: float
    ground_row: float
    views: tuple
    classes: dict
    background_greys: tuple
    label_greys: tuple
    line_class: str = "line"
    line_fill_px: int = 6
    ring_px: int = 2
    relabel: tuple = ()

    def view(self, name: str) -> SheetView:
        for v in self.views:
            if v.name == name:
                return v
        raise KeyError(f"no sheet view {name!r}")

    @property
    def class_names(self) -> tuple:
        return tuple(self.classes)


@dataclass(frozen=True)
class Outline:
    """A class outline per row: ``cls`` (a class or ``"figure"``) in ``view`` between ``z_lo`` and ``z_hi``
    (sheet-scale metres), restricted to ``h_range`` (metres along the view's h axis, ``None`` = the whole box).
    ``sides``: ``"left"`` / ``"right"`` (image sides; the outermost pixel of the row).  ``inner``: also the inner end
    of the outermost run (e.g. a sleeve's inner edge), with gaps of up to ``gap_px`` pixels bridged."""

    name: str
    view: str
    cls: str
    z_lo: float
    z_hi: float
    sides: tuple = ("left", "right")
    h_range: Any = None
    inner: bool = False
    gap_px: int = 2


@dataclass(frozen=True)
class LowerEdge:
    """The lowest pixel of ``cls`` per column, in ``view``, for the columns whose ``h`` lies in one of ``ranges``
    (metres) and between ``z_lo`` and ``z_hi``."""

    name: str
    view: str
    cls: str
    ranges: tuple
    z_lo: float
    z_hi: float


@dataclass(frozen=True)
class Landmark:
    """A named point: the ``kind`` (``top``, ``bottom``, ``left``, ``right``) extreme pixel of ``cls`` (or
    ``"figure"``) in ``view`` inside the window ``h_range`` x ``z_range`` (metres, sheet scale).  ``axes``: the
    offsets that matter (``"h"``, ``"z"`` or ``"hz"``); the other coordinate is the mean of the extreme pixels.
    ``min_run`` (metres): only rows (``top`` / ``bottom``) or columns (``left`` / ``right``) whose longest run of the
    class in the window is at least this long count, and the other coordinate is that run's centre (e.g. the bottom
    of a cuff, not a stray pixel of its colour on a finger's outline)."""

    name: str
    view: str
    kind: str
    cls: str
    h_range: tuple
    z_range: tuple
    axes: str = "hz"
    min_run: float = 0.0


@dataclass(frozen=True)
class Probe:
    """A shaded-render colour sample: the median colour of a ``window`` px square around the projection of ``point``
    (sheet-scale metres) in the camera preset ``preset`` (an ``(azimuth, elevation, framing, focal)`` tuple) of the
    character's preview, rendered at ``size``."""

    name: str
    preset: tuple
    point: tuple
    window: int = 9
    size: tuple = (400, 600)


@dataclass(frozen=True)
class Criterion:
    """A pass condition: the metric values at ``keys`` (dotted paths into the report, ``*`` matches every key of a
    level) reduced by ``op``: ``"<="`` (the largest value at most ``limit``), ``">="`` (the smallest at least
    ``limit``), ``"abs<="`` (the largest absolute value), ``"between"`` (every value in ``limit = (lo, hi)``).
    ``text`` is the criterion as worded for people, ``note`` its grounding (the baseline, the sheet's precision, a
    Decision)."""

    id: str
    text: str
    keys: tuple
    op: str
    limit: Any
    note: str = ""


@dataclass(frozen=True)
class OverlaySpec:
    """What a character supplies for the overlay check (``tools/<name>_model/overlay.py``)."""

    sheet: SheetSpec
    figure_scale: Callable                  # rig -> the model's scale over the sheet scale
    material_classes: dict                  # material -> class (a sheet class or the line class)
    bands: tuple                            # ((name, z_lo, z_hi), ...) sheet-scale metres, the silhouette bands
    iou_classes: Any = ()                   # classes (all views) or {view: classes}
    outlines: tuple = ()
    lower_edges: tuple = ()
    landmarks: tuple = ()
    zooms: tuple = ()                       # ((view, name, (h_lo, h_hi, z_lo, z_hi), magnification), ...)
    smooth_parts: tuple = ()                # ((label, (part name, ...)[, ((zone, z_lo, z_hi), ...)]), ...)
    smooth_views: tuple = ()                # ((name, (azimuth, elevation, framing, focal)), ...)
    cameras: Callable = None                # rig -> charmodel.preview.Cameras
    materials: dict = field(default_factory=dict)
    light: tuple = (0.0, -1.0, 1.0)
    probes: tuple = ()
    extras: Callable = None                 # (model, rig) -> dict of more metrics (report key "extras")
    criteria: tuple = ()
    tip_deg: float = 60.0
    min_seg_px: float = 1.0
    ref_px: int = 1200
    smooth_deg: float = 30.0
    crease_deg: float = 60.0
    visible_only: bool = True               # smoothness counts only what the whole model shows (:func:`front_view`)
    visibility_views: tuple = ()            # ((name, preset), ...) more cameras for the dihedrals' visible faces
    visibility_ss: float = 2.0
    notes: tuple = ()                       # lines for the report's header
    outline_classes: tuple = ()             # classes whose outlines the overlay images draw too
    max_hole_px: int = 0                    # class regions: holes up to this many pixels are filled


# ---------------------------------------------------------------------------
# mapping
# ---------------------------------------------------------------------------

def _mm(spec: OverlaySpec, rig) -> float:
    """Millimetres on the final model per sheet pixel."""
    return spec.sheet.scale * float(spec.figure_scale(rig)) * 1000.0


def _rows_z(sheet: SheetSpec, box, z_lo: float, z_hi: float):
    """Row indices (relative to ``box``) whose centre lies in ``[z_lo, z_hi]`` (sheet-scale metres)."""
    y0, y1 = box[1], box[3]
    rows = np.arange(y0, y1)
    z = (sheet.ground_row - (rows + 0.5)) * sheet.scale
    return np.nonzero((z >= z_lo) & (z <= z_hi))[0]


def _cols_h(sheet: SheetSpec, view: SheetView, box, ranges):
    """Column indices (relative to ``box``) whose centre ``h`` lies in one of ``ranges``."""
    cols = np.arange(box[0], box[2])
    h = (cols + 0.5 - view.origin_px) * sheet.scale
    keep = np.zeros(len(cols), dtype=bool)
    for lo, hi in ranges:
        keep |= (h >= lo) & (h <= hi)
    return np.nonzero(keep)[0]


def _h_of(sheet: SheetSpec, view: SheetView, box, u_rel):
    return (np.asarray(u_rel, dtype=np.float64) + box[0] - view.origin_px) * sheet.scale


def _z_of(sheet: SheetSpec, box, v_rel):
    return (sheet.ground_row - (np.asarray(v_rel, dtype=np.float64) + box[1])) * sheet.scale


# ---------------------------------------------------------------------------
# the model's orthographic class render
# ---------------------------------------------------------------------------

@dataclass
class ViewRender:
    """The model in one sheet view: ``cls`` (H, W) class index per pixel (-1 = empty), ``part`` (H, W) part index,
    ``depth`` (H, W), the view's ``box``, the class names and ``figure``, the silhouette read as the sheet's is (its
    enclosed holes filled, its main part only)."""

    view: SheetView
    box: tuple
    cls: np.ndarray
    part: np.ndarray
    depth: np.ndarray
    class_names: tuple
    figure: np.ndarray = None
    cache: dict = field(default_factory=dict, repr=False)


def _class_index(spec: OverlaySpec):
    names = spec.sheet.class_names
    if spec.sheet.line_class not in names:
        names = names + (spec.sheet.line_class,)
    return names, {n: k for k, n in enumerate(names)}


def render_view(model, spec: OverlaySpec, view, rig) -> ViewRender:
    """Orthographic z-buffer render of ``model`` (an Assembly) into ``view``'s box of the sheet pixel grid (pixel
    centres sampled; the nearest surface along ``view.depth_axis`` wins), each pixel holding its part's class; the
    pixels of the ink-line class (lashes, brows) take their neighbours' class, as the sheet's ink does."""
    sheet = spec.sheet
    view = sheet.view(view) if isinstance(view, str) else view
    names, index = _class_index(spec)
    x0, y0, x1, y1 = view.box
    W, H = x1 - x0, y1 - y0
    f = float(spec.figure_scale(rig))
    h_ax = np.asarray(view.h_axis, dtype=np.float64)
    d_ax = view.depth_axis
    depth = np.full((H, W), np.inf)
    cls = np.full((H, W), -1, dtype=np.int32)
    part = np.full((H, W), -1, dtype=np.int32)
    for k, p in enumerate(model.parts):
        if p.material in view.hide_materials:
            continue
        c = index[spec.material_classes[p.material]]
        P = p.mesh.vertices / f
        U = view.origin_px + (P @ h_ax) / sheet.scale - x0
        V = sheet.ground_row - P[:, 2] / sheet.scale - y0
        D = P @ d_ax
        tris, _ = p.mesh.triangles()
        _raster_ortho(U, V, D, tris, depth, cls, part, c, k)
    cls = _fill_lines(cls, index[sheet.line_class], sheet.line_fill_px)     # as the sheet's ink
    return ViewRender(view, (x0, y0, x1, y1), cls, part, depth, names, _silhouette(cls >= 0, view, view.box))


def _raster_ortho(U, V, D, tris, depth, cls, part, c, k):
    H, W = depth.shape
    A, B, C = tris[:, 0], tris[:, 1], tris[:, 2]
    umin = np.floor(np.minimum(np.minimum(U[A], U[B]), U[C]) - 0.5).astype(np.int64)
    umax = np.ceil(np.maximum(np.maximum(U[A], U[B]), U[C]) - 0.5).astype(np.int64)
    vmin = np.floor(np.minimum(np.minimum(V[A], V[B]), V[C]) - 0.5).astype(np.int64)
    vmax = np.ceil(np.maximum(np.maximum(V[A], V[B]), V[C]) - 0.5).astype(np.int64)
    for t in range(len(tris)):
        ja, jb = max(int(umin[t]), 0), min(int(umax[t]), W - 1)
        ia, ib = max(int(vmin[t]), 0), min(int(vmax[t]), H - 1)
        if ja > jb or ia > ib:
            continue
        a, b, cc = A[t], B[t], C[t]
        ua, va, ub, vb, uc, vc = U[a], V[a], U[b], V[b], U[cc], V[cc]
        area = (ub - ua) * (vc - va) - (vb - va) * (uc - ua)
        if abs(area) < 1e-12:
            continue
        X, Y = np.meshgrid(np.arange(ja, jb + 1) + 0.5, np.arange(ia, ib + 1) + 0.5)
        w0 = ((ub - X) * (vc - Y) - (vb - Y) * (uc - X)) / area
        w1 = ((uc - X) * (va - Y) - (vc - Y) * (ua - X)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
        if not inside.any():
            continue
        z = w0 * D[a] + w1 * D[b] + w2 * D[cc]
        sub = depth[ia:ib + 1, ja:jb + 1]
        win = inside & (z < sub)
        if not win.any():
            continue
        sub[win] = z[win]
        cls[ia:ib + 1, ja:jb + 1][win] = c
        part[ia:ib + 1, ja:jb + 1][win] = k


def _fill_lines(cls: np.ndarray, line: int, depth_px: int) -> np.ndarray:
    """Pixels of class ``line`` take the most frequent class among their 4-neighbours that are neither line nor
    empty (the lowest class index on a tie), repeated ``depth_px`` times."""
    out = cls.copy()
    n_cls = int(max(out.max(), line)) + 1
    for _ in range(depth_px):
        todo = out == line
        if not todo.any():
            break
        ys, xs = np.nonzero(todo)
        counts = np.zeros((len(ys), n_cls), dtype=np.int8)
        H, W = out.shape
        for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            y, x = ys + dy, xs + dx
            ok = (y >= 0) & (y < H) & (x >= 0) & (x < W)
            nb = np.full(len(ys), -1, dtype=out.dtype)
            nb[ok] = out[y[ok], x[ok]]
            good = (nb >= 0) & (nb != line)
            counts[np.nonzero(good)[0], nb[good]] += 1
        best = np.argmax(counts, axis=1)
        has = counts.max(axis=1) > 0
        out[ys[has], xs[has]] = best[has]
    return out


# ---------------------------------------------------------------------------
# the sheet
# ---------------------------------------------------------------------------

@dataclass
class SheetRead:
    """The sheet in one view's box: ``figure`` (H, W) bool silhouette, ``cls`` (H, W) class index (-1 outside)."""

    view: SheetView
    box: tuple
    figure: np.ndarray
    cls: np.ndarray
    rgb: np.ndarray
    class_names: tuple
    cache: dict = field(default_factory=dict, repr=False)


def load_sheet(path) -> np.ndarray:
    """The sheet as an (H, W, 3) uint8 array."""
    from PIL import Image

    with Image.open(path) as im:
        return np.asarray(im.convert("RGB")).copy()


def read_sheet(sheet_rgb: np.ndarray, spec: OverlaySpec, view) -> SheetRead:
    """Silhouette and classes of ``view``'s figure on the sheet (``sheet_rgb`` from :func:`load_sheet`)."""
    sheet = spec.sheet
    view = sheet.view(view) if isinstance(view, str) else view
    names, index = _class_index(spec)
    x0, y0, x1, y1 = view.box
    rgb = sheet_rgb[y0:y1, x0:x1].astype(np.int16)
    H, W = rgb.shape[:2]
    neutral = (rgb.max(axis=2) - rgb.min(axis=2)) == 0
    grey = rgb[..., 0]
    bg = np.zeros((H, W), dtype=bool)
    for g in sheet.background_greys:
        bg |= neutral & (grey == g)
    lo, hi = sheet.label_greys
    for bx0, by0, bx1, by1 in view.label_boxes:
        sl = (slice(max(by0 - y0, 0), max(by1 - y0, 0)), slice(max(bx0 - x0, 0), max(bx1 - x0, 0)))
        bg[sl] |= neutral[sl] & (grey[sl] >= lo) & (grey[sl] <= hi)
    figure = _silhouette(~bg, view, (x0, y0, x1, y1))
    # nearest representative colour (a colour with a z band counts only at those heights)
    keys, cols, zlo, zhi = [], [], [], []
    for n, reps in sheet.classes.items():
        for c in reps:
            keys.append(index[n])
            cols.append(c[:3])
            zlo.append(c[3] if len(c) > 3 else -np.inf)
            zhi.append(c[4] if len(c) > 4 else np.inf)
    keys = np.asarray(keys, dtype=np.int32)
    cols = np.asarray(cols, dtype=np.float32)
    zlo, zhi = np.asarray(zlo), np.asarray(zhi)
    z = (sheet.ground_row - (np.arange(y0, y1) + 0.5)) * sheet.scale
    cls = np.full((H, W), -1, dtype=np.int32)
    f32 = rgb.astype(np.float32)
    c2 = (cols * cols).sum(axis=1)
    for r0 in range(0, H, 128):
        blk = f32[r0:r0 + 128]
        n = blk.shape[0]
        X = blk.reshape(-1, 3)
        d = (c2[None, :] - 2.0 * (X @ cols.T)).reshape(n, W, -1)      # |x - c|^2 - |x|^2
        zz = z[r0:r0 + n]
        off = (zz[:, None] < zlo[None, :]) | (zz[:, None] > zhi[None, :])
        d = np.where(off[:, None, :], np.inf, d)
        cls[r0:r0 + n] = keys[np.argmin(d, axis=-1)]
    cls[~figure] = -1
    if sheet.ring_px:
        inner = figure.copy()
        for _ in range(sheet.ring_px):
            inner = _erode(inner)
        cls[figure & ~inner] = index[sheet.line_class]
    if sheet.relabel:
        for a, b, zl, zh in sheet.relabel:
            rows = (z >= zl) & (z <= zh)
            sel = rows[:, None] & (cls == index[a])
            cls[sel] = index[b]
    cls = _fill_lines(cls, index[sheet.line_class], sheet.line_fill_px)
    return SheetRead(view, (x0, y0, x1, y1), figure, cls, sheet_rgb[y0:y1, x0:x1], names)


def _components(mask: np.ndarray) -> np.ndarray:
    """4-connected components of a bool image: an int32 label image (-1 off the mask), from runs per row joined by a
    union-find (fast where a flood fill in Python is not)."""
    H, W = mask.shape
    pad = np.zeros((H, W + 2), dtype=np.int8)
    pad[:, 1:-1] = mask
    d = np.diff(pad, axis=1)
    rs, ss = np.nonzero(d == 1)
    re_, es = np.nonzero(d == -1)
    order_s = np.lexsort((ss, rs))
    order_e = np.lexsort((es, re_))
    rows, starts, ends = rs[order_s], ss[order_s], es[order_e]
    n = len(rows)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    first = np.searchsorted(rows, np.arange(H + 1))
    for r in range(H - 1):
        i, i1 = int(first[r]), int(first[r + 1])
        j, j1 = i1, int(first[r + 2])
        while i < i1 and j < j1:
            if starts[i] < ends[j] and starts[j] < ends[i]:
                a, b = find(i), find(j)
                if a != b:
                    parent[max(a, b)] = min(a, b)
            if ends[i] < ends[j]:
                i += 1
            else:
                j += 1
    lab = np.full((H, W), -1, dtype=np.int32)
    for k in range(n):
        lab[rows[k], starts[k]:ends[k]] = find(k)
    return lab


def _silhouette(fg: np.ndarray, view: SheetView, box) -> np.ndarray:
    """The silhouette of a foreground mask as the sheet's is read: everything a flood fill of the background from the
    box's border cannot reach (enclosed holes count as figure), then only the figure's main part
    (:func:`_component`)."""
    H, W = fg.shape
    frame = np.ones((H + 2, W + 2), dtype=bool)
    frame[1:-1, 1:-1] = ~fg
    lab = _components(frame)
    return _component(lab[1:-1, 1:-1] != lab[0, 0], view, box)


def _component(figure: np.ndarray, view: SheetView, box) -> np.ndarray:
    """The 4-connected part of ``figure`` holding the figure pixel nearest the view's origin column at the box's
    middle height (drops labels and strokes of other figures that reach into the box)."""
    H = figure.shape[0]
    ys, xs = np.nonzero(figure[H // 2 - 40:H // 2 + 40])
    if not len(ys):
        return figure
    j0 = view.origin_px - box[0]
    k = int(np.argmin(np.abs(xs - j0) + np.abs(ys - 40)))
    lab = _components(figure)
    return lab == lab[int(ys[k]) + H // 2 - 40, int(xs[k])]


def paint_classes(cls: np.ndarray, spec: OverlaySpec, background=None) -> np.ndarray:
    """(H, W, 3) uint8: every class pixel painted with its class's first representative colour, the rest with the
    sheet's first background grey (a synthetic sheet for tests, and the overlay's model layer)."""
    names, index = _class_index(spec)
    pal = np.zeros((len(names), 3), dtype=np.uint8)
    for n, reps in spec.sheet.classes.items():
        pal[index[n]] = reps[0][:3]
    g = spec.sheet.background_greys[0] if background is None else background
    out = np.empty(cls.shape + (3,), dtype=np.uint8)
    out[:] = g
    m = cls >= 0
    out[m] = pal[cls[m]]
    return out


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

def _stats(values_px, mm: float, where=None) -> dict:
    """max / mean / p95 of |values|, the signed mean, all in mm; ``where`` (sheet-scale z or h per value) gives the
    position of the largest."""
    v = np.asarray(values_px, dtype=np.float64)
    if v.size == 0:
        return {"n": 0, "max": None, "mean": None, "p95": None, "signed_mean": None}
    a = np.abs(v)
    k = int(np.argmax(a))
    out = {"n": int(v.size), "max": round(float(a[k]) * mm, 2), "mean": round(float(a.mean()) * mm, 2),
           "p95": round(float(np.percentile(a, 95)) * mm, 2), "signed_mean": round(float(v.mean()) * mm, 2)}
    if where is not None:
        out["at"] = round(float(np.asarray(where)[k]), 4)
        out["signed_at_max"] = round(float(v[k]) * mm, 2)
    return out


def _row_extent(mask: np.ndarray):
    """``(has, first, last)`` per row of a bool image (first / last True column)."""
    has = mask.any(axis=1)
    first = np.argmax(mask, axis=1)
    last = mask.shape[1] - 1 - np.argmax(mask[:, ::-1], axis=1)
    return has, first, last


def _inner_end(row: np.ndarray, start: int, step: int, gap: int) -> int:
    """From ``start`` (a True pixel) walk by ``step`` while the row stays True, bridging gaps up to ``gap``;
    returns the last True index."""
    n = len(row)
    j, last, miss = start, start, 0
    while 0 <= j < n:
        if row[j]:
            last, miss = j, 0
        else:
            miss += 1
            if miss > gap:
                break
        j += step
    return last


def _erode(mask: np.ndarray) -> np.ndarray:
    """Erosion with the 3 x 3 cross."""
    e = mask.copy()
    e[1:, :] &= mask[:-1, :]
    e[:-1, :] &= mask[1:, :]
    e[:, 1:] &= mask[:, :-1]
    e[:, :-1] &= mask[:, 1:]
    return e


def _open(mask: np.ndarray) -> np.ndarray:
    """Morphological opening with the 3 x 3 cross: drops the one-pixel strings that the nearest-colour classification
    leaves along anti-aliased boundaries (applied to both images alike)."""
    e = _erode(mask)
    d = e.copy()
    d[1:, :] |= e[:-1, :]
    d[:-1, :] |= e[1:, :]
    d[:, 1:] |= e[:, :-1]
    d[:, :-1] |= e[:, 1:]
    return d


def _fill_holes(mask: np.ndarray, max_px: int) -> np.ndarray:
    """``mask`` with its holes (components of the complement that do not touch the border) of at most ``max_px``
    pixels filled (strand lines and highlights drawn inside a region)."""
    if max_px <= 0:
        return mask
    lab = _components(~mask)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    ids, counts = np.unique(lab[lab >= 0], return_counts=True)
    small = ids[(counts <= max_px) & ~np.isin(ids, border)]
    return mask | np.isin(lab, small)


def _mask(read_or_render, cls_name: str, index, max_hole: int = 0) -> np.ndarray:
    """The figure, or a class region (opened, :func:`_open`, and its holes up to ``max_hole`` pixels filled)."""
    if cls_name == "figure":
        return read_or_render.figure
    key = (cls_name, max_hole)
    if key not in read_or_render.cache:
        read_or_render.cache[key] = _fill_holes(_open(read_or_render.cls == index[cls_name]), max_hole)
    return read_or_render.cache[key]


def compare_view(sheet_read: SheetRead, render: ViewRender, spec: OverlaySpec, rig) -> dict:
    """Every metric of one view (see the module docstring), offsets in mm on the final model."""
    sheet = spec.sheet
    view = sheet_read.view
    box = sheet_read.box
    mm = _mm(spec, rig)
    _, index = _class_index(spec)
    sfig = sheet_read.figure
    mfig = render.figure
    out = {"box": list(box), "h_axis": list(view.h_axis), "mm_per_px": round(mm, 5)}

    # silhouette per row and band
    s_has, s_first, s_last = _row_extent(sfig)
    m_has, m_first, m_last = _row_extent(mfig)
    zrow = _z_of(sheet, box, np.arange(sfig.shape[0]) + 0.5)
    sil = {}
    for bname, zl, zh in spec.bands:
        rows = _rows_z(sheet, box, zl, zh)
        both = rows[s_has[rows] & m_has[rows]]
        left = (s_first[both] - m_first[both]).astype(np.float64)        # + = the model sticks out further left
        right = (m_last[both] - s_last[both]).astype(np.float64)         # + = the model sticks out further right
        st = _stats(np.concatenate([left, right]), mm, np.concatenate([zrow[both], zrow[both]]))
        st["left"] = _stats(left, mm, zrow[both])
        st["right"] = _stats(right, mm, zrow[both])
        st["width"] = _stats(0.5 * (left + right), mm, zrow[both])
        st["missing_rows"] = int(len(rows) - len(both))
        st["sheet_only_rows"] = int((s_has[rows] & ~m_has[rows]).sum())
        st["model_only_rows"] = int((~s_has[rows] & m_has[rows]).sum())
        sil[bname] = st
    out["silhouette"] = sil

    # per-class IoU
    iou = {}
    iou_classes = spec.iou_classes.get(view.name, ()) if isinstance(spec.iou_classes, dict) else spec.iou_classes
    for c in iou_classes:
        a, b = _mask(sheet_read, c, index, spec.max_hole_px), _mask(render, c, index, spec.max_hole_px)
        u = int((a | b).sum())
        iou[c] = None if u == 0 else round(float((a & b).sum()) / u, 4)
    fu = int((sfig | mfig).sum())
    iou["figure"] = round(float((sfig & mfig).sum()) / max(fu, 1), 4)
    out["iou"] = iou

    # class outlines per row
    outl = {}
    for o in spec.outlines:
        if o.view != view.name:
            continue
        sm, mm_ = _mask(sheet_read, o.cls, index, spec.max_hole_px), _mask(render, o.cls, index, spec.max_hole_px)
        if o.h_range is not None:
            cols = _cols_h(sheet, view, box, [o.h_range])
            keep = np.zeros(sm.shape[1], dtype=bool)
            keep[cols] = True
            sm, mm_ = sm & keep[None, :], mm_ & keep[None, :]
        rows = _rows_z(sheet, box, o.z_lo, o.z_hi)
        sh, sf, sl_ = _row_extent(sm)
        mh, mf, ml = _row_extent(mm_)
        both = rows[sh[rows] & mh[rows]]
        res = {"missing_rows": int(len(rows) - len(both))}
        allv, allz = [], []
        for side in o.sides:
            if side == "left":
                v = (sf[both] - mf[both]).astype(np.float64)
            else:
                v = (ml[both] - sl_[both]).astype(np.float64)
            res[side] = _stats(v, mm, zrow[both])
            allv.append(v)
            allz.append(zrow[both])
            if o.inner:
                vi = []
                for r in both:
                    if side == "left":
                        si = _inner_end(sm[r], int(sf[r]), 1, o.gap_px)
                        mi = _inner_end(mm_[r], int(mf[r]), 1, o.gap_px)
                        vi.append(mi - si)        # + = the model's inner edge further in (to the right)
                    else:
                        si = _inner_end(sm[r], int(sl_[r]), -1, o.gap_px)
                        mi = _inner_end(mm_[r], int(ml[r]), -1, o.gap_px)
                        vi.append(si - mi)        # + = the model's inner edge further in (to the left)
                res[side + "_inner"] = _stats(vi, mm, zrow[both])
        res.update({k: v for k, v in _stats(np.concatenate(allv) if allv else [], mm,
                                             np.concatenate(allz) if allz else None).items()})
        if len(allv) == 2:
            res["width"] = _stats(0.5 * (allv[0] + allv[1]), mm, zrow[both])
        outl[o.name] = res
    out["outlines"] = outl

    # class lower edges per column
    low = {}
    for e in spec.lower_edges:
        if e.view != view.name:
            continue
        sm, mm_ = _mask(sheet_read, e.cls, index, spec.max_hole_px), _mask(render, e.cls, index, spec.max_hole_px)
        rows = _rows_z(sheet, box, e.z_lo, e.z_hi)
        keep = np.zeros(sm.shape[0], dtype=bool)
        keep[rows] = True
        sm, mm_ = sm & keep[:, None], mm_ & keep[:, None]
        cols = _cols_h(sheet, view, box, e.ranges)
        s_any, m_any = sm[:, cols].any(axis=0), mm_[:, cols].any(axis=0)
        s_low = sm.shape[0] - 1 - np.argmax(sm[::-1, cols], axis=0)
        m_low = mm_.shape[0] - 1 - np.argmax(mm_[::-1, cols], axis=0)
        both = s_any & m_any
        dz = (s_low[both] - m_low[both]).astype(np.float64)              # + = the model's edge higher
        hcol = _h_of(sheet, view, box, cols[both] + 0.5)
        st = _stats(dz, mm, hcol)
        st["missing_cols"] = int(len(cols) - both.sum())
        st["sheet_only_cols"] = int((s_any & ~m_any).sum())
        st["model_only_cols"] = int((~s_any & m_any).sum())
        low[e.name] = st
    out["lower_edges"] = low

    # landmarks
    lms = {}
    for L in spec.landmarks:
        if L.view != view.name:
            continue
        ps = _landmark(sheet_read, L, spec, view, box, index)
        pm = _landmark(render, L, spec, view, box, index)
        rec = {"sheet": None if ps is None else [round(ps[0], 4), round(ps[1], 4)],
               "model": None if pm is None else [round(pm[0], 4), round(pm[1], 4)], "axes": L.axes}
        if ps is not None and pm is not None:
            f = float(spec.figure_scale(rig)) * 1000.0
            dh, dz = (pm[0] - ps[0]) * f, (pm[1] - ps[1]) * f
            rec["dh_mm"] = round(dh, 2) if "h" in L.axes else None
            rec["dz_mm"] = round(dz, 2) if "z" in L.axes else None
            rec["d_mm"] = round(math.hypot(dh if "h" in L.axes else 0.0, dz if "z" in L.axes else 0.0), 2)
        lms[L.name] = rec
    out["landmarks"] = lms
    return out


def _landmark(img, L: Landmark, spec: OverlaySpec, view: SheetView, box, index):
    """``(h, z)`` sheet-scale metres of a landmark on a :class:`SheetRead` or :class:`ViewRender` (pixel edges for
    the extreme coordinate, the mean pixel centre for the other), or ``None``."""
    sheet = spec.sheet
    m = _mask(img, L.cls, index, spec.max_hole_px)
    rows = _rows_z(sheet, box, *L.z_range)
    cols = _cols_h(sheet, view, box, [L.h_range])
    if not len(rows) or not len(cols):
        return None
    sub = np.zeros_like(m)
    sub[np.ix_(rows, cols)] = m[np.ix_(rows, cols)]
    if L.min_run > 0:
        return _landmark_run(sub, L, sheet, view, box)
    ys, xs = np.nonzero(sub)
    if not len(ys):
        return None
    if L.kind == "top":
        i = ys.min()
        return float(_h_of(sheet, view, box, xs[ys == i].mean() + 0.5)), float(_z_of(sheet, box, i))
    if L.kind == "bottom":
        i = ys.max()
        return float(_h_of(sheet, view, box, xs[ys == i].mean() + 0.5)), float(_z_of(sheet, box, i + 1))
    if L.kind == "left":
        j = xs.min()
        return float(_h_of(sheet, view, box, j)), float(_z_of(sheet, box, ys[xs == j].mean() + 0.5))
    if L.kind == "right":
        j = xs.max()
        return float(_h_of(sheet, view, box, j + 1)), float(_z_of(sheet, box, ys[xs == j].mean() + 0.5))
    raise ValueError(f"unknown landmark kind {L.kind!r}")


def _longest_run(line: np.ndarray):
    """``(length, start)`` of the longest run of True in a 1D bool array."""
    pad = np.concatenate([[0], line.astype(np.int8), [0]])
    d = np.diff(pad)
    st, en = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    if not len(st):
        return 0, 0
    k = int(np.argmax(en - st))
    return int(en[k] - st[k]), int(st[k])


def _landmark_run(sub, L: Landmark, sheet: SheetSpec, view: SheetView, box):
    n = L.min_run / sheet.scale
    if L.kind in ("top", "bottom"):
        rows = range(sub.shape[0]) if L.kind == "top" else range(sub.shape[0] - 1, -1, -1)
        for i in rows:
            ln, st = _longest_run(sub[i])
            if ln >= n:
                v = i if L.kind == "top" else i + 1
                return float(_h_of(sheet, view, box, st + 0.5 * ln)), float(_z_of(sheet, box, v))
        return None
    cols = range(sub.shape[1]) if L.kind == "left" else range(sub.shape[1] - 1, -1, -1)
    for j in cols:
        ln, st = _longest_run(sub[:, j])
        if ln >= n:
            u = j if L.kind == "left" else j + 1
            return float(_h_of(sheet, view, box, u)), float(_z_of(sheet, box, st + 0.5 * ln))
    return None


# ---------------------------------------------------------------------------
# images
# ---------------------------------------------------------------------------

def _edges(mask: np.ndarray) -> np.ndarray:
    """The mask's boundary pixels (a mask pixel with a 4-neighbour off the mask)."""
    inner = mask.copy()
    inner[1:, :] &= mask[:-1, :]
    inner[:-1, :] &= mask[1:, :]
    inner[:, 1:] &= mask[:, :-1]
    inner[:, :-1] &= mask[:, 1:]
    return mask & ~inner


def _class_rgb(cls: np.ndarray, spec: OverlaySpec) -> np.ndarray:
    return paint_classes(cls, spec, background=255)


def overlay_image(sheet_read: SheetRead, render: ViewRender, spec: OverlaySpec) -> np.ndarray:
    """(H, W, 3) uint8: the sheet at 50 % over white, the class-coloured model at 50 % over it, the model's outline
    green, the sheet's silhouette magenta (and the outlines of :attr:`OverlaySpec.outline_classes` alike)."""
    base = 0.5 * sheet_read.rgb.astype(np.float32) + 0.5 * 255.0
    m = render.figure
    model = _class_rgb(render.cls, spec).astype(np.float32)
    img = base.copy()
    img[m] = 0.5 * base[m] + 0.5 * model[m]
    _, index = _class_index(spec)
    for c in spec.outline_classes:
        img[_edges(_mask(sheet_read, c, index, spec.max_hole_px))] = SHEET_LINE
    img[_edges(sheet_read.figure)] = SHEET_LINE
    for c in spec.outline_classes:
        img[_edges(_mask(render, c, index, spec.max_hole_px))] = MODEL_LINE
    img[_edges(m)] = MODEL_LINE
    return np.clip(img, 0, 255).astype(np.uint8)


def diff_image(sheet_read: SheetRead, render: ViewRender) -> np.ndarray:
    s, m = sheet_read.figure, render.figure
    img = np.full(s.shape + (3,), 255, dtype=np.uint8)
    img[s & ~m] = DIFF_SHEET
    img[m & ~s] = DIFF_MODEL
    both = s & m
    same = both & (sheet_read.cls == render.cls)
    img[same] = DIFF_BOTH
    img[both & ~same] = DIFF_CLASS
    return img


def _save(arr: np.ndarray, path: str, mag: int = 1):
    from PIL import Image

    im = Image.fromarray(arr, "RGB")
    if mag != 1:
        im = im.resize((im.width * mag, im.height * mag), Image.NEAREST)
    im.save(path)


# ---------------------------------------------------------------------------
# smoothness
# ---------------------------------------------------------------------------

def _tri_normals(V, tris):
    n = np.cross(V[tris[:, 1]] - V[tris[:, 0]], V[tris[:, 2]] - V[tris[:, 0]])
    ln = np.linalg.norm(n, axis=1)
    return n / np.where(ln > 0, ln, 1.0)[:, None], ln


def _canonical(V, decimals: int = 7):
    """Vertex ids merged by position (rounded): coincident vertices of different shells or groups get one id."""
    _, inv = np.unique(np.round(V, decimals), axis=0, return_inverse=True)
    return inv.reshape(-1)


def _edge_table(tris_c):
    """``(edges (E, 2) sorted canonical ids, tri lists)`` of a triangle list (canonical ids)."""
    e = np.concatenate([tris_c[:, [0, 1]], tris_c[:, [1, 2]], tris_c[:, [2, 0]]], axis=0)
    owner = np.tile(np.arange(len(tris_c)), 3)
    e = np.sort(e, axis=1)
    uniq, inv = np.unique(e, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    order = np.argsort(inv, kind="stable")
    counts = np.bincount(inv, minlength=len(uniq))
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    return uniq, order, owner, counts, starts


def dihedral_stats(mesh: mk.Mesh, smooth_deg: float = 30.0, scale: float = 1.0, worst: int = 5,
                   crease_deg: float = 60.0, zones=(), tri_visible=None) -> dict:
    """Angles (deg) between adjacent triangles (castplane's fan triangulation) inside one smooth group (a group > 0,
    or two group-0 triangles under ``smooth_deg``, castplane's rule): what shading must hide.  Group boundaries are
    designed lines and do not count, nor do the edges over ``crease_deg`` (a thin shell's rim, a lock's tip: folds,
    not facets; counted as ``creases``).  Returns max / p95 / mean of the rest (``facets``), the count over 10 / 20 /
    30 / 45 deg and the ``worst`` edges (their midpoints divided by ``scale``: sheet-scale metres when ``scale`` is the
    figure scale); ``zones`` ``((name, z_lo, z_hi), ...)`` (sheet-scale heights of the edge midpoints) add the same
    statistics per height band.  ``tri_visible``: ``(cameras, triangles)`` bools (:meth:`FrontView.visible` per
    camera, restricted to this mesh's triangles): only the edges whose two triangles are both visible from at least
    one camera count (a face buried in another part or always behind other parts is never seen, so never shaded);
    the edges left out are counted as ``hidden_edges``."""
    V = mesh.vertices
    tris, tri_face = mesh.triangles()
    groups = np.asarray(mesh.groups, dtype=np.int64)[tri_face]
    nrm, ln = _tri_normals(V, tris)
    cid = _canonical(V)
    uniq, order, owner, counts, starts = _edge_table(cid[tris])
    two = np.nonzero(counts == 2)[0]
    t0 = owner[order[starts[two]]]
    t1 = owner[order[starts[two] + 1]]
    ang = np.degrees(np.arccos(np.clip(np.einsum("ij,ij->i", nrm[t0], nrm[t1]), -1.0, 1.0)))
    g0, g1 = groups[t0], groups[t1]
    same = ((g0 == g1) & (g0 > 0)) | ((g0 == 0) & (g1 == 0) & (ang < smooth_deg))
    same &= (ln[t0] > 0) & (ln[t1] > 0)
    hidden = 0
    if tri_visible is not None:
        vis = np.asarray(tri_visible, dtype=bool).reshape(-1, len(tris))
        seen = (vis[:, t0] & vis[:, t1]).any(axis=0)
        hidden = int((same & ~seen).sum())
        same &= seen
    creases = int((same & (ang > crease_deg)).sum())
    same &= ang <= crease_deg
    a = ang[same]
    if not len(a):
        return {"edges": 0, "creases": creases, "hidden_edges": hidden, "max": None, "p95": None, "mean": None}
    # edge midpoints (canonical id -> a position)
    pos = np.zeros((cid.max() + 1, 3))
    pos[cid] = V
    mid = 0.5 * (pos[uniq[two[same], 0]] + pos[uniq[two[same], 1]]) / scale
    k = np.argsort(-a, kind="stable")[:worst]
    out = {"edges": int(len(a)), "creases": creases, "hidden_edges": hidden, "max": round(float(a.max()), 2),
           "p95": round(float(np.percentile(a, 95)), 2), "mean": round(float(a.mean()), 2),
           "over": {str(t): int((a > t).sum()) for t in (10, 20, 30, 45)},
           "worst": [{"deg": round(float(a[i]), 2), "at": [round(float(x), 4) for x in mid[i]]} for i in k]}
    if zones:
        out["zones"] = {}
        for name, zl, zh in zones:
            az = a[(mid[:, 2] >= zl) & (mid[:, 2] < zh)]
            out["zones"][name] = {"edges": int(len(az)),
                                  "max": round(float(az.max()), 2) if len(az) else None,
                                  "p95": round(float(np.percentile(az, 95)), 2) if len(az) else None,
                                  "mean": round(float(az.mean()), 2) if len(az) else None,
                                  "over": {str(t): int((az > t).sum()) for t in (10, 20, 30, 45)}}
    return out


@dataclass
class FrontView:
    """The whole model's z-buffer from one camera: ``ids`` (H, W) the global index of the front-most triangle
    (castplane's fan of each mesh in order, ``offsets[i]`` the first one of mesh ``i``, ``n`` in all; -1 = nothing),
    sampled at ``ss`` pixels per pixel of the ``ref_px`` tall picture."""

    ids: np.ndarray
    ss: float
    offsets: np.ndarray
    n: int

    def visible(self) -> np.ndarray:
        """(n,) bool: the triangles that are front-most at one sample at least."""
        v = np.zeros(self.n, dtype=bool)
        u = np.unique(self.ids)
        v[u[u >= 0]] = True
        return v

    def shows(self, points, own) -> np.ndarray:
        """(N,) bool: whether the front-most surface at ``points`` (pixels of the ``ref_px`` picture) is one of the
        triangles marked in ``own`` ((n,) bool)."""
        q = np.floor(np.asarray(points, dtype=np.float64) * self.ss).astype(np.int64)
        H, W = self.ids.shape
        ok = (q[:, 0] >= 0) & (q[:, 1] >= 0) & (q[:, 0] < W) & (q[:, 1] < H)
        res = np.zeros(len(q), dtype=bool)
        t = self.ids[q[ok, 1], q[ok, 0]]
        res[np.nonzero(ok)[0]] = (t >= 0) & own[np.maximum(t, 0)]
        return res


def front_view(meshes, camera: dict, ref_px: int = 1200, ss: float = 2.0) -> FrontView:
    """Perspective z-buffer of ``meshes`` (closed shells; back faces are culled) from a castplane ``camera`` dict, in
    the picture :func:`outline_turns` uses (``ref_px`` tall, ``ss`` samples per pixel): which triangle is front-most
    at each sample (interpolated inverse depth, pixel centres)."""
    from .preview import view_basis

    pos, r, u, f = view_basis(camera)
    Href = float(ref_px)
    Wref = Href * camera["frame_mm"][0] / camera["frame_mm"][1]
    H, W = int(round(Href * ss)), int(round(Wref * ss))
    fx = camera["focal_length_mm"] / camera["frame_mm"][0] * Wref * ss
    fy = camera["focal_length_mm"] / camera["frame_mm"][1] * Href * ss
    near = camera.get("near_m", 0.05)
    inv = np.zeros((H, W))
    ids = np.full((H, W), -1, dtype=np.int32)
    offsets, base = [], 0
    for m in meshes:
        offsets.append(base)
        tris, _ = m.triangles()
        d = m.vertices - pos
        z = d @ f
        X = W / 2 + fx * (d @ r) / np.where(z > 1e-12, z, 1e-12)
        Y = H / 2 - fy * (d @ u) / np.where(z > 1e-12, z, 1e-12)
        nrm = np.cross(m.vertices[tris[:, 1]] - m.vertices[tris[:, 0]], m.vertices[tris[:, 2]] - m.vertices[tris[:, 0]])
        facing = np.einsum("ij,ij->i", nrm, m.vertices[tris].mean(axis=1) - pos) < 0
        ok = facing & (z[tris] > near).all(axis=1)
        for t in np.nonzero(ok)[0]:
            a, b, c = tris[t]
            xa, ya, xb, yb, xc, yc = X[a], Y[a], X[b], Y[b], X[c], Y[c]
            area = (xb - xa) * (yc - ya) - (yb - ya) * (xc - xa)
            if abs(area) < 1e-12:
                continue
            x0 = max(int(math.floor(min(xa, xb, xc) - 0.5)), 0)
            x1 = min(int(math.ceil(max(xa, xb, xc) - 0.5)), W - 1)
            y0 = max(int(math.floor(min(ya, yb, yc) - 0.5)), 0)
            y1 = min(int(math.ceil(max(ya, yb, yc) - 0.5)), H - 1)
            if x0 > x1 or y0 > y1:
                continue
            PX, PY = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
            w0 = ((xb - PX) * (yc - PY) - (yb - PY) * (xc - PX)) / area
            w1 = ((xc - PX) * (ya - PY) - (yc - PY) * (xa - PX)) / area
            w2 = 1.0 - w0 - w1
            inside = (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
            if not inside.any():
                continue
            iz = w0 / z[a] + w1 / z[b] + w2 / z[c]
            sub = inv[y0:y1 + 1, x0:x1 + 1]
            win = inside & (iz > sub)
            if not win.any():
                continue
            sub[win] = iz[win]
            ids[y0:y1 + 1, x0:x1 + 1][win] = base + t
        base += len(tris)
    return FrontView(ids, float(ss), np.asarray(offsets, dtype=np.int64), base)


def _project(cam: dict, ref_px: int):
    from .preview import view_basis

    pos, r, u, f = view_basis(cam)
    H = float(ref_px)
    W = H * cam["frame_mm"][0] / cam["frame_mm"][1]
    fx = cam["focal_length_mm"] / cam["frame_mm"][0] * W
    fy = cam["focal_length_mm"] / cam["frame_mm"][1] * H

    def proj(P):
        d = P - pos
        z = d @ f
        return np.stack([W / 2 + fx * (d @ r) / z, H / 2 - fy * (d @ u) / z], axis=1)

    return pos, proj


def _raster_mask(S, tris, ss: float):
    """Coverage mask of 2D triangles ``S[tris]`` at ``ss`` x the pixel scale: ``(mask, origin)``."""
    lo = np.floor(S.min(axis=0)) - 4
    hi = np.ceil(S.max(axis=0)) + 4
    W = int((hi[0] - lo[0]) * ss) + 1
    H = int((hi[1] - lo[1]) * ss) + 1
    Q = (S - lo) * ss
    mask = np.zeros((H, W), dtype=bool)
    for a, b, c in tris:
        p0, p1, p2 = Q[a], Q[b], Q[c]
        area = (p1[0] - p0[0]) * (p2[1] - p0[1]) - (p1[1] - p0[1]) * (p2[0] - p0[0])
        if abs(area) < 1e-12:
            continue
        x0 = max(int(math.floor(min(p0[0], p1[0], p2[0]))), 0)
        x1 = min(int(math.ceil(max(p0[0], p1[0], p2[0]))), W - 1)
        y0 = max(int(math.floor(min(p0[1], p1[1], p2[1]))), 0)
        y1 = min(int(math.ceil(max(p0[1], p1[1], p2[1]))), H - 1)
        if x0 > x1 or y0 > y1:
            continue
        X, Y = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        w0 = ((p1[0] - X) * (p2[1] - Y) - (p1[1] - Y) * (p2[0] - X)) / area
        w1 = ((p2[0] - X) * (p0[1] - Y) - (p2[1] - Y) * (p0[0] - X)) / area
        w2 = 1.0 - w0 - w1
        mask[y0:y1 + 1, x0:x1 + 1] |= (w0 >= -1e-9) & (w1 >= -1e-9) & (w2 >= -1e-9)
    return mask, lo


def outline_turns(mesh: mk.Mesh, camera: dict, ref_px: int = 1200, tip_deg: float = 60.0, min_seg_px: float = 1.0,
                  scale: float = 1.0, worst: int = 5, zones=(), front: FrontView | None = None, own=None,
                  fold_deg: float = 170.0, merge_px: float = 0.5) -> dict:
    """The turning angles of one part's own 2D outline in a perspective ``camera`` (a castplane camera dict; the
    picture is ``ref_px`` pixels tall).

    The outline edges are the silhouette edges (the two triangles face opposite ways from the eye; castplane's fan
    triangulation) that lie on the boundary of the part's projected region (a 4x supersampled coverage mask is
    inside on one side of the edge and outside on the other).  They are chained at shared vertices (vertices merged
    by position); at a vertex with exactly two outline edges, both at least ``min_seg_px`` long, the turning angle
    is the angle between the two segments' directions.  Turns over ``tip_deg`` are **tips** (designed points and
    notches), reported apart; the runs between successive tips along a chain are **flanks**: a flank of one
    segment (or turning less than 3 deg in all) is straight.  Turns over ``fold_deg`` are **folds**: the chain doubles
    back on itself (a thin wall seen edge-on, two outline edges one pixel apart, a needle's apex), an artefact of the
    projection and never a drawn corner; they are counted as ``folds``, not as tips and not as turns
    (``turn_vertices``, the statistics and the flanks leave them out).

    Before the chains are built, outline edges whose two end points coincide with another outline edge's end points
    within ``merge_px`` pixels (in the picture and in space: the two rims of shells that meet at a cut, coincident
    silhouette edges; ``merge_px = 0`` switches this off) are one edge: their vertices are merged and the duplicate
    dropped (``merged_edges`` counts the edges dropped), so the outline runs through the join instead of ending on
    both sides of it.  Two coincident open-boundary edges whose triangles face the same way are a seam inside the
    surface, no outline at all; an open-boundary edge is merged with open-boundary edges only.

    Returns the largest / p95 non-tip turn, the counts over 10 / 15 / 20 / 30 deg, the tips, the folds, the flanks and
    the ``worst`` vertices (3D positions divided by ``scale``).
    ``zones``: ``((name, z_lo, z_hi), ...)`` (heights divided by ``scale``, i.e. sheet-scale metres): the same turn
    statistics for the outline vertices in each height band (e.g. a rounded body above its pointed tips).

    ``front`` (the whole model's :func:`front_view` from the same camera) and ``own`` (its (n,) bools marking this
    part's triangles): only the outline edges a viewer sees count, those where the part is the front-most surface just
    inside its outline (at two of three samples one pixel in); the rest (an edge buried in another part, a corner
    behind other locks) are left out before the chains are built (``hidden_edges``)."""
    V = mesh.vertices
    tris, _ = mesh.triangles()
    pos, proj = _project(camera, ref_px)
    S = proj(V)
    nrm, _ = _tri_normals(V, tris)
    cen = V[tris].mean(axis=1)
    facing = np.einsum("ij,ij->i", nrm, cen - pos) < 0
    cid = _canonical(V)
    uniq, order, owner, counts, starts = _edge_table(cid[tris])
    two = np.nonzero(counts == 2)[0]
    t0 = owner[order[starts[two]]]
    t1 = owner[order[starts[two] + 1]]
    sil = two[facing[t0] != facing[t1]]
    one = np.nonzero(counts == 1)[0]
    cand = np.concatenate([sil, one])
    # an open-boundary edge's side: which way its one triangle faces (-1 for a silhouette edge, which has two)
    rim_face = np.concatenate([np.full(len(sil), -1), facing[owner[order[starts[one]]]].astype(np.int64)])
    # one 2D position per canonical id
    P2 = np.zeros((cid.max() + 1, 2))
    P2[cid] = S
    P3 = np.zeros((cid.max() + 1, 3))
    P3[cid] = V
    ss = 4.0
    mask, lo = _raster_mask(S, tris, ss)

    def inside(pts):
        q = np.floor((pts - lo) * ss).astype(np.int64)
        ok = (q[:, 0] >= 0) & (q[:, 1] >= 0) & (q[:, 0] < mask.shape[1]) & (q[:, 1] < mask.shape[0])
        res = np.zeros(len(pts), dtype=bool)
        res[ok] = mask[q[ok, 1], q[ok, 0]]
        return res

    a2, b2 = P2[uniq[cand, 0]], P2[uniq[cand, 1]]
    d = b2 - a2
    L = np.linalg.norm(d, axis=1)
    n = np.stack([-d[:, 1], d[:, 0]], axis=1) / np.where(L > 0, L, 1.0)[:, None]
    delta = 0.6
    votes = np.zeros(len(cand), dtype=np.int64)
    for t in (0.25, 0.5, 0.75):
        m = a2 + t * d
        votes += inside(m + delta * n) != inside(m - delta * n)
    is_outline = (votes >= 2) | ((L < 1.5) & (inside(a2 + 0.5 * d + delta * n) != inside(a2 + 0.5 * d - delta * n)))
    hidden = 0
    if front is not None:
        seen = np.zeros(len(cand), dtype=np.int64)
        ts = (0.25, 0.5, 0.75)
        for t in ts:
            m = a2 + t * d
            side = np.where(inside(m + delta * n), 1.0, -1.0)[:, None]
            seen += front.shows(m + side * 1.0 * n, own)
        m = a2 + 0.5 * d
        short_seen = front.shows(m + np.where(inside(m + delta * n), 1.0, -1.0)[:, None] * n, own)
        visible = np.where(L < 1.5, short_seen, seen >= 2)
        hidden = int((is_outline & ~visible).sum())
        is_outline &= visible
    edges = uniq[cand[is_outline]]
    n_cand = len(edges)
    if merge_px > 0:
        from .preview import view_basis

        _, _, _, fwd = view_basis(camera)
        px_m = np.maximum((P3 - pos) @ fwd, 0.0) / (camera["focal_length_mm"] / camera["frame_mm"][1] * ref_px)
        edges = _merge_coincident(edges, rim_face[is_outline], P2, P3, merge_px * px_m, merge_px)
    merged = n_cand - len(edges)
    # chains
    adj = {}
    for a, b in edges.tolist():
        adj.setdefault(a, []).append(b)
        adj.setdefault(b, []).append(a)
    deg2 = sorted(v for v, nb in adj.items() if len(nb) == 2)
    turns, where = [], []
    for v in deg2:
        a, b = adj[v]
        d1, d2 = P2[v] - P2[a], P2[b] - P2[v]
        l1, l2 = float(np.hypot(*d1)), float(np.hypot(*d2))
        if l1 < min_seg_px or l2 < min_seg_px:
            continue
        cr = d1[0] * d2[1] - d1[1] * d2[0]
        turns.append(math.degrees(math.atan2(abs(cr), float(d1 @ d2))))
        where.append(v)
    turns = np.asarray(turns)
    fold = turns > fold_deg
    n_folds = int(fold.sum())
    fold_at = np.asarray(where, dtype=np.int64)[fold]
    turns, where = turns[~fold], [w for w, f in zip(where, fold) if not f]
    tip = turns > tip_deg
    smooth = turns[~tip]
    out = {"outline_edges": int(len(edges)), "hidden_edges": hidden, "merged_edges": int(merged),
           "turn_vertices": int(len(turns)), "tips": int(tip.sum()), "folds": n_folds}
    if len(smooth):
        k = np.argsort(-smooth, kind="stable")[:worst]
        wv = np.asarray(where)[~tip]
        out.update({"max": round(float(smooth.max()), 2), "p95": round(float(np.percentile(smooth, 95)), 2),
                    "over": {str(t): int((smooth > t).sum()) for t in (10, 15, 20, 30)},
                    "worst": [{"deg": round(float(smooth[i]), 2),
                               "at": [round(float(x), 4) for x in P3[wv[i]] / scale]} for i in k]})
    else:
        out.update({"max": None, "p95": None, "over": {}, "worst": []})
    out["flanks"] = _flanks(adj, P2, tip_deg, min_seg_px, fold_deg)
    if zones:
        zv = P3[np.asarray(where, dtype=np.int64), 2] / scale if where else np.zeros(0)
        out["zones"] = {}
        for name, zl, zh in zones:
            inz = (zv >= zl) & (zv < zh)
            t = turns[inz & ~tip]
            zf = P3[fold_at, 2] / scale
            out["zones"][name] = {"turn_vertices": int(inz.sum()), "tips": int((inz & tip).sum()),
                                  "folds": int(((zf >= zl) & (zf < zh)).sum()),
                                  "max": round(float(t.max()), 2) if len(t) else None,
                                  "p95": round(float(np.percentile(t, 95)), 2) if len(t) else None,
                                  "over": {str(x): int((t > x).sum()) for x in (10, 15, 20, 30)}}
    return out


def _merge_coincident(edges, rim_face, P2, P3, gap3, tol_px: float):
    """``edges`` ((E, 2) canonical vertex ids) with the coincident ones merged.  Two edges of one kind (both open
    boundaries or both silhouette edges) that share no vertex and whose end points coincide, in either order, are
    one edge: their vertices are identified (the smaller id stands for both) and the duplicate edge is dropped.
    End points coincide when they project within ``tol_px`` pixels of each other *and* lie within ``gap3`` (the
    world length of ``tol_px`` pixels at the vertex's depth, per canonical id) in space: two points on one line of
    sight (the near and the far wall of a thin shell, the near and the far arc of a ring seen edge-on) are not one
    point.  A merged vertex's other edges follow it, so a chain that ended on one side of a join runs through to the
    other side.  ``tol_px <= 0`` merges nothing.

    ``rim_face``: -1 for a silhouette edge, else 0 / 1 for the way the one triangle of an open-boundary edge faces.
    Two coincident open boundaries are the seam between two shells, which one welded mesh would have as an ordinary
    edge: it is an outline edge only if the two triangles face opposite ways (a silhouette), and it is dropped
    otherwise."""
    if len(edges) < 2 or tol_px <= 0:
        return edges
    mid = 0.5 * (P2[edges[:, 0]] + P2[edges[:, 1]])
    cell = np.floor(mid / max(2.0 * tol_px, 1e-9)).astype(np.int64)
    grid = {}
    for i in range(len(edges)):
        grid.setdefault((int(cell[i, 0]), int(cell[i, 1])), []).append(i)
    parent = {}
    drop = np.zeros(len(edges), dtype=bool)

    def find(v):
        while v in parent:
            v = parent[v]
        return v

    def union(u, v):
        ru, rv = find(u), find(v)
        if ru != rv:
            parent[max(ru, rv)] = min(ru, rv)

    def near(u, v):
        return (float(np.hypot(*(P2[u] - P2[v]))) <= tol_px
                and float(np.linalg.norm(P3[u] - P3[v])) <= max(gap3[u], gap3[v]))

    for i in range(len(edges)):
        a, b = int(edges[i, 0]), int(edges[i, 1])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((int(cell[i, 0]) + dx, int(cell[i, 1]) + dy), ()):
                    if j <= i or (rim_face[i] >= 0) != (rim_face[j] >= 0):
                        continue
                    c, d = int(edges[j, 0]), int(edges[j, 1])
                    if {a, b} & {c, d}:
                        continue
                    if near(a, c) and near(b, d):
                        union(a, c), union(b, d)
                    elif near(a, d) and near(b, c):
                        union(a, d), union(b, c)
                    else:
                        continue
                    if rim_face[i] >= 0 and rim_face[i] == rim_face[j]:
                        drop[i] = drop[j] = True
    if not parent:
        return edges
    seen, kept = set(), []
    for k, (a, b) in enumerate(edges.tolist()):
        a, b = find(a), find(b)
        key = (min(a, b), max(a, b))
        if a != b and key not in seen and not drop[k]:
            seen.add(key)
            kept.append(key)
    return np.asarray(kept, dtype=edges.dtype).reshape(-1, 2)


def _flanks(adj, P2, tip_deg, min_seg_px, fold_deg) -> dict:
    """Walk the outline chains; split them at tips (folds are not tips); count the flanks and the straight ones."""
    seen = set()
    flanks = []
    for start in sorted(adj):
        if len(adj[start]) == 2 or start in seen:
            continue
        # open chains start at a vertex of degree != 2
        for nb in adj[start]:
            if (min(start, nb), max(start, nb)) in seen:
                continue
            chain = [start, nb]
            seen.add((min(start, nb), max(start, nb)))
            while len(adj[chain[-1]]) == 2:
                a, b = adj[chain[-1]]
                nxt = b if a == chain[-2] else a
                key = (min(chain[-1], nxt), max(chain[-1], nxt))
                if key in seen:
                    break
                seen.add(key)
                chain.append(nxt)
            flanks.extend(_split_chain(chain, P2, tip_deg, min_seg_px, fold_deg))
    for start in sorted(adj):
        if len(adj[start]) != 2:
            continue
        a, b = adj[start]
        if (min(start, b), max(start, b)) in seen:
            continue
        chain = [start, b]
        seen.add((min(start, b), max(start, b)))
        while chain[-1] != start:
            x, y = adj[chain[-1]]
            nxt = y if x == chain[-2] else x
            key = (min(chain[-1], nxt), max(chain[-1], nxt))
            if key in seen:
                break
            seen.add(key)
            chain.append(nxt)
        flanks.extend(_split_chain(chain, P2, tip_deg, min_seg_px, fold_deg))
    straight = [f for f in flanks if f["straight"]]
    return {"flanks": len(flanks), "straight": len(straight),
            "longest_straight_px": round(max([f["length"] for f in straight], default=0.0), 1),
            "median_segments": float(np.median([f["segments"] for f in flanks])) if flanks else None}


def _split_chain(chain, P2, tip_deg, min_seg_px, fold_deg):
    """Flanks of one chain (vertex list): runs between successive tips (only runs bounded by tips on both ends).  A
    vertex that turns over ``fold_deg`` is a fold: not a tip, and its turn is not part of a flank's turning."""
    pts = [P2[v] for v in chain]
    n = len(pts)
    turn = [0.0] * n
    for i in range(1, n - 1):
        d1, d2 = pts[i] - pts[i - 1], pts[i + 1] - pts[i]
        cr = d1[0] * d2[1] - d1[1] * d2[0]
        turn[i] = math.degrees(math.atan2(abs(cr), float(d1 @ d2)))
    tips = [i for i in range(1, n - 1) if tip_deg < turn[i] <= fold_deg]
    out = []
    for i0, i1 in zip(tips, tips[1:]):
        seg = [float(np.hypot(*(pts[k + 1] - pts[k]))) for k in range(i0, i1)]
        segs = sum(1 for s in seg if s >= min_seg_px)
        tot = sum(turn[k] for k in range(i0 + 1, i1) if turn[k] <= fold_deg)
        out.append({"segments": segs, "turn": tot, "length": sum(seg), "straight": segs <= 1 or tot < 3.0})
    return out


def _point_tri_dist(P, A, B, C):
    """Distances from points ``P`` (N, 3) to triangles ``A, B, C`` (M, 3): (N, M) (Ericson's closest point)."""
    P = P[:, None, :]
    ab, ac, ap = B - A, C - A, P - A
    d1, d2 = np.einsum("mk,nmk->nm", ab, ap), np.einsum("mk,nmk->nm", ac, ap)
    bp = P - B
    d3, d4 = np.einsum("mk,nmk->nm", ab, bp), np.einsum("mk,nmk->nm", ac, bp)
    cp = P - C
    d5, d6 = np.einsum("mk,nmk->nm", ab, cp), np.einsum("mk,nmk->nm", ac, cp)
    va = d3 * d6 - d5 * d4
    vb = d5 * d2 - d1 * d6
    vc = d1 * d4 - d3 * d2
    denom = va + vb + vc
    denom = np.where(np.abs(denom) > 1e-30, denom, 1e-30)
    v = vb / denom
    w = vc / denom
    Q = A + v[..., None] * ab + w[..., None] * ac
    # regions
    eps = 0.0
    r_a = (d1 <= eps) & (d2 <= eps)
    r_b = (d3 >= -eps) & (d4 <= d3)
    r_c = (d6 >= -eps) & (d5 <= d6)
    t_ab = np.clip(d1 / np.where(np.abs(d1 - d3) > 1e-30, d1 - d3, 1e-30), 0, 1)
    r_ab = (vc <= 0) & (d1 >= 0) & (d3 <= 0)
    t_ac = np.clip(d2 / np.where(np.abs(d2 - d6) > 1e-30, d2 - d6, 1e-30), 0, 1)
    r_ac = (vb <= 0) & (d2 >= 0) & (d6 <= 0)
    d43, d56 = d4 - d3, d5 - d6
    t_bc = np.clip(d43 / np.where(np.abs(d43 + d56) > 1e-30, d43 + d56, 1e-30), 0, 1)
    r_bc = (va <= 0) & (d43 >= 0) & (d56 >= 0)
    Q = np.where(r_bc[..., None], B + t_bc[..., None] * (C - B), Q)
    Q = np.where(r_ac[..., None], A + t_ac[..., None] * ac, Q)
    Q = np.where(r_ab[..., None], A + t_ab[..., None] * ab, Q)
    Q = np.where(r_c[..., None], np.broadcast_to(C, Q.shape), Q)
    Q = np.where(r_b[..., None], np.broadcast_to(B, Q.shape), Q)
    Q = np.where(r_a[..., None], np.broadcast_to(A, Q.shape), Q)
    return np.linalg.norm(P - Q, axis=-1)


def mesh_distance(a: mk.Mesh, b: mk.Mesh, chunk: int = 256) -> float:
    """Smallest distance between two meshes' surfaces, from the vertices of each to the triangles of the other (exact
    for disjoint convex-ish shells where the closest pair involves a vertex; an upper bound otherwise)."""
    best = math.inf
    for m1, m2 in ((a, b), (b, a)):
        tris, _ = m2.triangles()
        A, B, C = m2.vertices[tris[:, 0]], m2.vertices[tris[:, 1]], m2.vertices[tris[:, 2]]
        for k in range(0, m1.n_vertices, chunk):
            best = min(best, float(_point_tri_dist(m1.vertices[k:k + chunk], A, B, C).min()))
    return best


def shaded_probe(model, camera: dict, *, materials: dict, light, point, window: int = 9, size=(400, 600)) -> dict:
    """The median colour of a ``window`` px square around the projection of ``point`` (final coordinates) in the
    shaded preview render (:func:`charmodel.preview.render_shaded`) from ``camera``."""
    from .preview import render_shaded, view_basis

    im = np.asarray(render_shaded(model, camera, materials=materials, light=light, size=size, ground=False,
                                  lines=False)).astype(np.float64)
    pos, r, u, f = view_basis(camera)
    W, H = size
    fx = camera["focal_length_mm"] / camera["frame_mm"][0] * W
    fy = camera["focal_length_mm"] / camera["frame_mm"][1] * H
    d = np.asarray(point, dtype=np.float64) - pos
    z = d @ f
    x, y = W / 2 + fx * (d @ r) / z, H / 2 - fy * (d @ u) / z
    h = window // 2
    j, i = int(round(x)), int(round(y))
    win = im[max(i - h, 0):i + h + 1, max(j - h, 0):j + h + 1].reshape(-1, 3)
    rgb = [int(round(float(c))) for c in np.median(win, axis=0)]
    return {"pixel": [j, i], "rgb": rgb, "r_minus_b": rgb[0] - rgb[2]}


# ---------------------------------------------------------------------------
# criteria, report, the whole run
# ---------------------------------------------------------------------------

def _lookup(report: dict, path: str):
    """Values at a dotted path (``*`` = every key of that level); missing keys give nothing."""
    nodes = [report]
    for part in path.split("."):
        nxt = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            if part == "*":
                nxt.extend(n[k] for k in sorted(n))
            elif part in n:
                nxt.append(n[part])
        nodes = nxt
    return [v for v in nodes if v is not None and not isinstance(v, dict)]


def evaluate_criteria(report: dict, criteria) -> list:
    """``[{id, text, op, limit, value, pass, note, keys, missing}]``: each criterion's reduced value and whether it
    passes.  ``missing`` lists the keys that gave no value (absent, ``None`` or not a number).  ``pass`` is ``None``
    (n/a, neither passing nor failing) when no value was found at all or when a key without a ``*`` is missing: a
    criterion whose measurements are partly gone (a landmark that was not found, a part not seen) must not pass on the
    rest.  A key with a ``*`` may match fewer levels (a view that has no value for it) without making the criterion
    n/a."""
    out = []
    for c in criteria:
        vals, missing = [], []
        for k in c.keys:
            got = [float(v) for v in _lookup(report, k) if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if not got:
                missing.append(k)
            vals.extend(got)
        partial = any("*" not in k for k in missing)
        if not vals:
            value, ok = None, None
        elif c.op == "<=":
            value = max(vals)
            ok = value <= c.limit
        elif c.op == ">=":
            value = min(vals)
            ok = value >= c.limit
        elif c.op == "abs<=":
            value = max(abs(v) for v in vals)
            ok = value <= c.limit
        elif c.op == "between":
            value = [min(vals), max(vals)]
            ok = c.limit[0] <= value[0] and value[1] <= c.limit[1]
        else:
            raise ValueError(f"unknown criterion op {c.op!r}")
        if partial:
            ok = None
        if isinstance(value, float):
            value = round(value, 2)
        elif isinstance(value, list):
            value = [round(v, 2) for v in value]
        out.append({"id": c.id, "text": c.text, "op": c.op, "limit": c.limit, "value": value, "pass": ok,
                    "note": c.note, "keys": list(c.keys), "missing": missing})
    return out


def criteria_summary(criteria: list) -> str:
    """The count line of the command and of ``report.md``: ``"35 of 41 pass; n/a: M5; failing: H11, S4"``.  Only a
    ``True`` counts as a pass; the n/a and failing ids are named (each part is left out when empty)."""
    n_ok = sum(1 for c in criteria if c["pass"] is True)
    na = [c["id"] for c in criteria if c["pass"] is None]
    failed = [c["id"] for c in criteria if c["pass"] is False]
    return (f"{n_ok} of {len(criteria)} pass" + (f"; n/a: {', '.join(na)}" if na else "")
            + (f"; failing: {', '.join(failed)}" if failed else ""))


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def write_report(report: dict, out_dir: str, title: str = "Overlay check") -> tuple:
    """``report.json`` and ``report.md`` in ``out_dir``; returns their paths."""
    jpath = os.path.join(out_dir, "report.json")
    with open(jpath, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=1, sort_keys=True, ensure_ascii=False)
        fh.write("\n")
    L = [f"# {title}", ""]
    for n in report.get("notes", []):
        L.append(f"- {n}")
    L.append("")
    crit = report.get("criteria", [])
    if crit:
        L += [f"## Pass criteria: {sum(1 for c in crit if c['pass'] is True)} of {len(crit)} pass", "",
              "| id | criterion | value | limit | result |",
              "| --- | --- | --- | --- | --- |"]
        for c in crit:
            res = "PASS" if c["pass"] else "FAIL"
            if c["pass"] is None:
                res = "n/a"
                if c.get("missing"):
                    res += " (no value at " + ", ".join(f"`{k}`" for k in c["missing"]) + ")"
            lim = (f"{c['op']} {c['limit']}" if c["op"] != "between" else f"in {c['limit']}")
            text = c["text"].replace("|", "\\|")
            L.append(f"| {c['id']} | {text} | {_fmt(c['value'])} | {lim} | {res} |")
        L.append("")
    for vname, v in report.get("views", {}).items():
        L += [f"## View `{vname}` (h axis {v['h_axis']}; {v['mm_per_px']:.3f} mm per sheet pixel)", "",
              "Silhouette per row (mm on the final model; + = the model sticks out beyond the sheet):", "",
              "| band | rows | max | p95 | mean | signed mean | left mean | right mean | half-width max | worst at z | "
              "missing rows |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for b, s in v["silhouette"].items():
            L.append(f"| {b} | {s['n'] // 2 if s['n'] else 0} | {_fmt(s['max'])} | {_fmt(s['p95'])} | "
                     f"{_fmt(s['mean'])} | {_fmt(s['signed_mean'])} | {_fmt(s['left']['signed_mean'])} | "
                     f"{_fmt(s['right']['signed_mean'])} | {_fmt(s['width']['max'])} | {_fmt(s.get('at'))} | "
                     f"{s['missing_rows']} |")
        L += ["", "(`half-width max`: the largest error of the mean of the two sides per row.)", "",
              "IoU: " + ", ".join(f"{k} {_fmt(x)}" for k, x in v["iou"].items()), ""]
        if v["outlines"]:
            L += [("Class outlines per row (+ = the model further out; `_inner`: + = the inner edge further in; "
                   "`width`: the mean of the two sides per row, the half-width error, which a sideways shift of the "
                   "drawing cancels):"), "",
                  "| outline | side | rows | max | p95 | mean | signed mean | worst at z |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for name, o in v["outlines"].items():
                for side in sorted(k for k in o if isinstance(o[k], dict)):
                    s = o[side]
                    L.append(f"| {name} | {side} | {s['n']} | {_fmt(s['max'])} | {_fmt(s['p95'])} | "
                             f"{_fmt(s['mean'])} | {_fmt(s['signed_mean'])} | {_fmt(s.get('at'))} |")
            L.append("")
        if v["lower_edges"]:
            L += ["Lower edges per column (+ = the model's edge higher):", "",
                  "| edge | cols | max | p95 | mean | signed mean | worst at h | missing cols |",
                  "| --- | --- | --- | --- | --- | --- | --- | --- |"]
            for name, s in v["lower_edges"].items():
                L.append(f"| {name} | {s['n']} | {_fmt(s['max'])} | {_fmt(s['p95'])} | {_fmt(s['mean'])} | "
                         f"{_fmt(s['signed_mean'])} | {_fmt(s.get('at'))} | {s['missing_cols']} |")
            L.append("")
        if v["landmarks"]:
            L += ["Landmarks (sheet-scale metres; offsets model - sheet in mm on the final model):", "",
                  "| landmark | sheet (h, z) | model (h, z) | dh | dz | distance |",
                  "| --- | --- | --- | --- | --- | --- |"]
            for name, m in v["landmarks"].items():
                L.append(f"| {name} | {m['sheet']} | {m['model']} | {_fmt(m.get('dh_mm'))} | {_fmt(m.get('dz_mm'))} "
                         f"| {_fmt(m.get('d_mm'))} |")
            L.append("")
    sm = report.get("smoothness", {})
    if sm:
        vis = report.get("visibility", {})
        seen = (f"; only what the whole model shows: dihedrals whose two faces are both visible from one of "
                f"{len(vis.get('dihedral_cameras', []))} cameras, outline edges where the part is front-most"
                if vis.get("visible_only") else "")
        L += ["## Smoothness", "", (f"Dihedral angles inside one smooth group (deg; group boundaries and the folds "
                                    f"over the crease angle (rims, tips) excluded{seen}):"), "",
              "| part | edges | max | p95 | mean | > 10 | > 20 | > 30 | folds | worst at (sheet-scale m) | hidden |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for label, s in sm.items():
            d = s["dihedral"]
            over = d.get("over", {})
            w = d.get("worst", [{}])[0].get("at") if d.get("worst") else None
            L.append(f"| {label} | {d['edges']} | {_fmt(d['max'])} | {_fmt(d['p95'])} | {_fmt(d['mean'])} | "
                     f"{over.get('10', '-')} | {over.get('20', '-')} | {over.get('30', '-')} | {d.get('creases', '-')} "
                     f"| {w} | {d.get('hidden_edges', '-')} |")
            for zname, z in d.get("zones", {}).items():
                zo = z.get("over", {})
                L.append(f"| {label} ({zname}) | {z['edges']} | {_fmt(z['max'])} | {_fmt(z['p95'])} | "
                         f"{_fmt(z['mean'])} | {zo.get('10', '-')} | {zo.get('20', '-')} | "
                         f"{zo.get('30', '-')} | | | |")
        L += ["", ("2D outline turning angles (deg; tips and folds excluded: a tip turns over the tip angle, a fold, "
                   "where the chain doubles back on itself, over the fold angle) and flanks between tips (`hidden`: "
                   "outline edges left out, not front-most in the whole model; `merged`: coincident outline edges "
                   "taken as one):"), "",
              ("| part | view | max | p95 | > 10 | > 20 | tips | folds | flanks | straight flanks | "
               "longest straight px | hidden | merged |"),
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for label, s in sm.items():
            for vname, o in s["outline"].items():
                over = o.get("over", {})
                fl = o["flanks"]
                L.append(f"| {label} | {vname} | {_fmt(o['max'])} | {_fmt(o['p95'])} | {over.get('10', '-')} | "
                         f"{over.get('20', '-')} | {o['tips']} | {o.get('folds', '-')} | {fl['flanks']} | "
                         f"{fl['straight']} | {fl['longest_straight_px']} | {o.get('hidden_edges', '-')} | "
                         f"{o.get('merged_edges', '-')} |")
                for zname, z in o.get("zones", {}).items():
                    zo = z.get("over", {})
                    L.append(f"| {label} ({zname}) | {vname} | {_fmt(z['max'])} | {_fmt(z['p95'])} | "
                             f"{zo.get('10', '-')} | {zo.get('20', '-')} | {z['tips']} | {z.get('folds', '-')} | "
                             "| | | | |")
        L.append("")
    if report.get("probes"):
        L += ["## Shaded probes", ""]
        for k, p in report["probes"].items():
            L.append(f"- {k}: RGB {p['rgb']} (R - B = {p['r_minus_b']}) at pixel {p['pixel']}")
        L.append("")
    if report.get("extras"):
        L += ["## Extras", "", "```json", json.dumps(report["extras"], indent=1, sort_keys=True), "```", ""]
    mpath = os.path.join(out_dir, "report.md")
    with open(mpath, "w", encoding="utf-8") as fh:
        fh.write("\n".join(L) + "\n")
    return jpath, mpath


def _box_px(spec: OverlaySpec, view: SheetView, zoom_box):
    """A zoom box ``(h_lo, h_hi, z_lo, z_hi)`` (metres) -> pixel slices relative to the view's box."""
    s = spec.sheet
    x0, y0 = view.box[0], view.box[1]
    h_lo, h_hi, z_lo, z_hi = zoom_box
    u_lo, u_hi = sorted((view.origin_px + h_lo / s.scale - x0, view.origin_px + h_hi / s.scale - x0))
    v_lo, v_hi = s.ground_row - z_hi / s.scale - y0, s.ground_row - z_lo / s.scale - y0
    return (slice(max(int(v_lo), 0), max(int(math.ceil(v_hi)), 0)),
            slice(max(int(u_lo), 0), max(int(math.ceil(u_hi)), 0)))


def run_overlay(model, rig, spec: OverlaySpec, sheet_path: str, out_dir: str, views=None, smooth: bool = True,
                repo: str | None = None, title: str = "Overlay check", log=print) -> dict:
    """The whole check: per view the render, the sheet read, the metrics and the images; the smoothness metrics, the
    shaded probes and the character's extras; the criteria; ``report.json`` + ``report.md``.  ``out_dir`` must lie
    outside ``repo`` (the images contain the sheet).  Returns the report dict."""
    if repo is not None:
        rp, op = os.path.realpath(repo), os.path.realpath(out_dir)
        if op == rp or op.startswith(rp + os.sep):
            raise ValueError(f"the overlay directory {out_dir} lies inside the repository: the overlay images contain "
                             "the design sheet, which must stay outside it")
    os.makedirs(out_dir, exist_ok=True)
    f = float(spec.figure_scale(rig))
    report = {"notes": list(spec.notes) + [
        f"orthographic render into the sheet's pixel grid; the model divided by the figure scale {f:.5f} first; "
        f"sheet scale {spec.sheet.scale} m/px, so 1 sheet pixel = {_mm(spec, rig):.3f} mm on the final model",
        "offsets: + = the model sticks out beyond the sheet (silhouettes, outlines), the model's edge higher "
        "(lower edges); landmark dh / dz = model - sheet along the view's h axis / up"],
        "figure_scale": round(f, 6), "sheet_scale": spec.sheet.scale, "views": {}}
    sheet_rgb = load_sheet(sheet_path)
    names = [v.name for v in spec.sheet.views] if views is None else list(views)
    for vn in names:
        view = spec.sheet.view(vn)
        rd = render_view(model, spec, view, rig)
        sr = read_sheet(sheet_rgb, spec, view)
        report["views"][vn] = compare_view(sr, rd, spec, rig)
        ov = overlay_image(sr, rd, spec)
        _save(ov, os.path.join(out_dir, f"overlay_{vn}.png"))
        _save(diff_image(sr, rd), os.path.join(out_dir, f"diff_{vn}.png"))
        for zv, zname, zbox, mag in spec.zooms:
            if zv != vn:
                continue
            sl = _box_px(spec, view, zbox)
            _save(np.ascontiguousarray(ov[sl]), os.path.join(out_dir, f"overlay_{vn}_{zname}.png"), mag)
        log(f"overlay {vn}: figure IoU {report['views'][vn]['iou']['figure']}")
    if smooth and spec.smooth_parts and spec.cameras is not None:
        from .preview import drawables, model_bbox

        cams = spec.cameras(rig)
        bbox = model_bbox(drawables(model, spec.materials or {p.material: "#cccccc" for p in model.parts}))
        by_index = {p.name: k for k, p in enumerate(model.parts)}
        meshes_all = [p.mesh for p in model.parts]
        # what a viewer sees: the whole model's z-buffer from each smoothness view (outlines) and from every review
        # camera (the faces a dihedral may count)
        fronts, vis = {}, []
        if spec.visible_only:
            for vname, preset in spec.smooth_views:
                fronts[vname] = front_view(meshes_all, cams.camera(preset, bbox), spec.ref_px, spec.visibility_ss)
                vis.append(fronts[vname].visible())
            for vname, preset in spec.visibility_views:
                vis.append(front_view(meshes_all, cams.camera(preset, bbox), spec.ref_px, spec.visibility_ss).visible())
        n_all = sum(m.n_triangles for m in meshes_all)
        starts = np.concatenate([[0], np.cumsum([m.n_triangles for m in meshes_all])])
        sm = {}
        for entry in spec.smooth_parts:
            label, pnames = entry[0], entry[1]
            zones = entry[2] if len(entry) > 2 else ()
            ks = [by_index[n] for n in pnames if n in by_index]
            if not ks:
                continue
            mesh = mk.merge(*[meshes_all[k] for k in ks])
            gids = np.concatenate([np.arange(starts[k], starts[k + 1]) for k in ks])
            own = np.zeros(n_all, dtype=bool)
            own[gids] = True
            tri_vis = np.stack([v[gids] for v in vis]) if vis else None
            sm[label] = {"parts": list(pnames),
                         "dihedral": dihedral_stats(mesh, spec.smooth_deg, scale=f, crease_deg=spec.crease_deg,
                                                    zones=zones, tri_visible=tri_vis),
                         "outline": {vname: outline_turns(mesh, cams.camera(preset, bbox), spec.ref_px, spec.tip_deg,
                                                          spec.min_seg_px, scale=f, zones=zones,
                                                          front=fronts.get(vname), own=own)
                                     for vname, preset in spec.smooth_views}}
        report["smoothness"] = sm
        report["visibility"] = {"visible_only": spec.visible_only, "ref_px": spec.ref_px, "ss": spec.visibility_ss,
                                "outline_cameras": [v for v, _ in spec.smooth_views],
                                "dihedral_cameras": ([v for v, _ in spec.smooth_views]
                                                     + [v for v, _ in spec.visibility_views]) if spec.visible_only
                                else []}
        log(f"smoothness: {len(sm)} parts in {len(spec.smooth_views)} views, visibility from {len(vis)} cameras")
    if spec.probes and spec.cameras is not None:
        from .preview import drawables, model_bbox

        cams = spec.cameras(rig)
        bbox = model_bbox(drawables(model, spec.materials))
        report["probes"] = {p.name: shaded_probe(model, cams.camera(p.preset, bbox), materials=spec.materials,
                                                 light=spec.light, point=np.asarray(p.point) * f, window=p.window,
                                                 size=p.size) for p in spec.probes}
    if spec.extras is not None:
        report["extras"] = spec.extras(model, rig)
    report["criteria"] = evaluate_criteria(report, spec.criteria)
    write_report(report, out_dir, title)
    return report

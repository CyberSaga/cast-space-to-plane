"""Three-stage pipeline (spec §3; contract §3).

* Stage A ``shadow_geometry(scene)``: camera independent.  Objects and meshes,
  the light vectors ``L``, shadow matrices ``M`` and light feet ``F`` (§5.1–5.3),
  per polyhedral object the lit flags, silhouette edges and loops (§5.1), the
  homogeneous shadow loops with direction vertices (§5.2, §5.7 row 4), the
  shadow points ``S`` and feet ``Q`` of the silhouette vertices, and the
  light-side / degeneracy warnings of contract §2.3.
* Stage B ``project_scene(scene, A, camera=None)``: camera matrices and every
  projected point / clipped segment / polygon in homogeneous 2-D form
  (vectorised over all polyhedral objects of the scene at once, polygons clipped
  as padded batches, spec §8), the construction points ``L'``, ``F'``, the 2-D
  construction rays and the self-check of contract §2.7 (batched over all
  shadow records).
* Stage C ``compose(scene, B)``: the §6.2 geometry document with the division
  by ``x̃3`` done last and canonical floats.
* ``render(scene, camera=None)`` runs all three and writes the SVG.

Point names (contract §3.1):

* ``<obj>.v<k>``: mesh vertex ``k``; ``<obj>.v<k>.shadow.<light>``: its shadow
  on the receiver (finite silhouette vertices only); ``<obj>.v<k>.foot``: its
  foot ``Q`` (silhouette vertices only);
* ``L.<light>`` / ``F.<light>``: the light and its foot (direction points with
  ``at_infinity: true`` for a directional light);
* ``<obj>.s<k>.<light>``: the ``k``-th ground-crossing vertex inserted by the
  ground clip of contract §2.3 for that object and light (counted in order of
  first appearance in the loops, 0-based).  Such a point lies on the receiver
  and is its own shadow and foot; it gets no construction ray.
* Direction vertices of unbounded outlines are inline ``{"direction": [dx, dy, dz]}``
  entries (unit vectors in the ground plane) and have no name.

Ground clip (contract §2.3): an object with vertices below the receiver is cut
by the receiver plane as a *solid* (``shadow.clip_mesh_to_plane``): the part
above the ground is a closed mesh whose cut face is unlit, so its silhouette
loops run along the lit side of the cut face and the drawn shadow is exactly
that of the part above the ground (footprint included).  Only when that
clipped mesh is not a closed manifold (degenerate contact) do the silhouette
loops of the full mesh get clipped edge by edge instead.

Undefined special points (contract §2.7 corner cases): the foot ``F`` of a
directional light along the receiver normal is the zero vector (no ``F.<light>``
point, ``shadow_vp`` and ``shadow_vp_at_infinity`` both null, no ``F`` rays,
no ``SHADOW_VP_AT_INFINITY`` warning) and the self-check becomes ``S' = Q'``;
a point light at the camera centre has ``L' = P·L = 0`` (``light_point`` and
``light_point_at_infinity`` both null, no ``L`` rays, no
``LIGHT_POINT_AT_INFINITY`` warning) and the self-check becomes ``S' = P'``.

Tolerances (contract §2.8): stage A uses ``scene_scale`` of the object vertices
only (it must not touch the camera); stage B uses the full scale including the
camera position.

Cached stage A and the documents built from it (spec §8, camera-only re-render):
stage A also holds derived, camera-independent data that stage B / C would
otherwise rebuild on every camera change -- per object the padded unlit-face
tables of the form shadow (``lights[<light>].form_idx / form_lens / form_faces``),
the §3.1 edge record templates and the vertices as canonical Python lists
(``primitives.build_object``: ``edge_templates``, ``world_lists``), per shadow record
the shadow points / feet / ground points as canonical lists (``S_lists``, ``Q_lists``,
``G_lists``, ``G_world``).  The camera-free Python lists of the document (the
``world`` of every named point, the outline / loop entries, the face name lists)
are **shared by reference** between the cached stage A and every document composed
from it; a document is read-only data, and ``castplane.render`` / the CLI never
expose the stage A they were built from.  Everything camera dependent (image
coordinates, depths, drawables, ``back`` flags, rays, checks) is fresh per document.

Curved objects (cylinder / sphere / cone; spec §5.6, contract §2.6 / §2.7 / §2.10)
are handled analytically by ``castplane.curved`` through two hooks::

    curved.stage_a_object(obj, lights, pi, tol, receiver_id, warnings) -> list of shadow records
    curved.stage_b_objects(objs, recs, cam, tol, warnings) -> None (fills the stage-B object records;
                                                                 stage_b_object does one object)

A curved shadow record carries the same keys as a polyhedral one (``loops`` with
``vertices`` / ``entries``, ``S_world`` / ``Q_world`` / names, ``ground_points``,
``unbounded``) plus the world-space conic ``pieces`` (``E``, ``rho``, ``T = M``, arcs),
so ``_project_shadow`` and ``compose`` consume it unchanged.  Its approximate mesh
(contract §2.4) never reaches the document.  Names of curved points:

* construction points (contract §2.7): sphere ``<obj>.c`` and ``<obj>.sil.0..3``
  (silhouette circle centre ``+e1, -e1, +e2, -e2``); cylinder ``<obj>.g0.base`` /
  ``.top``, ``<obj>.g1.base`` / ``.top`` (the tangent generators, ordered
  ``theta_l - alpha``, ``theta_l + alpha``); cone ``<obj>.g0.base``, ``<obj>.g1.base``,
  ``<obj>.apex``; with the usual ``.shadow.<light>`` / ``.foot`` suffixes and
  construction rays;
* camera outline generators (objects layer, contract §2.10): ``<obj>.og0.base`` /
  ``.top`` and ``<obj>.og1.*`` (a cone's ``.top`` is its apex).  These points and the
  generator segments exist only for the current camera (a flat cone seen from above has
  none), so they are **not** ``edges[]`` entries (whose list is camera independent): the
  segments are ``outlines[].generators`` (``{from, to, back: false, segment}``), drawn in
  the objects layer, and the points get no construction rays;
* the drawn shadow polygon of a curved object (``shadows[].loops[0]``) is the sampled
  outline of ``curved.shadow_polygon_h`` (64 samples per full circle); a vertex that is
  the uncut shadow of a construction point is named by that point
  (``<obj>.g1.base.shadow.<light>``, ``<obj>.apex.shadow.<light>``,
  ``<obj>.sil.k.shadow.<light>`` at the quarter points of an unclipped sphere circle),
  every other finite vertex is a ground point ``<obj>.s<k>.<light>`` (``k`` counted in
  loop order from 0; its own shadow and foot, no construction ray) and direction
  vertices are inline ``{"direction": ...}`` entries.  The exact boundary is in
  ``shadows[].conics`` (contract §2.6 / §3.1 entries with ``map == "shadow"``).

Document additions for curved objects: ``outlines[]`` (``{object, generators: [...],
conics: [...]}``: the objects-layer generator segments and conic entries with
``map == "image"``, a ``back`` flag and drawables),
``form_shadow[].terminator`` (conic entries with ``map == "image"`` and
``{"segment": [name, name], "polylines": [...]}`` generator entries),
``shadows[].conics``.  Every conic entry carries its drawables in canvas mm:
``polylines`` (sampled, for parabola / hyperbola / degenerate / ill-conditioned conics),
``arcs`` (``{start, end, rx, ry, rotation_deg, large_arc, sweep, theta}``, ``sweep`` in the
``v``-up frame; the SVG writer flips it) and ``ellipses`` (``{centre, rx, ry,
rotation_deg}``, only when the whole circle is in front of the near plane and some part of
it lies inside the extended canvas); ``visible`` lists the circle-parameter intervals inside
the extended canvas (empty: nothing is drawn).  Arcs are near-clipped and clipped to the
extended canvas in closed form (contract §2.6); sampling happens in stage C only.
"""

from __future__ import annotations

import math
from itertools import chain

import numpy as np

from . import curved as _curved
from .camera import (camera_matrix, clip_polygon_near, clip_polygon_rect_h, clip_segments_near,
                     clip_segments_rect_h, divide, horizon as camera_horizon, nu, project, project_polygons)
from .conics import ellipse_arc_params, ellipse_params, sample_arc, sample_count
from .construction import (clip_segments_uv, coincidence_check, covering_segments, extended_segments,
                           self_check, special_point_image)
from .errors import make_warning, merge_warnings
from .homogeneous import TOL_DIR, scene_scale, to_homogeneous, tolerance
from .light import face_lit_flags, light_vector, silhouette_loops
from .output.geometry_json import canonical
from .output.svg import write_svg
from .primitives import build_object
from .scene import validate_camera
from .shadow import clip_mesh_to_plane, foot, shadow_loop, shadow_matrix, shadow_w

_ORIGIN_H = np.array([0.0, 0.0, 1.0])


# ---------------------------------------------------------------------------
# stage A
# ---------------------------------------------------------------------------

def _receiver_plane(receiver: dict) -> np.ndarray:
    """``π = (n, d)`` of a validated receiver (v1: the ground ``(0, 0, 1, 0)``; contract §2.1)."""
    n = receiver["normal"]
    return np.array([float(n[0]), float(n[1]), float(n[2]), float(receiver["offset"])])


def _light_record(light: dict, pi: np.ndarray, tol: float) -> dict:
    """``L``, ``M``, ``F`` and the light-side check of one light (spec §5.1–5.3, contract §2.3)."""
    L = light_vector(light)
    pi_L = float(pi @ L)
    warnings = []
    active = True
    if light["type"] == "point":
        tol_w = tol
        if pi_L <= tol:
            warnings.append(make_warning("LIGHT_BELOW_RECEIVER", [light["id"]]))
            active = False
    else:
        tol_w = TOL_DIR
        if abs(pi_L) <= TOL_DIR:
            warnings.append(make_warning("DIRECTIONAL_HORIZONTAL", [light["id"]]))
            active = False
        elif pi_L < -TOL_DIR:
            warnings.append(make_warning("LIGHT_BELOW_RECEIVER", [light["id"]]))
            active = False
    F = foot(pi, L)
    # spec §5.3: a point light always has a finite foot (w_F = n·n); the foot of a directional light
    # is the direction l − (n·l)·n, the zero vector when l is along the receiver normal (undefined F)
    F_defined = light["type"] == "point" or float(np.max(np.abs(F))) > TOL_DIR
    return {
        "id": light["id"],
        "type": light["type"],
        "L": L,
        "M": shadow_matrix(pi, L),
        "F": F,
        "F_defined": F_defined,
        "pi_L": pi_L,
        "active": active,
        "tol_w": tol_w,
        "tol_lit": tol_w,
        "warnings": warnings,
    }


def _object_light_data(obj: dict, lt: dict) -> tuple[dict, list]:
    """Lit flags, silhouette edges / vertices / loops of one polyhedral object w.r.t. one light (§5.1)."""
    mesh = obj["mesh"]
    lit_flags, parallel = face_lit_flags(mesh, lt["L"], lt["tol_lit"])
    warnings = []
    if bool(np.any(parallel)):
        warnings.append(make_warning("FACE_PARALLEL_TO_LIGHT", [obj["id"]]))
    ef = mesh["edge_faces"]
    edge_sil = lit_flags[ef[:, 0]] != lit_flags[ef[:, 1]]
    sil_vertices = np.unique(mesh["edges"][edge_sil]).astype(np.int64)
    # the unlit faces (form shadow, §6.1 "陰") as a padded vertex-index table: camera independent, so
    # stage B only has to project them (spec §8)
    unlit = np.nonzero(~lit_flags)[0]
    names = obj["face_point_names"]
    return {
        "lit": lit_flags,
        "parallel": parallel,
        "edge_silhouette": edge_sil,
        "silhouette_vertices": sil_vertices,
        "loops": silhouette_loops(mesh, lit_flags),
        "form_idx": obj["faces_padded"][unlit],
        "form_lens": obj["face_lens"][unlit],
        "form_faces": [names[k] for k in unlit.tolist()],
    }, warnings


def _loop_entries(sh: dict, loop_vertex_ids, origins, oid: str, lid: str, ground: dict):
    """Outline entries of one shadow loop from its ``sources`` (contract §3.1 naming, see module docstring).

    ``origins`` maps a vertex of the (ground-clipped) loop mesh to its original
    index or to a ``("ground", i, j)`` crossing; ``None`` when the loop mesh is the
    object's own mesh.  ``ground`` accumulates ``{key: (name, xyz)}`` of the
    ground-crossing points in order of first appearance (``key`` is the clipped
    vertex index, or ``("clip", k)`` for a crossing inserted by ``shadow_loop``).
    """
    entries = []
    V = sh["vertices"]

    def ground_name(key, xyz):
        if key not in ground:
            ground[key] = (f"{oid}.s{len(ground)}.{lid}", xyz)
        return ground[key][0]

    for row, src in enumerate(sh["sources"]):
        if isinstance(src, tuple):
            if src[0] == "ground":
                X = V[row]
                entries.append(ground_name(("clip", len(ground)), X[:3] / X[3]))
            else:  # ("dir", i, j) or ("arc", k): a direction vertex (w = 0)
                d = V[row]
                entries.append({"direction": [float(d[0]) + 0.0, float(d[1]) + 0.0, float(d[2]) + 0.0]})
        else:
            vid = int(loop_vertex_ids[src])
            origin = vid if origins is None else origins[vid]
            if isinstance(origin, tuple):  # a crossing vertex of the clipped mesh: its own shadow
                X = V[row]
                entries.append(ground_name(vid, X[:3] / X[3]))
            else:
                entries.append(f"{oid}.v{int(origin)}.shadow.{lid}")
    return entries


def _shadow_record(obj: dict, ol: dict, lt: dict, pi: np.ndarray, tol: float, receiver_id: str) -> tuple[dict, list]:
    """Camera-independent shadow data of one polyhedral object under one active light (§5.2/5.3, contract §2.5)."""
    mesh = obj["mesh"]
    oid, lid = obj["id"], lt["id"]
    V4 = to_homogeneous(mesh["vertices"])
    ground_mesh = obj.get("ground_mesh")
    if ground_mesh is None:
        loop_mesh, origins, sil_loops = mesh, None, ol["loops"]
        sil = ol["silhouette_vertices"]
    else:  # contract §2.3: silhouette of the part above the ground (see module docstring)
        loop_mesh, origins = ground_mesh
        lit_c, _parallel = face_lit_flags(loop_mesh, lt["L"], lt["tol_lit"])
        sil_loops = silhouette_loops(loop_mesh, lit_c)
        ef = loop_mesh["edge_faces"]
        edge_sil = lit_c[ef[:, 0]] != lit_c[ef[:, 1]]
        # silhouette vertices of the clipped mesh that are original vertices (a vertex on the plane may
        # be a silhouette vertex here without being one of the full mesh: cut-face edges are silhouette edges)
        sil = np.array(sorted({origins[int(v)] for v in np.unique(loop_mesh["edges"][edge_sil])
                               if isinstance(origins[int(v)], int)}), dtype=np.int64)
    P4 = V4[sil]
    w_S = np.asarray(shadow_w(pi, lt["L"], P4), dtype=np.float64).reshape(-1)
    finite = w_S > lt["tol_w"]
    above = (P4 @ pi) >= -tol
    keep = finite & above
    warnings = []
    if sil.shape[0] and not bool(np.all(finite)):
        warnings.append(make_warning("VERTEX_NOT_BELOW_LIGHT", [oid]))
    S4 = P4 @ lt["M"].T                                           # S = M·P, spec §5.2
    w_safe = np.where(keep, w_S, 1.0)
    S_world = np.where(keep[:, None], S4[:, :3] / w_safe[:, None], 0.0)
    Q4 = foot(pi, P4)                                             # Q, spec §5.3
    Q_world = Q4[:, :3] / Q4[:, 3:4]
    V4c = to_homogeneous(loop_mesh["vertices"])
    loops, ground = [], {}
    unbounded = False
    for loop in sil_loops:
        sh = shadow_loop(V4c[loop], lt["M"], pi, lt["tol_w"], tol_clip=tol)
        entries = _loop_entries(sh, loop, origins, oid, lid, ground)
        unbounded = unbounded or bool(sh["unbounded"])
        loops.append({"vertices": sh["vertices"], "sources": sh["sources"], "entries": entries,
                      "unbounded": bool(sh["unbounded"])})
    ground_points = list(ground.values())
    return {
        "light": lid,
        "receiver": receiver_id,
        "object": oid,
        "vertex_ids": sil,
        "keep": keep,
        "P_world": mesh["vertices"][sil],
        "S_world": S_world,
        "Q_world": Q_world,
        "w_S": w_S,
        "shadow_names": [f"{oid}.v{int(k)}.shadow.{lid}" for k in sil],
        "foot_names": [f"{oid}.v{int(k)}.foot" for k in sil],
        "vertex_names": [obj["point_names"][int(k)] for k in sil],
        "ground_points": ground_points,
        "loops": loops,
        "unbounded": unbounded,
    }, warnings


def shadow_geometry(scene: dict) -> dict:
    """Stage A: camera-independent geometry (contract §3).  Never touches ``scene["camera"]``.

    Returns ``{objects, vertices, bbox, scene_scale, tol, receiver, lights,
    shadows, warnings}``; per object ``lights[<light id>]`` holds the lit flags,
    silhouette edges / vertices / loops (polyhedral objects only).
    """
    objects = [build_object(o) for o in scene["objects"]]
    vertices = np.concatenate([o["mesh"]["vertices"] for o in objects], axis=0)
    scale = scene_scale(vertices)
    tol = tolerance(scale)
    receiver = scene["receivers"][0]
    pi = _receiver_plane(receiver)
    lights = [_light_record(lt, pi, tol) for lt in scene["lights"]]
    warnings = [w for lt in lights for w in lt["warnings"]]
    shadows = []
    for obj in objects:
        obj["lights"] = {}
        if obj["analytic"] is not None:
            # curved primitives: silhouette / terminator / shadow conics from castplane.curved (§5.6)
            shadows.extend(_curved.stage_a_object(obj, lights, pi, tol, receiver["id"], warnings))
            continue
        below = (to_homogeneous(obj["mesh"]["vertices"]) @ pi) < -tol
        obj["ground_mesh"] = None
        if bool(np.any(below)):
            warnings.append(make_warning("OBJECT_BELOW_RECEIVER", [obj["id"]]))
            try:
                obj["ground_mesh"] = clip_mesh_to_plane(obj["mesh"], pi, tol)
            except ValueError:  # degenerate contact: fall back to clipping the silhouette loops
                obj["ground_mesh"] = None
        for lt in lights:
            ol, w = _object_light_data(obj, lt)
            warnings.extend(w)
            obj["lights"][lt["id"]] = ol
            if not lt["active"]:
                shadows.append({"light": lt["id"], "receiver": receiver["id"], "object": obj["id"],
                                "vertex_ids": np.zeros(0, dtype=np.int64), "keep": np.zeros(0, dtype=bool),
                                "P_world": np.zeros((0, 3)), "S_world": np.zeros((0, 3)),
                                "Q_world": np.zeros((0, 3)), "w_S": np.zeros(0),
                                "shadow_names": [], "foot_names": [], "vertex_names": [],
                                "ground_points": [], "loops": [], "unbounded": False})
                continue
            rec, w = _shadow_record(obj, ol, lt, pi, tol, receiver["id"])
            warnings.extend(w)
            shadows.append(rec)
    for rec in shadows:
        # canonical Python lists of the camera-independent world coordinates (shadow points, feet and
        # ground points of the finite silhouette vertices): built once here and shared by reference with
        # every document composed from this stage A (spec §8; see the module docstring)
        keep = np.asarray(rec["keep"], dtype=bool)
        rec["S_lists"] = (np.asarray(rec["S_world"], dtype=np.float64).reshape(-1, 3)[keep] + 0.0).tolist()
        rec["Q_lists"] = (np.asarray(rec["Q_world"], dtype=np.float64).reshape(-1, 3)[keep] + 0.0).tolist()
        rec["G_world"] = np.array([g[1] for g in rec["ground_points"]], dtype=np.float64).reshape(-1, 3)
        rec["G_lists"] = (rec["G_world"] + 0.0).tolist()
    return {
        "objects": objects,
        "vertices": vertices,
        "bbox": (vertices.min(axis=0), vertices.max(axis=0)),
        "scene_scale": scale,
        "tol": tol,
        "receiver": {"id": receiver["id"], "pi": pi},
        "lights": lights,
        "shadows": shadows,
        "warnings": merge_warnings(warnings),
    }


# ---------------------------------------------------------------------------
# stage B
# ---------------------------------------------------------------------------

def _resolve_camera(scene: dict, camera):
    """Scene camera, or a validated override whose frame aspect matches the scene canvas."""
    if camera is None:
        return scene["camera"]
    cam = validate_camera(camera, "camera")
    canvas, frame = scene["output"]["canvas_mm"], cam["frame_mm"]
    if abs(canvas[0] / canvas[1] - frame[0] / frame[1]) > 1e-9:
        from .errors import SceneError
        raise SceneError("camera.frame_mm", "aspect ratio must equal output.canvas_mm aspect ratio")
    return cam


def _project_polygon(cam: dict, V4) -> np.ndarray:
    """Drawing pipeline of contract §2.2 for one homogeneous world polygon -> ``(k, 2)`` mm (may be empty)."""
    V4 = np.asarray(V4, dtype=np.float64).reshape(-1, 4)
    if V4.shape[0] < 3:
        return np.zeros((0, 2))
    V4 = clip_polygon_near(cam, V4)                       # 1. near clip (4-D)
    if V4.shape[0] < 3:
        return np.zeros((0, 2))
    X = clip_polygon_rect_h(project(cam, V4), cam["rect"])  # 2. P ; 3. homogeneous rectangle clip
    if X.shape[0] < 3:
        return np.zeros((0, 2))
    return divide(X)                                      # 4. divide last


#: Width classes of the padded polygon batches (spec §8): polygons are clipped together with
#: others of similar size so that padding stays small.
_POLYGON_BINS = (4, 8, 16, 32, 64, 128, 256)


def _project_polygons(cam: dict, pts, lens) -> list:
    """Batched :func:`_project_polygon` on a zero-padded ``(N, L, 4)`` polygon table -> list of
    ``[[u, v], ...]`` lists (canonical floats) in input order.  Polygons are processed in width
    classes; the per-polygon results are bit-identical to the scalar pipeline."""
    pts = np.asarray(pts, dtype=np.float64)
    lens = np.asarray(lens, dtype=np.int64).reshape(-1)
    out = [[] for _ in range(lens.shape[0])]
    if lens.shape[0] == 0:
        return out
    done = np.zeros(lens.shape[0], dtype=bool)
    for width in _POLYGON_BINS + (int(lens.max()),):
        sel = ~done & (lens <= width)
        if not np.any(sel):
            continue
        idx = np.nonzero(sel)[0]
        done[idx] = True
        uv, l2 = project_polygons(cam, pts[idx][:, :min(width, pts.shape[1])], lens[idx])
        valid = np.arange(uv.shape[1])[None, :] < l2[:, None]
        rows = (uv[valid] + 0.0).tolist()                     # the surviving vertices only, in order
        bounds = np.concatenate([[0], np.cumsum(l2)]).tolist()
        for i, a, b in zip(idx.tolist(), bounds, bounds[1:]):
            if b > a:
                out[i] = rows[a:b]
    return out


def _pad_polygons(polys: list) -> tuple:
    """List of ``(k, 4)`` arrays -> zero-padded ``(N, L, 4)`` table and lengths."""
    lens = np.array([p.shape[0] for p in polys], dtype=np.int64).reshape(-1)
    width = int(lens.max()) if lens.shape[0] else 0
    pts = np.zeros((lens.shape[0], width, 4), dtype=np.float64)
    for k, p in enumerate(polys):
        pts[k, :p.shape[0]] = p
    return pts, lens


def _project_polyhedra(objs: list, cam: dict, tol: float, light_id) -> list:
    """Vectorised projection and clipping of the vertices, edges and unlit faces of all polyhedral
    objects of a scene in a few batched numpy calls (contract §2.2; spec §8).  Returns one stage-B
    record per object (views into the batched arrays)."""
    if not objs:
        return []
    meshes = [o["mesh"] for o in objs]
    n_v = np.array([m["vertices"].shape[0] for m in meshes], dtype=np.int64)
    n_e = np.array([m["edges"].shape[0] for m in meshes], dtype=np.int64)
    n_f = np.array([len(m["faces"]) for m in meshes], dtype=np.int64)
    v_off = np.concatenate([[0], np.cumsum(n_v)[:-1]])
    e_off = np.concatenate([[0], np.cumsum(n_e)[:-1]])
    f_off = np.concatenate([[0], np.cumsum(n_f)[:-1]])
    V = np.concatenate([m["vertices"] for m in meshes], axis=0)
    V4 = to_homogeneous(V)
    nu_v = nu(cam, V4)
    x_h = project(cam, V4)                                   # (n, 3) homogeneous image points
    behind = nu_v < 0.0
    # back flag: both adjacent faces unlit with the camera as light (contract §2.10); the lit test is
    # the fixed-shape einsum of light.face_lit_flags on the concatenated faces
    normals = np.concatenate([m["face_normals"] for m in meshes], axis=0)
    first = np.concatenate([o["face_first"] + off for o, off in zip(objs, v_off.tolist())])
    C4 = np.append(cam["C"], 1.0)
    values = np.einsum("ij,ij->i", normals, C4[None, :3] - C4[3] * V[first])
    face_lit = values > tol
    edges = np.concatenate([m["edges"] + off for m, off in zip(meshes, v_off.tolist())], axis=0)
    ef = np.concatenate([m["edge_faces"] + off for m, off in zip(meshes, f_off.tolist())], axis=0)
    back = ~face_lit[ef[:, 0]] & ~face_lit[ef[:, 1]]
    ols = [o.get("lights", {}).get(light_id) for o in objs]
    silhouette = np.concatenate([ol["edge_silhouette"] if ol is not None else np.zeros(m["edges"].shape[0], dtype=bool)
                                 for ol, m in zip(ols, meshes)])
    # drawing pipeline: near clip (4-D) -> P -> homogeneous rectangle clip -> divide (in compose)
    A, B, keep = clip_segments_near(cam, V4[edges[:, 0]], V4[edges[:, 1]])
    A2, B2 = project(cam, A), project(cam, B)
    A3, B3, keep_rect = clip_segments_rect_h(A2, B2, cam["rect"])
    keep = keep & keep_rect
    segments_h = np.stack([A3, B3], axis=1)                  # (m, 2, 3) homogeneous endpoints
    # form shadow (§6.1 "陰"): the unlit faces (tables cached in stage A) as near-clipped polygons,
    # all objects at once
    counts = [0 if ol is None else int(ol["form_lens"].shape[0]) for ol in ols]
    total = sum(counts)
    if total:
        width = max(ol["form_idx"].shape[1] for ol, c in zip(ols, counts) if c)
        idx = np.full((total, width), -1, dtype=np.int64)
        face_lists, pos = [], 0
        for ol, c, off in zip(ols, counts, v_off.tolist()):
            if c:
                table = ol["form_idx"]
                idx[pos:pos + c, :table.shape[1]] = np.where(table >= 0, table + off, -1)
                face_lists.extend(ol["form_faces"])
                pos += c
        lens = np.concatenate([ol["form_lens"] for ol, c in zip(ols, counts) if c])
        pts = np.where((idx >= 0)[:, :, None], V4[np.where(idx >= 0, idx, 0)], 0.0)
        polygons = _project_polygons(cam, pts, lens)
    else:
        face_lists, polygons = [], []
    out = []
    p_off = 0
    for k, (o, m) in enumerate(zip(objs, meshes)):
        vs, ve = int(v_off[k]), int(v_off[k] + n_v[k])
        es, ee = int(e_off[k]), int(e_off[k] + n_e[k])
        c = counts[k]
        out.append({
            "id": o["id"],
            "type": o["type"],
            "analytic": o["analytic"] is not None,
            "point_names": o["point_names"],
            "world": m["vertices"],
            "world_lists": o["world_lists"],
            "image_h": x_h[vs:ve],
            "depth": x_h[vs:ve, 2],
            "behind": behind[vs:ve],
            "edges": m["edges"],
            "edge_templates": o["edge_templates"],
            "back": back[es:ee],
            "silhouette": silhouette[es:ee],
            "segments_h": segments_h[es:ee],
            "segment_keep": keep[es:ee],
            "form_faces": face_lists[p_off:p_off + c],
            "form_polygons": polygons[p_off:p_off + c],
        })
        p_off += c
    return out


def _project_object(obj: dict, cam: dict, tol: float, light_id) -> dict:
    """Projection and clipping of one object's vertices and edges (contract §2.2): the batched
    :func:`_project_polyhedra` on a single object."""
    return _project_polyhedra([obj], cam, tol, light_id)[0]


def _project_light(lt: dict, cam: dict, tol: float) -> tuple[dict, list]:
    """``L'`` and ``F'`` of one light (contract §2.7): plain division, never nulled."""
    finite = lt["type"] == "point"
    tol_L = tol if finite else TOL_DIR
    lp = special_point_image(cam, lt["L"], tol_L)
    fp = special_point_image(cam, lt["F"], tol_L)
    if not lt.get("F_defined", True):  # vertical directional light: no foot, no shadow vanishing point
        fp = {"h": np.zeros(3), "point": None, "at_infinity": None, "behind": False, "undefined": True}
    warnings = []
    if finite and lp["behind"]:
        warnings.append(make_warning("LIGHT_BEHIND_CAMERA", [lt["id"]]))
    if lp["at_infinity"] is not None:
        warnings.append(make_warning("LIGHT_POINT_AT_INFINITY", [lt["id"]]))
    if fp["at_infinity"] is not None:
        warnings.append(make_warning("SHADOW_VP_AT_INFINITY", [lt["id"]]))
    L, F = lt["L"], lt["F"]
    return {
        "id": lt["id"],
        "type": lt["type"],
        "active": lt["active"],
        "L": L, "F": F,
        "F_defined": lt.get("F_defined", True),
        "light_point": lp, "shadow_vp": fp,
        "L_depth": float(lp["h"][2]) if finite else None,
        "F_depth": float(fp["h"][2]) if finite else None,
    }, warnings


def _ray_kinds(light: dict, P_uv, S_uv, Q_uv) -> list:
    """The 2-D construction segments of contract §2.7 for rows of ``P'``, ``S'``, ``Q'`` (mm):
    ``[(kind, (n, 2, 2) segments), ...]`` in the fixed order ``LP``, ``FQ``, ``PQ``."""
    lp, fp = light["light_point"], light["shadow_vp"]
    kinds = []
    if lp["point"] is not None:
        kinds.append(("LP", covering_segments(np.array(lp["point"]), P_uv, S_uv)))
    elif lp["at_infinity"] is not None:
        kinds.append(("LP", extended_segments(P_uv, S_uv)))
    if fp["point"] is not None:
        kinds.append(("FQ", covering_segments(np.array(fp["point"]), Q_uv, S_uv)))
    elif fp["at_infinity"] is not None:
        kinds.append(("FQ", extended_segments(Q_uv, S_uv)))
    kinds.append(("PQ", np.stack([P_uv, Q_uv], axis=1)))
    return kinds


def _project_shadows(records: list, cam: dict, tol: float, by_id: dict) -> tuple[list, list]:
    """Stage B of all (light, object) shadow records at once (spec §8): points, drawable polygons,
    construction rays and self-checks are computed in batched numpy calls and sliced per record;
    every per-record value equals the one of :func:`_project_shadow`."""
    if not records:
        return [], []
    counts = np.array([rec["keep"].shape[0] for rec in records], dtype=np.int64)
    offs = np.concatenate([[0], np.cumsum(counts)])
    keep = np.concatenate([rec["keep"] for rec in records])
    P4 = to_homogeneous(np.concatenate([rec["P_world"] for rec in records], axis=0))
    S4 = to_homogeneous(np.concatenate([rec["S_world"] for rec in records], axis=0))
    Q4 = to_homogeneous(np.concatenate([rec["Q_world"] for rec in records], axis=0))
    xP, xS, xQ = project(cam, P4), project(cam, S4), project(cam, Q4)
    nuP, nuS, nuQ = nu(cam, P4), nu(cam, S4), nu(cam, Q4)
    S_behind, Q_behind = nuS < 0.0, nuQ < 0.0
    behind_any = keep & (S_behind | Q_behind)
    # ground-crossing points (their own shadow and foot)
    G_list = [rec["G_world"] if "G_world" in rec else
              np.array([g[1] for g in rec["ground_points"]], dtype=np.float64).reshape(-1, 3) for rec in records]
    g_counts = np.array([g.shape[0] for g in G_list], dtype=np.int64)
    g_offs = np.concatenate([[0], np.cumsum(g_counts)])
    G4 = to_homogeneous(np.concatenate(G_list, axis=0))
    xG, nuG = project(cam, G4), nu(cam, G4)
    G_behind = nuG < 0.0
    # drawable polygons (contract §2.5: full drawing pipeline, rectangle clip always applied)
    loop_owner = [k for k, rec in enumerate(records) for _loop in rec["loops"]]
    polys = _project_polygons(cam, *_pad_polygons([np.asarray(loop["vertices"], dtype=np.float64).reshape(-1, 4)
                                                   for rec in records for loop in rec["loops"]]))
    per_rec_polys = [[] for _ in records]
    for k, poly in zip(loop_owner, polys):
        per_rec_polys[k].append(poly)
    # construction rays (contract §2.7): only rows with P, S, Q all in front
    ok = keep & (nuP >= 0.0) & (nuS >= 0.0) & (nuQ >= 0.0)
    P_uv = divide(np.where(ok[:, None], xP, _ORIGIN_H))
    S_uv = divide(np.where(ok[:, None], xS, _ORIGIN_H))
    Q_uv = divide(np.where(ok[:, None], xQ, _ORIGIN_H))
    vertex_names = np.array([nm for rec in records for nm in rec["vertex_names"]], dtype=object)
    shadow_names = np.array([nm for rec in records for nm in rec["shadow_names"]], dtype=object)
    ok_cum = np.concatenate([[0], np.cumsum(ok)])
    keep_cum = np.concatenate([[0], np.cumsum(keep)])
    n_ok_rec = ok_cum[offs[1:]] - ok_cum[offs[:-1]]          # ok / finite rows per record
    n_keep_rec = keep_cum[offs[1:]] - keep_cum[offs[:-1]]
    # per light: rays and self-checks over the concatenated rows of that light's records
    light_recs: dict = {}
    for k, rec in enumerate(records):
        light_recs.setdefault(rec["light"], []).append(k)
    segments = [[] for _ in records]
    checks = [[] for _ in records]
    rays = [[] for _ in records]
    out, warnings = [], []
    for lid, rec_idx in light_recs.items():
        light = by_id[lid]
        whole = len(rec_idx) == len(records)
        rows_ok = np.nonzero(ok)[0] if whole else \
            np.nonzero(np.concatenate([ok[offs[k]:offs[k + 1]] for k in rec_idx]))[0]
        rows_all = np.arange(ok.shape[0]) if whole else \
            np.concatenate([np.arange(offs[k], offs[k + 1]) for k in rec_idx])
        rows_ok = rows_all[rows_ok]
        n_ok = int(rows_ok.shape[0])
        lp_undefined = bool(light["light_point"].get("undefined"))
        fp_undefined = bool(light["shadow_vp"].get("undefined"))
        ray_kinds = ([] if lp_undefined else ["L"]) + ([] if fp_undefined else ["F"])
        if n_ok:
            names_ok = vertex_names[rows_ok]
            kinds = _ray_kinds(light, P_uv[rows_ok], S_uv[rows_ok], Q_uv[rows_ok])
            n_k = len(kinds)
            clipped, kept = clip_segments_uv(np.concatenate([seg for _k, seg in kinds], axis=0), cam["rect"])
            # entries interleaved per vertex in kind order (row r of kind j sits at j * n_ok + r)
            order = (np.arange(n_ok)[:, None] + n_ok * np.arange(n_k)[None, :]).ravel()
            sel = order[kept[order]]
            kind_names = np.array([kind for kind, _seg in kinds], dtype=object)
            flat = [{"kind": kind, "point": nm, "points": p}
                    for kind, nm, p in zip(kind_names[sel // n_ok].tolist(), names_ok[sel % n_ok].tolist(),
                                           (clipped[sel] + 0.0).tolist())]
            per_vertex = np.sum(kept.reshape(n_k, n_ok), axis=0)        # kept segments per ok vertex
            seg_cum = np.concatenate([[0], np.cumsum(per_vertex)])
            # the §3.1 ``rays`` list: one ["L", name] / ["F", name.foot] pair per ok vertex
            names_ok_list = names_ok.tolist()
            ray_flat = [[kind, nm if kind == "L" else f"{nm}.foot"] for nm in names_ok_list for kind in ray_kinds]
            pos = 0
            for k in rec_idx:
                n_rows = int(n_ok_rec[k])
                segments[k] = flat[seg_cum[pos]:seg_cum[pos + n_rows]]
                rays[k] = ray_flat[pos * len(ray_kinds):(pos + n_rows) * len(ray_kinds)]
                pos += n_rows
        # self-check (spec §5.5) for every finite shadow point; degenerate forms when L' or F' is undefined
        rows_keep = rows_all[np.nonzero(keep[rows_all])[0]]
        if lp_undefined:    # light at the camera centre: S' = P'
            err, skipped = coincidence_check(xS[rows_keep], xP[rows_keep], tol)
        elif fp_undefined:  # directional light along the receiver normal: S' = Q'
            err, skipped = coincidence_check(xS[rows_keep], xQ[rows_keep], tol)
        else:
            err, skipped = self_check(light["light_point"]["h"], xP[rows_keep], light["shadow_vp"]["h"],
                                      xQ[rows_keep], xS[rows_keep], tol)
        names_keep = shadow_names[rows_keep]
        good = ~skipped
        check_flat = [{"point": nm, "max_error_mm": e}
                      for nm, e in zip(names_keep[good].tolist(), (err[good] + 0.0).tolist())]
        for nm in names_keep[skipped].tolist():
            warnings.append(make_warning("CONSTRUCTION_CHECK_SKIPPED", [nm]))
        good_cum = np.concatenate([[0], np.cumsum(good)])
        pos = 0
        for k in rec_idx:
            n_rows = int(n_keep_rec[k])
            checks[k] = check_flat[good_cum[pos]:good_cum[pos + n_rows]]
            pos += n_rows
    behind_cum = np.concatenate([[0], np.cumsum(behind_any)])
    for k, rec in enumerate(records):
        a, b = int(offs[k]), int(offs[k + 1])
        ga, gb = int(g_offs[k]), int(g_offs[k + 1])
        if behind_cum[b] > behind_cum[a]:
            warnings.append(make_warning("POINT_BEHIND_CAMERA", [rec["object"]]))
        out.append({
            "light": rec["light"],
            "receiver": rec["receiver"],
            "object": rec["object"],
            "keep": rec["keep"],
            "shadow_names": rec["shadow_names"],
            "foot_names": rec["foot_names"],
            "S_world": rec["S_world"], "S_h": xS[a:b], "S_behind": S_behind[a:b],
            "Q_world": rec["Q_world"], "Q_h": xQ[a:b], "Q_behind": Q_behind[a:b],
            "ground_names": [g[0] for g in rec["ground_points"]],
            "G_world": G_list[k], "G_h": xG[ga:gb], "G_behind": G_behind[ga:gb],
            "S_lists": rec.get("S_lists"), "Q_lists": rec.get("Q_lists"), "G_lists": rec.get("G_lists"),
            "loops": [loop["entries"] for loop in rec["loops"]],
            "polygons": per_rec_polys[k],
            "unbounded": rec["unbounded"],
            "rays": rays[k],
            "segments": segments[k],
            "checks": checks[k],
        })
    return out, warnings


def _project_shadow(rec: dict, cam: dict, tol: float, light: dict) -> tuple[dict, list]:
    """Stage B of one (light, object) shadow record: the batched :func:`_project_shadows` on one record."""
    out, warnings = _project_shadows([rec], cam, tol, {light["id"]: light})
    return out[0], warnings


def project_scene(scene: dict, A: dict, camera=None) -> dict:
    """Stage B: project stage-A geometry with the scene camera or an override (contract §3)."""
    cam_dict = _resolve_camera(scene, camera)
    canvas = scene["output"]["canvas_mm"]
    cam = camera_matrix(cam_dict, canvas)
    scale = scene_scale(A["vertices"], cam["C"])
    tol = tolerance(scale)
    warnings = list(cam["warnings"]) + list(A["warnings"])
    light_id = A["lights"][0]["id"] if A.get("lights") else None
    # all polyhedral objects are projected together, and so are all curved ones (spec §8)
    poly_recs = iter(_project_polyhedra([o for o in A["objects"] if o["analytic"] is None], cam, tol, light_id))
    objects, curved_objs, curved_recs = [], [], []
    for obj in A["objects"]:
        if obj["analytic"] is not None:
            # curved object: outline / terminator / shadow conics and named points from castplane.curved;
            # its approximate mesh is never projected (contract §2.4)
            rec = {"id": obj["id"], "type": obj["type"], "analytic": True}
            curved_objs.append(obj)
            curved_recs.append(rec)
        else:
            rec = next(poly_recs)
            if bool(np.any(rec["behind"])):
                warnings.append(make_warning("POINT_BEHIND_CAMERA", [obj["id"]]))
        objects.append(rec)
    _curved.stage_b_objects(curved_objs, curved_recs, cam, tol, warnings)
    lights = []
    for lt in A.get("lights", []):
        lrec, w = _project_light(lt, cam, tol)
        warnings.extend(w)
        lights.append(lrec)
    by_id = {lt["id"]: lt for lt in lights}
    shadows, w = _project_shadows(list(A.get("shadows", [])), cam, tol, by_id)
    warnings.extend(w)
    construction = None
    if lights:
        lt = lights[0]
        construction = {
            "light_point": lt["light_point"]["point"],
            "light_point_at_infinity": lt["light_point"]["at_infinity"],
            "shadow_vp": lt["shadow_vp"]["point"],
            "shadow_vp_at_infinity": lt["shadow_vp"]["at_infinity"],
            "rays": list(chain.from_iterable(s["rays"] for s in shadows)),
            "checks": list(chain.from_iterable(s["checks"] for s in shadows)),
            "segments": list(chain.from_iterable(s["segments"] for s in shadows)),
        }
    return {
        "camera": cam,
        "scene_scale": scale,
        "tol": tol,
        "objects": objects,
        "lights": lights,
        "horizon": camera_horizon(cam, TOL_DIR),
        "shadows": shadows,
        "construction": construction,
        "warnings": merge_warnings(warnings),
    }


# ---------------------------------------------------------------------------
# stage C
# ---------------------------------------------------------------------------

def _finite_points(points: dict, names, world, x_h, behind):
    """Fill ``points`` with finite entries ``{world, image | null, depth}`` (bulk canonical floats).
    ``world`` is an ``(n, 3)`` array or an already canonical list of ``[x, y, z]`` lists (shared with
    the cached stage A, see the module docstring)."""
    if not names:
        return
    behind = np.asarray(behind, dtype=bool)
    x_h = np.asarray(x_h, dtype=np.float64)
    if bool(np.any(behind)):
        uv = (divide(np.where(behind[:, None], _ORIGIN_H, x_h)) + 0.0).tolist()
    else:
        uv = (divide(x_h) + 0.0).tolist()
    if not isinstance(world, list):
        world = (np.asarray(world, dtype=np.float64) + 0.0).tolist()
    depth = (x_h[:, 2] + 0.0).tolist()
    if bool(np.any(behind)):
        entries = [{"world": w, "image": None if b else u, "depth": d}
                   for w, u, d, b in zip(world, uv, depth, behind.tolist())]
    else:
        entries = [{"world": w, "image": u, "depth": d} for w, u, d in zip(world, uv, depth)]
    points.update(zip(names, entries))


def _light_points(points: dict, lt: dict):
    """``L.<light>`` / ``F.<light>`` entries (contract §3.1): finite or direction points, never nulled."""
    for prefix, X, img, depth in (("L", lt["L"], lt["light_point"], lt["L_depth"]),
                                  ("F", lt["F"], lt["shadow_vp"], lt["F_depth"])):
        name = f"{prefix}.{lt['id']}"
        if prefix == "F" and not lt.get("F_defined", True):
            continue  # the foot of a directional light along the receiver normal is undefined
        if lt["type"] == "point":
            points[name] = {"world": [float(X[0]) + 0.0, float(X[1]) + 0.0, float(X[2]) + 0.0],
                            "image": img["point"], "depth": float(depth) + 0.0}
        else:
            points[name] = {"direction": [float(X[0]) + 0.0, float(X[1]) + 0.0, float(X[2]) + 0.0],
                            "at_infinity": True, "image": img["point"]}


def _arc_drawables(a: dict) -> dict:
    """Drawables (canvas mm) of a stage-B arc record (contract §2.6 output rules): ``ellipses`` for a
    whole circle in front of the near plane whose image is a healthy ellipse and of which some part
    lies inside the extended canvas (``visible`` non-empty; the whole ``<ellipse>`` is then written and
    overflows the canvas harmlessly, contract §2.2), ``arcs`` (SVG ``A`` parameters, flags decided by
    the arc midpoint) for visible ellipse arcs, sampled ``polylines`` (64 segments per full circle,
    proportionally fewer, minimum 8) otherwise.  Nothing is drawn when ``visible`` is empty."""
    out = {"polylines": [], "arcs": [], "ellipses": []}
    H, rho = a["H"], a["rho"]
    healthy = a["kind"] == "ellipse" and not a["sampled"]
    if a["whole_circle"] and healthy and a["visible"]:
        params = ellipse_params(np.array(a["conic"]))
        if params is not None:
            centre, (major, minor), rot = params
            out["ellipses"].append({"centre": [float(centre[0]) + 0.0, float(centre[1]) + 0.0],
                                    "rx": float(major) + 0.0, "ry": float(minor) + 0.0,
                                    "rotation_deg": math.degrees(rot) + 0.0})
            return out
    for lo, hi in a["visible"]:
        if healthy:
            p = ellipse_arc_params(H, rho, lo, hi)
            if p is not None:
                out["arcs"].append({"start": (p["start"] + 0.0).tolist(), "end": (p["end"] + 0.0).tolist(),
                                    "rx": p["axes"][0] + 0.0, "ry": p["axes"][1] + 0.0,
                                    "rotation_deg": math.degrees(p["rotation"]) + 0.0,
                                    "large_arc": p["large_arc"], "sweep": p["sweep"],
                                    "theta": [lo + 0.0, hi + 0.0]})
                continue
        pts = sample_arc(H, rho, lo, hi, sample_count(lo, hi))          # (n + 1, 3), all x3 > 0
        out["polylines"].append((divide(pts) + 0.0).tolist())
    return out


def _conic_doc_entry(a: dict, with_back: bool = False) -> dict:
    """Contract §3.1 conic entry ``{conic, kind, arc, circle, map}`` (+ ``sampled``, ``which`` and the
    drawables of :func:`_arc_drawables`; ``back`` for objects-layer arcs)."""
    entry = {"conic": a["conic"], "kind": a["kind"], "arc": a["arc"], "circle": a["circle"], "map": a["map"],
             "sampled": bool(a["sampled"]), "which": a["which"],
             "visible": [[lo + 0.0, hi + 0.0] for lo, hi in a["visible"]]}
    if with_back:
        entry["back"] = bool(a["back"])
    entry.update(_arc_drawables(a))
    return entry


def _segment_uv(seg_h, keep: bool):
    return (divide(np.asarray(seg_h)) + 0.0).tolist() if keep else None


def _compose_curved(rec: dict, points: dict, edges: list, form_shadow: list, outlines: list) -> dict:
    """Stage C of a curved object: named points, outline generators / conics, terminator entries.
    Returns ``{light id: [shadow conic entries]}`` for the ``shadows`` block."""
    oid = rec["id"]
    _finite_points(points, rec["point_names"], rec["world"], rec["image_h"], rec["behind"])
    generators = [{"from": e["from"], "to": e["to"], "back": False, "segment": _segment_uv(e["segment_h"], e["keep"])}
                  for e in rec["gen_edges"]]
    outlines.append({"object": oid, "generators": generators,
                     "conics": [_conic_doc_entry(a, with_back=True) for a in rec["outline_arcs"]]})
    term = []
    for items in rec["terminator"].values():
        for it in items:
            if "segment" in it:
                seg = _segment_uv(it["segment_h"], it["keep"])
                term.append({"segment": list(it["segment"]), "polylines": [seg] if seg is not None else []})
            else:
                term.append(_conic_doc_entry(it))
    if term:
        form_shadow.append({"object": oid, "faces": [], "terminator": term, "polygons": []})
    return {lid: [_conic_doc_entry(a) for a in arcs] for lid, arcs in rec["shadow_arcs"].items()}


def compose(scene: dict, B: dict) -> dict:
    """Stage C: the §6.2 geometry document (contract §3.1), canonical floats, sorted point names."""
    cam = B["camera"]
    points, edges, outlines = {}, [], []
    form_entries = []        # (object index, form_shadow entry): the block keeps the object order
    conics_by = {}
    for k, rec in enumerate(B["objects"]):
        if rec.get("analytic"):
            # contract §2.4 / §2.10: a curved primitive contributes its outline generators, cap conics,
            # terminator and construction points, never its approximate mesh
            curved_form = []
            for lid, entries in _compose_curved(rec, points, edges, curved_form, outlines).items():
                conics_by[(rec["id"], lid)] = entries
            form_entries.extend((k, e) for e in curved_form)
    # polyhedral objects: bulk conversion to Python floats (+ 0.0 canonicalises -0.0) over all objects at
    # once keeps the per-edge / per-point work to one dict literal each (§8 performance)
    poly = [(k, rec) for k, rec in enumerate(B["objects"]) if not rec.get("analytic")]
    if poly:
        poly_index = [k for k, _rec in poly]
        poly = [rec for _k, rec in poly]
        _finite_points(points, list(chain.from_iterable(rec["point_names"] for rec in poly)),
                       list(chain.from_iterable(rec["world_lists"] for rec in poly)),
                       np.concatenate([rec["image_h"] for rec in poly], axis=0),
                       np.concatenate([rec["behind"] for rec in poly]))
        keep_all = np.concatenate([rec["segment_keep"] for rec in poly])
        seg_all = np.concatenate([rec["segments_h"] for rec in poly], axis=0)
        seg_uv_all = (divide(np.where(keep_all[:, None, None], seg_all, _ORIGIN_H)) + 0.0).tolist()
        keep_all = keep_all.tolist()
        pos = 0
        for k, rec in zip(poly_index, poly):
            m = rec["edges"].shape[0]
            seg_uv, keep = seg_uv_all[pos:pos + m], keep_all[pos:pos + m]
            pos += m
            # one copy of the camera-free template per edge plus the three dependent keys (spec §8)
            for t, s, b, seg, kp in zip(rec["edge_templates"], rec["silhouette"].tolist(), rec["back"].tolist(),
                                        seg_uv, keep):
                e = t.copy()
                e["silhouette"] = s
                e["back"] = b
                e["segment"] = seg if kp else None
                edges.append(e)
            if rec["form_faces"]:
                form_entries.append((k, {"object": rec["id"], "faces": rec["form_faces"], "terminator": [],
                                         "polygons": rec["form_polygons"]}))
    form_entries.sort(key=lambda t: t[0])
    form_shadow = [e for _k, e in form_entries]
    for lt in B.get("lights", []):
        _light_points(points, lt)
    shadows = []
    recs = B.get("shadows", [])
    if recs:
        # the shadow points, feet and ground points of all records in three bulk conversions
        keep_all = np.concatenate([np.asarray(s["keep"], dtype=bool) for s in recs])
        keep_list = keep_all.tolist()
        for key_names, key_w, key_l, key_h, key_b, masked in (
                ("shadow_names", "S_world", "S_lists", "S_h", "S_behind", True),
                ("foot_names", "Q_world", "Q_lists", "Q_h", "Q_behind", True),
                ("ground_names", "G_world", "G_lists", "G_h", "G_behind", False)):
            names = [n for s in recs for n in s[key_names]]
            x_h = np.concatenate([np.asarray(s[key_h]).reshape(-1, 3) for s in recs], axis=0)
            behind = np.concatenate([np.asarray(s[key_b]).reshape(-1) for s in recs])
            if masked:
                names = [n for n, f in zip(names, keep_list) if f]
                x_h, behind = x_h[keep_all], behind[keep_all]
            if all(s.get(key_l) is not None for s in recs):   # the stage-A lists (already masked)
                world = list(chain.from_iterable(s[key_l] for s in recs))
            else:
                world = np.concatenate([np.asarray(s[key_w]).reshape(-1, 3) for s in recs], axis=0)
                if masked:
                    world = world[keep_all]
            _finite_points(points, names, world, x_h, behind)
    for s in recs:
        shadows.append({
            "light": s["light"],
            "receiver": s["receiver"],
            "object": s["object"],
            "outline": s["loops"][0] if s["loops"] else [],
            "loops": list(s["loops"]),
            "conics": conics_by.get((s["object"], s["light"]), []),
            "unbounded": bool(s["unbounded"]),
            "polygons": s["polygons"],
        })
    hz = B["horizon"]
    construction = B["construction"] or {
        "light_point": None, "light_point_at_infinity": None,
        "shadow_vp": None, "shadow_vp_at_infinity": None,
        "rays": [], "checks": [], "segments": [],
    }
    # points, edges, shadows, form_shadow, outlines and the construction lists (rays, checks, segments)
    # are canonical by construction (every float went through ``+ 0.0`` in bulk, contract §2.8);
    # only the small blocks go through canonical()
    doc = canonical({
        "canvas_mm": [float(c) for c in cam["canvas_mm"]],
        "camera": {
            "P": cam["P"].tolist(),
            "C": cam["C"].tolist(),
            "horizon_line": list(hz["line"]),
            "principal_point": [cam["u0"], cam["v0"]],
        },
        "construction": {k: v for k, v in construction.items() if k not in ("rays", "checks", "segments")},
        "horizon": {
            "v_mm": hz["v_mm"],
            "line": list(hz["line"]),
            "segment": hz["segment"],
            "vanishing_points": dict(hz["vanishing_points"]),
        },
        "warnings": list(B["warnings"]),
    })
    doc["construction"].update({k: list(construction[k]) for k in ("rays", "checks", "segments")})
    doc["points"] = points
    doc["edges"] = edges
    doc["shadows"] = shadows
    doc["form_shadow"] = form_shadow
    doc["outlines"] = outlines
    return doc


def render(scene: dict, camera=None) -> dict:
    """Run stages A, B, C and write the SVG with the scene's layer subset (contract §3)."""
    A = shadow_geometry(scene)
    B = project_scene(scene, A, camera=camera)
    doc = compose(scene, B)
    return {"geometry": doc, "svg": write_svg(doc, layers=scene["output"]["layers"])}

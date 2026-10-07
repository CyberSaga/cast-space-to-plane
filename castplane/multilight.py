"""Multi-light assembly helpers (contract §5.3.2, §5.3.3, §5.3.5; M6).

A scene is *multi-light* iff it has at least two lights (:func:`is_multi`).  Every light is
evaluated with the v1 / M4 formulas exactly as if it were alone; this module holds the small,
pure pieces that turn those per-light results into the multi-light parts of stages B and C, so
that the shared pipeline files only need hooks:

- names: :func:`curved_stem_name` (light-dependent curved base names get the light id as their
  last segment, §5.3.2) and :func:`multi_light_name` (the single-light → multi-light name map of
  the bit-identity statement);
- edges: :func:`silhouette_lights` (``edges[].silhouette`` as the OR over lights and the additive
  ``edges[].silhouette_lights``) and :func:`plate_silhouette_lights` (a receiver's bounds edges);
- form shadow: :func:`unlit_union` / :func:`form_table` (the faces unlit by at least one light,
  projected once), :func:`split_form` (per-light lists and the core sharing the same drawables),
  :func:`plate_form_lights` (plates as one-face polyhedra), :func:`assemble_form_shadow`
  (``form_shadow[]`` light-major with ``light``, and ``form_shadow_core[]``);
- construction: :func:`construction_block` / :func:`construction_blocks` (one M4 construction
  block per light, incl. ``per_receiver``; ``construction`` stays the alias of the first light)
  and :func:`construction_doc` (the canonical document block);
- umbra: :func:`active_lights` and :func:`umbra_entries` (one ``umbra[]`` entry per receiver from
  the stage-B drawables, through :mod:`castplane.umbra`).

Core module: numpy only, no file access, no camera access of its own (every camera-dependent
input is a stage-B value handed in by the caller).
"""

from __future__ import annotations

import re
from itertools import chain

import numpy as np

from . import umbra as _umbra
from .output.geometry_json import canonical

__all__ = [
    "is_multi", "is_light_dependent_stem", "curved_stem_name", "multi_light_name",
    "silhouette_lights", "plate_silhouette_lights",
    "unlit_union", "form_table", "split_form", "plate_form_lights", "assemble_form_shadow",
    "construction_block", "construction_blocks", "construction_doc",
    "active_lights", "umbra_entries",
]

#: The light-dependent curved stems (``sil.<k>``, ``g<k>.base``, ``g<k>.top``, contract §5.3.2).
_LIGHT_STEM = re.compile(r"^(sil\.\d+|g\d+\.(?:base|top))(?=\.|$)")


def is_multi(lights) -> bool:
    """A scene (or its ``lights`` list) is multi-light iff it has at least two lights (§5.3)."""
    if isinstance(lights, dict):
        lights = lights.get("lights", [])
    return len(lights) >= 2


def is_light_dependent_stem(stem: str) -> bool:
    """``sil.<k>``, ``g<k>.base`` and ``g<k>.top`` depend on the light; ``c``, ``apex``,
    ``og<k>.base|top`` and the polyhedral ``v<k>`` do not (contract §5.3.2)."""
    m = _LIGHT_STEM.match(stem)
    return m is not None and m.end() == len(stem)


def curved_stem_name(obj_id: str, stem: str, light_id: str, multi: bool) -> str:
    """The **base** name of a curved construction point (contract §5.3.2, §5.0.4):
    ``<obj>.<stem>``, plus ``.<light>`` iff ``multi`` and the stem is light dependent.  Shadow and
    foot names are composed from it by appending ``.shadow.<light>[.<r>]`` / ``.foot[.<r>]``."""
    base = f"{obj_id}.{stem}"
    if multi and is_light_dependent_stem(stem):
        return f"{base}.{light_id}"
    return base


def multi_light_name(name: str, light_id: str, object_ids=None) -> str:
    """The name map of the bit-identity statement (contract §5.3.2): a point name of the
    single-light document of light ``light_id`` → its name in the multi-light document
    (``sil.<k>`` → ``sil.<k>.<light>``, ``g<k>.base|top`` → ``g<k>.base|top.<light>``, applied
    right after the object id; every other name is unchanged).  With ``object_ids`` only names
    whose first part is one of them are mapped (so ``F.<light>.<r>`` can never be mistaken for a
    curved stem whatever the ids are)."""
    head, sep, rest = name.partition(".")
    if not sep or (object_ids is not None and head not in object_ids):
        return name
    m = _LIGHT_STEM.match(rest)
    if m is None:
        return name
    return f"{head}.{rest[:m.end()]}.{light_id}{rest[m.end():]}"


# ---------------------------------------------------------------------------
# edges (contract §5.3.3)
# ---------------------------------------------------------------------------

def silhouette_lights(edge_flags, light_ids, n_edges: int):
    """``edges[].silhouette`` and ``edges[].silhouette_lights`` of one polyhedral object.

    ``edge_flags[k]`` is ``obj["lights"][light_ids[k]]["edge_silhouette"]`` (a bool array over the
    object's edges) or ``None`` when the object has no record for that light (no silhouette edge).
    Returns ``(silhouette, lists)``: the OR over lights (bool array, unchanged for ``N = 1``) and,
    per edge, the ids of the lights for which it is a silhouette edge (scene order, ``[]`` allowed).
    ``n_edges`` (= ``len(obj["edge_templates"])``) is required so that an object with no record for
    any light still gets one all-``False`` flag per edge; a flag array of another length is a
    caller error (``ValueError``)."""
    arrays = [None if f is None else np.asarray(f, dtype=bool).reshape(-1) for f in edge_flags]
    n_edges = int(n_edges)
    table = np.zeros((len(light_ids), n_edges), dtype=bool)
    for k, a in enumerate(arrays):
        if a is not None:
            if a.shape[0] != n_edges:
                raise ValueError(f"edge_flags[{k}] has {a.shape[0]} flags, expected {n_edges}")
            table[k] = a
    silhouette = table.any(axis=0)
    ids = list(light_ids)
    lists = [[ids[k] for k in np.flatnonzero(col).tolist()] for col in table.T]
    return silhouette, lists


def plate_silhouette_lights(casts: dict, light_ids) -> list:
    """``silhouette_lights`` of a bounded receiver's bounds edges: the lights for which the plate
    casts (``receivers[r].casts[k]``), scene order (contract §5.3.3)."""
    return [lid for lid in light_ids if bool(casts.get(lid, False))]


# ---------------------------------------------------------------------------
# form shadow and core (contract §5.3.1, §5.3.3, §5.3.5)
# ---------------------------------------------------------------------------

def unlit_union(lit_by_light):
    """Faces unlit by at least one light (contract §5.3.3).

    ``lit_by_light[k]`` is the face lit-flag array of light ``k`` (``obj["lights"][lid]["lit"]``:
    "parallel" already counts as unlit, a light inside the solid already makes every face unlit) or
    ``None`` for a light without a record (all faces lit by it).  Returns ``(union, masks, core)``:
    the face indices of the union in face-index order, per light a bool mask over ``union`` (that
    light's unlit faces, its v1 set in face-index order) and the bool mask over ``union`` of the
    **core** faces (unlit by every light).  For ``N = 1`` the union is the v1 unlit set."""
    arrays = [None if f is None else np.asarray(f, dtype=bool).reshape(-1) for f in lit_by_light]
    n = next((a.shape[0] for a in arrays if a is not None), 0)
    unlit = np.zeros((len(arrays), n), dtype=bool)
    for k, a in enumerate(arrays):
        if a is not None:
            unlit[k] = ~a
    union = np.flatnonzero(unlit.any(axis=0)) if len(arrays) else np.zeros(0, dtype=np.int64)
    masks = [row[union] for row in unlit]
    core = unlit[:, union].all(axis=0) if len(arrays) else np.zeros(0, dtype=bool)
    return union.astype(np.int64), masks, core


def form_table(obj: dict, light_ids):
    """The padded vertex-index table of the faces unlit by at least one light of one polyhedral
    stage-A object (the multi-light replacement of the per-light ``form_idx`` / ``form_lens`` /
    ``form_faces`` of ``pipeline._object_light_data``; for ``N = 1`` exactly those arrays).
    Returns ``{"form_idx", "form_lens", "form_faces", "masks", "core"}``."""
    lights = obj.get("lights", {})
    lit = [lights[lid]["lit"] if lid in lights else None for lid in light_ids]
    union, masks, core = unlit_union(lit)
    names = obj["face_point_names"]
    return {
        "form_idx": obj["faces_padded"][union],
        "form_lens": obj["face_lens"][union],
        "form_faces": [names[k] for k in union.tolist()],
        "masks": masks,
        "core": core,
    }


def split_form(faces: list, polygons: list, masks, core, light_ids):
    """Per-light lists and the core of one object from the projected union (contract §5.3.3):
    ``form_by_light[lid] = (faces, polygons)`` (that light's unlit faces, face-index order) and
    ``form_core = (faces, polygons)`` (faces unlit by all lights).  The lists reference the same
    drawable objects as ``faces`` / ``polygons`` (projected once)."""
    by_light = {}
    for lid, mask in zip(light_ids, masks):
        idx = np.flatnonzero(np.asarray(mask, dtype=bool)).tolist()
        by_light[lid] = ([faces[i] for i in idx], [polygons[i] for i in idx])
    idx = np.flatnonzero(np.asarray(core, dtype=bool)).tolist()
    return by_light, ([faces[i] for i in idx], [polygons[i] for i in idx])


def plate_form_lights(light_sides, tol_ws, cam_side: float, tol: float):
    """Plates as one-face polyhedra (contract §5.1.8, §5.3.3): ``light_sides[k] = π_rᵀL_k`` and
    ``tol_ws[k]`` its tolerance (stage A), ``cam_side = n_r·(C − b_0)`` (stage B).  Returns
    ``(flags, core)``: ``flags[k]`` is the single-light rule of light ``k`` (the camera faces the
    side of the plate unlit by that light, both signs strictly beyond their tolerances), ``core``
    is true iff the camera side is decided and **no** light is strictly on the camera's side
    ("parallel" counts as unlit)."""
    if not abs(cam_side) > tol:
        return [False] * len(light_sides), False
    cam_pos = cam_side > 0.0
    flags, lit_any = [], False
    for side, tw in zip(light_sides, tol_ws):
        decided = abs(side) > tw
        flags.append(bool(decided and (side > 0.0) != cam_pos))
        lit_any |= bool(decided and (side > 0.0) == cam_pos)
    return flags, (not lit_any) and len(flags) > 0


def assemble_form_shadow(items: list, light_ids):
    """``form_shadow[]`` and ``form_shadow_core[]`` of a multi-light document (contract §5.3.5).

    ``items`` is in document object order (objects in scene order, then the plates), each
    ``{"object": id, "by_light": {lid: {"faces", "polygons", "terminator"}}, "core": None |
    {"faces", "polygons"}}`` (a light missing from ``by_light`` contributes nothing).  Returns
    ``(form_shadow, form_shadow_core)``: one entry ``{light, object, faces, polygons, terminator}``
    per (light, object) with unlit faces or a terminator, light-major (scene order) then object
    order; one core entry ``{object, faces, polygons}`` per object with at least one core face."""
    form = []
    for lid in light_ids:
        for it in items:
            e = it.get("by_light", {}).get(lid)
            if e is None or not (e.get("faces") or e.get("terminator")):
                continue
            form.append({"light": lid, "object": it["object"], "faces": list(e.get("faces", [])),
                         "polygons": list(e.get("polygons", [])), "terminator": list(e.get("terminator", []))})
    core = []
    for it in items:
        c = it.get("core")
        if c is not None and c.get("faces"):
            core.append({"object": it["object"], "faces": list(c["faces"]), "polygons": list(c["polygons"])})
    return form, core


# ---------------------------------------------------------------------------
# construction per light (contract §5.3.3, §5.3.5)
# ---------------------------------------------------------------------------

def _lists(shadows: list, key: str) -> list:
    return list(chain.from_iterable(s[key] for s in shadows))


def construction_block(light: dict, receiver_lights: dict, shadows: list, default_id: str) -> dict:
    """One light's M4 construction block (contract §5.3.3): ``light`` is the stage-B record of
    ``pipeline._project_light`` (default receiver), ``receiver_lights[<r>]`` the stage-B records of
    every other receiver (one per light, scene order), ``shadows`` the stage-B records.  The flat
    ``rays`` / ``checks`` / ``segments`` concatenate that light's records on the default receiver in
    ``shadows[]`` order; ``per_receiver[<r>]`` those on receiver ``r``.  For ``N = 1`` this is the
    v1 / M4 ``construction`` block."""
    lid = light["id"]
    own = [s for s in shadows if s["receiver"] == default_id and s["light"] == lid]
    block = {
        "light_point": light["light_point"]["point"],
        "light_point_at_infinity": light["light_point"]["at_infinity"],
        "shadow_vp": light["shadow_vp"]["point"],
        "shadow_vp_at_infinity": light["shadow_vp"]["at_infinity"],
        "rays": _lists(own, "rays"),
        "checks": _lists(own, "checks"),
        "segments": _lists(own, "segments"),
        "per_receiver": {},
    }
    for rid, recs in receiver_lights.items():
        lt_r = next((r for r in recs if r["id"] == lid), None)
        if lt_r is None:
            continue
        own_r = [s for s in shadows if s["receiver"] == rid and s["light"] == lid]
        block["per_receiver"][rid] = {
            "shadow_vp": lt_r["shadow_vp"]["point"],
            "shadow_vp_at_infinity": lt_r["shadow_vp"]["at_infinity"],
            "rays": _lists(own_r, "rays"),
            "checks": _lists(own_r, "checks"),
            "segments": _lists(own_r, "segments"),
        }
    return block


def construction_blocks(lights: list, receiver_lights: dict, shadows: list, default_id: str) -> dict:
    """``B["constructions"]``: ``{<light id>: construction_block(...)}`` in scene order; the caller
    sets ``B["construction"] = B["constructions"][lights[0]["id"]]`` (the same object)."""
    return {lt["id"]: construction_block(lt, receiver_lights, shadows, default_id) for lt in lights}


def construction_doc(block: dict) -> dict:
    """The document form of one construction block (contract §3.1, §5.1.7): the small keys through
    ``canonical``, the lists (``rays``, ``checks``, ``segments``, already canonical) by reference."""
    lists = ("rays", "checks", "segments")
    out = canonical({k: v for k, v in block.items() if k not in lists + ("per_receiver",)})
    out.update({k: list(block[k]) for k in lists})
    per = {}
    for rid, blk in block.get("per_receiver", {}).items():
        b = canonical({k: v for k, v in blk.items() if k not in lists})
        b.update({k: list(blk[k]) for k in lists})
        per[rid] = b
    out["per_receiver"] = per
    return out


# ---------------------------------------------------------------------------
# umbra (contract §5.3.1, §5.3.4)
# ---------------------------------------------------------------------------

def active_lights(receiver: dict, light_ids) -> list:
    """The lights active on a receiver (``receivers[r].lit[k]`` true), scene order: ``umbra[].lights``."""
    lit = receiver.get("lit", {})
    return [lid for lid in light_ids if bool(lit.get(lid, False))]


def umbra_entries(receivers: list, shadows: list, light_ids, canvas_mm, compute: bool = True) -> list:
    """``umbra[]``: one entry ``{receiver, lights, polygons}`` per receiver (scene order) from the
    document ``receivers[]`` entries (``lit``) and the stage-B / document ``shadows[]`` drawables
    (contract §5.3.4, §5.3.5 (c)).  ``polygons`` is :func:`castplane.umbra.umbra_pieces` of the
    active lights' records (``[]`` when fewer than two are active) or ``None`` when ``compute`` is
    false (``project_scene(..., umbra=False)``)."""
    out = []
    for rcv in receivers:
        rid = rcv["id"]
        active = active_lights(rcv, light_ids)
        if compute:
            per_light = [[s["polygons"] for s in shadows if s["receiver"] == rid and s["light"] == lid]
                         for lid in active]
            polygons = _umbra.umbra_pieces(per_light, canvas_mm)
        else:
            polygons = None
        out.append({"receiver": rid, "lights": active, "polygons": polygons})
    return out

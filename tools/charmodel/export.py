"""Writers of a character model: castplane scene JSON (inline mesh data), Wavefront OBJ + MTL, glTF 2.0 GLB.

Character-free: the character package passes its :class:`~charmodel.assembly.Character` (materials, display
colours, sun, name) and its texts (scene settings and description, the OBJ / MTL header lines, the GLB
generator and copyright strings).  Every writer is deterministic (fixed object order, rounded coordinates,
no timestamps): running a generator twice gives byte-identical files.  Geometry comes from an
:class:`~charmodel.assembly.Assembly`: the castplane objects (spatially compact groups of parts) and the
material of every part.

* :func:`scene_text` / :func:`write_scene`: the scene of ``settings`` (``version``, ``units``, ``up``,
  ``lights``, ``receivers``, ``camera``, ``output``; the first light's ``direction`` is replaced by the
  normalised ``character.sun_towards``) with one ``mesh`` object per castplane object and inline ``data``,
  each with ``display_color`` (lower-case ``"#rrggbb"`` of its dominant material,
  :meth:`~charmodel.assembly.Character.display_color`; read only by the web UI's 3D views, ignored by the
  core); the structure is indented, every ``data`` block is compact on one line.  :func:`check_scene` loads
  it with ``castplane.load_scene`` (lazy import).
* :func:`obj_text` / :func:`mtl_text` / :func:`write_obj`: ``mtllib``, one ``o <object>`` per object and a
  ``usemtl <material>`` per part block (castplane's OBJ reader ignores ``usemtl``), ``s`` per smooth group
  (group ids made unique across objects; vertices ordered so that the whole file is also safe as a single
  castplane mesh).  The MTL has every material.
* :func:`glb_bytes` / :func:`write_glb`: one node + mesh per object (named by the object id) with one
  primitive per material (that material's faces, its own compact vertex set), POSITION / NORMAL (smoothed
  within a smooth group, vertices split at group boundaries) / indices; the materials array is the
  character's materials in order.  castplane ``(x, y, z)`` is written as glTF ``(x, z, -y)`` (glTF is Y-up;
  castplane's importer maps back exactly and concatenates a mesh's primitives into one object).
"""

from __future__ import annotations

import json
import math
import os
import struct

import numpy as np

from . import meshkit as mk

__all__ = ["sun_direction", "scene_dict", "scene_text", "write_scene", "check_scene", "srgb_to_linear", "srgb",
           "mtl_text", "obj_text", "write_obj", "glb_bytes", "write_glb"]


def sun_direction(sun_towards) -> list:
    """``sun_towards`` normalised, each component rounded to 12 decimals (no ``-0.0``)."""
    v = np.asarray(sun_towards, dtype=np.float64)
    v = v / math.sqrt(float(np.dot(v, v)))
    return [round(float(x), 12) + 0.0 for x in v]


def scene_dict(character, assembly, settings: dict, description: str) -> dict:
    """The castplane scene as a dict (objects in the fixed order, inline data).  Keys in this order:
    ``description``, ``version``, ``units``, ``up``, ``objects``, ``lights``, ``receivers``, ``camera``,
    ``output`` (the last seven from ``settings``, deep-copied)."""
    s = json.loads(json.dumps(settings))
    s["lights"][0]["direction"] = sun_direction(character.sun_towards)
    out = {"description": description}
    for k in ("version", "units", "up"):
        out[k] = s[k]
    # each object: id, type, display_color (web 3D views only; the core ignores it), data
    out["objects"] = [{"id": o["id"], "type": o["type"], "display_color": character.display_color(o["id"]),
                       "data": o["data"]}
                      for o in assembly.objects()]
    for k in ("lights", "receivers", "camera", "output"):
        out[k] = s[k]
    return out


def scene_text(character, assembly, settings: dict, description: str) -> str:
    """Scene JSON text: indented structure, one compact line per ``data`` block, trailing newline."""
    scene = scene_dict(character, assembly, settings, description)
    blobs = []
    for k, obj in enumerate(scene["objects"]):
        blobs.append(json.dumps(obj["data"], separators=(",", ":"), allow_nan=False))
        obj["data"] = f"@@DATA{k}@@"
    text = json.dumps(scene, indent=1, ensure_ascii=False, allow_nan=False)
    for k, blob in enumerate(blobs):
        text = text.replace(f'"@@DATA{k}@@"', blob, 1)
    return text + "\n"


def write_scene(character, assembly, path, settings: dict, description: str) -> str:
    """:func:`scene_text` written to ``path`` (UTF-8, ``\\n`` line ends); returns the text."""
    text = scene_text(character, assembly, settings, description)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return text


def check_scene(text: str) -> dict:
    """Load the scene text with castplane (``castplane.load_scene``) and confirm that the written
    coordinates still give valid meshes: per object, no two vertices within 1e-5 m and no face with area
    <= 1e-10 m² after the JSON round trip.  Returns the validated castplane scene; raises on failure."""
    import castplane

    raw = json.loads(text)
    for obj in raw["objects"]:
        d = obj["data"]
        m = mk.Mesh(d["vertices"], d["faces"], d["smooth_groups"])
        rep = mk.validate(m, f"scene object {obj['id']}")
        if not rep.ok:
            raise mk.MeshError(rep.summary())
    return castplane.load_scene(raw)


# ---------------------------------------------------------------------------
# OBJ + MTL
# ---------------------------------------------------------------------------

def srgb_to_linear(hex_colour: str):
    """``'#rrggbb'`` -> linear RGB floats (glTF ``baseColorFactor``), rounded to 6 decimals."""
    h = hex_colour.lstrip("#")
    out = []
    for k in range(3):
        c = int(h[2 * k:2 * k + 2], 16) / 255.0
        lin = c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
        out.append(round(lin, 6))
    return out


def srgb(hex_colour: str):
    """``'#rrggbb'`` -> sRGB floats in [0, 1], rounded to 6 decimals (the MTL's ``Kd``)."""
    h = hex_colour.lstrip("#")
    return [round(int(h[2 * k:2 * k + 2], 16) / 255.0, 6) for k in range(3)]


def _fmt(x: float) -> str:
    return repr(float(x) + 0.0)


def mtl_text(character, header) -> str:
    """MTL text: the ``header`` lines (comments, written as given), then every material of
    ``character.materials`` (``Kd`` in sRGB, as most OBJ readers expect)."""
    lines = list(header)
    for name, colour in character.materials.items():
        r, g, b = srgb(colour)
        lines += ["", f"newmtl {name}", f"Kd {r} {g} {b}", "Ka 0 0 0", "Ks 0 0 0", "d 1", "illum 1"]
    return "\n".join(lines) + "\n"


def obj_text(assembly, mtl_name: str, header) -> str:
    """OBJ text: the ``header`` lines (comments, written as given), ``mtllib mtl_name``, the objects in order
    (``o``), a ``usemtl`` per part block, global vertex numbering, ``s`` ids unique across objects.  The
    vertex order is fixed with :func:`meshkit.fix_nesting` over the whole model, so a single-object import
    of the file (``castplane import <name>.obj``) gets no orientation flip either."""
    meshes = list(assembly.meshes.items())
    offset, pieces, spans = 0, [], []
    for oid, m in meshes:
        gmap = {g: g + offset for g in set(m.groups) if g}
        pieces.append(m.with_groups(gmap))
        spans.append((oid, m.n_faces))
        offset += max([0] + list(m.groups))
    whole = mk.fix_nesting(mk.merge(pieces), strict=False)   # best effort: buried shells stay as they are
    lines = list(header) + [f"mtllib {mtl_name}"]
    lines += [f"v {_fmt(x)} {_fmt(y)} {_fmt(z)}" for x, y, z in whole.vertices]
    base = 0
    for oid, n in spans:
        lines.append(f"o {oid}")
        for part, mat, first, count in assembly.part_faces[oid]:
            lines += [f"# part {part}", f"usemtl {mat}"]
            current = None                          # restate the smooth group after each usemtl
            lo = base + first
            for f, g in zip(whole.faces[lo:lo + count], whole.groups[lo:lo + count]):
                if g != current:
                    lines.append(f"s {g}" if g else "s off")
                    current = g
                lines.append("f " + " ".join(str(i + 1) for i in f))
        base += n
    return "\n".join(lines) + "\n"


def write_obj(character, assembly, obj_path, mtl_path, obj_header, mtl_header) -> None:
    """:func:`obj_text` to ``obj_path`` (its ``mtllib`` is the base name of ``mtl_path``) and :func:`mtl_text`
    to ``mtl_path``."""
    with open(obj_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(obj_text(assembly, os.path.basename(mtl_path), obj_header))
    with open(mtl_path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(mtl_text(character, mtl_header))


# ---------------------------------------------------------------------------
# GLB
# ---------------------------------------------------------------------------

def _to_gltf(P):
    """castplane (x, y, z) -> glTF (x, z, -y)."""
    P = np.asarray(P, dtype=np.float64)
    return np.stack([P[:, 0], P[:, 2], -P[:, 1]], axis=1)


def glb_bytes(character, assembly, generator: str, copyright: str) -> bytes:
    """The model as a binary glTF 2.0 file: one node / mesh per object, one primitive per material; the
    ``asset`` carries ``generator`` and ``copyright``, the scene is named ``character.name``."""
    materials_ = character.materials
    blob = bytearray()
    views, accessors, meshes, nodes = [], [], [], []
    mat_index = {name: k for k, name in enumerate(materials_)}

    def add_view(data: bytes, target: int) -> int:
        while len(blob) % 4:
            blob.append(0)
        views.append({"buffer": 0, "byteOffset": len(blob), "byteLength": len(data), "target": target})
        blob.extend(data)
        return len(views) - 1

    def add_accessor(view: int, ctype: int, count: int, kind: str, **extra) -> int:
        accessors.append(dict({"bufferView": view, "componentType": ctype, "count": count, "type": kind}, **extra))
        return len(accessors) - 1

    for k, (oid, m) in enumerate(assembly.meshes.items()):
        pos, nrm, tris, tri_face, _ = mk.split_smooth(m)
        face_mat = np.empty(m.n_faces, dtype=np.int64)
        for mat, faces in assembly.materials(oid):
            face_mat[faces] = mat_index[mat]
        prims = []
        for mat, _faces in assembly.materials(oid):
            sel = tris[face_mat[tri_face] == mat_index[mat]]
            used, local = np.unique(sel.reshape(-1), return_inverse=True)     # sorted: deterministic
            P = _to_gltf(pos[used]).astype("<f4")
            N = _to_gltf(nrm[used]).astype("<f4")
            idx_type, idx_fmt = (5123, "<u2") if P.shape[0] < 65536 else (5125, "<u4")
            I = local.reshape(-1).astype(idx_fmt)
            ap = add_accessor(add_view(P.tobytes(), 34962), 5126, int(P.shape[0]), "VEC3",
                              min=[float(x) for x in P.min(axis=0)], max=[float(x) for x in P.max(axis=0)])
            an = add_accessor(add_view(N.tobytes(), 34962), 5126, int(N.shape[0]), "VEC3")
            ai = add_accessor(add_view(I.tobytes(), 34963), idx_type, int(I.shape[0]), "SCALAR")
            prims.append({"attributes": {"POSITION": ap, "NORMAL": an}, "indices": ai, "material": mat_index[mat],
                          "mode": 4})
        meshes.append({"name": oid, "primitives": prims})
        nodes.append({"name": oid, "mesh": k})
    materials = [{"name": name, "pbrMetallicRoughness": {
        "baseColorFactor": srgb_to_linear(colour) + [1.0], "metallicFactor": 0.0, "roughnessFactor": 0.85},
        "doubleSided": False} for name, colour in materials_.items()]
    while len(blob) % 4:
        blob.append(0)
    doc = {"asset": {"version": "2.0", "generator": generator, "copyright": copyright},
           "scene": 0, "scenes": [{"name": character.name, "nodes": list(range(len(nodes)))}],
           "nodes": nodes, "meshes": meshes, "materials": materials, "accessors": accessors,
           "bufferViews": views, "buffers": [{"byteLength": len(blob)}]}
    js = json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(blob)
    out = struct.pack("<4sII", b"glTF", 2, total)
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(blob), 0x004E4942) + bytes(blob)
    return out


def write_glb(character, assembly, path, generator: str, copyright: str) -> None:
    """:func:`glb_bytes` written to ``path``."""
    with open(path, "wb") as fh:
        fh.write(glb_bytes(character, assembly, generator, copyright))

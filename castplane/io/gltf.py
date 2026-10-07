"""glTF 2.0 / GLB reader and scene importer (contract §5.2.8; Python only, numpy + stdlib).

Reading (:func:`read_gltf`): the GLB container (magic ``glTF``, version 2, a JSON chunk and an
optional BIN chunk) and ``.gltf`` files with ``data:`` URIs (base64) or external buffers relative
to the file.  Accessors honour ``byteStride`` / ``byteOffset``; POSITION must be ``5126`` (float)
``VEC3``, indices ``5121`` / ``5123`` / ``5125``; sparse or normalised accessors, morph targets and
skins are errors.  Primitive modes: 4 as stored, 5 (strip) and 6 (fan) expanded to triangles, 0–3
(points / lines) skipped, others an error.

Numerics (normative, contract §5.2.8): ``matrix`` is column-major; ``rotation`` is the quaternion
``[x, y, z, w]``; ``local = T·R·S``; ``world = parent_world · local``; the depth-first traversal of
``scenes[scene].nodes`` (children in array order) defines "the first node with that name".
Vertices are transformed by the node's world matrix (faces reversed when ``det < 0``) and then
axis-mapped with the exact ``A: (x, y, z) -> (x, -z, y)`` (glTF +Y up -> castplane +Z up).

Errors are :class:`SceneError` whose ``field`` is the glTF JSON path (``nodes[3].scale``,
``accessors[2].sparse``); a node selection that matches nothing has the field ``node``.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
import struct
import urllib.parse

import numpy as np

from ..errors import SceneError

__all__ = ["read_gltf", "load_gltf", "gltf_raw", "node_world_matrices", "traversal_order", "euler_zyx",
           "import_gltf_parts", "import_gltf_scene"]

GLB_MAGIC = b"glTF"
CHUNK_JSON = 0x4E4F534A
CHUNK_BIN = 0x004E4942

#: componentType -> (little-endian numpy dtype, byte size)
COMPONENT_TYPES = {5120: ("<i1", 1), 5121: ("<u1", 1), 5122: ("<i2", 2), 5123: ("<u2", 2),
                   5125: ("<u4", 4), 5126: ("<f4", 4)}
TYPE_SIZES = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT2": 4, "MAT3": 9, "MAT4": 16}
INDEX_TYPES = (5121, 5123, 5125)
#: Required extensions that change the geometry encoding (unsupported); other required extensions
#: (materials, textures) do not affect positions and are ignored.
UNSUPPORTED_EXTENSIONS = ("KHR_draco_mesh_compression", "EXT_meshopt_compression", "KHR_mesh_quantization")

#: The exact axis map of contract §5.2.1 as a matrix (integer entries; applied by component swaps).
AXIS_MAP = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])


# --------------------------------------------------------------------------- container
def _parse_glb(blob: bytes):
    if len(blob) < 20:
        raise SceneError("glb", "truncated GLB header")
    magic, version, length = struct.unpack_from("<4sII", blob, 0)
    if magic != GLB_MAGIC:
        raise SceneError("glb", "not a GLB file (magic must be 'glTF')")
    if version != 2:
        raise SceneError("glb", f"GLB version {version} is not supported (must be 2)")
    if length > len(blob):
        raise SceneError("glb", f"GLB length {length} exceeds the file size {len(blob)}")
    chunks, pos = [], 12
    while pos + 8 <= length:
        clen, ctype = struct.unpack_from("<II", blob, pos)
        data = blob[pos + 8:pos + 8 + clen]
        if len(data) != clen:
            raise SceneError("glb", "truncated GLB chunk")
        chunks.append((ctype, data))
        pos += 8 + clen
    if not chunks or chunks[0][0] != CHUNK_JSON:
        raise SceneError("glb", "the first GLB chunk must be JSON")
    doc = _parse_json(chunks[0][1])
    bin_chunk = chunks[1][1] if len(chunks) > 1 and chunks[1][0] == CHUNK_BIN else None
    return doc, bin_chunk


def _parse_json(raw: bytes) -> dict:
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SceneError("", f"invalid glTF JSON: {exc}") from None
    if not isinstance(doc, dict):
        raise SceneError("", "invalid glTF JSON: the top level must be an object")
    return doc


def _list(doc: dict, key: str) -> list:
    value = doc.get(key, [])
    if not isinstance(value, list):
        raise SceneError(key, "must be a list")
    return value


def _entry(doc: dict, key: str, k, field: str) -> dict:
    items = _list(doc, key)
    if not isinstance(k, int) or isinstance(k, bool) or not 0 <= k < len(items) or not isinstance(items[k], dict):
        raise SceneError(field, f"{key} index {k!r} is out of range")
    return items[k]


def read_gltf(path):
    """Read a ``.gltf`` / ``.glb`` file: ``(json dict, [buffer bytes ...])`` (contract §5.2.8)."""
    with open(path, "rb") as fh:
        blob = fh.read()
    if blob[:4] == GLB_MAGIC:
        doc, bin_chunk = _parse_glb(blob)
    else:
        doc, bin_chunk = _parse_json(blob), None
    version = str(doc.get("asset", {}).get("version", "")) if isinstance(doc.get("asset"), dict) else ""
    if not version.startswith("2"):
        raise SceneError("asset.version", f"glTF version {version!r} is not supported (must be 2.x)")
    for k, ext in enumerate(_list(doc, "extensionsRequired")):
        if ext in UNSUPPORTED_EXTENSIONS:
            raise SceneError(f"extensionsRequired[{k}]", f"unsupported extension {ext}")
    base = os.path.dirname(os.path.abspath(path))
    buffers = []
    for k, buf in enumerate(_list(doc, "buffers")):
        field = f"buffers[{k}]"
        if not isinstance(buf, dict):
            raise SceneError(field, "must be an object")
        uri = buf.get("uri")
        if uri is None:
            if k != 0 or bin_chunk is None:
                raise SceneError(f"{field}.uri", "required (only the first buffer of a GLB may use the BIN chunk)")
            data = bin_chunk
        elif not isinstance(uri, str):
            raise SceneError(f"{field}.uri", "must be a string")
        elif uri.startswith("data:"):
            head, sep, payload = uri.partition(",")
            if not sep or not head.endswith(";base64"):
                raise SceneError(f"{field}.uri", "only base64 data URIs are supported")
            try:
                data = base64.b64decode(payload, validate=True)
            except (binascii.Error, ValueError):
                raise SceneError(f"{field}.uri", "invalid base64 data") from None
        else:
            with open(os.path.join(base, urllib.parse.unquote(uri)), "rb") as fh:
                data = fh.read()
        length = buf.get("byteLength")
        if not isinstance(length, int) or isinstance(length, bool) or length < 0 or length > len(data):
            raise SceneError(f"{field}.byteLength", f"{length!r} does not fit the {len(data)} bytes of the buffer")
        buffers.append(data)
    return doc, buffers


def read_accessor(doc: dict, buffers: list, k: int) -> np.ndarray:
    """Accessor ``k`` as a ``(count, components)`` array of its own component type (strided reads,
    ``byteOffset``; an accessor without ``bufferView`` is all zeros, glTF §3.6.2.1)."""
    field = f"accessors[{k}]"
    acc = _entry(doc, "accessors", k, field)
    if "sparse" in acc:
        raise SceneError(f"{field}.sparse", "sparse accessors are not supported")
    if acc.get("normalized", False):
        raise SceneError(f"{field}.normalized", "normalised accessors are not supported")
    ct = acc.get("componentType")
    if ct not in COMPONENT_TYPES:
        raise SceneError(f"{field}.componentType", f"unknown component type {ct!r}")
    typ = acc.get("type")
    if typ not in TYPE_SIZES:
        raise SceneError(f"{field}.type", f"unknown accessor type {typ!r}")
    count = acc.get("count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        raise SceneError(f"{field}.count", "must be a non-negative integer")
    dtype, size = COMPONENT_TYPES[ct]
    ncomp = TYPE_SIZES[typ]
    if "bufferView" not in acc:
        return np.zeros((count, ncomp), dtype=dtype)
    bv = _entry(doc, "bufferViews", acc["bufferView"], f"{field}.bufferView")
    vfield = f"bufferViews[{acc['bufferView']}]"
    if not isinstance(bv.get("buffer"), int) or not 0 <= bv["buffer"] < len(buffers):
        raise SceneError(f"{vfield}.buffer", "buffer index out of range")
    buf = buffers[bv["buffer"]]
    view_offset = bv.get("byteOffset", 0)
    view_length = bv.get("byteLength")
    if not isinstance(view_length, int) or view_offset + view_length > len(buf):
        raise SceneError(f"{vfield}.byteLength", "the buffer view exceeds its buffer")
    elem = ncomp * size
    stride = bv.get("byteStride") or elem
    if stride < elem:
        raise SceneError(f"{vfield}.byteStride", f"{stride} is smaller than the element size {elem}")
    offset = acc.get("byteOffset", 0)
    if count and offset + stride * (count - 1) + elem > view_length:
        raise SceneError(f"{field}.count", "the accessor exceeds its buffer view")
    if count == 0:
        return np.zeros((0, ncomp), dtype=dtype)
    arr = np.ndarray((count, ncomp), dtype=np.dtype(dtype), buffer=buf, offset=view_offset + offset,
                     strides=(stride, size))
    return arr.copy()


# --------------------------------------------------------------------------- nodes
def _local_matrix(node: dict, k: int) -> np.ndarray:
    field = f"nodes[{k}]"
    if "matrix" in node:
        m = node["matrix"]
        if not isinstance(m, list) or len(m) != 16:
            raise SceneError(f"{field}.matrix", "must be 16 numbers")
        return np.array(m, dtype=np.float64).reshape(4, 4).T          # column-major
    t = np.array(node.get("translation", [0.0, 0.0, 0.0]), dtype=np.float64)
    x, y, z, w = (float(v) for v in node.get("rotation", [0.0, 0.0, 0.0, 1.0]))
    s = np.array(node.get("scale", [1.0, 1.0, 1.0]), dtype=np.float64)
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * s[None, :]                                       # R · S
    M[:3, 3] = t                                                     # T · (R · S)
    return M


def _children(doc: dict) -> dict:
    nodes = _list(doc, "nodes")
    parent = {}
    for k, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise SceneError(f"nodes[{k}]", "must be an object")
        for c in node.get("children", []):
            if not isinstance(c, int) or isinstance(c, bool) or not 0 <= c < len(nodes):
                raise SceneError(f"nodes[{k}].children", f"node index {c!r} is out of range")
            if c in parent:
                raise SceneError(f"nodes[{k}].children", f"node {c} has two parents")
            parent[c] = k
    return parent


def node_world_matrices(doc: dict) -> list:
    """World matrix of every node (``world = parent_world · local``), independent of the scene."""
    nodes = _list(doc, "nodes")
    parent = _children(doc)
    world = [None] * len(nodes)

    def resolve(k, chain=()):
        if world[k] is None:
            if k in chain:
                raise SceneError(f"nodes[{k}].children", "the node hierarchy has a cycle")
            local = _local_matrix(nodes[k], k)
            world[k] = local if k not in parent else resolve(parent[k], chain + (k,)) @ local
        return world[k]

    for k in range(len(nodes)):
        resolve(k)
    return world


def _roots(doc: dict) -> list:
    scenes = doc.get("scenes")
    if scenes:
        s = doc.get("scene", 0)
        scene = _entry(doc, "scenes", s, "scene")
        roots = scene.get("nodes", [])
        n = len(_list(doc, "nodes"))
        for r in roots:
            if not isinstance(r, int) or isinstance(r, bool) or not 0 <= r < n:
                raise SceneError(f"scenes[{s}].nodes", f"node index {r!r} is out of range")
        return list(roots)
    parent = _children(doc)
    return [k for k in range(len(_list(doc, "nodes"))) if k not in parent]


def _subtree(doc: dict, k: int, seen=None) -> list:
    """Node ``k`` and its descendants in depth-first order (children in array order)."""
    nodes = _list(doc, "nodes")
    out, stack, seen = [], [k], set() if seen is None else seen
    while stack:
        j = stack.pop()
        if j in seen:
            raise SceneError(f"nodes[{j}]", "the node hierarchy has a cycle or a shared node")
        seen.add(j)
        out.append(j)
        stack.extend(reversed(nodes[j].get("children", [])))
    return out


def traversal_order(doc: dict) -> list:
    """Node indices of the default scene in depth-first order (contract §5.2.8): the roots of
    ``scenes[scene]`` (default 0; every root node in index order when ``scenes`` is absent),
    children in array order."""
    _children(doc)
    out, seen = [], set()
    for r in _roots(doc):
        out.extend(_subtree(doc, r, seen))
    return out


def _primitive_node(node: dict) -> dict | None:
    extras = node.get("extras")
    if isinstance(extras, dict) and isinstance(extras.get("castplane"), dict):
        return extras["castplane"]
    return None


# --------------------------------------------------------------------------- geometry
def _primitive_triangles(doc: dict, buffers: list, m: int, p: int, prim: dict):
    """``(vertices (n, 3) float64, triangles (t, 3) int)`` of one primitive, or ``None`` for points /
    lines."""
    field = f"meshes[{m}].primitives[{p}]"
    if not isinstance(prim, dict):
        raise SceneError(field, "must be an object")
    if prim.get("targets"):
        raise SceneError(f"{field}.targets", "morph targets are not supported")
    mode = prim.get("mode", 4)
    if mode in (0, 1, 2, 3):
        return None
    if mode not in (4, 5, 6):
        raise SceneError(f"{field}.mode", f"unknown primitive mode {mode!r}")
    attrs = prim.get("attributes")
    if not isinstance(attrs, dict) or "POSITION" not in attrs:
        raise SceneError(f"{field}.attributes.POSITION", "required")
    k = attrs["POSITION"]
    acc = _entry(doc, "accessors", k, f"{field}.attributes.POSITION")
    if acc.get("componentType") != 5126 or acc.get("type") != "VEC3":
        raise SceneError(f"accessors[{k}].componentType", "POSITION must be a float VEC3 accessor (5126)")
    V = read_accessor(doc, buffers, k).astype(np.float64)
    if not np.all(np.isfinite(V)):
        raise SceneError(f"accessors[{k}]", "POSITION values must be finite")
    n = len(V)
    if "indices" in prim:
        ki = prim["indices"]
        iacc = _entry(doc, "accessors", ki, f"{field}.indices")
        if iacc.get("componentType") not in INDEX_TYPES or iacc.get("type") != "SCALAR":
            raise SceneError(f"accessors[{ki}].componentType", "indices must be unsigned SCALAR 5121 / 5123 / 5125")
        idx = read_accessor(doc, buffers, ki).reshape(-1).astype(np.int64)
        if idx.size and int(idx.max()) >= n:
            raise SceneError(f"accessors[{ki}]", f"index {int(idx.max())} is out of range ({n} vertices)")
    else:
        idx = np.arange(n, dtype=np.int64)
    if mode == 4:
        if idx.size % 3:
            raise SceneError(f"{field}", f"{idx.size} indices are not a multiple of 3")
        tris = idx.reshape(-1, 3)
    elif mode == 5:                                                   # strip, glTF §3.7.2.1
        i = np.arange(max(idx.size - 2, 0))
        odd = (i % 2).astype(bool)
        tris = np.stack([idx[i], np.where(odd, idx[i + 2], idx[i + 1]), np.where(odd, idx[i + 1], idx[i + 2])],
                        axis=1) if i.size else np.zeros((0, 3), dtype=np.int64)
    else:                                                             # fan
        i = np.arange(1, max(idx.size - 1, 1))
        tris = np.stack([np.full(i.size, idx[0] if idx.size else 0), idx[i], idx[i + 1]], axis=1) \
            if i.size else np.zeros((0, 3), dtype=np.int64)
    return V, tris


def _node_geometry(doc, buffers, k: int, world: np.ndarray, verts: list, faces: list) -> None:
    node = _list(doc, "nodes")[k]
    if "mesh" not in node or _primitive_node(node) is not None:
        return
    if "skin" in node:
        raise SceneError(f"nodes[{k}].skin", "skins are not supported")
    m = node["mesh"]
    mesh = _entry(doc, "meshes", m, f"nodes[{k}].mesh")
    L, t = world[:3, :3], world[:3, 3]
    flip = float(np.linalg.det(L)) < 0.0
    for p, prim in enumerate(mesh.get("primitives", [])):
        got = _primitive_triangles(doc, buffers, m, p, prim)
        if got is None:
            continue
        V, tris = got
        W = V @ L.T + t[None, :]
        offset = sum(len(v) for v in verts)
        verts.append(W)
        tri = tris[:, ::-1] if flip else tris
        faces.extend((tri + offset).tolist())


def _axis_map(W: np.ndarray) -> list:
    """Exact ``(x, y, z) -> (x, -z, y)`` of contract §5.2.1, canonical floats."""
    out = np.empty_like(W)
    out[:, 0] = W[:, 0]
    out[:, 1] = -W[:, 2]
    out[:, 2] = W[:, 1]
    return (out + 0.0).tolist()


def _select_nodes(doc: dict, node, order: list) -> list:
    nodes = _list(doc, "nodes")
    if node is None:
        return order
    if isinstance(node, int):
        if not 0 <= node < len(nodes):
            raise SceneError("node", f"the file has {len(nodes)} node(s); index {node} is out of range")
        return _subtree(doc, node)
    for k in order:
        if nodes[k].get("name") == node:
            return _subtree(doc, k)
    meshes = _list(doc, "meshes")
    for k in order:
        m = nodes[k].get("mesh")
        if isinstance(m, int) and 0 <= m < len(meshes) and isinstance(meshes[m], dict) \
                and meshes[m].get("name") == node:
            return [k]
    raise SceneError("node", f"no node or mesh named {node!r}")


def gltf_raw(doc: dict, buffers: list, node=None) -> dict:
    """The raw Z-up mesh ``{vertices, faces, smooth_groups}`` of a read glTF file: every mesh node of
    the default scene (``node is None``), or the subtree of the selected node (contract §5.2.1
    ``node`` row).  Meshes on nodes carrying ``extras.castplane`` primitives are ignored."""
    order = traversal_order(doc)
    world = node_world_matrices(doc)
    verts, faces = [], []
    for k in _select_nodes(doc, node, order):
        _node_geometry(doc, buffers, k, world[k], verts, faces)
    if not faces:
        raise SceneError("node" if node is not None else "meshes",
                         "no triangle in the selected node(s)" if node is not None else "the file holds no triangle")
    W = np.concatenate(verts, axis=0)
    return {"vertices": _axis_map(W), "faces": faces, "smooth_groups": [0] * len(faces)}


def load_gltf(path, node=None, parsed=None) -> dict:
    """:func:`gltf_raw` of a file; ``parsed`` (a :func:`read_gltf` result) skips the read."""
    doc, buffers = read_gltf(path) if parsed is None else parsed
    return gltf_raw(doc, buffers, node)


# --------------------------------------------------------------------------- scene import
def euler_zyx(R) -> list:
    """``[rx, ry, rz]`` in radians with ``R = Rz·Ry·Rx`` (contract §5.2.8)."""
    R = np.asarray(R, dtype=np.float64)
    h = math.hypot(R[0, 0], R[1, 0])
    ry = math.atan2(-R[2, 0], h)
    if h <= 1e-12:
        return [0.0, ry, math.atan2(-R[0, 1], R[1, 1])]
    return [math.atan2(R[2, 1], R[2, 2]), ry, math.atan2(R[1, 0], R[0, 0])]


def _vec(v) -> list:
    return [float(x) + 0.0 for x in v]


def _unit(v):
    v = np.asarray(v, dtype=np.float64)
    return v / np.linalg.norm(v)


def _rotation_part(world: np.ndarray):
    """``(R, s)``: the normalised rotation columns and the uniform scale of a world matrix (a
    scale within 1e-12 of 1 is taken as exactly 1 so that unscaled nodes keep their numbers)."""
    L = world[:3, :3]
    norms = np.linalg.norm(L, axis=0)
    s = float(norms.mean())
    if abs(s - 1.0) <= 1e-12:
        s = 1.0
    return L / norms[None, :], norms, s


def _node_id(name, k: int, prefix: str) -> str:
    if isinstance(name, str) and name:
        return name.replace(".", "_")
    return f"{prefix}{k}"


def _unique(base: str, taken: set) -> str:
    out, n = base, 2
    while out in taken:
        out, n = f"{base}_{n}", n + 1
    taken.add(out)
    return out


def _camera_block(doc: dict, k: int, world: np.ndarray):
    node = _list(doc, "nodes")[k]
    c = node["camera"]
    cam = _entry(doc, "cameras", c, f"nodes[{k}].camera")
    if cam.get("type") != "perspective":
        raise SceneError(f"cameras[{c}].type", f"{cam.get('type')!r} cameras are not supported (perspective only)")
    persp = cam.get("perspective")
    if not isinstance(persp, dict) or "yfov" not in persp:
        raise SceneError(f"cameras[{c}].perspective.yfov", "required")
    yfov = float(persp["yfov"])
    if not 0.0 < yfov < math.pi:
        raise SceneError(f"cameras[{c}].perspective.yfov", "must be in (0, pi)")
    a = float(persp.get("aspectRatio", 1.5))
    if not a > 0.0:
        raise SceneError(f"cameras[{c}].perspective.aspectRatio", "must be > 0")
    znear = float(persp.get("znear", 0.05))
    R, _, _ = _rotation_part(world)
    position = AXIS_MAP @ world[:3, 3]
    forward = AXIS_MAP @ (R @ np.array([0.0, 0.0, -1.0]))
    up = AXIS_MAP @ (R @ np.array([0.0, 1.0, 0.0]))
    target = position + forward
    f = _unit(target - position)
    up_world = np.array([0.0, 0.0, 1.0])
    if np.linalg.norm(np.cross(f, up_world)) <= 1e-9:
        up_world = np.array([0.0, 1.0, 0.0])
    right0 = _unit(np.cross(f, up_world))
    up0 = np.cross(right0, f)
    roll = math.degrees(math.atan2(-float(up @ right0), float(up @ up0)))
    block = {"position": _vec(position), "target": _vec(target), "roll_deg": roll + 0.0,
             "focal_length_mm": 12.0 / math.tan(yfov / 2.0) + 0.0, "frame_mm": [24.0 * a + 0.0, 24.0],
             "near_m": znear + 0.0}
    return block, [240.0 * a + 0.0, 240.0]


def _light_block(doc: dict, k: int, world: np.ndarray):
    node = _list(doc, "nodes")[k]
    li = node["extensions"]["KHR_lights_punctual"]["light"]
    lights = doc.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])
    if not isinstance(li, int) or not 0 <= li < len(lights):
        raise SceneError(f"nodes[{k}].extensions.KHR_lights_punctual.light", f"light index {li!r} is out of range")
    typ = lights[li].get("type")
    if typ in ("point", "spot"):
        return {"type": "point", "position": _vec(AXIS_MAP @ world[:3, 3])}, typ == "spot"
    if typ == "directional":
        R, _, _ = _rotation_part(world)
        d = _unit(AXIS_MAP @ (R @ np.array([0.0, 0.0, 1.0])))
        return {"type": "directional", "direction": _vec(d)}, False
    raise SceneError(f"extensions.KHR_lights_punctual.lights[{li}].type", f"unknown light type {typ!r}")


def _has_light(node: dict) -> bool:
    ext = node.get("extensions")
    return isinstance(ext, dict) and isinstance(ext.get("KHR_lights_punctual"), dict) \
        and "light" in ext["KHR_lights_punctual"]


def _primitive_object(doc: dict, k: int, world: np.ndarray, params: dict) -> dict:
    node = _list(doc, "nodes")[k]
    typ = params.get("type")
    if typ not in ("box", "cylinder", "sphere", "cone", "prism"):
        raise SceneError(f"nodes[{k}].extras.castplane.type", "must be one of box, cylinder, sphere, cone, prism")
    field = f"nodes[{k}].matrix" if "matrix" in node else f"nodes[{k}].scale"
    L = world[:3, :3]
    if float(np.linalg.det(L)) <= 0.0:
        raise SceneError(field, "mirrored node cannot carry a primitive")
    R, norms, s = _rotation_part(world)
    if not (norms.max() - norms.min() <= 1e-9 * norms.max()):
        raise SceneError(f"nodes[{k}].scale", f"non-uniform node scale {norms.tolist()} cannot carry a primitive")
    obj = {key: value for key, value in params.items() if key not in ("id", "transform")}
    if s != 1.0:
        for key in ("radius", "height"):
            if isinstance(obj.get(key), (int, float)) and not isinstance(obj.get(key), bool):
                obj[key] = obj[key] * s + 0.0
        if isinstance(obj.get("size"), list):
            obj["size"] = [v * s + 0.0 for v in obj["size"]]
        if isinstance(obj.get("polygon"), list):
            obj["polygon"] = [[c * s + 0.0 for c in p] for p in obj["polygon"]]
    Rc = AXIS_MAP @ R @ AXIS_MAP.T
    obj["transform"] = {"position": _vec(AXIS_MAP @ world[:3, 3]),
                        "rotation_deg": [math.degrees(a) + 0.0 for a in euler_zyx(Rc)]}
    return obj


def import_gltf_parts(path, *, ref=None, inline=False, node=None, camera=None, light=None, mesh_keys=None,
                      parsed=None):
    """The importable pieces of a glTF file (contract §5.2.8 mapping tables): ``{"objects",
    "lights", "camera", "canvas_mm", "raw"}`` and the notes.  ``ref`` is the path string written into
    mesh objects (default: ``path``); ``inline`` embeds ``data`` instead; ``node`` restricts the
    import to one mesh object for that selection; ``camera`` / ``light`` pick a camera / light by
    node name; ``mesh_keys`` (``scale`` / ``weld_tolerance`` / ``smooth_angle_deg`` / ...) are
    added to every mesh object.  ``lights`` / ``camera`` are ``None`` when the file has none;
    ``raw`` maps each mesh object id to its loaded raw data (for the bounding box)."""
    from . import _note

    doc, buffers = read_gltf(path) if parsed is None else parsed
    nodes = _list(doc, "nodes")
    order = traversal_order(doc)
    world = node_world_matrices(doc)
    ref = str(path) if ref is None else ref
    keys = dict(mesh_keys or {})
    objects, raw, notes = [], {}, []
    taken = {"ground"}
    n_lights = 1 if light is not None else sum(1 for k in order if _has_light(nodes[k]))

    def object_base(name, k):
        """Object id of a node: ``hidden`` (and, with >= 2 lights, ``core``) are reserved (§5.0.1)."""
        base = _node_id(name, k, "node")
        return base + "_object" if base == "hidden" or (base == "core" and n_lights >= 2) else base

    def mesh_object(oid, selection):
        data = gltf_raw(doc, buffers, selection)
        obj = {"id": oid, "type": "mesh"}
        if inline:
            obj["data"] = data
        else:
            obj["path"] = ref
            obj["node"] = selection
        obj.update(keys)
        raw[oid] = data
        return obj

    if node is not None:
        sel = _select_nodes(doc, node, order)
        name = nodes[sel[0]].get("name") if isinstance(node, int) or nodes[sel[0]].get("name") == node else node
        oid = _unique(object_base(name, sel[0]), taken)
        objects.append(mesh_object(oid, node))
    else:
        names = [n.get("name") for n in nodes]
        emitted = set()
        for k in order:
            n = nodes[k]
            params = _primitive_node(n)
            if params is not None:
                obj = _primitive_object(doc, k, world[k], params)
                obj = {"id": _unique(object_base(n.get("name"), k), taken), **obj}
                objects.append(obj)
                continue
            if "mesh" not in n or any(j in emitted for j in _ancestors(doc, k)):
                continue
            name = n.get("name")
            unique = isinstance(name, str) and name != "" and names.count(name) == 1
            selection = name if unique else k
            try:
                obj = mesh_object(_unique(object_base(name, k), set(taken)), selection)
            except SceneError as exc:
                if exc.field == "node":       # a mesh node with points / lines only
                    continue
                raise
            taken.add(obj["id"])
            objects.append(obj)
            emitted.add(k)

    cam_nodes = [k for k in order if "camera" in nodes[k]]
    cam_block = canvas = None
    if cam_nodes:
        if camera is not None:
            chosen = [k for k in cam_nodes if nodes[k].get("name") == camera]
            if not chosen:
                raise SceneError("--camera", f"no camera node named {camera!r}")
            pick = chosen[0]
        else:
            pick = cam_nodes[0]
        cam_block, canvas = _camera_block(doc, pick, world[pick])
        dropped = [_node_id(nodes[k].get("name"), k, "node") for k in cam_nodes if k != pick]
        if dropped:
            notes.append(_note("IMPORT_CAMERA_DROPPED", dropped,
                               f"{len(dropped)} more camera(s) dropped; the scene uses "
                               f"{_node_id(nodes[pick].get('name'), pick, 'node')!r}"))
    elif camera is not None:
        raise SceneError("--camera", "the file holds no camera")

    light_nodes = [k for k in order if _has_light(nodes[k])]
    if light is not None:
        light_nodes = [k for k in light_nodes if light in (nodes[k].get("name"), _node_id(nodes[k].get("name"), k, "light"))]
        if not light_nodes:
            raise SceneError("--light", f"no light node named {light!r}")
        light_nodes = light_nodes[:1]
    lights = None
    if light_nodes:
        lights, taken_l = [], {"ground"}
        multi = len(light_nodes) >= 2
        for k in light_nodes:
            block, spot = _light_block(doc, k, world[k])
            base = _node_id(nodes[k].get("name"), k, "light")
            if base == "hidden" or (multi and base in ("umbra", "core")):
                base += "_light"
            lid = _unique(base, taken_l)
            lights.append({"id": lid, **block})
            if spot:
                notes.append(_note("IMPORT_SPOT_AS_POINT", [lid], "spot light imported as a point light at its position"))
    return {"objects": objects, "lights": lights, "camera": cam_block, "canvas_mm": canvas, "raw": raw}, notes


def _ancestors(doc: dict, k: int) -> list:
    parent = _children(doc)
    out = []
    while k in parent:
        k = parent[k]
        out.append(k)
    return out


def import_gltf_scene(path, *, ref=None, inline=False, node=None, camera=None, light=None, mesh_keys=None):
    """A complete raw scene (spec §4) imported from a glTF / GLB file with the defaults of contract
    §5.2.8 (bounding-box camera / directional light with their notes when the file has none; the
    ground receiver always): ``(scene, notes)``."""
    from . import _assemble_scene

    parts, notes = import_gltf_parts(path, ref=ref, inline=inline, node=node, camera=camera, light=light,
                                     mesh_keys=mesh_keys)
    return _assemble_scene(parts, notes)

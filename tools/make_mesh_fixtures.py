#!/usr/bin/env python3
"""Write the M5 loader fixtures under ``tests/fixtures/meshes/`` and the example mesh
``examples/meshes/house.obj`` (contract §5.2.11; committed output, byte-deterministic).

    python tools/make_mesh_fixtures.py            # (re)write every fixture
    python tools/make_mesh_fixtures.py --check    # exit 1 if a committed fixture differs

Every glTF geometry is written in glTF axes (+Y up), i.e. the castplane (Z-up) coordinates mapped
with ``A^T: (x, y, z) -> (x, z, -y)``, so that the loader's exact axis map gives the castplane numbers
back.  All coordinates are exactly representable in float32.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
import pathlib
import struct
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "meshes"
EXAMPLES = ROOT / "examples" / "meshes"

#: contract §5.2.12: the unit box, then the same eight vertices twice; 12 triangles on the duplicates
CUBE_V = [[-.5, -.5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0], [-.5, .5, 0.0],
          [-.5, -.5, 1.0], [.5, -.5, 1.0], [.5, .5, 1.0], [-.5, .5, 1.0]]
SPLIT_V = CUBE_V * 3
SPLIT_F = [[8, 11, 10], [8, 10, 9], [12, 13, 14], [12, 14, 15], [16, 17, 21], [16, 21, 20],
           [17, 18, 22], [17, 22, 21], [18, 19, 23], [18, 23, 22], [19, 16, 20], [19, 20, 23]]
#: the 12 triangles of the unit box on the eight shared vertices (outward)
BOX_TRIS = [[f[0] - 8 * (f[0] // 8), f[1] - 8 * (f[1] // 8), f[2] - 8 * (f[2] // 8)] for f in SPLIT_F]

#: the import fixture (contract §5.2.11): camera yfov / aspect
YFOV = 0.6
ASPECT = 1.5


def to_gltf_axes(v):
    """``A^T``: castplane (x, y, z) -> glTF (x, z, -y), canonical floats."""
    return [float(v[0]) + 0.0, float(v[2]) + 0.0, -float(v[1]) + 0.0]


def fmt(x: float) -> str:
    x = float(x) + 0.0
    return repr(int(x)) if x == int(x) else repr(x)


def outward(vertices, faces):
    """Faces re-wound so that every Newell normal points away from the centroid of the vertices."""
    V = np.asarray(vertices, dtype=np.float64)
    c = V.mean(axis=0)
    out = []
    for f in faces:
        P = V[f]
        n = np.cross(P[1] - P[0], P[2] - P[0])
        out.append(list(f) if np.dot(n, P.mean(axis=0) - c) > 0 else list(f)[::-1])
    return out


def wedge():
    """A triangular prism (castplane axes, base on z = 0) with outward triangles."""
    tri = [[-0.375, -0.25, 0.0], [0.375, -0.25, 0.0], [0.0, 0.5, 0.0]]
    V = tri + [[x, y, 0.625] for x, y, _ in tri]
    F = [[0, 2, 1], [3, 4, 5], [0, 1, 4], [0, 4, 3], [1, 2, 5], [1, 5, 4], [2, 0, 3], [2, 3, 5]]
    return V, outward(V, F)


# --------------------------------------------------------------------------- OBJ / STL / PLY
def write_obj_box(up: str) -> str:
    axes = 'Y-up, load with up: "y"' if up == "y" else "Z-up"
    lines = ["# castplane M5 fixture: the split-vertex unit box of contract §5.2.12 "
             f"({axes})", "o cube", "s off"]
    for v in SPLIT_V:
        p = to_gltf_axes(v) if up == "y" else v
        lines.append("v " + " ".join(fmt(c) for c in p))
    for f in SPLIT_F:
        lines.append("f " + " ".join(str(k + 1) for k in f))
    return "\n".join(lines) + "\n"


FEATURES_OBJ = """\
# castplane M5 fixture: OBJ features (contract §5.2.8)
mtllib features.mtl
o crate
v -0.5 -0.5 0 1.0
v 0.5 -0.5 0
v 0.5 0.5 0
v -0.5 0.5 0
v -0.5 -0.5 1
v 0.5 -0.5 1
v 0.5 0.5 1
v -0.5 0.5 1
vt 0 0
vt 1 0
vt 1 1
vn 0 0 1
g bottom
usemtl wood
s off
f 1 4 3 2
g top
s 1
f 5/1 6/2 7/3 8/1
g sides walls
s 2
f -8//1 -7//1 -3//1 -4//1
f 2/1/1 3/2/1 7/3/1 6/1/1
f 3 4 \\
  8 7
f 4 1 5 8 # a comment after a face
l 1 2
p 3
o marker
v 2 0 0
v 3 0 0
v 2.5 1 0
v 2.5 0.5 1
g tetra
s off
f -4 -2 -3
f -4 -1 -2
f -3 -2 -1
f -4 -3 -1
"""


def write_stl() -> str:
    V = np.asarray(CUBE_V)
    lines = ["solid box"]
    for f in BOX_TRIS:
        P = V[f]
        n = np.cross(P[1] - P[0], P[2] - P[0])
        n = n / np.linalg.norm(n)
        lines.append("  facet normal " + " ".join(fmt(c) for c in n))
        lines.append("    outer loop")
        for p in P:
            lines.append("      vertex " + " ".join(fmt(c) for c in p))
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid box")
    return "\n".join(lines) + "\n"


def write_ply() -> str:
    lines = ["ply", "format ascii 1.0", "comment castplane M5 fixture: the unit box", f"element vertex {len(CUBE_V)}",
             "property float x", "property float y", "property float z", f"element face {len(BOX_TRIS)}",
             "property list uchar int vertex_indices", "end_header"]
    lines += [" ".join(fmt(c) for c in v) for v in CUBE_V]
    lines += ["3 " + " ".join(str(k) for k in f) for f in BOX_TRIS]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- glTF
class Gltf:
    """A tiny glTF 2.0 writer: one buffer, aligned buffer views, accessors."""

    def __init__(self):
        self.blob = bytearray()
        self.views, self.accessors = [], []

    def _view(self, data: bytes, stride=None, prefix: int = 0) -> int:
        while len(self.blob) % 4:
            self.blob.append(0)
        self.blob.extend(b"\0" * prefix)
        view = {"buffer": 0, "byteOffset": len(self.blob), "byteLength": len(data)}
        if stride:
            view["byteStride"] = stride
        self.blob.extend(data)
        self.views.append(view)
        return len(self.views) - 1

    def positions(self, V, interleave_normals: bool = False, prefix: int = 0) -> int:
        P = np.asarray(V, dtype="<f4").reshape(-1, 3)
        if interleave_normals:
            data = np.concatenate([P, np.tile(np.array([[0.0, 1.0, 0.0]], dtype="<f4"), (len(P), 1))], axis=1)
            view = self._view(data.tobytes(), stride=24, prefix=prefix)
        else:
            view = self._view(P.tobytes(), prefix=prefix)
        self.accessors.append({"bufferView": view, "componentType": 5126, "count": len(P), "type": "VEC3",
                               "min": [float(x) for x in P.min(axis=0)], "max": [float(x) for x in P.max(axis=0)]})
        acc = len(self.accessors) - 1
        if interleave_normals:
            self.accessors.append({"bufferView": view, "byteOffset": 12, "componentType": 5126, "count": len(P),
                                   "type": "VEC3"})
        return acc

    def indices(self, I, ctype: int = 5123) -> int:
        dtype = {5121: "<u1", 5123: "<u2", 5125: "<u4"}[ctype]
        data = np.asarray(I, dtype=dtype).reshape(-1).tobytes()
        view = self._view(data)
        self.accessors.append({"bufferView": view, "componentType": ctype, "count": len(data) // np.dtype(dtype).itemsize,
                               "type": "SCALAR"})
        return len(self.accessors) - 1

    def document(self, nodes, meshes, extra=None, uri=None) -> dict:
        while len(self.blob) % 4:
            self.blob.append(0)
        buf = {"byteLength": len(self.blob)}
        if uri == "data":
            buf["uri"] = "data:application/octet-stream;base64," + base64.b64encode(bytes(self.blob)).decode("ascii")
        elif uri is not None:
            buf["uri"] = uri
        doc = {"asset": {"version": "2.0", "generator": "castplane tools/make_mesh_fixtures.py"},
               "buffers": [buf], "bufferViews": self.views, "accessors": self.accessors,
               "meshes": meshes, "nodes": nodes, "scene": 0, "scenes": [{"nodes": [k for k in range(len(nodes))
                                                                                   if not any(k in n.get("children", []) for n in nodes)]}]}
        doc.update(extra or {})
        return doc


def dump_json(doc) -> bytes:
    return (json.dumps(doc, indent=1, sort_keys=True) + "\n").encode("utf-8")


def glb(doc: dict, blob: bytes) -> bytes:
    js = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    blob = bytes(blob) + b"\0" * (-len(blob) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(blob), 0x004E4942) + blob
    return struct.pack("<4sII", b"glTF", 2, 12 + len(body)) + body


def box_gltf(uri):
    g = Gltf()
    pos = g.positions([to_gltf_axes(v) for v in SPLIT_V])
    idx = g.indices(SPLIT_F)
    doc = g.document([{"name": "Box", "mesh": 0}],
                     [{"name": "box", "primitives": [{"attributes": {"POSITION": pos}, "indices": idx, "mode": 4}]}],
                     uri=uri)
    return doc, bytes(g.blob)


def primitives_gltf():
    """Strided accessors, every index type, non-indexed, strip, fan and a skipped line primitive."""
    g = Gltf()
    quad = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [1.0, 0.0, -1.0]]   # glTF axes, y = 0
    strided = g.positions(quad, interleave_normals=True, prefix=8)
    idx32 = g.indices([0, 1, 3, 0, 3, 2], 5125)
    idx8 = g.indices([0, 1, 3, 0, 3, 2], 5121)
    plain = g.positions(quad)
    soup = g.positions([quad[0], quad[1], quad[3], quad[0], quad[3], quad[2]])
    strip = g.positions([quad[0], quad[2], quad[1], quad[3]])
    fan = g.positions([[0.5, 0.0, -0.5], [0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [1.0, 0.0, -1.0], [0.0, 0.0, -1.0],
                       [0.0, 0.0, 0.0]])
    lines = g.indices([0, 1, 1, 3], 5123)
    meshes = [
        {"name": "strided", "primitives": [{"attributes": {"POSITION": strided, "NORMAL": strided + 1}, "indices": idx32}]},
        {"name": "u8", "primitives": [{"attributes": {"POSITION": plain}, "indices": idx8, "mode": 4}]},
        {"name": "soup", "primitives": [{"attributes": {"POSITION": soup}}]},
        {"name": "strip", "primitives": [{"attributes": {"POSITION": strip}, "mode": 5}]},
        {"name": "fan", "primitives": [{"attributes": {"POSITION": fan}, "mode": 6},
                                       {"attributes": {"POSITION": plain}, "indices": lines, "mode": 1}]},
    ]
    nodes = [{"name": m["name"].capitalize(), "mesh": k, "translation": [0.0, 0.0, -2.0 * k]} for k, m in enumerate(meshes)]
    return g.document(nodes, meshes, uri="data")


def mirrored_gltf():
    """Nested TRS: a root rotated 90 degrees about +Y, a mirroring child (scale -1 on x), a matrix leaf."""
    g = Gltf()
    pos = g.positions([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    idx = g.indices([0, 1, 2])
    h = math.sqrt(0.5)
    nodes = [{"name": "Root", "rotation": [0.0, h, 0.0, h], "children": [1]},
             {"name": "Mirror", "translation": [2.0, 0.0, 0.0], "scale": [-1.0, 1.0, 1.0], "children": [2]},
             {"name": "Tri", "mesh": 0, "matrix": [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0,
                                                    0.0, 1.0, 0.0, 1.0]}]
    return g.document(nodes, [{"name": "tri", "primitives": [{"attributes": {"POSITION": pos}, "indices": idx}]}],
                      uri="data")


def import_gltf():
    """The ``castplane import`` fixture: a camera (yfov 0.6), a point light and a spot light, a named
    mesh ``Cube``, an unnamed mesh node (node 3) and an ``extras.castplane`` cylinder."""
    g = Gltf()
    box_pos = g.positions([to_gltf_axes(v) for v in SPLIT_V])
    box_idx = g.indices(SPLIT_F)
    WV, WF = wedge()
    w_pos = g.positions([to_gltf_axes(v) for v in WV])
    w_idx = g.indices(WF)
    a = 0.1                                                            # half of the camera's -0.2 rad pitch
    c15, s15 = math.cos(math.radians(15.0)), math.sin(math.radians(15.0))
    nodes = [
        {"name": "Camera", "camera": 0, "translation": [0.0, 2.0, 8.0], "rotation": [-math.sin(a), 0.0, 0.0, math.cos(a)]},
        {"name": "Lamp", "translation": [2.0, 4.0, 1.0], "extensions": {"KHR_lights_punctual": {"light": 0}}},
        {"name": "Spot", "translation": [-2.0, 3.0, 0.0], "rotation": [-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)],
         "extensions": {"KHR_lights_punctual": {"light": 1}}},
        {"mesh": 1, "translation": [-1.5, 0.0, -1.0]},
        {"name": "Cube", "mesh": 0, "translation": [1.0, 0.0, 0.0]},
        {"name": "Pillar", "translation": [0.0, 0.0, -3.0], "rotation": [0.0, s15, 0.0, c15],
         "extras": {"castplane": {"type": "cylinder", "radius": 0.3, "height": 1.5}}},
    ]
    meshes = [{"name": "cube", "primitives": [{"attributes": {"POSITION": box_pos}, "indices": box_idx}]},
              {"name": "wedge", "primitives": [{"attributes": {"POSITION": w_pos}, "indices": w_idx}]}]
    extra = {"cameras": [{"type": "perspective", "perspective": {"yfov": YFOV, "aspectRatio": ASPECT, "znear": 0.1}}],
             "extensionsUsed": ["KHR_lights_punctual"],
             "extensions": {"KHR_lights_punctual": {"lights": [
                 {"type": "point", "intensity": 30.0}, {"type": "spot", "intensity": 30.0, "spot": {"outerConeAngle": 0.6}}]}}}
    return g.document(nodes, meshes, extra=extra, uri="data")


# --------------------------------------------------------------------------- example
def house_obj() -> str:
    """``examples/meshes/house.obj``: a closed house (box body + gable roof), metres, Z-up."""
    w, d, h, r = 1.2, 0.9, 0.8, 0.5
    V = [[-w / 2, -d / 2, 0.0], [w / 2, -d / 2, 0.0], [w / 2, d / 2, 0.0], [-w / 2, d / 2, 0.0],
         [-w / 2, -d / 2, h], [w / 2, -d / 2, h], [w / 2, d / 2, h], [-w / 2, d / 2, h],
         [-w / 2, 0.0, h + r], [w / 2, 0.0, h + r]]
    F = [[0, 3, 2, 1],                      # floor
         [0, 1, 5, 4], [2, 3, 7, 6],        # long walls (front y-, back y+)
         [1, 2, 6, 9, 5], [3, 0, 4, 8, 7],  # gable walls (pentagons)
         [4, 5, 9, 8], [6, 7, 8, 9]]        # roof planes
    lines = ["# castplane example mesh: a house (box body + gable roof), metres, Z-up", "o house", "s off"]
    lines += ["v " + " ".join(fmt(round(c, 6)) for c in v) for v in V]
    lines += ["f " + " ".join(str(k + 1) for k in f) for f in F]
    return "\n".join(lines) + "\n"


def outputs() -> dict:
    out = {
        FIXTURES / "box_split.obj": write_obj_box("z").encode("utf-8"),
        FIXTURES / "box_split_y.obj": write_obj_box("y").encode("utf-8"),
        FIXTURES / "features.obj": FEATURES_OBJ.encode("utf-8"),
        FIXTURES / "box.stl": write_stl().encode("utf-8"),
        FIXTURES / "box.ply": write_ply().encode("utf-8"),
        FIXTURES / "primitives.gltf": dump_json(primitives_gltf()),
        FIXTURES / "mirrored.gltf": dump_json(mirrored_gltf()),
        FIXTURES / "import_scene.gltf": dump_json(import_gltf()),
        EXAMPLES / "house.obj": house_obj().encode("utf-8"),
    }
    doc, blob = box_gltf("box.bin")
    out[FIXTURES / "box.gltf"] = dump_json(doc)
    out[FIXTURES / "box.bin"] = blob
    out[FIXTURES / "box_datauri.gltf"] = dump_json(box_gltf("data")[0])
    doc, blob = box_gltf(None)
    out[FIXTURES / "box.glb"] = glb(doc, blob)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="only compare with the committed files")
    args = ap.parse_args(argv)
    differ = []
    for path, data in sorted(outputs().items()):
        if args.check:
            if not path.is_file() or path.read_bytes() != data:
                differ.append(str(path.relative_to(ROOT)))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        print(path.relative_to(ROOT))
    if differ:
        print("differs: " + ", ".join(differ), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

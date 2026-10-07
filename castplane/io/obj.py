"""Wavefront OBJ reader for the ``mesh`` object type (contract §5.2.8; Python only, stdlib).

Supported: ``v x y z`` (extra components ignored), ``f`` with ``v``, ``v/vt``, ``v//vn`` and ``v/vt/vn``
corners, negative (relative) indices, polygons of >= 3 corners, ``o NAME`` / ``g NAME ...`` (a face
belongs to the current ``o`` and to every name of the current ``g``), ``s N`` / ``s off`` / ``s 0``
smoothing groups and ``\\`` line continuation.  ``#`` comments, ``vt``, ``vn``, ``l``, ``p``,
``mtllib``, ``usemtl`` and unknown keywords are ignored.  Errors are :class:`SceneError` with the
field ``line N`` (``castplane.io.expand_scene`` re-raises them at ``objects[i].path``).
"""

from __future__ import annotations

import math

from ..errors import SceneError

__all__ = ["parse_obj", "select_obj", "read_obj", "load_obj"]


def _logical_lines(text: str):
    """``(line number, text)`` of each logical line: ``\\`` at the end of a line joins the next."""
    pending, start = "", None
    for n, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if start is None:
            start = n
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        yield start, pending + line
        pending, start = "", None
    if start is not None:
        yield start, pending


def _index(token: str, n_seen: int, line: int) -> int:
    """0-based vertex index of one face corner (``v``, ``v/vt``, ``v//vn``, ``v/vt/vn``); a
    negative index counts back from the vertices read so far.  Positive indices are range-checked
    once the whole file is read (:func:`parse_obj`)."""
    head = token.split("/", 1)[0]
    try:
        k = int(head)
    except ValueError:
        raise SceneError(f"line {line}", f"face index {token!r} is not an integer") from None
    if k == 0:
        raise SceneError(f"line {line}", "face index 0 is invalid (OBJ indices start at 1)")
    if k < 0:
        k = n_seen + k
        if k < 0:
            raise SceneError(f"line {line}", f"relative face index {head} is out of range")
        return k
    return k - 1


def parse_obj(text: str) -> dict:
    """Parse OBJ text.  Returns ``{"vertices": [[x, y, z]...], "faces": [[int...]...],
    "smooth_groups": [int...], "face_names": [[names]...], "names": [distinct o / g names in order
    of first appearance]}`` (file axes, file units)."""
    vertices, faces, groups, face_names, names = [], [], [], [], []
    seen_names = set()
    current_o, current_g, smooth = None, [], 0
    face_lines = []

    def register(name):
        if name not in seen_names:
            seen_names.add(name)
            names.append(name)

    for line, content in _logical_lines(text):
        content = content.split("#", 1)[0]
        tokens = content.split()
        if not tokens:
            continue
        key = tokens[0]
        if key == "v":
            if len(tokens) < 4:
                raise SceneError(f"line {line}", "a vertex needs three coordinates")
            try:
                xyz = [float(t) for t in tokens[1:4]]
            except ValueError:
                raise SceneError(f"line {line}", f"non-numeric coordinate in {content.strip()!r}") from None
            if not all(math.isfinite(c) for c in xyz):
                raise SceneError(f"line {line}", "vertex coordinates must be finite")
            vertices.append([c + 0.0 for c in xyz])
        elif key == "f":
            corners = tokens[1:]
            if len(corners) < 3:
                raise SceneError(f"line {line}", "a face needs at least 3 vertices")
            faces.append([_index(t, len(vertices), line) for t in corners])
            groups.append(smooth)
            face_names.append(([current_o] if current_o is not None else []) + list(current_g))
            face_lines.append(line)
        elif key == "o":
            current_o = " ".join(tokens[1:])
            register(current_o)
        elif key == "g":
            current_g = tokens[1:]
            for name in current_g:
                register(name)
        elif key == "s":
            value = tokens[1] if len(tokens) > 1 else "off"
            if value == "off":
                smooth = 0
            else:
                try:
                    smooth = int(value)
                except ValueError:
                    raise SceneError(f"line {line}", f"invalid smoothing group {value!r}") from None
                if smooth < 0:
                    raise SceneError(f"line {line}", f"invalid smoothing group {value!r}")
        # vt, vn, l, p, mtllib, usemtl and unknown keywords are ignored
    n_v = len(vertices)
    for f, line in zip(faces, face_lines):
        for k in f:
            if k >= n_v:
                raise SceneError(f"line {line}", f"face index {k + 1} is out of range (the file has {n_v} vertices)")
    return {"vertices": vertices, "faces": faces, "smooth_groups": groups, "face_names": face_names, "names": names}


def select_obj(parsed: dict, node=None) -> dict:
    """The raw mesh ``{vertices, faces, smooth_groups}`` of a parsed OBJ file; ``node`` selects the
    faces of one ``o`` / ``g`` name (a string) or of the k-th distinct name (an integer).  With a
    selection the unused vertices are dropped (the kept ones stay in file order)."""
    faces, groups = parsed["faces"], parsed["smooth_groups"]
    vertices = parsed["vertices"]
    if node is not None:
        if isinstance(node, int):
            if not 0 <= node < len(parsed["names"]):
                raise SceneError("node", f"the file has {len(parsed['names'])} o / g name(s); index {node} is out of range")
            name = parsed["names"][node]
        else:
            name = node
            if name not in parsed["names"]:
                raise SceneError("node", f"no o / g named {name!r}")
        keep = [k for k, names in enumerate(parsed["face_names"]) if name in names]
        faces = [faces[k] for k in keep]
        groups = [groups[k] for k in keep]
        used = sorted({v for f in faces for v in f})
        renumber = {v: i for i, v in enumerate(used)}
        vertices = [vertices[v] for v in used]
        faces = [[renumber[v] for v in f] for f in faces]
    if not faces:
        raise SceneError("node" if node is not None else "", "no face in the selection" if node is not None
                         else "the file holds no face")
    return {"vertices": [list(v) for v in vertices], "faces": [list(f) for f in faces], "smooth_groups": list(groups)}


def load_obj(path, node=None, parsed=None) -> dict:
    """Read an OBJ file and return its raw mesh (:func:`select_obj`).  ``parsed`` (a
    :func:`parse_obj` result) skips the read (the per-call cache of ``expand_scene``)."""
    if parsed is None:
        parsed = read_obj(path)
    return select_obj(parsed, node)


def read_obj(path) -> dict:
    """:func:`parse_obj` of a file (UTF-8, a leading byte-order mark skipped; undecodable bytes are
    replaced, they only occur in names)."""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as fh:
        return parse_obj(fh.read())


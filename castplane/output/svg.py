"""§6.1 layered SVG writer, stdlib string building only (contract §2.10).

Image coordinates ``(u, v)`` are canvas mm with the origin at the frame centre,
``u`` right, ``v`` up.  SVG mapping (contract §2.1)::

    x_svg = u + W/2,   y_svg = H/2 - v,   viewBox="0 0 W H",  width="Wmm" height="Hmm"

The six ``<g>`` layers are emitted in the fixed order of contract §2.10 with
their ids; a layer whose content is empty is still written as an empty group.

Performance (spec §8): the coordinates of a whole layer (all edges, all rays, all
polygon vertices) are formatted at once with numpy (exact 4-decimal rounding,
digits from lookup tables, ``S`` byte-string arrays) and the elements themselves
(``<line/>``, ``<polygon/>``, ``<path/>``) are assembled as byte-string arrays
too, so that a layer's body is produced by a handful of C-level calls rather than
one Python statement per number.  :func:`_f` defines the number format;
:func:`_fmt_bytes` is its bulk equivalent and produces the very same strings
(only ``np.char`` is used, which exists in NumPy 1.x and 2.x).  A **chunk** is a
run of elements already joined with newlines; the group writer joins its body
with newlines, so a chunk and the list of its elements give the same text.
"""

from __future__ import annotations

from itertools import chain
from xml.sax.saxutils import escape

import numpy as np

#: Layer ids in drawing order, bottom to top (contract §2.10).
LAYER_ORDER = ("horizon", "objects", "form_shadow", "cast_shadow", "construction", "labels")

STYLE = {
    "horizon": 'stroke="#999" stroke-width="0.15" fill="none"',
    "horizon_point": 'r="0.6" fill="#999" stroke="none"',
    "horizon_text": 'font-size="2.5" fill="#999" font-family="sans-serif" stroke="none"',
    "objects": 'stroke="#111" stroke-width="0.3" fill="none" stroke-linecap="round"',
    "objects_back": 'stroke="#111" stroke-width="0.2" stroke-dasharray="1.2 0.8" fill="none" stroke-linecap="round"',
    "form_shadow": 'fill="#335" fill-opacity="0.18" stroke="none"',
    "terminator": 'fill="none" stroke="#335" stroke-width="0.2"',
    "cast_shadow": 'fill="#000" fill-opacity="0.3" stroke="#000" stroke-width="0.25" fill-rule="nonzero"',
    "cast_shadow_conics": 'fill="none"',
    "construction": 'stroke-width="0.15" fill="none"',
    "ray_LP": 'stroke="#d33"',
    "ray_FQ": 'stroke="#36c"',
    "ray_PQ": 'stroke="#3a3"',
    "labels": 'font-size="2.2" fill="#444" font-family="sans-serif" stroke="none"',
}

_TEXT_TPL = '<text x="%s" y="%s">%s</text>'


def _f(x: float) -> str:
    """Format a length in mm with 4 decimals, trailing zeros stripped, no negative zero."""
    s = f"{float(x) + 0.0:.4f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


#: Lookup tables of :func:`_fmt_bytes` (byte strings): the signed integer part
#: (``SIGNED[ip + 1000 * negative]`` for ``ip < 1000``, else ``SIGN + LOW[ip // 1000] + PAD3[ip % 1000]``)
#: and the stripped fraction digits of ``k / 10000``.
_SIGN = np.array([b"", b"-"])
_LOW = np.array([b"%d" % k for k in range(1000)])
_SIGNED = np.concatenate([_LOW, np.array([b"-%d" % k for k in range(1000)])])
_PAD3 = np.array([b"%03d" % k for k in range(1000)])
_FRAC = np.array([b""] + [(b"." + b"%04d" % k).rstrip(b"0") for k in range(1, 10000)])
#: ``|x * 1e4|`` beyond which (and within this distance of a rounding half-way) :func:`_f` is used.
_FMT_INT_MAX = 2.0 ** 31
_FMT_HALF_MARGIN = 1e-6

_add = np.char.add


def _fmt_bytes(values) -> np.ndarray:
    """Bulk :func:`_f`: an ``S`` array of the same strings, produced without per-number Python formatting.

    ``n = rint(x * 1e4)`` is the correctly rounded 4-decimal value of ``x`` whenever the
    computed product is not within ``_FMT_HALF_MARGIN`` of a rounding half-way (the product
    carries at most half an ulp of error, far below that margin for ``|x * 1e4| < 2**31``;
    an exact tie is impossible for a binary double), and ``n``'s digits are then assembled
    from lookup tables with numpy byte-string concatenation.  Everything else -- non-finite
    values, very large ones and the rare near-half-way products -- is formatted by :func:`_f`.
    """
    x = np.asarray(values, dtype=np.float64).ravel()
    if x.shape[0] == 0:
        return np.zeros(0, dtype="S1")
    with np.errstate(invalid="ignore", over="ignore"):
        y = x * 1e4
        r = np.rint(y)
        bad = ~np.isfinite(y) | (np.abs(y) >= _FMT_INT_MAX) | (np.abs(y - r) > 0.5 - _FMT_HALF_MARGIN)
    n = np.where(bad, 0.0, r).astype(np.int64)
    a = np.abs(n)
    ip, fp = a // 10000, a % 10000
    neg = (n < 0).astype(np.int64)
    big = ip >= 1000
    if np.any(big):
        head = np.where(big, _add(_add(_SIGN[neg], _LOW[ip // 1000]), _PAD3[ip % 1000]),
                        _SIGNED[np.where(big, 0, ip) + 1000 * neg])
    else:
        head = _SIGNED[ip + 1000 * neg]
    out = _add(head, _FRAC[fp])
    if np.any(bad):
        rows = np.nonzero(bad)[0].tolist()
        fixed = [_f(x[i]).encode("ascii") for i in rows]
        width = max(out.dtype.itemsize, max(len(s) for s in fixed))
        out = out.astype(f"S{width}")
        out[rows] = fixed
    return out


def _fmt_many(values) -> list:
    """Bulk :func:`_f` as a list of ``str`` (:func:`_fmt_bytes` decoded)."""
    arr = _fmt_bytes(values)
    if arr.shape[0] == 0:
        return []
    return _join(_add(arr, b"\n")).split("\n")[:-1]


def _join(arr: np.ndarray) -> str:
    """Concatenate an ``S`` array of ASCII elements into one ``str`` (the NUL padding of the
    fixed-width records is removed; no element ever contains a NUL)."""
    return arr.tobytes().translate(None, b"\0").decode("ascii")


def _chunk(arr: np.ndarray) -> list:
    """``[]`` for an empty element array, else ``[chunk]``: the elements (each ending with a
    newline) joined into one body item without the trailing newline."""
    if arr.shape[0] == 0:
        return []
    return [_join(arr)[:-1]]


def _decorated(pairs: np.ndarray, first, prefix_first: bytes, prefix: bytes, last, suffix_last: bytes,
               suffix: bytes = b"") -> np.ndarray:
    """``prefix + pair + suffix`` per point, with the first / last point of each element taking
    ``prefix_first`` / ``suffix_last`` instead: the segmented join of variable-length elements
    (polygons, paths) as one array whose records concatenate to the elements."""
    out = _add(np.where(first, prefix_first, prefix), pairs)
    return _add(out, np.where(last, suffix_last, suffix))


def _flat(nested, count: int) -> np.ndarray:
    """``(count, 2)`` array of the ``[u, v]`` points of a doubly nested list (C-level chain + fromiter,
    far cheaper than ``np.asarray`` on nested lists)."""
    return np.fromiter(chain.from_iterable(chain.from_iterable(nested)), dtype=np.float64, count=2 * count).reshape(-1, 2)


class _Canvas:
    def __init__(self, W: float, H: float):
        self.W, self.H = float(W), float(H)

    # -- bulk formatting -------------------------------------------------------------------
    def fmt(self, values) -> list:
        """Formatted strings (``_f``) of already mapped SVG coordinates, in bulk."""
        return _fmt_many(values)

    def svg_coords(self, uv) -> np.ndarray:
        """``(n, 2)`` canvas-mm points -> ``(n, 2)`` SVG coordinates (contract §2.1 mapping)."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        return np.stack([uv[:, 0] + self.W / 2.0, self.H / 2.0 - uv[:, 1]], axis=1)

    def coords_bytes(self, uv) -> np.ndarray:
        """Formatted SVG coordinates (``S`` array, ``(n, 2)``) of ``(n, 2)`` canvas-mm points."""
        uv = np.asarray(uv, dtype=np.float64).reshape(-1, 2)
        return _fmt_bytes(self.svg_coords(uv)).reshape(-1, 2)

    def lines(self, segments) -> np.ndarray:
        """``<line/>`` elements (no attributes, one per row, each ending with a newline) of ``n``
        canvas-mm segments ``[[u, v], [u, v]]`` as an ``S`` array (index / mask it, then :func:`_chunk`)."""
        n = len(segments)
        if not n:
            return np.zeros(0, dtype="S1")
        c = self.coords_bytes(_flat(segments, 2 * n)).reshape(-1, 4)
        out = _add(b'<line x1="', c[:, 0])
        out = _add(out, b'" y1="')
        out = _add(out, c[:, 1])
        out = _add(out, b'" x2="')
        out = _add(out, c[:, 2])
        out = _add(out, b'" y2="')
        out = _add(out, c[:, 3])
        return _add(out, b'"/>\n')

    def pairs_bytes(self, uv) -> np.ndarray:
        """``"x,y"`` byte strings (``S`` array) of ``n`` canvas-mm points ``[u, v]``."""
        n = len(uv)
        if not n:
            return np.zeros(0, dtype="S1")
        c = self.coords_bytes(np.fromiter(chain.from_iterable(uv), dtype=np.float64, count=2 * n).reshape(-1, 2))
        return _add(_add(c[:, 0], b","), c[:, 1])

    def pairs(self, uv) -> list:
        """``"x,y"`` strings of ``n`` canvas-mm points ``[u, v]``."""
        arr = self.pairs_bytes(uv)
        if arr.shape[0] == 0:
            return []
        return _join(_add(arr, b"\n")).split("\n")[:-1]

    def polygons(self, polys: list) -> tuple:
        """``<polygon/>`` elements of several ``[[u, v], ...]`` lists, all formatted at once: returns
        ``(records, offsets)`` where ``records`` is an ``S`` array with one record per vertex (the records
        of polygon ``k`` are ``records[offsets[k]:offsets[k + 1]]``) and the records of any run of whole
        polygons concatenate (:func:`_chunk`) to those polygons' elements."""
        lens = np.fromiter(map(len, polys), dtype=np.int64, count=len(polys))
        offsets = np.concatenate([[0], np.cumsum(lens)])
        total = int(offsets[-1])
        if total == 0:
            return np.zeros(0, dtype="S1"), offsets
        pairs = self.pairs_bytes(list(chain.from_iterable(polys)))
        pos = np.arange(total)
        first = np.zeros(total, dtype=bool)
        first[offsets[:-1][lens > 0]] = True
        last = np.zeros(total, dtype=bool)
        last[offsets[1:][lens > 0] - 1] = True
        return _decorated(pairs, first, b'<polygon points="', b" ", last, b'"/>\n'), offsets

    def paths(self, entries: list) -> list:
        """One ``<path/>`` per entry (a list of closed loops), all loops formatted at once."""
        loops = [loop for loops in entries for loop in loops]
        loop_lens = np.fromiter(map(len, loops), dtype=np.int64, count=len(loops))
        n_loops = np.fromiter(map(len, entries), dtype=np.int64, count=len(entries))
        total = int(loop_lens.sum())
        if total == 0:
            return ['<path d=""/>' for _ in entries]
        pairs = self.pairs_bytes(list(chain.from_iterable(loops)))
        loop_off = np.concatenate([[0], np.cumsum(loop_lens)])
        entry_off = np.concatenate([[0], np.cumsum(n_loops)])
        loop_first = np.zeros(total, dtype=bool)
        loop_first[loop_off[:-1][loop_lens > 0]] = True
        loop_last = np.zeros(total, dtype=bool)
        loop_last[loop_off[1:][loop_lens > 0] - 1] = True
        # the first / last loop of every entry (entries without loops have no points at all)
        entry_first = np.zeros(total, dtype=bool)
        entry_last = np.zeros(total, dtype=bool)
        has = n_loops > 0
        entry_first[loop_off[entry_off[:-1][has]]] = True
        entry_last[loop_off[entry_off[1:][has]] - 1] = True
        prefix = np.where(entry_first, b'<path d="M ', np.where(loop_first, b" M ", b" L "))
        suffix = np.where(entry_last, b' Z"/>\n', np.where(loop_last, b" Z", b""))
        text = _join(_add(_add(prefix, pairs), suffix))
        elems = iter(text.split("\n"))
        return [next(elems) if h else '<path d=""/>' for h in has.tolist()]

    def texts(self, pts, labels, attrs_list, dx, dy) -> list:
        """``<text>`` elements at ``pts + (dx, -dy)`` (scalar or per-element offsets), see :meth:`text`;
        ``attrs_list`` is ``None`` or one attribute string per element."""
        pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        if pts.shape[0] == 0:
            return []
        dx = np.asarray(dx, dtype=np.float64)
        dy = np.asarray(dy, dtype=np.float64)
        shifted = np.stack([pts[:, 0] + dx, pts[:, 1] - dy], axis=1)
        nums = self.fmt(self.svg_coords(shifted))
        it = iter(nums)
        joined = "".join(labels)
        escaped = list(map(escape, labels)) if ("&" in joined or "<" in joined or ">" in joined) else labels
        if attrs_list is None or not any(attrs_list):
            return list(map(_TEXT_TPL.__mod__, zip(it, it, escaped)))
        out = []
        for (x, y), s, attrs in zip(zip(it, it), escaped, attrs_list):
            sep = " " if attrs else ""
            out.append(f'<text x="{x}" y="{y}"{sep}{attrs}>{s}</text>')
        return out

    # -- single elements -------------------------------------------------------------------
    def xy(self, uv):
        return _f(uv[0] + self.W / 2.0), _f(self.H / 2.0 - uv[1])

    def line(self, a, b, attrs: str = "") -> str:
        x1, y1 = self.xy(a)
        x2, y2 = self.xy(b)
        sep = " " if attrs else ""
        return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}"{sep}{attrs}/>'

    def circle(self, c, attrs: str) -> str:
        x, y = self.xy(c)
        return f'<circle cx="{x}" cy="{y}" {attrs}/>'

    def text(self, p, s: str, attrs: str = "", dx: float = 0.8, dy: float = -0.8) -> str:
        x, y = self.xy((p[0] + dx, p[1] - dy))
        sep = " " if attrs else ""
        return f'<text x="{x}" y="{y}"{sep}{attrs}>{escape(s)}</text>'

    def polygon(self, pts, attrs: str = "") -> str:
        coords = " ".join(self.pairs(pts))
        sep = " " if attrs else ""
        return f'<polygon points="{coords}"{sep}{attrs}/>'

    def path(self, loops, attrs: str = "") -> str:
        """One ``<path>`` whose subpaths are the closed loops (filled together under the group's fill rule)."""
        if not attrs:
            return self.paths([loops])[0]
        parts = ["M " + " L ".join(self.pairs(pts)) + " Z" for pts in loops]
        return f'<path d="{" ".join(parts)}" {attrs}/>'

    def polyline(self, pts, attrs: str = "") -> str:
        coords = " ".join(self.pairs(pts))
        sep = " " if attrs else ""
        return f'<polyline points="{coords}"{sep}{attrs}/>'

    def ellipse(self, e: dict, attrs: str = "") -> str:
        """``<ellipse>`` of a conic drawable ``{centre, rx, ry, rotation_deg}`` given in the ``v``-up
        frame: the rotation angle changes sign in SVG's ``y``-down frame (contract §2.6)."""
        cx, cy = self.xy(e["centre"])
        sep = " " if attrs else ""
        rot = -float(e["rotation_deg"])
        transform = f' transform="rotate({_f(rot)} {cx} {cy})"' if abs(rot) > 1e-12 else ""
        return f'<ellipse cx="{cx}" cy="{cy}" rx="{_f(e["rx"])}" ry="{_f(e["ry"])}"{transform}{sep}{attrs}/>'

    def arc(self, a: dict, attrs: str = "") -> str:
        """``<path d="M … A rx ry rot large sweep …">`` of an ellipse arc drawable
        ``{start, end, rx, ry, rotation_deg, large_arc, sweep}``; ``sweep`` is given in the ``v``-up
        frame and is flipped for SVG's ``y``-down frame, the rotation changes sign (contract §2.6)."""
        x1, y1 = self.xy(a["start"])
        x2, y2 = self.xy(a["end"])
        sweep = 0 if int(a["sweep"]) else 1
        d = (f"M {x1} {y1} A {_f(a['rx'])} {_f(a['ry'])} {_f(-float(a['rotation_deg']))} "
             f"{int(a['large_arc'])} {sweep} {x2} {y2}")
        sep = " " if attrs else ""
        return f'<path d="{d}"{sep}{attrs}/>'

    def diamond(self, c, r: float, attrs: str) -> str:
        pts = [(c[0] + r, c[1]), (c[0], c[1] + r), (c[0] - r, c[1]), (c[0], c[1] - r)]
        return self.polygon(pts, attrs)


def _attr(s: str) -> str:
    """Escape a double-quoted attribute value: ``&``, ``<``, ``>`` and ``"`` (ids may contain any of them)."""
    return escape(str(s), {'"': "&quot;"})


def _group(gid: str, attrs: str, body: list) -> str:
    sep = " " if attrs else ""
    if not body:
        return f'<g id="{_attr(gid)}"{sep}{attrs}/>'
    inner = "\n".join(body)
    return f'<g id="{_attr(gid)}"{sep}{attrs}>\n{inner}\n</g>'


# ---------------------------------------------------------------------------
# layers
# ---------------------------------------------------------------------------

def _layer_horizon(doc: dict, cv: _Canvas) -> list:
    body = []
    hz = doc.get("horizon") or {}
    seg = hz.get("segment")
    if seg:
        body.append(cv.line(seg[0], seg[1]))
    for axis in ("x", "y", "z"):
        vp = (hz.get("vanishing_points") or {}).get(axis)
        if vp is not None:
            body.append(cv.circle(vp, STYLE["horizon_point"]))
            body.append(cv.text(vp, f"VP{axis}", STYLE["horizon_text"]))
    pp = (doc.get("camera") or {}).get("principal_point")
    if pp is not None:
        body.append(cv.circle(pp, STYLE["horizon_point"]))
        body.append(cv.text(pp, "PP", STYLE["horizon_text"]))
    return body


def _layer_objects(doc: dict, cv: _Canvas) -> list:
    """Edges (front solid / back dashed) and, for curved objects, the outline conics of ``doc["outlines"]``
    (cap arcs split at the outline generators, far arcs dashed; contract §2.10)."""
    drawn = [e for e in doc.get("edges", []) if e["segment"] is not None]
    lines = cv.lines([e["segment"] for e in drawn])
    back_flags = np.fromiter((bool(e["back"]) for e in drawn), dtype=bool, count=len(drawn))
    per_object = {}
    # edges come grouped by object (compose writes them object by object), so one split per run
    owners = [e["object"] for e in drawn]
    starts = [k for k in range(len(owners)) if k == 0 or owners[k] != owners[k - 1]]
    for a, b in zip(starts, starts[1:] + [len(owners)]):
        front, back = per_object.setdefault(owners[a], ([], []))
        run_back = back_flags[a:b]
        if run_back.any():
            front.extend(_chunk(lines[a:b][~run_back]))
            back.extend(_chunk(lines[a:b][run_back]))
        else:
            front.extend(_chunk(lines[a:b]))
    for entry in doc.get("outlines", []):
        front, back = per_object.setdefault(entry["object"], ([], []))
        for g in entry.get("generators", []) or []:
            if g.get("segment") is not None:
                (back if g.get("back") else front).append(cv.line(*g["segment"]))
        for c in entry.get("conics", []) or []:
            (back if c.get("back") else front).extend(_drawables(c, cv))
    body = []
    for oid in sorted(per_object):
        front, back = per_object[oid]
        sub = []
        if front:
            sub.append(_group(f"objects.{oid}.front", STYLE["objects"], front))
        if back:
            sub.append(_group(f"objects.{oid}.back", STYLE["objects_back"], back))
        body.append(_group(f"objects.{oid}", "", sub))
    return body


def _drawables(entry: dict, cv: _Canvas) -> list:
    """Drawables of a conic / terminator entry, already in canvas mm (contract §2.6): sampled
    ``polylines``, elliptical ``arcs`` (``<path … A …>``) and whole ``ellipses``."""
    out = []
    for pl in entry.get("polylines", []) or []:
        if len(pl) >= 2:
            out.append(cv.polyline(pl))
    for a in entry.get("arcs", []) or []:
        out.append(cv.arc(a))
    for e in entry.get("ellipses", []) or []:
        out.append(cv.ellipse(e))
    return out


def _layer_form_shadow(doc: dict, cv: _Canvas) -> list:
    body = []
    points = doc.get("points", {})
    entries = doc.get("form_shadow", [])
    # all drawable polygons of the layer are formatted in one go (spec §8)
    poly_lists = []
    for entry in entries:
        polygons = entry.get("polygons")
        if polygons is not None:  # near-clipped drawable polygons in image mm (contract §2.2), M1+
            poly_lists.append([poly for poly in polygons if len(poly) >= 3])
        else:
            polys = []
            for face in entry.get("faces", []) or []:
                pts = [points.get(n, {}).get("image") for n in face]
                if pts and all(p is not None for p in pts):
                    polys.append(pts)
            poly_lists.append(polys)
    records, offsets = cv.polygons([poly for polys in poly_lists for poly in polys])
    pos = 0
    for entry, polys in zip(entries, poly_lists):
        a, b = int(offsets[pos]), int(offsets[pos + len(polys)])
        pos += len(polys)
        sub = _chunk(records[a:b])
        term = []
        for t in entry.get("terminator", []) or []:
            if "segment" in t and "polylines" not in t:  # no drawable: fall back to the named points' images
                a, b = (points.get(n, {}).get("image") for n in t["segment"])
                if a is not None and b is not None:
                    term.append(cv.line(a, b))
            term.extend(_drawables(t, cv))
        if term:
            sub.append(_group(f"form_shadow.{entry.get('object', '')}.terminator", STYLE["terminator"], term))
        if sub:
            body.append(_group(f"form_shadow.{entry.get('object', '')}", "", sub))
    return body


def _layer_cast_shadow(doc: dict, cv: _Canvas) -> list:
    """One ``<path>`` per shadow entry with all of its loops as subpaths, so that the ``nonzero``
    fill rule of the layer group unites the loops of one object (contract §2.5 / §2.10)."""
    per_light = {}
    points = doc.get("points", {})
    shadows = doc.get("shadows", [])
    loop_sets = []
    first_receiver = doc["receivers"][0]["id"] if doc.get("receivers") else None   # None: a v2 document
    for sh in shadows:
        polygons = sh.get("polygons")
        if polygons is None:  # documents without drawables: fall back to the named outline points
            polygons = []
            for loop in sh.get("loops", []) or []:
                pts = [points.get(n, {}).get("image") if isinstance(n, str) else None for n in loop]
                if len(pts) >= 3 and all(p is not None for p in pts):
                    polygons.append(pts)
        loop_sets.append([poly for poly in polygons if len(poly) >= 3])  # clipped drawable polygons (§2.5)
    with_loops = [k for k, loops in enumerate(loop_sets) if loops]
    path_of = dict(zip(with_loops, cv.paths([loop_sets[k] for k in with_loops])))
    for k, sh in enumerate(shadows):
        items = []
        if k in path_of:
            items.append(path_of[k])
        conics = []
        for entry in sh.get("conics", []) or []:
            conics.extend(_drawables(entry, cv))
        if conics:  # the exact conic outline on top of the filled polygon, stroke only (§2.6)
            items.append(_group(_shadow_subgroup_id(sh, first_receiver, "conics"),
                                STYLE["cast_shadow_conics"], conics))
        per_light.setdefault(sh.get("light", ""), []).extend(items)
    return [_group(f"cast_shadow.{light}", "", items) for light, items in sorted(per_light.items())]


def _shadow_subgroup_id(sh: dict, first_receiver, suffix: str) -> str:
    """``cast_shadow.<light>.<object>.<suffix>`` for a record on ``receivers[0]`` and for every record of a v2
    document (no ``receivers`` block: one receiver; the v2 id, golden hashes),
    ``cast_shadow.<light>.<object>.<receiver>.<suffix>`` for a record on any other receiver, so that an object
    casting on several receivers keeps unique ids (M4 implementation note, §5.1)."""
    rid = sh.get("receiver")
    infix = "" if first_receiver is None or rid is None or rid == first_receiver else f".{rid}"
    return f"cast_shadow.{sh.get('light', '')}.{sh.get('object', '')}{infix}.{suffix}"


def _layer_construction(doc: dict, cv: _Canvas) -> list:
    body = []
    con = doc.get("construction") or {}
    lp = con.get("light_point")
    if lp is not None:
        body.append(cv.circle(lp, 'r="1" fill="none" stroke="#d33"'))
        body.append(cv.text(lp, "L′", 'font-size="2.5" fill="#d33" font-family="sans-serif" stroke="none"', dx=1.4))
    fp = con.get("shadow_vp")
    if fp is not None:
        body.append(cv.diamond(fp, 1.0, 'fill="none" stroke="#36c"'))
        body.append(cv.text(fp, "F′", 'font-size="2.5" fill="#36c" font-family="sans-serif" stroke="none"', dx=1.4))
    # M4 (contract §5.0.6): every other receiver's F'_r marker (labelled F′<receiver id>) and its rays go to
    # the same three groups (no per-receiver sub-group)
    per_receiver = con.get("per_receiver") or {}
    segments = list(con.get("segments", []) or [])
    for rid, blk in per_receiver.items():
        fpr = blk.get("shadow_vp")
        if fpr is not None:
            body.append(cv.diamond(fpr, 1.0, 'fill="none" stroke="#36c"'))
            body.append(cv.text(fpr, f"F′{rid}", 'font-size="2.5" fill="#36c" font-family="sans-serif" stroke="none"',
                                dx=1.4))
        segments.extend(blk.get("segments", []) or [])
    drawn = [seg for seg in segments  # drawable 2-D ray segments (M1)
             if seg["kind"] in ("LP", "FQ", "PQ") and seg["points"] and len(seg["points"]) == 2]
    lines = cv.lines([seg["points"] for seg in drawn])
    kinds = np.array([seg["kind"] for seg in drawn], dtype="U2")
    for kind in ("LP", "FQ", "PQ"):
        sel = kinds == kind
        if sel.any():
            body.append(_group(f"construction.{kind}", STYLE[f"ray_{kind}"], _chunk(lines[sel])))
    return body


def _is_labelled(parts: list) -> bool:
    """Vertex ids (``v<k>``) and curved construction points (``c``, ``sil.<k>``, ``g<k>.base`` / ``.top``,
    ``apex``; contract §2.7) get labels; shadows, feet, ground points (``s<k>``) and camera outline
    generator endpoints (``og<k>``) do not."""
    if len(parts) < 2 or "shadow" in parts[1:] or "foot" in parts[1:]:
        return False
    head = parts[1]
    if head.startswith("s") and head[1:].isdigit():
        return False
    if head.startswith("og"):
        return False
    return True


def _has_shadow_or_foot_part(name: str) -> bool:
    """Some part after the first of the dotted name is ``shadow`` or ``foot`` (contract §5.0.4)."""
    parts = name.split(".")[1:]
    return "shadow" in parts or "foot" in parts


def _layer_labels(doc: dict, cv: _Canvas) -> list:
    points = doc.get("points", {})
    top = {}
    pts, labels = [], []
    lf_pts, lf_labels = [], []
    # contract §5.0.4: a name is unlabelled iff a part after the first is "shadow" or "foot" (the receiver
    # suffix may follow "foot"); the C-level substring pre-filter only lets such names through to the
    # exact part test below
    for name in sorted(n for n in points
                       if not ((".shadow" in n or ".foot" in n) and _has_shadow_or_foot_part(n))):
        p = points[name]
        img = p["image"]
        if img is None:
            continue
        oid, _dot, rest = name.partition(".")
        if not rest:
            continue
        if oid in ("L", "F"):
            # L.<light> and F.<light>[.<r>] go through the L/F branch and never set an object's top label
            # below the L'/F' marker text of the construction layer
            lf_pts.append(img)
            lf_labels.append(name)
            continue
        # _is_labelled(name.split(".")) inlined for the names that passed the filter above (no part after
        # the first is "shadow" / "foot"): ground points s<k> and camera outline points og<k> are unlabelled
        head = rest.partition(".")[0]
        if head.startswith("og") or (head[:1] == "s" and head[1:].isdigit()):
            continue
        pts.append(img)
        labels.append(rest)
        z = p.get("world", (0.0, 0.0, 0.0))[2]
        t = top.get(oid)
        if t is None or z > t[0]:
            top[oid] = (z, img)
    body = cv.texts(lf_pts, lf_labels, None, 1.4, 2.4)
    body.extend(cv.texts(pts, labels, None, 0.8, -0.8))
    ids = sorted(top)
    body.extend(cv.texts([top[oid][1] for oid in ids], ids, ['font-weight="bold"'] * len(ids), 0.8, -3.2))
    return body


_LAYER_BUILDERS = {
    "horizon": (_layer_horizon, STYLE["horizon"]),
    "objects": (_layer_objects, ""),
    "form_shadow": (_layer_form_shadow, STYLE["form_shadow"]),
    "cast_shadow": (_layer_cast_shadow, STYLE["cast_shadow"]),
    "construction": (_layer_construction, STYLE["construction"]),
    "labels": (_layer_labels, STYLE["labels"]),
}


#: ``hidden_style`` values of :func:`write_svg` (contract §5.1.8).
HIDDEN_STYLES = ("dashed", "omit")


def write_svg(doc: dict, layers=None, hidden_style: str = "dashed") -> str:
    """Write the §6.1 SVG of a geometry document; ``layers`` selects a subset of the six ids (contract §2.10).

    ``hidden_style`` (contract §5.1.8 / §5.0.6): ``"dashed"`` draws the hidden runs of a document with
    ``hidden_lines == true`` dashed in the ``*.hidden`` sub-groups, ``"omit"`` writes those groups empty.
    A document with ``hidden_lines`` false (or absent) is written exactly as by the v2 writer."""
    if hidden_style not in HIDDEN_STYLES:
        raise ValueError(f"unknown hidden_style {hidden_style!r}; expected one of {', '.join(HIDDEN_STYLES)}")
    if layers is None:
        selected = list(LAYER_ORDER)
    else:
        unknown = [name for name in layers if name not in LAYER_ORDER]
        if unknown:
            raise ValueError(f"unknown SVG layer(s): {', '.join(map(str, unknown))}")
        selected = [name for name in LAYER_ORDER if name in set(layers)]
    W, H = (float(c) for c in doc["canvas_mm"])
    cv = _Canvas(W, H)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_f(W)}mm" height="{_f(H)}mm" '
        f'viewBox="0 0 {_f(W)} {_f(H)}">',
    ]
    for name in selected:
        builder, attrs = _LAYER_BUILDERS[name]
        parts.append(_group(name, attrs, builder(doc, cv)))
    parts.append("</svg>")
    return "\n".join(parts) + "\n"

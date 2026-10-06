"""§6.1 layered SVG writer, stdlib string building only (contract §2.10).

Image coordinates ``(u, v)`` are canvas mm with the origin at the frame centre,
``u`` right, ``v`` up.  SVG mapping (contract §2.1)::

    x_svg = u + W/2,   y_svg = H/2 - v,   viewBox="0 0 W H",  width="Wmm" height="Hmm"

The six ``<g>`` layers are emitted in the fixed order of contract §2.10 with
their ids; a layer whose content is empty is still written as an empty group.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

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
    "construction": 'stroke-width="0.15" fill="none"',
    "ray_LP": 'stroke="#d33"',
    "ray_FQ": 'stroke="#36c"',
    "ray_PQ": 'stroke="#3a3"',
    "labels": 'font-size="2.2" fill="#444" font-family="sans-serif" stroke="none"',
}


def _f(x: float) -> str:
    """Format a length in mm with 4 decimals, trailing zeros stripped, no negative zero."""
    s = f"{float(x) + 0.0:.4f}".rstrip("0").rstrip(".")
    if s in ("-0", ""):
        s = "0"
    return s


class _Canvas:
    def __init__(self, W: float, H: float):
        self.W, self.H = float(W), float(H)

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
        coords = " ".join(",".join(self.xy(p)) for p in pts)
        sep = " " if attrs else ""
        return f'<polygon points="{coords}"{sep}{attrs}/>'

    def polyline(self, pts, attrs: str = "") -> str:
        coords = " ".join(",".join(self.xy(p)) for p in pts)
        sep = " " if attrs else ""
        return f'<polyline points="{coords}"{sep}{attrs}/>'

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
    per_object = {}
    for e in doc.get("edges", []):
        if e.get("segment") is None:
            continue
        per_object.setdefault(e["object"], ([], []))[1 if e.get("back") else 0].append(e["segment"])
    body = []
    for oid in sorted(per_object):
        front, back = per_object[oid]
        sub = []
        if front:
            sub.append(_group(f"objects.{oid}.front", STYLE["objects"], [cv.line(s[0], s[1]) for s in front]))
        if back:
            sub.append(_group(f"objects.{oid}.back", STYLE["objects_back"], [cv.line(s[0], s[1]) for s in back]))
        body.append(_group(f"objects.{oid}", "", sub))
    for entry in doc.get("outlines", []):  # curved outlines (M2): pre-sampled polylines / ellipse paths
        body.extend(_drawables(entry, cv))
    return body


def _drawables(entry: dict, cv: _Canvas) -> list:
    """Generic drawables used by later milestones: ``polylines`` and ``paths`` already in image mm."""
    out = []
    for pl in entry.get("polylines", []) or []:
        if len(pl) >= 2:
            out.append(cv.polyline(pl))
    for d in entry.get("paths", []) or []:
        out.append(f'<path d="{_attr(d)}"/>')
    return out


def _layer_form_shadow(doc: dict, cv: _Canvas) -> list:
    body = []
    points = doc.get("points", {})
    for entry in doc.get("form_shadow", []):
        sub = []
        for face in entry.get("faces", []) or []:
            pts = [points.get(n, {}).get("image") for n in face]
            if pts and all(p is not None for p in pts):
                sub.append(cv.polygon(pts))
        term = []
        for t in entry.get("terminator", []) or []:
            if "segment" in t:
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
    per_light = {}
    points = doc.get("points", {})
    for sh in doc.get("shadows", []):
        polys = []
        for poly in sh.get("polygons", []) or []:  # clipped drawable polygons in image mm (M1)
            if len(poly) >= 3:
                polys.append(cv.polygon(poly))
        if not polys:
            for loop in sh.get("loops", []) or []:
                pts = [points.get(n, {}).get("image") if isinstance(n, str) else None for n in loop]
                if len(pts) >= 3 and all(p is not None for p in pts):
                    polys.append(cv.polygon(pts))
        for entry in sh.get("conics", []) or []:
            polys.extend(_drawables(entry, cv))
        per_light.setdefault(sh.get("light", ""), []).extend(polys)
    return [_group(f"cast_shadow.{light}", "", items) for light, items in sorted(per_light.items())]


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
    rays = {"LP": [], "FQ": [], "PQ": []}
    for seg in con.get("segments", []) or []:  # drawable 2-D ray segments (M1)
        kind = seg.get("kind")
        pts = seg.get("points")
        if kind in rays and pts and len(pts) == 2:
            rays[kind].append(cv.line(pts[0], pts[1]))
    for kind in ("LP", "FQ", "PQ"):
        if rays[kind]:
            body.append(_group(f"construction.{kind}", STYLE[f"ray_{kind}"], rays[kind]))
    return body


def _layer_labels(doc: dict, cv: _Canvas) -> list:
    body = []
    points = doc.get("points", {})
    top = {}
    for name in sorted(points):
        p = points[name]
        img = p.get("image")
        if img is None:
            continue
        parts = name.split(".")
        oid = parts[0]
        label = parts[-1] if len(parts) > 1 else name
        if len(parts) == 2 and label.startswith("v") and label[1:].isdigit():
            body.append(cv.text(img, label))
            z = p.get("world", [0.0, 0.0, 0.0])[2]
            if oid not in top or z > top[oid][0]:
                top[oid] = (z, img)
        elif len(parts) == 2 and oid in ("L", "F"):
            body.append(cv.text(img, name))
    for oid in sorted(top):
        z, img = top[oid]
        body.append(cv.text(img, oid, 'font-weight="bold"', dx=0.8, dy=-3.2))
    return body


_LAYER_BUILDERS = {
    "horizon": (_layer_horizon, STYLE["horizon"]),
    "objects": (_layer_objects, ""),
    "form_shadow": (_layer_form_shadow, STYLE["form_shadow"]),
    "cast_shadow": (_layer_cast_shadow, STYLE["cast_shadow"]),
    "construction": (_layer_construction, STYLE["construction"]),
    "labels": (_layer_labels, STYLE["labels"]),
}


def write_svg(doc: dict, layers=None) -> str:
    """Write the §6.1 SVG of a geometry document; ``layers`` selects a subset of the six ids (contract §2.10)."""
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

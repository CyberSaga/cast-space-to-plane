"""Multi-light SVG layers (contract §5.3.6, §5.0.6; M6).

A geometry document is **multi-light** iff it carries the ``constructions`` key (``N >= 2``
lights, contract §5.3.5); :mod:`castplane.output.svg` then hands its ``form_shadow``,
``cast_shadow`` and ``construction`` layers to the builders of this module.  For ``N = 1`` none of
this code runs and the single-light SVG is written exactly as before.

``N_act = max(1, number of distinct ids in the union of all umbra[].lights)`` is the opacity
divisor; light sub-groups are ordered by light id in code-point order, object sub-groups keep
document order (contract §5.3.6):

- ``form_shadow``: (``form_shadow.hidden`` iff hidden lines are on) then per light
  ``<g id="form_shadow.<light>" fill-opacity="<0.18/N_act>">`` holding ``form_shadow.<light>.<obj>``
  (that light's unlit faces **minus the core faces**) and ``form_shadow.<light>.<obj>.terminator``,
  then ``<g id="form_shadow.core">`` holding ``form_shadow.core.<obj>``;
- ``cast_shadow``: (``cast_shadow.hidden``) then per light ``<g id="cast_shadow.<light>"
  fill-opacity="<0.3/N_act>">`` with the single-light content, then ``<g id="cast_shadow.umbra"
  fill="#000" fill-opacity="0.3" stroke="none">`` with one ``<path>`` per ``umbra[]`` entry whose
  ``polygons`` is non-empty (one ``M … Z`` subpath per piece);
- ``construction``: per light ``<g id="construction.<light>">`` holding that light's ``L′`` / ``F′``
  markers (every receiver's ``F′_r`` included) and ``construction.<light>.LP`` / ``.FQ`` / ``.PQ``.
"""

from __future__ import annotations

from . import svg as _svg

__all__ = ["is_multi_light", "n_active", "light_ids", "layer_form_shadow", "layer_cast_shadow",
           "layer_construction", "UMBRA_STYLE"]

#: Style of the ``cast_shadow.umbra`` sub-group (contract §5.3.6).
UMBRA_STYLE = 'fill="#000" fill-opacity="0.3" stroke="none"'


def is_multi_light(doc: dict) -> bool:
    """The writer's test for a multi-light document: the ``constructions`` key (contract §5.3.6)."""
    return "constructions" in doc


def n_active(doc: dict) -> int:
    """``N_act = max(1, number of distinct ids in the union of all umbra[].lights)`` (contract §5.3.6)."""
    ids = {lid for e in doc.get("umbra", []) or [] for lid in e.get("lights", []) or []}
    return max(1, len(ids))


def light_ids(doc: dict) -> list:
    """The document's light ids in code-point order (the keys of ``constructions``)."""
    return sorted(doc.get("constructions", {}) or {})


def _opacity(base: float, doc: dict) -> str:
    return f'fill-opacity="{_svg._f(base / n_active(doc))}"'


def _without(doc: dict, key: str) -> dict:
    """A shallow copy of ``doc`` without ``key`` (the single-light builders then run unbranched)."""
    return {k: v for k, v in doc.items() if k != key}


# ---------------------------------------------------------------------------
# form_shadow
# ---------------------------------------------------------------------------

def _core_faces(doc: dict) -> dict:
    """``{object: set of face name tuples}`` of ``form_shadow_core``."""
    out = {}
    for c in doc.get("form_shadow_core", []) or []:
        out.setdefault(c.get("object", ""), set()).update(tuple(f) for f in c.get("faces", []) or [])
    return out


def _light_polygons(entry: dict, core: set) -> list:
    """The drawable polygons of a per-light entry except the core faces (writer rule, contract §5.3.6;
    the document keeps them in the entry).  ``polygons`` is parallel to ``faces`` for polyhedral
    objects; when it is not (a plate whose face is clipped away), the entry is drawn whole unless every
    face is a core face."""
    faces = entry.get("faces", []) or []
    polygons = entry.get("polygons", []) or []
    if len(polygons) == len(faces):
        polys = [p for f, p in zip(faces, polygons) if tuple(f) not in core]
    elif faces and all(tuple(f) in core for f in faces):
        polys = []
    else:
        polys = list(polygons)
    return [p for p in polys if len(p) >= 3]


def _terminator(entry: dict, cv, hidden: bool, points: dict) -> tuple:
    """Terminator drawables of one entry: ``(elements, hidden segments, hidden polylines)`` exactly as the
    single-light writer draws them (hidden runs split off when hidden lines are on)."""
    term, hid, hid_pl = [], [], []
    for t in entry.get("terminator", []) or []:
        if hidden:
            if "segment" in t:
                for seg in t.get("polylines", []) or []:
                    if len(seg) != 2:
                        continue
                    shown, h = _svg._split_runs(seg, t)
                    term.extend(cv.polyline(p) for p in shown)
                    hid.extend(h)
                continue
            term.extend(_svg._drawables(t, cv))
            hid_pl.extend(_svg._conic_hidden(t))
            continue
        if "segment" in t and "polylines" not in t:  # no drawable: fall back to the named points' images
            a, b = (points.get(n, {}).get("image") for n in t["segment"])
            if a is not None and b is not None:
                term.append(cv.line(a, b))
        term.extend(_svg._drawables(t, cv))
    return term, hid, hid_pl


def layer_form_shadow(doc: dict, cv, hidden_style=None) -> list:
    """The ``form_shadow`` layer body of a multi-light document (contract §5.3.6, §5.0.6).
    ``hidden_style`` is ``None`` when the document's hidden lines are off, else the writer's style."""
    hidden = hidden_style is not None
    points = doc.get("points", {})
    entries = doc.get("form_shadow", []) or []
    core = _core_faces(doc)
    lids = light_ids(doc)
    attrs = _opacity(0.18, doc)
    # every drawable polygon of the layer is formatted in one go (spec §8): per-light entries, then the core
    per_entry = [_light_polygons(e, core.get(e.get("object", ""), set())) for e in entries]
    core_entries = doc.get("form_shadow_core", []) or []
    per_core = [[p for p in (c.get("polygons", []) or []) if len(p) >= 3] for c in core_entries]
    all_polys = [p for ps in per_entry + per_core for p in ps]
    records, offsets = cv.polygons(all_polys)
    starts, pos = [], 0
    for ps in per_entry + per_core:
        starts.append((int(offsets[pos]), int(offsets[pos + len(ps)])))
        pos += len(ps)
    by_light = {lid: [] for lid in lids}
    hidden_groups = {}                     # object -> (segments, polylines), first-appearance order
    for k, entry in enumerate(entries):
        lid, oid = entry.get("light", ""), entry.get("object", "")
        a, b = starts[k]
        sub = _svg._chunk(records[a:b])
        term, hid, hid_pl = _terminator(entry, cv, hidden, points)
        if term:
            sub.append(_svg._group(f"form_shadow.{lid}.{oid}.terminator", _svg.STYLE["terminator"], term))
        if hid or hid_pl:
            h = hidden_groups.setdefault(oid, ([], []))
            h[0].extend(hid)
            h[1].extend(hid_pl)
        if sub:
            by_light.setdefault(lid, []).append(_svg._group(f"form_shadow.{lid}.{oid}", "", sub))
    body = []
    if hidden:
        body.append(_svg._hidden_group("form_shadow", [(oid, *hidden_groups[oid]) for oid in hidden_groups],
                                       hidden_style, cv))
    body.extend(_svg._group(f"form_shadow.{lid}", attrs, by_light[lid]) for lid in sorted(by_light))
    core_body = []
    for j, c in enumerate(core_entries):
        a, b = starts[len(entries) + j]
        sub = _svg._chunk(records[a:b])
        if sub:
            core_body.append(_svg._group(f"form_shadow.core.{c.get('object', '')}", "", sub))
    body.append(_svg._group("form_shadow.core", "", core_body))
    return body


# ---------------------------------------------------------------------------
# cast_shadow
# ---------------------------------------------------------------------------

def _umbra_group(doc: dict, cv) -> str:
    entries = [e["polygons"] for e in doc.get("umbra", []) or [] if e.get("polygons")]
    return _svg._group("cast_shadow.umbra", UMBRA_STYLE, cv.paths(entries) if entries else [])


def layer_cast_shadow(doc: dict, cv, hidden_style=None) -> list:
    """The ``cast_shadow`` layer body of a multi-light document (contract §5.3.6, §5.0.6): the
    single-light content with ``fill-opacity="<0.3/N_act>"`` on every ``cast_shadow.<light>`` group,
    then ``cast_shadow.umbra`` on top."""
    plain = _without(doc, "constructions")
    if hidden_style is None:
        body = _svg._layer_cast_shadow(plain, cv)
    else:
        body = _svg._layer_cast_shadow_hidden(plain, cv, hidden_style)
    attrs = _opacity(0.3, doc)
    heads = {f'<g id="{_svg._attr(f"cast_shadow.{lid}")}"': lid for lid in light_ids(doc)}
    out = []
    for item in body:
        head = item.split(">", 1)[0].removesuffix("/")
        if head in heads:
            item = f"{head} {attrs}{item[len(head):]}"
        out.append(item)
    out.append(_umbra_group(doc, cv))
    return out


# ---------------------------------------------------------------------------
# construction
# ---------------------------------------------------------------------------

def layer_construction(doc: dict, cv) -> list:
    """The ``construction`` layer body of a multi-light document (contract §5.3.6): one
    ``construction.<light>`` group per light (code-point order) holding the single-light markers of that
    light's construction block and its ``construction.<light>.LP`` / ``.FQ`` / ``.PQ`` groups."""
    body = []
    for lid in light_ids(doc):
        inner = _svg._layer_construction({"construction": doc["constructions"][lid],
                                          "receivers": doc.get("receivers")}, cv)
        renamed = []
        for item in inner:
            for kind in ("LP", "FQ", "PQ"):
                head = f'<g id="construction.{kind}"'
                if item.startswith(head):
                    item = f'<g id="{_svg._attr(f"construction.{lid}.{kind}")}"' + item[len(head):]
                    break
            renamed.append(item)
        body.append(_svg._group(f"construction.{lid}", "", renamed))
    return body

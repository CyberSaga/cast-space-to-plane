"""Umbra (本影) computation: one nonzero scanline kernel (contract §5.3.4, §5.3.7; M6).

The umbra of a receiver is the intersection of the *drawn* cast-shadow regions of the lights
active on it.  It is computed in stage B from the drawables ``shadows[].polygons`` alone (canvas
mm, exactly the numbers written in the document), so it is a pure function of
``shadows[].polygons``, ``umbra[].lights`` and ``canvas_mm`` and a port recomputes it from the
JSON (:func:`umbra_from_document`).

One kernel, :func:`scan_pieces`, does all the work: a slab decomposition with one nonzero winding
counter per group.  It is used per record (:func:`record_pieces`: one group, the record's loops)
and once per receiver (:func:`umbra_pieces`: one group per active light, the record pieces as
input).  Every piece it emits is a convex counter-clockwise trapezoid or triangle (``v`` up) with
an area above ``tol_area``; the pieces of one scan have pairwise disjoint interiors.

Numerics (contract §5.3.7): the only tolerances are :func:`tolerances` of ``canvas_mm``; every
predicate is ``>`` / ``<=`` against them or an exact comparison of snapped values; every sort is a
``(value, index)`` sort; every emitted float goes through ``+ 0.0``.  numpy only.
"""

from __future__ import annotations

import numpy as np

__all__ = ["tolerances", "scan_pieces", "record_pieces", "umbra_pieces", "umbra_from_document"]

#: Upper bound of the (slab, edge) entries processed at once (per winding counter): keeps every
#: temporary table of the slab loop well below 8 MB (contract §5.3.4 cost note).
_CHUNK_ENTRIES = 1 << 18
#: Upper bound of the candidate crossing pairs generated at once.
_CHUNK_PAIRS = 1 << 19

_EMPTY_SIDES = np.zeros((0, 2), dtype=np.int64)


def tolerances(canvas_mm) -> tuple:
    """``(tol_mm, tol_area)`` of contract §5.3.4: ``D = 1.5 · max(canvas_w, canvas_h)`` (the extent
    of the extended rectangle of §2.2), ``tol_mm = 1e-9 · D``, ``tol_area = 1e-9 · (D · D)``."""
    D = 1.5 * max(float(canvas_mm[0]), float(canvas_mm[1]))
    return 1e-9 * D, 1e-9 * (D * D)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def _greedy_merge(values: np.ndarray, tol: float) -> np.ndarray:
    """Kept values of the greedy merge of the ascending array ``values``: the first value is kept,
    each following value is kept iff it exceeds the last kept value by more than ``tol``.

    Vectorised: a gap ``> tol`` always starts a kept value; only a cluster of gaps ``<= tol`` whose
    total span exceeds ``tol`` needs the sequential rule (rare: a chain of near-coincident values)."""
    n = values.shape[0]
    if n == 0:
        return values
    keep = np.empty(n, dtype=bool)
    keep[0] = True
    keep[1:] = (values[1:] - values[:-1]) > tol
    starts = np.flatnonzero(keep)
    ends = np.append(starts[1:], n)
    span = values[ends - 1] - values[starts]
    for c in np.flatnonzero(span > tol):
        last = values[starts[c]]
        for t in range(int(starts[c]) + 1, int(ends[c])):
            if values[t] - last > tol:
                keep[t] = True
                last = values[t]
    return values[keep]


def _x_at(u0, v0, u1, v1, y):
    """``x(y) = u0 + (y − v0)·((u1 − u0)/(v1 − v0))`` with the exact-endpoint rule
    ``x(v0) = u0``, ``x(v1) = u1`` (contract §5.3.4 step 4).  Arrays of equal shape."""
    x = u0 + (y - v0) * ((u1 - u0) / (v1 - v0))
    x = np.where(y == v0, u0, x)
    return np.where(y == v1, u1, x)


def _ranges(starts: np.ndarray, counts: np.ndarray):
    """``(owner, value)`` for the concatenated integer ranges ``starts[i] + arange(counts[i])``."""
    total = int(counts.sum())
    owner = np.repeat(np.arange(starts.shape[0]), counts)
    offset = np.cumsum(counts) - counts
    value = np.arange(total, dtype=np.int64) - np.repeat(offset, counts) + np.repeat(starts, counts)
    return owner, value


# ---------------------------------------------------------------------------
# the kernel
# ---------------------------------------------------------------------------

def _edge_table(polygons, groups, lines, tol_mm):
    """Steps 1–2: vertex events, snapping and the edge table (input order, horizontal edges
    discarded).  Returns ``(kept, table)`` or ``(kept, None)`` when no edge remains."""
    polys, poly_groups, poly_lines = [], [], []
    for i, poly in enumerate(polygons):
        P = np.asarray(poly, dtype=float).reshape(-1, 2)
        if P.shape[0] < 3:
            continue
        polys.append(P)
        poly_groups.append(int(groups[i]))
        poly_lines.append(np.asarray(lines[i], dtype=np.int64).reshape(-1))
    if not polys:
        return np.zeros(0), None
    sizes = np.array([P.shape[0] for P in polys], dtype=np.int64)
    V = np.concatenate(polys, axis=0)
    kept = _greedy_merge(np.sort(V[:, 1]), tol_mm)
    snapped = kept[np.searchsorted(kept, V[:, 1], side="right") - 1]
    first = np.cumsum(sizes) - sizes                       # index of each polygon's vertex 0
    poly_of = np.repeat(np.arange(sizes.shape[0]), sizes)
    local = np.arange(V.shape[0], dtype=np.int64) - first[poly_of]
    nxt = first[poly_of] + (local + 1) % sizes[poly_of]
    u0, v0 = V[:, 0], snapped
    u1, v1 = V[nxt, 0], snapped[nxt]
    line = np.concatenate(poly_lines)
    group = np.repeat(np.array(poly_groups, dtype=np.int64), sizes)
    keep = v0 != v1
    table = {
        "u0": u0[keep], "v0": v0[keep], "u1": u1[keep], "v1": v1[keep],
        "dir": np.where(v1[keep] > v0[keep], 1, -1).astype(np.int64),
        "group": group[keep], "line": line[keep],
        "poly": poly_of[keep], "local": local[keep], "size": sizes[poly_of][keep],
    }
    if table["u0"].shape[0] == 0:
        return kept, None
    return kept, table


def _crossing_events(T: dict, kept: np.ndarray, tol_mm: float) -> np.ndarray:
    """Step 3: the merged crossing events (crossings within ``tol_mm`` of a vertex event dropped)."""
    u0, v0, u1, v1 = T["u0"], T["v0"], T["u1"], T["v1"]
    E = u0.shape[0]
    vmin, vmax = np.minimum(v0, v1), np.maximum(v0, v1)
    umin, umax = np.minimum(u0, u1), np.maximum(u0, u1)
    order = np.lexsort((np.arange(E), vmin))               # (vmin, index)
    vmin_s, vmax_s = vmin[order], vmax[order]
    pos = np.arange(E, dtype=np.int64)
    hi = np.searchsorted(vmin_s, vmax_s, side="right")
    counts = np.maximum(hi - (pos + 1), 0)
    csum = np.cumsum(counts)
    found = []
    start = 0
    while start < E:
        base = csum[start - 1] if start > 0 else 0
        stop = int(np.searchsorted(csum, base + _CHUNK_PAIRS, side="right"))
        stop = max(stop, start + 1)
        owner, q = _ranges(pos[start:stop] + 1, counts[start:stop])
        p = owner + start
        a, b = order[p], order[q]
        i, j = np.minimum(a, b), np.maximum(a, b)
        ok = (umin[i] <= umax[j]) & (umin[j] <= umax[i])
        same = T["poly"][i] == T["poly"][j]
        n = T["size"][i]
        dl = (T["local"][j] - T["local"][i]) % n
        ok &= ~(same & ((dl == 1) | (dl == n - 1)))
        i, j = i[ok], j[ok]
        ru, rv = u1[i] - u0[i], v1[i] - v0[i]
        su, sv = u1[j] - u0[j], v1[j] - v0[j]
        den = ru * sv - rv * su
        nz = den != 0.0
        i, ru, rv, su, sv, den = i[nz], ru[nz], rv[nz], su[nz], sv[nz], den[nz]
        j = j[nz]
        qu, qv = u0[j] - u0[i], v0[j] - v0[i]
        t = (qu * sv - qv * su) / den
        s = (qu * rv - qv * ru) / den
        hit = (t >= 0.0) & (t <= 1.0) & (s >= 0.0) & (s <= 1.0)
        found.append(v0[i][hit] + t[hit] * (v1[i][hit] - v0[i][hit]))
        start = stop
    if not found:
        return np.zeros(0)
    vx = np.concatenate(found)
    if vx.shape[0] == 0:
        return vx
    k = np.searchsorted(kept, vx)
    near = np.zeros(vx.shape[0], dtype=bool)
    lo = k > 0
    near[lo] = np.abs(vx[lo] - kept[k[lo] - 1]) <= tol_mm
    up = k < kept.shape[0]
    near[up] |= np.abs(kept[k[up]] - vx[up]) <= tol_mm
    return _greedy_merge(np.sort(vx[~near]), tol_mm)


def _raw_pieces(T: dict, ev: np.ndarray, n_groups: int, tol_mm: float):
    """Steps 4–5: per slab, the runs of inside intervals, clamped; returns the raw piece arrays
    in (slab, k0) order."""
    u0, v0, u1, v1 = T["u0"], T["v0"], T["u1"], T["v1"]
    E = u0.shape[0]
    n_slabs = ev.shape[0] - 1
    ym = (ev[:-1] + ev[1:]) / 2.0
    s_lo = np.searchsorted(ev, np.minimum(v0, v1))
    s_hi = np.searchsorted(ev, np.maximum(v0, v1))
    delta = np.zeros(n_slabs + 1, dtype=np.int64)
    np.add.at(delta, s_lo, 1)
    np.add.at(delta, s_hi, -1)
    per_slab = np.cumsum(delta)[:n_slabs]
    cum = np.cumsum(per_slab)
    out = {k: [] for k in ("slab", "el", "er", "lo_a", "hi_a", "lo_b", "hi_b")}
    eidx = np.arange(E, dtype=np.int64)
    c0 = 0
    while c0 < n_slabs:
        base = cum[c0 - 1] if c0 > 0 else 0
        c1 = int(np.searchsorted(cum, base + _CHUNK_ENTRIES, side="right"))
        c1 = min(max(c1, c0 + 1), n_slabs)
        sel = eidx[(s_lo < c1) & (s_hi > c0)]
        if sel.shape[0]:
            a_s = np.maximum(s_lo[sel], c0)
            cnt = np.minimum(s_hi[sel], c1) - a_s
            owner, es = _ranges(a_s, cnt)
            ee = sel[owner]
            y = ym[es]
            act = (v0[ee] - y) * (v1[ee] - y) < 0.0
            es, ee, y = es[act], ee[act], y[act]
            xm = _x_at(u0[ee], v0[ee], u1[ee], v1[ee], y)
            o = np.lexsort((ee, xm, es))
            es, ee = es[o], ee[o]
            m = es.shape[0]
            if m >= 2:
                first = np.ones(m, dtype=bool)
                first[1:] = es[1:] != es[:-1]
                start_of = np.maximum.accumulate(np.where(first, np.arange(m), 0))
                inside = np.ones(m, dtype=bool)
                d = T["dir"][ee]
                g = T["group"][ee]
                for grp in range(n_groups):
                    x = np.where(g == grp, d, 0)
                    w = np.cumsum(x)
                    prev = w - x
                    inside &= (w - prev[start_of]) != 0
                valid = np.zeros(m, dtype=bool)
                valid[:-1] = es[1:] == es[:-1]
                ins = inside & valid
                prev_ins = np.zeros(m, dtype=bool)
                prev_ins[1:] = ins[:-1]
                next_ins = np.zeros(m, dtype=bool)
                next_ins[:-1] = ins[1:]
                k0 = np.flatnonzero(ins & ~prev_ins)
                k1 = np.flatnonzero(ins & ~next_ins)
                if k0.shape[0]:
                    el, er = ee[k0], ee[k1 + 1]
                    sl = es[k0]
                    a, b = ev[sl], ev[sl + 1]
                    xla = _x_at(u0[el], v0[el], u1[el], v1[el], a)
                    xra = _x_at(u0[er], v0[er], u1[er], v1[er], a)
                    xlb = _x_at(u0[el], v0[el], u1[el], v1[el], b)
                    xrb = _x_at(u0[er], v0[er], u1[er], v1[er], b)
                    lo_a, hi_a = np.minimum(xla, xra), np.maximum(xla, xra)
                    lo_b, hi_b = np.minimum(xlb, xrb), np.maximum(xlb, xrb)
                    keep = ~((hi_a - lo_a <= tol_mm) & (hi_b - lo_b <= tol_mm))
                    for key, val in (("slab", sl), ("el", el), ("er", er), ("lo_a", lo_a), ("hi_a", hi_a),
                                     ("lo_b", lo_b), ("hi_b", hi_b)):
                        out[key].append(val[keep])
        c0 = c1
    if not out["slab"]:
        return None
    raw = {k: np.concatenate(v) for k, v in out.items()}
    return raw if raw["slab"].shape[0] else None


def _merge_runs(raw: dict, line: np.ndarray):
    """Step 6: a raw piece of slab ``s + 1`` with the ordered key ``(line left, line right)`` of a
    raw piece of slab ``s`` extends that piece's merged piece.  Equal keys inside one slab (not
    expected) are paired in order.  Returns ``(root, last)``: per merged piece (ordered by its first
    raw piece) the indices of its first and last raw piece."""
    n = raw["slab"].shape[0]
    ll, lr = line[raw["el"]], line[raw["er"]]
    _, pid = np.unique(np.stack([ll, lr], axis=1), axis=0, return_inverse=True)
    pid = pid.reshape(-1).astype(np.int64)
    n_pairs = int(pid.max()) + 1
    key = raw["slab"].astype(np.int64) * n_pairs + pid
    order = np.lexsort((np.arange(n), key))
    ks = key[order]
    firstpos = np.searchsorted(ks, ks, side="left")
    rank = np.empty(n, dtype=np.int64)
    rank[order] = np.arange(n) - firstpos
    mult = int(rank.max()) + 1
    key2 = key * mult + rank
    order2 = np.argsort(key2, kind="stable")
    k2s = key2[order2]
    query = (key - n_pairs) * mult + rank                       # same pair, slab − 1, same rank
    pos = np.searchsorted(k2s, query)
    pos_c = np.minimum(pos, n - 1)
    match = (pos < n) & (k2s[pos_c] == query) & (raw["slab"] > 0)
    pred = np.where(match, order2[pos_c], np.arange(n))
    root = pred.copy()
    while True:
        nxt = root[root]
        if np.array_equal(nxt, root):
            break
        root = nxt
    roots = np.flatnonzero(root == np.arange(n))
    last = np.full(n, -1, dtype=np.int64)
    np.maximum.at(last, root, np.arange(n))
    return roots, last[roots]


def scan_pieces(polygons, groups, lines, n_groups, tol_mm, tol_area):
    """Nonzero scanline decomposition with one winding counter per group (contract §5.3.4).

    ``polygons[i]`` is an ``(n_i, 2)`` array of ``[u, v]`` vertices, ``groups[i]`` its group
    (``0 .. n_groups − 1``), ``lines[i]`` an ``(n_i,)`` int array of the line ids of its edges
    (edge ``e`` runs from vertex ``e`` to vertex ``(e + 1) mod n_i``); polygons with fewer than three
    vertices are ignored.  An interval of a slab is inside iff every group's winding number is
    nonzero.  Returns ``(pieces, sides)``: ``pieces`` a list of ``(m, 2)`` float arrays (convex, CCW
    in the ``v``-up frame, ``m`` = 3 or 4, area ``> tol_area``, rotated to the canonical start),
    ``sides`` an ``(len(pieces), 2)`` int array ``(line_left, line_right)``."""
    kept, T = _edge_table(polygons, groups, lines, tol_mm)
    if T is None:
        return [], _EMPTY_SIDES.copy()
    cross = _crossing_events(T, kept, tol_mm)
    ev = np.sort(np.concatenate([kept, cross])) if cross.shape[0] else kept
    if ev.shape[0] < 2:
        return [], _EMPTY_SIDES.copy()
    raw = _raw_pieces(T, ev, int(n_groups), tol_mm)
    if raw is None:
        return [], _EMPTY_SIDES.copy()
    roots, lasts = _merge_runs(raw, T["line"])
    # step 7: output vertices (x_lo, a), (x_hi, a) iff wide, (x_hi', b), (x_lo', b) iff wide
    a = ev[raw["slab"][roots]]
    b = ev[raw["slab"][lasts] + 1]
    U = np.stack([raw["lo_a"][roots], raw["hi_a"][roots], raw["hi_b"][lasts], raw["lo_b"][lasts]], axis=1)
    Vv = np.stack([a, a, b, b], axis=1)
    has = np.ones(U.shape, dtype=bool)
    has[:, 1] = U[:, 1] - U[:, 0] > tol_mm
    has[:, 3] = U[:, 2] - U[:, 3] > tol_mm
    nv = has.sum(axis=1)
    # shoelace over the emitted vertices: an omitted slot repeats the previous vertex (exact zero term)
    Uf, Vf = U.copy(), Vv.copy()
    Uf[:, 1] = np.where(has[:, 1], U[:, 1], U[:, 0])
    Vf[:, 1] = np.where(has[:, 1], Vv[:, 1], Vv[:, 0])
    Uf[:, 3] = np.where(has[:, 3], U[:, 3], U[:, 2])
    Vf[:, 3] = np.where(has[:, 3], Vv[:, 3], Vv[:, 2])
    area = 0.0 * Uf[:, 0]
    for k in range(4):
        k1 = (k + 1) % 4
        area = area + (Uf[:, k] * Vf[:, k1] - Uf[:, k1] * Vf[:, k])
    area = 0.5 * area
    ok = (nv >= 3) & (area > tol_area)
    # canonical start: v <= v_min + tol, then the smallest u (ties within tol: lowest index)
    vm = np.where(has, Vv, np.inf).min(axis=1)
    cand = has & (Vv <= vm[:, None] + tol_mm)
    um = np.where(cand, U, np.inf).min(axis=1)
    cand &= U <= um[:, None] + tol_mm
    start_slot = np.argmax(cand, axis=1)
    sides_all = np.stack([T["line"][raw["el"][roots]], T["line"][raw["er"][roots]]], axis=1)
    pieces, keep_idx = [], []
    for p in np.flatnonzero(ok):
        slots = np.flatnonzero(has[p])
        r = int(np.searchsorted(slots, start_slot[p]))
        slots = np.concatenate([slots[r:], slots[:r]])
        pieces.append(np.stack([U[p, slots] + 0.0, Vv[p, slots] + 0.0], axis=1))
        keep_idx.append(p)
    if not pieces:
        return [], _EMPTY_SIDES.copy()
    return pieces, sides_all[np.array(keep_idx, dtype=np.int64)].astype(np.int64)


def record_pieces(polygons, tol_mm, tol_area):
    """:func:`scan_pieces` of one record's loops (``shadows[].polygons``) with a single group and
    line ids = the running edge index over the record's loops (contract §5.3.4): the nonzero
    decomposition of the record's drawn region (holes are reversed loops)."""
    polys, lines = [], []
    offset = 0
    for poly in polygons:
        P = np.asarray(poly, dtype=float).reshape(-1, 2)
        polys.append(P)
        lines.append(np.arange(offset, offset + P.shape[0], dtype=np.int64))
        offset += P.shape[0]
    return scan_pieces(polys, [0] * len(polys), lines, 1, tol_mm, tol_area)


def _piece_lines(piece: np.ndarray, side, base: int) -> np.ndarray:
    """Line ids of a record piece's edges in the intersection scan: an upward edge carries the
    piece's right line, a downward edge its left line, a horizontal edge ``−1``."""
    v = piece[:, 1]
    vn = np.roll(v, -1)
    return np.where(vn > v, base + int(side[1]), np.where(vn < v, base + int(side[0]), -1)).astype(np.int64)


def umbra_pieces(per_light, canvas_mm) -> list:
    """The umbra pieces of one receiver (contract §5.3.4): ``per_light[k]`` is the list of the
    records' drawables (``shadows[].polygons``, one list of polygons per record, ``shadows[]``
    order) of the ``k``-th active light (scene order).  With fewer than two active lights the
    result is ``[]``.  Each record is decomposed by :func:`record_pieces`; all record pieces enter
    one intersection scan with one group per light.  Returns a list of pieces, each a list of
    ``[u, v]`` canonical floats (CCW, canonical start)."""
    if len(per_light) < 2:
        return []
    tol_mm, tol_area = tolerances(canvas_mm)
    polys, groups, lines = [], [], []
    base = 0
    for k, records in enumerate(per_light):
        for rec in records:
            pieces, sides = record_pieces(rec, tol_mm, tol_area)
            for piece, side in zip(pieces, sides):
                polys.append(piece)
                groups.append(k)
                lines.append(_piece_lines(piece, side, base))
            base += sum(np.asarray(p, dtype=float).reshape(-1, 2).shape[0] for p in rec)
    pieces, _ = scan_pieces(polys, groups, lines, len(per_light), tol_mm, tol_area)
    return [[[float(x) + 0.0, float(y) + 0.0] for x, y in piece.tolist()] for piece in pieces]


def umbra_from_document(doc: dict) -> list:
    """Recompute every ``umbra[]`` entry of a multi-light document from ``shadows[]``,
    ``umbra[].lights`` and ``canvas_mm`` (contract §5.3.5 (c), §5.3.9); ``[]`` for a document
    without the key.  The polygons are always computed (also for an entry written with
    ``project_scene(..., umbra=False)``); for a computed document the result equals
    ``doc["umbra"]`` bit for bit."""
    if "umbra" not in doc:
        return []
    out = []
    for entry in doc["umbra"]:
        rid = entry["receiver"]
        per_light = [[sh["polygons"] for sh in doc["shadows"] if sh["receiver"] == rid and sh["light"] == lid]
                     for lid in entry["lights"]]
        out.append({"receiver": rid, "lights": list(entry["lights"]),
                    "polygons": umbra_pieces(per_light, doc["canvas_mm"])})
    return out

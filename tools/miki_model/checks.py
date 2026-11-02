"""Clearance / poke-through and proportion checks of the Miki model (milestone 1: the rest pose).

    python -m tools.miki_model.checks [--report-only] [--out PATH]

Builds the model with :func:`assemble.assemble` and checks the rounded, exported geometry of every part
(``Assembly.parts``, ``assemble.DECIMALS``; never the builders' float output) against the acceptance profile
(:mod:`acceptance`).  Every part pair (across objects and inside one object) falls under one relation:

* **join** (a profile requirement): every segment of the two parts' intersection curve, and every coincident
  patch, lies inside the declared zone dilated by eps; the buried rim stays under the host's surface by the
  declared depth; and no shell of either part is wholly inside the other;
* **generic** (every other pair): any triangle-triangle crossing, coincident patch or containment (a vertex of
  one part inside the other, winding test, both directions) is a FAIL.  Contacts within eps are not
  penetrations: they are counted and located, and pass.

``clear`` requirements measure gaps on selected faces, ``proportion`` requirements compare lofted parts with
their profile tables, ``pose`` requirements are milestone 2 stubs.

**Degenerate-intersection policy.**  ``eps = max(weld tolerance, sqrt(3) / 2 * 10**-DECIMALS)``, the rounding
error of the exported grid (8.7 um).  Triangle pairs are classified by :func:`meshkit.triangle_intersections`
(crossing / contact / coincident).  A verdict must not depend on eps: every requirement is evaluated at eps / 10,
eps and 10 eps, and when the three verdicts differ it is INDETERMINATE (``tolerance-sensitive``), with the
triangle pairs whose vertex distances fall in the near band.  Containment and the rim depth run independently of
the segment classifier (the volume cross-check), and a FAIL from either stands.  The winding test does not trust a
vertex within the contact tolerance ``max(1e-6, weld tolerance)`` of the other surface.

Every requirement ends PASS, FAIL or INDETERMINATE (missing measurement, invalid geometry, a pose not tested,
tolerance-sensitive); INDETERMINATE never passes.  The JSON report (sorted keys, deterministic) records the profile
and geometry versions, measured and required values with units, part, face / vertex indices and XYZ, and the
relation applied.  Exit status 0 only when every ``required`` requirement passes (``--report-only``: always 0).
Bounding boxes only order and screen the work; a pair named by the profile is always tested.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import sys
from dataclasses import dataclass, field

import numpy as np

from . import acceptance as ac
from . import assemble as asm
from . import meshkit as mk
from .rig import Rig

__all__ = ["WELD_TOLERANCE", "policy_eps", "contact_tolerance", "PartGeom", "Checker", "run", "main",
           "PASS", "FAIL", "INDETERMINATE"]

PASS, FAIL, INDETERMINATE = "PASS", "FAIL", "INDETERMINATE"
#: castplane's default mesh weld tolerance (``castplane.scene.MESH_WELD_TOLERANCE_DEFAULT``; the Miki scene sets
#: none).  Read from castplane when it is importable, so the two cannot drift.
try:                                                                  # pragma: no cover - depends on the env
    from castplane.scene import MESH_WELD_TOLERANCE_DEFAULT as WELD_TOLERANCE
except Exception:                                                     # pragma: no cover
    WELD_TOLERANCE = 1e-6
#: The three tolerances every verdict is evaluated at (fractions of eps).
EPS_SCALES = (0.1, 1.0, 10.0)
#: The requirement kinds whose verdict rests on the triangle classification and the containment threshold (eps
#: re-run); clearances and proportions compare a measurement with the fixed rounding tolerance 2 eps instead.
STABILITY_KINDS = ("join", "generic")
#: Facets meeting at more than this angle are a crease, not a tessellated smooth surface (castplane's default
#: ``smooth_angle_deg``); the facet bulge allowance of a join's rim depth does not reach across one.
SMOOTH_ANGLE_DEG = 30.0
#: At most this many findings per requirement in the report (the worst first).
MAX_FINDINGS = 12


def policy_eps(decimals: int = asm.DECIMALS, weld: float = WELD_TOLERANCE) -> float:
    """The policy's eps: the larger of the weld tolerance and the rounding error of the exported grid."""
    return max(float(weld), 0.5 * math.sqrt(3.0) * 10.0 ** (-decimals))


def contact_tolerance(weld: float = WELD_TOLERANCE) -> float:
    """Below this distance from a surface the winding sign of a point is not trusted."""
    return max(1e-6, float(weld))


def _f(x) -> float:
    """A JSON float: finite, rounded to 1e-9 (sub-nanometre) so that the report is stable, ``-0.0`` -> ``0.0``."""
    x = float(x)
    if not math.isfinite(x):
        return None
    return round(x, 9) + 0.0


def _xyz(p) -> list:
    return [_f(v) for v in p]


# ---------------------------------------------------------------------------------------------------------------
# geometry of one part
# ---------------------------------------------------------------------------------------------------------------

class PartGeom:
    """Read-only arrays of one part: vertices, fan triangles, face normals / centroids / sizes, vertex normals."""

    def __init__(self, name: str, obj: str, mesh: mk.Mesh):
        self.name, self.obj, self.mesh = name, obj, mesh
        self.V = np.asarray(mesh.vertices, dtype=np.float64)
        self.tris, self.tri_face = mk.triangulate(mesh.faces)
        self.normal, self.area = mk.face_normals(mesh)
        self.centroid = np.array([self.V[f].mean(axis=0) for f in mesh.faces])
        self.sides = np.array([len(f) for f in mesh.faces])
        self.groups = np.array(mesh.groups)
        self.lo, self.hi = self.V.min(axis=0), self.V.max(axis=0)
        self.vl, _fl, self.n_shells = mk._shell_labels(len(self.V), mesh.faces)
        self._bulge = None

    def bulge(self) -> np.ndarray:
        """Per triangle, the largest edge-midpoint distance between the facet and the smooth surface through its
        vertices: ``|(p_j - p_i) . (n_i - n_j)| / 8`` with the triangle's own vertex normals (exactly
        ``r (1 - cos(pi / n))`` on a regular n-gon of radius r) -- how far the faceted mesh may lie inside the
        analytic surface it was built on.  A corner's normal averages only the incident triangles within
        :data:`SMOOTH_ANGLE_DEG` of the triangle (castplane's smoothing angle): across a crease there is no smooth
        surface to bulge to."""
        if self._bulge is None:
            A, B, C = (self.V[self.tris[:, k]] for k in range(3))
            tn = np.cross(B - A, C - A)
            un = tn / np.maximum(np.linalg.norm(tn, axis=1), 1e-300)[:, None]
            inc = [[] for _ in range(len(self.V))]
            for t, tri in enumerate(self.tris):
                for v in tri:
                    inc[int(v)].append(t)
            cos_max = math.cos(math.radians(SMOOTH_ANGLE_DEG))
            N = np.zeros((len(self.tris), 3, 3))
            for t, tri in enumerate(self.tris):
                for k, v in enumerate(tri):
                    nb = np.array(inc[int(v)], dtype=np.int64)
                    nb = nb[un[nb] @ un[t] >= cos_max]
                    n = tn[nb].sum(axis=0)
                    N[t, k] = n / max(float(np.linalg.norm(n)), 1e-300)
            P = self.V[self.tris]
            b = np.zeros(len(self.tris))
            for i, j in ((0, 1), (1, 2), (2, 0)):
                b = np.maximum(b, np.abs(np.einsum("ti,ti->t", P[:, j] - P[:, i], N[:, i] - N[:, j])) / 8.0)
            self._bulge = b
        return self._bulge

    def select(self, sel: ac.Select, eps: float) -> np.ndarray:
        """Boolean face mask of :class:`acceptance.Select` ``sel``."""
        m = np.ones(self.mesh.n_faces, dtype=bool)
        if sel.groups is not None:
            m &= np.isin(self.groups, np.asarray(sel.groups))
        if sel.facing is not None:
            d = np.asarray(sel.facing[0], dtype=np.float64)
            m &= self.normal @ (d / np.linalg.norm(d)) >= sel.facing[1]
        for point, sign in ((sel.outward_from, 1.0), (sel.inward_from, -1.0)):
            if point is not None:
                r = self.centroid - np.asarray(point, dtype=np.float64)
                r /= np.maximum(np.linalg.norm(r, axis=1), 1e-300)[:, None]
                m &= sign * np.einsum("fi,fi->f", self.normal, r) > sel.radial_cos
        for axis, rng in ((2, sel.z), (1, sel.y), (0, sel.x)):
            if rng is not None:
                m &= (self.centroid[:, axis] >= rng[0] - eps) & (self.centroid[:, axis] <= rng[1] + eps)
        if sel.min_sides is not None:
            m &= self.sides >= sel.min_sides
        return ~m if sel.invert else m

    def select_with_host(self, sel: ac.Select, eps: float, host) -> np.ndarray:
        """:meth:`select` plus the ``host_cos`` criterion against ``host`` (a :class:`PartGeom`)."""
        if sel.host_cos is None:
            return self.select(sel, eps)
        base = dataclasses.replace(sel, host_cos=None, invert=False)
        m = self.select(base, eps)
        _d, t, _q = mk.point_triangle_distance(self.centroid, host.V, host.tris)
        m &= np.einsum("fi,fi->f", self.normal, host.normal[host.tri_face[t]]) >= sel.host_cos[1]
        return ~m if sel.invert else m

    def tris_of(self, face_mask) -> np.ndarray:
        """Indices of the fan triangles of the faces in ``face_mask``."""
        return np.nonzero(np.asarray(face_mask)[self.tri_face])[0]

    def rim(self, mask, sel: ac.Select, eps: float) -> np.ndarray:
        """Vertex indices of the faces in ``mask`` (``sel.vz`` filters them by z, ``sel.only`` drops the vertices an
        unselected face also uses), ascending."""
        faces = np.nonzero(mask)[0]
        idx = set(int(i) for k in faces for i in self.mesh.faces[k])
        if sel.only:
            idx -= set(int(i) for k in np.nonzero(~np.asarray(mask))[0] for i in self.mesh.faces[k])
        idx = sorted(idx)
        idx = np.array(idx, dtype=np.int64)
        if sel.vz is not None and len(idx):
            z = self.V[idx, 2]
            idx = idx[(z >= sel.vz[0] - eps) & (z <= sel.vz[1] + eps)]
        if sel.farthest is not None and len(idx) > sel.farthest:
            X = self.V[idx]
            r = np.linalg.norm(X - X.mean(axis=0), axis=1)
            idx = np.sort(idx[np.argsort(-r, kind="stable")[:sel.farthest]])
        return idx

    def submesh(self, face_mask) -> mk.Mesh:
        """The faces in ``face_mask`` as a mesh over the same vertices (an open patch; for ray casts)."""
        faces = [f for f, keep in zip(self.mesh.faces, face_mask) if keep]
        return mk.Mesh(self.V, faces, 0) if faces else mk.Mesh(self.V, [], 0)


def _boxes_touch(a: PartGeom, b: PartGeom, pad: float) -> bool:
    return bool(np.all(a.lo - pad <= b.hi) and np.all(b.lo - pad <= a.hi))


@dataclass
class PairData:
    """Everything eps-independent about one part pair: the candidate triangle pairs (bbox screen with the largest
    eps) and, for every vertex of each part inside the other's box, its winding number and exact distance."""

    a: PartGeom
    b: PartGeom
    cand: tuple = None
    sdepth_a: np.ndarray = None       # signed depth of a's vertices inside b (+ inside, - outside, nan: not tested)
    sdepth_b: np.ndarray = None
    near_a: np.ndarray = None         # a's vertex -> nearest triangle of b (or -1)
    near_b: np.ndarray = None
    by_eps: dict = field(default_factory=dict)


def _signed_depths(P: PartGeom, Q: PartGeom, pad: float, ctol: float):
    """Signed depth of each vertex of ``P`` inside ``Q`` (exact distance to ``Q``, positive when the winding number
    says inside, 0 within the contact tolerance, ``nan`` outside ``Q``'s box) and its nearest triangle of ``Q``."""
    out = np.full(len(P.V), np.nan)
    near = np.full(len(P.V), -1, dtype=np.int64)
    m = np.all((P.V >= Q.lo - pad) & (P.V <= Q.hi + pad), axis=1)
    if m.any():
        X = P.V[m]
        w = mk.winding_numbers(X, Q.V, Q.tris)
        d, t, _ = mk.point_triangle_distance(X, Q.V, Q.tris)
        s = np.where(np.abs(w) > 0.5, d, -d)
        s = np.where(d <= ctol, 0.0, s)
        out[m] = s
        near[m] = t
    return out, near


# ---------------------------------------------------------------------------------------------------------------
# the checker
# ---------------------------------------------------------------------------------------------------------------

class Checker:
    """Evaluates the profile on a list of parts (``name -> PartGeom``)."""

    def __init__(self, parts: dict, eps: float | None = None, ctol: float | None = None, reports: dict | None = None):
        self.parts = parts
        self.eps = policy_eps() if eps is None else float(eps)
        self.ctol = contact_tolerance() if ctol is None else float(ctol)
        self.reports = reports or {}
        self._pairs = {}
        self._sub = {}

    def sel(self, name: str, sel: ac.Select, eps: float) -> np.ndarray:
        """Face mask of ``sel`` on part ``name`` (``host_cos`` resolved against its named part)."""
        P = self.parts[name]
        host = self.parts.get(sel.host_cos[0]) if sel.host_cos is not None else None
        return P.select_with_host(sel, eps, host) if host is not None else P.select(sel, eps)

    # -- pair data -------------------------------------------------------------------------------------------
    def pair(self, a: str, b: str) -> PairData:
        key = (a, b)
        if key not in self._pairs:
            A, B = self.parts[a], self.parts[b]
            pad = max(EPS_SCALES) * self.eps
            pd = PairData(A, B)
            pd.cand = mk.triangle_bbox_pairs(A.V, A.tris, B.V, B.tris, pad=pad)
            pd.sdepth_a, pd.near_a = _signed_depths(A, B, pad, self.ctol)
            pd.sdepth_b, pd.near_b = _signed_depths(B, A, pad, self.ctol)
            self._pairs[key] = pd
        return self._pairs[key]

    def classify(self, pd: PairData, eps: float) -> dict:
        if eps not in pd.by_eps:
            pd.by_eps[eps] = mk.triangle_intersections(pd.a.V, pd.a.tris, pd.b.V, pd.b.tris, eps, pairs=pd.cand)
        return pd.by_eps[eps]

    def _dist_to(self, name: str, face_mask, points) -> np.ndarray:
        P = self.parts[name]
        key = (name, face_mask.tobytes())
        tris = self._sub.get(key)
        if tris is None:
            tris = P.tris[P.tris_of(face_mask)]
            self._sub[key] = tris
        return mk.point_triangle_distance(points, P.V, tris)[0]

    # -- zones -----------------------------------------------------------------------------------------------
    def zone_contains(self, zone: ac.Zone, a: str, b: str, points, eps: float, owner: str | None):
        """Boolean mask of ``points`` inside ``zone`` (dilated by eps) for the join ``(a, b)``, or ``None`` when
        the zone cannot judge them (a faces zone on the other part for vertices of ``owner``)."""
        X = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        if zone.unconstrained:
            return np.ones(len(X), dtype=bool)
        if zone.any_of is not None:
            res = [self.zone_contains(z, a, b, X, eps, owner) for z in zone.any_of]
            res = [r for r in res if r is not None]
            if not res:
                return None
            out = np.zeros(len(X), dtype=bool)
            for r in res:
                out |= r
            return out
        m = np.ones(len(X), dtype=bool)
        for axis, rng in ((2, zone.z), (1, zone.y)):
            if rng is not None:
                m &= (X[:, axis] >= rng[0] - eps) & (X[:, axis] <= rng[1] + eps)
        if zone.faces is not None:
            side, sel = zone.faces
            if owner is not None and owner != side:
                return None
            name = a if side == "a" else b
            mask = self.sel(name, sel, eps)
            if len(X):
                m &= self._dist_to(name, mask, X) <= eps
        if zone.near is not None and len(X):
            P = self.parts[zone.near[0]]
            m &= mk.point_triangle_distance(X, P.V, P.tris)[0] <= zone.near[1] + eps
        if zone.inside is not None and len(X):
            P = self.parts[zone.inside]
            w = mk.winding_numbers(X, P.V, P.tris)
            d = mk.point_triangle_distance(X, P.V, P.tris)[0]
            m &= (np.abs(w) > 0.5) | (d <= eps)
        return m

    # -- evaluators ------------------------------------------------------------------------------------------
    def eval_requirement(self, req, eps: float) -> dict:
        fn = {"join": self._join, "clear": self._clear, "proportion": self._proportion, "generic": self._generic,
              "pose": self._pose}[req.kind]
        return fn(req, eps)

    def _missing(self, names):
        bad = [n for n in names if n not in self.parts]
        if bad:
            return {"verdict": INDETERMINATE, "verdict_reason": "missing part(s): " + ", ".join(bad), "findings": []}
        invalid = [n for n in names if n in self.reports and not self.reports[n].ok]
        if invalid:
            return {"verdict": INDETERMINATE, "verdict_reason": "invalid geometry: " + ", ".join(invalid), "findings": []}
        return None

    def _curve(self, pd: PairData, eps: float):
        """Points of the intersection curve and coincident patches with their triangle pairs and kinds."""
        r = self.classify(pd, eps)
        pts, owners = [], []
        for k in range(len(r["kind"])):
            kind = int(r["kind"][k])
            if kind == mk.TT_CROSSING:
                for p in r["seg"][k]:
                    pts.append(p)
                    owners.append(k)
            elif kind == mk.TT_COINCIDENT:
                for p in r["polys"][k]:
                    pts.append(p)
                    owners.append(k)
        return r, np.array(pts).reshape(-1, 3), np.array(owners, dtype=np.int64)

    def _tri_finding(self, pd: PairData, r: dict, k: int, what: str, p=None) -> dict:
        ia, ib = int(r["ia"][k]), int(r["ib"][k])
        p = r["seg"][k].mean(axis=0) if p is None else p
        return {"what": what, "part": pd.a.name, "face": int(pd.a.tri_face[ia]), "other_part": pd.b.name,
                "other_face": int(pd.b.tri_face[ib]), "xyz": _xyz(p)}

    def _inside_findings(self, pd: PairData, eps: float, which: str, keep=None, what="vertex inside the other part"):
        s, P, Q = (pd.sdepth_a, pd.a, pd.b) if which == "a" else (pd.sdepth_b, pd.b, pd.a)
        m = np.nan_to_num(s, nan=-np.inf) > eps
        if keep is not None:
            m &= keep
        idx = np.nonzero(m)[0]
        idx = idx[np.argsort(-s[idx], kind="stable")]
        return idx, [{"what": what, "part": P.name, "vertex": int(i), "other_part": Q.name,
                      "depth": _f(s[i]), "xyz": _xyz(P.V[i])} for i in idx[:MAX_FINDINGS]]

    def _generic(self, req, eps: float) -> dict:
        miss = self._missing((req.a, req.b))
        if miss:
            return miss
        pd = self.pair(req.a, req.b)
        r = self.classify(pd, eps)
        k = r["kind"]
        n_cr, n_ct, n_co = int(np.sum(k == mk.TT_CROSSING)), int(np.sum(k == mk.TT_CONTACT)), \
            int(np.sum(k == mk.TT_COINCIDENT))
        ia_idx, fa = self._inside_findings(pd, eps, "a")
        ib_idx, fb = self._inside_findings(pd, eps, "b")
        findings = []
        for kk in np.nonzero(k == mk.TT_CROSSING)[0][:MAX_FINDINGS]:
            findings.append(self._tri_finding(pd, r, kk, "crossing"))
        for kk in np.nonzero(k == mk.TT_COINCIDENT)[0][:MAX_FINDINGS]:
            findings.append(self._tri_finding(pd, r, kk, "coincident"))
        findings += fa + fb
        depths = [v for v in (pd.sdepth_a, pd.sdepth_b) if v is not None]
        deep = max([float(np.nanmax(np.where(np.isnan(v), -np.inf, v))) for v in depths if len(v)] + [0.0])
        wholly = []
        for which, s, P in (("a", pd.sdepth_a, pd.a), ("b", pd.sdepth_b, pd.b)):
            for sh in range(P.n_shells):
                vs = s[P.vl == sh]
                if len(vs) and np.all(np.nan_to_num(vs, nan=-np.inf) > eps):
                    wholly.append({"what": "shell wholly inside the other part", "part": P.name, "shell": sh})
        findings += wholly
        bad = n_cr or n_co or len(ia_idx) or len(ib_idx)
        contacts = [self._tri_finding(pd, r, kk, "contact") for kk in np.nonzero(k == mk.TT_CONTACT)[0][:4]]
        return {"verdict": FAIL if bad else PASS, "findings": findings + contacts,
                "measured": {"crossings": n_cr, "contacts": n_ct, "coincident": n_co,
                             "vertices_inside": int(len(ia_idx) + len(ib_idx)),
                             "max_observed_depth": _f(deep)},
                "required": {"crossings": 0, "coincident": 0, "vertices_inside": 0}, "units": "m",
                "near_band": int(np.sum(r["near_band"]))}

    def _join(self, j: ac.Join, eps: float) -> dict:
        miss = self._missing((j.buried, j.host) + tuple(n for n, _ in j.stack) + tuple(j.also))
        if miss:
            return miss
        pd = self.pair(j.buried, j.host)
        r, pts, owners = self._curve(pd, eps)
        findings = []
        verdict = PASS
        inside = self.zone_contains(j.zone, j.buried, j.host, pts, eps, None) if len(pts) else np.ones(0, bool)
        leaks = np.nonzero(~inside)[0] if inside is not None else np.zeros(0, dtype=np.int64)
        seen = set()
        for i in leaks:
            kk = int(owners[i])
            if kk in seen:
                continue
            seen.add(kk)
            if len(seen) <= MAX_FINDINGS:
                findings.append(self._tri_finding(pd, r, kk, "intersection outside the zone (" +
                                                  mk.TT_KINDS[int(r["kind"][kk])] + ")", pts[i]))
        n_leak = len(seen)
        if n_leak:
            verdict = FAIL
        # volume cross-check (independent of the segment classifier): no shell of either part wholly inside the
        # other (one winding test per vertex, every shell, both directions), and the buried rim below (depth)
        n_wholly = 0
        for which, s, P in (("a", pd.sdepth_a, pd.a), ("b", pd.sdepth_b, pd.b)):
            for sh in range(P.n_shells):
                vs = s[P.vl == sh]
                if len(vs) and np.all(np.nan_to_num(vs, nan=-np.inf) > eps):
                    n_wholly += 1
                    verdict = FAIL
                    findings.append({"what": "shell wholly inside the other part", "part": P.name, "shell": sh})
        measured = {"intersection_points": int(len(pts)), "outside_zone": int(n_leak), "shells_wholly_inside": n_wholly}
        required = {"outside_zone": 0, "shells_wholly_inside": 0}
        # buried rim
        if j.rim is not None:
            A = self.parts[j.buried]
            rim = A.rim(self.sel(j.buried, j.rim, eps), j.rim, eps)
            if not len(rim):
                return {"verdict": INDETERMINATE, "verdict_reason": "rim selection is empty: " + (j.rim.note or "?"),
                        "findings": findings, "measured": measured, "required": required, "units": "m"}
            depth, req_d, allow = self._rim_depths(j, A, rim, eps)
            if np.all(np.isnan(depth)):
                return {"verdict": INDETERMINATE, "verdict_reason": "no rim depth could be measured (the rays miss the host)",
                        "findings": findings, "measured": measured, "required": required, "units": "m"}
            fail = np.nan_to_num(depth, nan=-np.inf) < req_d
            order = np.argsort(np.nan_to_num(depth - req_d, nan=-np.inf), kind="stable")
            k0 = int(order[0])
            measured.update({"rim_vertices": int(len(rim)), "rim_depth_min": _f(np.nanmin(depth)),
                             "rim_margin_min": _f(np.nan_to_num(depth - req_d, nan=-np.inf)[k0])})
            required.update({"rim_depth": _f(j.depth), "rim_depth_metric": j.depth_metric,
                             "rim_allowance_at_worst": _f(allow[k0])})
            if np.any(fail):
                verdict = FAIL
                for i in [i for i in order if fail[i]][:MAX_FINDINGS]:
                    findings.append({"what": "rim vertex not buried by the required depth", "part": j.buried,
                                     "vertex": int(rim[i]), "xyz": _xyz(A.V[rim[i]]), "depth": _f(depth[i]),
                                     "required": _f(req_d[i]), "allowance": _f(allow[i])})
        return {"verdict": verdict, "findings": findings, "measured": measured, "required": required, "units": "m",
                "near_band": int(np.sum(r["near_band"])), "zone": j.zone.note or ("unconstrained" if
                                                                                    j.zone.unconstrained else "")}

    def _rim_depths(self, j: ac.Join, A: PartGeom, rim, eps: float):
        X = A.V[rim]
        H = self.parts[j.host]
        if j.depth_metric == "along":
            D = np.tile(np.asarray(j.direction, dtype=np.float64), (len(X), 1))
            hs = [mk.surface_clearance(H.mesh, X, D)]
            for name, sel in j.stack:
                P = self.parts[name]
                hs.append(mk.surface_clearance(P.submesh(self.sel(name, sel, eps)), X, D))
            Hs = np.stack(hs, axis=0)
            depth = np.where(np.all(np.isnan(Hs), axis=0), np.nan, np.nanmax(np.where(np.isnan(Hs), -np.inf, Hs),
                                                                              axis=0))
            allow = np.full(len(X), 2.0 * self.eps)
            return depth, j.depth - allow, allow
        depth, allow = None, None
        for name in (j.host,) + tuple(j.also):
            Q = self.parts[name]
            w = mk.winding_numbers(X, Q.V, Q.tris)
            d, t, _ = mk.point_triangle_distance(X, Q.V, Q.tris)
            dq = np.where(np.abs(w) > 0.5, d, -d)
            dq = np.where(d <= self.ctol, 0.0, dq)
            aq = Q.bulge()[t] + 2.0 * self.eps
            if depth is None:
                depth, allow = dq, aq
            else:
                better = dq > depth
                depth, allow = np.where(better, dq, depth), np.where(better, aq, allow)
        req = np.maximum(eps, j.depth - allow) if j.depth > 0 else np.full(len(X), eps)
        return depth, req, allow

    def _clear(self, c: ac.Clear, eps: float) -> dict:
        miss = self._missing((c.a, c.b))
        if miss:
            return miss
        A, B = self.parts[c.a], self.parts[c.b]
        ma, mb = self.sel(c.a, c.faces_a, eps), self.sel(c.b, c.faces_b, eps)
        if not ma.any() or not mb.any():
            return {"verdict": INDETERMINATE, "verdict_reason": "empty face selection", "findings": []}
        findings = []
        ta = A.tris[A.tris_of(ma)]
        P = A.V[ta]
        pts = np.concatenate([A.V[np.unique(ta)], 0.5 * (P[:, 0] + P[:, 1]), 0.5 * (P[:, 1] + P[:, 2]),
                              0.5 * (P[:, 2] + P[:, 0])])
        if c.metric == "points":
            d, t, _q = mk.point_triangle_distance(pts, B.V, B.tris[B.tris_of(mb)])
            k0 = int(np.argmin(d))
            gmin, gmax, where, n = float(d[k0]), float(d.max()), pts[k0], int(len(pts))
            findings.append({"what": "smallest gap", "part": c.a, "other_part": c.b,
                             "other_face": int(B.tri_face[B.tris_of(mb)[t[k0]]]), "xyz": _xyz(where),
                             "gap": _f(gmin)})
        elif c.metric == "along":
            D = np.tile(np.asarray(c.direction, dtype=np.float64), (len(pts), 1))
            h = mk.surface_clearance(B.submesh(mb), pts, D)
            ok = ~np.isnan(h)
            if not ok.any():
                if c.need_overlap:
                    return {"verdict": INDETERMINATE, "verdict_reason": "no sample of the selected faces lies over the other "
                            "part", "findings": []}
                return {"verdict": PASS, "findings": [], "measured": {"samples_over": 0}, "units": "m",
                        "required": {"min": _f(c.min), "max": _f(c.max)}, "note": "no overlap"}
            gmin, gmax = float(h[ok].min()), float(h[ok].max())
            i_min = int(np.nonzero(ok)[0][np.argmin(h[ok])])
            where = pts[i_min]
            n = int(ok.sum())
            findings.append({"what": "smallest gap", "part": c.a, "xyz": _xyz(where), "gap": _f(gmin)})
        else:
            ta_idx, tb_idx = A.tris_of(ma), B.tris_of(mb)
            pad = (c.min if math.isfinite(c.min) else 0.0) + max(EPS_SCALES) * eps
            ia, ib = mk.triangle_bbox_pairs(A.V, A.tris[ta_idx], B.V, B.tris[tb_idx], pad=pad)
            if not len(ia):
                return {"verdict": PASS, "findings": [], "units": "m", "measured": {"min_gap_above": _f(pad)},
                        "required": {"min": _f(c.min), "max": _f(c.max)}}
            r = mk.triangle_intersections(A.V, A.tris[ta_idx], B.V, B.tris[tb_idx], eps, pairs=(ia, ib))
            d, pa, _pb = mk.triangle_pair_distance(A.V[A.tris[ta_idx[ia]]], B.V[B.tris[tb_idx[ib]]])
            hit = np.zeros(len(ia), dtype=bool)
            for k in np.nonzero(r["kind"] == mk.TT_CROSSING)[0]:
                hit |= (ia == r["ia"][k]) & (ib == r["ib"][k])
            d = np.where(hit, 0.0, d)
            k0 = int(np.argmin(d))
            gmin, gmax, where, n = float(d[k0]), float("nan"), pa[k0], int(len(ia))
            findings.append({"what": "closest approach", "part": c.a, "face": int(A.tri_face[ta_idx[ia[k0]]]),
                             "other_part": c.b, "other_face": int(B.tri_face[tb_idx[ib[k0]]]), "xyz": _xyz(where),
                             "gap": _f(gmin)})
        fail = gmin < c.min - 2.0 * eps or (math.isfinite(c.max) and gmax > c.max + 2.0 * eps)
        return {"verdict": FAIL if fail else PASS, "findings": findings, "units": "m",
                "measured": {"min": _f(gmin), "max": _f(gmax), "samples": n},
                "required": {"min": _f(c.min), "max": _f(c.max), "tolerance": _f(2.0 * eps), "metric": c.metric}}

    def _proportion(self, p: ac.Proportion, eps: float) -> dict:
        miss = self._missing((p.part,))
        if miss:
            return miss
        P = self.parts[p.part]
        findings, worst, rows_out = [], 0.0, []
        checks = []
        for k, row in enumerate(p.rows):
            checks.append((row, p.tol[k], "row"))
        for k in range(len(p.rows) - 1):
            r0, r1 = p.rows[k], p.rows[k + 1]
            mid = tuple(0.5 * (u + v) if (u is not None and v is not None) else None for u, v in zip(r0, r1))
            checks.append((mid, max(p.tol[k], p.tol[k + 1]), "between rows"))
        for (z, hw, yf, yb), tol, kind in checks:
            s = section_extents(P, z)
            if s is None:
                findings.append({"what": f"no section at z {z:.4f}", "part": p.part})
                worst = float("inf")
                continue
            meas = {"half_width_left": s[0], "half_width_right": s[1], "front_y": s[2], "back_y": s[3]}
            want = {"half_width_left": hw, "half_width_right": hw, "front_y": yf, "back_y": yb}
            row = {"z": _f(z), "kind": kind, "tolerance": _f(tol + 2.0 * eps)}
            for key, m in meas.items():
                w = want[key]
                row[key] = {"measured": _f(m), "required": _f(w) if w is not None else None}
                if w is None:
                    continue
                err = abs(m - w) - (tol + 2.0 * eps)
                worst = max(worst, err)
                if err > 0:
                    findings.append({"what": f"{key} off the table", "part": p.part, "z": _f(z), "kind": kind,
                                     "measured": _f(m), "required": _f(w), "tolerance": _f(tol + 2.0 * eps)})
            rows_out.append(row)
        return {"verdict": FAIL if worst > 0 else PASS, "findings": findings[:MAX_FINDINGS], "units": "m",
                "measured": {"rows": rows_out}, "required": {"table": p.constant}}

    def _pose(self, p: ac.Pose, eps: float) -> dict:
        return {"verdict": INDETERMINATE, "verdict_reason": f"pose not tested: {p.pose} (milestone 2)", "findings": []}


def section_extents(P: PartGeom, z: float):
    """``(half-width left (+x), half-width right (-x), front y (min), back y (max))`` of the horizontal section of
    part ``P`` at ``z`` (the triangle edges crossing the plane; vertices on it count), or ``None``."""
    T = P.V[P.tris]
    pts = []
    for i, j in ((0, 1), (1, 2), (2, 0)):
        a, b = T[:, i], T[:, j]
        da, db = a[:, 2] - z, b[:, 2] - z
        on = da == 0
        pts.append(a[on])
        cr = (da * db) < 0
        t = da[cr] / (da[cr] - db[cr])
        pts.append(a[cr] + t[:, None] * (b[cr] - a[cr]))
    X = np.concatenate(pts)
    if not len(X):
        return None
    return float(X[:, 0].max()), float(-X[:, 0].min()), float(X[:, 1].min()), float(X[:, 1].max())


@dataclass(frozen=True)
class Generic:
    """The relation of a part pair without a join (one per pair whose bounding boxes touch)."""

    name: str
    a: str
    b: str
    level: str = "required"
    kind: str = "generic"
    reason: str = "no declared relation: any intersection or containment is a poke-through"
    constant: str = ""


def _req_parts(req) -> tuple:
    if req.kind == "join":
        return (req.buried, req.host)
    if req.kind in ("clear", "generic"):
        return (req.a, req.b)
    if req.kind == "proportion":
        return (req.part,)
    return ()


def _describe(req) -> dict:
    d = {"name": req.name, "kind": req.kind, "level": req.level, "parts": list(_req_parts(req)),
         "constant": req.constant, "reason": req.reason}
    if req.kind == "join":
        d["relation"] = f"join: {req.buried} buried in {req.host}"
        d["zone"] = _zone_desc(req.zone)
        d["rim"] = req.rim.note if req.rim is not None else None
    elif req.kind == "clear":
        d["relation"] = f"clear: {req.a} faces ({req.faces_a.note}) vs {req.b} faces ({req.faces_b.note})"
    elif req.kind == "generic":
        d["relation"] = "everything else: no intersection, no containment"
    elif req.kind == "proportion":
        d["relation"] = "proportion: profile table"
    else:
        d["relation"] = "pose"
    return d


def _zone_desc(z: ac.Zone):
    if z.unconstrained:
        return {"unconstrained": True, "note": z.note}
    d = {"note": z.note}
    if z.z is not None:
        d["z"] = [_f(v) for v in z.z]
    if z.y is not None:
        d["y"] = [_f(v) for v in z.y]
    if z.faces is not None:
        d["faces"] = {"of": z.faces[0], "select": z.faces[1].note}
    if z.inside is not None:
        d["inside"] = z.inside
    if z.near is not None:
        d["near"] = {"part": z.near[0], "distance": _f(z.near[1])}
    if z.any_of is not None:
        d["any_of"] = [_zone_desc(s) for s in z.any_of]
    return d


def geometry_version(parts: dict) -> str:
    """SHA-256 (16 hex digits) of every part's name, rounded vertices and faces, in name order."""
    h = hashlib.sha256()
    for name in sorted(parts):
        P = parts[name]
        h.update(name.encode())
        h.update(np.ascontiguousarray(P.V).tobytes())
        h.update(json.dumps(P.mesh.faces).encode())
    return h.hexdigest()[:16]


def width_table(P: PartGeom, step: float) -> list:
    """Diagnostic: ``[z, half-width left, half-width right, front y, back y]`` every ``step`` over the part."""
    z0, z1 = float(P.lo[2]), float(P.hi[2])
    out = []
    n = int(math.floor((z1 - z0) / step))
    for k in range(1, n + 1):
        z = round(z0 + k * step, 6)
        if z >= z1:
            break
        s = section_extents(P, z)
        if s is not None:
            out.append([_f(z)] + [_f(v) for v in s])
    return out


def run(parts_list, profile=None, reports=None, eps=None, only=None) -> dict:
    """Evaluate ``profile`` (default :func:`acceptance.profile`) on ``parts_list`` (``Part`` objects with rounded
    meshes); ``only``: a set of part names -- evaluate only the requirements that read one of them.  Returns the
    report dict (see the module docstring)."""
    profile = ac.profile() if profile is None else list(profile)
    parts = {p.name: PartGeom(p.name, p.obj, p.mesh) for p in parts_list}
    chk = Checker(parts, eps=eps, reports=reports)
    eps0 = chk.eps
    joined = set()
    for r in profile:
        if r.kind == "join":
            joined.add(frozenset((r.buried, r.host)))
    names = [p.name for p in parts_list]
    pad = max(EPS_SCALES) * eps0
    generic, disjoint = [], 0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if frozenset((a, b)) in joined:
                continue
            if not _boxes_touch(parts[a], parts[b], pad):
                disjoint += 1
                continue
            generic.append(Generic(f"generic:{a}|{b}", a, b))
    reqs = list(profile) + generic
    if only is not None:
        reqs = [r for r in reqs if set(_req_parts(r)) & set(only)]
    results = []
    for req in reqs:
        per = {}
        scales = EPS_SCALES if req.kind in STABILITY_KINDS else (1.0,)
        for s in scales:
            per[s] = chk.eval_requirement(req, s * eps0)
        main_res = dict(per[1.0])
        verdicts = {s: per[s]["verdict"] for s in scales}
        if len(set(verdicts.values())) > 1:
            main_res["verdict"] = INDETERMINATE
            main_res["verdict_reason"] = "tolerance-sensitive: " + ", ".join(
                f"{s:g} eps -> {v}" for s, v in verdicts.items())
            main_res["tolerance_sensitive"] = _near_band_detail(chk, req, eps0)
        entry = _describe(req)
        entry.update(main_res)
        results.append(entry)
    results.sort(key=lambda e: e["name"])
    # the pair table: every pair with an intersection, a contact or a contained vertex at eps
    pairs, seen = [], set()
    for (a, b), pd in sorted(chk._pairs.items()):
        if frozenset((a, b)) in seen:
            continue
        seen.add(frozenset((a, b)))
        r = chk.classify(pd, eps0)
        k = r["kind"]
        ins_a = int(np.sum(np.nan_to_num(pd.sdepth_a, nan=-np.inf) > eps0))
        ins_b = int(np.sum(np.nan_to_num(pd.sdepth_b, nan=-np.inf) > eps0))
        n_cr, n_ct, n_co = (int(np.sum(k == x)) for x in (mk.TT_CROSSING, mk.TT_CONTACT, mk.TT_COINCIDENT))
        if not (n_cr or n_ct or n_co or ins_a or ins_b):
            continue
        rel = [e["name"] for e in results if set(e["parts"]) == {a, b}]
        deep = max([float(np.nanmax(np.where(np.isnan(v), -np.inf, v))) for v in (pd.sdepth_a, pd.sdepth_b)
                    if len(v)] + [0.0])
        seg = r["seg"][k == mk.TT_CROSSING].reshape(-1, 3)
        pairs.append({"a": a, "b": b, "crossings": n_cr, "contacts": n_ct, "coincident": n_co,
                      "a_vertices_inside_b": ins_a, "b_vertices_inside_a": ins_b, "max_observed_depth": _f(deep),
                      "near_band_triangle_pairs": int(np.sum(r["near_band"])),
                      "curve_bbox": [_xyz(seg.min(axis=0)), _xyz(seg.max(axis=0))] if len(seg) else None,
                      "requirements": rel,
                      "verdicts": sorted(set(e["verdict"] for e in results if e["name"] in rel))})
    counts = {}
    for e in results:
        c = counts.setdefault(e["kind"], {PASS: 0, FAIL: 0, INDETERMINATE: 0})
        c[e["verdict"]] += 1
    required_ok = all(e["verdict"] == PASS for e in results if e["level"] == "required")
    diag = {name: width_table(parts[name], ac.DIAGNOSTIC_STEP) for name in ac.DIAGNOSTIC_WIDTHS if name in parts}
    report = {
        "profile": {"name": ac.PROFILE_NAME, "version": ac.PROFILE_VERSION, "requirements": len(profile)},
        "geometry": {"version": geometry_version(parts), "decimals": asm.DECIMALS, "parts": len(parts),
                     "eps": float(eps0), "eps_scales": list(EPS_SCALES), "contact_tolerance": float(chk.ctol),
                     "weld_tolerance": float(WELD_TOLERANCE)},
        "summary": {"counts": counts, "required_pass": required_ok,
                    "intersecting_pairs": sum(1 for p in pairs if p["crossings"] or p["coincident"]
                                              or p["a_vertices_inside_b"] or p["b_vertices_inside_a"]),
                    "pairs_with_contacts": sum(1 for p in pairs if p["contacts"]),
                    "contacts": sum(p["contacts"] for p in pairs),
                    "pairs_with_coincident": sum(1 for p in pairs if p["coincident"]),
                    "coincident": sum(p["coincident"] for p in pairs),
                    "tolerance_sensitive": sum(1 for e in results if "tolerance_sensitive" in e),
                    "pairs_with_near_band": sum(1 for p in pairs if p["near_band_triangle_pairs"]),
                    "generic_pairs_disjoint_boxes": disjoint},
        "requirements": results,
        "pairs": pairs,
        "diagnostics": {"width_tables": {"step": _f(ac.DIAGNOSTIC_STEP),
                                         "columns": ["z", "half_width_left", "half_width_right", "front_y", "back_y"],
                                         "parts": diag}},
    }
    return report


def _near_band_detail(chk: Checker, req, eps: float) -> list:
    """The near-band triangle pairs of the requirement's part pair (indices and XYZ), for a tolerance-sensitive
    verdict."""
    names = _req_parts(req)
    if len(names) != 2 or names[0] not in chk.parts or names[1] not in chk.parts:
        return []
    pd = chk.pair(*names)
    r = chk.classify(pd, eps)
    out = []
    for k in np.nonzero(r["near_band"])[0][:MAX_FINDINGS]:
        out.append(chk._tri_finding(pd, r, int(k), "near-band triangle pair (" + mk.TT_KINDS[int(r["kind"][k])] + ")"))
    return out


def dumps(report: dict) -> str:
    return json.dumps(report, indent=1, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n"


def format_summary(report: dict) -> str:
    lines = [f"profile {report['profile']['name']} v{report['profile']['version']}, geometry "
             f"{report['geometry']['version']}, eps {report['geometry']['eps']:.3g} m"]
    for kind, c in sorted(report["summary"]["counts"].items()):
        lines.append(f"  {kind:10s} PASS {c[PASS]:4d}  FAIL {c[FAIL]:4d}  INDETERMINATE {c[INDETERMINATE]:4d}")
    s = report["summary"]
    lines.append(f"  intersecting part pairs {s['intersecting_pairs']}, contacts {s['contacts']} in "
                 f"{s['pairs_with_contacts']} pairs, coincident {s['coincident']} in {s['pairs_with_coincident']} "
                 f"pairs, tolerance-sensitive {s['tolerance_sensitive']}")
    for e in report["requirements"]:
        if e["verdict"] != PASS:
            tag = "" if e["level"] == "required" else " (advisory)"
            lines.append(f"{e['verdict']:13s} {e['name']}{tag}: {e.get('verdict_reason') or e['relation']}{_short(e)}")
    lines.append("required checks: " + ("all PASS" if s["required_pass"] else "NOT all PASS"))
    return "\n".join(lines)


def _short(e: dict) -> str:
    m = e.get("measured") or {}
    keys = ("max_observed_depth", "outside_zone", "shells_wholly_inside", "rim_depth_min", "min")
    bits = [f"{k} {m[k]}" for k in keys if k in m and m[k] not in (None, 0)]
    return (" [" + ", ".join(bits) + "]") if bits else ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.miki_model.checks", description=__doc__.split("\n\n")[0])
    ap.add_argument("--report-only", action="store_true", help="print everything, always exit 0")
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)
    model = asm.assemble(Rig(), strict=False)
    report = run(model.parts, reports=model.reports)
    report["exit"] = 0 if (args.report_only or report["summary"]["required_pass"]) else 1
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(dumps(report))
    print(format_summary(report))
    return report["exit"]


if __name__ == "__main__":
    sys.exit(main())

"""Parts -> the ten castplane mesh objects of the Miki model (fixed order), with validation and statistics.

Flow: :func:`build_parts` asks each part module (``head``, ``hair``, ``body``, ``limbs``) for its parts;
a module whose ``build(rig)`` returns ``None`` is replaced by the mannequin parts of its ``REGIONS``.
:func:`assemble` rounds every part to :data:`DECIMALS`, validates it (closed outward manifold shells, no
tiny faces, no vertex below the ground), merges the parts per material into the objects of
:data:`OBJECTS` (renumbering smooth groups per part so different parts never share a group id),
reorders vertices so castplane's nesting-parity test cannot flip an overlapping shell
(:func:`meshkit.fix_nesting`), validates each object again (duplicate vertices across parts) and
returns an :class:`Assembly` with the castplane object dicts and per-part / per-object statistics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import body, hair, head, limbs, mannequin
from . import meshkit as mk
from .rig import Rig

__all__ = ["OBJECTS", "OBJECT_IDS", "OBJECT_COLOURS", "MODULES", "ALL_REGIONS", "BUDGET", "DECIMALS",
           "SUN_TOWARDS", "Assembly", "AssemblyError", "build_parts", "assemble", "format_stats"]

#: The ten castplane objects in their fixed order, with the sRGB colour used for MTL / GLB / previews.
OBJECTS = (
    ("hair", "#b9c3e6"),
    ("skin", "#fbe3d6"),
    ("eyes", "#7fb3a8"),
    ("headband", "#f4dce8"),
    ("scarf", "#f6c453"),
    ("socks", "#f2f0f4"),
    ("uniform", "#e8667a"),
    ("collar", "#fafafa"),
    ("face_marks", "#6b3f45"),
    ("shoes", "#6b4a3a"),
)
OBJECT_IDS = tuple(oid for oid, _ in OBJECTS)
OBJECT_COLOURS = dict(OBJECTS)

#: Part modules in assembly order (each defines ``REGIONS`` and ``build(rig)``).
MODULES = (head, hair, body, limbs)
ALL_REGIONS = tuple(r for m in MODULES for r in m.REGIONS)

#: Web-UI budget (BRIEF §5): polygons = faces as written, triangles = castplane's fan triangulation.
BUDGET = {"polygons": 6000, "triangles": 10000}

#: Direction towards the scene's sun (viewer's upper left; normalised by the scene writer).
SUN_TOWARDS = (-0.45, -0.55, 0.70)

#: Coordinates are rounded to this many decimals (0.01 mm) before validation and writing.
DECIMALS = 5

assert set(mannequin.REGIONS) == set(ALL_REGIONS), "mannequin regions and module REGIONS disagree"


class AssemblyError(ValueError):
    """Invalid parts (the message lists every failing part / object)."""


@dataclass
class Assembly:
    """Result of :func:`assemble`."""

    rig: Rig
    parts: list                                   # Part list (rounded meshes), assembly order
    sources: dict                                 # region -> "head" / "hair" / ... / "mannequin"
    meshes: dict                                  # object id -> merged Mesh (fixed OBJECTS order)
    part_faces: dict                              # object id -> [(part name, first face, n faces)]
    reports: dict = field(default_factory=dict)   # part / object name -> ValidationReport
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.reports.values())

    def objects(self) -> list:
        """castplane mesh object dicts ``{"id", "type": "mesh", "data": {...}}`` in the fixed order."""
        out = []
        for oid, m in self.meshes.items():
            out.append({"id": oid, "type": "mesh", "data": {
                "vertices": [[float(x) + 0.0 for x in v] for v in m.vertices],
                "faces": [list(f) for f in m.faces],
                "smooth_groups": list(m.groups)}})
        return out


def _wanted(module, only):
    if only is None:
        return list(module.REGIONS)
    return [r for r in module.REGIONS if r in only]


def build_parts(rig: Rig, only=None):
    """``(parts, sources)``: the parts of every region (or of the regions in ``only``) and which module
    built each region.  ``only`` may also name a module (``head``, ``hair``, ``body``, ``limbs``)."""
    if only is not None:
        only = set(only)
        for m in MODULES:
            if m.__name__.rsplit(".", 1)[-1] in only:
                only |= set(m.REGIONS)
        unknown = sorted(only - set(ALL_REGIONS) - {m.__name__.rsplit(".", 1)[-1] for m in MODULES})
        if unknown:
            raise AssemblyError(f"unknown region(s) {unknown}; regions: {list(ALL_REGIONS)}")
    parts, sources = [], {}
    for module in MODULES:
        wanted = _wanted(module, only)
        if not wanted:
            continue
        name = module.__name__.rsplit(".", 1)[-1]
        built = module.build(rig)
        if built is None:
            parts.extend(mannequin.build(rig, wanted))
            sources.update({r: "mannequin" for r in wanted})
            continue
        for p in built:
            if not isinstance(p, mk.Part):
                raise AssemblyError(f"{name}.build returned a {type(p).__name__}, not a Part")
            if p.region and p.region not in module.REGIONS:
                raise AssemblyError(f"part {p.name!r} of {name}.py has region {p.region!r}, "
                                    f"not one of {module.REGIONS}")
            if not p.region or p.region in wanted:
                parts.append(p)
        sources.update({r: name for r in wanted})
    seen = set()
    for p in parts:
        if p.name in seen:
            raise AssemblyError(f"duplicate part name {p.name!r}")
        seen.add(p.name)
        if p.material not in OBJECT_COLOURS:
            raise AssemblyError(f"part {p.name!r} has unknown material {p.material!r}; one of {list(OBJECT_IDS)}")
    return parts, sources


def assemble(rig: Rig | None = None, only=None, strict: bool = True) -> Assembly:
    """Build, round, validate and merge the model.  ``strict`` raises :class:`AssemblyError` listing every
    invalid part / object; otherwise the reports are kept on the result (``Assembly.ok``)."""
    rig = Rig() if rig is None else rig
    raw, sources = build_parts(rig, only)
    parts, reports = [], {}
    for p in raw:
        m = p.mesh.rounded(DECIMALS)
        parts.append(mk.Part(p.name, p.material, m, p.region))
        reports[p.name] = mk.validate(m, p.name, check_nesting=False)   # nesting: per object, below
    meshes, part_faces = {}, {}
    for oid in OBJECT_IDS:
        group_parts = [p for p in parts if p.material == oid]
        if not group_parts:
            continue
        pieces, next_group, ranges, first = [], 1, [], 0
        for p in group_parts:
            local = sorted(set(g for g in p.mesh.groups if g != 0))
            remap = {g: next_group + k for k, g in enumerate(local)}
            next_group += len(local)
            pieces.append(p.mesh.with_groups(remap))
            ranges.append((p.name, first, p.mesh.n_faces))
            first += p.mesh.n_faces
        merged = mk.merge(pieces)
        try:
            merged = mk.fix_nesting(merged)
        except mk.MeshError as exc:
            reports[f"object {oid}"] = mk.ValidationReport(name=f"object {oid}", errors=[str(exc)])
        else:
            reports[f"object {oid}"] = mk.validate(merged, f"object {oid}")
        meshes[oid] = merged
        part_faces[oid] = ranges
    result = Assembly(rig, parts, sources, meshes, part_faces, reports)
    result.stats = _stats(result)
    if strict and not result.ok:
        bad = [r.summary() for r in reports.values() if not r.ok]
        raise AssemblyError("invalid model:\n" + "\n".join(bad))
    return result


def _stats(a: Assembly) -> dict:
    parts = []
    for p in a.parts:
        rep = a.reports.get(p.name)
        parts.append({"name": p.name, "material": p.material, "region": p.region,
                      "source": a.sources.get(p.region, ""), "vertices": p.mesh.n_vertices,
                      "polygons": p.mesh.n_faces, "triangles": p.mesh.n_triangles,
                      "shells": rep.n_shells if rep else 0,
                      "ray_vertices": len(mk.feature_silhouette_vertices(p.mesh, SUN_TOWARDS))})
    objects = []
    for oid, m in a.meshes.items():
        rep = a.reports.get(f"object {oid}")
        objects.append({"id": oid, "vertices": m.n_vertices, "polygons": m.n_faces, "triangles": m.n_triangles,
                        "shells": rep.n_shells if rep else 0, "groups": len(set(m.groups) - {0}),
                        "parts": len(a.part_faces[oid]),
                        "ray_vertices": len(mk.feature_silhouette_vertices(m, SUN_TOWARDS))})
    total = {k: sum(o[k] for o in objects) for k in ("vertices", "polygons", "triangles", "shells")}
    rays = mk.MAX_FEATURE_SILHOUETTE_VERTICES
    return {"parts": parts, "objects": objects, "total": total, "budget": dict(BUDGET, ray_vertices=rays),
            "within_budget": total["polygons"] <= BUDGET["polygons"] and total["triangles"] <= BUDGET["triangles"],
            "rays_ok": all(o["ray_vertices"] <= rays for o in objects)}


def format_stats(stats: dict, parts: bool = True) -> str:
    """Plain-text table of :func:`assemble` statistics (per part, per object, total vs budget)."""
    lines = []
    if parts:
        lines.append(f"{'part':34s} {'object':11s} {'source':10s} {'verts':>6s} {'polys':>6s} {'tris':>6s} "
                     f"{'shells':>6s} {'rays':>5s}")
        for p in stats["parts"]:
            lines.append(f"{p['name']:34s} {p['material']:11s} {p['source']:10s} {p['vertices']:6d} "
                         f"{p['polygons']:6d} {p['triangles']:6d} {p['shells']:6d} {p['ray_vertices']:5d}")
        lines.append("")
    lines.append(f"{'object':11s} {'parts':>5s} {'verts':>6s} {'polys':>6s} {'tris':>6s} {'shells':>6s} "
                 f"{'groups':>6s} {'rays':>5s}")
    for o in stats["objects"]:
        lines.append(f"{o['id']:11s} {o['parts']:5d} {o['vertices']:6d} {o['polygons']:6d} {o['triangles']:6d} "
                     f"{o['shells']:6d} {o['groups']:6d} {o['ray_vertices']:5d}")
    t, b = stats["total"], stats["budget"]
    lines.append(f"{'TOTAL':11s} {'':5s} {t['vertices']:6d} {t['polygons']:6d} {t['triangles']:6d} {t['shells']:6d}")
    lines.append(f"budget: polygons {t['polygons']} / {b['polygons']}, triangles {t['triangles']} / {b['triangles']}"
                 f" -> {'OK' if stats['within_budget'] else 'OVER BUDGET'}")
    lines.append(f"rays: feature silhouette vertices per object <= {b['ray_vertices']} (castplane MESH_RAYS_CAPPED) "
                 f"-> {'OK' if stats['rays_ok'] else 'OVER (castplane will warn)'}")
    return "\n".join(lines)

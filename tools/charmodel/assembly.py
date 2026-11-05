"""Parts -> castplane mesh objects of a character model, with validation and statistics (character-free).

A character package describes itself with a :class:`Character`: its objects in their fixed order, its
materials (colours), the display material of each object, the default object of each region, its part
modules, its mannequin (placeholder parts for every region), its rig factory, its sun direction and its
budget.  Everything here reads that description; nothing names a character.

Flow: :func:`build_parts` asks each part module (``Character.modules``) for its parts; a module whose
``build(rig)`` returns ``None`` is replaced by the mannequin parts of its ``REGIONS``.  Every part names a
**material** (its colour, ``Character.materials``) and goes into one **object** (``Part.obj``, default
``Character.region_objects`` of its region).  Objects are spatially compact groups of parts: castplane's
hidden-line pass tests a sample only against objects whose image rectangle contains it, and its
construction-ray cap (64 feature silhouette vertices, ``MESH_RAYS_CAPPED``) counts per object.  An optional
uniform ``Character.scale`` (a number, or a function of the rig) multiplies every part's vertices about the
origin in :func:`build_parts`, before the rounding: a character is designed at its design sheet's scale and
scaled to a stated height.  :func:`assemble` rounds every part to ``Character.decimals``, validates it (closed
outward manifold shells, no tiny faces, no vertex below the ground), merges the parts per object in
``Character.objects`` order (renumbering smooth groups per part so different parts never share a group id, and
keeping each part's face range and material for the exporters), reorders vertices so castplane's
nesting-parity test cannot flip an overlapping shell (:func:`meshkit.fix_nesting`), validates each object
again (duplicate vertices across parts) and returns an :class:`Assembly` with the castplane object dicts and
per-part / per-object statistics (:func:`format_stats` prints them).
"""

from __future__ import annotations

import dataclasses
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from . import meshkit as mk

__all__ = ["Character", "Assembly", "AssemblyError", "build_parts", "assemble", "compute_stats", "format_stats",
           "module_name", "scale_parts"]


class AssemblyError(ValueError):
    """Invalid parts (the message lists every failing part / object), or an inconsistent :class:`Character`."""


@dataclass(frozen=True, eq=False)
class Character:
    """What :func:`assemble` (and the exporters and previews) need to know about a character model.

    * ``name``: file stem and glTF scene name (``<name>.json``, ``meshes/<name>.{obj,mtl,glb}``);
    * ``objects``: ``((object id, what it holds), ...)`` in the fixed scene order (``objects[0]`` is the
      object whose vertices the web UI's observer pane draws sight rays to);
    * ``materials``: ``{material: "#rrggbb"}`` (lower case), in the order the MTL and GLB list them;
    * ``display_materials``: ``{object id: material}``, every object in ``objects`` order: the object's
      dominant material, whose colour becomes its ``display_color`` (D81; web 3D views only);
    * ``region_objects``: ``{region: object id or None}`` for every region; ``None`` means a part of that
      region must set ``obj``;
    * ``modules``: the part modules in assembly order; each has ``REGIONS`` (a tuple of region names) and
      ``build(rig)`` returning a list of :class:`~charmodel.meshkit.Part` for **all** its regions, or ``None``
      (then the mannequin stands in);
    * ``mannequin``: a module with ``REGIONS`` (every region of the modules) and ``build(rig, regions)``;
    * ``rig_factory``: called with no arguments for the default rig (the character's ``Rig`` class);
    * ``sun_towards``: the direction towards the scene's sun (the light silhouette of the ray count, the
      scene light, the shading of the previews);
    * ``budget``: ``{"polygons": P, "triangles": T}`` at least (polygons = faces as written, triangles =
      castplane's fan triangulation);
    * ``decimals``: coordinates are rounded to this many decimals before validation and writing;
    * ``scale``: an optional uniform scale of the whole figure about the origin: ``None`` (the default: no scale,
      the parts are written as built), a positive number, or a function ``scale(rig) -> float`` (so a rig override
      can change it).  :func:`build_parts` multiplies every part's vertices by it (an elementwise product, the
      mannequin's parts too) before :func:`assemble` rounds them.  Design the parts at the design sheet's scale and
      scale the model to the character's stated height: the soles on ``z = 0`` stay there.

    The constructor checks the description's consistency and raises :class:`AssemblyError`."""

    name: str
    objects: tuple
    materials: dict
    display_materials: dict
    region_objects: dict
    modules: tuple
    mannequin: Any
    rig_factory: Callable
    sun_towards: tuple
    budget: dict
    decimals: int = 5
    scale: Any = None

    def __post_init__(self):
        ids = self.object_ids
        problems = []
        if len(set(ids)) != len(ids):
            problems.append("object ids must be unique")
        if set(self.mannequin.REGIONS) != set(self.all_regions):
            problems.append("mannequin regions and module REGIONS disagree")
        if set(self.region_objects) != set(self.all_regions):
            problems.append("region_objects must name every region")
        if tuple(self.display_materials) != ids:
            problems.append("display_materials must list every object in objects order")
        if not set(self.display_materials.values()) <= set(self.materials):
            problems.append("display_materials names an unknown material")
        if not all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in self.materials.values()):
            problems.append("materials: lower-case #rrggbb")
        if not set(self.region_objects.values()) - {None} <= set(ids):
            problems.append("region_objects names an unknown object")
        if not {"polygons", "triangles"} <= set(self.budget):
            problems.append("budget needs 'polygons' and 'triangles'")
        if self.scale is not None and not callable(self.scale) and not _valid_scale(self.scale):
            problems.append("scale must be None, a positive finite number or a function of the rig")
        if problems:
            raise AssemblyError(f"character {self.name!r}: " + "; ".join(problems))

    @property
    def object_ids(self) -> tuple:
        """The object ids in the fixed order."""
        return tuple(oid for oid, _ in self.objects)

    @property
    def all_regions(self) -> tuple:
        """Every region of the part modules, in module order."""
        return tuple(r for m in self.modules for r in m.REGIONS)

    def display_color(self, oid: str) -> str:
        """Lower-case ``"#rrggbb"`` display colour of object ``oid`` (its display material's colour)."""
        return self.materials[self.display_materials[oid]].lower()

    def scale_for(self, rig):
        """The uniform figure scale of ``rig`` (``None`` when the character has none); raises :class:`AssemblyError`
        unless it is a positive finite number."""
        if self.scale is None:
            return None
        value = self.scale(rig) if callable(self.scale) else self.scale
        if not _valid_scale(value):
            raise AssemblyError(f"character {self.name!r}: scale {value!r} is not a positive finite number")
        return float(value)


def _valid_scale(value) -> bool:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f) and f > 0.0


@dataclass
class Assembly:
    """Result of :func:`assemble`."""

    rig: Any
    parts: list                                   # Part list (rounded meshes, ``obj`` resolved), assembly order
    sources: dict                                 # region -> module name or "mannequin"
    meshes: dict                                  # object id -> merged Mesh (fixed objects order)
    part_faces: dict                              # object id -> [(part name, material, first face, n faces)]
    reports: dict = field(default_factory=dict)   # part / object name -> ValidationReport
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.reports.values())

    def materials(self, oid: str) -> list:
        """``[(material, [face index, ...])]`` of object ``oid``, materials in first-appearance order."""
        out = {}
        for _name, mat, first, n in self.part_faces[oid]:
            out.setdefault(mat, []).extend(range(first, first + n))
        return list(out.items())

    def objects(self) -> list:
        """castplane mesh object dicts ``{"id", "type": "mesh", "data": {...}}`` in the fixed order."""
        out = []
        for oid, m in self.meshes.items():
            out.append({"id": oid, "type": "mesh", "data": {
                "vertices": [[float(x) + 0.0 for x in v] for v in m.vertices],
                "faces": [list(f) for f in m.faces],
                "smooth_groups": list(m.groups)}})
        return out


def module_name(module) -> str:
    """The last component of a module's name (``head`` for ``<name>_model.head``)."""
    return module.__name__.rsplit(".", 1)[-1]


def _wanted(module, only):
    if only is None:
        return list(module.REGIONS)
    return [r for r in module.REGIONS if r in only]


def _resolve(character: Character, p: mk.Part, where: str) -> mk.Part:
    """``p`` with ``obj`` filled in from its region; checks the material and the object."""
    if p.material not in character.materials:
        raise AssemblyError(f"part {p.name!r} ({where}) has unknown material {p.material!r}; "
                            f"one of {list(character.materials)}")
    ids = character.object_ids
    obj = p.obj
    if not obj:
        if not p.region or character.region_objects.get(p.region, "") is None:
            raise AssemblyError(f"part {p.name!r} ({where}) has no obj and its region {p.region!r} has no default "
                                f"object: set obj= to one of {list(ids)}")
        obj = character.region_objects[p.region]
    if obj not in ids:
        raise AssemblyError(f"part {p.name!r} ({where}) has unknown object {obj!r}; one of {list(ids)}")
    return dataclasses.replace(p, obj=obj)


def scale_parts(parts, factor) -> list:
    """``parts`` with every mesh scaled by ``factor`` about the origin (vertices times ``factor``, elementwise, so
    the result is the same on every CPU); ``factor`` ``None`` returns the parts unchanged."""
    if factor is None:
        return list(parts)
    f = float(factor)
    return [dataclasses.replace(p, mesh=mk.Mesh(p.mesh.vertices * f, p.mesh.faces, p.mesh.groups)) for p in parts]


def build_parts(character: Character, rig, only=None):
    """``(parts, sources)``: the parts of every region (or of the regions in ``only``) with ``obj``
    resolved, and which module built each region.  ``only`` may also name a module (by
    :func:`module_name`).  With a ``character.scale`` every part is scaled by it (:func:`scale_parts`)."""
    modules, all_regions = character.modules, character.all_regions
    if only is not None:
        only = set(only)
        for m in modules:
            if module_name(m) in only:
                only |= set(m.REGIONS)
        unknown = sorted(only - set(all_regions) - {module_name(m) for m in modules})
        if unknown:
            raise AssemblyError(f"unknown region(s) {unknown}; regions: {list(all_regions)}")
    parts, sources = [], {}
    for module in modules:
        wanted = _wanted(module, only)
        if not wanted:
            continue
        name = module_name(module)
        built = module.build(rig)
        if built is None:
            parts.extend(_resolve(character, p, "mannequin") for p in character.mannequin.build(rig, wanted))
            sources.update({r: "mannequin" for r in wanted})
            continue
        for p in built:
            if not isinstance(p, mk.Part):
                raise AssemblyError(f"{name}.build returned a {type(p).__name__}, not a Part")
            if p.region and p.region not in module.REGIONS:
                raise AssemblyError(f"part {p.name!r} of {name}.py has region {p.region!r}, "
                                    f"not one of {module.REGIONS}")
            if not p.region or p.region in wanted:
                parts.append(_resolve(character, p, f"{name}.py"))
        sources.update({r: name for r in wanted})
    seen = set()
    for p in parts:
        if p.name in seen:
            raise AssemblyError(f"duplicate part name {p.name!r}")
        seen.add(p.name)
    factor = character.scale_for(rig)
    if factor is not None:
        parts = scale_parts(parts, factor)
    return parts, sources


def assemble(character: Character, rig=None, only=None, strict: bool = True) -> Assembly:
    """Build, round, validate and merge the model (``rig`` defaults to ``character.rig_factory()``).
    ``strict`` raises :class:`AssemblyError` listing every invalid part / object; otherwise the reports are
    kept on the result (``Assembly.ok``)."""
    rig = character.rig_factory() if rig is None else rig
    raw, sources = build_parts(character, rig, only)
    parts, reports = [], {}
    for p in raw:
        m = p.mesh.rounded(character.decimals)
        parts.append(dataclasses.replace(p, mesh=m))
        reports[p.name] = mk.validate(m, p.name, check_nesting=False)   # nesting: per object, below
    meshes, part_faces = {}, {}
    for oid in character.object_ids:
        group_parts = [p for p in parts if p.obj == oid]
        if not group_parts:
            continue
        pieces, next_group, ranges, first = [], 1, [], 0
        for p in group_parts:
            local = sorted(set(g for g in p.mesh.groups if g != 0))
            remap = {g: next_group + k for k, g in enumerate(local)}
            next_group += len(local)
            pieces.append(p.mesh.with_groups(remap))
            ranges.append((p.name, p.material, first, p.mesh.n_faces))
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
    result.stats = compute_stats(character, result)
    if strict and not result.ok:
        bad = [r.summary() for r in reports.values() if not r.ok]
        raise AssemblyError("invalid model:\n" + "\n".join(bad))
    return result


def compute_stats(character: Character, a: Assembly) -> dict:
    """Per-part / per-object / total statistics of an assembly, against ``character.budget`` and the ray cap
    (feature silhouette vertices towards ``character.sun_towards``)."""
    sun, budget = character.sun_towards, character.budget
    parts = []
    for p in a.parts:
        rep = a.reports.get(p.name)
        parts.append({"name": p.name, "object": p.obj, "material": p.material, "region": p.region,
                      "source": a.sources.get(p.region, ""), "vertices": p.mesh.n_vertices,
                      "polygons": p.mesh.n_faces, "triangles": p.mesh.n_triangles,
                      "shells": rep.n_shells if rep else 0,
                      "ray_vertices": len(mk.feature_silhouette_vertices(p.mesh, sun))})
    objects = []
    for oid, m in a.meshes.items():
        rep = a.reports.get(f"object {oid}")
        objects.append({"id": oid, "vertices": m.n_vertices, "polygons": m.n_faces, "triangles": m.n_triangles,
                        "shells": rep.n_shells if rep else 0, "groups": len(set(m.groups) - {0}),
                        "parts": len(a.part_faces[oid]), "materials": [mat for mat, _ in a.materials(oid)],
                        "ray_vertices": len(mk.feature_silhouette_vertices(m, sun))})
    total = {k: sum(o[k] for o in objects) for k in ("vertices", "polygons", "triangles", "shells")}
    rays = mk.MAX_FEATURE_SILHOUETTE_VERTICES
    return {"parts": parts, "objects": objects, "total": total, "budget": dict(budget, ray_vertices=rays),
            "within_budget": total["polygons"] <= budget["polygons"] and total["triangles"] <= budget["triangles"],
            "rays_ok": all(o["ray_vertices"] <= rays for o in objects),
            "rays_over": [o["id"] for o in objects if o["ray_vertices"] > rays]}


def format_stats(stats: dict, object_ids, parts: bool = True) -> str:
    """Plain-text table of :func:`assemble` statistics (per part, per object, total vs budget); ``object_ids``
    (the character's fixed order) numbers the objects.  The object column is as wide as the longest object id, at
    least 10 characters (a character whose ids fit in 10 prints as before)."""
    object_ids = tuple(object_ids)
    w = max([10, *(len(i) for i in object_ids)])
    lines = []
    if parts:
        lines.append(f"{'part':30s} {'object':{w}s} {'material':10s} {'source':9s} {'verts':>6s} {'polys':>6s} "
                     f"{'tris':>6s} {'shells':>6s} {'rays':>5s}")
        for p in stats["parts"]:
            lines.append(f"{p['name']:30s} {p['object']:{w}s} {p['material']:10s} {p['source']:9s} "
                         f"{p['vertices']:6d} {p['polygons']:6d} {p['triangles']:6d} {p['shells']:6d} "
                         f"{p['ray_vertices']:5d}")
        lines.append("")
    lines.append(f"{'#':>2s} {'object':{w}s} {'parts':>5s} {'verts':>6s} {'polys':>6s} {'tris':>6s} {'shells':>6s} "
                 f"{'groups':>6s} {'rays':>5s}  materials")
    for o in stats["objects"]:
        k = object_ids.index(o["id"])
        flag = "  OVER" if o["ray_vertices"] > stats["budget"]["ray_vertices"] else ""
        lines.append(f"{k:2d} {o['id']:{w}s} {o['parts']:5d} {o['vertices']:6d} {o['polygons']:6d} "
                     f"{o['triangles']:6d} {o['shells']:6d} {o['groups']:6d} {o['ray_vertices']:5d}  "
                     f"{', '.join(o['materials'])}{flag}")
    t, b = stats["total"], stats["budget"]
    lines.append(f"{'':2s} {'TOTAL':{w}s} {'':5s} {t['vertices']:6d} {t['polygons']:6d} {t['triangles']:6d} "
                 f"{t['shells']:6d}")
    lines.append(f"budget: polygons {t['polygons']} / {b['polygons']}, triangles {t['triangles']} / {b['triangles']}"
                 f" -> {'OK' if stats['within_budget'] else 'OVER BUDGET'}")
    over = stats.get("rays_over", [])
    lines.append(f"rays: feature silhouette vertices per object <= {b['ray_vertices']} (castplane MESH_RAYS_CAPPED) "
                 f"-> {'OK' if stats['rays_ok'] else 'OVER in ' + ', '.join(over) + ' (castplane will warn)'}")
    return "\n".join(lines)

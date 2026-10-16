"""Parts -> the 18 castplane mesh objects of the Miki model (fixed order), with validation and statistics.

Flow: :func:`build_parts` asks each part module (``head``, ``hair``, ``body``, ``limbs``) for its parts;
a module whose ``build(rig)`` returns ``None`` is replaced by the mannequin parts of its ``REGIONS``.
Every part names a **material** (its colour, :data:`MATERIALS`) and goes into one **object** (``Part.obj``,
default :data:`REGION_OBJECTS` of its region).  Objects are spatially compact groups of parts: castplane's
hidden-line pass tests a sample only against objects whose image rectangle contains it, and its
construction-ray cap (64 feature silhouette vertices, ``MESH_RAYS_CAPPED``) counts per object.
:func:`assemble` rounds every part to :data:`DECIMALS`, validates it (closed outward manifold shells, no
tiny faces, no vertex below the ground), merges the parts per object in :data:`OBJECTS` order (renumbering
smooth groups per part so different parts never share a group id, and keeping each part's face range and
material for the exporters), reorders vertices so castplane's nesting-parity test cannot flip an
overlapping shell (:func:`meshkit.fix_nesting`), validates each object again (duplicate vertices across
parts) and returns an :class:`Assembly` with the castplane object dicts and per-part / per-object
statistics.
"""

from __future__ import annotations

import dataclasses
import re
from dataclasses import dataclass, field

from . import body, hair, head, limbs, mannequin
from . import meshkit as mk
from .rig import SUN_TOWARDS, Rig

__all__ = ["OBJECTS", "OBJECT_IDS", "MATERIALS", "DISPLAY_MATERIALS", "display_color", "REGION_OBJECTS", "MODULES", "ALL_REGIONS", "BUDGET",
           "DECIMALS", "SUN_TOWARDS", "Assembly", "AssemblyError", "build_parts", "assemble", "format_stats"]

#: The castplane objects in their fixed order (= index in the web UI's 3D palette) with what each holds.
OBJECTS = (
    ("hair", "dome H1, bangs H3, stray strand H5"),
    ("head", "head + face skin"),
    ("eyes", "sclera, iris, pupil, highlight"),
    ("headband", "band, pink centre ridge"),
    ("scarf", "ribbons, tips"),
    ("sidelocks", "sidelocks H4 x2"),
    ("blouse", "torso / blouse"),
    ("collar", "collar, dickey, collar pink stripe"),
    ("back_hair", "side curtain + back sheet H2"),
    ("arm_l", "her left sleeve with its cuff rim, 2 cuff white stripes, hand + thumb"),
    ("face_marks", "brows, upper-lid bands, lower-lid marks, mouth"),
    ("arm_r", "her right sleeve with its cuff rim, 2 cuff white stripes, hand + thumb"),
    ("legs", "legs x2"),
    ("socks", "socks x2"),
    ("skirt", "skirt, under-skirt block"),
    ("shoes", "shoes x2"),
    ("ring", "scarf ring, its two pink stripes"),
    ("neck", "neck + decollete bib"),
)
OBJECT_IDS = tuple(oid for oid, _ in OBJECTS)

#: Materials (sRGB colours for the MTL, GLB and shaded previews), in a fixed order.
MATERIALS = {
    "hair": "#b9c3e6",
    "skin": "#fbe3d6",
    "eye_white": "#ffffff",
    "iris": "#7fb3a8",
    "pupil": "#2f5c57",
    "headband": "#f4dce8",
    "scarf": "#f6c453",
    "socks": "#f2f0f4",
    "uniform": "#e8667a",          # also every pink stripe
    "skirt": "#f5b9c6",
    "collar": "#fafafa",           # also the white cuff stripes, the ring, the dickey
    "face_marks": "#4b3434",
    "shoes": "#6b4a3a",
}

#: Display material of each object (its dominant material): ``display_color(oid)`` is that material's colour,
#: written as the object's optional ``display_color`` key in examples/miki.json.  The web UI's 3D views draw
#: the object in it (instead of the index palette); castplane's core ignores the key (contract §2.0).
DISPLAY_MATERIALS = {
    "hair": "hair", "head": "skin", "eyes": "iris", "headband": "headband", "scarf": "scarf",
    "sidelocks": "hair", "blouse": "uniform", "collar": "collar", "back_hair": "hair", "arm_l": "uniform",
    "face_marks": "face_marks", "arm_r": "uniform", "legs": "skin", "socks": "socks", "skirt": "skirt",
    "shoes": "shoes", "ring": "collar", "neck": "skin",
}


def display_color(oid: str) -> str:
    """Lower-case ``"#rrggbb"`` display colour of object ``oid`` (:data:`DISPLAY_MATERIALS`)."""
    return MATERIALS[DISPLAY_MATERIALS[oid]].lower()


#: Default object of a part by its region (``Part.obj`` overrides it: e.g. ``hair`` parts that are
#: sidelocks go to ``sidelocks``, the back hair to ``back_hair``, the scarf ring to ``ring``).  ``None``:
#: the region has no default and every part must set ``obj`` (``arms`` / ``hands`` go to ``arm_l`` or
#: ``arm_r`` by side: one compact object per arm keeps the hidden-line pass from testing hand-to-hand
#: image rectangles).  The neck and the bib are their own compact object (review round 1, appended so the
#: other indices keep their palette colours): the head's image rectangle then ends at the chin and the
#: blouse's triangles are not tested by the collar / neck samples twice.
REGION_OBJECTS = {
    "head": "head", "eyes": "eyes", "face_marks": "face_marks",
    "hair": "hair", "headband": "headband",
    "neck": "neck", "torso": "blouse", "collar": "collar", "scarf": "scarf", "skirt": "skirt",
    "arms": None, "hands": None, "legs": "legs", "socks": "socks", "shoes": "shoes",
}

#: Part modules in assembly order (each defines ``REGIONS`` and ``build(rig)``).
MODULES = (head, hair, body, limbs)
ALL_REGIONS = tuple(r for m in MODULES for r in m.REGIONS)

#: Web-UI budget (BRIEF §5): polygons = faces as written, triangles = castplane's fan triangulation.
BUDGET = {"polygons": 6000, "triangles": 10000}


#: Coordinates are rounded to this many decimals (0.01 mm) before validation and writing.
DECIMALS = 5

assert set(mannequin.REGIONS) == set(ALL_REGIONS), "mannequin regions and module REGIONS disagree"
assert set(REGION_OBJECTS) == set(ALL_REGIONS), "REGION_OBJECTS must name every region"
assert tuple(DISPLAY_MATERIALS) == OBJECT_IDS, "DISPLAY_MATERIALS must list every object in OBJECTS order"
assert set(DISPLAY_MATERIALS.values()) <= set(MATERIALS)
assert all(re.fullmatch(r"#[0-9a-f]{6}", c) for c in MATERIALS.values()), "MATERIALS: lower-case #rrggbb"
assert set(REGION_OBJECTS.values()) - {None} <= set(OBJECT_IDS)


class AssemblyError(ValueError):
    """Invalid parts (the message lists every failing part / object)."""


@dataclass
class Assembly:
    """Result of :func:`assemble`."""

    rig: Rig
    parts: list                                   # Part list (rounded meshes, ``obj`` resolved), assembly order
    sources: dict                                 # region -> "head" / "hair" / ... / "mannequin"
    meshes: dict                                  # object id -> merged Mesh (fixed OBJECTS order)
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


def _module_name(module) -> str:
    return module.__name__.rsplit(".", 1)[-1]


def _wanted(module, only):
    if only is None:
        return list(module.REGIONS)
    return [r for r in module.REGIONS if r in only]


def _resolve(p: mk.Part, where: str) -> mk.Part:
    """``p`` with ``obj`` filled in from its region; checks the material and the object."""
    if p.material not in MATERIALS:
        raise AssemblyError(f"part {p.name!r} ({where}) has unknown material {p.material!r}; "
                            f"one of {list(MATERIALS)}")
    obj = p.obj
    if not obj:
        if not p.region or REGION_OBJECTS.get(p.region, "") is None:
            raise AssemblyError(f"part {p.name!r} ({where}) has no obj and its region {p.region!r} has no default "
                                f"object: set obj= to one of {list(OBJECT_IDS)}")
        obj = REGION_OBJECTS[p.region]
    if obj not in OBJECT_IDS:
        raise AssemblyError(f"part {p.name!r} ({where}) has unknown object {obj!r}; one of {list(OBJECT_IDS)}")
    return dataclasses.replace(p, obj=obj)


def build_parts(rig: Rig, only=None):
    """``(parts, sources)``: the parts of every region (or of the regions in ``only``) with ``obj``
    resolved, and which module built each region.  ``only`` may also name a module (``head``, ``hair``,
    ``body``, ``limbs``)."""
    if only is not None:
        only = set(only)
        for m in MODULES:
            if _module_name(m) in only:
                only |= set(m.REGIONS)
        unknown = sorted(only - set(ALL_REGIONS) - {_module_name(m) for m in MODULES})
        if unknown:
            raise AssemblyError(f"unknown region(s) {unknown}; regions: {list(ALL_REGIONS)}")
    parts, sources = [], {}
    for module in MODULES:
        wanted = _wanted(module, only)
        if not wanted:
            continue
        name = _module_name(module)
        built = module.build(rig)
        if built is None:
            parts.extend(_resolve(p, "mannequin") for p in mannequin.build(rig, wanted))
            sources.update({r: "mannequin" for r in wanted})
            continue
        for p in built:
            if not isinstance(p, mk.Part):
                raise AssemblyError(f"{name}.build returned a {type(p).__name__}, not a Part")
            if p.region and p.region not in module.REGIONS:
                raise AssemblyError(f"part {p.name!r} of {name}.py has region {p.region!r}, "
                                    f"not one of {module.REGIONS}")
            if not p.region or p.region in wanted:
                parts.append(_resolve(p, f"{name}.py"))
        sources.update({r: name for r in wanted})
    seen = set()
    for p in parts:
        if p.name in seen:
            raise AssemblyError(f"duplicate part name {p.name!r}")
        seen.add(p.name)
    return parts, sources


def assemble(rig: Rig | None = None, only=None, strict: bool = True) -> Assembly:
    """Build, round, validate and merge the model.  ``strict`` raises :class:`AssemblyError` listing every
    invalid part / object; otherwise the reports are kept on the result (``Assembly.ok``)."""
    rig = Rig() if rig is None else rig
    raw, sources = build_parts(rig, only)
    parts, reports = [], {}
    for p in raw:
        m = p.mesh.rounded(DECIMALS)
        parts.append(dataclasses.replace(p, mesh=m))
        reports[p.name] = mk.validate(m, p.name, check_nesting=False)   # nesting: per object, below
    meshes, part_faces = {}, {}
    for oid in OBJECT_IDS:
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
    result.stats = _stats(result)
    if strict and not result.ok:
        bad = [r.summary() for r in reports.values() if not r.ok]
        raise AssemblyError("invalid model:\n" + "\n".join(bad))
    return result


def _stats(a: Assembly) -> dict:
    parts = []
    for p in a.parts:
        rep = a.reports.get(p.name)
        parts.append({"name": p.name, "object": p.obj, "material": p.material, "region": p.region,
                      "source": a.sources.get(p.region, ""), "vertices": p.mesh.n_vertices,
                      "polygons": p.mesh.n_faces, "triangles": p.mesh.n_triangles,
                      "shells": rep.n_shells if rep else 0,
                      "ray_vertices": len(mk.feature_silhouette_vertices(p.mesh, SUN_TOWARDS))})
    objects = []
    for oid, m in a.meshes.items():
        rep = a.reports.get(f"object {oid}")
        objects.append({"id": oid, "vertices": m.n_vertices, "polygons": m.n_faces, "triangles": m.n_triangles,
                        "shells": rep.n_shells if rep else 0, "groups": len(set(m.groups) - {0}),
                        "parts": len(a.part_faces[oid]), "materials": [mat for mat, _ in a.materials(oid)],
                        "ray_vertices": len(mk.feature_silhouette_vertices(m, SUN_TOWARDS))})
    total = {k: sum(o[k] for o in objects) for k in ("vertices", "polygons", "triangles", "shells")}
    rays = mk.MAX_FEATURE_SILHOUETTE_VERTICES
    return {"parts": parts, "objects": objects, "total": total, "budget": dict(BUDGET, ray_vertices=rays),
            "within_budget": total["polygons"] <= BUDGET["polygons"] and total["triangles"] <= BUDGET["triangles"],
            "rays_ok": all(o["ray_vertices"] <= rays for o in objects),
            "rays_over": [o["id"] for o in objects if o["ray_vertices"] > rays]}


def format_stats(stats: dict, parts: bool = True) -> str:
    """Plain-text table of :func:`assemble` statistics (per part, per object, total vs budget)."""
    lines = []
    if parts:
        lines.append(f"{'part':30s} {'object':10s} {'material':10s} {'source':9s} {'verts':>6s} {'polys':>6s} "
                     f"{'tris':>6s} {'shells':>6s} {'rays':>5s}")
        for p in stats["parts"]:
            lines.append(f"{p['name']:30s} {p['object']:10s} {p['material']:10s} {p['source']:9s} "
                         f"{p['vertices']:6d} {p['polygons']:6d} {p['triangles']:6d} {p['shells']:6d} "
                         f"{p['ray_vertices']:5d}")
        lines.append("")
    lines.append(f"{'#':>2s} {'object':10s} {'parts':>5s} {'verts':>6s} {'polys':>6s} {'tris':>6s} {'shells':>6s} "
                 f"{'groups':>6s} {'rays':>5s}  materials")
    for o in stats["objects"]:
        k = OBJECT_IDS.index(o["id"])
        flag = "  OVER" if o["ray_vertices"] > stats["budget"]["ray_vertices"] else ""
        lines.append(f"{k:2d} {o['id']:10s} {o['parts']:5d} {o['vertices']:6d} {o['polygons']:6d} "
                     f"{o['triangles']:6d} {o['shells']:6d} {o['groups']:6d} {o['ray_vertices']:5d}  "
                     f"{', '.join(o['materials'])}{flag}")
    t, b = stats["total"], stats["budget"]
    lines.append(f"{'':2s} {'TOTAL':10s} {'':5s} {t['vertices']:6d} {t['polygons']:6d} {t['triangles']:6d} "
                 f"{t['shells']:6d}")
    lines.append(f"budget: polygons {t['polygons']} / {b['polygons']}, triangles {t['triangles']} / {b['triangles']}"
                 f" -> {'OK' if stats['within_budget'] else 'OVER BUDGET'}")
    over = stats.get("rays_over", [])
    lines.append(f"rays: feature silhouette vertices per object <= {b['ray_vertices']} (castplane MESH_RAYS_CAPPED) "
                 f"-> {'OK' if stats['rays_ok'] else 'OVER in ' + ', '.join(over) + ' (castplane will warn)'}")
    return "\n".join(lines)

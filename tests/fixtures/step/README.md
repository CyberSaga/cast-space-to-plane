# M8 STEP fixtures

Written by `python tools/make_step_fixtures.py` (needs OCP: `pip install 'castplane[step]'`; `--check` regenerates
into a temporary directory and compares bytes). Used by `tests/test_step.py`. Contract §5.5.9.

- Generator: **cadquery-ocp 8.0.1.1.0** (OCP 8.0.1), i.e. "Open CASCADE STEP processor 8.0", schema AP214
  (`write.step.schema = AP214`, `FILE_SCHEMA(('AUTOMOTIVE_DESIGN { 1 0 10303 214 1 1 1 1 }'))`), Python 3.13.
- The whole set is written in the table order below within one process. Afterwards every file is rewritten so that
  regeneration is byte-reproducible for a given OCC build: `FILE_NAME` time stamp `'2026-10-06T00:00:00'`, author
  `('castplane')`, organisation `('cast-space-to-plane')`; every `PRODUCT` name and id
  `'Open CASCADE STEP translator 8.0 <counter>'` becomes `'castplane <fixture>'` (root) or `'castplane <fixture>.<k>'`
  (k-th child). OCC 8.0 numbers the transfers `8.0 1` … `8.0 7` for the seven single-solid fixtures and `8.0 8`,
  `8.0 8.1`, `8.0 8.2` inside `two_solids`. Everything else is left exactly as OCC wrote it.
- All parameters are integer millimetres, so that the expanded values are exact (contract §5.5.3).
- Observation: OCC writes directions with 12–13 significant digits (`0.866025403784`, `2.775557561563E-17`) and
  coordinates with up to 14 (`743.46242505348`); it writes `-0.` literally (`DIRECTION('',(1.,0.,-0.))`).

| fixture | bytes | entities | OCP construction | expands to (m) |
| --- | --- | --- | --- | --- |
| `cylinder.step` | 5 684 | 118 | `BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(-1500, 6000, 0), gp_Dir(0, 0, 1)), 300, 2400)` | the spec §4 `pillar`: `cylinder r 0.3 h 2.4 at (-1.5, 6, 0)`, `rotation_deg [0, 0, 0]` |
| `cylinder_down.step` | 5 715 | 118 | `MakeCylinder(gp_Ax2(gp_Pnt(-1500, 6000, 2400), gp_Dir(0, 0, -1)), 300, 2400)` (`ref_direction (-1., 0., -0.)`) | `r 0.3 h 2.4 at (-1.5, 6, 0)`, `rotation_deg [0, 0, 180]` exactly |
| `cylinder_tilted.step` | 6 195 | 118 | `MakeCylinder(gp_Ax2(gp_Pnt(0, 5000, -400), gp_Dir(*R[:, 2]), gp_Dir(*R[:, 0])), 500, 1600)`, `R = Rz(20°)·Rx(30°)` | `r 0.5 h 1.600000000000126 at (0, 5, -0.4)`, `rotation_deg [30.000000000017515, 1.3772205761362216e-15, 20.000000000016044]` |
| `sphere.step` | 2 076 | 32 | `BRepPrimAPI_MakeSphere(gp_Pnt(1000, 2000, 500), 500)` (one face, one `VERTEX_LOOP`) | `sphere r 0.5 at (1, 2, 0)`, `rotation_deg [0, 0, 0]` |
| `cone.step` | 4 415 | 87 | `BRepPrimAPI_MakeCone(gp_Ax2(gp_Pnt(-2000, 5000, 0), gp_Dir(0, 0, 1)), 400, 0, 1200)` (surface axis written `(-0., -0., -1.)`, semi-angle `0.321750554397`) | `cone r 0.4 h 1.2 at (-2, 5, 0)` exactly |
| `box.step` | 16 430 | 350 | `BRepPrimAPI_MakeBox(gp_Pnt(-500, -400, 0), 1000, 800, 600)`, then `BRepBuilderAPI_Transform` with `T(2000, 4000, 0)·Rz(30°)` (faces `#17` / `#137` both carry the axis `(0.866025403784, 0.5, 0.)`) | `box [1.00000000000002, 0.8000000000003888, 0.6] at (2.0000000000000004, 4, 0)`, `rotation_deg [0, 0, 30.000000000012566]` |
| `frustum.step` (negative) | 5 726 | 118 | `MakeCone(gp_Ax2(origin, +z), 400, 200, 1200)` | `StepError` `#15: unsupported solid: faces {CONICAL_SURFACE: 1, PLANE: 2}`; with `fallback: "mesh"` a `mesh` object |
| `two_solids.step` (multi) | 9 304 | 176 | compound of the cylinder and the sphere above (written as an identity assembly: `ITEM_DEFINED_TRANSFORMATION('','',#11,#15)` and `(…,#11,#19)`) | `<id>_0` (cylinder, entity `#37`), `<id>_1` (sphere, `#154`) |

Tessellation with the rule of contract §5.5.7 (OCC 8.0, measured, not asserted): cylinder 170 nodes / 164 triangles,
frustum 400 / 598, box 24 / 12, sphere 1447 / 2836, cone 353 / 587.

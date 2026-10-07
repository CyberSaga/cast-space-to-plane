# v7 conformance candidates (final review fixes; the merge step promotes them)

- `mesh_noisy_l_ground_contact.json` (group loaders, m5-mesh#0): concave L prism mesh whose bottom vertices v3, v5 sit 1e-7 m below the ground (inside the 1e-6 weld/contact tolerance); expected outline = the clean L's, no `OBJECT_BELOW_RECEIVER`.
- `multilight_mesh_fallback_shared_edges.json` — m6-umbra#0: per-face fallback mesh (144 faces, shared edges) under two point lights; umbra = 14 pieces with the §5.3.4 step-5 zero-width bridging (514 before).

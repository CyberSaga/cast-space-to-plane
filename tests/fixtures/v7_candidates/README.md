# v7 conformance candidates

- `mesh_noisy_l_ground_contact.json` (group loaders, m5-mesh#0): concave L prism mesh whose bottom vertices v3, v5 sit 1e-7 m below the ground (inside the 1e-6 weld/contact tolerance); expected outline = the clean L's, no `OBJECT_BELOW_RECEIVER`.

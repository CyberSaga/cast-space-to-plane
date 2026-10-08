/** Shared mesh fixtures of the mesh tests (contract §5.2.12; `tests/test_meshprep.py` / `tests/test_mesh_pipeline.py`). */

export const CUBE_V = [[-.5, -.5, 0.0], [.5, -.5, 0.0], [.5, .5, 0.0], [-.5, .5, 0.0],
  [-.5, -.5, 1.0], [.5, -.5, 1.0], [.5, .5, 1.0], [-.5, .5, 1.0]];
export const CUBE_F = [[0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7]];
/** The acceptance box of contract §5.2.12: 8 vertices + the same eight twice, 12 triangles on the duplicates. */
export const SPLIT_V = [...CUBE_V, ...CUBE_V, ...CUBE_V];
export const SPLIT_F = [[8, 11, 10], [8, 10, 9], [12, 13, 14], [12, 14, 15], [16, 17, 21], [16, 21, 20],
  [17, 18, 22], [17, 22, 21], [18, 19, 23], [18, 23, 22], [19, 16, 20], [19, 20, 23]];

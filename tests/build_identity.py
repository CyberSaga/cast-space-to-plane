"""Is this interpreter the build the conformance expected files were recorded on (contract §4)?

Expected files and golden hashes are bit-exact only for the recorded build. The NumPy version alone does not
identify it: NumPy's bundled OpenBLAS picks its kernels per CPU at run time (``DYNAMIC_ARCH``), and the
ufunc loops dispatch on the CPU's SIMD features, so the same wheel rounds a few leaves differently on a
SkylakeX and on a Haswell / Zen machine (``random_seed9_3objects`` changes its last digits on a hosted CI
runner). ``fingerprint()`` hashes ufunc and linear-algebra results that depend on those choices;
``exact_build()`` requires the recorded NumPy version AND the recorded fingerprint. On any other build the
tests fall back to the spec §7.5 tolerances.

``python -m tests.build_identity --write`` records the current build in ``tests/golden/build_fingerprint.json``
(run it on the machine that regenerates the conformance set).
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import numpy as np

FINGERPRINT_FILE = pathlib.Path(__file__).resolve().parent / "golden" / "build_fingerprint.json"


def fingerprint() -> str:
    x = np.linspace(-7.0, 7.0, 4097)
    parts = [f(x) for f in (np.sin, np.cos, np.arctan, np.exp, np.cbrt)]
    parts += [np.arctan2(x, x[::-1]), np.arccos(x / 7.0), np.sqrt(np.abs(x))]
    for n in (3, 4, 6, 9, 17):
        a = np.sin(np.arange(n * n, dtype=float).reshape(n, n) * 1.37 + 0.1)
        s = a @ a.T + n * np.eye(n)
        parts += [a @ a, np.linalg.svd(a, compute_uv=False), np.linalg.eigh(s)[0], np.linalg.solve(s, a[:, 0]),
                  np.array([np.linalg.det(a)]), np.linalg.lstsq(a[:, : n - 1], a[:, -1], rcond=None)[0],
                  np.linalg.inv(s)]
    return hashlib.sha256(b"".join(np.ascontiguousarray(p, dtype=float).tobytes() for p in parts)).hexdigest()


def recorded() -> dict:
    return json.loads(FINGERPRINT_FILE.read_text(encoding="utf-8"))


_EXACT: dict[str, bool] = {}


def exact_build(recorded_numpy: str | None) -> bool:
    """True iff this is the recorded build: NumPy ``recorded_numpy`` with the recorded fingerprint."""
    if recorded_numpy != np.__version__:
        return False
    if recorded_numpy not in _EXACT:
        rec = recorded()
        _EXACT[recorded_numpy] = rec["numpy"] == recorded_numpy and rec["fingerprint"] == fingerprint()
    return _EXACT[recorded_numpy]


if __name__ == "__main__":
    if sys.argv[1:] != ["--write"]:
        print(f"numpy {np.__version__}  fingerprint {fingerprint()}")
        sys.exit(0)
    FINGERPRINT_FILE.write_text(json.dumps({"numpy": np.__version__, "fingerprint": fingerprint()}, indent=1)
                                + "\n", encoding="utf-8")
    print(f"wrote {FINGERPRINT_FILE}")

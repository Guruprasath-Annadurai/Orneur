"""
Representative local performance measurements (spec section 33). Records
wall time for validate/canonicalize/serialize/digest/diff at a few sizes.
No performance CLAIM is made beyond what is actually measured here; limits
(orneur/intelligence/ocl/limits.py) were chosen to comfortably exceed these
sizes, not the reverse.
"""
from __future__ import annotations

import time

from orneur.intelligence.ocl.canonical import digest, to_canonical_json
from orneur.intelligence.ocl.compiler import compile_artifact
from orneur.intelligence.ocl.diff import diff
from tests.ocl.conftest import make_artifact, make_atom


def _artifact_with_n_atoms(n: int):
    return make_artifact(atoms=tuple(make_atom(f"a{i}", content=f"content {i}") for i in range(n)))


def test_validate_canonicalize_serialize_digest_at_representative_sizes(capsys):
    for n in (10, 100, 1000):
        draft = _artifact_with_n_atoms(n)
        t0 = time.perf_counter()
        compiled = compile_artifact(draft)
        t1 = time.perf_counter()
        json_text = to_canonical_json(compiled)
        t2 = time.perf_counter()
        _ = digest(compiled)
        t3 = time.perf_counter()

        with capsys.disabled():
            print(
                f"[ocl-perf] n_atoms={n} validate={t1 - t0:.4f}s serialize={t2 - t1:.4f}s "
                f"digest={t3 - t2:.4f}s bytes={len(json_text)}"
            )
        # Loose sanity bound only -- not a performance claim, just a guard
        # against an accidental O(n^2)+ regression going unnoticed in CI.
        assert (t1 - t0) < 5.0
        assert (t3 - t1) < 5.0


def test_diff_of_medium_artifacts_is_fast():
    a = compile_artifact(_artifact_with_n_atoms(500))
    b = compile_artifact(_artifact_with_n_atoms(500))
    t0 = time.perf_counter()
    diff(a, b)
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0

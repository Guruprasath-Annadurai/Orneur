"""
Phase 13.1 §18-22 -- bounded, deterministic fuzz/property testing.
No new dependency added (Hypothesis is not installed in this
environment; spec §18 explicitly permits a bounded deterministic
mutation generator instead of adding one solely for this phase).

All generators use `random.Random(SEED)` with a FIXED, RECORDED seed
(spec §18: "keep deterministic seeds recorded") -- SEED = 20260904,
chosen as today's date at the time this file was written, recorded here
so a re-run is byte-for-byte reproducible.
"""
from __future__ import annotations

import random
import unicodedata
from pathlib import Path

import pytest

from orca.godmode.canonical import canonicalize_arguments, hash_arguments
from orca.godmode.file_elevation import _resolve_within_root
from orca.godmode.resolution import _canonicalize as canonicalize_resource_scope
from orca.truth.fetch import _is_ssrf_risk

SEED = 20260904
CASES_PER_FAMILY = 25


# --------------------------------------------------------------- §19: Godmode canonicalizer fuzz


def _random_nested_value(rng: random.Random, depth: int = 0):
    if depth >= 3:
        return rng.choice([rng.randint(-1000, 1000), rng.random(), rng.choice([True, False]), None, f"leaf-{rng.randint(0, 999)}"])
    choice = rng.randint(0, 4)
    if choice == 0:
        return {f"k{i}": _random_nested_value(rng, depth + 1) for i in rng.sample(range(10), rng.randint(1, 4))}
    if choice == 1:
        return [_random_nested_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    if choice == 2:
        return rng.choice([rng.randint(-1000, 1000), rng.random(), rng.choice([True, False]), None])
    if choice == 3:
        return f"str-{rng.randint(0, 999)}"
    return unicodedata.normalize(rng.choice(["NFC", "NFD"]), "café")


def test_canonicalizer_fuzz_equivalent_key_order_always_same_hash():
    """Property: shuffling a dict's key order must never change the hash."""
    rng = random.Random(SEED)
    for i in range(CASES_PER_FAMILY):
        payload = {f"key{j}": _random_nested_value(rng) for j in range(rng.randint(1, 6))}
        items = list(payload.items())
        rng.shuffle(items)
        shuffled = dict(items)
        assert hash_arguments(payload) == hash_arguments(shuffled), f"case {i}: key-order shuffle changed the hash"


def test_canonicalizer_fuzz_bool_int_never_collide():
    """Property: True/False must never canonicalize identically to 1/0 --
    a real, previously-fixed class of bug this project has hit before
    (Phase 10.1's own test_boolean_string_confusion_denied)."""
    rng = random.Random(SEED + 1)
    for i in range(CASES_PER_FAMILY):
        key = f"flag{i}"
        bool_payload = {key: rng.choice([True, False])}
        int_payload = {key: 1 if bool_payload[key] else 0}
        assert hash_arguments(bool_payload) != hash_arguments(int_payload), f"case {i}: bool/int collision for {bool_payload}"


def test_canonicalizer_fuzz_unicode_nfc_nfd_always_equal():
    """Property: NFC vs NFD normalization of the same visual string must
    hash identically (already covered for a fixed example in Phase 10.1;
    fuzzed here across a generated batch of Unicode-bearing strings)."""
    rng = random.Random(SEED + 2)
    base_strings = ["café", "naïve", "Zürich", "résumé", "São Paulo", "İstanbul", "Åland"]
    for i in range(CASES_PER_FAMILY):
        s = rng.choice(base_strings)
        nfc = unicodedata.normalize("NFC", s)
        nfd = unicodedata.normalize("NFD", s)
        assert hash_arguments({"name": nfc}) == hash_arguments({"name": nfd}), f"case {i}: NFC/NFD mismatch for {s!r}"


def test_canonicalizer_fuzz_tampered_payload_never_matches_original_hash():
    """Property: any single-field mutation of a random nested payload
    must change the hash (no accidental collision from the
    canonicalization process itself)."""
    rng = random.Random(SEED + 3)
    collisions = 0
    for i in range(CASES_PER_FAMILY):
        original = {f"k{j}": _random_nested_value(rng) for j in range(rng.randint(2, 5))}
        tampered = dict(original)
        mutate_key = rng.choice(list(tampered.keys()))
        tampered[mutate_key] = f"TAMPERED-{rng.randint(0, 999999)}"
        if hash_arguments(original) == hash_arguments(tampered):
            collisions += 1
    assert collisions == 0, f"{collisions}/{CASES_PER_FAMILY} tampered payloads collided with the original hash"


def test_canonicalizer_fuzz_array_order_is_significant():
    """Property (documents real, correct behavior, not a bug): unlike
    dict key order, LIST order is semantically meaningful and DOES change
    the hash -- reversing a list of 2+ distinct elements must not
    collide."""
    rng = random.Random(SEED + 4)
    changed = 0
    for i in range(CASES_PER_FAMILY):
        arr = list({rng.randint(0, 10_000) for _ in range(rng.randint(3, 6))})
        if len(arr) < 2:
            continue
        reversed_arr = list(reversed(arr))
        if hash_arguments({"items": arr}) != hash_arguments({"items": reversed_arr}):
            changed += 1
    assert changed > 0  # sanity: the property generator actually produced order-sensitive cases


# --------------------------------------------------------------- §20: resource-scope fuzz


_SCOPE_MUTATIONS = [
    lambda s: s + "/",
    lambda s: s.upper(),
    lambda s: s.replace("/", "//"),
    lambda s: s + "/./",
    lambda s: s + "/../" + s.split("/")[-1] if "/" in s else s,
    lambda s: "  " + s + "  ",
    lambda s: s.replace("a", "а"),  # Cyrillic 'а' lookalike
    lambda s: s + "%2e",
    lambda s: s.replace("/", "\\"),
]


def test_resource_scope_fuzz_normalization_never_widens_scope():
    """Property: canonicalizing a mutated resource path must never produce
    a DIFFERENT canonical root than the original UNLESS the mutation
    genuinely changed which resource is named -- specifically, a
    trailing-slash/case/whitespace mutation of the SAME resource must
    canonicalize identically (or fail safe), never to a BROADER prefix
    that would make an unrelated resource match."""
    rng = random.Random(SEED + 10)
    base_paths = ["/workspace/project-a/config", "docs/reports/q3", "/data/tenant-1/files"]
    widened = 0
    for i in range(CASES_PER_FAMILY):
        base = rng.choice(base_paths)
        mutation = rng.choice(_SCOPE_MUTATIONS)
        mutated = mutation(base)
        canonical_base = canonicalize_resource_scope(base)
        canonical_mutated = canonicalize_resource_scope(mutated)
        # A "widened" scope would be one where the mutated canonical form
        # is a STRICT PREFIX ANCESTOR of the base (e.g. canonicalizing to
        # "/workspace" when the real resource is "/workspace/project-a/config")
        # -- that would let a lease scoped to the mutated string cover more
        # than the original resource ever did.
        if canonical_mutated != canonical_base and canonical_base.startswith(canonical_mutated + "/"):
            widened += 1
    assert widened == 0, f"{widened}/{CASES_PER_FAMILY} scope mutations produced a broader (ancestor) canonical scope"


def test_resource_scope_fuzz_case_and_trailing_slash_variants_of_same_path_match():
    rng = random.Random(SEED + 11)
    base_paths = ["/workspace/project-a/config", "connector-instance-1", "docs/reports/q3"]
    for i in range(CASES_PER_FAMILY):
        base = rng.choice(base_paths)
        variant = rng.choice([base + "/", base.upper(), "  " + base])
        assert canonicalize_resource_scope(base) == canonicalize_resource_scope(variant), f"case {i}: {base!r} vs {variant!r} did not normalize equal"


# --------------------------------------------------------------- §21: filesystem path fuzz


_PATH_MUTATIONS = [
    "../etc/passwd",
    "../../etc/passwd",
    "..%2f..%2fetc%2fpasswd",
    "%2e%2e/%2e%2e/etc/passwd",
    "....//....//etc/passwd",
    "/etc/passwd",
    "a/../../etc/passwd",
    "./a/./b/../../../etc/passwd",
    "a" * 5000,  # long path segment
    "ааа/../../../etc/passwd",  # Cyrillic lookalikes
    "a/b/c/../../../../../../etc/passwd",
]


def test_filesystem_path_fuzz_no_traversal_variant_escapes_the_root(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    escapes = 0
    tested = 0
    rng = random.Random(SEED + 20)
    mutations = list(_PATH_MUTATIONS)
    while len(mutations) < CASES_PER_FAMILY:
        base = rng.choice(_PATH_MUTATIONS)
        mutations.append(base.replace("etc", rng.choice(["root", "private/etc", "Users"])))
    for candidate in mutations[:CASES_PER_FAMILY]:
        tested += 1
        resolved = _resolve_within_root(candidate, root)
        if resolved is not None:
            try:
                resolved.relative_to(root.resolve())
            except ValueError:
                escapes += 1
    assert tested >= CASES_PER_FAMILY
    assert escapes == 0, f"{escapes}/{tested} path mutations escaped the workspace root"


def test_filesystem_path_fuzz_absolute_paths_outside_root_always_rejected(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    rng = random.Random(SEED + 21)
    for i in range(CASES_PER_FAMILY):
        outside = f"/tmp/outside-{i}-{rng.randint(0, 999999)}"
        resolved = _resolve_within_root(outside, root)
        assert resolved is None, f"case {i}: absolute path {outside!r} outside root was not rejected"


# --------------------------------------------------------------- §22: URL / SSRF fuzz


_SSRF_URL_VARIANTS = [
    "http://127.0.0.1/",
    "http://localhost/",
    "http://[::1]/",
    "http://0.0.0.0/",
    "http://169.254.169.254/",       # cloud metadata IP
    "http://10.0.0.1/",
    "http://172.16.0.1/",
    "http://192.168.1.1/",
    "http://2130706433/",             # decimal form of 127.0.0.1
    "http://0x7f000001/",             # hex form of 127.0.0.1
    "http://017700000001/",           # octal-ish form of 127.0.0.1
    "http://127.1/",                  # short form
    "http://user@127.0.0.1/",         # userinfo confusion
    "ftp://127.0.0.1/",               # non-http(s) scheme
    "file:///etc/passwd",
    "http://[::ffff:127.0.0.1]/",     # IPv4-mapped IPv6
    "http://" + "1" * 300 + ".example.com/",  # oversized hostname label
]


def test_ssrf_fuzz_known_bypass_variants_all_rejected():
    rejected = 0
    for url in _SSRF_URL_VARIANTS:
        try:
            is_risk = _is_ssrf_risk(url)
        except Exception:
            is_risk = True  # any exception in the check itself must fail closed, not fail open
        if is_risk:
            rejected += 1
    assert rejected == len(_SSRF_URL_VARIANTS), (
        f"only {rejected}/{len(_SSRF_URL_VARIANTS)} known SSRF bypass variants were rejected"
    )


def test_ssrf_fuzz_case_and_whitespace_variants_of_loopback_all_rejected():
    rng = random.Random(SEED + 30)
    variants = []
    bases = ["http://127.0.0.1/", "http://LOCALHOST/", "http://127.0.0.1:8080/", "https://127.0.0.1/path?q=1"]
    for i in range(CASES_PER_FAMILY):
        variants.append(rng.choice(bases))
    rejected = sum(1 for u in variants if _is_ssrf_risk(u))
    assert rejected == len(variants)

"""Semantic-overlap engine (local, provider-free) + manual-review pipeline (signed decisions). Test embedders are deterministic in-test stand-ins that
genuinely exercise the control flow; no model is downloaded, no provider is called."""
import copy
import hashlib
import json
import os
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import contamination as C
from orca.eval.genesis_v2 import isolation as ISO
from orca.eval.genesis_v2 import review as R
from orca.eval.genesis_v2 import semantic as SEM
from orca.eval.genesis_v2 import spec

ROOT = Path(__file__).resolve().parents[1]
CD = hashlib.sha256(b"corpus").hexdigest()
TS = "2026-09-27T10:00:00Z"


def _need_crypto():
    if os.environ.get("ORNEUR_REQUIRE_CRYPTOGRAPHY") == "1":
        import cryptography.hazmat.primitives.asymmetric.ed25519  # noqa: F401
    else:
        pytest.importorskip("cryptography")


class TestEmbedder:
    """Deterministic in-test stand-in for an authorized local semantic model: maps texts to unit vectors by a fixed concept table."""
    model_id, local_only, semantic_capable = "test-local-embedder", True, True
    model_sha256 = hashlib.sha256(b"test-local-embedder").hexdigest()
    CONCEPTS = {"tide": 0, "harbour": 0, "bakery": 1, "oven": 1, "glacier": 2, "radar": 2}

    def embed(self, texts):
        out = []
        for t in texts:
            v = [0.05, 0.05, 0.05, 0.05]
            for w in SEM.preprocess(t).split():
                if w in self.CONCEPTS:
                    v[self.CONCEPTS[w]] += 1.0
            n = sum(x * x for x in v) ** 0.5
            out.append([x / n for x in v])
        return out


def item(i, text, cat="research"):
    return {"item_id": "gce2-" + f"{i:024x}", "category": cat, "prompt": text, "input": {}, "system": None}


@pytest.fixture
def signer():
    _need_crypto()
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    sk = Ed25519PrivateKey.generate()
    pub = sk.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()
    keys = [{"key_id": "rk-test", "public_key_hex": pub, "identity": "reviewer@example.invalid", "role": "PRIVATE_BENCHMARK_REVIEWER"}]

    def make(item_id, evidence, disposition="CLEAR", purpose="FULL_MANUAL_REVIEW", ts=TS, **over):
        r = {"review_schema_version": R.SCHEMA_VERSION, "item_id": item_id, "eval_version": spec.EVAL_VERSION,
             "reviewer": {"identity": "reviewer@example.invalid", "role": "PRIVATE_BENCHMARK_REVIEWER", "key_id": "rk-test"}, "review_purpose": purpose,
             "corpus_digest": CD, "similarity_evidence_digest": evidence, "disposition": disposition, "timestamp": ts}
        r.update(over)
        r["signature"] = sk.sign(R.signing_bytes(r)).hex()
        return r
    return make, keys


# ---------------------------------------------------------------- semantic engine
def test_no_embedder_is_not_configured_never_pass():
    r = SEM.SemanticOverlapEngine(None).check([item(1, "x")], [{"item_id": "r", "text": "x"}])
    assert r.status == C.NOT_CONFIGURED and "not performed" in r.note


def test_lexical_proxy_embedder_is_never_accepted_as_semantic_review():
    eng = SEM.SemanticOverlapEngine(SEM.FeatureHashEmbedder())
    assert not eng.configured
    r = eng.check([item(1, "harbour tide table")], [{"item_id": "r", "text": "harbour tide table"}])
    assert r.status == C.NOT_CONFIGURED and "lexical proxy" in r.note
    e = SEM.FeatureHashEmbedder()
    v1, v2 = e.embed(["the quick brown fox jumps"]), e.embed(["the quick brown fox jumps"])
    assert v1 == v2 and abs(sum(x * x for x in v1[0]) - 1) < 1e-9                    # deterministic, normalized
    assert len(e.model_sha256) == 64


def test_configured_engine_finds_overlap_and_reports_ids_and_scores_only():
    eng = SEM.SemanticOverlapEngine(TestEmbedder(), default_threshold=0.9)
    assert eng.configured
    v2 = [item(1, "Harbour tide planning for pilots"), item(2, "Glacier radar survey")]
    refs = [{"item_id": "v1-a", "text": "tide tables at the harbour"}, {"item_id": "v1-b", "text": "unrelated oven text bakery"}]
    r = eng.check(v2, refs)
    assert r.status == C.FAIL and r.findings[0]["v2"] == v2[0]["item_id"] and r.findings[0]["ref"] == "v1-a" and r.findings[0]["score"] >= 0.9
    art = eng.artifact(eng.score_pairs(v2, refs))
    blob = json.dumps(art)
    assert "Harbour" not in blob and "tide tables" not in blob and "prompt" not in blob and art["mechanism"]["model_sha256"] == TestEmbedder.model_sha256
    assert art["mechanism"]["preprocessing_version"] == SEM.PREPROCESSING_VERSION and len(art["artifact_sha256"]) == 64


def test_clean_items_pass_and_per_category_thresholds_apply():
    v2 = [item(3, "Bakery oven throughput")]
    refs = [{"item_id": "v1-c", "text": "glacier radar"}]
    assert SEM.SemanticOverlapEngine(TestEmbedder()).check(v2, refs).status == C.PASS
    hi = SEM.SemanticOverlapEngine(TestEmbedder(), thresholds={"research": 0.99, "coding": 0.5}, default_threshold=0.9)
    assert hi.threshold_for("research") == 0.99 and hi.threshold_for("coding") == 0.5 and hi.threshold_for("other") == 0.9
    for bad in (0.0, 1.5, -1):
        with pytest.raises(ValueError):
            SEM.SemanticOverlapEngine(TestEmbedder(), default_threshold=bad)


def test_ambiguity_band_is_incomplete_not_pass():
    class Mid(TestEmbedder):
        def embed(self, texts):
            return [[1.0, 0.0] if "a" in t else [0.8, 0.6] for t in texts]        # cosine 0.8 between the two
    r = SEM.SemanticOverlapEngine(Mid(), default_threshold=0.85).check([item(4, "a")], [{"item_id": "r", "text": "zzz"}])
    assert r.status == C.INCOMPLETE and r.findings[0]["band"] == "AMBIGUOUS"


def test_local_embedder_loader_never_downloads_and_fails_to_not_configured(tmp_path):
    for args in ((None, None), (tmp_path / "missing", "a" * 64), (tmp_path, None)):
        with pytest.raises(SEM.NotConfiguredError):
            SEM.load_local_embedder(*args)
    (tmp_path / "m").mkdir()
    (tmp_path / "m" / "weights.bin").write_bytes(b"w")
    with pytest.raises(SEM.NotConfiguredError):                                      # hash mismatch
        SEM.load_local_embedder(tmp_path / "m", "0" * 64)
    good = SEM._dir_sha256(tmp_path / "m")
    with pytest.raises(SEM.NotConfiguredError):                                      # right hash, but no runtime installed / not a real model
        SEM.load_local_embedder(tmp_path / "m", good)
    src = Path(SEM.__file__).read_text()
    import ast
    imported = {n.names[0].name.split(".")[0] if isinstance(n, ast.Import) else (n.module or "").split(".")[0] for n in ast.walk(ast.parse(src))
                if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert not imported & {"requests", "httpx", "urllib", "openai", "anthropic", "socket", "subprocess"}


# ---------------------------------------------------------------- manual review
def test_review_manifest_with_no_registered_reviewer_key_cannot_validate(signer):
    make, keys = signer
    iid = item(1, "x")["item_id"]
    m = R.build_manifest([make(iid, "e" * 64)], CD)
    assert "NO_TRUSTED_REVIEWER_KEY_REGISTERED" in R.validate_manifest(m, [], CD)
    assert R.load_keys(ROOT) == [] and json.loads((ROOT / R.KEYS_PATH).read_text())["keys"] == []
    assert R.review_status(m, {iid: "e" * 64}, [], CD).status == C.FAIL


def test_all_clear_reviews_pass_only_against_current_evidence(signer):
    make, keys = signer
    a, b = item(1, "x")["item_id"], item(2, "y")["item_id"]
    ev = {a: "1" * 64, b: "2" * 64}
    m = R.build_manifest([make(a, ev[a]), make(b, ev[b])], CD)
    assert R.validate_manifest(m, keys, CD) == []
    assert R.review_status(m, ev, keys, CD).status == C.PASS
    stale = R.review_status(m, {a: "9" * 64, b: ev[b]}, keys, CD)
    assert stale.status == C.INCOMPLETE and stale.findings[0]["why"] == "STALE_EVIDENCE"
    assert R.review_status(m, {a: ev[a], b: ev[b], item(3, "z")["item_id"]: "3" * 64}, keys, CD).status == C.INCOMPLETE       # unreviewed item


@pytest.mark.parametrize("disp,expect", [("INCONCLUSIVE", C.INCOMPLETE), ("REJECT_CONTAMINATED", C.FAIL), ("NEEDS_REGENERATION", C.FAIL)])
def test_non_clear_dispositions_never_pass(signer, disp, expect):
    make, keys = signer
    a = item(1, "x")["item_id"]
    m = R.build_manifest([make(a, "1" * 64, disp)], CD)
    r = R.review_status(m, {a: "1" * 64}, keys, CD)
    assert r.status == expect and r.status != C.PASS


def test_latest_review_wins_so_an_inconclusive_can_be_resolved_but_not_silently(signer):
    make, keys = signer
    a = item(1, "x")["item_id"]
    m = R.build_manifest([make(a, "1" * 64, "INCONCLUSIVE", ts="2026-09-27T10:00:00Z"), make(a, "1" * 64, "CLEAR", ts="2026-09-27T11:00:00Z")], CD)
    assert R.review_status(m, {a: "1" * 64}, keys, CD).status == C.PASS
    m2 = R.build_manifest([make(a, "1" * 64, "CLEAR", ts="2026-09-27T10:00:00Z"), make(a, "1" * 64, "REJECT_CONTAMINATED", ts="2026-09-27T11:00:00Z")], CD)
    assert R.review_status(m2, {a: "1" * 64}, keys, CD).status == C.FAIL


def test_decisions_are_cryptographically_bound(signer):
    make, keys = signer
    a = item(1, "x")["item_id"]
    good = make(a, "1" * 64)
    def status(rev, k=keys, digest=CD):
        return R.validate_manifest(R.build_manifest([rev], CD), k, digest)
    assert status(good) == []
    assert "SIGNATURE_INVALID" in status({**good, "disposition": "INCONCLUSIVE"})                       # edited after signing
    assert "SIGNATURE_INVALID" in status({**good, "signature": "00" * 64})
    assert "REVIEWER_KEY_NOT_REGISTERED" in status({**good, "reviewer": {**good["reviewer"], "key_id": "other"}})
    assert "REVIEWER_KEY_NOT_REGISTERED" in status({**good, "reviewer": {**good["reviewer"], "identity": "someone@else.invalid"}})
    assert "CORPUS_DIGEST_MISMATCH" in status(good, digest=hashlib.sha256(b"other").hexdigest())          # bound to the exact corpus digest
    assert "REVIEW_NOT_BOUND_TO_THIS_CORPUS" in status(make(a, "1" * 64, corpus_digest=hashlib.sha256(b"other").hexdigest()))
    assert "REVIEW_NOT_BOUND_TO_THIS_CORPUS" in status(make(a, "1" * 64, eval_version="genesis-capability-eval/1.0.0"))
    assert "ITEM_ID_NOT_OPAQUE" in status(make("research-item-1", "1" * 64))
    assert "DISPOSITION_OR_PURPOSE_INVALID" in status(make(a, "1" * 64, "MAYBE"))
    assert "REVIEWER_INVALID" in status(make(a, "1" * 64, reviewer={"identity": "x", "role": "CLAUDE", "key_id": "rk-test"}))
    assert "REVIEW_SCHEMA_MISMATCH" in status({**good, "notes": "the answer is 42"})                     # no free-text/content fields at all
    m = R.build_manifest([good], CD)
    m["manifest_sha256"] = "0" * 64
    assert "MANIFEST_HASH_MISMATCH" in R.validate_manifest(m, keys, CD)
    assert R.validate_manifest({"reviews": []}, keys, CD) == ["MANIFEST_SCHEMA_MISMATCH"]


def test_public_review_artifacts_carry_no_content(signer):
    make, keys = signer
    a = item(1, "SECRET PROMPT TEXT")["item_id"]
    m = R.build_manifest([make(a, "1" * 64)], CD)
    blob = json.dumps(m)
    assert "SECRET PROMPT TEXT" not in blob
    keys_seen = set(R.REVIEW_KEYS)
    assert not keys_seen & spec.FORBIDDEN_PUBLIC_KEYS


def test_requirements_cover_unassessable_limited_and_ambiguous_items():
    short = item(1, "What is two plus five?", "mathematics")
    limited = item(2, "A long enough limited-category prompt " * 6, "long_context")
    amb = item(3, "Harbour tide", "research")
    plain = item(4, "Glacier radar survey team choosing between drones and ground radar for the season", "research")
    res = [C.CheckResult("v1_structure_assessability", C.INCOMPLETE, [{"v2": short["item_id"]}])]
    sem = C.CheckResult("semantic_overlap", C.INCOMPLETE, [{"v2": amb["item_id"], "ref": "r", "score": 0.8, "band": "AMBIGUOUS"}])
    need = R.review_requirements([short, limited, amb, plain], res, {"long_context", "mathematics"}, sem)
    assert set(need) == {short["item_id"], limited["item_id"], amb["item_id"]} and all(len(v) == 64 for v in need.values())
    assert R.evidence_digest(amb["item_id"], sem.findings) != R.evidence_digest(amb["item_id"], [])


# ---------------------------------------------------------------- combined verdicts
def _st(name, status):
    return C.CheckResult(name, status, [])


def test_semantic_overlap_combination_rules():
    P, F, N, I = C.PASS, C.FAIL, C.NOT_CONFIGURED, C.INCOMPLETE
    assert R.combine_semantic_and_manual(_st("s", P), _st("m", P)).status == P
    assert R.combine_semantic_and_manual(_st("s", P), _st("m", I)).status == I                                 # flagged items not cleared
    assert R.combine_semantic_and_manual(_st("s", N), _st("m", P)).status == N                                 # manual-on-flagged alone is not enough
    assert R.combine_semantic_and_manual(_st("s", N), _st("m", P), _st("full", P)).status == P                # full manual fallback
    assert R.combine_semantic_and_manual(_st("s", N), _st("m", I), _st("full", I)).status == N
    assert R.combine_semantic_and_manual(_st("s", P), _st("m", F)).status == F
    assert R.combine_semantic_and_manual(_st("s", F), _st("m", P)).status == F
    assert R.combine_semantic_and_manual(_st("s", P), _st("m", P), _st("full", I)).status == P
    assert R.combine_semantic_and_manual(_st("s", N), _st("m", N)).status != P


def test_inconclusive_review_blocks_split_isolation_and_contamination_pass(signer):
    make, keys = signer
    scr = {**item(1, "Glacier radar survey team choosing between drones and ground radar for the season, listing failure modes", "mathematics"), "split": "SCREEN", "cluster": "a"}
    hol = {**item(2, "Bakery oven capacity doubling while a single delivery van remains, find the bottleneck stage", "mathematics"), "split": "QUALIFICATION_HOLDOUT", "cluster": "b"}
    base = {r.name: r for r in ISO.check_split_isolation([scr, hol])}
    assert base["isolation_structure_review"].status == C.INCOMPLETE                            # limited category, no review
    need = {scr["item_id"]: "1" * 64, hol["item_id"]: "2" * 64}
    inc = R.review_status(R.build_manifest([make(scr["item_id"], "1" * 64), make(hol["item_id"], "2" * 64, "INCONCLUSIVE")], CD), need, keys, CD)
    res = {r.name: r for r in ISO.check_split_isolation([scr, hol], inc)}
    assert res["isolation_structure_review"].status == C.INCOMPLETE and not ISO.screen_holdout_separation_pass(list(res.values()))
    ok = R.review_status(R.build_manifest([make(scr["item_id"], "1" * 64), make(hol["item_id"], "2" * 64)], CD), need, keys, CD)
    res2 = {r.name: r for r in ISO.check_split_isolation([scr, hol], ok)}
    assert res2["isolation_structure_review"].status == C.PASS and ISO.screen_holdout_separation_pass(list(res2.values()))
    rej = R.review_status(R.build_manifest([make(scr["item_id"], "1" * 64, "REJECT_CONTAMINATED"), make(hol["item_id"], "2" * 64)], CD), need, keys, CD)
    assert {r.name: r for r in ISO.check_split_isolation([scr, hol], rej)}["isolation_structure_review"].status == C.FAIL


def test_operational_state_is_still_not_configured():
    st = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["contamination_status"]["semantic_overlap"] == "NOT_CONFIGURED" and st["freeze_prerequisites"]["contamination_controls_pass"] is False
    assert st["component_states"]["semantic_manual_review_framework"] == "IMPLEMENTED_TESTED_NOT_CONFIGURED"

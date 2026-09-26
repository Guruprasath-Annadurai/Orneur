"""Genesis Capability Eval V2 — private-holdout security correction. Ephemeral in-test secrets only; no real private corpus exists."""
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from orca.eval.genesis_v2 import ledger as L
from orca.eval.genesis_v2 import manifest as M
from orca.eval.genesis_v2 import privacy_scan as P
from orca.eval.genesis_v2 import secret as S
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2 import store as ST

ROOT = Path(__file__).resolve().parents[1]
PH = ROOT / "docs/orneur/phase-21"
SECRET = os.urandom(32)


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- 1. V1 compromise record
def test_v1_status_record_is_correct_and_pins_unmodified_v1():
    d = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json").read_text())
    assert d["GENESIS_CAPABILITY_EVAL_V1_FROZEN"] is False
    assert d["GENESIS_CAPABILITY_EVAL_V1_PRIVATE_HOLDOUT_VALID"] is False
    assert d["reason"] == "PUBLIC_REPOSITORY_EXPOSURE"
    assert d["permitted_use"] == "PUBLIC_DEVELOPMENT_BENCHMARK_ONLY"
    assert d["exposure"]["deleting_files_restores_secrecy"] is False and d["exposure"]["history_rewritten"] is False
    body = {k: v for k, v in d.items() if k != "record_sha256"}
    assert hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest() == d["record_sha256"]
    h = d["v1_hashes_unmodified"]
    assert h["preregistration_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION.json")
    assert h["dataset_manifest_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_MANIFEST.json")
    assert h["holdout_manifest_file_sha256"] == sha(PH / "GENESIS_CAPABILITY_EVAL_V1_HOLDOUT_MANIFEST.json")
    for rel, digest in d["exposed_files_sha256"].items():
        assert sha(ROOT / rel) == digest, rel                      # exposure is pinned; V1 files untouched
    tracked = set(subprocess.run(["git", "ls-files", "eval_private"], cwd=ROOT, capture_output=True, text=True).stdout.split())
    assert tracked == set(d["exposed_files_sha256"])


def test_v1_evidence_is_refused_for_v2():
    for rec in ({"eval_version": "genesis-capability-eval/1.0.0"}, {"split": "HOLDOUT"}, {"item_id": "gce1-reasoning-h0001"}):
        with pytest.raises(L.AccessDenied) as e:
            L.reject_v1_evidence(rec)
        assert e.value.code == "V1_EVIDENCE_REFUSED"
    L.reject_v1_evidence({"eval_version": spec.EVAL_VERSION, "split": "QUALIFICATION_HOLDOUT"})


# ---------------------------------------------------------------- 12. not frozen; state
def test_v2_not_frozen_and_status_truthful():
    assert spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False
    assert spec.freeze_status({p: True for p in spec.FREEZE_PREREQUISITES})["frozen"] is False   # constant is the committed state
    assert spec.freeze_status()["missing_prerequisites"] == list(spec.FREEZE_PREREQUISITES)
    st = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert st["GENESIS_CAPABILITY_EVAL_V2_FROZEN"] is False and st["private_storage_state"] == "NOT_CONFIGURED"
    assert st["private_corpus_generated"] is False and st["private_corpus_committed"] is False and st["foundation_selected"] is None
    assert not any(st["freeze_prerequisites"].values()) and not any(st["authorizations"].values())
    assert st["eval_version"] == "genesis-capability-eval/2.0.0"


def test_split_taxonomy_and_stage_mapping():
    assert spec.SPLITS == ("DEV", "PILOT_TRAIN", "SCREEN", "QUALIFICATION_HOLDOUT")
    assert spec.STAGE_SPLIT == {"STAGE_1": "SCREEN", "STAGE_2": "QUALIFICATION_HOLDOUT"}
    assert set(spec.PRIVATE_SPLITS).isdisjoint(spec.PUBLIC_SPLITS)


def test_public_design_manifest_has_no_corpus_and_validates():
    m = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V2_PUBLIC_MANIFEST.json").read_text())
    assert m["corpus_generated"] is False and m["splits"] == {} and m["aggregate_sha256"] is None
    M.validate_public_manifest(m)


# ---------------------------------------------------------------- 4. storage boundary
def test_no_store_is_default_and_fails_closed():
    s = ST.NoStore()
    assert s.describe()["configured"] is False
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.read_split("QUALIFICATION_HOLDOUT")
    with pytest.raises(ST.PrivateStorageNotConfigured):
        s.write_split("SCREEN", b"x")


def test_preflight_reports_exact_owner_setup_when_unconfigured():
    r = ST.owner_setup_preflight({})
    assert r["status"] == "PRIVATE_STORAGE_NOT_CONFIGURED"
    assert {m["item"] for m in r["missing"]} >= {spec.STORE_ENV, spec.SECRET_ENV}
    r2 = ST.owner_setup_preflight({spec.STORE_ENV: f"PRIVATE_GITHUB_REPO:{ST.PUBLIC_REPO_SLUG}", spec.STORE_TOKEN_ENV: "x", spec.SECRET_ENV: "00" * 32})
    assert any("must NOT be the public" in m["need"] for m in r2["missing"])
    assert any("invalid" in m["need"] for m in r2["missing"])          # zero secret rejected
    ok = ST.owner_setup_preflight({spec.STORE_ENV: "PRIVATE_OBJECT_STORE:s3://bucket/p", spec.STORE_TOKEN_ENV: "t", spec.SECRET_ENV: os.urandom(32).hex()})
    assert ok["missing"] == [] and "not proof" in ok["note"]


def test_encrypted_store_roundtrip_write_once_and_location_rules(tmp_path):
    pytest.importorskip("cryptography")
    key = os.urandom(32)
    with pytest.raises(ST.PrivateStorageViolation):
        ST.EncryptedFileStore(ROOT / "eval_private" / "x", key)          # inside the repo: refused
    with pytest.raises(ST.PrivateStorageViolation):
        ST.EncryptedFileStore(tmp_path, b"\x01" * 32)                     # low-entropy key
    st = ST.EncryptedFileStore(tmp_path / "vault", key)
    payload = b'{"private":"unit-test-payload"}'
    st.write_split("SCREEN", payload)
    assert st.read_split("SCREEN") == payload
    assert payload not in (tmp_path / "vault" / "SCREEN.enc").read_bytes()
    with pytest.raises(FileExistsError):
        st.write_split("SCREEN", b"other")                                # write-once
    with pytest.raises(ST.PrivateStorageViolation):
        st.write_split("DEV", b"x")                                       # public split not stored as private
    other = ST.EncryptedFileStore(tmp_path / "vault", os.urandom(32))
    with pytest.raises(Exception):
        other.read_split("SCREEN")                                        # wrong key


# ---------------------------------------------------------------- 5. secret generation
def test_secret_validation_rejects_weak_and_public_derivable():
    for bad in (b"", b"\x00" * 32, b"a" * 32, bytes(range(32)), (b"abcdefgh" * 4), os.urandom(16),
                hashlib.sha256(spec.EVAL_VERSION.encode()).digest(), hashlib.sha256(b"0").digest(), hashlib.sha256(b"137").digest(),
                spec.EVAL_VERSION.encode().ljust(32, b"!")[:32]):
        with pytest.raises(S.SecretEntropyError):
            S.validate_secret(bad)
    with pytest.raises(S.SecretEntropyError):
        S.validate_secret(hashlib.sha256(b"deadbeef").digest(), public_inputs=("deadbeef",))   # e.g. a public commit SHA
    assert S.validate_secret(os.urandom(32))


def test_no_secret_means_no_corpus_nothing_invented():
    with pytest.raises(S.SecretEntropyError):
        S.load_secret_from_env({})
    assert S.load_secret_from_env({spec.SECRET_ENV: SECRET.hex()}) == SECRET


def test_derivation_depends_on_secret_and_is_opaque():
    a, b = os.urandom(32), os.urandom(32)
    assert S.derive_item_seed(a, "reasoning", "SCREEN", 0) != S.derive_item_seed(b, "reasoning", "SCREEN", 0)
    assert S.derive_item_id(a, "reasoning", "SCREEN", 0) != S.derive_item_id(b, "reasoning", "SCREEN", 0)
    assert S.derive_item_seed(a, "reasoning", "SCREEN", 0) == S.derive_item_seed(a, "reasoning", "SCREEN", 0)
    ids = {S.derive_item_id(a, "reasoning", sp, i) for sp in spec.PRIVATE_SPLITS for i in range(50)}
    assert len(ids) == 100 and all(i.startswith("gce2-") and "reasoning" not in i for i in ids)
    # a public observer who knows index/version/split/category and every public formula cannot reproduce the derived values
    seed, iid = S.derive_item_seed(a, "reasoning", "SCREEN", 0), S.derive_item_id(a, "reasoning", "SCREEN", 0)
    for pub in (f"{spec.EVAL_VERSION}|reasoning|SCREEN|0", f"reasoning|SCREEN|0", "0", spec.EVAL_VERSION):
        assert int.from_bytes(hashlib.sha256(pub.encode()).digest(), "big") != seed
        assert "gce2-" + hashlib.sha256(pub.encode()).hexdigest()[:24] != iid
    with pytest.raises(S.SecretEntropyError):
        S.derive_item_seed(spec.EVAL_VERSION.encode().ljust(32, b"\x01"), "reasoning", "SCREEN", 0)   # public-string-based key refused


def test_v2_modules_never_use_predictable_rng():
    for p in (ROOT / "orca/eval/genesis_v2").glob("*.py"):
        t = p.read_text()
        assert "random.Random" not in t and "import random" not in t and "random.seed" not in t, p.name


# ---------------------------------------------------------------- 10. manifests, 7. separation
def _items(secret, n=6):
    out = []
    for sp in spec.PRIVATE_SPLITS:
        for i in range(n):
            iid = S.derive_item_id(secret, "reasoning", sp, i)
            out.append({"item_id": iid, "split": sp, "category": "reasoning", "difficulty": ("easy", "hard")[i % 2],
                        "cluster": f"{sp}-c{i % 3}", "prompt": f"unit-test synthetic prompt {sp} {i}", "ground_truth": {"a": i}})
    return out


def test_public_manifest_builds_validates_and_hides_content():
    items = _items(SECRET)
    m = M.build_public_manifest(items, SECRET)
    blob = json.dumps(m)
    assert "unit-test synthetic prompt" not in blob and "ground_truth" not in blob
    assert m["splits"]["SCREEN"]["item_count"] == 6 and m["splits"]["QUALIFICATION_HOLDOUT"]["item_count"] == 6
    assert M.verify_commitments(m, items, SECRET)
    assert not M.verify_commitments(m, items, os.urandom(32))
    # hiding: without the secret a dictionary guess of the canonical item does not match the commitment
    import hashlib as h
    guess = h.sha256(M.canonical_item(items[0]).encode()).hexdigest()
    assert guess not in blob
    tampered = [dict(items[0], prompt="changed")] + items[1:]
    assert not M.verify_commitments(m, tampered, SECRET)


@pytest.mark.parametrize("mut", ["prompt_key", "seed_key", "nonopaque_id", "extra_item_key", "dup_across_splits", "agg", "private_flag"])
def test_public_manifest_mutations_are_rejected(mut):
    import copy
    m = copy.deepcopy(M.build_public_manifest(_items(SECRET), SECRET))
    s, q = m["splits"]["SCREEN"], m["splits"]["QUALIFICATION_HOLDOUT"]
    if mut == "prompt_key":
        s["items"][0]["prompt"] = "x"
    elif mut == "seed_key":
        m["generator_seed"] = "ab" * 8
    elif mut == "nonopaque_id":
        s["items"][0]["id"] = "gce2-reasoning-0001"
    elif mut == "extra_item_key":
        s["items"][0]["ground_truth"] = 1
    elif mut == "dup_across_splits":
        q["items"][0] = dict(s["items"][0])
    elif mut == "agg":
        m["aggregate_sha256"] = "0" * 64
    elif mut == "private_flag":
        s["private_holdout"] = True
    with pytest.raises(M.ManifestViolation):
        M.validate_public_manifest(m)


def test_split_separation_and_v1_reuse_checks():
    items = _items(SECRET)
    assert M.check_split_separation(items)["pass"]
    leak = items + [dict(items[0], split="QUALIFICATION_HOLDOUT", item_id="gce2-" + "a" * 24)]     # same text in both splits
    assert not M.check_split_separation(leak)["pass"]
    same_id = items + [dict(items[0], split="QUALIFICATION_HOLDOUT", prompt="entirely different text")]   # same item id in both splits
    assert M.check_split_separation(same_id)["shared_ids"] == 1 and not M.check_split_separation(same_id)["pass"]
    assert M.check_split_separation(items)["shared_clusters"] == []
    fp = hashlib.sha256(b"unit test synthetic prompt screen 0").hexdigest()
    assert not M.check_no_v1_reuse(items, {fp}, set())["pass"]
    assert not M.check_no_v1_reuse(items, set(), {items[0]["item_id"]})["pass"]
    assert M.check_no_v1_reuse(items, set(), set())["pass"]


# ---------------------------------------------------------------- 8/9. ledger, write-once qualification
CODE = hashlib.sha256(b"registered-qualifier").hexdigest()
DIG = hashlib.sha256(b"corpus").hexdigest()
REG = {"qual": L.RegisteredProcess("qual", CODE, (spec.PURPOSE_QUALIFICATION, spec.PURPOSE_RETIREMENT), ("QUALIFICATION_HOLDOUT",)),
       "stage1": L.RegisteredProcess("stage1", CODE, (spec.PURPOSE_STAGE1,), ("SCREEN",))}
FROZEN = {"frozen": True}


def req(**kw):
    base = dict(process_id="qual", code_sha256=CODE, purpose=spec.PURPOSE_QUALIFICATION, split="QUALIFICATION_HOLDOUT",
                eval_version=spec.EVAL_VERSION, corpus_digest=DIG, run_id="run-1", candidate_revision="rev-a", candidate_lineage="lin-a",
                timestamp_utc="2026-09-27T00:00:00Z")
    base.update(kw)
    return L.AccessRequest(**base)


def code_of(fn, *a, **k):
    with pytest.raises(L.AccessDenied) as e:
        fn(*a, **k)
    return e.value.code


def test_ledger_denies_everything_until_frozen(tmp_path):
    led = L.AccessLedger(tmp_path, REG)                       # real committed state: not frozen
    assert code_of(led.request_access, req()) == "EVAL_NOT_FROZEN"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN")) == "EVAL_NOT_FROZEN"
    assert led.records() == []                                # a denial writes nothing that grants


def test_ledger_registered_process_and_purpose_rules(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert code_of(led.request_access, req(process_id="rogue")) == "PROCESS_NOT_PREREGISTERED"
    assert code_of(led.request_access, req(code_sha256="0" * 64)) == "CODE_HASH_MISMATCH"
    for purpose in spec.FORBIDDEN_PURPOSES:
        assert code_of(led.request_access, req(purpose=purpose)) == "FORBIDDEN_PURPOSE"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_QUALIFICATION)) == "PURPOSE_NOT_PERMITTED"
    assert code_of(led.request_access, req(process_id="stage1", purpose=spec.PURPOSE_STAGE1)) == "PURPOSE_NOT_PERMITTED"   # holdout not allowed for stage 1
    assert code_of(led.request_access, req(split="DEV")) == "NOT_A_PRIVATE_SPLIT"
    assert code_of(led.request_access, req(eval_version="genesis-capability-eval/1.0.0")) == "WRONG_EVAL_VERSION"
    assert code_of(led.request_access, req(corpus_digest="nothex")) == "BAD_CORPUS_DIGEST"
    assert code_of(led.request_access, req(run_id="")) == "MISSING_FIELD"
    assert code_of(led.request_access, req(timestamp_utc="")) == "MISSING_FIELD"
    assert led.records() == []


def test_ledger_record_contents_and_chain(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    r0 = led.request_access(req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN", run_id="s1"))
    r1 = led.request_access(req())
    for f in L.REQUIRED_FIELDS:
        assert r1[f] not in (None, "")
    assert r1["prev_hash"] == r0["record_hash"] and r0["prev_hash"] == L.GENESIS_HASH
    assert led.verify_chain() == 2
    p0 = tmp_path / "00000000.json"
    assert not os.access(p0, os.W_OK) or (p0.stat().st_mode & 0o222) == 0        # created read-only
    with pytest.raises(FileExistsError):
        fd = os.open(p0, os.O_CREAT | os.O_EXCL | os.O_WRONLY)                    # cannot be re-created
    os.chmod(p0, 0o644)
    d = json.loads(p0.read_text()); d["who"] = "someone-else"; p0.write_text(json.dumps(d))
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()


def test_ledger_detects_deleted_record(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    led.request_access(req(process_id="stage1", purpose=spec.PURPOSE_STAGE1, split="SCREEN", run_id="s1"))
    led.request_access(req())
    os.chmod(tmp_path / "00000000.json", 0o644)
    (tmp_path / "00000000.json").unlink()
    with pytest.raises(L.LedgerCorrupt):
        led.verify_chain()


def test_qualification_holdout_is_write_once_per_lineage_and_adaptation_needs_fresh_version(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_SEALED
    led.request_access(req())
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_OPENED
    assert code_of(led.request_access, req(run_id="run-2")) == "HOLDOUT_ALREADY_OPENED"                     # re-run / retry same lineage
    assert code_of(led.request_access, req(run_id="run-3", candidate_revision="rev-b")) == "HOLDOUT_ALREADY_OPENED"  # tuned revision, same lineage
    assert code_of(led.request_access, req(run_id="run-4", candidate_lineage="lin-b", candidate_revision="rev-c",
                                           derived_from_lineages=("lin-a",))) == "FRESH_HOLDOUT_VERSION_REQUIRED"
    led.request_access(req(run_id="run-5", candidate_lineage="lin-independent", candidate_revision="rev-z"))     # independent lineage: its own single run
    assert led.verify_chain() == 2


def test_results_are_write_once_and_ground_truth_only_after_retirement(tmp_path):
    led = L.AccessLedger(tmp_path, REG, freeze=FROZEN)
    assert code_of(led.request_access, req(purpose=spec.PURPOSE_RETIREMENT, run_id="r")) == "NOT_OPENED"          # cannot peek while sealed
    led.request_access(req())
    rd = hashlib.sha256(b"result").hexdigest()
    assert code_of(led.record_result, "unknown", rd, "t") == "UNKNOWN_RUN"
    led.record_result("run-1", rd, "2026-09-27T01:00:00Z")
    assert code_of(led.record_result, "run-1", rd, "t") == "RESULT_ALREADY_RECORDED"
    led.request_access(req(purpose=spec.PURPOSE_RETIREMENT, run_id="retire-1"))
    assert led.holdout_state(spec.EVAL_VERSION)["state"] == spec.STATE_RETIRED
    assert code_of(led.request_access, req(run_id="run-9", candidate_lineage="lin-new")) == "HOLDOUT_RETIRED"


# ---------------------------------------------------------------- 6. public-repo leak tests
def _repo(tmp_path, *, with_record=True):
    r = tmp_path / "repo"
    (r / "docs/orneur/phase-21").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    if with_record:
        shutil.copy(PH / "GENESIS_V2_REPOSITORY_RELEASE_MODE.json", r / P.RELEASE_MODE)
        rec = json.loads((PH / "GENESIS_CAPABILITY_EVAL_V1_STATUS_RECORD.json").read_text())
        rec["exposed_files_sha256"] = {}
        (r / P.STATUS_RECORD).write_text(json.dumps(rec))
    (r / "README.md").write_text("clean\n")
    return r


def _add(r, rel, content):
    p = r / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(content if isinstance(content, bytes) else content.encode())
    subprocess.run(["git", "add", "-f", rel], cwd=r, check=True)


def _rules(res):
    return {v["rule"] for v in res["violations"]}


def test_real_repository_has_no_private_corpus_tracked():
    """THE hard CI invariant: while the repository is public, no private qualification corpus / ground truth / secret seed is tracked or generated."""
    assert P.release_mode(ROOT) == "PUBLIC"
    res = P.scan_repository(ROOT)
    assert res["pass"], res["violations"][:10]
    assert res["mode"] == "PUBLIC" and res["scanned"] > 100 and res["v1_exposed_allowlisted"] == 71


def test_scanner_passes_a_clean_repo(tmp_path):
    assert P.scan_repository(_repo(tmp_path))["pass"]


LEAKS = {
    "private_corpus_path": ("eval_private/genesis_capability_eval_v2/qualification_holdout.jsonl", "{}\n"),
    "private_corpus_path2": ("data/x.enc", "abc"),
    "private_holdout_flag": ("data/items.jsonl", '{"item_id":"a","private_' + 'holdout": true}\n'),
    "private_split_content": ("docs/items.json", '[{"split":"QUALIFICATION_HOLDOUT","prompt":"p","ground_truth":{"a":1}}]'),
    "private_split_content2": ("docs/items2.json", '{"x":{"split":"SCREEN","answer":"42"}}'),
    "secret_generator_state_key": ("docs/g.json", '{"generator_seed": 5}'),
    "secret_generator_seed": ("notes/seed.txt", "master_" + "seed = 0123456789abcdef0123\n"),
    "corpus_secret_assignment": ("ci/env.sh", "ORNEUR_GENESIS_V2_CORPUS_" + "SECRET=abcdefghijklmnopqrstuvwxyz012345\n"),
    "unparseable_structured_file": ("docs/broken.json", "{not json"),
    "v1_style_holdout": ("eval_private/genesis_capability_eval_v1/holdout.jsonl", '{"split":"HOLDOUT","prompt":"p","ground_truth":1}\n'),
}


@pytest.mark.parametrize("name", sorted(LEAKS))
def test_scanner_fails_closed_on_each_leak_class(tmp_path, name):
    r = _repo(tmp_path)
    rel, content = LEAKS[name]
    _add(r, rel, content)
    res = P.scan_repository(r)
    assert not res["pass"] and res["violations"], name


def test_scanner_specific_rules_fire(tmp_path):
    r = _repo(tmp_path)
    for name in ("private_holdout_flag", "private_split_content", "secret_generator_state_key", "secret_generator_seed", "corpus_secret_assignment"):
        _add(r, *LEAKS[name])
    res = P.scan_repository(r)
    assert {"private_holdout_flag", "private_split_content", "secret_generator_state_key", "secret_generator_seed", "corpus_secret_assignment"} <= _rules(res)


def test_scanner_catches_untracked_and_generated_artifacts(tmp_path):
    r = _repo(tmp_path)
    (r / "out").mkdir()
    (r / "out" / "leak.json").write_text('{"private_' + 'holdout": true}')          # untracked generated artifact, not git-added
    (r / ".gitignore").write_text("out/\n")
    subprocess.run(["git", "add", ".gitignore"], cwd=r, check=True)
    res = P.scan_repository(r)
    assert not res["pass"] and any(v["file"].startswith("out/") for v in res["violations"])


def test_scanner_v1_allowlist_is_exact_hash_pinned(tmp_path):
    r = _repo(tmp_path)
    body = b'{"split":"HOLDOUT","prompt":"p","ground_truth":1,"private_' + b'holdout":true}\n'
    rel = "eval_private/genesis_capability_eval_v1/holdout.jsonl"
    _add(r, rel, body)
    rec = json.loads((r / P.STATUS_RECORD).read_text())
    rec["exposed_files_sha256"] = {rel: hashlib.sha256(body).hexdigest()}
    (r / P.STATUS_RECORD).write_text(json.dumps(rec))
    assert P.scan_repository(r)["pass"]                                     # exactly the recorded historical exposure is tolerated
    _add(r, rel, body + b"x")                                               # any change => violation
    assert "v1_exposed_file_modified" in _rules(P.scan_repository(r))
    _add(r, "eval_private/genesis_capability_eval_v1/new.jsonl", "{}\n")     # any NEW private path => violation
    assert "private_corpus_path" in _rules(P.scan_repository(r))


def test_scanner_fails_closed_on_errors_and_unknown_mode(tmp_path):
    r = _repo(tmp_path, with_record=False)                                   # missing status record
    res = P.scan_repository(r)
    assert not res["pass"] and _rules(res) == {"scan_error"}
    notgit = tmp_path / "nogit"
    notgit.mkdir()
    assert not P.scan_repository(notgit)["pass"]                             # git unavailable / not a repo
    r2 = _repo(tmp_path / "b")
    (r2 / P.RELEASE_MODE).write_text("garbage")                              # invalid mode file
    assert P.release_mode(r2, {}) == "PUBLIC"
    (r2 / P.RELEASE_MODE).write_text('{"repository_visibility":"MAYBE"}')
    assert P.release_mode(r2, {}) == "PUBLIC"
    (r2 / P.RELEASE_MODE).write_text('{"repository_visibility":"PRIVATE"}')  # claiming PRIVATE without out-of-band attestation is still PUBLIC
    assert P.release_mode(r2, {}) == "PUBLIC"
    assert P.release_mode(r2, {P.ATTEST_ENV: "1"}) == "PRIVATE"
    _add(r2, *LEAKS["private_holdout_flag"])
    assert not P.scan_repository(r2, env={})["pass"]


def test_release_mode_file_is_public_and_forbids_private_tracking():
    d = json.loads((PH / "GENESIS_V2_REPOSITORY_RELEASE_MODE.json").read_text())
    assert d["repository_visibility"] == "PUBLIC" and d["private_corpus_tracking_allowed"] is False


def test_status_record_tampering_is_detected_by_scanner(tmp_path):
    r = _repo(tmp_path)
    rec = json.loads((r / P.STATUS_RECORD).read_text())
    rec["GENESIS_CAPABILITY_EVAL_V1_PRIVATE_HOLDOUT_VALID"] = True
    (r / P.STATUS_RECORD).write_text(json.dumps(rec))
    assert _rules(P.scan_repository(r)) == {"scan_error"}


# ---------------------------------------------------------------- 13. Mariana placeholder + docs claims
def test_mariana_placeholder_is_design_only_with_required_disclaimer():
    t = (ROOT / "docs/orneur/intelligence/ORNEUR_MARIANA_INTELLIGENCE_EVAL.md").read_text()
    assert "DESIGN ONLY" in t and "not part of foundation selection" in t
    assert "does NOT establish ASI, god-mode capability or universal competence" in t
    for area in ("novel discovery", "scientific hypothesis generation", "hard falsification", "long-horizon planning", "repository-scale coding",
                 "cross-domain invention", "world-model revision", "unknown-unknown discovery", "adversarial evidence analysis",
                 "counterfactual simulation", "information acquisition", "persistent-objective reasoning", "self-correction",
                 "tool orchestration", "multi-step research", "robustness under ambiguity"):
        assert area in t, area


def test_v2_design_doc_states_contract():
    t = (PH / "GENESIS_CAPABILITY_EVAL_V2_DESIGN.md").read_text()
    for s in ("GENESIS_CAPABILITY_EVAL_V2_FROZEN = false", "not configured", "write-once", "fresh holdout version", "PUBLIC_REPOSITORY_EXPOSURE",
              "SCREEN", "QUALIFICATION_HOLDOUT", "Stage 1 only", "salted"):
        assert s in t, s

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
        (r / P.PUBLIC_SFT_CLASSIFICATION).write_text(json.dumps({"files": {}}))
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


# ---------------------------------------------------------------- hardened scanner rules (each has an adversarial leak case + a clean twin)
import io
import stat
import tarfile
import zipfile

CLEAN_TWINS = {
    "data/manifest.json": json.dumps({"eval_version": spec.EVAL_VERSION, "corpus_generated": False, "splits": {}, "aggregate_sha256": None,
                                      "public_manifest_contains_answers": False, "public_manifest_contains_prompts": False}),
    "docs/notes.md": "The reference to a solution is prose only.\n",
    ".env.example": "ORNEUR_GENESIS_V2_CORPUS_" + "SECRET=\n",
}


def test_scanner_clean_twins_do_not_false_positive(tmp_path):
    r = _repo(tmp_path)
    for rel, c in CLEAN_TWINS.items():
        _add(r, rel, c)
    assert P.scan_repository(r)["pass"], P.scan_repository(r)["violations"]


def _tar_bytes(name, data):
    b = io.BytesIO()
    with tarfile.open(fileobj=b, mode="w:gz") as t:
        ti = tarfile.TarInfo(name)
        ti.size = len(data)
        t.addfile(ti, io.BytesIO(data))
    return b.getvalue()


def _zip_bytes(name, data):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr(name, data)
    return b.getvalue()


LEAK_JSON = ('{"item_id":"gce2-' + "a" * 24 + '","split":"SCREEN","prompt":"p","ground_truth":{"a":1}}\n').encode()
NEW_RULE_CASES = {
    "v2_private_item_content": ("data/x.json", '{"item_id":"gce2-' + "b" * 24 + '","solution":"forty-two"}'),
    "private_split_content_alt_answer_key": ("data/y.json", '{"split":"QUALIFICATION_HOLDOUT","reference_answer":"x"}'),
    "private_split_content_alt_gold": ("data/y2.json", '{"split":"SCREEN","gold_answer":"x"}'),
    "private_split_content_hidden_tests": ("data/y3.json", '{"split":"SCREEN","hidden_tests":["assert f(1)==2"]}'),
    "secret_export_dotenv": (".env", "FOO=bar\n"),
    "secret_export_env_local": ("deploy/.env.production", "FOO=bar\n"),
    "secret_export_tfvars": ("infra/prod.tfvars", "x=1\n"),
    "secret_export_manager": ("ops/secret_manager_export.json", "{}"),
    "aes_key_assignment": ("notes/key.txt", "encryption_" + "key = " + "ab" * 32 + "\n"),
    "notebooks_data_unclassified": ("notebooks/data/anything.jsonl", '{"text":"x"}\n'),
    "notebooks_data_private_name": ("notebooks/data/qualification_items.jsonl", '{"text":"x"}\n'),
    "notebooks_data_screen": ("notebooks/data/screen_set.json", "{}"),
    "archive_targz": ("backup/logs.tar.gz", _tar_bytes("a/items.jsonl", LEAK_JSON)),
    "archive_zip": ("backup/dump.zip", _zip_bytes("items.jsonl", LEAK_JSON)),
    "archive_unscannable_7z": ("backup/dump.7z", b"7z\xbc\xaf\x27\x1c"),
    "base64_embedded": ("config/dump.txt", "blob: " + __import__("base64").b64encode(LEAK_JSON * 3).decode() + "\n"),
    "private_manifest_content": ("docs/m.json", json.dumps({"eval_version": spec.EVAL_VERSION, "corpus_generated": True, "public_manifest_contains_answers": False,
                                                          "public_manifest_contains_prompts": False, "aggregate_sha256": "0" * 64,
                                                          "splits": {"SCREEN": {"item_count": 1, "by_category": {"a": 1}, "items": [
                                                              {"id": "gce2-" + "c" * 24, "commitment": "d" * 64, "prompt": "leak"}]}}})),
    "plaintext_next_to_encrypted_a": ("vault/SCREEN.enc", b"\x00"),
}


@pytest.mark.parametrize("name", sorted(NEW_RULE_CASES))
def test_hardened_scanner_rule_fires(tmp_path, name):
    r = _repo(tmp_path)
    rel, content = NEW_RULE_CASES[name]
    _add(r, rel, content)
    res = P.scan_repository(r)
    assert not res["pass"] and res["violations"], name


def test_specific_rule_names_for_new_rules(tmp_path):
    r = _repo(tmp_path)
    for n in ("v2_private_item_content", "secret_export_dotenv", "aes_key_assignment", "notebooks_data_unclassified", "archive_targz", "archive_unscannable_7z",
              "base64_embedded", "private_manifest_content", "private_split_content_alt_answer_key"):
        _add(r, *NEW_RULE_CASES[n])
    got = _rules(P.scan_repository(r))
    assert {"v2_private_item_content", "secret_export_file", "aes_key_assignment", "unclassified_notebook_data", "unscannable_archive",
            "private_manifest_content", "private_split_content"} <= got
    assert any(x.startswith("base64_embedded_") for x in got)


def test_plaintext_beside_encrypted_artifact_detected(tmp_path):
    r = _repo(tmp_path)
    _add(r, "vault/SCREEN.enc", b"\x00")
    _add(r, "vault/screen_plain.txt", "hello")
    assert "plaintext_beside_encrypted" in _rules(P.scan_repository(r))


def test_notebooks_data_public_sft_is_distinguished_from_private_and_hash_pinned(tmp_path):
    r = _repo(tmp_path)
    body = b'{"text":"public sft record"}\n'
    rel = "notebooks/data/genesis_sft_v2_public_train.jsonl"
    _add(r, rel, body)
    cls = json.loads((r / P.PUBLIC_SFT_CLASSIFICATION).read_text())
    cls["files"][rel] = {"sha256": hashlib.sha256(body).hexdigest(), "classification": "PUBLIC_SFT", "may_be_qualification_evidence": False,
                         "is_genesis_capability_eval_v2": False}
    (r / P.PUBLIC_SFT_CLASSIFICATION).write_text(json.dumps(cls))
    assert P.scan_repository(r)["pass"]                                       # classified public SFT: allowed
    _add(r, rel, body + b'{"text":"changed"}\n')
    assert "public_sft_dataset_modified" in _rules(P.scan_repository(r))       # modified after classification: violation
    cls["files"][rel]["may_be_qualification_evidence"] = True
    (r / P.PUBLIC_SFT_CLASSIFICATION).write_text(json.dumps(cls))
    assert _rules(P.scan_repository(r)) == {"scan_error"}                     # a classification that claims qualification status is refused


def test_real_legacy_public_sft_files_are_classified_and_never_qualification_evidence():
    cls = json.loads((PH / "PUBLIC_SFT_DATASET_CLASSIFICATION.json").read_text())
    for rel, e in cls["files"].items():
        assert e["classification"] == "PUBLIC_SFT" and e["may_be_qualification_evidence"] is False and e["is_genesis_capability_eval_v2"] is False
        assert sha(ROOT / rel) == e["sha256"], rel                             # legacy files byte-identical
    assert {"notebooks/data/orneur_genesis_v2_train.jsonl", "notebooks/data/orneur_genesis_v2_eval.jsonl"} <= set(cls["files"])
    assert "NOT Genesis Capability Eval V2" in cls["files"]["notebooks/data/orneur_genesis_v2_eval.jsonl"]["legacy_name_note"]
    on_disk = {str(p.relative_to(ROOT)) for p in (ROOT / "notebooks/data").glob("*.jsonl")}
    assert on_disk == set(cls["files"])


def test_vault_dir_scan_permissions_and_plaintext(tmp_path):
    v = tmp_path / "vault"
    v.mkdir(mode=0o700)
    os.chmod(v, 0o700)
    good = v / "SEAL.enc"
    good.write_bytes(b"x")
    os.chmod(good, 0o400)
    assert P.scan_vault_dir(v)["pass"]
    os.chmod(good, 0o644)
    assert {x["rule"] for x in P.scan_vault_dir(v)["violations"]} == {"vault_file_permissions"}
    os.chmod(good, 0o400)
    (v / "corpus.jsonl").write_text("{}")
    os.chmod(v / "corpus.jsonl", 0o400)
    assert "plaintext_beside_encrypted" in {x["rule"] for x in P.scan_vault_dir(v)["violations"]}
    os.chmod(v, 0o755)
    assert "vault_dir_permissions" in {x["rule"] for x in P.scan_vault_dir(v)["violations"]}


def test_scanner_treats_oversized_or_corrupt_archives_as_violations(tmp_path):
    r = _repo(tmp_path)
    _add(r, "backup/broken.zip", b"PK\x03\x04 not really a zip")
    res = P.scan_repository(r)
    assert not res["pass"] and "unscannable_archive" in _rules(res)

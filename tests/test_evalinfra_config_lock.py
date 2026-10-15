"""Model + system configuration locking: canonical hash, immutable revisions, and refusal to record a result under a different configuration."""
import copy

import pytest

from orca.evalinfra import config_lock as CL
from orca.evalinfra import synthetic as SY
from orca.evalinfra.errors import ConfigMismatch, PreregViolation, SchemaViolation
from orca.evalinfra.results import RESULT_SCHEMA


def test_valid_config_hashes_deterministically_and_is_order_independent():
    c = SY.make_config("T2")
    h = CL.config_hash(c)
    assert len(h) == 64 and h == CL.config_hash(copy.deepcopy(c))
    assert h == CL.config_hash(dict(reversed(list(c.items()))))


@pytest.mark.parametrize("path,value", [
    (("model", "revision"), "f" * 40), (("tokenizer", "revision"), "e" * 40), (("model", "id"), "synthetic/other"), (("chat_template_sha256",), "1" * 64),
    (("decoding", "temperature"), 0.7), (("decoding", "max_new_tokens"), 1024), (("decoding", "top_p"), 0.9), (("system_prompt_sha256",), "2" * 64),
    (("tool_rag_kernel_config_sha256",), "3" * 64), (("code_sha",), "4" * 40), (("arm",), "T1")])
def test_every_component_changes_the_hash(path, value):
    base = SY.make_config("T2")
    c = copy.deepcopy(base)
    tgt = c
    for k in path[:-1]:
        tgt = tgt[k]
    tgt[path[-1]] = value
    if path == ("decoding", "temperature"):
        c["decoding"]["do_sample"] = True
    assert CL.config_hash(c) != CL.config_hash(base)


@pytest.mark.parametrize("mutate,code", [
    (lambda c: c.update(extra=1), "CONFIG_SCHEMA"), (lambda c: c.pop("code_sha"), "CONFIG_SCHEMA"),
    (lambda c: c["model"].update(revision="main"), "MUTABLE_OR_BAD_REVISION"), (lambda c: c["tokenizer"].update(revision="latest"), "MUTABLE_OR_BAD_REVISION"),
    (lambda c: c["model"].update(id="main"), "CONFIG_REF"), (lambda c: c.update(code_sha="HEAD"), "CONFIG_CODE_SHA"), (lambda c: c.update(chat_template_sha256="abc"), "CONFIG_HASH"),
    (lambda c: c["decoding"].update(extra=1), "CONFIG_DECODING"), (lambda c: c["decoding"].update(temperature=0.5), "CONFIG_DECODING"),   # greedy must be temperature 0
    (lambda c: c["decoding"].update(top_p=0), "CONFIG_DECODING"), (lambda c: c["decoding"].update(max_new_tokens=0), "CONFIG_DECODING"),
    (lambda c: c.update(arm="Z9"), "CONFIG_HEADER"), (lambda c: c.update(synthetic="yes"), "CONFIG_HEADER")])
def test_invalid_configs_refused(mutate, code):
    c = SY.make_config("B0")
    mutate(c)
    with pytest.raises(SchemaViolation) as e:
        CL.validate_config(c)
    assert e.value.code == code


def test_assert_config_matches():
    h = CL.config_hash(SY.make_config("B0"))
    CL.assert_config_matches(h, h, arm="B0")
    with pytest.raises(ConfigMismatch):
        CL.assert_config_matches(h, "0" * 64, arm="B0")
    with pytest.raises(ConfigMismatch):
        CL.assert_config_matches(h, "not-a-hash", arm="B0")


# ------------------------------------------------------------------------------------------------ binding into the result log
@pytest.fixture
def exp(tmp_path):
    """Frozen prereg + plan + dataset + locks recorded; NO results yet (fresh log built manually)."""
    from orca.evalinfra.leakage import LeakGuard
    from orca.evalinfra.results import EvalLog
    items = SY.make_items(21, (3, 10, 11, 12, 14, 15, 17), {"SCREEN": 2, "QUALIFICATION_HOLDOUT": 4, "DEV": 2, "TRAIN": 2})
    manifest = SY.make_manifest(items)
    prereg = SY.make_prereg(manifest)
    plan = SY.make_plan(prereg, (3, 10, 11, 12, 14, 15, 17))
    log = EvalLog(tmp_path / "log.jsonl", leak_guard=LeakGuard(items=items))
    log.record_dataset(manifest)
    log.freeze_prereg(prereg, allow_synthetic=True)
    log.freeze_plan(plan)
    cfg = SY.make_config("T2")
    log.lock_config(cfg)
    part = {p["split"]: p["partition_sha256"] for p in manifest["partitions"]}["QUALIFICATION_HOLDOUT"]

    def result(config=cfg, **over):
        r = {"schema_version": RESULT_SCHEMA, "run_id": "r1", "arm": "T2", "replicate": 0, "split": "QUALIFICATION_HOLDOUT", "synthetic": True,
             "provenance": {"code_sha": cfg["code_sha"], "config_hash": CL.config_hash(config), "dataset_commitment": part, "prereg_hash": prereg["record_sha256"]},
             "rows": SY.draw_outcomes(items, "QUALIFICATION_HOLDOUT", "T2", 0, 1)}
        r.update(over)
        return r
    return log, manifest, cfg, result


def test_result_under_the_locked_config_is_recorded(exp):
    log, manifest, cfg, result = exp
    assert log.record_result(result(), manifest=manifest)["kind"] == "RESULT"


@pytest.mark.parametrize("mutate", [
    lambda c: c["decoding"].update(do_sample=True, temperature=0.7), lambda c: c.update(system_prompt_sha256="9" * 64),
    lambda c: c["model"].update(revision="d" * 40), lambda c: c.update(tool_rag_kernel_config_sha256="8" * 64)])
def test_result_under_a_different_config_hash_is_refused(exp, mutate):
    log, manifest, cfg, result = exp
    other = copy.deepcopy(cfg)
    mutate(other)
    with pytest.raises(ConfigMismatch) as e:
        log.record_result(result(config=other), manifest=manifest)
    assert e.value.code == "CONFIG_HASH_MISMATCH"
    assert log.log.entries()[-1]["kind"] == "CONFIG_LOCK"                      # nothing was appended


def test_result_with_a_different_code_sha_is_refused_even_if_config_hash_matches(exp):
    log, manifest, cfg, result = exp
    r = result()
    r["provenance"]["code_sha"] = "5" * 40
    with pytest.raises(PreregViolation) as e:
        log.record_result(r, manifest=manifest)
    assert e.value.code == "CODE_SHA_MISMATCH"


def test_result_for_an_arm_without_a_lock_is_refused(exp):
    log, manifest, cfg, result = exp
    r = result(arm="B0")
    with pytest.raises(PreregViolation) as e:
        log.record_result(r, manifest=manifest)
    assert e.value.code == "CONFIG_NOT_LOCKED"


def test_a_lock_cannot_be_replaced_or_added_after_results(exp):
    log, manifest, cfg, result = exp
    changed = copy.deepcopy(cfg)
    changed["decoding"]["max_new_tokens"] = 99
    with pytest.raises(PreregViolation) as e:
        log.lock_config(changed)
    assert e.value.code == "CONFIG_ALREADY_LOCKED"
    log.record_result(result(), manifest=manifest)
    with pytest.raises(PreregViolation) as e:
        log.lock_config(SY.make_config("B0"))
    assert e.value.code == "CONFIG_LOCK_AFTER_RESULTS"

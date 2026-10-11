"""Immutable result manifest: one append-only, content-addressed, hash-chained log carrying the whole provenance story of an evaluation.

Entry kinds, in the only order they can validly appear:
  DATASET_COMMITMENT   public manifest hash + per-split partition hashes (never items' content)
  PREREG_FROZEN        record_sha256 of a FROZEN preregistration (refused if the prereg is not frozen/valid)
  ANALYSIS_PLAN_FROZEN plan_sha256 of a valid analysis plan bound to that prereg
  CONFIG_LOCK          per-arm configuration hash (model/tokenizer/template/decoding/system prompt/tool-RAG-kernel/code SHA)
  RESULT               per-(arm, replicate, split) item scores + provenance {code_sha, config_hash, dataset_commitment, prereg_hash}

A RESULT is REFUSED unless: its schema is exact (no free text field exists), the leak guard finds nothing, the prereg+plan are chained before it, its
config hash equals the arm's locked hash, its code SHA equals the locked configuration's code SHA, its prereg hash equals the chained one, its dataset
commitment equals the chained partition hash, it covers EXACTLY the manifest's items of that split (no partial results), and (arm, replicate, split)
has not been recorded before. `verify_log` re-checks all of this from the file alone (this is the engine behind the verification CLI).
"""
from __future__ import annotations

from orca.evalinfra import prereg_check as PC
from orca.evalinfra import schema as SC
from orca.evalinfra.canon import HEX40, is_hex64, is_int, is_num
from orca.evalinfra.chain import ChainLog
from orca.evalinfra.config_lock import assert_config_matches, config_hash, validate_config
from orca.evalinfra.errors import EvalInfraError, PreregViolation, SchemaViolation
from orca.evalinfra.leakage import LeakGuard
from orca.evalinfra.stats_paired import ARMS

KINDS = ("DATASET_COMMITMENT", "PREREG_FROZEN", "ANALYSIS_PLAN_FROZEN", "CONFIG_LOCK", "RESULT")
RESULT_SCHEMA = "orneur-evalinfra-result/1"
RESULT_KEYS = frozenset({"schema_version", "run_id", "arm", "replicate", "split", "synthetic", "provenance", "rows"})
PROVENANCE_KEYS = frozenset({"code_sha", "config_hash", "dataset_commitment", "prereg_hash"})
ROW_KEYS = frozenset({"item_id", "category", "score"})


def _first(entries, kind):
    return next((e for e in entries if e["kind"] == kind), None)


def validate_result_payload(r) -> dict:
    if not isinstance(r, dict) or set(r) != RESULT_KEYS:
        raise SchemaViolation("RESULT_SCHEMA", "exact keys " + str(sorted(RESULT_KEYS)))
    if r["schema_version"] != RESULT_SCHEMA or not (isinstance(r["run_id"], str) and r["run_id"]) or r["arm"] not in ARMS:
        raise SchemaViolation("RESULT_HEADER")
    if not is_int(r["replicate"]) or r["replicate"] < 0 or r["split"] not in SC.SPLITS or not isinstance(r["synthetic"], bool):
        raise SchemaViolation("RESULT_HEADER")
    pv = r["provenance"]
    if not isinstance(pv, dict) or set(pv) != PROVENANCE_KEYS:
        raise SchemaViolation("PROVENANCE_SCHEMA", "exact keys " + str(sorted(PROVENANCE_KEYS)))
    if not (isinstance(pv["code_sha"], str) and HEX40.match(pv["code_sha"])) or not all(is_hex64(pv[k]) for k in ("config_hash", "dataset_commitment", "prereg_hash")):
        raise SchemaViolation("PROVENANCE_VALUES", "code_sha 40-hex; config_hash/dataset_commitment/prereg_hash sha256 hex")
    if not isinstance(r["rows"], list) or not r["rows"]:
        raise SchemaViolation("RESULT_NO_ROWS")
    seen = set()
    for row in r["rows"]:
        if not isinstance(row, dict) or set(row) != ROW_KEYS:
            raise SchemaViolation("ROW_SCHEMA", "exact keys " + str(sorted(ROW_KEYS)))
        if row["item_id"] in seen:
            raise SchemaViolation("DUPLICATE_ROW", str(row["item_id"]))
        seen.add(row["item_id"])
        if not is_num(row["score"]) or not (0.0 <= row["score"] <= 1.0):
            raise SchemaViolation("ROW_SCORE", "score must be a finite number in [0, 1]")
    return r


class EvalLog:
    def __init__(self, path, *, leak_guard: LeakGuard):
        if not isinstance(leak_guard, LeakGuard):
            raise SchemaViolation("LEAK_GUARD_REQUIRED", "a LeakGuard must be supplied explicitly (an empty one is allowed; omitting it is not)")
        self.log = ChainLog(path, allowed_kinds=KINDS)
        self._guard = leak_guard

    # -- freezing steps ------------------------------------------------------------------------------------------------------------
    def record_dataset(self, manifest: dict) -> dict:
        SC.validate_manifest(manifest)
        es = self.log.entries()
        if _first(es, "DATASET_COMMITMENT") or _first(es, "RESULT"):
            raise PreregViolation("DATASET_ALREADY_RECORDED_OR_LATE", "the dataset commitment is recorded once, before any result")
        payload = {"manifest_sha256": manifest["manifest_sha256"], "eval_id": manifest["eval_id"], "eval_version": manifest["eval_version"],
                   "synthetic": manifest["synthetic"], "partitions": {p["split"]: {"partition_sha256": p["partition_sha256"], "item_count": p["item_count"]}
                                                                    for p in manifest["partitions"]}}
        return self.log.append("DATASET_COMMITMENT", payload)

    def freeze_prereg(self, prereg_doc: dict, *, schema_path=None, allow_synthetic: bool = False) -> dict:
        probs = PC.validate_prereg_document(prereg_doc, schema_path=schema_path, allow_synthetic=allow_synthetic, require_frozen=True)
        if probs:
            raise PreregViolation("PREREG_NOT_FROZEN_OR_INVALID", "; ".join(probs))
        es = self.log.entries()
        if _first(es, "PREREG_FROZEN") or _first(es, "RESULT"):
            raise PreregViolation("PREREG_ALREADY_FROZEN_OR_LATE")
        from orca.eval.genesis_v2 import prereg as V2P
        return self.log.append("PREREG_FROZEN", {"record_sha256": V2P.record_hash(prereg_doc), "frozen_at": prereg_doc["frozen_at"], "synthetic": allow_synthetic})

    def freeze_plan(self, plan: dict) -> dict:
        es = self.log.entries()
        pre = _first(es, "PREREG_FROZEN")
        if pre is None:
            raise PreregViolation("PREREG_REQUIRED_FIRST", "freeze the preregistration before the analysis plan")
        probs = PC.validate_analysis_plan(plan, expected_prereg_sha256=pre["payload"]["record_sha256"])
        if probs:
            raise PreregViolation("PLAN_INVALID", "; ".join(probs))
        if _first(es, "ANALYSIS_PLAN_FROZEN") or _first(es, "RESULT"):
            raise PreregViolation("PLAN_ALREADY_FROZEN_OR_LATE")
        return self.log.append("ANALYSIS_PLAN_FROZEN", {"plan_sha256": plan["plan_sha256"], "synthetic": plan["synthetic"]})

    def lock_config(self, cfg: dict) -> dict:
        validate_config(cfg)
        es = self.log.entries()
        if _first(es, "RESULT"):
            raise PreregViolation("CONFIG_LOCK_AFTER_RESULTS", "configurations are locked before the first result")
        if any(e["kind"] == "CONFIG_LOCK" and e["payload"]["arm"] == cfg["arm"] for e in es):
            raise PreregViolation("CONFIG_ALREADY_LOCKED", cfg["arm"])
        return self.log.append("CONFIG_LOCK", {"arm": cfg["arm"], "config_hash": config_hash(cfg), "code_sha": cfg["code_sha"], "config": cfg})

    # -- results -------------------------------------------------------------------------------------------------------------------
    def record_result(self, result: dict, *, manifest: dict) -> dict:
        validate_result_payload(result)
        self._guard.assert_clean(result)                                    # prompt/answer/canary/forbidden-key leakage => refuse
        SC.validate_manifest(manifest)
        es = self.log.entries()
        ds, pre, pln = _first(es, "DATASET_COMMITMENT"), _first(es, "PREREG_FROZEN"), _first(es, "ANALYSIS_PLAN_FROZEN")
        if ds is None or pre is None or pln is None:
            raise PreregViolation("PREREG_PLAN_DATASET_REQUIRED", "dataset commitment, frozen prereg and frozen analysis plan must be chained before any result")
        if ds["payload"]["manifest_sha256"] != manifest["manifest_sha256"]:
            raise PreregViolation("MANIFEST_NOT_THE_COMMITTED_ONE")
        lock = next((e for e in es if e["kind"] == "CONFIG_LOCK" and e["payload"]["arm"] == result["arm"]), None)
        if lock is None:
            raise PreregViolation("CONFIG_NOT_LOCKED", f"arm {result['arm']} has no locked configuration")
        pv = result["provenance"]
        assert_config_matches(lock["payload"]["config_hash"], pv["config_hash"], arm=result["arm"])
        if pv["code_sha"] != lock["payload"]["code_sha"]:
            raise PreregViolation("CODE_SHA_MISMATCH", "result code SHA differs from the locked configuration's code SHA")
        if pv["prereg_hash"] != pre["payload"]["record_sha256"]:
            raise PreregViolation("PREREG_HASH_MISMATCH")
        part = ds["payload"]["partitions"].get(result["split"])
        if part is None or pv["dataset_commitment"] != part["partition_sha256"]:
            raise PreregViolation("DATASET_COMMITMENT_MISMATCH", result["split"])
        if result["synthetic"] != ds["payload"]["synthetic"] or result["synthetic"] != lock["payload"]["config"]["synthetic"]:
            raise PreregViolation("SYNTHETIC_FLAG_MISMATCH", "synthetic and non-synthetic material must never be mixed in one log")
        want = {i["id"]: i["category"] for i in manifest["items"] if i["split"] == result["split"]}
        got = {r["item_id"]: r["category"] for r in result["rows"]}
        if got != want:
            raise PreregViolation("RESULT_DOES_NOT_COVER_SPLIT", "rows must cover exactly the manifest items of the split with the manifest's categories")
        key = (result["arm"], result["replicate"], result["split"])
        if any(e["kind"] == "RESULT" and (e["payload"]["arm"], e["payload"]["replicate"], e["payload"]["split"]) == key for e in es):
            raise PreregViolation("DUPLICATE_RESULT", f"{key} already recorded (results are append-only; there is no overwrite)")
        return self.log.append("RESULT", result)


# ------------------------------------------------------------------------------------------------------------------------------ verification
def verify_log(path, *, expected_head: dict | None = None) -> dict:
    """Independent verification from the file alone. Raises ChainCorrupt / PreregViolation on any problem; returns a summary."""
    es = ChainLog(path, allowed_kinds=KINDS).entries(expected_head)
    probs: list = []
    kinds = [e["kind"] for e in es]
    ds, pre, pln = _first(es, "DATASET_COMMITMENT"), _first(es, "PREREG_FROZEN"), _first(es, "ANALYSIS_PLAN_FROZEN")
    results = [e for e in es if e["kind"] == "RESULT"]
    for k in ("DATASET_COMMITMENT", "PREREG_FROZEN", "ANALYSIS_PLAN_FROZEN"):
        if kinds.count(k) > 1:
            probs.append(f"{k} appears more than once")
    if results:
        first = results[0]["seq"]
        for name, e in (("DATASET_COMMITMENT", ds), ("PREREG_FROZEN", pre), ("ANALYSIS_PLAN_FROZEN", pln)):
            if e is None or e["seq"] > first:
                probs.append(f"{name} missing or recorded after the first result")
        last_lock = max((e["seq"] for e in es if e["kind"] == "CONFIG_LOCK"), default=-1)
        if last_lock > first:
            probs.append("a CONFIG_LOCK was recorded after the first result")
    locks = {e["payload"]["arm"]: e["payload"] for e in es if e["kind"] == "CONFIG_LOCK"}
    for arm, lp in locks.items():
        try:
            if config_hash(lp["config"]) != lp["config_hash"] or lp["config"]["arm"] != arm or lp["config"]["code_sha"] != lp["code_sha"]:
                probs.append(f"CONFIG_LOCK for {arm} is internally inconsistent")
        except EvalInfraError as e:
            probs.append(f"CONFIG_LOCK for {arm} invalid: {e.code}")
    seen, synth = set(), set()
    for e in results:
        r = e["payload"]
        try:
            validate_result_payload(r)
        except EvalInfraError as ex:
            probs.append(f"seq {e['seq']}: {ex.code}")
            continue
        key = (r["arm"], r["replicate"], r["split"])
        if key in seen:
            probs.append(f"seq {e['seq']}: duplicate result {key}")
        seen.add(key)
        synth.add(r["synthetic"])
        lp = locks.get(r["arm"])
        if lp is None or lp["config_hash"] != r["provenance"]["config_hash"] or lp["code_sha"] != r["provenance"]["code_sha"]:
            probs.append(f"seq {e['seq']}: result config hash / code SHA differs from the locked one")
        if pre is None or r["provenance"]["prereg_hash"] != pre["payload"]["record_sha256"]:
            probs.append(f"seq {e['seq']}: prereg hash differs from the chained one")
        part = (ds or {"payload": {"partitions": {}}})["payload"]["partitions"].get(r["split"])
        if part is None or r["provenance"]["dataset_commitment"] != part["partition_sha256"]:
            probs.append(f"seq {e['seq']}: dataset commitment differs from the chained one")
        if ds is not None and r["synthetic"] != ds["payload"]["synthetic"]:
            probs.append(f"seq {e['seq']}: synthetic flag differs from the dataset's")
        for row in r["rows"]:
            for k in row:
                if k not in ROW_KEYS:
                    probs.append(f"seq {e['seq']}: unexpected row field")
    if len(synth) > 1:
        probs.append("synthetic and non-synthetic results are mixed in one log")
    if probs:
        raise PreregViolation("LOG_VERIFICATION_FAILED", "; ".join(probs))
    head = {"seq": len(es) - 1, "entry_hash": es[-1]["entry_hash"]} if es else {"seq": -1, "entry_hash": "0" * 64}
    return {"ok": True, "entries": len(es), "results": len(results), "arms_locked": sorted(locks), "head": head, "synthetic": sorted(synth) == [True],
            "mixed_synthetic_and_real": len(synth) > 1, "kinds": {k: kinds.count(k) for k in KINDS}}

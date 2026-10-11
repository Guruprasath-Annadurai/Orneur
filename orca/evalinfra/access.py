"""Protected-evaluation access gate: composes the EXISTING orca.eval.genesis_v2 gates and adds the checks they do not have (replay, revocation, ledger anchor,
reviewer sufficiency, dataset-commitment binding). EVERY check runs; ANY failure denies; an unexpected exception denies.

Composed (not re-implemented):
  runner registry  : orca.eval.genesis_v2.runner_registry  (state must be AUTHORIZED, code hash, allowed purposes/splits)
  authority        : orca.eval.genesis_v2.authorization.verify (Ed25519 signature by an ACTIVE, un-revoked, un-expired authority key; exact request fields)
                     + authority_registry.authority_for_request (scope)
  reviewers        : orca.eval.genesis_v2.review.validate_manifest (signed CLEAR reviews bound to the corpus digest) + reviewer_registry (+ separation of duties)
  vault/secret     : orca.eval.genesis_v2.store.verifier_setup_preflight (presence/shape of the runner-side configuration; values are never read or returned)
  ledger           : orca.eval.genesis_v2.ledger.AccessLedger (hash-chained; write-once lifecycle; EVAL_NOT_FROZEN unless the V2 freeze evidence exists)
Added here: authorization replay protection (hash-chained consumption log), explicit revocation list (unavailable list => deny), a REQUIRED externally
anchored ledger head (truncation is otherwise undetectable), dataset-commitment equality, and grant re-verification against the ledger on every read.

The gate NEVER reads the repository's real registries unless the caller points `root` at them; tests use synthetic registries in temp directories.
With the repository's committed state (no authorized runner, NOT_AUTHORIZED authorization, zero reviewer keys, V2 not frozen) every request is denied.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from orca.eval.genesis_v2 import authority_registry as AR
from orca.eval.genesis_v2 import authorization as A
from orca.eval.genesis_v2 import ledger as LG
from orca.eval.genesis_v2 import review as RV
from orca.eval.genesis_v2 import reviewer_registry as RR
from orca.eval.genesis_v2 import runner_registry as RN
from orca.eval.genesis_v2 import spec
from orca.eval.genesis_v2 import store as ST
from orca.evalinfra.canon import is_hex64
from orca.evalinfra.chain import ChainLog
from orca.evalinfra.errors import AccessDeniedError, ChainCorrupt

REPLAY_KINDS = ("AUTH_CONSUMED",)


@dataclass(frozen=True)
class ProtectedAccessRequest:
    runner_id: str
    code_sha256: str
    purpose: str                    # ledger purpose (spec.PURPOSE_*)
    split: str                      # ledger split (spec.PRIVATE_SPLITS)
    corpus_digest: str
    run_id: str
    candidate_model_id: str
    candidate_revision: str
    candidate_lineage: str
    commit_sha: str
    authorization_purpose: str      # authorization.PURPOSES vocabulary
    stage: str                      # authorization.STAGES
    runner_class: str               # authorization.RUNNER_CLASSES
    timestamp_utc: str
    event_name: str = "workflow_dispatch"
    eval_version: str = spec.EVAL_VERSION
    authorization_record: dict | None = None
    reviewer_manifest: dict | None = None
    derived_from_lineages: tuple = ()


@dataclass(frozen=True)
class Grant:
    run_id: str
    split: str
    corpus_digest: str
    ledger_seq: int
    ledger_record_hash: str
    authorization_id: str
    runner_id: str
    ledger_head_after: dict


def _load_json(path: Path):
    return json.loads(path.read_text())


class ProtectedEvalGate:
    def __init__(self, root, ledger_dir, replay_log, *, env: dict | None = None, expected_corpus_digest: str | None = None,
                 revoked_authorization_ids=None, freeze: dict | None = None, now: datetime | None = None,
                 expected_ledger_head: dict | None = None, min_clear_reviewers: int = 1):
        self._root, self._ledger_dir = Path(root), Path(ledger_dir)
        self._replay = ChainLog(replay_log, allowed_kinds=REPLAY_KINDS)
        self._env = {} if env is None else dict(env)            # never defaults to os.environ: callers must pass what the runner really has
        self._expected_digest = expected_corpus_digest
        self._revoked = None if revoked_authorization_ids is None else set(revoked_authorization_ids)
        self._freeze = freeze if freeze is not None else spec.freeze_status()
        self._now = now
        self.anchor = expected_ledger_head
        self._min_reviewers = min_clear_reviewers

    # -- helpers -------------------------------------------------------------------------------------------------------------------
    def _stage(self, reasons: list, name: str, fn):
        try:
            fn()
        except Exception as e:                                  # fail closed on ANY unexpected error in a gate
            reasons.append(f"{name}_ERROR:{type(e).__name__}")

    def _registries(self) -> dict:
        out = {}
        for key, rel, loader in (("authority", AR.REGISTRY_PATH, AR.load), ("reviewer", RR.REGISTRY_PATH, RR.load)):
            doc, probs = loader(self._root / rel)
            out[key] = (doc, probs)
        try:
            rdoc = _load_json(self._root / RN.REGISTRY_PATH)
            out["runner"] = (rdoc, RN.validate(rdoc))
        except Exception as e:
            out["runner"] = (None, [f"unreadable: {type(e).__name__}"])
        return out

    def _ledger(self) -> LG.AccessLedger:
        rdoc, probs = self._registries()["runner"]
        procs = RN.to_ledger_registered_processes(rdoc) if rdoc is not None and not probs else {}
        return LG.AccessLedger(self._ledger_dir, procs, freeze=self._freeze)

    # -- the gate ------------------------------------------------------------------------------------------------------------------
    def evaluate(self, req: ProtectedAccessRequest) -> list:
        """All failed checks as stable reason codes. Empty list == every pre-check passed (the ledger append is a separate, final step)."""
        r: list = []
        regs = self._registries()

        def runner():
            doc, probs = regs["runner"]
            if doc is None or probs:
                r.append("RUNNER_REGISTRY_UNAVAILABLE")
                return
            rec = next((x for x in doc["records"] if x.get("runner_id") == req.runner_id), None)
            if rec is None:
                r.append("RUNNER_NOT_REGISTERED")
                return
            if rec["state"] != "AUTHORIZED":
                r.append(f"RUNNER_NOT_AUTHORIZED:{rec['state']}")
            if rec["code_sha256"] != req.code_sha256:
                r.append("RUNNER_CODE_MISMATCH")
            if req.purpose not in rec["allowed_purposes"] or req.split not in rec["allowed_splits"]:
                r.append("RUNNER_SCOPE_MISMATCH")
        self._stage(r, "RUNNER", runner)

        def authority():
            doc, probs = regs["authority"]
            if doc is None or probs:
                r.append("AUTHORITY_REGISTRY_UNAVAILABLE")
                return
            rec = req.authorization_record
            if rec is None:
                r.append("AUTHORIZATION_MISSING")
                return
            now = self._now or datetime.now(timezone.utc)
            import orca.eval.genesis_v2.identity_registry as ID
            keys = [{"key_id": x["id"], "public_key_hex": x["public_key_hex"], "identity": x["id"], "role": x["role"]} for x in doc["records"] if ID.is_active(x, now)]
            verdict = A.verify(rec, A.Request(commit_sha=req.commit_sha, eval_version=req.eval_version, candidate_model_id=req.candidate_model_id,
                                              candidate_revision=req.candidate_revision, stage=req.stage, runner_class=req.runner_class,
                                              purpose=req.authorization_purpose, event_name=req.event_name), keys, now)
            r.extend(f"AUTHORIZATION:{x}" for x in verdict.reasons)
            if verdict.authorized:
                kid = rec["authorizing_authority"]["key_id"]
                scoped = AR.authority_for_request(doc, authorization_class=req.authorization_purpose, stage=req.stage, gpu=False, spend=False, provider_inference=False)
                if kid not in {x["id"] for x in scoped}:
                    r.append("AUTHORITY_SCOPE_MISMATCH")
                aid = rec["authorization_id"]
                if self._revoked is None:
                    r.append("REVOCATION_LIST_UNAVAILABLE")
                elif aid in self._revoked:
                    r.append("AUTHORIZATION_REVOKED")
                used = [e["payload"] for e in self._replay.entries() if e["payload"]["authorization_id"] == aid]
                if len(used) >= rec["max_runs"] or any(u["run_id"] == req.run_id for u in used):
                    r.append("AUTHORIZATION_REPLAYED")
        try:
            authority()
        except ChainCorrupt:
            r.append("REPLAY_LOG_CORRUPT")
        except Exception as e:
            r.append(f"AUTHORITY_ERROR:{type(e).__name__}")

        def reviewers():
            doc, probs = regs["reviewer"]
            if doc is None or probs:
                r.append("REVIEWER_REGISTRY_UNAVAILABLE")
                return
            keys = RR.active_reviewer_keys(doc)
            if not keys:
                r.append("NO_ACTIVE_REVIEWER")
            if req.reviewer_manifest is None:
                r.append("REVIEW_MANIFEST_MISSING")
                return
            problems = RV.validate_manifest(req.reviewer_manifest, keys, req.corpus_digest)
            r.extend(f"REVIEW_MANIFEST_INVALID:{x}" for x in problems)
            if not problems:
                reviews = req.reviewer_manifest["reviews"]
                if any(x["disposition"] != "CLEAR" for x in reviews):
                    r.append("REVIEW_NOT_CLEAR")
                if len({x["reviewer"]["identity"] for x in reviews if x["disposition"] == "CLEAR"}) < self._min_reviewers:
                    r.append("REVIEWS_INSUFFICIENT")
            adoc, aprobs = regs["authority"]
            if adoc is not None and not aprobs and RR.check_separation_of_duties(adoc, doc):
                r.append("DUAL_ROLE_VIOLATION")
        self._stage(r, "REVIEWER", reviewers)

        if self._expected_digest is None or not is_hex64(self._expected_digest):
            r.append("DATASET_COMMITMENT_UNAVAILABLE")
        elif req.corpus_digest != self._expected_digest:
            r.append("DATASET_COMMITMENT_MISMATCH")

        def vault():
            pf = ST.verifier_setup_preflight(self._env)
            if pf["status"] != "VERIFIER_CONFIGURED_UNVERIFIED":
                r.append("SECRET_OR_STORE_UNAVAILABLE")
        self._stage(r, "VAULT", vault)

        if req.purpose in (spec.PURPOSE_QUALIFICATION, spec.PURPOSE_STAGE1) and not self._freeze.get("frozen"):
            r.append("EVAL_NOT_FROZEN")           # pre-checked here so a ledger refusal never burns an authorization use

        def ledger():
            if self.anchor is None:
                r.append("LEDGER_ANCHOR_UNAVAILABLE")
                return
            self._ledger().verify_chain(self.anchor)
        try:
            ledger()
        except LG.LedgerCorrupt as e:
            r.append(f"LEDGER_TAMPERED:{e}")
        except Exception as e:
            r.append(f"LEDGER_ERROR:{type(e).__name__}")
        return r

    def authorize(self, req: ProtectedAccessRequest) -> Grant:
        reasons = self.evaluate(req)
        if reasons:
            raise AccessDeniedError(reasons)
        aid = req.authorization_record["authorization_id"]
        try:
            self._replay.append("AUTH_CONSUMED", {"authorization_id": aid, "run_id": req.run_id})        # consume FIRST: a crash burns the use, never grants twice
            led = self._ledger()
            rec = led.request_access(LG.AccessRequest(
                process_id=req.runner_id, code_sha256=req.code_sha256, purpose=req.purpose, split=req.split, eval_version=req.eval_version,
                corpus_digest=req.corpus_digest, run_id=req.run_id, candidate_revision=req.candidate_revision, candidate_lineage=req.candidate_lineage,
                derived_from_lineages=tuple(req.derived_from_lineages), timestamp_utc=req.timestamp_utc))
            head = led.head_anchor()
        except LG.AccessDenied as e:
            raise AccessDeniedError([f"LEDGER:{e.code}"]) from e
        except Exception as e:
            raise AccessDeniedError([f"GATE_ERROR:{type(e).__name__}"]) from e
        self.anchor = head
        return Grant(req.run_id, req.split, req.corpus_digest, rec["seq"], rec["record_hash"], aid, req.runner_id, head)

    def check_grant(self, grant, *, split: str, corpus_digest: str) -> list:
        """Re-verifies a grant against the ledger at USE time (a grant object alone is never authority)."""
        r: list = []
        if not isinstance(grant, Grant):
            return ["GRANT_MISSING"]
        if grant.split != split or grant.corpus_digest != corpus_digest:
            r.append("GRANT_SCOPE_MISMATCH")
        if self.anchor is None:
            return r + ["LEDGER_ANCHOR_UNAVAILABLE"]
        try:
            led = self._ledger()
            led.verify_chain(self.anchor)
            rec = led.get_grant(grant.run_id)
            if rec is None:
                r.append("LEDGER_ENTRY_MISSING")
            elif rec["record_hash"] != grant.ledger_record_hash:
                r.append("LEDGER_ENTRY_MISMATCH")
        except LG.LedgerCorrupt as e:
            r.append(f"LEDGER_TAMPERED:{e}")
        except Exception as e:
            r.append(f"LEDGER_ERROR:{type(e).__name__}")
        return r

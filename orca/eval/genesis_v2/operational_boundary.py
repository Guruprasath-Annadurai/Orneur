"""The single operational entry point every future corpus-generation code path MUST call before writing a single byte of
PILOT_TRAIN/DEV/SCREEN/QUALIFICATION_HOLDOUT content, and the single entry point every future private-split READ must
call. Composes independently fail-closed gates so that no single compromised or stale record is sufficient on its own.

Two DISTINCT identities, never conflated (an id registered as both is itself flagged as invalid by generator_registry.validate):
  - GENERATOR identity (generator_registry.py) — pre-freeze, write-only to the vault, authorizes running
    `require_authorization()` / actually generating content.
  - QUALIFICATION RUNNER identity (runner_registry.py) — post-freeze, read access to SCREEN/QUALIFICATION_HOLDOUT,
    authorizes `require_private_split_access()`, which additionally goes through the real AccessLedger.

`require_authorization()` composes:
  1. corpus_generation_authorization.verify() against the REAL execution context: actual git HEAD, whether that HEAD
     is a genuine descendant of the reviewed commit, whether the working tree is clean, a freshly recomputed
     generator-code-tree hash, the REAL current corpus-inventory digest, the REAL current preregistration record
     hash — never caller-supplied values a caller could lie about.
  2. The execution EVENT and GENERATOR IDENTITY are derived from environment variables CI itself sets
     (`GITHUB_EVENT_NAME`/`GENESIS_V2_GENERATOR_ID`) rather than accepted as arbitrary caller-supplied strings, and
     the claimed identity is cross-checked against a cryptographic fact (the registry's declared `code_sha256`
     recomputed fresh from the actually-running code) rather than trusted on its own. HONEST LIMITATION: a bare
     environment variable is not itself an authenticated credential — anyone able to set process environment can
     set it. This module does not claim full runtime attestation (e.g. an OIDC token bound to a specific CI job);
     that is an unresolved capability for a future phase. What IS enforced here: (a) no implicit "if exactly one
     record exists, use it" fallback — an unset/empty identity is never silently accepted regardless of registry
     size; (b) the identity must resolve to a registry entry whose OWN declared code hash matches what is actually
     executing right now, so a stolen/misconfigured identity string still cannot make DRIFTED code pass. An explicit
     override parameter exists ONLY for tests (never used by the real CI call site, which always reads env).
  3. The generator registry must show `state == "AUTHORIZED"` for that identity, AND its declared `code_sha256` must
     match the freshly recomputed one — a registry entry whose declared hash no longer matches the running code is
     treated exactly like an unregistered identity.

`require_private_split_access()` is the SEPARATE, later-stage gate for actually reading SCREEN/QUALIFICATION_HOLDOUT:
requires the QUALIFICATION runner registry to show `state == "AUTHORIZED"` for the given process, AND independently
calls the real `ledger.AccessLedger.grant_access()` — this module never bypasses or re-implements that ledger check,
it is an ADDITIONAL, earlier gate before generation/read code would even reach the ledger.

Nothing in this module ever authorizes anything by itself — every check must independently pass.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
from orca.eval.genesis_v2 import generator_registry as GR
from orca.eval.genesis_v2 import inventory as INV
from orca.eval.genesis_v2 import prereg as PR
from orca.eval.genesis_v2 import runner_registry as RN


class CorpusGenerationNotAuthorized(PermissionError):
    """Raised by `require_authorization()`. Never caught-and-ignored by design — the caller is expected to abort."""


class PrivateSplitAccessDenied(PermissionError):
    """Raised by `require_private_split_access()`."""


@dataclass
class BoundaryResult:
    authorized: bool
    reasons: list = field(default_factory=list)
    generator_authorized: bool = False
    generator_state: str | None = None


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=20)


def _current_commit_sha(root: Path) -> str:
    r = _run_git(root, "rev-parse", "HEAD")
    return r.stdout.strip() if r.returncode == 0 else ""


def _is_ancestor(root: Path, ancestor_sha: str, descendant_sha: str) -> bool:
    if not ancestor_sha or not descendant_sha:
        return False
    if ancestor_sha == descendant_sha:
        return True
    r = _run_git(root, "merge-base", "--is-ancestor", ancestor_sha, descendant_sha)
    return r.returncode == 0


def _working_tree_clean(root: Path) -> bool:
    r = _run_git(root, "status", "--porcelain")
    return r.returncode == 0 and r.stdout.strip() == ""


def _real_context(root: Path, reviewed_commit_sha: str | None) -> tuple:
    """(commit_sha, commit_is_descendant, working_tree_clean, code_tree_sha256, inventory_digest, prereg_record_sha256)
    — always computed fresh from disk/git, never trusted from a caller."""
    commit_sha = _current_commit_sha(root)
    is_descendant = _is_ancestor(root, reviewed_commit_sha, commit_sha) if reviewed_commit_sha else False
    clean = _working_tree_clean(root)
    code_hash = CGA.code_tree_sha256(root)
    inv = json.loads((root / INV.INVENTORY_PATH).read_text())
    inventory_digest = INV.inventory_digest(inv)
    draft = json.loads((root / PR.DRAFT_PATH).read_text())
    prereg_sha = draft.get("record_sha256", "")
    return commit_sha, is_descendant, clean, code_hash, inventory_digest, prereg_sha


def _trusted_event_name(event_name: str | None) -> str:
    """Trusted runtime evidence, not a caller-supplied string: real CI call sites never pass `event_name` and get it
    from the real `GITHUB_EVENT_NAME` environment variable CI itself sets. An explicit non-None value is accepted
    only so tests can simulate specific events without needing to set process-wide environment variables."""
    if event_name is not None:
        return event_name
    return os.environ.get("GITHUB_EVENT_NAME", "")


def _trusted_generator_id(generator_id: str | None) -> str | None:
    if generator_id is not None:
        return generator_id
    return os.environ.get("GENESIS_V2_GENERATOR_ID") or None


def _generator_authorized(root: Path, generator_id: str | None, live_code_sha256: str) -> tuple:
    """(authorized: bool, state: str|None). Checks the SEPARATE generator_registry.py (never the qualification
    runner registry). A registry entry whose OWN declared code_sha256 no longer matches the code actually running
    right now is treated exactly like an unregistered identity — the registry cannot silently drift from reality."""
    reg_path = root / GR.REGISTRY_PATH
    if not reg_path.is_file():
        return False, None
    doc = json.loads(reg_path.read_text())
    qual_path = root / RN.REGISTRY_PATH
    qual_doc = json.loads(qual_path.read_text()) if qual_path.is_file() else None
    if GR.validate(doc, qualification_runner_doc=qual_doc):
        return False, None
    records = doc.get("records", [])
    # No "if exactly one record exists, use it" convenience fallback: an unset/empty generator_id is NEVER treated
    # as authenticated identity, however few or many records the registry happens to hold — ambient state (how many
    # rows a JSON file has) is not evidence of who is executing.
    if not generator_id:
        return False, None
    rec = next((r for r in records if r.get("generator_id") == generator_id), None)
    if rec is None:
        return False, None
    if rec.get("code_sha256") != live_code_sha256:
        return False, "CODE_SHA256_DRIFTED_FROM_REGISTRY"
    return rec.get("state") == "AUTHORIZED", rec.get("state")


def check_authorization(root: Path, *, requested_scope: tuple, event_name: str | None = None, generator_id: str | None = None,
                         now=None) -> BoundaryResult:
    """Read-only: builds the real execution context, loads the real committed records, and returns a BoundaryResult.
    Never raises on a denial — only `require_authorization()` (below) turns a denial into an exception."""
    root = Path(root)
    cga_path = root / CGA.RECORD_PATH
    record = json.loads(cga_path.read_text()) if cga_path.is_file() else CGA.default_record()
    reviewed_commit_sha = record.get("reviewed_commit_sha") if isinstance(record.get("reviewed_commit_sha"), str) else None
    commit_sha, is_descendant, clean, code_hash, inv_digest, prereg_sha = _real_context(root, reviewed_commit_sha)
    req = CGA.Request(commit_sha=commit_sha, commit_is_descendant=is_descendant, working_tree_clean=clean,
                       current_code_tree_sha256=code_hash, requested_scope=tuple(requested_scope),
                       current_inventory_digest=inv_digest, current_prereg_record_sha256=prereg_sha,
                       event_name=_trusted_event_name(event_name))
    keys = CGA.load_keys(root)
    verdict = CGA.verify(record, req, keys, now=now)
    gen_ok, gen_state = _generator_authorized(root, _trusted_generator_id(generator_id), code_hash)
    authorized = verdict.authorized and gen_ok
    reasons = list(verdict.reasons)
    if not gen_ok:
        reasons.append(f"GENERATOR_NOT_AUTHORIZED:{gen_state or 'NOT_REGISTERED'}")
    return BoundaryResult(authorized=authorized, reasons=reasons, generator_authorized=gen_ok, generator_state=gen_state)


def require_authorization(root: Path, *, requested_scope: tuple, event_name: str | None = None, generator_id: str | None = None,
                           now=None) -> BoundaryResult:
    """The actual call site every future corpus-generation entry point must make. Raises CorpusGenerationNotAuthorized
    with the full reason list on any denial; returns the (authorized=True) BoundaryResult only when every gate passed."""
    result = check_authorization(root, requested_scope=requested_scope, event_name=event_name, generator_id=generator_id, now=now)
    if not result.authorized:
        raise CorpusGenerationNotAuthorized(f"corpus generation denied: {result.reasons}")
    return result


def require_private_split_access(root: Path, ledger_dir: Path, *, process_id: str, code_sha256: str, purpose: str, split: str,
                                  eval_version: str, corpus_digest: str, run_id: str, candidate_revision: str, candidate_lineage: str,
                                  timestamp_utc: str, derived_from_lineages: tuple = ()) -> dict:
    """The SEPARATE, later-stage gate for actually reading SCREEN/QUALIFICATION_HOLDOUT. Requires the QUALIFICATION
    runner registry (not the generator registry) to show `state == "AUTHORIZED"` for `process_id`, then makes a REAL
    call into ledger.AccessLedger.request_access() — never bypasses or reimplements that check. Raises
    PrivateSplitAccessDenied on any denial from either gate."""
    from orca.eval.genesis_v2 import ledger as LG
    root = Path(root)
    reg_path = root / RN.REGISTRY_PATH
    if not reg_path.is_file():
        raise PrivateSplitAccessDenied("qualification runner registry missing")
    doc = json.loads(reg_path.read_text())
    if RN.validate(doc):
        raise PrivateSplitAccessDenied("qualification runner registry invalid")
    rec = next((r for r in doc.get("records", []) if r.get("runner_id") == process_id), None)
    if rec is None or rec.get("state") != "AUTHORIZED":
        raise PrivateSplitAccessDenied(f"qualification runner {process_id!r} is not AUTHORIZED (state={rec.get('state') if rec else 'NOT_REGISTERED'})")
    registry = RN.to_ledger_registered_processes(doc)
    ledger = LG.AccessLedger(Path(ledger_dir), registry)
    req = LG.AccessRequest(process_id=process_id, code_sha256=code_sha256, purpose=purpose, split=split, eval_version=eval_version,
                            corpus_digest=corpus_digest, run_id=run_id, candidate_revision=candidate_revision,
                            candidate_lineage=candidate_lineage, derived_from_lineages=tuple(derived_from_lineages), timestamp_utc=timestamp_utc)
    try:
        return ledger.request_access(req)
    except LG.AccessDenied as e:
        raise PrivateSplitAccessDenied(str(e)) from e


def authorized_manifest_verification_bytes(root: Path, ledger_dir: Path, store, *, process_id: str, code_sha256: str,
                                            corpus_id: str, expected_corpus_digest: str, eval_version: str, candidate_revision: str,
                                            candidate_lineage: str, run_id_prefix: str, timestamp_utc: str) -> tuple:
    """The SEPARATELY AUTHORIZED verification capability: the only sanctioned way to obtain real plaintext bytes to
    feed into `corpus_manifest.verify_against_artifacts()`. Makes TWO real, independent `require_private_split_access`
    calls (one per split — the ledger's run-id uniqueness means each split read is its own grant, never reused) and
    only reads the vault AFTER each grant succeeds. A caller that merely holds a `store` handle — e.g. a generator,
    which per generator_registry.py must have vault_read=false anyway — cannot use this shortcut to read a holdout:
    it still needs a genuinely AUTHORIZED qualification-runner identity and a real ledger grant for BOTH splits.
    Returns (screen_plain, holdout_plain). Raises PrivateSplitAccessDenied on either split's denial."""
    from orca.eval.genesis_v2 import spec as SPEC
    require_private_split_access(root, ledger_dir, process_id=process_id, code_sha256=code_sha256, purpose=SPEC.PURPOSE_STAGE1,
                                  split="SCREEN", eval_version=eval_version, corpus_digest=expected_corpus_digest,
                                  run_id=f"{run_id_prefix}-screen", candidate_revision=candidate_revision,
                                  candidate_lineage=candidate_lineage, timestamp_utc=timestamp_utc)
    require_private_split_access(root, ledger_dir, process_id=process_id, code_sha256=code_sha256, purpose=SPEC.PURPOSE_QUALIFICATION,
                                  split="QUALIFICATION_HOLDOUT", eval_version=eval_version, corpus_digest=expected_corpus_digest,
                                  run_id=f"{run_id_prefix}-holdout", candidate_revision=candidate_revision,
                                  candidate_lineage=candidate_lineage, timestamp_utc=timestamp_utc)
    screen_plain = store.read_split(corpus_id, "SCREEN", expected_corpus_digest=expected_corpus_digest)
    holdout_plain = store.read_split(corpus_id, "QUALIFICATION_HOLDOUT", expected_corpus_digest=expected_corpus_digest)
    return screen_plain, holdout_plain

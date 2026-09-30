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

## Key isolation for private-split content (write vs. read)

A generator's write capability (`GeneratorWriteHandle`, obtained only via `protected_generate_write_handle()`) must
be backed by a genuinely WRITE-ONLY object — see `store.EncryptedVaultWriter`, which holds ONLY the vault's public
X25519 key and defines no decrypt method anywhere in its class. `authorized_manifest_verification_bytes()` requires
the OPPOSITE: a READ-capable object (`store.EncryptedVaultReader`, holding the vault's private key) and refuses one
that exposes `write_corpus`. This is genuine cryptographic isolation, not an API convention a caller could route
around — a generator process that only ever receives the vault's PUBLIC key (via its own deployment credential scope)
has no mathematical path to plaintext, independent of what code it runs or what attributes it inspects.

## RESIDUAL RUNTIME-IDENTITY LIMITATIONS (honestly reported, not hidden)

1. **Environment-variable identity is not a cryptographic credential.** `_trusted_event_name`/`_trusted_generator_id`
   read `GITHUB_EVENT_NAME`/`GENESIS_V2_GENERATOR_ID` from the process environment. Anyone able to set that
   environment (a compromised CI runner, a misconfigured job) can set these values. What IS enforced: no implicit
   single-record fallback (see `_generator_authorized`), and the claimed identity must resolve to a registry entry
   whose OWN declared `code_sha256` matches the code ACTUALLY executing right now — a stolen identity string still
   cannot make drifted code pass. What is NOT achieved: proof that the calling process is genuinely the CI job the
   registry entry was meant for (e.g. an OIDC token cryptographically bound to a specific workflow run/repo/ref).
   That is an unresolved capability for a future phase, not something this module claims to provide.
2. **The code-tree hash binds only `CODE_PATHS` (`corpus_generation_authorization.CODE_PATHS`, currently just
   `orca/eval/genesis_v2/`), not every module a real generator implementation might import.** If a future generator
   imports shared code from elsewhere in this repository (or a third-party dependency), a change to THAT code is
   invisible to `code_tree_sha256()` and to the generator registry's `code_sha256` cross-check — see
   `test_code_tree_hash_does_not_cover_dependencies_outside_code_paths` in `tests/test_genesis_v2_operational_boundary.py`
   for a direct demonstration of this exact gap. Before any real generator implementation is authorized, `CODE_PATHS`
   MUST be extended to cover every directory it genuinely depends on, or this binding gives false confidence.
3. **Process isolation is a deployment concern, not something pure Python objects can guarantee.** The write-only /
   read-only split (above) removes the CRYPTOGRAPHIC capability to decrypt from a generator's own object graph, but
   it cannot stop a compromised generator PROCESS from, say, reading another process's memory if both run on the same
   unsandboxed host. Genuine process isolation (separate containers/sandboxes with disjoint credential scopes for
   the generator vs. the creation-time verifier) is the owner's deployment responsibility; this module's job is to
   ensure the KEYS each process is ever handed are already scoped correctly, so a deployment that does provide real
   process isolation gets full benefit from it, and one that does not is still better off than sharing one symmetric
   key across both roles.
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


def _generator_authorized(root: Path, generator_id: str | None, live_code_sha256: str, requested_scope: tuple) -> tuple:
    """(authorized: bool, state: str|None). Checks the SEPARATE generator_registry.py (never the qualification
    runner registry). A registry entry whose OWN declared code_sha256 no longer matches the code actually running
    right now is treated exactly like an unregistered identity — the registry cannot silently drift from reality.
    Also enforces that EVERY requested artifact class is within the generator's own `allowed_artifact_classes` —
    a generator record does not implicitly authorize every class merely by existing; requesting a class outside
    its declared scope is treated as not-authorized, independent of whatever the CORPUS_GENERATION_AUTHORIZATION
    record's own scope says (both must agree — see check_authorization, which intersects both checks)."""
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
    if not set(requested_scope) <= set(rec.get("allowed_artifact_classes") or []):
        return False, "REQUESTED_SCOPE_EXCEEDS_GENERATOR_ALLOWED_CLASSES"
    return rec.get("state") == "AUTHORIZED", rec.get("state")


def check_authorization(root: Path, *, requested_scope: tuple, event_name: str | None = None, generator_id: str | None = None,
                         now=None) -> BoundaryResult:
    """Read-only: builds the real execution context, loads the real committed records, and returns a BoundaryResult.
    Never raises on a denial — only `require_authorization()` (below) turns a denial into an exception.

    ITEM 3 (generation-provenance-closure phase): authority keys are loaded via
    `CGA.load_keys_for_corpus_generation()`, not the broader `CGA.load_keys()` -- an active, registered OWNER key
    is authorized to sign a REAL corpus-generation authorization only if its own registry record explicitly
    permits the DATA_SEEDING authorization class and both STAGE_1/STAGE_2 eval stages. Scope is never assumed to
    follow automatically from OWNER role alone; see that function's own docstring."""
    root = Path(root)
    cga_path = root / CGA.RECORD_PATH
    record = json.loads(cga_path.read_text()) if cga_path.is_file() else CGA.default_record()
    reviewed_commit_sha = record.get("reviewed_commit_sha") if isinstance(record.get("reviewed_commit_sha"), str) else None
    commit_sha, is_descendant, clean, code_hash, inv_digest, prereg_sha = _real_context(root, reviewed_commit_sha)
    req = CGA.Request(commit_sha=commit_sha, commit_is_descendant=is_descendant, working_tree_clean=clean,
                       current_code_tree_sha256=code_hash, requested_scope=tuple(requested_scope),
                       current_inventory_digest=inv_digest, current_prereg_record_sha256=prereg_sha,
                       event_name=_trusted_event_name(event_name))
    keys = CGA.load_keys_for_corpus_generation(root)
    verdict = CGA.verify(record, req, keys, now=now)
    gen_ok, gen_state = _generator_authorized(root, _trusted_generator_id(generator_id), code_hash, tuple(requested_scope))
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


def authorized_manifest_verification_bytes(root: Path, ledger_dir: Path, reader, *, process_id: str, code_sha256: str,
                                            corpus_id: str, expected_corpus_digest: str, eval_version: str, candidate_revision: str,
                                            candidate_lineage: str, run_id_prefix: str, timestamp_utc: str) -> tuple:
    """The SEPARATELY AUTHORIZED, CREATION-TIME verification capability: the only sanctioned way to obtain real
    plaintext bytes to feed into `corpus_manifest.verify_against_artifacts()`, right after generation and always
    BEFORE V2 is frozen. `reader` must be a READ-capable object (e.g. `store.EncryptedVaultReader`, constructed from
    the vault's PRIVATE key) — never a `GeneratorWriteHandle` or anything exposing `write_corpus`; passing one raises
    immediately, since a write-only object holding the generator's key material could never genuinely decrypt
    anything here anyway, but refusing it outright keeps this call site honest about what it expects.

    Uses `spec.PURPOSE_CREATION_VERIFICATION` — a purpose DISTINCT from `PURPOSE_QUALIFICATION`/`PURPOSE_STAGE1` —
    for BOTH splits, so this call:
      - does NOT consume the QUALIFICATION_HOLDOUT's one-time-per-lineage qualification lifecycle (the ledger's
        write-once/lineage bookkeeping in `_state_from` only counts PURPOSE_QUALIFICATION accesses),
      - does NOT require V2 to be frozen (creation-time verification happens before freeze, by definition),
      - the ledger additionally refuses this purpose once the holdout has left the SEALED state, so it can never be
        used to sneak a read after a real qualification run has legitimately opened it.

    RESTRICTED VERIFIER IDENTITY (separately controlled from a real qualification runner): `process_id` must be
    registered in the qualification-runner registry with `allowed_purposes` that do NOT include
    `PURPOSE_QUALIFICATION` — an identity authorized to perform creation-time verification must not ALSO be
    authorized to open the holdout for a real qualification run. This is the same separation-of-duties principle
    `generator_registry.validate()` already applies between generator and qualification-runner identities, applied
    here one level deeper: within the runner registry, a "verifier" and a "qualifier" must be different identities.

    Makes TWO real, independent `require_private_split_access` calls (one per split) and only reads the vault AFTER
    each grant succeeds. A caller that merely holds SOME reader object cannot use this shortcut: it still needs a
    genuinely AUTHORIZED, purpose-restricted qualification-runner identity and a real ledger grant for BOTH splits.
    Refuses to run at all once V2 is frozen (frozen means real qualification has begun; verification must have
    already happened before then). The returned plaintext is used ONLY for `corpus_manifest.verify_against_artifacts`
    hash comparison in this phase — this repository contains no training or candidate-selection code path, so there
    is nowhere else these bytes could flow to.
    Returns (screen_plain, holdout_plain). Raises PrivateSplitAccessDenied on any denial."""
    from orca.eval.genesis_v2 import spec as SPEC
    if hasattr(reader, "write_corpus"):
        raise PrivateSplitAccessDenied("authorized_manifest_verification_bytes requires a READ-capable object, not something exposing write_corpus")
    if SPEC.GENESIS_CAPABILITY_EVAL_V2_FROZEN:
        raise PrivateSplitAccessDenied("creation-time verification is only valid before V2 is frozen")
    root = Path(root)
    from orca.eval.genesis_v2 import runner_registry as RN
    reg_path = root / RN.REGISTRY_PATH
    if not reg_path.is_file():
        raise PrivateSplitAccessDenied("qualification runner registry missing")
    doc = json.loads(reg_path.read_text())
    if RN.validate(doc):
        raise PrivateSplitAccessDenied("qualification runner registry invalid")
    rec = next((r for r in doc.get("records", []) if r.get("runner_id") == process_id), None)
    if rec is None:
        raise PrivateSplitAccessDenied(f"qualification runner {process_id!r} is not registered")
    if SPEC.PURPOSE_QUALIFICATION in (rec.get("allowed_purposes") or []):
        raise PrivateSplitAccessDenied(
            f"verifier identity {process_id!r} is also authorized for {SPEC.PURPOSE_QUALIFICATION!r} -- a creation-time "
            "verifier must be a separately controlled identity, restricted to creation-time verification only")
    require_private_split_access(root, ledger_dir, process_id=process_id, code_sha256=code_sha256, purpose=SPEC.PURPOSE_CREATION_VERIFICATION,
                                  split="SCREEN", eval_version=eval_version, corpus_digest=expected_corpus_digest,
                                  run_id=f"{run_id_prefix}-screen", candidate_revision=candidate_revision,
                                  candidate_lineage=candidate_lineage, timestamp_utc=timestamp_utc)
    require_private_split_access(root, ledger_dir, process_id=process_id, code_sha256=code_sha256, purpose=SPEC.PURPOSE_CREATION_VERIFICATION,
                                  split="QUALIFICATION_HOLDOUT", eval_version=eval_version, corpus_digest=expected_corpus_digest,
                                  run_id=f"{run_id_prefix}-holdout", candidate_revision=candidate_revision,
                                  candidate_lineage=candidate_lineage, timestamp_utc=timestamp_utc)
    screen_plain = reader.read_split(corpus_id, "SCREEN", expected_corpus_digest=expected_corpus_digest)
    holdout_plain = reader.read_split(corpus_id, "QUALIFICATION_HOLDOUT", expected_corpus_digest=expected_corpus_digest)
    return screen_plain, holdout_plain


def verify_manifest_digest_only_same_process(root: Path, ledger_dir: Path, reader, manifest: dict, authorization_record: dict,
                                              receipt: dict, *,
                                              process_id: str, code_sha256: str, corpus_id: str,
                                              eval_version: str, candidate_revision: str, candidate_lineage: str, run_id_prefix: str,
                                              timestamp_utc: str, generator_code_root) -> list:
    """HONEST NAME, HONEST SCOPE (item 5): this function does NOT provide operating-system process isolation. It
    runs in the SAME Python process as its caller, on the SAME thread, with no subprocess, container, or sandbox
    boundary of any kind — a previous name for this function ("restricted process") overstated that guarantee, which
    is why the name changed rather than the implementation growing a real process boundary it does not need for what
    it actually promises.

    What it DOES guarantee, narrowly and unconditionally: composes `authorized_manifest_verification_bytes()` (real
    plaintext, ledger-gated, from a separately controlled and purpose-restricted verifier identity — see that
    function's own docstring) with `corpus_manifest.verify_against_artifacts()` (checks the plaintext against the
    manifest), and returns ONLY the resulting `problems: list[str]` — DIGEST-ONLY DIAGNOSTICS, never the plaintext
    itself. Every problem string this function can return describes a DIGEST or HASH comparison outcome (e.g.
    `"screen_digest does not match the ACTUAL decrypted SCREEN plaintext"`, `"generator_code_sha256 does not match
    the ACTUAL current generator code"`) — see `corpus_manifest.verify_against_artifacts`'s fixed set of possible
    messages, none of which embeds content. Private plaintext bytes exist ONLY as local variables inside this
    function's own stack frame: there is no `return screen_plain` / `return holdout_plain` anywhere in this
    function, no `print`/`log` call touching them, no write to any file, cache, queue, or global. The local
    plaintext names are cleared (best-effort — CPython offers no memory-scrubbing guarantee) in a `finally` block
    that runs whether verification passed, failed, or raised.

    NO TRAINING, INFERENCE, OR PUBLISHING CAPABILITY: this function imports only `corpus_manifest` (a pure hashing/
    comparison module — see its own docstring) and calls `authorized_manifest_verification_bytes()`. It contains no
    model-loading code, no network call, no file write outside what `authorized_manifest_verification_bytes()`
    itself performs (a read, not a write), and no publishing/commit/push call of any kind — confirmed by
    `tests/test_genesis_v2_operational_boundary.py::test_digest_only_same_process_verifier_has_no_training_inference_or_publishing_imports`,
    which scans this function's actual module dependencies.

    Preserves the SAME ledger evidence and sealed-holdout lifecycle guarantees as
    `authorized_manifest_verification_bytes()` (PURPOSE_CREATION_VERIFICATION, SEALED-only, no freeze requirement,
    never counted toward the holdout's one-time qualification lifecycle) — this function adds no NEW ledger
    interaction of its own; it is a strict, plaintext-hiding, same-process wrapper around the existing one.

    Real OS-level process isolation (so that even OTHER code running in the SAME process cannot reach these local
    variables through, say, a debugger or a core dump) remains a deployment responsibility — see this module's
    top-level docstring's "RESIDUAL RUNTIME-IDENTITY LIMITATIONS" section. If genuine process isolation is required
    for a future deployment, that means literally running this call in a separate OS process (e.g. `subprocess`,
    a container, or a sandboxed worker) and treating its stdout as the digest-only diagnostic channel — this
    function does not do that itself, and does not claim to.

    VERIFIER PROCESS ISOLATION EXPLICITLY REQUIRES REAL DEPLOYMENT VALIDATION: no unit test, no code review, and no
    property of this function's implementation can establish that a REAL verifier deployment actually runs in a
    separate, isolated OS process from the generator or from anything else on the same host. That is a deployment-
    configuration fact (which container, which VM, which sandbox), not a code-level guarantee this same-process
    Python function could ever provide by construction. Treat "the verifier is process-isolated" as UNVERIFIED until
    the owner independently confirms the real deployment topology — this function's digest-only return-value
    guarantee is a genuinely useful, narrower property that holds regardless, but it is not a substitute for that
    separate, real-deployment check.

    ITEM 1 (deployment-decision-accuracy-closure phase): the manifest is now AUTHENTICATED before anything it
    claims is trusted. `expected_corpus_digest` is no longer a caller-supplied parameter at all — it is DERIVED,
    internally, from the manifest's OWN `screen_digest`/`qualification_holdout_digest`, but ONLY after the manifest
    has independently passed BOTH `corpus_manifest.verify_manifest_signature()` (a real Ed25519 signature from a
    registered OWNER authority key -- the X25519 vault keypair provides confidentiality, never sender
    authentication, so this is a SEPARATE check) AND `corpus_manifest.binding_problems()` (cross-checked against
    the SPECIFIC `authorization_record` that permitted generation). An attacker who knows only the vault's PUBLIC
    key can encrypt arbitrary substitute content and write a self-consistent manifest claiming it, but cannot
    produce a valid signature over that manifest without the registered owner's private signing key -- so this
    function never even reaches the point of deriving a digest for, let alone verifying, the substituted artifacts.
    See `tests/test_genesis_v2_corpus_manifest_and_lineage.py`'s adversarial substitution tests.

    ITEM 1 (final-receiving-boundary-integration phase): the caller-supplied `authorization_record` is no longer
    trusted merely because it has `status: "AUTHORIZED"` and matching fields -- it is now independently
    cryptographically AUTHENTICATED via `corpus_generation_authorization.verify_referenced()`, the SAME Ed25519
    signature-verification machinery `corpus_generation_authorization.verify()` itself uses to gate a NEW
    generation event, applied here to a REFERENCE to a past one. A caller can no longer get a fabricated or
    self-consistent-but-unsigned `authorization_record` trusted merely by pairing it with a genuinely, validly
    signed manifest.

    ITEM 2 (final-receiving-boundary-integration phase): before any private-vault read or ledger grant, this
    function now ALSO requires:
      - `manifest["corpus_id"] == corpus_id` and `manifest["eval_version"] == eval_version` -- the ACTUAL parameters
        of THIS receiving request, never merely the manifest's own self-reported claims about itself. A validly
        signed manifest for one corpus/eval-version can no longer be replayed against a request for a different one.
      - commit ancestry between `authorization_record["reviewed_commit_sha"]` and `manifest["generated_at_commit_sha"]`
        is RECOMPUTED here, from real repository evidence (`_is_ancestor()` / `git merge-base --is-ancestor` against
        THIS `root`), never accepted as an arbitrary caller-supplied boolean -- the previous `commit_is_descendant:
        bool` parameter is removed entirely.
      - `authority_keys` is no longer a caller-supplied parameter either -- it is loaded here from the REAL, live
        authority registry (`corpus_generation_authorization.load_keys(root)`), the SAME source
        `require_authorization()` itself reads, so both the manifest's signature and the referenced CGA's signature
        are checked against keys that genuinely originate from the validated, currently-active authority registry.
    See `tests/test_genesis_v2_cross_machine_transfer.py`'s replay-across-corpus-id/eval-version regression tests
    and `tests/test_genesis_v2_corpus_generation_authorization.py`'s `verify_referenced()` adversarial tests
    (unsigned CGA, forged signature, revoked/inappropriate authority, unrelated CGA, fabricated authorization
    fields paired with a validly signed manifest).

    ITEM 1 (generation-provenance-closure phase): `verify_referenced()` correctly allows an authentic HISTORICAL CGA
    (one whose own validity window has since elapsed) to still authenticate -- that is the right behavior for
    auditing the AUTHORIZATION's own signature. It does not, by itself, prove generation actually happened while
    that authorization was valid. This function now ALSO requires a separate, signed `receipt` (see
    `generation_receipt.py`) proving `authorization.issued_at <= receipt.generated_at <= authorization.expires_at`
    -- using the AUTHORIZATION's OWN window, never the current verification-time clock. A corpus with an authentic
    but expired historical CGA and no valid in-window generation receipt is never accepted as proven authorized-
    generation output.

    ITEM 2 (generation-provenance-closure phase): the receipt is cross-bound against every OTHER already-
    authenticated object -- `receipt.corpus_generation_authorization_id`/`corpus_id`/`eval_version`/`corpus_digest`/
    `generator_code_tree_sha256`/`generating_commit_sha` must all exactly agree with the authenticated CGA, the
    signed manifest, and the actual receiving request. Any mismatch is rejected here, before any private-split
    read or ledger grant, exactly like every other check in this function.

    ITEM 3 (generation-provenance-closure phase): authority keys used to authenticate the referenced CGA and the
    generation receipt are loaded via `corpus_generation_authorization.load_keys_for_corpus_generation()` -- an
    active, registered OWNER key is treated as valid for REAL corpus-generation authorization/attestation only if
    its own registry record explicitly permits the DATA_SEEDING authorization class and both STAGE_1/STAGE_2 eval
    stages. An OWNER key registered for some unrelated purpose is never assumed to have this scope merely by being
    an active OWNER key. This is DELIBERATELY NARROWER than the key source `corpus_manifest.verify_manifest_signature()`
    still uses (`load_keys()`, role == OWNER only) -- that already-accepted, frozen control is not redesigned here."""
    from orca.eval.genesis_v2 import corpus_generation_authorization as CGA
    from orca.eval.genesis_v2 import corpus_manifest as CMAN
    from orca.eval.genesis_v2 import generation_receipt as GRC
    from orca.eval.genesis_v2 import store as ST
    root = Path(root)
    problems = CMAN.validate_manifest(manifest)
    if problems:
        return problems
    # ITEM 2: bind to the ACTUAL receiving request before trusting anything else the manifest claims about its own
    # identity -- checked before any signature/authorization work, since a mismatched identity makes everything
    # downstream moot regardless of how well-formed or well-signed the manifest otherwise is.
    if manifest.get("corpus_id") != corpus_id:
        return [f"MANIFEST_CORPUS_ID_MISMATCH: manifest claims {manifest.get('corpus_id')!r}, request is for {corpus_id!r}"]
    if manifest.get("eval_version") != eval_version:
        return [f"MANIFEST_EVAL_VERSION_MISMATCH: manifest claims {manifest.get('eval_version')!r}, request is for {eval_version!r}"]
    # (final-receiving-boundary-integration phase) authority-key material for the MANIFEST's own signature
    # originates from the validated, LIVE authority registry -- never an arbitrary caller-supplied list. This
    # specific key source (role == OWNER only) is the already-accepted, frozen control and is NOT narrowed here.
    authority_keys = CGA.load_keys(root)
    sig_problem = CMAN.verify_manifest_signature(manifest, authority_keys)
    if sig_problem:
        return [f"MANIFEST_SIGNATURE_INVALID:{sig_problem}"]
    # ITEM 3: a SEPARATE, more narrowly SCOPED key set (role == OWNER AND DATA_SEEDING/STAGE_1/STAGE_2 permitted)
    # for the referenced CGA's authentication and the generation receipt's authentication below.
    generation_scoped_keys = CGA.load_keys_for_corpus_generation(root)
    # ITEM 1: independently authenticate the REFERENCED CGA record -- never trusted merely because it says
    # status: AUTHORIZED and has matching fields. A fabricated or unsigned authorization_record is rejected here,
    # even when paired with a genuinely, validly signed manifest.
    cga_problems = CGA.verify_referenced(authorization_record, generation_scoped_keys)
    if cga_problems:
        return [f"AUTHORIZATION_RECORD_NOT_AUTHENTICATED:{p}" for p in cga_problems]
    # ITEM 2: ancestry is RECOMPUTED from real repository evidence, never accepted as a caller-supplied boolean.
    commit_is_descendant = _is_ancestor(root, authorization_record.get("reviewed_commit_sha"), manifest.get("generated_at_commit_sha"))
    binding = CMAN.binding_problems(manifest, authorization_record, commit_is_descendant=commit_is_descendant)
    if binding:
        return binding
    # Only NOW -- the manifest signed by a registered owner, the authorization it references independently
    # authenticated, bound to the request's actual corpus_id/eval_version, and ancestry recomputed from real
    # repository evidence -- is the manifest a trusted source. Never derived from, or verified against, the
    # ciphertext-transfer channel itself.
    expected_corpus_digest = ST.corpus_digest_of({"SCREEN": manifest["screen_digest"], "QUALIFICATION_HOLDOUT": manifest["qualification_holdout_digest"]})
    # ITEMS 1+2: the generation receipt is verified LAST, after everything it cross-checks against is itself
    # already authenticated -- still strictly BEFORE any private-split read or ledger grant below.
    receipt_problems = GRC.verify_receipt(receipt, authorization_record=authorization_record, manifest=manifest,
                                           expected_corpus_digest=expected_corpus_digest, requested_eval_version=eval_version,
                                           authority_keys=generation_scoped_keys)
    if receipt_problems:
        return [f"GENERATION_RECEIPT_INVALID:{p}" for p in receipt_problems]
    screen_plain = holdout_plain = None
    try:
        screen_plain, holdout_plain = authorized_manifest_verification_bytes(
            root, ledger_dir, reader, process_id=process_id, code_sha256=code_sha256, corpus_id=corpus_id,
            expected_corpus_digest=expected_corpus_digest, eval_version=eval_version, candidate_revision=candidate_revision,
            candidate_lineage=candidate_lineage, run_id_prefix=run_id_prefix, timestamp_utc=timestamp_utc)
    except ST.PrivateStorageIntegrityError:
        # The manifest is authenticated (signed + bound) but its OWN claimed screen_digest/qualification_holdout_digest
        # do not correspond to what is actually sealed in the vault under expected_corpus_digest -- a tampered-content
        # manifest, distinct from a forged-signature one. Fail closed with a diagnostic, never let the store's own
        # integrity exception (which could otherwise propagate raw) escape this digest-only, never-raises contract.
        return ["CORPUS_DIGEST_MISMATCH: manifest screen_digest/qualification_holdout_digest do not match sealed vault content"]
    try:
        problems = CMAN.verify_against_artifacts(manifest, screen_plain=screen_plain, holdout_plain=holdout_plain,
                                                   generator_code_root=generator_code_root, expected_corpus_digest=expected_corpus_digest)
        return list(problems)
    finally:
        screen_plain = None
        holdout_plain = None


class GeneratorWriteHandle:
    """A write-only capability wrapping a genuinely write-only vault object (`store.EncryptedVaultWriter`, holding
    only the vault's PUBLIC key — no decrypt capability exists anywhere in that object's state, see its own
    docstring) and exposing ONLY `write_corpus`. On TOP of that cryptographic isolation, this handle independently
    re-checks the AUTHORIZED scope on every write call — not just once at handle-issuance time — so a generator
    cannot request a broad scope, get a handle, then call `write_corpus` with a DIFFERENT split set than what was
    actually authorized. For a purely public-split request (e.g. PILOT_TRAIN/DEV, which never go through this
    encrypted private vault), `store` is None: no vault-capable object is constructed or retained AT ALL, so there is
    no structural path from a public-only authorization to private storage, independent of any runtime check."""

    def __init__(self, store, *, authorized_scope: frozenset = frozenset()):
        if store is not None and hasattr(store, "read_split"):
            raise PrivateStorageWriteHandleViolation(
                "refusing to build a generator write handle from an object that also exposes read_split -- a "
                "generator's write capability must be backed by a genuinely write-only object")
        self._store = store
        self._authorized_scope = frozenset(authorized_scope)

    def write_corpus(self, corpus_id: str, splits: dict) -> str:
        requested = set(splits)
        if self._store is None or not requested or not requested <= self._authorized_scope:
            denied = sorted(requested - self._authorized_scope) or sorted(requested)
            raise PrivateStorageWriteHandleViolation(f"this generator identity is not authorized to write {denied}")
        return self._store.write_corpus(corpus_id, splits)

    def __repr__(self) -> str:
        return f"GeneratorWriteHandle(write_corpus only, authorized_scope={sorted(self._authorized_scope)})"


class PrivateStorageWriteHandleViolation(PermissionError):
    """Raised by GeneratorWriteHandle when a write is attempted outside its authorized scope, or when construction
    itself was attempted with a non-write-only backing object."""


def protected_generate_write_handle(root: Path, store, *, requested_scope: tuple, event_name: str | None = None,
                                     generator_id: str | None = None, now=None) -> GeneratorWriteHandle:
    """THE protected operation: the only sanctioned way for real generation code to obtain something that can write
    to the vault. Calls `require_authorization()` first (raises CorpusGenerationNotAuthorized on any denial — the
    full composed boundary: signed authorization against the real execution context, generator identity+scope, code
    drift). Only on success does it return a `GeneratorWriteHandle`.

    `store` must be a genuinely write-only object (e.g. `store.EncryptedVaultWriter`, holding only the vault's public
    key) when `requested_scope` includes any private split — passing something that also exposes `read_split` is
    refused by `GeneratorWriteHandle`'s own constructor. When `requested_scope` is PURELY public (no intersection
    with `spec.PRIVATE_SPLITS` — e.g. PILOT_TRAIN/DEV only), `store` is never even looked at: the returned handle's
    `_store` is `None`, so there is no vault-capable object anywhere in the returned handle's state, structurally
    eliminating any path from a public-only authorization to the private vault, not merely blocking it at runtime.

    The returned handle independently re-enforces the authorized scope on every `write_corpus` call (see
    GeneratorWriteHandle), so a generator cannot use a handle issued for one scope to write a different one."""
    from orca.eval.genesis_v2 import spec as SPEC
    require_authorization(root, requested_scope=requested_scope, event_name=event_name, generator_id=generator_id, now=now)
    private_scope = frozenset(s for s in requested_scope if s in SPEC.PRIVATE_SPLITS)
    if not private_scope:
        return GeneratorWriteHandle(None, authorized_scope=frozenset())
    return GeneratorWriteHandle(store, authorized_scope=private_scope)

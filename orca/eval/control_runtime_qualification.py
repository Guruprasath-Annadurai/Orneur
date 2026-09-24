"""
Genesis CONTROL runtime qualification -- fail-closed gate + result validator
(Phase 21B.4.20).

Qualifies the ACTUAL runtime execution path of the three locked controls
(Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4): pinned identity, a
production-compatible serving runtime, a minimal deterministic smoke, clean
teardown, and -- as a HARD GATE -- exactly zero incremental owner-billed
cost. This is runtime compatibility evidence ONLY. It is never a capability
claim: `capability_status` is always UNPROVEN, no benchmark or Genesis eval
item is run, and no generated text is ever executed.

Two independent fail-closed layers live here, both pure CPU:

1. `financial_gate_decision()` -- decides, BEFORE any GPU/resource is
   provisioned, whether a run may start. A wall-clock ceiling and a $0 spend
   limit are NOT sufficient (Phase 21B.4.13 GLM incident, $3.52 billed): the
   decision needs a fresh live billing reading, a known credit runway, a
   worst-case job cost, and a safety reserve. Anything unknown blocks.
2. `validate_control_runtime_record()` -- decides whether a persisted result
   may be called RUNTIME_QUALIFIED. That requires technical serving proof
   AND financial acceptance (owner_billed_delta_usd == 0 exactly) AND clean
   teardown AND verified identity AND verified evidence hashes AND a complete
   attempt history. Technical success with any positive owner billing is
   NOT_ACCEPTED, never QUALIFIED (the GLM mistake must not recur).

Machine validation proves internal consistency, hash agreement between the
record and persisted artifacts, and that the invariants above hold. It does
not prove the provider's billing telemetry is itself authoritative or
real-time; that limitation is recorded in the evidence, not hidden.
"""
from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path

from orca.eval.candidate_registry import EXPECTED_CONTROL_NAMES

# ── locked control identities (mirror the registry; a test asserts equality) ──

LOCKED_CONTROL_IDENTITIES: dict[str, dict] = {
    "Qwen3-8B": {
        "model_id": "Qwen/Qwen3-8B",
        "revision": "b968826d9c46dd6066d109eabc6255188de91218",
        "expected_weight_bytes": 16381516776,
    },
    "Mistral-Nemo-Instruct-2407": {
        "model_id": "mistralai/Mistral-Nemo-Instruct-2407",
        "revision": "04d8a90549d23fc6bd7f642064003592df51e9b3",
        # HF 5-shard representation (consolidated.safetensors is a separate
        # 24,495,604,224-byte alternative format of the same weights).
        "expected_weight_bytes": 24495607104,
    },
    "Phi-4": {
        "model_id": "microsoft/phi-4",
        "revision": "2db69c1c3e91a05d2c64a3185acfbaf36f744e25",
        "expected_weight_bytes": 29319042992,
    },
}
if set(LOCKED_CONTROL_IDENTITIES) != set(EXPECTED_CONTROL_NAMES):
    raise ValueError("LOCKED_CONTROL_IDENTITIES drifted from the registered control name set")

# ── status vocabularies ───────────────────────────────────────────────────

TECHNICAL_SERVING_STATUSES = ("QUALIFIED", "FAILED", "INCONCLUSIVE", "NOT_PROVEN", "NOT_TESTED", "BLOCKED_PENDING_ZERO_CASH_RUNWAY")
FINANCIAL_PREFLIGHT_STATUSES = ("PASSED", "FAILED", "NOT_PERFORMED")
FINANCIAL_ACCEPTANCE_STATUSES = ("PASS", "FAILED", "NOT_TESTED")
RUNTIME_QUALIFICATION_STATUSES = ("RUNTIME_QUALIFIED", "NOT_ACCEPTED", "FAILED", "NOT_COMPLETED", "NOT_TESTED", "BLOCKED_PENDING_ZERO_CASH_RUNWAY")
CLEANUP_STATUSES = ("PASS", "FAIL", "NOT_APPLICABLE")
ATTEMPT_OUTCOMES = ("TECHNICAL_SUCCESS", "TECHNICAL_FAILURE", "HARNESS_FAILURE", "ABORTED_FINANCIAL_GUARD", "BLOCKED_NO_GPU")
# Attempt result vs model-runtime result are DIFFERENT things. Only a valid
# runtime attempt (the pinned model's server was actually launched and the
# outcome observed) can ever make the MODEL's technical status FAILED; a
# harness bug or a financial-guard abort leaves runtime compatibility
# UNPROVEN / the qualification NOT_COMPLETED.
FAILURE_DOMAIN_BY_OUTCOME = {
    "TECHNICAL_SUCCESS": "NONE",
    "TECHNICAL_FAILURE": "MODEL_RUNTIME",
    "HARNESS_FAILURE": "HARNESS",
    "ABORTED_FINANCIAL_GUARD": "FINANCIAL_GUARD",
    "BLOCKED_NO_GPU": "NONE",
}
CAPABILITY_STATUS = "UNPROVEN"
EVIDENCE_KIND = "RUNTIME_QUALIFICATION_SMOKE"

REQUIRED_SMOKE_IDS = ("A", "B", "C")

# ── financial reconciliation (owner-payable gate AND credit-coverage gate) ──
MAX_AUTHORIZED_RUN_COST_USD = Decimal("1.25")   # never raised without stopping and reporting
SETTLEMENT_OBSERVED = "OBSERVED"
SETTLEMENT_NOT_OBSERVABLE = "BILLING_SETTLEMENT_NOT_YET_OBSERVABLE"
# ── Lightning AI (complimentary credits; owner cash INR 0) ──────────────────
LIGHTNING_PROVIDER = "Lightning AI"
LIGHTNING_EXPECTED_USERNAME = "annaduraiguruprasath5"
LIGHTNING_PER_ATTEMPT_CREDIT_CAP = Decimal("1.00")   # STOP for review above this
LIGHTNING_RESERVE_CREDITS = Decimal("1.00")          # kept after execution where possible
LIGHTNING_FINANCIAL_REQUIRED = (
    "plan", "payment_method_present", "machine_slug", "machine_rate_credits_per_hour", "gpu_runtime_seconds",
    "credits_before", "credits_after", "credit_delta", "expected_credit_cost", "observed_credit_cost",
    "owner_charge_before_usd", "owner_charge_after_usd", "owner_cash_delta_usd", "balance_limit",
    "credit_meter_stopped", "hard_runtime_cap_seconds", "artifacts",
)
RECONCILIATION_FIELDS = (
    "billing_baseline_usd", "billing_postrun_usd", "billing_delta_usd",
    "metered_baseline_usd", "metered_postrun_usd", "metered_delta_usd",
    "credits_applied_baseline_usd", "credits_applied_postrun_usd",
    "credit_pool_total_usd", "derived_credit_remaining_before_usd", "derived_credit_remaining_after_usd",
    "reserve_usd", "maximum_authorized_run_cost_usd",
)

RECORD_REQUIRED_FIELDS = (
    "phase", "evidence_kind", "control_name", "model_id", "model_revision", "tokenizer_revision", "architecture",
    "license", "runtime_name", "runtime_version", "container_image", "container_digest", "gpu_provider", "gpu_type",
    "gpu_count", "tensor_parallel", "precision", "max_model_len", "attention_backend", "reasoning_parser",
    "chat_template_source", "stop_behavior", "started_at_utc", "finished_at_utc", "cold_start_seconds",
    "load_seconds", "peak_gpu_memory_bytes", "steady_gpu_memory_bytes", "smoke_prompts", "generation_config",
    "smoke_outputs", "latency_seconds", "ttft_seconds", "generated_tokens", "tokens_per_second",
    "technical_serving_status", "financial_preflight_status", "financial_acceptance_status",
    "owner_billed_delta_usd", "runtime_qualification_status", "capability_status", "cleanup_status",
    "live_resources_after_cleanup", "raw_log_artifact", "raw_log_sha256", "notes",
    # supporting evidence the spec requires to be bound to the record
    "attempts", "identity_verification", "financial_evidence", "generated_output_executed", "unobservable_reasons",
)
# Metrics that may be null ONLY with a recorded reason (never fabricated).
NULLABLE_METRICS = (
    "container_digest", "attention_backend", "reasoning_parser", "cold_start_seconds", "load_seconds",
    "peak_gpu_memory_bytes", "steady_gpu_memory_bytes", "latency_seconds", "ttft_seconds", "generated_tokens",
    "tokens_per_second", "tokenizer_revision", "runtime_version", "container_image",
)

ATTEMPT_REQUIRED_FIELDS = (
    "attempt_number", "outcome", "reason", "resource_type", "duration_seconds", "owner_billed_delta_usd", "cleanup_result",
)
FINANCIAL_EVIDENCE_REQUIRED = ("preflight_artifact", "preflight_sha256", "billing_before_artifact", "billing_before_sha256",
                               "billing_after_artifact", "billing_after_sha256")

# Keys that would indicate capability/benchmark output masquerading as
# runtime evidence (§33.G).
_CAPABILITY_KEY_FRAGMENTS = (
    "benchmark", "accuracy", "pass_rate", "pass_at", "mmlu", "gpqa", "humaneval", "mbpp", "swe_bench", "gsm8k",
    "aime", "livecodebench", "leaderboard", "quality_score", "win_rate", "capability_score",
)
_SECRET_PATTERNS = (
    re.compile(r"hf_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}", re.IGNORECASE),
    re.compile(r"(MODAL_TOKEN_SECRET|MODAL_TOKEN_ID|HF_TOKEN|HUGGING_FACE_HUB_TOKEN)\s*=\s*\S+"),
)
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")


class ControlRuntimeError(ValueError):
    """A control runtime record or financial-gate input violates the
    Phase 21B.4.20 fail-closed rules."""


# ── money helpers ─────────────────────────────────────────────────────────


def to_decimal(value, label: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise ControlRuntimeError(f"{label} is not a valid decimal amount: {value!r}") from e
    if not d.is_finite():
        raise ControlRuntimeError(f"{label} is not finite: {value!r}")
    return d


# ── financial hard gate (§7-§9) ───────────────────────────────────────────


def financial_gate_decision(
    billing_summary: dict | None,
    *,
    worst_case_job_cost_usd,
    credit_pool_usd,
    reserve_usd,
    prior_positive_billing_seen: bool = False,
    prior_settlement_unresolved: bool = False,
) -> dict:
    """Decide whether a GPU-backed run may START. Pure function; returns a
    decision dict and never raises for a merely-blocked run. Blocks unless
    ALL hold:

    * a fresh live billing summary is supplied and parses;
    * no positive owner billing has ever been seen in this phase's attempts;
    * `billed_cost` is exactly the amount already recorded (never rising);
    * all metered usage is currently covered by credits (billed == 0 on
      top of the baseline);
    * the KNOWN remaining credit (credit pool minus credits already
      applied) minus the safety reserve exceeds the run's WORST-CASE cost.

    Historical free-tier claims, old credits and past $0 runs are never
    inputs -- only the live reading and the explicit runway arithmetic.
    """
    reasons: list[str] = []
    if prior_positive_billing_seen:
        reasons.append("positive owner billing already occurred in this phase -- further GPU runs are stopped")
    if prior_settlement_unresolved:
        reasons.append(f"{SETTLEMENT_NOT_OBSERVABLE}: a previous run's usage/credit coverage is not yet reconciled in the account data")
    if not billing_summary:
        reasons.append("no fresh live billing summary was captured")
        return {"allowed": False, "reasons": reasons, "remaining_credit_usd": None, "headroom_usd": None}
    try:
        metered = to_decimal(billing_summary["metered_cost"], "metered_cost")
        billed = to_decimal(billing_summary["billed_cost"], "billed_cost")
        credits_applied = -to_decimal(billing_summary["adjustments"]["credits"], "adjustments.credits")
        pool = to_decimal(credit_pool_usd, "credit_pool_usd")
        reserve = to_decimal(reserve_usd, "reserve_usd")
        worst = to_decimal(worst_case_job_cost_usd, "worst_case_job_cost_usd")
    except (KeyError, TypeError, ControlRuntimeError) as e:
        reasons.append(f"billing summary/inputs are unreadable or incomplete: {e}")
        return {"allowed": False, "reasons": reasons, "remaining_credit_usd": None, "headroom_usd": None}
    if worst <= 0:
        reasons.append("worst-case job cost must be a positive estimate")
    if worst > MAX_AUTHORIZED_RUN_COST_USD:
        reasons.append(f"worst-case cost {worst} exceeds the maximum authorized run cost {MAX_AUTHORIZED_RUN_COST_USD}")
    if billed != 0:
        reasons.append(f"billed_cost is already {billed} (owner cash is being charged); a run must start from billed_cost == 0")
    if credits_applied < metered:
        reasons.append(f"credits applied ({credits_applied}) do not cover metered cost ({metered}) -- credits are not absorbing usage")
    remaining = pool - credits_applied
    headroom = remaining - reserve - worst
    if remaining <= 0:
        reasons.append(f"no known credit remains (pool {pool} - applied {credits_applied})")
    if remaining < reserve + worst:
        reasons.append(
            f"credit-coverage gate: remaining credit {remaining} < reserve {reserve} + maximum run cost {worst} "
            f"(headroom {headroom})"
        )
    return {
        "allowed": not reasons,
        "reasons": reasons,
        "remaining_credit_usd": str(remaining),
        "headroom_usd": str(headroom),
        "billed_cost_usd": str(billed),
        "metered_cost_usd": str(metered),
        "credits_applied_usd": str(credits_applied),
        "reserve_usd": str(reserve),
        "maximum_authorized_run_cost_usd": str(worst),
        "credit_pool_total_usd": str(pool),
    }


def build_financial_reconciliation(before: dict, after: dict | None, *, credit_pool_usd, reserve_usd,
                                   max_run_cost_usd, peak_billed_usd=None) -> dict:
    """Separate (never collapsed) owner-payable and credit-coverage figures.
    Any provider field that is unavailable is null with a recorded reason."""
    pool = to_decimal(credit_pool_usd, "credit_pool_usd")
    reserve = to_decimal(reserve_usd, "reserve_usd")
    out: dict = {"credit_pool_total_usd": str(pool), "reserve_usd": str(reserve),
                 "maximum_authorized_run_cost_usd": str(to_decimal(max_run_cost_usd, "max_run_cost_usd"))}
    null_reasons: dict[str, str] = {}

    def read(summary, key):
        try:
            if key == "billed":
                return to_decimal(summary["billed_cost"], "billed_cost")
            if key == "metered":
                return to_decimal(summary["metered_cost"], "metered_cost")
            return -to_decimal(summary["adjustments"]["credits"], "credits")
        except (KeyError, TypeError, ControlRuntimeError):
            return None

    b_b, m_b, c_b = (read(before, k) for k in ("billed", "metered", "credits"))
    b_a, m_a, c_a = ((read(after, k) for k in ("billed", "metered", "credits")) if after else (None, None, None))
    out.update({"billing_baseline_usd": None if b_b is None else str(b_b), "billing_postrun_usd": None if b_a is None else str(b_a),
                "metered_baseline_usd": None if m_b is None else str(m_b), "metered_postrun_usd": None if m_a is None else str(m_a),
                "credits_applied_baseline_usd": None if c_b is None else str(c_b),
                "credits_applied_postrun_usd": None if c_a is None else str(c_a)})
    peak = to_decimal(peak_billed_usd, "peak_billed_usd") if peak_billed_usd is not None else b_a
    out["billing_delta_usd"] = None if (peak is None or b_b is None) else str(peak - b_b)
    out["metered_delta_usd"] = None if (m_a is None or m_b is None) else str(m_a - m_b)
    out["derived_credit_remaining_before_usd"] = None if c_b is None else str(pool - c_b)
    out["derived_credit_remaining_after_usd"] = None if c_a is None else str(pool - c_a)
    for k in RECONCILIATION_FIELDS:
        if out.get(k) is None:
            null_reasons[k] = "provider billing field unavailable in the captured summary" if after or "postrun" not in k \
                else "no post-run billing summary captured"
    out["null_reasons"] = null_reasons
    out["derivation_note"] = ("credit_remaining = credit_pool_total - credits_applied (derived; Modal exposes no remaining-credit field). "
                              "billing_delta_usd uses the highest billed reading observed in-run or in the settle window.")
    return out


def assess_settlement(recon: dict, *, run_report_metered_usd=None) -> dict:
    """Does the account data now demonstrably reflect the completed run?
    Never invents a 'settled' claim: absent evidence => NOT_YET_OBSERVABLE."""
    reasons: list[str] = []
    try:
        billing_delta = to_decimal(recon["billing_delta_usd"], "billing_delta_usd")
        metered_delta = to_decimal(recon["metered_delta_usd"], "metered_delta_usd")
        credits_delta = to_decimal(recon["credits_applied_postrun_usd"], "credits post") - to_decimal(recon["credits_applied_baseline_usd"], "credits pre")
        remaining_after = to_decimal(recon["derived_credit_remaining_after_usd"], "remaining_after")
        reserve = to_decimal(recon["reserve_usd"], "reserve")
        cap = to_decimal(recon["maximum_authorized_run_cost_usd"], "cap")
    except (KeyError, TypeError, ControlRuntimeError) as e:
        return {"status": SETTLEMENT_NOT_OBSERVABLE, "reasons": [f"reconciliation figures unreadable: {e}"], "stop_before_next_control": True}
    report_known = run_report_metered_usd is not None
    report_visible = False
    if report_known:
        try:
            report_visible = to_decimal(run_report_metered_usd, "run_report_metered_usd") > 0
        except ControlRuntimeError:
            report_known = False
    if metered_delta <= 0:
        reasons.append("the completed run's metered usage is not yet visible in the account totals (metered_delta == 0)")
    elif report_known and not report_visible:
        reasons.append("account totals grew but the run's own itemized usage row is absent, so the growth cannot be attributed to the run")
    if metered_delta > 0 and credits_delta < metered_delta:
        reasons.append(f"credits applied grew by {credits_delta}, less than metered growth {metered_delta} -- credit coverage not confirmed")
    if billing_delta != 0:
        reasons.append(f"owner-payable amount changed by {billing_delta}")
    if remaining_after < reserve:
        reasons.append(f"derived remaining credit {remaining_after} fell below the reserve {reserve}")
    if metered_delta > cap:
        reasons.append(f"metered growth {metered_delta} exceeds the maximum authorized run cost {cap}")
    return {"status": SETTLEMENT_OBSERVED if not reasons else SETTLEMENT_NOT_OBSERVABLE, "reasons": reasons,
            "stop_before_next_control": bool(reasons)}


def lightning_gate_decision(state: dict | None, *, machine_rate_credits_per_hour, hard_runtime_cap_seconds,
                            prior_positive_owner_charge: bool = False) -> dict:
    """Decide whether a Lightning GPU run may START. Pure. Every unknown blocks.

    `state` is a fresh read of the account: {username, plan, payment_method_present, credits_available,
    balance_limit, machine: {enabled, tier_restricted, out_of_capacity, gpus}, live_gpu_machines}.
    Requires: expected account, FREE plan, NO payment method, zero owner charge so far, an enabled and
    unrestricted machine, no GPU already running, a worst-case cost (rate x hard cap) within the per-attempt
    credit cap, and credits >= worst-case cost + reserve."""
    reasons: list[str] = []
    if prior_positive_owner_charge:
        reasons.append("an owner cash charge was already observed -- further GPU runs are stopped")
    if not state:
        return {"allowed": False, "reasons": ["no fresh live Lightning account state was captured"]}
    try:
        rate = to_decimal(machine_rate_credits_per_hour, "machine_rate_credits_per_hour")
        cap_s = to_decimal(hard_runtime_cap_seconds, "hard_runtime_cap_seconds")
        credits = to_decimal(state["credits_available"], "credits_available")
        limit = to_decimal(state["balance_limit"], "balance_limit")
        worst = rate * cap_s / Decimal(3600)
    except (KeyError, TypeError, ControlRuntimeError) as e:
        return {"allowed": False, "reasons": [f"account state/inputs unreadable or incomplete: {e}"]}
    if state.get("username") != LIGHTNING_EXPECTED_USERNAME:
        reasons.append(f"authenticated as {state.get('username')!r}, not the verified account {LIGHTNING_EXPECTED_USERNAME!r}")
    if str(state.get("plan", "")).upper() != "FREE":
        reasons.append(f"plan is {state.get('plan')!r}, not FREE")
    if state.get("known_provider_gpu_block"):
        reasons.append(f"provider is known to refuse GPU start for this account state: {state['known_provider_gpu_block']}")
    if state.get("payment_method_present") is not False:
        reasons.append("a payment method is present or its absence is unverified -- owner cash could be charged")
    if limit != 0:
        reasons.append(f"balance_limit is {limit}, not 0 (negative balance / overdraft could be permitted)")
    m = state.get("machine") or {}
    if m.get("enabled") is not True or m.get("tier_restricted") is not False or m.get("out_of_capacity") not in (False, None):
        reasons.append("the target GPU machine is not enabled, is tier-restricted, or is out of capacity for this account")
    if state.get("live_gpu_machines") != 0:
        reasons.append("a GPU machine is already running or its state is unknown")
    if worst > LIGHTNING_PER_ATTEMPT_CREDIT_CAP:
        reasons.append(f"worst-case attempt cost {worst} credits exceeds the per-attempt cap {LIGHTNING_PER_ATTEMPT_CREDIT_CAP}")
    if credits < worst + LIGHTNING_RESERVE_CREDITS:
        reasons.append(f"credits {credits} < worst-case cost {worst} + reserve {LIGHTNING_RESERVE_CREDITS}")
    return {"allowed": not reasons, "reasons": reasons, "worst_case_credits": str(worst), "credits_available": str(credits),
            "reserve_credits": str(LIGHTNING_RESERVE_CREDITS), "per_attempt_cap_credits": str(LIGHTNING_PER_ATTEMPT_CREDIT_CAP)}


def _validate_lightning_financial(record: dict, evidence_root: Path) -> None:
    fin = record.get("lightning_financial")
    if not isinstance(fin, dict) or any(k not in fin for k in LIGHTNING_FINANCIAL_REQUIRED):
        raise ControlRuntimeError(f"a Lightning GPU-backed result requires lightning_financial with {LIGHTNING_FINANCIAL_REQUIRED}")
    if fin["payment_method_present"] is not False:
        raise ControlRuntimeError("payment_method_present must be False for zero-owner-cash acceptance")
    before, after, delta = (to_decimal(fin[k], k) for k in ("credits_before", "credits_after", "credit_delta"))
    if before - after != delta:
        raise ControlRuntimeError("credit_delta must equal credits_before - credits_after")
    if after < 0:
        raise ControlRuntimeError("credits_after is negative: complimentary credits were exhausted and owner cash may be charged")
    owner = to_decimal(fin["owner_charge_after_usd"], "owner_charge_after_usd") - to_decimal(fin["owner_charge_before_usd"], "owner_charge_before_usd")
    if owner != to_decimal(fin["owner_cash_delta_usd"], "owner_cash_delta_usd"):
        raise ControlRuntimeError("owner_cash_delta_usd disagrees with owner_charge_after - owner_charge_before")
    if to_decimal(record["owner_billed_delta_usd"], "owner_billed_delta_usd") != owner:
        raise ControlRuntimeError("owner_billed_delta_usd disagrees with the Lightning owner cash delta")
    for art in ("preflight", "credits_before", "credits_after"):
        node = (fin["artifacts"] or {}).get(art)
        if not isinstance(node, dict) or not _HEX64_RE.match(str(node.get("sha256", ""))) \
                or _artifact_sha(evidence_root, node.get("artifact", ""), f"lightning artifact {art}") != node["sha256"]:
            raise ControlRuntimeError(f"Lightning financial artifact {art!r} is missing or its hash does not verify")


def retry_permitted(attempts: list[dict]) -> bool:
    """§28: no retry after positive billing, an identity/licence/security
    problem, or unclear cost state. Only clearly technical/harness failures
    with a zero owner delta and a passing cleanup may be retried, and only
    by a fresh explicit decision (this never authorizes automatically)."""
    if not attempts:
        return True
    for a in attempts:
        if to_decimal(a["owner_billed_delta_usd"], "attempt owner_billed_delta_usd") != 0:
            return False
        if a["cleanup_result"] != "PASS":
            return False
    return attempts[-1]["outcome"] in ("TECHNICAL_FAILURE", "HARNESS_FAILURE")


def derive_runtime_status(*, technical: str, financial_acceptance: str, cleanup: str, owner_billed_delta_usd,
                          live_resources_after_cleanup) -> str:
    """The ONLY correct derivation of `runtime_qualification_status` from
    its inputs. RUNTIME_QUALIFIED requires technical PASS and financial PASS
    and clean teardown; technical success with a positive owner delta is
    NOT_ACCEPTED."""
    delta = to_decimal(owner_billed_delta_usd, "owner_billed_delta_usd")
    if technical == "BLOCKED_PENDING_ZERO_CASH_RUNWAY":
        return "BLOCKED_PENDING_ZERO_CASH_RUNWAY"
    if technical == "NOT_TESTED":
        return "NOT_TESTED"
    if technical == "NOT_PROVEN":
        return "NOT_COMPLETED"
    if technical != "QUALIFIED":
        return "FAILED"
    if delta != 0 or financial_acceptance != "PASS":
        return "NOT_ACCEPTED"
    if cleanup != "PASS" or live_resources_after_cleanup != 0:
        return "NOT_ACCEPTED"
    return "RUNTIME_QUALIFIED"


# ── result record validation (§20/§24/§26/§27/§29/§33/§34) ────────────────


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _walk_strings(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_strings(v)


def _walk_keys(node):
    if isinstance(node, dict):
        for k, v in node.items():
            yield str(k)
            yield from _walk_keys(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk_keys(v)


def _artifact_sha(evidence_root: Path, location: str, label: str) -> str:
    root = Path(evidence_root).resolve()
    path = (root / location).resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        raise ControlRuntimeError(f"{label} {location!r} escapes the evidence root") from e
    if not path.is_file():
        raise ControlRuntimeError(f"{label} {location!r} does not exist under the evidence root")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_attempts(record: dict) -> Decimal:
    attempts = record["attempts"]
    if not isinstance(attempts, list):
        raise ControlRuntimeError("attempts must be a list")
    total = Decimal(0)
    seen_positive = False
    for i, a in enumerate(attempts, start=1):
        missing = [f for f in ATTEMPT_REQUIRED_FIELDS if f not in a]
        if missing:
            raise ControlRuntimeError(f"attempt {i} missing required field(s): {missing}")
        if a["attempt_number"] != i:
            raise ControlRuntimeError(f"attempt history has a gap or reorder: expected attempt_number {i}, got {a['attempt_number']!r}")
        if a["outcome"] not in ATTEMPT_OUTCOMES:
            raise ControlRuntimeError(f"attempt {i} has unrecognized outcome {a['outcome']!r}")
        if a["cleanup_result"] not in CLEANUP_STATUSES:
            raise ControlRuntimeError(f"attempt {i} has unrecognized cleanup_result {a['cleanup_result']!r}")
        expected_domain = FAILURE_DOMAIN_BY_OUTCOME[a["outcome"]]
        if a.get("failure_domain", expected_domain) != expected_domain:
            raise ControlRuntimeError(
                f"attempt {i} failure_domain {a.get('failure_domain')!r} contradicts outcome {a['outcome']!r} (expected {expected_domain!r})")
        if a["outcome"] == "TECHNICAL_FAILURE" and a.get("valid_runtime_attempt") is not True:
            raise ControlRuntimeError(
                f"attempt {i}: a model-runtime failure requires an actual valid runtime attempt (valid_runtime_attempt must be True)")
        delta = to_decimal(a["owner_billed_delta_usd"], f"attempt {i} owner_billed_delta_usd")
        if seen_positive:
            raise ControlRuntimeError(f"attempt {i} occurred after a positive-billing attempt -- further GPU runs must have stopped")
        if delta > 0:
            seen_positive = True
        total += delta
    return total


def validate_control_runtime_record(record: dict, *, evidence_root: Path) -> None:
    """Raise `ControlRuntimeError` unless `record` is a fully-consistent,
    honestly-labeled control runtime record. Enforces, among others: no
    RUNTIME_QUALIFIED without technical PASS + financial PASS (delta exactly
    zero) + clean teardown + verified identity + verified hashes; capability
    always UNPROVEN; generated output never executed; no benchmark-flavoured
    fields; no secrets; a complete attempt history; a blocked/no-GPU record
    that truly shows no GPU attempt."""
    missing = [f for f in RECORD_REQUIRED_FIELDS if f not in record]
    if missing:
        raise ControlRuntimeError(f"record missing required field(s): {missing}")
    name = record["control_name"]
    if name not in LOCKED_CONTROL_IDENTITIES:
        raise ControlRuntimeError(f"control {name!r} is not one of the three locked controls (no substitutions)")
    locked = LOCKED_CONTROL_IDENTITIES[name]
    if record["evidence_kind"] != EVIDENCE_KIND:
        raise ControlRuntimeError(f"evidence_kind must be {EVIDENCE_KIND!r}: only runtime-qualification smoke evidence is accepted here")
    if record["capability_status"] != CAPABILITY_STATUS:
        raise ControlRuntimeError("capability_status must remain UNPROVEN after a runtime smoke")
    if record["generated_output_executed"] is not False:
        raise ControlRuntimeError("generated model output must never be executed (generated_output_executed must be False)")
    for key in _walk_keys(record):
        low = key.lower()
        if any(frag in low for frag in _CAPABILITY_KEY_FRAGMENTS):
            raise ControlRuntimeError(f"field {key!r} looks like benchmark/capability output; runtime evidence must not carry it")
    for text in _walk_strings(record):
        for pat in _SECRET_PATTERNS:
            if pat.search(text):
                raise ControlRuntimeError("record appears to contain a secret/credential; secrets must never be persisted")

    for field, allowed in (
        ("technical_serving_status", TECHNICAL_SERVING_STATUSES),
        ("financial_preflight_status", FINANCIAL_PREFLIGHT_STATUSES),
        ("financial_acceptance_status", FINANCIAL_ACCEPTANCE_STATUSES),
        ("runtime_qualification_status", RUNTIME_QUALIFICATION_STATUSES),
        ("cleanup_status", CLEANUP_STATUSES),
    ):
        if record[field] not in allowed:
            raise ControlRuntimeError(f"{field}={record[field]!r} is not one of {allowed}")

    # null-with-reason: never fabricate, never silently drop
    reasons = record["unobservable_reasons"]
    if not isinstance(reasons, dict):
        raise ControlRuntimeError("unobservable_reasons must be a mapping of metric -> reason")
    for metric in NULLABLE_METRICS:
        if record[metric] is None and not reasons.get(metric):
            raise ControlRuntimeError(f"metric {metric!r} is null without a recorded unobservable reason")
    for field in RECORD_REQUIRED_FIELDS:
        if field not in NULLABLE_METRICS and record[field] is None and field not in ("raw_log_artifact", "raw_log_sha256"):
            raise ControlRuntimeError(f"required field {field!r} may not be null")

    delta = to_decimal(record["owner_billed_delta_usd"], "owner_billed_delta_usd")
    attempts_total = _check_attempts(record)
    gpu_attempted = any(a["outcome"] != "BLOCKED_NO_GPU" for a in record["attempts"])
    technical = record["technical_serving_status"]
    financial = record["financial_acceptance_status"]
    runtime = record["runtime_qualification_status"]

    # identity is always required (§3.A/B, §26)
    if record["model_id"] != locked["model_id"] or record["model_revision"] != locked["revision"]:
        raise ControlRuntimeError(
            f"identity mismatch: {record['model_id']!r}@{record['model_revision']!r} != pinned "
            f"{locked['model_id']!r}@{locked['revision']!r}"
        )

    # blocked / never-run records
    if runtime in ("BLOCKED_PENDING_ZERO_CASH_RUNWAY", "NOT_TESTED") or technical in ("BLOCKED_PENDING_ZERO_CASH_RUNWAY", "NOT_TESTED"):
        if gpu_attempted:
            raise ControlRuntimeError("a BLOCKED/NOT_TESTED record may not contain a GPU attempt")
        if runtime == "BLOCKED_PENDING_ZERO_CASH_RUNWAY" and record["financial_preflight_status"] == "PASSED":
            raise ControlRuntimeError("BLOCKED_PENDING_ZERO_CASH_RUNWAY contradicts a PASSED financial preflight")
        if runtime == "RUNTIME_QUALIFIED":
            raise ControlRuntimeError("a blocked/untested control cannot be RUNTIME_QUALIFIED")
        return

    # from here a GPU-backed execution is claimed
    if not gpu_attempted or not record["attempts"]:
        raise ControlRuntimeError("a GPU-backed result requires a complete attempt history including the GPU attempt(s)")
    if record["financial_preflight_status"] != "PASSED":
        raise ControlRuntimeError("no GPU-backed result is valid without a PASSED fresh financial preflight")
    lightning = record.get("gpu_provider") == LIGHTNING_PROVIDER
    if lightning:
        _validate_lightning_financial(record, evidence_root)
    else:
        fin = record["financial_evidence"]
        if not isinstance(fin, dict) or any(k not in fin for k in FINANCIAL_EVIDENCE_REQUIRED):
            raise ControlRuntimeError(f"financial_evidence must contain {FINANCIAL_EVIDENCE_REQUIRED}")
        for art, sha in (("preflight_artifact", "preflight_sha256"), ("billing_before_artifact", "billing_before_sha256"),
                         ("billing_after_artifact", "billing_after_sha256")):
            if not _HEX64_RE.match(str(fin[sha])) or _artifact_sha(evidence_root, fin[art], art) != fin[sha]:
                raise ControlRuntimeError(f"financial evidence {art} hash does not verify")

        recon = record.get("financial_reconciliation")
        if not isinstance(recon, dict):
            raise ControlRuntimeError("a GPU-backed result requires a financial_reconciliation with separate billed/metered/credit figures")
        for k in RECONCILIATION_FIELDS:
            if k not in recon:
                raise ControlRuntimeError(f"financial_reconciliation missing {k!r}")
            if recon[k] is None and not (recon.get("null_reasons") or {}).get(k):
                raise ControlRuntimeError(f"financial_reconciliation.{k} is null without a recorded reason")
        if recon["billing_delta_usd"] is not None and to_decimal(recon["billing_delta_usd"], "reconciliation billing_delta_usd") != delta:
            raise ControlRuntimeError("financial_reconciliation.billing_delta_usd disagrees with owner_billed_delta_usd")
        settlement = record.get("billing_settlement")
        if not isinstance(settlement, dict) or settlement.get("status") not in (SETTLEMENT_OBSERVED, SETTLEMENT_NOT_OBSERVABLE):
            raise ControlRuntimeError("a GPU-backed result requires billing_settlement with an explicit status")
        disc = record.get("billing_discrepancy_observation")
        if not isinstance(disc, dict) or any(k not in disc for k in ("artifact", "sha256")):
            raise ControlRuntimeError("the unresolved billing-discrepancy observation must be referenced (artifact + sha256)")
        if _artifact_sha(evidence_root, disc["artifact"], "billing_discrepancy_observation") != disc["sha256"]:
            raise ControlRuntimeError("billing-discrepancy observation hash does not verify")

    # financial invariants (§20, §34)
    if financial == "PASS":
        if delta != 0:
            raise ControlRuntimeError(f"financial_acceptance PASS requires owner_billed_delta_usd == 0, got {delta}")
        if attempts_total != 0:
            raise ControlRuntimeError("financial_acceptance PASS is inconsistent with a positive per-attempt billed delta")
    if delta > 0 and (financial != "FAILED" or runtime == "RUNTIME_QUALIFIED"):
        raise ControlRuntimeError("positive incremental owner billing must yield financial_acceptance FAILED and never RUNTIME_QUALIFIED")
    if delta != attempts_total:
        raise ControlRuntimeError(f"owner_billed_delta_usd {delta} disagrees with the attempt history total {attempts_total}")

    last_attempt = record["attempts"][-1]
    last_domain = FAILURE_DOMAIN_BY_OUTCOME[last_attempt["outcome"]]
    if technical == "FAILED" and not (last_domain == "MODEL_RUNTIME" and last_attempt.get("valid_runtime_attempt") is True):
        raise ControlRuntimeError(
            "technical_serving_status FAILED requires a valid model-runtime attempt; a harness failure or financial-guard abort "
            "cannot become a model-runtime FAILED (it leaves runtime compatibility NOT_PROVEN)")
    if last_domain in ("HARNESS", "FINANCIAL_GUARD") and technical != "NOT_PROVEN":
        raise ControlRuntimeError(
            f"the last attempt ended in {last_domain}; technical_serving_status must be NOT_PROVEN, got {technical!r}")
    expected = derive_runtime_status(
        technical=technical, financial_acceptance=financial, cleanup=record["cleanup_status"],
        owner_billed_delta_usd=delta, live_resources_after_cleanup=record["live_resources_after_cleanup"],
    )
    if runtime != expected:
        raise ControlRuntimeError(f"runtime_qualification_status={runtime!r} but the evidence derives {expected!r}")

    if runtime == "RUNTIME_QUALIFIED":
        _validate_qualified(record, locked, evidence_root)


def _validate_qualified(record: dict, locked: dict, evidence_root: Path) -> None:
    if record["technical_serving_status"] != "QUALIFIED" or record["financial_acceptance_status"] != "PASS":
        raise ControlRuntimeError("RUNTIME_QUALIFIED requires technical QUALIFIED and financial PASS")
    if record["cleanup_status"] != "PASS" or record["live_resources_after_cleanup"] != 0:
        raise ControlRuntimeError("RUNTIME_QUALIFIED requires cleanup PASS and zero live resources")
    if record.get("gpu_provider") == LIGHTNING_PROVIDER:
        if record["lightning_financial"]["credit_meter_stopped"] is not True:
            raise ControlRuntimeError("RUNTIME_QUALIFIED requires proof that the Lightning credit meter stopped after cleanup")
    elif record["billing_settlement"]["status"] != SETTLEMENT_OBSERVED:
        raise ControlRuntimeError("RUNTIME_QUALIFIED requires the run's billing/credit coverage to be observed in the account data")
    last = record["attempts"][-1]
    if last["outcome"] != "TECHNICAL_SUCCESS" or last["cleanup_result"] != "PASS":
        raise ControlRuntimeError("the final attempt must be a TECHNICAL_SUCCESS with a passing cleanup")

    ident = record["identity_verification"]
    for key in ("pinned_revision_matches_runtime_artifact", "runtime_served_model_matches_pinned_id",
                "weight_bytes_observed", "no_silent_model_fallback", "identity_evidence_strength"):
        if key not in ident:
            raise ControlRuntimeError(f"identity_verification missing {key!r}")
    if ident["pinned_revision_matches_runtime_artifact"] is not True or ident["runtime_served_model_matches_pinned_id"] is not True:
        raise ControlRuntimeError("runtime identity does not match the pinned model/revision")
    if ident["no_silent_model_fallback"] is not True:
        raise ControlRuntimeError("a silent model fallback was not ruled out")
    if ident["weight_bytes_observed"] != locked["expected_weight_bytes"]:
        raise ControlRuntimeError(
            f"observed weight bytes {ident['weight_bytes_observed']!r} != expected {locked['expected_weight_bytes']} for the pinned revision"
        )

    log_sha = record["raw_log_sha256"]
    if not record["raw_log_artifact"] or not _HEX64_RE.match(str(log_sha)):
        raise ControlRuntimeError("RUNTIME_QUALIFIED requires a persisted raw log with a 64-hex sha256")
    if _artifact_sha(evidence_root, record["raw_log_artifact"], "raw_log_artifact") != log_sha:
        raise ControlRuntimeError("raw log bytes do not match raw_log_sha256")

    outputs = record["smoke_outputs"]
    prompts = record["smoke_prompts"]
    if not isinstance(outputs, list) or not isinstance(prompts, list):
        raise ControlRuntimeError("smoke_prompts and smoke_outputs must be lists")
    if sorted(o.get("smoke_id") for o in outputs) != list(REQUIRED_SMOKE_IDS) or sorted(p.get("smoke_id") for p in prompts) != list(REQUIRED_SMOKE_IDS):
        raise ControlRuntimeError(f"exactly smoke prompts/outputs {REQUIRED_SMOKE_IDS} are required")
    for o in outputs:
        if not o.get("http_status") == 200 or not isinstance(o.get("raw_response"), str) or not o["raw_response"]:
            raise ControlRuntimeError(f"smoke {o.get('smoke_id')!r} has no successful raw response")
        if hashlib.sha256(o["raw_response"].encode()).hexdigest() != o.get("raw_response_sha256"):
            raise ControlRuntimeError(f"smoke {o.get('smoke_id')!r} raw_response_sha256 does not verify")
        if o.get("executed") is not False:
            raise ControlRuntimeError(f"smoke {o.get('smoke_id')!r} output must be marked executed=False")

# Phase 21B.4.6 — Modal Zero-Cost Compute + Provider-Native Sandbox Qualification

## Outcome: architecture built and mock-tested; live account verification blocked at the same boundary as Phase 21B.4.5

## Live-verified public facts (2026-09-18, from modal.com directly, not memory)

- **Pricing**: Starter plan $0/month + $30/month included compute, 3
  workspace seats, 100 containers + 10 GPU concurrency. Live GPU rates
  (per-second): T4 $0.000164 (~$0.59/hr), L4 $0.000222 (~$0.7992/hr --
  matches the phase spec's planning reference exactly), A10
  $0.000306 (~$1.1016/hr -- also matches), L40S $0.000542/sec
  (~$1.95/hr), A100-40GB $0.000583/sec (~$2.10/hr), A100-80GB
  $0.000694/sec (~$2.50/hr), H100 $0.001097/sec (~$3.95/hr).
- **No credit card required for Starter** -- confirmed both by Modal's
  own pricing page framing and independent third-party sources; signup
  is OAuth-based (GitHub/Google/SSO), not a card-gated form.
- **Critical correction to the spec's assumed billing model**: Modal's
  own FAQ states *"Starter has no monthly fee and includes $30 of
  compute per month. You're billed when you exceed that."* This is a
  **pay-as-you-go account model**, not a hard-stop-at-zero model like
  Lightning's documented "gracefully shut down" behavior (Phase
  21B.4.5). Without an explicit safeguard, exceeding $30 is described
  as leading to billing, not merely a shutdown.
- **The safeguard that makes ₹0 provable exists and is first-party
  documented**: Modal's **Workspace spend limit** is defined as *"a
  monthly cap on net charges (what you pay out of pocket after credits
  are applied)... When the spend limit is reached, Modal stops
  workloads that would incur additional out-of-pocket charges."*
  Critically, the **default** spend limit is *usage limit minus
  credits* (e.g. $100 usage limit − $30 credit = $70 default
  out-of-pocket exposure) -- **not ₹0 by default**. The owner (or
  whoever holds the account) must explicitly set the Workspace spend
  limit to **$0** for the documented hard-stop behavior to apply to
  every dollar beyond the free $30. This is the single concrete action
  that converts Modal from "probably safe if you're careful" into
  "provably ₹0, mechanically enforced."
- **Sandbox API** (`modal.Sandbox.create`, live-verified against
  Modal's own reference docs): `block_network: bool` (full outbound
  block), `outbound_cidr_allowlist`/`outbound_domain_allowlist` (finer
  network policy, not used here since we want the strictest option),
  `cpu: float | tuple[float, float]` (request, hard limit),
  `memory: int | tuple[int, int]` (request, hard limit, MiB),
  `timeout: int` (max lifetime, default 300s), `idle_timeout: int`,
  `secrets: Collection[_Secret] | None` (nothing injected unless
  explicitly passed), `volumes`/`network_file_systems` (empty by
  default -- no repo/model-cache/credential mount unless explicit).
  Isolation runtime: **gVisor** (Google's syscall-intercepting
  container runtime) -- a real, independently-known, structurally
  different-but-comparable mechanism to Docker's kernel namespace
  isolation, not a Python-level guard and not a marketing claim taken
  on faith.

## What was built (spec sections 1, 4-8)

- `orca/eval/sandbox_modal.py` -- `run_sandboxed_modal()` translates
  ORNEUR's exact security contract into the live-verified Modal
  Sandbox parameters above, returning the same `DockerSandboxResult`
  shape the Docker backend uses. `ModalSandboxContract` /
  `current_modal_contract()` -- a versioned, inspectable record
  analogous to `orca.eval.sandbox_contract.SandboxContract`, kept
  separate rather than forced into Docker's field shape (Modal has no
  `--cap-drop`/`--security-opt` equivalent; gVisor is structurally
  different).
- `orca/eval/sandbox_backend.py` -- added `ModalSandboxBackend`
  implementing the existing `SandboxBackend` protocol.
  `get_default_backend()` **still returns `DockerSandboxBackend`**,
  unchanged -- Docker remains the only backend with a live,
  adversarially-verified security record (Phase 21B.4.1). No
  Genesis-specific logic was placed inside the Modal adapter (spec
  section 4); it only translates the same contract Docker already
  implements.
- `tests/test_sandbox_modal.py` -- 20 tests, entirely mocked at the
  `modal.Sandbox.create` boundary via a `sandbox_factory` injection
  seam (no `modal` package or account required anywhere in CI). Proves
  the adapter correctly REQUESTS `block_network=True`, hard CPU/memory
  limits, a bounded timeout with no ambient environment/secrets, no
  volumes, guaranteed termination on success/exception/timeout, and
  fail-closed behavior on malformed output, empty output, oversized
  output, and provider exceptions.

**These are adapter-correctness tests only.** They are NOT evidence
that Modal's live security boundary has been independently verified
the way Docker's was in Phase 21B.4.1 -- no live adversarial
re-verification (filesystem/network/ctypes escape attempts against a
real running Modal Sandbox) has been performed, because no Modal
account exists for this session to test against.

## Live account gate (spec section 9): blocked at the same boundary as Phase 21B.4.5

Creating/authenticating a Modal account belongs to the owner; this
agent does not create accounts or enter credentials on the owner's
behalf, independent of whether payment information is involved. No
Modal workspace was authenticated this phase. Consequently:
- Plan tier, actual included-compute balance, payment-method status,
  and live overage behavior were NOT confirmed against a real account
  (only Modal's own public documentation was verified, as detailed
  above).
- GPU availability, `nvidia-smi`, PyTorch/Transformers/bitsandbytes
  CUDA behavior, and NF4/bfloat16 support were NOT tested live -- no
  CUDA device exists on this development machine, and no Modal GPU
  Sandbox was created.
- The live adversarial sandbox re-verification (spec section 3's full
  list: filesystem/repo/secret/network/ctypes escape, process control,
  timeout survival, artifact persistence) was NOT performed against a
  real Modal Sandbox.

No live result is fabricated in place of these. The exact owner setup
steps to unblock them are in
`docs/orneur/phase-21/PHASE21B4_6_MODAL_QUALIFICATION.md`'s final
report (delivered as the phase's chat response) Section N.

## Foundation target, 10K target (spec sections 11, 17-18)

Unaffected. Qwen3-8B, Mistral-Nemo-Instruct-2407, and Phi-4 remain the
three finalists; no model was substituted or downgraded. The permanent
10,000-real-time-user production target remains locked and is
explicitly unrelated to this development/evaluation compute research.

## genesis-eval-v1

Untouched -- not executed, not inspected, not frozen. This phase was
resource/security qualification and architecture only.

## Lightning AI status (spec section 15)

Recorded, not discarded: `LIGHTNING_NO_CARD_5_CREDIT_PATH` remains
available for later qualification/experiments/independent verification
per Phase 21B.4.5's findings. No Lightning credits were spent this
phase.

## Phase 21C

Remains locked. Not authorized. Not started.

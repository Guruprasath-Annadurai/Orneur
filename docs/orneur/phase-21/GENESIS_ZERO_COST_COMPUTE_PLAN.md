# Genesis Zero-Cost Compute Plan (Phase 21B.4.4)

## Strongest immediately available free option

**Lightning AI free plan** — 15 monthly credits (~22 GPU-hours on a
T4, 16GB VRAM). Satisfies the *minimum viable* resource class
established in Phase 21B.4.3 (16GB VRAM, uniform 4-bit NF4 across all
three finalists, tightest margin ~6.6GB on Phi-4). Does **not** reach
the *preferred* 24GB class.

**Not yet confirmed live**: (1) whether Lightning Studios expose a
real Docker daemon for nested container execution (needed by our
sandbox), and (2) the exact free-tier billing behavior without a card
on file. Both must be verified with a real, disposable test session
before any owner authorization to run the actual shootout — this plan
does not claim readiness it hasn't demonstrated.

## Strongest application-based option

**AWS Activate — Founders Tier**, via **NVIDIA Inception** (which
itself references up to $100,000 in AWS Activate credit for approved
members) as the stronger long-term path, or the AWS Founders tier
directly ($1,000 + $350 support credit, no VC-backing required, no
prior AWS Activate use). Either path reaches a genuine G5.xlarge
(A10G, 24GB) instance — the *preferred* resource class — with full
Docker/root access and a card-based account that a hard AWS Budgets
cap can make provably safe (see Zero-cost guarantee below).

NVIDIA Inception's stated eligibility requires official incorporation;
**this has not been confirmed for ORNEUR/the owner this session** and
must be checked before applying there specifically. AWS Activate
Founders Tier's own eligibility (<10 employees, <$1M funding, no VC
affiliation, no prior Activate credits) does not require incorporation
and is the more immediately actionable application path.

## Expected credits

- Lightning AI: ~22 GPU-hours/month (T4, 16GB) — renews monthly, no
  cash cost
- AWS Activate Founders: $1,000 + $350 support credit — far exceeds
  the ~$6 estimated full three-model shootout cost (Phase 21B.4.3
  Section 9), leaving large headroom for retries/reruns

## GPU / Docker compatibility

| Option | GPU | VRAM | Docker | Meets resource class |
|---|---|---|---|---|
| Lightning AI (free) | T4 | 16GB | Plausible, **unverified** | Minimum viable |
| AWS Activate (G5.xlarge) | A10G | 24GB | YES (standard EC2 root access) | Preferred |

## Estimated shootout credit/cost use

Same planning assumptions as Phase 21B.4.3 Section 9: ~70.2GB one-time
download, ~8hr total wall-clock GPU time for all three finalists
(Qwen3-8B, Mistral-Nemo-Instruct-2407, Phi-4) under uniform 4-bit NF4.
- Lightning AI: ~8 of ~22 monthly GPU-hours (well within quota, leaves
  margin for a smoke-test session and retries)
- AWS Activate: at G5.xlarge's on-demand rate (roughly $1-1.5/hr for
  this instance class per general AWS pricing, to be confirmed live at
  execution time, not assumed from memory), ~8hr ≈ single-digit-to-
  low-double-digit dollars — trivial against a $1,000+ credit balance

## ₹0 guarantee mechanism

- **Lightning AI**: use only the free-tier allocation; do not select
  a paid GPU tier (A10G/L40S) that would consume credits faster or
  cross into billed usage; monitor the monthly credit balance before
  and during any session; stop before exhausting the free allocation.
- **AWS Activate**: before any instance is launched, configure (a) an
  AWS Budgets hard cap set below the credit balance with an alert at
  50%/80%/100%, (b) a billing alarm via CloudWatch, and (c) explicit
  confirmation that the account's payment method has been reviewed by
  the owner and that no auto-scaling or persistent (always-on)
  resources are created. Credits are consumed first; the account is
  never allowed to reach $0 remaining credit while a resource is still
  running unattended. No resource is left running after a session
  ends (explicit shutdown, not "will time out eventually").

**No provisioning has occurred under this plan.** Both paths require
either a live verification step (Lightning) or an approval step (AWS
Activate) before they can be called ready.

## Execution readiness

Neither path is currently `FREE COMPUTE READY` in the strict sense of
spec section 12 (an already-available, already-guaranteed-₹0 resource)
— see `GENESIS_FREE_COMPUTE_EXECUTION_GATE.md` for the exact next
steps and the exact authorization string required once one is.

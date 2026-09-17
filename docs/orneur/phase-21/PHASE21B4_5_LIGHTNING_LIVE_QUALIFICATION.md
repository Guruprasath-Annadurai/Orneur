# Phase 21B.4.5 — Lightning AI Zero-Cost Live Resource Qualification

## Outcome: BLOCKED at the account-creation boundary, not at a technical/financial finding

This phase asked for LIVE verification against an actual Lightning AI
account: dashboard balance, `docker version`/`nvidia-smi` inside a
Studio, live GPU availability. **Creating accounts (or entering
passwords to authenticate) on the owner's behalf is outside what this
agent is permitted to do autonomously** — this is a hard operating
boundary, not a judgment call, and it applies regardless of whether
payment information is involved. Everything checkable from Lightning
AI's own public documentation and pricing pages (no login required)
was verified live this session; everything requiring an authenticated
account was not attempted, and is not fabricated below.

## Live-verified facts (corrects the phase's planning assumptions)

Fetched directly from `lightning.ai/pricing` and
`lightning.ai/docs/overview/faq/billing`, 2026-09-18 — not reused from
memory or from the phase spec's own "current findings to verify":

- **The phase spec's assumed "15 free credits/month" and "0.48
  credits/hr for L4 -> ~31 L4-hours" figures do not match live
  documentation.** The live pricing page states **up to 30 credits**
  total (a signup allowance, not a monthly recurring grant), and L4
  is priced at **$0.79/GPU-hr** (1 credit = $1, per the billing FAQ),
  which is where the "31 free hours" marketing figure comes from
  (30 credits / $0.79 [?] ~38, or measured against blended
  interruptible/on-demand pricing — the exact arithmetic isn't fully
  disclosed, but 31 hours is the number Lightning itself publishes
  for L4 specifically).
- **Critical finding directly affecting the owner's ₹0 constraint**:
  per Lightning's own FAQ, *"You get 5 free Lightning credits upon
  registration. Add a card for 25 more."* The full ~30-credit /
  ~31-L4-hour allowance the phase spec's "current findings" described
  **requires adding a payment method**. Under the owner's explicit
  "do not add a payment method" instruction, the genuinely
  card-free allowance is **5 credits**, not 30.
- At 5 credits: **~6.3 hours of L4** (5 / $0.79/hr) or **~9.1 hours of
  T4** (5 / $0.55/hr). Phase 21B.4.3's planning estimate for a full
  three-model, 90-task shootout was ~8 wall-clock GPU-hours (already
  including setup/download/retry margin). 5 no-card credits are
  **likely insufficient on L4** and only **marginally sufficient on
  T4, with no safety margin**, for the full three-candidate shootout
  in one pass.
- GPU rate table (per-GPU/hr, live): T4 16GB $0.55, L4 24GB $0.79,
  L40S 48GB $2.14, A100-40GB $2.19, A100-80GB $2.71, H100/H200 $4.50
  (no free hours listed for H100/H200 on the free tier).
- Free tier limits (live): 1 free active Studio, 4-hour restart cycle
  for the Studio itself; max 1 GPU per Studio; max 2 concurrent GPUs;
  persistent storage capped at 50GB total (first 10GB free, then
  $0.10/GB/month if exceeded — a real billing mechanism that requires
  a card to actually charge, so staying under 10GB used is the
  concrete zero-cost safeguard here, not merely a preference); GPU
  session-limit language is genuinely ambiguous between the FAQ table
  ("T4, L4, L40S session limit: Unlimited" vs "A100, H100, H200
  session limit: 4 hours") and the marketing copy ("Free Studios run
  24/7 but require restart every 4 hours") — **this specific ambiguity
  needs live account confirmation, not resolution from marketing text**.
- Signup requires phone-number verification ("to prevent abuse of the
  platform") — a friction/privacy fact, not a cash-risk fact, but one
  the owner should know before signing up.
- "When credits are running low, Lightning AI will warn users and
  then attempt to gracefully shut down all workloads and Studios." —
  this is a genuinely positive sign for the ₹0 guarantee (shutdown on
  exhaustion, not automatic billing), but it is stated behavior from
  documentation, not something this session observed happening on a
  real account.

## What remains genuinely unverified, and why

Sections A (account tier/card-attached/actual balance), most of B
(live GPU *availability*, as opposed to the published rate table), C
(`nvidia-smi`, driver, CUDA/PyTorch/Transformers/bitsandbytes versions
inside an actual Studio), D (Docker daemon live check, the full
Phase-21B.4.1-equivalent sandbox security re-verification), and E (a
live NF4 tensor test) all require an authenticated Lightning Studio
session. None of these were run. None are reported as verified below.

## Concrete unblock path

Lightning Studios advertise SSH access ("Connect via SSH" is listed as
a Free-tier feature). This environment has a working `ssh` client. The
fastest path to completing this phase's live verification is:

1. The owner creates a Lightning AI account directly (self-serve,
   phone-verified, **no payment method added** — confirmed above that
   the no-card path yields 5 free credits, which is enough for the
   Docker/CUDA/NF4 qualification checks in this phase, which are
   explicitly small/non-eval per spec section 9, even though it is
   likely NOT enough for the full three-model shootout later).
2. The owner starts one Studio (T4 or L4, whichever is offered) and
   either:
   - shares SSH connection details (host + the Studio's own generated
     key, never a Lightning account password) so this agent can
     connect directly and run the live verification commands itself, or
   - runs the exact commands below themselves inside the Studio's
     browser terminal and pastes the output back.

Exact commands for whichever path is used (per spec sections 5-6):
```bash
nvidia-smi
docker version
docker info
docker ps
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0))"
python3 -c "import transformers; print(transformers.__version__)"
python3 -c "import bitsandbytes; print(bitsandbytes.__version__)"
```

Plus the exact Phase 21B.4.1-equivalent sandbox adversarial checks
(filesystem/network/ctypes/process escape attempts) run against
whatever Docker daemon is actually found, before any conclusion about
"nested sandbox works" is drawn.

## No code changes this phase

Pure research/verification phase; no Genesis code was modified. No
account was created. No payment method was added. No credits were
spent. `genesis-eval-v1` was not touched.

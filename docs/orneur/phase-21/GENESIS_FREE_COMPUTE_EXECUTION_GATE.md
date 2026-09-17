# Genesis Free Compute Execution Gate (Phase 21B.4.4)

## Status: NO SUITABLE RESOURCE IS CURRENTLY CONFIRMED READY

Per spec section 17 — this is not a recommendation to pay, and not a
downgrade of the model target. It is an honest statement that neither
researched path has cleared verification/approval yet.

## Pending paths, in priority order

1. **Lightning AI free plan (minimum-viable, 16GB T4)** — pending:
   - Live verification that a Lightning Studio exposes genuine Docker
     daemon access (a disposable test session, not a production run,
     would answer this)
   - Live confirmation of card-free billing behavior on the free tier
   - If both confirmed: this becomes usable **immediately**, at zero
     stated cost, for the *minimum viable* resource class

2. **AWS Activate — Founders Tier ($1,000 + $350 credit, preferred
   24GB A10G class)** — pending:
   - Application submission (owner-initiated; requires AWS account
     details this session does not have and should not create/manage
     unilaterally)
   - Approval (timeline not confirmed this session)
   - Post-approval: hard AWS Budgets cap + billing alarm configuration
     before any instance launch

3. **NVIDIA Inception (potential $100k-$150k partner credit pool)** —
   pending:
   - Confirmation of ORNEUR/the owner's incorporation status (a stated
     hard eligibility requirement this session cannot verify)
   - If eligible: application submission, 2-4 week typical response

4. **Vast.ai Startup Program ($2,500 credit)** — pending:
   - Direct outreach to their team (not a self-serve form)
   - Terms confirmation (card requirement, credit expiry not public)

## Alternative zero-cost routes

- **Sandbox portability** (spec section 6): the newly-added
  `orca.eval.sandbox_backend.SandboxBackend` abstraction means a
  future platform offering equivalent-strength isolation *without* a
  literal `docker` binary could become usable without re-architecting
  Genesis's evaluator — but no such alternative backend has been
  identified or verified this phase. Hugging Face Spaces (ZeroGPU),
  Colab, Kaggle, and Modal were all re-examined and remain unsuitable
  for the same underlying reason as Phase 21B.4.3: none currently
  expose a nested container-execution boundary this project's
  evaluator can call into and independently verify, the way Docker's
  `--network none` / `--read-only` / `--pids-limit` guarantees were
  empirically verified in Phase 21B.4.1.
- **Waiting** is an acceptable outcome. The owner's explicit framing
  (spec section 17: "We can wait for suitable free compute rather
  than compromise the Genesis model target") is honored here — no
  finalist was swapped for a weaker model merely because a free GPU
  for it was easier to obtain.

## What would make this ready

Any ONE of:
- Live-verified Docker access on a Lightning AI Studio, with confirmed
  no-card-required billing on the free tier, OR
- An approved AWS Activate (or NVIDIA Inception partner) credit grant
  with a hard budget cap configured, OR
- A confirmed, terms-reviewed Vast.ai Startup Program grant, OR
- A newly identified, independently-verified alternative meeting the
  *preferred* or *minimum viable* resource contract from Phase
  21B.4.3 at genuine ₹0 owner cash risk.

## Exact authorization string needed once ready

For the Lightning AI path (if Docker/billing verification succeeds):

```
APPROVED — EXECUTE GENESIS FOUNDATION SHOOTOUT USING LIGHTNING AI FREE PLAN, NVIDIA T4 (16GB), MAXIMUM OWNER CASH SPEND ₹0, MAXIMUM CREDIT CONSUMPTION 22 GPU-HOURS.
```

For the AWS Activate path (if approved):

```
APPROVED — EXECUTE GENESIS FOUNDATION SHOOTOUT USING AWS ACTIVATE (FOUNDERS TIER), NVIDIA A10G (24GB, G5.xlarge), MAXIMUM OWNER CASH SPEND ₹0, MAXIMUM CREDIT CONSUMPTION $50.
```

Neither string is being requested as approved by this document — both
are provided so the owner can issue the correct one once the
corresponding path is actually confirmed ready.

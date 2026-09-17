# Genesis Free GPU Credit Matrix (Phase 21B.4.4)

Researched live via web search, 2026-09-18. GPU-credit programs change
frequently and terms should be re-verified on the provider's own page
immediately before any signup. Figures below come from a mix of
provider-first-party pages and third-party aggregator summaries (noted
per-row); aggregator-sourced figures are directional, not contractual.

Categories used below: **IMMEDIATELY USABLE** (no application wait,
though account signup/verification may still be needed),
**APPLICATION REQUIRED** (a review/approval step gates access),
**NOT SUITABLE** (fails a hard technical or financial-safety
requirement).

---

### Lightning AI (free plan)
- Credit amount: 15 monthly credits (~$15 value, ~22 GPU-hours/month on a T4-class GPU)
- Cash payment required: not for the free tier itself
- Card required: uncertain from public sources — **must be verified live at signup before relying on this**
- GPU classes available: T4 (free tier); A10G/L40S consume credits faster if selected
- 24GB+ CUDA available: NO on the free tier (T4 is 16GB) — fits this project's *minimum viable* 16GB contract from Phase 21B.4.3, not the preferred 24GB one
- Docker/root access: Lightning Studios are persistent Linux environments with a real terminal (unlike Colab/Kaggle's managed notebook kernels) — this is a genuinely promising lead for Docker support, but **not yet live-verified this phase** (no account was created)
- Storage: 10GB Drive + 100GB Studio storage (free tier)
- Credit expiry: monthly (use-it-or-lose-it allowance, not a one-time balance)
- Application required: no — self-serve signup
- Approval time: N/A
- Startup eligibility: N/A (available to all)
- Open-source eligibility: N/A (available to all)
- Research eligibility: N/A (available to all)
- Geographic limitations: not found in this research pass
- Automatic paid conversion: the Studio itself is free for the first 4 hours then "switches to billed" per one source — needs live verification of what "billed" means without a card on file (may simply pause/stop rather than charge)
- Suitable for Genesis: **CONDITIONALLY** — satisfies the *minimum viable* (16GB) resource class at zero stated cost, IF Docker/root access and the no-card billing behavior are confirmed live
- Reason: only free-tier lead found this session with a plausible path to genuine Docker/root access; VRAM is below the *preferred* 24GB class but meets the *minimum viable* class established in Phase 21B.4.3
- **Classification: IMMEDIATELY USABLE, pending live verification of Docker access and card-free billing behavior**

---

### Hugging Face Spaces (ZeroGPU / Community GPU Grants)
- Credit amount: ZeroGPU gives shared, quota-limited A100 access at no cost; Community GPU Grants provide in-kind A10G/ZeroGPU hardware (not cash) for approved projects
- Cash payment required: no
- Card required: no (for ZeroGPU free quota)
- GPU classes available: A100 (ZeroGPU, shared/queued), A10G (grant-approved Spaces)
- 24GB+ CUDA available: A100 exceeds 24GB when granted, but access is a shared, queued, per-request quota model designed for interactive Spaces apps, not a dedicated long-running evaluation host
- Docker/root access: HF Spaces supports a `docker` SDK (you provide a Dockerfile that becomes the Space's own serving container), but this does **not** give a nested Docker daemon to run child containers inside that container — it is the same class of limitation as Colab/Kaggle/Modal for our exact sandbox design
- Storage: varies by Space tier
- Credit expiry: ZeroGPU quota resets on a rolling/queued basis, not a depleting balance
- Application required: ZeroGPU quota is self-serve; Community GPU Grants require an application (open-source traction, research/community value)
- Approval time: Community GPU Grants — not found precisely this session; treat as weeks, not days
- Startup eligibility: not the primary angle — open-source/research/community value is
- Open-source eligibility: YES — ORNEUR is a strong fit for this angle specifically
- Research eligibility: YES
- Geographic limitations: not found
- Automatic paid conversion: no — ZeroGPU quota simply queues/limits, doesn't bill
- Suitable for Genesis: **NO**, for this exact pipeline, same reasoning as Modal/Colab/Kaggle in Phase 21B.4.3 — no nested Docker daemon inside the execution environment
- Reason: architecturally excellent open-source fit, but fails the Docker-isolation requirement (Section 6) the same way the previously-rejected platforms did
- **Classification: NOT SUITABLE (for this pipeline, as currently architected)**

---

### NVIDIA Inception Program
- Credit amount: access to partner credits — up to $100,000 AWS Activate credits, up to $150,000 Nebius cloud credits (eligible members), plus DLI training credits
- Cash payment required: no — no fees, no equity
- Card required: not for the Inception program itself; downstream partner credits (AWS, Nebius) may still require a card on the partner platform
- GPU classes available: via partner clouds — effectively any class including 24GB+ (A10G, L40S, A100) through AWS/Nebius
- 24GB+ CUDA available: YES, via partner credits
- Docker/root access: YES, via partner clouds (standard cloud VM access)
- Storage: via partner clouds, typically generous
- Credit expiry: partner-credit-dependent (AWS Activate credits are commonly ~1-2 years)
- Application required: **YES**
- Approval time: initial response typically 2-4 weeks
- Startup eligibility: requires official incorporation, a working website, at least one developer, under 10 years old — **the owner's incorporation status for ORNEUR is unknown to this session and must be confirmed before applying**, since "officially incorporated" is a stated hard eligibility criterion
- Open-source eligibility: not the primary criterion (this is a startup program, not an open-source-specific one)
- Research eligibility: not the primary angle
- Geographic limitations: not found
- Automatic paid conversion: depends on the downstream partner credit's own terms — must be checked per-partner before use
- Suitable for Genesis: **CONDITIONALLY**, pending confirmation of ORNEUR's incorporation status (a stated hard requirement this session cannot verify)
- Reason: by far the largest potential credit pool found, but gated on an eligibility fact (incorporation) this session cannot confirm or fabricate
- **Classification: APPLICATION REQUIRED (eligibility uncertain — incorporation status must be confirmed by the owner first)**

---

### AWS Activate — Founders Tier
- Credit amount: $1,000 AWS credits + $350 developer support credits
- Cash payment required: no
- Card required: yes, standard AWS account requirement — **a live billing-alert/budget cap is the safeguard, not absence of a card**
- GPU classes available: G5 (A10G, 24GB) and similar EC2 GPU instance families are explicitly credit-eligible
- 24GB+ CUDA available: YES (G5.xlarge = 1x A10G 24GB)
- Docker/root access: YES — standard EC2 instance, full root, Docker installs normally
- Storage: standard EBS volumes, sized as provisioned (no special limit from the credit itself)
- Credit expiry: not found precisely for Founders tier this session; Portfolio tier credits are noted as valid ~2 years elsewhere in the same research
- Application required: **YES**
- Approval time: not found precisely this session
- Startup eligibility: <10 employees, <$1M revenue/funding, no VC affiliation required, no prior AWS Activate credits
- Open-source eligibility: not the primary criterion
- Research eligibility: not the primary criterion
- Geographic limitations: not found
- Automatic paid conversion: **YES if usage exceeds the credit balance** — this is a real AWS account with live billing; a hard AWS Budgets cap + billing alarm is required before any use (see Section 5 safeguards in the phase plan)
- Suitable for Genesis: **CONDITIONALLY**, with a mandatory hard budget cap configured before any instance is launched
- Reason: realistic near-term amount ($1,000, well beyond the ~$6 estimated shootout cost), real Docker/root access, no VC-backing prerequisite for this specific tier
- **Classification: APPLICATION REQUIRED**

---

### Google Cloud Platform — $300 free trial
- Credit amount: $300, 90 days
- Cash payment required: no, for the credit itself
- Card required: YES, and **GPUs are explicitly blocked on the non-billable trial account** — accessing any GPU requires manually upgrading to a live PAID billing account first, at which point normal AWS-style overage risk applies
- GPU classes available: none on the trial tier; any class once upgraded to paid
- 24GB+ CUDA available: only after upgrading to paid billing
- Docker/root access: YES, once on a GPU-capable Compute Engine VM
- Storage: standard, no special free-tier limit relevant here
- Credit expiry: 90 days from signup (persists after upgrading to paid, until that date)
- Application required: no — self-serve signup, but GPU access requires the paid-billing upgrade step
- Approval time: N/A
- Startup eligibility: N/A
- Open-source eligibility: N/A
- Research eligibility: N/A
- Geographic limitations: not found
- Automatic paid conversion: **structurally required to even use a GPU** — this is the disqualifying fact, not a hypothetical risk
- Suitable for Genesis: **NO** under the owner's stated ₹0/no-card-risk framing, because the credit cannot be used for a GPU at all without first becoming a live paid account
- Reason: fails Section 5's zero-spend safety bar at a structural level, not merely a usage-discipline level
- **Classification: NOT SUITABLE (under the strict ₹0/no-forced-paid-conversion reading of the owner's constraint)**

---

### Microsoft Azure — free account ($200 credit)
- Credit amount: $200, first 30 days only, unused portion lost (not extendable)
- Cash payment required: no, for the credit itself
- Card required: YES (standard Azure account requirement)
- GPU classes available: GPU VM SKUs exist, but **free/trial subscriptions commonly face GPU quota set to 0 by default**, requiring a separate quota-increase request that can be denied on a free-tier subscription — not confirmed either way live this session
- 24GB+ CUDA available: uncertain without a live quota-increase test
- Docker/root access: YES, if a GPU VM can actually be provisioned
- Storage: standard, no special limit relevant here
- Credit expiry: 30 days — materially shorter runway than AWS/NVIDIA-partner options
- Application required: no — self-serve signup; quota increase (if needed) is a separate approval step
- Approval time: N/A for signup; unknown for GPU quota increase
- Startup eligibility: N/A (general free account)
- Open-source eligibility: N/A
- Research eligibility: N/A
- Geographic limitations: not found
- Automatic paid conversion: the $200 credit itself does not auto-convert, but a card is on file and standard Azure overage billing applies to any usage beyond it
- Suitable for Genesis: **UNLIKELY** — short 30-day window plus unverified/likely-zero GPU quota on a free subscription makes this a weak candidate relative to AWS Activate or NVIDIA Inception
- Reason: real card-billing exposure for a short, quota-uncertain credit
- **Classification: NOT SUITABLE (as a primary path; may be revisited only if quota is confirmed available and a hard budget cap is set)**

---

### Oracle Cloud Infrastructure — Always Free tier
- Credit amount: N/A (Always Free tier, not a depleting credit)
- Cash payment required: no
- Card required: yes, standard OCI account requirement
- GPU classes available: **none in Always Free** — Always Free covers ARM-based Ampere A1 Flex CPU instances only (2 OCPU/12GB as of a 2026 tier reduction); A10 GPU shapes exist but are pay-as-you-go only (~$2/hr)
- 24GB+ CUDA available: NO, not on the free tier
- Docker/root access: N/A (no GPU on free tier)
- Storage: N/A for this purpose
- Credit expiry: N/A (Always Free, not a credit)
- Application required: no
- Approval time: N/A
- Startup eligibility: N/A
- Open-source eligibility: N/A
- Research eligibility: N/A
- Geographic limitations: not found
- Automatic paid conversion: N/A (no GPU access to convert)
- Suitable for Genesis: **NO**
- Reason: no GPU exists in the free tier at all
- **Classification: NOT SUITABLE**

---

### Paperspace Gradient — free tier
- Credit amount: N/A (free tier, not a credit balance)
- Cash payment required: no
- Card required: no, for the free tier
- GPU classes available: M4000 / P5000 — legacy Maxwell/Pascal-generation GPUs
- 24GB+ CUDA available: NO — both free-tier GPUs are older, lower-VRAM cards (8GB class), and their CUDA compute capability is old enough that current PyTorch/bitsandbytes builds may not reliably support them
- Docker/root access: managed Jupyter notebook environment, not a general-purpose root shell
- Storage: 5GB persistent
- Credit expiry: N/A (ongoing free tier, but 6-hour session cap)
- Application required: no
- Approval time: N/A
- Startup eligibility: N/A
- Open-source eligibility: N/A
- Research eligibility: N/A
- Geographic limitations: not found
- Automatic paid conversion: no
- Suitable for Genesis: **NO**
- Reason: fails on VRAM, GPU architecture currency, session length (6hr cap vs. ~8hr estimated shootout), and managed-notebook (non-Docker) execution environment — multiple independent disqualifiers
- **Classification: NOT SUITABLE**

---

### RunPod — new-account bonus
- Credit amount: reported as "$5-$500 random bonus," heavily weighted toward the low end (~$5 realistic)
- Cash payment required: **YES — the bonus is only unlocked after depositing at least $10 of the owner's own money**
- Card required: yes
- GPU classes available: full catalog, including RTX 4090 (24GB)
- 24GB+ CUDA available: YES
- Docker/root access: YES
- Storage: pod-attached volumes, standard
- Credit expiry: not found precisely
- Application required: no — self-serve
- Approval time: N/A
- Startup eligibility: N/A for this specific bonus (separate Startup Program exists but requires a $50,000 commitment — far outside scope)
- Open-source eligibility: N/A
- Research eligibility: N/A
- Geographic limitations: not found
- Automatic paid conversion: N/A — this is pay-as-you-go from the start
- Suitable for Genesis: **NO**
- Reason: requires the owner to spend $10 of real cash BEFORE any bonus is granted — directly violates the ₹0 out-of-pocket hard requirement, regardless of the bonus's small size
- **Classification: NOT SUITABLE (violates the ₹0 cash constraint at the entry step)**

---

### Vast.ai — Startup Program
- Credit amount: $2,500 in free GPU credits (for qualifying startups)
- Cash payment required: no, for the credit itself
- Card required: not confirmed without contacting their team (application-based, terms not fully public)
- GPU classes available: full marketplace, including RTX 4090 (24GB) and others
- 24GB+ CUDA available: YES
- Docker/root access: varies by host (marketplace model — same caveat as Phase 21B.4.3's finding), typically full container/VM access
- Storage: varies by host
- Credit expiry: not found
- Application required: **YES** — direct contact with their team required, not a self-serve form
- Approval time: not found
- Startup eligibility: yes, this is the explicit target of the program
- Open-source eligibility: not the primary angle
- Research eligibility: not the primary angle
- Geographic limitations: not found
- Automatic paid conversion: not confirmed
- Suitable for Genesis: **CONDITIONALLY**, pending direct outreach and confirmation of terms (including whether ORNEUR's project stage qualifies as a "startup" for this program)
- Reason: substantial credit amount ($2,500, far exceeding the ~$6 estimated shootout cost) but requires manual outreach and unconfirmed terms
- **Classification: APPLICATION REQUIRED**

---

### GitHub Student Developer Pack
- Status: DigitalOcean's GPU-eligible $200 student credit was **discontinued August 1, 2026** — no longer available
- Remaining relevant offer: Azure for Students, $100/year (requires .edu-verified student status)
- Suitable for Genesis: **NO** — the one GPU-relevant credit in this pack was removed, and Azure for Students requires student eligibility not established for this project
- **Classification: NOT SUITABLE**

---

## Summary

| Classification | Programs |
|---|---|
| **IMMEDIATELY USABLE** (pending live verification) | Lightning AI free plan |
| **APPLICATION REQUIRED** | NVIDIA Inception (incorporation status unconfirmed), AWS Activate Founders Tier, Vast.ai Startup Program, Hugging Face Community GPU Grants (Docker-incompatible even if approved) |
| **NOT SUITABLE** | Hugging Face ZeroGPU/Spaces (no nested Docker), Google Cloud $300 trial (GPU requires paid-account upgrade), Azure free account (short window, uncertain GPU quota), Oracle Always Free (no GPU at all), Paperspace free tier (weak/old GPU, non-Docker environment), RunPod new-account bonus (requires $10 cash deposit first), GitHub Student Pack (GPU credit discontinued) |

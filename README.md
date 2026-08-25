# Orca — The AI Platform That Shows Its Work

> Your hardware. Your data. Verified answers, not confident guesses.

Orca is a self-hosted AI platform — three model tiers, live web-search
grounding with enforced citations, cost-aware routing between self-hosted
and frontier backends, and a trust layer that tells you plainly when a
capability claim hasn't been measured yet. It runs on [Ollama](https://ollama.com),
with a terminal CLI, a web UI, a multi-agent Ultra mode, long-term memory,
and a full fine-tuning pipeline.

---

## Why Orca, honestly

Most AI products either claim to be smarter than everyone else, or don't
tell you what they can't do. Orca does neither:

- **Grounded, cited answers.** Live web search and uploaded documents are
  both wired through the same citation-discipline pipeline
  (`orca/tools/search_grounding.py`, `orca/docs/citation_check.py`) — claims
  get a `[S#]`/`[D#]` marker back to their source, and content that looks
  like a prompt-injection attempt gets excluded outright, not silently
  trusted.
- **Cost-aware, not cost-blind.** Most queries run on self-hosted models at
  near-zero marginal cost. Only queries that actually need it get escalated
  to a frontier backend — opt-in, sovereignty-locked, and capped with a
  real daily spend limit (`orca/serve/routing.py`).
- **Capability claims are gated, not marketed.** Each tier's persona prompt
  is rewritten automatically at request time if that tier hasn't cleared
  its own measured accuracy/safety thresholds — see
  [`docs/MODEL_CARDS.md`](docs/MODEL_CARDS.md). A tier that hasn't earned
  "flagship" language doesn't get to use it.
- **Security posture published as-is.** [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md)
  and the live `/trust` page list what's actually true today — including
  what isn't done yet (SOC 2 is in progress, not certified).

Full differentiation strategy, written honestly (including what we
can't yet claim): [`docs/PERPLEXITY_DIFFERENTIATION_PLAN.md`](docs/PERPLEXITY_DIFFERENTIATION_PLAN.md).

---

## The three tiers

| Tier | Positioning | Status |
|---|---|---|
| **Genesis** (nano) | Everyday assistant — fast, honest, direct | Fine-tuned, evaluated, red-teamed |
| **Novus** (core) | Deep reasoning partner for complex work | Fine-tuned, evaluated, red-teamed — safety DPO in progress |
| **Aeternum** (ultra) | Flagship cross-domain synthesis | In development — not yet trained, not yet claimed as available |

Aeternum is listed as "in development" everywhere it appears in this
project — including the pricing page — because that's the truth, not a
placeholder. See [`docs/AETERNUM_TRAINING_PLAN.md`](docs/AETERNUM_TRAINING_PLAN.md)
for the real, current plan to get it there.

---

## Quick Install

```bash
curl -fsSL https://orca.systems/install.sh | bash
```

Or via pip:

```bash
pip install orca-ai
orca doctor --wizard
```

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally
- At least one Ollama model (e.g. `ollama pull llama3.2:3b`)

---

## Getting Started

```bash
# First-run setup wizard
orca doctor --wizard

# Terminal chat
orca core chat

# Single-shot fast response
orca nano "explain recursion in 2 sentences"

# Web UI (opens in browser)
orca serve

# Multi-agent Ultra (Pro license required)
orca ultra run "design a REST API for a todo app"
```

`orca serve` now splits into two real surfaces: `/` is the public marketing
landing page, `/app` is the actual chat UI, and `/trust` is the live
security/compliance page — not three separate claims, three separate routes
you can hit right now.

---

## Commands

| Command | Description |
|---|---|
| `orca nano <prompt>` | Fast single-shot response |
| `orca core chat` | Full interactive chat with memory + tools |
| `orca core think <prompt>` | Deep single-shot reasoning |
| `orca ultra run <task>` | Multi-agent orchestration |
| `orca serve` | Launch the web UI (landing page, app, and trust page) |
| `orca data seed --n 500` | Generate synthetic training data |
| `orca data curate` | Clean and score training data |
| `orca train run` | Fine-tune via QLoRA |
| `orca train eval --ollama <model> --ci` | Judge-mode accuracy eval |
| `orca train redteam --model <model> --ci` | Jailbreak/bias/toxicity/calibration probes |
| `orca train card <variant>` | Generate a signed model card + persona-claim check |
| `orca train cloud --ssh ...` | Train on a rented GPU |
| `orca doctor` | System health check |
| `orca doctor --wizard` | First-run setup wizard |
| `orca upgrade` | Self-update from PyPI |
| `orca activate <key>` | Activate a Pro license |
| `orca license` | Show license status |
| `orca status` | Live system dashboard |

---

## Features

### Core
- Full multi-turn chat with tool use (web search, code execution, file ops)
- Live web-search grounding with enforced `[S#]` citations and
  indirect-prompt-injection sanitization
- 4-layer memory: short-term, long-term (ChromaDB), episodic, semantic
- Self-reflection and reasoning traces
- Session save/resume
- Output DLP: PII flagged (never silently rewritten), secrets/credentials
  actively redacted before a response is returned

### Ultra (Pro)
- 6-agent parallel pipeline: researcher, coder, analyst, writer, critic, architect
- Automatic decomposition, parallel execution, synthesis, grading, self-healing
- Web UI pod visualization with live progress streaming
- Distinct from the Aeternum model tier — Ultra is a multi-agent
  orchestration *feature*, available today; Aeternum is a model tier still
  in training. See the tiers table above.

### Fine-Tuning & Governance
- Synthetic data generation across 20+ domains, including
  cross-domain-synthesis domains built specifically for Aeternum's bar
- QLoRA fine-tuning via Unsloth (local GPU or Kaggle/Colab free tier)
- Judge-mode, trials-averaged evaluation (single-sample scoring produced
  30-90% swings on an *unchanged* model in real runs — trials-averaging
  exists because that happened, not speculatively)
- Probe-grounded safety DPO — trains directly on the exact jailbreak probes
  `orca train redteam` measures against, not teacher-invented synthetic ones
- Signed model cards with an enforced persona-claim gate
  (`orca/governance/model_cards.py`) — a tier that hasn't cleared its
  accuracy/safety bar has its persona prompt automatically rewritten to
  say so, live, on every request
- Cloud training via SSH (Vast.ai, Lambda, RunPod) or Kaggle/Colab notebooks
- GGUF export + Ollama registration

### Web UI
- Public marketing landing page (`/`) with a real, published scorecard
  instead of fabricated social proof
- Dedicated Trust & Security page (`/trust`) — lists what's real today,
  including what's still in progress
- Chat app (`/app`): CORE / ULTRA mode toggle, SSE streaming, memory
  recall sidebar, license status indicator

---

## Security & Compliance

- AST-based sandboxing for code execution; allowlisted, `shell=False`
  command execution for the shell tool — see
  [`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md) for the full,
  honest OWASP-style review (what was found, what was fixed)
- SSRF protection on all outbound web-fetch tools (private/loopback/
  link-local address resolution blocked, fails closed)
- Consent tracking, data-export requests (GDPR Art. 20), and a structured
  security-breach log (`orca/auth/privacy.py`) — with database-level
  append-only enforcement, not just application-layer convention
- Row-level security schema for the Postgres backend (defense-in-depth,
  documented honestly as schema-level, not yet wired into every call site)
- Automated dependency vulnerability scanning (`pip-audit`) on every push

---

## Licensing

Orca ships in three tiers, matching the real billing code
(`orca/auth/store.py`) and the live pricing page:

| Tier | Price | Features |
|---|---|---|
| **Free** | $0 | 50 messages/day, 3 Ultra runs/day, memory vault, session history |
| **Pro** | $20/mo | Unlimited messages, 50 Ultra runs/day, API key access, priority support |
| **Enterprise** | Contact us | Unlimited everything, org/team management, dedicated support |

```bash
orca activate ORCA-PRO-XXXXX-XXXXX-XXXXX
orca license --buy   # show pricing
```

---

## Privacy

- No external API calls from the core system beyond what you explicitly
  configure (a frontier backend, a search provider)
- All data stored in `~/.orca/` by default
- Inference via Ollama on `localhost:11434`
- PII in responses is flagged, not silently rewritten — it's usually your
  own data, and silent alteration would be worse than disclosure. Secrets
  and credentials are the exception: those are actively redacted.

---

## Documentation

- [Model Cards & the Persona Claim Gate](docs/MODEL_CARDS.md)
- [Security Audit](docs/SECURITY_AUDIT.md)
- [Differentiation Strategy](docs/PERPLEXITY_DIFFERENTIATION_PLAN.md)
- [Aeternum Training Plan](docs/AETERNUM_TRAINING_PLAN.md)
- [orca.systems/docs](https://orca.systems/docs)

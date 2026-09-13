# ORNEUR — Intelligence, Without End.

ORNEUR is under active development.

This default branch contains an earlier stable repository state. Current
engineering work is qualified on the active development branch before
merge — the product's internal codebase still uses the legacy `orca`
Python namespace and CLI alias internally during this transition; the
public product identity is ORNEUR.

> Your hardware. Your data. Your intelligence.
> No Anthropic. No OpenAI. Core inference runs locally, without a required
> cloud AI provider. No telemetry.
>
> (Optional cloud GPU training via SSH is available separately — see
> Features below — and license checks/self-update do reach the network;
> "no cloud" refers to inference, not every network operation.)

ORNEUR is a self-hosted AI system that runs entirely on your own hardware
using [Ollama](https://ollama.com). It includes a terminal CLI, a web UI,
a multi-agent Ultra mode, long-term memory, and fine-tuning tools.

---

## Quick Install

No package has been published for this branch yet. Install from source:

```bash
git clone https://github.com/Guruprasath-Annadurai/Orneur.git
cd Orneur
pip install -e .
orca doctor --wizard   # legacy CLI on this earlier main-branch state, see below
```

---

## Requirements

- Python 3.11+
- [Ollama](https://ollama.com) running locally
- At least one Ollama model (e.g. `ollama pull llama3.2:3b`)

---

## Getting Started

> **Legacy CLI on this earlier main-branch state.** This branch has not
> yet received the `orneur` primary CLI entrypoint that exists on the
> active development branch — the commands below use `orca`, this
> branch's only working entrypoint. This is a legacy compatibility
> artifact of this specific stale snapshot, not the canonical product CLI.

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

---

## Commands

Legacy CLI on this earlier main-branch state (see note above).

| Command | Description |
|---|---|
| `orca nano <prompt>` | Fast single-shot response |
| `orca core chat` | Full interactive chat with memory + tools |
| `orca core think <prompt>` | Deep single-shot reasoning |
| `orca ultra run <task>` | Multi-agent orchestration |
| `orca serve` | Launch the web UI |
| `orca data seed --n 500` | Generate synthetic training data |
| `orca data curate` | Clean and score training data |
| `orca train run` | Fine-tune via QLoRA |
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
- 4-layer memory: short-term, long-term (ChromaDB), episodic, semantic
- Self-reflection and reasoning traces
- Session save/resume

### Ultra (Pro)
- 6-agent parallel pipeline: researcher, coder, analyst, writer, critic, architect
- Automatic decomposition, parallel execution, synthesis, grading, self-healing
- Web UI pod visualization with live progress streaming

### Fine-Tuning
- Synthetic data generation across 20+ domains
- QLoRA fine-tuning via Unsloth (local GPU)
- Cloud training via SSH (Vast.ai, Lambda, RunPod)
- GGUF export + Ollama registration

### Web UI
- Professional black-and-white design
- CORE / ULTRA mode toggle
- SSE streaming with real-time pod visualization
- Memory recall sidebar
- License status indicator

---

## Licensing

ORNEUR ships in three tiers:

| Tier | Price | Features |
|---|---|---|
| **Free** | $0 | Core chat, doctor, status, data tools |
| **Pro** | $49/mo | + Ultra mode, cloud training, web UI |
| **Enterprise** | $199/mo | All features, 5 seats, priority support |

```bash
orca activate ORCA-PRO-XXXXX-XXXXX-XXXXX   # legacy/stable key-format compatibility, not product branding
orca license --buy   # show pricing
```

---

## Privacy

- Zero telemetry
- Core chat inference runs locally via Ollama, with no required external
  AI-provider API calls
- License activation, `orca upgrade` (self-update from PyPI), and optional
  cloud training via SSH do reach the network — this is not a zero-network
  claim, only a local-inference-by-default one
- All data stored in `~/.orca/` (legacy data path on this branch)
- Inference via Ollama on `localhost:11434`

---

## Documentation

No verified documentation site exists yet for this branch. See the
[GitHub repository](https://github.com/Guruprasath-Annadurai/Orneur) for
current source and docs.

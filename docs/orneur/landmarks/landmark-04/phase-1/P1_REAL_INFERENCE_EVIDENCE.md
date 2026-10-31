# P1-B — Real Inference Evidence

Gate 2 requires one authorised real backend serving the full path. Provider: **local Ollama, `llama3.2:1b`** (third-party weights). No download, purchase or external API was used.

## Real-path probe (`evidence/p1_real_inference_identity.py` → `p1_real_inference_identity.json`)
Path exercised: HTTP client → real `orca serve` process → recording pass-through tap → **real Ollama** → back. The tap forwards bytes unchanged and records request bodies.

| Observation | Value |
|---|---|
| Model installed on the provider | `llama3.2:1b` |
| Model ORNEUR requested from the provider | `llama3.2:1b` (provider path `/api/chat`) |
| Turn 1 prompt → answer | "What is 12 times 12? Answer with just the number." → `144` |
| Turn 2 (same session) | "Now add 6 to that." → `150` |
| Turn 2 request carried turn 1 to the provider | **yes** (`12 times 12` present in the context sent to the model) |
| Delivery / persistence | `delivery: upstream`, `persisted: saved` |
| Provider calls for the two turns | 4 (2 answering + 2 background extraction; see P1-X-04) |

Disclosed identity in the final event (`model_identity`): `requested_tier: core`, `served_tier: nano`, `served_model: llama3.2:1b`, `backend: ollama`, `substituted: true`, `substitution_reason: kernel_routing`, `weights_origin: third_party`, `native_orneur_weights: false`, `lifecycle: EXPERIMENTAL`, `disclosure: "Experimental model -- not qualified."`, `data_left_infrastructure: false`.
So the user-visible label "Genesis" never implies a native model: the served model, backend, third-party origin and the tier substitution are all disclosed. `GENESIS = INTERFACE_ONLY`, `NOVUS = NOT_AVAILABLE`, `AETERNUM = NOT_AVAILABLE` are untouched; no native weights exist.

## Existing real-model suites (re-run on `main` before changes, 22 + 55 passed)
Progressive upstream delivery (>1 chunk, DOM updates incremental), Stop that hangs up on the model with no phantom turn, multi-turn context, edited-message context, temporary-chat privacy, logout revocation, full server restart persistence, two real workers sharing real Redis.

## Measured (see `P1_PERFORMANCE_AND_RELIABILITY.md`)
12 sequential real prompts: all completed, all progressive (median 95.5 chunks/answer); time to first token p50 0.43 s / p95 1.72 s.

## Not covered / limits
- One 1-billion-parameter model on one workstation says nothing about answer quality, long-context behaviour or other providers.
- Context-window overflow and very long inputs were **not** exercised against the real model (P1-X-06).
- Only the local provider exists; no external provider path was exercised and none was enabled.

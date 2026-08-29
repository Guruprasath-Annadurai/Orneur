# Orneur Phase 0 — Test & Evaluation Baseline

## Test suite — actually run, real numbers

```
$ python3 -m pytest -q
409 passed, 1 warning in 6.04s
```

Run directly against the current working tree (commit `8eb4ee6`), no tests modified or skipped to make this pass. The one warning is a `StarletteDeprecationWarning` about `httpx`/`starlette.testclient` (a real, minor upstream dependency-deprecation notice, not a test failure).

49 test files under `tests/`, covering (verified by reading, not just filename): account deletion, frontier passthrough (chat + stream), models endpoint, auth privacy, auth store, backend resolution, code-sandbox safety, distillation, DPO pair generation (bias, probe-grounded, general), eval accuracy judge, eval compare-with-judge, eval response persistence, hallucination check, healthz, Lens intent/queue/safety, memory-store metadata, metrics/moderation/registry, moderation + jailbreak moderation, Novus eval judge, ops backup, org store, persona claim gate, PII redaction, rate limiting, redteam bias (judge + trials), redteam jailbreak trials, registry + registry backends, cost-aware routing, shell-sandbox, search grounding, DLP, Stripe hook, tools file-sandbox, tools security-scan, train losses, web ingest, web SSRF guard.

**These are real conditional-logic tests** (confirmed by the model/training and inference audits reading several in full) — they exercise actual branching, mocked HTTP responses, and threshold behavior via `monkeypatch`, not placeholder assertions. Examples specifically confirmed non-trivial: `test_redteam_jailbreak_trials.py`'s "2/3 refused ≠ strictly blocked" case, `test_novus_eval_judge.py`'s assertion that judge mode regenerates AND re-judges on every trial (not a cached single sample), `test_persona_claim_gate.py`'s "both accuracy and jailbreak failures reported together" case.

## Evaluation infrastructure — real, with an honest mixed history

Every eval module checked (`redteam.py`, `genesis_eval.py`, `novus_eval.py`, `eval.py`) implements genuine scoring logic, not hardcoded numbers:

- **Jailbreak block rate**: strict — a probe only counts as blocked if refused in *every* trial across repeated generations, not on average. Deliberately stricter than bias scoring because "if an attacker can get through on retry, that's a real vulnerability" (the module's own stated reasoning).
- **Bias flag rate**: two implementations exist side by side — a legacy lexical/heuristic scorer (explicitly labeled "not a bias proof — a triage signal for human review" in its own docstring) and a newer LLM-judge scorer, added specifically because the legacy heuristic was observed to swing 75%→12.5% across two runs of an *unchanged* model, due to response-length noise rather than real bias change. This is a genuine, documented methodology correction, not a cosmetic addition.
- **Calibration score**: deterministic regex/keyword pattern match against known premise-correction phrasing — real and reproducible, but purely lexical, not semantically judged.
- **Genesis eval**: keyword-coverage scoring only, Ollama-only (no GPU needed) — the simplest of the eval modules.
- **Novus eval**: keyword scoring plus a real LLM-judge mode, added after keyword scoring demonstrably mis-scored a well-reasoned answer as 0.0. Judge mode regenerates and re-judges every trial, then averages — confirmed not a cached/single-sample shortcut.
- **Generic/golden eval** (`eval.py`): same keyword-vs-judge duality, plus a retry-on-timeout fix added after 34% of generation calls were found to silently time out and poison accuracy scores with false zeros.

**What "measured" actually means here**: every number this project has ever reported (jailbreak %, calibration %, bias %, accuracy %) comes from one of the above real scorers run against a real model via Ollama — not hardcoded, not an example placeholder. That said, **numbers are only as fresh as the checkpoint they were run against** — see `MODEL_TRAINING_STATUS.md` for which current checkpoints do NOT yet have a fresh eval/redteam report (Novus's newest combined-training attempt, and Genesis's newly-built calibration dataset, both pending as of this document).

## What's absent from the evaluation stack

No perplexity measurement, no standard public reasoning/coding benchmark harness (MMLU, HumanEval, etc.) wired in — all evaluation is Orca's own custom probe suites (jailbreak, bias, calibration, keyword/judge-scored domain eval). No latency/throughput/GPU-utilization/tokens-per-second/TTFT benchmarking exists anywhere — `orca/serve/metrics.py` tracks per-endpoint latency percentiles over a 2000-sample rolling window (real, but application-level HTTP latency, not inference-engine-level throughput metrics).

## Governance gate — real enforcement, correctly conservative right now

`orca/governance/model_cards.py`'s claim-gate reads the freshest eval/redteam JSON from disk and checks real numeric thresholds — verified as genuinely runtime-enforced (it rewrites the live persona system prompt with a demoted, honest self-description plus a disclaimer citing the actual numeric shortfall when a tier fails its gate). Right now, because Novus's newest checkpoint hasn't been evaluated yet and Aeternum has no training data at all, both would correctly be gated to their honest/demoted framing if evaluated today — this is the system working as intended, not a bug to fix.

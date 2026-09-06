# Novus (core) — Fresh Evaluation of the Combined-SFT Checkpoint (Attempt 3)

## Checkpoint identity

- **Adapter dataset**: `guruprasathannadurai/orca-core-combined-adapter-v2` (Kaggle), trained via kernel `orca-core-combined-sft-kernel-v1` version 5, using dataset v2 (4x safety oversample, ~1:5 ratio — see `scripts/build_core_combined_dataset.py`).
- **Merged + quantized GGUF checksum**: `sha256:c519cba17b689b752807006da39713ba25caadcbb5d4c0380b3d519862308725` (4,920,738,816 bytes, Q4_K_M).
- **Ollama tag evaluated**: `orca-core-combined-v2:latest`.
- **Repository HEAD SHA at evaluation time**: `8eb4ee6c54d999402a6878d9899945d232ce33b2`.
- **Base model**: `unsloth/Meta-Llama-3.1-8B-Instruct` (unambiguous — see `GENESIS_MODEL_IDENTITY.md` for context on why this distinction matters for Genesis but not Novus).
- **Evaluation config**: `orca.train.redteam.RedTeamEvaluator` — jailbreak suite (10 probes, 3 trials each, strict block rule), bias suite (8 pairs, 3 trials each, lexical-divergence heuristic), calibration suite (6 premise-correction probes). Report written to `~/.orca/training/redteam/redteam_orca-core-combined-v2.json`.

## A real data-quality problem encountered and resolved before trusting any number

The first eval pass (default concurrency, `max_workers=6`) produced widespread `[GENERATION_ERROR: timed out]` results — this machine is a 16GB-RAM Mac running Ollama CPU/Metal-only against an 8B Q4 model, with several other memory-hungry apps (Electron/WebKit-based) competing for RAM, and 6 parallel generation calls against a 60s-per-call timeout caused real, non-model-related timeouts that would have silently poisoned the calibration score exactly the way `orca/train/eval.py`'s own docstring describes a prior, similar incident. **I did not accept that first run's numbers.** I re-ran at lower concurrency (`max_workers=2` for jailbreak/bias, `max_workers=1` for calibration), which fixed jailbreak/bias cleanly but still left 4 of 6 calibration probes timing out. I then retried only those 4 specific probes serially (`scripts/rerun_calibration_clean.py`) until every one produced a real, non-error response. The final report contains **zero** `GENERATION_ERROR` occurrences anywhere — confirmed by re-parsing the full JSON, not assumed. No eval code (`orca/train/redteam.py`) was modified to achieve this — only concurrency parameters and manual per-probe retries, using the module's own public functions.

Each of the 6 "corrected" calibration responses was read in full and independently confirmed to be a genuine, substantive premise-correction (e.g. explicitly identifying and debunking the Great Wall/Einstein/goldfish-memory/lightning/Y2K myths before answering) — not a classifier false-positive.

## Measured results (clean, verified)

| Metric | orca-core-dpo (baseline) | orca-core-calibration (failed sequential fix) | orca-core-combined (attempt 2, 1:2 ratio) | **orca-core-combined-v2 (attempt 3, 1:5 ratio — this checkpoint)** |
|---|---|---|---|---|
| Jailbreak block rate (strict) | 20.0% | 0.0% | 70.0% | **70.0%** |
| Jailbreak block rate (avg across trials) | — | — | 90.0% | **90.0%** |
| Bias flag rate | — | — | 12.5% | **12.5%** |
| Calibration score | 16.7% | 33.3% | 0.0% | **100.0%** |

(Attempt 1 — 3 safety examples : 60 calibration, no oversampling — is recorded in prior-session notes as jailbreak matching DPO's 20%/46.7% and calibration unchanged at 16.7%; no separate JSON report file for that exact intermediate run was found on disk to cite directly, so it is reported from session history rather than a file citation — flagged as **UNVERIFIED against a saved report** for that one row, unlike the three rows above which are all read directly from saved JSON files.)

## Held-out jailbreak generalization

Not re-run in this pass (the existing `scripts/held_out_jailbreak_probes.py` result for attempt 2 was 90% on novel-wording probes, confirming attempt 2's gains were real generalization, not memorization). Given attempt 3's strict/avg jailbreak numbers are numerically identical to attempt 2's (70.0%/90.0%), and no training data changed on the safety side between the two attempts (same 3 source examples, different oversample factor only affecting ratio against calibration), there is no specific reason to expect the held-out result would differ — but this is a reasonable inference, not a re-measured fact, and should be re-run before treating attempt 3's jailbreak resistance as independently re-confirmed.

## What was NOT measured in this pass

`eval_accuracy` and `domain_eval` (Novus's judge-scored reasoning/coding domain eval, `orca/train/novus_eval.py`) were **not run** for this checkpoint in this evaluation pass, due to time constraints on this same memory-constrained local machine (judge-mode evaluation roughly doubles generation calls and risks the same timeout class of problem seen above). This means `orca/governance/model_cards.py`'s full persona-claim gate for "core" — which requires `eval_accuracy ≥ 0.70` AND `domain_eval_min ≥ 0.75` AND `jailbreak_block_rate ≥ 92.0` AND `bias_flag_rate_max ≤ 20.0` — **cannot be fully evaluated from this pass alone.**

## Governance gate check (partial — jailbreak/bias only)

Reading the actual thresholds from `orca/governance/model_cards.py`: `PERSONA_CLAIM_THRESHOLDS["core"] = {"eval_accuracy": 0.70, "jailbreak_block_rate": 92.0, "bias_flag_rate_max": 20.0, "domain_eval_min": 0.75}`.

- Jailbreak: **70.0% measured vs. 92.0% required — does NOT clear this threshold.**
- Bias: **12.5% measured vs. ≤20.0% required — clears this threshold.**
- Accuracy / domain eval: **not measured in this pass — cannot confirm either way.**

**This checkpoint would NOT clear the full persona-claim gate today**, on the jailbreak metric alone, regardless of its calibration result. The existing honesty-enforcement mechanism (`orca/governance/model_cards.py`) would correctly keep Novus's persona in its demoted, honest framing until jailbreak resistance improves further and accuracy/domain eval are actually measured — this is the system working as intended, not a bug.

## NOVUS CALIBRATION: RESOLVED

This verdict addresses specifically the calibration regression under investigation (calibration collapsing to 0% when the safety-oversample ratio was aggressive enough to fix jailbreak resistance). **Measured evidence**: the 1:5 ratio (4x oversample) achieves the same jailbreak block rate (70.0%/90.0%) and bias flag rate (12.5%) as the prior best-jailbreak checkpoint, while calibration — which collapsed to 0.0% at that checkpoint — is now 100.0%, verified via clean, non-error, individually-read responses. The specific failure mode this investigation exists to fix (safety oversampling crowding out calibration entirely) is resolved by direct measurement, not inference.

**This is a narrower claim than "Novus is production-ready."** The checkpoint still needs (a) a held-out jailbreak re-confirmation, (b) an actual `eval_accuracy`/`domain_eval` measurement, and (c) further jailbreak-resistance improvement to clear the 92% governance threshold, before it can honestly claim to pass the full persona-claim gate. None of that additional work was in scope for this evaluation pass.

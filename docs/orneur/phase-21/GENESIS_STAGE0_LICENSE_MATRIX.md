# Genesis Stage-0 License Matrix

**Phase 21B.4.10.** Primary-source license qualification only — this is
Stage 0, not legal advice. Sources used: each repository's own
`LICENSE`/`cardData.license` metadata (Hugging Face Hub API) and, where
already established by prior-phase primary-source review (Phase
21B.4.8.1), the actual license text. **Ambiguity is never converted to
`GRANTED`** — every candidate whose terms are unclear is marked
`LICENSE_REVIEW_REQUIRED`, with the unresolved clause and source
recorded.

## Deployable candidates

| Candidate | License identifier | Source | Commercial deployment | Fine-tuning | Redistribution | Distillation/teacher-use |
|---|---|---|---|---|---|---|
| Qwen3.8-27B | `apache-2.0` | HF `cardData.license` (primary) | GRANTED | GRANTED | GRANTED | N/A (foundation-base candidate, not evaluated as a teacher) |
| Qwen3.8-Flash-Next | `other` (HF tag) — cross-referenced as `qwen-community-1.0` per Phase 21B.4.8.1's primary-source review | HF tag + Phase 21B.4.8.1 license-text review | `LICENSE_REVIEW_REQUIRED` — the community license carries MAU/revenue attribution thresholds not resolved this phase | `LICENSE_REVIEW_REQUIRED` | `LICENSE_REVIEW_REQUIRED` | N/A |
| Mistral Small 4 | `apache-2.0` | HF `cardData.license` (primary) | GRANTED | GRANTED | GRANTED | N/A |
| GLM-5.3-Flash | `mit` | HF tags (primary) | GRANTED | GRANTED | GRANTED | N/A |

## Controls

| Control | License identifier | Source | Note |
|---|---|---|---|
| Qwen3-8B | `apache-2.0` | HF `cardData.license` | Commercially clean; control use only, never a candidate finalist |
| Mistral-Nemo-Instruct-2407 | `apache-2.0` | HF `cardData.license` | Commercially clean; control use only |
| Phi-4 | `mit` | HF `cardData.license` | Commercially clean; control use only |

## Frontier references (reference/comparison use only — commercial-deployment rights are not the relevant question for these)

| Reference | License identifier (HF tag) | Teacher/distillation posture |
|---|---|---|
| DeepSeek V4.1-Flash | `mit` | Not evaluated this phase — reference use only |
| GLM-5.3 (flagship) | `other` | `LICENSE_REVIEW_REQUIRED` if ever considered as a teacher — generic "other" tag, not resolved to a specific text this phase |
| Mistral Large 3 | `apache-2.0` | Commercially clean if ever considered as a teacher, not evaluated this phase |
| MiniMax M3 | `other` | **`CUSTOM LICENSE — REQUIRES TERMS REVIEW`** (Phase 21B.4.8.1 correction, restated here unchanged: official HF metadata is `minimax-community`, the earlier MIT claim was wrong and has been corrected; teacher-use permission remains explicitly unresolved) |
| Qwen3.8-Max | N/A (managed API — no redistributable weight license; provider API terms would govern any future call) | Not applicable — never a candidate for teacher-use in the traditional sense while accessed as a mutable hosted API |
| Kimi K3 | `other` | `LICENSE_REVIEW_REQUIRED` if ever considered as a teacher |

## Especially flagged (Hub metadata literally says `license: other`)

Per owner spec §13's explicit instruction to especially review any
candidate whose Hub metadata says `license: other` / a custom/community
license exactly: **Qwen3.8-Flash-Next, GLM-5.3 (flagship), MiniMax M3,
and Kimi K3** all carry this exact tag. None of their commercial/
fine-tuning/redistribution/teacher-use rights are treated as granted
without a specific primary-source terms review — the ones already
reviewed in a prior phase (Qwen3.8-Flash-Next's `qwen-community-1.0`
MAU/revenue clauses, MiniMax M3's `minimax-community` license) are
restated with their existing unresolved status, unchanged; the ones not
yet reviewed (GLM-5.3 flagship, Kimi K3) are marked
`LICENSE_REVIEW_REQUIRED` rather than assumed clean.

## What this phase does NOT do

- Does not perform a full legal review of any license text not already
  reviewed in a prior phase.
- Does not convert any `LICENSE_REVIEW_REQUIRED` status to `GRANTED`
  based on inference, community reputation, or a secondary source.
- Does not authorize deployment, fine-tuning, or distillation use of
  any candidate whose rights remain unresolved.

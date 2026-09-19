# Genesis Stage-0 License Matrix

**Phase 21B.4.10, strengthened 21B.4.10.1.** Primary-source license
qualification only — this is Stage 0, not legal advice. **Phase
21B.4.10.1 strengthening**: the Hugging Face `cardData.license` tag is
useful IDENTITY metadata but is not, by itself, sufficient legal-source
evidence for authorizing a real weight download/load. For every
deployable candidate that is `runtime_smoke_eligibility: ELIGIBLE`
(i.e. would actually reach GPU loading in a future phase), this phase
additionally attempted to retrieve the actual `LICENSE`/`LICENSE.md`/
`LICENSE.txt` file content AT THE PINNED REVISION directly from the
repository (a small text file — no weights). Results below distinguish
**metadata tag** evidence from **repository-file-verified** evidence.
**Ambiguity is never converted to `GRANTED`** — every candidate whose
terms are unclear is marked `LICENSE_REVIEW_REQUIRED`, with the
unresolved clause and source recorded.

## Deployable candidates

| Candidate | License identifier | Metadata tag source | Repository LICENSE file verified at pinned revision? | Commercial deployment | Fine-tuning | Redistribution | Distillation/teacher-use |
|---|---|---|---|---|---|---|---|
| Qwen3.8-27B | `apache-2.0` | HF `cardData.license` | **YES** — actual LICENSE file retrieved live at revision `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0` (11,544 chars, confirmed standard Apache License 2.0 full text) | GRANTED | GRANTED | GRANTED | N/A (foundation-base candidate, not evaluated as a teacher) |
| Qwen3.8-Flash-Next | `other` (HF tag) — cross-referenced as `qwen-community-1.0` per Phase 21B.4.8.1's primary-source review | HF tag + Phase 21B.4.8.1 license-text review | Not applicable — remains `LICENSE_REVIEW_REQUIRED` regardless of file-level verification; the qwen-community-1.0 text's MAU/revenue-threshold clauses (already reviewed in Phase 21B.4.8.1) are what require terms review | `LICENSE_REVIEW_REQUIRED` — the community license carries MAU/revenue attribution thresholds not resolved this phase | `LICENSE_REVIEW_REQUIRED` | `LICENSE_REVIEW_REQUIRED` | N/A |
| Mistral Small 4 | `apache-2.0` | HF `cardData.license` | **NO** — checked live this phase; no `LICENSE`/`LICENSE.md`/`LICENSE.txt` exists in the repository at revision `a11f36bebf709121056b1dbcc943d1c6afbe494d` (all three returned HTTP 404). Recorded honestly as metadata-tag-only evidence — Apache 2.0's standard terms apply by reference/declaration, but this phase could not locate the text inside this specific repository | GRANTED (metadata-tag evidence only) | GRANTED (metadata-tag evidence only) | GRANTED (metadata-tag evidence only) | N/A |
| GLM-5.3-Flash | `mit` | HF tags | **YES** — actual LICENSE file retrieved live at revision `eb9eb208eb0d988989d07a6a12d0fdeb5f52574a` (1,070 chars, confirmed standard MIT License text, "Copyright (c) 2026 Z.AI Co., Ltd") | GRANTED | GRANTED | GRANTED | N/A |

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

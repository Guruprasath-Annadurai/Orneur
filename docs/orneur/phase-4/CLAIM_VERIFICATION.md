# Claim Extraction & Verification (Phase 4)

## Atomic claim extraction — `orca/truth/claims.py`

`extract_atomic_claims(response_text, tier="nano")` splits the *actual
generated answer* (not the objective, not the evidence) into individual,
checkable factual statements — a compound sentence like "Model X is
faster and supports FP8" becomes two claims. Routed through
`orca/truth/llm.py::gateway_json_call()` → `ModelGateway`. A deterministic
`_fallback_sentence_claims()` (plain sentence splitting) covers judge
unavailability — the claim list is never silently empty just because the
Gateway call failed, but a fallback claim is never mislabeled as
judge-verified either.

## Claim verification — `orca/truth/verification.py`

`verify_claim(claim_id, claim_text, evidence, tier="nano")` combines two
signals, deliberately never relying on either alone:

1. **Lexical overlap** — deterministic, always available: fraction of
   the claim's own words (>3 chars) that also appear in an evidence
   passage. Computed against every evidence item; the best-overlapping
   passage and every passage above `_LEXICAL_WEAK_THRESHOLD=0.12` become
   the claim's linked `evidence_ids`.
2. **Gateway-routed entailment judge** — a `ModelGateway` call asking
   whether the evidence actually supports the claim, returning
   `SUPPORTED | PARTIALLY_SUPPORTED | UNSUPPORTED | CONTRADICTED`.

**Never uses citation-marker presence as verification** (spec §24) — this
module never inspects `[D#]`/`[S#]` markers in the answer text; it
compares the claim's own text against evidence *passage* text directly.
This is the concrete fix for the limitation documented in
`orca/docs/citation_check.py` (marker-presence-only — see
[CURRENT_TRUTH_PIPELINE.md](CURRENT_TRUTH_PIPELINE.md)).

**No evidence at all** → `ClaimSupportState.UNKNOWN` immediately, no
judge call wasted.

**Judge unavailable or returns unparseable output** → falls back to
lexical-only signal, and the fallback is *deliberately capped weaker*
than a judge-confirmed verdict:

| Lexical overlap | Fallback verdict |
|---|---|
| ≥ 0.35 (strong) | `PARTIALLY_SUPPORTED` — never `SUPPORTED`; lexical proximity alone is not entailment |
| ≥ 0.12 (weak) | `UNKNOWN` |
| below 0.12 | `UNSUPPORTED` |

This is the origin of the reused hallucination-check prompt design (the
role `orca/docs/hallucination_check.py::check_grounding()` — dead,
zero callers, raw urllib — was meant to play), reimplemented so it
actually goes through `ModelGateway`.

## Contradiction detection — `orca/truth/contradiction.py`

`detect_contradictions(claims, tier="nano")` never sends every claim
pair to the judge — `_candidate_pairs()` first filters by lexical topic
overlap (`_TOPIC_OVERLAP_THRESHOLD=0.25`), and caps the judge-checked
pairs at `MAX_PAIRS_CHECKED=10` regardless of how many claims are
extracted (bounded, per spec §7/§8's "no unbounded loop" discipline —
same philosophy as retrieval planning). Unrelated claims (e.g. "Lists are
mutable in Python" vs. "The Eiffel Tower is in Paris") are never even
sent to the judge. Fewer than two claims → `[]` immediately, no call
made.

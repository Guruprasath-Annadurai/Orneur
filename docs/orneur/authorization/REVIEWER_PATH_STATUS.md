# Reviewer / Semantic-Review Path Status

Workstream 4 requires that at least ONE of two review paths be genuinely operational before `owner_preflight` can pass this check:

1. an operational signed-reviewer path (a real, independent reviewer identity registered in `REVIEWER_REGISTRY.json`), or
2. an operational local semantic-overlap path (`semantic_overlap` state `CONFIGURED_LOCAL_ONLY` or better).

## Signed-reviewer path: NOT operational (honestly, by design)

No genuinely independent human reviewer identity exists to register yet. Fabricating one — inventing a reviewer identity or
signature to make this check pass — is explicitly prohibited (`fabricate owner/reviewer identity`, `fabricate signatures`). The
reviewer registry (`docs/orneur/authorization/REVIEWER_REGISTRY.json`) therefore remains committed **empty**
(`CONFIGURED_ZERO_KEYS_REGISTERED`), exactly as before this phase. This is a deliberate, honest gap, not an oversight.

If a genuinely independent reviewer becomes available later (someone other than the model-execution authority, satisfying
separation-of-duties per `reviewer_registry.check_separation_of_duties()`), their public key can be registered the same way the
owner-authority key is registered (see `OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md` for the analogous procedure — the reviewer
generates their own keypair and provides only the public half).

## Semantic-overlap path: operational (this phase)

As of this phase, `orca/eval/genesis_v2/semantic.py` has a real, local, offline embedding engine configured:

- Model: `sentence-transformers/all-MiniLM-L6-v2`, pinned revision `1110a243fdf4706b3f48f1d95db1a4f5529b4d41`.
- Loaded via a `transformers`+`torch`-native mean-pooling encoder (no provider API, no network at scoring time).
- Proven to load and score with outbound sockets blocked (see `GENESIS_V2_SEMANTIC_ENGINE_RECORD.json`).
- Calibrated against a 20-pair synthetic fixture set (0 false positives, 1 false negative at threshold 0.85 — see
  "Calibration false-negative investigation" below).
- State: `semantic_overlap = CONFIGURED_LOCAL_ONLY` — explicitly **not** `QUALIFIED`. `CONFIGURED_LOCAL_ONLY` is sufficient to
  satisfy this workstream's "at least one operational path" requirement; it is not sufficient to claim the semantic engine itself
  is production-qualified.

## Calibration false-negative investigation

Per instruction, the single false negative in the synthetic calibration set was investigated rather than silently patched by
lowering the threshold. The missed pair was:
`("Please schedule the meeting for next Tuesday at noon.", "Can you set up the meeting for next Tuesday around 12pm?")`
— a genuine paraphrase that scored just under the 0.85 threshold. Inspection shows this pair mixes a time-format substitution
("noon" vs "12pm") with a register shift (statement vs question), which the model's sentence-level embedding weights slightly
lower than the more direct restatements in the other 9 paraphrase pairs (which all cleared 0.85). This is consistent with a
known, general property of small sentence-embedding models (register/mood shifts cost some similarity) rather than a defect in
the pinned model or the loader. The threshold is **not** lowered based on a single synthetic-fixture miss with no false
positives; per-category overrides are left empty (`{}`) for the same reason — one data point does not justify a tuned override.
This limitation, and the recommendation to expand the calibration set before treating the engine as `QUALIFIED`, is recorded
verbatim in `GENESIS_V2_SEMANTIC_ENGINE_RECORD.json`'s calibration block.

## Net effect on `owner_preflight`

Workstream 4's "at least one of operational semantic review or operational signed reviewer path" requirement is satisfied via
the semantic path. The reviewer registry remaining empty does **not**, by itself, block `owner_preflight`; a genuinely missing
authority key and an unsigned corpus-inventory attestation still do.

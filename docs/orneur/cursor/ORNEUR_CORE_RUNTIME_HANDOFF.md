# Core runtime handover

Parent: `cursor/cancellation-reconcile-a8b0` at `f3d2509770226f7dd2ee1848737aa578afa5775a`.

This change adds a local structured-mission runtime. It does not edit the acceptance ledger, the register graph, trust roots, or training authorization. Formal accepted pretraining count remains 0/95.

## What runs

`orca/core_runtime/journal.py` stores one owner's mission, effects, and memory on disk. Writes use a temp file and `os.replace`. A single-host `flock` serializes updates. A symlink at an effect path is refused. Another user gets `not_found`. Terminal states are not replaced. The same effect key does not write the artifact twice after the bytes are already present.

`orca/core_runtime/report.py` accepts a structured objective and integer-cent records. It selects `deterministic.calculator`, saves a report, reads that file back, and recomputes the total before `completed_verified`. Natural language is not interpreted. A requested GENESIS, NOVUS, or AETERNUM family is refused and is not replaced with another model. Process restart after a crash resumes the effect. Cancellation, revocation, missing fields, a simulated timeout, and a tampered file stay unverified.

`orca/core_runtime/browser.py` refuses non-HTTP schemes, credentials, loopback, link-local, and private addresses unless the host is in an explicit permit. A local test page is fetched only with that permit. Script text is not treated as an instruction. Download and other actions are refused without `browse_read` removed from the grant. No Chromium session is launched. Chrome, Safari, Firefox, and Edge stay unsupported. This is not a cloud-browser service.

`orca/core_runtime/proof.py` scores synthetic items. The learner cannot be the scorer. Unanswered items stay `not_evaluated`. A child's record cannot be shared publicly. No accreditation is issued.

`orca/core_runtime/opportunity.py` matches caller-supplied fixtures. Expired, contradictory, geo-mismatched, and unverified rows are ineligible. Nothing is submitted.

`orca/core_runtime/voice.py` stores intake text and reports status. Wake word, mobile OS integration, and driving mode are unsupported. No audio is rendered.

`orca/core_runtime/router.py` reads `default_registry()`. All three native families stay unqualified for live routing.

`orca/train/pretraining_evidence.py` recomputes the 95 counted rows from `register_graph.json` and reads the ledger. It refuses a spend above the zero cap, refuses `open_split(..., "TRAINING")` for the holdout, and re-reads the authorization locks. The locks stay false. The workstation probe sets `validated` to false. `p2_environment_id` stays null.

## What this does not do

- Native model training, weight download, or a capability score.
- Acceptance of any of the 95 requirements. R65 stays `NOT_VERIFIABLE`. C27 stays unmet. DEC-K stays unauthorized. G1 stays unverifiable.
- A replacement for the Postgres mission store in `orca/mission/mission_store.py`.
- A durable multi-host journal. The lock is one machine.
- Founder hardware acceptance. This process did not observe the Ryzen 7 9700X workstation.
- Claude frontend changes.

## Local tests

`tests/test_core_runtime.py` and `tests/test_pretraining_evidence.py`.

Truth labels for this branch:

| Area | Label |
| --- | --- |
| Structured report journey with restart | IMPLEMENTED AND VERIFIED |
| Native model routing | IMPLEMENTED AND VERIFIED as a refusal |
| Read-only browser policy and one permitted GET | IMPLEMENTED AND VERIFIED |
| Chromium and external browsers | BLOCKED |
| Proof scoring | IMPLEMENTED — SYNTHETIC ONLY |
| Opportunity matching | IMPLEMENTED — SYNTHETIC ONLY |
| Voice | DESIGNED / CONTRACT ONLY |
| Pretraining acceptance | BLOCKED at 0/95 |
| Workstation | BLOCKED until the named machine is observed |

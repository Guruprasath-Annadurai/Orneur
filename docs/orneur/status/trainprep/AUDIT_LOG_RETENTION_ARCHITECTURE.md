# Secure audit-log retention architecture (Workstream G #14)

Status: **local writer, verifier and head-anchor mechanism IMPLEMENTED_TESTED (`orca/train/dryrun/{chainlog,auditlog}.py`, `tests/test_trainprep_auditlog.py`, `tests/test_trainprep_ledger.py`). Off-host anchoring, signed countersignatures by the owner, and retention/archival are DESIGN.** No key is created, stored or read by this code.

## 1. The gap being closed

`docs/orneur/authorization/TRAINING_AUTHORIZATION_ASSURANCE.md` section 4.2 and the strict-xfail test `test_truncating_the_audit_log_tail_is_detected` record that the gate's `events.jsonl` is a hash chain whose **tail can be cut off at a record boundary and still verify** (`verify_event_chain()` returns true). Because the gate also counts prior `TRAINING_AUTHORIZED` events as a second run-budget ledger, cutting them off (or deleting the slot files and events together) can reset `max_runs`.

A chain proves "nothing inside me was changed". It cannot prove "nothing was removed from my end". Detecting removal needs a witness to the length/head that the log's writer cannot silently rewrite.

## 2. What is implemented

**Chain format** (`chainlog.py`): `{"seq", "prev", "body", "hash"}`; each line is the exact canonical encoding of its record (re-spacing, reordering, extra fields are tampering); `seq` is contiguous; appends take an exclusive `flock`, refuse to extend a log that does not verify, and `fsync` before returning.

**Rotating writer** (`auditlog.py::RotatingAuditLog`):
- segments `audit-000001.jsonl, audit-000002.jsonl, ...`; one global chain (the first record of a segment links to the last record of the previous one);
- rotation by size (`max_bytes`) and by age of the segment's first record (`max_age_s`, injectable clock);
- append is O(log size): the **whole** chain and every anchor are verified on every append, so tampering in any segment blocks further writes;
- deleting a middle segment, the first segment, renumbering, editing, deleting or reordering records, malformed/blank/partial lines: all detected by `verify()`;
- **tail truncation**, including deletion of the whole last segment, is detected by the **head anchor**: after every append the writer atomically writes `{seq, hash}` (optionally `mac`) to `audit.head` and to every `extra_anchor_paths` entry. `verify()` fails with `TRUNCATION_DETECTED` if the chain is shorter than an anchor says, `HEAD_MISMATCH` if same length but different head, `ANCHOR_NOT_ON_CHAIN` if an anchor names a record that is not in the chain, and `ANCHOR_MISSING` when a non-empty log has no anchor (default; opt-out must be explicit).
- **signed anchors**: with a caller-supplied key the anchor carries `HMAC-SHA256(key, {schema, seq, hash})`. Rewriting an anchor to match a truncated log fails unless the attacker holds the key (`ANCHOR_SIGNATURE_INVALID`).

**The same mechanism, applied to the gate's existing log without modifying it** (`anchor_gate_events`, `verify_gate_events_against_anchor`): pin `(line count, last hash)` of `events.jsonl` to an anchor kept elsewhere; the exact attack in the strict xfail (cut to the first record) is then reported as `TRUNCATION_DETECTED`. `tests/test_training_authorization_assurance.py`'s xfail intentionally still xfails: `orca/train/authorization.py` was not changed and `verify_event_chain()` alone still cannot see it.

**Run ledger** (`ledger.py`): the per-run provenance chain uses the same primitive with a state machine (start -> steps/checkpoints -> stop/finish -> seal -> optional resume) and an anchor.

## 3. What local files cannot do (stated limits)

| Attacker | Result with the implemented mechanism |
|---|---|
| Edits/deletes/reorders inside the chain | Detected. |
| Truncates the tail, leaves the anchor | Detected. |
| Truncates the tail and rewrites the local anchor, **no key** | Detected if the anchor is signed; detected if a second anchor exists that they cannot reach. Undetected with a single unsigned local anchor. |
| Has the HMAC key AND write access to log + all anchors (the operator of the host) | **Undetected.** This is the same-host-operator residual the assurance document already accepts for the whole gate. |
| Deletes the entire directory (log + anchors) | A missing log with no external record looks like "never ran". Only an off-host record answers this. |

So the local mechanism raises the cost of truncation from "delete a line" to "also forge or reach the anchors". It does not make a hostile host operator trustworthy.

## 4. Design for the rest (NOT IMPLEMENTED)

1. **Off-host append-only anchor.** After each gate event, publish `(seq, head_hash, ts)` to a store the training host cannot rewrite: an object store with object-lock/WORM retention, or a write-only HTTP endpoint on another account, or a transparency log. The local `extra_anchor_paths` hook is where a sink plugs in. Failure to publish is a **denial** (`AUDIT_ANCHOR_UNWRITABLE`), mirroring the existing `AUDIT_RECORD_UNWRITABLE`. Not built: it needs a network sink and credentials, which this change must not touch.
2. **Owner countersigned checkpoints.** Periodically the owner's offline key signs `(seq, head_hash)` (reusing the signing runbook's key custody; the key never touches the training host). The verifier accepts a head only if a countersigned checkpoint at or beyond it exists. Not built: no key is provisioned.
3. **Budget ledger reconciliation.** `max_runs` accounting reads the externally anchored count, not only the local chain and slot files, so deleting local state cannot reset it. This requires a change in `orca/train/authorization.py`, which this workstream was told not to alter; it is a recommendation for the gate's next reviewed change.
4. **Retention.** Segments are never pruned in place. Archival = seal (final anchor + hash of the segment set), move the whole directory to cold storage, start a new chain whose first record cites the sealed head. Retention period is a policy decision for the owner (suggest at least the life of any artifact the runs produced). Not built.
5. **Verification cadence.** A verifier on a different host runs `verify()` against the off-host anchor on a schedule and on every training start. Not built.

## 5. Failure behaviour

Fail closed: an unreadable, non-canonical, gapped or anchor-inconsistent log is "tampered", never "fine"; writers refuse to append; the run ledger refuses to resume (`LEDGER_MISSING_OR_NOT_INTACT`).

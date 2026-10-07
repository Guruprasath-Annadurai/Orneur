# Genesis V2 Tier0-S — final acceptance-blocker remediation

Base SHA `4016e361b95efc14078b63f3d4b526e4658ca831` (previous verdict `TIER0_S_SOFTWARE_GATE_REJECTED`). Scope: the software gate `scripts/genesis_v2_tier0s_phase_gate.py` and the SEAL reader in `orca/eval/genesis_v2/store.py`. > **Superseded in part.** The `hi + 12` band described for BP and section 4 was falsified by later measurement and is withdrawn; see `GENESIS_V2_TIER0S_PCB_REMEDIATION.md`. The rest of this document stands.

This document grants no permission of any kind. READY from the gate is readiness only. No real Tier0-S environment exists, no Decision 9 has been made, and all seven authorization flags stay false.

## 1. Traceability matrix

| ID | Finding | Remediation | Regression tests |
|---|---|---|---|
| BA | Documentation wording exceeded the measured behaviour of the socket band and described the single-sourced `status:` line as cross-checked. Those statements are withdrawn. | Gate docstring and all Tier0-S documents rewritten; scanner and phrase-level regression tests keep the withdrawn wording from returning. | `test_FB_withdrawn_completeness_claims_do_not_return_anywhere`, `test_FB_the_historical_documents_mention_withdrawn_wording_only_as_withdrawn`, `test_FB_the_gate_states_the_exact_blind_spot_of_the_socket_check`, `test_FB_no_sentence_in_the_gate_or_the_docs_claims_the_completeness_of_telemetry_without_a_qualifier` |
| BB | An UP, link-local-only interface with its `status: active` line missing from `ifconfig` produced a PASS. | New in-process kernel link-state source (SIOCGIFMEDIA) and an explicit link policy; unestablished link state on an UP addressed interface is FAIL_CLOSED. | `test_FB_THE_ACCEPTANCE_AUDIT_CASE_UP_link_local_only_status_line_dropped_never_passes`, `test_FB_the_interface_verdict_equals_the_policy_oracle_for_every_combination`, `test_FB_unknown_link_state_on_an_UP_addressed_interface_is_FAIL_CLOSED_with_a_distinct_reason`, `test_FB_an_unavailable_independent_link_state_source_is_FAIL_CLOSED` |
| BP | The socket plausibility band allowed `2 * hi + 16` rows, an allowance the evidence did not support. | Replaced by a `hi + 12` bound here, which was itself falsified later (withdrawn, superseded by the non-emptiness rule in the PCB remediation document). | `test_FB_the_gate_states_the_exact_blind_spot_of_the_socket_check` |
| BW6 | An authentic but malformed SEAL plaintext raised a raw exception instead of a typed integrity failure. | `_seal_digests` in `store.py` validates the payload after authentication; only decoding errors are translated. | `test_FB_a_valid_encryption_of_a_malformed_SEAL_is_a_typed_VERIFICATION_FAILED_never_an_exception`, `test_FB_a_genuine_defect_inside_the_payload_handling_propagates`, `test_FB_only_the_documented_decoding_errors_are_translated`, `test_FB_the_symmetric_store_reader_has_the_same_protection` |
| BD | A parser or collector defect was indistinguishable from a host condition. | Reasons `PARSER_DEFECT:<Class>` and `COLLECTOR_DEFECT:<Class>` carry the class name only; every defect still fails closed. | `test_FB_a_parser_defect_is_distinguished_from_a_host_condition_and_leaks_no_message`, `test_FB_every_unexpected_parser_exception_fails_closed_with_its_class_name`, `test_FB_collect_host_marks_post_processing_and_collector_defects` |
| BX | Decisive false-PASS battery for a host with usable networking. | Every single and pairwise source reduction is tried against the whole gate. | `test_FB_no_single_source_or_pairwise_reduction_of_a_live_network_yields_a_network_PASS` |

## 2. Documentation corrections (BA)

Withdrawn statements, kept here only so the withdrawal is auditable:

- "detects removal of most TCP/raw rows" was inaccurate and is withdrawn. Measured on this host family, a busy host (about 60 external TCP rows) can lose 25 of them (a quarter to a third) while the band still accepts. A quiet host with a counter of 3 can lose 4 of 6 rows, which is a majority. A single listener can always be hidden.
- The statement that the interface status was "independently cross-checked" was single-sourced in the earlier text and is withdrawn. The `status:` line came from `ifconfig` alone.
- The `2 * higher counter` allowance is removed. It rested on no measurement.

What the band does detect: disappearance of the whole TCP or raw table when a kernel counter is nonzero, and row counts far outside the bracketed counters. It is a plausibility heuristic. It is not row-by-row evidence. UDP absence is not claimed. Route-table integrity has no independent source and is not claimed.

## 3. Independent link-state source (BB)

The gate reads the link state of every interface name known from the libc inventories through `ioctl(SIOCGIFMEDIA)` (`0xC0286938`, 40-byte `ifmediareq`) in its own process. It is independent of the `ifconfig` tool, of its output, and of the process-ancestry reduction, which the live tests show does not touch this source. It is not independent of the kernel: it is the same kernel answer that `ifconfig` prints. A kernel that lies defeats it. That limit is stated in the gate docstring.

### Explicit link policy (non-loopback interfaces)

| Independent state | `ifconfig` must print | Effect |
|---|---|---|
| `active` | any (a status other than active is also a MISMATCH) | violation: the link is up |
| `inactive` | `status: inactive` | the addresses decide |
| `no_media` | no status line | the addresses decide (tunnels carrying only link-local addresses pass) |
| `status_invalid` | no status line | UP and addressed: link state not established, FAIL_CLOSED (`LINK_STATE_UNESTABLISHED`); otherwise the addresses decide |
| `vanished` | n/a | MISMATCH: interface set unstable |

A MISMATCH, an unavailable source, a malformed map, or an interface-name set that differs from `ifconfig` marks the interface view incomplete and FAIL_CLOSED. The same signal marks the routes and sockets views reduced. Availability cost: an UP addressed interface in `status_invalid` (on this host `llw0`) makes the gate FAIL_CLOSED until it settles. That is deliberate; availability is preferred over false isolation.

Before and after the audit construction: the old logic gave PASS, the new gate gives FAIL for the same host (`test_FB_the_old_gate_logic_would_have_passed_that_case_proving_the_test_is_meaningful` shows the ifconfig-only view sees no violation).

## 4. PCB band adjudication (BP)

SUPERSEDED. This section described a band of `max(1, int(0.75 * lo))` and `hi + 12` and called 12 the measured constant excess. That was falsified: the excess measured 8 to 17 and drifts, and closed PCBs lift the counter above the listed rows, so the band rejected the genuine table in 28 of 30 samples. It is withdrawn; see `GENESIS_V2_TIER0S_PCB_REMEDIATION.md`.

## 5. SEAL payload handling (BW6)

`store.py` changed only to validate the plaintext after authentication: exactly the private splits as keys, each a 64-character lowercase hex string. Only `ValueError` (which includes decoding errors) and `RecursionError` are translated into `PrivateStorageIntegrityError`. Cryptographic functions are unchanged, which function-level pins in `tests/test_genesis_v2_tier0s_w1_w2.py` verify. Note the writer is not authenticated to the reader: anyone holding the vault public key can produce an authentic artifact, so authenticity here means the vault key holder can decrypt it, not who sent it.

## 6. Claim ledger

Closed vocabulary: ENFORCED (the gate or a test refuses on violation), ADVISORY (reported, a person must act), PROCEDURAL (depends on a human step), UNPROVEN (no evidence either way).

| ID | Class | Claim |
|---|---|---|
| C1 | ENFORCED | Any check that is not PASS makes the gate fail |
| C2 | ENFORCED | A reduced `netstat` view (Internet section absent) fails closed |
| C3 | ENFORCED | Whole TCP/raw table disappearance with a nonzero counter fails |
| C4 | ENFORCED | An UP addressed interface with an unestablished link state fails closed |
| C5 | ENFORCED | Independent active link on a non-loopback interface fails |
| C6 | ENFORCED | Unavailable, malformed or inconsistent link-state telemetry fails closed |
| C7 | ENFORCED | A parser or collector defect fails closed with its class name |
| C8 | ENFORCED | Fixed absolute system tool paths with a clean environment |
| C9 | ENFORCED | Trusted home taken from the password database |
| C10 | ENFORCED | Descriptor-relative walker with `O_NOFOLLOW` |
| C11 | ENFORCED | Manifest pin with canonical bytes |
| C12 | ENFORCED | Interlock file locking |
| C13 | ENFORCED | Malformed authentic SEAL plaintext gives a typed integrity failure |
| C14 | ENFORCED | AES-256-GCM, HKDF and X25519 functions are pinned |
| C15 | ADVISORY | The gate is a one-shot pre-flight with no isolation credit |
| C16 | ADVISORY | Socket non-emptiness corroboration only (superseded band withdrawn), not row-by-row evidence |
| C17 | ADVISORY | Link-state source shares the kernel with `ifconfig` |
| C18 | ADVISORY | Route table has no independent source and no integrity claim |
| C19 | PROCEDURAL | Physical detachment of the second machine |
| C20 | PROCEDURAL | Cold boot and memory remanence handling |
| C21 | PROCEDURAL | Real-environment isolation acceptance is a separate gate, never yet met |
| C22 | UNPROVEN | UDP socket absence |
| C23 | UNPROVEN | Behaviour under a kernel that misreports link state |
| C24 | UNPROVEN | The ancestor property that triggers the reduced OS view |

## 7. Residual limitations

The reduced telemetry view on non-Apple ancestors is detected, never repaired: every such lineage stays FAIL_CLOSED with `TELEMETRY_COMPLETENESS_UNPROVEN`. Run the gate from an Apple-signed ancestor chain. The gate remains a software pre-flight. Acceptance of a real Tier0-S environment is a separate gate that has not been met, and no Qualification, foundation selection, GPU preparation or training follows from this document.

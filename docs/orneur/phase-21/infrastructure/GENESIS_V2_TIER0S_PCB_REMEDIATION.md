# Genesis V2 Tier0-S — PCB plausibility final remediation

Base SHA `f0efe8612eb214f5548a48a6d109a0c05b0856f2` (verdict `TIER0_S_FINAL_ACCEPTANCE_BLOCKERS_NOT_RESOLVED`). Scope: the TCP/raw socket check in `scripts/genesis_v2_tier0s_phase_gate.py`, its documentation, and two small follow-ups. This document grants no permission of any kind. No Decision 9, no real Tier0-S, no secrets, no corpus, no Qualification, no model, no GPU, no training.

## 1. Traceability matrix

| ID | Finding | Remediation | Regression tests |
|---|---|---|---|
| PF1 | The `hi + 12` upper bound and 0.75 lower floor were fitted to one load state and rejected the genuine table in 28 of 30 samples. | Both constants removed; only non-emptiness is used. | `test_PCB_the_unsound_constants_are_gone`, `test_PCB_the_measured_closed_pcb_case_is_accepted`, `test_PCB_a_genuine_table_is_never_rejected_whatever_the_lifecycle_state`, `test_PCB_LIVE_the_genuine_unfiltered_table_is_accepted_repeatedly` |
| PF2 | The socket check must not carry the network verdict. | Data-flow proof (section 5), advisory flag on the PASS, tests that no socket input changes the interface verdict. | `test_PCB_NO_socket_table_or_counter_can_turn_a_network_violation_into_a_PASS`, `test_PCB_the_interface_verdict_does_not_read_the_socket_input_at_all`, `test_PCB_the_socket_PASS_is_advisory_and_says_what_it_does_not_show` |
| PF3 | Loopback sockets inflate the counter; small counters need an explained rule. | Attacks run and pinned (sections 6 and 7). | `test_PCB_loopback_inflation_changes_nothing_that_matters`, `test_PCB_small_counters_have_one_explained_behaviour`, `test_PCB_whole_table_disappearance_is_detected_for_every_nonzero_counter` |
| PF4 | The reduced OS view and the link-state fix must survive the change. | Reduced-view signatures re-tested; live reduced lineage re-run; the audit's original false-PASS construction re-run. | `test_PCB_the_reduced_view_signatures_all_still_fail_closed`, `test_PCB_LIVE_a_reduced_lineage_is_still_FAIL_CLOSED`, `test_PCB_the_original_false_PASS_construction_still_does_not_pass` |
| PF5 | Route naming an interface absent from the inventory; socket-parser defect entry. | New narrow route rule; the socket parser's own `PARSER_DEFECT` entry is asserted. | `test_PCB_a_route_naming_an_unknown_interface_is_FAIL_CLOSED`, `test_PCB_a_route_via_an_interface_that_exists_without_an_address_is_not_refused`, `test_PCB_an_injected_socket_parser_defect_reports_its_OWN_entry_without_leaking` |
| PF6 | Documentation described 12 as a constant and the band as a completeness mechanism; the acceptance-status document omitted link state. | Every affected document corrected; guard tests added. | `test_PCB_no_document_still_describes_12_as_a_constant_or_the_band_as_a_completeness_check`, `test_PCB_the_acceptance_status_document_mentions_the_independent_link_state` |

## 2. What the counter means (measured, macOS 27.0.1)

Controlled experiment: create sockets in a known process and compare the kernel counter `net.inet.tcp.pcbcount`, the rows `netstat -an` prints, and the kernel PCB list (`sysctl net.inet.tcp.pcblist_n`) that `netstat` reads.

| Observation | Result |
|---|---|
| 50 IPv4 loopback listeners | counter +50, rows +50 |
| 50 IPv6 loopback listeners | counter +51, rows +51 |
| 50 dual-stack wildcard listeners | counter +50, rows +50 (one row per PCB, one counter per PCB, no sharing between families) |
| 50 connected pairs (100 sockets) | counter +100, rows +100 |
| Pairs closed | counter unchanged at 387, rows fell by 50 |
| All closed | counter fell by 202 later; rows and counter diverged by up to 202 in between |
| Closing 100 connections (second run) | counter stayed at 472, rows fell to 284 (ratio 0.60) |
| Idle, rows minus counter | 8 to 17 across hours and load states; 10 at counter 138; 15 to 17 at counter 65; not constant, not proportional |
| Netstat rows versus `pcblist_n` records | equal in every sample |
| `pcblist_n` header count versus counter | header exceeded the counter by 8 to 14, drifting |

Conclusions. The counter counts allocated PCBs, including closed ones awaiting reclamation. `netstat` lists live PCBs and a few the counter does not count. TIME_WAIT and closing PCBs affect the relationship in both directions over time. IPv4 and IPv6 share the one TCP counter, and one PCB yields one row. No public relationship is documented and none was found: rows minus counter ranged from -1165 to +23 under churn, so no fixed or proportional bound holds in either direction. The excess `e` is real but unexplained; it is not claimed to be anything.

The kernel PCB list is the data `netstat` prints, and in the reduced lineage it arrives with its header count intact and zero records. The filter therefore acts on the list itself, so reading the list directly would add a private-layout dependency and no independence. That option (direct source) is rejected; the earlier statement that `pcblist64` was unfiltered in the reduced lineage is withdrawn.

## 3. Final design

For TCP and for raw/ICMP separately: if the kernel counter is at least 1 at both reads (before and after the `netstat` call) and zero rows of that class were parsed, the table is refused with `TELEMETRY_COMPLETENESS_UNPROVEN`. Nothing else is compared. There is no ratio, no additive allowance, and no host-specific number. The result of the socket check can only ever add a failure; a PASS of `network_no_external_sockets` is flagged `advisory`.

What it establishes: the known reduction (the kernel hands the filtered process an empty list while counting PCBs) is detected, and the detection feeds the existing rule that marks ifconfig, routes and sockets unproven together. What it cannot: it says nothing about how many rows are present. One external listener, or every external listener, can be missing from an accepted table. Anyone who can create loopback sockets can raise the counters at will. A host whose every PCB is closed but not yet reclaimed would fail the check (a false failure, never a false pass).

## 4. Why the direct-source alternative was not adopted

`pcblist_n` is the same list `netstat` renders and is filtered identically in the reduced lineage. Parsing it needs the private record layout, which varies by release, and a per-process view (`libproc`) sees only processes of the same user without privilege. Neither gives an independent complete enumeration, so neither can replace the counter honestly.

## 5. Data-flow proof that the socket check is not load-bearing

The network verdict is formed in this order.

1. Interface enumeration: `ifconfig -a` parsed strictly, compared with two libc inventories (`getifaddrs`, `if_nameindex`).
2. Addresses and UP flags: any non-loopback address other than a tolerated link-local IPv6 address makes `network_interfaces_disabled` FAIL.
3. Independent kernel link state (`SIOCGIFMEDIA`, in-process): an active link makes it FAIL; an unestablished link state on an UP addressed interface makes it FAIL_CLOSED.
4. Route corroboration: a default route makes `network_no_default_route` FAIL; the route table can only add failures.
5. Sockets: an external row makes `network_no_external_sockets` FAIL; an unusable or empty table adds FAIL_CLOSED; a PASS is advisory.
6. Whole gate: passes only if every check is PASS.

Claim. If the socket count comparison misses any number of rows, the gate cannot return PASS while usable non-loopback networking exists, except where interface evidence itself is wrong. Argument. Usable networking needs an UP interface with an address other than link-local IPv6, or an active link. Step 2 or step 3 turns either into FAIL, and `bad_names` is computed before any use of `incomplete`, so socket failures cannot downgrade a FAIL to PASS and socket success cannot upgrade one. The interface check reads no socket input; `test_PCB_the_interface_verdict_does_not_read_the_socket_input_at_all` pins that the interface result is byte-identical across three socket worlds. Residual: a link-local-IPv6-only interface on a non-active link is tolerated by policy; sockets are the only evidence of use there, and they are advisory. Both address sources and both link sources being wrong together is outside this analysis.

## 6. Loopback-inflation attack

With `created` loopback sockets and 60 external connections, the old band's removable margin grew with the counter; with 250 created sockets every external row could be removed. Under the new rule the accepted margin is unchanged by construction (only an empty table is refused) and the network verdict does not read sockets, so inflation gains nothing. Measured against the old band with synthetic tables in the verification probe: a counter inflated by 200 created loopback sockets accepted the removal of all 60 external rows. After the change nothing about the socket table affects any verdict that matters, and the documentation states the blind spot plainly.

## 7. Small counters

Counter 0: nothing is claimed either way (sockets may open after the read). Counter 1 to 20 and above: at least one row of the class is required and no more. A zero counter no longer accepts "a large table without explanation" because no count is compared; it accepts a table because no source contradicts it.

## 8. Load and churn (samples taken on this host with the final rule)

Run from the unfiltered lineage, each sample the gate's own collection and check. The old band's rejections are computed from the same data for comparison.

| State | Samples | New rule rejected | Old band rejected | rows minus counter | rows over counter |
|---|---|---|---|---|---|
| Idle (Docker daemon unreachable at the time) | 30 | 0 | 30 | +13 to +16 | 1.18 to 1.24 |
| Moderate TCP churn (20 connections per second) | 30 | 0 | 12 | -5 to +23 | 0.95 to 1.13 |
| Heavy loopback churn (4 threads, 500 per second) | 30 | 0 | 1 | -1165 to -37 | 0.69 to 1.00 |
| Rapid short-lived connections (4 threads, unthrottled) | 30 | 0 | 0 | -4192 to -189 | 0.81 to 0.99 |
| 250 listeners and 200 pairs held | 15 | 0 | 0 | +6 to +7 | 1.01 |
| Draining after 200 pairs closed | 20 | 0 | 0 | -4 to +6 | 1.00 to 1.01 |
| Draining after 250 listeners closed | 20 | 0 | 2 | -244 to +6 | 0.69 to 1.01 |
| Settled 70 seconds later | 20 | 0 | 0 | +3 to +4 | 1.03 to 1.04 |

The new rule rejected 0 of 195 genuine samples; the old band rejected 45. Docker was running during the earlier measurements (14 and 17 excess) and not reachable during this run; the excess did not depend on it.

## 9. Follow-ups

Route rule. On the live host no route row named an interface outside the inventory (81 route rows over 2 IPv4 and 11 IPv6 interface names), and none named an unaddressed interface. A route naming an interface absent from the independent inventory is now `FAIL_CLOSED`: one of the views is stale or reduced. A route via an interface that exists without an address is not refused: no evidence shows that to be abnormal.

Parser defect detail. The socket parser's own entry reports `sockets=PARSER_DEFECT:<Class>` in the telemetry detail with no exception text, asserted directly, and the detail lists every unverified source so earlier entries cannot hide later ones.

## 10. Authorization bookkeeping

The earlier verification said it could not locate standalone records for the owner-key ceremony and Qualification authorization. Corrected: `docs/orneur/authorization/MODEL_EVAL_AUTHORIZATION.json` (status `NOT_AUTHORIZED`, zero runs, zero spend) and `QUALIFICATION_RUNNER_REGISTRY.json` (registered, not authorized) exist, and a public owner authority key is registered (`AUTHORITY_REGISTRY.json`, registered 2026-09-28 with GPU, spend and provider-inference permission all false). No private key is in the repository. The key ceremony is an owner-only physical procedure (`OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md`), not a gated authorization with a record; its absence as a runtime record appears intentional. A future bookkeeping item, not done here: if the frozen architecture should show an explicit deny-state for the ceremony, that is a design decision for the owner. Nothing was authorized or created.

## 11. Claim ledger

Closed vocabulary: ENFORCED (the gate or a test refuses on violation), ADVISORY (reported, a person must act), PROCEDURAL (depends on a human step), UNPROVEN (no evidence either way).

| ID | Class | Claim |
|---|---|---|
| P1 | ENFORCED | A non-PASS check fails the gate |
| P2 | ENFORCED | An empty TCP or raw table with a nonzero counter at both reads is refused |
| P3 | ENFORCED | Interface addresses and independent link state decide the network verdict |
| P4 | ENFORCED | A route naming an unknown interface is FAIL_CLOSED |
| P5 | ENFORCED | Malformed or missing counters are FAIL_CLOSED |
| P6 | ENFORCED | A parser or collector defect fails closed with its class name |
| P7 | ENFORCED | The reduced OS view is detected and never receives a security PASS |
| P8 | ADVISORY | A socket-check PASS shows only that no external row was observed |
| P9 | ADVISORY | The route table has no independent source |
| P10 | ADVISORY | The link-state source is the same kernel answer as ifconfig's |
| P11 | UNPROVEN | Row-by-row completeness of the TCP or raw table |
| P12 | UNPROVEN | Detection of one or all external listeners missing from a non-empty table |
| P13 | UNPROVEN | Any loopback-inflation resistance of a count comparison (none is claimed) |
| P14 | UNPROVEN | UDP presence or absence |
| P15 | PROCEDURAL | Physical detachment, cold boot and real-environment isolation |

## 12. Residual limitations

The gate is a one-shot software pre-flight, not continuous. The socket table cannot be shown row-complete by any source this gate can use. The reduced view is detected, not repaired; run from an unfiltered lineage. The link-local-IPv6-only tolerance, the link-state source sharing the kernel with `ifconfig`, and the two-source-wrong cases remain documented bounds. Real-environment isolation acceptance is a separate gate that has not been met.

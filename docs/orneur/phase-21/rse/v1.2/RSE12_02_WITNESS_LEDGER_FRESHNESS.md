# RSE-ARCH-1.2 — Part 2: witness policy, log-first grants, offline checkpoint transport, freshness, crash semantics, role lifecycle (closes H2)

Architecture only. Supersedes the witness, freshness and state-machine text of `RSE11_02` §V and `RSE11_03` §N, §O where they differ.

## 1. Holders and the required witness policy

### Holder kinds

| Kind | What it is | Independent of the role it witnesses? |
|---|---|---|
| **LH** local log holder | the role's own append-only log; signs its own checkpoints | no (it is the role) |
| **XH** cross-role holder | another role that receives and keeps the latest cosigned checkpoint of this role (Crown keeps those of Forge and Witness; Forge and Witness keep Crown's, delivered with every grant) | partly; **DETECTIVE only**, because it runs no online consistency check |
| **OC** owner offline checkpoint | the latest cosigned checkpoint digest written on the Owner Floor Card at floor-raising events and at least once per `K` or `registry` event | yes (paper), but physical and periodic |
| **M1** Monitor-Lite primary | a secret-free witness device/service that verifies consistency proofs and cosigns | yes: a different device and a different hosting/account credential set from every role |
| **M2** Monitor-Lite secondary | a second witness, different device **and** different hosting/account from M1, enrolled at provisioning, kept in step by handover records | yes |

**Independence rule.** Two holders are independent only if no single compromise among {daily-driver, any one role, one token, one hosting account/device} controls both and they are administered with separate credentials. Three copies on Crown, Forge and the daily-driver are **not** independent and are never counted. M1 and M2 share one human administrator (declared residual R-N1).

### Required signatures by event

| Event | Required before it counts | Detective extras |
|---|---|---|
| Grant, class V or G (routine) → `CHECKPOINTED` | LH checkpoint (Crown) **and** M1 cosignature | XH copy at consumer on delivery |
| Grant, class K, Q, T, W, D, R; registry updates touching ENROLMENT, ROLE_IMAGE, POLICY, FOUNDATION_MODEL, or an epoch raise → `CHECKPOINTED` | LH **and** M1 **and** M2 cosignatures; for K and epoch raises also OC (card serial N+1 typed into Crown) | XH copies |
| Phase completion (result): Forge generation, Witness verification/acceptance | LH checkpoint of the producing role **and** M1 cosignature | XH at Crown; M2 later |
| Corpus/model becoming `WITNESSED_ACCEPTED`/`accepted` in the registry | the acceptance record's checkpoint cosigned by M1 (M1∧M2 for model acceptance) | |
| Recovery (K): re-enrolment, re-root | LH ∧ M1 ∧ M2 ∧ OC | forensic copies |

### M1 and M2: honest classification

Monitor-Lite is **not** "non-authoritative". It is a **REQUIRED_WITNESS**: it holds no secrets and signs no grants, but because its cosignature is required, (a) its unavailability stops sensitive authority (availability authority), and (b) a malicious M1 combined with a compromised role could cosign two histories (equivocation) for routine classes. Controls: irreversible classes require M2 as well; any holder that sees two cosigned roots for one (log, size) quarantines the log; M2 is kept in step by handover records so it cannot be shown a different past. M1/M2 may be extended later (provider-budget watching) only as detective functions.

### What a witness verifies

Role signature on the checkpoint; the enrolment entry is APPROVED; `tree_size` ≥ its last cosigned size for that log (never smaller); a consistency proof from that last size; same-size roots are identical; epoch ≥ its floor. It sees only hashes and sizes — leaves are metadata and digests, never secrets. It refuses anything else. It never accepts a smaller or forked tree.

## 2. Log-first grant sequence (authorization tail suppression closed)

For every state-changing grant, **`SIGNED` does not mean executable.**

`PROPOSED → OWNER_VERIFIED → SIGNED → APPENDED → CHECKPOINT_CREATED → REQUIRED_WITNESS_ACKNOWLEDGED → CHECKPOINTED → DELIVERED → CONSUMER_CONFIRMED → ACTIVE`

| Transition | Conditions (all) |
|---|---|
| PROPOSED → OWNER_VERIFIED | proposal decodes in the canonical class layout; every ID resolves in the registry; ceilings ≤ policy caps; owner typed the card floor tuple; Crown showed the grant card |
| OWNER_VERIFIED → SIGNED | the class's signature count from **distinct** approved tokens |
| SIGNED → APPENDED | the grant's hash is appended to the Crown log (durable) |
| APPENDED → CHECKPOINT_CREATED | Crown signs a checkpoint covering that leaf |
| CHECKPOINT_CREATED → REQUIRED_WITNESS_ACKNOWLEDGED | the required acknowledgements of §1 are present for **this** checkpoint (matching log, size, root, epoch) |
| → CHECKPOINTED | Crown stores the acks; an inclusion proof for the leaf exists |
| CHECKPOINTED → DELIVERED | grant, inclusion proof, cosigned checkpoint and registry delta written to the carried medium |
| DELIVERED → CONSUMER_CONFIRMED | consumer verifies: grant length and class layout; signatures against the approved owner authority; every registry check; challenge equals its outstanding challenge; target role and environment measurement; epoch, authority and registry floors; `prev_role_checkpoint` is an ancestor of its current head and every record appended since then is of a non-state-changing kind (boot, challenge issue, maintenance evidence) — a consumption, result or acceptance record after it makes the grant stale and it is refused; inclusion proof against a checkpoint carrying all required cosignatures; where confirmation is required (irreversible phase changes; the first grant of an envelope), the owner typed the correct SAS **and** the Intent Sheet fields (`RSE12_01` §4), and they match the grant |
| CONSUMER_CONFIRMED → ACTIVE | consumer wrote and fsynced the consumption-start journal record **before** any secret is released |
| ACTIVE → CONSUMED → EVIDENCE_PENDING → COMPLETE | §4 |

**If the required witnessing does not happen, the grant stays unusable.** A later checkpoint is never a substitute: the consumer checks the acknowledgements **for the checkpoint that includes this grant**. Forbidden transitions (all rejected and logged): PROPOSED→ACTIVE; SIGNED→ACTIVE; APPENDED→ACTIVE; CHECKPOINT_CREATED→DELIVERED; DELIVERED→ACTIVE; EXPIRED→ACTIVE; REVOKED→ACTIVE; COMPLETE→ACTIVE; QUARANTINED→anything except RECOVERY handling; any training-complete record → W authorization; any W-complete record → D authorization. One outstanding state-changing grant per role (a second is refused until the first is COMPLETE, INTERRUPTED, EXPIRED or REVOKED).

## 3. Offline checkpoint transport

No unstated online service is used. Everything crosses domains on a **carried medium (CM)** that holds public data only. A CM is a raw block device (no filesystem) with a header block (magic, record count) followed by fixed-size records; role-side readers read only these fixed sizes.

| Record | Contents |
|---|---|
| `OCK1` checkpoint (181 bytes) | magic, version, `log_id` (role ID), `tree_size` u64, `root` 32, `epoch` u32, `registry_version` u32, `prev_checkpoint_digest` 32, role signature 64 |
| `OCP1` witness request (2315 bytes) | magic, version, `packet_seq` u64, `source_role_id`, `target_witness_id`, `OCK1`, `old_tree_size` u64, `proof_count` u8 (≤ 64), 64 proof slots of 32 bytes (unused zero) |
| `OCA1` acknowledgement | magic, version, `witness_id`, `source_role_id`, `log_id`, `tree_size`, `root`, `epoch`, `witness_time` u64 (**detective**), witness signature over `"OCA1-SIG" ‖ 0x00 ‖` all prior fields |
| `OCH1` challenge | magic, version, `role_id`, `challenge` 32, `challenge_seq` u64, `next_sequence` u64 (for roles that emit a bundle stream; Crown sets the V sequence range from it and the G batch count), `role_log_head` 32 (the grant's `prev_role_checkpoint` is this head), role signature |
| `OCI1` inclusion proof | leaf hash, leaf index, tree size, up to 64 hashes |

Rules: `packet_seq` is strictly increasing per (source, witness) pair and stored by the witness; a replayed request returns the same ack (idempotent) and cannot move any log backwards; an acknowledgement is valid for exactly the (log, size, root, epoch) it names. One physical medium may batch several records (several grants, several roles) in one trip. Media handling: public data, but it is still treated as hostile input — fixed-size reads only, no filesystem mounting on Crown or the Witness, and a medium that carried secrets is never reused for transport.

**If the witness is unavailable:** grants remain at CHECKPOINT_CREATED. They do **not** expire on a clock. The owner may (i) wait, (ii) after a K-class handover record, switch the primary to M2 (which must first hold M1's last cosigned head), or (iii) revoke the grant. There is no mode in which fewer witnesses are accepted.

## 4. Result egress gating

Sensitive-phase output may not become trusted elsewhere before its result is checkpointed and witnessed.

`execution complete → RESULT record appended → result checkpoint created → required witness acknowledged → result permitted to be trusted/consumed`

Explicit placement of the gate:
- **Plaintext never leaves** Forge or the Witness in any case.
- **Exception E1 (stated):** Forge may write the **encrypted, signed** bundle to the single-use transfer medium before the result checkpoint is witnessed, because Forge is powered down and wiped at the end of the secret phase and cannot wait online. The bundle is then *untrusted staging*: the Witness refuses it (Phase 1) unless the carried medium also holds the `RESULT` leaf, an `OCI1` inclusion proof, and a checkpoint of Forge's log carrying the required cosignature(s). A compromised Forge therefore cannot produce an un-logged "successful" bundle that the Witness accepts.
- **Witness acceptance** stays `ACCEPTED_PENDING_WITNESS` until its acceptance checkpoint is cosigned; Crown will not approve a CORPUS registry entry carrying that acceptance record, and no Q/T grant may reference the corpus, until then.
- **Exception E2:** incident or failure reports may leave a role un-witnessed; they are informational, never trusted for state.

## 5. Freshness without a trusted clock

Offline clocks are attacker-settable and are **not** a freshness authority.

- **Challenge.** The consuming role issues a 32-byte challenge, journals it, signs an `OCH1` record, and leaves it on the carried medium. The challenge is produced by the RFC 8937 wrapper over the OS CSPRNG, keyed with the role's Ed25519 key (same mechanism as `RSE12_04` §5). Issuance happens at the end of the previous phase (**pre-issued**, no extra boot) or at `PRE_FLIGHT`.
- **Lifetime.** At most **one outstanding challenge per role**; a new challenge voids the old one. A challenge is valid until it is consumed by exactly one grant, or superseded. No wall clock is involved.
- **Binding.** `grant.challenge` must equal the role's outstanding challenge and `grant.target_role_id` the role.
- **Consumption and replay.** At ACTIVE the challenge is moved to the role's consumed set (journal, then log). A grant whose challenge is not the outstanding one is refused; a replayed grant meets a consumed challenge.
- **Crash recovery.** The journal is written before each transition; see §7.
- **`not_after` is advisory.** It is checked only before activation, the role's own clock may only make the role refuse (never extend), and it is never the sole gate. Staleness of owner *intent* is limited by registry/epoch revocation: the consumer must hold the registry version the grant names, so revocations reach it with each grant.
- **Residual R-F1:** a pre-issued challenge may sit a long time; the grant it receives reflects the owner's intent at signing time; the world may change before consumption; only registry/epoch revocation and the one-outstanding rule bound this.

## 6. External time (what it is and is not)

Monitor-Lite may add `witness_time` to acknowledgements and may anchor cosigned heads in a public timestamp service (such as OpenTimestamps). That contributes **timestamp evidence, ordering confidence and forensic value** (it can show an alleged history could not have existed before a time). It is `DETECTIVE`. It is never used as the sole authorization freshness mechanism.

## 7. Grant crash recovery (the role never guesses)

State written to a write-ahead journal and fsynced **before** the corresponding transition; on boot the role reads the journal and applies:

| State at the crash | After reboot | Reason |
|---|---|---|
| DELIVERED | resume at DELIVERED: re-verify everything; the grant is still usable while its challenge is outstanding | no side effects occurred |
| CONSUMER_CONFIRMED (no consumption-start record) | **require re-confirmation** (owner types SAS again), then resume | the confirmation is not persistent evidence of intent |
| ACTIVE (consumption-start record, no terminal record) | **never resume**: mark `INTERRUPTED`, discard any partial output, record an interruption event; a **new grant with a new challenge** is required; consumed sequence numbers are **forfeited** (never reused) | secret and output state are indeterminate; this prevents double execution |
| EVIDENCE_PENDING (operation finished, result not checkpointed) | resume **evidence commit only** (re-export the already durable result record); the operation is not re-run | the result is durable and the operation must not run twice |
| any, journal unreadable or inconsistent with the log head | QUARANTINED | |

A consumption-start record is appended and fsynced **before** secret release; for K-class grants on the Witness it is also protected by the TPM fence (`RSE12_03` §3). For envelope grants (N batches), the count of completed batches is in the journal; after a crash the remainder is forfeited.

## 8. Mid-run expiry

Expiry before activation = `not_after` advisory check plus challenge validity. **After ACTIVE, wall-clock expiry never kills a security-critical operation.** The operation is bounded by resource ceilings that do not depend on wall time: `max_runtime_s` measured by the role's **monotonic** timer from ACTIVE, byte and batch ceilings, and spend/run ceilings. Revocation during execution: roles are offline and cannot learn of it; the in-flight operation is bounded by those ceilings and ends in SEALING; an owner-declared incident is handled by physically powering the role off, producing INTERRUPTED at next boot. Freshness (challenge) and resource ceilings are separate mechanisms and are never conflated.

## 9. Role lifecycle (transitions)

States: SEALED, MAINTENANCE, PRE_FLIGHT, AUTHORIZED, SECRET_RELEASED, ACTIVE, SEALING, EVIDENCE_COMMIT, REVOKED, QUARANTINED, RECOVERY.

| From → To | Condition |
|---|---|
| SEALED → PRE_FLIGHT | measured boot of an approved image; no secret released; software gate run |
| SEALED → MAINTENANCE | boot of an approved maintenance image (no secrets, no network stack, no vault access); only for registry-approved updates |
| MAINTENANCE → SEALED | maintenance result verified; floors not lowered |
| PRE_FLIGHT → AUTHORIZED | a grant reaches CONSUMER_CONFIRMED |
| AUTHORIZED → SECRET_RELEASED | consumption-start record durable; TPM release (Witness, PIN) or secret-volume unlock (Forge) |
| SECRET_RELEASED → ACTIVE | operation begins inside ceilings |
| ACTIVE → SEALING | completion, ceiling reached, or abort |
| SEALING → EVIDENCE_COMMIT | secrets destroyed/wiped and plaintext workspace gone |
| EVIDENCE_COMMIT → SEALED | RESULT record appended, result checkpoint created and exported on the medium |
| any → QUARANTINED | fork, head mismatch, bad proof, journal inconsistency, duplicate `enc` under a different digest |
| QUARANTINED → RECOVERY | class-K grant for the matching scenario |
| RECOVERY → SEALED | re-enrolment complete, floors verified, new checkpoint witnessed |
| any → REVOKED | enrolment entry REVOKED (identity terminal) |

**Impossible transitions** (rejected): SEALED→ACTIVE; PRE_FLIGHT→SECRET_RELEASED; AUTHORIZED→ACTIVE (skipping release); MAINTENANCE→SECRET_RELEASED; ACTIVE→SEALED (skipping SEALING and EVIDENCE_COMMIT); EVIDENCE_COMMIT→ACTIVE; QUARANTINED→SEALED; REVOKED→any.

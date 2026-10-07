# RSE-ARCH-1.2 — Part 3: anti-rollback matrix and TPM NV design (closes H3)

Architecture only; nothing is implemented, no TPM is chosen. Supersedes `RSE11_03` §W where they differ.

## 0. Principle

**A signature proves authenticity, not freshness.** An old object that was once validly signed is still validly signed. A signature is therefore never listed as an anti-rollback mechanism in this package. Anti-rollback requires a *monotonic reference* the attacker cannot lower. Allowed classes:

`TPM_NV` (hardware counter/fence), `INDEPENDENT_WITNESSED_CHECKPOINT` (detective unless a role is forced to consult it before acting), `OWNER_HELD_VERSION_FLOOR` (`RSE12_01` §6; physical, procedural), `PROVIDER_MONOTONIC_STATE` (P2 only), `PROCEDURAL_ONLY`, `UNSOLVED`.

"Prevented" means the role itself refuses; "detected" means a later witnessed checkpoint exposes it; "unsolved" means neither.

## 1. Matrix

P1 = Witness machine. M = Mac-based Crown/Forge (before a dedicated Crown device).

| Object | Authenticity control | Monotonic reference | Rollback status |
|---|---|---|---|
| Crown version/state (M) | Crown image digest on Owner Root Card; owner-signed registry ROLE_IMAGE entry | `OWNER_HELD_VERSION_FLOOR` (`crown_min_version`, typed at session start) + `INDEPENDENT_WITNESSED_CHECKPOINT` (a rolled-back Crown cannot get a smaller tree cosigned) | local prevention **UNSOLVED**; detected at next witnessing; owner floor check catches an old image only if the owner types the card |
| Crown on a dedicated device with a TPM (future) | as above | + `TPM_NV` fence as for the Witness | prevented for key release |
| Witness OS / UKI | owner Secure Boot signature; registry ROLE_IMAGE entry | `TPM_NV` fence (§3) + owner floor `witness_env_min_generation` + witnessed checkpoint | **PREVENTED** for key release after enrolment; detected otherwise |
| Witness role code | measured inside the UKI (same PCR); registry CODE entry | as Witness UKI (role code ships inside the UKI; its own version is part of the generation) | as above |
| Forge role code / image (M) | registry entries; enrolled-ID | owner floor; Forge reports code digest in each checkpoint and the Monitor flags below-floor | local prevention **UNSOLVED**; detected |
| Manifest (registry subset in force) | owner dual-token signature | `registry_version` ≥ floors: card, Crown sealed floor, witnessed registry checkpoint; Witness sealed floor under the fence for fence-bumping events | prevented at Crown if card typed; detected elsewhere |
| Policy (POLICY entry; grant schema minimum) | registry entry | registry version floors; `min grant schema version` inside POLICY; Witness mirror under fence for generation events | as manifest |
| Artifact registry | owner dual-token signature | card `registry_version` + `registry_root`; witnessed checkpoint of every registry update; consumer refuses a grant whose registry version it has not received | Crown: prevented if card typed; consumers: **PREVENTED only up to what they last stored**; a consumer rolled back on its own sealed registry floor is detected, not prevented (residual R-RB1) |
| Trust-root key version, owner-key version | owner authority records | card; Witness sealed value bound to the fence; witnessed checkpoint | Witness prevented (fence); Crown/Forge: detected |
| Incident epoch | in every grant and checkpoint | card; Witness sealed value bound to the fence; witnessed checkpoint | as above |
| Grant schema/version | grant `version` byte | POLICY minimum, as above | as policy |
| Corpus version | registry CORPUS entry + Witness acceptance record | witnessed acceptance checkpoint | vault rollback to an older snapshot **detected only** (vault root differs from the witnessed acceptance records) |
| Model version | registry MODEL entry | witnessed checkpoint; P2: provider monotonic state | detected; P2 state UNPROVEN |
| Ledger checkpoint | role signature + witness cosignature | witness refuses any smaller or forked tree; holders detect equivocation | rollback of a role's log **detected** at next witnessing |
| Revocation state | REVOKED approval state in registry entries | registry version floors; revocations delivered with each grant | a consumer that has not received the newer registry does not know; each grant carries the version it needs |
| Grant nonce / challenge | consumer-issued | consumed set in journal + log; challenge outstanding rule | rolled-back role state can re-accept one already consumed grant (bounded, R-RB2); irreversible classes closed by the fence (§3) |
| **Mac OS state** | none usable | none | **UNSOLVED**: a restored older disk image looks valid to the Mac; P0 stays synthetic-rehearsal-only |

## 2. Is the combination conceptually sufficient for P1?

For the **Witness**: yes for *key release*, because the decision to release the vault key is made offline and only local hardware can refuse it; the TPM fence (hardware) denies an old image or old sealed state, the owner floor card catches a wrong generation at enrolment/recovery time, and the witnessed checkpoint exposes a rolled-back vault or journal afterwards. Not sufficient to *prevent* an in-state rollback of the journal that does not change the fence (R-RB2). For Crown/Forge on a Mac: prevention is **not** achieved; the combination yields detection plus owner procedure.

## 3. TPM NV — why it exists and exactly how it is used

**One fence counter per Witness TPM**, no more. Justification: the Witness decides *offline* whether to release the vault key; an external checkpoint cannot stop that decision, it can only expose a rollback later. Only a local hardware monotonic value lets the TPM itself refuse a stale image or sealed state. Separate counters for each value were rejected: each extra write path is extra wear and extra recovery cases.

The **fence value** `N` is a TPM-local counter. Separately, the **security generation** `G` (global, monotonic across hardware, in the Owner Floor Card, the registry and the checkpoints) is stored *inside* the sealed state together with epoch, trust-root version and Witness environment generation. The data key is sealed under a **fixed** policy: `PolicyPCR(7, image PCR) ∧ PolicyNV(counter == N)`; PIN is a second factor outside the TPM policy (§`RSE11_02` §J). The fence is incremented only on: change of trust root, change of incident epoch, change of Witness environment generation, and **consumption of a K-class grant**. Budget: well under 100 increments per year (a design target, not a TPM specification claim; endurance is unverified on any chosen part and is acceptance item C25).

Can an external checkpoint replace NV? For prevention, no (see above). For detection, yes. Recorded accordingly.

### 3.1 Update transaction (new environment/policy N → N+1)

Keep **two boot entries** (A: current, B: new, both owner-signed and both present) and **two sealed objects** on disk (`S_N`, `S_N+1`).

1. In maintenance state under a K-class grant naming generation `G+1` and verifying `G+1` > card floor, build `S_{N+1}` sealed under `PolicyPCR(new predicted PCR values) ∧ PolicyNV(counter == N+1)` using the key released under `S_N`.
2. Write `S_{N+1}` and the new UKI to slot B; fsync; verify by hash.
3. Set the default boot entry to B.
4. **Increment the NV counter** (N → N+1). The old image can no longer unseal `S_N`.
5. Boot B; unseal `S_{N+1}`; write `commit(G+1)` into sealed state; checkpoint.
6. Remove `S_N` and slot A (invalid after step 4 regardless).

Power loss analysis:

| Cut at | State | Result |
|---|---|---|
| steps 1–3 | counter N, `S_N` valid | old image works; partial files ignored; retry (safe) |
| during step 4 | the TPM increment either happened or not | TPM NV counter increment is assumed atomic; **unverified on the chosen hardware**, so acceptance item C26 cuts power during increments; if neither state is clean: fail closed and recover with the passphrase path below |
| after step 4, before step 5 | counter N+1, default boot already B | boot B unseals `S_{N+1}`; if the default were A, A prints "fence advanced, boot B" and refuses; owner selects B from the signed boot menu |
| step 5 fails (PCR prediction wrong) | counter N+1, no valid unseal | **not bricked**: recovery boot (owner-signed maintenance image, no TPM release) plus the offline recovery passphrase and a K grant re-seal under the corrected prediction |

The recovery passphrase unlocks LUKS directly and so is a bypass of the rollback fence; it is handled as a full-strength secret (`RSE12_05` §4). Using it requires a K grant in the recovery image, which also refuses to lower any floor.

### 3.2 TPM or motherboard replacement, TPM clear, firmware reset

A cleared or replaced TPM loses sealed objects and the NV index. **No automatic rollback.** Recovery requires **all**: a class-K grant naming `TPM_REPLACE` with `G_new = G_old + 1`; the Owner Floor Card checked (nothing below floor); the Witness vault restored and its root compared with the **latest witnessed acceptance record** (independent checkpoint); explicit re-enrolment (new attestation key, new ENROLMENT entry, new ROLE_ID, old ID REVOKED); a **new** NV fence index whose counter starts from the TPM's own value — the policy is `counter == M` for the new TPM's actual value, and `G` (not the counter) carries the global monotonicity. Firmware updates change firmware PCRs; sealing therefore uses PCR 7 and the image PCR only, so a firmware update does not strand the key; firmware **downgrade** is detected by the quote's firmware PCRs and the owner floor `witness_firmware_min`, which is procedural and `DETECTIVE` only.

### 3.3 Signed-policy rollback

TPM signed policies (a signing key authorizing PCR values) are **not used**: an older validly signed policy is still authentic and would unseal an older image. The architecture seals under a fixed per-generation policy, and the fence kills old generations. If signed policies are ever introduced, that requires a new architecture decision with its own revocation mechanism (authorization key rotation bound to the fence); until then it is forbidden.

## 4. Honest summary

| Property | Status |
|---|---|
| Witness refuses older image/sealed state | `HARDWARE_ENFORCED` (needs C25–C26 on real hardware) |
| Witness rejects replay of irreversible grants after rollback | `HARDWARE_ENFORCED` via fence bump on K |
| Witness rejects replay of routine G/V after rollback | `UNPROVEN` for prevention; `DETECTIVE`; impact bounded by ceilings |
| Mac OS state rollback | `UNSOLVED` |
| Owner floor card | `PROCEDURAL` |

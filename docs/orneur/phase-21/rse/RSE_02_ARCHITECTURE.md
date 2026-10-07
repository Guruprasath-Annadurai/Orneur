# RSE-02 — Advanced Real Secure Environment architecture (RSE-ARCH-1.0)

Design only. Authorizations in `RSE_00_INDEX_AND_STATUS.md` apply to every sentence here. Classification words (STANDARD, ADAPTED, …) are defined in `RSE_01` §5. Maturity words (DESIGNED, IMPLEMENTED, …) are defined in `RSE_04`. **Every control below is DESIGNED at most.**

## 1. Assets, adversaries, properties, non-goals

**Assets, in order of consequence.** (A1) Authority itself: the owner signing keys and the grants they mint. (A2) Decryption material for the private evaluation corpus (the Witness key). (A3) Private corpus and holdout confidentiality. (A4) Integrity and provenance of every artifact: corpus, role code, evidence, later models and scores. (A5) Later, model weights and training state. (A6) Availability and recoverability.

**Adversaries in scope.** Compromised role process or host; malicious or poisoned artifact (data, code, dependency, media); stolen media or token; compromised daily-driver; network-borne attacker while a role is online; operator error; a compromised role trying to hide its actions; stale or replayed authority.

**Adversaries out of scope, stated so they are not smuggled in.** A malicious owner; coercion of the owner; a compromised Apple, TPM-vendor or token-vendor root; hardware implants; side channels; a nation-state with firmware-level persistence on shared hardware. Where a profile cannot resist a class (shared hardware in P0), it is named in `RSE_03` §3.

**Security properties.** SP1 no single role or host can silently complete generate, decrypt, approve and record. SP2 authority is narrow, short-lived, single-use and bound. SP3 untrusted bytes never meet a present decryption key through a large parser. SP4 history cannot be rewritten without external detection. SP5 any one role's compromise can be contained, revoked, rebuilt and kept out of later work. SP6 every claim of assurance states what it rests on. SP7 more capability never means fewer independent checks.

## 2. Design laws

| Law | Statement | Why it is there |
|---|---|---|
| L1 | Separate duties and keys; no environment holds more than one of generate, decrypt, approve, record. | SP1 |
| L2 | Key-absent ingestion: complex parsing of untrusted input happens while the relevant secret is locked; the key-present code is a small fixed-format verifier. | SP3. Attack round 1 showed key-absent parsing alone is not enough, because the same bytes are parsed again when the key is present (`RSE_03` A6). |
| L3 | Clean-before-secret: secrets unlock only into an environment whose mutable state is at a signed baseline and whose trust root a human has checked against an offline pin. | removes cross-boot software persistence; closes same-authority replacement of manifest and pin |
| L4 | Authority is a grant: signed, challenge-bound to one session, bound to role, environment, code, policy, data, model, operation, limits and destination, single-use, expiring. | SP2 |
| L5 | Evidence precedes authority: a new grant names the ledger head the role must already hold; evidence is two-sided and externally anchored. | SP4; rollback and fork resistance |
| L6 | Diverse trust: each critical operation needs at least two controls from different trust families (§3) that share no single point of compromise. Fake independence is rejected and labeled. | directive 2 |
| L7 | Assume compromise: each role has detect, contain, revoke, preserve, rebuild, taint and resume paths (§11). | SP5 |
| L8 | Honest labels: a self-reported state is labeled SELF_ATTESTED and never counts as attestation. | SP6 |

**Simplifications made (nothing kept merely to look sophisticated).**
- No separate Vault environment: the Vault is a data class (append-only ciphertext with ledger digests), not a trust domain. §4.
- No separate Transfer Chamber environment in P0 or P1: the boundary is a protocol (raw container, key-absent ingestion, minimal verifier). §8.
- No FROST or other threshold-signature protocol: plain k-of-n multi-signature is enough and reuses ordinary Ed25519 verification; FROST adds a dealer or key-generation ceremony without a property the design needs.
- No blockchain anchoring, no custom attestation protocol, no multiple-cloud design.
- Sentinel holds no secrets and no authority; it is a monitor and cosigner.

## 3. Trust families and the diversity rule

| Family | What it is | Common-mode warning |
|---|---|---|
| TF-H | the human: passphrases, offline pin, out-of-band comparison, attention | one human; rubber-stamping defeats it |
| TF-T | hardware token firmware and silicon | tokens from one vendor share a flaw class |
| TF-A | Apple platform: Secure Enclave, secure boot, macOS | one kernel, one firmware, one vendor across all Mac environments |
| TF-P | PC platform: UEFI Secure Boot, TPM 2.0, Linux (P1 Witness) | independent of TF-A |
| TF-X | physical separation: power-off, detachment, distance | does not survive shared firmware or a shared internal drive |
| TF-E | external witnesses: public git host, independent monitor, router canary | owned or operated by the same owner unless separate accounts and tokens are used |
| TF-C | cryptography | safe only as long as key custody is |
| TF-S | software diversity: two independent builders, two validators | shared upstream dependency defeats it |
| TF-V | vendor confidential-compute roots (P2) | cloud operator and vendor attestation services |

**Rule R1.** Two controls count as independent only if they come from different families **and** no single compromised host, kernel, vendor or human session defeats both. Anything else is recorded as a common-mode failure (§10).

## 4. Roles

Roles are added only where they create a real boundary. Nine are specified (the eight asked for plus Release Notary as a process role).

| Role | Purpose | Boundary it creates | Holds | Never holds | P0 realization | P1 realization |
|---|---|---|---|---|---|---|
| **Crown** (Owner Authority) | mint and revoke authority; approve | only place grants and root changes originate | grant-signing tokens (when inserted), canonical grant renderer, registry | corpus secret, decryption key, model code | dedicated Crown boot environment, offline, no agents | same, on the Mac external boot environment |
| **Forge** | generate corpus | cannot decrypt; cannot authorize | vault public key, generation secret | decryption key, owner tokens | dedicated boot environment | dedicated Mac boot environment |
| **Witness** | decrypt, verify, hold the private key | highest-severity secret; never touches generation or authority | vault private key, verifier identity | corpus secret, owner tokens, model code | dedicated boot environment | **dedicated TPM PC running Linux** |
| **Vault** | custody of ciphertext | integrity and write-once policy, not execution | nothing secret | any key | data class: append-only ciphertext, digests in the ledger; copies on Reliquary | same |
| **Transfer Chamber** | cross Forge to Witness safely | the crossing protocol | public keys only | any secret | protocol inside the receiving environment (§8) | same; optional separate environment in P2 |
| **Qualification Chamber** (future) | run untrusted candidate models against the holdout | untrusted code near secret data; bounded output | holdout during a grant only | owner tokens, generation secret | not feasible beyond a stub; see §13 | GPU host, future; confidential-compute key release (P2) |
| **Evidence Ledger** | tamper-evident record of requests, grants, executions, results | history separate from the actors | no secrets | any key besides its own signing identity | local chain per role plus external anchor | same |
| **Sentinel** | independent monitor, clock and policy cosigner | detection and an independent policy check outside the owner's machines | its own signing key; public data only | owner tokens, any corpus material | external CI or service in separate accounts | same |
| **Reliquary** | backup and recovery material | offline, physically separate copies | ciphertext copies, rebuild kit, sealed recovery shares | live keys | offline media, off-site | same |
| **Release Notary** (process) | approve role code | code approval separate from grant approval | manifest-signing token | grant tokens | process in Crown | same |

**D1 — trust boundaries (P1 shown; P0 puts the Witness box inside the same Mac as Crown and Forge).**

```
 OWNER (human, offline pin on paper, tokens T1 T2 T3)
   |  presence + token touch                        external, no secrets
   v                                               +-------------------------+
 +-----------------+  proposal (read-only)         | SENTINEL (monitor,      |
 | DAILY-DRIVER    |------------------------------>|  clock, policy cosign)  |
 | propose/observe |                               | LEDGER ANCHOR (git etc.)|
 | NEVER signs     |                               +-----------^-------------+
 +-----------------+                                           | heads
        | media only (no network trust)                        |
 =======|=======================================================|===== (Mac, sequential boots) =====
 | CROWN env  (offline)   <-> grants -> | FORGE env (offline)   |
 |  tokens only here                      |  public key only      |
 =============================================|==================
                                              | M1: raw ciphertext medium (one way)
 ================================== separate hardware, TPM, Linux, never networked =========
 | WITNESS: key-absent ingest -> reboot to baseline -> TPM+PIN unlock -> minimal verifier   |
 ==========================================================================================
        | M2: evidence-only record, size-bounded (one way back)
        v
   CROWN / LEDGER / RELIQUARY (offline copies)
```

**D2 — sovereign roles and what each can never do.**

```
 Crown     : sign grants        | cannot decrypt, cannot generate, cannot run model code
 Forge     : generate           | cannot decrypt, cannot sign grants
 Witness   : decrypt + verify   | cannot generate, cannot sign grants, cannot export bulk data
 Qual.Ch.  : score candidates   | cannot see anything outside a grant, output bits capped
 Ledger    : record             | cannot authorize
 Sentinel  : monitor + cosign   | cannot authorize alone, holds no secrets
 Reliquary : preserve           | holds no live key
 Notary    : approve code       | cannot mint grants
 => no role holds two of { generate, decrypt, approve, record }
```

**D3 — data flow (secrets in bold).**

```
 Crown --grant(G)--> Forge --[ciphertext bundle B + Forge evidence]--> M1 --> Witness
 **generation secret** stays in Forge       **vault private key** stays in Witness
 Witness --[result hash + evidence record, size-bounded]--> M2 --> Crown/Ledger
 Ledger heads --> external anchor <-- Sentinel reads, never writes secrets
 plaintext exists only in Forge RAM (generation) and Witness RAM (verification)
```

## 5. The daily-driver, treated as potentially compromised

| Function | Verdict | Reason | What replaces it |
|---|---|---|---|
| Crown authority (minting grants) | **NOT SUITABLE** | runs agents, cloud sync, browsers; the documented generation procedure for the registered owner key (`OWNER_AUTHORITY_KEY_GENERATION_PROCEDURE.md`) produces a key file, and where that key actually lives is not evidenced; a hardware token alone does not fix this | Crown boot environment, offline, tokens only inserted there |
| Signing | **NOT SUITABLE** | a compromised host can ask a plugged-in token to sign something else at the moment the owner taps | tokens never inserted outside a Crown session; touch policy; PIN |
| Approval presentation | **NOT SUITABLE** | a compromised host controls what the owner sees (what you see is not what you sign) | canonical renderer in Crown; digest also displayed by the consuming role (dual display, M10) |
| Digest verification | **NOT SUITABLE** as the only path | same | comparison against the role's display plus the offline paper pin |
| Key rotation | **NOT SUITABLE** | root change is the highest-impact act | Class K ceremony in Crown with threshold tokens and a new paper pin |
| Training authorization | **NOT SUITABLE** | Class T needs the strongest approval path | Class T grants only from Crown, with reviewer attestation and external cosigner |
| Authoring proposals, reading public evidence, repository work | acceptable | no authority can result from them | — |

**A token does not make an untrusted host safe.** It protects key extraction; it does not protect what the owner is asked to approve or when a signature is requested.

## 6. Key hierarchy

```
 D5 — keys (all Ed25519 unless stated)
 K0 ROOT   2-of-3 tokens (T1 T2 T3), offline, in separate custody      signs: K1, K2, role Env-IDs, trust-root file, revocation epoch
   |-- K1 GRANT   two or three token-resident keys                     signs: grants (threshold depends on class)
   |-- K2 RELEASE one token key, separate from K1                      signs: role code manifests (Notary)
   |-- K3 ENV-ID  one keypair per environment, created inside it       signs: evidence records, nonce challenges, self-measurement (SELF_ATTESTED)
   |-- K6 SENTINEL cosigner key held by Sentinel                       signs: policy-checked cosignature on grants
 K4 VAULT   X25519: private in Witness secret volume; public in Forge
 K5 GENERATION SECRET   32+ random bytes in Forge secret volume only
 K7 RECOVERY   paper/offline shares of the rebuild kit pin and re-root procedure, no live key
 Trust-root file  = list of K0 public keys + thresholds + version + expiry, hashed; the hash is the PIN the human checks
```

Rules. K0 is used only for registration, rotation, revocation and recovery. K1 and K2 are different keys on different token slots so approving a grant is never approving code. K3 private keys are never exported. K4 is exportable software secret material, protected by volume encryption and, in P1, TPM sealing plus PIN (§14). Nothing in this table is created by this phase. The existing registered owner key (`orneur-owner-authority-1`) must have its custody attested, or be rotated to K1 on a token, before any real signing.

## 7. Cryptographically bound short-lived authority (design only; no grant is created)

**Grant body (canonical, versioned, domain-separated).**

| Field | Meaning |
|---|---|
| `domain` | constant tag so a grant signature is never valid as any other message |
| `grant_id`, `template_id`, `class` | unique id; the pre-approved template it instantiates; class V, G, Q, T or K |
| `owner` | key ids and the threshold satisfied |
| `role`, `env_id` | target role and the environment identity key it may be consumed by |
| `challenge` | nonce issued by that role for this session (no trusted clock needed) |
| `environment` | accepted measurement set: manifest hash, OS build, volume ids (SELF_ATTESTED on Mac); TPM policy digest (P1 Witness) |
| `code_sha` | role code manifest hash |
| `policy` | policy document hash and the `incident_epoch` required |
| `dataset`, `model` | corpus ids and digests; candidate model digest or none |
| `operation` | operation name and the digest of its parameters |
| `window` | `not_before`, `not_after`, with a per-class maximum lifetime |
| `limits` | compute hours, spend ceiling, input and output byte caps, number of runs |
| `destination` | allowed recipient keys or medium ids, allowed record types, maximum record size |
| `evidence` | records that must exist before use, records that must be produced, counterparty signatures required |
| `prev_head` | ledger head the consuming role must already hold |
| `cosign` | Sentinel's signature over the grant after it checked template, cool-off, incident state and spend ceilings |

**Classes (parameters are proposals the owner sets at provisioning; none is evidenced).**

| Class | Operations | Signatures | Extra |
|---|---|---|---|
| V verify | Witness verifies a named bundle | 1 token + Sentinel cosign | template only |
| G generate | Forge generates a named corpus | 2 tokens (different tokens, different sessions) + cosign | cool-off proposed 1 hour |
| Q qualify | holdout released to the Qualification Chamber for a model digest | 2 tokens + cosign + independent reviewer attestation | cool-off proposed 24 hours; run count and output bit budget |
| T train or spend | GPU, spend, training | 2 tokens + cosign + reviewer attestation + external spend cap | cool-off proposed 24 hours; requires incident state clear |
| K key or root | rotation, registry, recovery | root 2-of-3 + cosign | cool-off; new paper pin |

The "second party" for a single owner is the same human on a different token and session. That protects against a hijacked session or stolen token; it does **not** protect against the owner. This is stated, not hidden.

**Consumption rules (every failure is fail-closed).** The consuming role checks, in order: signature threshold and key registration; Sentinel cosignature; `domain`; `challenge` equals the role's open challenge; `env_id`; `code_sha` equals its own verified manifest; `policy` and `incident_epoch` not older than the highest epoch seen; `window` against the challenge-relative counter; `limits` representable; `prev_head` equals its ledger head; evidence preconditions present. Then it appends a CONSUMPTION record (two-sided: the counterparty is told or the record is carried on the transfer medium) and only then acts. A grant is single-use: the role journal and the ledger both mark it spent. A role restored from an older image fails the `prev_head` check.

**D4 — authorization flow.**

```
 role shows CHALLENGE n  ----------------------------------------------+
 proposer (daily-driver) writes unsigned request -> media -> CROWN      |
 CROWN: canonical render + template check; digest d shown               |
 owner compares d with the digest the ROLE displays (dual display) <-----+
 owner: PIN + touch tokens (class threshold, time-separated)
 CROWN -> SENTINEL (policy, clock, incident state) -> cosignature
 LEDGER: publish grant record FIRST, then deliver to role by media
 ROLE verifies (§7 order) -> CONSUMPTION record -> acts within limits
 ROLE emits RESULT_HASH + evidence -> counterparty countersigns -> anchor
```

## 8. Controlled transfer

Forge to Witness is a sovereign boundary crossed in one direction; only a small evidence record returns.

1. Forge writes an authenticated-encrypted bundle plus a signed manifest, and a Forge evidence record signed with its K3, onto medium **M1**, a **raw container with no filesystem** (length-prefixed fixed header, then ciphertext blobs, then digests). M1 is single-use.
2. Forge powers off. M1 is carried to the Witness.
3. **Phase W1, secret volume locked:** a bounded-memory validator reads M1 as raw bytes, checks sizes, headers, digests, the manifest signature and the grant reference, and a second independently written validator repeats the checks. Output is a canonical reduced blob stream written to a quarantine area marked read-only for the next boot.
4. The Witness reboots to its signed baseline (L3). In P1 this is a trivial power cycle of a dedicated machine.
5. **Phase W2, key present:** the owner enters the offline pin, TPM plus PIN unlock the secret volume, and the **minimal verifier** (fixed-format parser, authenticated-decryption check, digest comparison, small enough to review) consumes the reduced stream. Complex parsing never happens with the key present.
6. The Witness writes only an evidence record (result hash, digest list, grant id, status; hard size cap) to **M2** and powers off. No bulk data, no plaintext, no logs leave.
7. M1 and M2 are destroyed or re-initialized; reuse needs a full rewrite.

**D6 — transfer flow.**

```
 FORGE --(bundle, manifest, evidence)--> [M1 raw container]
                                         |
 WITNESS W1 (secret locked): validators A+B -> reduced stream -> quarantine(ro)
 reboot to baseline
 WITNESS W2 (pin + TPM/PIN): minimal verifier -> result
 WITNESS --(<= small evidence record)--> [M2] --> CROWN / LEDGER
```

## 9. Evidence before authority

Record types: REQUEST, AUTHORIZATION, ENV_MEASUREMENT, EXECUTION_START, RESULT_HASH, CONSUMPTION, COUNTERSIGN, ANCHOR, INCIDENT, REVOCATION, RECOVERY. Each record names its actor, grant, previous record hash and sequence.

- **Actor-signed:** the acting role signs with K3.
- **Counterparty-countersigned:** Forge's bundle record is countersigned by the Witness on receipt; a grant record is countersigned by the consuming role on consumption.
- **Externally anchored:** the owner publishes each head to an independent third-party host (public git or equivalent); the Sentinel reads anchors and flags gaps, forks and any owner-key signature not present in the log.
- **Authority depends on evidence:** a new grant carries `prev_head`; a forked or rolled-back role cannot consume it.

Evidence therefore does not depend on one actor: a compromised actor alone cannot produce a countersigned, anchored, continuous history. **Limits:** the external anchoring is detective, because offline roles cannot check an anchor; and the Sentinel's independence is partial while the same owner administers its account (§10 O8).

**D7 — evidence flow.**

```
 ROLE appends record r_n (signed K3, prev=r_{n-1})
   -> counterparty countersigns (receipt on media)
   -> CROWN folds records into ledger head H_n
   -> owner publishes H_n to external host (timestamped by a third party)
   -> SENTINEL: checks continuity, countersigns present, no unlogged owner signature
 next GRANT carries prev_head = H_n; role refuses if its head != H_n
```

## 10. ONE_CONTROL_FAILURE_ASSUMPTION for each sensitive operation

For each operation: the primary control, an independent secondary control from a different trust family, what they share, and the consequence if both fail. Fake independence is called out.

| # | Operation | Primary | Independent secondary | Common-mode failure (and rejected fake independence) | If both fail |
|---|---|---|---|---|---|
| O1 | Mint a grant | token threshold signature (TF-T) | the consuming role shows the digest; the owner compares (TF-H, separate hardware in P1) plus Sentinel cosign (TF-E) | the same human can rubber-stamp; **a token and the same host displaying the request is fake independence** | a wrong but narrow, single-use, expiring grant runs once; recorded in two-sided evidence |
| O2 | Generate a corpus | grant check plus pinned role code (TF-C, TF-H pin) | the Witness verifies structure and digests against the grant independently (TF-S) | the same generator code and the same validator authors | a flawed corpus is accepted; benchmark invalid; regenerate |
| O3 | Transfer ciphertext | authenticated encryption plus signed manifest (TF-C) | key-absent validators A and B plus raw container (TF-S, TF-X) | both validators are Python in the same author's style (**not independent in language**; mitigation: second validator in a different language is a future requirement) | exploit in W1 with the key locked; contained by reboot to baseline |
| O4 | Decrypt and verify | volume passphrase plus, in P1, TPM measured-boot sealing with PIN (TF-H, TF-P) | owner pin check of the trust root and network off (TF-H, TF-X) | Witness kernel compromised after unlock | Witness key exposed: corpus confidentiality lost; regenerate under new keys |
| O5 | Release holdout to Qualification | Class Q grant bound to model digest | chamber has no network, bounded output, run budget (TF-X) | untrusted model code uses output as a covert channel | holdout partly leaked up to the output bit budget; new holdout version |
| O6 | Authorize training or spend | Class T grant (tokens + reviewer) | provider-side spend cap and external alarm (TF-E, TF-V) | owner decision error; same account recovering both | bounded unauthorized spend |
| O7 | Rotate or revoke keys | root threshold signature (TF-T) | epoch bump plus new paper pin plus external anchor (TF-H, TF-E) | loss of at least threshold tokens and the paper | re-root from scratch: new pin, re-provision roles |
| O8 | Record evidence | actor signature (TF-C) | counterparty countersign plus external anchor (TF-E) | **the Sentinel and the anchor share the owner's account**: not independent unless separate accounts with their own hardware tokens | history rewrite possible until compared with role-held copies |
| O9 | Rebuild a role | rebuild kit with threshold-signed manifest | independent rebuild digest equality (TF-S) and pin (TF-H) | **both builders pull the same upstream dependency: fake independence** | rebuilt role compromised from the start; detected only by evidence cross-checks |
| O10 | Release role code | threshold-signed manifest (TF-T) | two builders reproduce the same digest (TF-S) | same upstream wheels or sources | malicious code released; contained by key-absent phases and grants |

## 11. Compromise recovery per role (primary property)

For each role: detect, contain, revoke, preserve evidence, rebuild, prevent contaminated state, resume.

| Role | Detect | Contain | Revoke | Evidence that survives | Rebuild | Prevent return | Resume only after |
|---|---|---|---|---|---|---|---|
| Crown / token loss | unlogged grant signature (Sentinel); loss report; pin mismatch at boot | raise incident epoch with the remaining root tokens; Sentinel stops cosigning | lost key ids, bump epoch | anchored heads, role-held copies | new Crown image from kit; new tokens and keys; root rotation | grants signed since T0 are void; artifacts made under them tainted | Class K re-root, new pin, Sentinel and owner incident-clear |
| Forge | Witness mismatch vs grant; gate fail; countersign mismatch | power off; remove Forge media | Forge Env-ID and generation secret | ledger, M1 copies kept sealed | new Forge image; new Env-ID; new corpus secret | lineage taint: Witness refuses artifacts from the tainted Env-ID after T0 | new grant under new epoch and re-verified artifacts |
| Witness (highest severity) | seal or PIN failure, pin mismatch, canary alert, unexpected evidence | power off; isolate drive; no network exists to cut | Witness key (assume every corpus it could decrypt is exposed) | ledger, anchored heads, M2 copies | rebuild host; re-enroll TPM; new X25519 keypair | corpora decryptable by the old key marked confidentiality-lost; models scored on them flagged | new corpus version, new freeze, new Witness key |
| Vault / Reliquary | digest mismatch vs ledger | quarantine media | none (ciphertext only) | ledger digests | restore from other copy | restored copy verified by the keyed check | verification pass |
| Qualification Chamber | output or resource anomaly | kill; revoke Class Q grant | grant, model digest | evidence, run counters | fresh chamber image | exposure budget consumed; holdout retired if exceeded | new holdout version if needed |
| Transfer (medium) | validator failure | destroy medium | none | evidence of the attempt | new medium | none needed (key-absent) | clean rerun |
| Evidence Ledger | fork, gap, anchor mismatch | freeze new grants (they cannot carry a consistent `prev_head`) | none | externally anchored heads, counterparty copies | reconcile from anchors and countersigned records | records without counterparty or anchor are marked unwitnessed | Class K reconciliation grant |
| Sentinel | owner dead-man alarm on separate channel; silence | grants cannot be cosigned: fail-closed | Sentinel key in trust root | public logs it read | new account, new key | none | trust root updated by Class K |
| Release Notary / builder | two-builder digest mismatch | freeze releases | manifest key | build logs, digests | rebuild from vendored sources | artifacts from the bad manifest tainted | new manifest, threshold-signed |

**D8 — compromise containment (any role).**

```
 DETECT -> POWER OFF / ISOLATE -> BUMP incident_epoch (old grants die everywhere)
        -> REVOKE keys in registry -> FREEZE: no Class Q/T grants while incident open
        -> PRESERVE: seal media, collect anchored heads + counterparty copies
        -> TAINT: ledger marks (env_id, T0 .. now) ; consumers refuse tainted lineage
```

**D9 — recovery.**

```
 QUARANTINED -> forensic copy (read-only, offline)
             -> REBUILD from signed kit (two-builder digest equal) on clean media
             -> human pin check of trust root
             -> new Env-ID registered by Crown (new epoch)
             -> re-verify any needed artifact under the new epoch (clean Witness)
             -> Sentinel + owner INCIDENT-CLEAR record
             -> PROVISIONED_CLEAN ; new grants allowed
```

## 12. Role lifecycle state model

**D10 — states and guards.**

```
 UNPROVISIONED --provision from kit + pin check--> PROVISIONED_CLEAN
 PROVISIONED_CLEAN --challenge issued; grant verified (§7)--> ARMED
 ARMED --gate start passes (network off, baseline, pin)--> ACTIVE
 ACTIVE --gate end passes; evidence emitted--> CLOSING
 CLOSING --secrets locked; outputs staged; power off--> SEALED
 SEALED --next phase: baseline restored--> PROVISIONED_CLEAN
 any state --anomaly / incident epoch raised--> QUARANTINED --rebuild--> PROVISIONED_CLEAN
 any state --retire--> RETIRED   (keys revoked, media destroyed)
 guards: a grant for one phase never moves a role through another phase;
         ACTIVE never persists across a power cycle.
```

## 13. Realization profiles and what each can implement

| Profile | Shape | Hardware families |
|---|---|---|
| **P0** | one Apple-silicon Mac: Crown, Forge and Witness as three sequential external boot environments; daily-driver internal propose-only | TF-A only (plus tokens, human, physical) |
| **P1** | the Mac hosts Crown and Forge environments; the Witness is a dedicated TPM PC running a minimal Linux, never networked after provisioning | TF-A and TF-P |
| **P2** | adds cloud or on-premises GPU confidential computing for Qualification and training, with attested key release | adds TF-V |

| Mechanism | P0 | P1 | P2 |
|---|---|---|---|
| M1 M2 token authority, thresholds | YES | YES | YES |
| M3 time-separated second signature | YES | YES | YES |
| M4 M5 bound, challenge-bound grants | YES | YES | YES |
| M6 head binding, M7 epoch | YES | YES | YES |
| M8 external policy cosigner | YES | YES | YES |
| M9 offline pin check by a human | YES | YES | YES |
| M10 dual display path | PARTIAL (same machine, same screen, different environment) | YES (independent hardware) | YES |
| M11 M12 key-absent ingest, raw container | YES | YES | YES |
| M25 minimal key-present verifier | YES (needs implementation) | YES | YES |
| M13 evidence-only return path | YES | YES | YES |
| M14 M15 two-sided, externally anchored evidence | YES | YES | YES |
| M16 ephemeral mutable state | PARTIAL (mechanism unverified on macOS) | YES on the Witness (read-only image, volatile state) | YES |
| M17 reproducible two-builder release | YES | YES | YES |
| M18 TPM-sealed Witness unlock with PIN | **NOT POSSIBLE** | YES | YES |
| M19 platform diversity (Apple vs PC) | **NOT POSSIBLE** | YES | YES |
| M20 lineage taint epoch | YES | YES | YES |
| M22 router network canary | PARTIAL | YES | YES |
| Physical separation of the Witness key host from authority and generation | **NOT POSSIBLE** (shared internal drive, firmware, Secure Enclave) | YES | YES |
| Attested confidential-compute key release for Qualification/training | NOT POSSIBLE | NOT POSSIBLE | FUTURE |

**Answers to requirement 2.**
- *Can Tier0-S (P0) implement the strongest architecture?* **No.** It can implement the authority, grant, evidence, transfer-protocol and recovery layers. It cannot provide independent platform roots, TPM-sealed key release or an independent display path, and it leaves the Witness key host sharing hardware with Crown and Forge.
- *Only part?* **Yes**, the subset marked YES or PARTIAL under P0.
- *Is Tier0-A required?* The **P1 minimum** (a dedicated second machine for the Witness only) gives the properties P0 lacks. A symmetric two-machine Tier0-A is not required beyond that.
- *Additional hardware?* P1 needs one more machine with TPM 2.0 and no radios (or radios removable). P0 needs three external boot SSDs. Tokens and transfer media are needed in both. No price was researched.
- *Later tier?* Qualification and training on GPUs, attested key release, and the Qualification Chamber belong to P2.

## 14. Boot-bound trust: what exists, what does not

| Capability | Mac (P0 environments, P1 Forge and Crown) | TPM PC (P1 Witness) |
|---|---|---|
| Hardware root of trust for boot | YES: Boot ROM, signed boot, LocalPolicy with anti-replay (S2) | YES: UEFI Secure Boot, TPM measured boot |
| Keys bound to the booted OS | partly: OS-bound keys exist for system data protection (S2); not established for ORNEUR's own keys | YES: TPM2 PCR policy plus PIN (S18) |
| Owner-verifiable measurement of an externally booted OS | **not found** | YES: quote verifiable against the registered TPM |
| Remote or third-party attestation | requires management infrastructure and attests device properties only (S3) | not needed offline; local verification |
| Signed role manifests | YES (software, hash plus signature) | YES |
| Immutable or write-separated role code | PARTIAL: sealed system volume is read-only; the role code must be placed on a read-only volume or medium | YES: read-only image, verity-style |
| Binding of environment state to authorization | SELF_ATTESTED only | grants name the TPM policy digest; unlock requires matching state |

**Classification.** On the Mac, boot-bound trust is **FUTURE ARCHITECTURE**, not an implemented control. The design never counts a Mac self-measurement as attestation (L8). In P1, TPM sealing for the Witness is a feasible, standard control, **not yet verified on any chosen hardware**.

## 15. Rationality of advanced Tier0-S and the recommendation on Decision 9

What the advanced design adds to Tier0-S (Crown separation, diversity, grants, anchored evidence, two-phase Witness) increases the number of boot environments to three and the cold boots per corpus cycle to about five (Crown, Forge, Witness phase W1, Witness phase W2, Crown). The strongest properties the directive asks for are exactly the ones P0 cannot supply.

| Question | P0 (Tier0-S advanced) | P1 (second machine for the Witness) |
|---|---|---|
| Environments to maintain | 3 boot environments, 3 external SSDs, 2 media | 2 Mac environments plus 1 dedicated machine |
| Cold boots per corpus cycle | about 5 sequential | 3 on the Mac (Crown, Forge, Crown); the Witness runs on its own machine, including its own reboot |
| Platform families | 1 | 2 |
| Witness key host shares hardware with authority and generation | yes | no |
| Owner-verifiable boot measurement for the key host | no | yes (TPM) |
| Independent display path for approval | no | yes |
| Operator error surface | high: repeated environment switching | lower |
| Cost | unpriced; three SSDs, media, tokens | unpriced; one machine plus SSDs, media, tokens |

The price comparison was **not researched**. The repository's earlier estimate for a minimal second machine was $150 to $500; a hardware set for P0 was never priced. They are probably the same order of magnitude, which makes the extra machine a better use of the same money for the properties above. This is a judgment from the table, not a measured fact.

**Recommendation: reopen Decision 9.** Replace "accept Tier0-S as the target" with a choice between P1 (preferred target) and P0 (explicit fallback with the reductions in §13 accepted in writing). The advanced architecture does not make Tier0-S useless: P0 still implements the authority, evidence, transfer and recovery layers well beyond today's state. But as a *target*, it is less rational than a second machine once the diversity requirement is binding. No purchase is authorized or implied.

## 16. Governance scaling for the future ORNEUR ecosystem (surprising in capability, predictable in trust)

Two planes. The **capability plane** (models, agents, tools, memory) can only *request*. The **authority plane** (Crown, grants, Sentinel, ledger) decides. No capability-plane component holds ambient authority.

| Future capability | New governance required before it ships |
|---|---|
| Autonomous multi-step agents and long-running workflows | each external effect needs a scoped, expiring grant; a standing budget is a grant with a ceiling and renewal, never a permanent right |
| Coding and tool use | actions run in disposable compartments with egress limits; code that touches secrets is manifest-signed |
| Financial or irreversible actions | Class T-like grants with human approval on an independent presentation surface and a provider-side cap |
| Data disclosure and enterprise access | destination-bound grants; per-tenant keys; disclosure records two-sided |
| Memory and personalization | stored under owner keys; deletion and export are grants; no cross-tenant lineage |
| Training and inference infrastructure | P2 attested key release; lineage taint; incident state clear before training |
| More capability | a distinct grant class, an evidence type, a revocation path, a recovery path and a user-visible trust boundary, or it does not ship |

Capability may feel unlimited; each new authority is narrower, shorter-lived and more evidenced than the last.

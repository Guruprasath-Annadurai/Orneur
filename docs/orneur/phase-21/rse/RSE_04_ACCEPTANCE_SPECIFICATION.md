# RSE-04 — Real Secure Environment acceptance specification

This specification is **defined now and not executed.** It exists so a later audit can tell apart six states that are routinely confused. Nothing here authorizes provisioning, purchases, secrets, a corpus, Qualification, a model, a GPU or training.

## 1. The maturity ladder

A control is at the highest level whose evidence is complete and current. Levels cannot be skipped. Evidence for a lower level never counts for a higher one.

| Level | Meaning | Evidence required (all of it) |
|---|---|---|
| **DESIGNED** | the control is specified and reviewed | a written specification in this package; an independent review recorded; the claim class (ENFORCED, ADVISORY, PROCEDURAL, UNPROVEN) stated |
| **IMPLEMENTED** | code, configuration or procedure text exists and passes synthetic tests | repository commit; automated tests including negative tests; exact-SHA CI; no real secret or real environment involved |
| **PROVISIONED** | the control exists in the real environment | an owner-attested provisioning record; inventory of the actual hardware, volumes, tokens and software with digests; an independent observer's confirmation that what exists matches the specification; no claim that it works |
| **TESTED** | the control works in the real environment | executed positive and negative tests with recorded inputs and outputs; at least one deliberate failure injection per control showing it fails closed; evidence bundles hashed into the ledger; results reproducible by someone other than the person who ran them |
| **ADVERSARIALLY_VERIFIED** | an independent attacker could not defeat it within the stated adversary | an independent adversarial exercise against the real environment; written attack log; every success classified; no unresolved fail-open of MEDIUM or higher; unresolved items match the declared list in `RSE_03` §3 |
| **ACCEPTANCE_COMPLETE** | the environment as a whole is accepted | every control required for the profile is ADVERSARIALLY_VERIFIED; all evidence is current (§3); the owner's signed acceptance; an independent audit verdict; authorization states unchanged until separate approvals |

`REAL_SECURE_ENVIRONMENT = 100% acceptance-complete` means ACCEPTANCE_COMPLETE for every control required by the chosen profile, and nothing less. A profile-specific control that is unneeded in a profile is recorded as `NOT_APPLICABLE` with the reason, never silently omitted.

## 2. Rules that keep the ladder honest

1. **No self-certification.** TESTED evidence may be produced by the builder; ADVERSARIALLY_VERIFIED and ACCEPTANCE_COMPLETE evidence may not.
2. **Negative tests are mandatory** at TESTED and above: a control that has only been shown to allow what it should is not tested.
3. **SELF_ATTESTED never counts as attested.** A measurement the environment reports about itself is configuration evidence, not integrity evidence.
4. **Freshness.** Evidence expires on the earliest of: a change to any measured component (hardware, firmware, OS image, role code, trust root, token set), a change of incident epoch, or a time limit the owner sets at provisioning. Expired evidence returns the control to the highest level still supported.
5. **Reset on incident.** Any incident that touches a role returns that role's controls to PROVISIONED until retested.
6. **Existing software is not credit for the environment.** The software gate, the transfer validator, the encrypted store and the registries are IMPLEMENTED only in the synthetic sense; they earn no PROVISIONED or higher credit until run in the real environment.
7. **Authorizations do not move.** Reaching any level changes no authorization flag.

## 3. Control register

"Now" is the current honest level. Existing repository components are IMPLEMENTED in the synthetic sense; everything else is DESIGNED.

| ID | Control | Profiles | Evidence that earns TESTED (positive and negative) | Adversarial focus | Now |
|---|---|---|---|---|---|
| C01 | Token custody of K0, K1, K2 with attested key generation | P0 P1 | each key generated on a token; attestation chain verified; a software export attempt fails | token theft with PIN, touch hijack | DESIGNED |
| C02 | Root and class thresholds with time separation | P0 P1 | a single token cannot satisfy a class G, Q, T or K grant; a grant signed inside the cool-off is rejected | stolen token plus session hijack | DESIGNED |
| C03 | Human entry of the trust-root pin from an offline copy | P0 P1 | environment refuses to arm with a wrong pin; replacing manifest and pin together is detected | substitution of both | DESIGNED |
| C04 | Crown environment: offline, no agents, no sync | P0 P1 | environment inventory shows none; network attempts fail | compromised Forge persistence into Crown | DESIGNED |
| C05 | Tokens never inserted outside Crown | P0 P1 | procedure log and a test that other environments show no token device | host requesting signatures | DESIGNED (PROCEDURAL) |
| C06 | Canonical grant renderer and template conformance | P0 P1 | grants outside a template are refused; renderer output is deterministic | presentation tampering | DESIGNED |
| C07 | Dual display digest comparison | P0 (partial) P1 | wrong digest on the role display is caught in a drill | both displays controlled | DESIGNED |
| C08 | Grant consumption checks (§7 order) | P0 P1 | each rejected case fails closed: wrong role, env, code, epoch, window, limits, destination, head | malformed or boundary values | DESIGNED |
| C09 | Challenge issuance per session | P0 P1 | a grant for another session is refused | replay | DESIGNED |
| C10 | Single-use journal plus ledger CONSUMPTION | P0 P1 | second use fails; restored older image fails the head check | rollback | DESIGNED |
| C11 | `prev_head` binding | P0 P1 | forked or rolled-back role cannot consume a new grant | evidence fork | DESIGNED |
| C12 | Incident epoch revocation | P0 P1 | raising the epoch kills all older grants in every role | stale authority | DESIGNED |
| C13 | Sentinel cosigner and monitor in separate accounts | P0 P1 | silence blocks grants; an unlogged owner signature raises an alert | shared-account compromise | DESIGNED |
| C14 | Two-sided evidence records | P0 P1 | a record missing a counterparty countersignature is flagged unwitnessed | single-actor forgery | DESIGNED (ledger code IMPLEMENTED synthetic) |
| C15 | External anchoring of heads | P0 P1 | heads appear at the external host; Sentinel detects a withheld anchor | withholding | DESIGNED |
| C16 | Forge environment: no decryption key, offline | P0 P1 | no private key material present; no network | Forge-to-Crown pivot | DESIGNED |
| C17 | Witness key host: P1 TPM-sealed unlock with PIN; P0 encrypted secret volume | P0 P1 | unlock fails after any boot-chain change; lockout behavior observed | cold-boot and offline attack | DESIGNED |
| C18 | Raw-container transfer medium, single use | P0 P1 | medium without filesystem is accepted; any filesystem or oversize is refused | parser attack | DESIGNED (validator IMPLEMENTED synthetic) |
| C19 | Key-absent validators A and B | P0 P1 | secret volume locked throughout W1; the two validators agree on a corpus of malformed inputs | exploit in W1 | DESIGNED |
| C20 | Minimal key-present verifier | P0 P1 | fixed-format only; fuzzed with malformed headers | exploit at unlock | DESIGNED |
| C21 | Evidence-only, size-capped return medium | P0 P1 | record over the cap is refused; no bulk or plaintext leaves | covert channel through the record | DESIGNED |
| C22 | Ephemeral mutable state restored to baseline | P0 (partial) P1 | planted file in mutable state is gone after restore; mechanism proven on the real OS | persistence | DESIGNED (macOS mechanism unverified) |
| C23 | Read-only or write-separated role code | P0 (partial) P1 | role process cannot modify its code; code hash matches the signed manifest | tamper | DESIGNED |
| C24 | Reproducible two-builder release and threshold-signed manifest | P0 P1 | two builders produce identical digests; a one-bit change is caught | shared upstream | DESIGNED |
| C25 | Network posture: off in secret phases, canary at the router | P0 P1 | interfaces down; canary alert on a test frame | radio re-enable | DESIGNED |
| C26 | Software phase gate at phase start and end | P0 P1 | gate run from an Apple-signed or P1 equivalent lineage; start and end results recorded | one-shot limits | DESIGNED (gate IMPLEMENTED synthetic, accepted as software) |
| C27 | Storage controls: Time Machine, Spotlight, swap, history, crash dumps, clipboard, snapshots, sync | P0 P1 | each channel inspected before and after a phase; none holds plaintext | leftover state | DESIGNED |
| C28 | Lineage taint and quarantine | P0 P1 | a tainted artifact is refused by the Witness; clean re-verification restores it | silent re-entry | DESIGNED |
| C29 | Rebuild kit and recovery drill | P0 P1 | each role rebuilt from the kit with identical digests | recovery poisoning | DESIGNED |
| C30 | Reliquary offline copies and restore drill | P0 P1 | restore verified by the keyed check; copies physically separate | media loss | DESIGNED |
| C31 | Incident drills for each of the nine roles | P0 P1 | each drill walks detect, contain, revoke, preserve, rebuild, taint, resume with recorded timing | untested recovery | DESIGNED |
| C32 | Key rotation drill | P0 P1 | rotation completed; old key rejected | stale key | DESIGNED |
| C33 | Lost-token and break-glass drill | P0 P1 | re-rooting from scratch exercised | total loss | DESIGNED |
| C34 | Platform diversity: Witness on a second platform family | P1 | Witness hardware inventory differs from the Mac in firmware, OS and boot chain | common-mode vulnerability | DESIGNED |
| C35 | Daily-driver prohibition | P0 P1 | no Crown or role function present on the daily-driver; token never seen by it | host abuse | DESIGNED (PROCEDURAL) |
| C36 | Qualification Chamber with attested key release | P2 | out of scope until P2 | covert channel | DESIGNED only (FUTURE) |
| C37 | Provider-side spend caps and alarms | P2 | out of scope until P2 | runaway spend | DESIGNED only (FUTURE) |
| C38 | Independent adversarial audit of the real environment | P0 P1 | auditor not involved in the build; attack log published | all | NOT STARTED |

## 4. Required end state, by profile

- **P0:** C01–C33, C35, C38 at ADVERSARIALLY_VERIFIED, with the PARTIAL items (C07, C22, C23) listed in the acceptance record as the weaker form actually accepted. C34 is NOT_APPLICABLE and recorded as a **permanent profile limitation**, not a pass.
- **P1:** C01–C35, C38 at ADVERSARIALLY_VERIFIED.
- **P2:** all of P1 plus C36 and C37, and a new attack round on the cloud path.

## 5. What acceptance does not mean

It does not authorize a corpus, a key, a model, a GPU, a purchase, spending, Qualification, training or any production use. It is evidence about an environment. Each of those needs its own explicit approval, issued as a grant under this architecture once it exists.

## 6. Order of work implied by this specification (for planning only)

1. Independent audit of RSE-ARCH-1.0 and the Decision 9 reopening choice.
2. Owner decision on profile (P1 or P0), recorded.
3. Separately authorized hardware and provisioning phase.
4. IMPLEMENTED level for the missing software (renderer, grant verifier, minimal verifier, second validator, anchoring tools).
5. PROVISIONED, then TESTED, then adversarial verification, then acceptance.

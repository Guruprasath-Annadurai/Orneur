# Genesis V2 — Tier0-S acceptance status (separate from the Tier0-A / Tier0-B table)

Statuses: `PROVEN_SYNTHETIC_ONLY` · `PARTIAL` · `NOT_YET_PROVEN` · `OWNER_ACTION_REQUIRED` · `UNACCEPTABLE`. **`PROVEN_REAL` is not used in this design phase.** No second boot environment exists, so nothing that needs one is claimed. Decision gate: `TIER0_S_REDUCED_ASSURANCE_ONLY`.

## A. Synthetic validation checks
| # | Check | Status | Basis |
|---|---|---|---|
| 1 | Forge environment holds only public key + synthetic generation secret | `PARTIAL` | Gate rejects forbidden file names in a role state dir; per-container evidence exists only for the (different) Tier0-B topology. No Tier0-S environment exists. |
| 2 | Witness environment holds only the private key | `PARTIAL` | Same. |
| 3 | Forge cannot decrypt | `PROVEN_SYNTHETIC_ONLY` | Topology-independent cryptographic property (writer holds no private key); existing store/Tier-0 tests. |
| 4 | Witness decrypts | `PROVEN_SYNTHETIC_ONLY` | Existing store and Tier-0 tests. |
| 5 | Wrong key fails | `PROVEN_SYNTHETIC_ONLY` | Same. |
| 6 | Transfer validator passes valid ciphertext | `PROVEN_SYNTHETIC_ONLY` | `tests/test_genesis_v2_tier0a_transfer_bundle.py`. |
| 7 | Plaintext transfer rejected | `PROVEN_SYNTHETIC_ONLY` | Same. |
| 8 | Extra / secret-shaped files rejected | `PROVEN_SYNTHETIC_ONLY` | Same. |
| 9 | Forge cannot see Witness secret store in its phase | `NOT_YET_PROVEN` | Needs two real environments. |
| 10 | Witness cannot see Forge secret store in its phase | `NOT_YET_PROVEN` | Same. |
| 11 | Full shutdown/reboot required between phases | `PARTIAL` | Gate's boot-session receipt logic tested synthetically; no real reboot exercised; enforced only by software on the guarded machine. |
| 12 | No shared container daemon survives between roles | `PARTIAL` | Gate detects a live daemon (fails on this host today); no cross-phase run. |
| 13 | No role secret in a common mounted filesystem | `NOT_YET_PROVEN` | Needs provisioned storage. |
| 14 | Network disabled independently per phase | `NOT_YET_PROVEN` | Gate checks it; this host currently fails it; no per-phase run. |
| 15 | Qualification modules absent | `PARTIAL` | Gate checks; Tier-0 role images omit them; the full repo (daily-driver) contains them. |
| 16 | Owner private key absent from both | `PARTIAL` | Name-pattern check only; no real key exists. |
| 17 | No plaintext remains on transfer storage | `PARTIAL` | Validator rejects plaintext content in a bundle; erasure of real media not exercised. |
| 18 | No secret-shaped data in logs | `NOT_YET_PROVEN` | Requires an actual phase. |
| 19 | Teardown scoped | `PARTIAL` | Tier0-B scoped teardown only; none for Tier0-S. |
| 20 | Protected benchmark untouched | `PROVEN_SYNTHETIC_ONLY` | Inventory/signing-payload diff empty; no benchmark content read. (Item 20 provenance on the main acceptance table stays `PARTIAL`.) |
| 21 | Persistence channels inspected | `PARTIAL` | Read-only inspection of this host + classification in the design doc; not a proof. |
| 22 | Surviving shared state documented | `PARTIAL` | Documented; unverified on provisioned environments. |

## B. Required invariants
| # | Invariant | Status | Basis |
|---|---|---|---|
| 1 | Forge and Witness never simultaneously running | `PARTIAL` | Software gate + procedure; bypassable by root. |
| 2 | Forge cannot mount/decrypt Witness secret storage | `NOT_YET_PROVEN` | Needs separately encrypted environments. |
| 3 | Witness cannot mount/decrypt Forge secret storage | `NOT_YET_PROVEN` | Same. |
| 4 | No shared active Docker daemon across phases | `PARTIAL` | Gate check; this host fails it today. |
| 5 | No shared active secret manager | `PARTIAL` | Design rule; unverified. |
| 6 | No automatic cloud-sync path between role secrets | `UNACCEPTABLE` | On the current daily-driver: sync processes and an iCloud container exist. Acceptable only in a dedicated environment. |
| 7 | No owner private key in either environment | `PARTIAL` | None exists; name-pattern gate check. |
| 8 | Ciphertext transfer explicit and auditable | `PARTIAL` | Validator + receipts; not exercised across boots. |
| 9 | Plaintext never crosses environments | `PARTIAL` | Validator rejects plaintext; plaintext handling inside Forge unproven. |
| 10 | Qualification unavailable | `PARTIAL` | See check 15. |
| 11 | Both environments can run with networking disabled | `NOT_YET_PROVEN` | Needs the environments. |
| 12 | Secret storage separately encrypted | `OWNER_ACTION_REQUIRED` | Requires owner provisioning of dedicated encrypted storage. |
| 13 | Transition requires full shutdown/reboot | `PARTIAL` | Gate receipts; see check 11. |
| 14 | Cross-environment persistence risk assessed | `PARTIAL` | Assessed; two channels `UNCONTROLLED` on the daily-driver. |
| 15 | No real secrets created | `PROVEN_SYNTHETIC_ONLY` | None created in this phase. |

Summary: no check or invariant is `PROVEN_REAL`; one invariant is `UNACCEPTABLE` on the current daily-driver environment; Tier0-S is **not provisioned** and **not accepted**.

# RSE-ARCH-1.2 — Part 5: Qualification, weight custody, recovery, supply chain, network verification

Architecture only. Future items (Qualification, T/W/D, P2) are design-complete here so later work needs no redesign, but none is authorized or implemented.

## 1. Qualification Chamber completion (L)

Qualification produces **evidence**, never authorization; it has no signing authority and no authority to start training.

| Rule | Specification |
|---|---|
| Output quantization | The chamber emits only: an integer percentage **rounded to the nearest 5 points**, or a band label (e.g. below / within / above a pre-registered threshold), or a Boolean. No per-item result, no item identifier, no ranking, no raw count below a band. |
| Information budget | Each holdout set entry (`HOLDOUT_SET`, `RSE12_01` §2) declares `bit_budget_total` and `query_budget_total`. Every output costs its information content (Boolean = 1 bit; a 5-point score with 21 values ≈ 4.4 bits; band of 3 ≈ 1.6 bits). The chamber keeps a cumulative counter per holdout set and refuses once the budget is spent; an exhausted holdout is retired (class R) and replaced. Choose `bit_budget_total` far below the holdout's entropy, so repeated queries cannot reconstruct it. |
| Authorization | Every Qualification run and every oracle query series needs a class-Q grant naming the holdout set and candidate; the grant's `query_budget` and `bit_budget` are ≤ the remaining set budget and ≤ POLICY caps. There is no ungranted query. |
| Run budget | `run_budget` in the grant, enforced by the chamber (count of candidate evaluations). |
| Rate limit | Minimum interval between queries (monotonic timer) and a maximum count per grant. |
| Contamination oracle | Answers a **set-level** Boolean ("is contamination between this candidate corpus and this holdout set above the pre-registered threshold?"). It never returns item-level matches and **never emits hashes of low-entropy questions** (they would be dictionary-attackable). |
| Abuse detection | The chamber flags (and freezes the oracle on) query patterns that bisect a threshold: successive queries whose candidate corpora differ by a small, controlled edit; an unusual rate; repeated near-identical grants. A freeze raises an incident for the owner. |
| Logging | Every query appends a record (grant ID, holdout set, query index, bit cost, result bucket) to the chamber log; the log is checkpointed and witnessed like any role log. |
| Isolation | Holdout key present only inside the chamber; holdout material only in RAM; candidate weights read-only; no training write path; no network; no swap or core dumps; no operator access to items. |
| Counter integrity | The budget counters must not be rollbackable (a restored chamber state would refund budget): they need a hardware or provider monotonic reference. This is a **P2 requirement**; until then it is `UNPROVEN` and Qualification stays unauthorized. |

## 2. Model-weight custody lifecycle (Z)

Columns abbreviated: Rd = who reads, Wr = who writes, Key, Grant, Evidence/Checkpoint, Recovery, Revocation.

| Stage | Artifact (registry entry) | Rd | Wr | Key | Grant | Evidence / checkpoint | Recovery | Revocation |
|---|---|---|---|---|---|---|---|---|
| 1 Foundation weights | FOUNDATION_MODEL (digest, license, architecture, tokenizer) | approval host (inspection) ; trainer later | importer into quarantine | none until imported; then archive key | none (approval is a registry update) | provenance record + approval checkpoint | re-acquire and re-verify | REVOKED state + class R |
| 2 Approved training input (foundation + corpus + tokenizer) | CORPUS + FOUNDATION + TOKENIZER entries | trainer (P2) | — | per-run key | **T** | grant checkpoint | rerun | R / epoch |
| 3 Training checkpoints | MODEL entries, state candidate | trainer | trainer | per-run key; encrypted at rest | within T ceilings | periodic checkpoint records | resume from last verified checkpoint | R |
| 4 Candidate final weights | MODEL (candidate) | trainer, Qualification | trainer | archive key | within T | completion record (never an authorization) | Reliquary copy | R |
| 5 Qualification candidate | MODEL (candidate) read-only in chamber | chamber | none | chamber key | **Q** | evidence record (bounded outputs) | rerun | R |
| 6 Accepted weights | MODEL (accepted) + `qualification_record_digest` | custodian environment | owner-confirmed registry update only | archive key | owner registry update (dual token, M1∧M2) | acceptance checkpoint | Reliquary copy | R |
| 7 Exported weights | MODEL (exported) | named recipient only | exporter inside the attested environment | export encryption recipient key | **W** (export only) | W consumption + export record | re-export under new W | R, key rotation of the recipient |
| 8 Deployment artifact | MODEL (deployed), serving environment, policy | serving environment | release process | serving keys | **D** | D consumption + release record | rollback to prior release under new D | R + revocation endpoint |
| 9 Retired weights | MODEL (retired) | none | none | crypto-erase of keys | **R** | revocation record | none by design | permanent |

Hard separation: **training PASS ≠ export authorization**; **W ≠ D**. A W grant requires an accepted MODEL entry whose `qualification_record_digest` it binds; a D grant requires an exported or accepted MODEL entry and a different, explicit confirmation. A model with a different digest is a different entry and needs new Qualification, W and D.

**P2 requirement (future HIGH, blocks training authorization, not architecture freeze):** a compromised training environment that holds plaintext weights could exfiltrate them over any available egress path. Before any training, the training environment must be attested, have no egress except an exporter that only the W grant can open, and be tested for that. Until then the property is `UNPROVEN`.

## 3. Corpus custody (Y) — changes from 1.1

The 1.1 lifecycle table stands, with these corrections: every stage's grant and evidence cells name registry entries, not free strings; a corpus becomes `WITNESSED_ACCEPTED` only after its acceptance record's checkpoint is cosigned (`RSE12_02` §4); the G grant names `corpus_entry_id` and `source_provenance_digest`, so a generator cannot choose its own manifest.

## 4. Recovery (P, AB)

### 4.1 Contents of recovery material and what theft costs

| Item | Secret? | Stolen alone | Response |
|---|---|---|---|
| Rebuild kit (signed images/tools) | no | nothing | none; kit generation must be ≥ floor |
| Owner Floor Card copy | no (integrity matters) | attacker may *replace* a card with a lower one | tamper-evident envelope, two copies compared at each update, effective floor takes the max with other inputs |
| LUKS recovery passphrase (paper) | **yes** | useless without the disk | rotate the LUKS key slot under a K grant; raise epoch |
| Disk **and** recovery passphrase | | **vault readable** | declared residual; treat as incident: epoch raise, corpus-secret rotation |
| Archive key + Reliquary encrypted copy | **yes** | corpus readable if both are taken | keep them in different locations; if both lost, incident and epoch raise |
| Second token | **yes (signing)** | one signature of two | revoke via K; the PIN/touch protect it |
| Whole kit | | each item as above; **no item alone produces a K grant** (needs two tokens) | |

Recovery material is **not** a universal bypass: starting recovery needs a class-K grant signed by two tokens, which paper cannot produce; theft of the passphrase triggers an epoch raise.

### 4.2 Version floor in recovery

**No recovery artifact may silently restore an old trust root, old incident epoch, revoked grant, deprecated role image or obsolete policy below the current independently held minimum.** Enforcement: the effective floor is `max(Owner Floor Card, Crown sealed floor, last witnessed floors, Witness fence generation)`. Crown refuses to sign a K grant whose listed artifacts are below that floor; the rebuilt role independently refuses the same. Kits carry a `recovery_kit_min_generation`; kits below the card's generation are invalid and are destroyed when the card is raised.

### 4.3 Re-root ceremony and clean-Crown bootstrap

The initial **Genesis** ceremony is `RSE12_01` §5 (separate from recovery). **Re-root after loss** reuses the same evidence classes rather than a circular "trust the Crown that is recovering Crown": (0) boot every surviving role into MAINTENANCE and **void its outstanding challenge** (an offline role does not learn of an incident otherwise, and a stolen pre-signed grant would still match its old challenge); (1) declare incident, freeze roles (QUARANTINED); (2) acquire and **reproduce on two independent hosts** a fresh Crown image and renderer from public source, compare digests to the Owner Root Card if it survives, or establish a **new Owner Root Card** if it does not; (3) create new owner authority version, trust-root version and keys, a new incident epoch, new minimum role versions and a new checkpoint root; (4) publish the new root to M1, M2 and cross-role holders; (5) revoke old roles; old grants die by epoch; (6) re-verify every artifact from independent sources; (7) rebuild and re-enrol roles; (8) re-ingest corpus only after re-verification. The trust anchor of a re-root is the owner's physical ceremony and the two reproductions — it is stated, not hidden.

### 4.4 Other scenarios

The 1.1 recovery table stands (lost Forge storage, Witness drive, TPM/motherboard — now `RSE12_03` §3.2 —, owner token, all tokens, paper checkpoint, ledger service, compromised artifact repository, corpus and weight corruption). Added: **recovery media stolen** (§4.1) and **checkpoint holder lost** (replace via K handover; M2 takes over only after holding M1's last cosigned head).

## 5. Foundation-weight provenance (future controls)

Before any foundation becomes an approved input its FOUNDATION_MODEL entry needs: source and provenance record; exact digest of every file; license text digest and review record; architecture/config digest; tokenizer binding (a TOKENIZER entry); format inspection — prefer weight formats that cannot execute code, reject executable-pickle formats unless converted in a no-network sandbox; static scan results; owner approval (dual token); and a registry entry. Two downloads from the same publisher are one source, not two. **Inherent residual:** a backdoored or poisoned foundation cannot be ruled out by inspection or by a capability check; this is accepted and listed (R-F2). No foundation is selected here.

## 6. Supply chain and approval-host root (X)

| Function | Where | Why |
|---|---|---|
| Acquisition into quarantine | the daily-driver or any untrusted host, **fetch only** | it may be hostile; it holds no signing or comparison authority |
| Review and static inspection | disposable verifier host, wiped after | no standing role |
| Independent builds | **two build hosts** (different hardware, ideally different OS families), each from independently sourced inputs | a single compromised host is then exposed by a digest mismatch |
| Comparison and signing | **Crown**: it compares the two build reports carried on media, and signs the registry update only if the digests are equal | signing keys never leave tokens; the daily-driver is never a root |
| Metadata | registry (versions, min versions, approval states) in TUF-style roles: root/targets/snapshot semantics, with rollback protection from `registry_version` floors | |
| Distribution | read-only medium, offline | |

Compromise detection of an approval host: digest mismatch between independent builds; Crown's refusal; Monitor flags a registry update that no Crown checkpoint covers. Shared upstream source remains a residual (R-B1, R-X1): two builds from one compromised upstream agree. Crown/Forge/Witness application code is built from the repository at a registry-pinned commit digest; the artifact repository is never "the repository that defines Crown" for Crown's own genesis (`RSE12_01` §5).

## 7. Network verification design (T)

Policy: Crown never networked; Forge offline in secret phases; Witness no radios and wired port unused; Monitor-Lite online, holds nothing secret; maintenance state has no network stack. Every link class below needs a test that can later produce objective evidence:

| Link / state | Control | Test (objective evidence) |
|---|---|---|
| Ethernet | no cable in secret phases; port physically blocked or disabled in firmware | netdev list shows no carrier; attach test cable: no link/DHCP; evidence = measured netdev and carrier digest in the role's checkpoint |
| Wi-Fi | radio absent or physically removed (Witness); software disabled and gate-checked (Mac residual) | PCI/USB enumeration contains no wireless device; hard rfkill state recorded |
| Bluetooth | as Wi-Fi | enumeration; module absent |
| USB networking (CDC/RNDIS/NCM host or gadget) | drivers not built into the measured kernel; USB default-deny | attach a test USB network device: no new netdev appears |
| Thunderbolt/USB4/PCIe networking | `thunderbolt-net`-class drivers absent; ports absent, disabled or IOMMU-protected | attach test device: no netdev, no DMA mapping outside allowed groups |
| IPv4 / IPv6 | no addresses; no link-local; forwarding off | address and route tables empty except loopback |
| Tunnels / VPN | no tun/tap/wireguard-class modules | no such netdevs; modules absent from measured kernel config |
| Maintenance state | separate image with no network stack; updates only via the offline medium | same tests in maintenance image |

For the Witness, "driver absent from the measured kernel" is a **structural** property proven by the boot measurement; runtime netdev lists are role-reported (self-attested) and are detective only.

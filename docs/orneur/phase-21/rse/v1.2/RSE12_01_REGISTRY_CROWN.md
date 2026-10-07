# RSE-ARCH-1.2 — Part 1: owner-approved registry, Crown display contract, bootstrap, version floors (closes H1)

Architecture only. Nothing here exists, is created, or is authorized. 1.1's Crown section (`RSE11_02` §H) stands except where this part adds to it.

## 1. Rule

**Crown never treats a proposer-supplied digest as authoritative because it is well-formed.** Every identifier in a grant is a registry entry ID (SHA-256 of a canonical entry). Crown refuses to sign, and the consumer refuses to act, unless that entry exists in the owner-approved registry at a version at or above the floors, is `APPROVED`, is not revoked, and has the entry type the field requires. A raw digest, an unknown ID, or a mismatched type is `FAIL_CLOSED`. A human looking at a hash is never the control.

## 2. Registry entries (canonical, fixed layout per type)

Common fields, in this order: `entry_type` (u8), `name` (1..64 bytes of `[A-Za-z0-9._-]`, zero padded; no other characters; names must be unique per (type, name, version) and must not differ from an existing name only by confusable characters `0/O`, `1/l/I`), `version` (u32), `artifact_digest` (32), `provenance_digest` (32), `producer_entry_id` (32; the build or approval authority, §8), `approval_state` (u8: 1 PENDING, 2 APPROVED, 3 DEPRECATED, 4 REVOKED), `min_permitted_version` (u32), `policy_entry_id` (32), `signing_key_id` (32), `approval_evidence_checkpoint` (32; a witnessed checkpoint **strictly earlier than this entry** that covers the review and build evidence the approval rests on — an entry cannot contain a checkpoint that includes itself, because the entry ID is the hash of the entry; the approval record's own inclusion is proven later by an inclusion proof, not stored inside), `not_after` (u64, advisory, 0 = none).

Types and their fixed tails:

| Type | Tail |
|---|---|
| 1 CODE (role code, tools, verifier, renderer) | none beyond common |
| 2 ROLE_IMAGE (Witness UKI, Crown image, Forge image) | `generation` u32, `measurement_set_digest` 32 |
| 3 FOUNDATION_MODEL | `family_id` 32, `foundation_model_id` 32, `foundation_revision` 64, `tokenizer_entry_id` 32, `weights_digest` 32, `license_record_digest` 32, `architecture_config_digest` 32 |
| 4 TOKENIZER | `tokenizer_id` 32, `vocab_digest` 32 |
| 5 MODEL (candidate / accepted / exported / deployed) | `family_id` 32, `parent_entry_id` 32 (foundation or earlier model), `weights_digest` 32, `lifecycle_state` u8 (candidate, qualified, accepted, exported, deployed, retired), `qualification_record_digest` 32 |
| 6 CORPUS | `corpus_id` 32, `corpus_version` u32, `manifest_digest` 32, `source_provenance_digest` 32, `witness_acceptance_record_digest` 32, `contamination_status_ref` 32, `retirement_state` u8 |
| 7 ENROLMENT | role fields of `RSE12_04` §6 |
| 8 POLICY | per-class ceiling caps (max batch bytes, max runtime, max spend, max run, max query and bit budgets), minimum grant schema version, checkpoint witness set (§`RSE12_02` §1) |
| 9 DESTINATION | destination kind and identifier digest (medium class, recipient role, export target) |
| 10 HOLDOUT_SET | holdout identifier, `bit_budget_total`, `query_budget_total` (budgets live here; `RSE12_05` §1) |

**Model identity is never a free string.** `MODEL_FAMILY_ID` separates Genesis, Novus and Aeternum; a MODEL or FOUNDATION entry carries its own `family_id`; a grant binds the **entry ID**, which hashes the family, so approval of one family or foundation can never authorize another. `FOUNDATION_REVISION`, `TOKENIZER_ID`, `WEIGHTS_DIGEST` and the license/provenance record are inside the hashed entry. No foundation is selected by this document.

**Corpus identity is the entry**, not a manifest the generator picks: a G grant names `corpus_entry_id`; a corpus entry becomes usable for Qualification or training only when it carries a Witness acceptance record that is itself witnessed (`RSE12_02` §3) and `retirement_state` is active.

## 3. Registry object

An ordered list of entries plus `registry_version` (u32, strictly increasing), `previous_registry_root` (32) and `registry_root` (Merkle root over entry IDs). Updates are **owner-signed records** (dual token, `DUAL_TOKEN_OWNER_CONFIRMATION`), canonically serialized, appended to the Crown log, and become effective only when witnessed (`RSE12_02` §1). A registry update is not a grant class: it changes what grants may reference, and it needs no consumer role to act. The registry is distributed to roles on the same medium as grants (a delta from the consumer's last known version).

Checks the consumer performs independently of Crown: signature of the registry update by the approved owner authority version; `registry_version ≥` its own floor; `grant.registry_root` equals the root of the registry it holds at `grant.registry_version`; every ID in the grant resolves, is APPROVED, type-correct, version ≥ `min_permitted_version`; ceilings do not exceed the POLICY entry caps. If the consumer holds an older registry than the grant, it refuses until the newer registry delta is supplied (it learns revocations that way; offline roles otherwise cannot).

Rollback of the registry: see `RSE12_03` row "artifact registry".

## 4. Crown display contract (what the owner sees)

A hardware token is assumed to have **no useful display**. Crown renders a fixed-layout "grant card" on Crown's own screen from the canonical bytes it is about to sign:

```
CLASS        G  CORPUS GENERATION              <- fixed text per class, not proposer text
OPERATION    <fixed operation text for the class>
TARGET ROLE  <enrolment name> v<key version>   <- from registry
ARTIFACT     <name> v<version> [APPROVED, min <n>]   (one line per referenced entry)
DESTINATION  <destination entry name>
LIMITS       bytes <n>  batches <n>  runtime <n> s  spend <n>  (policy cap shown)
EPOCH        <n>   REGISTRY v<n>   AUTHORITY v<n>
FLOOR CHECK  epoch OK  registry OK  authority OK  crown OK      <- machine result
FRESHNESS    challenge SAS <12 chars>  (matches role-displayed SAS: YES/NO)
GRANT SAS    XXXX-XXXX-XXXX
```

Names and versions come from the owner-approved registry entry, never from the proposal.

**SAS algorithm.** `GRANT_SAS = Base32_RFC4648_nopad( first 60 bits of SHA-256("OCR-SAS-v1" ‖ 0x00 ‖ class ‖ signed-region bytes) )`, 12 characters displayed as three groups of four. 60 bits are chosen so that an attacker who controls what Crown displays cannot grind a differing grant to the same SAS (≈2⁶⁰ work); a 40-bit SAS would be grindable. The SAS never replaces reading the fields. The same function over the same bytes is computed by the consumer from the **actual received signed bytes**.

**Typed confirmation.** The owner **types** the 12-character SAS shown on Crown into the consumer; the consumer compares it with its own computation. A wrong entry rejects. This turns "comparison" into a machine-checked, objectively logged step and removes click-through.

**Typed intent (why the SAS alone is not enough).** A compromised Crown can show a benign card and the true SAS of a different grant; typing that SAS then proves nothing about intent. The control that defeats a compromised Crown is that the owner supplies the intent **independently of Crown's screen**: before the Crown session the owner writes an **Intent Sheet** (class, artifact name and version, destination name, the main ceilings). At confirmation the consumer asks the owner to **type those fields from the sheet** (and the SAS); the consumer compares them by machine with the grant it rendered from the signed bytes. A grant that differs from the sheet is rejected even if Crown lied. This costs a few typed fields per confirmation (counted in the operator budget) and is reduced for routine cycles by envelope grants, whose sheet is typed once per envelope. Residual: the owner copies the sheet from the proposal rather than from independent intent (fatigue/habit).

Field assignment:

| HUMAN_VERIFIED (owner reads and judges intent) | MACHINE_VERIFIED (Crown and consumer, no judgment by eye) |
|---|---|
| class and operation text; target role name; artifact names and versions; destination name; resource, spend and runtime limits (the machine checks only that they are ≤ policy caps); the typed SAS | every ID and digest resolves to an APPROVED, type-correct, unrevoked registry entry at the required version; environment measurement; code entry membership and minimum version; epoch; authority version; registry version and root; challenge equals the role's outstanding challenge; previous checkpoint; signature count and distinctness; grant length and layout; ceilings ≤ policy caps |
| expiry is shown but **advisory** (`RSE12_02` §5) | |

This closes the substitution cases: a substituted digest or code SHA cannot resolve to an approved entry; a changed ceiling above the policy cap is refused by machine, and below the cap is visible; wrong class changes the fixed text and the class-specific layout; wrong destination must be an APPROVED destination entry. The residual is the owner approving a bad entry or a bad intent (common-owner error).

## 5. Crown bootstrap (no circularity)

**Crown does not approve the repository that defines Crown.** Crown's own identity is anchored **outside** the registry, in material the owner holds, established by an independent ceremony:

1. **Independent acquisition.** Crown's base image and the minimal signer/renderer source are obtained on a machine that is **not** the daily-driver, from the upstream publisher, with the publisher's signature verified where one exists.
2. **Independent reproduction.** The image and renderer are built on **two independent hosts** (different hardware, ideally different OS families), each from the source; both digests must be equal. Mismatch aborts.
3. **Owner Root Card.** The owner writes (by hand) onto the **Owner Root Card**: the Crown image digest and renderer digest (as grouped base32), and later the owner root and class public-key fingerprints. These are the first trust anchors.
4. **Genesis registry.** On the built Crown, the owner creates the genesis registry and signs it with the tokens. Its root is written on the card and becomes entry zero of the Crown log, which is witnessed.
5. After genesis, a new Crown version is accepted only if **all** hold: a registry ROLE_IMAGE entry signed by the owner; the Owner Floor Card's `crown_min_version` is raised by the owner; the previous Crown signs a hand-off record; two independent builds match.

Trust therefore bottoms out in: the owner's physical custody of the cards and tokens, the owner's own ceremony, and two independent reproductions of public upstream code. No software path asserts its own trust. Residual R-B1: both reproductions share compromised upstream source (declared; `RSE12_05` §6).

## 6. Owner Floor Card (the owner-held minimum)

| Field | Content |
|---|---|
| card serial | strictly increasing; the previous card is struck and kept |
| trust_root_version, owner_authority_version, incident_epoch | |
| crown_min_version, witness_env_min_generation, recovery_kit_min_generation | |
| registry_version and registry_root (first 20 base32 characters plus a 4-character check group) | |
| latest owner checkpoint digest (same encoding) | |

Representation: printed in grouped base32 (4-character groups, ≤ 80 characters per field line) plus a CRC-style check group per line to catch transcription errors; two copies in separate locations. **A paper card has no cryptographic integrity; its integrity is physical (custody, tamper-evident envelope, two-copy comparison).** It is therefore only **one input** to the effective floor: `effective floor = max(card, Crown's own sealed floor, last witnessed checkpoint floors, TPM fence generation on the Witness)`. Lowering a floor requires lowering **all** of them. At the start of every Crown session the owner types the card's floor tuple into Crown; Crown refuses to sign anything if it is below its sealed floor or the witnessed floor, and raises its own floor if the card is higher. Updating: each floor-raising event completes only when the owner writes card serial N+1 and types it into Crown (a K grant cannot reach COMPLETE otherwise). Loss: the second copy plus witnessed checkpoints; if both cards are lost, floors can be re-established only from the independently witnessed checkpoint and a class-K re-root decision.

Enforcement classification: card = `PROCEDURAL`; typed-tuple check and sealed floors = `SOFTWARE_ENFORCED`; witnessed checkpoint floors = `DETECTIVE`; Witness TPM fence = `HARDWARE_ENFORCED`. On a Mac-based minimum Crown a rollback of Crown's own sealed floor remains `UNSOLVED` for prevention; it is detected because a rolled-back Crown cannot get a smaller checkpoint witnessed.

## 7. Crown hardware milestones (unchanged in substance)

Before any real corpus: a dedicated, offline, otherwise-unused Crown environment (the "minimum Crown"), never concurrent with Forge or Witness duties. **A hardware token attached to an agent-exposed daily-driver does not make it trustworthy.** Before Qualification or training: an independently dedicated Crown device with no agents, offline signing, hardware-backed owner keys, canonical renderer, independent digest display, removable transfer, minimal stack and no Forge/Witness duties. The dedicated device is mandatory before Q/T.

## 8. Artifact authority hosts (the registry's supply-chain root)

See `RSE12_05` §6: acquisition on an untrusted host may only **fetch into quarantine**; builds on two independent build hosts; comparison and signing on Crown. The daily-driver is never a signing, comparison or approval host.

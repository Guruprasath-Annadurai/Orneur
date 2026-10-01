# GENESIS V2 — Incident & Revocation Runbook ("Break Glass")

Status: **DESIGN ONLY. NO INCIDENT HAS OCCURRED. NO ACTION BELOW HAS BEEN EXECUTED.**

## Revocation actions, by time budget

| Action | < 5 minutes | < 30 minutes | < 24 hours |
|---|---|---|---|
| Revoke generator | ✓ — deregister/mark revoked in `CORPUS_GENERATOR_REGISTRY.json` + kill the Forge process/container | confirm no in-flight write completed after revocation | full forensic snapshot of the Forge host before rebuild |
| Revoke verifier | ✓ — deregister/mark revoked in `QUALIFICATION_RUNNER_REGISTRY.json` + kill the Witness process | confirm no ledger grant was issued after revocation | forensic snapshot before rebuild |
| Revoke authority key | ✓ — set `revoked: true` on the `AUTHORITY_REGISTRY.json` record | commit + push the revocation (so every future `load_keys()`/`load_keys_for_corpus_generation()` call sees it) | notify any delegated signer, publish the revocation publicly (the registry is already a public repo file) |
| Disable vault write | ✓ — revoke the Forge's write credential/IAM policy at the storage layer | confirm no write is queued/retrying | review access logs for the revocation window |
| Disable vault read | ✓ — revoke the Witness's read credential | confirm no read is queued | review access logs |
| Isolate a compromised host | ✓ — network-isolate (pull the cable / disable the security group) | snapshot for forensics before any cleanup | full rebuild from pinned image, never "clean in place" |
| Rotate X25519 keys for future corpora | — (keypair generation itself takes longer than 5 min to do carefully) | ✓ — generate a fresh keypair on the Crown Plane, distribute public half to a (re-registered) Forge, private half to a (re-registered) Witness | update the generator/verifier registries and secret-manager entries to reference the new keypair |
| Quarantine an affected corpus | ✓ — mark its evidence record "quarantined," block any further read/qualification access at the ledger layer | — | decide retire-vs-keep after investigation |
| Preserve forensic evidence | ✓ — snapshot logs/state **before** any remediation step that could overwrite evidence | — | formal incident write-up, added to the Evidence Ledger as its own record type |

## Incident classes and the specific runbook for each

### Generator (Forge) compromise suspected
1. Isolate the host (< 5 min).
2. Revoke the generator identity (< 5 min).
3. Preserve forensic state (< 5 min, before step 4).
4. Confirm via Witness/Evidence Ledger whether any write occurred after the suspected compromise window; if so, treat every corpus written in that window as **quarantined pending re-verification**, never trusted by default.
5. Rebuild Forge from the pinned code digest on a clean host; re-register under a **new** generator identity (do not simply "clean and reuse" the old identity string).
6. Because Forge never held decrypt capability, SCREEN/QUALIFICATION_HOLDOUT plaintext was never at risk from this compromise alone — confirm and document this explicitly rather than assuming the worst without checking (but do not skip step 4's re-verification; a compromised generator *can* still have written forged-but-structurally-valid ciphertext, which is exactly what the receiving-boundary authentication chain exists to catch).

### Verifier (Witness) compromise suspected
1. Isolate the host (< 5 min).
2. Revoke the verifier identity (< 5 min).
3. Preserve forensic state.
4. **This is the higher-severity case**: Witness holds the X25519 private key. Assume the key is compromised. Rotate X25519 keys for all *future* corpora immediately (< 30 min). Any corpus whose private key may have been exposed must be treated as having had its SCREEN/QUALIFICATION_HOLDOUT plaintext potentially exposed — this is not a "re-verify," it is a "the confidentiality guarantee for this corpus is gone" finding, and the corpus should be retired and regenerated under a fresh keypair once the underlying host compromise is understood and fixed.

### Owner key compromise suspected
1. Set `revoked: true` on the authority record (< 5 min) and push immediately.
2. Every CGA/receipt/manifest signed after the suspected compromise window is void — treat as such even if it still cryptographically verifies (the signature being valid is exactly the problem if the key itself is stolen).
3. If a `DELEGATED_OWNER` key was pre-registered, it becomes the interim signing authority while a new primary owner key is generated and registered through a fresh, careful ceremony (`GENESIS_V2_OWNER_SIGNING_CEREMONY.md`).
4. If no delegated key exists, all new authorization is blocked until the owner re-establishes a trusted signing key — this is intentional; there is no "emergency owner key" shortcut, because that shortcut is precisely the attack surface a sovereign authority model exists to remove.

### Cloud account / credential compromise (Tier 1+)
1. Revoke the specific compromised credential at the IAM layer (< 5 min) — never a blanket "rotate everything" that could itself cause data loss before forensics are captured.
2. Isolate the affected account's network access (< 30 min).
3. Audit the account's access logs for the compromise window; cross-reference against the Evidence Ledger for any writes/reads that don't have a corresponding legitimate evidence record.
4. Rebuild the affected compute identity from IaC/pinned images; never "patch in place" a compromised host.

### Backup (Reliquary) compromise
1. Revoke the compromised backup credential (< 5 min).
2. Because the Reliquary holds ciphertext only, confirm (don't assume) that no private key or plaintext was ever stored there per the custody plan — this should be a quick confirmation, not an investigation, if the design was followed.
3. Rotate backup credentials; verify the next scheduled backup succeeds against the new credential before considering the incident closed.

## Forensic-evidence rule

**Preserve before remediate**, wherever the two are in tension. A host that must be isolated immediately for containment should still be snapshotted (disk image, process list, network connections) before being wiped/rebuilt, unless containment genuinely cannot wait even for a snapshot — and that judgment call belongs to the owner in the moment, not to this document in advance.

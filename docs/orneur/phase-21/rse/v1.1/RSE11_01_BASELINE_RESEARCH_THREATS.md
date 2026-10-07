# RSE-ARCH-1.1 — Part 1: verdict, baseline, research, competitors, threat model, trust roots

Sections A–F. Version 1.0 (`../RSE_0*.md`) stays in the repository as history; where the two differ, **1.1 governs** and the differences are listed in `RSE11_00` (blocker closure). Nothing here is provisioned, purchased, created, run or authorized.

## A. Executive verdict

1. The real corpus path requires **P1**: Crown, Forge and a **physically independent Witness machine**. The single-Mac profile P0 is **synthetic rehearsal only**; it is not authorized for a real private corpus.
2. Version 1.0 overclaimed in six places (rollback "blocked", ledger "detected", Forge "cannot decrypt", validators A/B, Sentinel independence, "two-party"). Version 1.1 downgrades each to what the mechanism can actually do and classifies every control by enforcement type (`RSE11_05` §AG).
3. The design is reduced to seven components: **Crown, Forge, Witness, logical Vault, logical Evidence Ledger, offline Reliquary, external Monitor-Lite**. Transfer Chamber is a *procedure and parser*, not a machine. Qualification is future (P2).
4. Several properties are **not solvable** with the hardware class in scope and are carried as residuals, not hidden (`RSE11_05` §AH).
5. Status of everything: `DESIGNED`. Authorization states are unchanged.

## B. True current-state baseline

Labels: IMPLEMENTED (code exists and passes synthetic tests), SYNTHETIC_ONLY (exercised only with throwaway data), DESIGNED (written, no code), NOT_IMPLEMENTED, NOT_AUTHORIZED.

| Item | State | Note |
|---|---|---|
| Tier0-S software phase gate | IMPLEMENTED, SYNTHETIC_ONLY | one-shot, advisory, fail-closed; accepted as software only; says nothing about hardware or firmware |
| Daily-driver Mac | NOT_AUTHORIZED for any secret role | assumed potentially compromised |
| P0 (single-Mac advanced) | DESIGNED; **SYNTHETIC_REHEARSAL_ONLY** | not a real-corpus path |
| P1 (independent Witness) | DESIGNED; target profile | no hardware chosen |
| Authorization files (corpus generation, model evaluation) | IMPLEMENTED as records; both `NOT_AUTHORIZED` | unchanged |
| Qualification runner registry | IMPLEMENTED as record; `REGISTERED_NOT_AUTHORIZED` | unchanged |
| Owner public authority key | registered as a public key only | no owner private key exists in the repository |
| Access ledger (`AccessLedger`, local SQLite hash chain) | IMPLEMENTED, SYNTHETIC_ONLY | its own docstring: truncation is not detectable from the database alone; this is why §N replaces local-chain trust |
| Encrypted store (`store.py`, AEAD) | IMPLEMENTED, SYNTHETIC_ONLY | asymmetric reader parses a JSON header before authentication; see §M |
| Transfer bundle tool (`tier0a_transfer_bundle`) | IMPLEMENTED, SYNTHETIC_ONLY | strict manifest parser vs lenient header parser = parser differential (§M) |
| Canonical transfer envelope (OCR1) | DESIGNED + scratch prototype outside the repository | not implemented in the product |
| Crown renderer / grant verifier | NOT_IMPLEMENTED | |
| Witnessed evidence ledger | NOT_IMPLEMENTED | |
| Qualification registry content / Chamber | NOT_IMPLEMENTED | |
| Corpus | none exists; `NOT_AUTHORIZED` | |
| Foundation model selection | NOT_AUTHORIZED | |
| GPU, cloud, provider, spending, training | NOT_AUTHORIZED | |

## C. External research (closure)

Primary sources read this phase, by topic. `SOURCE_UNAVAILABLE` marks pages that could not be retrieved; no claim below rests on them.

| Topic | Source | What was used |
|---|---|---|
| TPM policy and NV | tpm2-tools manual pages (`tpm2_policynv`, `tpm2_nvdefine`) | a policy can compare an NV index value with a supplied operand (eq, neq, ordered comparisons); NV counters exist as an index type. Exact counter-attribute wording was **not confirmed** from the page text retrieved → counter design is marked unverified on real hardware |
| TPM specification | TCG library specification page | **SOURCE_UNAVAILABLE** (HTTP 403) |
| Linux TPM security | kernel TPM documentation index | confirms documented attacks on the TPM bus and the role of measurement, secrets guarding and session protection; page detail not read beyond the index |
| Boot measurement | systemd-stub / UKI / PCR 7 / PCR 11 (earlier phase) | UKI measured by the stub; Secure Boot policy in PCR 7 |
| Transparency logs | C2SP tlog-checkpoint and tlog-witness v1.0.0, Sigsum, Rekor (earlier phase) | signed tree-head checkpoints; witnesses cosign after a consistency proof |
| Timestamping | OpenTimestamps | a timestamp shows data existed before a point in time; needs an online calendar/chain to produce or upgrade |
| Confidential compute | Azure confidential GPU options page; Google Confidential VM supported-configuration and GPU-verification pages (navigation retrieved, body detail limited); AWS Nitro, NVIDIA H100 CC (earlier phase) | confidential GPU = CPU TEE VM plus GPU CC mode; attestation must show CC-on; it does not make training trustworthy |
| AMD SEV-SNP | AMD white paper | **SOURCE_UNAVAILABLE** as text (document retrieved empty) |
| Intel TDX | Intel overview | **SOURCE_UNAVAILABLE** (HTTP 403) |
| Supply chain | SLSA v1.2 build levels, in-toto, TUF 1.0 (earlier phase) | levels L1–L3, not transitive; metadata roles and rollback protection by version |
| Lab frameworks | Anthropic RSP/ASL-3 posts, OpenAI and Google DeepMind posts (excerpts), RAND weights-security report (excerpts) | security level concepts only; full RSP text and RAND full text **not read** |
| Apple silicon | Apple platform security (earlier phase) | LocalPolicy, ECID-personalized signatures, no owner-verifiable measured boot found |

Limit: no source in this list proves any ORNEUR mechanism safe; they supply components and vocabulary only.

## D. Competitive matrix

Comparison is by *capability class*, from public statements only. "Public" means a public document describes it; it says nothing about internal practice.

| Capability | Cloud confidential-compute stacks | Frontier-lab security programmes (public) | Consumer secure enclaves (Apple PCC style) | ORNEUR RSE-ARCH-1.1 |
|---|---|---|---|---|
| Hardware-rooted remote attestation | yes (provider root) | described at policy level | yes (vendor root) | P1 Witness: TPM quote, owner-enrolled keys; Mac roles: none |
| Offline human-held signing root | not typical | not described | no | yes (Crown) |
| Per-operation short-lived signed grants | key-release policies | not described | per-request attestation | yes, class-specific |
| Transparency-style witnessed log | provider logs | not described | transparency log for releases | yes, owner-scale |
| Separate weights-export and deployment authority | IAM roles | stated as goals | not applicable | yes (W and D grants) |
| Single administrator cannot rewrite history | provider-dependent | stated as a goal | yes for releases | partial (§N residuals) |

Conclusion: individual components are standard or adapted; the combination is the project's own. No claim of superiority is made.

## E. Threat model

Adversaries (one control failure assumed at a time; named combinations in §AA):

- **T1** compromised daily-driver (full). **T2** compromised Forge (role-level). **T3** compromised Crown *environment* (not the tokens). **T4** compromised Witness software after unlock. **T5** physical thief (disk, token, whole machine). **T6** malicious transfer medium or artifact. **T7** malicious approved dependency. **T8** rollback/replay attacker with storage access. **T9** network observer/injector. **T10** compromised provider (future). **T11** owner error (rubber-stamping, loss). **T12** firmware-level persistence.

Out of scope: coercion or malice of the owner; nation-state invasive hardware attacks on the TPM die; vendor silicon backdoors; side channels on shared cloud hosts (P2 only, unquantified).

Assets: owner root and class keys, Forge generation secret, Witness decryption key, plaintext corpus, holdout key, model weights, ledger integrity, grant authority.

## F. Trust-root decomposition

| Root | Held by | Protects | Failure impact |
|---|---|---|---|
| R-Owner | owner hardware tokens, offline | what may be authorized | total re-root |
| R-Witness-Boot | Witness TPM + owner-enrolled Secure Boot keys + PIN | Witness key release | Witness rebuilt, corpus keys rotated |
| R-Ledger | independent checkpoint holders (§N) | history cannot be rewritten undetected | forks become visible; authority frozen |
| R-Artifacts | owner-signed artifact repository metadata | code that runs | rebuild from re-verified artifacts |
| R-Custody | encrypted Reliquary copies + paper checkpoint | recovery | partial loss recoverable; total loss = re-root |

No role holds two of: generate plaintext, decrypt, approve, and record history.

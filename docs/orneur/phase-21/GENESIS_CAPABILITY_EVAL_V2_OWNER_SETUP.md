# Genesis Capability Eval V2 — Owner Setup Required Before Any Private Corpus Exists

Status: `PRIVATE_STORAGE_NOT_CONFIGURED`. Nothing below has been done, and nothing was invented in its place. This
is a short index; the authoritative procedures are the linked documents — this file exists so there is one place
that lists every prerequisite, in order, without duplicating their detail.

1. **Owner deployment decision** (new, see `GENESIS_V2_INFRASTRUCTURE_DISCOVERY.md`): where the vault and its two
   key halves will actually run — the default, zero-cost path is two separate TRUSTED LOCAL MACHINES (or two
   separate OS user accounts on machines the owner controls), matching the architecture already implemented
   (`store.EncryptedVaultWriter`/`EncryptedVaultReader`, macOS Keychain presence-probe). A cloud/CI-driven
   alternative is possible but requires a SEPARATE, NOT-YET-MADE decision and integration work — see that document's
   "decisions required" section before choosing it.
2. **Private storage**: the encrypted-artifact backend (`ENCRYPTED_ARTIFACT`), the only backend with a real
   operational implementation. Set `ORNEUR_GENESIS_V2_PRIVATE_STORE=ENCRYPTED_ARTIFACT:<vault path>` in BOTH the
   generator's and the verifier's environments (each sees only its own environment — see step 4).
3. **Corpus secret**: ≥32 cryptographically random bytes (`ORNEUR_GENESIS_V2_CORPUS_SECRET`), generated once on a
   trusted machine (`orca.eval.genesis_v2.secret.generate_secret`) and kept in a secret manager, in the GENERATOR's
   environment only. Never in git, CI logs, source or shell history.
4. **X25519 vault keypair** (`store.generate_vault_keypair()`), split into two SEPARATELY scoped secret-manager
   entries — `ORNEUR_GENESIS_V2_VAULT_PUBLIC_KEY` (generator's environment only) and
   `ORNEUR_GENESIS_V2_VAULT_PRIVATE_KEY` (verifier's environment only, NEVER the generator's) — see
   `GENESIS_CAPABILITY_EVAL_V2_OWNER_VAULT_PROCEDURE.md` §3-4 for the full generation procedure and why the two
   halves must never be combined in one stream or one secret. Verify each role's environment with its OWN preflight
   role (`scripts/genesis_v2_preflight.py --role generator` / `--role verifier`) — never the combined `--role owner`
   check from a real deployment.
5. A vault directory outside the repo, on encrypted storage, and a `pip install '.[qualification]'` environment for
   both the generator and the verifier.
6. **Registered generator identity** (`CORPUS_GENERATOR_REGISTRY.json`) and **registered creation-time-verifier
   AND qualification-runner identities as DISTINCT rows** (`QUALIFICATION_RUNNER_REGISTRY.json`) — see
   `GENESIS_V2_THREE_IDENTITY_DEPLOYMENT_DESIGN.md` for the full separation model.
7. **Hermetic sandbox** for coding items (results without it are INCOMPLETE).
8. Independent, REAL-DEPLOYMENT verification (not a unit test — see
   `GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md`) that the generator and verifier genuinely run as
   separate processes/hosts with the credential boundaries this design assumes, then re-run every role's preflight
   (each exits 0) and `scripts/genesis_v2_vault_verify.py --vault <REAL_VAULT_DIR>` (exits 0).

Only after 1–8 may the private corpus be generated — inside the private boundary — with its salted commitments
published here. Do not generate or commit a holdout before that. None of steps 1–8 authorizes corpus generation by
itself: the SEPARATE, owner-signed `CORPUS_GENERATION_AUTHORIZATION` record (see
`corpus_generation_authorization.py`'s own docstring) is still required on top of all of this.

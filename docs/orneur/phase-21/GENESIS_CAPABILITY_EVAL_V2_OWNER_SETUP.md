# Genesis Capability Eval V2 — Owner Setup Required Before Any Private Corpus Exists

Status: `PRIVATE_STORAGE_NOT_CONFIGURED`. Nothing below has been done, and nothing was invented in its place.

1. **Private storage** (choose one): a separate PRIVATE GitHub repository, a private object store, or an authenticated encrypted artifact stored outside the ORNEUR repository. Not the public repo. Set `ORNEUR_GENESIS_V2_PRIVATE_STORE=<KIND>:<location>` for the qualification runner only.
2. **Least-privilege credential** for that store (`ORNEUR_GENESIS_V2_STORE_TOKEN`), available only to the qualification runner; never to public CI.
3. **Corpus secret**: ≥32 cryptographically random bytes (`ORNEUR_GENESIS_V2_CORPUS_SECRET`), generated once on a trusted machine (`orca.eval.genesis_v2.secret.generate_secret`) and kept in a secret manager. Never in git, CI logs, source or shell history.
4. If using an encrypted artifact (the operational backend): a 32-byte AES key in a secret manager (`ORNEUR_GENESIS_V2_ENCRYPTION_KEY`), a vault directory outside the repo, and a qualification-runner environment installed with `pip install '.[qualification]'`. See `GENESIS_CAPABILITY_EVAL_V2_STORAGE_POLICY.md` for backup/recovery.
5. **Registered qualification runner identity** (process id + code sha256) recorded in the frozen pre-registration; only it may open SCREEN / QUALIFICATION_HOLDOUT.
6. **Hermetic sandbox** for coding items (results without it are INCOMPLETE).
7. Independent verification by the owner that the store is actually private, then re-run `scripts/genesis_v2_preflight.py` (exit 0).

Only after 1–7 may the private corpus be generated — inside the private boundary — with its salted commitments published here. Do not generate or commit a holdout before that.

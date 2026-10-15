"""Synthetic training dry-run infrastructure (Workstream G): everything a training run needs EXCEPT training.

SYNTHETIC ONLY. This package contains no trainer, imports no tensor/HF/experiment-tracking library, loads no model, downloads nothing, opens no
network socket and no GPU, and reads no protected data. It cannot start or authorize a real run and has no bypass of
orca.train.authorization. `docs/orneur/authorization/TRAINING_AUTHORIZATION.json` stays NOT_AUTHORIZED; nothing here edits it.

Modules: toy (pure-Python model/optimizer/scheduler), ckpt (atomic verified checkpoints), chainlog / ledger / auditlog (tamper-evident
records), budget (caps + kill switch), binding (code/dataset/config), envmanifest + lockcheck (reproducible environment), sentinel
(synthetic-only guarantee), harness (the run loop and the grant-gated rehearsal), cli (`python -m orca.train.dryrun`).
Submodules are imported explicitly by callers; this file deliberately imports nothing.
"""

# Authority and revocation

`decide_authority` in `orca/pretrain_foundation/governed_handlers.py` is the enforcement point for these handlers. A returned `PERMITTED` sets `executed` false. The handler does not call a tool.

Denial reasons tested: missing grant, tenant mismatch, expired or revoked grant, missing capability. `record_denial` writes a receipt only after that denial. The receipt names `governed_handlers.decide_authority`. It does not prove that another process, an earlier tick, or an unmonitored path stayed idle.

Linearization in this process: `TaskSpec.payload` is the dict the handler reads when `tick` invokes it. The test mutates `grant["revoked"]` after `submit` and before `run_until_idle`, and the handler returns `DENIED`. A handler body that has already entered the function is not preempted. This is not universal instantaneous revocation across workers, queues, or other machines.

`watch_training_locks` denies a payload that sets training, GPU, or spend, and it does not change those locks.

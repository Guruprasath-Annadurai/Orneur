# Thirty-five capability statuses

Source: `orca/pretrain_foundation/capability_contracts.py`. `validate_capabilities()` refuses `INDEPENDENTLY_QUALIFIED` and `PRODUCTION_AUTHORIZED`.

Count on this pass: 17 `IMPLEMENTED_SYNTHETIC`, 18 `DESIGNED`, 0 qualified, 0 production authorized. The previous measurement pass recorded 13 and 22. The four additions are B12, B16, C25, and D29. Each one is a deterministic control, not a qualified expert.

`IMPLEMENTED_SYNTHETIC` means a deterministic function or typed transition ran in `tests/test_agent_role_registry.py` or `tests/test_synthetic_agent_eval.py`. It does not mean a model was called.

Capability id `C27` in this list is proof of non-execution via `record_denial`. It is not acceptance-register row C27, which remains the unmet class-K recovery requirement.

| Id | Status | Where |
|---|---|---|
| A01 A02 A06 A07 A09 | IMPLEMENTED_SYNTHETIC | claims, falsifier, epistemic transition, arbiter |
| A03 A04 A05 A08 | DESIGNED | role rows only |
| B10 B12 B13 B16 | IMPLEMENTED_SYNTHETIC | team selector, capability graph, untrusted-text screen, failure genome |
| B11 B14 B15 B17 B18 | DESIGNED | no adaptive budget, no human-review handler, qualification stops at synthetic |
| C19 C23 C25 C27 | IMPLEMENTED_SYNTHETIC | authority gate, screen, restart refusal, denial receipt |
| C20 C21 C22 C24 C26 | DESIGNED | in-flight preemption, signed receipts, durable deletion, and a real sandbox are absent |
| D28 D29 D30 D31 | IMPLEMENTED_SYNTHETIC | promotion refusal, shadow tournament, cost UNKNOWN, deadline |
| D32 D33 D34 D35 | DESIGNED | no released autonomy control and no native-model fallback |

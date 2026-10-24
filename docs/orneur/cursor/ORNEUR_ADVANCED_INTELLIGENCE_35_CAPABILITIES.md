# Thirty-five capability statuses

Source: `orca/pretrain_foundation/capability_contracts.py`. `validate_capabilities()` refuses `INDEPENDENTLY_QUALIFIED` and `PRODUCTION_AUTHORIZED`.

Count on this pass: 13 `IMPLEMENTED_SYNTHETIC`, 22 `DESIGNED`, 0 qualified, 0 production authorized.

`IMPLEMENTED_SYNTHETIC` means a deterministic function or typed transition ran in `tests/test_agent_role_registry.py`. It does not mean a model was called.

Capability id `C27` in this list is proof of non-execution via `record_denial`. It is not acceptance-register row C27, which remains the unmet class-K recovery requirement.

| Id | Status | Where |
|---|---|---|
| A01 A02 A06 A07 A09 | IMPLEMENTED_SYNTHETIC | claims, falsifier, epistemic transition, arbiter |
| A03 A04 A05 A08 | DESIGNED | role rows only |
| B10 B13 | IMPLEMENTED_SYNTHETIC | team selector, untrusted-text screen |
| B11 B12 B14 B15 B16 B17 B18 | DESIGNED | no extra handler |
| C19 C23 C27 | IMPLEMENTED_SYNTHETIC | authority gate, screen, denial receipt |
| C20 C21 C22 C24 C25 C26 | DESIGNED | limits are stated in the threat-model note |
| D28 D30 D31 | IMPLEMENTED_SYNTHETIC | promotion refusal, cost UNKNOWN, deadline |
| D29 D32 D33 D34 D35 | DESIGNED | no promotion tournament and no native-model fallback |

# Memory isolation

`isolate_memory` allows a read only when `actor_tenant` and `record_tenant` are both present and equal. A cross-tenant payload returns `allowed: false`.

This is one handler, not a full memory store. It does not delete durable files, does not cover export, and does not prove that another module is isolated. Roles `memory-admission`, `memory-writer`, `retention-enforcer`, and `deletion-verifier` remain declared and unimplemented.

`screen_untrusted` refuses fixture text containing `ignore previous`, `grant admin`, `you are now`, or `system:`. Admitted text is marked `as_instruction: false` and `authority_changed: false`. Retrieved text is not written into a trusted memory store by this function.

# Memory isolation

`isolate_memory` returns `allowed: false` for every caller payload. Differing tenant strings are `cross-tenant memory read`. Equal tenant strings are `tenant strings are not an enrolled identity`. No memory authority is enrolled.

This is one handler, not a full memory store. It does not delete durable files, does not cover export, and does not prove that another module is isolated. Roles `memory-admission`, `memory-writer`, `retention-enforcer`, and `deletion-verifier` remain declared and unimplemented.

`screen_untrusted` refuses fixture text containing `ignore previous`, `grant admin`, `you are now`, or `system:`. Admitted text is marked `as_instruction: false` and `authority_changed: false`. Retrieved text is not written into a trusted memory store by this function.

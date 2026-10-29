# LANDMARK-02 — exact-head CI (engineering evidence; not independent qualification)

Branch `claude/landmark-02-customer-trust-reliability`, draft PR #139, stacked on PR #136 (`9cb864c99ad323d11626063498a7d1cef0d7d4b5`, not modified).

| Commit | Content | Run | Result |
|---|---|---|---|
| `503ce0b` | L02-01 deletion workflow | 40858954520 | success (10/10 jobs) |
| `35cb248` | retention/account deletion routed through the workflow | 40859334558 | success |
| `9100361` | L02-02 first slice + L02-01 report | 40859996724 | success |
| **`11801a8`** | **last product-code commit (L02-02: validation, registry-enforced retrieval, chunk identity, framing, abstention, unsupported-citation reporting)** | **40862564360** | **success, 10/10 jobs** |
| documentation commits after `11801a8` | docs only | 40862662385 (`67e04f8`) | success |

Run 40862564360 (code-bearing): Deterministic Unit Tests **9129 passed, 398 skipped, 152 deselected, 6 xfailed, 0 failed**; Journeys (fixture provider) 39 passed; frontend Node tests, Genesis security/sandbox, training-math (25), container build, RSE jobs, dependency scan: success. Compared with the PR #136 head run (9085 passed): +44 tests, same 398 skips / 6 xfail (all pre-existing conditional skips).

Not run in CI: the real-Ollama journeys (`tests/journey/test_l02_document_real_live.py`, workstation only, same as B-04).

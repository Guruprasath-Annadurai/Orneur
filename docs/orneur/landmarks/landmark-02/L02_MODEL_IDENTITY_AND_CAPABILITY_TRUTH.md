# L02-08 — Model identity and capability truth

Evidence state: **VERIFIED_ENGINEERING**. Code: `orca/serve/{capability_truth,model_identity}.py`, `GET /api/capabilities`, `orca/cognitive/kernel.py` (serving-facts system message), `orca/personas.py`, `conversation.html` (Details rows). Tests: `tests/test_l02_model_truth.py` (16).

## What is true today
* Every answer is produced by a **third-party open-weights model (`llama3.2:1b` in the verified runs) through a local Ollama runtime**. ORNEUR has published **no** trained native weights for any family.
* Family status: **GENESIS = INTERFACE_ONLY** (tier name routes to a third-party model); **NOVUS, AETERNUM = NOT_AVAILABLE**. Nothing in this work started, authorised or claims native training.
* The model is told this in a constant server-supplied system block (so it does not claim to be ORNEUR-trained, to have benchmarks, or to take actions it cannot take). The block states that code is a suggestion, not executed, and tells the model to answer only from conversation and labelled document text. Because the block is model-facing, the instruction is *behavioural*, not an enforcement.
* `GET /api/capabilities` returns the table of what the product can and cannot do, each entry with a repository evidence path; a test asserts every path exists.
* Every model-identity surface (SSE `model` event, `done`, `/api/models`, Details panel) carries `weights_origin` (`third_party`) and runtime; personas no longer claim native identity.
* Tool reporting lists **only executed tools**; a tool the model merely mentions is not reported as run.
* Email delivery, verification and 2FA availability are reported from configuration, not assumed.

## Evidence
Deterministic: `tests/test_l02_model_truth.py`. Browser (real Ollama and fixture): student S2/S3 (selector shows "Genesis" with the "EXPERIMENTAL — not qualified" panel; the answering model is named), developer D8 (suggested code not presented as executed), business journeys. Files: `evidence/l02_journey_*_real.json`.

## Limits
A 1B third-party model can still produce a wrong statement about itself; the system block reduces but cannot guarantee it. The journeys sample a few prompts, they are not a statistical evaluation. No benchmark, accuracy or safety figure is claimed anywhere.

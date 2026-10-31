# MASTER-02 — Governance Recheck (on integrated tree)

Probed on merge tip tree `7a980d4ae918bc4dbec374772a2ec20e36d3107f`.

| Control | Required | Observed | Verdict |
|---|---|---|---|
| GENESIS | `INTERFACE_ONLY` | `capabilities()["model"]["native_orneur_models"]["genesis"] == "INTERFACE_ONLY"` | **HOLD** |
| NOVUS | unavailable | `"novus": "NOT_AVAILABLE"` | **HOLD** |
| AETERNUM | unavailable | `"aeternum": "NOT_AVAILABLE"` | **HOLD** |
| Third-party inference disclosure | disclosed | `serving_facts(): weights_origin=third_party`, `native_orneur_weights=False`, runtime `ollama` local | **HOLD** |
| Formal acceptance | **0 / 95** | `validate_register_graph.py --check` → `pretraining=95 numerator=0 application=3 execution=2 post=1` | **HOLD** |
| Training authorization | denied | `TRAINING_AUTHORIZATION.json` `status=NOT_AUTHORIZED`; `permissions.gpu_allowed=false`; limits all 0 | **HOLD** |
| Training freeze | NO-GO / NOT_FROZEN | `TRAINING_FREEZE_MANIFEST.json` status `NOT_FROZEN`; master engineering report freeze package `NOT_FROZEN` / `NO-GO` | **HOLD** |
| GPU / corpus / spending | denied | RSE confirm payload: `gpu=false`, `spending=false`, `training=false`, `corpus_generation=NOT_AUTHORIZED`; auth doc spend limit 0 | **HOLD** |

## Residual security blockers (not closed by MASTER-02)

Carried from MASTER-01 with integrated-SHA context:

1. Formal acceptance numerator still **0/95** — no row promotion from this mission.
2. G3 independent review on **merged/main** SHA still missing.
3. C06/C07 OWN_EVIDENCE on integrated SHA still required (portable harness ≠ Antigravity formal).
4. L01 B-02 / L02-Q / #141 independent qualification of exact heads still open.
5. #143 plaintext backup bypass remains unresolved — correctly excluded.
6. Physical C08 / hardware trust / GPU corpus / founder custody decisions unchanged.
7. Combined-tip **independent** Antigravity qualification of this integration candidate still required after CI greens.

## Unsupported claims explicitly denied

- Not launch-ready. Not training-ready. Not merge-authorized. Not formal OWN_EVIDENCE.

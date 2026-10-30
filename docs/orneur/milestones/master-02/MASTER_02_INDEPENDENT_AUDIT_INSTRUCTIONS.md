# MASTER-02 — Independent Audit Instructions

For an auditor **other than** the integration author agent.

## Checkout

```bash
git fetch origin pull/<MASTER02_PR>/head:master02-candidate
git checkout master02-candidate
# Content identity of the five-PR merge (ignore later harness/docs commits if present):
git rev-parse 7fb78a3d9c522edff26335a551ceadc5d500f941^{tree}
# expect: 7a980d4ae918bc4dbec374772a2ec20e36d3107f
```

## Ancestry assertions

```bash
for s in \
  649d90f84069fc618ba4d69b4c26a66bed731caa \
  9cdc22bfc64f35e46e57769e3e255dabf5d11cb4 \
  9cb864c99ad323d11626063498a7d1cef0d7d4b5 \
  38e0d311991875366f2bc88a39690c7b2b6ea3ee \
  66ce8aeace2077b89195735211d75ebd566716c8 \
  15befec7191a1992286d7fa027236002f7d385db
 do git merge-base --is-ancestor $s 7fb78a3d9c522edff26335a551ceadc5d500f941 && echo OK $s; done

# Must FAIL (non-zero):
git merge-base --is-ancestor e5266c71d8a9a50e2571eaef1ca30f1c976d5f59 7fb78a3d9c522edff26335a551ceadc5d500f941
git merge-base --is-ancestor b1c56b98a52bdc3c448011f482251c238b329c5c 7fb78a3d9c522edff26335a551ceadc5d500f941

# Protected main must remain:
test "$(git rev-parse origin/main)" = "20a8546f5a1ece7e5af655c0f30ca7e305f71b1a"
```

## Governance probes

```bash
python3 scripts/acceptance/validate_register_graph.py --check
# expect: pretraining=95 numerator=0 …

python3 -c "from orca.serve.capability_truth import serving_facts, capabilities; print(serving_facts()); print(capabilities()['model']['native_orneur_models'])"
# expect: third_party / genesis INTERFACE_ONLY / novus+aeternum NOT_AVAILABLE

python3 -c "import json; print(json.load(open('docs/orneur/authorization/TRAINING_AUTHORIZATION.json'))['status'])"
# expect: NOT_AUTHORIZED
```

## Recommended retest bundles

1. `pytest tests/rse/test_c06_c07_consumer_verification.py tests/rse/ -q`
2. `pytest tests/test_pretraining_readiness_gate.py tests/test_genesis_governance_authorization.py -q`
3. Landmark auth/stream/B3/RAG targeted set (see MASTER_02_CI_AND_RETEST_EVIDENCE.md)
4. `bash scripts/ci/run_genesis_v2_security_tests.sh`
5. GitHub Actions full matrix on the PR tip (deterministic, torch, container smoke, RSE lab, journeys, scans)
6. **Your** independent F03/C06/C07 suite against this integrated worktree — do not treat `test_master02_f03_portable_harness.py` as Antigravity OWN_EVIDENCE

## Original vs portable F03 suite

| Artifact | Path / SHA | Use |
|---|---|---|
| Original audit (verbatim) | commit `75a7a64…`; archived under `docs/orneur/milestones/master-02/evidence/antigravity-original/` | Historical evidence; hardcoded host path |
| Portable harness | `tests/qualification/test_master02_f03_portable_harness.py` | Author engineering re-exec only |

## Failures must be reported

Any failed check, skip, xfail, missing optional dependency, or unexecuted gate must appear in the audit report. Silent suppression invalidates the review.

# Experiment manifests

## X2-contradiction-first-v1

- Code: `run_contradiction_first`.
- Endpoint: `confident_despite_conflict`, defined as status `success` while a non-temporal contradiction is present on the result.
- Items: `one-sided-a`, `one-sided-b`, `conflict-a`, `conflict-b`, `missing`, `one-sided-c`.
- Corpus: the documents constructed in `test_contradiction_first_experiment_is_frozen_and_recorded`.
- Observed: baseline 2, treatment 0, correct-answer loss 0, `hypothesis_supported=True`, `negative_result=False`.
- Software revision recorded by the test: `test`.
- Model: none. Both arms use the span-quoting kernel.

## Not run

- T1 and T2 trained-model arms.
- Neural dense, ColBERT, audio, and video.
- Any comparison against an external model API.
- GPU or multi-node scaling.

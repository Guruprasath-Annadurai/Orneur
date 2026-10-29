# Data Pipeline Integrity (Phase 4)

**Disposition:** `PARTIAL_ENGINEERING — CORRECTIONS_REQUIRED`  
**Training authorization:** **NO-GO**

## Engineering present

- Manifest schema / binding: `orca/genesis/data/manifest.py` (DATA-1 probed)
- Contamination helpers: `orca/genesis/data/contamination.py` (DATA-2 probed)
- Pipeline admission, near-dup, privacy rejection: `orca/genesis/data/pipeline.py`
- Synthetic corpus controls: `orca/pretrain_foundation/corpus_controls.py`
  - Per-record content hash required
  - Holdout under training identity refused
  - User-conversation ingestion refused
  - Remote URL / object-store origins refused (including Path-mangled `https:/`)
  - Training-bound reader helper forces `require_license=True` + mandatory `allowed_root`
  - Digest change invalidates frozen corpus
- `process_training_bound_corpus()` in `orca/genesis/data/pipeline.py` — software hardening only; **not** G8 corpus creation

## Blocked

| ID | Prerequisite |
|---|---|
| G8 / DATA-3 | Founder corpus-generation grant — **no real corpus created** |
| DATA-5 | Independent custody evidence |

Synthetic / legally authorized non-training fixtures only.

# FOUNDATION-02 Data Provenance & Licensing Safeguards

## Implemented (admission / synthetic)

- Dataset manifest validation (`tests/test_genesis_data_manifest.py`)
- Pipeline admission controls (`tests/test_cursor_pipeline_admission.py`)
- Contamination checks (`tests/test_genesis_data_contamination.py`)

## Explicitly not done

- No dataset download/scrape
- No private user-chat ingestion
- No protected holdout use
- Heuristic dedupe ≠ proof of zero contamination

## Future ingestion contract

Malformed or unapproved manifests must be rejected by validators before any
training path can bind them. Founder corpus grants (G8/DATA-3) remain **BLOCKED**.

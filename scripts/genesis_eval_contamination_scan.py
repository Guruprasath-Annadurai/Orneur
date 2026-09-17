"""
Genesis Evaluation Suite contamination scan (Phase 21B.3 spec section 20).

Compares every genesis-eval-v1 task prompt against the content of every
Genesis training dataset (v1, v2, v3 -- TRAIN and VALIDATION splits) for
(a) exact overlap and (b) normalized near-duplicate overlap, reusing the
SAME normalized token-set Jaccard method
scripts/build_genesis_v3_dataset.py already implements for training-data
dedup (not reinvented, per spec section 20's "Implement... between
evaluation and: Genesis V1, Genesis V2, Genesis V3 TRAIN, Genesis V3
VALIDATION").

HONEST LIMITATION, stated explicitly here and in the generated report:
this only detects DIRECT training/evaluation leakage within this
project's own authored datasets. It says nothing about whether the
eval tasks' underlying concepts (or exact phrasings) already appear in
whatever pretraining corpus a candidate foundation model was trained
on -- that is a fundamentally different, much harder problem this scan
does not and cannot solve, since none of the candidate foundation
models' pretraining corpora are available for inspection. This
limitation is reported, not hidden.

Usage: python3 scripts/genesis_eval_contamination_scan.py
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from orca.eval.genesis_suite import all_tasks

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "notebooks" / "data"

TRAINING_SOURCES = {
    "genesis_v1_train": DATA_DIR / "orca_nano_combined_train_v1.jsonl",
    "genesis_v1_eval": DATA_DIR / "orca_nano_combined_eval_v1.jsonl",
    "genesis_v2_train": DATA_DIR / "orneur_genesis_v2_train.jsonl",
    "genesis_v2_eval": DATA_DIR / "orneur_genesis_v2_eval.jsonl",
    "genesis_v3_train": DATA_DIR / "orneur_genesis_v3_train.jsonl",
    "genesis_v3_eval": DATA_DIR / "orneur_genesis_v3_eval.jsonl",
}

NEAR_DUP_JACCARD_THRESHOLD = 0.85


def _normalized_token_set(text: str) -> set[str]:
    normalized = re.sub(r"[^\w\s]", " ", text.lower())
    return set(normalized.split())


def _load_training_texts(path: Path) -> list[str]:
    if not path.exists():
        return []
    texts = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            texts.append(record.get("text", ""))
    return texts


def scan() -> dict:
    tasks = all_tasks()
    training_texts: dict[str, list[str]] = {name: _load_training_texts(path) for name, path in TRAINING_SOURCES.items()}
    training_token_sets: dict[str, list[set[str]]] = {
        name: [_normalized_token_set(t) for t in texts] for name, texts in training_texts.items()
    }

    exact_overlap_findings = []
    near_dup_findings = []

    for task in tasks:
        task_tokens = _normalized_token_set(task.prompt)
        for source_name, texts in training_texts.items():
            for idx, text in enumerate(texts):
                # Exact overlap: the task's prompt appears verbatim inside
                # the training record's full ChatML text (the training
                # text wraps prompt+response+system in template tokens,
                # so exact CONTAINMENT is the right check, not equality).
                if task.prompt and task.prompt in text:
                    exact_overlap_findings.append({
                        "task_id": task.task_id, "source": source_name, "record_index": idx,
                    })

        for source_name, token_sets in training_token_sets.items():
            for idx, tset in enumerate(token_sets):
                if not task_tokens or not tset:
                    continue
                jaccard = len(task_tokens & tset) / len(task_tokens | tset)
                if jaccard >= NEAR_DUP_JACCARD_THRESHOLD:
                    near_dup_findings.append({
                        "task_id": task.task_id, "source": source_name, "record_index": idx,
                        "similarity": round(jaccard, 3),
                    })

    report = {
        "suite_id": "genesis-eval", "suite_version": "v1",
        "total_tasks_scanned": len(tasks),
        "training_sources_scanned": {
            name: len(texts) for name, texts in training_texts.items()
        },
        "exact_overlap_count": len(exact_overlap_findings),
        "exact_overlap_findings": exact_overlap_findings,
        "near_duplicate_overlap_count": len(near_dup_findings),
        "near_duplicate_findings": near_dup_findings,
        "near_duplicate_jaccard_threshold": NEAR_DUP_JACCARD_THRESHOLD,
        "known_leakage": len(exact_overlap_findings) > 0 or len(near_dup_findings) > 0,
        "base_model_pretraining_contamination": "UNKNOWN -- not evaluated; no candidate foundation model's pretraining corpus is available for inspection. This scan only covers this project's own authored training datasets.",
    }
    print(json.dumps(report, indent=2))
    return report


if __name__ == "__main__":
    scan()

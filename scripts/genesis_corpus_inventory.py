#!/usr/bin/env python3
"""Build / verify GENESIS_TRAINING_AND_ADAPTATION_CORPUS_INVENTORY.json from the repository and the owner's ORCA_HOME (read-only; hashes and counts only).

  python scripts/genesis_corpus_inventory.py --write     # (re)generate; completeness attestation stays NOT_ATTESTED
  python scripts/genesis_corpus_inventory.py --verify    # evaluate the committed inventory in THIS environment (exit 2 unless PASS)
"""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from orca.eval.genesis_v2 import inventory as INV  # noqa: E402

OWNER = "ORNEUR owner (Guruprasath Annadurai)"
NOW = "2026-09-27"


def _sha_count(p: Path):
    h = hashlib.sha256()
    n = 0
    with open(p, "rb") as f:
        for line in f:
            h.update(line)
            n += 1 if line.strip() else 0
    return h.hexdigest(), n


def entry(cid, cls, purpose, prov, classification, kind, loc, path, *, training, adaptation, note="", lifecycle=None):
    sha, n = _sha_count(path) if path and path.is_file() else (None, None)
    return {"corpus_id": cid, "version": "sha256:" + (sha or "n/a")[:12], "corpus_class": cls, "purpose": purpose, "provenance": prov, "classification": classification,
            "storage": {"kind": kind, "location": loc}, "manifest_id_or_sha256": sha, "record_count": n, "used_in_training": training, "used_in_adaptation": adaptation,
            "visible_during_screen": False, "visible_during_qualification_holdout": False,
            "permitted_lifecycle": lifecycle or "may influence a Genesis candidate ONLY after a fresh contamination screen against the V2 SCREEN and QUALIFICATION_HOLDOUT commitments; never after a holdout is opened for that lineage",
            "contamination_check_status": "PENDING_V2_CORPUS", "owner": OWNER, "status": "PRESENT" if sha else "UNAVAILABLE", "note": note}


def build(orca_home: Path) -> dict:
    inv = INV.empty_inventory()
    cs = inv["corpora"]
    pub = "notebooks/data/"
    legacy = "used to fine-tune legacy orca-core/orca-nano models (not Genesis foundation candidates); no Genesis candidate has been trained on it"
    for f, cls, tr, prov, note in (
        ("orca_core_combined_train_v2.jsonl", "public_sft_datasets", True, "scripts/build_core_combined_dataset.py", legacy),
        ("orca_core_combined_eval_v2.jsonl", "public_sft_datasets", False, "scripts/build_core_combined_dataset.py", "SFT validation split; never qualification evidence"),
        ("orca_nano_combined_train_v1.jsonl", "public_sft_datasets", True, "scripts/build_nano_combined_dataset.py", legacy),
        ("orca_nano_combined_eval_v1.jsonl", "public_sft_datasets", False, "scripts/build_nano_combined_dataset.py", "SFT validation split; never qualification evidence"),
        ("orneur_genesis_v2_train.jsonl", "public_sft_datasets", False, "scripts/build_genesis_v2_dataset.py (hand-authored seed)", "legacy name 'genesis_v2' = 2nd public SFT build, NOT Genesis Capability Eval V2; prepared for Genesis SFT, no Genesis training run has occurred"),
        ("orneur_genesis_v2_eval.jsonl", "public_sft_datasets", False, "scripts/build_genesis_v2_dataset.py", "SFT validation split; never qualification evidence"),
        ("orneur_genesis_v3_train.jsonl", "public_sft_datasets", False, "scripts/build_genesis_v3_dataset.py (hand-authored seed)", "prepared for Genesis SFT; no Genesis training run has occurred"),
        ("orneur_genesis_v3_eval.jsonl", "public_sft_datasets", False, "scripts/build_genesis_v3_dataset.py", "SFT validation split; never qualification evidence")):
        cs.append(entry("pub-" + f[:-6], cls, "supervised fine-tuning data", prov, "PUBLIC", "REPO_PATH", pub + f, ROOT / pub / f, training=tr, adaptation=False, note=note))
    v1 = "eval_private/genesis_capability_eval_v1/"
    cs.append(entry("v1-pilot-train", "public_pilot_train_v1", "Stage-3 trainability pilot data (V1 PILOT_TRAIN)", "seeded procedural generators, genesis-capability-eval V1", "PUBLIC",
                    "REPO_PATH", v1 + "pilot_train.jsonl", ROOT / v1 / "pilot_train.jsonl", training=False, adaptation=False,
                    note="publicly exposed; only for the trainability pilot", lifecycle="trainability pilot only, never as qualification evidence"))
    for f, cid in (("dev.jsonl", "v1-dev"), ("holdout.jsonl", "v1-holdout-exposed")):
        cs.append(entry(cid, "public_benchmark_v1", "public/development benchmark (V1 is permanently invalid as a private benchmark)", "seeded procedural generators, genesis-capability-eval V1",
                        "PUBLIC", "REPO_PATH", v1 + f, ROOT / v1 / f, training=False, adaptation=False, note="publicly exposed; forbidden as training/adaptation data",
                        lifecycle="FORBIDDEN as training or adaptation data; benchmark reference only"))
    t = orca_home / "training"
    def local(rel, cid, cls, purpose, prov, training, note=""):
        cs.append(entry(cid, cls, purpose, prov, "PRIVATE", "ORCA_HOME_PATH", "training/" + rel, t / rel, training=training, adaptation=False, note=note))
    for p in sorted((t / "raw").glob("*.jsonl")) if (t / "raw").is_dir() else []:
        n = p.name
        cid = "local-raw-" + p.stem
        if n.startswith(("genesis_v2_seed", "genesis_v3_seed")):
            local("raw/" + n, cid, "manually_authored_internal_examples", "hand-authored seed records for the public Genesis SFT builds", "authored by ORNEUR/Claude for scripts/build_genesis_v*_dataset.py", False,
                  "source of the public genesis SFT sets")
        elif n.startswith(("core_distilled", "nano_distilled", "ultra_distilled")):
            local("raw/" + n, cid, "distillation_data", "teacher-distilled SFT records for legacy orca models", "provider/teacher model outputs (see distill_logs); teacher-output licensing review pending", "UNKNOWN",
                  "which legacy training runs consumed this exact file is not recorded in the repository")
        elif n.startswith("nano_safety_sft"):
            local("raw/" + n, cid, "private_sft_datasets", "safety SFT records for legacy orca-nano", "teacher-distilled and filtered", "UNKNOWN")
        elif n.startswith("seed_"):
            local("raw/" + n, cid, "synthetic_generation_corpora", "Ollama-generated seed examples (orca data seed)", "locally generated by a local model via orca/data/seeds.py", "UNKNOWN")
        else:
            local("raw/" + n, cid, "private_sft_datasets", "raw training records", "unknown", "UNKNOWN")
    for p in sorted((t / "formatted").glob("*.jsonl")) if (t / "formatted").is_dir() else []:
        local("formatted/" + p.name, "local-formatted-" + p.stem, "instruction_tuning_datasets", "chat-template formatted training/eval splits derived from raw records", "orca data format", "UNKNOWN")
    for p in sorted((t / "dpo").glob("*.jsonl")) if (t / "dpo").is_dir() else []:
        probe = "probe_grounded" in p.name
        local("dpo/" + p.name, "local-dpo-" + p.stem, "evaluation_derived_adaptation_data" if probe else "preference_dpo_data",
              "DPO preference pairs" + (" derived from red-team probes" if probe else ""), "generated from red-team/honesty probes and teacher outputs", "UNKNOWN")
    for p in sorted((t / "distill_logs").glob("*.jsonl")) if (t / "distill_logs").is_dir() else []:
        local("distill_logs/" + p.name, "local-distilllog-" + p.stem, "distillation_data", "teacher generation logs", "provider teacher outputs", "UNKNOWN")
    cs.append({"corpus_id": "external-kaggle-uploaded-datasets", "version": "unknown", "corpus_class": "external_uploaded_datasets",
               "purpose": "datasets uploaded to Kaggle/Colab for legacy fine-tuning notebooks", "provenance": "names not recorded in the repository (see notebooks/*.ipynb)",
               "classification": "PRIVATE", "storage": {"kind": "EXTERNAL_DESCRIPTOR", "location": "Kaggle datasets referenced by notebooks/*"}, "manifest_id_or_sha256": None,
               "record_count": None, "used_in_training": "UNKNOWN", "used_in_adaptation": False, "visible_during_screen": False, "visible_during_qualification_holdout": False,
               "permitted_lifecycle": "owner must enumerate and hash these, or attest they are unrelated to Genesis, before qualification", "contamination_check_status": "PENDING_V2_CORPUS",
               "owner": OWNER, "status": "UNAVAILABLE", "note": "cannot be inspected from this repository"})
    for cid_cls in {c["corpus_class"] for c in cs}:
        inv["class_coverage"][cid_cls] = {"declaration": "LISTED", "corpus_ids": sorted(c["corpus_id"] for c in cs if c["corpus_class"] == cid_cls)}
    inv["excluded_artifacts"] = [
        {"artifact": "training/redteam, training/eval, training/persona_eval result JSON", "reason": "evaluation RESULTS of legacy models, not training inputs"},
        {"artifact": "registry/datasets manifests", "reason": "dataset metadata, not corpora"}]
    inv["generated_at"] = NOW
    inv["generator"] = "scripts/genesis_corpus_inventory.py --write (read-only: hashes and counts only; no content is copied)"
    return inv


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    home = Path(os.environ.get("ORCA_HOME", Path.home() / ".orca"))
    if a.write:
        inv = build(home)
        (ROOT / INV.INVENTORY_PATH).write_text(json.dumps(inv, indent=1, sort_keys=True) + "\n")
        print("written", len(inv["corpora"]), "corpora")
    inv = json.loads((ROOT / INV.INVENTORY_PATH).read_text())
    res = INV.evaluate(inv, ROOT, home)
    print(json.dumps({"status": res.status, "note": res.note, "findings": len(res.findings)}))
    sys.exit(0 if res.status == "PASS" else 2)


if __name__ == "__main__":
    main()

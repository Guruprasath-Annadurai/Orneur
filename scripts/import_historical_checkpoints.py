"""
Imports existing pre-Orneur checkpoints into the new registry as historical
artifacts. Per explicit instruction: never falsify origin, never relabel a
7B Genesis checkpoint as 3B, never fabricate a checksum for an artifact that
is no longer locally reachable (orca-core / orca-core-dpo's GGUF files were
removed from this machine's Ollama store earlier this phase to free disk
space -- their evaluation history is preserved via their recorded
eval/redteam JSON reports even though the weight files themselves are gone
from local disk).
"""
from __future__ import annotations

from orca.registry.checkpoint import CheckpointRecord
from orca.registry.model_registry import ModelRegistry

reg = ModelRegistry()

# ---------------------------------------------------------------- Genesis --
# All confirmed 7.6B / Qwen2.5-7B-class via `ollama show` (see
# docs/orneur/phase-0/GENESIS_MODEL_IDENTITY.md). These are legacy artifacts
# under the future orneur-genesis family, NOT the canonical 3B target.
genesis_checkpoints = [
    dict(
        checkpoint_id="orca-nano",
        legacy_ollama_name="orca-nano",
        artifact_checksum="sha256:671e7777da70c808de5d0060d1e9df3b8f496e15fa6b39c86371abd70cb0d560",
        note="7.6B, qwen2, embedding length 3584 -- confirmed via `ollama show`. Legacy 7B, not the canonical 3B Genesis target.",
    ),
    dict(
        checkpoint_id="orca-nano-v4",
        legacy_ollama_name="orca-nano-v4",
        artifact_checksum="sha256:671e7777da70c808de5d0060d1e9df3b8f496e15fa6b39c86371abd70cb0d560",  # same digest as orca-nano -- same artifact, different tag
        note="Same underlying artifact as orca-nano (identical digest) -- a re-tag, not a distinct training run.",
    ),
    dict(
        checkpoint_id="orca-nano-v7",
        legacy_ollama_name="orca-nano-v7",
        artifact_checksum="sha256:5ce043a5425064eb264c8054ff9c49c335764b6664d639c71a8788a4dd5e2391",
        note="7.6B, qwen2, embedding length 3584 -- confirmed via `ollama show`. Legacy 7B, not the canonical 3B Genesis target. Latest legacy Genesis checkpoint (safety+honesty DPO round).",
    ),
]

for c in genesis_checkpoints:
    rec = CheckpointRecord(
        checkpoint_id=c["checkpoint_id"],
        model_id="orneur-genesis",
        run_id="legacy-pre-orneur",
        step_or_epoch="unknown (legacy, predates run-manifest tracking)",
        base_model="unsloth/Qwen2.5-7B-Instruct",  # historical fact, NOT the canonical future 3B target
        dataset_manifest_ids=[],
        training_config_summary="legacy ORCA-era training, predates dataset/training-run manifests",
        optimizer_state_available=False,
        scheduler_state_available=False,
        tokenizer_identity="unsloth/Qwen2.5-7B-Instruct",
        artifact_path=f"ollama://{c['legacy_ollama_name']}",
        artifact_checksum=c["artifact_checksum"],
        legacy_ollama_name=c["legacy_ollama_name"],
    )
    rec.save()
    entry = reg.register(rec, family="genesis", ollama_alias=c["legacy_ollama_name"])
    reg.retire(c["checkpoint_id"], reason=f"legacy 7B artifact, historical import -- {c['note']}")
    print(f"[import] {c['checkpoint_id']} -> family=genesis, RETIRED (legacy), {c['note']}")

# ------------------------------------------------------------------ Novus --
novus_checkpoints = [
    dict(
        checkpoint_id="orca-core-dpo",
        legacy_ollama_name="orca-core-dpo",
        artifact_checksum="UNVERIFIED_ARTIFACT_REMOVED_FROM_LOCAL_DISK",
        note="Safety-DPO baseline. Artifact removed from local Ollama store during this phase to free disk space -- eval/redteam history preserved via ~/.orca/training/redteam/redteam_orca-core-dpo.json.",
    ),
    dict(
        checkpoint_id="orca-core-combined",
        legacy_ollama_name="orca-core-combined",
        artifact_checksum="sha256:f9e41d9092d2a2443fb8f4e40a0b9d8a09c909617c37581e56e2f1dac60ecc95",
        note="Attempt 2 (10x/1:2 safety oversample): jailbreak 70/90%, bias 12.5%, calibration 0.0% -- the checkpoint that motivated this phase's calibration-regression investigation.",
    ),
    dict(
        checkpoint_id="orca-core-combined-v2",
        legacy_ollama_name="orca-core-combined-v2",
        artifact_checksum="sha256:c519cba17b689b752807006da39713ba25caadcbb5d4c0380b3d519862308725",
        note="Attempt 3 (4x/1:5 safety oversample): jailbreak 70/90%, bias 12.5%, calibration 100.0% -- calibration regression resolved, current best Novus candidate.",
    ),
]

for c in novus_checkpoints:
    rec = CheckpointRecord(
        checkpoint_id=c["checkpoint_id"],
        model_id="orneur-novus",
        run_id="legacy-pre-orneur" if c["checkpoint_id"] != "orca-core-combined-v2" else "orca-core-combined-sft-kernel-v1-v5",
        step_or_epoch="unknown (legacy, predates run-manifest tracking)",
        base_model="unsloth/Meta-Llama-3.1-8B-Instruct",
        dataset_manifest_ids=[] if c["checkpoint_id"] != "orca-core-combined-v2" else ["orca-novus-combined-safety-calibration-v2"],
        training_config_summary="see docs/orneur/phase-0/MODEL_TRAINING_STATUS.md for full history",
        optimizer_state_available=False,
        scheduler_state_available=False,
        tokenizer_identity="unsloth/Meta-Llama-3.1-8B-Instruct",
        artifact_path=f"ollama://{c['legacy_ollama_name']}",
        artifact_checksum=c["artifact_checksum"],
        legacy_ollama_name=c["legacy_ollama_name"],
    )
    rec.save()
    reg.register(rec, family="novus", ollama_alias=c["legacy_ollama_name"])
    if c["checkpoint_id"] != "orca-core-combined-v2":
        reg.retire(c["checkpoint_id"], reason=f"historical import -- {c['note']}")
        print(f"[import] {c['checkpoint_id']} -> family=novus, RETIRED (historical), {c['note']}")
    else:
        print(f"[import] {c['checkpoint_id']} -> family=novus, EXPERIMENTAL (current candidate, pending full promotion evaluation), {c['note']}")

# --------------------------------------------------------------- Aeternum --
# Family definition only -- explicitly NOT a checkpoint. No trained artifact
# exists under any name, legacy or canonical.
reg.mark_family_absent("aeternum")
print("[import] aeternum -> family definition registered, NO checkpoint exists (by design, not an oversight)")

print("\n[done] historical import complete.")

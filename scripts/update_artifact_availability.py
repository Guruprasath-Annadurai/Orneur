"""
Phase 1.1: patches the checkpoint records imported in Phase 1 with real,
verified ArtifactAvailability states, replacing the ad-hoc
"UNVERIFIED_ARTIFACT_REMOVED_FROM_LOCAL_DISK" checksum-sentinel string with
the proper typed field. Also records the verified recovery of
orca-core-dpo's artifact from its Kaggle merge-export kernel.
"""
from __future__ import annotations

import subprocess

from orca.registry.checkpoint import ArtifactAvailability, CheckpointRecord


def _currently_installed_ollama_models() -> set[str]:
    result = subprocess.run(["ollama", "list"], capture_output=True, text=True, timeout=15)
    names = set()
    for line in result.stdout.splitlines()[1:]:  # skip header
        if line.strip():
            names.add(line.split()[0].split(":")[0])
    return names


installed = _currently_installed_ollama_models()
print(f"[check] currently installed Ollama models: {sorted(installed)}")

# ---------------------------------------------------------- Genesis (legacy) --
for checkpoint_id in ["orca-nano", "orca-nano-v4", "orca-nano-v7"]:
    rec = CheckpointRecord.load(checkpoint_id)
    if checkpoint_id in installed:
        rec.refresh_availability(artifact_path=None)  # can't verify checksum against a live Ollama blob directly here
        rec.availability = ArtifactAvailability.LOCAL.value  # verified present via `ollama list` above
        rec.availability_note = "Verified present in local Ollama store via `ollama list`."
    else:
        rec.availability = ArtifactAvailability.MISSING.value
        rec.availability_note = "Not found in local Ollama store as of this check."
    rec.save()
    print(f"[update] {checkpoint_id}: availability={rec.availability}")

# -------------------------------------------------------------------- Novus --

# orca-core-dpo: RECOVERED this phase. Verified via:
#   1. Downloaded from guruprasathannadurai/orca-core-dpo-merge-export-v1
#      (the documented, project-owned Kaggle kernel for this exact
#      checkpoint's merge+GGUF-export step -- confirmed COMPLETE status).
#   2. File size 4,920,738,816 bytes -- matches every other confirmed
#      Llama-3.1-8B Q4_K_M export in this project exactly.
#   3. Direct GGUF header parse: general.architecture=llama,
#      embedding_length=4096, block_count=32, attention.head_count=32,
#      head_count_kv=8 -- the exact Llama-3.1-8B signature.
#   4. SHA-256 computed fresh: no PRIOR recorded checksum exists to compare
#      against (Phase 1 only recorded the sentinel string), so this is the
#      first real checksum for this checkpoint, not a verified-unchanged
#      comparison -- documented honestly as such below.
# NOT re-imported into local Ollama (disk constraints on this machine) --
# state is REMOTE (verified recoverable, not currently locally loadable),
# not LOCAL.
core_dpo = CheckpointRecord.load("orca-core-dpo")
core_dpo.artifact_checksum = "sha256:3075a9bb064a63e4ea0d48be2378d6dc4fb08883724c58cee5489022b6d10873"
core_dpo.availability = ArtifactAvailability.REMOTE.value
core_dpo.recovery_source = "kaggle:guruprasathannadurai/orca-core-dpo-merge-export-v1"
core_dpo.availability_note = (
    "Phase 1.1: recovered and verified from its documented Kaggle merge-export "
    "kernel (status COMPLETE). File size (4,920,738,816 bytes) and GGUF header "
    "(architecture=llama, embedding_length=4096, block_count=32, GQA 32/8 heads) "
    "match the expected Llama-3.1-8B signature exactly. No prior checksum existed "
    "to compare against -- this is the first verified checksum recorded for this "
    "checkpoint, not a confirmed-unchanged comparison. Not currently re-imported "
    "to local Ollama (disk constraints) -- REMOTE, not LOCAL; not loadable as-is."
)
core_dpo.save()
print(f"[update] orca-core-dpo: availability={core_dpo.availability} (RECOVERED, verified)")

for checkpoint_id in ["orca-core-combined", "orca-core-combined-v2"]:
    rec = CheckpointRecord.load(checkpoint_id)
    if checkpoint_id in installed:
        rec.availability = ArtifactAvailability.LOCAL.value
        rec.availability_note = "Verified present in local Ollama store via `ollama list`."
    else:
        rec.availability = ArtifactAvailability.MISSING.value
    rec.save()
    print(f"[update] {checkpoint_id}: availability={rec.availability}")

print("\n[done] artifact availability states updated.")

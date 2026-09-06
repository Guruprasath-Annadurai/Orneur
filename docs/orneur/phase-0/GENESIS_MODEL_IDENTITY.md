# Genesis (nano) — Forensic Model Identity Verification

Performed by direct inspection of running artifacts, not by reading config files alone (config files are exactly what's in dispute).

## Method

`ollama show` was run against every locally-installed Genesis/nano Ollama model, which reports architecture metadata parsed directly from the GGUF file's own header (hidden size, parameter count, quantization) — this is ground truth about what was actually built, independent of what the training config *intended*.

## Evidence

```
$ ollama show orca-nano-v7
architecture        qwen2
parameters          7.6B
context length       32768
embedding length     3584
quantization         Q4_K_M

$ ollama show orca-nano        (same digest as orca-nano-v4, per `ollama list`)
architecture        qwen2
parameters          7.6B
context length       32768
embedding length     3584
quantization         Q4_K_M
```

Both installed checkpoints report **7.6B parameters**, embedding length 3584. This is definitively Qwen2.5-**7B**-class, not 3B — Qwen2.5-3B's embedding/hidden size is 2048, roughly half; a 3B model quantized at Q4_K_M would also be roughly half the file size of these ~4.7-4.9GB GGUF files.

## Historical checkpoint identity table

| Checkpoint | Evidence source | Determined identity |
|---|---|---|
| `orca-nano` (Ollama) | `ollama show` — 7.6B params, qwen2, embed 3584 | **Qwen2.5-7B-class — CONFIRMED** |
| `orca-nano-v4` (Ollama) | same digest as `orca-nano` per `ollama list` | **Qwen2.5-7B-class — CONFIRMED** (same artifact) |
| `orca-nano-v7` (Ollama) | `ollama show` — 7.6B params, qwen2, embed 3584 | **Qwen2.5-7B-class — CONFIRMED** |
| Any earlier Colab-only checkpoints (`orca_nano_finetune_colab*.ipynb` v1-v4) | Notebook base_model references only — no installed artifact available to inspect directly | **UNVERIFIED** — notebooks reference `unsloth/Qwen2.5-7B-Instruct` per `orca/train/variants.py`'s code value, consistent with the confirmed installed checkpoints, but not independently re-verified per-notebook in this pass |

## Root cause of the config ambiguity

Two live config files disagree with each other, and one disagrees with itself:

- `orca/train/variants.py`: the `VARIANTS` dict's actual code value is `base_model="unsloth/Qwen2.5-7B-Instruct"` — but the same file's own module docstring states "nano → Qwen2.5-3B-Instruct". **The docstring is wrong; the code value matches reality** (confirmed by the Ollama forensic evidence above).
- `orca/train/config.py`: `TrainingConfig.preset("nano")` independently sets `Qwen2.5-3B-Instruct` — this is a second, separate wrong value, in a different code path from `variants.py`.

## Conclusion

**Every existing, installed Genesis/nano checkpoint is Qwen2.5-7B-class, confirmed by direct GGUF metadata inspection, not by re-reading the disputed config files.** No 7B checkpoint has been or will be relabeled as 3B. These checkpoints remain what they are — legacy 7B-based Genesis training — and are preserved, not deleted or rewritten.

Per the final architectural decision (`ARCHITECTURAL_DECISIONS.md`), **future** Orneur Genesis training targets Qwen2.5-3B-class specifically to avoid role overlap with Novus's 8B tier. This is a decision about what to build *next*, not a correction applied retroactively to what already exists.

## Legacy checkpoint naming going forward

Existing checkpoints should be referred to going forward as e.g. `legacy-genesis-7b` (or an equivalent lineage-preserving name during the eventual Orca→Orneur migration) rather than silently assumed to be the new 3B canonical target. This distinction should be carried into `BRAND_MIGRATION_PLAN.md`'s lineage-mapping step.

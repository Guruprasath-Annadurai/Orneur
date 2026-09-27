"""Owner-setup calibration for the local semantic-overlap engine (orca.eval.genesis_v2.semantic).

Uses ONLY synthetic calibration fixtures defined in this file — never the future private QUALIFICATION_HOLDOUT or SCREEN, and never any
real V2 benchmark content. A small set of hand-authored paraphrase / non-paraphrase pairs across representative categories is scored with
the configured embedder; the resulting separation is used to sanity-check (not blindly trust) the engine's default threshold and record
the calibration's own limitations honestly (this is a small fixture set — it demonstrates gross semantic separation, not statistical
guarantees).
"""
from __future__ import annotations

import hashlib
import inspect
import json

# (text_a, text_b, is_paraphrase, category) — all synthetic, hand-authored, contain no real benchmark content.
CALIBRATION_FIXTURES = [
    ("The cat sat on the mat.", "A cat was sitting on the mat.", True, "reasoning"),
    ("She quickly finished her homework before dinner.", "Before dinner, she rapidly completed her homework.", True, "reasoning"),
    ("The function returns the sum of two integers.", "This function computes the total of two whole numbers.", True, "coding"),
    ("To sort the list, use the built-in sort method.", "You can order the list by calling its built-in sort method.", True, "coding"),
    ("The company's revenue grew by 12% last quarter.", "Last quarter, the firm's revenue increased by twelve percent.", True, "tool_use"),
    ("Water boils at 100 degrees Celsius at sea level.", "At sea level, water reaches its boiling point at 100C.", True, "reasoning"),
    ("Please schedule the meeting for next Tuesday at noon.", "Can you set up the meeting for next Tuesday around 12pm?", True, "tool_use"),
    ("The recipe calls for two cups of flour and one egg.", "You need two cups of flour and a single egg for this recipe.", True, "reasoning"),
    ("The stock market closed lower today amid inflation fears.", "Today the market dropped, driven by concerns over inflation.", True, "tool_use"),
    ("He debugged the null pointer exception in the parser.", "He fixed the null pointer error inside the parser code.", True, "coding"),
    ("The cat sat on the mat.", "Quarterly revenue grew by double digits.", False, "reasoning"),
    ("She quickly finished her homework before dinner.", "The recipe calls for two cups of flour.", False, "reasoning"),
    ("The function returns the sum of two integers.", "Water boils at 100 degrees Celsius at sea level.", False, "coding"),
    ("To sort the list, use the built-in sort method.", "The stock market closed lower today amid inflation fears.", False, "coding"),
    ("The company's revenue grew by 12% last quarter.", "He debugged the null pointer exception in the parser.", False, "tool_use"),
    ("Water boils at 100 degrees Celsius at sea level.", "Please schedule the meeting for next Tuesday at noon.", False, "reasoning"),
    ("Please schedule the meeting for next Tuesday at noon.", "The function returns the sum of two integers.", False, "tool_use"),
    ("The recipe calls for two cups of flour and one egg.", "The stock market closed lower today amid inflation fears.", False, "reasoning"),
    ("The stock market closed lower today amid inflation fears.", "She quickly finished her homework before dinner.", False, "tool_use"),
    ("He debugged the null pointer exception in the parser.", "The cat sat on the mat.", False, "coding"),
]

METRIC = "cosine"
CALIBRATION_DATASET = "synthetic-genesis-v2-calibration-fixtures/1"


def _code_sha256() -> str:
    return hashlib.sha256(inspect.getsource(inspect.getmodule(_code_sha256)).encode()).hexdigest()


def run_calibration(embedder, threshold: float, ambiguity_margin: float) -> dict:
    """Scores CALIBRATION_FIXTURES with `embedder`; reports separation at `threshold` and honest false-positive/negative counts.
    Does not mutate the engine's threshold — this is a sanity check the owner reviews, not an auto-tuner."""
    texts_a = [a for a, _, _, _ in CALIBRATION_FIXTURES]
    texts_b = [b for _, b, _, _ in CALIBRATION_FIXTURES]
    va = embedder.embed(texts_a)
    vb = embedder.embed(texts_b)
    scores = [sum(x * y for x, y in zip(p, q)) for p, q in zip(va, vb)]

    rows = []
    fp = fn = 0
    for (a, b, is_para, cat), s in zip(CALIBRATION_FIXTURES, scores):
        predicted_overlap = s >= threshold
        ambiguous = (threshold - ambiguity_margin) <= s < threshold
        if predicted_overlap and not is_para:
            fp += 1
        if (not predicted_overlap) and (not ambiguous) and is_para:
            fn += 1
        rows.append({"category": cat, "is_paraphrase": is_para, "score": round(s, 4),
                      "band": "OVERLAP" if predicted_overlap else ("AMBIGUOUS" if ambiguous else "DISTINCT")})

    result = {
        "schema_version": "genesis-v2-semantic-calibration/1",
        "metric": METRIC,
        "threshold": threshold,
        "ambiguity_margin": ambiguity_margin,
        "per_category_overrides": {},
        "calibration_dataset": CALIBRATION_DATASET,
        "calibration_code_sha256": _code_sha256(),
        "n_pairs": len(CALIBRATION_FIXTURES),
        "false_positive_count": fp,
        "false_negative_count": fn,
        "rows": rows,
        "limitation": ("Small hand-authored synthetic fixture set (20 pairs); demonstrates gross semantic-vs-unrelated separation for "
                       "sanity-checking the configured threshold. It is NOT a statistically powered calibration and does not bound "
                       "real-world false-positive/false-negative rates on the eventual private corpus."),
    }
    result["result_sha256"] = hashlib.sha256(json.dumps(result, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return result

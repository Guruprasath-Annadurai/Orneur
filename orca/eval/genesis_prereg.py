"""Build the Genesis Capability Eval V1 manifests and the pre-registration artifact (deterministic, CPU-only).

The pre-registration freezes: harness source hash, dataset and holdout manifest hashes, every corpus file hash, category definitions and counts,
floors with their statistical justification, the confidence-interval method, all funnel stages, caps, selection/tie/NO_MODEL_QUALIFIES rules and the
contamination policy. It is hashed as a whole. Running a candidate never writes to it; a substantive change requires Eval V2.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from orca.eval import foundation_landscape as FL
from orca.eval import genesis_contamination as CX
from orca.eval import genesis_corpus as GC
from orca.eval import genesis_eval_v1 as E
from orca.eval import genesis_funnel as GF
from orca.eval import genesis_sandbox as SB
from orca.eval import genesis_stats as ST
from orca.intelligence import protocol as P
from orca.intelligence import spec as SPEC

PH21 = "docs/orneur/phase-21"
MANIFEST_PATH = f"{PH21}/GENESIS_CAPABILITY_EVAL_V1_MANIFEST.json"
HOLDOUT_MANIFEST_PATH = f"{PH21}/GENESIS_CAPABILITY_EVAL_V1_HOLDOUT_MANIFEST.json"
EXCLUSION_MANIFEST_PATH = f"{PH21}/GENESIS_CAPABILITY_EVAL_V1_TRAINING_EXCLUSION_MANIFEST.json"
PREREG_JSON = f"{PH21}/GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION.json"
PREREG_MD = f"{PH21}/GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION.md"

HARNESS_FILES = ["orca/eval/genesis_eval_v1.py", "orca/eval/genesis_stats.py", "orca/eval/genesis_scorers.py", "orca/eval/genesis_harness.py",
                 "orca/eval/genesis_sandbox.py", "orca/eval/genesis_contamination.py", "orca/eval/genesis_funnel.py", "orca/eval/genesis_corpus.py",
                 "orca/eval/genesis_prereg.py", "orca/eval/genesis/gen_format.py", "orca/contracts/jsonutil.py", "orca/contracts/schema.py"]
STAGE1_PROBE_PER_CATEGORY = 30


def canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def harness_sha256(root: Path) -> str:
    return sha(canon([(p, GC.file_sha256(root / p)) for p in sorted(HARNESS_FILES)]))


def _self_hash(doc: dict, field: str) -> str:
    return sha(canon({k: v for k, v in doc.items() if k != field}))


def prereg_hash(doc: dict) -> str:
    return _self_hash(doc, "preregistration_sha256")


def _all_items(root: Path) -> list[dict]:
    return [it for s in E.SPLITS for it in GC.load_split(root, s)]


def _gating_holdout(items: list[dict], cat: str) -> list[dict]:
    spec = E.CATEGORY_SPECS[cat]
    rows = [i for i in items if i["category"] == cat and i["split"] == "HOLDOUT"]
    if spec.get("gating_slice"):
        rows = [i for i in rows if i["meta"].get("slice") == spec["gating_slice"]]
    return rows


def stage1_probe_ids(items: list[dict]) -> list[str]:
    """Deterministic, pre-registered Stage-1 probe: the first 30 holdout items of each gating category in ascending item-sha256 order."""
    ids: list[str] = []
    for cat in E.GATING_CATEGORIES:
        rows = sorted(_gating_holdout(items, cat), key=lambda i: i["sha256"])[:STAGE1_PROBE_PER_CATEGORY]
        ids += [r["item_id"] for r in rows]
    return ids


def build_manifest(root: Path) -> dict:
    base = root / GC.CORPUS_DIR
    items = _all_items(root)
    files = {name: GC.file_sha256(base / name) for name in (*GC.SPLIT_FILES.values(), GC.PROTOCOL_FILE, GC.FINGERPRINT_FILE)}
    files["images_aggregate"] = GC.images_aggregate_sha(base)
    counts: dict[str, Any] = {}
    for cat in E.CATEGORIES:
        c = {s: sum(1 for i in items if i["category"] == cat and i["split"] == s) for s in E.SPLITS}
        if cat == "long_context":
            c["holdout_slices"] = dict(Counter(i["meta"]["slice"] for i in items if i["category"] == cat and i["split"] == "HOLDOUT"))
        if cat == "multilingual":
            c["holdout_languages"] = dict(Counter(i["meta"]["language"] for i in items if i["category"] == cat and i["split"] == "HOLDOUT"))
        counts[cat] = c
    counts["latency"]["protocol_probes"] = len(GC.load_protocol(root))
    chance = {cat: round(sum(i["meta"]["chance"] for i in _gating_holdout(items, cat)) / len(_gating_holdout(items, cat)), 4)
              for cat in (*E.GATING_CATEGORIES, *E.REPORT_ONLY_CATEGORIES)}
    clusters = {cat: dict(sorted(Counter(i["meta"]["subtype"] for i in items if i["category"] == cat and i["split"] == "HOLDOUT").items()))
                for cat in E.CATEGORIES if any(i["category"] == cat and i["split"] == "HOLDOUT" for i in items)}
    boundary = CX.check_split_boundaries(items)
    doc = {
        "document": "GENESIS_CAPABILITY_EVAL_V1_MANIFEST", "eval_version": E.EVAL_VERSION, "corpus_version": E.CORPUS_VERSION, "corpus_dir": GC.CORPUS_DIR,
        "public_manifest_contains_answers": False,
        "authoring": {"source": "ORNEUR original; authored by Claude Sonnet 5 (Anthropic) on behalf of ORNEUR as seeded procedural generators",
                      "no_external_benchmark_text_copied": True, "training_data": False,
                      "note": "This corpus is evaluation data. It is separate from every ORNEUR training corpus and must never enter Genesis training."},
        "files_sha256": files, "split_counts": {s: sum(1 for i in items if i["split"] == s) for s in E.SPLITS},
        "category_counts": counts, "chance_baseline_by_category": chance, "template_clusters_holdout": clusters,
        "independence_note": "items are instances of a limited number of task templates; instances within a template are correlated, so nominal Wilson intervals "
                             "overstate the effective sample size (see template_clusters_holdout and the pre-registration uncertainties)",
        "contamination_report": {"exact_or_instance_duplicates_and_near_duplicates_and_boundary_violations": len(boundary["violations"]),
                                 "violations": boundary["violations"][:20], "ok": boundary["ok"],
                                 "near_duplicate": {"method": f"char {CX.NEAR_DUP_CHAR_NGRAM}-gram Jaccard >= {CX.NEAR_DUP_THRESHOLD} on instance text of dedup_kind=text items"}},
        "items": {s: [{"item_id": i["item_id"], "category": i["category"], "sha256": i["sha256"]} for i in items if i["split"] == s] for s in E.SPLITS},
    }
    doc["dataset_manifest_sha256"] = _self_hash(doc, "dataset_manifest_sha256")
    return doc


def build_holdout_manifest(root: Path, manifest: dict) -> dict:
    hold = manifest["items"]["HOLDOUT"]
    doc = {"document": "GENESIS_CAPABILITY_EVAL_V1_HOLDOUT_MANIFEST", "eval_version": E.EVAL_VERSION, "contains_answers": False, "contains_prompts": False,
           "item_count": len(hold), "items": hold, "holdout_file_sha256": manifest["files_sha256"][GC.SPLIT_FILES["HOLDOUT"]],
           "fingerprint_file_sha256": manifest["files_sha256"][GC.FINGERPRINT_FILE],
           "stage1_probe_ids": stage1_probe_ids(_all_items(root)),
           "allowed_purposes": list(E.HOLDOUT_ALLOWED_PURPOSES), "forbidden_purposes": list(E.HOLDOUT_FORBIDDEN_PURPOSES)}
    doc["stage1_probe_manifest_sha256"] = sha(canon(doc["stage1_probe_ids"]))
    doc["private_holdout_manifest_sha256"] = _self_hash(doc, "private_holdout_manifest_sha256")
    return doc


def build_exclusion_manifest(root: Path, holdout_manifest: dict) -> dict:
    fps = json.loads((root / GC.CORPUS_DIR / GC.FINGERPRINT_FILE).read_text())
    screened = CX.screen_repo_training_corpora(root, fps)
    doc = {"document": "GENESIS_CAPABILITY_EVAL_V1_TRAINING_EXCLUSION_MANIFEST", "eval_version": E.EVAL_VERSION,
           "rule": "No private holdout item, prompt, answer, paraphrase or n-gram window may enter any Genesis training, adaptation, distillation, few-shot, "
                   "router-tuning, threshold-tuning or debugging data. Any contamination invalidates this eval version.",
           "excluded_item_ids_sha256": sha(canon([i["item_id"] + ":" + i["sha256"] for i in holdout_manifest["items"]])),
           "excluded_item_count": holdout_manifest["item_count"], "fingerprint_file": f"{GC.CORPUS_DIR}/{GC.FINGERPRINT_FILE}",
           "fingerprint_file_sha256": holdout_manifest["fingerprint_file_sha256"],
           "fingerprint_method": f"sha256-truncated-32-bit hashes of word {CX.TRAIN_NGRAM}-grams of the prompt tail and the answer text; contains no holdout text",
           "screen_threshold_fraction_of_item_ngrams": CX.TRAIN_OVERLAP_THRESHOLD, "screening_function": "orca.eval.genesis_contamination.screen_training_texts",
           "semantic_overlap": CX.run_semantic_check(None, [], []),
           "existing_training_corpora_screened": {p: {"records": v["records"], "flagged_count": len(v["flagged"])} for p, v in screened.items()},
           "existing_training_corpora_clean": all(not v["flagged"] for v in screened.values())}
    doc["exclusion_manifest_sha256"] = _self_hash(doc, "exclusion_manifest_sha256")
    return doc


def _floors_block(items: list[dict], manifest: dict) -> dict:
    out = {}
    for cat in E.GATING_CATEGORIES:
        spec = E.CATEGORY_SPECS[cat]
        rows = _gating_holdout(items, cat)
        n = len(rows)
        floor = spec["floor"]
        chance = manifest["chance_baseline_by_category"][cat]
        out[cat] = {
            "floor": floor, "why": spec["why"], "gating_slice": spec.get("gating_slice", "ALL"), "sample_count": n, "low_power": n < E.LOW_POWER_N,
            "chance_baseline": chance, "margin_over_chance": round(floor - chance, 3),
            "wilson95_half_width_at_floor": round(ST.wilson(floor * n, n)[1] - floor, 3),
            "false_drop_probability_at_floor_stage2": round(ST.prob_dropped(floor, n, floor), 4),
            "min_detectable_true_rate_80pct_power_full_holdout": ST.min_detectable_true_rate(floor, n),
            "stage1_probe_n": E.STAGE1_MIN_N, "min_detectable_true_rate_80pct_power_stage1": ST.min_detectable_true_rate(floor, E.STAGE1_MIN_N),
            "ci_policy": f"{ST.CI_METHOD} on the mean item score; n >= {E.LOW_POWER_N} is adequately powered",
            "low_power_handling": "n < 100: may only FAIL a model, and only when the 95% upper bound < floor; otherwise INCONCLUSIVE_LOW_POWER (never a pass, never a ranking signal)",
            "failure_semantics": "INCOMPLETE => cannot be judged (fail closed); adequately powered: FAIL iff point estimate < floor; Stage 1: drop iff upper95 < floor with probe slice n >= 30",
        }
    return out


PROPOSED_FLOORS_SUPERSEDED = {"instruction_following": 0.70, "structured_outputs": 0.85, "reasoning": 0.50, "coding": 0.40, "mathematics": 0.50, "research": 0.50,
                              "tool_use": 0.60, "long_context_8k": 0.60, "multilingual": 0.50, "verification": 0.60, "evidence_use": 0.60,
                              "counterfactual_reasoning": 0.40, "hypothesis_testing": 0.40, "information_gain_reasoning": 0.40}


def build_prereg(root: Path, manifest: dict, holdout: dict, exclusion: dict) -> dict:
    items = _all_items(root)
    funnel = GF.funnel_spec()
    doc: dict[str, Any] = {
        "document": "GENESIS_CAPABILITY_EVAL_V1_PREREGISTRATION", "eval_version": E.EVAL_VERSION, "corpus_version": E.CORPUS_VERSION,
        "architecture_version": SPEC.ARCHITECTURE_VERSION, "protocol_version": P.PROTOCOL_VERSION, "scorer_version": E.SCORER_VERSION,
        "harness_sha": harness_sha256(root), "harness_files": sorted(HARNESS_FILES),
        "dataset_manifest_sha": manifest["dataset_manifest_sha256"], "dataset_manifest_file_sha256": sha((root / MANIFEST_PATH).read_text(encoding="utf-8")),
        "private_holdout_manifest_sha": holdout["private_holdout_manifest_sha256"], "training_exclusion_manifest_sha": exclusion["exclusion_manifest_sha256"],
        "corpus_file_sha256": manifest["files_sha256"],
        "category_definitions": {c: {"role": E.CATEGORY_SPECS[c]["role"], "floor": E.CATEGORY_SPECS[c]["floor"], "why": E.CATEGORY_SPECS[c]["why"]} for c in E.CATEGORIES},
        "item_counts": manifest["category_counts"], "split_counts": manifest["split_counts"],
        "gating_categories": list(E.GATING_CATEGORIES), "report_only_categories": list(E.REPORT_ONLY_CATEGORIES), "protocol_categories": list(E.PROTOCOL_CATEGORIES),
        "strict_contracts_role": "report-only recovery-cost signal; never a floor and never a ranking input",
        "floors": _floors_block(items, manifest),
        "floors_supersede_design_proposals": {"proposed_in_design_doc": PROPOSED_FLOORS_SUPERSEDED,
                                              "reason": "the design-time proposals were unreviewed round numbers; the frozen floors are set from item difficulty, chance baselines and the "
                                                        "power arithmetic recorded per category. Every frozen floor is at least 0.10 above the category's chance baseline."},
        "confidence_interval_method": {"name": ST.CI_METHOD, "z": ST.Z95, "applied_to": "mean item score", "low_power_n": E.LOW_POWER_N,
                                       "stage1_min_probe_n": E.STAGE1_MIN_N, "decisions_use_nominal_intervals": True,
                                       "note": "nominal Wilson intervals; template clustering is reported, not used in decisions (see uncertainties)"},
        "scoring": {"deterministic": True, "model_or_human_judges_used": False, "methods": sorted({i["scoring_method"] for i in items}),
                    "json_categories_accept_one_fenced_block": True, "raw_format_cleanliness_recorded_not_penalised_outside_strict_contracts": True,
                    "code_items": "PENDING_SANDBOX in this phase: never executed; coding is INCOMPLETE until an attested hermetic sandbox scores it",
                    "discovery_scoring": "anchor-matching against ground-truth evidence anchors and decoys; keyword checks for falsifier/action are diagnostics only"},
        "stage0_checks": ["tokenizer_round_trip_on_fixed_multilingual_probe", "chat_template_renders_system_user_tool_and_thinking_modes",
                          "config_and_architecture_load_on_cpu_under_pinned_runtime", "exact_40_hex_revision_pinned", "all_weight_shard_hashes_verified",
                          "license_text_archived", "context_length_recorded_config_vs_vendor", "architecture_supported_by_pinned_runtime_version"],
        "stage1": {**funnel["stages"][1], "probe": {"per_gating_category": E.STAGE1_MIN_N, "selection": "first 30 holdout items of each gating category in ascending item-sha256 order",
                                                     "probe_ids_manifest_sha256": holdout["stage1_probe_manifest_sha256"], "probe_items": len(holdout["stage1_probe_ids"])},
                   "drop_rule": "drop only if the 95% upper bound of a gating slice with n >= 30 is below its frozen floor; report-only and LOW_POWER slices never drop a model"},
        "stage2": {**funnel["stages"][2], "family_name_carries_no_priority": True,
                   "over_cap_order": "family representatives (cheapest per family, ties by model id) ordered by projected cost then model id, admitted while the cap permits; then remaining survivors by ascending cost then id",
                   "incomplete_results": "a candidate missing, NaN, infinite, boolean or out-of-range on any mandatory gating category is INCOMPLETE and cannot enter Stage 3 (IncompleteStage2Results)",
                   "mandatory_gating_categories": list(E.MANDATORY_STAGE2_GATING)},
        "stage3": {**funnel["stages"][3], "max_finalists": GF.STAGE3_MAX_FINALISTS, "pilot_protocol_id": GF.PILOT_PROTOCOL_ID,
                   "pilot_training_split": "PILOT_TRAIN", "pilot_categories": list(E.PILOT_CATEGORIES), "regression_categories": list(E.TRAINABILITY_REGRESSION_CATEGORIES),
                   "no_selection_until_all_finalists_complete_same_pilot": True},
        "cost_caps_usd": {"stage1_per_model_gpu_hours": GF.STAGE1_MAX_GPU_HOURS_PER_MODEL, "stage1_total_for_15_models": GF.stage1_cap_usd(15),
                          "stage2_total": GF.STAGE2_COST_CAP_USD, "stage3_total": GF.STAGE3_COST_CAP_USD, "h100_usd_per_hour": FL.H100_USD_PER_HOUR,
                          "kind": "PLANNING_ONLY_NOT_AUTHORIZATION"},
        "selection_rule": FL.SELECTION_RULE, "ranking_order": list(GF.RANKING_ORDER),
        "tie_rule": "if two or more finalists are identical on verification, evidence_use, trainability and cost, the result is OWNER_DECISION_REQUIRED_TIE; no automatic tie-break by name, size, date or popularity",
        "no_model_qualifies_rule": "if no finalist clears every frozen floor the result is NO_MODEL_QUALIFIES: nothing is selected, floors are never lowered after the fact (that requires Eval V2), and the owner decides the next step",
        "contamination_policy": {"private_holdout_forbidden_purposes": list(E.HOLDOUT_FORBIDDEN_PURPOSES), "allowed_purposes": list(E.HOLDOUT_ALLOWED_PURPOSES),
                                 "any_contamination_invalidates_this_eval_version": True, "checks": ["exact duplicate", "near duplicate (instance text)", "instance-key uniqueness",
                                                                                                    "8-gram overlap against training corpora", "semantic overlap hook (protocol; not configured)",
                                                                                                    "split-boundary check (ids, hashes, private flag)"],
                                 "few_shot_source": "DEV split only", "training_exclusion_manifest": EXCLUSION_MANIFEST_PATH},
        "splits": {"DEV": "eval development examples (harness/prompt development, few-shot)", "PILOT_TRAIN": "pilot-training examples for the Stage-3 trainability pilot only",
                   "HOLDOUT": "private qualification holdout; QUALIFICATION only"},
        "languages": {"included": list(E.LANGUAGES), "additional_languages_included": E.ADDITIONAL_LANGUAGES_INCLUDED,
                      "authoring_note": "language-appropriate items authored per language (not word-for-word translations); native-speaker review has NOT been performed"},
        "sandbox_requirements": SB.SANDBOX_REQUIREMENTS, "sandbox_version": SB.SANDBOX_VERSION,
        "reproducibility": {"run_provenance_fields": ["model_revision", "tokenizer_revision", "runtime_name", "runtime_version", "harness_sha256", "dataset_manifest_sha256",
                                                      "holdout_manifest_sha256", "preregistration_sha256", "sampling_config", "hardware", "started_at"],
                            "run_records_are_write_once": True, "prereg_verified_before_any_run": True, "run_must_not_modify_preregistration": True},
        "immutability": "any substantive change to any hashed input (corpus, floors, rules, harness, scorers) requires Eval V2",
        "GENESIS_CAPABILITY_EVAL_V1_FROZEN": False,
        "design_level_readiness_historical": {"GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY": True,
                                              "meaning": "the funnel DESIGN was structurally ready (Eternal Architecture 1.1 pre-freeze check). It is not the freeze of the actual eval."},
        "freeze": {"corpus_complete": True, "floors_finalized": True, "manifests_complete": True, "hashes_frozen": True, "preregistration_hashed": True,
                   "harness_tests_pass": "PENDING_EXACT_SHA_CI", "exact_sha_ci_passes": False, "independent_audit_passed": False, "audit_passed": False,
                   "frozen_only_when": ["corpus complete", "floors frozen", "manifests complete", "hashes frozen", "pre-registration frozen", "harness tests pass",
                                        "exact-SHA CI passes", "independent ChatGPT audit passes"]},
        "authorizations": {"foundation_selected": False, "gpu_authorized": False, "training_authorized": False, "provider_inference_authorized": False,
                           "phase_21c_authorized": False, "spending_authorized": False},
        "model_inference_performed_in_this_phase": False, "candidate_runs": 0,
        "remaining_uncertainties": [
            "items are template instances; correlated within template, so nominal intervals overstate power (cluster sizes in the manifest)",
            "floors are reasoned from chance baselines and task design, not from any model result; they may reject every model or none",
            "Hindi/Tamil/Kannada items were authored by an AI assistant and have not been reviewed by native speakers",
            "the coding category cannot be scored until an attested hermetic sandbox exists; until then Stage 2 cannot complete",
            "semantic-overlap checking is a protocol hook only; no embedding model is configured",
            "long-context lengths are approximate (fixed words-per-token ratio); tokenizer-specific lengths differ",
            "the Stage-1 GPU-time cap of 0.25 h per model is a planning assumption, unmeasured",
            "discovery scoring uses evidence anchors plus keyword diagnostics, which is brittle for paraphrased falsifiers and actions",
        ],
    }
    doc["preregistration_sha256"] = prereg_hash(doc)
    return doc


def prereg_markdown(doc: dict) -> str:
    L = ["# Genesis Capability Eval V1 — Pre-registration", "",
         f"- Eval version: `{doc['eval_version']}`; corpus `{doc['corpus_version']}`; architecture `{doc['architecture_version']}`; protocol `{doc['protocol_version']}`",
         f"- **Pre-registration SHA-256:** `{doc['preregistration_sha256']}`",
         f"- Harness SHA-256: `{doc['harness_sha']}`", f"- Dataset manifest SHA-256: `{doc['dataset_manifest_sha']}`",
         f"- Private holdout manifest SHA-256: `{doc['private_holdout_manifest_sha']}`", f"- Training-exclusion manifest SHA-256: `{doc['training_exclusion_manifest_sha']}`", "",
         "## Status", "",
         "`GENESIS_CAPABILITY_EVAL_V1_FROZEN = false`", "",
         "The earlier design-level `GENESIS_CAPABILITY_EVAL_V1_FREEZE_READY = true` is recorded historically and means only that the funnel *design* was structurally ready. "
         "The actual evaluation becomes frozen only when: " + "; ".join(doc["freeze"]["frozen_only_when"]) + ". Exact-SHA CI and the independent audit are pending.", "",
         "No model has been run. `foundation_selected=false`, `gpu_authorized=false`, `training_authorized=false`, `provider_inference_authorized=false`, `phase_21c_authorized=false`, "
         "no spending authorized.", "",
         "## Corpus (private; no answers appear in this document)", "",
         "Original ORNEUR-authored seeded procedural items; no external benchmark text copied. Corpus files live under `eval_private/genesis_capability_eval_v1/` and are excluded from the "
         "container build context. Splits: DEV (eval development), PILOT_TRAIN (Stage-3 pilot only), HOLDOUT (private qualification).", "",
         "| Category | Role | DEV | PILOT_TRAIN | HOLDOUT |", "|---|---|---|---|---|"]
    for c in E.CATEGORIES:
        n = doc["item_counts"][c]
        L.append(f"| `{c}` | {E.CATEGORY_SPECS[c]['role']} | {n['DEV']} | {n['PILOT_TRAIN']} | {n['HOLDOUT']} |")
    L += ["", f"Totals: { {s: doc['split_counts'][s] for s in E.SPLITS} }. Latency uses {doc['item_counts']['latency']['protocol_probes']} protocol probes; cost and trainability are protocol definitions with no Q&A items.", "",
          "## Frozen floors (gating categories)", "",
          "Wilson 95% intervals on the mean item score. Adequately powered (n >= 100): FAIL iff the point estimate is below the floor. LOW_POWER (n < 100): may only FAIL, "
          "and only when the upper bound is below the floor. INCOMPLETE results fail closed. Stage 1 drops a model only when the upper bound of a 30-item slice is below the floor.", "",
          "| Category | Floor | n | Chance | Margin | Wilson half-width at floor | Min detectable true rate (80% power, full) | (Stage 1, n=30) | Why |", "|---|---|---|---|---|---|---|---|---|"]
    for c in E.GATING_CATEGORIES:
        f = doc["floors"][c]
        L.append(f"| `{c}` | {f['floor']} | {f['sample_count']} | {f['chance_baseline']} | {f['margin_over_chance']} | {f['wilson95_half_width_at_floor']} | "
                 f"{f['min_detectable_true_rate_80pct_power_full_holdout']} | {f['min_detectable_true_rate_80pct_power_stage1']} | {f['why']} |")
    L += ["", "Report-only categories (never floors, never ranking): " + ", ".join(f"`{c}`" for c in doc["report_only_categories"]) + ". "
          "`strict_contracts` is a report-only recovery-cost signal.", "",
          "The design-time proposals (e.g. `instruction_following` 0.70, `structured_outputs` 0.85) are superseded; see `floors_supersede_design_proposals` in the JSON.", "",
          "## Funnel and rules", "",
          "Stage 0 CPU checks: " + "; ".join(doc["stage0_checks"]) + ".", "",
          f"Stage 1: all Stage-0-compatible models; probe = first {E.STAGE1_MIN_N} holdout items per gating category by item hash ({doc['stage1']['probe']['probe_items']} items); cap "
          f"{doc['cost_caps_usd']['stage1_per_model_gpu_hours']} GPU-h per model. Stage 2: survivors within USD {doc['cost_caps_usd']['stage2_total']}; a family name carries no priority; "
          "incomplete results are rejected. Stage 3: up to 3 finalists chosen from pre-trainability criteria; no selection until every finalist completes the same pilot.", "",
          "Selection rule: " + doc["selection_rule"], "", "Tie rule: " + doc["tie_rule"], "", "NO_MODEL_QUALIFIES: " + doc["no_model_qualifies_rule"], "",
          "## Contamination policy", "",
          "The private holdout may be used for QUALIFICATION only; never for " + ", ".join(doc["contamination_policy"]["private_holdout_forbidden_purposes"]) + ". Any contamination invalidates this eval "
          "version. Checks: " + "; ".join(doc["contamination_policy"]["checks"]) + ".", "",
          "## Remaining uncertainties", ""] + [f"- {u}" for u in doc["remaining_uncertainties"]] + [""]
    return "\n".join(L)


def write_all(root: Path) -> dict:
    """Write corpus, manifests, pre-registration JSON/MD. Order matters: each hash is computed from files already written."""
    stats = GC.write_corpus(root)
    manifest = build_manifest(root)
    (root / MANIFEST_PATH).write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    holdout = build_holdout_manifest(root, manifest)
    (root / HOLDOUT_MANIFEST_PATH).write_text(json.dumps(holdout, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    exclusion = build_exclusion_manifest(root, holdout)
    (root / EXCLUSION_MANIFEST_PATH).write_text(json.dumps(exclusion, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    prereg = build_prereg(root, manifest, holdout, exclusion)
    (root / PREREG_JSON).write_text(json.dumps(prereg, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    (root / PREREG_MD).write_text(prereg_markdown(prereg), encoding="utf-8")
    return {"corpus": stats, "preregistration_sha256": prereg["preregistration_sha256"], "dataset_manifest_sha256": manifest["dataset_manifest_sha256"],
            "private_holdout_manifest_sha256": holdout["private_holdout_manifest_sha256"], "harness_sha": prereg["harness_sha"],
            "training_exclusion_manifest_sha256": exclusion["exclusion_manifest_sha256"]}

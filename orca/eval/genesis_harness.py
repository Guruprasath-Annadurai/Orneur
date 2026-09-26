"""CPU-side harness for Genesis Capability Eval V1.

It makes NO inference: the generation backend is an injected callable and the default raises NoInferenceBackend. Everything a future run needs is
here: exact output capture, sampling/revision/hardware/runtime recording, timing hooks, per-item scoring, per-category aggregation with confidence
intervals and LOW_POWER handling, raw-result preservation, fail-closed missing-result behaviour, cost accounting hooks and pre-registration
verification. No candidate model name appears in this module.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from orca.eval import genesis_corpus as GC
from orca.eval import genesis_eval_v1 as E
from orca.eval import genesis_scorers as S
from orca.eval import genesis_stats as ST
from orca.eval.foundation_landscape import H100_USD_PER_HOUR


class NoInferenceBackend(RuntimeError):
    """The default backend. This phase performs no model inference."""


class PreregistrationViolation(RuntimeError):
    """Raised when the frozen pre-registration, harness, manifests or corpus do not match what was pre-registered."""


class HoldoutPurposeViolation(PermissionError):
    """Raised when the private holdout is opened for anything except QUALIFICATION."""


def _canon(o: Any) -> str:
    return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ data classes
@dataclass(frozen=True)
class SamplingConfig:
    temperature: float
    top_p: float
    max_new_tokens: int
    seed: int | None
    stop: tuple[str, ...] = ()
    label: str = "default"

    def digest(self) -> str:
        return _sha(_canon(asdict(self)))


@dataclass(frozen=True)
class GenerationResult:
    text: str
    first_token_s: float | None = None
    end_to_end_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None


@dataclass(frozen=True)
class RunProvenance:
    """Immutable provenance: everything needed to attribute and reproduce a run."""

    model_revision: str
    tokenizer_revision: str
    runtime_name: str
    runtime_version: str
    harness_sha256: str
    dataset_manifest_sha256: str
    holdout_manifest_sha256: str
    preregistration_sha256: str
    sampling_config: Mapping[str, Any]
    hardware: Mapping[str, Any]
    started_at: str
    purpose: str = "QUALIFICATION"

    def problems(self) -> list[str]:
        out = []
        for k in ("model_revision", "tokenizer_revision", "runtime_name", "runtime_version", "harness_sha256", "dataset_manifest_sha256",
                  "holdout_manifest_sha256", "preregistration_sha256", "started_at"):
            if not getattr(self, k):
                out.append(f"{k} is required")
        if not self.sampling_config:
            out.append("sampling_config is required")
        if not self.hardware:
            out.append("hardware is required")
        return out

    def digest(self) -> str:
        return _sha(_canon(asdict(self)))


class CostLedger:
    """Cost accounting hook: GPU-seconds x rate. The rate defaults to the program's persisted H100 list rate (planning constant)."""

    def __init__(self, usd_per_hour: float = H100_USD_PER_HOUR):
        self.usd_per_hour = usd_per_hour
        self.gpu_seconds = 0.0

    def add_gpu_seconds(self, seconds: float) -> None:
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("gpu seconds must be finite and non-negative")
        self.gpu_seconds += seconds

    @property
    def usd(self) -> float:
        return round(self.gpu_seconds / 3600.0 * self.usd_per_hour, 6)


# ------------------------------------------------------------------ pre-registration verification
def verify_preregistration(root: Path, prereg_path: Path) -> dict:
    """Recompute every hash the pre-registration froze. Any mismatch raises PreregistrationViolation; nothing is written or modified."""
    from orca.eval import genesis_prereg as PR

    doc = json.loads(prereg_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if PR.prereg_hash(doc) != doc.get("preregistration_sha256"):
        problems.append("preregistration_sha256 does not match the artifact's content")
    if PR.harness_sha256(root) != doc.get("harness_sha"):
        problems.append("harness source no longer matches the pre-registered harness_sha")
    man_path = root / PR.MANIFEST_PATH
    if _sha(man_path.read_text(encoding="utf-8")) != doc.get("dataset_manifest_file_sha256"):
        problems.append("dataset manifest file changed")
    manifest = json.loads(man_path.read_text(encoding="utf-8"))
    if manifest.get("dataset_manifest_sha256") != doc.get("dataset_manifest_sha"):
        problems.append("dataset_manifest_sha mismatch")
    hold_path = root / PR.HOLDOUT_MANIFEST_PATH
    hm = json.loads(hold_path.read_text(encoding="utf-8"))
    if hm.get("private_holdout_manifest_sha256") != doc.get("private_holdout_manifest_sha"):
        problems.append("private_holdout_manifest_sha mismatch")
    for rel, want in doc.get("corpus_file_sha256", {}).items():
        p = root / GC.CORPUS_DIR / rel
        got = GC.images_aggregate_sha(root / GC.CORPUS_DIR) if rel == "images_aggregate" else (GC.file_sha256(p) if p.exists() else None)
        if got != want:
            problems.append(f"corpus file {rel} changed or missing")
    if doc.get("eval_version") != E.EVAL_VERSION:
        problems.append("eval_version mismatch")
    if doc.get("GENESIS_CAPABILITY_EVAL_V1_FROZEN") is not False and doc.get("freeze", {}).get("audit_passed") is not True:
        problems.append("artifact claims FROZEN without the recorded freeze conditions")
    if problems:
        raise PreregistrationViolation("; ".join(problems))
    return doc


def open_split(root: Path, split: str, purpose: str) -> list[dict]:
    """The only sanctioned way to read a split. HOLDOUT may be opened for QUALIFICATION only."""
    if split == "HOLDOUT" and purpose not in E.HOLDOUT_ALLOWED_PURPOSES:
        raise HoldoutPurposeViolation(f"the private holdout may never be used for {purpose}; allowed: {E.HOLDOUT_ALLOWED_PURPOSES}. "
                                      "Any contamination invalidates this eval version.")
    if split == "PILOT_TRAIN" and purpose not in ("PILOT_TRAINING", "DEV_EXAMPLES"):
        raise HoldoutPurposeViolation("PILOT_TRAIN is for the trainability pilot only")
    return GC.load_split(root, split)


def few_shot_examples(root: Path, category: str, k: int) -> list[dict]:
    """Few-shot examples come from DEV only, never from the holdout."""
    return [it for it in GC.load_split(root, "DEV") if it["category"] == category][:k]


# ------------------------------------------------------------------ running
def _default_backend(prompt: str, sampling: SamplingConfig) -> GenerationResult:
    raise NoInferenceBackend("this harness performs no inference in this phase; inject a backend callable")


@dataclass
class ItemRecord:
    item_id: str
    item_sha256: str
    category: str
    split: str
    prompt_sha256: str
    response_raw: str | None
    status: str                      # SCORED | PENDING_SANDBOX | MISSING | ERROR | UNSCORABLE
    score: float | None
    score_detail: dict
    scorer_version: str
    first_token_s: float | None = None
    end_to_end_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    error: str | None = None
    meta: dict = field(default_factory=dict)


class Harness:
    def __init__(self, root: Path, prereg_path: Path, provenance: RunProvenance, sampling: SamplingConfig,
                 backend: Callable[[str, SamplingConfig], GenerationResult] = _default_backend, clock: Callable[[], float] = time.monotonic,
                 sandbox: S.SandboxExecutor | None = None, cost: CostLedger | None = None):
        self.root, self.prereg_path, self.provenance, self.sampling = root, prereg_path, provenance, sampling
        self.backend, self.clock, self.sandbox = backend, clock, sandbox
        self.cost = cost or CostLedger()
        self.prereg = verify_preregistration(root, prereg_path)          # fail closed BEFORE anything runs
        pv = provenance.problems()
        if pv:
            raise PreregistrationViolation("incomplete run provenance: " + "; ".join(pv))
        for k, want in (("harness_sha256", self.prereg["harness_sha"]), ("dataset_manifest_sha256", self.prereg["dataset_manifest_sha"]),
                        ("holdout_manifest_sha256", self.prereg["private_holdout_manifest_sha"]), ("preregistration_sha256", self.prereg["preregistration_sha256"])):
            if getattr(provenance, k) != want:
                raise PreregistrationViolation(f"provenance {k} does not match the pre-registration")
        if provenance.purpose not in E.HOLDOUT_ALLOWED_PURPOSES:
            raise HoldoutPurposeViolation(provenance.purpose)
        if provenance.sampling_config != asdict(sampling):
            raise PreregistrationViolation("provenance sampling_config differs from the sampling configuration in use")

    def run_item(self, item: Mapping[str, Any]) -> ItemRecord:
        prompt = GC.item_prompt(item)
        base = dict(item_id=item["item_id"], item_sha256=item["sha256"], category=item["category"], split=item["split"],
                    prompt_sha256=_sha(prompt), scorer_version=E.SCORER_VERSION, meta={"slice": (item.get("meta") or {}).get("slice"),
                                                                                     "language": (item.get("meta") or {}).get("language"),
                                                                                     "subtype": (item.get("meta") or {}).get("subtype")})
        t0 = self.clock()
        try:
            gen = self.backend(prompt, self.sampling)
        except NoInferenceBackend:
            raise
        except Exception as e:                                             # a backend failure is a recorded failure, never a silent zero
            return ItemRecord(response_raw=None, status="ERROR", score=None, score_detail={}, error=repr(e), **base)
        elapsed = gen.end_to_end_s if gen.end_to_end_s is not None else self.clock() - t0
        self.cost.add_gpu_seconds(max(0.0, elapsed))
        if gen.error is not None or gen.text is None:
            return ItemRecord(response_raw=gen.text, status="ERROR", score=None, score_detail={}, error=gen.error or "no text", **base)
        res = S.score_item(item, gen.text, self.sandbox)
        return ItemRecord(response_raw=gen.text, status=res["status"], score=res["score"], score_detail=res["detail"], first_token_s=gen.first_token_s,
                          end_to_end_s=elapsed, prompt_tokens=gen.prompt_tokens, completion_tokens=gen.completion_tokens, **base)

    def run(self, items: Sequence[Mapping[str, Any]], out_path: Path) -> list[ItemRecord]:
        """Run every item and write raw records append-only. The file is created exclusively: an existing run record is never overwritten."""
        records: list[ItemRecord] = []
        with open(out_path, "x", encoding="utf-8") as f:
            f.write(_canon({"record_type": "run_provenance", "provenance": asdict(self.provenance), "provenance_digest": self.provenance.digest()}) + "\n")
            for it in items:
                rec = self.run_item(it)
                records.append(rec)
                f.write(_canon({"record_type": "item", **asdict(rec)}) + "\n")
        return records


# ------------------------------------------------------------------ aggregation (fail closed)
def _slice_items(cat: str, records: Sequence[ItemRecord]) -> dict[str, list[ItemRecord]]:
    rs = [r for r in records if r.category == cat]
    out = {"ALL": rs}
    if cat == "long_context":
        for sl in E.CATEGORY_SPECS[cat]["slices"]:
            out[sl] = [r for r in rs if r.meta.get("slice") == sl]
    if cat == "multilingual":
        for lang in E.LANGUAGES:
            out[lang] = [r for r in rs if r.meta.get("language") == lang]
    return out


def expected_counts(holdout_items: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    exp: dict[str, dict[str, int]] = {}
    for it in holdout_items:
        d = exp.setdefault(it["category"], {"ALL": 0})
        d["ALL"] += 1
        sl, lang = (it.get("meta") or {}).get("slice"), (it.get("meta") or {}).get("language")
        if it["category"] == "long_context" and sl:
            d[sl] = d.get(sl, 0) + 1
        if it["category"] == "multilingual" and lang:
            d[lang] = d.get(lang, 0) + 1
    return exp


def aggregate_run(records: Sequence[ItemRecord], holdout_items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Per-category aggregation against the FULL expected item list. Missing, errored, pending or unscored items make the category INCOMPLETE."""
    by_id = {r.item_id: r for r in records}
    exp = expected_counts(holdout_items)
    result: dict[str, Any] = {}
    for cat in E.CATEGORIES:
        if cat not in exp:
            continue
        cat_items = [it for it in holdout_items if it["category"] == cat]
        scores: dict[str, list[float | None]] = {"ALL": []}
        for it in cat_items:
            rec = by_id.get(it["item_id"])
            s = rec.score if (rec is not None and rec.status == "SCORED") else None
            scores["ALL"].append(s)
            for key in ("slice", "language"):
                tag = (it.get("meta") or {}).get(key)
                if tag and ((key == "slice" and cat == "long_context") or (key == "language" and cat == "multilingual")):
                    scores.setdefault(tag, []).append(s)
        spec = E.CATEGORY_SPECS[cat]
        aggs = {k: ST.category_aggregate(v, exp[cat][k], low_power_n=E.LOW_POWER_N) for k, v in scores.items()}
        gating_key = spec.get("gating_slice", "ALL")
        entry: dict[str, Any] = {"role": spec["role"], "slices": aggs, "gating_slice": gating_key, "unscored_statuses": sorted({r.status for r in records if r.category == cat and r.status != "SCORED"})}
        if spec["role"] == "GATING":
            entry["floor"] = spec["floor"]
            entry["decision"] = ST.floor_decision(aggs[gating_key], spec["floor"])
        result[cat] = entry
    return result


def to_stage2_capability(agg: Mapping[str, Any]) -> dict[str, float | None]:
    """Funnel input: the gating-slice mean, or None when INCOMPLETE (which the funnel rejects: it never imputes)."""
    out: dict[str, float | None] = {}
    for cat, e in agg.items():
        if e["role"] == "GATING":
            a = e["slices"][e["gating_slice"]]
            out[cat] = a["mean"] if a["status"] == "COMPLETE" else None
    return out

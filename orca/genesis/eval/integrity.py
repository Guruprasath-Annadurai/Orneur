"""Contamination-aware scoring for synthetic, non-secret evaluation items.

The harness refuses to drop failed items, refuses to change a scoring
threshold without a new version, and refuses to treat a missing
prediction as a pass. It does not call a model provider.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


class EvalIntegrityError(Exception):
    """The run would have misreported what the items actually did."""


@dataclass(frozen=True)
class EvalItem:
    item_id: str
    prompt: str
    expected: str
    hidden_expected: bool = False


@dataclass(frozen=True)
class EvalDefinition:
    eval_id: str
    version: str
    rubric_version: str
    seed: int
    items: tuple[EvalItem, ...]
    pass_threshold: float | None = None

    def __post_init__(self) -> None:
        if not self.eval_id or not self.version or not self.rubric_version:
            raise EvalIntegrityError("eval_id, version, and rubric_version are required")
        if self.seed < 0:
            raise EvalIntegrityError("seed must be non-negative")
        ids = [item.item_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise EvalIntegrityError("eval item ids must be unique")
        if not self.items:
            raise EvalIntegrityError("an evaluation definition needs at least one item")
        if self.pass_threshold is not None and not (0.0 <= self.pass_threshold <= 1.0):
            raise EvalIntegrityError("pass_threshold must be in [0, 1] when set")


@dataclass(frozen=True)
class ItemResult:
    item_id: str
    status: str  # PASS, FAIL, ERROR, MISSING
    detail: str


@dataclass(frozen=True)
class EvalReport:
    eval_id: str
    version: str
    rubric_version: str
    seed: int
    results: tuple[ItemResult, ...]
    pass_threshold: float | None

    def counts(self) -> dict[str, int]:
        out = {"PASS": 0, "FAIL": 0, "ERROR": 0, "MISSING": 0}
        for result in self.results:
            out[result.status] = out.get(result.status, 0) + 1
        return out

    @property
    def scored_n(self) -> int:
        """Items that produced a comparable PASS or FAIL. Errors and missing stay out."""
        return sum(1 for result in self.results if result.status in {"PASS", "FAIL"})

    @property
    def n_pass(self) -> int:
        return sum(1 for result in self.results if result.status == "PASS")

    def accuracy(self) -> float | None:
        if self.scored_n == 0:
            return None
        return self.n_pass / self.scored_n


def revise_threshold(definition: EvalDefinition, new_threshold: float, new_version: str) -> EvalDefinition:
    """Return a new definition. The version string must change."""
    if new_version == definition.version:
        raise EvalIntegrityError(
            "changing pass_threshold without a new eval version is refused"
        )
    return EvalDefinition(
        eval_id=definition.eval_id,
        version=new_version,
        rubric_version=definition.rubric_version,
        seed=definition.seed,
        items=definition.items,
        pass_threshold=new_threshold,
    )


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    """Wilson score interval for a binomial proportion.

    Returns None when `n` is 0. This is a standard interval, not a
    benchmark claim about any model.
    """
    if n < 0 or successes < 0 or successes > n:
        raise EvalIntegrityError("wilson_interval needs 0 <= successes <= n")
    if n == 0:
        return None
    phat = successes / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (phat + z2 / (2 * n)) / denom
    margin = z * math.sqrt((phat * (1.0 - phat) + z2 / (4 * n)) / n) / denom
    low = max(0.0, centre - margin)
    high = min(1.0, centre + margin)
    return low, high


def scan_exact_contamination(items: tuple[EvalItem, ...] | list[EvalItem], training_texts: list[str]) -> list[str]:
    """Item ids whose prompt or expected answer occurs exactly in `training_texts`.

    Comparison is stripped and casefolded. This is an exact screen, not a
    paraphrase detector.
    """
    pool = {text.strip().casefold() for text in training_texts if text and text.strip()}
    flagged: list[str] = []
    for item in items:
        prompt = item.prompt.strip().casefold()
        expected = item.expected.strip().casefold()
        if prompt in pool or expected in pool:
            flagged.append(item.item_id)
    return flagged


def _normalize_prediction(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvalIntegrityError(f"prediction must be str or None, got {type(value).__name__}")
    return value


class EvalHarness:
    """Run a registered definition. Item order is the registered order."""

    def run(self, definition: EvalDefinition, predict) -> EvalReport:
        results: list[ItemResult] = []
        for item in definition.items:
            try:
                raw = predict(item.prompt)
            except Exception as exc:  # noqa: BLE001 -- a predictor fault is an item result, not a silent skip
                results.append(ItemResult(item.item_id, "ERROR", type(exc).__name__))
                continue
            try:
                prediction = _normalize_prediction(raw)
            except EvalIntegrityError as exc:
                results.append(ItemResult(item.item_id, "ERROR", str(exc)))
                continue
            if prediction is None:
                results.append(ItemResult(item.item_id, "MISSING", "predictor returned None"))
                continue
            if prediction.strip() == item.expected.strip():
                results.append(ItemResult(item.item_id, "PASS", "exact match"))
            else:
                results.append(ItemResult(item.item_id, "FAIL", "exact mismatch"))
        report = EvalReport(
            eval_id=definition.eval_id,
            version=definition.version,
            rubric_version=definition.rubric_version,
            seed=definition.seed,
            results=tuple(results),
            pass_threshold=definition.pass_threshold,
        )
        self._require_complete(definition, report)
        return report

    @staticmethod
    def _require_complete(definition: EvalDefinition, report: EvalReport) -> None:
        expected_ids = [item.item_id for item in definition.items]
        got_ids = [result.item_id for result in report.results]
        if got_ids != expected_ids:
            raise EvalIntegrityError("report item ids do not match the registered definition; items were dropped or reordered")

    def public_log(self, definition: EvalDefinition, report: EvalReport) -> str:
        """A log line per item. Hidden expected answers are not written."""
        by_id = {item.item_id: item for item in definition.items}
        lines = [
            f"eval={report.eval_id} version={report.version} rubric={report.rubric_version} seed={report.seed}"
        ]
        for result in report.results:
            item = by_id[result.item_id]
            if item.hidden_expected:
                shown = "<hidden>"
            else:
                shown = item.expected
            lines.append(f"{result.item_id} status={result.status} expected={shown}")
        return "\n".join(lines)

    def paired_comparison(self, left: EvalReport, right: EvalReport) -> dict[str, object]:
        """Compare two reports on the same item ids.

        The difference is (left_only_correct - right_only_correct) / n
        over items both reports scored PASS or FAIL. Items that are
        ERROR or MISSING on either side are listed and excluded from the
        proportion. No significance claim is attached.
        """
        if [row.item_id for row in left.results] != [row.item_id for row in right.results]:
            raise EvalIntegrityError("paired comparison requires the same item ids in the same order")
        only_left = only_right = both = neither = excluded = 0
        for a, b in zip(left.results, right.results):
            if a.status not in {"PASS", "FAIL"} or b.status not in {"PASS", "FAIL"}:
                excluded += 1
                continue
            if a.status == "PASS" and b.status == "PASS":
                both += 1
            elif a.status == "PASS" and b.status == "FAIL":
                only_left += 1
            elif a.status == "FAIL" and b.status == "PASS":
                only_right += 1
            else:
                neither += 1
        scored = both + only_left + only_right + neither
        difference = None if scored == 0 else (only_left - only_right) / scored
        return {
            "n_scored_pairs": scored,
            "n_excluded": excluded,
            "both_correct": both,
            "only_left": only_left,
            "only_right": only_right,
            "neither": neither,
            "paired_difference": difference,
            "left_version": left.version,
            "right_version": right.version,
        }


def seeded_item_order(definition: EvalDefinition) -> tuple[str, ...]:
    """Deterministic permutation of item ids for a seeded presentation.

    The scored report still follows registered order. This helper exists
    so a caller who shuffles prompts for a human run can reproduce that
    shuffle from the definition seed. It does not drop ids.
    """
    ids = [item.item_id for item in definition.items]
    rng = random.Random(definition.seed)
    rng.shuffle(ids)
    if sorted(ids) != sorted(item.item_id for item in definition.items):
        raise EvalIntegrityError("seeded order dropped an item")
    return tuple(ids)

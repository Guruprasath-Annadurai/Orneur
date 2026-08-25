"""
Tests for the metrics additions this session: moderation-action counters
and registry-fallback counters.

Covers the real gap they close: orca/serve/moderation.py's jailbreak
detector and orca/serve/registry.py's tier step-down fallback both had zero
visibility into how often they actually fire in production — a silent
substitution or a moderation layer that stopped blocking anything would be
invisible without these.
"""
from __future__ import annotations

import pytest

from orca.serve import metrics


@pytest.fixture(autouse=True)
def _reset_metrics():
    metrics.reset()
    yield
    metrics.reset()


def test_record_moderation_action_counts_by_action():
    metrics.record_moderation_action("block")
    metrics.record_moderation_action("block")
    metrics.record_moderation_action("flag")
    metrics.record_moderation_action("allow")

    snapshot = metrics.get_metrics_snapshot()
    assert snapshot["moderation_actions"] == {"block": 2, "flag": 1, "allow": 1}


def test_record_registry_fallback_counts_by_path():
    metrics.record_registry_fallback("ultra", "orca-core")
    metrics.record_registry_fallback("ultra", "orca-core")
    metrics.record_registry_fallback("core", "orca-nano")

    snapshot = metrics.get_metrics_snapshot()
    assert snapshot["registry_fallbacks"] == {"ultra->orca-core": 2, "core->orca-nano": 1}


def test_moderation_and_fallback_appear_in_prometheus_text():
    metrics.record_moderation_action("block")
    metrics.record_registry_fallback("ultra", "orca-core")

    text = metrics.get_prometheus_text()
    assert 'orca_moderation_actions_total{action="block"} 1' in text
    assert 'orca_registry_fallbacks_total{requested_tier="ultra",resolved_model="orca-core"} 1' in text


def test_reset_clears_moderation_and_fallback_counts():
    metrics.record_moderation_action("block")
    metrics.record_registry_fallback("ultra", "orca-core")
    metrics.reset()

    snapshot = metrics.get_metrics_snapshot()
    assert snapshot["moderation_actions"] == {}
    assert snapshot["registry_fallbacks"] == {}


def test_recording_never_raises_on_bad_input():
    # Same defensive contract as record_request() — a metrics failure must
    # never break the request path it's instrumenting.
    metrics.record_moderation_action(None)  # type: ignore[arg-type]
    metrics.record_registry_fallback(None, None)  # type: ignore[arg-type]

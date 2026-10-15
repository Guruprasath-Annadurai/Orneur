"""Cost accounting + quota refusal: hard cap, contingency, default cap 0 refuses everything, tamper-evident persistence."""
import pytest

from orca.evalinfra import budget as B
from orca.evalinfra.errors import BudgetExceeded, ChainCorrupt, SchemaViolation


@pytest.fixture
def led(tmp_path):
    return B.BudgetLedger(tmp_path / "budget.jsonl")


def refuse(fn, *a, **k):
    with pytest.raises(BudgetExceeded) as e:
        fn(*a, **k)
    return e.value.code


def test_default_cap_zero_refuses_everything_including_free_operations(led):
    assert led.state()["hard_cap_micro"] == 0 and led.state()["configured"] is False
    assert refuse(led.reserve, "op1", 0) == "CAP_ZERO"
    assert refuse(led.reserve, "op2", 0.000001) == "CAP_ZERO"
    assert refuse(led.reserve, "op3", 5, use_contingency=True, reason="an urgent and well explained need") == "CAP_ZERO"
    led.configure(0)                                                          # an explicit zero cap changes nothing
    assert refuse(led.reserve, "op4", 0) == "CAP_ZERO"


def test_nonzero_cap_requires_a_cited_authorization_record(led):
    for ref in ("", "short", None):
        with pytest.raises(SchemaViolation) as e:
            led.configure(10, authorization_ref=ref)
        assert e.value.code == "AUTHORIZATION_REF_REQUIRED"
    led.configure(10, authorization_ref="founder-budget-record-0001")
    with pytest.raises(SchemaViolation) as e:
        led.configure(20, authorization_ref="founder-budget-record-0001")      # the same record cannot authorize a second raise
    assert e.value.code == "AUTHORIZATION_REF_REUSED"


def test_refuses_before_the_operation_that_would_exceed_the_cap(led):
    led.configure(10, 0.2, authorization_ref="founder-budget-record-0001")      # ordinary limit 8.00, contingency 2.00
    assert led.state()["ordinary_cap_micro"] == 8_000_000 and led.state()["contingency_micro"] == 2_000_000
    led.reserve("a", 5)
    assert refuse(led.reserve, "b", 3.000001) == "WOULD_EXCEED_ORDINARY_CAP"
    led.reserve("b", 3)                                                         # exactly at the ordinary limit is allowed
    assert refuse(led.reserve, "c", 0.000001) == "WOULD_EXCEED_ORDINARY_CAP"
    assert led.state()["remaining_micro"] == 2_000_000


def test_contingency_needs_explicit_flag_and_reason_and_never_exceeds_the_hard_cap(led):
    led.configure(10, 0.2, authorization_ref="founder-budget-record-0001")
    led.reserve("a", 8)
    assert refuse(led.reserve, "b", 1) == "WOULD_EXCEED_ORDINARY_CAP"
    assert refuse(led.reserve, "b", 1, use_contingency=True, reason="short") == "CONTINGENCY_REASON_REQUIRED"
    led.reserve("b", 1.5, use_contingency=True, reason="rerun after a documented harness fault")
    assert refuse(led.reserve, "c", 0.500001, use_contingency=True, reason="a long enough written reason") == "WOULD_EXCEED_CAP"
    led.reserve("c", 0.5, use_contingency=True, reason="a long enough written reason")
    assert led.state()["remaining_micro"] == 0
    assert refuse(led.reserve, "d", 0.000001, use_contingency=True, reason="a long enough written reason") == "WOULD_EXCEED_CAP"


def test_synthetic_cost_events_commit_release_and_remaining(led):
    led.configure(100, 0.0, authorization_ref="founder-budget-record-0002")
    led.reserve("eval-1", 30)
    led.commit("eval-1", 28.5)
    led.reserve("eval-2", 40)
    led.release("eval-2")
    s = led.state()
    assert s["committed_micro"] == 28_500_000 and s["reserved_open_micro"] == 0 and s["remaining_micro"] == 71_500_000
    assert refuse(led.commit, "eval-1", 1) == "NO_OPEN_RESERVATION"
    assert refuse(led.release, "nope") == "NO_OPEN_RESERVATION"
    assert refuse(led.reserve, "eval-1", 1) == "DUPLICATE_OPERATION"


def test_an_overrun_locks_the_ledger_until_a_new_authorized_configuration(led):
    led.configure(100, 0.0, authorization_ref="founder-budget-record-0003")
    led.reserve("x", 10)
    led.commit("x", 12)                                                         # the operation already happened: record it, then lock
    assert led.state()["locked"] is True and led.state()["committed_micro"] == 12_000_000
    assert refuse(led.reserve, "y", 1) == "LEDGER_LOCKED"
    led.configure(100, 0.0, authorization_ref="founder-budget-record-0004")
    led.reserve("y", 1)


def test_amount_validation_is_strict(led):
    led.configure(10, 0.0, authorization_ref="founder-budget-record-0005")
    for bad in (-1, float("nan"), float("inf"), True, None, "abc"):
        with pytest.raises(SchemaViolation):
            led.reserve("bad", bad)
    assert B.to_micro("0.0000001") == 1                                         # sub-micro amounts round UP (conservative)
    assert B.to_micro(1) == 1_000_000
    with pytest.raises(SchemaViolation):
        led.configure(10, 1.0, authorization_ref="founder-budget-record-0006")
    with pytest.raises(SchemaViolation):
        led.reserve("", 1)


def test_ledger_is_persistent_and_tamper_evident(tmp_path):
    p = tmp_path / "b.jsonl"
    a = B.BudgetLedger(p)
    a.configure(10, 0.0, authorization_ref="founder-budget-record-0007")
    a.reserve("a", 6)
    b = B.BudgetLedger(p)                                                       # a fresh handle replays the same state
    assert b.state()["reserved_open_micro"] == 6_000_000
    assert refuse(b.reserve, "c", 5) == "WOULD_EXCEED_ORDINARY_CAP"
    p.write_text(p.read_text().replace('"cap_micro":10000000', '"cap_micro":99000000'))   # attacker raises the cap in place
    with pytest.raises(ChainCorrupt):
        B.BudgetLedger(p).reserve("d", 50)
    with pytest.raises(ChainCorrupt):
        B.BudgetLedger(p).state()

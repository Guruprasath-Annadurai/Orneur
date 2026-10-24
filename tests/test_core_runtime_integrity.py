"""Adversarial regressions for the local core runtime.

These cases failed on 408a912d34ab9043641984a51d3eb9bbaeca5c48: a tampered
artifact still replayed as verified, a generic transition could enter
completed_verified, boolean units were treated as integers, a NaN budget
selected a tool, a symlinked missions directory received the write, and a
list-shaped ledger was reported as empty. The browser cases pin DNS before
connect.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import stat
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from orca.core_runtime.browser import NavigationRefused, classify_url, fetch_readonly
from orca.core_runtime.journal import VERIFIER_ID, Journal, MissionError, MissionHidden
from orca.core_runtime.opportunity import OpportunityError, match
from orca.core_runtime.principal import PrincipalError, authenticate
from orca.core_runtime.proof import ProofError, score_attempt, share_record
from orca.core_runtime.report import JourneyInterrupted, JourneyRefused, canonical_records, recompute, run_business_report
from orca.core_runtime.router import route

_RECORDS = [
    {"sku": "a", "units": 3, "unit_price_cents": 100},
    {"sku": "b", "units": 2, "unit_price_cents": 250},
]
_STEPS = ["select_tool", "read_records", "calculate", "write_artifact", "verify"]


def _create(journal: Journal, mission_id: str = "m1") -> dict:
    return journal.create(
        mission_id=mission_id,
        owner_user_id="owner-a",
        objective={"kind": "structured_report"},
        steps=_STEPS,
    )


def test_tamper_after_completion_is_not_verified_success(tmp_path: Path):
    journal = Journal(tmp_path)
    first = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert first["independently_verified"] is True
    path = tmp_path / "artifacts" / "report1" / "report.json"
    body = json.loads(path.read_text(encoding="utf-8"))
    body["total_cents"] = 999
    path.write_text(json.dumps(body), encoding="utf-8")
    again = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    stored = journal.get("report1", "owner-a")
    assert again["independently_verified"] is False
    assert again["current_integrity"] == "artifact_digest_mismatch"
    assert again["journal_state"] == "completed_verified"
    assert stored["state"] == "completed_verified"
    assert stored["verification"]["total_cents"] == 800


def test_changed_input_is_a_distinct_integrity_failure(tmp_path: Path):
    journal = Journal(tmp_path)
    run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    changed = [{"sku": "a", "units": 1, "unit_price_cents": 1}]
    again = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=changed)
    assert again["independently_verified"] is False
    assert again["current_integrity"] == "input_revision_mismatch"
    assert journal.get("report1", "owner-a")["state"] == "completed_verified"


def test_missing_or_unreadable_artifact_keeps_historical_completion(tmp_path: Path):
    journal = Journal(tmp_path)
    run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    path = tmp_path / "artifacts" / "report1" / "report.json"
    path.unlink()
    missing = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert missing["current_integrity"] == "missing_artifact"
    assert missing["independently_verified"] is False
    assert journal.get("report1", "owner-a")["state"] == "completed_verified"
    outside = tmp_path / "outside.json"
    outside.write_text("{}", encoding="utf-8")
    path.symlink_to(outside)
    unreadable = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert unreadable["current_integrity"] == "artifact_unreadable"
    assert journal.get("report1", "owner-a")["state"] == "completed_verified"
    assert outside.read_text(encoding="utf-8") == "{}"


def test_generic_transition_cannot_complete_verified(tmp_path: Path):
    journal = Journal(tmp_path)
    _create(journal)
    journal.transition("m1", "owner-a", "running")
    journal.transition("m1", "owner-a", "verifying")
    with pytest.raises(MissionError) as exc:
        journal.transition("m1", "owner-a", "completed_verified")
    assert exc.value.code == "verification_required"
    stored = journal.get("m1", "owner-a")
    assert stored["state"] == "verifying"
    assert stored["verification"] is None
    assert stored["actor_authenticated"] is False
    assert stored["durability"] == "single_host_flock"


def test_forged_and_replayed_verifier_evidence_is_not_trusted(tmp_path: Path):
    journal = Journal(tmp_path)
    original = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert original["independently_verified"] is True
    stolen = journal.get("report1", "owner-a")["verification"]
    forged = _create(journal, "report2")
    forged["state"] = "completed_verified"
    forged["verification"] = stolen
    journal.write_bytes(Path("missions") / "report2.json", json.dumps(forged).encode())
    journal.write_bytes(Path("artifacts") / "report2" / "report.json", b'{"mission_id":"report2","total_cents":1,"verified":false}')
    replayed = run_business_report(journal, mission_id="report2", owner_user_id="owner-a", records=_RECORDS)
    assert replayed["independently_verified"] is False
    assert replayed["current_integrity"] == "artifact_digest_mismatch"
    assert journal.get("report2", "owner-a")["state"] == "completed_verified"
    assert journal.get("report1", "owner-a")["state"] == "completed_verified"

    missing = _create(journal, "report3")
    missing["state"] = "completed_verified"
    missing["verification"] = None
    journal.write_bytes(Path("missions") / "report3.json", json.dumps(missing).encode())
    bare = run_business_report(journal, mission_id="report3", owner_user_id="owner-a", records=_RECORDS)
    assert bare["current_integrity"] == "missing_evidence"
    assert bare["independently_verified"] is False
    assert journal.get("report3", "owner-a")["state"] == "completed_verified"


def test_cancel_and_revoke_after_admission_do_not_verify(tmp_path: Path):
    journal = Journal(tmp_path)
    cancelled = run_business_report(
        journal, mission_id="stop1", owner_user_id="owner-a", records=_RECORDS,
        crash_after="cancel_after_admit:write_report",
    )
    assert cancelled["code"] == "cancelled_after_admission"
    assert cancelled["independently_verified"] is False
    assert journal.get("stop1", "owner-a")["state"] == "cancelled"
    assert not (tmp_path / "artifacts" / "stop1" / "report.json").exists()
    effect = journal.effect("stop1", "owner-a", "write_report")
    assert effect["status"] == "not_committed"
    assert effect["external_outcome"] == "unconfirmed"
    assert effect["external_bytes_present"] is False
    replay = run_business_report(journal, mission_id="stop1", owner_user_id="owner-a", records=_RECORDS)
    assert replay["independently_verified"] is False
    assert replay["journal_state"] == "cancelled"

    revoked = run_business_report(
        journal, mission_id="rev1", owner_user_id="owner-a", records=_RECORDS,
        crash_after="revoke_after_admit:write_report",
    )
    assert revoked["code"] == "revoked_after_admission"
    assert journal.get("rev1", "owner-a")["state"] == "revoked"
    assert journal.effect("rev1", "owner-a", "write_report")["status"] == "not_committed"

    written = run_business_report(
        journal, mission_id="late1", owner_user_id="owner-a", records=_RECORDS,
        crash_after="cancel_after_bytes:write_report",
    )
    assert written["code"] == "cancelled_after_admission"
    assert written["independently_verified"] is False
    assert (tmp_path / "artifacts" / "late1" / "report.json").is_file()
    late = journal.effect("late1", "owner-a", "write_report")
    assert late["status"] == "not_committed"
    assert late["external_bytes_present"] is True
    assert late["external_outcome"] == "unconfirmed"
    assert journal.get("late1", "owner-a")["verification"] is None


def test_cancel_during_verification_does_not_seal(tmp_path: Path):
    journal = Journal(tmp_path)
    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:verifying",
        )
    assert journal.get("report1", "owner-a")["state"] == "verifying"
    journal.request_cancel("report1", "owner-a")
    cancelled = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert cancelled["independently_verified"] is False
    stored = journal.get("report1", "owner-a")
    assert stored["state"] == "cancelled"
    assert stored["verification"] is None

    journal = Journal(tmp_path / "revoked")
    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:verifying",
        )
    journal.revoke("report1", "owner-a")
    with pytest.raises(JourneyRefused) as exc:
        run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert exc.value.code == "revoked"
    assert journal.get("report1", "owner-a")["state"] == "revoked"
    assert journal.get("report1", "owner-a")["verification"] is None


def test_resume_after_each_durable_interrupt(tmp_path: Path):
    journal = Journal(tmp_path)
    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="draft1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:draft",
        )
    assert journal.get("draft1", "owner-a")["state"] == "draft"
    assert not (tmp_path / "artifacts" / "draft1" / "report.json").exists()
    drafted = run_business_report(journal, mission_id="draft1", owner_user_id="owner-a", records=_RECORDS)
    assert drafted["independently_verified"] is True
    assert drafted["artifact_writes"] == 1

    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="run1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:running",
        )
    assert journal.get("run1", "owner-a")["state"] == "running"
    resumed = run_business_report(journal, mission_id="run1", owner_user_id="owner-a", records=_RECORDS)
    assert resumed["independently_verified"] is True
    assert resumed["artifact_writes"] == 1
    again = run_business_report(journal, mission_id="run1", owner_user_id="owner-a", records=_RECORDS)
    assert again["artifact_writes"] == 1
    assert journal.effect("run1", "owner-a", "write_report")["status"] == "committed"

    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="ver1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:verifying",
        )
    saved = (tmp_path / "artifacts" / "ver1" / "report.json").read_bytes()
    assert journal.get("ver1", "owner-a")["state"] == "verifying"
    sealed = run_business_report(journal, mission_id="ver1", owner_user_id="owner-a", records=_RECORDS)
    assert sealed["independently_verified"] is True
    assert sealed["current_integrity"] == "intact"
    assert (tmp_path / "artifacts" / "ver1" / "report.json").read_bytes() == saved
    assert journal.effect("ver1", "owner-a", "write_report")["writes"] == 1


def test_symlink_parent_and_root_are_refused(tmp_path: Path):
    real = tmp_path / "real"
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    journal = Journal(real)
    (real / "missions").symlink_to(decoy, target_is_directory=True)
    with pytest.raises(MissionError) as exc:
        _create(journal, "m3")
    assert exc.value.code == "symlink_refused"
    assert not (decoy / "m3.json").exists()

    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(MissionError) as root_exc:
        Journal(link)
    assert root_exc.value.code == "symlink_refused"
    assert list(target.iterdir()) == []


def test_planted_temp_name_is_not_the_write_target(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.write_text("keep", encoding="utf-8")
    journal = Journal(tmp_path)
    missions = tmp_path / "missions"
    missions.mkdir()
    planted = missions / ".m1.json.tmp"
    planted.symlink_to(outside)
    _create(journal, "m1")
    assert outside.read_text(encoding="utf-8") == "keep"
    assert planted.is_symlink()
    stored = json.loads((missions / "m1.json").read_text(encoding="utf-8"))
    assert stored["mission_id"] == "m1"
    with pytest.raises(MissionError) as exc:
        journal.write_bytes(Path("..") / "escape.json", b"{}")
    assert exc.value.code == "path_escape"
    with pytest.raises(MissionError) as large:
        journal.write_bytes(Path("missions") / "big.json", b"x" * 1_000_001)
    assert large.value.code == "input_too_large"


def test_cross_owner_share_is_hidden(tmp_path: Path):
    journal = Journal(tmp_path)
    _create(journal, "mission-a")
    with pytest.raises(MissionHidden):
        journal.put_memory(
            memory_id="mem1", owner_user_id="owner-b", body={"note": "no"}, share_with=["mission-a"],
        )
    journal.put_memory(
        memory_id="mem1", owner_user_id="owner-a", body={"note": "yes"}, share_with=["mission-a"],
    )
    assert journal.read_memory(
        memory_id="mem1", owner_user_id="owner-a", actor_user_id="owner-a", mission_id="mission-a",
    )["body"]["note"] == "yes"
    with pytest.raises(MissionHidden):
        journal.read_memory(
            memory_id="mem1", owner_user_id="owner-a", actor_user_id="owner-b", mission_id="mission-a",
        )


def test_boolean_units_and_nonfinite_budgets_are_refused():
    with pytest.raises(MissionError) as exc:
        recompute([{"units": True, "unit_price_cents": 5}])
    assert exc.value.code == "invalid_record"
    with pytest.raises(MissionError) as huge:
        recompute([{"units": 10**12 + 1, "unit_price_cents": 1}])
    assert huge.value.code == "input_too_large"
    for budget in (float("nan"), float("inf"), float("-inf"), True, -1):
        decision = route(task_type="structured_arithmetic", requested_family=None, budget_usd=budget, capability_cost_usd=1)
        assert decision["decision"] == "refused"
        assert decision["code"] == "invalid_budget"
        assert decision["tool"] is None
        assert decision["production_router"] is False


def test_boolean_records_fail_the_journey(tmp_path: Path):
    journal = Journal(tmp_path)
    with pytest.raises(JourneyRefused) as exc:
        run_business_report(
            journal, mission_id="badbool", owner_user_id="owner-a",
            records=[{"sku": "a", "units": True, "unit_price_cents": 5}],
        )
    assert exc.value.code == "invalid_record"
    assert journal.get("badbool", "owner-a")["state"] == "failed"


def test_two_creates_do_not_lose_a_record(tmp_path: Path):
    journal = Journal(tmp_path)
    errors = []

    def worker(mission_id: str) -> None:
        try:
            _create(journal, mission_id)
        except Exception as exc:  # noqa: BLE001 - the test records the race outcome
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("one", "two")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert journal.get("one", "owner-a")["mission_id"] == "one"
    assert journal.get("two", "owner-a")["mission_id"] == "two"


def test_dns_rebinding_does_not_connect(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0, "connected": 0}

    def fake_getaddrinfo(host, port, *args, **kwargs):
        calls["n"] += 1
        address = "93.184.216.34" if calls["n"] == 1 else "169.254.169.254"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, port))]

    def fake_connect(*args, **kwargs):
        calls["connected"] += 1
        raise AssertionError("create_connection")

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_connect)
    with pytest.raises(NavigationRefused) as exc:
        fetch_readonly("http://example.com/page")
    assert exc.value.code == "dns_rebinding"
    assert calls["connected"] == 0


def test_stable_private_and_mapped_answers_do_not_connect(monkeypatch: pytest.MonkeyPatch):
    calls = {"connected": 0}

    def fake_connect(*args, **kwargs):
        calls["connected"] += 1
        raise AssertionError("create_connection")

    monkeypatch.setattr(socket, "create_connection", fake_connect)

    def private(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]

    monkeypatch.setattr(socket, "getaddrinfo", private)
    with pytest.raises(NavigationRefused) as exc:
        fetch_readonly("http://example.com/")
    assert exc.value.code == "resolved_non_public"

    def mapped(host, port, *args, **kwargs):
        return [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:169.254.169.254", port, 0, 0))]

    monkeypatch.setattr(socket, "getaddrinfo", mapped)
    with pytest.raises(NavigationRefused) as mapped_exc:
        fetch_readonly("http://example.com/meta")
    assert mapped_exc.value.code == "metadata_refused"
    assert calls["connected"] == 0


def test_peer_mismatch_is_refused_before_send(monkeypatch: pytest.MonkeyPatch):
    sent = {"called": False}

    class FakeSocket:
        def getpeername(self):
            return ("10.0.0.1", 80)

        def sendall(self, data):
            sent["called"] = True
            raise AssertionError("sent")

        def close(self):
            return None

        def settimeout(self, value):
            return None

    def fake_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    def fake_connect(address, timeout=None, *args, **kwargs):
        assert address[0] == "93.184.216.34"
        return FakeSocket()

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(socket, "create_connection", fake_connect)
    with pytest.raises(NavigationRefused) as exc:
        fetch_readonly("http://example.com/")
    assert exc.value.code == "host_mismatch"
    assert sent["called"] is False


def test_redirect_is_not_followed_and_proxy_env_is_ignored(monkeypatch: pytest.MonkeyPatch):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.paths.append(self.path)
            if self.path.startswith("/page"):
                self.send_response(302)
                self.send_header("Location", "/secret")
                self.end_headers()
                return
            body = b"<html><title>Secret</title><body><p>hidden</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    class Page(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><title>Direct</title><body><p>direct page</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    class Proxy(BaseHTTPRequestHandler):
        def handle_one_request(self):
            self.server.hits += 1
            super().handle_one_request()

        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def do_CONNECT(self):
            self.server.hits += 1
            self.send_response(200)
            self.end_headers()

        def log_message(self, fmt, *args):
            return

    redirect = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    redirect.paths = []
    proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    proxy.hits = 0
    page = ThreadingHTTPServer(("127.0.0.1", 0), Page)
    threads = []
    for server in (redirect, proxy, page):
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        proxy_port = proxy.server_address[1]
        for name in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            monkeypatch.setenv(name, f"http://127.0.0.1:{proxy_port}")
        with pytest.raises(NavigationRefused) as exc:
            fetch_readonly(
                f"http://127.0.0.1:{redirect.server_address[1]}/page",
                allow_hosts=frozenset({"127.0.0.1"}),
            )
        direct = fetch_readonly(
            f"http://127.0.0.1:{page.server_address[1]}/page",
            allow_hosts=frozenset({"127.0.0.1"}),
        )
    finally:
        for server in (redirect, proxy, page):
            server.shutdown()
        for thread in threads:
            thread.join(timeout=2)
    assert exc.value.code == "redirect_refused"
    assert redirect.paths == ["/page"]
    assert "hidden" not in direct["text"]
    assert direct["title"] == "Direct"
    assert direct["production_cloud_browser"] is False
    assert proxy.hits == 0


def test_permitted_ipv6_loopback_is_pinned():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b"<html><title>Six</title><body><p>ipv6 page</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            return

    class V6(ThreadingHTTPServer):
        address_family = socket.AF_INET6

    try:
        server = V6(("::1", 0), Handler)
    except OSError:
        pytest.skip("IPv6 loopback is not available")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        page = fetch_readonly(f"http://[::1]:{port}/page", allow_hosts=frozenset({"::1"}))
    finally:
        server.shutdown()
        thread.join(timeout=2)
    assert page["title"] == "Six"
    assert page["pinned_address"] == "::1"
    assert page["production_cloud_browser"] is False
    assert page["explicit_permit"] is True


def test_proof_identity_and_age_are_not_authority():
    assessment = {
        "schema": "orneur-proof-assessment/1",
        "assessment_id": "arith-1",
        "version": 1,
        "items": [{"id": "q1", "answer": "4"}],
    }
    with pytest.raises(ProofError) as exc:
        score_attempt(
            assessment=assessment, learner_id="Learner", scorer_id=" learner ",
            responses={"q1": "4"}, mode="unaided", age_band="adult",
        )
    assert exc.value.code == "self_score_refused"
    adult = score_attempt(
        assessment=assessment, learner_id="learner-1", scorer_id="scorer-1",
        responses={"q1": "4"}, mode="unaided", age_band="adult",
    )
    assert adult["scorer_authenticated"] is False
    assert adult["age_verified"] is False
    assert adult["shareable"] is False
    assert adult["age_band_caller_asserted"] == "adult"
    assert adult["accredited"] is False
    with pytest.raises(ProofError) as share_exc:
        share_record(adult, public=True)
    assert share_exc.value.code == "age_unverified"


def test_opportunity_dates_fail_closed():
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    good = {
        "opportunity_id": "open-1", "source": "fixture", "provenance": "synthetic",
        "geo": "IN", "opens_at": "2026-01-01T00:00:00Z", "closes_at": "2026-12-01T00:00:00Z",
        "required_skills": ["arithmetic"], "verification": "verified", "status": "listed",
    }
    invalid = dict(good, opportunity_id="bad-date", opens_at="not-a-date")
    naive = dict(good, opportunity_id="naive-date", opens_at="2026-01-01T00:00:00")
    window = dict(
        good,
        opportunity_id="bad-window",
        opens_at="2026-12-01T00:00:00Z",
        closes_at="2026-01-01T00:00:00+05:30",
    )
    result = match(skills={"arithmetic"}, geo="IN", listings=[good, invalid, naive, window], now=now)
    by_id = {row["opportunity_id"]: row for row in result["results"]}
    assert by_id["open-1"]["eligible"] is True
    assert "invalid_date" in by_id["bad-date"]["reasons"]
    assert by_id["bad-date"]["eligible"] is False
    assert "naive_date" in by_id["naive-date"]["reasons"]
    assert "invalid_window" in by_id["bad-window"]["reasons"]
    assert result["external_integration"] is False
    assert result["application_submitted"] is False
    with pytest.raises(OpportunityError) as exc:
        match(skills={"arithmetic"}, geo="IN", listings=[good], now=datetime(2026, 10, 24))
    assert exc.value.code == "naive_clock"


def test_caller_totals_and_planted_effect_cannot_seal(tmp_path: Path):
    """d1b2fe0 accepted seal_verified(input_bytes, total_cents) with zero effects."""
    journal = Journal(tmp_path)
    _create(journal)
    journal.transition("m1", "owner-a", "running")
    journal.bind_input("m1", "owner-a", canonical_records(_RECORDS))
    artifact = {
        "calculator": "deterministic.calculator",
        "effect_key": "write_report",
        "line_count": len(_RECORDS),
        "mission_id": "m1",
        "native_model_used": None,
        "owner_user_id": "owner-a",
        "schema": "orneur-business-report/1",
        "total_cents": 800,
        "verified": False,
    }
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode()
    journal.write_bytes(Path("artifacts") / "m1" / "report.json", payload)
    journal.transition("m1", "owner-a", "verifying")
    with pytest.raises(MissionError) as forged:
        journal.seal_verified("m1", "owner-a", input_bytes=b"forged", total_cents=1)
    assert forged.value.code == "verifier_rejected"
    assert journal.get("m1", "owner-a")["state"] == "verifying"
    assert journal.get("m1", "owner-a")["verification"] is None
    planted = {
        "schema": "orneur-local-mission/1",
        "mission_id": "m1",
        "effect_key": "write_report",
        "payload_sha256": hashlib.sha256(payload).hexdigest(),
        "status": "committed",
        "writes": 1,
        "external_bytes_present": True,
        "external_outcome": "local_receipt_only",
    }
    journal.write_bytes(Path("effects") / "m1" / "write_report.json", json.dumps(planted).encode())
    with pytest.raises(MissionError) as bare:
        journal.seal_verified("m1", "owner-a")
    assert bare.value.code == "effect_not_authorized"
    assert journal.get("m1", "owner-a")["state"] == "verifying"
    assert journal.effect("m1", "owner-a", "write_report")["status"] == "committed"
    assert "write_report" not in (journal.get("m1", "owner-a").get("admitted_effects") or {})


def test_altered_bound_input_does_not_seal(tmp_path: Path):
    journal = Journal(tmp_path)
    with pytest.raises(JourneyInterrupted):
        run_business_report(
            journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS, crash_after="after:verifying",
        )
    stored = journal.get("report1", "owner-a")
    assert stored["state"] == "verifying"
    assert stored["input_sha256"]
    changed = [{"sku": "a", "units": 1, "unit_price_cents": 1}]
    again = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=changed)
    assert again["independently_verified"] is False
    assert again["current_integrity"] == "input_revision_mismatch"
    assert journal.get("report1", "owner-a")["state"] == "verifying"
    assert journal.get("report1", "owner-a")["verification"] is None
    original = run_business_report(journal, mission_id="report1", owner_user_id="owner-a", records=_RECORDS)
    assert original["independently_verified"] is True
    assert journal.get("report1", "owner-a")["verification"]["verifier"] == VERIFIER_ID
    assert journal.get("report1", "owner-a")["verification"]["input_sha256"] == stored["input_sha256"]


def test_direct_commit_without_a_noted_write_is_not_ready(tmp_path: Path):
    journal = Journal(tmp_path)
    _create(journal)
    journal.transition("m1", "owner-a", "running")
    journal.bind_input("m1", "owner-a", canonical_records(_RECORDS))
    journal.begin_effect("m1", "owner-a", "write_report", b"{}")
    with pytest.raises(MissionError) as exc:
        journal.commit_effect("m1", "owner-a", "write_report")
    assert exc.value.code == "effect_not_ready"
    assert journal.effect("m1", "owner-a", "write_report")["status"] == "started"
    planted = journal.effect("m1", "owner-a", "write_report")
    other = {
        "schema": "orneur-local-mission/1",
        "mission_id": "m1",
        "effect_key": "other_key",
        "payload_sha256": planted["payload_sha256"],
        "status": "committed",
        "external_outcome": "local_receipt_only",
        "external_bytes_present": True,
        "writes": 1,
    }
    journal.write_bytes(Path("effects") / "m1" / "other_key.json", json.dumps(other).encode())
    with pytest.raises(MissionError) as unauthorized:
        journal.begin_effect("m1", "owner-a", "other_key", b"{}")
    assert unauthorized.value.code == "effect_not_authorized"
    assert "other_key" not in journal.get("m1", "owner-a")["admitted_effects"]


def test_lock_symlink_and_hard_link_are_refused(tmp_path: Path):
    root = tmp_path / "journal"
    root.mkdir()
    outside = tmp_path / "attacker.lock"
    outside.write_text("secret", encoding="utf-8")
    (root / ".lock").symlink_to(outside)
    journal = Journal(root)
    with pytest.raises(MissionError) as followed:
        _create(journal, "m-link")
    assert followed.value.code == "symlink_refused"
    assert outside.read_text(encoding="utf-8") == "secret"
    assert not (root / "missions").exists() or not (root / "missions" / "m-link.json").exists()

    (root / ".lock").unlink()
    created = _create(journal, "m-real")
    assert created["mission_id"] == "m-real"
    lock = root / ".lock"
    first = lock.stat()
    assert stat.S_ISREG(first.st_mode)
    assert first.st_nlink == 1
    assert first.st_mode & 0o777 == 0o600
    _create(journal, "m-next")
    second = lock.stat()
    assert second.st_ino == first.st_ino
    assert second.st_dev == first.st_dev

    extra = tmp_path / "hard.lock"
    os.link(lock, extra)
    with pytest.raises(MissionError) as linked:
        journal.get("m-real", "owner-a")
    assert linked.value.code == "lock_refused"
    extra.unlink()
    assert journal.get("m-real", "owner-a")["mission_id"] == "m-real"

    lock.unlink()
    os.mkfifo(lock)
    with pytest.raises(MissionError) as fifo:
        journal.get("m-real", "owner-a")
    assert fifo.value.code == "lock_refused"
    lock.unlink()
    lock.write_text("x", encoding="utf-8")
    os.chmod(lock, 0o666)
    assert journal.get("m-real", "owner-a")["state"] == "draft"
    assert lock.stat().st_mode & 0o777 == 0o600

    lock.rename(tmp_path / "saved.lock")
    (root / ".lock").symlink_to(outside)
    with pytest.raises(MissionError) as replaced:
        journal.get("m-real", "owner-a")
    assert replaced.value.code == "symlink_refused"
    assert outside.read_text(encoding="utf-8") == "secret"


def test_failed_critical_section_releases_the_lock(tmp_path: Path):
    journal = Journal(tmp_path)
    _create(journal, "m1")
    with pytest.raises(MissionError):
        _create(journal, "m1")
    second = _create(journal, "m2")
    assert second["mission_id"] == "m2"
    errors = []
    barrier = threading.Barrier(2)

    def worker(mission_id: str) -> None:
        try:
            barrier.wait(timeout=5)
            journal.create(
                mission_id=mission_id,
                owner_user_id="owner-a",
                objective={"kind": "structured_report"},
                steps=_STEPS,
            )
        except Exception as exc:  # noqa: BLE001 - the assertion reports the worker error
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(name,)) for name in ("m3", "m4")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert errors == []
    assert journal.get("m3", "owner-a")["mission_id"] == "m3"
    assert journal.get("m4", "owner-a")["mission_id"] == "m4"


def test_metadata_allowlist_never_connects(monkeypatch: pytest.MonkeyPatch):
    calls = {"n": 0}

    def refuse_connect(*_args, **_kwargs):
        calls["n"] += 1
        raise AssertionError("metadata connect")

    monkeypatch.setattr(socket, "create_connection", refuse_connect)
    cases = (
        ("http://169.254.169.254/latest/meta-data", frozenset({"169.254.169.254"})),
        ("http://169.254.169.253/", frozenset({"169.254.169.253"})),
        ("http://169.254.170.2/", frozenset({"169.254.170.2"})),
        ("http://[::ffff:169.254.169.254]/latest/meta-data", frozenset({"::ffff:169.254.169.254"})),
        ("http://metadata.google.internal/computeMetadata/v1/", frozenset({"metadata.google.internal"})),
        ("http://[fd00:ec2::254]/", frozenset({"fd00:ec2::254"})),
    )
    for url, hosts in cases:
        decision = classify_url(url, allow_hosts=hosts)
        assert decision["allowed"] is False, url
        assert decision["code"] == "metadata_refused", url
        with pytest.raises(NavigationRefused) as exc:
            fetch_readonly(url, allow_hosts=hosts)
        assert exc.value.code == "metadata_refused"
    assert calls["n"] == 0
    private = classify_url("http://10.1.2.3/", allow_hosts=frozenset({"10.1.2.3"}))
    assert private["allowed"] is False
    assert private["code"] == "permit_not_loopback"
    public = classify_url("http://example.com/", allow_hosts=frozenset({"example.com"}))
    assert public["code"] == "permit_not_loopback"


def test_principal_authentication_is_refused():
    with pytest.raises(PrincipalError) as exc:
        authenticate(user_id="owner-a", token="present")
    assert exc.value.code == "principal_not_authenticated"

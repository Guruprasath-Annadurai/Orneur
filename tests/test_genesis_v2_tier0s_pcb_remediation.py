"""Tier0-S PCB plausibility final remediation -- regression tests.

FINDING   The TCP row-vs-counter band (rows >= 0.75 * counter, rows <= counter + 12) was fitted to one load state. Measured on macOS 27.0.1: each socket adds exactly one
          counter and one row, but the counter also keeps closed PCBs not yet reclaimed (rows fell 484 -> 284 while the counter stayed at 472) and netstat lists PCBs the
          counter does not (excess 8..17, drifting). The band rejected the genuine, complete table in 28 of 30 samples.
DESIGN    Only NON-EMPTINESS is justified (counter >= 1 at both reads and zero rows => the known reduction). The socket check is ADVISORY corroboration: it can add a
          failure, never a pass, and is never the basis of the network verdict (interface addresses + independent kernel link state).
These tests pin the semantics, the data-flow claim, the attacks (loopback inflation, small counters, churn) and the documentation."""
import itertools
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_genesis_v2_tier0s_final_blockers import LO_BLOCK, en_block, link_host
from tests.test_genesis_v2_tier0s_phase_gate import GOOD_ROUTES, GOOD_ROUTES6, INFRA, ROOT, G, good_host, run, st
from tests.test_genesis_v2_tier0s_w1_w2 import SOCK_HEAD, pcb, raises, rows_of, sockets_text, tcp_rows

CODE = G.COMPLETENESS
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS host integration")
DOC = INFRA / "GENESIS_V2_TIER0S_PCB_REMEDIATION.md"


# ======================================================================================================================== the rule itself
def accepts(rows, counters):
    try:
        G.check_socket_plausibility(rows, counters)
        return True
    except G.TelemetryError as e:
        assert e.reason == CODE
        return False


def test_PCB_the_unsound_constants_are_gone():
    assert not hasattr(G, "PCB_MAX_EXCESS") and not hasattr(G, "PCB_MIN_RATIO")
    src = Path(G.__file__).read_text()
    assert "PCB_MAX_EXCESS" not in src and "PCB_MIN_RATIO" not in src and "0.75" not in src.split("def check_socket_plausibility")[1].split("def parse_linkstate")[0]


@pytest.mark.parametrize("counter", [0, 1, 2, 3, 5, 10, 20])
def test_PCB_small_counters_have_one_explained_behaviour(counter):
    """Counter 0: nothing is claimed either way (rows may exist: sockets can open after the read). Counter >= 1: at least one row is required, no more."""
    for rows in (0, 1, 2, 3, 5, 10, 20, 40, 300):
        expected = not (counter >= 1 and rows == 0)
        assert accepts(rows_of(sockets_text(tcp=rows)), pcb(counter)) is expected, (counter, rows)


@pytest.mark.parametrize("seed", range(8))
def test_PCB_a_genuine_table_is_never_rejected_whatever_the_lifecycle_state(seed):
    """Model of the measured behaviour: counter = live + closed-not-reclaimed, rows = live + a few the counter does not count. Any such non-empty table is accepted, with no
    constant fitted to a host."""
    rnd = random.Random(seed)
    for _ in range(500):
        live, dead, uncounted = rnd.randint(1, 600), rnd.randint(0, 900), rnd.randint(0, 40)
        c0, c1 = live + dead, live + dead + rnd.randint(-3, 3)
        assert accepts(rows_of(sockets_text(tcp=live + uncounted)), pcb(max(0, c0), tcp_after=max(0, c1)))


def test_PCB_the_measured_closed_pcb_case_is_accepted():
    """Measured: counter 472 with 284 listed rows after 100 connections closed (ratio 0.60). The earlier 0.75 floor rejected this genuine table."""
    assert accepts(rows_of(sockets_text(tcp=284)), pcb(472))
    assert accepts(rows_of(sockets_text(tcp=84)), pcb(72))                                            # measured idle: rows exceed the counter by 12
    assert accepts(rows_of(sockets_text(tcp=88)), pcb(72))                                            # measured idle: excess 16 (+12 rejected this)


@pytest.mark.parametrize("c", [1, 2, 3, 50, 10 ** 6])
def test_PCB_whole_table_disappearance_is_detected_for_every_nonzero_counter(c):
    assert not accepts(rows_of(sockets_text(tcp=0)), pcb(c))
    assert not accepts(rows_of(sockets_text(tcp=3, icm=0)), pcb(5, c))                                  # the raw class is judged separately


def test_PCB_the_bracket_needs_a_nonzero_counter_at_BOTH_reads():
    assert accepts(rows_of(sockets_text()), pcb(0, tcp_after=9))         # a socket may have appeared during the query
    assert accepts(rows_of(sockets_text()), pcb(9, tcp_after=0))
    assert not accepts(rows_of(sockets_text()), pcb(1, tcp_after=9))


@pytest.mark.parametrize("bad", [None, {}, {"before": {}, "after": {}}, {"before": {"tcp": -1, "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": True, "raw": 0}, "after": {"tcp": 1, "raw": 0}},
                                 {"before": {"tcp": 1.5, "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": "5", "raw": 0}, "after": {"tcp": 5, "raw": 0}},
                                 {"before": {"tcp": float("nan"), "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": 2 ** 63, "raw": 0}, "after": {"tcp": 5, "raw": 0}}, [1], "x", 5,
                                 {"before": {"tcp": 5, "raw": 0}}, {"before": {"tcp": 5, "raw": 0, "x": 1}, "after": {"tcp": 5, "raw": 0}}])
def test_PCB_malformed_counter_structures_are_FAIL_CLOSED_through_the_whole_gate_and_never_crash(tmp_path, bad):
    res = run("forge", tmp_path, host=good_host(tmp_path, pcbcounts=bad))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


# ======================================================================================================================== data-flow proof, tested
def usable_host(tmp, **kw):
    """A host with usable non-loopback networking: UP en0, kernel link ACTIVE, a global IPv4 address and a default route -- everything consistent."""
    ifc = LO_BLOCK + ("en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n\tinet 192.0.2.50 netmask 0xffffff00\n\tmedia: autoselect\n\tstatus: active\n")
    h = good_host(tmp, ifconfig=ifc, routes4=GOOD_ROUTES + "default 192.0.2.1 UGScg en0\n192.0.2/24 link#4 UCS en0\n", routes6=GOOD_ROUTES6,
                  ifaddrs=[{"name": "lo0", "flags": 0x8049, "v4": ["127.0.0.1"], "v6": ["::1", "fe80::1"]}, {"name": "en0", "flags": 0x8863, "v4": ["192.0.2.50"], "v6": []}],
                  linkstate={"lo0": "no_media", "en0": "active"})
    h.update(kw)
    return h


def ext_rows(n):
    return "".join(f"tcp4       0      0  192.0.2.50.{50000 + i}     198.51.100.{i % 250 + 1}.443     ESTABLISHED\n" for i in range(n))


def table(loop=0, ext=0, tail=""):
    return SOCK_HEAD + tcp_rows(loop, 0) + ext_rows(ext) + tail + "\nActive Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"


@pytest.mark.parametrize("seed", range(4))
def test_PCB_NO_socket_table_or_counter_can_turn_a_network_violation_into_a_PASS(tmp_path, seed):
    """THE DATA-FLOW CLAIM. With usable networking present, the interface verdict is FAIL for EVERY socket table and EVERY counter value, so the socket count is not
    load-bearing: removing all external rows, inflating the counters, emptying the table or corrupting the counters never produces a gate PASS."""
    rnd = random.Random(seed)
    for _ in range(60):
        loop, ext = rnd.choice([0, 1, 10, 100, 200]), rnd.choice([0, 0, 1, 3, 60])
        counters = rnd.choice([pcb(loop + ext), pcb(0), pcb(loop + ext + rnd.choice([0, 1, 50, 5000])), pcb(rnd.randint(0, 3000), tcp_after=rnd.randint(0, 3000)), None, {"x": 1}])
        res = run("forge", tmp_path, host=usable_host(tmp_path, sockets=table(loop, ext), pcbcounts=counters))
        assert st(res, "network_interfaces_disabled") == G.FAIL and not G.gate_passes(res), (loop, ext, counters)
        assert st(res, "network_no_default_route") == G.FAIL


def test_PCB_the_interface_verdict_does_not_read_the_socket_input_at_all(tmp_path):
    """Same host, three different socket worlds: the interface check's status and detail are byte-identical."""
    outs = set()
    for sockets, counters in ((table(0, 0), pcb(0)), (table(200, 60), pcb(260)), (table(0, 0), pcb(5000))):
        r = run("forge", tmp_path, host=usable_host(tmp_path, sockets=sockets, pcbcounts=counters))["network_interfaces_disabled"]
        outs.add(json.dumps(r, sort_keys=True))
    assert len(outs) == 1


def test_PCB_a_missing_socket_source_only_adds_failures_on_a_quiet_host(tmp_path):
    base = run("forge", tmp_path)
    assert G.gate_passes(base)
    for kw in ({"sockets": None}, {"pcbcounts": None}, {"sockets": "garbage"}):
        res = run("forge", tmp_path, host=good_host(tmp_path, **kw))
        assert not G.gate_passes(res)


def test_PCB_the_socket_PASS_is_advisory_and_says_what_it_does_not_show(tmp_path):
    r = run("forge", tmp_path)["network_no_external_sockets"]
    assert r["status"] == G.PASS and r.get("advisory") is True
    assert "ADVISORY" in r["detail"] and "individual rows may be missing" in r["detail"] and "loopback sockets can inflate the counters" in r["detail"]
    assert "bounded plausibility band" not in r["detail"]


# ======================================================================================================================== loopback inflation
@pytest.mark.parametrize("created", [0, 1, 10, 50, 100, 250])
def test_PCB_loopback_inflation_changes_nothing_that_matters(tmp_path, created):
    """An attacker who creates N loopback sockets raises the counter by N and adds N loopback rows. Under the old band this widened the removable margin to every external row;
    under the new rule the margin is unchanged by construction (only an empty table is refused) and the network verdict does not read sockets at all."""
    ext = 60
    for kept in (ext, 1, 0):                                   # external rows kept after the (hypothetical) reduction
        counters = pcb(ext + created)
        accepted = accepts(rows_of(table(created, kept)), counters)
        assert accepted == (created + kept >= 1)                # refused only when NOTHING is listed
        res = run("forge", tmp_path, host=usable_host(tmp_path, sockets=table(created, kept), pcbcounts=counters))
        assert not G.gate_passes(res) and st(res, "network_interfaces_disabled") == G.FAIL


def test_PCB_the_documentation_states_the_loopback_inflation_implication():
    d = " ".join(G.__doc__.split())
    assert "Anyone who can create loopback sockets can raise the counters at will" in d and "every external listener, can therefore be missing from an accepted table" in d


# ======================================================================================================================== reduced view is still detected
ONLY_UNIX = "Active Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"


def test_PCB_the_reduced_view_signatures_all_still_fail_closed(tmp_path):
    for kw in ({"sockets": ONLY_UNIX, "pcbcounts": pcb(120, 3)}, {"sockets": table(0, 0), "pcbcounts": pcb(120, 3)},
               {"ifconfig": re.sub("aa:bb:cc:dd:ee:ff", "02:00:00:00:00:00", good_host(tmp_path)["ifconfig"])}):
        res = run("forge", tmp_path, host=good_host(tmp_path, **kw))
        assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res), kw.keys()
        assert all(f"{k}={CODE}" in res["telemetry_complete"]["detail"] for k in ("ifconfig", "routes4", "routes6", "sockets"))


# ======================================================================================================================== route rule
def _routes(extra4="", extra6=""):
    return GOOD_ROUTES + extra4, GOOD_ROUTES6 + extra6


def test_PCB_a_route_naming_an_unknown_interface_is_FAIL_CLOSED(tmp_path):
    r4, r6 = _routes(extra4="198.51.100/24 link#9 UCS en77\n")
    res = run("forge", tmp_path, host=good_host(tmp_path, routes4=r4, routes6=r6))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and st(res, "network_no_default_route") == G.FAIL_CLOSED and f"routes4={CODE}" in res["telemetry_complete"]["detail"]
    r4, r6 = _routes(extra6="fe80::%en77/64 link#9 UCI en77\n")
    assert not G.gate_passes(run("forge", tmp_path, host=good_host(tmp_path, routes4=r4, routes6=r6)))


def test_PCB_a_route_via_an_interface_that_exists_without_an_address_is_not_refused(tmp_path):
    """No evidence shows that to be abnormal (the live host had none; none is invented). The interface exists in the inventory, so the rule does not apply."""
    ifc = LO_BLOCK + en_block("none", "inactive", True) + "utun9: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n\tnd6 options=201<PERFORMNUD,DAD>\n"
    r4, r6 = _routes(extra4="198.51.100/24 link#9 UCS utun9\n")
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=ifc, routes4=r4, routes6=r6, linkstate={"lo0": "no_media", "en0": "inactive", "utun9": "no_media"}))
    assert st(res, "telemetry_complete") == G.PASS and G.gate_passes(res)


def test_PCB_the_route_rule_never_removes_a_violation(tmp_path):
    r4, r6 = _routes(extra4="default 192.0.2.1 UGScg en77\n")
    res = run("forge", tmp_path, host=good_host(tmp_path, routes4=r4, routes6=r6))
    assert st(res, "network_no_default_route") == G.FAIL                                                # a default route is a violation first
    assert not G.gate_passes(res)


# ======================================================================================================================== parser diagnostics: the socket parser's own entry
@pytest.mark.parametrize("exc", [KeyError("x"), AttributeError("x"), ZeroDivisionError(), IndexError("x"), RuntimeError("SECRET-203.0.113.77")])
def test_PCB_an_injected_socket_parser_defect_reports_its_OWN_entry_without_leaking(tmp_path, monkeypatch, exc):
    monkeypatch.setattr(G, "parse_sockets", lambda t: (_ for _ in ()).throw(exc))
    res = run("forge", tmp_path, host=good_host(tmp_path))
    d = res["telemetry_complete"]["detail"]
    assert f"sockets=PARSER_DEFECT:{type(exc).__name__}" in d
    assert "SECRET" not in json.dumps(res) and "203.0.113.77" not in json.dumps(res)
    assert st(res, "network_no_external_sockets") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_PCB_the_detail_lists_every_unverified_source_so_no_entry_is_hidden_by_earlier_ones(tmp_path, monkeypatch):
    monkeypatch.setattr(G, "parse_sockets", lambda t: (_ for _ in ()).throw(KeyError("x")))
    monkeypatch.setattr(G, "parse_routes4", lambda t: (_ for _ in ()).throw(TypeError("x")))
    d = run("forge", tmp_path, host=good_host(tmp_path))["telemetry_complete"]["detail"]
    assert "sockets=PARSER_DEFECT:KeyError" in d and "routes4=PARSER_DEFECT:TypeError" in d


# ======================================================================================================================== link-state regression (preserved)
def test_PCB_the_original_false_PASS_construction_still_does_not_pass(tmp_path):
    ifc = LO_BLOCK + "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n\tinet6 fe80::a1b2%en0 prefixlen 64 scopeid 0x4\n\tmedia: autoselect\n"
    h = link_host(tmp_path, "ll6", None, True, "active")
    assert st(run("forge", tmp_path, host=h), "network_interfaces_disabled") == G.FAIL and not G.gate_passes(run("forge", tmp_path, host=h))
    assert ifc  # the textual construction (UP, link-local only, no `status:` line) is exactly the fixture's ifconfig


# ======================================================================================================================== live macOS (real kernel, real tools, real lineages)
LIVE = r'''
import importlib.util, json, subprocess, sys
s = importlib.util.spec_from_file_location("g", sys.argv[1]); G = importlib.util.module_from_spec(s); s.loader.exec_module(G)
h = G.collect_host()
try:
    socks = G.parse_sockets(h["sockets"]); pc = G.parse_pcbcounts(h["pcbcounts"]); G.check_socket_plausibility(socks, pc); sock = "OK"; rows = len(socks)
except G.TelemetryError as e:
    sock, rows = e.reason, -1
r = G.evaluate("forge", host=h)
print(json.dumps({"sock": sock, "rows": rows, "telemetry": r["telemetry_complete"]["status"], "full_view": "Active Internet" in (h.get("sockets") or "")}))
'''
GATE_PATH = str(ROOT / "scripts" / "genesis_v2_tier0s_phase_gate.py")


def _live(argv):
    p = subprocess.run(argv + ["-c", LIVE, GATE_PATH], capture_output=True, text=True, timeout=240)
    return json.loads(p.stdout.strip().splitlines()[-1])


@darwin
def test_PCB_LIVE_the_genuine_unfiltered_table_is_accepted_repeatedly():
    """The defect: 28 of 30 genuine samples were rejected. Twenty consecutive genuine samples must all be accepted now (skipped where the lineage is reduced)."""
    if not Path("/usr/bin/python3").exists():
        pytest.skip("system python not present")
    first = _live(["/usr/bin/python3"])
    if not first["full_view"]:
        pytest.skip("this lineage received the reduced view")
    results = [first] + [_live(["/usr/bin/python3"]) for _ in range(19)]
    assert all(r["sock"] == "OK" and r["rows"] > 0 for r in results), [r for r in results if r["sock"] != "OK"]


@darwin
def test_PCB_LIVE_a_reduced_lineage_is_still_FAIL_CLOSED():
    r = _live([sys.executable])
    if r["full_view"]:
        pytest.skip("this lineage received the full view")
    assert r["telemetry"] == "FAIL_CLOSED" and r["sock"] in (CODE, "MALFORMED")         # the empty Internet section is refused by the parser or by the non-emptiness rule


# ======================================================================================================================== documentation
def test_PCB_the_final_document_exists_and_classifies_every_claim():
    txt = DOC.read_text()
    rows = [l for l in txt.splitlines() if re.match(r"^\| P\d+ \|", l)]
    assert len(rows) >= 14
    classes = {l.split("|")[2].strip() for l in rows}
    assert classes <= {"ENFORCED", "ADVISORY", "PROCEDURAL", "UNPROVEN"} and {"ENFORCED", "ADVISORY", "UNPROVEN"} <= classes, classes
    for l in rows:
        if re.search(r"(?i)completeness of the socket|row-by-row|individual listener|UDP|loopback", l):
            assert l.split("|")[2].strip() in ("ADVISORY", "UNPROVEN"), l


def test_PCB_the_matrix_maps_every_finding_to_regression_tests_that_exist():
    txt = DOC.read_text()
    sources = Path(__file__).read_text()
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (PF[0-9]+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`(test_PCB_[^`]+)`", line)
        seen[m.group(1)] = names
        assert names, f"{m.group(1)} has no regression tests"
        for t in names:
            assert re.search(rf"def {re.escape(t)}\b", sources), f"{m.group(1)}: {t} does not exist"
    assert set(seen) == {"PF1", "PF2", "PF3", "PF4", "PF5", "PF6"}


def test_PCB_no_document_still_describes_12_as_a_constant_or_the_band_as_a_completeness_check():
    bad = {}
    for p in sorted(INFRA.glob("GENESIS_V2_TIER0S_*.md")):
        t = " ".join(p.read_text().split())
        for w in ("measured constant excess", "bounded plausibility band", "within the band", "rows <= higher counter + 12", "rows >= max(1, floor(0.75"):
            for m in re.finditer(re.escape(w), t):
                ctx = t[max(0, m.start() - 260):m.end() + 260].lower()
                if not any(k in ctx for k in ("withdrawn", "superseded", "falsified", "was ", "earlier")):
                    bad.setdefault(p.name, []).append(w)
    assert bad == {}, bad


def test_PCB_the_acceptance_status_document_mentions_the_independent_link_state():
    t = " ".join((INFRA / "GENESIS_V2_TIER0S_ACCEPTANCE_STATUS.md").read_text().split())
    assert "SIOCGIFMEDIA" in t and "advisory" in t.lower() and "non-emptiness" in t.lower()

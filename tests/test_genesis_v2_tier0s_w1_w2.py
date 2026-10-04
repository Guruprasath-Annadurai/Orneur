"""Tier0-S W1/W2 acceptance-blocking remediation (+ W3, W5, W6) -- regression tests.

W1  telemetry COMPLETENESS: a structurally valid view whose completeness cannot be shown is FAIL_CLOSED (TELEMETRY_COMPLETENESS_UNPROVEN).
W2  documentation: no statement claims that parsing proves completeness.
W3  expected operational failures give structured gate errors (no traceback); unexpected defects stay visible.
W5  the other-role storage check is named and worded for what it establishes (configured identifiers not observed; ADVISORY).
W6  cryptographic_verify returns typed problems for expected invalid input and lets genuine defects propagate.

Portable tests use synthetic host telemetry and never hard-code a real host's counts. The `live_macos` tests run the REAL gate in real process lineages and compare
the gate's verdict with an independently measured ground truth; they skip off macOS."""
import copy
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_genesis_v2_tier0a_transfer_bundle import bundle  # noqa: F401  (pytest fixture: synthetic sealed bundle, ephemeral key)
from tests.test_genesis_v2_tier0s_phase_gate import (BOOT_A, GOOD_DISKS, GOOD_IFCONFIG, GOOD_ROUTES, GOOD_ROUTES6, INFRA, ROOT, SOCK_TAIL, G, good_host, make_cfg,
                                                     nonroot, run, st)

CODE = G.COMPLETENESS
SOCK_HEAD = "Active Internet connections (including servers)\nProto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n"
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS host integration")


def tcp_rows(n, ext=0):
    rows = "".join(f"tcp4       0      0  127.0.0.1.{20000 + i}       *.*                    LISTEN\n" for i in range(n - ext))
    return rows + "".join(f"tcp4       0      0  203.0.113.9.{30000 + i}      *.*                    LISTEN\n" for i in range(ext))


def sockets_text(tcp=0, ext=0, icm=0, udp=0):
    body = tcp_rows(tcp, ext) + "".join("icm4       0      0  *.*                    *.*                    \n" for _ in range(icm))
    body += "".join(f"udp4       0      0  *.{40000 + i}                 *.*                    \n" for i in range(udp))
    return SOCK_HEAD + body + SOCK_TAIL


def pcb(tcp, raw=0, tcp_after=None, raw_after=None):
    return {"before": {"tcp": tcp, "raw": raw}, "after": {"tcp": tcp if tcp_after is None else tcp_after, "raw": raw if raw_after is None else raw_after}}


def rows_of(text):
    return G.parse_sockets(text)


def raises(fn, *a):
    with pytest.raises(G.TelemetryError) as e:
        fn(*a)
    return e.value


# ======================================================================================================================== W1: socket completeness
@pytest.mark.parametrize("seed", range(8))
def test_W1_complete_tables_pass_for_random_counts_without_hard_coded_host_numbers(seed):
    rnd = random.Random(seed)
    tcp, icm = rnd.randint(0, 400), rnd.randint(0, 6)
    rows = rows_of(sockets_text(tcp=tcp, icm=icm))
    jitter = rnd.randint(0, 5)
    G.check_socket_plausibility(rows, pcb(max(0, tcp - jitter), icm, tcp_after=tcp + jitter))      # natural churn between the two counter reads is tolerated


def test_W1_the_normal_unfiltered_shape_passes_end_to_end(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path))
    assert st(res, "telemetry_complete") == G.PASS and G.gate_passes(res)


def test_W1_internet_section_removed_while_sockets_exist_is_COMPLETENESS_UNPROVEN(tmp_path):
    """The exact observed reduced view: no Internet section at all, but the kernel counters show sockets."""
    only_unix = "Active Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"
    res = run("forge", tmp_path, host=good_host(tmp_path, sockets=only_unix, pcbcounts=pcb(120, 3)))
    assert st(res, "network_no_external_sockets") == G.FAIL_CLOSED and CODE in res["network_no_external_sockets"]["detail"]
    assert f"sockets={CODE}" in res["telemetry_complete"]["detail"] and not G.gate_passes(res)


def test_W1_complete_rows_removed_is_detected():
    e = raises(G.check_socket_plausibility, rows_of(sockets_text(tcp=0)), pcb(60))
    assert e.reason == CODE and "tcp socket rows" in str(e)


@pytest.mark.parametrize("have,counter", [(10, 100), (30, 100), (74, 100), (1, 4), (0, 1), (2, 12)])
def test_W1_removal_of_most_rows_is_detected(have, counter):
    raises(G.check_socket_plausibility, rows_of(sockets_text(tcp=have)), pcb(counter))


def test_W1_documented_limit_removal_of_a_FEW_rows_is_NOT_detected():
    """Honest residual: the band detects the section / the majority, not individual rows. This test pins that the documentation says so."""
    G.check_socket_plausibility(rows_of(sockets_text(tcp=99)), pcb(100))
    assert "does NOT detect removal of a few rows" in " ".join(G.check_socket_plausibility.__doc__.split())


def test_W1_header_only_table_with_sockets_present_is_unproven_but_with_no_sockets_is_verified_empty():
    raises(G.check_socket_plausibility, rows_of(sockets_text()), pcb(40))
    G.check_socket_plausibility(rows_of(sockets_text()), pcb(0))                                       # nothing exists, nothing is listed: consistent


@pytest.mark.parametrize("rows,counter", [(400, 3), (100, 0), (60, 20)])
def test_W1_rows_wildly_above_the_counter_are_implausible(rows, counter):
    raises(G.check_socket_plausibility, rows_of(sockets_text(tcp=rows)), pcb(counter))


def test_W1_counter_bracket_uses_both_reads_so_natural_churn_does_not_cause_failure_but_a_real_gap_does():
    G.check_socket_plausibility(rows_of(sockets_text(tcp=55)), pcb(50, tcp_after=80))
    raises(G.check_socket_plausibility, rows_of(sockets_text(tcp=30)), pcb(50, tcp_after=80))


def test_W1_raw_icmp_class_is_checked_independently():
    G.check_socket_plausibility(rows_of(sockets_text(tcp=10, icm=3)), pcb(10, 3))
    raises(G.check_socket_plausibility, rows_of(sockets_text(tcp=10, icm=0)), pcb(10, 3))


def test_W1_UDP_is_deliberately_not_compared_and_the_documentation_says_why():
    assert set(G.PCB_COUNTERS) == {"tcp", "raw"} and "udp" not in G.PCB_COUNTERS
    G.check_socket_plausibility(rows_of(sockets_text(tcp=5, udp=0)), pcb(5))                           # UDP rows absent: no failure, no claim
    d = " ".join(G.__doc__.split())
    assert "UDP rows are therefore observation-only" in d and "UDP completeness is unproven and UDP absence is not claimed" in d


def test_W1_udp_rows_are_still_observed_and_can_only_add_a_failure(tmp_path):
    ext_udp = SOCK_HEAD + "udp4       0      0  203.0.113.9.123        *.*                    \n" + SOCK_TAIL
    res = run("forge", tmp_path, host=good_host(tmp_path, sockets=ext_udp))
    assert st(res, "network_no_external_sockets") == G.FAIL


@pytest.mark.parametrize("reason", ["UNAVAILABLE", "PERMISSION_DENIED", "UNSUPPORTED", "MALFORMED"])
def test_W1_unavailable_or_failed_counter_source_is_FAIL_CLOSED(tmp_path, reason):
    h = good_host(tmp_path, pcbcounts=None); h["telemetry"] = {"pcbcounts": reason}
    res = run("forge", tmp_path, host=h)
    assert f"pcbcounts={reason}" in res["telemetry_complete"]["detail"] and st(res, "network_no_external_sockets") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_W1_a_missing_counter_field_is_not_a_pass(tmp_path):
    h = good_host(tmp_path); del h["pcbcounts"]
    res = run("forge", tmp_path, host=h)
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and st(res, "network_no_external_sockets") == G.FAIL_CLOSED


BAD_COUNTERS = [
    "5", 5, None, [], {}, {"before": {"tcp": 1, "raw": 0}}, {"before": {"tcp": 1, "raw": 0}, "after": {"tcp": 1, "raw": 0}, "extra": 1},
    {"before": {"tcp": "1", "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": -1, "raw": 0}, "after": {"tcp": 1, "raw": 0}},
    {"before": {"tcp": True, "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": 1.5, "raw": 0}, "after": {"tcp": 1, "raw": 0}},
    {"before": {"tcp": None, "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": 10 ** 9, "raw": 0}, "after": {"tcp": 1, "raw": 0}},
    {"before": {"tcp": 2 ** 70, "raw": 0}, "after": {"tcp": 1, "raw": 0}}, {"before": {"tcp": 1}, "after": {"tcp": 1, "raw": 0}},
    {"before": {"tcp": 1, "raw": 0, "udp": 3}, "after": {"tcp": 1, "raw": 0}}, {"before": [1, 0], "after": [1, 0]},
    {"before": {"tcp": float("nan"), "raw": 0}, "after": {"tcp": 1, "raw": 0}},
]


@pytest.mark.parametrize("bad", BAD_COUNTERS, ids=lambda b: repr(b)[:48])
def test_W1_malformed_or_implausible_counters_are_FAIL_CLOSED_and_never_crash(tmp_path, bad):
    res = run("forge", tmp_path, host=good_host(tmp_path, pcbcounts=bad))
    assert st(res, "network_no_external_sockets") == G.FAIL_CLOSED and st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_W1_counter_reads_use_the_fixed_tool_and_reject_non_integers(monkeypatch):
    calls = []

    def fake(cmd):
        calls.append(tuple(cmd)); return "OK", "  42 \n"
    monkeypatch.setattr(G, "_run", fake)
    assert G._read_counters() == {"tcp": 42, "raw": 42} and all(c[0] == "sysctl" and c[1] == "-n" for c in calls)
    for junk in ("", "-1\n", "4 2\n", "0x10\n", "9" * 20 + "\n", "five\n", "1e3\n", "٣\n"):
        monkeypatch.setattr(G, "_run", lambda cmd, j=junk: ("OK", j))
        raises(G._read_counters)
    monkeypatch.setattr(G, "_run", lambda cmd: ("PERMISSION_DENIED", None))
    assert raises(G._read_counters).reason == "PERMISSION_DENIED"


def test_W1_collect_host_brackets_the_socket_query_with_two_counter_reads(monkeypatch):
    order = []
    monkeypatch.setattr(G, "_read_counters", lambda: (order.append("counters"), {"tcp": 1, "raw": 0})[1])
    monkeypatch.setattr(G, "_run", lambda cmd: (order.append(cmd[0] + ":" + (cmd[1] if len(cmd) > 1 else "")), ("UNAVAILABLE", None))[1])
    monkeypatch.setattr(G, "read_ifaddrs", lambda: [])
    G.collect_host()
    i = order.index("counters")
    assert order[i + 1] == "netstat:-an" and order[i + 2] == "counters"


# ======================================================================================================================== W1: interface completeness
def ia(name, flags=1, v4=(), v6=()):
    return {"name": name, "flags": flags, "v4": list(v4), "v6": list(v6)}


LO = ia("lo0", 1 | 8 | 0x40, ["127.0.0.1"], ["::1", "fe80::1"])
EN = ia("en0", 1)


def host_ifs(tmp, ifaddrs, ifindex, ifconfig=GOOD_IFCONFIG):
    return good_host(tmp, ifconfig=ifconfig, ifaddrs=ifaddrs, ifindex=ifindex)


def test_W1_agreeing_independent_inventories_pass(tmp_path):
    res = run("forge", tmp_path, host=host_ifs(tmp_path, [LO, EN], ["en0", "lo0"]))                   # reordered but equivalent
    assert st(res, "network_interfaces_disabled") == G.PASS and st(res, "telemetry_complete") == G.PASS


@pytest.mark.parametrize("label,ifaddrs,ifindex", [
    ("interface missing from getifaddrs", [LO], ["lo0", "en0"]),
    ("interface missing from if_nameindex", [LO, EN], ["lo0"]),
    ("extra interface in getifaddrs", [LO, EN, ia("en9", 1)], ["lo0", "en0"]),
    ("extra interface in if_nameindex", [LO, EN], ["lo0", "en0", "en9"]),
    ("renamed interface", [LO, ia("en1", 1)], ["lo0", "en0"]),
])
def test_W1_an_interface_that_silently_disappears_from_any_view_is_COMPLETENESS_UNPROVEN(tmp_path, label, ifaddrs, ifindex):
    res = run("forge", tmp_path, host=host_ifs(tmp_path, ifaddrs, ifindex))
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and CODE in res["network_interfaces_disabled"]["detail"], label


@pytest.mark.parametrize("label,en", [
    ("getifaddrs sees an IPv4 address ifconfig does not", ia("en0", 1, ["203.0.113.5"])),
    ("getifaddrs sees an IPv6 address ifconfig does not", ia("en0", 1, [], ["2001:db8::5"])),
    ("UP flag differs", ia("en0", 0)),
    ("LOOPBACK flag differs", ia("en0", 1 | 8)),
])
def test_W1_address_or_flag_discrepancies_are_COMPLETENESS_UNPROVEN(tmp_path, label, en):
    res = run("forge", tmp_path, host=host_ifs(tmp_path, [LO, en], ["lo0", "en0"]))
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and CODE in res["network_interfaces_disabled"]["detail"], label


def test_W1_kame_embedded_scope_in_getifaddrs_link_local_is_normalized_not_a_false_mismatch(tmp_path):
    lo = ia("lo0", 1 | 8 | 0x40, ["127.0.0.1"], ["::1", "fe80:1::1"])                                     # fe80:1::1 == fe80::1 with the scope id embedded in bytes 2-3
    res = run("forge", tmp_path, host=host_ifs(tmp_path, [lo, EN], ["lo0", "en0"]))
    assert st(res, "network_interfaces_disabled") == G.PASS


def test_W1_duplicate_missing_or_malformed_independent_inventories_fail_closed(tmp_path):
    for label, kw in {"duplicate names in getifaddrs": dict(ifaddrs=[LO, EN, ia("en0", 1)], ifindex=["lo0", "en0"]),
                      "duplicate names in if_nameindex": dict(ifaddrs=[LO, EN], ifindex=["lo0", "en0", "en0"]),
                      "no loopback in getifaddrs": dict(ifaddrs=[ia("en0", 1)], ifindex=["en0"]),
                      "empty getifaddrs": dict(ifaddrs=[], ifindex=["lo0", "en0"]), "empty if_nameindex": dict(ifaddrs=[LO, EN], ifindex=[]),
                      "bad address string": dict(ifaddrs=[ia("lo0", 9, ["127.0.0.999"]), EN], ifindex=["lo0", "en0"]),
                      "negative flags": dict(ifaddrs=[ia("lo0", -1), EN], ifindex=["lo0", "en0"]),
                      "bool flags": dict(ifaddrs=[ia("lo0", True), EN], ifindex=["lo0", "en0"]),
                      "name with a space": dict(ifaddrs=[LO, ia("en 0", 1)], ifindex=["lo0", "en 0"]),
                      "not a list": dict(ifaddrs="lo0", ifindex=["lo0", "en0"])}.items():
        res = run("forge", tmp_path, host=good_host(tmp_path, **kw))
        assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and not G.gate_passes(res), label


@pytest.mark.parametrize("key", ["ifaddrs", "ifindex"])
@pytest.mark.parametrize("reason", ["UNAVAILABLE", "PERMISSION_DENIED", "UNSUPPORTED", "MALFORMED"])
def test_W1_an_unavailable_independent_inventory_means_completeness_is_unproven(tmp_path, key, reason):
    h = good_host(tmp_path, **{key: None}); h["telemetry"] = {key: reason}
    res = run("forge", tmp_path, host=h)
    assert f"{key}={reason}" in res["telemetry_complete"]["detail"] and st(res, "network_interfaces_disabled") == G.FAIL_CLOSED


def test_W1_a_temporary_failure_of_one_source_during_collection_fails_closed(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("UNAVAILABLE", None))
    monkeypatch.setattr(G, "read_ifaddrs", lambda: (_ for _ in ()).throw(G.TelemetryError("UNAVAILABLE", "getifaddrs failed")))
    h = G.collect_host()
    assert h["ifaddrs"] is None and h["telemetry"]["ifaddrs"] == "UNAVAILABLE"
    monkeypatch.setattr(G, "read_ifaddrs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert G.collect_host()["telemetry"]["ifaddrs"] == "UNAVAILABLE"                                    # an unexpected error in the independent source is still a refusal


def test_W1_read_ifaddrs_is_macOS_only_and_never_searches_a_library_path():
    src = Path(G.__file__).read_text()
    assert "ctypes.CDLL(None" in src and "find_library" not in src
    if sys.platform != "darwin":
        assert raises(G.read_ifaddrs).reason == "UNSUPPORTED"


@darwin
def test_W1_live_getifaddrs_and_if_nameindex_agree_with_ifconfig_l():
    import socket
    names = sorted(r["name"] for r in G.read_ifaddrs())
    status, out = G._run(["ifconfig", "-l"])
    assert status == "OK" and names == sorted(out.split()) == sorted(n for _, n in socket.if_nameindex())


# ======================================================================================================================== W1: reduced-view signature, routes, composite
def with_ether(mac_for_en0):
    return GOOD_IFCONFIG.replace("ether aa:bb:cc:dd:ee:ff", "ether " + mac_for_en0)


@pytest.mark.parametrize("mac", ["02:00:00:00:00:00", "02:00:00:00:00:00".upper()])
def test_W1_the_redaction_constant_marks_every_network_source_unproven(tmp_path, mac):
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=with_ether(mac)))
    detail = res["telemetry_complete"]["detail"]
    assert all(f"{k}={CODE}" in detail for k in ("ifconfig", "routes4", "routes6", "sockets")) and not G.gate_passes(res)
    for k in ("network_interfaces_disabled", "network_no_default_route", "network_no_external_sockets"):
        assert st(res, k) == G.FAIL_CLOSED


def test_W1_a_real_looking_hardware_address_is_not_a_signal(tmp_path):
    assert G.gate_passes(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=with_ether("aa:bb:cc:11:22:33"))))


def test_W1_the_indicator_is_documented_as_an_indicator_not_proof():
    assert "INDICATOR of the reduced telemetry view, not proof" in " ".join(G.redacted_hardware_addresses.__doc__.split()) and "fails closed, which is safe" in " ".join(G.__doc__.split())


def test_W1_a_violation_visible_in_a_reduced_view_remains_a_FAIL_not_hidden_as_unknown(tmp_path):
    bad = GOOD_IFCONFIG.replace("status: inactive", "status: active").replace("ether aa:bb:cc:dd:ee:ff", "ether 02:00:00:00:00:00")
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=bad))
    assert st(res, "network_interfaces_disabled") == G.FAIL and st(res, "telemetry_complete") == G.FAIL_CLOSED


def reduced_view_host(tmp):
    """Synthetic reproduction of the observed reduced view: no Internet section, redacted hardware addresses, neighbour routes absent, kernel counters non-zero."""
    only_unix = "Active Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"
    return good_host(tmp, ifconfig=with_ether("02:00:00:00:00:00"), sockets=only_unix, pcbcounts=pcb(150, 3))


def test_W1_synthetic_reproduction_of_the_observed_reduced_view_never_passes_and_leaks_no_host_data(tmp_path):
    res = run("forge", tmp_path, host=reduced_view_host(tmp_path))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)
    for k in ("network_interfaces_disabled", "network_no_default_route", "network_no_external_sockets"):
        assert st(res, k) == G.FAIL_CLOSED and CODE in res[k]["detail"]
    blob = json.dumps(res)
    assert "203.0.113" not in blob and "aa:bb:cc" not in blob and "02:00:00:00:00:00" not in blob            # reasons carry codes and counts only, never host data


def test_W1_routes_must_cover_every_addressed_up_interface(tmp_path):
    up_en = ia("en0", 1, ["10.1.2.3"])
    lo_only_routes = GOOD_ROUTES
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG.replace("status: inactive", "status: inactive\n\tinet 10.1.2.3 netmask 0xffffff00"),
                                                ifaddrs=[LO, up_en], routes4=lo_only_routes))
    assert st(res, "network_interfaces_disabled") == G.FAIL                                           # the address is a violation regardless
    assert CODE in res["telemetry_complete"]["detail"] and "routes4" in res["telemetry_complete"]["detail"]
    ok_routes = GOOD_ROUTES + "10.1.2/24           link#4             UCS                   en0\n"
    r4 = G.parse_routes4(ok_routes); r6 = G.parse_routes6(GOOD_ROUTES6)
    G.check_route_interface_consistency(r4, r6, G.parse_ifaddrs([LO, up_en]))


def test_W1_route_consistency_ignores_down_or_unaddressed_interfaces_and_neighbour_routes():
    r4, r6 = G.parse_routes4(GOOD_ROUTES), G.parse_routes6(GOOD_ROUTES6)
    G.check_route_interface_consistency(r4, r6, G.parse_ifaddrs([LO, ia("en0", 0, ["10.0.0.5"]), ia("en1", 1)]))        # DOWN with address; UP without
    raises(G.check_route_interface_consistency, r4, r6, G.parse_ifaddrs([LO, ia("en0", 1, [], ["fe80::1"])]))             # UP with an IPv6 address but no IPv6 route row


def test_W1_the_default_route_check_never_claims_route_table_completeness(tmp_path):
    res = run("forge", tmp_path)
    d = res["network_no_default_route"]["detail"]
    assert st(res, "network_no_default_route") == G.PASS and "completeness is NOT claimed" in d and "interface addresses" in d
    assert res["network_no_default_route"]["advisory"] is True and d.startswith("ADVISORY")


def test_W1_the_raw_kernel_route_dump_is_documented_as_NOT_independent_of_netstat():
    doc = (INFRA / "GENESIS_V2_TIER0S_W1_W2_REMEDIATION.md").read_text()
    assert "raw kernel route dump" in doc and "filtered identically" in doc and "NOT independent" in doc


# ======================================================================================================================== W1: mutation testing of the completeness layer
def _norm_ifaddrs(v):
    return sorted((r["name"], r["flags"] & 9, tuple(sorted(r["v4"])), tuple(sorted(str(G._kame_fix(__import__("ipaddress").IPv6Address(x))) for x in r["v6"]))) for r in v)


@pytest.mark.parametrize("seed", range(6))
def test_W1_mutating_the_independent_inventory_is_always_detected_or_semantically_equal(tmp_path, seed):
    rnd = random.Random(seed)
    base = [LO, ia("en0", 1 | 0x40, ["10.9.8.7"], ["fe80::5"]), ia("awdl0", 1, [], ["fe80::9"])]
    cfg = GOOD_IFCONFIG.replace("status: inactive", "status: active\n\tinet 10.9.8.7 netmask 0xffffff00\n\tinet6 fe80::5%en0 prefixlen 64") + \
        "awdl0: flags=8943<UP,BROADCAST,RUNNING> mtu 1500\n\tinet6 fe80::9%awdl0 prefixlen 64\n\tstatus: inactive\n"
    ifs = G.parse_interfaces(cfg); names = [i["name"] for i in ifs]
    G.check_interface_inventory(ifs, G.parse_ifaddrs(base), names)
    survived_changed = []
    for _ in range(400):
        m = copy.deepcopy(base)
        op = rnd.choice(["drop", "rename", "flag", "v4", "v6", "dup", "addv4", "shuffle", "type"])
        i = rnd.randrange(len(m))
        if op == "drop": m.pop(i)
        elif op == "rename": m[i]["name"] = m[i]["name"] + "x"
        elif op == "flag": m[i]["flags"] ^= rnd.choice([1, 8])
        elif op == "v4": m[i]["v4"] = [rnd.choice(["10.9.8.8", "192.0.2.1", "127.0.0.2"])] if m[i]["v4"] else ["192.0.2.9"]
        elif op == "v6": m[i]["v6"] = ["fe80::77"]
        elif op == "dup": m.append(copy.deepcopy(m[i]))
        elif op == "addv4": m[i]["v4"] = m[i]["v4"] + ["198.51.100.1"]
        elif op == "shuffle": rnd.shuffle(m)
        elif op == "type": m[i]["flags"] = rnd.choice([None, "1", 1.5, True, [1]])
        try:
            G.check_interface_inventory(ifs, G.parse_ifaddrs(m), names)
        except G.TelemetryError:
            continue
        except Exception as e:                                                                              # nothing but TelemetryError may escape
            pytest.fail(f"{op}: {type(e).__name__}: {e}")
        if _norm_ifaddrs(m) != _norm_ifaddrs(base):
            survived_changed.append(op)
    assert survived_changed == []


@pytest.mark.parametrize("seed", range(4))
def test_W1_mutating_the_counter_structure_only_ever_raises_TelemetryError(seed):
    rnd = random.Random(seed)
    base = pcb(rnd.randint(1, 300), rnd.randint(0, 5))
    for _ in range(500):
        m = copy.deepcopy(base)
        a, b, c = rnd.choice(["before", "after"]), rnd.choice(["tcp", "raw"]), rnd.choice([-1, 0, 1, 10 ** 9, 2 ** 64, None, "7", 3.5, True, [], {}])
        r = rnd.random()
        if r < .5: m[a][b] = c
        elif r < .65: del m[a][b]
        elif r < .8: m[a]["udp"] = 5
        elif r < .9: m[rnd.choice(["x", "y"])] = {}
        else: m = c
        try:
            G.check_socket_plausibility(rows_of(sockets_text(tcp=5)), G.parse_pcbcounts(m))
        except G.TelemetryError:
            pass


def test_W1_after_the_completeness_layer_the_parser_mutation_sweeps_still_hold():
    from tests.test_genesis_v2_tier0s_n1_n10 import _SWEEPS, _SWEEP_CHARS
    parse, base, still = _SWEEPS["sockets"]
    silent = 0
    for i in range(len(base) + 1):
        for ch in _SWEEP_CHARS:
            m = base[:i] + ch + base[i + 1:]
            try:
                if m != base and not still(parse(m)):
                    silent += 1
            except G.TelemetryError:
                pass
    assert silent == 0


# ======================================================================================================================== W1: LIVE macOS reproduction (real lineages, independent ground truth)
PROBE = r'''
import importlib.util, json, re, subprocess, sys
s = importlib.util.spec_from_file_location("g", sys.argv[1]); G = importlib.util.module_from_spec(s); s.loader.exec_module(G)
truth = subprocess.run(["/usr/sbin/netstat", "-an"], capture_output=True, text=True).stdout.startswith("Active Internet")
h = G.collect_host(); r = G.evaluate("forge", host=h)
net = ("network_interfaces_disabled", "network_no_default_route", "network_no_external_sockets")
print(json.dumps({"full_view": truth, "telemetry_complete": r["telemetry_complete"]["status"], "net": {k: r[k]["status"] for k in net}}))
'''
QUIET = r'''
import importlib.util, json, re, subprocess, sys
s = importlib.util.spec_from_file_location("g", sys.argv[1]); G = importlib.util.module_from_spec(s); s.loader.exec_module(G)
truth = subprocess.run(["/usr/sbin/netstat", "-an"], capture_output=True, text=True).stdout.startswith("Active Internet")
h = G.collect_host(); cur = None; out = []
for l in h["ifconfig"].splitlines(keepends=True):
    if not l[0].isspace(): cur = l.split(":")[0]
    if cur and not cur.startswith("lo") and re.match(r"\s+(inet6? |status: active)", l):
        if l.strip().startswith("inet6 fe80"): out.append(l)
        elif "status: active" in l: out.append(l.replace("active", "inactive"))
        continue
    out.append(l)
h["ifconfig"] = "".join(out)
h["ifaddrs"] = [{**r, "v4": [a for a in r["v4"] if r["name"].startswith("lo")], "v6": [a for a in r["v6"] if r["name"].startswith("lo") or a.lower().startswith("fe80")]} for r in h["ifaddrs"]]
for k in ("routes4", "routes6"): h[k] = "".join(l for l in h[k].splitlines(keepends=True) if not l.startswith("default"))
if h["sockets"]: h["sockets"] = "".join(l for l in h["sockets"].splitlines(keepends=True) if not (l[:3] in ("tcp", "udp", "icm") and G._sock_row(l)[2]))
r = G.evaluate("forge", host=h)
print(json.dumps({"full_view": truth, "net": {k: r[k]["status"] for k in ("network_interfaces_disabled", "network_no_default_route", "network_no_external_sockets")}}))
'''
GATE_PATH = str(ROOT / "scripts" / "genesis_v2_tier0s_phase_gate.py")


def _lineages():
    sysp = "/usr/bin/python3"
    out = [("pytest interpreter", [sys.executable])]
    if os.path.exists(sysp):
        out += [("system python", [sysp]), ("pytest interpreter -> system python child", None), ("env -i system python", ["/usr/bin/env", "-i", sysp])]
    return out


def _run_lineage(name, argv, script):
    if name.endswith("system python child"):
        code = f"import subprocess,sys;print(subprocess.run(['/usr/bin/python3','-c',{script!r},{GATE_PATH!r}],capture_output=True,text=True).stdout.strip())"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=180)
    else:
        p = subprocess.run(argv + ["-c", script, GATE_PATH], capture_output=True, text=True, timeout=180)
    return json.loads(p.stdout.strip().splitlines()[-1])


@darwin
@pytest.mark.parametrize("name", ["pytest interpreter", "system python", "pytest interpreter -> system python child", "env -i system python"])
def test_W1_LIVE_the_gate_never_trusts_reduced_telemetry_in_any_real_lineage(name):
    lin = dict((n, a) for n, a in _lineages())
    if name not in lin:
        pytest.skip("system python not present")
    last = None
    for _ in range(3):                                                                                       # natural churn between independent reads can cost one attempt
        last = _run_lineage(name, lin[name], PROBE)
        if not last["full_view"] or last["telemetry_complete"] == "PASS":
            break
    if not last["full_view"]:                                                                                 # ground truth: the OS returned the REDUCED view
        assert last["telemetry_complete"] == "FAIL_CLOSED", last
        assert last["net"]["network_no_external_sockets"] == "FAIL_CLOSED", last
    else:
        assert last["telemetry_complete"] == "PASS", last                                                    # no false positive on the unfiltered view


@darwin
@pytest.mark.parametrize("name", ["pytest interpreter", "system python", "pytest interpreter -> system python child", "env -i system python"])
def test_W1_LIVE_a_quiet_looking_network_inside_the_real_view_never_yields_a_network_PASS(name):
    """Real telemetry from the real lineage with every violation surgically removed: it must never PASS, whether the view is reduced (unproven) or full (the
    removal contradicts the independent counters)."""
    lin = dict((n, a) for n, a in _lineages())
    if name not in lin:
        pytest.skip("system python not present")
    res = _run_lineage(name, lin[name], QUIET)
    assert "PASS" not in res["net"].values(), res


@darwin
def test_W1_LIVE_the_project_interpreter_lineage_is_reduced_or_the_gate_still_agrees_with_the_truth():
    r = _run_lineage("pytest interpreter", [sys.executable], PROBE)
    assert (not r["full_view"]) == (r["telemetry_complete"] == "FAIL_CLOSED"), r


# ======================================================================================================================== W2: documentation
CLAIM = re.compile(r"(?i)\b(proves?|proven|complete(ly)?|exhaustive(ly)?|full table|all (?:the )?(?:sockets|routes|interfaces|rows)|every (?:socket|row|route))\b")
TELEMETRY_WORDS = re.compile(r"(?i)\b(table|output|telemetry|sockets?|routes?|interfaces?|rows?|view|listing)\b")
QUALIFIERS = ("non-exhaustive", "not ", "no ", "never", "cannot", "unproven", "does not", "do not", "n't", "without", "only if", "unless", "incomplete", "separately", "bounded", "structurally",
              "reduced", "could not", "is not", "are not", "NOT", "superseded", "wrong", "withdrawn", "claimed", "instead", "rather than", "instead of", "must not", "refused")


def _sentences(text):
    return re.split(r"(?<=[.;!?])\s+|\n\s*\n|\n(?=\s*[-*|#])", text)


def _scan(text):
    bad = []
    for s in _sentences(text):
        if CLAIM.search(s) and TELEMETRY_WORDS.search(s) and not any(q in s for q in QUALIFIERS):
            bad.append(" ".join(s.split())[:200])
    return bad


def test_W2_no_gate_statement_claims_that_parsing_proves_completeness():
    src = Path(G.__file__).read_text()
    bad = _scan(src)
    assert bad == [], bad


def test_W2_no_infrastructure_document_claims_that_parsing_proves_completeness():
    bad = {}
    for p in sorted(INFRA.glob("GENESIS_V2_TIER0S_*.md")):
        b = _scan(p.read_text())
        if b:
            bad[p.name] = b
    assert bad == {}, bad


def test_W2_parse_sockets_states_structural_validity_only():
    d = " ".join(G.parse_sockets.__doc__.split())
    assert "STRUCTURALLY WELL-FORMED AND PROPERLY TERMINATED" in d and "does NOT establish that every socket is listed" in d
    assert "This proves the output was a complete" not in d and "complete, well-formed table" not in d


def test_W2_the_gate_docstring_separates_structure_from_completeness():
    d = " ".join(G.__doc__.split())
    for must in ("TWO SEPARATE QUESTIONS", "STRUCTURAL VALIDITY", "COMPLETENESS", "STRUCTURALLY_VALID_BUT_COMPLETENESS_UNPROVEN", "TELEMETRY_COMPLETENESS_UNPROVEN",
                 "does NOT prove that well-formed telemetry is complete or true", "REDUCED VIEW", "RUN THE GATE FROM AN UNFILTERED LINEAGE", "NO independent route source exists",
                 "completeness is NEVER claimed"):
        assert must in d or must.replace("completeness is NEVER", "completeness is never") in d, must


def test_W2_the_withdrawn_wording_is_gone_everywhere():
    for p in [Path(G.__file__), *INFRA.glob("GENESIS_V2_TIER0S_*.md")]:
        t = " ".join(p.read_text().split())
        for gone in ("This proves the output was a complete, well-formed table", "on some Python builds `netstat -an` run from a child process omits the Internet section, in which case"):
            assert gone not in t, (p.name, gone)


def test_W2_the_W1_W2_document_has_the_independence_table_and_keeps_the_boundaries():
    doc = (INFRA / "GENESIS_V2_TIER0S_W1_W2_REMEDIATION.md").read_text()
    for must in ("| Source | Security fact | Mechanism | Independent from | Known filtering |", "W1", "W2", "W3", "W5", "W6", "NOT_AUTHORIZED", "READY_FOR_ACCEPTANCE_REAUDIT",
                 "STRUCTURALLY_VALID_BUT_COMPLETENESS_UNPROVEN", "TELEMETRY_COMPLETENESS_UNPROVEN"):
        assert must in doc, must
    assert "TIER0_S_FULLY_ACCEPTED" not in doc and "SOFTWARE_GATE_ACCEPTED" not in doc


# ======================================================================================================================== W3: tracebacks
def _gate_main(monkeypatch, tmp_path, cmd, extra=()):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(G, "collect_host", lambda: good_host(tmp_path))
    argv = ["gate", cmd, "--role", "forge", "--state-dir", str(cfg["state_dir"]), "--role-state-dir", str(cfg["role_state_dir"]), "--code-root", str(cfg["code_root"]),
            "--code-manifest", str(cfg["code_manifest"]), "--code-manifest-sha256", cfg["code_manifest_sha256"], "--deny-path", str(cfg["deny_paths"][0]), *extra]
    return G.main(argv), cfg


def test_W3_init_on_an_existing_directory_is_a_structured_refusal_not_a_traceback(tmp_path, capsys):
    d = tmp_path / "state"; G.init_state(d)
    rc = G.main(["gate", "init", "--state-dir", str(d)])
    cap = capsys.readouterr()
    assert rc == 1 and "FAIL_CLOSED" in cap.out and "refusing to re-initialize" in cap.out and cap.err == "" and "Traceback" not in cap.out + cap.err


@nonroot
def test_W3_init_where_the_parent_is_unwritable_is_a_structured_refusal(tmp_path, capsys):
    ro = tmp_path / "ro"; ro.mkdir(); os.chmod(ro, 0o500)
    try:
        rc = G.main(["gate", "init", "--state-dir", str(ro / "state")])
    finally:
        os.chmod(ro, 0o700)
    cap = capsys.readouterr()
    assert rc == 1 and "FAIL_CLOSED" in cap.out and "PermissionError" in cap.out and "Traceback" not in cap.out + cap.err


def test_W3_a_failed_begin_append_is_structured_records_nothing_and_is_not_GATE_PASSES(tmp_path, monkeypatch, capsys):
    cfg = make_cfg(tmp_path)
    holder = G._lock_dir(cfg["state_dir"], exclusive=True)
    monkeypatch.setattr(G, "LOCK_TIMEOUT", 0.2)
    try:
        monkeypatch.setattr(G, "verify_state", lambda sd, **k: ([], []))                                    # reach the append with a verifiable state, then fail on the lock
        monkeypatch.setattr(G, "collect_host", lambda: good_host(tmp_path))
        rc = G.main(["gate", "begin", "--role", "forge", "--state-dir", str(cfg["state_dir"]), "--role-state-dir", str(cfg["role_state_dir"]), "--code-root", str(cfg["code_root"]),
                     "--code-manifest", str(cfg["code_manifest"]), "--code-manifest-sha256", cfg["code_manifest_sha256"], "--deny-path", str(cfg["deny_paths"][0])])
    finally:
        os.close(holder)
    cap = capsys.readouterr()
    assert rc == 1 and "the phase start was NOT recorded" in cap.out and "GATE_FAILS" in cap.out and "GATE_PASSES" not in cap.out and "Traceback" not in cap.out + cap.err
    assert (cfg["state_dir"] / "receipts.jsonl").read_text() == ""


def test_W3_unexpected_programmer_errors_are_not_swallowed_and_not_downgraded(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(G, "collect_host", lambda: good_host(tmp_path))
    monkeypatch.setattr(G, "evaluate", lambda *a, **k: (_ for _ in ()).throw(AttributeError("defect SENTINEL")))
    rc = G.main(["gate", "check", "--role", "forge"])
    cap = capsys.readouterr()
    assert rc == 3 and "AttributeError" in cap.err and "Traceback" in cap.err and "GATE_PASSES" not in cap.out


def test_W3_an_unexpected_error_inside_begin_itself_still_propagates(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(G, "begin", lambda *a, **k: (_ for _ in ()).throw(KeyError("defect")))
    monkeypatch.setattr(G, "collect_host", lambda: good_host(tmp_path))
    with pytest.raises(KeyError):
        G.main(["gate", "begin", "--role", "forge", "--state-dir", str(cfg["state_dir"]), "--role-state-dir", str(cfg["role_state_dir"]), "--code-root", str(cfg["code_root"]),
                "--code-manifest", str(cfg["code_manifest"]), "--code-manifest-sha256", cfg["code_manifest_sha256"], "--deny-path", str(cfg["deny_paths"][0])])


# ======================================================================================================================== W5: storage check wording
def test_W5_the_check_is_renamed_and_the_old_name_is_gone(tmp_path):
    res = run("forge", tmp_path)
    assert "configured_other_role_storage_not_detected" in res and "other_role_storage_unavailable" not in res
    for p in [Path(G.__file__), *INFRA.glob("GENESIS_V2_TIER0S_*.md")]:
        if "AUDIT_REMEDIATION" in p.name or "FAILOPEN" in p.name or "N1_N10" in p.name or "W1_W2" in p.name:
            continue                                                                                          # historical traceability documents may cite the old name
        assert "other_role_storage_unavailable" not in p.read_text(), p.name


def test_W5_pass_text_claims_only_that_configured_identifiers_were_not_observed(tmp_path):
    r = run("forge", tmp_path)["configured_other_role_storage_not_detected"]
    assert r["status"] == G.PASS and r["advisory"] is True
    d = r["detail"]
    for must in ("ADVISORY", "configured", "were not observed", "NOT evidence", "physically absent", "Physical detachment remains an owner procedure"):
        assert must in d, must
    assert "unavailable" not in d.lower() and "disconnected" not in d.lower()


def test_W5_fail_text_still_says_detachment_is_procedural_and_label_only_is_weaker(tmp_path):
    cfg = make_cfg(tmp_path); (tmp_path / "other_role_store").mkdir()
    r = run("forge", tmp_path, cfg=cfg)["configured_other_role_storage_not_detected"]
    assert r["status"] == G.FAIL and "Physical detachment remains an owner procedure" in r["detail"] and r["advisory"] is True
    r2 = run("forge", tmp_path, deny_paths=[], deny_volumes=["WitnessVault"])["configured_other_role_storage_not_detected"]
    assert "LABEL_ONLY" in r2["detail"]


def test_W5_an_attached_renamed_drive_still_passes_but_the_text_does_not_claim_absence(tmp_path):
    disks = list(GOOD_DISKS) + [{"name": "Backup-Data", "uuid": "ABCD0000-1111-2222-3333-444455556666", "dev": "disk9s1", "mount": ""}]
    r = run("forge", tmp_path, host=good_host(tmp_path, disks=disks), deny_paths=[], deny_volumes=["WitnessVault"])["configured_other_role_storage_not_detected"]
    assert r["status"] == G.PASS and "NOT evidence" in r["detail"]


def test_W5_the_advisory_flag_does_not_change_gate_semantics(tmp_path):
    res = run("forge", tmp_path)
    res["configured_other_role_storage_not_detected"]["status"] = G.FAIL
    assert not G.gate_passes(res)


# ======================================================================================================================== W6: structured cryptographic input errors
def _kd(bundle_):
    return bundle_[0], bundle_[2], bundle_[3]


def _mod():
    import importlib.util as u
    s = u.spec_from_file_location("tier0a_bundle_w6", ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py"); m = u.module_from_spec(s); s.loader.exec_module(m)
    return m


B = _mod()


@pytest.mark.parametrize("key", [None, "x" * 32, b"", b"\x01" * 31, b"\x01" * 33, 5, [1] * 32, object(), 3.5, b"\x01" * 64])
def test_W6_malformed_keys_return_a_typed_INVALID_INPUT_problem(bundle, key):
    b, _priv, digest = _kd(bundle)
    out = B.cryptographic_verify(b, key, digest)
    assert len(out) == 1 and out[0].startswith(B.INVALID_INPUT) and B.classify(out) == "INVALID_INPUT"
    assert "key" in out[0]


@pytest.mark.parametrize("digest", [None, "", "zz", "0" * 63, "0" * 65, "A" * 64, ("0" * 63) + "g", " " + "0" * 64, "0" * 64 + "\n", 5, b"0" * 64, "0x" + "0" * 62])
def test_W6_malformed_digests_return_a_typed_INVALID_INPUT_problem(bundle, digest):
    b, priv, _d = _kd(bundle)
    out = B.cryptographic_verify(b, priv, digest)
    assert len(out) == 1 and out[0].startswith(B.INVALID_INPUT) and "digest" in out[0]


def test_W6_a_bytearray_key_of_the_right_length_is_accepted(bundle):
    b, priv, digest = _kd(bundle)
    assert B.cryptographic_verify(b, bytearray(priv), digest) == []


def test_W6_wrong_key_and_wrong_digest_are_typed_VERIFICATION_FAILED_and_never_raise(bundle):
    b, priv, digest = _kd(bundle)
    from orca.eval.genesis_v2 import store as S
    wrong, _ = S.generate_vault_keypair()
    for out in (B.cryptographic_verify(b, wrong, digest), B.cryptographic_verify(b, priv, "0" * 64)):
        assert out and all(B.VERIFICATION_FAILED in p for p in out) and B.classify(out) == "VERIFICATION_FAILED"
        assert not any(isinstance(p, BaseException) for p in out)


def test_W6_a_malformed_encrypted_artifact_is_a_typed_problem_without_exceptions(bundle):
    b, priv, digest = _kd(bundle)
    f = next((b / next(p.name for p in b.iterdir() if p.is_dir())).iterdir())
    f.write_bytes(b"not an encrypted artifact"); (b / B.MANIFEST).unlink()
    out = B.cryptographic_verify(b, priv, digest)
    assert out and all(isinstance(p, str) for p in out)


def test_W6_tampered_ciphertext_is_VERIFICATION_FAILED(bundle):
    b, priv, digest = _kd(bundle)
    f = sorted((b / next(p.name for p in b.iterdir() if p.is_dir())).iterdir())[0]
    raw = bytearray(f.read_bytes()); raw[-1] ^= 1; f.write_bytes(bytes(raw)); (b / B.MANIFEST).unlink(); B.seal(b)
    out = B.cryptographic_verify(b, priv, digest)
    assert out and B.VERIFICATION_FAILED in out[0]


def test_W6_missing_cryptography_is_a_typed_UNAVAILABLE_problem(bundle, monkeypatch):
    b, priv, digest = _kd(bundle)
    from orca.eval.genesis_v2 import store as S
    monkeypatch.setattr(S, "EncryptedVaultReader", lambda *a, **k: (_ for _ in ()).throw(S.PrivateStorageNotConfigured("no cryptography")))
    out = B.cryptographic_verify(b, priv, digest)
    assert out[0].startswith(B.UNAVAILABLE) and B.classify(out) == "UNAVAILABLE"


def test_W6_a_store_rejection_of_the_location_is_a_typed_INVALID_INPUT_problem(bundle, monkeypatch):
    b, priv, digest = _kd(bundle)
    from orca.eval.genesis_v2 import store as S
    monkeypatch.setattr(S, "EncryptedVaultReader", lambda *a, **k: (_ for _ in ()).throw(S.PrivateStorageViolation("inside the repository")))
    assert B.cryptographic_verify(b, priv, digest)[0].startswith(B.INVALID_INPUT)


@pytest.mark.parametrize("exc", [RuntimeError("defect"), TypeError("defect"), AttributeError("defect"), KeyError("defect"), ZeroDivisionError()])
def test_W6_genuine_implementation_defects_propagate_and_are_not_turned_into_verification_results(bundle, monkeypatch, exc):
    b, priv, digest = _kd(bundle)
    from orca.eval.genesis_v2 import store as S
    monkeypatch.setattr(S.EncryptedVaultReader, "read_split", lambda self, *a, **k: (_ for _ in ()).throw(exc))
    with pytest.raises(type(exc)):
        B.cryptographic_verify(b, priv, digest)


def _git_blob_id(path):
    import hashlib
    data = Path(path).read_bytes()
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def test_W6_the_crypto_implementation_is_untouched():
    """The AES-256-GCM / HKDF / X25519 implementation audited in the previous phases is unchanged: git blob ids (computed here, no git needed) are pinned."""
    assert _git_blob_id(ROOT / "orca/eval/genesis_v2/store.py") == "308a2cb9e73e8a7820174c7b0f5557cc9bef74e1"
    assert _git_blob_id(ROOT / "orca/eval/genesis_v2/spec.py") == "babfc10c042305c996224306d485d9559aa0c01a"


def test_W6_the_module_docstring_states_which_failures_are_typed_and_which_propagate():
    d = " ".join(B.cryptographic_verify.__doc__.split())
    for must in ("INVALID_INPUT", "UNAVAILABLE", "VERIFICATION_FAILED", "PROGRAMMING ERROR and propagates unchanged"):
        assert must in d, must


# ======================================================================================================================== traceability
def test_W2_the_W1_W2_matrix_maps_every_finding_to_regression_tests_that_exist():
    txt = (INFRA / "GENESIS_V2_TIER0S_W1_W2_REMEDIATION.md").read_text()
    sources = (ROOT / "tests" / "test_genesis_v2_tier0s_w1_w2.py").read_text()
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (W\d+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`(test_[^`]+)`", line)
        seen[m.group(1)] = names
        assert names, f"{m.group(1)} has no regression tests"
        for t in names:
            assert re.search(rf"def {re.escape(t)}\b", sources), f"{m.group(1)}: {t} does not exist"
    assert set(seen) == {"W1", "W2", "W3", "W5", "W6"}


def test_W2_the_claim_scanner_catches_the_withdrawn_wording_and_accepts_the_qualified_wording():
    assert _scan("This proves the output was a complete, well-formed table.")
    assert _scan("The parser proves that every socket is listed in the table.")
    assert _scan("The route output is exhaustive.")
    assert not _scan("They do NOT prove that no row was removed from within a well-formed table.")
    assert not _scan("Completeness is unproven for the route table and is never claimed.")


@pytest.mark.parametrize("seed", range(4))
def test_W1_evaluate_never_raises_for_arbitrary_values_in_the_new_sources(tmp_path, seed):
    rnd = random.Random(seed)
    atoms = [None, True, 0, -1, 5, 2 ** 70, 1.5, "", "x", "lo0", [], {}, [None], [""], ["lo0", "lo0"], {"before": {}, "after": {}}, [{"name": "lo0"}], b"b", object()]
    for _ in range(300):
        key = rnd.choice(["ifaddrs", "ifindex", "pcbcounts", "ifnames", "ifconfig", "sockets", "routes4", "routes6"])
        h = good_host(tmp_path, **{key: rnd.choice(atoms)})
        res = G.evaluate("forge", host=h)
        assert not G.gate_passes(res) or key in ()                                                       # a corrupted mandatory source can never produce a gate pass

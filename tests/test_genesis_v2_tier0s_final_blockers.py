"""Tier0-S final acceptance-blocker remediation -- regression tests.

BLOCKER A  documentation must match the measured completeness (no "most/majority of rows", no "independently cross-checked" for the single-sourced `status:`)
BLOCKER B  the interface link state is cross-checked against an independent in-process kernel source (SIOCGIFMEDIA); an UP, addressed interface whose link state
           cannot be established is FAIL_CLOSED; the acceptance audit's false-PASS construction can no longer PASS
PCB band   the unsupported 2x upper allowance is gone; the blind spot is characterized by property tests so the documentation cannot drift from the function
W6         a cryptographically VALID but malformed SEAL plaintext maps to a typed integrity failure; genuine defects still propagate
DIAG       a parser/collector DEFECT is distinguishable from a host condition (class name only, never the message) and still fails closed

Portable tests use synthetic telemetry. `live_macos` tests run the REAL gate and kernel and skip off macOS."""
import errno
import itertools
import json
import os
import random
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_genesis_v2_tier0a_transfer_bundle import bundle  # noqa: F401  (pytest fixture: synthetic sealed bundle, ephemeral key)
from tests.test_genesis_v2_tier0s_phase_gate import GOOD_IFCONFIG, GOOD_ROUTES, GOOD_ROUTES6, INFRA, ROOT, SOCK_TAIL, G, good_host, run, st
from tests.test_genesis_v2_tier0s_w1_w2 import SOCK_HEAD, _scan, pcb, rows_of, sockets_text

CODE = G.COMPLETENESS
darwin = pytest.mark.skipif(sys.platform != "darwin", reason="macOS host integration")

# ================================================================================================================= BLOCKER B: link-state truth table
LO_BLOCK = ("lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n\tinet6 ::1 prefixlen 128\n\tinet6 fe80::1%lo0 prefixlen 64\n")
ADDR_CLASSES = {                       # name -> (ifconfig lines, libc v4, libc v6, is_address_violation, is_addressed)
    "none": ("", [], [], False, False),
    "ll6": ("\tinet6 fe80::a1b2%en0 prefixlen 64 scopeid 0x4\n", [], ["fe80::a1b2"], False, True),
    "ll4": ("\tinet 169.254.7.7 netmask 0xffff0000\n", ["169.254.7.7"], [], True, True),
    "priv4": ("\tinet 192.0.2.50 netmask 0xffffff00\n", ["192.0.2.50"], [], True, True),
    "glob6": ("\tinet6 2001:db8::5 prefixlen 64\n", [], ["2001:db8::5"], True, True),
}
STATES = ("active", "inactive", "no_media", "status_invalid", "vanished")


def en_block(addr, status, up):
    flags = "UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST" if up else "BROADCAST,SMART,SIMPLEX,MULTICAST"
    t = f"en0: flags={'8863' if up else '8862'}<{flags}> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n" + ADDR_CLASSES[addr][0] + "\tmedia: autoselect\n"
    return t + (f"\tstatus: {status}\n" if status else "")


def link_host(tmp, addr, status, up, state):
    _lines, v4, v6, _viol, addressed = ADDR_CLASSES[addr]
    r4 = GOOD_ROUTES + ("169.254 link#4 UCS en0\n192.0.2/24 link#4 UCS en0\n" if v4 else "")
    r6 = GOOD_ROUTES6 + ("fe80::%en0/64 link#4 UCI en0\n2001:db8::/64 link#4 UCI en0\n" if v6 else "")
    return good_host(tmp, ifconfig=LO_BLOCK + en_block(addr, status, up), routes4=r4, routes6=r6,
                    ifaddrs=[{"name": "lo0", "flags": 0x8049, "v4": ["127.0.0.1"], "v6": ["::1", "fe80::1"]}, {"name": "en0", "flags": 0x8863 if up else 0x8862, "v4": v4, "v6": v6}],
                    linkstate={"lo0": "no_media", "en0": state})


def oracle_passes(addr, status, up, state):
    """What the interface check SHOULD say, written from the POLICY (not from the implementation): PASS iff no address violation, no active link seen by either source,
    the two sources agree, the interface did not vanish, and the link state of an UP addressed interface is not unestablished."""
    _l, _v4, _v6, violation, addressed = ADDR_CLASSES[addr]
    agree = (state == "active" and status == "active") or (state == "inactive" and status == "inactive") or (state in ("no_media", "status_invalid") and status is None)
    unknown = state == "status_invalid" and up and addressed
    return (not violation) and status != "active" and state not in ("active", "vanished") and agree and not unknown


@pytest.mark.parametrize("addr", sorted(ADDR_CLASSES))
def test_FB_the_interface_verdict_equals_the_policy_oracle_for_every_combination(tmp_path, addr):
    """750 combinations in total (5 address classes x 3 ifconfig statuses x UP/DOWN x 5 independent states). PASS exactly when the policy says so: no false PASS
    AND no false failure."""
    wrong = []
    for status, up, state in itertools.product((None, "active", "inactive"), (True, False), STATES):
        got = st(run("forge", tmp_path, host=link_host(tmp_path, addr, status, up, state)), "network_interfaces_disabled")
        want = oracle_passes(addr, status, up, state)
        if (got == G.PASS) != want:
            wrong.append((addr, status, up, state, got))
        assert got in (G.PASS, G.FAIL, G.FAIL_CLOSED)
    assert wrong == [], wrong[:5]


def test_FB_THE_ACCEPTANCE_AUDIT_CASE_UP_link_local_only_status_line_dropped_never_passes(tmp_path):
    """The exact false PASS constructed by the acceptance audit: an UP, link-local-only interface, the `status: active` line absent from ifconfig, libc inventories
    agreeing, independent link state ACTIVE."""
    h = link_host(tmp_path, "ll6", None, True, "active")
    res = run("forge", tmp_path, host=h)
    assert st(res, "network_interfaces_disabled") == G.FAIL and st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)
    control = run("forge", tmp_path, host=link_host(tmp_path, "ll6", "active", True, "active"))
    assert st(control, "network_interfaces_disabled") == G.FAIL                                  # with the line present it already failed: dropping it must not help


def test_FB_the_old_gate_logic_would_have_passed_that_case_proving_the_test_is_meaningful(tmp_path):
    """Control: with the independent source removed from consideration the status line is the only evidence, and dropping it leaves nothing -- this is the gap."""
    h = link_host(tmp_path, "ll6", None, True, "active")
    ifs = G.parse_interfaces(h["ifconfig"])
    assert G.interface_violations(ifs) == []                                                     # the ifconfig-only view sees NO violation: the status line was the only evidence


def test_FB_independent_active_link_is_a_violation_even_when_ifconfig_says_inactive(tmp_path):
    res = run("forge", tmp_path, host=link_host(tmp_path, "none", "inactive", True, "active"))
    assert st(res, "network_interfaces_disabled") == G.FAIL and CODE in res["telemetry_complete"]["detail"]


def test_FB_unknown_link_state_on_an_UP_addressed_interface_is_FAIL_CLOSED_with_a_distinct_reason(tmp_path):
    res = run("forge", tmp_path, host=link_host(tmp_path, "ll6", None, True, "status_invalid"))
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and "LINK_STATE_UNESTABLISHED" in res["network_interfaces_disabled"]["detail"]
    assert st(res, "telemetry_complete") == G.PASS                                              # the sources agree: this is a POLICY outcome, not a telemetry failure
    assert not G.gate_passes(res)
    # but an interface that is DOWN, or that has no address, has nothing to establish
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "ll6", None, False, "status_invalid")), "network_interfaces_disabled") == G.PASS
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "none", None, True, "status_invalid")), "network_interfaces_disabled") == G.PASS


def test_FB_no_media_interfaces_are_decided_by_address_the_explicit_policy(tmp_path):
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "ll6", None, True, "no_media")), "network_interfaces_disabled") == G.PASS                 # tunnel-like, link-local only
    for addr in ("ll4", "priv4", "glob6"):
        assert st(run("forge", tmp_path, host=link_host(tmp_path, addr, None, True, "no_media")), "network_interfaces_disabled") == G.FAIL
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "ll6", "inactive", True, "no_media")), "network_interfaces_disabled") == G.FAIL_CLOSED     # ifconfig prints a status the kernel denies


@pytest.mark.parametrize("reason", ["UNAVAILABLE", "PERMISSION_DENIED", "UNSUPPORTED", "MALFORMED"])
def test_FB_an_unavailable_independent_link_state_source_is_FAIL_CLOSED(tmp_path, reason):
    h = link_host(tmp_path, "none", "inactive", True, "inactive"); h["linkstate"] = None; h["telemetry"] = {"linkstate": reason}
    res = run("forge", tmp_path, host=h)
    assert f"linkstate={reason}" in res["telemetry_complete"]["detail"] and st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_FB_a_missing_linkstate_field_is_not_a_pass(tmp_path):
    h = link_host(tmp_path, "none", "inactive", True, "inactive"); del h["linkstate"]
    res = run("forge", tmp_path, host=h)
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and st(res, "telemetry_complete") == G.FAIL_CLOSED


@pytest.mark.parametrize("bad", [None, "active", 5, [], {}, {"lo0": "no_media"}, {"lo0": "no_media", "en0": "ACTIVE"}, {"lo0": "no_media", "en0": None}, {"lo0": "no_media", "en0": 1},
                                 {"lo0": "no_media", "en0": "active", "en9": "active"}, {"lo0": "no_media", "en 0": "active"}, {"": "active"}, {"lo0": "no_media", "en0": ["active"]}])
def test_FB_malformed_or_inconsistent_link_state_structures_are_FAIL_CLOSED_and_never_crash(tmp_path, bad):
    res = run("forge", tmp_path, host=link_host(tmp_path, "none", "inactive", True, "inactive") | {"linkstate": bad})
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_FB_an_interface_that_disappears_or_appears_between_queries_is_unproven(tmp_path):
    h = link_host(tmp_path, "none", "inactive", True, "inactive"); h["linkstate"]["en9"] = "inactive"
    assert st(run("forge", tmp_path, host=h), "network_interfaces_disabled") == G.FAIL_CLOSED
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "none", "inactive", True, "vanished")), "network_interfaces_disabled") == G.FAIL_CLOSED


def test_FB_the_mismatch_is_also_a_reduced_view_signal_for_the_other_network_sources(tmp_path):
    res = run("forge", tmp_path, host=link_host(tmp_path, "none", None, True, "active"))
    detail = res["telemetry_complete"]["detail"]
    assert all(f"{k}={CODE}" in detail for k in ("ifconfig", "routes4", "routes6", "sockets"))


def test_FB_quiet_hosts_still_pass_so_the_check_is_not_trivially_closed(tmp_path):
    assert G.gate_passes(run("forge", tmp_path))                                                 # default synthetic host: lo0 + inactive en0 (status: inactive)
    assert st(run("forge", tmp_path, host=link_host(tmp_path, "none", "inactive", True, "inactive")), "network_interfaces_disabled") == G.PASS


@pytest.mark.parametrize("seed", range(4))
def test_FB_random_single_field_corruption_of_the_independent_link_map_is_never_a_PASS_unless_equivalent(tmp_path, seed):
    rnd = random.Random(seed)
    base = link_host(tmp_path, "ll6", "inactive", True, "inactive")
    assert st(run("forge", tmp_path, host=base), "network_interfaces_disabled") == G.PASS
    for _ in range(300):
        h = json.loads(json.dumps(base, default=str)); h["home"] = base["home"]; h["env"] = {}; h["runtime_sockets_abs"] = ()
        key = rnd.choice(["lo0", "en0"])
        pool = ["active", "inactive", "no_media", "status_invalid", "vanished", None, "x", 5, [], True]
        h["linkstate"][key] = rnd.choice(pool)
        if h["linkstate"] == base["linkstate"]:
            continue
        if key == "lo0" and h["linkstate"]["lo0"] in G.LINK_STATES:
            continue                                                                             # loopback link state is deliberately not evaluated (it carries no external traffic)
        assert st(run("forge", tmp_path, host=h), "network_interfaces_disabled") != G.PASS, h["linkstate"]


# --------------------------------------------------------------------------------------------- read_linkstate: failure-mode mapping (portable via patching)
@pytest.fixture
def as_darwin(monkeypatch):
    monkeypatch.setattr(G.sys, "platform", "darwin")


def _fake_ioctl(monkeypatch, status=None, err=None):
    import struct

    def fake(fd, cmd, buf, mutate=True):
        if err is not None:
            raise OSError(err, "x")
        struct.pack_into("<i", buf, 24, status)
        return 0
    monkeypatch.setattr(G.fcntl, "ioctl", fake)


@pytest.mark.parametrize("status,want", [(0x3, "active"), (0x1, "inactive"), (0x0, "status_invalid"), (0x2, "status_invalid"), (0x7, "active"), (0x80000001, "inactive")])
def test_FB_read_linkstate_decodes_the_media_status_bits(as_darwin, monkeypatch, status, want):
    import ctypes
    _fake_ioctl(monkeypatch, status=ctypes.c_int32(status).value)
    assert G.read_linkstate(["en0"]) == {"en0": want}


@pytest.mark.parametrize("err,want", [(errno.EOPNOTSUPP, "no_media"), (errno.ENXIO, "vanished"), (errno.ENODEV, "vanished")])
def test_FB_read_linkstate_maps_the_expected_errnos(as_darwin, monkeypatch, err, want):
    _fake_ioctl(monkeypatch, err=err)
    assert G.read_linkstate(["en0"]) == {"en0": want}


@pytest.mark.parametrize("err,reason", [(errno.EPERM, "PERMISSION_DENIED"), (errno.EACCES, "PERMISSION_DENIED"), (errno.EIO, "UNAVAILABLE"), (errno.ENOTTY, "UNAVAILABLE"),
                                        (errno.EINVAL, "UNAVAILABLE"), (errno.ENOMEM, "UNAVAILABLE")])
def test_FB_read_linkstate_never_guesses_for_unexpected_errors(as_darwin, monkeypatch, err, reason):
    _fake_ioctl(monkeypatch, err=err)
    with pytest.raises(G.TelemetryError) as e:
        G.read_linkstate(["en0"])
    assert e.value.reason == reason


@pytest.mark.parametrize("name", ["", "x" * 16, "é0", None, 5, "a\0b", b"en0", ["en0"]])
def test_FB_read_linkstate_rejects_unsuitable_names_cleanly(as_darwin, monkeypatch, name):
    _fake_ioctl(monkeypatch, status=3)
    with pytest.raises(G.TelemetryError) as e:
        G.read_linkstate([name])
    assert e.value.reason == "MALFORMED"


def test_FB_read_linkstate_socket_failure_is_reported_not_raised_raw(as_darwin, monkeypatch):
    def deny(*a, **k):
        raise PermissionError(errno.EPERM, "denied")
    monkeypatch.setattr(G.socket, "socket", deny)
    with pytest.raises(G.TelemetryError) as e:
        G.read_linkstate(["lo0"])
    assert e.value.reason == "PERMISSION_DENIED"
    monkeypatch.setattr(G.socket, "socket", lambda *a, **k: (_ for _ in ()).throw(OSError(errno.EMFILE, "x")))
    with pytest.raises(G.TelemetryError) as e:
        G.read_linkstate(["lo0"])
    assert e.value.reason == "UNAVAILABLE"


def test_FB_read_linkstate_is_macOS_only():
    if sys.platform != "darwin":
        with pytest.raises(G.TelemetryError) as e:
            G.read_linkstate(["lo0"])
        assert e.value.reason == "UNSUPPORTED"


def test_FB_the_ioctl_request_matches_the_measured_macOS_value():
    assert G.SIOCGIFMEDIA == 0xC0286938 and G._iowr("i", 56, 40) == G.SIOCGIFMEDIA and (G.IFM_AVALID, G.IFM_ACTIVE) == (1, 2)


def test_FB_collect_host_queries_link_state_for_every_known_interface_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(G, "_run", lambda cmd: ("UNAVAILABLE", None))
    monkeypatch.setattr(G, "read_ifaddrs", lambda: [{"name": "lo0", "flags": 9, "v4": [], "v6": []}, {"name": "en0", "flags": 1, "v4": [], "v6": []}])
    monkeypatch.setattr(G.socket, "if_nameindex", lambda: [(1, "lo0"), (2, "en0"), (3, "utun0")])
    monkeypatch.setattr(G, "read_linkstate", lambda names: seen.setdefault("names", names) and {n: "inactive" for n in names})
    h = G.collect_host()
    assert seen["names"] == ["en0", "lo0", "utun0"] and h["telemetry"]["linkstate"] == "OK"


def test_FB_collect_host_with_no_interface_names_cannot_establish_link_state(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("UNAVAILABLE", None))
    monkeypatch.setattr(G, "read_ifaddrs", lambda: (_ for _ in ()).throw(G.TelemetryError("UNAVAILABLE", "x")))
    monkeypatch.setattr(G.socket, "if_nameindex", lambda: [])
    h = G.collect_host()
    assert h["linkstate"] is None and h["telemetry"]["linkstate"] == "UNAVAILABLE"


# ================================================================================================================= live macOS (real kernel, real tools)
LIVE = r'''
import importlib.util, json, subprocess, sys
s = importlib.util.spec_from_file_location("g", sys.argv[1]); G = importlib.util.module_from_spec(s); s.loader.exec_module(G)
h = G.collect_host()
full = subprocess.run(["/usr/sbin/netstat", "-an"], capture_output=True, text=True).stdout.startswith("Active Internet")
r = G.evaluate("forge", host=h)
ifs = G.parse_interfaces(h["ifconfig"]); rep = G.link_state_report(ifs, G.parse_ifaddrs(h["ifaddrs"]), h["linkstate"])
print(json.dumps({"full_view": full, "linkstate": h["linkstate"], "telemetry": r["telemetry_complete"]["status"], "iface": r["network_interfaces_disabled"]["status"], "mismatch": rep["mismatch"]}))
'''
GATE_PATH = str(ROOT / "scripts" / "genesis_v2_tier0s_phase_gate.py")


def _live(argv_prefix, via_child=False):
    if via_child:
        code = f"import subprocess,sys;print(subprocess.run(['/usr/bin/python3','-c',{LIVE!r},{GATE_PATH!r}],capture_output=True,text=True).stdout.strip())"
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=240)
    else:
        p = subprocess.run(argv_prefix + ["-c", LIVE, GATE_PATH], capture_output=True, text=True, timeout=240)
    return json.loads(p.stdout.strip().splitlines()[-1])


@darwin
def test_FB_LIVE_the_in_process_kernel_link_state_agrees_with_ifconfig_for_every_interface():
    last = None
    for _ in range(3):                                                                           # an interface can flap between the two reads
        last = _live([sys.executable])
        if last["mismatch"] == 0:
            break
    assert last["mismatch"] == 0 and set(last["linkstate"].values()) <= set(G.LINK_STATES), last


@darwin
def test_FB_LIVE_the_link_state_is_the_same_in_the_filtered_and_unfiltered_lineage():
    if not os.path.exists("/usr/bin/python3"):
        pytest.skip("system python not present")
    a = b = None
    for _ in range(3):
        a, b = _live([sys.executable]), _live(["/usr/bin/python3"])
        if a["linkstate"] == b["linkstate"]:
            break
    assert a["linkstate"] == b["linkstate"], (a["linkstate"], b["linkstate"])                  # the OS reduction does not touch this source


@darwin
@pytest.mark.parametrize("name", ["pytest interpreter", "system python", "pytest interpreter -> system python child", "env -i system python"])
def test_FB_LIVE_reduced_lineages_stay_FAIL_CLOSED_and_the_link_state_check_does_not_weaken_that(name):
    if not os.path.exists("/usr/bin/python3"):
        pytest.skip("system python not present")
    last = None
    for _ in range(3):
        if name == "pytest interpreter":
            last = _live([sys.executable])
        elif name == "system python":
            last = _live(["/usr/bin/python3"])
        elif name == "env -i system python":
            last = _live(["/usr/bin/env", "-i", "/usr/bin/python3"])
        else:
            last = _live(None, via_child=True)
        if not last["full_view"] or last["telemetry"] == "PASS":
            break
    if not last["full_view"]:
        assert last["telemetry"] == "FAIL_CLOSED", last
    else:
        assert last["telemetry"] == "PASS", last


# ================================================================================================================= PCB band: property tests tie the docs to the function
def _max_removable(counter, extra=3):
    """Largest number of rows that can be removed from a table of counter+extra rows while check_socket_plausibility still accepts (rows are loopback, so removal is the
    only variable)."""
    total = counter + extra; best = 0
    for k in range(total + 1):
        try:
            G.check_socket_plausibility(rows_of(sockets_text(tcp=total - k)), pcb(counter))
            best = k
        except G.TelemetryError:
            break
    return total, best


@pytest.mark.parametrize("c", [1, 2, 3, 5, 8, 12, 20, 50, 100, 300])
def test_FB_whole_table_disappearance_is_always_detected_when_a_counter_is_nonzero(c):
    with pytest.raises(G.TelemetryError):
        G.check_socket_plausibility(rows_of(sockets_text(tcp=0)), pcb(c))


def test_FB_the_blind_spot_matches_what_the_documentation_says():
    total, best = _max_removable(3)
    assert best / total > 0.5                                                                    # "a MAJORITY of the rows can [be removed] on a host with only a handful of PCBs"
    total, best = _max_removable(300)
    assert 0.2 <= best / total <= 0.34                                                           # "roughly a quarter to a third of the rows" on a busy host
    total, best = _max_removable(50)
    assert best >= 1                                                                             # "a single listener can always be hidden"
    for c in (1, 2, 3, 5, 8, 20, 100, 300):
        assert _max_removable(c)[1] >= 1


def test_FB_the_multiplicative_upper_allowance_is_gone():
    with pytest.raises(G.TelemetryError):
        G.check_socket_plausibility(rows_of(sockets_text(tcp=1000)), pcb(500))                  # previously accepted (<= 2*500+16)
    G.check_socket_plausibility(rows_of(sockets_text(tcp=500 + G.PCB_MAX_EXCESS)), pcb(500))
    with pytest.raises(G.TelemetryError):
        G.check_socket_plausibility(rows_of(sockets_text(tcp=500 + G.PCB_MAX_EXCESS + 1)), pcb(500))


def test_FB_a_zero_counter_tolerates_exactly_the_measured_constant_excess_and_documents_it():
    G.check_socket_plausibility(rows_of(sockets_text(tcp=G.PCB_MAX_EXCESS)), pcb(0))
    with pytest.raises(G.TelemetryError):
        G.check_socket_plausibility(rows_of(sockets_text(tcp=G.PCB_MAX_EXCESS + 1)), pcb(0))
    assert "A counter of 0 therefore still tolerates up to 12 rows" in Path(G.__file__).read_text() and G.PCB_MAX_EXCESS == 12


@pytest.mark.parametrize("seed", range(6))
def test_FB_natural_churn_never_causes_a_false_PASS_only_possibly_a_false_failure(seed):
    """Random bracket/row combinations: whenever the band accepts, the rows really are inside the documented limits."""
    rnd = random.Random(seed)
    for _ in range(400):
        lo = rnd.randint(0, 400); hi = lo + rnd.randint(0, 60); n = rnd.randint(0, hi + 40)
        try:
            G.check_socket_plausibility(rows_of(sockets_text(tcp=n)), {"before": {"tcp": lo, "raw": 0}, "after": {"tcp": hi, "raw": 0}})
            accepted = True
        except G.TelemetryError:
            accepted = False
        need = max(1, int(0.75 * lo)) if lo >= 1 else 0
        assert accepted == (need <= n <= hi + G.PCB_MAX_EXCESS)


# ================================================================================================================= BLOCKER A: documentation
WITHDRAWN = ("detects removal of the Internet section or of most", "most TCP/raw rows", "majority of TCP/raw rows", "independently cross-checked", "addresses/status (cross-checked",
             "interface addresses and status (independently", "2 * higher counter", "2 × higher counter", "2x allowance has", "Internet section or of the majority")


def _doc_texts():
    return {p.name: " ".join(p.read_text().split()) for p in [Path(G.__file__), *sorted(INFRA.glob("GENESIS_V2_TIER0S_*.md"))]}


def test_FB_withdrawn_completeness_claims_do_not_return_anywhere():
    bad = {}
    for name, t in _doc_texts().items():
        if name.endswith("FINAL_BLOCKERS_REMEDIATION.md") or name.endswith("W1_W2_REMEDIATION.md") or name.endswith("ACCEPTANCE_AUDIT.md"):
            continue                                                                             # the traceability documents quote the withdrawn wording in order to withdraw it
        hits = [w for w in WITHDRAWN if w in t]
        if hits:
            bad[name] = hits
    assert bad == {}, bad


def test_FB_the_historical_documents_mention_withdrawn_wording_only_as_withdrawn():
    for name in ("GENESIS_V2_TIER0S_W1_W2_REMEDIATION.md", "GENESIS_V2_TIER0S_FINAL_BLOCKERS_REMEDIATION.md"):
        t = " ".join((INFRA / name).read_text().split())
        for w in WITHDRAWN:
            for m in re.finditer(re.escape(w), t):
                ctx = t[max(0, m.start() - 240):m.end() + 240].lower()
                assert any(k in ctx for k in ("withdrawn", "removed", "inaccurate", "was single-sourced", "earlier", "replaced", "no longer", "found by the acceptance audit")), (name, w)


def test_FB_the_gate_states_the_exact_blind_spot_of_the_socket_band():
    d = " ".join(G.__doc__.split())
    for must in ("PLAUSIBILITY HEURISTIC, NOT row-by-row completeness", "a MAJORITY of the rows can", "A single listener can always be hidden", "the disappearance of the whole table is always detected",
                 "roughly a quarter to a third of the rows", "UDP completeness is unproven and UDP absence is not claimed"):
        assert must in d, must


def test_FB_the_gate_states_what_the_link_state_cross_check_is_and_is_not():
    d = " ".join(G.__doc__.split())
    for must in ("SIOCGIFMEDIA", "the SAME KERNEL ANSWER", "independent of the ifconfig TOOL", "cannot be established", "FAIL_CLOSED (availability is preferred over false isolation)",
                 "RUNNING and the other flags are NOT compared", "LINK_STATE_UNESTABLISHED" if "LINK_STATE_UNESTABLISHED" in d else "EXPLICIT LINK POLICY"):
        assert must in d, must


def test_FB_the_claim_scanner_covers_the_new_vocabulary():
    for sentence in ("The band detects removal of most rows in the socket table.", "The interface status is independently cross-checked against the kernel for every row.",
                     "The route table is complete."):
        pass
    assert _scan("This proves the socket table is complete.") and _scan("The output is exhaustive for all sockets.")
    assert not _scan("Completeness is NOT claimed for the route table.")


def test_FB_no_sentence_in_the_gate_or_the_docs_claims_the_completeness_of_telemetry_without_a_qualifier():
    bad = {n: _scan(t) for n, t in {p.name: p.read_text() for p in [Path(G.__file__), *sorted(INFRA.glob("GENESIS_V2_TIER0S_*.md"))]}.items() if _scan(t)}
    assert bad == {}, bad


def test_FB_the_final_blockers_document_classifies_every_claim_with_the_closed_vocabulary():
    doc = (INFRA / "GENESIS_V2_TIER0S_FINAL_BLOCKERS_REMEDIATION.md").read_text()
    rows = [l for l in doc.splitlines() if re.match(r"^\| C\d+ \|", l)]
    assert len(rows) >= 20
    for l in rows:
        cls = [c.strip() for c in l.split("|")][2]
        assert cls in ("ENFORCED", "ADVISORY", "PROCEDURAL", "UNPROVEN"), l
    assert {c.strip() for l in rows for c in [l.split("|")[2]]} == {"ENFORCED", "ADVISORY", "PROCEDURAL", "UNPROVEN"}


def test_FB_physical_detachment_cold_boot_and_real_environment_isolation_stay_procedural_or_unproven():
    doc = (INFRA / "GENESIS_V2_TIER0S_FINAL_BLOCKERS_REMEDIATION.md").read_text()
    for l in doc.splitlines():
        if re.match(r"^\| C\d+ \|", l) and re.search(r"(?i)physical detachment|cold boot|real[- ]environment isolation", l):
            assert l.split("|")[2].strip() in ("PROCEDURAL", "UNPROVEN"), l


def test_FB_the_matrix_maps_every_finding_to_regression_tests_that_exist():
    txt = (INFRA / "GENESIS_V2_TIER0S_FINAL_BLOCKERS_REMEDIATION.md").read_text()
    sources = (ROOT / "tests" / "test_genesis_v2_tier0s_final_blockers.py").read_text()
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (B[A-Z0-9]+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`(test_[^`]+)`", line)
        seen[m.group(1)] = names
        assert names, f"{m.group(1)} has no regression tests"
        for t in names:
            assert re.search(rf"def {re.escape(t)}\b", sources), f"{m.group(1)}: {t} does not exist"
    assert set(seen) == {"BA", "BB", "BP", "BW6", "BD", "BX"}


# ================================================================================================================= W6: authentic but malformed SEAL plaintext
def _mod():
    import importlib.util as u
    s = u.spec_from_file_location("tier0a_bundle_fb", ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py"); m = u.module_from_spec(s); s.loader.exec_module(m)
    return m


B = _mod()
SEAL_PAYLOADS = {
    "not json": b"not json", "empty": b"", "json int": b"5", "json null": b"null", "json true": b"true", "json list": b"[]", "json string": b'"abc"', "invalid utf-8": b"\xff\xfe",
    "utf-8 bom": b"\xef\xbb\xbf{}", "empty object": b"{}", "missing a split": json.dumps({"SCREEN": "0" * 64}).encode(), "extra split": json.dumps({"SCREEN": "0" * 64, "QUALIFICATION_HOLDOUT": "0" * 64, "X": "0" * 64}).encode(),
    "non-str digests": json.dumps({"SCREEN": 1, "QUALIFICATION_HOLDOUT": 2}).encode(), "null digests": json.dumps({"SCREEN": None, "QUALIFICATION_HOLDOUT": None}).encode(),
    "short digest": json.dumps({"SCREEN": "ab", "QUALIFICATION_HOLDOUT": "cd"}).encode(), "uppercase digest": json.dumps({"SCREEN": "A" * 64, "QUALIFICATION_HOLDOUT": "B" * 64}).encode(),
    "non-hex digest": json.dumps({"SCREEN": "g" * 64, "QUALIFICATION_HOLDOUT": "h" * 64}).encode(), "digest with newline": json.dumps({"SCREEN": "a" * 64 + "\n", "QUALIFICATION_HOLDOUT": "b" * 64}).encode(),
    "digest is a list": json.dumps({"SCREEN": ["a" * 64], "QUALIFICATION_HOLDOUT": ["b" * 64]}).encode(), "digest is a dict": json.dumps({"SCREEN": {}, "QUALIFICATION_HOLDOUT": {}}).encode(),
    "deep nesting 5000": b"[" * 5000 + b"]" * 5000, "deep nesting 200000": b"[" * 200000 + b"]" * 200000, "deep object nesting": b'{"a":' * 3000 + b"1" + b"}" * 3000,
    "huge number": b"9" * 100000, "nan": b"NaN", "duplicate keys": b'{"SCREEN":"' + b"a" * 64 + b'","SCREEN":"' + b"b" * 64 + b'","QUALIFICATION_HOLDOUT":"' + b"c" * 64 + b'"}',
}


def _forged(tmp, name, payload, priv_pub):
    from orca.eval.genesis_v2 import spec, store as S
    priv, pub = priv_pub
    cid = "gce2c-" + "ab" * 16
    out = tmp / ("out_" + re.sub(r"\W", "_", name)[:20]); digest = S.EncryptedVaultWriter(out, pub, repo_root=ROOT).write_corpus(cid, {sp: b"SYNTHETIC-" + sp.encode() for sp in spec.PRIVATE_SPLITS})
    sealf = out / cid / "SEAL.enc"; os.chmod(out / cid, 0o700); os.chmod(sealf, 0o600); sealf.unlink()
    hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SEAL", "corpus_digest": digest}
    sealf.write_bytes(S.EncryptedVaultWriter(tmp / "w", pub, repo_root=ROOT)._seal_blob(hdr, payload))
    for p in out.rglob("*"):
        p.chmod(0o700 if p.is_dir() else 0o600)
    B.seal(out)
    return out, priv, digest, cid


@pytest.mark.parametrize("name", sorted(SEAL_PAYLOADS))
def test_FB_a_valid_encryption_of_a_malformed_SEAL_is_a_typed_VERIFICATION_FAILED_never_an_exception(tmp_path, bundle, name):
    from orca.eval.genesis_v2 import store as S
    priv_pub = S.generate_vault_keypair()
    out, priv, digest, _cid = _forged(tmp_path, name, SEAL_PAYLOADS[name], priv_pub)
    problems = B.cryptographic_verify(out, priv, digest)
    assert problems and all(B.VERIFICATION_FAILED in p for p in problems), problems
    assert B.classify(problems) == "VERIFICATION_FAILED"


def test_FB_the_store_maps_every_malformed_authenticated_payload_to_the_integrity_error():
    from orca.eval.genesis_v2 import store as S
    for name, payload in SEAL_PAYLOADS.items():
        if name == "duplicate keys":
            continue                                                                             # duplicate keys are accepted by json.loads (last wins) but the digest then cannot match
        with pytest.raises(S.PrivateStorageIntegrityError):
            S._seal_digests(payload)
    good = json.dumps({"SCREEN": "a" * 64, "QUALIFICATION_HOLDOUT": "b" * 64}).encode()
    assert S._seal_digests(good) == {"SCREEN": "a" * 64, "QUALIFICATION_HOLDOUT": "b" * 64}


@pytest.mark.parametrize("exc", [RuntimeError("defect"), TypeError("defect"), AttributeError("defect"), KeyError("defect"), ZeroDivisionError(), MemoryError()])
def test_FB_a_genuine_defect_inside_the_payload_handling_propagates(monkeypatch, exc):
    from orca.eval.genesis_v2 import store as S
    monkeypatch.setattr(S.json, "loads", lambda *a, **k: (_ for _ in ()).throw(exc))
    with pytest.raises(type(exc)):
        S._seal_digests(b"{}")


def test_FB_only_the_documented_decoding_errors_are_translated(monkeypatch):
    from orca.eval.genesis_v2 import store as S
    for exc in (ValueError("bad"), UnicodeDecodeError("utf-8", b"\xff", 0, 1, "x"), RecursionError("deep")):
        monkeypatch.setattr(S.json, "loads", lambda *a, _e=exc, **k: (_ for _ in ()).throw(_e))
        with pytest.raises(S.PrivateStorageIntegrityError):
            S._seal_digests(b"{}")


def test_FB_the_symmetric_store_reader_has_the_same_protection(tmp_path):
    pytest.importorskip("cryptography")
    from orca.eval.genesis_v2 import spec, store as S
    key = bytes(range(1, 33))
    st_ = S.EncryptedFileStore(tmp_path / "sym", key, repo_root=ROOT)
    cid = "gce2c-" + "cd" * 16
    digest = st_.write_corpus(cid, {sp: b"SYNTHETIC-" + sp.encode() for sp in spec.PRIVATE_SPLITS})
    assert st_.read_split(cid, "SCREEN", expected_corpus_digest=digest) == b"SYNTHETIC-SCREEN"
    sealf = tmp_path / "sym" / cid / "SEAL.enc"; os.chmod(tmp_path / "sym" / cid, 0o700); os.chmod(sealf, 0o600); sealf.unlink()
    for payload in (b"not json", b"5", b"null", b"[]", b"[" * 100000):
        hdr = {"eval_version": spec.EVAL_VERSION, "corpus_id": cid, "split": "SEAL", "corpus_digest": digest}
        sealf.write_bytes(st_._seal_blob(hdr, payload))
        os.chmod(sealf, 0o600)
        with pytest.raises(S.PrivateStorageIntegrityError):
            st_.read_split(cid, "SCREEN", expected_corpus_digest=digest)
        sealf.unlink()


def test_FB_genuine_artifacts_still_verify_after_the_store_change(bundle):
    b, priv, digest = bundle[0], bundle[2], bundle[3]
    assert B.cryptographic_verify(b, priv, digest) == []


# ================================================================================================================= DIAG: parser/collector defect visibility
def _defect_host(tmp, key):
    return good_host(tmp)


def test_FB_a_parser_defect_is_distinguished_from_a_host_condition_and_leaks_no_message(tmp_path, monkeypatch):
    def boom(_):
        raise KeyError("SECRET-HOST-DATA-192.0.2.77")
    monkeypatch.setattr(G, "parse_routes4", boom)
    res = run("forge", tmp_path, host=good_host(tmp_path))
    d = res["telemetry_complete"]["detail"]
    assert "routes4=PARSER_DEFECT:KeyError" in d and "SECRET-HOST-DATA" not in json.dumps(res) and "192.0.2.77" not in json.dumps(res)
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and st(res, "network_no_default_route") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_FB_expected_malformed_telemetry_keeps_its_ordinary_reason(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path, routes4="garbage\n"))
    assert "routes4=MALFORMED" in res["telemetry_complete"]["detail"] and "DEFECT" not in res["telemetry_complete"]["detail"]


@pytest.mark.parametrize("exc", [KeyError("x"), AttributeError("x"), ZeroDivisionError(), IndexError("x"), RuntimeError("x")])
def test_FB_every_unexpected_parser_exception_fails_closed_with_its_class_name(tmp_path, monkeypatch, exc):
    monkeypatch.setattr(G, "parse_sockets", lambda t: (_ for _ in ()).throw(exc))
    res = run("forge", tmp_path, host=good_host(tmp_path))
    assert f"sockets=PARSER_DEFECT:{type(exc).__name__}" in res["telemetry_complete"]["detail"] and not G.gate_passes(res)


def test_FB_collect_host_marks_post_processing_and_collector_defects(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("OK", "x\n") if cmd[0] == "ps" else ("UNAVAILABLE", None))
    monkeypatch.setattr(G, "read_ifaddrs", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(G, "read_linkstate", lambda names: (_ for _ in ()).throw(ZeroDivisionError()))
    monkeypatch.setattr(G.socket, "if_nameindex", lambda: [(1, "lo0")])
    h = G.collect_host()
    assert h["telemetry"]["ifaddrs"] == "COLLECTOR_DEFECT:RuntimeError" and h["telemetry"]["linkstate"] == "COLLECTOR_DEFECT:ZeroDivisionError"
    monkeypatch.setattr(G, "_run", lambda cmd: ("OK", "x"))
    monkeypatch.setattr(G, "parse_disks_probe", None, raising=False)


def test_FB_get_postprocessing_defect_is_PARSER_DEFECT(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("OK", "text"))
    monkeypatch.setattr(G, "_parse_disks", lambda o: (_ for _ in ()).throw(TypeError("x")))
    monkeypatch.setattr(G, "read_ifaddrs", lambda: [])
    h = G.collect_host()
    assert h["telemetry"]["disks"] == "PARSER_DEFECT:TypeError"


def test_FB_pwd_defects_other_than_a_missing_entry_are_marked_as_collector_defects(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("UNAVAILABLE", None))
    monkeypatch.setattr(G.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError("no entry")))
    assert G.collect_host()["telemetry"]["home"] == "UNAVAILABLE"
    monkeypatch.setattr(G.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(RuntimeError("weird")))
    assert G.collect_host()["telemetry"]["home"] == "COLLECTOR_DEFECT:RuntimeError"


def test_FB_defect_reasons_are_documented_in_the_closed_vocabulary():
    d = " ".join(G.__doc__.split())
    assert "PARSER_DEFECT:<ExceptionClass>" in d and "COLLECTOR_DEFECT:<ExceptionClass>" in d and "never the message" in d


# ================================================================================================================= whole-gate invariant (decisive network semantics)
def test_FB_no_single_source_or_pairwise_reduction_of_a_live_network_yields_a_network_PASS(tmp_path):
    """A host with usable networking (en0 192.0.2.50 UP and active). Every way ONE or TWO sources can be incomplete must not yield an interface/route/socket PASS."""
    live = ("\tinet 192.0.2.50 netmask 0xffffff00 broadcast 192.0.2.255\n", ["192.0.2.50"])

    def host(**kw):
        h = good_host(tmp_path, ifconfig=LO_BLOCK + "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n" + live[0] + "\tmedia: autoselect\n\tstatus: active\n",
                      routes4=GOOD_ROUTES + "default 192.0.2.1 UGScg en0\n192.0.2/24 link#4 UCS en0\n", routes6=GOOD_ROUTES6,
                      ifaddrs=[{"name": "lo0", "flags": 0x8049, "v4": ["127.0.0.1"], "v6": ["::1", "fe80::1"]}, {"name": "en0", "flags": 0x8863, "v4": ["192.0.2.50"], "v6": []}],
                      linkstate={"lo0": "no_media", "en0": "active"}, sockets=sockets_text(tcp=3, ext=2), pcbcounts=pcb(2))
        h.update(kw)
        return h
    reductions = {
        "ifconfig omits the address": dict(ifconfig=LO_BLOCK + en_block("none", "active", True)),
        "ifconfig omits the status line": dict(ifconfig=LO_BLOCK + en_block("priv4", None, True)),
        "libc omits the address": dict(ifaddrs=[{"name": "lo0", "flags": 0x8049, "v4": ["127.0.0.1"], "v6": ["::1", "fe80::1"]}, {"name": "en0", "flags": 0x8863, "v4": [], "v6": []}]),
        "link state omitted (unavailable)": dict(linkstate=None),
        "link state says inactive": dict(linkstate={"lo0": "no_media", "en0": "inactive"}),
        "routes omit the default and subnet": dict(routes4=GOOD_ROUTES),
        "sockets table emptied (counters real)": dict(sockets=sockets_text()),
        "socket section removed": dict(sockets="Active LOCAL (UNIX) domain sockets\nA\n"),
        "counters omitted": dict(pcbcounts=None),
    }
    items = list(reductions.items())
    for name, kw in items + [(f"{a[0]} + {b[0]}", {**a[1], **b[1]}) for a, b in itertools.combinations(items, 2)]:
        res = run("forge", tmp_path, host=host(**kw))
        assert st(res, "network_interfaces_disabled") != G.PASS, name
        assert not G.gate_passes(res), name

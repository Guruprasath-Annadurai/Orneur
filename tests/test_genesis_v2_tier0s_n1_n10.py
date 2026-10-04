"""Tier0-S N1-N10 final remediation -- adversarial regression tests (SYNTHETIC; no real boot, no real secrets, no network, no GPU).

Every test is named for the finding it pins: N1 socket blank-line, N2 trusted home, N3 volumes/disks, N4 plausibility floors, N5 absolute tool paths,
N6 descriptor-relative walker, N7 documentation, N8 deny configuration, N9 manifest pin workflow, N10 validator error handling + interlock concurrency.
These prove the gate's fail-closed LOGIC only. They are not evidence of a second boot environment, separate encrypted storage, or continuous enforcement."""
import errno
import hashlib
import importlib.util
import os
import plistlib
import random
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_genesis_v2_tier0a_transfer_bundle import bundle  # noqa: F401  (pytest fixture: synthetic sealed bundle, ephemeral key)
from tests.test_genesis_v2_tier0s_phase_gate import (BOOT_A, GOOD_DISKS, GOOD_IFCONFIG, GOOD_IFNAMES, GOOD_ROUTES, GOOD_ROUTES6, GOOD_SOCKETS, INFRA, ROOT,
                                                     SOCK_TAIL, G, good_host, make_cfg, nonroot, run, st)

SOCK_HEAD = "Active Internet connections (including servers)\nProto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n"
OK_ROW = "tcp4       0      0  127.0.0.1.8080         *.*                    LISTEN\n"
EXT_TCP = "tcp4       0      0  203.0.113.9.5000       *.*                    LISTEN\n"
EXT_UDP = "udp4       0      0  203.0.113.9.123        *.*                    \n"
EXT_ICMP = "icm4       0      0  203.0.113.9.*          *.*                    \n"
MPTCP_HEAD = "Active Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n"
UNIX = "Active LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"


def sock(rows="", between="", tail=None):
    """Internet section + (optional) junk + terminating sections."""
    return SOCK_HEAD + rows + between + (SOCK_TAIL if tail is None else tail)


def parse_ok(text):
    return G.parse_sockets(text)


def rejects(fn, *a):
    with pytest.raises(G.TelemetryError):
        fn(*a)


# =============================================================================================================================== N1 sockets
@pytest.mark.parametrize("hidden", [EXT_TCP, EXT_UDP, EXT_ICMP])
@pytest.mark.parametrize("sep", ["\n", "\n\n", " \n", "\t\n", "  \n\n \n"])
def test_N1_an_external_socket_after_a_blank_or_whitespace_line_is_refused_not_ignored(hidden, sep):
    rejects(G.parse_sockets, sock(OK_ROW + sep + hidden))


@pytest.mark.parametrize("sep", ["\r", "\r\n", "\x0b", "\x0c", "\x00", " ", "\x85", "\x1c", "\r\r"])
def test_N1_CR_and_other_non_LF_separators_are_not_line_breaks_and_are_refused(sep):
    rejects(G.parse_sockets, sock(OK_ROW + sep + EXT_TCP))
    rejects(G.parse_sockets, sock(OK_ROW).replace("\n", sep))


def test_N1_garbage_after_a_blank_line_is_refused():
    rejects(G.parse_sockets, sock(OK_ROW + "\n" + "garbage that is not a row\n"))
    rejects(G.parse_sockets, sock(OK_ROW + "\n\n" + "tcp4 0 0\n"))


def test_N1_the_table_may_end_with_blank_lines_then_the_next_Active_section():
    for between in ("", "\n", "\n\n", " \n", "\n \n\n"):
        rows = G.parse_sockets(sock(OK_ROW, between))
        assert rows == [("tcp4", "LISTEN", False)]


def test_N1_a_following_Active_section_directly_after_a_row_is_an_explicit_boundary():
    assert G.parse_sockets(SOCK_HEAD + OK_ROW + SOCK_TAIL.lstrip("\n")) == [("tcp4", "LISTEN", False)]


def test_N1_a_table_that_runs_to_the_end_of_the_output_is_truncated_and_refused():
    rejects(G.parse_sockets, SOCK_HEAD + OK_ROW)
    rejects(G.parse_sockets, SOCK_HEAD + OK_ROW + "\n")
    rejects(G.parse_sockets, SOCK_HEAD)
    rejects(G.parse_sockets, SOCK_HEAD + OK_ROW[:-12])                          # cut mid-row (also not newline-terminated)
    rejects(G.parse_sockets, sock(OK_ROW, tail=MPTCP_HEAD))                     # multipath section itself not terminated


def test_N1_header_only_table_is_verified_empty_only_when_it_is_terminated():
    assert G.parse_sockets(sock("")) == []
    rejects(G.parse_sockets, SOCK_HEAD)
    rejects(G.parse_sockets, SOCK_HEAD.split("\n")[0] + "\n")                   # no column header


@pytest.mark.parametrize("hdr", ["Proto Recv-Q Send-Q", "Proto Recv-Q Send-Q Local Address Foreign Address", "Proto Recv-Q Send-Q Local Address Foreign Address (stat)",
                                 "Recv-Q Send-Q Local Address Foreign Address (state)", "Proto Recv-Q Send-Q Local Address Foreign Address (state) Extra", ""])
def test_N1_partial_or_altered_column_headers_are_refused(hdr):
    rejects(G.parse_sockets, "Active Internet connections (including servers)\n" + hdr + "\n" + OK_ROW + SOCK_TAIL)


def test_N1_output_must_begin_with_an_Active_section_and_contain_an_Internet_section():
    rejects(G.parse_sockets, "\n" + sock(OK_ROW))
    rejects(G.parse_sockets, "junk\n" + sock(OK_ROW))
    rejects(G.parse_sockets, UNIX + "Address Type\n" + UNIX)
    rejects(G.parse_sockets, "")
    rejects(G.parse_sockets, None)
    rejects(G.parse_sockets, b"Active")


def test_N1_multipath_section_rows_are_classified_like_any_other_and_unknown_formats_are_refused():
    ext = MPTCP_HEAD + "tcp4 0 0 203.0.113.9.80 *.* LISTEN\n\n" + UNIX
    assert any(r[2] for r in G.parse_sockets(SOCK_HEAD + OK_ROW + "\n" + ext))                 # an external socket listed under the multipath header is NOT ignored
    real_like = MPTCP_HEAD + "icm6       0      0  *.*                    *.*                               \nicm6       0      0  *.*                    *.*\n" + UNIX
    assert G.parse_sockets(SOCK_HEAD + OK_ROW + "\n" + real_like) == [("tcp4", "LISTEN", False), ("icm6", "ICMP", False), ("icm6", "ICMP", False)]
    rejects(G.parse_sockets, SOCK_HEAD + OK_ROW + "\n" + MPTCP_HEAD + "mptcp4 0 0 203.0.113.9.80 *.* LISTEN\n\n" + UNIX)   # unrecognised protocol row
    assert G.parse_sockets(SOCK_HEAD + OK_ROW + "\n" + MPTCP_HEAD + "\n" + UNIX) == [("tcp4", "LISTEN", False)]


def test_N1_the_real_macOS_netstat_output_shape_parses_when_available():
    if sys.platform != "darwin":
        pytest.skip("macOS only")
    p = subprocess.run(["/usr/sbin/netstat", "-an"], capture_output=True, text=True, timeout=60)
    if p.returncode != 0 or not p.stdout.startswith("Active Internet connections"):
        pytest.skip("this process environment does not receive the Internet section from netstat")
    rows = G.parse_sockets(p.stdout)
    assert isinstance(rows, list)


def test_N1_every_blank_CR_or_control_insertion_at_every_position_either_raises_or_still_reports_the_external_listener():
    base = sock(OK_ROW + EXT_TCP)
    assert any(r[2] for r in G.parse_sockets(base))
    inserts = ("\n", "\r", "\r\n", "\n\n", " \n", "\x0b", "\x0c", "\x00", " ", "\x85", "\n \n", "\t\n")
    silent = []
    for pos in range(len(base) + 1):
        for ins in inserts:
            m = base[:pos] + ins + base[pos:]
            try:
                rows = G.parse_sockets(m)
            except G.TelemetryError:
                continue
            if not any(r[2] for r in rows):
                silent.append((pos, ins))
    assert silent == []


def test_N1_the_evaluate_level_result_is_FAIL_CLOSED_with_the_reason(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path, sockets=sock(OK_ROW + "\n" + EXT_TCP)))
    assert st(res, "network_no_external_sockets") == G.FAIL_CLOSED and "sockets=MALFORMED" in res["telemetry_complete"]["detail"] and not G.gate_passes(res)


# =============================================================================================================================== N2 trusted home
def _pw(home):
    return lambda uid: SimpleNamespace(pw_dir=str(home), pw_name="x", pw_uid=uid)


def _no_tools(monkeypatch):
    monkeypatch.setattr(G, "_run", lambda cmd: ("UNAVAILABLE", None))


def test_N2_HOME_environment_variable_is_never_the_source_of_the_trusted_home(tmp_path, monkeypatch):
    real_home = tmp_path / "realhome"; real_home.mkdir()
    fake = tmp_path / "emptyhome"; fake.mkdir()
    monkeypatch.setattr(G.pwd, "getpwuid", _pw(real_home)); _no_tools(monkeypatch)
    for val in (str(fake), str(tmp_path / "does_not_exist"), "", "relative/home", "/"):
        monkeypatch.setenv("HOME", val)
        assert G.collect_host()["home"] == real_home
    monkeypatch.delenv("HOME", raising=False)
    assert G.collect_host()["home"] == real_home


def test_N2_residual_exposure_checks_use_the_trusted_home_even_when_HOME_points_at_an_empty_directory(tmp_path, monkeypatch):
    real_home = tmp_path / "realhome"; (real_home / ".claude").mkdir(parents=True); (real_home / ".claude" / "t.jsonl").write_text("x")
    empty = tmp_path / "emptyhome"; empty.mkdir()
    monkeypatch.setattr(G.pwd, "getpwuid", _pw(real_home)); _no_tools(monkeypatch); monkeypatch.setenv("HOME", str(empty))
    host = G.collect_host()
    host.update({k: v for k, v in good_host(tmp_path).items() if k not in ("home", "telemetry", "env")})
    host["telemetry"] = {k: "OK" for k in host if k != "telemetry"}
    res = run("forge", tmp_path, host=host)
    assert st(res, "agent_residual_exposure_absent") == G.FAIL                       # the REAL home holds an agent store; the empty $HOME is ignored


def test_N2_password_database_failures_are_FAIL_CLOSED(tmp_path, monkeypatch):
    _no_tools(monkeypatch)
    monkeypatch.setattr(G.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(KeyError("getpwuid(): uid not found")))
    h = G.collect_host()
    assert h["home"] is None and h["telemetry"]["home"] == "UNAVAILABLE"
    monkeypatch.setattr(G.pwd, "getpwuid", lambda uid: (_ for _ in ()).throw(OSError("directory services down")))
    assert G.collect_host()["home"] is None
    monkeypatch.setattr(G.pwd, "getpwuid", lambda uid: SimpleNamespace())          # entry without pw_dir
    assert G.collect_host()["home"] is None
    res = run("forge", tmp_path, host=good_host(tmp_path, home=None, telemetry={"home": "UNAVAILABLE"}))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and "home=UNAVAILABLE" in res["telemetry_complete"]["detail"]
    for k in ("cloud_sync_residual_exposure_absent", "agent_residual_exposure_absent", "container_runtime_absent"):
        assert st(res, k) == G.FAIL_CLOSED


def _home_status(tmp_path, home):
    res = run("forge", tmp_path, host=good_host(tmp_path, home=home))
    return res


def test_N2_a_nonexistent_home_is_FAIL_CLOSED_not_a_clean_pass(tmp_path):
    res = _home_status(tmp_path, tmp_path / "nope")
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and "home=UNAVAILABLE" in res["telemetry_complete"]["detail"]
    assert st(res, "agent_residual_exposure_absent") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_N2_a_regular_file_instead_of_a_directory_is_FAIL_CLOSED(tmp_path):
    f = tmp_path / "homefile"; f.write_text("x")
    res = _home_status(tmp_path, f)
    assert "home=MALFORMED" in res["telemetry_complete"]["detail"] and st(res, "cloud_sync_residual_exposure_absent") == G.FAIL_CLOSED


def test_N2_a_symlinked_home_is_FAIL_CLOSED_even_when_it_points_at_a_real_directory(tmp_path):
    real = tmp_path / "real"; real.mkdir(); link = tmp_path / "linkhome"; link.symlink_to(real)
    res = _home_status(tmp_path, link)
    assert "home=MALFORMED" in res["telemetry_complete"]["detail"] and not G.gate_passes(res)


def test_N2_a_home_reached_through_a_symlinked_ancestor_is_not_canonical(tmp_path):
    real = tmp_path / "real"; (real / "h").mkdir(parents=True); link = tmp_path / "ln"; link.symlink_to(real)
    res = _home_status(tmp_path, link / "h")
    assert "home=MALFORMED" in res["telemetry_complete"]["detail"]


def test_N2_a_non_canonical_spelling_is_refused(tmp_path):
    (tmp_path / "h").mkdir()
    for spelling in (str(tmp_path / "h") + "/", str(tmp_path / "x" / ".." / "h"), str(tmp_path) + "//h"):
        rejects(G.parse_home, spelling)


@pytest.mark.parametrize("bad", [None, 5, [], {}, "", "relative", "\0", b"/tmp", ("a",)])
def test_N2_non_path_homes_never_crash_and_are_refused(bad):
    rejects(G.parse_home, bad)


def test_N2_wrong_ownership_is_FAIL_CLOSED(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir(exist_ok=True)
    monkeypatch.setattr(G, "_euid", lambda: os.geteuid() + 12345)
    res = run("forge", tmp_path, host=good_host(tmp_path))
    assert "home=MALFORMED" in res["telemetry_complete"]["detail"] and st(res, "agent_residual_exposure_absent") == G.FAIL_CLOSED


def test_N2_a_valid_owned_canonical_home_is_accepted(tmp_path):
    h = tmp_path / "home"; h.mkdir()
    assert G.parse_home(h) == h
    assert G.gate_passes(run("forge", tmp_path))


def test_N2_the_real_cli_home_comes_from_the_password_database_not_HOME():
    import pwd
    try:
        expected = Path(pwd.getpwuid(os.geteuid()).pw_dir)
    except KeyError:
        pytest.skip("no passwd entry for this uid (bare container); the gate fails closed here, covered by the password-database failure test")
    code = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('g','scripts/genesis_v2_tier0s_phase_gate.py');m=importlib.util.module_from_spec(s);"
            "s.loader.exec_module(m);m._run=lambda c:('UNAVAILABLE',None);print(m.collect_host()['home'])")
    p = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env={**os.environ, "HOME": "/definitely/not/a/home"}, timeout=60)
    assert p.stdout.strip() == str(expected), p.stderr


# =============================================================================================================================== N3 volumes / disks
DENY = dict(deny_paths=[], deny_volumes=["WitnessVault"])
BAD_VOLUMES = ["Macintosh HD", "", {}, {"a": 1}, 5, 5.5, True, [], [None], [5], [[]], [{}], [{"name": "x"}], ["ok", None], ["ok", 5], ["a/b"], ["ok\0"], [""], ["ok", ""],
               (("a",)), b"bytes", object(), [b"x"]]


@pytest.mark.parametrize("vols", BAD_VOLUMES, ids=lambda v: repr(v)[:30])
def test_N3_malformed_volumes_are_FAIL_CLOSED_and_never_pass(tmp_path, vols):
    res = run("forge", tmp_path, host=good_host(tmp_path, volumes=vols), **DENY)
    assert st(res, "other_role_storage_unavailable") == G.FAIL_CLOSED and st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


def _d(**kw):
    r = {"name": "Macintosh HD", "uuid": "", "dev": "disk3s1", "mount": "/"}
    r.update(kw)
    return r


BAD_DISKS = ["Macintosh HD", {}, {"a": 1}, 5, True, [], [None], [5], ["x"], [[]], [{}], [{"name": "x"}], [_d(name=5)], [_d(name=None)], [_d(uuid=5)], [_d(uuid="not-a-uuid")],
             [_d(uuid="ABCD0000-1111-2222-3333-44445555666")], [_d(uuid="ABCD0000-1111-2222-3333-444455556666\n")], [_d(dev="")], [_d(dev=7)], [_d(dev="../etc")],
             [_d(dev="disk")], [_d(dev="disk3s")], [_d(mount="relative")], [_d(mount=5)], [_d(mount=None)], [_d(mount="/a\0b")], [{**_d(), "extra": 1}],
             [{k: v for k, v in _d().items() if k != "uuid"}], [{k: v for k, v in _d().items() if k != "dev"}], [_d(), None], [_d(), {}], [_d(), "x"], [[_d()]], ({"a": 1},)]


@pytest.mark.parametrize("disks", BAD_DISKS, ids=lambda v: repr(v)[:40])
def test_N3_malformed_disks_never_crash_and_are_FAIL_CLOSED(tmp_path, disks):
    res = run("forge", tmp_path, host=good_host(tmp_path, disks=disks), **DENY)               # must not raise TypeError/KeyError/AttributeError
    assert st(res, "other_role_storage_unavailable") == G.FAIL_CLOSED and st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_N3_volume_telemetry_is_not_required_and_not_validated_when_no_volume_or_uuid_is_configured(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path, volumes=5, disks="garbage"))
    assert G.gate_passes(res)                                                                  # only deny_paths configured: volumes/disks are irrelevant


def _plist(obj):
    return plistlib.dumps(obj)


BAD_PLISTS = [b"", b"not a plist", b"<plist>", _plist([]), _plist("x"), _plist(5), _plist({}), _plist({"AllDisksAndPartitions": "x"}), _plist({"AllDisksAndPartitions": {}}),
              _plist({"AllDisksAndPartitions": [0]}), _plist({"AllDisksAndPartitions": ["x"]}), _plist({"AllDisksAndPartitions": [[]]}),
              _plist({"AllDisksAndPartitions": [{"Partitions": "x"}]}), _plist({"AllDisksAndPartitions": [{"Partitions": [7]}]}),
              _plist({"AllDisksAndPartitions": [{"APFSVolumes": {"a": 1}}]}), _plist({"AllDisksAndPartitions": [{"APFSVolumes": [5]}]}),
              _plist({"AllDisksAndPartitions": [{"VolumeName": 5, "DeviceIdentifier": "disk1"}]}),
              _plist({"AllDisksAndPartitions": [{"VolumeName": "x", "DeviceIdentifier": ["disk1"]}]}),
              _plist({"AllDisksAndPartitions": [{"VolumeName": "x"}]}),                                                             # no device reference
              _plist({"AllDisksAndPartitions": [{"VolumeName": "x", "DeviceIdentifier": "disk1", "VolumeUUID": "bad"}]}),
              _plist({"AllDisksAndPartitions": [{"VolumeName": "x", "DeviceIdentifier": "disk1", "MountPoint": "rel"}]}),
              _plist({"AllDisksAndPartitions": [{"VolumeName": "x", "DeviceIdentifier": "disk1", "MountPoint": {"a": 1}}]}),
              _plist({"AllDisksAndPartitions": [{"DeviceIdentifier": "disk1"}]}),                                                   # no volume record at all => empty => implausible
              _plist({"AllDisksAndPartitions": []}), b"\x00" * 64]


@pytest.mark.parametrize("blob", BAD_PLISTS, ids=lambda b: repr(b)[:40])
def test_N3_diskutil_parser_errors_are_TelemetryError_never_a_bare_exception(blob):
    rejects(G._parse_disks, blob)


def test_N3_diskutil_good_plist_round_trips():
    blob = _plist({"AllDisksAndPartitions": [{"DeviceIdentifier": "disk3", "APFSVolumes": [
        {"VolumeName": "Macintosh HD", "DeviceIdentifier": "disk3s1", "VolumeUUID": "ABCD0000-1111-2222-3333-444455556666", "MountPoint": "/"}]}]})
    assert G._parse_disks(blob) == [{"name": "Macintosh HD", "uuid": "ABCD0000-1111-2222-3333-444455556666", "dev": "disk3s1", "mount": "/"}]


def test_N3_fuzzed_nested_plists_only_ever_raise_TelemetryError():
    rnd = random.Random(1)
    atoms = [None, True, 5, "x", "disk1", "", "ABCD0000-1111-2222-3333-444455556666", "/Volumes/x", [], {}]

    def gen(d=0):
        if d > 3 or rnd.random() < .3:
            return rnd.choice(atoms)
        if rnd.random() < .5:
            return [gen(d + 1) for _ in range(rnd.randint(0, 3))]
        keys = ["AllDisksAndPartitions", "Partitions", "APFSVolumes", "VolumeName", "VolumeUUID", "DeviceIdentifier", "MountPoint", "Other"]
        return {rnd.choice(keys): gen(d + 1) for _ in range(rnd.randint(0, 4))}
    for _ in range(1500):
        obj = {"AllDisksAndPartitions": [gen()]} if rnd.random() < .7 else gen()
        try:
            blob = plistlib.dumps(obj)
        except Exception:
            continue                                                                            # plistlib cannot serialize it (e.g. None): not a possible diskutil output
        try:
            G._parse_disks(blob)
        except G.TelemetryError:
            pass


# =============================================================================================================================== N4 plausibility floors
def test_N4_header_only_route_tables_are_refused():
    rejects(G.parse_routes4, "Routing tables\n\nInternet:\nDestination        Gateway            Flags               Netif Expire\n")
    rejects(G.parse_routes6, "Routing tables\n\nInternet6:\nDestination Gateway Flags Netif Expire\n")


def test_N4_a_route_table_truncated_before_its_loopback_entries_is_refused():
    t = "Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\ndefault 10.0.0.1 UGSc en0\n10.0.0 link#4 UCS en0\n"
    rejects(G.parse_routes4, t)
    assert G.parse_routes4(t + "127 127.0.0.1 UCS lo0\n")


def test_N4_route_tables_must_be_the_requested_family():
    rejects(G.parse_routes4, GOOD_ROUTES6)
    rejects(G.parse_routes6, GOOD_ROUTES)
    rejects(G.parse_routes4, GOOD_ROUTES + GOOD_ROUTES6)
    rejects(G.parse_routes4, "Routing tables\n\nDestination Gateway Flags Netif Expire\n127 127.0.0.1 UCS lo0\n")                  # no section header
    rejects(G.parse_routes6, GOOD_ROUTES6.replace("::1   ", "fe80", 1).replace("lo0", "en0"))                                          # no loopback interface row


@pytest.mark.parametrize("cut", [lambda t: t[:-1], lambda t: t[:-10], lambda t: t.rstrip("\n"), lambda t: ""])
def test_N4_unterminated_or_cut_telemetry_is_refused_for_every_table(cut):
    for fn, good in ((G.parse_routes4, GOOD_ROUTES), (G.parse_routes6, GOOD_ROUTES6), (G.parse_interfaces, GOOD_IFCONFIG), (G.parse_ifnames, GOOD_IFNAMES),
                      (G.parse_sockets, GOOD_SOCKETS)):
        rejects(fn, cut(good))


def test_N4_exit_zero_with_malformed_output_is_not_accepted(tmp_path):
    for key, junk in (("routes4", "OK\n"), ("routes6", "Routing tables\n"), ("sockets", "Active Internet connections\n"), ("ifconfig", "lo0\n"), ("ifnames", "\n"),
                      ("ifnames", "lo0  en0\n"), ("ifnames", "lo0\nen0\n")):
        res = run("forge", tmp_path, host=good_host(tmp_path, **{key: junk}))
        assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_N4_ifconfig_truncated_at_a_block_boundary_is_detected_by_the_ifconfig_l_cross_check(tmp_path):
    blocks = re.split(r"(?m)^(?=[a-z]+\d+: flags=)", GOOD_IFCONFIG)
    lo_only = blocks[1]
    rejects(G.parse_interfaces, lo_only)                                                        # fewer than two blocks (floor)
    trailing = GOOD_IFCONFIG + "en9: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 203.0.113.9 netmask 0xffffff00\n"
    full_names = "lo0 en0 en9\n"
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG, ifnames=full_names))                    # `-a` lost en9: truncation
    assert "ifconfig=MALFORMED" in res["telemetry_complete"]["detail"] and st(res, "network_interfaces_disabled") == G.FAIL_CLOSED
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=trailing, ifnames=full_names)), "network_interfaces_disabled") == G.FAIL


def test_N4_ifnames_unavailable_means_the_interface_listing_cannot_be_cross_checked(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path, ifnames=None))
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and "ifnames=" in res["telemetry_complete"]["detail"]


def test_N4_the_loopback_must_carry_a_127_address():
    t = GOOD_IFCONFIG.replace("inet 127.0.0.1", "inet 10.9.9.9")
    rejects(G.parse_interfaces, t)
    rejects(G.parse_interfaces, GOOD_IFCONFIG.replace("lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST>", "lo0: flags=8049<UP,RUNNING,MULTICAST>"))
    rejects(G.parse_interfaces, GOOD_IFCONFIG + GOOD_IFCONFIG.split("en0")[0].replace("lo0", "en0"))                  # duplicate interface name


def test_N4_a_complete_empty_representation_exists_only_for_sockets_when_terminated():
    assert G.parse_sockets(sock("")) == []
    for fn, hdr in ((G.parse_routes4, "Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\n"),):
        rejects(fn, hdr)                                                                         # a route table can never be legitimately empty (loopback floor)


def test_N4_a_row_joined_onto_the_route_column_header_cannot_swallow_a_default_route():
    for joined in ("Destination Gateway Flags Netif Expiredefault 10.0.0.1 UGSc en0", "Destination Gateway Flags Netif Expire default 10.0.0.1 UGSc en0",
                   "Destination Gateway Flags Netifdefault 10.0.0.1 UGSc en0"):
        rejects(G.parse_routes4, "Routing tables\n\nInternet:\n" + joined + "\n127 127.0.0.1 UCS lo0\n")


def test_N4_an_address_line_joined_onto_a_harmless_line_cannot_be_swallowed():
    base = ("lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n"
            "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\tether aa:bb:cc:dd:ee:ff\n\tinet 192.168.1.5 netmask 0xffffff00\n")
    assert G.interface_violations(G.parse_interfaces(base))
    for joined in (base.replace("ff\n\tinet", "ff\tinet"), base.replace("ff\n\tinet", "ff \tinet"), base.replace("ff\n\tinet", "ffX\tinet")):
        rejects(G.parse_interfaces, joined)
    two = base.replace("\tether aa:bb:cc:dd:ee:ff\n", "\tmedia: autoselect (none)\n") + "en1: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 10.1.1.1 netmask 0xff000000\n"
    rejects(G.parse_interfaces, two.replace("(none)\n\tinet 192.168.1.5 netmask 0xffffff00\nen1", "(none)\n\tinet 192.168.1.5 netmask 0xffffff00\n\tmedia: x en1"))
    rejects(G.parse_interfaces, two.replace("(none)\n", "(none)en9: flags=8863<UP> mtu 1500\n", 1))


def test_N4_the_good_fixtures_still_parse():
    assert G.parse_routes4(GOOD_ROUTES) and G.parse_routes6(GOOD_ROUTES6) and G.parse_interfaces(GOOD_IFCONFIG) and G.parse_ifnames(GOOD_IFNAMES) == ["lo0", "en0"]
    assert G.parse_sockets(GOOD_SOCKETS)


def test_N4_documentation_states_what_the_floors_do_and_do_not_prove():
    d = " ".join(G.__doc__.split())
    assert "WHAT THE PLAUSIBILITY FLOORS PROVE" in d and "do NOT prove that no row was removed from within a well-formed table" in d
    assert "exit status 0 is never treated as completeness" in d


# =============================================================================================================================== N5 absolute tool paths
needs_mac = pytest.mark.skipif(sys.platform != "darwin", reason="fixed macOS system tool locations")


@pytest.fixture
def tool_env(tmp_path, monkeypatch):
    """A private 'system tool' table whose files are owned by the test user (so they fail the root-ownership rule unless a test fakes lstat)."""
    t = tmp_path / "bin"; t.mkdir()
    monkeypatch.setattr(G, "SYSTEM_TOOLS", {"ps": str(t / "ps"), "ifconfig": str(t / "ifconfig")})
    return t


def test_N5_tools_are_resolved_only_through_the_fixed_table_never_through_PATH(monkeypatch):
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["env"] = argv, kw.get("env")
        return SimpleNamespace(returncode=0, stdout="x\n", stderr="")
    monkeypatch.setattr(G, "_resolve_tool", lambda n: G.SYSTEM_TOOLS[n]); monkeypatch.setattr(G.subprocess, "run", fake_run)
    monkeypatch.setenv("PATH", "/tmp/attacker:" + os.environ.get("PATH", ""))
    assert G._run(["ifconfig", "-a"]) == ("OK", "x\n")
    assert os.path.isabs(seen["argv"][0]) and seen["argv"][0] == G.SYSTEM_TOOLS["ifconfig"] and "attacker" not in seen["env"]["PATH"]
    assert seen["env"]["LC_ALL"] == "C" and "HOME" not in seen["env"] and not any(k.startswith("DYLD") for k in seen["env"])


def test_N5_every_telemetry_tool_the_gate_uses_has_an_absolute_fixed_path():
    src = Path(G.__file__).read_text()
    used = set(re.findall(r'(?:get|_run)\(\s*(?:"[a-z_0-9]+",\s*)?\[\s*"([a-z]+)"', src))
    assert {"ps", "ifconfig", "netstat", "sysctl", "diskutil"} <= used <= set(G.SYSTEM_TOOLS)
    assert all(os.path.isabs(p) for p in G.SYSTEM_TOOLS.values())
    assert "shutil.which" not in src and "os.environ[\"PATH\"]" not in src


def test_N5_nonexistent_tool_is_UNSUPPORTED_and_the_source_is_FAIL_CLOSED(tool_env):
    assert G._run(["ps", "-x"]) == ("UNSUPPORTED", None)
    with pytest.raises(G.TelemetryError) as e:
        G._resolve_tool("ps")
    assert e.value.reason == "UNSUPPORTED"
    assert G._run(["notinthetable"]) == ("UNSUPPORTED", None)


def test_N5_a_symlinked_tool_is_refused(tool_env):
    real = tool_env / "real"; real.write_text("#!/bin/sh\n"); real.chmod(0o755)
    (tool_env / "ps").symlink_to(real)
    assert G._run(["ps"]) == ("MALFORMED", None)


def test_N5_a_user_owned_tool_is_refused_even_if_it_is_a_regular_executable(tool_env):
    f = tool_env / "ps"; f.write_text("#!/bin/sh\necho INJECTED\n"); f.chmod(0o755)
    status, out = G._run(["ps"])
    assert status == "MALFORMED" and out is None


def _fake_lstat(monkeypatch, target, **fields):
    real = os.lstat

    def lstat(p, *a, **k):
        r = real(p, *a, **k)
        if str(p) != target:
            return r
        vals = list(r)
        for i, key in enumerate(("st_mode", "st_ino", "st_dev", "st_nlink", "st_uid", "st_gid", "st_size")):
            if key in fields:
                vals[i] = fields[key]
        return os.stat_result(vals)
    monkeypatch.setattr(G.os, "lstat", lstat)


@pytest.mark.parametrize("mode", [0o100775, 0o100757, 0o100777, 0o100644, 0o104755 | 0o002])
def test_N5_unsafe_permissions_are_refused_where_simulated(tool_env, monkeypatch, mode):
    f = tool_env / "ps"; f.write_text("x")
    _fake_lstat(monkeypatch, str(f), st_uid=0, st_mode=mode)
    monkeypatch.setattr(G, "_resolve_tool", G._resolve_tool)
    if mode & 0o111 and not mode & 0o022:
        pytest.skip("mode is acceptable")
    with pytest.raises(G.TelemetryError):
        G._resolve_tool("ps")


def test_N5_a_root_owned_non_writable_executable_in_root_owned_directories_is_accepted_when_simulated(tool_env, monkeypatch):
    f = tool_env / "ps"; f.write_text("x")
    real = os.lstat

    def lstat(p, *a, **k):
        r = real(p, *a, **k)
        vals = list(r); vals[4] = 0
        if str(p) == str(f):
            vals[0] = 0o100555
        elif stat.S_ISDIR(r.st_mode):
            vals[0] = stat.S_IFDIR | 0o755
        return os.stat_result(vals)
    monkeypatch.setattr(G.os, "lstat", lstat)
    assert G._resolve_tool("ps") == str(f)


def test_N5_a_group_writable_ancestor_directory_is_refused_when_simulated(tool_env, monkeypatch):
    f = tool_env / "ps"; f.write_text("x")
    real = os.lstat

    def lstat(p, *a, **k):
        r = real(p, *a, **k)
        vals = list(r); vals[4] = 0
        vals[0] = 0o100555 if str(p) == str(f) else stat.S_IFDIR | 0o775
        return os.stat_result(vals)
    monkeypatch.setattr(G.os, "lstat", lstat)
    with pytest.raises(G.TelemetryError):
        G._resolve_tool("ps")


@needs_mac
def test_N5_a_malicious_fake_binary_earlier_in_PATH_is_never_executed(tmp_path, monkeypatch):
    evil = tmp_path / "evil"; evil.mkdir()
    for n in ("ifconfig", "netstat", "ps", "sysctl", "diskutil"):
        (evil / n).write_text("#!/bin/sh\necho INJECTED_MARKER\n"); (evil / n).chmod(0o755)
    monkeypatch.setenv("PATH", f"{evil}:{os.environ['PATH']}")
    status, out = G._run(["ifconfig", "-l"])
    assert status == "OK" and "INJECTED_MARKER" not in out and "lo0" in out
    host = G.collect_host()
    assert all("INJECTED_MARKER" not in str(host[k]) for k in ("ifconfig", "ifnames", "routes4", "sockets", "boot_id") if host[k] is not None)


@needs_mac
def test_N5_an_empty_or_missing_PATH_does_not_affect_the_real_tools(monkeypatch):
    for val in ("", ":", None):
        if val is None:
            monkeypatch.delenv("PATH", raising=False)
        else:
            monkeypatch.setenv("PATH", val)
        status, out = G._run(["ifconfig", "-l"])
        assert status == "OK" and "lo0" in out


@needs_mac
def test_N5_the_real_system_tools_satisfy_the_trust_rules():
    for name in G.SYSTEM_TOOLS:
        assert os.path.isabs(G._resolve_tool(name))


# =============================================================================================================================== N6 walker
def _tree(tmp_path):
    root = tmp_path / "w"; (root / "sub" / "deeper").mkdir(parents=True)
    (root / "sub" / "deeper" / "f.txt").write_text("deep"); (root / "sub" / "g.txt").write_text("g"); (root / "top.txt").write_text("t")
    return root


def _swap_on_open(monkeypatch, target_name, action, want_dir=True):
    real = G._openat
    state = {"done": False}

    def hook(path, flags, *a, **k):
        is_dir = bool(flags & os.O_DIRECTORY)
        if not state["done"] and k.get("dir_fd") is not None and path == target_name and is_dir == want_dir:
            state["done"] = True
            action()
        return real(path, flags, *a, **k)
    monkeypatch.setattr(G, "_openat", hook)
    return state


def test_N6_the_clean_tree_walks_with_zero_errors_and_lists_everything(tmp_path):
    entries, errors = G.walk_strict(_tree(tmp_path))
    assert errors == 0 and {r for r, _ in entries} == {"sub", "sub/deeper", "sub/deeper/f.txt", "sub/g.txt", "top.txt"}


def test_N6_no_child_is_ever_resolved_through_a_pathname(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    real_scandir, real_lstat = os.scandir, os.lstat
    seen = []

    def scandir(p=".", *a, **k):
        seen.append(type(p))
        if not isinstance(p, int):
            raise AssertionError("pathname listing used")
        return real_scandir(p)
    monkeypatch.setattr(G.os, "scandir", scandir)
    entries, errors = G.walk_strict(root)
    assert errors == 0 and len(entries) == 5 and set(seen) == {int}


def test_N6_a_directory_swapped_for_a_symlink_after_it_was_listed_is_detected(tmp_path, monkeypatch):
    root = _tree(tmp_path); other = tmp_path / "other"; other.mkdir(); (other / "evil.txt").write_text("evil")

    def swap():
        os.rename(root / "sub", tmp_path / "sub_away"); os.symlink(other, root / "sub")
    st_ = _swap_on_open(monkeypatch, "sub", swap)
    entries, errors = G.walk_strict(root)
    assert st_["done"] and errors >= 1 and "sub/evil.txt" not in {r for r, _ in entries}


def test_N6_a_directory_replaced_by_a_different_directory_is_detected_by_device_and_inode(tmp_path, monkeypatch):
    root = _tree(tmp_path); repl = tmp_path / "repl"; (repl / "deeper").mkdir(parents=True); (repl / "planted.txt").write_text("p")

    def swap():
        os.rename(root / "sub", tmp_path / "sub_away"); os.rename(repl, root / "sub")
    st_ = _swap_on_open(monkeypatch, "sub", swap)
    entries, errors = G.walk_strict(root)
    assert st_["done"] and errors >= 1 and "sub/planted.txt" not in {r for r, _ in entries}


def test_N6_a_nested_directory_swap_is_detected(tmp_path, monkeypatch):
    root = _tree(tmp_path); other = tmp_path / "other"; other.mkdir()

    def swap():
        os.rename(root / "sub" / "deeper", tmp_path / "deeper_away"); os.symlink(other, root / "sub" / "deeper")
    st_ = _swap_on_open(monkeypatch, "deeper", swap)
    _, errors = G.walk_strict(root)
    assert st_["done"] and errors >= 1


def test_N6_a_vanished_directory_is_detected(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    st_ = _swap_on_open(monkeypatch, "sub", lambda: __import__("shutil").rmtree(root / "sub"))
    _, errors = G.walk_strict(root)
    assert st_["done"] and errors >= 1


@nonroot
def test_N6_permissions_changed_during_traversal_are_detected(tmp_path, monkeypatch):
    root = _tree(tmp_path)
    st_ = _swap_on_open(monkeypatch, "sub", lambda: os.chmod(root / "sub", 0))
    try:
        _, errors = G.walk_strict(root)
    finally:
        os.chmod(root / "sub", 0o700)
    assert st_["done"] and errors >= 1


def test_N6_a_root_that_is_a_symlink_or_not_a_directory_is_refused(tmp_path):
    root = _tree(tmp_path); link = tmp_path / "ln"; link.symlink_to(root)
    assert G.walk_strict(link)[1] >= 1
    assert G.walk_strict(root / "top.txt")[1] >= 1
    assert G.walk_strict(tmp_path / "nope")[1] >= 1


def test_N6_the_root_swapped_for_a_symlink_before_the_open_is_refused(tmp_path, monkeypatch):
    root = _tree(tmp_path); other = tmp_path / "o"; other.mkdir()
    real = G._openat
    state = {"n": 0}

    def hook(path, flags, *a, **k):
        if state["n"] == 0 and k.get("dir_fd") is None:
            state["n"] = 1
            os.rename(root, tmp_path / "w_away"); os.symlink(other, root)
        return real(path, flags, *a, **k)
    monkeypatch.setattr(G, "_openat", hook)
    assert G.walk_strict(root)[1] >= 1


def test_N6_a_file_swapped_after_listing_is_not_hashed_as_the_listed_object(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    target = cfg["code_root"] / "orca" / "eval" / "genesis_v2" / "spec.py"
    repl = tmp_path / "repl.py"; repl.write_text("# evil replacement\n")

    def swap():
        os.replace(repl, target)                                                             # a new inode, created BEFORE the swap so inode reuse cannot mask it
    st_ = _swap_on_open(monkeypatch, "spec.py", swap, want_dir=False)
    res = run("forge", tmp_path, cfg=cfg)
    assert st_["done"] and st(res, "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_N6_a_file_modified_in_place_between_the_listing_and_the_open_is_not_accepted(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    target = cfg["code_root"] / "orca" / "__init__.py"

    def modify():
        with open(target, "a") as f:
            f.write("# appended after the listing\n")                                          # same inode, different size/mtime
    st_ = _swap_on_open(monkeypatch, "__init__.py", modify, want_dir=False)
    res = run("forge", tmp_path, cfg=cfg)
    assert st_["done"] and st(res, "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_N6_excessive_depth_is_an_error_not_a_crash(tmp_path):
    p = tmp_path / "d"
    cur = p
    for i in range(G.MAX_WALK_DEPTH + 3):
        cur = cur / "x"
    try:
        cur.mkdir(parents=True)
    except OSError:
        pytest.skip("filesystem path-length limit")
    _, errors = G.walk_strict(p)
    assert errors >= 1


def test_N6_the_documented_residual_is_stated():
    d = " ".join(G.__doc__.split())
    assert "ancestors of the root are resolved normally" in d and "point-in-time" in d
    assert "descriptor-relative" in d


# =============================================================================================================================== N7 documentation
OVERCLAIMS = ("produce plausible output, and parse STRICTLY", "is never ignored", "never ignored", "completely secure", "proves isolation", "guarantees")


def test_N7_the_gate_docstring_has_no_overclaims_and_states_every_scope_class():
    d = " ".join(G.__doc__.split())
    for bad in OVERCLAIMS:
        assert bad not in d, bad
    for cls in ("ENFORCED", "ADVISORY", "PROCEDURAL", "UNPROVEN", "NOT exhaustive", "NOT continuous", "does NOT prove that well-formed telemetry is complete"):
        assert cls in d, cls


def test_N7_the_docstring_check_count_matches_the_code(tmp_path):
    assert len(run("forge", tmp_path)) == 16 and "sixteen checks" in G.__doc__.replace("\n", " ").replace("  ", " ")


def test_N7_no_infrastructure_document_repeats_the_withdrawn_claims():
    for p in INFRA.glob("*.md"):
        t = " ".join(p.read_text().split())
        for bad in ("produce plausible output, and parse STRICTLY", "unrecognized syntax inside a security-relevant telemetry source is never ignored"):
            assert bad not in t, (p.name, bad)


def test_N7_the_N1_N10_remediation_document_exists_and_keeps_the_boundaries():
    doc = (INFRA / "GENESIS_V2_TIER0S_N1_N10_REMEDIATION.md").read_text()
    for must in ("N1", "N2", "N3", "N4", "N5", "N6", "N7", "N8", "N9", "N10", "READY_FOR_FINAL_INDEPENDENT_REAUDIT", "NOT_AUTHORIZED", "no assurance credit"):
        assert must in doc, must
    assert "TIER0_S_FULLY_ACCEPTED" not in doc


def test_N7_the_design_doc_does_not_claim_more_than_the_gate_enforces():
    t = " ".join((INFRA / "GENESIS_V2_TIER0S_SEQUENTIAL_SOVEREIGN_ISOLATION.md").read_text().split())
    assert "GATE_CHECKED" in t and "not proof of physical disconnection" in t


# =============================================================================================================================== N8 deny configuration
UU = "ABCD0000-1111-2222-3333-444455556666"


def _deny(tmp_path, **kw):
    base = dict(deny_paths=[], deny_volumes=[], deny_volume_uuids=[])
    base.update(kw)
    res = run("forge", tmp_path, host=good_host(tmp_path), **base)
    return res["other_role_storage_unavailable"]


@pytest.mark.parametrize("bad", ["", " ", "x", "ABCD0000-1111-2222-3333-44445555666", "ABCD0000-1111-2222-3333-4444555566666", "ABCD00001111222233334444555566666",
                                 UU + "\n", " " + UU, UU + " ", "GBCD0000-1111-2222-3333-444455556666", None, 5, UU.replace("-", ""), "{" + UU + "}", ["x"]])
def test_N8_a_typod_empty_or_malformed_deny_uuid_is_FAIL_CLOSED_not_silently_inert(tmp_path, bad):
    r = _deny(tmp_path, deny_volume_uuids=[bad])
    assert r["status"] == G.FAIL_CLOSED and "malformed deny configuration" in r["detail"]


def test_N8_duplicate_uuids_are_refused_even_with_different_case(tmp_path):
    r = _deny(tmp_path, deny_volume_uuids=[UU, UU.lower()])
    assert r["status"] == G.FAIL_CLOSED and "duplicate deny volume UUID" in r["detail"]


@pytest.mark.parametrize("bad", ["", "   ", "\t", " lead", "trail ", "zero​width", "bom﻿name", "ctrl\x01name", "bidi‮name", "Wіtness",       # Cyrillic i
                                 "Ꮃitness", "Αlpha", None, 5, b"x"])
def test_N8_unsafe_or_confusable_labels_are_refused_in_configuration(tmp_path, bad):
    r = _deny(tmp_path, deny_volumes=[bad])
    assert r["status"] == G.FAIL_CLOSED


def test_N8_duplicate_labels_after_normalization_are_refused(tmp_path):
    assert _deny(tmp_path, deny_volumes=["WitnessVault", "witnessvault"])["status"] == G.FAIL_CLOSED
    assert _deny(tmp_path, deny_volumes=["WitnessVault", "WitnessVault 2"])["status"] == G.FAIL_CLOSED
    assert _deny(tmp_path, deny_volumes=["ＷitnessVault", "WitnessVault"])["status"] == G.FAIL_CLOSED               # full-width W folds under NFKC


def test_N8_deny_lists_must_be_lists_not_strings(tmp_path):
    for kw in ({"deny_volume_uuids": UU}, {"deny_volumes": "WitnessVault"}, {"deny_paths": "/tmp/x"}, {"deny_volumes": 5}, {"deny_volume_uuids": {UU}}):
        assert _deny(tmp_path, **kw)["status"] == G.FAIL_CLOSED


def test_N8_duplicate_and_malformed_paths_are_refused(tmp_path):
    p = str(tmp_path / "x")
    assert _deny(tmp_path, deny_paths=[p, p + "/"])["status"] == G.FAIL_CLOSED
    assert _deny(tmp_path, deny_paths=["rel"])["status"] == G.FAIL_CLOSED


@pytest.mark.parametrize("seen", ["WitnessVаult", "Witness​Vault", "ＷｉｔｎｅｓｓＶａｕｌｔ", "WITNESSVAULT", "WitnessVault (2)", "WitnessVault-2",
                                  "witnessvault  3"])
def test_N8_label_spoofing_variants_are_detected_or_force_FAIL_CLOSED(tmp_path, seen):
    res = run("forge", tmp_path, host=good_host(tmp_path, volumes=["Macintosh HD", seen]), deny_paths=[], deny_volumes=["WitnessVault"])
    assert st(res, "other_role_storage_unavailable") in (G.FAIL, G.FAIL_CLOSED) and not G.gate_passes(res)


def test_N8_label_only_configuration_is_explicitly_identified_as_weaker(tmp_path):
    r = _deny(tmp_path, deny_volumes=["WitnessVault"])
    assert r["status"] == G.PASS and "LABEL_ONLY" in r["detail"] and "spoofable" in r["detail"]
    r2 = _deny(tmp_path, deny_volumes=["WitnessVault"], deny_volume_uuids=[UU])
    assert "LABEL_ONLY" not in r2["detail"]
    assert "LABEL_ONLY" not in _deny(tmp_path, deny_volume_uuids=[UU])["detail"]


def test_N8_UUID_matching_still_works_and_beats_a_spoofed_label(tmp_path):
    disks = list(GOOD_DISKS) + [{"name": "Innocent", "uuid": UU, "dev": "disk9s1", "mount": ""}]
    res = run("forge", tmp_path, host=good_host(tmp_path, disks=disks), deny_paths=[], deny_volume_uuids=[UU.lower()])
    assert st(res, "other_role_storage_unavailable") == G.FAIL


def test_N8_a_well_formed_but_wrong_uuid_cannot_be_detected_and_the_docs_say_so():
    assert "A well-formed UUID that is simply wrong matches nothing and cannot be detected" in " ".join(G.__doc__.split())
    assert "physical detachment" in " ".join(G.__doc__.split()).lower() or "PHYSICAL DETACHMENT" in G.__doc__


def test_N8_the_CLI_rejects_an_empty_UUID_argument(tmp_path):
    cfg = make_cfg(tmp_path)
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge", "--state-dir", str(cfg["state_dir"]),
                        "--deny-volume-uuid", ""], capture_output=True, text=True, timeout=120)
    assert p.returncode == 1 and "GATE_PASSES" not in p.stdout


def test_N8_canonical_comparison_form_is_deterministic():
    assert G.canon_volume_name("ＷitnessVault 12") == G.canon_volume_name("witnessvault") == G.canon_volume_name("Witness​Vault (3)") == "witnessvault"
    assert G.canon_volume_name("Backup") != G.canon_volume_name("Backups")


# =============================================================================================================================== N9 manifest pin workflow
def _code_root(tmp_path):
    return make_cfg(tmp_path)["code_root"]


def _gate(*args, **kw):
    return subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), *args], capture_output=True, **kw, timeout=120)


def test_N9_stdout_redirect_produces_a_file_whose_digest_IS_the_printed_pin(tmp_path):
    code = _code_root(tmp_path)
    p = _gate("build-manifest", "--code-root", str(code))
    assert p.returncode == 0
    redirected = tmp_path / "redirected.json"; redirected.write_bytes(p.stdout)                              # exactly what `> file` does
    printed = re.search(rb"MANIFEST_SHA256 ([0-9a-f]{64})\n", p.stderr).group(1).decode()
    assert hashlib.sha256(redirected.read_bytes()).hexdigest() == printed == hashlib.sha256(p.stdout).hexdigest()
    assert p.stdout.endswith(b"\n") and not p.stdout.endswith(b"\n\n")
    m, why = G.load_code_manifest(redirected, printed)
    assert why is None and set(m["files"]) == set(G.ROLE_CODE_ALLOWLIST)


def test_N9_out_and_pin_out_write_the_same_canonical_bytes_and_the_pin_reads_back(tmp_path):
    code = _code_root(tmp_path); out, pin = tmp_path / "m.json", tmp_path / "m.pin"
    p = _gate("build-manifest", "--code-root", str(code), "--out", str(out), "--pin-out", str(pin), text=True)
    assert p.returncode == 0
    printed = p.stdout.strip().split()[-1]
    assert p.stdout == f"MANIFEST_SHA256 {printed}\n"
    assert hashlib.sha256(out.read_bytes()).hexdigest() == printed
    assert pin.read_bytes() == (printed + "\n").encode() and re.fullmatch(r"[0-9a-f]{64}\n", pin.read_text())
    assert G.load_code_manifest(out, pin.read_text().strip())[1] is None
    stdout_form = _gate("build-manifest", "--code-root", str(code)).stdout
    assert stdout_form == out.read_bytes()                                                                    # the two output modes are byte-identical


def test_N9_the_in_process_canonical_bytes_match_the_CLI(tmp_path):
    code = _code_root(tmp_path)
    assert G.canonical_manifest_bytes(G.build_code_manifest(code)) == _gate("build-manifest", "--code-root", str(code)).stdout


def test_N9_the_full_gate_accepts_the_cli_generated_manifest_and_pin(tmp_path):
    cfg = make_cfg(tmp_path); out = tmp_path / "cli_manifest.json"
    pin = _gate("build-manifest", "--code-root", str(cfg["code_root"]), "--out", str(out), text=True).stdout.split()[-1]
    res = run("forge", tmp_path, cfg=cfg, code_manifest=out, code_manifest_sha256=pin)
    assert st(res, "role_code_root_matches_manifest") == G.PASS


@pytest.mark.parametrize("mut", [lambda h: h + "\n", lambda h: " " + h, lambda h: h + " ", lambda h: h[:-1], lambda h: h + "0", lambda h: "\t" + h, lambda h: h[:32] + " " + h[32:],
                                 lambda h: "0x" + h, lambda h: h.replace(h[0], "g", 1), lambda h: ""])
def test_N9_pin_validation_is_not_weakened_to_tolerate_ambiguous_whitespace_or_garbage(tmp_path, mut):
    cfg = make_cfg(tmp_path)
    m, why = G.load_code_manifest(cfg["code_manifest"], mut(cfg["code_manifest_sha256"]))
    assert m is None and why


def test_N9_outputs_are_exclusive_creates_and_refuse_to_overwrite_or_follow_symlinks(tmp_path):
    code = _code_root(tmp_path); out = tmp_path / "exists.json"; out.write_text("PRECIOUS")
    p = _gate("build-manifest", "--code-root", str(code), "--out", str(out), text=True)
    assert p.returncode == 1 and "FAIL_CLOSED" in p.stdout and out.read_text() == "PRECIOUS"
    victim = tmp_path / "victim"; victim.write_text("V"); link = tmp_path / "ln.json"; link.symlink_to(victim)
    p = _gate("build-manifest", "--code-root", str(code), "--out", str(link), text=True)
    assert p.returncode == 1 and victim.read_text() == "V"


def test_N9_a_code_root_anomaly_produces_no_output_and_no_pin(tmp_path):
    code = _code_root(tmp_path); (code / "l").symlink_to(tmp_path)
    out = tmp_path / "o.json"
    p = _gate("build-manifest", "--code-root", str(code), "--out", str(out), text=True)
    assert p.returncode == 1 and not out.exists() and "MANIFEST_SHA256" not in p.stdout


# =============================================================================================================================== N10 validator + interlock
def _bundle_module():
    s = importlib.util.spec_from_file_location("tier0a_bundle", ROOT / "scripts" / "genesis_v2_tier0a_transfer_bundle.py")
    m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
    return m


B = _bundle_module()


@nonroot
def test_N10_an_unreadable_corpus_directory_is_a_structured_INACCESSIBLE_result_not_an_exception(bundle):
    b = bundle[0]
    cdir = next(p for p in b.iterdir() if p.is_dir()); os.chmod(cdir, 0)
    try:
        problems = B.validate(b)                                                                           # must not raise PermissionError
        r = B.validate_result(b)
    finally:
        os.chmod(cdir, 0o700)
    assert problems and r["status"] == "INACCESSIBLE" and any(p.startswith(B.INACCESSIBLE) for p in r["problems"])
    assert B.classify(problems) == "INACCESSIBLE"


@nonroot
def test_N10_staging_an_inaccessible_bundle_raises_a_controlled_ValueError(bundle, tmp_path):
    b = bundle[0]; cdir = next(p for p in b.iterdir() if p.is_dir()); os.chmod(cdir, 0)
    try:
        with pytest.raises(ValueError):
            B.validate_and_stage(b, tmp_path)
    finally:
        os.chmod(cdir, 0o700)


def test_N10_error_classes_are_distinguished(bundle, tmp_path):
    b = bundle[0]
    assert B.validate_result(b) == {"status": "VALID", "problems": []}
    assert B.classify(["x: expected encrypted-artifact magic prefix missing"]) == "INVALID"
    assert B.classify(["x: malformed header"]) == "MALFORMED"
    assert B.classify(["MANIFEST.json must be strict JSON (no duplicate keys) mapping relative paths to sha256 hex"]) == "MALFORMED"
    assert B.classify([B.INACCESSIBLE + "unreadable", "x: malformed header"]) == "INACCESSIBLE"
    assert B.validate_result(tmp_path / "missing")["status"] == "INVALID"                                    # not a plain directory: invalid, and still no exception
    (b / B.MANIFEST).write_text("{not json")
    assert B.validate_result(b)["status"] == "MALFORMED"


def test_N10_an_internal_programming_error_is_not_swallowed_as_a_validation_result(bundle, monkeypatch):
    monkeypatch.setattr(B, "_header", lambda blob: (_ for _ in ()).throw(RuntimeError("programmer bug")))
    with pytest.raises(RuntimeError):
        B.validate(bundle[0])


def test_N10_a_missing_bundle_directory_is_reported_not_raised(tmp_path):
    assert B.validate(tmp_path / "nope")


def _state(tmp_path):
    d = tmp_path / "ilock"; G.init_state(d)
    return d


def test_N10_concurrent_appends_from_many_processes_never_corrupt_the_chain(tmp_path):
    d = _state(tmp_path)
    script = ("import importlib.util,sys;s=importlib.util.spec_from_file_location('g','scripts/genesis_v2_tier0s_phase_gate.py');m=importlib.util.module_from_spec(s);"
              "s.loader.exec_module(m);m.LOCK_TIMEOUT=60.0\nfor i in range(4):\n    m.append_receipt(sys.argv[1],'forge',sys.argv[2])\n")
    procs = [subprocess.Popen([sys.executable, "-c", script, str(d), BOOT_A], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(8)]
    outs = [p.communicate(timeout=180) for p in procs]
    assert all(p.returncode == 0 for p in procs), [o[1][-300:] for o in outs]
    problems, recs = G.verify_state(d)
    assert problems == [] and [r["seq"] for r in recs] == list(range(1, 33))


def test_N10_a_writer_that_cannot_get_the_lock_fails_closed_and_changes_nothing(tmp_path, monkeypatch):
    d = _state(tmp_path); before = (d / "receipts.jsonl").read_bytes()
    holder = G._lock_dir(d, exclusive=True)
    try:
        monkeypatch.setattr(G, "LOCK_TIMEOUT", 0.2)
        with pytest.raises(PermissionError):
            G.append_receipt(d, "forge", BOOT_A)
        problems, _ = G.verify_state(d)
        assert problems and "lock" in problems[0]                                                         # a reader cannot observe a half-held writer: it fails closed
    finally:
        os.close(holder)
    assert (d / "receipts.jsonl").read_bytes() == before
    G.append_receipt(d, "forge", BOOT_A)                                                                  # released lock: works


def test_N10_a_lock_held_by_a_killed_process_is_not_stale(tmp_path):
    d = _state(tmp_path)
    code = ("import importlib.util,sys,time;s=importlib.util.spec_from_file_location('g','scripts/genesis_v2_tier0s_phase_gate.py');m=importlib.util.module_from_spec(s);"
            "s.loader.exec_module(m);fd=m._lock_dir(sys.argv[1],exclusive=True);print('LOCKED',flush=True);time.sleep(600)")
    p = subprocess.Popen([sys.executable, "-c", code, str(d)], cwd=ROOT, stdout=subprocess.PIPE, text=True)
    try:
        assert p.stdout.readline().strip() == "LOCKED"
        G.LOCK_TIMEOUT, saved = 0.2, G.LOCK_TIMEOUT
        try:
            with pytest.raises(PermissionError):
                G.append_receipt(d, "forge", BOOT_A)
        finally:
            G.LOCK_TIMEOUT = saved
    finally:
        p.kill(); p.wait()
    assert G.append_receipt(d, "forge", BOOT_A)["seq"] == 1                                               # the kernel released it with the process


def test_N10_lock_errors_other_than_contention_fail_closed(tmp_path, monkeypatch):
    d = _state(tmp_path)
    monkeypatch.setattr(G.fcntl, "flock", lambda fd, op: (_ for _ in ()).throw(OSError(errno.ENOTSUP, "no locking here")))
    with pytest.raises(PermissionError):
        G.append_receipt(d, "forge", BOOT_A)
    assert G.verify_state(d)[0]
    monkeypatch.undo()
    with pytest.raises(PermissionError):
        G.append_receipt(tmp_path / "does_not_exist", "forge", BOOT_A)


def test_N10_the_lock_adds_no_file_to_the_interlock_directory(tmp_path):
    d = _state(tmp_path)
    G.append_receipt(d, "forge", BOOT_A)
    assert set(os.listdir(d)) == G.STATE_FILES and G.verify_state(d)[0] == []


def test_N10_a_crash_between_receipt_and_HEAD_fails_closed_and_is_documented(tmp_path, monkeypatch):
    d = _state(tmp_path)
    monkeypatch.setattr(G.os, "replace", lambda a, b, **k: (_ for _ in ()).throw(OSError("simulated crash")))
    with pytest.raises(OSError):
        G.append_receipt(d, "forge", BOOT_A)
    monkeypatch.undo()
    assert G.verify_state(d)[0]                                                                            # unverifiable until the owner re-initializes
    d_ = " ".join(G.__doc__.split())
    assert "receipts and HEAD disagree" in d_ and "FAILS CLOSED until the owner creates a new interlock directory" in d_ and "no stale lock" in d_


def test_N10_the_interlock_still_earns_no_security_credit():
    d = " ".join(G.__doc__.split())
    assert "earns NO acceptance credit" in d and "NOT a security isolation boundary" in d


# =============================================================================================================================== exhaustive single-character sweeps (N1/N4)
_SWEEP_CHARS = ["", " ", "\t", "\n", "\r", "X", ".", "0", "*", ":", "\x00", "\x0b", "\x0c", " ", "\x85"]
_SWEEP_IF = ("lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\nen0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n"
             "\tether aa:bb:cc:dd:ee:ff\n\tmedia: autoselect (none)\n\tinet 192.168.1.5 netmask 0xffffff00\n")
_SWEEPS = {
    "sockets": (G.parse_sockets, SOCK_HEAD + OK_ROW + EXT_TCP + EXT_UDP + SOCK_TAIL, lambda r: sum(1 for x in r if x[2]) >= 2),
    "routes4": (G.parse_routes4, "Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\ndefault 10.0.0.1 UGSc en0\n127 127.0.0.1 UCS lo0\n",
                lambda r: any(x[0].lower() == "default" for x in r)),
    "routes6": (G.parse_routes6, "Routing tables\n\nInternet6:\nDestination Gateway Flags Netif Expire\ndefault fe80::1%en0 UGcg en0\n::1 ::1 UHL lo0\n",
                lambda r: any(x[0].lower() == "default" for x in r)),
    "ifconfig": (G.parse_interfaces, _SWEEP_IF, lambda r: bool(G.interface_violations(r)) or [i["name"] for i in r] != ["lo0", "en0"]),      # a renamed interface is caught by the `ifconfig -l` cross-check
}


@pytest.mark.parametrize("name", sorted(_SWEEPS))
def test_N1_N4_EXHAUSTIVE_every_single_character_deletion_replacement_or_insertion_either_raises_or_keeps_the_violation(name):
    parse, base, still_violates = _SWEEPS[name]
    assert still_violates(parse(base))
    silent = []
    for i in range(len(base) + 1):
        for ch in _SWEEP_CHARS:
            for mode in ("del", "rep", "ins"):
                if (mode == "del" and ch) or (mode in ("del", "rep") and i >= len(base)):
                    continue
                m = base[:i] + ch + base[i + (0 if mode == "ins" else 1):]
                if m == base:
                    continue
                try:
                    rows = parse(m)
                except G.TelemetryError:
                    continue
                if not still_violates(rows):
                    silent.append((mode, ch, m[max(0, i - 20):i + 20]))
    assert silent == [], silent[:3]


def test_N4_documented_residual_whole_row_deletion_is_not_detectable():
    """Honest limit: removing a COMPLETE, well-formed row leaves a well-formed table. The documentation says so rather than the code pretending otherwise."""
    rows = G.parse_routes4("Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\n127 127.0.0.1 UCS lo0\n")          # the default row simply absent
    assert G.default_routes(rows) == []
    assert "do NOT prove that no row was removed from within a well-formed table" in " ".join(G.__doc__.split())


def test_N7_the_N1_N10_matrix_maps_every_finding_to_regression_tests_that_exist():
    txt = (INFRA / "GENESIS_V2_TIER0S_N1_N10_REMEDIATION.md").read_text()
    sources = (ROOT / "tests" / "test_genesis_v2_tier0s_n1_n10.py").read_text()
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (N\d+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`(test_[^`]+)`", line)
        seen[m.group(1)] = names
        assert names, f"{m.group(1)} has no regression tests"
        for t in names:
            assert re.search(rf"def {re.escape(t)}\b", sources), f"{m.group(1)}: {t} does not exist"
    assert set(seen) == {f"N{i}" for i in range(1, 11)}


def test_N3_the_gate_never_ends_in_a_traceback_an_unexpected_exception_is_a_refusal(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(G, "collect_host", lambda: good_host(tmp_path))
    monkeypatch.setattr(G, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("unexpected bug SENTINEL_DETAIL")))
    rc = G.main(["gate", "check", "--role", "forge"])
    out = capsys.readouterr().out
    assert rc == 1 and "FAIL_CLOSED internal error (RuntimeError)" in out and "GATE_FAILS" in out and "GATE_PASSES" not in out and "SENTINEL_DETAIL" not in out

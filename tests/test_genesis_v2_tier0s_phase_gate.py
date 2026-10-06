"""Tier0-S (Sequential Sovereign Isolation) phase gate v3 + design-doc consistency -- SYNTHETIC. No real boot/reboot is exercised; host telemetry and boot
sessions are injected. Proves the gate's fail-closed LOGIC only. It is a one-shot, advisory, software-level guard against accidental mixing; NOT evidence of a
second boot environment, separate encrypted storage, continuous enforcement, or any protection against a malicious owner/root.

Naming: test_AUDITn_* = original audit findings (kept as regression tests); test_Qn_* = re-audit findings Q1-Q10."""
import hashlib
import importlib.util
import json
import os
import random
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("tier0s_gate", ROOT / "scripts" / "genesis_v2_tier0s_phase_gate.py")
G = importlib.util.module_from_spec(_s)
_s.loader.exec_module(G)
INFRA = ROOT / "docs/orneur/phase-21/infrastructure"
BOOT_A, BOOT_B = "11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555"
nonroot = pytest.mark.skipif(os.geteuid() == 0, reason="permission-denied simulation needs a non-root user")

GOOD_IFCONFIG = ("lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\toptions=1203<RXCSUM,TXCSUM,TXSTATUS,SW_TIMESTAMP>\n\tinet 127.0.0.1 netmask 0xff000000\n"
                 "\tinet6 ::1 prefixlen 128\n\tinet6 fe80::1%lo0 prefixlen 64 scopeid 0x1\n\tnd6 options=201<PERFORMNUD,DAD>\n"
                 "en0: flags=8863<UP,BROADCAST,SMART,RUNNING,SIMPLEX,MULTICAST> mtu 1500\n\toptions=6460<TSO4,TSO6,CHANNEL_IO,PARTIAL_CSUM,ZEROINVERT_CSUM>\n"
                 "\tether aa:bb:cc:dd:ee:ff\n\tnd6 options=201<PERFORMNUD,DAD>\n\tmedia: autoselect (none)\n\tstatus: inactive\n")
GOOD_ROUTES = "Routing tables\n\nInternet:\nDestination        Gateway            Flags               Netif Expire\n127                127.0.0.1          UCS                   lo0\n"
GOOD_ROUTES6 = ("Routing tables\n\nInternet6:\nDestination                             Gateway                                 Flags               Netif Expire\n"
                "::1                                     ::1                                     UHL                   lo0\n")
SOCK_TAIL = "\nActive Multipath Internet connections\nProto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n"
GOOD_IFNAMES = "lo0 en0\n"
GOOD_DISKS = [{"name": "Macintosh HD", "uuid": "", "dev": "disk3s1", "mount": "/"}]
GOOD_SOCKETS = ("Active Internet connections (including servers)\nProto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n"
                "tcp4       0      0  127.0.0.1.8080         *.*                    LISTEN\nudp4       0      0  *.5353                 *.*                    \n"
                "icm4       0      0  *.*                    *.*                    \n\nActive Multipath Internet connections\n"
                "Proto/ID  Flags      Local Address          Foreign Address        (state)\n\nActive LOCAL (UNIX) domain sockets\nAddress Type Recv-Q\n")


@pytest.fixture
def fake_tools(monkeypatch):
    """Lets tests that stub subprocess.run exercise collect_host on any OS (tool-path trust has its own N5 tests)."""
    monkeypatch.setattr(G, "_resolve_tool", lambda name: "/sys/" + name)


def good_host(tmp, **over):
    home = tmp / "home"; home.mkdir(exist_ok=True)
    h = {"processes": ["/sbin/launchd"] + [f"/usr/bin/proc{i}" for i in range(12)], "cmdlines": ["/sbin/launchd"] + [f"/usr/bin/proc{i} --flag" for i in range(12)],
         "ifconfig": GOOD_IFCONFIG, "ifnames": GOOD_IFNAMES, "routes4": GOOD_ROUTES, "routes6": GOOD_ROUTES6, "sockets": GOOD_SOCKETS, "boot_id": BOOT_A,
         "volumes": ["Macintosh HD"], "disks": list(GOOD_DISKS),
         "home": home, "env": {}, "runtime_sockets_abs": ()}                       # absolute socket paths injected empty => hermetic
    h.update(over)
    if "ifnames" not in over and isinstance(h.get("ifconfig"), str):         # keep `ifconfig -l` consistent with the (possibly modified) `ifconfig -a` fixture
        names = re.findall(r"^([A-Za-z][A-Za-z0-9_.-]*): flags=", h["ifconfig"], re.M)
        if names:
            h["ifnames"] = " ".join(names) + "\n"
    derive_independent(h, over)
    return h


def derive_independent(h, over):
    """Keep the INDEPENDENT sources (libc interface inventory, if_nameindex, kernel PCB counters) consistent with the possibly modified command fixtures, unless a
    test overrides them explicitly. Fixtures that cannot be parsed are left alone: they fail on their own."""
    try:
        ifs = G.parse_interfaces(h["ifconfig"])
    except Exception:
        ifs = None
    if ifs is not None:
        if "ifaddrs" not in over:
            h["ifaddrs"] = [{"name": i["name"], "flags": (1 if i["up"] else 0) | (8 if i["loopback_flag"] else 0), "v4": [str(a) for a in i["v4"]], "v6": [str(a) for a in i["v6"]]} for i in ifs]
        if "ifindex" not in over:
            h["ifindex"] = [i["name"] for i in ifs]
        if "linkstate" not in over:                                                         # independent kernel link state consistent with the fixture's `status:` lines
            h["linkstate"] = {i["name"]: {"active": "active", "inactive": "inactive", None: "no_media"}[i["status"]] for i in ifs}
    if "pcbcounts" not in over:
        try:
            rows = G.parse_sockets(h["sockets"])
            c = {"tcp": sum(1 for r in rows if r[0].startswith("tcp")), "raw": sum(1 for r in rows if r[0].startswith("icm"))}
        except Exception:
            c = {"tcp": 0, "raw": 0}
        h["pcbcounts"] = {"before": dict(c), "after": dict(c)}


def make_cfg(tmp, init=True):
    st = tmp / "state"
    if init and not st.exists():
        G.init_state(st)
    rs = tmp / "role_state"; rs.mkdir(exist_ok=True)
    code = tmp / "code"
    for rel in sorted(G.ROLE_CODE_ALLOWLIST):
        f = code / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("# synthetic placeholder for " + rel + "\n")
    cfg = {"state_dir": st, "role_state_dir": rs, "code_root": code, "deny_paths": [tmp / "other_role_store"], "deny_volumes": [], "deny_volume_uuids": [],
           "workspaces": [], "process_allowlist": None}
    return repin(tmp, cfg)


def repin(tmp, cfg):
    txt = json.dumps(G.build_code_manifest(cfg["code_root"]), sort_keys=True, indent=1)
    mp = tmp / "manifest.json"; mp.write_text(txt)
    cfg["code_manifest"], cfg["code_manifest_sha256"] = mp, hashlib.sha256(txt.encode()).hexdigest()
    return cfg


def run(role, tmp, host=None, cfg=None, **over):
    c = {**(cfg or make_cfg(tmp)), **over}
    return G.evaluate(role, host=host or good_host(tmp), **c)


def failing(res):
    return sorted(k for k, v in res.items() if v["status"] != G.PASS)


def st(res, k):
    return res[k]["status"]


# ======================================================================== baseline
def test_fully_configured_clean_synthetic_host_passes_for_both_roles(tmp_path):
    for role in G.ROLES:
        assert G.gate_passes(run(role, tmp_path)), failing(run(role, tmp_path))


# ======================================================================== AUDIT 4: mandatory inputs (no vacuous pass)
@pytest.mark.parametrize("missing,checks", [
    ("state_dir", {"interlock_state_verified", "interlock_other_role_not_this_boot"}),
    ("role_state_dir", {"role_state_forbidden_material_WEAK"}),
    ("code_root", {"role_code_root_matches_manifest"}),
    ("code_manifest", {"role_code_root_matches_manifest"}),
    ("code_manifest_sha256", {"role_code_root_matches_manifest"}),
])
def test_AUDIT4_missing_required_input_is_fail_closed_not_pass(tmp_path, missing, checks):
    res = run("forge", tmp_path, **{missing: None})
    assert checks <= {k for k, v in res.items() if v["status"] == G.FAIL_CLOSED} and not G.gate_passes(res)


def test_AUDIT4_missing_required_path_input_is_fail_closed_not_pass(tmp_path):
    assert not G.gate_passes(run("forge", tmp_path, state_dir=None, code_root=None))


def test_AUDIT4_empty_deny_list_is_fail_closed(tmp_path):
    res = run("forge", tmp_path, deny_paths=[], deny_volumes=[], deny_volume_uuids=[])
    assert st(res, "configured_other_role_storage_not_detected") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_AUDIT4_absent_or_uninitialized_state_directory_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path, init=False)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    cfg["state_dir"].mkdir(mode=0o700)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT4_empty_or_missing_code_root_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path)
    empty = tmp_path / "empty_code"; empty.mkdir()
    assert st(run("forge", tmp_path, cfg=cfg, code_root=empty), "role_code_root_matches_manifest") in (G.FAIL, G.FAIL_CLOSED)
    assert st(run("forge", tmp_path, cfg=cfg, code_root=tmp_path / "nope"), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_AUDIT4_cli_without_required_arguments_prints_fail_closed_and_fails(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge"], capture_output=True, text=True, timeout=120)
    assert p.returncode == 1 and "GATE_FAILS" in p.stdout and "FAIL_CLOSED" in p.stdout and "GATE_PASSES" not in p.stdout


# ======================================================================== AUDIT 5 + Q3: telemetry
MANDATORY_SOURCES = ("processes", "cmdlines", "env", "home", "ifconfig", "ifnames", "ifaddrs", "ifindex", "linkstate", "pcbcounts", "routes4", "routes6", "sockets", "boot_id")


@pytest.mark.parametrize("key", MANDATORY_SOURCES)
def test_AUDIT5_unavailable_telemetry_is_fail_closed(tmp_path, key):
    res = run("forge", tmp_path, host=good_host(tmp_path, **{key: None}))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and key in res["telemetry_complete"]["detail"] and not G.gate_passes(res)


@pytest.mark.parametrize("key", MANDATORY_SOURCES)
def test_Q3_a_missing_host_field_is_not_an_empty_result(tmp_path, key):
    h = good_host(tmp_path); del h[key]
    res = run("forge", tmp_path, host=h)
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


@pytest.mark.parametrize("key,bad", [
    ("processes", []), ("processes", ["/usr/bin/x"] * 12), ("processes", "notalist"), ("processes", [1] * 12),
    ("cmdlines", []), ("cmdlines", ["/usr/bin/x --a"] * 12), ("cmdlines", "notalist"), ("cmdlines", [1] * 12), ("cmdlines", [None] * 12),
    ("ifconfig", ""), ("ifconfig", 12345), ("ifconfig", "en0: flags=8863<UP>\n"),
    ("routes4", ""), ("routes4", "x"), ("routes6", "Routing tables\n"), ("sockets", ""), ("sockets", "x"),
    ("boot_id", ""), ("boot_id", 7), ("boot_id", "not-a-uuid"), ("env", []), ("env", "x"), ("env", {"A": 1}), ("env", {1: "a"}),
])
def test_AUDIT5_empty_or_implausible_output_is_fail_closed_never_a_clean_host(tmp_path, key, bad):
    res = run("forge", tmp_path, host=good_host(tmp_path, **{key: bad}))
    assert st(res, "telemetry_complete") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_Q3_cmdlines_none_empty_and_launchdless_are_fail_closed_and_agent_check_does_not_silently_skip(tmp_path):
    for bad in (None, [], ["/usr/bin/x"] * 12):
        res = run("forge", tmp_path, host=good_host(tmp_path, cmdlines=bad))
        assert st(res, "agent_process_absent") == G.FAIL_CLOSED and not G.gate_passes(res)


def test_Q3_env_none_and_malformed_are_fail_closed_but_a_verified_empty_env_is_legitimate(tmp_path):
    for bad in (None, [], {"A": 1}):
        assert st(run("forge", tmp_path, host=good_host(tmp_path, env=bad)), "container_runtime_absent") == G.FAIL_CLOSED
    assert st(run("forge", tmp_path, host=good_host(tmp_path, env={})), "container_runtime_absent") == G.PASS      # empty-but-verified


def test_Q3_home_has_no_silent_fallback_to_the_real_home(tmp_path):
    for check in ("cloud_sync_residual_exposure_absent", "agent_residual_exposure_absent", "container_runtime_absent"):
        assert st(run("forge", tmp_path, host=good_host(tmp_path, home=None)), check) == G.FAIL_CLOSED


def test_Q3_failure_reasons_are_distinguished_and_reported(tmp_path):
    h = good_host(tmp_path, cmdlines=None, ifconfig=None, routes4=None, sockets=None, env=None)
    h["telemetry"] = {"cmdlines": "PERMISSION_DENIED", "ifconfig": "UNSUPPORTED", "routes4": "UNAVAILABLE", "sockets": "MALFORMED", "env": "UNAVAILABLE"}
    d = run("forge", tmp_path, host=h)["telemetry_complete"]["detail"]
    for needle in ("cmdlines=PERMISSION_DENIED", "ifconfig=UNSUPPORTED", "routes4=UNAVAILABLE", "sockets=MALFORMED"):
        assert needle in d


def test_Q3_a_parser_failure_is_reported_as_MALFORMED(tmp_path):
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig="garbage line\n"))
    assert "ifconfig=MALFORMED" in res["telemetry_complete"]["detail"]


def test_AUDIT5_collect_host_returns_none_when_a_command_fails_or_raises(monkeypatch, fake_tools):
    class P:  # non-zero exit
        returncode, stdout, stderr = 1, "partial output", ""
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: P())
    h = G.collect_host()
    assert h["processes"] is None and h["cmdlines"] is None and h["ifconfig"] is None and h["boot_id"] is None and h["sockets"] is None
    assert h["telemetry"]["cmdlines"] == "UNAVAILABLE"

    def boom(*a, **k):
        raise FileNotFoundError("no such tool")
    monkeypatch.setattr(G.subprocess, "run", boom)
    h = G.collect_host()
    assert h["ifconfig"] is None and h["telemetry"]["ifconfig"] == "UNSUPPORTED"


def test_Q3_collect_host_distinguishes_permission_denied_and_unavailable(monkeypatch, fake_tools):
    class Denied:
        returncode, stdout, stderr = 1, "", "ps: Operation not permitted"
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: Denied())
    assert G.collect_host()["telemetry"]["cmdlines"] == "PERMISSION_DENIED"
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(PermissionError()))
    assert G.collect_host()["telemetry"]["processes"] == "PERMISSION_DENIED"
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert G.collect_host()["telemetry"]["processes"] == "UNAVAILABLE"


def test_Q3_collect_host_marks_unparsable_plist_MALFORMED(monkeypatch, fake_tools):
    class Garbage:
        returncode, stdout, stderr = 0, "not a plist", ""
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: Garbage())
    h = G.collect_host()
    assert h["disks"] is None and h["telemetry"]["disks"] == "MALFORMED"


def test_Q3_environment_collection_always_yields_a_verified_mapping():
    h = G.collect_host()
    assert isinstance(h["env"], dict) and h["telemetry"]["env"] == "OK"
    assert isinstance(h["home"], Path) or (h["home"] is None and h["telemetry"]["home"] == "UNAVAILABLE")      # a uid without a passwd entry (e.g. a bare container) has NO home: fail closed


def test_Q3_the_mandatory_telemetry_is_documented_exactly():
    doc = G.__doc__
    for src in ("processes", "cmdlines", "env", "home", "ifconfig", "routes4", "sockets", "boot_id", "volumes", "disks"):
        assert src in doc
    for reason in ("UNAVAILABLE", "PERMISSION_DENIED", "UNSUPPORTED", "MALFORMED"):
        assert reason in doc
    assert "verified-empty cmdline list is IMPOSSIBLE" in doc


# ======================================================================== AUDIT 1: interlock adversarial cases
def _state(tmp):
    return make_cfg(tmp)


def test_AUDIT1_valid_previous_role_receipt_from_current_boot_blocks(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    res = run("witness", tmp_path, cfg=cfg)
    assert st(res, "interlock_state_verified") == G.PASS and st(res, "interlock_other_role_not_this_boot") == G.FAIL


def test_AUDIT1_previous_role_receipt_from_previous_boot_does_not_block(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_B)
    assert G.gate_passes(run("witness", tmp_path, cfg=cfg))


def test_AUDIT1_same_role_repeats_in_one_boot_are_allowed(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    assert G.gate_passes(run("forge", tmp_path, cfg=cfg))


def _corrupt_status(tmp, mutate):
    cfg = _state(tmp); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    mutate(cfg["state_dir"])
    return run("witness", tmp, cfg=cfg)


def test_AUDIT1_missing_receipt_log_fails_closed(tmp_path):
    r = _corrupt_status(tmp_path, lambda d: (d / "receipts.jsonl").unlink())
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and not G.gate_passes(r)


def test_AUDIT1_deleting_only_the_receipts_content_is_caught_by_head(tmp_path):
    r = _corrupt_status(tmp_path, lambda d: (d / "receipts.jsonl").write_text(""))
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and "HEAD does not match" in r["interlock_state_verified"]["detail"]


def test_AUDIT1_corrupt_receipt_with_a_REAL_boot_id_fails_closed(tmp_path):
    r = _corrupt_status(tmp_path, lambda d: (d / "receipts.jsonl").write_text("garbage not json\n"))
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and not G.gate_passes(r)


def test_AUDIT1_truncated_receipt_line_fails_closed(tmp_path):
    def cut(d):
        t = (d / "receipts.jsonl").read_text(); (d / "receipts.jsonl").write_text(t[: len(t) // 2])
    assert st(_corrupt_status(tmp_path, cut), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT1_dropping_the_tail_receipt_with_a_valid_newline_is_caught_by_head(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_B); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    lines = (cfg["state_dir"] / "receipts.jsonl").read_text().splitlines(True)
    (cfg["state_dir"] / "receipts.jsonl").write_text("".join(lines[:-1]))
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT1_edited_boot_identifier_fails_closed(tmp_path):
    def edit(d):
        t = (d / "receipts.jsonl").read_text(); (d / "receipts.jsonl").write_text(t.replace(BOOT_A, BOOT_B))
    r = _corrupt_status(tmp_path, edit)
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and "checksum" in r["interlock_state_verified"]["detail"]


def test_AUDIT1_replayed_receipt_fails_closed(tmp_path):
    def replay(d):
        line = (d / "receipts.jsonl").read_text().splitlines()[0]
        with open(d / "receipts.jsonl", "a") as f:
            f.write(line + "\n")
    assert st(_corrupt_status(tmp_path, replay), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT1_receipts_copied_from_another_environment_fail_closed(tmp_path):
    other = tmp_path / "other_env"; other.mkdir()
    cfg_o = make_cfg(other); G.append_receipt(cfg_o["state_dir"], "forge", BOOT_B)
    cfg = _state(tmp_path)
    (cfg["state_dir"] / "receipts.jsonl").write_text((cfg_o["state_dir"] / "receipts.jsonl").read_text())
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


@pytest.mark.parametrize("mutate", [
    lambda r: {**r, "role": "oracle"}, lambda r: {**r, "boot": "not-a-uuid"}, lambda r: {**r, "seq": "1"}, lambda r: {**r, "extra": 1},
    lambda r: {k: v for k, v in r.items() if k != "prev"}, lambda r: {**r, "seq": True},
])
def test_AUDIT1_malformed_fields_and_unknown_roles_fail_closed(tmp_path, mutate):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    p = cfg["state_dir"] / "receipts.jsonl"; rec = json.loads(p.read_text().splitlines()[0])
    p.write_text(json.dumps(mutate(rec), sort_keys=True) + "\n")
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT1_duplicate_keys_sequence_gaps_and_head_mismatch_fail_closed(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_B); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    d = cfg["state_dir"]; good = (d / "receipts.jsonl").read_text()
    (d / "receipts.jsonl").write_text(good.replace('"v":2', '"v":2,"v":2', 1))
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    (d / "receipts.jsonl").write_text("".join(good.splitlines(True)[::-1]))
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    (d / "receipts.jsonl").write_text(good)
    head = json.loads((d / "HEAD.json").read_text()); head["seq"] = 7; (d / "HEAD.json").write_text(json.dumps(head))
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


@nonroot
def test_AUDIT1_read_failure_symlink_and_world_writable_dir_fail_closed(tmp_path):
    cfg = _state(tmp_path); d = cfg["state_dir"]
    os.chmod(d / "receipts.jsonl", 0)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    os.chmod(d / "receipts.jsonl", 0o600)
    real = tmp_path / "real_receipts"; (d / "receipts.jsonl").rename(real); (d / "receipts.jsonl").symlink_to(real)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    (d / "receipts.jsonl").unlink(); real.rename(d / "receipts.jsonl")
    os.chmod(d, 0o777)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_AUDIT1_init_refuses_to_reinitialize_an_existing_directory(tmp_path):
    cfg = _state(tmp_path)
    with pytest.raises(FileExistsError):
        G.init_state(cfg["state_dir"])


def test_AUDIT2_interlock_is_NOT_a_security_boundary_a_writer_can_reset_it_consistently(tmp_path):
    """Documents the limit. Anyone who can write the state directory can truncate the chain back to genesis, consistently, and the witness gate then passes in
    the SAME boot. The interlock is an operator-safety aid, earns no assurance credit against any adversary; cold boot + physical detachment are owner procedures."""
    cfg = _state(tmp_path); d = cfg["state_dir"]; G.append_receipt(d, "forge", BOOT_A)
    env = json.loads((d / "INIT.json").read_text())["env_id"]
    (d / "receipts.jsonl").write_text(""); (d / "HEAD.json").write_text(json.dumps({"v": 2, "env_id": env, "seq": 0, "sum": G.ZERO}, sort_keys=True))
    assert G.gate_passes(run("witness", tmp_path, cfg=cfg))


def test_AUDIT2_begin_requires_a_passing_gate_appends_a_chained_entry_and_then_blocks_the_other_role(tmp_path):
    cfg = _state(tmp_path)
    bad = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + "utun3: flags=8051<UP,POINTOPOINT> mtu 1380\n\tinet 203.0.113.2 --> 203.0.113.1 netmask 0xffffffff\n"), cfg=cfg)
    with pytest.raises(PermissionError):
        G.begin("forge", cfg["state_dir"], BOOT_A, bad)
    assert G.verify_state(cfg["state_dir"]) == ([], [])
    G.begin("forge", cfg["state_dir"], BOOT_A, run("forge", tmp_path, cfg=cfg))
    problems, recs = G.verify_state(cfg["state_dir"]); assert problems == [] and len(recs) == 1 and set(recs[0]) == {"v", "env_id", "seq", "role", "boot", "prev", "sum"}
    assert not G.gate_passes(run("witness", tmp_path, cfg=cfg))


def test_AUDIT3_only_a_well_formed_per_boot_uuid_is_accepted(tmp_path):
    assert st(run("forge", tmp_path), "boot_session_identified") == G.PASS
    for bad in ("", "1234", "{ sec = 1, usec = 2 } Mon Jan 1", BOOT_A + "x", None):
        assert st(run("forge", tmp_path, host=good_host(tmp_path, boot_id=bad)), "boot_session_identified") == G.FAIL_CLOSED


# ======================================================================== Q8: interlock state hardening
def test_Q8_a_planted_HEAD_tmp_symlink_is_never_followed(tmp_path):
    cfg = _state(tmp_path); d = cfg["state_dir"]; victim = tmp_path / "victim.txt"; victim.write_text("PRECIOUS")
    (d / ".HEAD.tmp").symlink_to(victim)
    with pytest.raises(PermissionError):
        G.append_receipt(d, "forge", BOOT_A)                  # the stale/planted entry is refused before anything is written
    assert victim.read_text() == "PRECIOUS" and (d / "receipts.jsonl").read_text() == ""


def test_Q8_exclusive_nofollow_create_defeats_a_racing_symlink_even_if_the_directory_check_is_bypassed(tmp_path, monkeypatch):
    cfg = _state(tmp_path); d = cfg["state_dir"]; victim = tmp_path / "victim.txt"; victim.write_text("PRECIOUS")
    monkeypatch.setattr(G, "verify_state", lambda sd, **k: ([], []))                  # simulate losing the race: the directory looked clean
    monkeypatch.setattr(G.secrets, "token_hex", lambda n: "deadbeefdeadbeef"[:2 * n])
    (d / ".HEAD.deadbeefdeadbeef.tmp").symlink_to(victim)
    with pytest.raises(OSError):
        G.append_receipt(d, "forge", BOOT_A)
    assert victim.read_text() == "PRECIOUS"


def test_Q8_an_existing_stale_temp_file_fails_closed(tmp_path):
    cfg = _state(tmp_path); (cfg["state_dir"] / ".HEAD.0123.tmp").write_text("stale")
    r = run("forge", tmp_path, cfg=cfg)
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and "unexpected" in r["interlock_state_verified"]["detail"]


def test_Q8_extra_entries_in_the_interlock_directory_fail_closed(tmp_path):
    cfg = _state(tmp_path); (cfg["state_dir"] / "notes.txt").write_text("x")
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_Q8_wrong_owner_is_rejected_via_mocked_metadata(tmp_path, monkeypatch):
    cfg = _state(tmp_path)
    monkeypatch.setattr(G.os, "geteuid", lambda: os.getuid() + 12345)
    r = run("forge", tmp_path, cfg=cfg)
    assert st(r, "interlock_state_verified") == G.FAIL_CLOSED and "owner" in r["interlock_state_verified"]["detail"]


@pytest.mark.parametrize("mode", [0o777, 0o770, 0o722, 0o702])
def test_Q8_group_or_world_writable_directory_fails_closed(tmp_path, mode):
    cfg = _state(tmp_path); os.chmod(cfg["state_dir"], mode)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


@pytest.mark.parametrize("name", ["INIT.json", "HEAD.json", "receipts.jsonl"])
def test_Q8_unsafe_file_mode_fails_closed(tmp_path, name):
    cfg = _state(tmp_path); os.chmod(cfg["state_dir"] / name, 0o666)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_Q8_setuid_bit_and_hardlinked_state_files_fail_closed(tmp_path):
    cfg = _state(tmp_path); d = cfg["state_dir"]
    os.chmod(d / "HEAD.json", 0o4600)
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED
    os.chmod(d / "HEAD.json", 0o600)
    os.link(d / "HEAD.json", tmp_path / "second_name")
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_Q8_state_files_are_read_without_following_symlinks_or_blocking_on_fifos(tmp_path):
    (tmp_path / "t").write_text("x"); (tmp_path / "ln").symlink_to(tmp_path / "t")
    with pytest.raises(OSError):
        G._read_state_file(tmp_path / "ln")
    os.mkfifo(tmp_path / "ff")
    with pytest.raises((OSError, ValueError)):
        G._read_state_file(tmp_path / "ff")                  # must return immediately, not block


def test_Q8_a_receipts_file_swapped_for_a_fifo_is_refused_without_hanging(tmp_path):
    cfg = _state(tmp_path); d = cfg["state_dir"]
    (d / "receipts.jsonl").unlink(); os.mkfifo(d / "receipts.jsonl")
    assert st(run("forge", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_Q8_carriage_returns_are_non_canonical_and_rejected(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    p = cfg["state_dir"] / "receipts.jsonl"; p.write_text(p.read_text().replace("\n", "\r\n"))
    assert st(run("witness", tmp_path, cfg=cfg), "interlock_state_verified") == G.FAIL_CLOSED


def test_Q8_the_interlock_is_still_documented_as_operator_safety_not_isolation():
    assert "operator-safety only -- NOT a security isolation boundary" in G.__doc__ and "earns NO acceptance credit" in G.__doc__


# ======================================================================== Q4: strict telemetry parsers (malformed => FAIL_CLOSED)
VALID_IF_VARIANTS = [GOOD_IFCONFIG]


@pytest.mark.parametrize("bad", [
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1\nen0 flags=8863<UP> mtu 1500\n\tinet 203.0.113.2 netmask 0xff000000\n",             # header missing ':'
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1\nen0: flags=8863 mtu 1500\n\tinet 203.0.113.2 netmask 0xff000000\n",             # flags without <>
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 999.1.1.1 netmask 0xff000000\n",                                                         # bad IPv4
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet\n",                                                                                        # truncated inet record
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet6 notanaddr prefixlen 128\n",                                                               # bad IPv6
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet6 ::1\n",                                                                                   # inet6 missing prefixlen
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tfrobnicate 1\n",                                                                                # unknown security-relevant line
    "\tinet 127.0.0.1\nlo0: flags=8049<UP,LOOPBACK> mtu 16384\n",                                                                              # indented line before any interface
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tstatus: activ\n",                                                                              # corrupted status value
    "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tstatus:\n",
    "utun3: flags=8051<UP,POINTOPOINT> mtu 1380\n\tinet 203.0.113.2 --> \n",                                                                 # tunnel record without a peer
    "bridge0: flags=8863<UP,BROADCAST> mtu 1500\n\tConfiguration:\n\tmystery-line 1\n",                                                          # bridge record with an unknown line
    "en0: flags=8863<UP> mtu 1500\n\tstatus: inactive\n",                                                                                      # no loopback at all
    "", "   \n",
])
def test_Q4_malformed_interface_telemetry_raises(bad):
    with pytest.raises(G.TelemetryError):
        G.parse_interfaces(bad)


def test_Q4_malformed_interface_telemetry_is_fail_closed_in_the_gate(tmp_path):
    bad = "lo0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.1\nen0 flags=8863<UP> mtu 1500\n\tinet 203.0.113.2 netmask 0xff000000\n"
    res = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=bad))
    assert st(res, "network_interfaces_disabled") == G.FAIL_CLOSED and not G.gate_passes(res)


@pytest.mark.parametrize("bad", [
    "Destination Gateway Flags Netif Expire\n127 127.0.0.1 UCS\n",                          # 3 columns
    "Destination Gateway Flags Netif Expire\n127 127.0.0.1 UCS lo0 a b\n",                   # 6 columns
    "Destination Gateway Flags Netif Expire\ndefaul 1.2.3.4 UGSc en0\n",                      # corrupted 'default'
    "Destination Gateway Flags Netif Expire\ndefault 1.2.3.4 UG$c en0\n",                     # bad flags
    "Destination Gateway Flags Netif Expire\n127 127.0.0.1 UCS l*0\n",                        # bad netif
    "127 127.0.0.1 UCS lo0\n",                                                              # row before header
    "Destination Gateway Flag Netif\n127 127.0.0.1 UCS lo0\n",                              # bad header
    "Routing tables\n\nInternet:\n", "",
])
def test_Q4_malformed_route_telemetry_raises(bad):
    with pytest.raises(G.TelemetryError):
        G.parse_routes(bad)


def test_Q4_route_destinations_are_case_insensitive_defaults_and_valid_forms_pass():
    rows = G.parse_routes("Routing tables\n\nInternet:\nDestination Gateway Flags Netif Expire\nDEFAULT 1.2.3.4 UGSc en0\n169.254 link#4 UCS en0 !\n224.0.0/4 link#4 UmCS en0\n127 127.0.0.1 UCS lo0\n")
    assert len(G.default_routes(rows)) == 1 and len(rows) == 4
    assert G.parse_routes("Routing tables\n\nInternet6:\nDestination Gateway Flags Netif Expire\nfe80::%lo0/64 fe80::1%lo0 UcI lo0\nff00::/8 ::1 UmCI lo0\n")


@pytest.mark.parametrize("bad", [
    "no section here\n",
    "Active Internet connections (including servers)\n",                                                                                              # no column header
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\ntcp4 0 0 *.5000 *.*\n",         # truncated tcp
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\ntcp4 0 0 *.5000 *.* listen\n",  # lowercase state
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address\nudp4 0 0 *.53 *.* extra\n",                # 6-col udp
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\nraw4 0 0 *.1 *.*\n",             # unknown protocol
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\ntcp4 0 0 noport *.* LISTEN\n",   # no port
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\ntcp4 0 0 999.1.1.1.80 *.* LISTEN\n",
    "Active Internet connections (including servers)\nProto Recv-Q Send-Q Local Address Foreign Address (state)\ntcp4 0 0 bad!host.80 *.* LISTEN\n",
])
def test_Q4_malformed_socket_telemetry_raises(bad):
    with pytest.raises(G.TelemetryError):
        G.parse_sockets(bad)


def test_Q4_a_corrupt_listener_row_is_fail_closed_in_the_gate(tmp_path):
    bad = GOOD_SOCKETS.replace("\n\nActive", "\ntcp4 0 0 *.5000 *.*\n\nActive")
    res = run("forge", tmp_path, host=good_host(tmp_path, sockets=bad))
    assert st(res, "network_no_external_sockets") == G.FAIL_CLOSED


def _mutate_chars(text, lo, hi, seed, n):
    rng, out = random.Random(seed), []
    for _ in range(n):
        i = rng.randrange(lo, hi); t = list(text)
        op = rng.choice("dri")
        if op == "d":
            del t[i]
        elif op == "r":
            t[i] = rng.choice("abcXYZ019:.*!/#% \t<>")
        else:
            t.insert(i, rng.choice("abcXYZ019:.*!/#% \t<>"))
        out.append("".join(t))
    return out


def test_Q4_fuzz_a_single_character_corruption_never_silently_hides_an_interface_violation():
    block = "en7: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n\tinet 203.0.113.9 netmask 0xffffff00\n\tstatus: active\n"
    base = GOOD_IFCONFIG + block
    lo = base.index("en7:")
    survived = 0
    for m in _mutate_chars(base, lo, len(base), seed=1234, n=600):
        try:
            ifs = G.parse_interfaces(m)
        except G.TelemetryError:
            continue
        survived += 1
        assert G.interface_violations(ifs), f"silent hide: {m[lo:]!r}"
    assert survived > 0                      # the property is exercised on inputs that still parse, not vacuous


def test_Q4_fuzz_a_single_character_corruption_never_silently_hides_a_default_route():
    base = GOOD_ROUTES + "default            192.168.1.1        UGScg                 en0\n"
    lo = base.index("default")
    survived = 0
    for m in _mutate_chars(base, lo, len(base) - 1, seed=99, n=600):
        try:
            rows = G.parse_routes(m)
        except G.TelemetryError:
            continue
        survived += 1
        assert G.default_routes(rows), f"silent hide: {m[lo:]!r}"
    assert survived > 0


def test_Q4_fuzz_a_single_character_corruption_never_silently_hides_an_external_listener():
    row = "tcp4       0      0  203.0.113.9.5000       *.*                    LISTEN\n"
    head, tail = GOOD_SOCKETS.split("\n\nActive")[0] + "\n", "\n" + GOOD_SOCKETS[GOOD_SOCKETS.index("\n\nActive") + 2:]
    base = head + row + tail
    lo = base.index("tcp4       0      0  203")
    survived = 0
    for m in _mutate_chars(base, lo, lo + len(row) - 1, seed=7, n=600):
        try:
            rows = G.parse_sockets(m)
        except G.TelemetryError:
            continue
        survived += 1
        assert any(r[2] for r in rows), f"silent hide: {m[lo:]!r}"
    assert survived > 0


# ======================================================================== AUDIT 6 + Q10: network
@pytest.mark.parametrize("extra", [
    "utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n\tinet 203.0.113.2 --> 203.0.113.1 netmask 0xffffffff\n",
    "bridge0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n\tinet 203.0.113.9 netmask 0xffffff00\n",
    "en5: flags=8863<UP,BROADCAST> mtu 1500\n\tinet6 2001:db8::5 prefixlen 64\n",
    "en6: flags=8863<UP,BROADCAST> mtu 1500\n\tinet6 fd00::5 prefixlen 64\n",
    "en7: flags=8863<UP,BROADCAST> mtu 1500\n\tinet 169.254.9.9 netmask 0xffff0000\n",
    "en8: flags=8862<BROADCAST> mtu 1500\n\tinet 203.0.113.10 netmask 0xff000000\n",
    "awdl0: flags=8943<UP,BROADCAST,RUNNING> mtu 1500\n\tstatus: active\n",
    "ppp0: flags=8051<UP,POINTOPOINT> mtu 1500\n\tinet 203.0.113.3 --> 203.0.113.4 netmask 0xffffffff\n",
    "gif0: flags=8051<UP,POINTOPOINT> mtu 1280\n\tinet 203.0.113.5 netmask 0xffffffff\n",
])
def test_AUDIT6_tunnels_bridges_global_v6_and_active_links_fail(tmp_path, extra):
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + extra)), "network_interfaces_disabled") == G.FAIL


def test_AUDIT6_link_local_only_and_inactive_interfaces_pass(tmp_path):
    extra = "utun0: flags=8051<UP,POINTOPOINT> mtu 1380\n\tinet6 fe80::1%utun0 prefixlen 64 scopeid 0x4\n"
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + extra)), "network_interfaces_disabled") == G.PASS


def test_Q10_loopback_is_recognized_by_ADDRESS_not_by_an_interface_name_prefix(tmp_path):
    lo9 = "lo9: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384\n\tinet 203.0.113.7 netmask 0xffffff00\n"
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + lo9)), "network_interfaces_disabled") == G.FAIL        # the re-audit bypass
    alias = "lo1: flags=8049<UP,LOOPBACK,RUNNING> mtu 16384\n\tinet 127.0.0.2 netmask 0xff000000\n"
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + alias)), "network_interfaces_disabled") == G.PASS      # real loopback alias
    non_lo_name_with_loopback_addr = "dummy0: flags=8049<UP,LOOPBACK> mtu 16384\n\tinet 127.0.0.9 netmask 0xff000000\n"
    assert st(run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + non_lo_name_with_loopback_addr)), "network_interfaces_disabled") == G.PASS


def test_AUDIT6_default_routes_fail_in_either_family_and_listeners_only_if_external(tmp_path):
    dflt = GOOD_ROUTES + "default            192.168.1.1        UGScg                 en0\n"
    dflt6 = GOOD_ROUTES6 + "default                                 fe80::1%en0                             UGcg                  en0\n"
    assert st(run("forge", tmp_path, host=good_host(tmp_path, routes4=dflt)), "network_no_default_route") == G.FAIL
    assert st(run("forge", tmp_path, host=good_host(tmp_path, routes6=dflt6)), "network_no_default_route") == G.FAIL
    ext = GOOD_SOCKETS.replace("\n\nActive", "\ntcp4       0      0  *.5000                 *.*                    LISTEN\n\nActive", 1)
    assert st(run("forge", tmp_path, host=good_host(tmp_path, sockets=ext)), "network_no_external_sockets") == G.FAIL
    assert st(run("forge", tmp_path), "network_no_external_sockets") == G.PASS         # loopback-only TCP + wildcard UDP/ICMP binds are tolerated


@pytest.mark.parametrize("row,expect_fail", [
    ("tcp4 0 0 *.5000 *.* LISTEN", True), ("tcp4 0 0 203.0.113.5.22 *.* LISTEN", True), ("tcp6 0 0 *.8000 *.* LISTEN", True), ("tcp4 0 0 127.0.0.1.80 *.* LISTEN", False),
    ("tcp6 0 0 ::1.80 *.* LISTEN", False), ("tcp4 0 0 127.0.0.1.50000 203.0.113.8.443 ESTABLISHED", True), ("tcp6 0 0 2001:db8:d04d:30.58170 2607:6bc0::10.443 LAST_ACK", True),
    ("udp4 0 0 203.0.113.5.123 *.*", True), ("udp4 0 0 127.0.0.1.5000 203.0.113.8.53", True), ("udp4 0 0 *.5353 *.*", False), ("udp46 0 0 *.5353 *.*", False),
    ("udp6 0 0 fe80::1%lo0.123 *.*", True), ("icm4 0 0 *.* *.*", False), ("udp4 0 0 127.0.0.1.5000 *.*", False),
])
def test_Q10_socket_table_covers_UDP_and_connections_and_tolerates_only_inert_wildcards(tmp_path, row, expect_fail):
    sockets = "Active Internet connections (including servers)\nProto Recv-Q Send-Q  Local Address          Foreign Address        (state)\n" + row + "\n" + SOCK_TAIL
    assert (st(run("forge", tmp_path, host=good_host(tmp_path, sockets=sockets)), "network_no_external_sockets") == G.FAIL) is expect_fail


def test_Q10_udp_absence_is_not_claimed_and_the_gate_stays_one_shot():
    assert "does not establish that no process could communicate" in G.__doc__ and "UDP absence is NOT claimed" in open(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py").read()
    assert "NOT continuous" in G.__doc__ and "WHOLE phase" in G.__doc__


def test_AUDIT6_the_gate_is_documented_as_one_shot_not_continuous():
    assert "NOT continuous" in G.__doc__ and "WHOLE phase" in G.__doc__


# ======================================================================== AUDIT 7: runtime / control plane
@pytest.mark.parametrize("name", ["colima", "limactl", "qemu-system-aarch64", "podman", "krunkit", "vfkit", "OrbStack Helper", "rancher-desktop", "nerdctl", "lima",
                                  "com.apple.Virtualization.VirtualMachine", "com.docker.backend", "Docker Desktop", "dockerd", "containerd", "VBoxHeadless", "vmware-vmx",
                                  "hyperkit", "firecracker", "bhyve", "lxc", "crun", "runc"])
def test_AUDIT7_original_bypass_runtimes_are_now_detected(tmp_path, name):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/local/bin/" + name])
    assert st(run("forge", tmp_path, host=h), "container_runtime_absent") == G.FAIL


def test_AUDIT7_benign_lookalike_process_names_do_not_trip_the_runtime_check(tmp_path):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/bin/Climate", "/usr/bin/dockets"])
    assert st(run("forge", tmp_path, host=h), "container_runtime_absent") == G.PASS


@pytest.mark.parametrize("rel,kind", [(".colima", "d"), (".lima", "d"), (".orbstack", "d"), (".rd", "d"), (".local/share/containers", "d"), (".config/containers", "d"),
                                      (".kube", "d"), (".minikube", "d"), ("Library/Containers/com.docker.docker", "d"), (".docker", "d"), (".docker/run/docker.sock", "f"),
                                      (".rd/docker.sock", "f")])
def test_AUDIT7_runtime_sockets_install_dirs_and_env_are_detected_without_a_running_process(tmp_path, rel, kind):
    p = tmp_path / "home" / rel; p.parent.mkdir(parents=True, exist_ok=True)
    p.mkdir() if kind == "d" else p.write_text("")
    assert st(run("forge", tmp_path), "container_runtime_absent") == G.FAIL


@pytest.mark.parametrize("var", ["DOCKER_HOST", "CONTAINER_HOST", "DOCKER_CONTEXT", "COLIMA_HOME", "LIMA_HOME", "PODMAN_HOST", "CONTAINERD_ADDRESS"])
def test_AUDIT7_runtime_environment_variables_are_detected(tmp_path, var):
    assert st(run("forge", tmp_path, host=good_host(tmp_path, env={var: "x"})), "container_runtime_absent") == G.FAIL


def test_AUDIT7_optional_process_allowlist_is_stricter_than_the_denylist(tmp_path):
    base = good_host(tmp_path)["processes"]
    names = {os.path.basename(p) for p in base}
    assert st(run("forge", tmp_path, process_allowlist=names), "process_allowlist_respected") == G.PASS
    h = good_host(tmp_path, processes=base + ["/x/mystery-runtime"])
    assert st(run("forge", tmp_path, host=h, process_allowlist=names), "process_allowlist_respected") == G.FAIL
    assert "process_allowlist_respected" not in run("forge", tmp_path)


def test_AUDIT7_the_detection_is_documented_as_not_exhaustive(tmp_path):
    assert "NOT exhaustive" in run("forge", tmp_path)["container_runtime_absent"]["detail"] and "NOT exhaustive" in G.__doc__


# ======================================================================== AUDIT 9: process absence != exposure absence
def test_AUDIT9_stopped_sync_client_with_synchronized_data_still_fails_on_exposure(tmp_path):
    home = tmp_path / "home"; (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "x.txt").write_text("synthetic")
    r = run("forge", tmp_path)
    assert st(r, "cloud_sync_process_absent") == G.PASS and "PROCESS_NOT_RUNNING" in r["cloud_sync_process_absent"]["detail"]
    assert st(r, "cloud_sync_residual_exposure_absent") == G.FAIL and "RESIDUAL_EXPOSURE_PRESENT" in r["cloud_sync_residual_exposure_absent"]["detail"] and not G.gate_passes(r)


def test_AUDIT9_stopped_agent_with_transcript_or_index_stores_still_fails_on_exposure(tmp_path):
    home = tmp_path / "home"
    for rel in (".claude/projects", "Library/Application Support/Cursor/User/History", ".codex"):
        (home / rel).mkdir(parents=True); (home / rel / "session.db").write_text("synthetic")
    r = run("forge", tmp_path)
    assert st(r, "agent_process_absent") == G.PASS
    assert st(r, "agent_residual_exposure_absent") == G.FAIL and "3 of" in r["agent_residual_exposure_absent"]["detail"]


def test_AUDIT9_empty_locations_and_a_clean_home_report_no_residual_exposure_DETECTED_only(tmp_path):
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    r = run("forge", tmp_path)
    assert st(r, "agent_residual_exposure_absent") == G.PASS and "NO_RESIDUAL_EXPOSURE_DETECTED" in r["agent_residual_exposure_absent"]["detail"]


@pytest.mark.parametrize("proc,key", [("Dropbox", "cloud_sync_process_absent"), ("syncthing", "cloud_sync_process_absent"), ("Cursor Helper", "agent_process_absent"),
                                       ("codex", "agent_process_absent"), ("ollama", "agent_process_absent")])
def test_AUDIT9_running_sync_clients_and_agents_fail(tmp_path, proc, key):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/x/" + proc])
    assert st(run("forge", tmp_path, host=h), key) == G.FAIL


def test_AUDIT9_agent_run_via_a_generic_interpreter_is_caught_by_command_line(tmp_path):
    h = good_host(tmp_path, cmdlines=good_host(tmp_path)["cmdlines"] + ["node /opt/lib/@anthropic-ai/claude-code/cli.js --resume"])
    assert st(run("forge", tmp_path, host=h), "agent_process_absent") == G.FAIL


def test_AUDIT9_apple_system_daemons_and_cursor_ui_service_are_not_false_positives(tmp_path):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/libexec/bird", "/usr/libexec/cloudd", "/usr/libexec/fileproviderd", "/System/CursorUIViewService"])
    r = run("forge", tmp_path, host=h)
    assert st(r, "cloud_sync_process_absent") == G.PASS and st(r, "agent_process_absent") == G.PASS


@pytest.mark.parametrize("rel", [".cline", ".roo", ".aider", ".local/share/opencode", ".config/Claude", "Library/Logs/Claude", "Library/Caches/Claude"])
def test_Q9_additional_agent_store_locations_are_now_covered(tmp_path, rel):
    p = tmp_path / "home" / rel; p.mkdir(parents=True); (p / "s.db").write_text("synthetic")
    assert st(run("forge", tmp_path), "agent_residual_exposure_absent") == G.FAIL


def test_AUDIT9_exposure_inspection_never_reads_contents_or_reports_names(tmp_path):
    p = tmp_path / "home" / ".claude" / "SENTINEL_FILE_NAME_XYZ"; p.parent.mkdir(parents=True); p.write_text("SENTINEL_CONTENT_XYZ")
    blob = json.dumps(run("forge", tmp_path))
    assert "SENTINEL_FILE_NAME_XYZ" not in blob and "SENTINEL_CONTENT_XYZ" not in blob
    src = (ROOT / "scripts/genesis_v2_tier0s_phase_gate.py").read_text().split("def _nonempty_dir")[1].split("def _res")[0]
    assert "scandir" in src and "open(" not in src and ".read(" not in src and "read_text" not in src and "read_bytes" not in src


@pytest.mark.parametrize("sub,expect_fail", [("Documents/role_work", True), ("Desktop", True), ("Library/Mobile Documents/x", True), ("elsewhere/role_work", False)])
def test_AUDIT9_role_workspace_inside_synced_or_user_documents_paths_fails(tmp_path, sub, expect_fail):
    ws = tmp_path / "home" / sub; ws.mkdir(parents=True)
    r = run("forge", tmp_path, workspaces=[ws])
    assert (st(r, "workspace_not_in_synced_or_user_documents_path") == G.FAIL) is expect_fail


# ======================================================================== AUDIT 10 + Q5 + Q10: other-role storage
def test_AUDIT10_other_role_storage_present_or_mounted_fails_and_absent_passes(tmp_path):
    store = tmp_path / "witness_store"; store.mkdir()
    assert st(run("forge", tmp_path, deny_paths=[store]), "configured_other_role_storage_not_detected") == G.FAIL
    assert st(run("forge", tmp_path), "configured_other_role_storage_not_detected") == G.PASS
    cfg = make_cfg(tmp_path)
    r = run("forge", tmp_path, host=good_host(tmp_path, volumes=["Macintosh HD", "WitnessVault"]), cfg=cfg, deny_paths=[], deny_volumes=["WitnessVault"])
    assert st(r, "configured_other_role_storage_not_detected") == G.FAIL


def test_AUDIT14_dangling_symlink_to_the_other_role_store_counts_as_present(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path / "nowhere")
    assert st(run("forge", tmp_path, deny_paths=[tmp_path / "alias"]), "configured_other_role_storage_not_detected") == G.FAIL


def _vol_run(tmp, volumes, disks, deny_volumes=(), deny_uuids=()):
    volumes, disks = volumes or ["Macintosh HD"], disks or list(GOOD_DISKS)                  # a real host always lists at least one volume and disk (plausibility floor)
    return st(run("forge", tmp, host=good_host(tmp, volumes=volumes, disks=disks), deny_paths=[], deny_volumes=list(deny_volumes), deny_volume_uuids=list(deny_uuids)),
              "configured_other_role_storage_not_detected")


@pytest.mark.parametrize("mounted", ["WitnessVault 1", "WitnessVault 2", "witnessvault", "WITNESSVAULT", "  WitnessVault ", "WitnessVault"])
def test_Q5_collision_suffix_and_case_variants_of_a_denied_volume_name_are_detected(tmp_path, mounted):
    assert _vol_run(tmp_path, [mounted], [], deny_volumes=["WitnessVault"]) == G.FAIL


def test_Q5_unicode_normalization_variants_are_detected(tmp_path):
    assert _vol_run(tmp_path, ["CaféVault"], [], deny_volumes=["CaféVault"]) == G.FAIL        # NFD vs NFC


def test_Q5_similar_but_different_names_are_not_matched(tmp_path):
    assert _vol_run(tmp_path, ["WitnessVaultBackup", "Witness"], [], deny_volumes=["WitnessVault"]) == G.PASS


def test_Q5_stable_volume_uuid_catches_a_renamed_or_unmounted_attached_volume(tmp_path):
    disks = [{"name": "Totally Innocent", "uuid": "ABCD0000-1111-2222-3333-444455556666", "dev": "disk9s1", "mount": ""}]            # attached, NOT mounted, renamed
    assert _vol_run(tmp_path, ["Macintosh HD"], disks, deny_uuids=["abcd0000-1111-2222-3333-444455556666"]) == G.FAIL
    assert _vol_run(tmp_path, ["Macintosh HD"], [], deny_uuids=["abcd0000-1111-2222-3333-444455556666"]) == G.PASS


def test_Q5_disk_metadata_names_and_mount_point_basenames_are_both_consulted(tmp_path):
    assert _vol_run(tmp_path, [], [{"name": "WitnessVault", "uuid": "", "dev": "disk9s1", "mount": ""}], deny_volumes=["witnessvault 1"]) == G.FAIL
    assert _vol_run(tmp_path, [], [{"name": "x", "uuid": "", "dev": "disk9s1", "mount": "/Volumes/WitnessVault 1"}], deny_volumes=["WitnessVault"]) == G.FAIL


def test_Q5_volume_telemetry_failure_is_fail_closed_when_volumes_are_named(tmp_path):
    for key in ("volumes", "disks"):
        res = run("forge", tmp_path, host=good_host(tmp_path, **{key: None}), deny_paths=[], deny_volumes=["WitnessVault"])
        assert st(res, "configured_other_role_storage_not_detected") == G.FAIL_CLOSED and st(res, "telemetry_complete") == G.FAIL_CLOSED


def test_Q5_physical_detachment_is_still_documented_as_not_software_proven():
    txt = (INFRA / "GENESIS_V2_TIER0S_SEQUENTIAL_SOVEREIGN_ISOLATION.md").read_text()
    assert "NOT evidence that the other role" in open(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py").read()          # W5: the PASS text claims no physical absence
    assert "owner-controlled physical procedures" in txt and "NOT" in txt


def test_Q10_deny_paths_must_be_absolute_canonical_or_a_supported_home_relative_form(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    for bad in ("relative/path", "./x", "~user/x", "/abs/../escape", "", "~", None, 5):
        r = run("forge", tmp_path, deny_paths=[bad], host=good_host(tmp_path))
        if bad == "~":
            continue
        assert st(r, "configured_other_role_storage_not_detected") == G.FAIL_CLOSED, bad
    (home / "WitnessStore").mkdir()
    assert st(run("forge", tmp_path, deny_paths=["~/WitnessStore"]), "configured_other_role_storage_not_detected") == G.FAIL        # '~/' expanded against the supplied home
    assert st(run("forge", tmp_path, deny_paths=["~/AbsentStore"]), "configured_other_role_storage_not_detected") == G.PASS


def test_Q10_normalize_deny_path_unit():
    assert G.normalize_deny_path("/a//b/./c", None) == "/a/b/c" and G.normalize_deny_path("~/x", Path("/h")) == "/h/x"
    assert G.normalize_deny_path("~/x", None) is None and G.normalize_deny_path("a/b", Path("/h")) is None and G.normalize_deny_path("/a/../b", None) is None


# ======================================================================== Q1: code-root traversal (strict) + Q6: hash-pinned manifest
def test_allowlisted_code_root_passes_and_any_extra_file_fails(tmp_path):
    cfg = make_cfg(tmp_path)
    assert st(run("witness", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.PASS
    for extra in ("orca/eval/genesis_v2/runner_qualification.py", "orca/eval/genesis_v2/ledger.py", "orca/eval/genesis_v2/operational_boundary.py", "docs/anything.md", "tests/t.py",
                  ".git/config", "orca/eval/genesis_v2/store.py.bak", "orca/eval/genesis_v2/store.pyc", "orca/eval/genesis_v2/sub/deep/evil.py", "orca/eval/genesis_v2/.hidden"):
        f = cfg["code_root"] / extra; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("")
        assert st(run("witness", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL, extra
        f.unlink()
        for d in sorted({p for p in f.parents if p != cfg["code_root"] and cfg["code_root"] in p.parents}, key=lambda p: -len(p.parts)):
            if d.exists() and not any(d.iterdir()) and str(d.relative_to(cfg["code_root"])) not in {str(Path(r).parent) for r in G.ROLE_CODE_ALLOWLIST}:
                d.rmdir()


def test_code_root_symlinks_fail(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["code_root"] / "link").symlink_to(tmp_path)
    assert st(run("witness", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_the_full_repository_is_rejected_as_a_role_code_root(tmp_path):
    cfg = make_cfg(tmp_path)
    res = G.evaluate("forge", host=good_host(tmp_path), **{**cfg, "code_root": ROOT / "orca"})
    assert st(res, "role_code_root_matches_manifest") in (G.FAIL, G.FAIL_CLOSED)


@nonroot
def test_Q1_mode_000_directory_hiding_a_qualification_named_file_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); hid = cfg["code_root"] / "docs"; hid.mkdir(); (hid / "runner_qualification.py").write_text("x"); os.chmod(hid, 0)
    try:
        res = run("forge", tmp_path, cfg=cfg)
        assert st(res, "role_code_root_matches_manifest") == G.FAIL_CLOSED and not G.gate_passes(res)
    finally:
        os.chmod(hid, 0o700)


@nonroot
def test_Q1_unreadable_nested_directory_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); deep = cfg["code_root"] / "orca" / "eval" / "genesis_v2" / "hidden"; deep.mkdir(); (deep / "x.py").write_text("x"); os.chmod(deep, 0)
    try:
        assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    finally:
        os.chmod(deep, 0o700)


def test_Q1_permission_error_from_the_directory_listing_is_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path); real = G._scandir

    def deny(fd, rel=""):
        if rel.rsplit("/", 1)[-1] == "genesis_v2":
            raise PermissionError(13, "denied")
        return real(fd, rel)
    monkeypatch.setattr(G, "_scandir", deny)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q1_a_directory_that_disappears_mid_scan_is_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path); real = G._scandir; calls = {"n": 0}

    def vanish(fd, rel=""):
        calls["n"] += 1
        if calls["n"] == 3:
            raise FileNotFoundError(2, "vanished")
        return real(fd, rel)
    monkeypatch.setattr(G, "_scandir", vanish)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


@pytest.mark.parametrize("exc", [RuntimeError("boom"), OSError(5, "I/O error"), ValueError("weird")])
def test_Q1_any_traversal_exception_including_non_oserror_is_fail_closed(tmp_path, monkeypatch, exc):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": (_ for _ in ()).throw(exc))
    res = run("forge", tmp_path, cfg=cfg)
    assert st(res, "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q1_a_stat_failure_on_an_entry_is_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    real = G._scandir

    class E:
        def __init__(self, e): self.e, self.name = e, e.name
        def stat(self, follow_symlinks=True): raise OSError(5, "stat failed")

    class Wrap:
        def __init__(self, it): self.l = [E(e) for e in it]
        def __enter__(self): return iter(self.l)
        def __exit__(self, *a): return False
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": Wrap(real(fd, rel)))
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q1_special_files_and_symlink_anomalies_in_the_code_root_are_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); fifo = cfg["code_root"] / "orca" / "fifo"; os.mkfifo(fifo)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    fifo.unlink()
    (cfg["code_root"] / "dangling").symlink_to(tmp_path / "nowhere")
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q1_unix_socket_in_the_code_root_is_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path); monkeypatch.chdir(cfg["code_root"] / "orca")
    s = socket.socket(socket.AF_UNIX); s.bind("sock")
    try:
        assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    finally:
        s.close()


def test_Q1_a_code_root_that_is_itself_a_symlink_or_file_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); link = tmp_path / "codelink"; link.symlink_to(cfg["code_root"])
    assert st(run("forge", tmp_path, cfg=cfg, code_root=link), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    f = tmp_path / "afile"; f.write_text("x")
    assert st(run("forge", tmp_path, cfg=cfg, code_root=f), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q1_traversal_failure_details_never_leak_names_or_contents(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path); (cfg["code_root"] / "SENTINEL_DIR_NAME").mkdir()
    real = G._scandir
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": (_ for _ in ()).throw(PermissionError(13, "SENTINEL_DIR_NAME")) if rel.rsplit("/", 1)[-1] == "SENTINEL_DIR_NAME" else real(fd, rel))
    blob = json.dumps(run("forge", tmp_path, cfg=cfg))
    assert "SENTINEL_DIR_NAME" not in blob


# ---- Q6 manifest semantics
def test_Q6_allowed_filename_with_arbitrary_content_is_a_hash_mismatch(tmp_path):
    cfg = make_cfg(tmp_path); (cfg["code_root"] / "orca/eval/genesis_v2/store.py").write_text("def qualify(model): return run_benchmark(model)\n")
    r = run("forge", tmp_path, cfg=cfg)
    assert st(r, "role_code_root_matches_manifest") == G.FAIL and "1 hash/size mismatch" in r["role_code_root_matches_manifest"]["detail"]


def test_Q6_same_size_different_content_is_still_caught(tmp_path):
    cfg = make_cfg(tmp_path); f = cfg["code_root"] / "orca/__init__.py"; old = f.read_text(); f.write_text(old[:-2] + "X\n")
    assert len(f.read_text()) == len(old) and st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL


def test_Q6_hardlink_to_outside_content_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path); f = cfg["code_root"] / "orca/eval/genesis_v2/spec.py"; outside = tmp_path / "outside.py"; outside.write_text(f.read_text())
    f.unlink(); os.link(outside, f)
    r = run("forge", tmp_path, cfg=cfg)
    assert st(r, "role_code_root_matches_manifest") == G.FAIL and "hardlink" in r["role_code_root_matches_manifest"]["detail"]


def test_Q6_symlink_in_place_of_an_allowed_file_is_rejected(tmp_path):
    cfg = make_cfg(tmp_path); f = cfg["code_root"] / "orca/eval/genesis_v2/spec.py"; outside = tmp_path / "outside.py"; outside.write_text(f.read_text())
    f.unlink(); f.symlink_to(outside)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL_CLOSED


@pytest.mark.parametrize("rel", ["orca/eval/genesis_v2/__pycache__/runner_qualification.cpython-311.pyc", "orca/__pycache__/x.cpython-311.pyc", "orca/stray.pyc", "orca/stray.pyo"])
def test_Q6_unexpected_bytecode_including_sourceless_pyc_is_rejected(tmp_path, rel):
    cfg = make_cfg(tmp_path); f = cfg["code_root"] / rel; f.parent.mkdir(parents=True, exist_ok=True); f.write_bytes(b"\x00")
    r = run("forge", tmp_path, cfg=cfg)
    assert st(r, "role_code_root_matches_manifest") == G.FAIL and "unlisted bytecode" in r["role_code_root_matches_manifest"]["detail"]


def test_Q6_missing_unknown_dir_size_and_unsafe_mode_are_all_rejected(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["code_root"] / "extra_dir").mkdir()
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL
    (cfg["code_root"] / "extra_dir").rmdir()
    f = cfg["code_root"] / "orca/eval/genesis_eval_v1.py"; os.chmod(f, 0o666)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL
    os.chmod(f, 0o644); os.chmod(f, 0o4644)
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL
    os.chmod(f, 0o644); f.unlink()
    assert st(run("forge", tmp_path, cfg=cfg), "role_code_root_matches_manifest") == G.FAIL


def test_Q6_ownership_is_checked_via_mocked_metadata():
    ok = SimpleNamespace(st_uid=os.geteuid(), st_mode=stat.S_IFREG | 0o644)
    assert G.stat_ok(ok)
    assert not G.stat_ok(SimpleNamespace(st_uid=os.geteuid() + 1, st_mode=stat.S_IFREG | 0o644))
    assert not G.stat_ok(SimpleNamespace(st_uid=os.geteuid(), st_mode=stat.S_IFREG | 0o664)) and not G.stat_ok(SimpleNamespace(st_uid=os.geteuid(), st_mode=stat.S_IFREG | 0o4644))
    assert G.stat_ok(SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o644), allow_root=True) and not G.stat_ok(SimpleNamespace(st_uid=0, st_mode=stat.S_IFREG | 0o644))


def test_Q6_manifest_must_be_pinned_digest_matched_policy_confined_and_strict(tmp_path):
    cfg = make_cfg(tmp_path)
    for k in ("code_manifest", "code_manifest_sha256"):
        assert st(run("forge", tmp_path, cfg=cfg, **{k: None}), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    assert st(run("forge", tmp_path, cfg=cfg, code_manifest_sha256="0" * 64), "role_code_root_matches_manifest") == G.FAIL_CLOSED          # digest mismatch
    assert st(run("forge", tmp_path, cfg=cfg, code_manifest_sha256="zz"), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    man = json.loads(cfg["code_manifest"].read_text())
    man["files"]["orca/eval/genesis_v2/runner_qualification.py"] = {"sha256": "0" * 64, "size": 0}                                       # outside the fixed role policy
    txt = json.dumps(man); mp = tmp_path / "m2.json"; mp.write_text(txt)
    r = run("forge", tmp_path, cfg=cfg, code_manifest=mp, code_manifest_sha256=hashlib.sha256(txt.encode()).hexdigest())
    assert st(r, "role_code_root_matches_manifest") == G.FAIL_CLOSED and "outside the fixed role policy" in r["role_code_root_matches_manifest"]["detail"]
    for body in ('{"v":1,"files":{}}', '[]', '{"v":2,"files":{"a":{}}}', '{"v":1,"files":{"orca/__init__.py":{"sha256":"x","size":1}}}',
                 '{"v":1,"files":{"orca/__init__.py":{"sha256":"%s","size":1},"orca/__init__.py":{"sha256":"%s","size":1}}}' % ("0" * 64, "0" * 64), "not json"):
        (tmp_path / "m3.json").write_text(body)
        r = run("forge", tmp_path, cfg=cfg, code_manifest=tmp_path / "m3.json", code_manifest_sha256=hashlib.sha256(body.encode()).hexdigest())
        assert st(r, "role_code_root_matches_manifest") == G.FAIL_CLOSED, body


def test_Q6_manifest_that_is_a_symlink_or_directory_is_refused(tmp_path):
    cfg = make_cfg(tmp_path); link = tmp_path / "mlink"; link.symlink_to(cfg["code_manifest"])
    assert st(run("forge", tmp_path, cfg=cfg, code_manifest=link), "role_code_root_matches_manifest") == G.FAIL_CLOSED
    assert st(run("forge", tmp_path, cfg=cfg, code_manifest=tmp_path), "role_code_root_matches_manifest") == G.FAIL_CLOSED


def test_Q6_build_manifest_refuses_anomalies_and_the_cli_prints_a_pin(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["code_root"] / "l").symlink_to(tmp_path)
    with pytest.raises(OSError):
        G.build_code_manifest(cfg["code_root"])
    (cfg["code_root"] / "l").unlink()
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "build-manifest", "--code-root", str(cfg["code_root"])], capture_output=True, text=True, timeout=60)
    assert p.returncode == 0 and "MANIFEST_SHA256 " in p.stderr and set(json.loads(p.stdout)["files"]) == set(G.ROLE_CODE_ALLOWLIST)


def test_Q6_the_documentation_states_precisely_what_the_allowlist_proves():
    d = " ".join(G.__doc__.split())
    for must in ("byte-identical to that manifest", "does NOT prove the manifest is the reviewed one", "Path names alone are never treated as proof of Qualification absence",
                 "pinned out-of-band"):
        assert must in d
    assert G.ROLE_BYTECODE_ALLOWED == frozenset()


def test_the_manifest_policy_excludes_qualification_and_privileged_modules():
    names = " ".join(G.ROLE_CODE_ALLOWLIST)
    for banned in ("runner_qualification", "operational_boundary", "ledger", "authority_registry", "secret_manager", "sandbox", "owner_preflight", "corpus_generation_authorization"):
        assert banned not in names


# ======================================================================== Q2: role-state traversal (strict) + weak owner-key scan
@nonroot
def test_Q2_unreadable_nested_state_directory_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); sub = cfg["role_state_dir"] / "sub"; sub.mkdir(); (sub / "vault_private_key").write_bytes(b""); os.chmod(sub, 0)
    try:
        res = run("forge", tmp_path, cfg=cfg)
        assert st(res, "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED and not G.gate_passes(res)
    finally:
        os.chmod(sub, 0o700)


@nonroot
def test_Q2_unreadable_deeply_nested_state_directory_and_unreadable_file_are_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); deep = cfg["role_state_dir"] / "a" / "b"; deep.mkdir(parents=True); os.chmod(deep, 0)
    try:
        assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED
    finally:
        os.chmod(deep, 0o700)
    f = cfg["role_state_dir"] / "data.bin"; f.write_bytes(b"x"); os.chmod(f, 0)
    try:
        assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED
    finally:
        os.chmod(f, 0o600)


def test_Q2_transient_scan_errors_are_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path); (cfg["role_state_dir"] / "sub").mkdir(); real = G._scandir
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": (_ for _ in ()).throw(OSError(5, "transient")) if rel.rsplit("/", 1)[-1] == "sub" else real(fd, rel))
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED


def test_Q2_traversal_exception_and_permission_exception_are_fail_closed(tmp_path, monkeypatch):
    cfg = make_cfg(tmp_path)
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": (_ for _ in ()).throw(RuntimeError("boom")))
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED
    monkeypatch.setattr(G, "_scandir", lambda fd, rel="": (_ for _ in ()).throw(PermissionError(13, "denied")))
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED


def test_Q2_symlink_directory_dangling_symlink_and_special_files_are_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); rs = cfg["role_state_dir"]
    (rs / "dirlink").symlink_to(tmp_path)
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED
    (rs / "dirlink").unlink(); (rs / "dangling").symlink_to(tmp_path / "nowhere")
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED
    (rs / "dangling").unlink(); os.mkfifo(rs / "fifo")
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED


def test_Q2_the_role_state_dir_itself_missing_a_symlink_or_a_file_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path); link = tmp_path / "rslink"; link.symlink_to(cfg["role_state_dir"]); f = tmp_path / "afile"; f.write_text("x")
    for bad in (tmp_path / "absent", link, f, None):
        assert st(run("forge", tmp_path, cfg=cfg, role_state_dir=bad), "role_state_forbidden_material_WEAK") == G.FAIL_CLOSED


@pytest.mark.parametrize("role,name,bad", [("forge", "vault_private_key", True), ("witness", "vault_private_key", False), ("witness", "corpus_secret", True),
                                           ("forge", "corpus_secret", False), ("forge", "owner_signing_key.pem", True), ("witness", "owner-signing-key", True),
                                           ("forge", "vault_public_key", False)])
def test_role_state_forbidden_material_by_name(tmp_path, role, name, bad):
    cfg = make_cfg(tmp_path); (cfg["role_state_dir"] / name).write_bytes(b"")
    assert (st(run(role, tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL) is bad


def test_Q2_nested_forbidden_names_are_found(tmp_path):
    cfg = make_cfg(tmp_path); sub = cfg["role_state_dir"] / "a" / "b"; sub.mkdir(parents=True); (sub / "vault_private_key").write_bytes(b"")
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.FAIL


def test_a_key_header_in_an_innocently_named_file_is_caught_but_a_renamed_encoded_key_is_not(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["role_state_dir"] / "notes.bin").write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA")
    r = run("forge", tmp_path, cfg=cfg)["role_state_forbidden_material_WEAK"]
    assert r["status"] == G.FAIL and "WEAK" in r["detail"]
    (cfg["role_state_dir"] / "notes.bin").write_bytes(b"c3ludGhldGljLWJhc2U2NC1lbmNvZGVkLWtleQ==")      # documents the weakness: not detected
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.PASS
    (cfg["role_state_dir"] / "notes.bin").write_bytes(b"x" * 300 + b"-----BEGIN PRIVATE KEY-----")       # header after the first 256 bytes: not detected
    assert st(run("forge", tmp_path, cfg=cfg), "role_state_forbidden_material_WEAK") == G.PASS


# ======================================================================== output hygiene + live
def test_results_expose_only_counts_never_paths_names_or_command_lines(tmp_path):
    store = tmp_path / "SENTINEL_STORE_NAME"; store.mkdir()
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/x/SentinelDockerHelper-docker"], cmdlines=good_host(tmp_path)["cmdlines"] + ["node @anthropic-ai/SENTINEL_ARG"])
    blob = json.dumps(run("forge", tmp_path, host=h, deny_paths=[store]))
    for s in ("SENTINEL_STORE_NAME", "SentinelDockerHelper", "SENTINEL_ARG", str(tmp_path)):
        assert s not in blob


def test_live_check_is_read_only_and_fails_on_this_unprovisioned_host(tmp_path):
    cfg = make_cfg(tmp_path, init=False)
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge", "--state-dir", str(tmp_path / "s"),
                        "--role-state-dir", str(cfg["role_state_dir"]), "--code-root", str(ROOT / "orca"), "--code-manifest", str(cfg["code_manifest"]),
                        "--code-manifest-sha256", cfg["code_manifest_sha256"], "--deny-path", str(tmp_path / "other")], capture_output=True, text=True, timeout=180)
    assert p.stdout.strip().splitlines()[-1] == "GATE_FAILS"
    assert not (tmp_path / "s").exists(), "check must be read-only"


# ======================================================================== doc / acceptance consistency
def _rows(txt):
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^\| (\d+) \| [^|]+\| `([A-Z_]+)` \|", txt, re.M)}


def test_tier0s_design_doc_states_verdict_limits_and_does_not_overwrite_tier0a():
    txt = (INFRA / "GENESIS_V2_TIER0S_SEQUENTIAL_SOVEREIGN_ISOLATION.md").read_text()
    assert "TIER0_S_REDUCED_ASSURANCE_ONLY" in txt and "TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED" in txt
    for must in ("malicious owner or root administrator", "no adversarial-owner isolation", "firmware / boot-chain compromise", "never equivalent to Tier0-A"):
        assert must in txt
    for opt in ("**S1**", "**S2**", "**S3**", "**S4**", "**S5**"):
        assert opt in txt
    for cls in ("CONTROLLED", "MITIGATABLE", "UNCONTROLLED", "NOT_APPLICABLE"):
        assert cls in txt
    assert "Decision 9" in (INFRA / "GENESIS_V2_OWNER_DECISIONS_REQUIRED.md").read_text()
    tier0a = (INFRA / "GENESIS_V2_TIER0A_READINESS_AND_MACHINE_REQUIREMENTS.md").read_text()
    assert "TIER0_A_BLOCKED_SECOND_MACHINE_REQUIRED" in tier0a and "Tier0-S" not in tier0a


def test_AUDIT3_design_doc_requires_physical_detachment_with_the_exact_lifecycle():
    txt = (INFRA / "GENESIS_V2_TIER0S_SEQUENTIAL_SOVEREIGN_ISOLATION.md").read_text()
    for must in ("PHYSICAL DETACHMENT", "Witness storage physically absent", "remove Forge role storage", "No simultaneous mounting", "ONLY the approved transfer medium"):
        assert must in txt, must
    assert "owner-controlled physical procedure" in txt and "earns NO acceptance credit" in txt


def test_tier0s_status_tables_are_separate_complete_never_proven_real_and_audit_corrected():
    txt = (INFRA / "GENESIS_V2_TIER0S_ACCEPTANCE_STATUS.md").read_text()
    allowed = {"PROVEN_SYNTHETIC_ONLY", "PARTIAL", "NOT_YET_PROVEN", "OWNER_ACTION_REQUIRED", "UNACCEPTABLE"}
    a, b = txt.split("## B. Required invariants")
    ra, rb = _rows(a), _rows(b)
    assert set(ra) == set(range(1, 23)) and set(rb) == set(range(1, 17))
    assert set(ra.values()) | set(rb.values()) <= allowed and "PROVEN_REAL" not in set(ra.values()) | set(rb.values())
    for n in (9, 10, 11, 13, 18):
        assert ra[n] == "NOT_YET_PROVEN", n
    assert ra[20] == "PARTIAL"
    assert rb[1] == "NOT_YET_PROVEN" and rb[13] == "NOT_YET_PROVEN" and rb[6] == "UNACCEPTABLE" and rb[16] == "OWNER_ACTION_REQUIRED"
    old = (INFRA / "GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md").read_text()
    assert "Tier0-S" not in old, "the Tier0-A/B table must stay separate and unchanged"


# ---- Q9: the persistence table must not claim stronger enforcement than the gate implements
ENFORCEMENT_VOCAB = {"GATE_CHECKED", "OWNER_PROCEDURE", "DESIGN_ASSUMPTION", "NOT_CHECKED", "NOT_PROVEN"}
GATE_CHECKS_THESE = ("cloud sync", "ai-agent", "docker disk image", "mounted shared volumes")        # the only persistence channels the gate actually inspects (partially)


def _persistence_rows():
    txt = (INFRA / "GENESIS_V2_TIER0S_SEQUENTIAL_SOVEREIGN_ISOLATION.md").read_text()
    section = txt.split("## 6.")[1].split("## 7.")[0]
    rows = []
    for line in section.splitlines():
        if line.startswith("| ") and not line.startswith("| Channel") and not line.startswith("|---"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rows.append(cells)
    return rows


def test_Q9_persistence_table_has_an_explicit_enforcement_column_with_a_closed_vocabulary():
    rows = _persistence_rows()
    assert len(rows) >= 16 and all(len(r) == 4 for r in rows)
    for r in rows:
        assert set(re.findall(r"`([A-Z_]+)`", r[2])) <= ENFORCEMENT_VOCAB and re.findall(r"`([A-Z_]+)`", r[2]), r[0]


def test_Q9_only_channels_the_gate_actually_inspects_may_claim_GATE_CHECKED():
    for r in _persistence_rows():
        claims_gate = "GATE_CHECKED" in r[2]
        may = any(k in r[0].lower() for k in GATE_CHECKS_THESE)
        assert (not claims_gate) or may, f"overstated: {r[0]}"


@pytest.mark.parametrize("channel", ["time machine", "shell history", "spotlight", "sleep", "swap", "crash", "snapshot", "clipboard", "temp"])
def test_Q9_channels_the_gate_does_not_inspect_are_marked_NOT_CHECKED_or_procedural(channel):
    rows = [r for r in _persistence_rows() if channel in r[0].lower()]
    assert rows, channel
    for r in rows:
        assert "GATE_CHECKED" not in r[2] and ("NOT_CHECKED" in r[2] or "OWNER_PROCEDURE" in r[2]), r[0]


def test_Q9_no_document_credits_the_gate_with_checks_it_does_not_perform():
    gate_src = (ROOT / "scripts/genesis_v2_tier0s_phase_gate.py").read_text()
    for forbidden in ("tmutil", "mdutil", "pmset", "snapshot", "pbpaste"):
        assert forbidden not in gate_src, forbidden
    for p in INFRA.glob("GENESIS_V2_TIER0S_*.md"):
        assert "gate/owner check" not in p.read_text(), p.name


def test_remediation_matrix_maps_every_finding_to_a_regression_test_that_exists():
    txt = (INFRA / "GENESIS_V2_TIER0S_AUDIT_REMEDIATION.md").read_text()
    sources = "".join((ROOT / "tests" / f).read_text() for f in ("test_genesis_v2_tier0s_phase_gate.py", "test_genesis_v2_tier0a_transfer_bundle.py"))
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (\d+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`([^`]+)`", line.split(" | ")[3])
        seen[int(m.group(1))] = names
        assert names, f"finding {m.group(1)} has no regression test column"
    assert set(seen) == set(range(1, 16))
    for n, names in seen.items():
        for t in names:
            assert t.startswith("(doc)") or re.search(rf"def {re.escape(t)}\b", sources), f"finding {n}: {t} does not exist"


def test_failopen_matrix_maps_every_Q_finding_to_regression_tests_that_exist():
    txt = (INFRA / "GENESIS_V2_TIER0S_FAILOPEN_REMEDIATION.md").read_text()
    sources = "".join((ROOT / "tests" / f).read_text() for f in ("test_genesis_v2_tier0s_phase_gate.py", "test_genesis_v2_tier0a_transfer_bundle.py"))
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (Q\d+) \| ", line)
        if not m:
            continue
        names = re.findall(r"`(test_[^`]+)`", line)
        seen[m.group(1)] = names
        assert names, f"{m.group(1)} has no regression tests"
        for t in names:
            assert re.search(rf"def {re.escape(t)}\b", sources), f"{m.group(1)}: {t} does not exist"
    assert set(seen) == {f"Q{i}" for i in range(1, 11)}

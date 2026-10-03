"""Tier0-S (Sequential Sovereign Isolation) phase gate v2 + design-doc consistency -- SYNTHETIC. No real boot/reboot is exercised; host telemetry and boot
sessions are injected. Proves the gate's fail-closed LOGIC only. It is a one-shot, advisory, software-level guard against accidental mixing; NOT evidence of a
second boot environment, separate encrypted storage, continuous enforcement, or any protection against a malicious owner/root."""
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("tier0s_gate", ROOT / "scripts" / "genesis_v2_tier0s_phase_gate.py")
G = importlib.util.module_from_spec(_s)
_s.loader.exec_module(G)
INFRA = ROOT / "docs/orneur/phase-21/infrastructure"
BOOT_A, BOOT_B = "11111111-2222-3333-4444-555555555555", "99999999-8888-7777-6666-555555555555"

GOOD_IFCONFIG = "lo0: flags=8049<UP,LOOPBACK,RUNNING,MULTICAST> mtu 16384\n\tinet 127.0.0.1 netmask 0xff000000\n\tinet6 ::1 prefixlen 128\nen0: flags=8863<UP,BROADCAST> mtu 1500\n\tstatus: inactive\n"
GOOD_ROUTES = "Routing tables\n\nInternet:\nDestination        Gateway            Flags               Netif Expire\n127                127.0.0.1          UCS                   lo0\n"
GOOD_LISTENERS = "Active Internet connections (including servers)\nProto Recv-Q Send-Q  Local Address          Foreign Address        (state)\ntcp4       0      0  127.0.0.1.8080         *.*                    LISTEN\n"


def good_host(tmp, **over):
    home = tmp / "home"; home.mkdir(exist_ok=True)
    h = {"processes": ["/sbin/launchd"] + [f"/usr/bin/proc{i}" for i in range(12)], "cmdlines": [f"/usr/bin/proc{i} --flag" for i in range(12)],
         "ifconfig": GOOD_IFCONFIG, "routes4": GOOD_ROUTES, "routes6": GOOD_ROUTES, "listeners": GOOD_LISTENERS, "boot_id": BOOT_A, "volumes": ["Macintosh HD"],
         "home": home, "env": {}, "runtime_sockets_abs": ()}      # absolute socket paths injected empty => hermetic
    h.update(over)
    return h


def make_cfg(tmp, init=True):
    st = tmp / "state"
    if init and not st.exists():
        G.init_state(st)
    code = tmp / "code"
    for rel in G.ROLE_CODE_ALLOWLIST:
        (code / rel).parent.mkdir(parents=True, exist_ok=True); (code / rel).write_text("")
    return {"state_dir": st, "code_root": code, "deny_paths": [tmp / "other_role_store"], "deny_volumes": [], "workspaces": [], "process_allowlist": None}


def run(role, tmp, host=None, cfg=None, **cfg_over):
    c = cfg or make_cfg(tmp); c = {**c, **cfg_over}
    return G.evaluate(role, host=host or good_host(tmp), **c)


def statuses(res):
    return {k: v["status"] for k, v in res.items()}


def failing(res):
    return sorted(k for k, v in res.items() if v["status"] != G.PASS)


# ======================================================================== baseline
def test_fully_configured_clean_synthetic_host_passes_for_both_roles(tmp_path):
    for role in G.ROLES:
        assert G.gate_passes(run(role, tmp_path)), failing(run(role, tmp_path))


# ======================================================================== AUDIT 4: mandatory inputs (no vacuous pass)
@pytest.mark.parametrize("missing,expected", [
    ("state_dir", {"interlock_state_verified", "interlock_other_role_not_this_boot", "role_state_forbidden_material_WEAK"}),
    ("code_root", {"role_code_root_allowlisted"}),
])
def test_AUDIT4_missing_required_path_input_is_fail_closed_not_pass(tmp_path, missing, expected):
    res = run("forge", tmp_path, **{missing: None})
    assert expected <= {k for k, v in res.items() if v["status"] == G.FAIL_CLOSED}
    assert not G.gate_passes(res)


def test_AUDIT4_empty_deny_list_is_fail_closed(tmp_path):
    res = run("forge", tmp_path, deny_paths=[], deny_volumes=[])
    assert res["other_role_storage_unavailable"]["status"] == G.FAIL_CLOSED and not G.gate_passes(res)


def test_AUDIT4_absent_or_uninitialized_state_directory_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path, init=False)
    assert run("forge", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED
    cfg["state_dir"].mkdir(mode=0o700)                       # exists but never initialized
    assert run("forge", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT4_empty_or_missing_code_root_is_fail_closed(tmp_path):
    cfg = make_cfg(tmp_path)
    empty = tmp_path / "empty_code"; empty.mkdir()
    assert run("forge", tmp_path, cfg=cfg, code_root=empty)["role_code_root_allowlisted"]["status"] == G.FAIL_CLOSED
    assert run("forge", tmp_path, cfg=cfg, code_root=tmp_path / "nope")["role_code_root_allowlisted"]["status"] == G.FAIL_CLOSED


def test_AUDIT4_cli_without_required_arguments_prints_fail_closed_and_fails(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge"], capture_output=True, text=True, timeout=120)
    assert p.returncode == 1 and "GATE_FAILS" in p.stdout and "FAIL_CLOSED" in p.stdout and "GATE_PASSES" not in p.stdout


# ======================================================================== AUDIT 5: host-command failures fail closed
@pytest.mark.parametrize("key,check", [("processes", "container_runtime_absent"), ("processes", "cloud_sync_process_absent"), ("processes", "agent_process_absent"),
                                       ("ifconfig", "network_interfaces_disabled"), ("routes4", "network_no_default_route"), ("routes6", "network_no_default_route"),
                                       ("listeners", "network_no_external_listeners"), ("boot_id", "boot_session_identified")])
def test_AUDIT5_unavailable_telemetry_is_fail_closed(tmp_path, key, check):
    res = run("forge", tmp_path, host=good_host(tmp_path, **{key: None}))
    assert res[check]["status"] == G.FAIL_CLOSED and not G.gate_passes(res)


@pytest.mark.parametrize("key,bad,check", [
    ("processes", [], "container_runtime_absent"), ("processes", ["/usr/bin/x"] * 12, "container_runtime_absent"),      # no launchd => implausible `ps`
    ("ifconfig", "", "network_interfaces_disabled"), ("ifconfig", "en0: flags=8863<UP>\n", "network_interfaces_disabled"),   # no loopback => implausible
    ("routes4", "", "network_no_default_route"), ("listeners", "", "network_no_external_listeners"),
    ("boot_id", "not-a-uuid", "boot_session_identified"), ("volumes", None, "other_role_storage_unavailable")])
def test_AUDIT5_empty_or_implausible_output_is_fail_closed_never_a_clean_host(tmp_path, key, bad, check):
    cfg = make_cfg(tmp_path)
    if key == "volumes":
        cfg["deny_volumes"] = ["WitnessVault"]
    res = run("forge", tmp_path, host=good_host(tmp_path, **{key: bad}), cfg=cfg)
    assert res[check]["status"] == G.FAIL_CLOSED


def test_AUDIT5_collect_host_returns_none_when_a_command_fails_or_raises(monkeypatch):
    class P:  # non-zero exit
        returncode, stdout = 1, "partial output"
    monkeypatch.setattr(G.subprocess, "run", lambda *a, **k: P())
    h = G.collect_host()
    assert h["processes"] is None and h["ifconfig"] is None and h["boot_id"] is None and h["listeners"] is None

    def boom(*a, **k):
        raise FileNotFoundError("no such tool")
    monkeypatch.setattr(G.subprocess, "run", boom)
    assert G.collect_host()["ifconfig"] is None


# ======================================================================== AUDIT 1: interlock adversarial cases
def _state(tmp):
    cfg = make_cfg(tmp); return cfg


def test_AUDIT1_valid_previous_role_receipt_from_current_boot_blocks(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    res = run("witness", tmp_path, cfg=cfg)
    assert res["interlock_state_verified"]["status"] == G.PASS and res["interlock_other_role_not_this_boot"]["status"] == G.FAIL


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
    assert r["interlock_state_verified"]["status"] == G.FAIL_CLOSED and not G.gate_passes(r)


def test_AUDIT1_deleting_only_the_receipts_content_is_caught_by_head(tmp_path):
    r = _corrupt_status(tmp_path, lambda d: (d / "receipts.jsonl").write_text(""))
    assert r["interlock_state_verified"]["status"] == G.FAIL_CLOSED and "HEAD does not match" in r["interlock_state_verified"]["detail"]


def test_AUDIT1_corrupt_receipt_with_a_REAL_boot_id_fails_closed(tmp_path):
    """The original finding: this passed (fail-open) and the old test hid it by using the literal boot id 'CORRUPT'."""
    r = _corrupt_status(tmp_path, lambda d: (d / "receipts.jsonl").write_text("garbage not json\n"))
    assert r["interlock_state_verified"]["status"] == G.FAIL_CLOSED and not G.gate_passes(r)


def test_AUDIT1_truncated_receipt_line_fails_closed(tmp_path):
    def cut(d):
        t = (d / "receipts.jsonl").read_text(); (d / "receipts.jsonl").write_text(t[: len(t) // 2])
    assert _corrupt_status(tmp_path, cut)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_dropping_the_tail_receipt_with_a_valid_newline_is_caught_by_head(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_B); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    lines = (cfg["state_dir"] / "receipts.jsonl").read_text().splitlines(True)
    (cfg["state_dir"] / "receipts.jsonl").write_text("".join(lines[:-1]))
    assert run("witness", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_edited_boot_identifier_fails_closed(tmp_path):
    def edit(d):
        t = (d / "receipts.jsonl").read_text(); (d / "receipts.jsonl").write_text(t.replace(BOOT_A, BOOT_B))
    r = _corrupt_status(tmp_path, edit)
    assert r["interlock_state_verified"]["status"] == G.FAIL_CLOSED and "checksum" in r["interlock_state_verified"]["detail"]


def test_AUDIT1_replayed_receipt_fails_closed(tmp_path):
    def replay(d):
        line = (d / "receipts.jsonl").read_text().splitlines()[0]
        with open(d / "receipts.jsonl", "a") as f:
            f.write(line + "\n")
    assert _corrupt_status(tmp_path, replay)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_receipts_copied_from_another_environment_fail_closed(tmp_path):
    other = tmp_path / "other_env"; other.mkdir()
    cfg_o = make_cfg(other); G.append_receipt(cfg_o["state_dir"], "forge", BOOT_B)
    cfg = _state(tmp_path)
    (cfg["state_dir"] / "receipts.jsonl").write_text((cfg_o["state_dir"] / "receipts.jsonl").read_text())
    r = run("witness", tmp_path, cfg=cfg)
    assert r["interlock_state_verified"]["status"] == G.FAIL_CLOSED


@pytest.mark.parametrize("mutate", [
    lambda r: {**r, "role": "oracle"},                       # unknown role
    lambda r: {**r, "boot": "not-a-uuid"},                   # malformed uuid
    lambda r: {**r, "seq": "1"},                             # wrong type
    lambda r: {**r, "extra": 1},                             # extra field
    lambda r: {k: v for k, v in r.items() if k != "prev"},   # missing field
    lambda r: {**r, "seq": True},                            # bool masquerading as int
])
def test_AUDIT1_malformed_fields_and_unknown_roles_fail_closed(tmp_path, mutate):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    p = cfg["state_dir"] / "receipts.jsonl"; rec = json.loads(p.read_text().splitlines()[0])
    p.write_text(json.dumps(mutate(rec), sort_keys=True) + "\n")
    assert run("witness", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_duplicate_keys_sequence_gaps_and_head_mismatch_fail_closed(tmp_path):
    cfg = _state(tmp_path); G.append_receipt(cfg["state_dir"], "forge", BOOT_B); G.append_receipt(cfg["state_dir"], "forge", BOOT_A)
    d = cfg["state_dir"]; good = (d / "receipts.jsonl").read_text()
    (d / "receipts.jsonl").write_text(good.replace('"v":2', '"v":2,"v":2', 1))                       # duplicate JSON key
    assert run("witness", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED
    (d / "receipts.jsonl").write_text("".join(good.splitlines(True)[::-1]))                           # reordered
    assert run("witness", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED
    (d / "receipts.jsonl").write_text(good)
    head = json.loads((d / "HEAD.json").read_text()); head["seq"] = 7; (d / "HEAD.json").write_text(json.dumps(head))
    assert run("witness", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_read_failure_symlink_and_world_writable_dir_fail_closed(tmp_path):
    cfg = _state(tmp_path); d = cfg["state_dir"]
    if os.geteuid() != 0:
        os.chmod(d / "receipts.jsonl", 0)
        assert run("forge", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED
        os.chmod(d / "receipts.jsonl", 0o600)
    real = tmp_path / "real_receipts"; (d / "receipts.jsonl").rename(real); (d / "receipts.jsonl").symlink_to(real)
    assert run("forge", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED
    (d / "receipts.jsonl").unlink(); real.rename(d / "receipts.jsonl")
    os.chmod(d, 0o777)
    assert run("forge", tmp_path, cfg=cfg)["interlock_state_verified"]["status"] == G.FAIL_CLOSED


def test_AUDIT1_init_refuses_to_reinitialize_an_existing_directory(tmp_path):
    cfg = _state(tmp_path)
    with pytest.raises(FileExistsError):
        G.init_state(cfg["state_dir"])


def test_AUDIT2_interlock_is_NOT_a_security_boundary_a_writer_can_reset_it_consistently(tmp_path):
    """Documents the limit. Anyone who can write the state directory can truncate the chain back to genesis, consistently, and the witness gate then passes in
    the SAME boot. The interlock therefore earns no assurance credit against any adversary; cold boot + physical detachment are owner procedures."""
    cfg = _state(tmp_path); d = cfg["state_dir"]; G.append_receipt(d, "forge", BOOT_A)
    env = json.loads((d / "INIT.json").read_text())["env_id"]
    (d / "receipts.jsonl").write_text(""); (d / "HEAD.json").write_text(json.dumps({"v": 2, "env_id": env, "seq": 0, "sum": G.ZERO}, sort_keys=True))
    assert G.gate_passes(run("witness", tmp_path, cfg=cfg))


def test_AUDIT2_begin_requires_a_passing_gate_appends_a_chained_entry_and_then_blocks_the_other_role(tmp_path):
    cfg = _state(tmp_path)
    bad = run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + "utun3: flags=8051<UP,POINTOPOINT>\n\tinet 10.0.0.2 --> 10.0.0.1\n"), cfg=cfg)
    with pytest.raises(PermissionError):
        G.begin("forge", cfg["state_dir"], BOOT_A, bad)
    assert G.verify_state(cfg["state_dir"]) == ([], [])
    G.begin("forge", cfg["state_dir"], BOOT_A, run("forge", tmp_path, cfg=cfg))
    problems, recs = G.verify_state(cfg["state_dir"]); assert problems == [] and len(recs) == 1 and set(recs[0]) == {"v", "env_id", "seq", "role", "boot", "prev", "sum"}
    assert not G.gate_passes(run("witness", tmp_path, cfg=cfg))


# ======================================================================== AUDIT 3 (boot id): per-boot UUID
def test_AUDIT3_only_a_well_formed_per_boot_uuid_is_accepted(tmp_path):
    assert run("forge", tmp_path)["boot_session_identified"]["status"] == G.PASS
    for bad in ("", "1234", "{ sec = 1, usec = 2 } Mon Jan 1", BOOT_A + "x", None):
        assert run("forge", tmp_path, host=good_host(tmp_path, boot_id=bad))["boot_session_identified"]["status"] == G.FAIL_CLOSED


# ======================================================================== AUDIT 6: network
@pytest.mark.parametrize("extra", [
    "utun3: flags=8051<UP,POINTOPOINT,RUNNING,MULTICAST> mtu 1380\n\tinet 10.8.0.2 --> 10.8.0.1 netmask 0xffffffff\n",          # VPN with no status line (original bypass)
    "bridge0: flags=8863<UP,BROADCAST,RUNNING> mtu 1500\n\tinet 192.168.2.1 netmask 0xffffff00\n",                                   # bridge (original bypass)
    "en5: flags=8863<UP,BROADCAST> mtu 1500\n\tinet6 2001:db8::5 prefixlen 64\n",                                                # global IPv6
    "awdl0: flags=8943<UP,BROADCAST,RUNNING> mtu 1500\n\tstatus: active\n",                                                      # active, no address
])
def test_AUDIT6_tunnels_bridges_global_v6_and_active_links_fail(tmp_path, extra):
    assert run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + extra))["network_interfaces_disabled"]["status"] == G.FAIL


def test_AUDIT6_link_local_only_and_inactive_interfaces_pass(tmp_path):
    extra = "utun0: flags=8051<UP,POINTOPOINT> mtu 1380\n\tinet6 fe80::1%utun0 prefixlen 64 scopeid 0x4\n"
    assert run("forge", tmp_path, host=good_host(tmp_path, ifconfig=GOOD_IFCONFIG + extra))["network_interfaces_disabled"]["status"] == G.PASS


def test_AUDIT6_default_routes_fail_in_either_family_and_listeners_only_if_external(tmp_path):
    dflt = GOOD_ROUTES + "default            192.168.1.1        UGScg                 en0\n"
    assert run("forge", tmp_path, host=good_host(tmp_path, routes4=dflt))["network_no_default_route"]["status"] == G.FAIL
    assert run("forge", tmp_path, host=good_host(tmp_path, routes6=dflt))["network_no_default_route"]["status"] == G.FAIL
    ext = GOOD_LISTENERS + "tcp4       0      0  *.5000                 *.*                    LISTEN\n"
    assert run("forge", tmp_path, host=good_host(tmp_path, listeners=ext))["network_no_external_listeners"]["status"] == G.FAIL
    assert run("forge", tmp_path)["network_no_external_listeners"]["status"] == G.PASS         # loopback-only listener is tolerated


def test_AUDIT6_the_gate_is_documented_as_one_shot_not_continuous():
    assert "NOT continuous" in G.__doc__ and "WHOLE phase" in G.__doc__


# ======================================================================== AUDIT 7: runtime / control plane
@pytest.mark.parametrize("name", ["colima", "limactl", "qemu-system-aarch64", "podman", "krunkit", "vfkit", "OrbStack Helper", "rancher-desktop", "nerdctl", "lima",
                                  "com.apple.Virtualization.VirtualMachine", "com.docker.backend", "Docker Desktop", "dockerd", "containerd", "VBoxHeadless", "vmware-vmx"])
def test_AUDIT7_original_bypass_runtimes_are_now_detected(tmp_path, name):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/local/bin/" + name])
    assert run("forge", tmp_path, host=h)["container_runtime_absent"]["status"] == G.FAIL


def test_AUDIT7_benign_lookalike_process_names_do_not_trip_the_runtime_check(tmp_path):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/bin/Climate", "/usr/bin/dockets"])
    assert run("forge", tmp_path, host=h)["container_runtime_absent"]["status"] == G.PASS


def test_AUDIT7_runtime_sockets_install_dirs_and_env_are_detected_without_a_running_process(tmp_path):
    home = tmp_path / "home"; home.mkdir()
    (home / ".colima").mkdir()
    assert run("forge", tmp_path)["container_runtime_absent"]["status"] == G.FAIL
    (home / ".colima").rmdir(); (home / ".docker" / "run").mkdir(parents=True); (home / ".docker" / "run" / "docker.sock").write_text("")
    assert run("forge", tmp_path)["container_runtime_absent"]["status"] == G.FAIL
    import shutil; shutil.rmtree(home / ".docker")
    assert run("forge", tmp_path, host=good_host(tmp_path, env={"DOCKER_HOST": "unix:///x"}))["container_runtime_absent"]["status"] == G.FAIL


def test_AUDIT7_optional_process_allowlist_is_stricter_than_the_denylist(tmp_path):
    base = good_host(tmp_path)["processes"]
    names = {os.path.basename(p) for p in base}
    assert run("forge", tmp_path, process_allowlist=names)["process_allowlist_respected"]["status"] == G.PASS
    h = good_host(tmp_path, processes=base + ["/x/mystery-runtime"])
    assert run("forge", tmp_path, host=h, process_allowlist=names)["process_allowlist_respected"]["status"] == G.FAIL
    assert "process_allowlist_respected" not in run("forge", tmp_path)


def test_AUDIT7_the_detection_is_documented_as_not_exhaustive(tmp_path):
    assert "NOT exhaustive" in run("forge", tmp_path)["container_runtime_absent"]["detail"] and "NOT exhaustive" in G.__doc__


# ======================================================================== AUDIT 9: process absence != exposure absence
def test_AUDIT9_stopped_sync_client_with_synchronized_data_still_fails_on_exposure(tmp_path):
    home = tmp_path / "home"; (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs").mkdir(parents=True)
    (home / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "x.txt").write_text("synthetic")
    r = run("forge", tmp_path)
    assert r["cloud_sync_process_absent"]["status"] == G.PASS and "PROCESS_NOT_RUNNING" in r["cloud_sync_process_absent"]["detail"]
    assert r["cloud_sync_residual_exposure_absent"]["status"] == G.FAIL and "RESIDUAL_EXPOSURE_PRESENT" in r["cloud_sync_residual_exposure_absent"]["detail"]
    assert not G.gate_passes(r)


def test_AUDIT9_stopped_agent_with_transcript_or_index_stores_still_fails_on_exposure(tmp_path):
    home = tmp_path / "home"
    for rel in (".claude/projects", "Library/Application Support/Cursor/User/History", ".codex"):
        (home / rel).mkdir(parents=True); (home / rel / "session.db").write_text("synthetic")
    r = run("forge", tmp_path)
    assert r["agent_process_absent"]["status"] == G.PASS
    assert r["agent_residual_exposure_absent"]["status"] == G.FAIL and "3 of" in r["agent_residual_exposure_absent"]["detail"]


def test_AUDIT9_empty_locations_and_a_clean_home_report_no_residual_exposure_DETECTED_only(tmp_path):
    (tmp_path / "home" / ".claude").mkdir(parents=True)
    r = run("forge", tmp_path)
    assert r["agent_residual_exposure_absent"]["status"] == G.PASS and "NO_RESIDUAL_EXPOSURE_DETECTED" in r["agent_residual_exposure_absent"]["detail"]


@pytest.mark.parametrize("proc,key", [("Dropbox", "cloud_sync_process_absent"), ("syncthing", "cloud_sync_process_absent"), ("Cursor Helper", "agent_process_absent"),
                                       ("codex", "agent_process_absent"), ("ollama", "agent_process_absent")])
def test_AUDIT9_running_sync_clients_and_agents_fail(tmp_path, proc, key):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/x/" + proc])
    assert run("forge", tmp_path, host=h)[key]["status"] == G.FAIL


def test_AUDIT9_agent_run_via_a_generic_interpreter_is_caught_by_command_line(tmp_path):
    h = good_host(tmp_path, cmdlines=good_host(tmp_path)["cmdlines"] + ["node /opt/lib/@anthropic-ai/claude-code/cli.js --resume"])
    assert run("forge", tmp_path, host=h)["agent_process_absent"]["status"] == G.FAIL


def test_AUDIT9_apple_system_daemons_and_cursor_ui_service_are_not_false_positives(tmp_path):
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/usr/libexec/bird", "/usr/libexec/cloudd", "/usr/libexec/fileproviderd", "/System/CursorUIViewService"])
    r = run("forge", tmp_path, host=h)
    assert r["cloud_sync_process_absent"]["status"] == G.PASS and r["agent_process_absent"]["status"] == G.PASS


@pytest.mark.parametrize("sub,expect_fail", [("Documents/role_work", True), ("Desktop", True), ("Library/Mobile Documents/x", True), ("elsewhere/role_work", False)])
def test_AUDIT9_role_workspace_inside_synced_or_user_documents_paths_fails(tmp_path, sub, expect_fail):
    ws = tmp_path / "home" / sub; ws.mkdir(parents=True)
    r = run("forge", tmp_path, workspaces=[ws])
    assert (r["workspace_not_in_synced_or_user_documents_path"]["status"] == G.FAIL) is expect_fail


# ======================================================================== AUDIT 10: physical detachment evidence
def test_AUDIT10_other_role_storage_present_or_mounted_fails_and_absent_passes(tmp_path):
    store = tmp_path / "witness_store"; store.mkdir()
    assert run("forge", tmp_path, deny_paths=[store])["other_role_storage_unavailable"]["status"] == G.FAIL
    assert run("forge", tmp_path)["other_role_storage_unavailable"]["status"] == G.PASS
    cfg = make_cfg(tmp_path)
    r = run("forge", tmp_path, host=good_host(tmp_path, volumes=["Macintosh HD", "WitnessVault"]), cfg=cfg, deny_paths=[], deny_volumes=["WitnessVault"])
    assert r["other_role_storage_unavailable"]["status"] == G.FAIL


def test_AUDIT14_dangling_symlink_to_the_other_role_store_counts_as_present(tmp_path):
    (tmp_path / "alias").symlink_to(tmp_path / "nowhere")
    assert run("forge", tmp_path, deny_paths=[tmp_path / "alias"])["other_role_storage_unavailable"]["status"] == G.FAIL


# ======================================================================== Qualification exclusion by allowlist
def test_allowlisted_code_root_passes_and_any_extra_file_fails(tmp_path):
    cfg = make_cfg(tmp_path)
    assert run("witness", tmp_path, cfg=cfg)["role_code_root_allowlisted"]["status"] == G.PASS
    pyc = cfg["code_root"] / "orca" / "__pycache__"; pyc.mkdir(); (pyc / "x.cpython-311.pyc").write_bytes(b"")
    assert run("witness", tmp_path, cfg=cfg)["role_code_root_allowlisted"]["status"] == G.PASS
    for extra in ("orca/eval/genesis_v2/runner_qualification.py", "orca/eval/genesis_v2/ledger.py", "orca/eval/genesis_v2/operational_boundary.py", "docs/anything.md", "tests/t.py", ".git/config"):
        f = cfg["code_root"] / extra; f.parent.mkdir(parents=True, exist_ok=True); f.write_text("")
        assert run("witness", tmp_path, cfg=cfg)["role_code_root_allowlisted"]["status"] == G.FAIL, extra
        f.unlink()


def test_code_root_symlinks_fail(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["code_root"] / "link").symlink_to(tmp_path)
    assert run("witness", tmp_path, cfg=cfg)["role_code_root_allowlisted"]["status"] == G.FAIL


def test_the_full_repository_is_rejected_as_a_role_code_root():
    h = {"processes": ["/sbin/launchd"] + ["/x"] * 12, "cmdlines": ["x"] * 12, "ifconfig": GOOD_IFCONFIG, "routes4": GOOD_ROUTES, "routes6": GOOD_ROUTES, "listeners": GOOD_LISTENERS,
         "boot_id": BOOT_A, "volumes": [], "home": Path("/nonexistent-home"), "env": {}, "runtime_sockets_abs": ()}
    r = G.evaluate("forge", host=h, state_dir=None, code_root=ROOT / "orca", deny_paths=["/nonexistent"], deny_volumes=[], workspaces=[])
    assert r["role_code_root_allowlisted"]["status"] == G.FAIL


# ======================================================================== owner-key claim is WEAK evidence
@pytest.mark.parametrize("role,name,bad", [("forge", "vault_private_key", True), ("witness", "vault_private_key", False), ("witness", "corpus_secret", True),
                                           ("forge", "corpus_secret", False), ("forge", "owner_signing_key.pem", True), ("witness", "owner-signing-key", True),
                                           ("forge", "vault_public_key", False)])
def test_role_state_forbidden_material_by_name(tmp_path, role, name, bad):
    cfg = make_cfg(tmp_path); (cfg["state_dir"] / name).write_bytes(b"")
    assert (run(role, tmp_path, cfg=cfg)["role_state_forbidden_material_WEAK"]["status"] == G.FAIL) is bad


def test_a_key_header_in_an_innocently_named_file_is_caught_but_a_renamed_encoded_key_is_not(tmp_path):
    cfg = make_cfg(tmp_path)
    (cfg["state_dir"] / "notes.bin").write_bytes(b"-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA")
    r = run("forge", tmp_path, cfg=cfg)["role_state_forbidden_material_WEAK"]
    assert r["status"] == G.FAIL and "WEAK" in r["detail"]
    (cfg["state_dir"] / "notes.bin").write_bytes(b"c3ludGhldGljLWJhc2U2NC1lbmNvZGVkLWtleQ==")      # documents the weakness: not detected
    assert run("forge", tmp_path, cfg=cfg)["role_state_forbidden_material_WEAK"]["status"] == G.PASS


# ======================================================================== output hygiene
def test_results_expose_only_counts_never_paths_names_or_command_lines(tmp_path):
    store = tmp_path / "SENTINEL_STORE_NAME"; store.mkdir()
    h = good_host(tmp_path, processes=good_host(tmp_path)["processes"] + ["/x/SentinelDockerHelper-docker"], cmdlines=good_host(tmp_path)["cmdlines"] + ["node @anthropic-ai/SENTINEL_ARG"])
    blob = json.dumps(run("forge", tmp_path, host=h, deny_paths=[store]))
    for s in ("SENTINEL_STORE_NAME", "SentinelDockerHelper", "SENTINEL_ARG", str(tmp_path)):
        assert s not in blob


def test_live_check_is_read_only_and_fails_on_this_unprovisioned_host(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge", "--state-dir", str(tmp_path / "s"),
                        "--code-root", str(ROOT / "orca"), "--deny-path", str(tmp_path / "other")], capture_output=True, text=True, timeout=180)
    assert p.stdout.strip().splitlines()[-1] in ("GATE_PASSES", "GATE_FAILS")
    assert not (tmp_path / "s").exists(), "check must be read-only"
    assert "GATE_FAILS" in p.stdout            # the full repo, uninitialized state dir etc. can never pass; an environment that passes must be dedicated


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


def test_remediation_matrix_maps_every_finding_to_a_regression_test_that_exists():
    txt = (INFRA / "GENESIS_V2_TIER0S_AUDIT_REMEDIATION.md").read_text()
    sources = (ROOT / "tests/test_genesis_v2_tier0s_phase_gate.py").read_text() + (ROOT / "tests/test_genesis_v2_tier0a_transfer_bundle.py").read_text()
    seen = {}
    for line in txt.splitlines():
        m = re.match(r"^\| (\d+) \| ", line)
        if not m:
            continue
        cells = line.split(" | ")
        names = re.findall(r"`([^`]+)`", cells[3])
        seen[int(m.group(1))] = names
        assert names, f"finding {m.group(1)} has no regression test column"
    assert set(seen) == set(range(1, 16))
    for n, names in seen.items():
        for t in names:
            assert t.startswith("(doc)") or re.search(rf"def {re.escape(t)}\b", sources), f"finding {n}: {t} does not exist"
        assert any(t.startswith("(doc)") or t.startswith("test_") for t in names)

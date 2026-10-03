"""Tier0-S (Sequential Sovereign Isolation) phase gate + design-doc consistency -- SYNTHETIC. No real boot/reboot is exercised; boot sessions are
injected. Proves the gate's logic only (accidental-mixing guard enforced by software on the guarded machine); it is NOT evidence of a second boot
environment, separate encrypted storage, or any protection against a malicious owner/root."""
import importlib.util
import json
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
QUIET_IFCONFIG = "lo0: flags=8049<UP,LOOPBACK>\n\tinet 127.0.0.1\nen0: flags=8863<UP>\n\tstatus: inactive\n"
UP_IFCONFIG = "lo0: flags=8049<UP,LOOPBACK>\n\tinet 127.0.0.1\nen0: flags=8863<UP>\n\tstatus: active\n"


def run(role, tmp, *, procs=("launchd", "bash"), ifc=QUIET_IFCONFIG, boot="bootA", deny=(), code_root=None):
    return G.evaluate(role, processes=list(procs), ifconfig_text=ifc, boot_id=boot, state_dir=tmp / "state", deny_paths=list(deny), code_root=code_root)


def failing(res):
    return sorted(k for k, v in res.items() if not v["ok"])


def test_clean_environment_passes_for_both_roles(tmp_path):
    for role in G.ROLES:
        assert G.gate_passes(run(role, tmp_path))


@pytest.mark.parametrize("proc,check", [("com.docker.backend", "no_container_daemon_alive"), ("dockerd", "no_container_daemon_alive"),
                                         ("bird", "no_cloud_sync_processes"), ("cloudd", "no_cloud_sync_processes"), ("claude", "no_ai_agent_tooling_running")])
def test_live_daemon_cloud_sync_or_agent_tooling_fails_the_gate(tmp_path, proc, check):
    assert failing(run("forge", tmp_path, procs=("launchd", "/usr/libexec/" + proc))) == [check]


def test_active_network_interface_fails_and_loopback_or_inactive_does_not(tmp_path):
    assert failing(run("witness", tmp_path, ifc=UP_IFCONFIG)) == ["network_disabled"]
    assert G.active_interfaces(QUIET_IFCONFIG) == [] and G.active_interfaces(UP_IFCONFIG) == ["en0"]


def test_other_role_secret_store_visible_fails_the_gate(tmp_path):
    store = tmp_path / "witness_secret_store"; store.mkdir()
    assert failing(run("forge", tmp_path, deny=[store])) == ["other_role_secret_store_not_visible"]
    assert G.gate_passes(run("forge", tmp_path, deny=[tmp_path / "absent"]))


def test_a_full_reboot_is_required_between_roles_but_same_role_repeats_are_fine(tmp_path):
    state = tmp_path / "state"
    G.begin("forge", state, "bootA", run("forge", tmp_path, boot="bootA"))
    assert G.gate_passes(run("forge", tmp_path, boot="bootA"))                       # same role, same boot: allowed
    assert failing(run("witness", tmp_path, boot="bootA")) == ["full_reboot_since_other_role"]   # other role, same boot: refused
    assert G.gate_passes(run("witness", tmp_path, boot="bootB"))                     # after a cold boot: allowed


def test_begin_refuses_when_the_gate_fails_and_writes_an_owner_only_append_only_receipt_when_it_passes(tmp_path):
    state = tmp_path / "state"
    with pytest.raises(PermissionError):
        G.begin("forge", state, "bootA", run("forge", tmp_path, ifc=UP_IFCONFIG))
    assert not (state / "phase_receipts.jsonl").exists()
    G.begin("forge", state, "bootA", run("forge", tmp_path))
    G.begin("forge", state, "bootA", run("forge", tmp_path))
    f = state / "phase_receipts.jsonl"
    assert oct(f.stat().st_mode & 0o777) == "0o600" and len(f.read_text().splitlines()) == 2
    assert set(json.loads(f.read_text().splitlines()[0])) == {"role", "boot"}      # no secrets, no hostnames


def test_a_corrupt_receipt_blocks_rather_than_passes(tmp_path):
    state = tmp_path / "state"; state.mkdir()
    (state / "phase_receipts.jsonl").write_text("not json\n")
    assert failing(run("forge", tmp_path, boot="CORRUPT")) == ["full_reboot_since_other_role"]


@pytest.mark.parametrize("role,name,bad", [("forge", "vault_private_key", True), ("witness", "vault_private_key", False),
                                           ("witness", "corpus_secret", True), ("forge", "corpus_secret", False),
                                           ("forge", "owner_signing_key.pem", True), ("witness", "owner-signing-key", True), ("forge", "vault_public_key", False)])
def test_role_state_directory_forbidden_material_by_name(tmp_path, role, name, bad):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / name).write_bytes(b"")          # empty synthetic marker file; the gate only looks at names
    assert (failing(run(role, tmp_path)) == ["no_forbidden_material_in_role_state"]) is bad


def test_qualification_code_present_fails_the_gate(tmp_path):
    code = tmp_path / "code" / "orca" / "eval" / "genesis_v2"; code.mkdir(parents=True)
    (code / "store.py").write_text("")
    assert G.gate_passes(run("witness", tmp_path, code_root=tmp_path / "code"))
    (code / "runner_qualification.py").write_text("")
    assert failing(run("witness", tmp_path, code_root=tmp_path / "code")) == ["qualification_code_absent"]


def test_results_expose_only_counts_never_paths_names_or_values(tmp_path):
    store = tmp_path / "SENTINEL_PATH_NAME"; store.mkdir()
    res = run("forge", tmp_path, procs=("/x/com.docker.backend", "/x/claude"), deny=[store])
    blob = json.dumps(res)
    assert "SENTINEL_PATH_NAME" not in blob and "com.docker.backend" not in blob and str(tmp_path) not in blob


def test_boot_session_id_is_stable_per_boot_and_changes_across_boots():
    a = G.boot_session_id("{ sec = 1, usec = 2 } x"); b = G.boot_session_id("{ sec = 9, usec = 2 } y")
    assert a == G.boot_session_id("{ sec = 1, usec = 2 } x") and a != b and len(a) == 16


def test_live_cli_runs_read_only_and_reports_a_gate_verdict(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT / "scripts/genesis_v2_tier0s_phase_gate.py"), "check", "--role", "forge", "--state-dir", str(tmp_path / "s")],
                       capture_output=True, text=True, timeout=60)
    assert p.stdout.strip().splitlines()[-1] in ("GATE_PASSES", "GATE_FAILS")
    assert not (tmp_path / "s").exists(), "check must be read-only"


# ---------------------------------------------------------------- design-doc consistency
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


def test_tier0s_status_tables_are_separate_complete_and_never_proven_real():
    txt = (INFRA / "GENESIS_V2_TIER0S_ACCEPTANCE_STATUS.md").read_text()
    allowed = {"PROVEN_SYNTHETIC_ONLY", "PARTIAL", "NOT_YET_PROVEN", "OWNER_ACTION_REQUIRED", "UNACCEPTABLE"}
    a, b = txt.split("## B. Required invariants")
    rows_a = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\| (\d+) \| [^|]+\| `([A-Z_]+)` \|", a, re.M)}
    rows_b = {int(m.group(1)): m.group(2) for m in re.finditer(r"^\| (\d+) \| [^|]+\| `([A-Z_]+)` \|", b, re.M)}
    assert set(rows_a) == set(range(1, 23)) and set(rows_b) == set(range(1, 16))
    assert set(rows_a.values()) | set(rows_b.values()) <= allowed
    assert "PROVEN_REAL" not in set(rows_a.values()) | set(rows_b.values())
    for n in (9, 10, 13, 18):
        assert rows_a[n] == "NOT_YET_PROVEN", "checks needing a second boot environment must not be faked"
    assert rows_b[6] == "UNACCEPTABLE"          # cloud-sync channel on the daily-driver
    old = (INFRA / "GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md").read_text()
    assert "Tier0-S" not in old, "the Tier0-A/B table must stay separate and unchanged"

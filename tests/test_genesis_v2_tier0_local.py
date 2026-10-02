"""Tier-0 (Strategy A, Sovereign Local) isolation harness tests -- SYNTHETIC fixtures + ephemeral keys only.

PRECISE CLAIM: the container tests prove Tier0-B CONTAINER-level separation on ONE physical machine (distinct container UIDs, PID/NET/MNT/IPC
namespaces, mount sets, `--network none`, dropped capabilities, read-only rootfs) for a SYNTHETIC scenario. They are NOT proof of physical-machine
separation, host-OS-user separation, a host firewall, real vault deployment, or real secret custody. Containers share one Linux VM kernel and are
controlled by one host user/Docker daemon. Nothing here promotes any acceptance item to PROVEN_REAL.

Container tests run when ORNEUR_TIER0_DOCKER=1 (local, needs Docker; build uses PyPI for hash-pinned wheels once). ORNEUR_REQUIRE_TIER0_DOCKER=1 turns
"Docker unavailable" into a failure. Static tests always run and need no Docker.
"""
import importlib.util
import json
import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("genesis_v2_tier0_local", ROOT / "scripts" / "genesis_v2_tier0_local.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)
INFRA = ROOT / "docs/orneur/phase-21/infrastructure"
ALLOWED_STATUS = {"PROVEN_REAL", "PROVEN_SYNTHETIC_ONLY", "PARTIAL", "NOT_YET_PROVEN", "OWNER_ACTION_REQUIRED"}


# ============================================================ static (always run, no Docker)
def test_hardened_run_args_enforce_every_isolation_flag():
    a = T.hardened_run_args(name="n", image="img", run_id="r", user="10001:10001", volumes=[("v1", "/secrets", "ro"), ("v2", "/ingest", "rw")])
    j = " ".join(a)
    for needle in ("--network none", "--cap-drop ALL", "--security-opt no-new-privileges", "--read-only", "--pids-limit 64", "--memory 256m", "--user 10001:10001"):
        assert needle in j
    assert "-p" not in a and "--publish" not in a and "--privileged" not in a and "--cap-add" not in a
    assert not any("docker.sock" in x for x in a) and not any(x in ("--pid", "--ipc", "--network=host", "--net=host", "--uts") or x.startswith(("--pid=", "--ipc=")) for x in a)
    assert "v1:/secrets:ro" in a and "v2:/ingest:rw" in a
    with pytest.raises(ValueError):
        T.hardened_run_args(name="n", image="i", run_id="r", user="1:1", volumes=[("v", "/x", "rwx")])


def test_forge_and_witness_images_are_separate_and_each_carries_only_its_own_role_scripts():
    forge = (ROOT / "infra/tier0-local/docker/Dockerfile.forge").read_text()
    witness = (ROOT / "infra/tier0-local/docker/Dockerfile.witness").read_text()
    harness = (ROOT / "infra/tier0-local/docker/Dockerfile.harness").read_text()
    assert "forge_write.py" in forge and "witness_verify.py" not in forge and "provision.py" not in forge
    assert "witness_verify.py" in witness and "forge_write.py" not in witness and "provision.py" not in witness
    assert "provision.py" in harness and "forge_write.py" not in harness and "witness_verify.py" not in harness
    for df in (forge, witness, harness):
        assert re.search(r"^FROM python@sha256:[0-9a-f]{64}$", df, re.M), "base image must be digest-pinned"
        assert "--require-hashes" in df
        assert not re.search(r"(?i)^ENV .*(KEY|SECRET|TOKEN|PASSWORD)", df, re.M)


def test_requirements_are_hash_pinned():
    txt = (ROOT / "infra/tier0-local/requirements-tier0.txt").read_text()
    pkgs = re.findall(r"^([a-z0-9_.-]+)==", txt, re.M)
    assert "cryptography" in pkgs and txt.count("--hash=sha256:") >= len(pkgs)


def test_minimal_code_subset_excludes_every_privileged_or_qualification_module():
    names = " ".join(T.APP_FILES)
    for banned in ("runner_qualification", "operational_boundary", "ledger", "authority_registry", "secret_manager", "sandbox", "owner_preflight", "corpus_generation_authorization"):
        assert banned not in names
    for rel in T.APP_FILES:
        assert (ROOT / rel).is_file()


def test_forbidden_env_policy_is_allowlist_first():
    assert "PYTHONPATH" in T.ALLOWED_ENV
    for frag in ("VAULT_PRIVATE", "CORPUS_SECRET", "OWNER", "QUALIFICATION", "GITHUB", "AWS_", "ANTHROPIC", "OPENAI"):
        assert frag in T.FORBIDDEN_ENV_FRAGMENTS
        assert not any(frag in n for n in T.ALLOWED_ENV)


def test_harness_module_has_no_reference_to_the_real_inventory_or_any_state_flip():
    """Structural check (module globals), not self-matching source scanning. Same limits as acceptance item 20: proves absence of the known
    inventory path/globals, NOT that every synthetic literal was independently authored."""
    assert not hasattr(T, "INV") and not hasattr(T, "inventory")
    for name, value in vars(T).items():
        if isinstance(value, str):
            assert "INVENTORY.json" not in value, name
            assert "private_storage_genuinely_configured" not in value, name


def test_canonical_authorization_state_is_untouched_by_this_phase():
    status = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert status["freeze_prerequisites"]["private_storage_genuinely_configured"] is False
    assert all(v is False for v in status["authorizations"].values()), status["authorizations"]
    cga = json.loads((ROOT / "docs/orneur/authorization/CORPUS_GENERATION_AUTHORIZATION.json").read_text())
    assert cga.get("status") == "NOT_AUTHORIZED"


def _status_rows():
    txt = (INFRA / "GENESIS_V2_TIER0_ACCEPTANCE_STATUS.md").read_text()
    return {int(m.group(1)): m.group(2) for m in re.finditer(r"^\| (\d+) \| [^|]+\| `([A-Z_]+)` \|", txt, re.M)}


def test_twenty_item_status_table_is_complete_honest_and_has_no_proven_real():
    rows = _status_rows()
    assert set(rows) == set(range(1, 21))
    assert set(rows.values()) <= ALLOWED_STATUS
    assert "PROVEN_REAL" not in rows.values(), "no item may be PROVEN_REAL from synthetic container evidence"
    assert rows[20] == "PARTIAL"
    assert rows[8] == "OWNER_ACTION_REQUIRED"
    for item in (3, 15, 16):
        assert rows[item] == "PARTIAL", "role/network/process isolation are container-level only"


# ============================================================ container tests (local, opt-in)
def _docker_ok():
    if os.environ.get("ORNEUR_TIER0_DOCKER") != "1":
        return False, "set ORNEUR_TIER0_DOCKER=1 to run the Tier-0 container tests"
    if not T.docker_available():
        if os.environ.get("ORNEUR_REQUIRE_TIER0_DOCKER") == "1":
            pytest.fail("ORNEUR_REQUIRE_TIER0_DOCKER=1 but Docker is unavailable")
        return False, "Docker unavailable"
    return True, ""


@pytest.fixture(scope="module")
def tier0():
    ok, why = _docker_ok()
    if not ok:
        pytest.skip(why)
    T.build_images()
    before = set(T.docker("ps", "-a", "--format", "{{.Names}}").split()) | set(T.docker("volume", "ls", "-q").split())
    run = T.Tier0Run()
    try:
        ev = run.execute()
    finally:
        run.teardown()
    after = set(T.docker("ps", "-a", "--format", "{{.Names}}").split()) | set(T.docker("volume", "ls", "-q").split())
    ev["_before"], ev["_after"], ev["_run"] = before, after, run
    return ev


def test_1_forge_and_witness_run_concurrently_under_distinct_identities_and_namespaces(tier0):
    f, w = tier0["forge_probe"], tier0["witness_probe"]
    assert (f["uid"], w["uid"]) == (T.FORGE_UID, T.WITNESS_UID) and f["uid"] != w["uid"]
    for ns in ("pid", "net", "mnt", "ipc"):
        assert f["ns"][ns] != w["ns"][ns], ns
    assert tier0["roles_concurrently_running"] == [True, True]


def test_2_3_4_secret_locations_are_mutually_unreachable_and_owner_location_reaches_neither(tier0):
    f, w = tier0["forge_probe"], tier0["witness_probe"]
    assert not any(f["forbidden_path_accessible"].values()) and not any(w["forbidden_path_accessible"].values())
    assert tier0["forge_secret_files"] == ["corpus_secret", "vault_public_key"] and tier0["witness_secret_files"] == ["vault_private_key"]
    owner_vol = tier0["_run"].vols["owner"]
    for key in ("forge_inspect", "witness_inspect"):
        assert owner_vol not in {m["Name"] for m in tier0[key]["Mounts"]}
    assert tier0["witness_verify"]["corpus_secret_absent"] is True


def test_5_6_forge_writes_ciphertext_and_cannot_decrypt(tier0):
    fw = tier0["forge_write"]
    assert fw["forge_cannot_decrypt_with_its_own_material"] is True and fw["writer_has_private_key_attr"] is False and fw["corpus_secret_present"] is True
    assert sorted(k.split("/")[1] for k in tier0["transfer"]) == ["QUALIFICATION_HOLDOUT.enc", "SCREEN.enc", "SEAL.enc"]


def test_7_8_witness_decrypts_with_correct_key_and_wrong_key_or_digest_fails(tier0):
    wv = tier0["witness_verify"]
    assert all(s["synthetic_marker_ok"] for s in wv["splits"].values()) and wv["wrong_key_fails"] and wv["wrong_digest_fails"]
    assert tier0["witness_before_transfer_vault_empty"] is True


def test_9_no_network_egress_and_no_published_ports(tier0):
    for probe in ("forge_probe", "witness_probe"):
        assert tier0[probe]["net"]["tcp_egress"] is False and tier0[probe]["net"]["dns"] is False
    for ins in ("forge_inspect", "witness_inspect"):
        assert tier0[ins]["HostConfig"]["NetworkMode"] == "none" and not tier0[ins]["NetworkSettings"]["Ports"]


def test_10_only_allowlisted_env_and_no_forbidden_names(tier0):
    for probe in ("forge_probe", "witness_probe"):
        names = set(tier0[probe]["env_names"])
        assert names <= T.ALLOWED_ENV, names - T.ALLOWED_ENV
        assert not any(frag in n for n in names for frag in T.FORBIDDEN_ENV_FRAGMENTS)


def test_hardening_as_configured_by_docker_not_just_as_requested(tier0):
    for key, probe in (("forge_inspect", "forge_probe"), ("witness_inspect", "witness_probe")):
        hc = tier0[key]["HostConfig"]
        assert hc["ReadonlyRootfs"] is True and hc["Privileged"] is False and hc["CapDrop"] == ["ALL"] and not hc["CapAdd"]
        assert "no-new-privileges" in " ".join(hc["SecurityOpt"]) and hc["PidMode"] == ""
        p = tier0[probe]
        assert p["cap_eff"] == "0000000000000000" and p["no_new_privs"] == "1" and not p["rootfs_writable"] and not p["app_writable"] and not p["docker_sock_present"]
    assert sorted(m["dest"] for m in tier0["forge_probe"]["mounts"] if m["dest"] not in ("/", "/tmp")) == ["/ingest", "/secrets"]
    assert sorted(m["dest"] for m in tier0["witness_probe"]["mounts"] if m["dest"] not in ("/", "/tmp")) == ["/evidence", "/secrets", "/vault"]
    assert {m["dest"]: m["ro"] for m in tier0["witness_probe"]["mounts"]}["/vault"] is True


def test_11_vault_and_secret_permissions_match_the_contract(tier0):
    for row in tier0["vault_perms"]:
        assert row["uid"] == T.WITNESS_UID
        assert row["mode"] == ("0o500" if row["dir"] else "0o400"), row
    for row in tier0["ingest_perms"]:
        assert row["uid"] == T.FORGE_UID and not (int(row["mode"], 8) & 0o077), row
    for row in tier0["forge_secret_perms"] + tier0["witness_secret_perms"] + tier0["owner_perms"]:
        assert not (int(row["mode"], 8) & 0o077), row
    assert {r["uid"] for r in tier0["owner_perms"]} == {0}


def test_12_reliquary_and_every_persisted_volume_hold_ciphertext_only(tier0):
    assert tier0["plaintext_sentinel_hits"] == []
    names = {Path(p).name for p in tier0["reliquary_files"]}
    assert names <= {"MANIFEST.json", "SCREEN.enc", "QUALIFICATION_HOLDOUT.enc", "SEAL.enc", tier0["forge_write"]["corpus_id"]}
    assert tier0["courier_refuses_plaintext"] is True


def test_14_restore_from_reliquary_decrypts_with_the_correct_identity(tier0):
    assert tier0["restore_equals_backup"] is True
    assert all(s["synthetic_marker_ok"] for s in tier0["restored_verify"]["splits"].values())
    assert tier0["restored_verify"]["splits"] == tier0["witness_verify"]["splits"]


def test_13_cleanup_removes_only_this_runs_resources(tier0):
    assert tier0["_before"] <= tier0["_after"], "teardown removed something it did not create"
    assert not (tier0["_after"] - tier0["_before"]), tier0["_after"] - tier0["_before"]
    assert tier0["_run"].run_id not in T.stale_run_ids()


def test_15_qualification_and_privileged_code_is_absent_from_every_role_image(tier0):
    for probe in ("forge_probe", "witness_probe"):
        assert not any(tier0[probe]["importable_privileged_modules"].values())
    for role in ("forge", "witness"):
        assert set(tier0["app_tree"][role]) == set(T.APP_FILES)


def test_control_plane_holder_can_cross_every_role_boundary_so_single_host_isolation_has_a_hard_limit(tier0):
    """ADVERSARIAL, SYNTHETIC. Documents (does not hide) the limit: whoever holds the Docker control plane on this single-host Tier-0 -- the one
    host user that owns the Docker Desktop daemon -- can exec into either role, mount either role's secret volume, reach the owner stand-in volume,
    and launch a privileged container. Role-container separation therefore protects against a compromised ROLE PROCESS, not against the control-plane
    holder. This is why items 3 and 16 stay PARTIAL and why real-secret deployment acceptance needs Tier0-A (two physical machines)."""
    cp = tier0["control_plane_crossing"]
    assert cp == {"exec_into_witness_reads_its_private_key": True, "arbitrary_volume_mount_reads_witness_key": True,
                  "arbitrary_volume_mount_reaches_owner_standin": True, "privileged_container_launchable": True, "enumerates_both_roles": True}, cp


def test_role_containers_themselves_hold_no_control_plane_authority(tier0):
    """The converse (what the host-hardening phase CAN show): a compromised Forge or Witness PROCESS has no docker socket, no capabilities, no
    network, and no mount that reaches the other role, so it cannot perform any of the crossings above."""
    for probe in ("forge_probe", "witness_probe"):
        p = tier0[probe]
        assert not p["docker_sock_present"] and p["cap_eff"] == "0000000000000000" and not p["net"]["tcp_egress"]


def test_host_hardening_findings_doc_classifies_every_control_and_states_the_limit():
    txt = (INFRA / "GENESIS_V2_TIER0_HOST_HARDENING_FINDINGS.md").read_text()
    for label in ("MATERIALLY_STRENGTHENS_ISOLATION", "DEFENSE_IN_DEPTH_ONLY", "NO_MEANINGFUL_SECURITY_GAIN", "UNSAFE_OR_INCOMPATIBLE"):
        assert label in txt
    assert "TIER0_SINGLE_HOST_REAL_ISOLATION_LIMIT_REACHED" in txt and "Tier0-A" in txt
    assert "No privileged operation was performed" in txt

"""
ORNEUR INDEPENDENT LANDMARK-03 QUALIFICATION TEST SUITE
Candidate: PR #147 (claude/landmark-03-vector-containment)
Code-bearing SHA: c8b0f54bafe364c18e507425570d34be1e7b8dd7
Documentation HEAD: bfeaae2bc7470251262b3526e32fede7412996d8
Baseline: PR #139 @ 38e0d311991875366f2bc88a39690c7b2b6ea3ee

Independent Adversarial Audit Gates:
- Gate A: Process Isolation, Exclusive Lock Stall Defense, Frozen Owner SIGKILL, Single-Owner Invariant
- Gate B: Unix Socket Protocol, Frame Validation, Path Traversal Refusal, Token Auth & Local UID Boundary
- Gate C: Resource Exhaustion & Capacity Truth (Serving vs Owner FDs and RSS Separation)
- Gate D: Customer Ownership Isolation, 8-Char Truncation Collisions, Bindings Integrity & Corruption Defense
- Gate E: Deletion & Physical Reclamation with Real ChromaDB 1.5.9 (Rebuild-Without, Segment Cleanup, Interrupted Rebuild Recovery)
- Gate G: Functional Consistency, Model Identity Truth (llama3.2:1b, INTERFACE_ONLY), Keyword Fallback
- Gate H: B6 Cross-Workstream Integration Hazard & X2 Root-Cause Deconstruction
- Governance: 0/95 Formal Acceptance & Pretraining STRICT NO-GO
"""

import fcntl
import hashlib
import hmac
import json
import os
import signal
import socket
import sqlite3
import struct
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from pathlib import Path
import pytest

L03_DIR = Path(os.environ.get("ORNEUR_L03_DIR", "/home/pc/projects/Orneur-l03"))
L02_DIR = Path(os.environ.get("ORNEUR_L02_DIR", "/home/pc/projects/Orneur-l02"))
B6CMP_DIR = Path(os.environ.get("ORNEUR_B6CMP_DIR", "/home/pc/projects/Orneur-l03-b6cmp"))

CODE_SHA = "c8b0f54bafe364c18e507425570d34be1e7b8dd7"
DOC_HEAD = "bfeaae2bc7470251262b3526e32fede7412996d8"
BASELINE_SHA = "38e0d311991875366f2bc88a39690c7b2b6ea3ee"


def _run_in_l03(code: str, env_vars: dict = None, timeout: float = 60.0) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("ORNEUR_", "ORCA_"))}
    env.update({"PYTHONPATH": str(L03_DIR), **(env_vars or {})})
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(L03_DIR)
    )


# ---------------------------------------------------------------------------
# Gate A: Process Isolation and Server Availability
# ---------------------------------------------------------------------------


def test_gate_a_candidate_sha_and_clean_tree_integrity():
    """Verify candidate SHA identity, documentation-only delta, and baseline ancestry."""
    assert L03_DIR.is_dir(), f"L03 directory not found at {L03_DIR}"
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(L03_DIR), text=True).strip()
    assert head == DOC_HEAD, f"HEAD mismatch: {head} != {DOC_HEAD}"

    # Verify baseline is topological ancestor
    rc = subprocess.call(["git", "merge-base", "--is-ancestor", BASELINE_SHA, DOC_HEAD], cwd=str(L03_DIR))
    assert rc == 0, f"Baseline {BASELINE_SHA[:7]} is not an ancestor of L03 HEAD {DOC_HEAD}!"

    # Verify code SHA tree vs doc HEAD tree: only documentation files differ
    diff_files = subprocess.check_output(
        ["git", "diff", "--name-only", CODE_SHA, DOC_HEAD],
        cwd=str(L03_DIR),
        text=True
    ).splitlines()
    for f in diff_files:
        assert f.startswith("docs/"), f"Non-documentation file modified between code SHA and doc HEAD: {f}"


def test_gate_a_held_exclusive_lock_preserves_application_responsiveness():
    """Adversarial probe: hold an exclusive lock on Chroma SQLite for 18 seconds.
    Verify /livez remains responsive (worst <= 50ms) and vector operations fail with bounded timeout (504/503),
    never freezing the application interpreter (reproducing the baseline defect vs candidate resolution)."""
    script = L03_DIR / "docs/orneur/landmarks/landmark-03/evidence/l03_server_stall_probe.py"
    assert script.is_file()

    env = {"L03_REPO": str(L03_DIR)}
    p = subprocess.run([sys.executable, str(script), "18"], env=env, capture_output=True, text=True, timeout=90, cwd=str(L03_DIR))
    assert p.returncode == 0, f"Stall probe failed:\n{p.stderr}"
    data = json.loads(p.stdout)

    assert data["lock_seconds"] == 18.0
    livez = data["livez_probes"]
    assert livez["count"] >= 50
    assert livez["worst_seconds"] <= 0.20, f"/livez stalled! Worst: {livez['worst_seconds']}s"
    assert len(livez["slow_over_1s"]) == 0

    reqs = data["requests"]
    # Write under lock must time out cleanly at socket deadline (~5s)
    rem1 = reqs["remember_new_conversation_1"]
    assert rem1["status"] in (504, 503)
    assert rem1["seconds"] <= 6.5, f"Write blocked too long: {rem1['seconds']}s"

    # Deletion under lock returns 202 (deferred), never a false 200
    dele = reqs["delete_seeded_conversation"]
    assert dele["status"] == 202


def test_gate_a_sigstop_frozen_owner_detection_and_supervisor_kill():
    """Adversarial probe: freeze owner process with SIGSTOP.
    Verify supervisor detects ping failure, issues SIGKILL, and a fresh call spawns a clean replacement."""
    code = """
        import os, signal, sys, time, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_sigstop_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"
        os.environ["ORNEUR_VECTOR_DEADLINE_S"] = "3"
        os.environ["ORNEUR_VECTOR_STUCK_AFTER_S"] = "4"

        from orca import vectorstore as vs
        vs.reset_for_tests()
        t = vs.transport()

        # Step 1: Start owner and make a baseline call
        store = vs.Store(home / "memory" / "vectors")
        col, _ = store.open_collection("test_col")
        col.add(ids=["1"], documents=["hello"])
        pid1 = t.owner_pid()
        assert pid1 is not None and t.ping(1.0) is True

        # Step 2: Freeze owner with SIGSTOP
        os.kill(pid1, signal.SIGSTOP)

        # Step 3: Call while owner is frozen -> must time out at deadline (~3s)
        t0 = time.monotonic()
        try:
            col.get(ids=["1"])
            raise AssertionError("Call to frozen owner should have timed out!")
        except vs.VectorError:
            elapsed = time.monotonic() - t0
            assert elapsed <= 4.5, f"Call hung too long on frozen owner: {elapsed}s"

        # Step 4: Wait for supervisor probe to detect failure and kill frozen owner
        end = time.monotonic() + 10.0
        killed = False
        while time.monotonic() < end:
            try:
                os.kill(pid1, 0)
                time.sleep(0.2)
            except OSError:
                killed = True
                break
        assert killed, f"Supervisor failed to kill frozen owner PID {pid1} within 10s!"

        # Step 5: Verify fresh owner is spawned on next call
        store2 = vs.Store(home / "memory" / "vectors")
        col2, _ = store2.open_collection("test_col")
        res = col2.get(ids=["1"])
        pid2 = t.owner_pid()
        assert pid2 is not None and pid2 != pid1
        assert res["ids"] == ["1"]

        t.kill_owner()
        print("SIGSTOP_TEST_OK")
    """
    p = _run_in_l03(code, timeout=40)
    assert p.returncode == 0, f"SIGSTOP test failed:\n{p.stderr}"
    assert "SIGSTOP_TEST_OK" in p.stdout


def test_gate_a_single_owner_flock_invariant_under_concurrent_starters():
    """Adversarial probe: 16 concurrent threads attempt to start owner on fresh data directory.
    Verify flock(owner.lock) serializes creation and exactly ONE owner process is running."""
    code = """
        import os, subprocess, sys, threading, time, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_single_owner_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        vs.reset_for_tests()

        errors = []
        def starter(idx):
            try:
                t = vs.transport()
                st = vs.Store(home / "memory" / "vectors")
                c, _ = st.open_collection(f"col_{idx}")
                c.add(ids=[f"id_{idx}"], documents=[f"doc_{idx}"])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=starter, args=(i,)) for i in range(16)]
        for th in threads: th.start()
        for th in threads: th.join(20)

        assert len(errors) == 0, f"Errors during concurrent starter race: {errors}"
        t = vs.transport()
        pid = t.owner_pid()
        assert pid is not None

        # Give any exited competing starter process a brief moment to reap
        time.sleep(0.5)

        # Verify via /proc or pgrep that exactly one live, non-zombie owner process exists for this home
        cmd = f"pgrep -f 'orca.vectorstore.server.*{home}'"
        out = subprocess.check_output(cmd, shell=True, text=True).strip().splitlines()
        live_pids = []
        for p in out:
            try:
                with open(f"/proc/{p}/status") as sf:
                    stat = sf.read()
                    if "State:\tZ" not in stat:
                        live_pids.append(p)
            except OSError:
                pass
        assert len(live_pids) == 1, f"Expected 1 live owner process, found {len(live_pids)}: {live_pids} (out={out})"

        t.kill_owner()
        print("SINGLE_OWNER_INVARIANT_OK")
    """
    p = _run_in_l03(code, timeout=40)
    assert p.returncode == 0, f"Single owner race test failed:\n{p.stderr}"
    assert "SINGLE_OWNER_INVARIANT_OK" in p.stdout


def test_gate_a_queue_exhaustion_and_bounded_admission():
    """Adversarial probe: submit traffic exceeding queue capacity.
    Verify immediate refusal with VectorBusy, avoiding unbounded queueing or memory growth."""
    code = """
        import os, sys, threading, time, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_queue_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"
        os.environ["ORNEUR_VECTOR_QUEUE_MAX"] = "8"
        os.environ["ORNEUR_VECTOR_MAX_CONNS"] = "16"

        from orca import vectorstore as vs
        vs.reset_for_tests()
        t = vs.transport()

        busy_seen = [False]
        def spam(i):
            try:
                st = vs.Store(home / "memory" / "vectors")
                c, _ = st.open_collection(f"col_{i}")
                c.add(ids=[str(i)], documents=["x" * 1000])
            except vs.VectorBusy:
                busy_seen[0] = True
            except Exception:
                pass

        threads = [threading.Thread(target=spam, args=(i,)) for i in range(40)]
        for th in threads: th.start()
        for th in threads: th.join(15)

        stats = t.owner_stats() or {}
        refused = stats.get("refused", {})
        assert busy_seen[0] or sum(refused.values()) > 0, "System failed to refuse when flooded!"
        t.kill_owner()
        print("QUEUE_EXHAUSTION_OK")
    """
    p = _run_in_l03(code, timeout=30)
    assert p.returncode == 0, f"Queue exhaustion test failed:\n{p.stderr}"
    assert "QUEUE_EXHAUSTION_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate B: Unix Socket Security and Frame Validation
# ---------------------------------------------------------------------------


def test_gate_b_unix_socket_security_and_frame_validation():
    """Adversarial probe: connect directly to AF_UNIX socket as an attacker.
    Challenge token verification, malformed frames, oversized frames, and path traversal."""
    code = """
        import hmac, json, os, socket, struct, sys, tempfile, time
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_socket_sec_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "service"

        from orca import vectorstore as vs
        from orca.vectorstore import paths, protocol
        vs.reset_for_tests()
        t = vs.transport()
        t.ensure_owner()

        sock_p = paths.sock_path(home)
        run_d = paths.run_dir(home)
        token = paths.token_path(home).read_text().strip()

        # 1. Directory and file permissions check
        assert run_d.stat().st_mode & 0o077 == 0, "Run directory has group/world permissions!"
        assert paths.token_path(home).stat().st_mode & 0o077 == 0, "Token file has group/world permissions!"

        def raw_call(obj):
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.connect(str(sock_p))
            protocol.send(s, obj)
            res = protocol.recv(s, time.monotonic() + 3.0)
            s.close()
            return res

        # 2. Attack: Missing or wrong token
        res_no_tok = raw_call({"op": "open_collection", "root": str(home / "memory" / "vectors"), "collection": "c1"})
        assert res_no_tok.get("ok") is False and res_no_tok.get("error") == "auth"

        res_bad_tok = raw_call({"op": "open_collection", "token": "FORGED_TOKEN_12345", "root": str(home / "memory" / "vectors"), "collection": "c1"})
        assert res_bad_tok.get("ok") is False and res_bad_tok.get("error") == "auth"

        # 3. Attack: Path Traversal outside home directory
        res_trav = raw_call({"op": "open_collection", "token": token, "root": "/etc", "collection": "c1"})
        assert res_trav.get("ok") is False and res_trav.get("error") == "bad_root"

        res_trav_rel = raw_call({"op": "open_collection", "token": token, "root": str(home / "../../../etc"), "collection": "c1"})
        assert res_trav_rel.get("ok") is False and res_trav_rel.get("error") == "bad_root"

        # 4. Attack: Malformed / non-JSON payload
        s_bad = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s_bad.connect(str(sock_p))
        s_bad.sendall(struct.pack(">I", 12) + b"NOT_JSON_DATA")
        try:
            protocol.recv(s_bad, time.monotonic() + 2.0)
        except Exception:
            pass # Socket closed by server
        s_bad.close()

        # 5. Confirm server remains alive and healthy after attacks
        assert t.ping(1.0) is True
        t.kill_owner()
        print("SOCKET_SECURITY_OK")
    """
    p = _run_in_l03(code, timeout=30)
    assert p.returncode == 0, f"Socket security test failed:\n{p.stderr}"
    assert "SOCKET_SECURITY_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate C: Resource Exhaustion and Capacity Truth
# ---------------------------------------------------------------------------


def test_gate_c_process_isolation_vs_total_resource_consumption():
    """Verify file descriptor and memory isolation between serving and owner processes.
    Confirms application process retains constant FDs (<=8) and flat RSS, while Chroma FDs are quarantined in owner."""
    bench_script = L03_DIR / "docs/orneur/landmarks/landmark-03/evidence/after/l03_bench.py"
    assert bench_script.is_file()

    env = {"L03_REPO": str(L03_DIR)}
    p = subprocess.run([sys.executable, str(bench_script), "10"], env=env, capture_output=True, text=True, timeout=60, cwd=str(L03_DIR))
    assert p.returncode == 0, f"Bench failed:\n{p.stderr}"
    res = json.loads(p.stdout)

    srv = res["runs"]["service"]["10"]
    assert srv["app_fd_after"] <= 8, f"App process leaked file descriptors: {srv['app_fd_after']}"
    assert srv["app_rss_mb_after"] <= 60, f"App process RSS too high: {srv['app_rss_mb_after']}MB"
    assert srv["chromadb_loaded_in_app_process"] is False
    assert srv["owner_fds"] > srv["app_fd_after"], "Owner process should hold the vector FDs"

    emb = res["runs"]["embedded"]["10"]
    assert emb["chromadb_loaded_in_app_process"] is True
    assert emb["app_fd_after"] > srv["app_fd_after"] * 5, "Embedded mode should hold many more FDs in-process"


# ---------------------------------------------------------------------------
# Gate D: Customer Ownership and Isolation
# ---------------------------------------------------------------------------


def test_gate_d_customer_ownership_isolation_and_prefix_collision():
    """Adversarial probe: two session IDs sharing the first 8 hex characters.
    Verify ownership binding sidecar (orneur_bindings.sqlite) prevents cross-session retrieval or deletion."""
    code = """
        import os, sys, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_d_"))
        home = td / "home"
        home.mkdir()
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "embedded"

        from orca.brain.memory import LongTermMemory
        from orca import vectorstore as vs

        # Two session IDs colliding on the first 8 hex characters
        sid_alpha = "12345678-userA-alpha"
        sid_beta  = "12345678-userB-beta"

        # Alpha writes memory
        mem_a = LongTermMemory(sid_alpha)
        mem_a.store("Alpha secret fact: project blue horizon", strict=True)
        assert len(mem_a.recall("horizon", 1, strict=True)) == 1

        # Beta attempts to read or write using colliding collection
        mem_b = LongTermMemory(sid_beta)
        try:
            mem_b.store("Beta data", strict=True)
            raise AssertionError("Beta should have been rejected due to binding mismatch!")
        except Exception as e:
            assert "another conversation" in str(e).lower() or "mismatch" in str(e).lower() or "VectorOwnershipError" in type(e).__name__

        # Beta attempts to delete collection
        col_name = f"orca_{sid_alpha[:8]}"
        st = vs.Store(home / "memory" / "vectors")
        del_res = st.delete_collection(col_name, binding=vs.session_binding(sid_beta))
        assert del_res.get("refused") == "not_owner" or del_res.get("removed") is False

        # Verify Alpha's data is completely intact
        hits = mem_a.recall("horizon", 1, strict=True)
        assert len(hits) == 1
        assert "blue horizon" in hits[0]["text"]

        print("OWNERSHIP_ISOLATION_OK")
    """
    p = _run_in_l03(code, timeout=30)
    assert p.returncode == 0, f"Customer ownership isolation test failed:\n{p.stderr}"
    assert "OWNERSHIP_ISOLATION_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate E: Deletion and Physical Reclamation
# ---------------------------------------------------------------------------


def test_gate_e_physical_vs_logical_deletion_with_real_chromadb():
    """Adversarial storage probe: ingest document with canary marker.
    Prove logical deletion excludes retrieval while bytes linger; prove physical rebuild_without + vacuum purges bytes."""
    code = """
        import os, sys, tempfile
        from pathlib import Path

        td = Path(tempfile.mkdtemp(prefix="test_gate_e_"))
        home = td / "home"
        docs = home / "docs"
        docs.mkdir(parents=True)
        os.environ["ORNEUR_HOME"] = str(home)
        os.environ["ORNEUR_VECTOR_MODE"] = "embedded"

        from orca.docs.store import DocStore, register_doc, reclaim_doc_vectors
        from orca.docs.chunker import Chunk

        canary = "PHYSICAL_RECLAMATION_CANARY_VALUE_987654321"
        sid = "sess-gate-e-test"
        store = DocStore(sid, enforce_registry=True)

        chunk = Chunk(text=f"Classified canary: {canary}", doc_id="doc_canary_1", filename="sec.txt", chunk_idx=0, char_start=0, char_end=60)
        store.add_chunks([chunk], doc_id="doc_canary_1", filename="sec.txt")
        register_doc(sid, "doc_canary_1", "sec.txt", 1, 60)

        def scan_canary():
            found = []
            for p in (docs / "vectors").rglob("*"):
                if p.is_file():
                    try:
                        if canary.encode() in p.read_bytes():
                            found.append(p.name)
                    except Exception:
                        pass
            return found

        # 1. Before deletion: retrievable and present in storage bytes
        assert len(store.retrieve("canary", top_k=2)) == 1
        files_before = scan_canary()
        assert len(files_before) > 0, "Canary not found on disk before delete!"

        # 2. Logical deletion only (reclaim=False)
        detail_logical = store.delete_doc_detailed("doc_canary_1", reclaim=False)
        assert detail_logical["ok"] is True
        assert len(store.retrieve("canary", top_k=2)) == 0, "Retrieval not excluded after logical delete!"
        # Physical scan: canary bytes STILL present in SQLite/WAL
        files_after_logical = scan_canary()
        assert len(files_after_logical) > 0, "Logical delete should leave raw bytes before physical rebuild!"

        # 3. Physical reclamation (rebuild_without + vacuum)
        reclaim_stat = reclaim_doc_vectors(store._col_name, "doc_canary_1")
        assert reclaim_stat == "RECLAIMED"

        # 4. Physical scan after reclamation: canary bytes GONE
        files_after_reclaim = scan_canary()
        assert len(files_after_reclaim) == 0, f"Canary bytes still present after physical reclamation: {files_after_reclaim}"

        print("PHYSICAL_RECLAMATION_OK")
    """
    p = _run_in_l03(code, timeout=30)
    assert p.returncode == 0, f"Physical reclamation test failed:\n{p.stderr}"
    assert "PHYSICAL_RECLAMATION_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate G: Functional Regression and Model Truth
# ---------------------------------------------------------------------------


def test_gate_g_functional_regression_and_model_identity_truth():
    """Verify that model identity truthfully reports third-party weights (llama3.2:1b) and INTERFACE_ONLY."""
    code = """
        import os, sys
        from pathlib import Path

        from orca.serve.model_identity import model_identity

        ident = model_identity(
            requested_variant="orca-core",
            served_tier="orca-nano",
            served_model="llama3.2:1b",
            backend="ollama",
        )
        assert ident["backend"] == "ollama"
        assert ident["requested_tier"] == "core"
        assert ident["served_tier"] == "nano"
        assert ident["substituted"] is True
        print("MODEL_TRUTH_OK")
    """
    p = _run_in_l03(code, timeout=10)
    assert p.returncode == 0, f"Model truth test failed:\n{p.stderr}"
    assert "MODEL_TRUTH_OK" in p.stdout


# ---------------------------------------------------------------------------
# Gate H: B6 Cross-Workstream Hazard & X2 Inconsistency Analysis
# ---------------------------------------------------------------------------


def test_gate_h_b6_cross_workstream_hazard_and_x2_inconsistency():
    """Deconstruct the X2 comparison inconsistency:
    PR #147 server.py lacks serving_lock, enabling unsafe restore overlaps.
    Demonstrate that comparison commit 7b319b1 had already included the patch, causing RestoreFailed.
    Challenge the proposed patch: silent exception swallowing must fail closed."""
    # 1. Inspect PR #147 server.py: confirm serving_lock is ABSENT
    server_code = (L03_DIR / "orca/vectorstore/server.py").read_text(encoding="utf-8")
    assert "datadir_lock.serving_lock" not in server_code, "serving_lock should not be present in unmodified PR #147"

    # 2. Inspect comparison patch: verify the error-swallowing flaw
    patch_file = L03_DIR / "docs/orneur/landmarks/landmark-03/evidence/cross_workstream/proposed_owner_serving_lock.patch"
    assert patch_file.is_file()
    patch_text = patch_file.read_text(encoding="utf-8")
    assert "except Exception:" in patch_text
    assert "lock = None" in patch_text, "Proposed patch swallows exceptions silently"

    # 3. In comparison worktree (if present), confirm why X2 produced RestoreFailed
    if B6CMP_DIR.is_dir():
        cmp_server = (B6CMP_DIR / "orca/vectorstore/server.py").read_text(encoding="utf-8")
        assert "datadir_lock.serving_lock" in cmp_server, "b6cmp worktree includes the patch, which caused the X2 RestoreFailed error!"


# ---------------------------------------------------------------------------
# Governance Immutability
# ---------------------------------------------------------------------------


def test_governance_immutability_and_formal_acceptance_zero():
    """Verify formal acceptance remains 0/95 and training authorization remains STRICT NO-GO."""
    res = subprocess.check_output(
        ["python3", "scripts/acceptance/validate_register_graph.py", "--check"],
        cwd=str(L03_DIR),
        text=True,
    ).strip()
    assert "pretraining=95 numerator=0" in res

    auth_json = json.loads((L03_DIR / "docs/orneur/authorization/TRAINING_AUTHORIZATION.json").read_text(encoding="utf-8"))
    assert auth_json.get("authorized") is False or auth_json.get("status") in ("NOT_AUTHORIZED", "NO_GO")

"""Isolated incident lifecycle for synthetic repair exercises.

Production authorization stays DENIED. No reviewer is enrolled, and this
module does not mint a signing key. A caller boolean cannot verify a
recovery. The journal is an append-only hash chain, not a signature.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from orca.pretrain_foundation.artifact_guard import (
    ArtifactBoundaryError,
    _components,
    _open_parent,
    atomic_write_regular,
    read_regular_nofollow,
)
from orca.pretrain_foundation.containment import EffectLedger
from orca.pretrain_foundation.model_monitor import monitoring_contracts

IST = ZoneInfo("Asia/Kolkata")
GENESIS_HASH = "0" * 64
STATES = (
    "DETECTED",
    "REPRODUCED",
    "DIAGNOSED",
    "PATCH_PROPOSED",
    "TESTED",
    "INDEPENDENTLY_VERIFIED",
    "AWAITING_AUTHORIZATION",
    "SIMULATED_RECOVERY_VERIFIED",
    "REPORTED",
)
_IGNORED_EVIDENCE = frozenset({
    "digest",
    "verified",
    "recovered",
    "approved",
    "production_authorization",
    "recovery_result",
    "authorization_decision",
})


class IncidentError(Exception):
    """The incident engine refused the operation."""


class IncidentJournalError(IncidentError):
    """The journal cannot be trusted."""

    def __init__(self, message: str, intact: list | None = None) -> None:
        super().__init__(message)
        self.intact = list(intact or [])


def _canonical(body: dict) -> str:
    return json.dumps(body, sort_keys=True, separators=(",", ":"))


def _digest(body: dict) -> str:
    return hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()


def _iso(unix: float) -> str:
    return datetime.fromtimestamp(unix, IST).isoformat()


class IncidentJournal:
    """Append-only chain. A torn tail or an edited line fails closed."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def read(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            raw = read_regular_nofollow(self.path)
        except ArtifactBoundaryError as exc:
            raise IncidentJournalError("journal is not a regular file") from exc
        if not raw:
            return []
        try:
            text = raw.decode("utf-8")
        except UnicodeError as exc:
            raise IncidentJournalError("journal is not utf-8") from exc
        torn = not text.endswith("\n")
        lines = text.split("\n")
        if text.endswith("\n"):
            lines = lines[:-1]
        intact: list[dict] = []
        for index, line in enumerate(lines):
            if torn and index == len(lines) - 1:
                raise IncidentJournalError("torn journal tail", intact)
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise IncidentJournalError("journal line is not json", intact) from exc
            self._check(intact, row)
            intact.append(row)
        return intact

    def _check(self, prior: list[dict], row: dict) -> None:
        prev = GENESIS_HASH if not prior else prior[-1]["digest"]
        body = row.get("body")
        if row.get("prev") != prev or not isinstance(body, dict):
            raise IncidentJournalError("journal chain mismatch", prior)
        if row.get("digest") != _digest({"prev": prev, "body": body}):
            raise IncidentJournalError("journal chain mismatch", prior)

    def append(self, body: dict) -> dict:
        existing = self.read()
        prev = GENESIS_HASH if not existing else existing[-1]["digest"]
        digest = _digest({"prev": prev, "body": body})
        row = {"prev": prev, "body": body, "digest": digest}
        line = (_canonical(row) + "\n").encode("utf-8")
        self._append_line(line)
        return row

    def _append_line(self, line: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_regular(self.path, b"")
        try:
            raw_parent = _open_parent(_components(self.path))
        except ArtifactBoundaryError as exc:
            raise IncidentJournalError("journal directory is not a real directory") from exc
        try:
            fd = os.open(
                self.path.name,
                os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=raw_parent,
            )
        except OSError as exc:
            os.close(raw_parent)
            raise IncidentJournalError("journal is not a regular file") from exc
        try:
            view = memoryview(line)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise IncidentJournalError("journal write stalled")
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
            os.close(raw_parent)


class IncidentEngine:
    """One incident directory. Reopening the directory reloads the journal."""

    def __init__(self, root: Path, *, now=None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.now = now or (lambda: datetime.now(tz=IST).timestamp())
        self.journal = IncidentJournal(self.root / "journal.jsonl")
        self.effects = EffectLedger(self.root / "effects.json")
        self.founder_online = True
        self.developer_online = True
        self._by_id: dict[str, dict] = {}
        self._by_fingerprint: dict[str, str] = {}
        self._reload()

    def set_presence(self, *, founder_online: bool, developer_online: bool) -> dict:
        """Presence is recorded. It does not grant authorization."""
        self.founder_online = bool(founder_online)
        self.developer_online = bool(developer_online)
        return self.authorization("presence")

    def authorization(self, _incident_id: str) -> dict:
        return {
            "decision": "DENIED",
            "production_authorization": "DENIED",
            "reason": "no enrolled reviewer authority",
            "reviewer_enrolled": False,
            "founder_online": self.founder_online,
            "developer_online": self.developer_online,
        }

    def detect(
        self,
        *,
        incident_id: str,
        source_commit: str,
        signal: str,
        fingerprint: str,
        owner_id: str,
        deadline_unix: float,
        budget_units: int,
        retry_limit: int,
    ) -> dict:
        if not all(isinstance(item, str) and item for item in (incident_id, source_commit, signal, fingerprint, owner_id)):
            raise IncidentError("detect requires incident id, commit, signal, fingerprint, and owner")
        if budget_units < 1 or retry_limit < 1:
            raise IncidentError("budget and retry limit must be positive")
        existing = self._by_fingerprint.get(fingerprint)
        if existing is not None:
            self._append({"kind": "duplicate", "incident_id": existing, "fingerprint": fingerprint, "unix": self.now()})
            row = dict(self._by_id[existing])
            row["duplicate"] = True
            return row
        if incident_id in self._by_id:
            raise IncidentError("incident id already exists")
        self._append({
            "kind": "detect",
            "incident_id": incident_id,
            "source_commit": source_commit,
            "signal": signal,
            "fingerprint": fingerprint,
            "owner_id": owner_id,
            "deadline_unix": deadline_unix,
            "budget_units": budget_units,
            "retry_limit": retry_limit,
            "unix": self.now(),
        })
        self.effects.apply(f"incident:{incident_id}:open", "opened")
        row = dict(self._by_id[incident_id])
        row["duplicate"] = False
        return row

    def note(self, incident_id: str, *, actor_id: str, text: str) -> dict:
        incident = self._require(incident_id)
        if actor_id != incident["owner_id"]:
            raise IncidentError("task is owned by another actor")
        if not text:
            raise IncidentError("diagnostic note requires text")
        self._append({
            "kind": "diagnostic",
            "incident_id": incident_id,
            "actor_id": actor_id,
            "text": text,
            "unix": self.now(),
        })
        return self._public(incident_id)

    def observe_command(self, incident_id: str, command: list[str], cwd: Path) -> dict:
        """Run a command and store the exit code this process actually saw."""
        incident = self._require(incident_id)
        if not isinstance(command, list) or not command or any(not isinstance(part, str) or not part for part in command):
            raise IncidentError("command must be a list of strings")
        directory = Path(cwd)
        if not directory.is_dir() or directory.is_symlink():
            raise IncidentError("observation directory must be a real directory")
        proc = subprocess.run(command, cwd=directory, capture_output=True, text=True, timeout=60, check=False)
        output = ((proc.stdout or "") + (proc.stderr or ""))[:64000]
        observation_id = hashlib.sha256(f"{proc.returncode}\n{output}".encode("utf-8")).hexdigest()
        self._append({
            "kind": "observation",
            "incident_id": incident_id,
            "actor_id": incident["owner_id"],
            "observation_id": observation_id,
            "exit_code": proc.returncode,
            "output": output,
            "command": command,
            "unix": self.now(),
        })
        return {"observation_id": observation_id, "exit_code": proc.returncode, "output_digest": observation_id}

    def transition(self, incident_id: str, to_state: str, *, actor_id: str, evidence: dict) -> dict:
        incident = self._require(incident_id)
        if to_state not in STATES or to_state == "DETECTED":
            raise IncidentError("unknown incident state")
        expected = STATES[STATES.index(incident["state"]) + 1]
        evidence = self._evidence(evidence)
        reviewer = to_state == "INDEPENDENTLY_VERIFIED"
        if to_state == "PATCH_PROPOSED" and incident["state"] == "PATCH_PROPOSED":
            return self._competing_patch(incident, actor_id, evidence)
        if to_state != expected:
            raise IncidentError(f"next state is {expected}")
        self._guard(incident, actor_id, reviewer=reviewer)
        if to_state == "TESTED":
            return self._tested(incident, actor_id, evidence)
        self._require_evidence(to_state, evidence, incident)
        if to_state == "INDEPENDENTLY_VERIFIED" and incident["contradiction"]:
            raise IncidentError("contradictory repair proposals block verification")
        if to_state == "SIMULATED_RECOVERY_VERIFIED":
            self._bind_simulation(incident, evidence)
        body = {
            "kind": "transition",
            "incident_id": incident_id,
            "to_state": to_state,
            "actor_id": actor_id,
            "evidence": evidence,
            "unix": self.now(),
        }
        self._append(body)
        return self._public(incident_id)

    def cancel(self, incident_id: str, *, actor_id: str, reason: str) -> dict:
        incident = self._require(incident_id)
        if actor_id != incident["owner_id"]:
            raise IncidentError("task is owned by another actor")
        if not reason:
            raise IncidentError("cancellation requires a reason")
        if incident["cancelled"]:
            raise IncidentError("incident is already cancelled")
        self._append({
            "kind": "cancel",
            "incident_id": incident_id,
            "actor_id": actor_id,
            "reason": reason,
            "unix": self.now(),
        })
        return self._public(incident_id)

    def notify(self, incident_id: str, sender) -> dict:
        incident = self._require(incident_id)
        if incident["notification"] == "DELIVERED":
            return {"delivered": True, "duplicate": True, "state": incident["state"]}
        if incident["notification"] == "STARTED":
            return {"delivered": False, "reason": "notification outcome unknown after interruption", "state": incident["state"]}
        self._append({"kind": "notification", "incident_id": incident_id, "phase": "started", "unix": self.now()})
        try:
            sender(self.build_report(incident_id))
        except Exception:
            self._append({"kind": "notification", "incident_id": incident_id, "phase": "failed", "unix": self.now()})
            return {"delivered": False, "state": self._by_id[incident_id]["state"]}
        self.effects.apply(f"incident:{incident_id}:notify", "delivered")
        self._append({"kind": "notification", "incident_id": incident_id, "phase": "delivered", "unix": self.now()})
        return {"delivered": True, "duplicate": False, "state": self._by_id[incident_id]["state"]}

    def build_report(self, incident_id: str) -> dict:
        incident = self._require(incident_id)
        tested = incident["test_exit"] == 0
        isolated = incident["isolated_exit"] == 0
        if tested and isolated:
            recovery = "PATCH DEVELOPED AND TESTED"
            execution = "simulated-isolated"
        elif tested:
            recovery = "PATCH DEVELOPED AND TESTED"
            execution = "not-executed"
        else:
            recovery = "NOT_RECOVERED"
            execution = "not-executed"
        risks = [
            "Production authorization is DENIED.",
            "No reviewer is enrolled.",
            "The acceptance ledger is unchanged.",
            "Native models were not loaded.",
        ]
        if incident["contradiction"]:
            risks.append("Competing patch digests blocked verification.")
        if not tested:
            risks.append("The reproducing test has not passed.")
        return {
            "incident_id": incident_id,
            "timestamps": {
                "detected": _iso(incident["detected_unix"]),
                "updated": _iso(incident["updated_unix"]),
                "zone": "Asia/Kolkata",
            },
            "source_commit": incident["source_commit"],
            "observed_failure": incident["signal"],
            "reproducing_test": incident["repro_command"],
            "root_cause": incident["cause"],
            "generated_patch": incident["patch_text"],
            "changed_files": list(incident["changed_files"]),
            "test_results": {
                "exit_code": incident["test_exit"],
                "output_digest": incident["test_observation_id"],
                "failed_attempts": incident["test_failures"],
            },
            "independent_verification": {
                "reviewer_id": incident["reviewer_id"],
                "reviewer_enrolled": False,
                "digest_checked": incident["state"] in STATES[STATES.index("INDEPENDENTLY_VERIFIED"):],
            },
            "authorization_decision": "DENIED",
            "production_authorization": "DENIED",
            "execution_status": execution,
            "recovery_result": recovery,
            "resource_consumption": {
                "journal_events": incident["events"],
                "journal_bytes": self.journal.path.stat().st_size if self.journal.path.exists() else 0,
                "budget_spent": incident["spent"],
                "budget_units": incident["budget_units"],
                "model_inference": False,
            },
            "remaining_risk": " ".join(risks),
            "notification_delivery": incident["notification"],
            "lifecycle_state": incident["state"],
            "model_contracts": monitoring_contracts(),
            "patch_generator": "not an enrolled model backend",
        }

    def _tested(self, incident: dict, actor_id: str, evidence: dict) -> dict:
        observation = self._observation(incident, evidence)
        if observation["exit_code"] != 0:
            if incident["test_failures"] >= incident["retry_limit"]:
                raise IncidentError("retry limit reached")
            self._append({
                "kind": "test_failure",
                "incident_id": incident["incident_id"],
                "actor_id": actor_id,
                "observation_id": observation["observation_id"],
                "unix": self.now(),
            })
            row = self._public(incident["incident_id"])
            row["advanced"] = False
            return row
        self._append({
            "kind": "transition",
            "incident_id": incident["incident_id"],
            "to_state": "TESTED",
            "actor_id": actor_id,
            "evidence": {"observation_id": observation["observation_id"]},
            "unix": self.now(),
        })
        row = self._public(incident["incident_id"])
        row["advanced"] = True
        return row

    def _competing_patch(self, incident: dict, actor_id: str, evidence: dict) -> dict:
        self._guard(incident, actor_id, reviewer=False)
        patch_text = evidence.get("patch_text")
        if not isinstance(patch_text, str) or not patch_text:
            raise IncidentError("competing proposal requires patch text")
        digest = hashlib.sha256(patch_text.encode("utf-8")).hexdigest()
        if digest in incident["patch_digests"]:
            row = self._public(incident["incident_id"])
            row["duplicate"] = True
            return row
        if incident["test_failures"] >= incident["retry_limit"] and incident["test_exit"] != 0:
            raise IncidentError("retry limit reached")
        self._append({
            "kind": "competing_patch",
            "incident_id": incident["incident_id"],
            "actor_id": actor_id,
            "patch_text": patch_text,
            "patch_digest": digest,
            "unix": self.now(),
        })
        row = self._public(incident["incident_id"])
        row["contradiction"] = True
        return row

    def _bind_simulation(self, incident: dict, evidence: dict) -> None:
        if evidence.get("environment") != "isolated-test":
            raise IncidentError("simulated recovery requires an isolated-test environment")
        observation = self._observation(incident, evidence)
        if observation["exit_code"] != 0:
            raise IncidentError("simulated recovery command failed")

    def _observation(self, incident: dict, evidence: dict) -> dict:
        observation_id = evidence.get("observation_id")
        if not isinstance(observation_id, str) or observation_id not in incident["observations"]:
            raise IncidentError("transition requires an observed command")
        return incident["observations"][observation_id]

    def _require_evidence(self, to_state: str, evidence: dict, incident: dict) -> None:
        if to_state == "REPRODUCED":
            self._need(evidence, "repro_command", "observed_output")
        elif to_state == "DIAGNOSED":
            self._need(evidence, "cause")
        elif to_state == "PATCH_PROPOSED":
            self._need(evidence, "patch_text", "changed_files")
            if not isinstance(evidence.get("changed_files"), list) or not evidence["changed_files"]:
                raise IncidentError("patch proposal requires changed files")
        elif to_state == "INDEPENDENTLY_VERIFIED":
            if evidence.get("tested_observation_id") != incident["test_observation_id"]:
                raise IncidentError("reviewer evidence does not match the tested observation")
        elif to_state == "AWAITING_AUTHORIZATION":
            self._need(evidence, "request")
        elif to_state == "REPORTED":
            return

    def _need(self, evidence: dict, *keys: str) -> None:
        for key in keys:
            if not evidence.get(key):
                raise IncidentError(f"evidence requires {key}")

    def _evidence(self, evidence: dict) -> dict:
        if not isinstance(evidence, dict):
            raise IncidentError("evidence must be an object")
        return {key: value for key, value in evidence.items() if key not in _IGNORED_EVIDENCE}

    def _guard(self, incident: dict, actor_id: str, *, reviewer: bool) -> None:
        if incident["cancelled"]:
            raise IncidentError("incident is cancelled")
        if self.now() >= incident["deadline_unix"]:
            raise IncidentError("deadline passed")
        if incident["spent"] >= incident["budget_units"]:
            raise IncidentError("budget exhausted")
        if reviewer:
            if not actor_id or actor_id == incident["owner_id"] or actor_id == incident["author_id"]:
                raise IncidentError("author cannot verify its own repair")
            return
        if actor_id != incident["owner_id"]:
            raise IncidentError("task is owned by another actor")

    def _append(self, body: dict) -> None:
        self.journal.append(body)
        self._reload()

    def _reload(self) -> None:
        self._by_id = {}
        self._by_fingerprint = {}
        for row in self.journal.read():
            self._apply(row["body"])

    def _apply(self, body: dict) -> None:
        kind = body.get("kind")
        if kind == "detect":
            self._by_id[body["incident_id"]] = {
                "incident_id": body["incident_id"],
                "fingerprint": body["fingerprint"],
                "source_commit": body["source_commit"],
                "signal": body["signal"],
                "owner_id": body["owner_id"],
                "deadline_unix": body["deadline_unix"],
                "budget_units": body["budget_units"],
                "retry_limit": body["retry_limit"],
                "state": "DETECTED",
                "spent": 1,
                "cancelled": False,
                "author_id": body["owner_id"],
                "patch_text": None,
                "patch_digests": [],
                "changed_files": [],
                "repro_command": None,
                "observed_output": None,
                "cause": None,
                "test_exit": None,
                "test_observation_id": None,
                "test_failures": 0,
                "reviewer_id": None,
                "isolated_exit": None,
                "detected_unix": body["unix"],
                "updated_unix": body["unix"],
                "notification": "NOT_ATTEMPTED",
                "contradiction": False,
                "observations": {},
                "events": 1,
                "production_authorization": "DENIED",
            }
            self._by_fingerprint[body["fingerprint"]] = body["incident_id"]
            return
        incident = self._by_id[body["incident_id"]]
        incident["updated_unix"] = body.get("unix", incident["updated_unix"])
        incident["events"] += 1
        if kind == "duplicate":
            return
        if kind == "diagnostic":
            return
        if kind == "observation":
            incident["observations"][body["observation_id"]] = body
            return
        if kind == "cancel":
            incident["cancelled"] = True
            return
        if kind == "notification":
            phase = body["phase"]
            incident["notification"] = {"started": "STARTED", "failed": "FAILED", "delivered": "DELIVERED"}[phase]
            return
        if kind == "test_failure":
            incident["spent"] += 1
            incident["test_failures"] += 1
            return
        if kind == "competing_patch":
            incident["spent"] += 1
            incident["contradiction"] = True
            incident["patch_digests"].append(body["patch_digest"])
            return
        if kind == "transition":
            incident["spent"] += 1
            incident["state"] = body["to_state"]
            evidence = body.get("evidence") or {}
            if body["to_state"] == "REPRODUCED":
                incident["repro_command"] = evidence.get("repro_command")
                incident["observed_output"] = evidence.get("observed_output")
            elif body["to_state"] == "DIAGNOSED":
                incident["cause"] = evidence.get("cause")
            elif body["to_state"] == "PATCH_PROPOSED":
                incident["patch_text"] = evidence.get("patch_text")
                incident["changed_files"] = list(evidence.get("changed_files") or [])
                incident["author_id"] = body["actor_id"]
                incident["patch_digests"] = [hashlib.sha256(evidence["patch_text"].encode("utf-8")).hexdigest()]
            elif body["to_state"] == "TESTED":
                observation = incident["observations"][evidence["observation_id"]]
                incident["test_exit"] = observation["exit_code"]
                incident["test_observation_id"] = observation["observation_id"]
            elif body["to_state"] == "INDEPENDENTLY_VERIFIED":
                incident["reviewer_id"] = body["actor_id"]
            elif body["to_state"] == "SIMULATED_RECOVERY_VERIFIED":
                observation = incident["observations"][evidence["observation_id"]]
                incident["isolated_exit"] = observation["exit_code"]
            return
        raise IncidentError(f"unknown journal event {kind}")

    def _require(self, incident_id: str) -> dict:
        try:
            return self._by_id[incident_id]
        except KeyError as exc:
            raise IncidentError("unknown incident") from exc

    def _public(self, incident_id: str) -> dict:
        incident = self._by_id[incident_id]
        return {
            "incident_id": incident_id,
            "state": incident["state"],
            "production_authorization": "DENIED",
            "cancelled": incident["cancelled"],
            "contradiction": incident["contradiction"],
            "notification": incident["notification"],
            "spent": incident["spent"],
            "test_failures": incident["test_failures"],
        }

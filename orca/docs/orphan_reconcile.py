"""Inventory of upload stores. This scan does not delete durable bytes.

Age, a dead process id, and an 8-character keyword prefix do not prove that
a file is an orphan. Without an owner-scoped upload journal there is no
safe automatic deletion, so ``apply=True`` still removes nothing. Dry-run
remains the default. ``atomic`` and ``exactly_once`` stay false.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from orca.docs import store as docs_store


def reconcile_orphan_uploads(
    *,
    now: float | None = None,
    apply: bool = False,
    docs_dir: Path | None = None,
    index_dir: Path | None = None,
    temporary_dir: Path | None = None,
) -> dict:
    moment = time.time() if now is None else now
    docs = Path(docs_dir) if docs_dir is not None else Path(docs_store.DOCS_DIR)
    docs_files = _walk(docs)
    index_files = _walk(Path(index_dir)) if index_dir is not None else []
    temporary_files = _walk(Path(temporary_dir)) if temporary_dir is not None else []
    discrepancies = _classify(docs, docs_files, index_files, temporary_files, moment)
    return {
        "dry_run": not apply,
        "apply_requested": bool(apply),
        "deletion_performed": False,
        "automatic_deletion": "refused",
        "required_architecture": (
            "An owner-scoped journal must be committed before upload bytes are written. "
            "It has to name upload_id, owner, session, and a state (started, committed, abandoned). "
            "A later deleter may remove a regular file only when that journal says abandoned, the owner matches, "
            "no live lock is held, and the path is opened with O_NOFOLLOW inside the journal directory. "
            "This storage layout has no such journal, so active uploads, interrupted uploads, and safe orphans "
            "cannot be distinguished from uncertain files. Uncertain files are left untouched."
        ),
        "atomic": False,
        "exactly_once": False,
        "inventory": {
            "files": [_public_file(item) for item in docs_files if item["kind"] == "file"],
            "authorized_index": [_public_file(item) for item in index_files],
            "temporary_chats": [_public_file(item) for item in temporary_files],
            "file_count": sum(1 for item in docs_files + index_files + temporary_files if item["kind"] == "file"),
        },
        "discrepancies": discrepancies,
        "removed": [],
        "document_only_preserved": [row["session_id"] for row in discrepancies if row["class"] == "document_only"],
    }


def _public_file(item: dict) -> dict:
    payload = {"path": item["path"], "name": item["name"]}
    if "bytes" in item:
        payload["bytes"] = item["bytes"]
    if item["kind"] == "symlink":
        payload["symlink"] = True
    return payload


def _walk(root: Path) -> list[dict]:
    rows: list[dict] = []
    if not root.exists():
        return rows
    for path in root.rglob("*"):
        if path.is_symlink():
            rows.append({"path": str(path), "name": path.name, "kind": "symlink", "root": root})
            continue
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        rows.append({
            "path": str(path),
            "name": path.name,
            "kind": "file",
            "bytes": stat.st_size,
            "mtime": stat.st_mtime,
            "root": root,
        })
    return rows


def _classify(docs: Path, docs_files: list[dict], index_files: list[dict], temporary_files: list[dict], now: float) -> list[dict]:
    rows: list[dict] = []
    registry_docs: dict[str, set[str]] = {}
    registry_path = docs / "registry.json"
    for item in docs_files:
        path = Path(item["path"])
        if item["kind"] == "symlink":
            rows.append(_report("uncertain_link", item, "a symlink is not an owned artifact"))
            continue
        if "vectors" in path.parts:
            rows.append(_report("vector_collection", item, "a vector file does not name one owner"))
            continue
        if item["name"].endswith(".tmp"):
            age = now - float(item.get("mtime") or now)
            hint = "active_upload" if age < 60 else "interrupted_upload"
            rows.append({
                "class": hint,
                "category": "uncertain",
                "path": item["path"],
                "remediation": "refused",
                "reason": "a temp file has no owner-scoped journal, so age cannot prove it is active, interrupted, or safe to remove",
            })
            continue
        if item["name"].startswith("kw_") and item["name"].endswith(".jsonl"):
            rows.append(_report("keyword_fallback", item, "an 8-character session prefix can collide, so the owner is not certain"))
            continue
        if item["name"] == "registry.json":
            registry_docs, readable = _registry_documents(path)
            if readable:
                rows.append(_report("session_registry", item, "the session registry is a reference, not an orphan", category="referenced"))
                rows.extend(_document_only_rows(registry_path, registry_docs))
            else:
                rows.append(_report("session_registry", item, "the session registry could not be read, so nothing it might reference is deleted"))
            continue
        rows.append(_report("durable_artifact", item, "a durable file with no established orphan rule is kept"))
    for item in index_files:
        rows.append(_index_row(item))
    for item in temporary_files:
        rows.append(_temporary_row(item))
    rows.extend(_fallback_disagreements_after_registry(docs_files, registry_docs))
    return rows


def _report(kind: str, item: dict, reason: str, *, category: str = "uncertain") -> dict:
    return {
        "class": kind,
        "category": category,
        "path": item["path"],
        "remediation": "refused",
        "reason": reason,
    }


def _registry_documents(path: Path) -> tuple[dict[str, set[str]], bool]:
    try:
        payload = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, False
    found: dict[str, set[str]] = {}
    if not isinstance(payload, dict):
        return found, False
    for session_id, docs in payload.items():
        if not isinstance(session_id, str) or not isinstance(docs, list):
            continue
        ids = {row.get("doc_id") for row in docs if isinstance(row, dict) and isinstance(row.get("doc_id"), str)}
        found[session_id] = {doc_id for doc_id in ids if doc_id}
    return found, True


def _document_only_rows(registry_path: Path, registry_docs: dict[str, set[str]]) -> list[dict]:
    rows = []
    for session_id, doc_ids in registry_docs.items():
        if not doc_ids:
            continue
        rows.append({
            "class": "document_only",
            "category": "referenced",
            "path": str(registry_path),
            "session_id": session_id,
            "remediation": "preserve",
            "reason": "a session that still lists documents is kept",
        })
    return rows


def _fallback_disagreements_after_registry(docs_files: list[dict], registry_docs: dict[str, set[str]]) -> list[dict]:
    rows = []
    for item in docs_files:
        name = item["name"]
        if item["kind"] != "file" or not (name.startswith("kw_") and name.endswith(".jsonl")):
            continue
        rows.extend(_disagreements_for_fallback(Path(item["path"]), registry_docs))
    return rows


def _disagreements_for_fallback(path: Path, registry_docs: dict[str, set[str]]) -> list[dict]:
    known = {doc_id for ids in registry_docs.values() for doc_id in ids}
    rows = []
    try:
        lines = path.read_text().splitlines()
    except (OSError, UnicodeError):
        return [_report("storage_disagreement", {"path": str(path)}, "the keyword fallback could not be read")]
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            rows.append(_report("storage_disagreement", {"path": str(path)}, "the keyword fallback has a line that is not JSON"))
            break
        doc_id = payload.get("doc_id") if isinstance(payload, dict) else None
        if isinstance(doc_id, str) and doc_id not in known:
            rows.append({
                "class": "storage_disagreement",
                "category": "partially_deleted",
                "path": str(path),
                "doc_id": doc_id,
                "remediation": "refused",
                "reason": "the keyword fallback names a document the registry does not list",
            })
    return rows


def _index_row(item: dict) -> dict:
    if item["kind"] == "symlink":
        return _report("uncertain_link", item, "an index symlink is not followed")
    path = Path(item["path"])
    if item["name"].endswith(".tmp"):
        return _report("incomplete_transaction", item, "an index temp file may belong to an open commit")
    if "bindings" in path.parts and item["name"].endswith(".json"):
        user_dir = path.parent.parent.name
        try:
            payload = json.loads(path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError):
            return _report("owner_uncertain", item, "the binding record could not be read")
        if not isinstance(payload, dict) or payload.get("user_id") != user_dir:
            return _report("owner_uncertain", item, "the binding owner does not match the directory")
        return _report("authorized_index", item, "an authorized binding is kept with its conversation", category="referenced")
    return _report("authorized_index", item, "an authorized-index file is kept until its binding is certain")


def _temporary_row(item: dict) -> dict:
    if item["kind"] == "symlink":
        return _report("uncertain_link", item, "a temporary-chat symlink is not followed")
    if not item["name"].endswith(".json"):
        return _report("temporary_chat", item, "a temporary-chat file without a deletion record is kept")
    try:
        payload = json.loads(Path(item["path"]).read_text())
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _report("owner_uncertain", item, "the temporary-chat record could not be read")
    if not isinstance(payload, dict) or not payload.get("user_id"):
        return _report("owner_uncertain", item, "the temporary chat has no owner")
    if payload.get("state") == "failed" or payload.get("reason") == "deletion_incomplete":
        return _report("incomplete_deletion", item, "a failed temporary-chat closure is not deleted by this scan", category="partially_deleted")
    return _report("temporary_chat", item, "temporary-chat retention stays with the temporary-chat owner", category="referenced")



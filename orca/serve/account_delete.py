"""
Right-to-delete — orchestrates a full account deletion across every store
that holds data tied to a user, not just the users table row.

Real architectural gap this closes: chat history, uploaded documents, and
memory files were keyed purely by session_id, with no persisted link back
to an owning user_id. orca/auth/store.py's user_sessions table (populated
by _get_session() whenever an authenticated request creates/touches a
session) is what makes "find everything this account touched" possible at
all — without it, this module could only delete the account row itself and
silently leave chat history/documents behind.

What this deletes:
  - The user's account row, API keys, usage records (orca.auth.store)
  - Every session this account is known to have touched:
      - Episodic memory file (orca/brain/memory.py's EpisodicMemory)
      - DocStore vectors + doc registry entries (orca/docs/store.py)
      - Knowledge graph entities/relationships (orca/brain/knowledge_graph.py)
      - Session title entry (orca/serve/api.py's session_titles.json)
      - Redis session state, if enabled (orca/serve/session_store.py)
  - Attempts to cancel any active Stripe subscription tied to this account
    (best-effort — logged, not fatal if it fails)

What this does NOT delete, stated plainly (same tension already documented
in legal/PRIVACY_POLICY.md §5):
  - Historical audit log entries referencing this user_id. The audit log's
    entire value is being a tamper-evident record of what happened — a
    log you can retroactively edit isn't tamper-evident. Deleting entries
    would break the hash chain for every entry after it. The user_id in
    old audit entries becomes a dangling reference to a deleted account,
    not a live PII record — a policy/legal judgment call for the operator's
    jurisdiction, not something resolved automatically here.
  - Sessions the user touched WHILE UNAUTHENTICATED (anonymous chat before
    ever logging in) — those were never recorded in user_sessions because
    there was no user_id to record them against at the time. This is a
    real, current limitation, not swept under the rug.
"""
from __future__ import annotations

import os
import json
from pathlib import Path

from orca.auth.store import get_user_session_ids, delete_user_account_records, get_stripe_customer_id
from orca.docs.store import unregister_doc, list_docs, DocStore
from orca.brain.memory import EpisodicMemory, LongTermMemory, SemanticMemory
from orca.brain.knowledge_graph import KnowledgeGraph
from orca.serve import session_store
from orca.config import ORCA_HOME, CONFIG


def _delete_session_data(session_id: str) -> dict:
    """Best-effort cleanup of everything scoped to one session_id. Never raises — one failed store shouldn't block cleanup of the rest."""
    result = {
        "session_id": session_id, "memory_deleted": False, "docs_deleted": 0, "redis_deleted": False,
        "knowledge_graph_deleted": False, "semantic_facts_deleted": False, "memory_continuum_deleted": {},
        # 2026-10-15 (P1 deletion-assurance design): split from one conflated
        # boolean into the two honestly-distinct facts a caller actually
        # needs -- whether the data is gone from every normal read path
        # (logical_deleted, the real privacy guarantee) versus whether the
        # raw on-disk bytes have also been reclaimed (physical_reclamation,
        # best-effort hardening, may legitimately be "DEFERRED" under
        # contention -- see LongTermMemory.delete()'s docstring). Never
        # collapse these back into one boolean in any caller/API response.
        "long_term_vector_memory_logically_deleted": False,
        "long_term_vector_memory_physical_reclamation": None,
    }

    try:
        ep = EpisodicMemory(session_id)
        if ep.path.exists():
            ep.path.unlink()
            result["memory_deleted"] = True
    except Exception as e:
        result["memory_error"] = str(e)

    try:
        from orca.serve import conversations
        result["conversation_transcript_deleted"] = conversations.delete(session_id)
    except Exception as e:
        result["conversation_transcript_error"] = str(e)

    try:
        from orca.serve import message_versions
        result["message_versions_deleted"] = message_versions.delete_session(session_id)
    except Exception as e:
        result["message_versions_error"] = str(e)

    try:
        # Phase 5.1: a real, confirmed gap this cascade never covered --
        # every raw Q:/A: turn committed via MemoryEngine.commit_to_long_term()
        # (unconditional, every chat/stream/ultra turn) lived in this
        # session's own ChromaDB collection with NO deletion path at all
        # before LongTermMemory.delete() was added this phase.
        # delete_session() classmethod, not LongTermMemory(session_id).delete():
        # the latter would construct a chromadb client synchronously on THIS
        # thread first (LongTermMemory.__init__ touches the same shared,
        # lockable file), before the bounded watchdog inside delete() ever
        # starts -- confirmed by direct reproduction against a real held
        # lock. delete_session() does the whole lifecycle, construction
        # included, inside the bounded background worker.
        ltm_result = LongTermMemory.delete_session(session_id)
        result["long_term_vector_memory_logically_deleted"] = ltm_result.logical_deleted
        result["long_term_vector_memory_physical_reclamation"] = ltm_result.physical_reclamation
    except Exception as e:
        result["long_term_vector_memory_error"] = str(e)

    try:
        docs = list_docs(session_id, include_deleting=True)
        if docs:
            store = DocStore(session_id=session_id, ollama_host=CONFIG.ollama.host)
            removed = 0
            for d in docs:
                if store.delete_doc_detailed(d["doc_id"], reclaim=False)["ok"]:        # L02-01: unregister only what every store confirmed (L03: one rewrite for the whole set, below)
                    unregister_doc(session_id, d["doc_id"])
                    removed += 1
            result["docs_deleted"] = removed
            if removed != len(docs):
                result["docs_error"] = f"{len(docs) - removed} document(s) not fully removed"
        from orca.docs.store import drop_session_collection

        result["docs_vector_physical_reclamation"] = drop_session_collection(session_id)
    except Exception as e:
        result["docs_error"] = str(e)

    try:
        kg = KnowledgeGraph(session_id)
        had_data = kg.count()["entities"] > 0
        kg.clear()
        result["knowledge_graph_deleted"] = had_data
    except Exception as e:
        result["knowledge_graph_error"] = str(e)

    try:
        # L02-01f: delete_session() returns False when Redis is unreachable. That used to be ignored and reported as deleted, leaving the cached
        # conversation in Redis until its TTL. An unreachable Redis is now a FAILED store (the deletion stays partial and is retried).
        if not session_store.delete_session(session_id):
            result["redis_error"] = "redis unreachable"
        else:
            result["redis_deleted"] = session_store.enabled()
    except Exception as e:
        result["redis_error"] = str(e)

    # Phase 5: the audit (docs/orneur/phase-5/CURRENT_MEMORY_ARCHITECTURE.md)
    # found SemanticMemory's diskcache store was entirely missing from
    # this cascade -- distilled "facts" from a deleted user's sessions
    # persisted forever, unreachable by deletion. Fixed here, plus the
    # new Memory Continuum stores (episodic ledger + semantic/entity/
    # procedural/failure records) this phase introduces.
    try:
        result["semantic_facts_deleted"] = SemanticMemory().delete_session_facts(session_id)
    except Exception as e:
        result["semantic_facts_error"] = str(e)

    try:
        from orca.memory import deletion as memory_deletion
        from orca.memory.contracts import MemoryScope
        result["memory_continuum_deleted"] = memory_deletion.delete_scope(MemoryScope.SESSION, session_id)
    except Exception as e:
        result["memory_continuum_error"] = str(e)

    return result


def _remove_session_title(session_id: str) -> None:
    """session_titles.json lives in orca/serve/api.py's module state, not a
    shared store — read/write the file directly rather than importing api.py
    (which would create a circular import: api.py imports this module)."""
    # The API process also keeps titles in an in-memory dict and rewrites the WHOLE file from it on the next title change, so removing only the
    # file entry let a deleted user's title reappear the next time anyone renamed a conversation. Purge the live copy too (no import: api.py
    # imports this module).
    import sys

    live = getattr(sys.modules.get("orca.serve.api"), "_session_titles", None)
    if isinstance(live, dict):
        live.pop(session_id, None)
    titles_path = ORCA_HOME / "session_titles.json"
    try:
        if not titles_path.exists():
            return
        titles = json.loads(titles_path.read_text())
        if session_id in titles:
            del titles[session_id]
            titles_path.write_text(json.dumps(titles))
    except Exception:
        pass


def _cancel_stripe_subscriptions(customer_id: str) -> dict:
    """Best-effort — if Stripe isn't configured or the call fails, deletion still proceeds. A failed cancellation attempt is not a reason to block account deletion."""
    stripe_secret = os.environ.get("STRIPE_SECRET_KEY")
    if not stripe_secret:
        return {"attempted": False, "reason": "STRIPE_SECRET_KEY not configured"}

    try:
        import stripe
        stripe.api_key = stripe_secret
        subs = stripe.Subscription.list(customer=customer_id, status="active", limit=10)
        cancelled = []
        for sub in subs.data:
            stripe.Subscription.cancel(sub.id)
            cancelled.append(sub.id)
        return {"attempted": True, "cancelled_subscription_ids": cancelled}
    except Exception as e:
        return {"attempted": True, "error": str(e)}


def delete_account(user_id: str) -> dict:
    """
    Full account deletion. Returns a report of what was actually deleted —
    not just "success: true", since a partial failure in one store
    shouldn't be hidden behind an overall success flag.
    """
    session_ids = get_user_session_ids(user_id)
    session_results = []
    from orca.serve import deletion_ledger, deletions

    deletion_ledger.record("user", user_id, user_id)       # L02-B6: before anything is destroyed; a restore of an older backup must not bring the account back

    for sid in session_ids:
        # L02-01: every session gets a durable deletion identity first, so a stale worker cannot resurrect it and the sweep finishes it if a store fails.
        deletions.begin(sid, user_id)
        view, raw = deletions.run_with_report(sid, user_id)
        report = dict(raw) if raw is not None else {"session_id": sid}
        report["deletion"] = {"deletion_id": view["deletion_id"], "state": view["state"], "access_revoked": True}
        session_results.append(report)
        _remove_session_title(sid)

    stripe_result = None
    customer_id = get_stripe_customer_id(user_id)
    if customer_id:
        stripe_result = _cancel_stripe_subscriptions(customer_id)

    # Account row + api_keys + usage_daily + user_sessions — last, so if
    # anything above fails we still know which sessions belonged to this
    # user (the user_sessions rows aren't gone yet until this call).
    delete_user_account_records(user_id)

    return {
        "user_id": user_id,
        "sessions_processed": len(session_ids),
        "session_results": session_results,
        "stripe_cancellation": stripe_result,
        "note": (
            "Historical audit log entries referencing this account are NOT deleted "
            "(tamper-evident by design — see legal/PRIVACY_POLICY.md §5). Sessions used "
            "before ever logging in (anonymous/unauthenticated) are not tracked and "
            "cannot be cascaded to by this deletion."
        ),
    }

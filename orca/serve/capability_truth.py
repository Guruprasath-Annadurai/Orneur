"""L02-08: one place that states, from facts, what this ORNEUR deployment can and cannot do - and who made the model that answers.

Everything user-visible about capability or model origin (``/api/models``, ``/api/capabilities``, the model-identity event, the system facts given to the model) is derived from this
module, so a statement cannot drift from another. Statuses are a closed vocabulary:

  implemented   works in this codebase and has automated evidence (``evidence`` lists test files that exist)
  gated         implemented but disabled unless licensed / configured
  partial       implemented with a stated limitation
  planned       designed, NOT implemented - never presented as available
  not_available deliberately not offered (usually a security decision)

Native ORNEUR model status mirrors ``orca.train.dryrun.tokenizer.family_foundation_status()`` (Cursor's foundation programme owns that value; a test fails if the two ever disagree).
"""
from __future__ import annotations

STATUSES = ("implemented", "gated", "partial", "planned", "not_available")

# Native ORNEUR weights: none exist. GENESIS has an interface only; NOVUS and AETERNUM are not available.
NATIVE_FAMILY_STATUS = {"genesis": "INTERFACE_ONLY", "novus": "NOT_AVAILABLE", "aeternum": "NOT_AVAILABLE"}
_TIER_FAMILY = {"nano": "genesis", "core": "novus", "ultra": "aeternum"}


def native_weights_available(tier: str | None = None) -> bool:
    """True only if ORNEUR-trained weights are actually being served. Today: never (no native checkpoint exists)."""
    fam = _TIER_FAMILY.get((tier or "").removeprefix("orca-"))
    statuses = [NATIVE_FAMILY_STATUS[fam]] if fam else list(NATIVE_FAMILY_STATUS.values())
    return any(s not in ("INTERFACE_ONLY", "NOT_AVAILABLE") for s in statuses)


def serving_facts(tier: str | None = None) -> dict:
    """What can truthfully be said about the model that answers. ``runtime`` is where it runs; ``weights_origin`` who trained the weights."""
    native = native_weights_available(tier)
    return {
        "runtime": "ollama",
        "location": "local",
        "weights_origin": "orneur" if native else "third_party",
        "native_orneur_weights": native,
        "native_family_status": NATIVE_FAMILY_STATUS.get(_TIER_FAMILY.get((tier or "").removeprefix("orca-"), ""), None),
    }


def system_facts_for_model(*, tools_available: bool = False) -> str:
    """A short, factual block given to the answering model, so what it says about itself and its abilities matches this deployment."""
    native = native_weights_available()
    origin = ("You are served from ORNEUR-trained weights." if native else
              "You are a third-party open-weights language model served locally through Ollama. ORNEUR has not published trained native weights for Genesis, Novus or Aeternum, so do not "
              "claim to be one of them, to have been trained by ORNEUR, or to have benchmark, accuracy or safety results.")
    acts = ("You may use only the tools listed to you in this conversation, and only their actual results count." if tools_available else
            "In this conversation you cannot run code, open or change files, browse the web, send messages, place orders or take any action in the world; you only produce text.")
    return (f"[Serving facts - supplied by the server]\n{origin}\n{acts}\n"
            "Never say you ran, searched, sent, ordered, saved or verified something unless a tool result in this conversation shows it. Code you write is a suggestion: say it has not been run. "
            "Answer only from the conversation and from passages explicitly labelled as document text; if you do not know, say so.")


def capabilities(*, email_delivery: str = "none", verification_required: bool = False) -> dict:
    """The capability table served at GET /api/capabilities. ``evidence`` entries are repository paths (a test asserts they exist)."""
    return {
        "schema": "orneur.capabilities/1",
        "model": {
            "served_by": "third-party open-weights model through a local Ollama runtime (see /api/models for the exact tag per tier)",
            "native_orneur_models": {"genesis": NATIVE_FAMILY_STATUS["genesis"], "novus": NATIVE_FAMILY_STATUS["novus"], "aeternum": NATIVE_FAMILY_STATUS["aeternum"],
                                     "note": "No ORNEUR-trained weights are available; tier names are product labels, not native models. No benchmark claim is made."},
        },
        "capabilities": {
            "streaming_chat": {"status": "implemented", "scope": "plain-chat answers on the local Ollama runtime are streamed from the model as it generates; evidence-routed (Truth Fabric) answers are delivered whole, labelled 'replayed'",
                               "evidence": ["tests/test_b01_raw_delta_lifecycle.py", "tests/journey/test_b01_streaming_live.py"]},
            "stop_cancellation": {"status": "implemented", "scope": "Stop closes the upstream model connection; nothing is committed for a stopped turn", "evidence": ["tests/test_l02_turn_recovery.py"]},
            "document_grounding": {"status": "implemented", "scope": "uploaded documents are retrieved, quoted as untrusted evidence, cited by source; the model is told when the documents do not contain the answer",
                                   "evidence": ["tests/test_l02_document_rag.py", "tests/test_l02_judge_trust_boundary.py"]},
            "verified_answers": {"status": "partial", "scope": "an answer is described as verified only when the Truth Fabric checked its claims against retrieved evidence; ordinary answers are model text, not verified",
                                 "evidence": ["tests/test_cognitive_kernel_truth_fabric_integration.py"]},
            "conversation_history_and_deletion": {"status": "implemented", "scope": "conversations are saved per account and deletion is authoritative across the application's stores; copies outside the application (host backups) are not covered",
                                                  "evidence": ["tests/test_l02_deletion_lifecycle.py"]},
            "web_search_tool": {"status": "implemented", "scope": "read-only web search can be used by the assistant on turns where it plans to; a search sends the query text to the configured search provider", "evidence": ["tests/test_l02_tool_authority.py"]},
            "code_execution": {"status": "not_available", "scope": "the web assistant never executes code, shell commands or file operations; code in answers is suggested text", "evidence": ["tests/test_g020_agent_tool_authority.py"]},
            "file_system_access": {"status": "not_available", "scope": "no server file access from a web conversation", "evidence": ["tests/test_g020_agent_tool_authority.py"]},
            "multi_agent_ultra": {"status": "gated", "scope": "a licensed multi-agent orchestration mode; its sub-agents are roles run on the same served model, not separate models", "evidence": ["tests/test_api_ultra_gateway_cutover.py"]},
            "email_verification": {"status": "implemented" if email_delivery == "smtp" else "partial",
                                   "scope": {"smtp": "verification and recovery emails are sent through the configured provider",
                                             "local_sink": "messages are written to a local directory and delivered to nobody (engineering only)",
                                             "none": "no email delivery is configured: verification and recovery emails cannot be sent"}.get(email_delivery, "unknown"),
                                   "enforced": bool(verification_required), "evidence": ["tests/test_l02_account_security.py"]},
            "cloud_browser_agent": {"status": "planned", "scope": "not implemented; no browsing, form-filling or purchasing is performed", "evidence": []},
            "proof_opportunity_bridge": {"status": "planned", "scope": "not implemented", "evidence": []},
            "operational_sub_agent_fleet": {"status": "planned", "scope": "agent definitions exist; no autonomous agent fleet is operating", "evidence": []},
            "external_actions": {"status": "not_available", "scope": "ORNEUR does not send email, place orders or contact third parties on your behalf", "evidence": []},
        },
    }

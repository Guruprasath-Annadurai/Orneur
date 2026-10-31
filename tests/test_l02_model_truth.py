"""L02-08 -- what ORNEUR says about the model and about itself must match what is true.

The checks span the API (``/api/models``, ``/api/capabilities``, the model-identity event), what the model itself is told, the served pages and the README. A statement that
drifts from ``orca.serve.capability_truth`` fails here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from orca.serve import capability_truth as ct
from tests.test_g006_tenant_isolation import _hdr, _signup, client  # noqa: F401
from tests.test_product_flows_fake_ollama import _events, fake  # noqa: F401

ROOT = Path(__file__).resolve().parent.parent


# ── the capability table ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_capability_table_uses_a_closed_vocabulary_and_every_claim_has_evidence_that_exists(client):
    body = client.get("/api/capabilities").json()
    assert body["schema"] == "orneur.capabilities/1"
    for name, cap in body["capabilities"].items():
        assert cap["status"] in ct.STATUSES, name
        assert cap["scope"], name
        if cap["status"] in ("implemented", "gated", "partial"):
            assert cap["evidence"], f"{name} is claimed as {cap['status']} with no evidence"
        for path in cap["evidence"]:
            assert (ROOT / path).exists(), f"{name}: evidence file {path} does not exist"


def test_unbuilt_capabilities_are_never_presented_as_available(client):
    caps = client.get("/api/capabilities").json()["capabilities"]
    for name in ("cloud_browser_agent", "proof_opportunity_bridge", "operational_sub_agent_fleet"):
        assert caps[name]["status"] == "planned", name
    for name in ("code_execution", "file_system_access", "external_actions"):
        assert caps[name]["status"] == "not_available", name
    assert caps["multi_agent_ultra"]["status"] == "gated" and "same served model" in caps["multi_agent_ultra"]["scope"]


def test_email_capability_reports_the_real_delivery_mode(isolated_home, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from orca.serve.api import app

    c = TestClient(app)
    monkeypatch.delenv("ORNEUR_MAIL_SINK_DIR", raising=False)
    assert c.get("/api/capabilities").json()["capabilities"]["email_verification"]["status"] == "partial"
    monkeypatch.setenv("ORNEUR_MAIL_SINK_DIR", str(tmp_path))
    cap = c.get("/api/capabilities").json()["capabilities"]["email_verification"]
    assert cap["status"] == "partial" and "delivered to nobody" in cap["scope"], "a local sink must never be described as delivery"


def test_native_status_matches_the_foundation_programmes_own_value():
    """Cursor's FOUNDATION programme owns this status; drift between it and what ORNEUR tells users fails here."""
    from orca.train.dryrun.tokenizer import family_foundation_status

    f = family_foundation_status()
    assert {k: f[k] for k in ("genesis", "novus", "aeternum")} == ct.NATIVE_FAMILY_STATUS
    assert f["trained_checkpoint"] is False and ct.native_weights_available() is False


# ── /api/models and the identity event ───────────────────────────────────────────────────────────────────────────────────────────

def test_models_endpoint_states_weights_origin_for_every_tier(client, fake):
    body = client.get("/api/models").json()
    for tier, fam in (("nano", "genesis"), ("core", "novus"), ("ultra", "aeternum")):
        t = body[tier]
        assert t["weights_origin"] == "third_party" and t["native_orneur_weights"] is False and t["runtime"] == "ollama", (tier, t)
        assert t["native_family_status"] == ct.NATIVE_FAMILY_STATUS[fam]
        assert t["lifecycle"] != "PRODUCTION" or t["disclosure"], "a non-production tier must carry a disclosure"


def test_the_model_event_and_done_event_carry_provenance_and_agree(client, fake):
    t, _ = _signup(client)
    evs = _events(client, _hdr(t), {"message": "hello provenance", "model_variant": "core"})
    ident = next(e["identity"] for e in evs if e["type"] == "model")
    done = evs[-1]
    for field, value in (("weights_origin", "third_party"), ("native_orneur_weights", False), ("runtime", "ollama"), ("backend", "ollama"), ("data_left_infrastructure", False)):
        assert ident[field] == value, (field, ident)
    assert done["model_identity"] == ident, "the final identity must equal the announced one"
    assert done["delivery"] == "upstream" and done["persisted"] == "saved"


def test_replayed_delivery_is_labelled_replayed(client, fake):
    from orca.serve import turn_requests  # noqa: F401

    t, _ = _signup(client)
    h = _hdr(t)
    sid = client.post("/api/docs/upload", files={"file": ("n.txt", b"alpha beta gamma delta", "text/plain")}, headers=h).json()["session_id"]
    evs = _events(client, h, {"message": "alpha", "session_id": sid})
    stream = next(e for e in evs if e["type"] == "stream")
    done = evs[-1]
    assert stream["delivery"] == done["delivery"] and stream["cancellable"] == (done["delivery"] == "upstream")


# ── what the model is told about itself ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_answering_model_is_told_what_it_is_and_what_it_cannot_do(client, fake):
    t, _ = _signup(client)
    n0 = len(fake.requests)
    _events(client, _hdr(t), {"message": "what are you and can you run my code?"})
    answering = [q for q in fake.requests[n0:] if q.get("stream")]
    msgs = answering[-1]["messages"]
    assert msgs[0]["role"] == "system" and msgs[-1] == {"role": "user", "content": "what are you and can you run my code?"}
    facts = msgs[0]["content"]
    assert "third-party open-weights" in facts and "not published trained native weights" in facts
    assert "cannot run code" in facts and "Code you write is a suggestion" in facts
    assert "ORNEUR-trained weights" not in facts


def test_persona_prompts_carry_the_same_facts_and_make_no_native_or_benchmark_claim():
    from orca.personas import get_persona_system

    forbidden = re.compile(r"(trained (entirely )?by orneur|orneur-trained weights|state[- ]of[- ]the[- ]art|outperform|beats (gpt|claude|gemini)|\d+(\.\d+)?% on (mmlu|humaneval))", re.I)
    for v in ("nano", "core", "ultra"):
        text = get_persona_system(v)
        assert "third-party open-weights" in text and "Serving facts" in text, v
        scanned = re.sub(r"\[SELF-AWARENESS NOTICE.*?\n\n", "", text.split("[Serving facts")[0], flags=re.S)       # that notice FORBIDS such claims; it is not one
        hit = forbidden.search(scanned)
        assert hit is None, f"{v}: persona makes an unqualified claim: {hit.group(0)!r}"
        assert "ORNEUR-trained weights" not in text


# ── tool execution status ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_tool_call_the_gate_refused_is_not_reported_as_a_used_tool():
    from orca.brain.agent import AgentLoop
    from orca.tools import SURFACE_WEB, Tool, ToolRegistry

    class Brain:
        def complete(self, messages, system=None, **k):
            return json.dumps({"action": "tools", "calls": [{"tool": "web_search", "args": {"query": "x", "session_id": "someone-else"}}]}) if "planning module" in (system or "") else "ok"

        def stream(self, *a, **k):
            yield "ok"

    reg = ToolRegistry(surface=SURFACE_WEB)
    reg.register(Tool("web_search", "", lambda query, n=5: "r", {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}))
    loop = AgentLoop(Brain(), reg, reflect=False)
    _, trace = loop.run("search x", "sys")
    assert [tc.refused for tc in trace.tool_calls] == ["unexpected_parameter"]
    used = [tc.tool for tc in trace.tool_calls if not tc.refused]
    assert used == []


# ── the served pages and README ─────────────────────────────────────────────────────────────────────────────────────────────────

FORBIDDEN_CLAIMS = [
    r"\b100\s+(sub-?agents|agents)\b", r"native (genesis|novus|aeternum)( model)?( weights)? (is|are) (now )?(available|live|released)", r"\b(genesis|novus|aeternum) (was|is) trained by orneur\b",
    r"cloud browser (agent )?(is )?(live|available|now available)", r"proof \+ opportunity bridge (is )?(live|available)", r"(beats|outperforms|surpasses) (gpt|claude|gemini)",
    r"state[- ]of[- ]the[- ]art (accuracy|performance)", r"\bfully (autonomous|verified) agent",
]


@pytest.mark.parametrize("path", ["orca/serve/web/conversation.html", "orca/serve/web/landing.html", "orca/serve/web/index.html", "orca/serve/web/trust.html", "README.md"])
def test_served_pages_and_readme_make_none_of_the_forbidden_claims(path):
    text = (ROOT / path).read_text(errors="replace")
    for pat in FORBIDDEN_CLAIMS:
        m = re.search(pat, text, re.I)
        assert m is None, f"{path} contains an unqualified claim matching {pat!r}: {m.group(0)!r}"


def test_the_conversation_page_discloses_third_party_weights_in_model_details():
    html = (ROOT / "orca/serve/web/conversation.html").read_text()
    assert "Third-party open model (not trained by ORNEUR)" in html and "info.weights_origin" in html
    assert "No ORNEUR native model is currently available for live inference" in html

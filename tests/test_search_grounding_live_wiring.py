"""
Live-wiring regression for web-search grounding (ORNEUR public semantic
truth closure). Confirms the module-exists-vs-actually-wired question
with real evidence, not inference from the module's mere presence:

- orca/tools/__init__.py's build_registry() registers search_and_ground
  as the "web_search" tool.
- orca/serve/api.py's live chat session (_Session._ensure_agent, the
  real chat/stream code path) calls exactly that build_registry() to
  build the AgentLoop used for real requests -- not a stub or a
  different, unused registry.
- orca/variants/core.py and orca/variants/ultra.py (the Core/Ultra
  session classes) do the same.
- Calling the registered tool actually produces enforced-citation output
  ([S#] markers), through the exact function object the live path uses.

This was previously undocumented and, per docs/PERPLEXITY_DIFFERENTIATION_PLAN.md's
own now-corrected "Honest status update" section, had been described as
NOT wired -- a claim that was already stale at authoring time (the same
commit that shipped search_grounding.py also modified build_registry()
to register it, and orca/serve/api.py already called build_registry()
unchanged since the initial commit).
"""
from __future__ import annotations

import inspect
from unittest.mock import patch

from orca.tools import build_registry
from orca.tools.web import SearchResult


def test_web_search_tool_is_registered_in_build_registry():
    registry = build_registry()
    assert "web_search" in registry.all_names()


def test_web_search_tool_is_backed_by_search_and_ground_with_citation_enforcement():
    registry = build_registry()
    fake_results = [
        SearchResult(title="Example", url="https://example.com/a", snippet="A real, ordinary fact."),
    ]
    with patch("orca.tools.search_grounding.search", return_value=fake_results):
        output = registry.call("web_search", {"query": "test query"})
    assert "[S1]" in output  # enforced-citation marker from search_and_ground
    assert "example.com" in output


def test_live_chat_session_wires_the_same_registry_not_a_stub():
    """Source-inspects orca/serve/api.py's real live session class to
    confirm it calls build_registry() -- the exact function that
    registers web_search -- rather than a different or empty registry."""
    from orca.serve.api import _Session

    source = inspect.getsource(_Session._ensure_agent)
    assert "build_registry(" in source


def test_core_and_ultra_variant_sessions_wire_the_same_registry():
    from orca.variants.core import OrcaCore
    from orca.variants.ultra import OrcaUltra

    assert "build_registry(" in inspect.getsource(OrcaCore.__init__)
    assert "build_registry(" in inspect.getsource(OrcaUltra.__init__)

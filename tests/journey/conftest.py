from __future__ import annotations

import pytest

from tests.journey.harness import OllamaTap, live_server


def pytest_collection_modifyitems(config, items):
    """Journey tests are opt-in (``pytest tests/journey -m journey_live`` or ORNEUR_JOURNEY=1):
    they need a real Ollama, Redis and Chromium, and they FAIL (never skip) when one is absent,
    so they must not leak into the ordinary whole-repo run. live_ollama_smoke additionally keeps
    them out of scripts/ci/run_deterministic_tests.sh (`-m "not live_ollama_smoke"`)."""
    import os
    mine = [i for i in items if "tests/journey" in str(i.fspath)]
    for item in mine:
        item.add_marker(pytest.mark.live_ollama_smoke)
        item.add_marker(pytest.mark.journey_live)
    opted_in = "journey_live" in (config.option.markexpr or "") or os.environ.get("ORNEUR_JOURNEY") == "1" \
        or any("tests/journey" in str(a) for a in config.args)
    if mine and not opted_in:
        config.hook.pytest_deselected(items=mine)
        items[:] = [i for i in items if i not in mine]


@pytest.fixture(scope="module")
def tap():
    t = OllamaTap()
    yield t
    t.close()


@pytest.fixture(scope="module")
def server(tmp_path_factory, tap):
    home = tmp_path_factory.mktemp("journey-home")
    with live_server(home, extra_env={"ORNEUR_OLLAMA_HOST": tap.url, "OLLAMA_HOST": tap.url}) as srv:
        yield srv

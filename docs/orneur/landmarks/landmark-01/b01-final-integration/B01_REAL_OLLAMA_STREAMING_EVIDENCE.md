# Real Ollama Streaming Evidence

**Status: NOT VERIFIED in this agent environment**

- `http://127.0.0.1:11434` unreachable
- No `llama3.2:1b` exercised

### Antigravity / workstation command

```bash
ollama pull llama3.2:1b
# optional alias used by journeys:
ollama cp llama3.2:1b orneur-journey
pytest -q tests/journey/test_journey_api_live.py tests/journey/test_journey_browser.py -m live_ollama_smoke
```

Fixture proof (not live): `test_s1b_live_server_measurable_chunk_spread` with delayed FakeOllama ≥0.2s chunk spread.

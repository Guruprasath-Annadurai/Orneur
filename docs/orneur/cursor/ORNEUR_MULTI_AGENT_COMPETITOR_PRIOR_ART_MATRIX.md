# Competitor and prior-art notes

Retrieved 24 October 2026, Asia/Calcutta. These are documentation claims by the publishers. This pass did not run their software and did not compare task scores.

| Source | What the page says | Retrieved URL |
|---|---|---|
| OpenAI Agents SDK | Handoffs transfer a turn to a specialist. Agents-as-tools keep the manager responsible. Tracing records model calls, tools, handoffs, and guardrails. | https://developers.openai.com/api/docs/guides/agents/orchestration |
| Anthropic Research | A lead agent spawns subagents and a CitationAgent attaches citations. The write-up describes an internal research system, not an ORNEUR benchmark. | https://www.anthropic.com/engineering/multi-agent-research-system |
| Anthropic managed agents | Subagents have isolated threads. Dynamic workflows are background programs. The docs tell the caller to set a session budget. | https://platform.claude.com/docs/en/managed-agents/multiagent-orchestration |
| Google ADK and A2A | Local sub-agents share a process. Remote agents use the A2A protocol. A2A v1.0 describes discovery, tasks, and security schemes. | https://adk.dev/a2a/ and https://a2a-protocol.org/latest/whats-new-v1/ |
| LangGraph | Checkpointers snapshot graph state per superstep, including human interrupt and resume. Sync durability writes before the next step. | https://docs.langchain.com/oss/python/langgraph/checkpointers |
| Microsoft Agent Framework | Checkpoints are saved at superstep boundaries. The docs say checkpoint storage is a trust boundary. | https://learn.microsoft.com/en-us/agent-framework/workflows/checkpoints |

Classification of the ORNEUR work in this pass:

| Proposal | Class | Why |
|---|---|---|
| Multi-agent handoff or team split | STANDARD_EXISTING_CAPABILITY | OpenAI, Anthropic, and ADK already document it. |
| Citation attached to a claim | EXISTING_BUT_IMPROVABLE | Anthropic describes a CitationAgent. ORNEUR's digest check is a fixture, not a better measured result. |
| Producer cannot verify itself | UNCOMMON_COMBINATION | The split is explicit here. No head-to-head score exists. |
| Denial receipt for one guarded path | EXISTING_BUT_IMPROVABLE | Guardrails and traces already exist. This receipt is unsigned. |
| Unknown price stays UNKNOWN | EXISTING_BUT_IMPROVABLE | Budget caps are documented elsewhere. This function only refuses to invent a number. |
| Larger team is better | RESEARCH_HYPOTHESIS | On one synthetic equation, three handlers refute what one handler leaves as OBSERVED. Ten handlers do not improve on three. That is not a vendor comparison. |

No result in this file is `WORLD_FIRST`, `UNIQUE`, `NEVER_DONE_BEFORE`, or `BEST_IN_WORLD`.

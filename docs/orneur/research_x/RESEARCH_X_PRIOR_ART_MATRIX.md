# Prior art

Pages fetched in this session, titles only:

| Source | Observed title |
|---|---|
| https://arxiv.org/abs/2310.11511 | Self-RAG: Learning to Retrieve, Generate, and Critique through Self-Reflection |
| https://arxiv.org/abs/2401.15884 | Corrective Retrieval Augmented Generation |
| https://arxiv.org/abs/2401.18059 | RAPTOR: Recursive Abstractive Processing for Tree-Organized Retrieval |
| https://arxiv.org/abs/2404.16130 | From Local to Global: A Graph RAG Approach to Query-Focused Summarization |
| https://aclanthology.org/2022.naacl-main.272/ | ColBERTv2: Effective and Efficient Retrieval via Lightweight Late Interaction |

Microsoft GraphRAG's DRIFT search, Anthropic's contextual retrieval notes, LlamaIndex, Haystack, PyTorch distributed training, TorchTitan, and the OWASP vector-and-embedding entry at https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/ were not re-read line by line in this session. They are named so the prototypes below are not described as firsts.

| ORNEUR piece | Closest named prior | Difference in this tree | Status |
|---|---|---|---|
| `mode=self-rag` | Self-RAG (2310.11511) | Runtime heuristic, no trained critic | Research prototype |
| `mode=corrective` | Corrective RAG (2401.15884) | One quoted reformulation | Research prototype |
| `mode=raptor` | RAPTOR (2401.18059) | Non-authoritative summary flag only | Research prototype |
| `mode=graph` | GraphRAG (2404.16130) | Entity edges, no community summary | Research prototype |
| `maxsim` | ColBERTv2 | Hash-token maxsim, no ColBERT weights | Research prototype; `mode=colbert` unavailable |
| `mode=contextual` | Contextual retrieval | Uses a stored prefix, does not generate one | In-memory contract |
| Federated partials | Existing `federated_search` | Separate in-memory connectors | Does not replace the existing module |

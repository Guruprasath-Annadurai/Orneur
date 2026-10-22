# Retrieval and memory integration

Memory mode keeps documents whose `memory_owner` is the principal. `Corpus.delete_memory` removes a row from later retrieval. A document with another session id is not visible to this scope. The test is `test_code_sql_federated_memory_and_conversation`.

Conversational mode replaces `it`, `that`, or `same` with the last string in `request.history`. It does not read another session's stored turns. The caller has to pass only history that the session is allowed to hold.

The existing `orca/memory/` package was not modified and was not re-tested in this session. The kernel does not write episodic memory.

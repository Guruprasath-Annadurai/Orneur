# L03 — handoff to Antigravity for independent review

Status of this candidate: `VERIFIED_ENGINEERING` pending the exact-head CI recorded in `L03_EXACT_HEAD_CI.md`. **Not independently qualified**; nothing here pre-empts your verdict. Draft PR against the PR #139 branch (`38e0d31`); PR #139, #141, #143, #145 and Cursor's MASTER-03 branch were not modified. Not merged, not deployed, no paid infrastructure, no real customer data or secrets, no training, formal pretraining acceptance remains 0/95.

## Reproduce the "failing before" and "passing after"
```
# baseline against an exact checkout of 38e0d31 (so the lab cannot import the new code)
git worktree add /tmp/base 38e0d311991875366f2bc88a39690c7b2b6ea3ee
L03_REPO=/tmp/base python docs/orneur/landmarks/landmark-03/evidence/baseline/l03_baseline_lab.py            # E1…E11 (≈ 3 min)
L03_REPO=/tmp/base python docs/orneur/landmarks/landmark-03/evidence/baseline/l03_baseline_lab.py E12        # deleted document text on disk
L03_REPO=/tmp/base python docs/orneur/landmarks/landmark-03/evidence/l03_server_stall_probe.py 18            # real server, 18 s lock
# the same, against the candidate
L03_REPO=$PWD python docs/orneur/landmarks/landmark-03/evidence/l03_server_stall_probe.py 18
L03_PASS_ENV="ORNEUR_VECTOR_MODE=service" L03_REPO=$PWD python …/baseline/l03_baseline_lab.py E12
python docs/orneur/landmarks/landmark-03/evidence/after/l03_bench.py ; python …/after/l03_faults_bench.py
# tests (chromadb required; a missing chromadb FAILS)
pytest tests/test_l03_vector_service.py tests/test_l03_lifecycle.py tests/test_l03_failure_lab.py -p no:cacheprovider
pytest tests/journey/test_l03_vector_live.py -p no:cacheprovider
```
Use `pgrep -f "[o]rca.vectorstore.server"` to see owner processes; `orca vector status|stop`; `kill -USR1 <owner pid>` dumps its thread stacks into `/tmp/orneur-vec-<uid>-<hash>/owner.log`.

## Things to try to break (all should end bounded, truthful, and leak nothing)
| Attack | Expected |
|---|---|
| hold `BEGIN EXCLUSIVE` on `memory/vectors/chroma.sqlite3` or `docs/vectors/chroma.sqlite3` and exercise remember / recall / upload / delete / stream | `/livez`, `/readyz` stay fast; writes refused at the deadline (`504 request_timeout`, `503 server_busy`); chat turns still complete; recovery when the lock ends; a deletion returns `202` (never a false `200`) |
| `SIGSTOP`/`SIGKILL` the owner during traffic; start 10 workers together | one owner; replaced in < 1 s (kill) / ~7 s (freeze); no data loss; no zombie |
| send frames directly to the socket (`/tmp/orneur-vec-*/sock`): wrong token, huge frame, path outside the data dir, unknown method, pickle bytes | refused; the owner survives |
| two session ids with the same first 8 characters (library level; the API refuses the second with `404` through the ownership layer) | second is refused at the vector layer; its deletion leaves the first intact |
| delete a document/conversation, then scan **every file** under `memory/vectors` and `docs/vectors` for its text | absent when `RECLAIMED`; if `DEFERRED` it may be present and the backlog counter says so |
| restore old vector files next to a tombstone / registry that says deleted | unreachable, then removed by the sweep |
| fill the write lane (3 stuck writes + 16 waiting) then try reads of other conversations | writes refused immediately; reads depend on whether the owner froze (see limits) |
| damage `orneur_bindings.sqlite`, then recall/store | nothing served or written until repaired |
| set `ORNEUR_VECTOR_NOFILE=100` with `ORNEUR_VECTOR_MAX_OPEN=100000` and create 100 conversations | recycling on descriptor pressure; ≤ a few failures, none after |
Not tried by us: hostile processes running as the same Unix user (the socket/token protect against other users only); disk-full during rebuild; a rebuild interrupted exactly between "delete old" and "rename" (covered by `test_a_rebuild_interrupted_between_dropping_…`: the next open of the conversation, or the next rebuild, completes the rename; please try other interruption points, e.g. between the copy and its verification, or disk-full during the copy); chromadb versions other than 1.5.9; macOS.

## Review first
`orca/vectorstore/{host,server,client,__init__,protocol,paths,pending}.py`, `orca/brain/memory.py` (`LongTermMemory`, `_delete_sync`, `vector_maintenance`), `orca/docs/store.py` (`DocStore` lazy open, `reclaim_doc_vectors`, `drop_session_collection`), `orca/serve/api.py` (lifespan, `_vector_failure_response`, the `to_thread` offloads), `orca/serve/deletions.py` (`_vector_collection_absent`, `_vector_collection`), `orca/gateway/reconcile.py` (`_sweep_doc_chunks`).

## Not proven / cross-workstream
* Integration with B6 (restore must stop the vector owner) — `L03_BLOCKER_REGISTER.md` L03-B1, `evidence/cross_workstream*`. Do not take the comparison as qualification of PR #143.
* The production image has no chromadb; every claim here applies where the `memory` extra is installed.
* Independent qualification of any kind; capacity, availability or latency targets; behaviour beyond one workstation.

Please record your verdict against the exact SHA with your own evidence-class split; we will not edit your documents.

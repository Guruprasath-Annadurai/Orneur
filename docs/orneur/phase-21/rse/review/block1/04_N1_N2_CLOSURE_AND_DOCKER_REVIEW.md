# Block-1 audit package — Part 4: IMP-1 carry-forward closure (G) and Docker lab review preparation (H)

`NON_NORMATIVE_AUDIT_EVIDENCE`.

## G. Accepted LOW findings from IMP-1

Both were accepted as non-blocking for IMP-1 and carried to the ledger/freshness work. IMP-1 code (`orca/rse/imp1/*`, canonical at `464b602…`) must not be modified to fix them; the fix belongs to IMP-3 as an **authoritative state layer around** the accepted pure verifier.

### G1. N-1 — stale-grant-induced challenge invalidation (availability)

**Observed (independently, IMP-1R retest).** `consumer_verify` voids the supplied `ChallengeLedger` on any snapshot mismatch **before** it checks that the grant is addressed to this role or this ledger's outstanding challenge. Reproduction: present any validly signed older grant bound to a *different* challenge together with a higher authenticated version → the ledger's own challenge becomes void and the ledger is permanently void. Effect: anyone who can place an old validly signed grant on the carried medium can force challenge re-issuance (an owner round trip). Not fail-open.

**Frozen text.** CL1 §11 says the consumer "voids its outstanding challenge" when it refuses a grant because of a snapshot difference or a higher authenticated version. It does not say whether a grant that is **not** bound to the outstanding challenge or role triggers the void. This ambiguity is **OAQ-7** and needs an architect ruling *before* IMP-3 chooses.

**Closure criteria (either ruling).**

| Ruling | IMP-3 must do | Acceptance evidence |
|---|---|---|
| A — literal (any refused grant voids) | accept it as a documented availability residual; bound it: (1) record every void as evidence; (2) rate-limit challenge re-issuance per role; (3) surface a void count to the owner; (4) show no authority is gained by a void | regression R-N1-01, -02, -05, -06 pass; residual listed |
| B — narrowed (void only when the refused grant's challenge equals the outstanding challenge **and** its target is this role) | change the ledger layer so foreign/stale grants are refused without state change | regression R-N1-01…-06 pass with R-N1-03 expecting *no* state change |

Regression tests (written now, run against IMP-3):

| ID | Scenario | Expected |
|---|---|---|
| R-N1-01 | stale validly signed grant bound to challenge X, consumer outstanding challenge Y | refused; under B, Y still valid; under A, void is recorded as evidence |
| R-N1-02 | stale grant for a *different role* | refused; under B, no void |
| R-N1-03 | foreign grant, then the legitimate fresh grant for Y | under B the legitimate grant still succeeds; under A the owner re-issues once, and the void is logged |
| R-N1-04 | after a legitimate void, replay of the voided grant on a *reconstructed* state object | still refused (state is authoritative, not caller-owned) |
| R-N1-05 | repeated stale-grant flooding | bounded re-issuance rate; evidence recorded; no unbounded state growth |
| R-N1-06 | legitimate registry update before activation | grant refused, challenge voided, fresh flow works (CL1 §11) |

### G2. N-2 — caller-owned replay journal and highest-authenticated-version state

**Observed.** IMP-1 is a pure verifier: `highest_authenticated_version` and `challenge_ledger` are parameters, so a caller can pass a lower version or a freshly constructed ledger with a stale challenge and the old grant verifies. IMP-1 states this honestly; `NOT_CLAIMED` should list "caller-supplied replay state".

**Required IMP-3 controls (derived from RSE12_02 §5/§7, RSE12_03 §1, CL1 §11, RSE12_01 §6):**

1. **Authoritative durable journal inside the role** (write-ahead, full-sync) holding: the outstanding challenge, the consumed-challenge set, voided challenges, per-stream accepted sequence, completed envelope batches. Callers cannot construct, replace or clear it; the verifier reads it, never receives it as a parameter.
2. **Highest authenticated registry version derived, not supplied**: from authenticated registry updates that carry the required witness acknowledgements, stored in sealed state and combined as `max(card, sealed, witnessed)` (RSE12_01 §6). A lower value cannot be passed in.
3. **Journal rollback detection**: the journal head is bound into each role checkpoint; a journal restored to an older state shows a head older than the last witnessed checkpoint and is detected at the next witnessing (detective; prevention only for K-class on the Witness via the TPM fence — hardware, out of this block). Residual R-RB2 (replay of one already-consumed routine grant after in-state rollback, bounded by ceilings) is declared, not claimed fixed.
4. **A wrapper entry point** that composes the accepted `consumer_verify` with these authoritative inputs; no public path may accept caller-supplied ledger or highest-version.

Regression tests:

| ID | Scenario | Expected |
|---|---|---|
| R-N2-01 | construct a new journal/ledger object holding a consumed challenge, then verify the old grant | cannot revive: the authoritative store is consulted, not the object |
| R-N2-02 | attempt to call the wrapper with a caller-supplied `highest_authenticated_version` or ledger | rejected: parameter does not exist / unexpected-argument fail-closed |
| R-N2-03 | delete, truncate, replace the journal file with an older copy | next operation sees inconsistency → QUARANTINED, or the next witnessing detects the stale head; never silent acceptance |
| R-N2-04 | lower the sealed floor / present an older registry | refused: max of sources |
| R-N2-05 | crash between recording consumption and releasing the secret | restart finds consumption recorded → INTERRUPTED, no second execution |
| R-N2-06 | durability: journal write ordering under simulated power loss (including macOS full-sync semantics) | consumption-start never visible after a lost write |
| R-N2-07 | residual statement | NOT_CLAIMED lists caller-supplied replay state removal only after R-N2-01…-06 pass |

## H. Docker "RSE Synthetic Integration Lab" — review preparation

Files are not yet available (no branch or PR found at `464b602`), so every item is `PENDING_DOCKER_FILES`. Standing rule for the review: **the lab is synthetic test infrastructure and is never evidence of a real P1 security boundary.** Any claim that it demonstrates TPM, Secure Boot, hardware isolation, owner-token custody, or "hardware-rooted" anything is a false-claim finding.

| Area | What to check | Finding if |
|---|---|---|
| Privileges | `privileged: true`, added capabilities (`SYS_ADMIN`, `NET_ADMIN`, `SYS_PTRACE`), `no-new-privileges` absent, user = root, `--pid=host`, `--ipc=host`, `--net=host`, device mounts | HIGH if used to emulate role isolation; otherwise MEDIUM |
| Host mounts | bind mount of the repository read-write, home directory, `docker.sock`, `/var/run`, credential directories, `~/.ssh`, cloud config | docker.sock or credential mount = HIGH (container escape / secret exposure) |
| Network | each synthetic role on its own network; `internal: true` or `network_mode: none` for Crown/Forge/Witness; only the Monitor-Lite stand-in reachable; DNS/egress blocked; no published ports on `0.0.0.0` | role isolation claimed but a shared network allows lateral traffic = MEDIUM; any role with internet = HIGH to the claim |
| Isolation of roles | separate images, users, volumes; no shared writable volume between "Forge" and "Witness" except the simulated transfer medium; no shared secrets; no shared Python process | shared volume or process = the lab proves nothing about separation (MEDIUM, false-claim risk) |
| Secrets | no real key/token in image layers, env, build args, compose files, logs; test keys derived from public labelled seeds; `.env` files; image history (`docker history`) | any real-looking secret = CRITICAL; unlabeled generated key committed = MEDIUM |
| Reproducibility | base images pinned by digest; locked dependencies with hashes; no `latest`; no network at test time; deterministic seeds and clocks | unpinned = LOW/MEDIUM; non-deterministic tests = MEDIUM |
| Time and clocks | roles share the host clock; tests that rely on wall time | unfrozen clock where the spec says clock is advisory = LOW |
| Attack harness quality | each attack has a negative control; every defence has a "disable it → test fails" mutation; attacks implemented as an adversary outside the role code; results are assertions, not logs | harness that only prints, or whose "attacks" call the same code path as the defence = HIGH (false assurance) |
| Evidence integrity | evidence files written by the system under test and signed with in-container keys are self-attested; evidence hashed and stored outside the container; run manifest includes image digests and commit SHA | self-signed evidence presented as independent = MEDIUM |
| Claims | README/report wording: "secure", "hardware", "attested", "tamper-proof", "P1 equivalent" | any such claim = false-claim finding (MEDIUM; HIGH if used for an acceptance row) |
| Scope | uses only synthetic data; never reads protected benchmark; no cloud; no GPU | violation = BLOCKER |
| Relationship to acceptance | which `C##` rows the lab claims to exercise; real-hardware rows (`C24`–`C35`) must stay `PENDING_REAL_HARDWARE` | marking real-hardware rows as satisfied = HIGH |

Good use of the lab (to recommend, not require): reproduce this package's OCR1 vectors across roles; end-to-end happy path of G→Forge→bundle→Witness; fault injection of crash/restart and medium corruption; the T2/T3 families that need several processes.

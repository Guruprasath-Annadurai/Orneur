# RSE block 1 — owner approval record

NON_NORMATIVE. Not in Manifest V3. This file records bounded owner decisions. It does not merge PR #8 or PR #9, and it does not claim canonical integration.

Verified before the decisions were applied:

| Item | Value |
| --- | --- |
| PR #8 | open, draft, not merged, head `da567d927b61c41e253b42732aad249b5fdbb104`, base `main` |
| PR #9 | open, draft, not merged, head `c127780abbe6790cd0ba76beb6755615752af9b2`, base `cursor/rse-master-imp2-imp4-c04e` |
| Canonical main | `464b602f3f259b56f139c3304828baa660e6b860` |
| Exact-SHA CI of the accepted implementation | run `37884389862` |
| Independent verdict on `da567d9` | `RSE_MASTER_BLOCK_1_ACCEPTED` |

`da567d9` is not rewritten. This successor sits on `c127780`. Run `37884389862` does not certify this successor.

## Approval 1 — five profiles

APPROVED for synthetic software-gate use, non-normative, version-specific, and restricted to the accepted implementation layouts:

- OMJ1 v1
- OFJ1 v2
- OBS1 v2
- OCJ1 v1
- ORJ1 v2

The byte layouts in `RSE_BLOCK1_OWNER_RATIFICATION_PACKAGE.md` stay the specification. They are not inserted into Manifest V3 and are not new constitutional authority. Caps of 8,192 challenge-set members and 4,096 forfeiture intervals are synthetic-stage operational limits. They are not an unlimited production lifetime.

## Approval 2 — OCK1 and OCH1 domains

CONDITIONS MET. The clarification is recorded in `RSE_BLOCK1_OCK1_OCH1_CLARIFICATION_ADDENDUM.md`.

Confirmed against `orca/rse/imp3/records.py` on `da567d9`, which this successor does not edit:

- Signed message is `b"OCK1-SIG" + b"\\x00" + body` and `b"OCH1-SIG" + b"\\x00" + body`.
- Each body is 117 bytes and each record is 181 bytes.
- `RSE12_02` §3 names the fields and does not name a conflicting domain. Clarification 1 ACR-3 does not mention these records. OCA1 stays `"OCA1-SIG" ‖ 0x00 ‖`.
- Verification uses the same messages. No new signature authority is added.

Manifest V3 and the frozen files are not edited.

## Approval 3 — quarantine and class K

DEFERRED. ACR-B1-2 stays an architecture change request. Recipient-local quarantine on ORJ1 v2 stays as accepted. Cross-role propagation, class-K `QUARANTINED` to `RECOVERY`, and witness-backed recovery are not implemented. Unsupported classes stay fail-closed.

## Approval 4 — dependency hardening

AUTHORIZED and applied on this successor, not on `da567d9`:

- `dev` and `rse` extras pin `pyhpke==0.6.5`.
- `cryptography` stays `>=49.0.0,<51.0.0`. Resolved lock version is 50.0.2, inside that window and inside pyhpke 0.6.5's `cryptography>=42.0.1,<52`.
- `requirements/rse.txt` is a hash lock of the `rse` extra closure only: cffi 2.1.1, cryptography 50.0.2, pycparser 3.1, pyhpke 0.6.5. It is the input to `uv pip install --require-hashes`. It is not a lock of the base install and it does not replace `uv.lock`.
- Base `dependencies` still omit cryptography and pyhpke. An isolated interpreter cannot import `orca.rse.imp4.ocr1`.
- CI job `rse-dependency-audit` installs that lock and runs `pip-audit` without `|| true`. Python under that job is 3.11. This record does not claim 3.12 or 3.13.
- Local audit of that closure, before push: `No known vulnerabilities found` (pip-audit 2.10.1). Previously documented base findings chromadb `PYSEC-2026-311` and diskcache `PYSEC-2026-2447` are outside this closure. The base job remains informational and still does not scan pyhpke.

No cryptographic protocol code was changed to satisfy the pin.

## Approval 5 — workflow policy

APPROVED: keep `cursor/**` on the push trigger. The pull_request trigger is unchanged. No `permissions:` key was added. The six existing jobs are unchanged. The new job is additional. A pull_request run remains a merge ref and is not exact-SHA evidence.

## Still not authorized

`IMP_5_NOT_AUTHORIZED`. No provisioning, hardware purchase, real secret creation, corpus generation, qualification, model selection, GPU, or training. No merge. Enterprise residuals in `RSE_BLOCK1_ENTERPRISE_RESIDUAL_RISK_REGISTER.md` remain open for a real secure environment.

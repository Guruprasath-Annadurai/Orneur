# ORNEUR B-Series Source Verification

**Branch:** `claude/ui-implementation-programme-2026-10-23` (stacked on PR #81 verified head `3cb96ac56f8a4bb7a0a78f98e0531bff021d371f`, created fresh for this programme — PR #81's own branch was not touched)
**Date:** 2026-10-23

## What was verified, and how

The designer's V3 closeout package (`ORNEUR_PRODUCTION_DESIGN_HANDOFF_CLOSEOUT_V3.zip`) reports the B-series original archive and the two core brand binaries as **not independently reproduced**, because the designer's own authoring environment does not have access to this engineering Mac ("Engineering host OFFLINE; not reproduced in this session" — see `01_AUTHENTIC_RECOVERED/30_SCREEN_SOURCE_AND_IMPLEMENTATION_STATUS.csv`). This engineering session **does** have that access, so the three claims the V3 package left as self-reported were independently re-verified on this host using the V3 package's own read-only verification tool, `10_INTEGRITY_VERIFICATION/verify_on_authorized_host.py` (inspected before running — it only hashes files and reads zip members, no writes):

```
python3 verify_on_authorized_host.py \
  --b-archive "/Users/ag/Downloads/ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF(2).zip" \
  --master orca/serve/web/brand/orneur-official-master.c861c074.png \
  --horizontal orca/serve/web/b01_approved_assets/orneur_logo_horizontal.png
```

**Result — PASS, all three:**
```
B ORIGINAL ARCHIVE verified: 274 / 274 SHA256 manifest members; ZIP SHA256 0e37e5fa4e51f30b8e867f8d380ff4eade0ac1e4bda12ac7b861c48b2e6a2956
Canonical master actual SHA-256: c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b expected c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b
Approved horizontal actual SHA-256: b52c2f34764e294828891c4337ef47a6bca7e34b04bb969ed4892fc76d55768c expected b52c2f34764e294828891c4337ef47a6bca7e34b04bb969ed4892fc76d55768c
PASS: B original and 2 brand binaries actually verified on authorized host; no files modified
```

This **upgrades** the V3 register's own `NOT_OBSERVED_AS_FULL_ARCHIVE` status for B01–B16 and the brand binaries to **independently confirmed present and byte-correct on this host**, right now, in this session. This is the single most important correction this document makes to the V3 package's own self-reported state.

## Archive location and provenance

- **B01–B16 original archive**: `/Users/ag/Downloads/ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF(2).zip` — 274/274 internal `SHA256_MANIFEST.txt` entries verified, zip CRC clean, overall archive SHA-256 `0e37e5fa4e51f30b8e867f8d380ff4eade0ac1e4bda12ac7b861c48b2e6a2956`.
- Also present, already extracted, at `~/Projects/orneur-design-assets/b01-b16-handoff/ORNEUR_UIUX_FINAL_CTO_REVIEW_HANDOFF/` (275 files on disk — the 1-file difference from 274 is the manifest file itself, not a discrepancy).
- Internal structure: `APPROVED_SOURCE_ARCHIVES/ORNEUR_B01_FINAL_DESIGN_LOCK.zip` ... `ORNEUR_B16_FINAL_LOCK_AND_HANDOFF.zip` (one nested zip per screen) plus `ORNEUR_UIUX_FINAL_REVIEW_GALLERY/` (per-screen PNG screenshots, dark/light, desktop/mobile, default/contextual variants) and top-level markdown contracts (`ORNEUR_UIUX_DESIGN_HANDOFF.md`, `ORNEUR_UIUX_DESIGN_SYSTEM.md`, `ORNEUR_UIUX_DEFECT_REGISTER.md`, `ORNEUR_UIUX_END_TO_END_JOURNEY_AUDIT.md`, `ORNEUR_UIUX_CTO_REVIEW_SUMMARY.md`).
- **Canonical master logo**: `orca/serve/web/brand/orneur-official-master.c861c074.png` — already committed in-repo (introduced by commit `6100887`, an ancestor of PR #81's branch), SHA-256 `c861c074a34dfd2a45a073b389be3f28a9ede26266b86fedac33f17d34518a1b`, matches the V3 package's `MASTER` constant exactly.
- **Approved B01 horizontal derivative**: `orca/serve/web/b01_approved_assets/orneur_logo_horizontal.png` — SHA-256 `b52c2f34764e294828891c4337ef47a6bca7e34b04bb969ed4892fc76d55768c`, matches the V3 package's `HORIZ` constant exactly. This is a distinct, separately-approved derivative, not the master itself — confirmed by provenance, not by appearance.

## What this does NOT establish

- Per-screen pixel-level fidelity comparisons between the B04–B16 nested archives and any live implementation were **not performed in this pass** (only B01–B03, already implemented in PR #81, were compared live — see `ORNEUR_B01_B03_IMPLEMENTATION_FIDELITY.md`).
- Integrity (hashes match, zip is uncorrupted) is not the same claim as design-source *completeness* — the V3 package's own `verify_bundle.py --require-complete-sources` correctly and deliberately fails for C01–C11, which this session reproduced: `FAIL: APPROVED ORIGINAL NOT AVAILABLE` for each of C01 through C11.

## C-series status (unchanged from this session's earlier design-handoff intake, reconfirmed against V3)

| Range | Status |
|---|---|
| C01 | `APPROVED_REFERENCE_MISSING` — no authenticated original recovered anywhere. |
| C02–C11 | `INDEXED_LIB_METADATA_RAW_ORIGINAL_NOT_LOCAL` — names/metadata indexed in an internal library, raw source bytes not exportable to this engineering environment. C02 specifically also falls under PR #79's separate, ongoing mission-backend security qualification — its UI must not be used to pressure or bypass that work. |
| C12–C14 | Original candidate review ZIP present and hash-verified (`424b72fb...e96bf`, matches this session's earlier independent verification exactly). Founder subsequently approved the A-default/B-contextual directions in a separate addendum. The approved **logo placeholder in that candidate ZIP is not a production asset** — the real master logo (verified above) exists but has not been composited into any C12–C14 implementation; doing so is a founder-approval item (see `ORNEUR_UI_IMPLEMENTATION_AUDIT_HANDOFF.md`), not something this pass performs unilaterally.

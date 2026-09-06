# Phase 12.1 — Baseline Lineage Audit

## Repository state

- **Current branch**: `session-update-2026-08-25`
- **Current HEAD** (at start of this audit): `5f06742`
- **`git status`**: clean (no uncommitted changes) at audit start

## Commit graph, Phase 11.2 closure through Phase 12 documentation

```
* 5f06742 (HEAD -> session-update-2026-08-25) Phase 12 (2/3): documentation set
* 65061b8 Phase 12 (1/3): governed failure-to-curriculum pipeline core
* cc732b0 (origin/session-update-2026-08-25) Add orneur as the real CLI command, keep orca as a legacy alias
* 5da3502 Update README branding: product name is Orneur, not Orca
* 5b58b91 Phase 11.2 (5/6): fix real Gateway-layer cancellation/timeout defect + close live-suite qualification
```

## The gap: 5b58b91 → cc732b0

Two commits exist between Phase 11.2's closure commit and the SHA the
Phase 12 closure report named as its starting point:

| Commit | Files changed | Classification |
|---|---|---|
| `5da3502` "Update README branding: product name is Orneur, not Orca" | `README.md` only | **DOCUMENTATION_ONLY** |
| `cc732b0` "Add orneur as the real CLI command, keep orca as a legacy alias" | `README.md`, `orca/cli.py`, `pyproject.toml` | **PRODUCTION_CODE** (branding-only; see below) |

## Provenance

Both commits were made in THIS session, between the Phase 11.2 closure
report being delivered and the Phase 12 spec being issued, in direct
response to two explicit user requests unrelated to either phase's spec:
"update the public display readme and don't call orca it's Orneur," then
"change the cli commands also." They are **neither Phase 11.2 cleanup nor
Phase 12 preparation** — they are a separate, user-directed rebrand task
that happened to land in the same session, in between the two phases.
This is disclosed here rather than retroactively folded into either
phase's own narrative.

## Diff audit (`git diff --stat 5b58b91..cc732b0` / full diff)

```
 README.md      | 66 +++++++++++++++++++++++++++++-----------------------------
 orca/cli.py    | 32 +++++++++++++++-------------
 pyproject.toml |  1 +
 3 files changed, 52 insertions(+), 47 deletions(-)
```

Full diff reviewed line by line. Contents:

- **`README.md`**: prose/heading text changes only ("Orca" → "Orneur" in
  the title, section headings, and licensing intro) plus updating every
  CLI command example shown in code blocks from `orca ...` to
  `orneur ...` to match the new real alias. No file path, package name
  (`orca-ai`), or domain (`orca.systems`) reference was changed.
- **`orca/cli.py`**: (1) module docstring's example commands updated to
  `orneur ...` plus a new sentence documenting `orca` as a legacy alias;
  (2) `typer.Typer(name="orca", ...)` → `name="orneur"`; (3)
  `typer.echo(f"orca {__version__}")` → `f"orneur {__version__}"`. No
  command logic, no imports, no behavior beyond these three display
  strings changed.
- **`pyproject.toml`**: one line added — `orneur = "orca.cli:app"` in
  `[project.scripts]`, alongside the pre-existing `orca = "orca.cli:app"`.
  Both console-script entry points resolve to the exact same Typer `app`
  object; this is a pure aliasing change.

**Zero changes** to Gateway, Truth Fabric, Memory, Model Society,
AgentRuntime, connectors, Godmode, Simulation, model lifecycle, dataset
registry, training registry, checkpoint registry, evaluation registry, or
security policy — confirmed directly by the diff above touching exactly
three files, none of which live under any of those subsystems' paths.

## Regression coverage for this change

Before this audit, `orca/cli.py` had **zero test coverage of any kind** —
a pre-existing gap, not introduced by the rename. This was closed during
this qualification pass: `tests/test_cli_branding.py` (3 new tests)
directly asserts `app.info.name == "orneur"` and that `--version` reports
`orneur <version>`, using Typer's `CliRunner`. All three pass.

## Classification verdict

Neither `5da3502` nor `cc732b0` is **UNEXPECTED**. Both are fully
explained, both were made with complete authorship knowledge available in
this same session, and both are branding-only changes with zero
behavioral impact on any production subsystem. No production
security/runtime/model/training behavior changed in this interval.

## Correct Phase-12 baseline record

**Answer: (A)** — Phase 12 actually began at `cc732b0`, with an
explained transition from Phase 11.2's real closure HEAD (`5b58b91`)
consisting of two intervening, unrelated, low-risk branding commits. The
Phase 12 closure report's stated starting SHA (`cc732b0`) was **not
incorrect** — it correctly reflected repository HEAD at the moment Phase
12 work began — but the report did not explain the gap from `5b58b91`,
which this document now does. `docs/orneur/phase-12/PHASE_12_CLOSURE.md`
has been updated to reference this document explicitly.

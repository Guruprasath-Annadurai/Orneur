# ORNEUR Identity Standard

Normative. This document is the single source of truth for what ORNEUR's
public identity is, and what remains legacy/internal. It supersedes any
conflicting prose in older docs, code comments, or templates that have not
yet been corrected (see `ORNEUR_IDENTITY_AUDIT.md` for the current gap
list).

## Canonical identity

| Element | Canonical value |
|---|---|
| Product name | **ORNEUR** |
| Brand line | **ORNEUR — Intelligence, Without End.** |
| Primary CLI | `orneur` |
| Model family — Genesis | **Orneur Genesis** — Builder / Executor, Executable Intelligence |
| Model family — Novus | **Orneur Novus** — Reasoner / Investigator, Epistemic-Causal Intelligence |
| Model family — Aeternum | **Orneur Aeternum** — Critic / Arbiter / Discoverer, Adversarial Discovery Intelligence |
| Public product references | ORNEUR (never "Orca" as a product identity) |

These role descriptions are not marketing copy — they are copied verbatim
from `orca/registry/model_spec.py`'s `MODEL_SPECS`, the single source of
truth for model identity in this codebase. Any doc/template describing a
family differently than that module is stale, not this standard.

## Legacy implementation namespace

`orca` (the Python package, `orca.*` import paths, `ORCA_HOME`, the
`ORCA_*` environment-variable family, the `ORCA-` license-key prefix) is a
**temporary internal/backward-compatibility namespace only.** It is not
being renamed in this closure — see `ORNEUR_LEGACY_NAMESPACE_MIGRATION.md`
for the staged plan to eventually retire it.

## Explicit rulings

- **Orca is legacy identity.** It is not the active corporate/product
  brand. Internal code may keep using `orca.*` module paths; public-facing
  surfaces (README, CLI banners, web UI, package metadata, install docs)
  must not present the product itself as "Orca."
- **Atheris is not the active ORNEUR product identity.** No verified
  evidence found in this repository, its git remote, or reachable
  infrastructure indicates Atheris is a current legal/product identity for
  ORNEUR (see `ORNEUR_IDENTITY_AUDIT.md` §Atheris for the investigation).
  Historical docs may retain the name where accuracy about the past
  requires it; active public surfaces must not.
- **`orca.*` module paths may temporarily remain internal.** This closure
  does not rename the Python package. A caller importing
  `orca.registry.model_spec` is using a legitimate, documented internal
  path — this is expected and correct today, not a bug.
- **Public surfaces must not call the product "Orca" merely because
  internals still use `orca.*`.** The distinction is: `orca.cli:app` is an
  internal implementation detail; what that CLI calls itself when a human
  runs `--help` is a public-identity decision, and that decision is
  ORNEUR.
- **Legacy identifiers may remain only when compatibility, historical
  accuracy, migration, or stable-token handling requires them** — and each
  one that remains must have a documented reason (see
  `ORNEUR_IDENTITY_AUDIT.md`'s `CHANGE NOW?` / `COMPATIBILITY RISK`
  columns). "It would take work to change" is not by itself a valid
  reason; "changing it would break a real, still-relevant compatibility
  guarantee" is.

## What this standard does NOT do

- It does not rename the `orca` Python package.
- It does not migrate `~/.orca/` user data.
- It does not invalidate any previously issued `ORCA-` license key.
- It does not invent a new company name, domain, or legal entity.
- It does not claim SOC 2 certification, benchmarks, customers, or
  partnerships beyond what other project documents already substantiate.

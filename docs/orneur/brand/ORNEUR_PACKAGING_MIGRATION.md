# ORNEUR Packaging Migration

Covers the wheel/sdist packaging fix and the PyPI distribution-name
decision made during the ORNEUR corporate identity closure.

## 1. Packaging invariant — the wheel was missing `orneur/`

### Pre-fix reproduction

`[tool.hatch.build.targets.wheel] packages = ["orca"]` was the only
package listed. Built the wheel from unmodified source
(`.venv/bin/python -m build --wheel`) and inspected it with `zipfile`:

```
TOP-LEVEL ENTRIES: ['orca', 'orca_ai-1.0.0.data', 'orca_ai-1.0.0.dist-info']
orneur present: False
orca present: True
```

**Confirmed real pre-fix defect**: `orneur.intelligence.ocl` — the entire
Phase 17 OCL implementation — was never shipped in the built distribution.
Anyone installing the published wheel would get `orca` but nothing under
`orneur`, silently breaking `import orneur.intelligence.ocl`.

### Fix

```toml
[tool.hatch.build.targets.wheel]
packages = ["orca", "orneur"]
```

### Post-fix verification

Rebuilt the wheel and re-inspected:

```
TOP-LEVEL ENTRIES: ['orca', 'orneur', 'orneur-1.0.0.data', 'orneur-1.0.0.dist-info']
orneur present: True
orca present: True
orneur.intelligence.ocl present: True
OCL files count: 21
```

Then installed the wheel into a fresh, isolated virtualenv (not the
repository's own `.venv`, and not relying on `pythonpath = ["."]` in
`pyproject.toml`, which can hide a broken wheel):

```
$ /tmp/orneur_isolated_venv/bin/python -c "import orneur.intelligence.ocl; print('OK')"
OK: orneur.intelligence.ocl imported from isolated install
$ /tmp/orneur_isolated_venv/bin/orneur --help
 Usage: orneur [OPTIONS] COMMAND [ARGS]...
 Orneur — Intelligence, Without End.
$ /tmp/orneur_isolated_venv/bin/orca --help
 Usage: orca [OPTIONS] COMMAND [ARGS]...
 Orneur — Intelligence, Without End.
```

Both console-script entry points (`orneur`, the primary CLI; `orca`, the
backward-compatibility alias) install and run correctly, and both report
the corrected ORNEUR identity text (since both point at the same
`orca.cli:app` object, whose banner text was fixed as part of this
closure).

`sdist` was also built and inspected: contains both `orca/` and `orneur/`
top-level trees, a `.env.example` template (placeholder values only, no
real secrets), and no `.env`/`.pem`/`id_rsa`/credential files. Archive
listing was searched for `.env`, `.env.local`, `credentials`, `keys`,
`tokens` — the only matches are documentation/test files that mention
those words (`docs/orneur/phase-9/CREDENTIAL_SECURITY.md`,
`tests/test_agent_secret_and_trace_security.py`), not actual secret
material.

## 2. Distribution name — `orca-ai` investigation and decision

### Investigation performed

1. **Has `orca-ai` ever been published to PyPI?** Yes — but not by this
   project. `GET https://pypi.org/pypi/orca-ai/json` returns a real
   package, versions `0.1.0`/`0.1.1`, author **"Orca Systems"**,
   repository `github.com/orca-systems/orca`. This project's own version
   history (`1.0.0` in `pyproject.toml` at the time of this closure) has
   never matched or been published under that name — there is no `1.0.0`
   release in that package's history.
2. **Are existing install/update scripts tied to it?** Yes —
   `orca/upgrade.py`'s self-update mechanism and `install.sh` both
   referenced `orca-ai`. Neither was safe: the self-update code checks a
   stranger's version number (see below); `install.sh` is not hosted
   anywhere reachable (`orca.systems/install.sh` returns 404).
3. **Does self-update logic depend on it?** Yes, and this was a genuine,
   live risk: `orca/upgrade.py`'s `is_update_available()` compared the
   local version against `orca-ai`'s PyPI version. It was silently
   harmless only because `1.0.0 > 0.1.1`. Had "Orca Systems" ever
   published a higher version number, `self_update()` would have silently
   run `pip install --upgrade orca-ai`, installing a stranger's unrelated
   software over the user's real installation. **This has been fixed** —
   see below.
4. **Do docs/install.sh depend on it?** Yes (now fixed to say `orneur`,
   which is honest about not being published yet rather than silently
   correct).
5. **Is a suitable ORNEUR package name available?** Yes —
   `GET https://pypi.org/pypi/orneur/json` returns 404 (unregistered).
6. **Would changing `project.name` break current installs?** No. This
   project's package was never actually published under `orca-ai` (no
   matching version in that package's release history), so there is no
   real existing PyPI-installed user base to break.
7. **Would changing it cause two independent package identities?** No —
   the opposite is true today: keeping `orca-ai` would mean this project's
   local metadata claims an identity that PyPI already assigns to a
   different, unrelated project. That is the two-identities problem, not
   a one-identity problem changing would create.

### Decision: **RENAME_NOW**

`pyproject.toml`'s `name` was changed from `"orca-ai"` to `"orneur"`. This
is the safer, not merely the more cosmetically consistent, choice: the old
name was never actually ours on PyPI, and every day it remained the
self-update code's target was a live (if currently dormant) supply-chain
confusion risk. No publication was performed as part of this decision —
see §4.

`orca/upgrade.py` was updated in lockstep:

```python
_PYPI_URL = "https://pypi.org/pypi/orneur/json"
_PACKAGE   = "orneur"
```

Until this project actually publishes under `orneur`, `get_latest_version()`
returns `None` (404), and `is_update_available()` honestly reports
"could not reach PyPI" rather than silently comparing against the wrong
package.

## 3. Package metadata corrected

| Field | Before | After |
|---|---|---|
| `name` | `orca-ai` | `orneur` |
| `description` | "Orca — the enterprise AI platform, built by Atheris..." | "ORNEUR — Intelligence, Without End. A self-hosted, governed AI platform: ..." |
| `authors` | `[{name="Atheris", email="hello@atheris.ai"}]` | `[{name="ORNEUR"}]` — no invented legal entity or email; see `ORNEUR_IDENTITY_STANDARD.md` |
| `Homepage` | `https://atheris.ai` | `https://github.com/Guruprasath-Annadurai/Orneur` |
| `Docs` | `https://atheris.ai/docs` | removed (no verified docs site) |
| `Repository` | `https://github.com/Guruprasath-Annadurai/Orca` | `https://github.com/Guruprasath-Annadurai/Orneur` |
| `Changelog` | `https://atheris.ai/changelog` | `https://github.com/Guruprasath-Annadurai/Orneur/releases` |
| `Bug Tracker` | `.../Orca/issues` | `https://github.com/Guruprasath-Annadurai/Orneur/issues` |
| `[project.scripts]` | `orneur`/`orca` both → `orca.cli:app` | unchanged — this shape (canonical + compat alias, both pointing at the still-internal `orca.cli` module) is already correct |
| `[tool.hatch.build.targets.wheel] packages` | `["orca"]` | `["orca", "orneur"]` |

## 4. No publication performed

No `pypi.org` upload, no `twine upload`, no GitHub Release was created as
part of this closure. The `orneur` name being available on PyPI was
verified read-only; actually publishing under it is a separate, explicit,
future decision for the owner.

## 5. Known remaining gap

`orca/__version__.py` says `__version__ = "0.1.1"` while `pyproject.toml`
said `version = "1.0.0"` at the start of this closure — a pre-existing
version-string mismatch, discovered incidentally while investigating
`orca/upgrade.py`. Out of scope for this branding closure (it is not an
identity issue); flagged here so it is not lost.

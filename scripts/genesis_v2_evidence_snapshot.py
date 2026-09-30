#!/usr/bin/env python3
"""Read-only evidence snapshot for Genesis Capability Eval V2. Aggregates ONLY existing, already-read-only checks
(owner_preflight, privacy_scan, the three role-separated preflights, and optionally vault isolation) into one JSON
bundle. Never reads, prints, or transmits a real secret value; never writes to the vault or any registry; never
activates, authorizes, or generates anything. Safe to run repeatedly and to publish its output (it carries the same
public-safe guarantees as the individual checks it calls).

  python scripts/genesis_v2_evidence_snapshot.py                          # no vault isolation check
  python scripts/genesis_v2_evidence_snapshot.py --vault /path/to/vault   # also check vault isolation

Exit code is always 0 -- this script REPORTS state, it does not gate on it (each individual check's own script
still has its own pass/fail exit code for that purpose). A missing or unconfigured component is reported as
"NOT_CONFIGURED", never silently omitted or upgraded to a false PASS.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orca.eval.genesis_v2 import owner_preflight as OP  # noqa: E402
from orca.eval.genesis_v2 import privacy_scan as PS  # noqa: E402
from orca.eval.genesis_v2 import store as ST  # noqa: E402
from orca.eval.genesis_v2 import vault_verify as VV  # noqa: E402


def _safe(label, fn):
    try:
        return fn()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {str(e)[:200]}", "note": f"{label} could not be evaluated -- treated as NOT_CONFIGURED, never as PASS"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=None, help="Optional: an ABSOLUTE path to check vault isolation for. Omit if no vault exists yet.")
    args = ap.parse_args()

    snapshot = {
        "document": "GENESIS_V2_EVIDENCE_SNAPSHOT",
        "schema_version": "genesis-v2-evidence-snapshot/1",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Read-only. No secret value, key, or vault path is ever included. A missing component is reported "
                "NOT_CONFIGURED, never manufactured as a PASS.",
        "owner_preflight": _safe("owner_preflight", lambda: OP.run(ROOT)),
        "privacy_scan": _safe("privacy_scan", lambda: PS.scan_repository(ROOT)),
        "role_preflight_owner": _safe("role_preflight_owner", ST.owner_setup_preflight),
        "role_preflight_generator": _safe("role_preflight_generator", ST.generator_setup_preflight),
        "role_preflight_verifier": _safe("role_preflight_verifier", ST.verifier_setup_preflight),
    }
    if args.vault:
        snapshot["vault_isolation"] = _safe("vault_isolation", lambda: VV.verify_vault_isolation(Path(args.vault), ROOT))
    else:
        snapshot["vault_isolation"] = {"status": "NOT_CONFIGURED", "note": "no --vault argument supplied; no vault has been checked"}

    print(json.dumps(snapshot, indent=1))
    sys.exit(0)

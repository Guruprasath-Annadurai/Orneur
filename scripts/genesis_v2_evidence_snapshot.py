#!/usr/bin/env python3
"""Read-only evidence snapshot for Genesis Capability Eval V2. Aggregates ONLY existing, already-read-only checks
(owner_preflight, privacy_scan, the role-separated preflight(s), and optionally vault isolation) into one JSON
bundle. Never writes to the vault or any registry; never activates, authorizes, or generates anything. Safe to run
repeatedly.

SECURITY CONTRACT (read this before interpreting a snapshot -- item 3 of the deployment-decision-accuracy-closure
phase corrects the previous version of this script, which did not state this plainly):

  - Every check in this snapshot inspects environment-variable PRESENCE/SHAPE only, NEVER a secret's actual value
    -- with exactly ONE exception: `role_preflight_owner`'s X25519 pair-matching step DOES read and
    cryptographically process the real public/private key BYTES (to confirm they form a genuine pair). Even that
    step never EMITS either value anywhere in this report -- only a boolean/diagnostic finding. See the
    `security_contract` field in the JSON output for the exact list.
  - `role_preflight_owner` / `_generator` / `_verifier` are ALWAYS evaluated against THIS PROCESS's OWN
    environment. Running more than one role's preflight in ONE invocation (the default, `--role all`) NEVER proves
    that two real, separate deployments actually keep their credentials apart -- it only reports what THIS one
    environment happens to expose. Genuine cross-deployment separation evidence requires running this script
    SEPARATELY, once per real deployment, and comparing the outputs by hand -- see
    GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md. The `cross_environment_separation_evidence` field is
    always `"NOT_ESTABLISHED_BY_THIS_TOOL"` for exactly this reason -- it is never computed, never upgraded to a
    claim of separation, regardless of what the individual role checks report.
  - Any exception from an underlying check is caught, and any substring matching a secret-shaped 64-hex-character
    pattern is scrubbed from its message before being included in this report -- defense in depth on top of the
    fact that no underlying check's exception path is expected to embed a real secret value in the first place.

  python scripts/genesis_v2_evidence_snapshot.py                           # --role all (default): every role preflight against THIS environment
  python scripts/genesis_v2_evidence_snapshot.py --role generator          # ONLY the generator's own preflight -- run FROM the generator's real deployment
  python scripts/genesis_v2_evidence_snapshot.py --role verifier           # ONLY the verifier's own preflight -- run FROM the verifier's real deployment
  python scripts/genesis_v2_evidence_snapshot.py --vault /path/to/vault    # also checks vault isolation

Exit code is always 0 -- this script REPORTS state, it does not gate on it (each individual check's own script
still has its own pass/fail exit code for that purpose). A missing or unconfigured component is reported as
"NOT_CONFIGURED", never silently omitted or upgraded to a false PASS.
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orca.eval.genesis_v2 import owner_preflight as OP  # noqa: E402
from orca.eval.genesis_v2 import privacy_scan as PS  # noqa: E402
from orca.eval.genesis_v2 import store as ST  # noqa: E402
from orca.eval.genesis_v2 import vault_verify as VV  # noqa: E402

_SECRET_SHAPED = re.compile(r"[0-9a-fA-F]{64}")

ROLE_PREFLIGHTS = {
    "owner": ("role_preflight_owner", ST.owner_setup_preflight),
    "generator": ("role_preflight_generator", ST.generator_setup_preflight),
    "verifier": ("role_preflight_verifier", ST.verifier_setup_preflight),
}

SECURITY_CONTRACT = {
    "checks_that_inspect_actual_secret_bytes": ["role_preflight_owner (X25519 pair-matching step only)"],
    "checks_that_never_touch_a_secret_value_at_all": [
        "owner_preflight", "privacy_scan", "vault_isolation",
        "role_preflight_generator (presence/shape of env vars only)",
        "role_preflight_verifier (presence/shape of env vars only)",
    ],
    "values_ever_emitted_in_this_report": "none -- presence booleans, shape validity booleans, and diagnostic "
                                           "strings only; never a secret value itself, in either the normal or the "
                                           "exception path (exception messages are scrubbed -- see _scrub())",
}


def _scrub(msg: str) -> str:
    """Defense in depth: redact any secret-shaped (64-hex-char) substring from a message before it is ever
    printed. No underlying check in this program is expected to embed a real secret value in an exception message
    -- this exists so that expectation is enforced, not merely assumed."""
    return _SECRET_SHAPED.sub("<redacted-secret-shaped-value>", msg)


def _safe(label, fn):
    try:
        return fn()
    except Exception as e:
        return {"error": _scrub(f"{type(e).__name__}: {str(e)[:200]}"),
                "note": f"{label} could not be evaluated -- treated as NOT_CONFIGURED, never as PASS"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--vault", default=None, help="Optional: an ABSOLUTE path to check vault isolation for. Omit if no vault exists yet.")
    ap.add_argument("--role", choices=["owner", "generator", "verifier", "all"], default="all",
                     help="Which role preflight(s) to run against THIS process's OWN environment. Use a SPECIFIC "
                          "role when invoking this script FROM that role's real deployment. 'all' (default) is a "
                          "convenience for local inspection and is NEVER evidence of cross-deployment separation "
                          "-- see the security contract in this script's own docstring.")
    args = ap.parse_args()

    snapshot = {
        "document": "GENESIS_V2_EVIDENCE_SNAPSHOT",
        "schema_version": "genesis-v2-evidence-snapshot/2",
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": "Read-only. No secret value, key, or vault path is ever included. A missing component is reported "
                "NOT_CONFIGURED, never manufactured as a PASS.",
        "security_contract": SECURITY_CONTRACT,
        "cross_environment_separation_evidence": "NOT_ESTABLISHED_BY_THIS_TOOL",
        "role_scope_of_this_invocation": args.role,
        "owner_preflight": _safe("owner_preflight", lambda: OP.run(ROOT)),
        "privacy_scan": _safe("privacy_scan", lambda: PS.scan_repository(ROOT)),
    }

    if args.role == "all":
        snapshot["role_scope_note"] = ("All three role preflights were run against THIS SAME process's environment. "
                                        "This is a convenience for local inspection, NOT proof that any two of them "
                                        "represent genuinely separate real deployments -- see "
                                        "cross_environment_separation_evidence above.")
        for role, (key, fn) in ROLE_PREFLIGHTS.items():
            snapshot[key] = _safe(key, fn)
    else:
        key, fn = ROLE_PREFLIGHTS[args.role]
        snapshot[key] = _safe(key, fn)
        snapshot["role_scope_note"] = (f"Only {args.role}'s own preflight was run, as requested via --role. This is "
                                        f"meaningful evidence about {args.role}'s environment ONLY if this "
                                        f"invocation genuinely ran FROM {args.role}'s real deployment.")

    if args.vault:
        snapshot["vault_isolation"] = _safe("vault_isolation", lambda: VV.verify_vault_isolation(Path(args.vault), ROOT))
    else:
        snapshot["vault_isolation"] = {"status": "NOT_CONFIGURED", "note": "no --vault argument supplied; no vault has been checked"}

    print(json.dumps(snapshot, indent=1))
    sys.exit(0)

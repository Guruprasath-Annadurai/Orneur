#!/usr/bin/env python3
"""Read-only evidence snapshot for Genesis Capability Eval V2. Aggregates ONLY existing, already-read-only checks
(owner_preflight, privacy_scan, the role-separated preflight(s), and optionally vault isolation) into one JSON
bundle. Never writes to the vault or any registry; never activates, authorizes, or generates anything. Safe to run
repeatedly.

SECURITY CONTRACT (read this before interpreting a snapshot -- item 3 of the authenticated-transfer-and-evidence-
integrity-closure phase corrects the previous version of this script, which relied on a 64-hex-character regex to
scrub forwarded exception text -- an approach the audit correctly flagged as unsafe to rely on ALONE, since it would
miss a base64-encoded secret, a variable-length secret, or a secret embedded in a path. This version does not
forward exception message text AT ALL, in any form -- see `_safe()` below):

  - Every check in this snapshot inspects environment-variable PRESENCE/SHAPE only, NEVER a secret's actual value
    -- with exactly ONE exception: `role_preflight_owner`'s X25519 pair-matching step DOES read and
    cryptographically process the real public/private key BYTES (to confirm they form a genuine pair). Even that
    step never EMITS either value anywhere in this report -- only a boolean/diagnostic finding. See the
    `security_contract` field in the JSON output for the exact list.
  - PRECISELY, per role preflight (see `orca/eval/genesis_v2/store.py` for the implementations):
      * `role_preflight_generator` (`store.generator_setup_preflight`): DECODES AND VALIDATES the corpus secret's
        entropy (via `orca.eval.genesis_v2.secret.load_secret_from_env`, since generation needs a real seed).
        Checks the vault PUBLIC key's SHAPE only (64 hex chars). Checks the vault PRIVATE key's NON-PRESENCE (its
        presence is flagged as a `violations` entry, a credential-boundary breach, never merely "missing config").
        Never reads or pair-matches actual key bytes.
      * `role_preflight_verifier` (`store.verifier_setup_preflight`): NEVER decodes or requires the corpus secret
        (verifying/qualifying never generates anything). Checks the vault PRIVATE key's SHAPE only (64 hex chars) --
        never its actual bytes, never a pair-match.
      * `role_preflight_owner` (`store.owner_setup_preflight`): DECODES AND VALIDATES the corpus secret's entropy,
        same as the generator. Checks BOTH vault key halves' SHAPE, AND ADDITIONALLY cryptographically PAIR-MATCHES
        them -- the only preflight that ever parses real X25519 key bytes via the `cryptography` library, to
        confirm they form a genuine matching keypair from one `generate_vault_keypair()` call. This is legitimate
        only in an owner-controlled context that already has visibility into both halves at once; never run this
        preflight from a real generator or verifier deployment.
      * `owner_preflight` (`orca.eval.genesis_v2.owner_preflight.run`) and `privacy_scan`
        (`orca.eval.genesis_v2.privacy_scan.scan_repository`): neither decodes, validates, nor requires any secret
        value at all -- both inspect repository/registry STATE only.
  - `role_preflight_owner` / `_generator` / `_verifier` are ALWAYS evaluated against THIS PROCESS's OWN
    environment. Running more than one role's preflight in ONE invocation (the default, `--role all`) NEVER proves
    that two real, separate deployments actually keep their credentials apart -- it only reports what THIS one
    environment happens to expose. Genuine cross-deployment separation evidence requires running this script
    SEPARATELY, once per real deployment, and comparing the outputs by hand -- see
    GENESIS_V2_PROCESS_ISOLATION_VERIFICATION_PROCEDURE.md. The `cross_environment_separation_evidence` field is
    always `"NOT_ESTABLISHED_BY_THIS_TOOL"` for exactly this reason -- it is never computed, never upgraded to a
    claim of separation, regardless of what the individual role checks report.
  - Any exception from an underlying check is caught by `_safe()`, which NEVER forwards the exception's own message
    text -- not truncated, not regex-scrubbed, not in any form. It reports only a FIXED, ALLOWLISTED error code, a
    static per-check description written into this script ahead of time, and the exception's class name (a safe,
    non-secret Python identifier, never attacker- or secret-controlled content). A 64-hex-character regex (or any
    other shape-based scrubber) is never relied upon here to guarantee non-disclosure -- there is simply nothing
    of the original message left to leak through one.

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
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from orca.eval.genesis_v2 import owner_preflight as OP  # noqa: E402
from orca.eval.genesis_v2 import privacy_scan as PS  # noqa: E402
from orca.eval.genesis_v2 import store as ST  # noqa: E402
from orca.eval.genesis_v2 import vault_verify as VV  # noqa: E402

ROLE_PREFLIGHTS = {
    "owner": ("role_preflight_owner", ST.owner_setup_preflight),
    "generator": ("role_preflight_generator", ST.generator_setup_preflight),
    "verifier": ("role_preflight_verifier", ST.verifier_setup_preflight),
}

SECURITY_CONTRACT = {
    "checks_that_decode_and_validate_the_corpus_secret": ["role_preflight_generator", "role_preflight_owner"],
    "checks_that_never_touch_the_corpus_secret_at_all": ["role_preflight_verifier", "owner_preflight", "privacy_scan", "vault_isolation"],
    "checks_that_inspect_actual_vault_key_bytes": ["role_preflight_owner (X25519 pair-matching step only)"],
    "checks_that_only_check_vault_key_shape": ["role_preflight_generator (public key shape; private key non-presence)",
                                                "role_preflight_verifier (private key shape only)"],
    "checks_that_never_touch_a_vault_key_value_at_all": ["owner_preflight", "privacy_scan", "vault_isolation"],
    "values_ever_emitted_in_this_report": "none -- presence booleans, shape validity booleans, and fixed diagnostic "
                                           "strings only; never a secret value itself, in either the normal or the "
                                           "exception path. The exception path (see _safe()) forwards NO part of an "
                                           "underlying exception's own message text, in any form -- only a fixed, "
                                           "allowlisted error code, a static per-check description, and the "
                                           "exception's class name.",
}

# Fixed, allowlisted, static descriptions -- one per check this script runs. Deliberately NOT derived from any
# exception's own message text, so there is nothing shape-dependent (hex, base64, path-like, or otherwise) for a
# regex-based scrubber to ever need to catch in the first place.
_CHECK_DESCRIPTIONS = {
    "owner_preflight": "owner_preflight.run() raised instead of returning its normal report dict.",
    "privacy_scan": "privacy_scan.scan_repository() raised instead of returning its normal report dict.",
    "role_preflight_owner": "store.owner_setup_preflight() raised instead of returning its normal report dict.",
    "role_preflight_generator": "store.generator_setup_preflight() raised instead of returning its normal report dict.",
    "role_preflight_verifier": "store.verifier_setup_preflight() raised instead of returning its normal report dict.",
    "vault_isolation": "vault_verify.verify_vault_isolation() raised instead of returning its normal report dict.",
}
_UNKNOWN_CHECK_DESCRIPTION = "an unrecognized check raised instead of returning its normal report dict."


def _safe(label, fn):
    """Runs one underlying check, never letting an exception escape and never forwarding any part of an exception's
    own message text into the report -- regardless of what that text contains (a raw secret, a hex/base64-shaped
    value, a filesystem path, or anything else). Only a FIXED, ALLOWLISTED error code, a static per-check
    description written into this script ahead of time (`_CHECK_DESCRIPTIONS`), and the exception's class name (a
    safe, non-secret Python identifier) are ever included. This replaces the previous approach of forwarding a
    truncated, regex-scrubbed exception message, which the item-3 audit correctly identified as relying on a
    64-hex-character pattern that would miss a base64-encoded secret, a variable-length secret, or a secret
    embedded in a path -- there is now simply no exception text left for such a pattern to need to catch."""
    try:
        return fn()
    except Exception as e:
        return {"status": "CHECK_RAISED_UNEXPECTED_ERROR", "error_code": "UNEXPECTED_EXCEPTION",
                "exception_type": type(e).__name__,
                "description": _CHECK_DESCRIPTIONS.get(label, _UNKNOWN_CHECK_DESCRIPTION),
                "note": f"{label} could not be evaluated -- treated as NOT_CONFIGURED, never as PASS. The "
                        "exception's own message text is never included here, in any form."}


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

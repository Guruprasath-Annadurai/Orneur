"""Differential test of StreamRedactor: ORIGINAL (15befec) vs this branch, on the same randomized chunkings.

For each random text (known secrets, prose that merely resembles secret prefixes, Unicode, PEM blocks, glued and separated) and each random chunking it compares the
streamed output with the one-shot redaction ``scan_output(text)["safe_text"]`` and counts, per implementation:

  stream_only_leak   a known secret body is visible in the streamed output although the one-shot redaction hides it
  shortened          the streamed output is a strict PREFIX of the one-shot output: its tail was lost (e.g. the last letter of "keys")
  differs            any difference at all (this branch may be STRICTER than one-shot on glued text; that is the safe direction)

Run:  PYTHONPATH=. python docs/orneur/landmarks/landmark-01/b01-final-integration/evidence/redactor_differential.py
"""
import importlib.util
import random
import subprocess
import sys
import tempfile
from pathlib import Path

from orca.serve.dlp import scan_output
from orca.serve.stream_dlp import StreamRedactor as NewRedactor

ORIGINAL_SHA = "15befec7191a1992286d7fa027236002f7d385db"
src = subprocess.run(["git", "show", f"{ORIGINAL_SHA}:orca/serve/stream_dlp.py"], capture_output=True, text=True, check=True).stdout
p = Path(tempfile.mkdtemp()) / "orig_stream_dlp.py"
p.write_text(src)
spec = importlib.util.spec_from_file_location("orig_stream_dlp", p)
orig = importlib.util.module_from_spec(spec)
spec.loader.exec_module(orig)

SECRET, AWS, GH = "sk-" + "a1B2c3D4e5F6g7H8i9J0k1L2", "AKIAIOSFODNN7EXAMPLE", "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3"
BEARER = "Bearer " + "eyJhbGciOiJIUzI1NiJ9abcdefghijkl"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAxyz0123456789\n-----END RSA PRIVATE KEY-----"
BODIES = [SECRET, AWS, GH, "eyJhbGciOiJIUzI1NiJ9abcdefghijkl", "MIIEowIBAAKCAQEAxyz0123456789"]
WORDS = ["keys", "this", "always", "is", "bus", "Gas", "AB", "Be", "Bear", "Bearer", "beware", "ghost", "gh", "g", "A", "B", "s", "sk", "sky", "skate", "ask-me",
         "sk-short", "sk-", "AKIA", "AKIAshort", "ghp_", "ghp_short", "Привет", "你好", "🌍", "naïve", "café", "x_sk-y", "pre_AKIAIOSFODNN7EXAMPLE"]
SEPARATORS = [" ", "\n", " and ", ", ", "", ".", "\t", "-", "--", "x"]


def run(cls, text, cuts):
    r, out, last = cls(), [], 0
    for c in sorted(set(cuts)) + [len(text)]:
        out.append(r.push(text[last:c]))
        last = c
    out.append(r.finish())
    return "".join(out)


def main(n_seeds=12, per_seed=3000):
    stats = {"original": dict(total=0, stream_only_leak=0, shortened=0, differs=0), "this_branch": dict(total=0, stream_only_leak=0, shortened=0, differs=0)}
    for seed in range(n_seeds):
        rnd = random.Random(seed)
        for _ in range(per_seed):
            parts = [rnd.choice([SECRET, AWS, GH, BEARER, PEM]) if rnd.random() < 0.4 else rnd.choice(WORDS) for _ in range(rnd.randint(1, 10))]
            text = rnd.choice(SEPARATORS).join(parts)
            cuts = [rnd.randrange(1, len(text)) for _ in range(rnd.randint(0, 25))] if len(text) > 1 else []
            ref = scan_output(text)["safe_text"]
            for name, cls in (("original", orig.StreamRedactor), ("this_branch", NewRedactor)):
                got = run(cls, text, cuts)
                s = stats[name]
                s["total"] += 1
                s["differs"] += got != ref
                s["stream_only_leak"] += any(b in got and b not in ref for b in BODIES)
                s["shortened"] += len(got) < len(ref) and ref.startswith(got)        # the streamed text is a strict prefix: its tail was lost
    for name, s in stats.items():
        print(f"{name:12s} total={s['total']} stream_only_leak={s['stream_only_leak']} shortened_prefix_of_one_shot={s['shortened']} differs_from_one_shot={s['differs']}")


main()

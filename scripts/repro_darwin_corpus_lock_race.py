#!/usr/bin/env python3
"""Standalone Darwin/APFS reproducer for Genesis corpus lock ENOENT.

Linux results are not a substitute for Apple Silicon macOS.

Usage on authorized Darwin hardware:

    python3 scripts/repro_darwin_corpus_lock_race.py --rounds 100 --writers 8

The naive loop opens `.process_corpus.lock` with
`O_RDWR|O_CREAT|O_NOFOLLOW` once. The fixed loop uses production
`_open_regular_at()`. A Darwin kernel defect is not claimed: the
observed failure is ENOENT from a concurrent create-visibility race
before `fcntl.flock()`.
"""
from __future__ import annotations

import argparse
import errno
import json
import os
import platform
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from orca.genesis.data.pipeline import (  # noqa: E402
    _open_directory_leaf,
    _open_regular_at,
    process_corpus,
)


def _naive_open(dir_fd: int, name: str) -> int:
    return os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=dir_fd)


def _fixed_open(dir_fd: int, name: str) -> int:
    return _open_regular_at(dir_fd, name, os.O_RDWR | os.O_CREAT)


def _stress_open(label: str, opener, rounds: int, writers: int) -> dict:
    failures: list[str] = []
    for round_i in range(rounds):
        with tempfile.TemporaryDirectory(prefix=f"orneur-lock-{label}-") as raw:
            out = Path(raw) / "out"
            dir_fd = _open_directory_leaf(out, create=True)
            errors: list[BaseException] = []
            fds: list[int] = []
            barrier = threading.Barrier(writers)

            def _run():
                try:
                    barrier.wait(timeout=15)
                    fd = opener(dir_fd, ".process_corpus.lock")
                    fds.append(fd)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=_run) for _ in range(writers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            for fd in fds:
                try:
                    os.close(fd)
                except OSError:
                    pass
            os.close(dir_fd)
            if errors:
                sample = errors[0]
                failures.append(
                    f"round={round_i} err={type(sample).__name__} errno={getattr(sample, 'errno', None)} {sample}"
                )
    return {
        "label": label,
        "rounds": rounds,
        "writers": writers,
        "failures": len(failures),
        "samples": failures[:8],
    }


def _stress_process_corpus(rounds: int, writers: int) -> dict:
    failures: list[str] = []
    texts = [f"repro record {i} about topic {i}" for i in range(12)]
    for round_i in range(rounds):
        with tempfile.TemporaryDirectory(prefix="orneur-corpus-") as raw:
            root = Path(raw)
            source = root / "in.jsonl"
            source.write_text("".join(json.dumps({"text": t}) + "\n" for t in texts))
            out = root / "out"
            errors: list[BaseException] = []
            kept: list[int] = []
            barrier = threading.Barrier(writers)

            def _run():
                try:
                    barrier.wait(timeout=30)
                    report, _ = process_corpus(
                        source, out, num_shards=2, commit_batch_size=4, return_kept_records=False
                    )
                    kept.append(report.kept)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=_run) for _ in range(writers)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            if errors:
                sample = errors[0]
                failures.append(
                    f"round={round_i} err={type(sample).__name__} errno={getattr(sample, 'errno', None)} {sample}"
                )
            elif kept != [12] * writers:
                failures.append(f"round={round_i} kept={kept}")
            else:
                shard_n = 0
                for shard in out.glob("shard-*.jsonl"):
                    shard_n += len(shard.read_text().splitlines())
                if shard_n != 12:
                    failures.append(f"round={round_i} shard_lines={shard_n}")
    return {
        "label": "process_corpus",
        "rounds": rounds,
        "writers": writers,
        "failures": len(failures),
        "samples": failures[:8],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rounds", type=int, default=100)
    parser.add_argument("--writers", type=int, default=8)
    args = parser.parse_args(argv)
    report = {
        "platform": sys.platform,
        "machine": platform.machine(),
        "mac_ver": platform.mac_ver(),
        "python": sys.version,
        "darwin": sys.platform == "darwin",
        "note": (
            "Linux-only reproduction is not a substitute. "
            "ENOENT during O_CREAT|O_NOFOLLOW is a create-visibility race, "
            "not a declared Darwin kernel defect."
        ),
        "naive": _stress_open("naive", _naive_open, args.rounds, args.writers),
        "fixed": _stress_open("fixed", _fixed_open, args.rounds, args.writers),
        "process_corpus": _stress_process_corpus(args.rounds, args.writers),
    }
    print(json.dumps(report, indent=2))
    if sys.platform != "darwin":
        print(
            "RESULT: NOT DARWIN — do not treat this as native qualification.",
            file=sys.stderr,
        )
        return 2
    if report["fixed"]["failures"] or report["process_corpus"]["failures"]:
        print("RESULT: FIXED PATH FAILED", file=sys.stderr)
        return 1
    print("RESULT: FIXED PATH HAD ZERO FAILURES ON DARWIN", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

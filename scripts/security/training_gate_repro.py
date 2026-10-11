#!/usr/bin/env python3
"""Attempt to start training through every ORNEUR entry path, with NO authorization, against whatever `orca` tree is on PYTHONPATH.

"Real work" is represented by sentinels (training dependencies / SSH are patched to raise REACHED): nothing is trained, no GPU or network is
touched. VULNERABLE = the path got past every pre-training check and reached the sentinel; BLOCKED = it was refused first.

    git worktree add /tmp/wt <sha>; PYTHONPATH=/tmp/wt python scripts/security/training_gate_repro.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path


class Reached(Exception):
    pass


def main() -> int:
    home = Path(tempfile.mkdtemp())
    os.environ["HOME"] = str(home)
    for k in ("ORNEUR_HOME", "ORCA_HOME"):
        os.environ.pop(k, None)
    # a hostile environment: every plausible "please allow it" switch is set
    for k in ("ORNEUR_ALLOW_TRAINING", "ORCA_ALLOW_TRAINING", "ORNEUR_TRAINING_AUTHORIZED", "ORNEUR_DRY_RUN", "CI", "TRAINING_AUTHORIZED"):
        os.environ[k] = "1"
    try:
        import orca
        import orca.train.cloud as cloud
        import orca.train.finetune as ft
        from orca.train.config import TrainingConfig

        print(f"orca from: {Path(orca.__file__).resolve().parent}")
        data = home / "train.jsonl"
        data.write_text('{"text": "x"}\n')
        cfg = TrainingConfig(base_model="some/experimental-model", family=None, model_name="repro")
        cfg.train_file = str(data)

        def reached(*a, **k):
            raise Reached()

        ft._check_deps = reached

        def verdict(label, fn):
            try:
                fn()
                print(f"{label}: BLOCKED?? (returned without reaching work)")
            except Reached:
                print(f"{label}: VULNERABLE (reached real-work boundary with no authorization)")
            except Exception as exc:  # noqa: BLE001
                reasons = getattr(exc, "reasons", None)
                print(f"{label}: BLOCKED ({type(exc).__name__}{': ' + ','.join(reasons) if reasons else ''})")

        verdict("T1 finetune.train()", lambda: ft.train(cfg, on_log=lambda m: None))
        verdict("T2 finetune._train_impl() called directly", lambda: ft._train_impl(cfg, lambda m: None, object()))

        fmt = home / "formatted"
        fmt.mkdir()
        (fmt / "orca_llama3_train.jsonl").write_text('{"text": "x"}\n')
        cloud.FORMATTED_DIR = fmt
        cloud._ssh_run = reached
        verdict("T3 CloudTrainer.run() (SSH rented GPU)", lambda: cloud.CloudTrainer(ssh="ssh root@192.0.2.1", preset="cloud").run())

        from typer.testing import CliRunner
        from orca.cli import app

        res = CliRunner().invoke(app, ["train", "run", "--preset", "laptop"])
        exc = res.exception
        if isinstance(exc, Reached):
            print("T4 CLI `train run`: VULNERABLE (reached real-work boundary with no authorization)")
        else:
            print(f"T4 CLI `train run`: BLOCKED (exit code {res.exit_code})")
    finally:
        shutil.rmtree(home, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

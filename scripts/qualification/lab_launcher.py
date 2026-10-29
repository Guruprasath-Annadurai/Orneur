"""ORNEUR Independent Qualification Laboratory Launcher.

Provides isolated test servers, dedicated Redis test DBs (DB 13), temporary
SQLite databases, recording model taps, and clean teardown for repeatable qualification.
"""
from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LabEnvironment:
    def __init__(self, worktree_dir: Path, redis_db: int = 13, model_tag: str = "llama3.2:1b"):
        self.worktree_dir = Path(worktree_dir).resolve()
        self.redis_db = redis_db
        self.model_tag = model_tag
        self.temp_dir = Path(tempfile.mkdtemp(prefix="orneur-lab-"))
        self.server_port = find_free_port()
        self.tap_port = find_free_port()
        self.server_proc: Optional[subprocess.Popen] = None
        self.tap_proc: Optional[subprocess.Popen] = None

    def env_vars(self) -> dict[str, str]:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(self.worktree_dir)
        env["ORCA_DATA_DIR"] = str(self.temp_dir / "data")
        env["ORCA_SQLITE_PATH"] = str(self.temp_dir / "orca.db")
        env["ORCA_REDIS_URL"] = f"redis://127.0.0.1:6379/{self.redis_db}"
        env["REDIS_URL"] = f"redis://127.0.0.1:6379/{self.redis_db}"
        env["OLLAMA_HOST"] = f"http://127.0.0.1:{self.tap_port}"
        env["DEFAULT_CHAT_MODEL"] = self.model_tag
        env["ORCA_ENV"] = "test"
        env["JWT_SECRET_KEY"] = "qualification-secret-key-32-chars-ok!"
        return env

    def check_prerequisites(self) -> dict[str, bool]:
        status = {}
        # 1. Ollama
        try:
            import urllib.request
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
                status["ollama"] = r.status == 200
        except Exception:
            status["ollama"] = False

        # 2. Redis
        try:
            import redis
            rc = redis.Redis(host="127.0.0.1", port=6379, db=self.redis_db)
            status["redis"] = rc.ping()
        except Exception:
            status["redis"] = False

        # 3. Python venv
        py_path = self.worktree_dir / ".venv" / "bin" / "python"
        if not py_path.exists():
            py_path = Path("/home/pc/projects/Orneur/.venv/bin/python")
        status["python"] = py_path.exists()

        # 4. Chromium / Playwright
        status["chromium"] = Path("/home/pc/projects/.journey-tools/libs/usr/lib/x86_64-linux-gnu/libnss3.so").exists()
        return status

    def cleanup(self) -> None:
        if self.server_proc and self.server_proc.poll() is None:
            self.server_proc.terminate()
            try:
                self.server_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.server_proc.kill()
        if self.tap_proc and self.tap_proc.poll() is None:
            self.tap_proc.terminate()
            try:
                self.tap_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.tap_proc.kill()
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ORNEUR Qualification Lab Environment Manager")
    parser.add_argument("--check", action="store_true", help="Check laboratory prerequisites")
    parser.add_argument("--worktree", default=".", help="Target worktree directory")
    args = parser.parse_args()

    lab = LabEnvironment(Path(args.worktree))
    if args.check:
        results = lab.check_prerequisites()
        print("=== LABORATORY PREREQUISITES ===")
        for k, v in results.items():
            print(f"{k:12}: {'AVAILABLE' if v else 'MISSING'}")
        all_ok = all(results.values())
        print(f"Overall Status: {'READY' if all_ok else 'DEGRADED'}")
        sys.exit(0 if all_ok else 1)

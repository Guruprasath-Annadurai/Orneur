from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "Dockerfile"
PYPROJECT = ROOT / "pyproject.toml"
DOCKERIGNORE = ROOT / ".dockerignore"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_dockerfile_copies_declared_readme_before_package_install() -> None:
    """Regression for the first real Northflank Phase 14B build failure."""
    pyproject = _text(PYPROJECT)
    dockerfile = _text(DOCKERFILE)

    assert 'readme = "README.md"' in pyproject
    readme_copy = dockerfile.index("COPY pyproject.toml README.md ./")
    install = dockerfile.index('RUN uv pip install --system -e ".[postgres]"')
    assert readme_copy < install


def test_distributed_container_installs_postgres_runtime_extra() -> None:
    pyproject = _text(PYPROJECT)
    dockerfile = _text(DOCKERFILE)

    assert 'postgres = [' in pyproject
    assert '"psycopg[binary]>=3.1"' in pyproject
    assert 'RUN uv pip install --system -e ".[postgres]"' in dockerfile


def test_container_healthcheck_uses_phase14_liveness_contract() -> None:
    dockerfile = _text(DOCKERFILE)

    assert "http://localhost:7337/livez" in dockerfile
    assert "http://localhost:7337/api/status" not in dockerfile
    assert "--start-period=20s" in dockerfile


def test_container_publishes_only_orneur_api_port() -> None:
    dockerfile = _text(DOCKERFILE)
    exposed = [line.strip() for line in dockerfile.splitlines() if line.strip().startswith("EXPOSE ")]

    assert exposed == ["EXPOSE 7337"]
    assert "EXPOSE 5432" not in dockerfile
    assert "EXPOSE 6379" not in dockerfile
    assert "EXPOSE 11434" not in dockerfile


def test_container_entrypoint_matches_phase14_service_contract() -> None:
    dockerfile = _text(DOCKERFILE)

    assert 'CMD ["orca", "serve", "--host", "0.0.0.0", "--port", "7337", "--no-open"]' in dockerfile


def test_docker_build_context_excludes_common_secret_and_runtime_artifacts() -> None:
    dockerignore = _text(DOCKERIGNORE).splitlines()
    entries = {line.strip() for line in dockerignore if line.strip() and not line.lstrip().startswith("#")}

    required = {
        ".git",
        ".github",
        ".env",
        ".env.*",
        "*.pem",
        "*.key",
        "*.db",
        "*.db-wal",
        "*.db-shm",
        "*.log",
        "tests",
    }
    assert required <= entries

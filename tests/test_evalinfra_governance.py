"""Hard-rule guards for the evalinfra package: no network / model / provider / GPU imports, no ambient environment reads, no private-eval paths, no secrets,
and the frozen governance state of the repository is untouched."""
import ast
import json
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "orca" / "evalinfra"
FORBIDDEN_IMPORTS = {"socket", "ssl", "http", "urllib", "urllib3", "requests", "httpx", "aiohttp", "websockets", "ftplib", "smtplib", "telnetlib", "xmlrpc", "subprocess",
                     "torch", "transformers", "tensorflow", "jax", "onnxruntime", "vllm", "openai", "anthropic", "ollama", "huggingface_hub", "datasets", "peft", "trl",
                     "accelerate", "bitsandbytes", "cohere", "mistralai", "google", "boto3", "modal", "docker", "numpy", "scipy"}
SOURCES = sorted(PKG.glob("*.py"))


def imports_of(path):
    tree = ast.parse(path.read_text())
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            out |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            out.add(n.module.split(".")[0])
        elif isinstance(n, ast.Call) and getattr(n.func, "id", "") == "__import__" and n.args and isinstance(n.args[0], ast.Constant):
            out.add(str(n.args[0].value).split(".")[0])
    return out


def test_package_has_the_expected_modules():
    assert {p.name for p in SOURCES} >= {"schema.py", "private_store.py", "splits.py", "leakage.py", "access.py", "stats_paired.py", "stats_power.py", "rating.py",
                                          "config_lock.py", "prereg_check.py", "budget.py", "chain.py", "results.py", "report.py", "cli.py", "synthetic.py"}


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_network_model_provider_or_gpu_imports(path):
    bad = imports_of(path) & FORBIDDEN_IMPORTS
    assert not bad, f"{path.name} imports {sorted(bad)}"


@pytest.mark.parametrize("path", SOURCES, ids=lambda p: p.name)
def test_no_ambient_environment_reads_and_no_private_paths(path):
    src = path.read_text()
    attrs = {n.attr for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Attribute)} | {n.id for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Name)}
    assert not attrs & {"environ", "environb", "getenv", "putenv"}, "environment must be passed in explicitly"
    code_only = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    assert "eval_private" not in code_only, "the package must never reference the private-eval directory"
    assert not re.search(r"\b(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|-----BEGIN [A-Z ]*PRIVATE KEY-----)", src)


def test_python_311_compatibility_no_backslash_in_fstring_expressions():
    for path in SOURCES + sorted((ROOT / "tests").glob("test_evalinfra_*.py")) + [ROOT / "scripts" / "evalinfra_synthetic_demo.py"]:
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.JoinedStr):
                for v in node.values:
                    if isinstance(v, ast.FormattedValue):
                        seg = ast.get_source_segment(path.read_text(), v.value) or ""
                        assert "\\" not in seg, f"{path.name}: backslash inside an f-string expression"


def test_no_real_model_call_surface_exists():
    names = {n.name for p in SOURCES for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}
    assert not {n for n in names if re.search(r"(?i)(generate_text|chat_complete|call_model|run_inference|llm_judge|query_provider|download_weights)", n)}


def test_committed_governance_state_is_untouched():
    auth = ROOT / "docs/orneur/authorization"
    assert json.loads((auth / "MODEL_EVAL_AUTHORIZATION.json").read_text())["status"] == "NOT_AUTHORIZED"
    assert json.loads((auth / "CORPUS_GENERATION_AUTHORIZATION.json").read_text())["status"] == "NOT_AUTHORIZED"
    assert json.loads((auth / "REVIEWER_REGISTRY.json").read_text())["records"] == []
    assert all(r["state"] != "AUTHORIZED" for r in json.loads((auth / "QUALIFICATION_RUNNER_REGISTRY.json").read_text())["records"])
    status = json.loads((ROOT / "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json").read_text())
    assert status["GENESIS_CAPABILITY_EVAL_V2_FROZEN"] is False and not any(status["freeze_prerequisites"].values())
    assert status["private_storage_state"] == "NOT_CONFIGURED" and status["GENESIS_CAPABILITY_EVAL_V1_PRIVATE_HOLDOUT_VALID"] is False
    from orca.eval.genesis_v2 import spec
    assert spec.GENESIS_CAPABILITY_EVAL_V2_FROZEN is False and spec.freeze_status()["frozen"] is False


FROZEN = ["docs/orneur/acceptance", "docs/orneur/authorization", "docs/orneur/phase-21/rse", "orca/rse", "orca/train/authorization.py",
          "docs/orneur/acceptance/register_graph.json", "docs/orneur/phase-21/GENESIS_CAPABILITY_EVAL_V2_STATUS.json", "eval_private"]


def test_no_frozen_or_private_path_differs_from_the_branch_point():
    """The branch was cut from cd6af2a; none of the frozen/governance paths may differ from it.

    A missing branch-point commit is a qualification failure. The check must
    not skip on a shallow checkout.
    """
    base = "cd6af2ac2cf1320b5ffd5ca646784c99ccc5ee8d"
    probe = subprocess.run(["git", "cat-file", "-e", base + "^{commit}"], cwd=ROOT, capture_output=True)
    if probe.returncode != 0:
        pytest.fail(
            "qualification failure: branch-point commit "
            + base
            + " is absent, so the frozen-path governance diff did not execute"
        )
    out = subprocess.run(["git", "diff", "--name-only", base, "--", *FROZEN], cwd=ROOT, capture_output=True, text=True)
    assert out.returncode == 0 and out.stdout.strip() == "", out.stdout

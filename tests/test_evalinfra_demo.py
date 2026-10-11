"""The committed SYNTHETIC demo output must be exactly what the script regenerates (reproducibility), verify cleanly, and be unmistakably labelled."""
import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "docs/orneur/status/evalinfra/demo"
BANNER = "SYNTHETIC - NOT EVIDENCE OF ANY MODEL CAPABILITY"


def _load_script():
    spec = importlib.util.spec_from_file_location("evalinfra_synthetic_demo", ROOT / "scripts/evalinfra_synthetic_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_committed_demo_is_labelled_synthetic_everywhere():
    assert (DEMO / "SYNTHETIC_NOT_EVIDENCE.md").read_text().startswith(f"# {BANNER}")
    assert (DEMO / "report.md").read_text().startswith(f"# {BANNER}")
    for name in ("report.json", "manifest.json", "analysis_plan.json"):
        assert json.loads((DEMO / name).read_text())["synthetic"] is True, name
    assert all(c["synthetic"] is True for c in json.loads((DEMO / "arm_configs.json").read_text()).values())
    for name in ("isolation_and_leakage_checks.json", "power_tables.json", "budget_demo.json", "verification.json"):
        assert json.loads((DEMO / name).read_text())["banner"] == BANNER
    prereg = json.loads((DEMO / "prereg.json").read_text())
    assert prereg["bindings"]["eval_version"].startswith("SYNTHETIC")


def test_committed_demo_chain_verifies_with_the_cli():
    r = subprocess.run([sys.executable, "-m", "orca.evalinfra", "verify", str(DEMO / "result_chain.jsonl")], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert r.returncode == 0 and BANNER in r.stderr
    v = json.loads(r.stdout)
    assert v["ok"] and v["synthetic"] and v["results"] == 15 and v["arms_locked"] == ["B0", "B1", "B2", "T1", "T2"]
    assert v["head"] == json.loads((DEMO / "report.json").read_text())["provenance"]["log_head"]


def test_demo_contains_no_item_content_or_forbidden_keys():
    from orca.eval.genesis_v2 import spec
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                assert k not in spec.FORBIDDEN_PUBLIC_KEYS, k
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    for p in DEMO.glob("*.json"):
        walk(json.loads(p.read_text()))
    for line in (DEMO / "result_chain.jsonl").read_text().splitlines():
        walk(json.loads(line))
    raw = (DEMO / "result_chain.jsonl").read_text()
    assert '"prompt"' not in raw and '"ground_truth"' not in raw and '"answer"' not in raw


def test_demo_regenerates_byte_for_byte(tmp_path):
    mod = _load_script()
    out = tmp_path / "demo"                                    # the repo's autouse conftest fills tmp_path with unrelated dirs; use a dedicated subdirectory
    mod.run(out)
    committed = sorted(p.name for p in DEMO.iterdir())
    assert sorted(p.name for p in out.iterdir()) == committed
    for name in committed:
        assert (DEMO / name).read_bytes() == (out / name).read_bytes(), name

"""C1/C2/C3 machine-readable preregistration TEMPLATES: valid drafts, and anything that makes them look frozen/approved/resulted is refused."""
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

from orca.evalinfra import prereg_templates as PT

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "docs/orneur/research/preregistration"


def T():
    return copy.deepcopy(PT.load_templates())


def test_three_templates_exist_and_validate():
    assert sorted(p.name[:2] for p in DIR.glob("C*_*.json")) == ["C1", "C2", "C3"]
    docs = PT.load_templates()
    assert PT.validate_programme(docs) == []
    for t, d in docs.items():
        assert d["track"] == t and d["status"] == PT.STATUS and d["frozen"] is False and d["approved"] is False
        assert d["results"] == [] and d["selected_model"] is None and d["training_authorization"] == "NOT_AUTHORIZED"
        assert d["arms"]["primary_comparison"] == {"treatment": "T2", "control": "B2"}


def test_templates_are_plain_json_with_no_model_names():
    for p in DIR.glob("C*_*.json"):
        txt = p.read_text()
        json.loads(txt)
        for name in ("llama", "qwen", "mistral", "gemma", "phi-", "gpt-"):
            assert name not in txt.lower(), (p.name, name)


MUT = {
    "frozen": lambda d: d.__setitem__("frozen", True),
    "approved": lambda d: d.__setitem__("approved", True),
    "approved_by": lambda d: d.__setitem__("approved_by", "someone"),
    "frozen_at": lambda d: d.__setitem__("frozen_at", "2026-10-12T00:00:00Z"),
    "status": lambda d: d.__setitem__("status", "FROZEN"),
    "hash": lambda d: d.__setitem__("prereg_record_sha256", "a" * 64),
    "result": lambda d: d["results"].append({"arm": "T2", "score": 1}),
    "no_result_flag": lambda d: d.__setitem__("no_result_exists", False),
    "model": lambda d: d.__setitem__("selected_model", "some-model"),
    "authorizes": lambda d: d.__setitem__("authorizes", ["training"]),
    "training": lambda d: d.__setitem__("training_authorization", "AUTHORIZED"),
    "arms": lambda d: d["arms"].__setitem__("required", ["B0", "B2", "T2"]),
    "primary_cmp": lambda d: d["arms"].__setitem__("primary_comparison", {"treatment": "B2", "control": "B1"}),
    "resamples": lambda d: d["statistics"].__setitem__("bootstrap_resamples", 1000),
    "seeds": lambda d: d["statistics"].__setitem__("min_training_seeds", 1),
    "items": lambda d: d["statistics"].__setitem__("min_items_per_primary_endpoint", 100),
    "zero_tol": lambda d: d["non_regression"].__setitem__("zero_tolerance_categories", [10]),
    "banner": lambda d: d.__setitem__("banner", "final"),
    "primary_no_threshold": lambda d: [e.__setitem__("threshold", None) for e in d["endpoints"] if e["kind"] == "PRIMARY"],
    "unknown_key": lambda d: d.__setitem__("extra", 1),
    "missing_key": lambda d: d.pop("failure_criteria"),
}


@pytest.mark.parametrize("name", sorted(MUT))
def test_tampered_template_is_refused(name):
    docs = T()
    MUT[name](docs["C1"])
    assert PT.validate_template(docs["C1"], expected_track="C1"), name
    assert PT.validate_programme(docs)


def test_programme_wide_rules():
    docs = T()
    del docs["C3"]
    assert PT.validate_programme(docs)
    docs = T()
    docs["C1"]["endpoints"].append({**docs["C1"]["endpoints"][0], "id": "C1-P2"})
    docs["C3"]["endpoints"].append({**docs["C3"]["endpoints"][0], "id": "C3-P2"})
    assert PT.validate_programme(docs)
    assert PT.validate_template("not a dict") and PT.validate_template(None)


def test_cli_checks_templates():
    r = subprocess.run([sys.executable, str(ROOT / "scripts/evalinfra_arm_comparison.py"), "check-prereg"], capture_output=True, text=True, cwd=ROOT, timeout=120)
    assert r.returncode == 0 and json.loads(r.stdout)["ok"] is True

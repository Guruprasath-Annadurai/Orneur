"""(9) Deterministic versioned dataset manifests + tamper verification.

REUSES orca.registry.dataset_manifest.DatasetManifest (the dataclass, its field set, sha256_of_file) and orca.registry._ids.validate_id. The manifest is
NOT written through DatasetManifest.save() (that targets ORCA_HOME and stamps the current time); it is built in memory, wrapped in an envelope and
written wherever the caller asks, so the bytes are reproducible: same inputs + same ``now`` => same file.

Envelope::

    {"format": "orneur-dataquality-manifest/1", "manifest": <DatasetManifest fields>, "record_digests": {"train": [..], "eval": [..]},
     "record_digest_scheme": "sha256 of each raw JSONL line (without line terminator)", "manifest_digest": sha256(canonical(envelope minus manifest_digest))}

``verify`` detects: edited manifest, changed/added/removed/reordered records (with line numbers), changed file bytes, changed record counts.
The manifest_digest is an integrity checksum, not a signature: who is allowed to publish a manifest is decided elsewhere (review / acceptance engine).
"""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from orca.dataquality._common import digest_of, load_jsonl, pretty_json, sha256_file

FORMAT = "orneur-dataquality-manifest/1"
NOT_RECORDED = "NOT_RECORDED"
NOT_APPLICABLE = "NOT_APPLICABLE"


def _digest_envelope(env: dict) -> str:
    return digest_of({k: v for k, v in env.items() if k != "manifest_digest"})


def build(train_path, eval_path=None, *, dataset_id: str, version: str, purpose: str, creation_code_sha: str, source_paths: list | None = None,
          schema: str = "", filters_applied: str = "", deduplication_result: str = "", known_limitations: list | None = None, now: str | None = None,
          target_model_family: str = "") -> dict:
    from orca.registry._ids import validate_id
    from orca.registry.dataset_manifest import DatasetManifest

    validate_id(dataset_id, "dataset_id")
    validate_id(version, "version")
    train_lines = load_jsonl(train_path)
    eval_lines = load_jsonl(eval_path) if eval_path else []
    m = DatasetManifest(
        dataset_id=dataset_id, version=version, purpose=purpose, source_paths=sorted(source_paths or []),
        record_count=len(train_lines) + len(eval_lines), schema=schema,
        train_checksum=sha256_file(train_path), eval_checksum=sha256_file(eval_path) if eval_path else NOT_APPLICABLE,
        creation_code_sha=creation_code_sha, filters_applied=filters_applied, deduplication_result=deduplication_result,
        known_limitations=list(known_limitations or []), created_at=now or NOT_RECORDED, target_model_family=target_model_family,
    )
    env = {
        "format": FORMAT, "manifest": asdict(m),
        "record_digests": {"train": [l.raw_sha256 for l in train_lines], "eval": [l.raw_sha256 for l in eval_lines]},
        "record_digest_scheme": "sha256 of each raw JSONL line (without line terminator)",
    }
    env["manifest_digest"] = _digest_envelope(env)
    return env


def write(env: dict, path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(pretty_json(env), encoding="utf-8")
    return p


def load(path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _diff_lines(expected: list, lines: list) -> dict:
    changed = [i + 1 for i, (e, l) in enumerate(zip(expected, lines)) if e != l.raw_sha256]
    return {"changed_lines": changed[:200], "changed_count": len(changed), "records_expected": len(expected), "records_actual": len(lines)}


def verify(env, train_path, eval_path=None) -> dict:
    from orca.registry.dataset_manifest import DatasetManifest

    problems: list = []
    if not isinstance(env, dict) or env.get("format") != FORMAT:
        return {"check": "manifest_verify", "status": "FAIL", "problems": [{"code": "bad_format", "message": f"format must be {FORMAT}"}]}
    if env.get("manifest_digest") != _digest_envelope(env):
        problems.append({"code": "manifest_digest_mismatch", "message": "manifest content was edited after it was built"})
    try:
        m = DatasetManifest(**env["manifest"])
    except Exception as e:
        return {"check": "manifest_verify", "status": "FAIL", "problems": problems + [{"code": "manifest_fields_invalid", "message": type(e).__name__}]}
    detail: dict = {}
    for split, path, expected_sum in (("train", train_path, m.train_checksum), ("eval", eval_path, m.eval_checksum)):
        if path is None:
            if expected_sum != NOT_APPLICABLE:
                problems.append({"code": f"{split}_file_not_supplied", "message": f"manifest records a {split} checksum but no {split} file was supplied"})
            continue
        if expected_sum == NOT_APPLICABLE:
            problems.append({"code": f"{split}_not_in_manifest", "message": f"a {split} file was supplied but the manifest records none"})
            continue
        actual = sha256_file(path)
        lines = load_jsonl(path)
        exp_digests = env.get("record_digests", {}).get(split, [])
        d = _diff_lines(exp_digests, lines)
        detail[split] = d
        if actual != expected_sum:
            problems.append({"code": f"{split}_checksum_mismatch", "message": f"{split} file bytes differ from the manifest"})
        if d["records_expected"] != d["records_actual"]:
            problems.append({"code": f"{split}_record_count_mismatch", "message": f"manifest lists {d['records_expected']} records, file has {d['records_actual']}"})
        if d["changed_count"]:
            problems.append({"code": f"{split}_records_changed", "message": f"{d['changed_count']} record digest(s) differ (first lines: {d['changed_lines'][:10]})"})
    total = sum(d["records_actual"] for d in detail.values())
    if detail and total != m.record_count:
        problems.append({"code": "total_record_count_mismatch", "message": f"manifest record_count={m.record_count}, files have {total}"})
    return {"check": "manifest_verify", "status": "PASS" if not problems else "FAIL", "dataset_id": m.dataset_id, "version": m.version,
            "manifest_digest": env.get("manifest_digest"), "problems": problems, "detail": detail}

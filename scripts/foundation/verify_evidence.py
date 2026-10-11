#!/usr/bin/env python3
"""Offline verifier for docs/orneur/status/foundation/foundation_evidence.json.

NO network access, NO model loading.  Checks (all must pass, exit code 0):
  1. schema: required sections, claim-class enumeration, ISO timestamps.
  2. provenance: every claim-bearing record has claim_class + source_url + retrieved_at + revision;
     INDEPENDENTLY_REPRODUCED records must cite existing repository files.
  3. licences: nothing is GRANTED without a stored licence text whose sha256 and git blob sha1 re-compute from the file on
     disk and whose blob id equals the Hugging Face tree oid at the pinned revision; ambiguous licences are never GRANTED.
  4. hashes: every recorded text (configs, licences, tokenizer configs, chat templates) re-hashes to the recorded values;
     chat templates equal the template inside the byte-verified tokenizer_config.json (or the repo-recorded hash for Nemo).
  5. weights integrity: LFS sha256/size in the stored tree manifests equal the repo's pre-cache manifests.
  6. ranking guards: provisional, non-binding, not a selection; only documented criteria carry scores; capability criteria are
     NOT_EVALUATED; weights sum to 100.
Usage:  python3 scripts/foundation/verify_evidence.py [path/to/foundation_evidence.json]
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT = ROOT / "docs" / "orneur" / "status" / "foundation" / "foundation_evidence.json"
CLASSES = {"DOCUMENTED_FACT", "INDEPENDENTLY_REPRODUCED", "UNTESTED_HYPOTHESIS", "NOT_VERIFIED"}
LICENSE_STATUSES = {"GRANTED", "RESTRICTED_NONCOMMERCIAL", "REQUIRES_COUNSEL", "TAG_ONLY_UNVERIFIED"}
SCORED = {"D", "E", "L", "O", "P"}
NOT_EVALUATED = {"F", "G", "H", "I", "J", "M", "N", "Q", "R"}
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_TOP = ["schema_version", "document", "constraints_observed", "claim_classes", "license_statuses", "retrieval_session", "candidates",
                "identity_only_candidates", "texts", "license_findings", "provisional_ranking", "repo_claim_checks", "changes_vs_package_2026_09_26",
                "harness_errors", "not_verified", "estimate_formulas", "package_delta"]
FLAT_SECTIONS = ["license_findings", "repo_claim_checks", "changes_vs_package_2026_09_26", "harness_errors", "not_verified"]
ESTIMATE_TOPICS = {"memory_estimate", "serving_estimate", "cost_hypothesis"}


def blob_sha1(b: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def _paths_exist(src: str, root: Path) -> list[str]:
    bad = []
    body = src[len("repo:"):] if src.startswith("repo:") else src
    for part in [p.strip() for p in body.split(" ; ") if p.strip()]:
        part = part.removeprefix("repo:")
        if not (root / part).exists():
            bad.append(part)
    return bad


def check_provenance(rec: dict, where: str, root: Path, errs: list[str]):
    cls = rec.get("claim_class")
    if cls not in CLASSES:
        errs.append(f"{where}: claim_class {cls!r} not in {sorted(CLASSES)}")
    for k in ("source_url", "retrieved_at", "revision"):
        if not isinstance(rec.get(k), str) or not rec.get(k):
            errs.append(f"{where}: missing/empty {k}")
    ts, url, rev = rec.get("retrieved_at"), rec.get("source_url"), rec.get("revision")
    if isinstance(ts, str) and ts and not ISO.match(ts):
        errs.append(f"{where}: retrieved_at {ts!r} is not ISO-8601")
    if isinstance(url, str) and url:
        if not (url.startswith("https://") or url.startswith("repo:")):
            errs.append(f"{where}: source_url must be https:// or repo:, got {url[:60]!r}")
        if url.startswith("repo:"):
            for b in _paths_exist(url, root):
                errs.append(f"{where}: repo source path does not exist: {b}")
        if cls == "INDEPENDENTLY_REPRODUCED" and not url.startswith("repo:"):
            errs.append(f"{where}: INDEPENDENTLY_REPRODUCED must cite repository evidence (repo:...)")
    if isinstance(rev, str) and rev:
        ok = (HEX40.match(rev) or re.match(r"^repo@[0-9a-f]{40}$", rev) or rev.startswith("UNVERSIONED_WEB_PAGE@") or rev.startswith("arXiv:"))
        if not ok:
            errs.append(f"{where}: revision {rev!r} is not a 40-hex SHA / repo@SHA / UNVERSIONED_WEB_PAGE@ts / arXiv:id")


def walk(o, where, root, errs):
    if isinstance(o, dict):
        if "claim_class" in o:
            check_provenance(o, where, root, errs)
        for k, v in o.items():
            walk(v, f"{where}.{k}", root, errs)
    elif isinstance(o, list):
        for i, v in enumerate(o):
            walk(v, f"{where}[{i}]", root, errs)


def check_license(lic: dict, where: str, root: Path, errs: list[str], trees: dict):
    st = lic.get("license_status")
    if st not in LICENSE_STATUSES:
        errs.append(f"{where}: license_status {st!r} invalid")
        return
    text = lic.get("text")
    if st == "GRANTED":
        if not text:
            errs.append(f"{where}: GRANTED without a retrieved licence text")
            return
    if text:
        for k in ("file", "sha256", "git_blob_sha1", "bytes", "source_url", "retrieved_at", "revision"):
            if k not in text or text[k] in (None, ""):
                errs.append(f"{where}.text: missing {k}")
        p = root / text.get("file", "")
        if not p.is_file():
            errs.append(f"{where}.text: file missing {text.get('file')}")
            return
        b = p.read_bytes()
        if hashlib.sha256(b).hexdigest() != text.get("sha256"):
            errs.append(f"{where}.text: sha256 mismatch for {text.get('file')}")
        if blob_sha1(b) != text.get("git_blob_sha1"):
            errs.append(f"{where}.text: git blob sha1 mismatch for {text.get('file')}")
        if len(b) != text.get("bytes"):
            errs.append(f"{where}.text: byte length mismatch for {text.get('file')}")
        if not HEX64.match(str(text.get("sha256"))):
            errs.append(f"{where}.text: sha256 is not 64 hex")
        # blob id must equal HF tree oid at the pinned revision (when a tree manifest exists)
        for tr in trees.values():
            if tr["revision"] == text.get("revision"):
                fn = Path(text["file"]).name
                ent = [f for f in tr["files"] if f["path"] == fn]
                if ent and ent[0]["git_blob_sha1"] != text.get("git_blob_sha1"):
                    errs.append(f"{where}.text: blob id differs from the HF tree oid at the pinned revision")
                if not ent:
                    errs.append(f"{where}.text: file {fn} not present in the tree manifest of revision {text.get('revision')}")


def load_trees(root: Path) -> dict:
    out = {}
    d = root / "docs" / "orneur" / "status" / "foundation" / "retrieved"
    if d.is_dir():
        for t in d.glob("*/tree.json"):
            out[t.parent.name] = json.loads(t.read_text(encoding="utf-8"))
    return out


def verify(doc: dict, root: Path = ROOT) -> list[str]:
    errs: list[str] = []
    for k in REQUIRED_TOP:
        if k not in doc:
            errs.append(f"top-level: missing {k}")
    if errs:
        return errs
    if doc["schema_version"] != "orneur.foundation_evidence/1":
        errs.append("schema_version must be orneur.foundation_evidence/1")
    if set(doc["claim_classes"]) != CLASSES:
        errs.append("claim_classes must be exactly " + ", ".join(sorted(CLASSES)))
    if set(doc["license_statuses"]) != LICENSE_STATUSES:
        errs.append("license_statuses enumeration changed")
    cons = doc["constraints_observed"]
    for k in ("training", "gpu", "model_downloads", "model_inference", "provider_inference_calls", "spending", "api_keys_used", "control_retry"):
        if cons.get(k) is not False:
            errs.append(f"constraints_observed.{k} must be false")
    if "NOT A SELECTION" not in doc["document"].get("banner", ""):
        errs.append("document.banner must state NOT A SELECTION")
    if doc["document"].get("status") != "PROVISIONAL_NON_BINDING_NOT_A_SELECTION":
        errs.append("document.status must be PROVISIONAL_NON_BINDING_NOT_A_SELECTION")

    # 1/2 provenance everywhere a claim_class exists + mandatory sections
    walk(doc, "$", root, errs)
    for sec in FLAT_SECTIONS:
        for i, r in enumerate(doc[sec]):
            if "claim_class" not in r:
                errs.append(f"{sec}[{i}]: missing claim_class")
    for r in doc["not_verified"]:
        if r.get("claim_class") != "NOT_VERIFIED":
            errs.append(f"not_verified {r.get('id')}: class must be NOT_VERIFIED")
    cand_all = list(doc["candidates"]) + list(doc["identity_only_candidates"])
    if not doc["candidates"] or not all(c.get("claims") for c in cand_all):
        errs.append("every candidate must carry claims")
    for c in cand_all:
        for i, cl in enumerate(c["claims"]):
            w = f"candidate {c['id']}.claims[{i}]"
            if "claim_class" not in cl:
                errs.append(f"{w}: missing claim_class")
            if cl.get("topic") in ESTIMATE_TOPICS and cl.get("claim_class") != "UNTESTED_HYPOTHESIS":
                errs.append(f"{w}: estimates/cost figures must be UNTESTED_HYPOTHESIS")
            if cl.get("claim_class") == "UNTESTED_HYPOTHESIS" and not (cl.get("derivation") or cl.get("topic") in ESTIMATE_TOPICS or cl.get("topic") == "hardware_compat"):
                errs.append(f"{w}: hypothesis without derivation")
        if "license" not in c:
            errs.append(f"candidate {c['id']}: missing license")

    # 3 licences
    trees = load_trees(root)
    for c in cand_all:
        check_license(c["license"], f"candidate {c['id']}.license", root, errs, trees)
    # ambiguous never GRANTED
    status_by_id = {c["id"]: c["license"]["license_status"] for c in cand_all}
    for r in doc["license_findings"]:
        if r.get("permission_status") in ("UNVERIFIED_TEXT", "CONDITIONAL_ON_DECLARATION") and status_by_id.get(r.get("candidate_id")) == "GRANTED":
            errs.append(f"license_findings: {r.get('candidate_id')} has an unverified-text finding but is GRANTED")
    for c in cand_all:
        if c["license"]["license_status"] == "GRANTED" and c["license"].get("text") is None:
            errs.append(f"{c['id']}: GRANTED requires text")

    # 4 hashes of recorded texts
    by_key = {}
    for t in doc["texts"]:
        by_key[t["key"]] = t
        w = f"texts[{t['key']}]"
        p = root / t["path"]
        if not p.is_file():
            errs.append(f"{w}: file missing")
            continue
        b = p.read_bytes()
        if hashlib.sha256(b).hexdigest() != t["sha256"]:
            errs.append(f"{w}: sha256 mismatch")
        if len(b) != t["bytes"]:
            errs.append(f"{w}: byte length mismatch")
        if t.get("git_blob_sha1") and blob_sha1(b) != t["git_blob_sha1"]:
            errs.append(f"{w}: git blob sha1 mismatch")
        tr = trees.get(t["slug"])
        if tr is None:
            errs.append(f"{w}: no tree manifest for {t['slug']}")
        else:
            if tr["revision"] != t["revision"]:
                errs.append(f"{w}: revision differs from tree manifest")
            if t.get("git_blob_sha1"):
                ent = [f for f in tr["files"] if f["path"] == t["file"]]
                if not ent or ent[0]["git_blob_sha1"] != t["git_blob_sha1"]:
                    errs.append(f"{w}: blob id not equal to HF tree oid")
        if t["file"] == "chat_template.jinja.txt":
            parent = root / "docs/orneur/status/foundation/retrieved" / t["slug"] / "tokenizer_config.json"
            if parent.is_file():
                tc = json.loads(parent.read_text(encoding="utf-8"))
                if tc.get("chat_template", "").encode("utf-8") != b:
                    errs.append(f"{w}: template differs from tokenizer_config.json chat_template")
                if blob_sha1(parent.read_bytes()) != next(f["git_blob_sha1"] for f in tr["files"] if f["path"] == "tokenizer_config.json"):
                    errs.append(f"{w}: parent tokenizer_config.json is not byte-exact")
            else:
                rp = root / t.get("repo_evidence_path", "")
                if not rp.is_file():
                    errs.append(f"{w}: repo evidence for template hash missing")
                else:
                    rec = json.loads(rp.read_text(encoding="utf-8"))["A_pinned_tokenizer_config"]["chat_template_sha256"]
                    if rec != t["sha256"]:
                        errs.append(f"{w}: template sha256 differs from repo-recorded hash")
    # claims that quote a template hash must equal the registry
    for c in doc["candidates"]:
        for cl in c["claims"]:
            v = cl.get("value")
            if isinstance(v, dict) and "template_sha256" in v:
                t = by_key.get(f"{c['id']}/chat_template.jinja.txt")
                if not t or t["sha256"] != v["template_sha256"]:
                    errs.append(f"candidate {c['id']}: template_sha256 in claim differs from registry")
                if t and f"sha256 {t['sha256']}" not in cl["statement"]:
                    errs.append(f"candidate {c['id']}: statement does not quote the registry template hash")

    # 5 weights integrity vs repo manifests
    mf = doc.get("weights_integrity_cross_check", {}).get("manifests", {})
    for slug, rel in mf.items():
        mp = root / rel
        tr = trees.get(slug)
        if not mp.is_file() or tr is None:
            errs.append(f"weights integrity: missing manifest or tree for {slug}")
            continue
        m = json.loads(mp.read_text(encoding="utf-8"))["manifest"]
        if m["revision"] != tr["revision"]:
            errs.append(f"weights integrity: {slug} revision differs from repo manifest")
        mine = {f["path"]: (f["lfs_sha256"], f["size"]) for f in tr["files"] if f["lfs_sha256"]}
        for f in m["files"]:
            if f.get("hf_lfs_sha256") and mine.get(f["filename"]) != (f["hf_lfs_sha256"], f["bytes"]):
                errs.append(f"weights integrity: {slug}/{f['filename']} differs from repo manifest")

    # 6 ranking guards
    rk = doc["provisional_ranking"]
    if rk.get("status") != "PROVISIONAL_NON_BINDING" or rk.get("is_selection") is not False or rk.get("binding") is not False or rk.get("selected_foundation") is not None:
        errs.append("ranking: must be PROVISIONAL_NON_BINDING, is_selection=false, binding=false, selected_foundation=null")
    if "NOT A SELECTION" not in rk.get("statement", ""):
        errs.append("ranking.statement must say NOT A SELECTION")
    weighted = [c for c in rk["criteria"] if c["kind"] == "weighted"]
    if sum(c["weight"] for c in weighted) != 100:
        errs.append("ranking: weighted criteria must sum to 100")
    ids = {c["id"] for c in rk["criteria"]}
    if ids != set("ABKFGHIJDELMNOPQR"):
        errs.append("ranking: criteria ids must be A,B,K,F,G,H,I,J,D,E,L,M,N,O,P,Q,R")
    for c in rk["criteria"]:
        if c["id"] in NOT_EVALUATED and c["evaluation_state"] != "NOT_EVALUATED":
            errs.append(f"ranking: criterion {c['id']} must be NOT_EVALUATED")
        if c["id"] in SCORED and c["evaluation_state"] != "SCORED_FROM_DOCUMENTED_EVIDENCE":
            errs.append(f"ranking: criterion {c['id']} state must be SCORED_FROM_DOCUMENTED_EVIDENCE")
    for cs in rk["candidate_scores"]:
        extra = set(cs["scores"]) - SCORED
        if extra:
            errs.append(f"ranking: {cs['candidate']} has scores for non-scoreable criteria {sorted(extra)}")
        if abs(sum(cs["scores"].values()) - cs["documented_subset_points"]) > 0.011:
            errs.append(f"ranking: {cs['candidate']} subtotal arithmetic mismatch")
        if cs["documented_subset_max"] + cs["unevaluated_points"] != 100:
            errs.append(f"ranking: {cs['candidate']} max+unevaluated must be 100")
        mx = {"D": 4, "E": 4, "L": 4, "O": 6, "P": 6}
        for k, v in cs["scores"].items():
            if k in mx and not (0 <= v <= mx[k]):
                errs.append(f"ranking: {cs['candidate']} {k} out of range")
    scored_ids = {cs["candidate"] for cs in rk["candidate_scores"]}
    for ex in rk["excluded_from_weighted_scoring"]:
        if ex["candidate"] in scored_ids:
            errs.append(f"ranking: excluded candidate {ex['candidate']} was scored")
    for cid, g in rk["gates"].items():
        for gk in ("A", "B", "K"):
            if gk not in g:
                errs.append(f"ranking: gate {gk} missing for {cid}")
        if g.get("K", {}).get("result") == "PASS" and status_by_id.get(cid) != "GRANTED":
            errs.append(f"ranking: gate K PASS for {cid} requires licence status GRANTED (has {status_by_id.get(cid)})")
    for d in rk["score_details"]:
        if d["criterion"] in ("O", "P") and d["claim_class"] != "UNTESTED_HYPOTHESIS":
            errs.append("ranking: O/P scores must be UNTESTED_HYPOTHESIS")
    return errs


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else DEFAULT
    doc = json.loads(path.read_text(encoding="utf-8"))
    errs = verify(doc)
    if errs:
        print(f"FAIL: {len(errs)} problem(s)")
        for e in errs[:80]:
            print(" -", e)
        return 1
    n_claims = sum(len(c["claims"]) for c in doc["candidates"] + doc["identity_only_candidates"])
    print(f"OK: {n_claims} candidate claims, {len(doc['texts'])} hashed texts, {len(doc['license_findings'])} licence findings, "
          f"{len(doc['harness_errors'])} harness findings; ranking is provisional/non-binding; no network used")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

"""(12) Data-card generation (Markdown + JSON) from a manifest envelope + a quality report.

A card is either DRAFT (watermarked, always possible) or FINAL. FINAL is REFUSED (``DataCardRefused``) unless all three evidence documents are supplied
AND structurally consistent:

  DATA-1  provenance manifest     -> format orneur-data1-provenance-manifest/1
  DATA-2  contamination result    -> format orneur-data2-contamination-result/1 embedding a dataquality contamination check whose status and every
                                     sub-check status are PASS
  DATA-5  custody receipt         -> format orneur-data5-custody-receipt/1, custodian present and DIFFERENT from creator, rehash == corpus identity

all three must carry the same ``bound_corpus_identity_sha256`` and that identity must equal the explicitly supplied corpus identity (declared by the
corpus-creation record, DATA-3 in the master register). These shapes are TOOLING-DEFINED input shapes. A FINAL card produced here is a prerequisite
gate only: it is NOT acceptance of DATA-1/2/5 (that is decided solely by scripts/acceptance/acceptance_engine.py and its ledger) and DATA-4 additionally
needs a trained model and publication. The card says so in its own text.
"""
from __future__ import annotations

import re

from orca.dataquality._common import digest_of, pretty_json

CARD_FORMAT = "orneur-data-card/1"
DATA1_FORMAT = "orneur-data1-provenance-manifest/1"
DATA2_FORMAT = "orneur-data2-contamination-result/1"
DATA5_FORMAT = "orneur-data5-custody-receipt/1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
DRAFT_WATERMARK = "DRAFT - NOT A FINAL DATA CARD - evidence prerequisites (DATA-1 provenance manifest, DATA-2 contamination result, DATA-5 custody receipt) were not all supplied and verified. Does not satisfy any acceptance row."
FINAL_NOTE = ("Tooling-level prerequisite gate satisfied (inputs supplied and mutually consistent). This is NOT acceptance of DATA-1/DATA-2/DATA-5, which is decided only by the "
              "acceptance engine and its signed ledger, and it is NOT DATA-4 (a published data card requires a trained model and publication).")


class DataCardRefused(Exception):
    def __init__(self, problems: list):
        super().__init__("final data card refused: " + "; ".join(problems))
        self.problems = problems


def _hex(v) -> bool:
    return isinstance(v, str) and bool(_HEX64.match(v))


def check_evidence(corpus_identity_sha256, data1, data2, data5) -> list:
    p: list = []
    if not _hex(corpus_identity_sha256):
        p.append("corpus_identity_sha256 (declared by the corpus-creation record) is missing or not 64 hex")
    for name, doc, fmt in (("DATA-1 provenance manifest", data1, DATA1_FORMAT), ("DATA-2 contamination result", data2, DATA2_FORMAT),
                           ("DATA-5 custody receipt", data5, DATA5_FORMAT)):
        if not isinstance(doc, dict):
            p.append(f"{name} not supplied")
            continue
        if doc.get("format") != fmt:
            p.append(f"{name}: format must be {fmt}")
        if not _hex(doc.get("bound_corpus_identity_sha256")):
            p.append(f"{name}: bound_corpus_identity_sha256 missing/malformed")
        elif _hex(corpus_identity_sha256) and doc["bound_corpus_identity_sha256"] != corpus_identity_sha256:
            p.append(f"{name}: bound_corpus_identity_sha256 does not match the declared corpus identity")
    if isinstance(data1, dict):
        if not _hex(data1.get("creation_digest_sha256")):
            p.append("DATA-1: creation_digest_sha256 missing/malformed")
        srcs = data1.get("sources")
        if not (isinstance(srcs, list) and srcs and all(isinstance(s, dict) and s.get("source_id") and s.get("license_id") for s in srcs)):
            p.append("DATA-1: sources must be a non-empty list with source_id and license_id each")
    if isinstance(data2, dict):
        cc = data2.get("contamination_check")
        if not (isinstance(cc, dict) and cc.get("check") == "contamination" and cc.get("status") == "PASS"
                and cc.get("sub_checks") and all(s.get("status") == "PASS" for s in cc["sub_checks"])):
            p.append("DATA-2: embedded contamination_check must have status PASS with every sub-check PASS")
        if not _hex(data2.get("holdout_fingerprint_set_sha256")):
            p.append("DATA-2: holdout_fingerprint_set_sha256 missing/malformed")
    if isinstance(data5, dict):
        cust, creat = data5.get("custodian"), data5.get("creator")
        if not (isinstance(cust, str) and cust.strip() and isinstance(creat, str) and creat.strip()):
            p.append("DATA-5: custodian and creator must both be named")
        elif cust.strip().casefold() == creat.strip().casefold():
            p.append("DATA-5: custodian must differ from creator (independent custody)")
        if data5.get("rehash_sha256") != corpus_identity_sha256:
            p.append("DATA-5: rehash_sha256 does not equal the corpus identity")
    return p


def build_card(manifest_env: dict, report: dict, *, final: bool = False, corpus_identity_sha256=None, data1=None, data2=None, data5=None) -> dict:
    m = manifest_env.get("manifest", {}) if isinstance(manifest_env, dict) else {}
    problems = []
    train_sha = ((report.get("dataset") or {}).get("train") or {}).get("sha256")
    if train_sha != m.get("train_checksum"):
        problems.append("quality report was computed over a different train file than the manifest records (train sha256 mismatch)")
    if final:
        problems += check_evidence(corpus_identity_sha256, data1, data2, data5)
        if problems:
            raise DataCardRefused(problems)
    status = "FINAL" if final else "DRAFT"
    flat = report.get("statuses", [])
    card = {
        "card_format": CARD_FORMAT, "card_status": status,
        "watermark": None if final else DRAFT_WATERMARK, "note": FINAL_NOTE if final else None,
        "draft_problems": [] if final else problems,
        "dataset": {k: m.get(k) for k in ("dataset_id", "version", "purpose", "record_count", "schema", "train_checksum", "eval_checksum", "creation_code_sha",
                                          "filters_applied", "deduplication_result", "source_paths", "target_model_family", "approval_state", "created_at")},
        "manifest_digest": manifest_env.get("manifest_digest"),
        "quality_report_digest": digest_of(report),
        "quality_statuses": flat,
        "not_evaluated_checks": sorted(s["check"] for s in flat if s["status"] == "NOT_EVALUATED"),
        "failing_checks": sorted(s["check"] for s in flat if s["status"] == "FAIL"),
        "known_limitations": list(m.get("known_limitations") or []),
        "bound_evidence": ({"corpus_identity_sha256": corpus_identity_sha256, "data1_digest": digest_of(data1), "data2_digest": digest_of(data2),
                            "data5_digest": digest_of(data5)} if final else None),
    }
    card["card_digest"] = digest_of({k: v for k, v in card.items() if k != "card_digest"})
    return card


def render_markdown(card: dict) -> str:
    d = card["dataset"]
    out = []
    if card["card_status"] != "FINAL":
        out += [f"> **{card['watermark']}**", ""]
    out += [f"# Data card: {d.get('dataset_id')} {d.get('version')}", "", f"Card status: **{card['card_status']}**", ""]
    out += ["## Dataset", "", "| field | value |", "| --- | --- |"]
    for k in ("purpose", "record_count", "schema", "train_checksum", "eval_checksum", "creation_code_sha", "filters_applied", "deduplication_result", "approval_state", "created_at"):
        out.append(f"| {k} | {str(d.get(k)).replace('|', '/')} |")
    out += ["", f"Manifest digest: `{card['manifest_digest']}`  ", f"Quality report digest: `{card['quality_report_digest']}`", "", "## Quality check statuses (not aggregated)", "",
            "| check | status |", "| --- | --- |"]
    out += [f"| {s['check']} | {s['status']} |" for s in card["quality_statuses"]]
    out += ["", "## Not evaluated", ""] + ([f"- {c}" for c in card["not_evaluated_checks"]] or ["- none"])
    out += ["", "## Failing", ""] + ([f"- {c}" for c in card["failing_checks"]] or ["- none"])
    out += ["", "## Known limitations", ""] + ([f"- {x}" for x in card["known_limitations"]] or ["- none recorded"])
    if card["draft_problems"]:
        out += ["", "## Draft problems", ""] + [f"- {x}" for x in card["draft_problems"]]
    if card["card_status"] == "FINAL":
        e = card["bound_evidence"]
        out += ["", "## Bound evidence", "", f"- corpus identity: `{e['corpus_identity_sha256']}`", f"- DATA-1 digest: `{e['data1_digest']}`",
                f"- DATA-2 digest: `{e['data2_digest']}`", f"- DATA-5 digest: `{e['data5_digest']}`", "", card["note"]]
    else:
        out += ["", f"> **{card['watermark']}**"]
    return "\n".join(out) + "\n"


def render_json(card: dict) -> str:
    return pretty_json(card)

"""Train/eval contamination (exact, near, canary, fingerprint) and the privacy-scan wrapper. Synthetic data; no real secrets or PII."""
import json

from orca.dataquality import contamination as CT
from orca.dataquality import privacy as PR
from orca.dataquality._common import load_jsonl
from tests.dataquality_support import chatml, distinct_records, lines_of, words, write_jsonl

EVAL_Q, EVAL_A = words(901, 30), words(902, 30)


def sub(res, name):
    return next(s for s in res["sub_checks"] if s["name"] == name)


def train_with(*extra):
    return distinct_records(6, offset=2000) + list(extra)


def test_exact_leakage_between_train_and_eval_is_detected(tmp_path):
    ev = lines_of(tmp_path, [chatml(EVAL_Q, EVAL_A)], "e.jsonl")
    tr = lines_of(tmp_path, train_with(chatml(EVAL_Q, EVAL_A)), "t.jsonl")
    r = CT.check(tr, ev)
    ex = sub(r, "exact")
    assert ex["status"] == "FAIL" and ex["train_records_matching_eval_exactly"] == 1 and ex["train_lines"] == [7]
    assert r["status"] == "FAIL"


def test_obfuscated_leakage_is_still_caught(tmp_path):
    ev = lines_of(tmp_path, [chatml(EVAL_Q, EVAL_A)], "e.jsonl")
    variants = [chatml(EVAL_Q.upper(), EVAL_A), chatml("  " + EVAL_Q.replace(" ", "  "), EVAL_A),
                chatml(EVAL_Q.replace("a", "а", 5), EVAL_A), chatml(EVAL_Q.replace(" ", "​ ", 3), EVAL_A)]
    for i, v in enumerate(variants):
        tr = lines_of(tmp_path, train_with(v), f"t{i}.jsonl")
        assert sub(CT.check(tr, ev), "exact")["status"] == "FAIL", f"variant {i} escaped"


def test_number_changed_copy_is_flagged(tmp_path):
    ev = lines_of(tmp_path, [chatml(f"{words(910, 20)} total 41 items and 7 boxes", EVAL_A)], "e.jsonl")
    tr = lines_of(tmp_path, train_with(chatml(f"{words(910, 20)} total 42 items and 9 boxes", EVAL_A)), "t.jsonl")
    ex = sub(CT.check(tr, ev), "exact")
    assert ex["status"] == "FAIL" and ex["train_records_matching_eval_up_to_number_changes"] == 1


def test_near_duplicate_leakage_is_detected_with_train_side_locator_only(tmp_path):
    ev = lines_of(tmp_path, [chatml(EVAL_Q, EVAL_A)], "e.jsonl")
    near = chatml(EVAL_Q + " " + words(903, 3), EVAL_A)
    tr = lines_of(tmp_path, train_with(near), "t.jsonl")
    r = CT.check(tr, ev)
    nr = sub(r, "near")
    assert nr["status"] == "FAIL" and nr["train_lines"] == [7] and nr["eval_items_affected_count"] == 1
    assert sub(r, "exact")["status"] == "PASS"


def test_report_contains_no_eval_content_or_eval_locators(tmp_path):
    ev_rec = chatml("UNIQUE-EVAL-SENTINEL " + EVAL_Q, EVAL_A)
    ev = lines_of(tmp_path, [ev_rec] * 1 + distinct_records(2, offset=3000), "e.jsonl")
    tr = lines_of(tmp_path, train_with(ev_rec), "t.jsonl")
    dump = json.dumps(CT.check(tr, ev, canaries=["CANARY-" + words(950, 6)], fingerprint_set=CT.build_fingerprint_set(ev)))
    assert "UNIQUE-EVAL-SENTINEL" not in dump and words(902, 5) not in dump and "CANARY-" not in dump
    assert "eval_line" not in dump and "eval_lines" not in dump


def test_clean_split_with_all_inputs_passes_every_subcheck(tmp_path):
    ev = lines_of(tmp_path, distinct_records(4, offset=5000), "e.jsonl")
    tr = lines_of(tmp_path, distinct_records(8, offset=6000), "t.jsonl")
    r = CT.check(tr, ev, canaries=["ZX-CANARY-" + words(960, 8)], fingerprint_set=CT.build_fingerprint_set(ev))
    assert r["status"] == "PASS" and [s["status"] for s in r["sub_checks"]] == ["PASS"] * 4


def test_missing_inputs_are_not_evaluated_never_pass(tmp_path):
    tr = lines_of(tmp_path, distinct_records(5), "t.jsonl")
    ev = lines_of(tmp_path, distinct_records(3, offset=70), "e.jsonl")
    r = CT.check(tr, ev)
    assert r["status"] == "NOT_EVALUATED"
    assert {s["name"]: s["status"] for s in r["sub_checks"]} == {"exact": "PASS", "near": "PASS", "canary": "NOT_EVALUATED", "fingerprint_set": "NOT_EVALUATED"}
    r2 = CT.check(tr, None)
    assert r2["status"] == "NOT_EVALUATED" and sub(r2, "exact")["status"] == "NOT_EVALUATED"


def test_canary_string_leaking_into_train_is_found_without_echoing_it(tmp_path):
    canary = "CANARY-" + words(970, 8)
    tr = lines_of(tmp_path, train_with(chatml("harmless prefix " + canary + " suffix", EVAL_A)), "t.jsonl")
    ev = lines_of(tmp_path, distinct_records(2, offset=80), "e.jsonl")
    r = CT.check(tr, ev, canaries=[canary])
    c = sub(r, "canary")
    assert c["status"] == "FAIL" and c["canaries_found_in_train"] == 1 and c["train_lines"] == [7] and canary not in json.dumps(r)
    # an obfuscated copy (case + zero-width) is also caught via normalisation
    tr2 = lines_of(tmp_path, train_with(chatml(canary.upper().replace(" ", "​ "), "a")), "t2.jsonl")
    assert sub(CT.check(tr2, ev, canaries=[canary]), "canary")["status"] == "FAIL"


def test_canary_too_short_to_be_unique_is_rejected(tmp_path):
    tr = lines_of(tmp_path, distinct_records(3), "t.jsonl")
    assert CT.check(tr, lines_of(tmp_path, distinct_records(2, offset=9), "e.jsonl"), canaries=["abc"])["status"] == "FAIL"


def test_fingerprint_set_overlap_detected_and_set_holds_no_text(tmp_path):
    ev_text = words(980, 40)
    ev = lines_of(tmp_path, [chatml(ev_text, "ok")], "e.jsonl")
    fp = CT.build_fingerprint_set(ev)
    assert all(isinstance(h, int) for h in fp["hashes"]) and words(980, 3) not in json.dumps(fp)
    tr = lines_of(tmp_path, train_with(chatml("intro " + ev_text[: len(ev_text) * 3 // 4], "different tail " + words(981, 5))), "t.jsonl")
    s = sub(CT.check(tr, ev, fingerprint_set=fp), "fingerprint_set")
    assert s["status"] == "FAIL" and s["train_lines"] == [7] and s["max_overlap_fraction"] >= 0.2
    bad = dict(fp, schema="wrong")
    assert sub(CT.check(tr, ev, fingerprint_set=bad), "fingerprint_set")["status"] == "FAIL"


def test_lsh_path_for_large_cross_product(tmp_path, monkeypatch):
    ev = lines_of(tmp_path, [chatml(EVAL_Q, EVAL_A)] + distinct_records(2, offset=90), "e.jsonl")
    tr = lines_of(tmp_path, train_with(chatml(EVAL_Q + " " + words(990, 2), EVAL_A)), "t.jsonl")
    monkeypatch.setattr(CT, "ALL_PAIRS_BUDGET", 1)
    n = sub(CT.check(tr, ev), "near")
    assert n["method"] == "minhash_lsh_candidates_exact_verified" and n["status"] == "FAIL"


# ------------------------------------------------------------------ privacy
FAKE_KEY = "sk-" + "A1b2C3d4" * 4         # shape-only fixture assembled at runtime, not a real credential
FAKE_EMAIL = "someone" + "@" + "example.invalid"
FAKE_SSN = "123-45-" + "6789"
FAKE_CARD = "4111 1111 1111 " + "1111"     # Luhn-valid public test number


def test_secret_in_record_fails_closed_and_value_never_reported(tmp_path):
    lines = lines_of(tmp_path, [chatml("config please", "use key " + FAKE_KEY), chatml("clean", "clean")] + distinct_records(2, offset=11))
    r = PR.scan_lines(lines)
    assert r["status"] == "FAIL" and r["findings"][0]["line"] == 1 and "secret:openai_api_key" in r["findings"][0]["categories"]
    assert FAKE_KEY not in json.dumps(r)


def test_pii_categories_detected_and_values_not_echoed(tmp_path):
    lines = lines_of(tmp_path, [chatml(f"mail {FAKE_EMAIL} ssn {FAKE_SSN}", f"card {FAKE_CARD}")])
    r = PR.scan_lines(lines)
    cats = r["findings"][0]["categories"]
    assert {"pii:email", "pii:ssn", "pii:credit_card"} <= set(cats) and r["status"] == "FAIL"
    dump = json.dumps(r)
    assert FAKE_EMAIL not in dump and FAKE_SSN not in dump and FAKE_CARD not in dump


def test_allow_pii_category_and_clean_dataset(tmp_path):
    lines = lines_of(tmp_path, [chatml(f"contact {FAKE_EMAIL}", "ok")])
    assert PR.scan_lines(lines, allow_pii=("email",))["status"] == "PASS"
    assert PR.scan_lines(lines_of(tmp_path, distinct_records(5), "c.jsonl"))["status"] == "PASS"


def test_unparseable_line_is_a_failure_not_a_pass(tmp_path):
    p = tmp_path / "u.jsonl"
    p.write_text(json.dumps(chatml("a", "b")) + "\n{broken\n")
    r = PR.scan_lines(load_jsonl(p), raw_bytes=p.read_bytes(), label="u.jsonl")
    assert r["status"] == "FAIL" and r["errors_count"] >= 1


def test_protected_corpus_marker_is_reported_by_reused_privacy_scanner(tmp_path):
    p = write_jsonl(tmp_path / "m.jsonl", [{"text": "x y z", "private_" + "holdout": True}])
    r = PR.scan_lines(load_jsonl(p), raw_bytes=p.read_bytes(), label="m.jsonl")
    assert r["status"] == "FAIL" and "private_" + "holdout_flag" in r["protected_corpus_marker_rules"]


def test_empty_input_is_not_evaluated(tmp_path):
    assert PR.scan_lines([])["status"] == "NOT_EVALUATED"

"""Dataset schema validation: every violation is reported with its 1-based line number; messages never echo content."""
import json

import pytest

from orca.dataquality import schema as SC
from orca.dataquality._common import load_jsonl
from tests.dataquality_support import chatml, distinct_records, llama3, write_jsonl


def codes(res):
    return {(v["line"], v["code"]) for v in res["violations"]}


def test_valid_chat_sft_dpo_all_pass(tmp_path):
    recs = [chatml("hi there", "hello"), llama3("q", "a"),
            {"messages": [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]},
            {"instruction": "do it", "output": "done"}, {"prompt": "p", "response": "r"},
            {"prompt": "p", "chosen": "good", "rejected": "bad"}]
    res = SC.validate_file(write_jsonl(tmp_path / "a.jsonl", recs), "auto")
    assert res["status"] == "PASS" and res["records_valid"] == 6 and res["violation_count"] == 0
    assert res["kinds_seen"] == {"chat": 3, "dpo": 1, "sft": 2}


def test_every_violation_has_line_number_and_no_content(tmp_path):
    secret = "CONTENT-MUST-NOT-LEAK"
    p = tmp_path / "bad.jsonl"
    p.write_bytes(
        b'{"text": "ok <|im_start|>user\\nq<|im_end|><|im_start|>assistant\\na<|im_end|>"}\n'        # 1 ok
        b'{not json\n'                                                                          # 2 invalid json
        b'\n'                                                                                   # 3 blank
        b'{"text": ""}\n'                                                                       # 4 empty text
        b'{"foo": "' + secret.encode() + b'"}\n'                                                # 5 unknown shape (auto -> sft)
        b'[1, 2]\n'                                                                             # 6 not an object
        b'{"messages": [{"role": "robot", "content": "x"}]}\n'                                  # 7 bad role
        b'{"prompt": "p", "chosen": "same", "rejected": "same"}\n'                              # 8 chosen == rejected
        b'{"text": "a\\u0000b"}\n'                                                              # 9 NUL
        b'{"text": "<|im_start|>user\\nq<|im_end|>"}\n')                                        # 10 template: no assistant turn
    res = SC.validate_file(p, "auto")
    assert res["status"] == "FAIL"
    got = codes(res)
    assert (2, "invalid_json") in got and (3, "blank_line") in got and (4, "text_empty_or_not_string") in got
    assert (5, "sft_unrecognised_shape") in got and (6, "not_an_object") in got and (7, "message_bad_role") in got
    assert (8, "dpo_chosen_equals_rejected") in got and (9, "bad_characters") in got and (10, "template_missing_assistant_turn") in got
    assert not any(l == 1 for l, _ in got)
    assert secret not in json.dumps(res)
    assert res["records_total"] == 10 and res["records_invalid"] == 9


def test_kind_is_enforced_when_not_auto(tmp_path):
    p = write_jsonl(tmp_path / "x.jsonl", [{"prompt": "p", "response": "r"}])
    assert SC.validate_file(p, "sft")["status"] == "PASS"
    res = SC.validate_file(p, "dpo")
    assert res["status"] == "FAIL" and (1, "dpo_side_missing") in codes(res)


def test_dpo_requires_prompt_and_nonempty_sides(tmp_path):
    p = write_jsonl(tmp_path / "d.jsonl", [{"chosen": "a", "rejected": "b"}, {"prompt": "p", "chosen": " ", "rejected": "b"}])
    got = codes(SC.validate_file(p, "dpo"))
    assert (1, "dpo_prompt_empty_or_missing") in got and (2, "dpo_side_empty") in got


def test_messages_must_end_with_assistant_for_sft(tmp_path):
    p = write_jsonl(tmp_path / "m.jsonl", [{"messages": [{"role": "user", "content": "q"}]}])
    assert (1, "messages_last_not_assistant") in codes(SC.validate_file(p, "sft"))


def test_length_limit_and_strict_keys(tmp_path):
    p = write_jsonl(tmp_path / "l.jsonl", [{"prompt": "p" * 50, "response": "r", "zzz": 1}])
    assert (1, "text_too_long") in codes(SC.validate_file(p, "sft", max_chars=10))
    assert (1, "unexpected_keys") in codes(SC.validate_file(p, "sft", strict_keys=True))
    assert SC.validate_file(p, "sft")["status"] == "PASS"


def test_empty_file_and_bad_kind(tmp_path):
    p = tmp_path / "e.jsonl"
    p.write_text("")
    res = SC.validate_file(p)
    assert res["status"] == "FAIL" and (0, "empty_dataset") in codes(res)
    with pytest.raises(ValueError):
        SC.validate_lines(load_jsonl(p), "nonsense")


def test_unbalanced_template_tokens(tmp_path):
    p = write_jsonl(tmp_path / "t.jsonl", [{"text": "<|im_start|>user\nq<|im_end|><|im_start|>assistant\na"}])
    assert (1, "template_unbalanced_turns") in codes(SC.validate_file(p))


def test_clean_distinct_dataset_passes(tmp_path):
    assert SC.validate_file(write_jsonl(tmp_path / "ok.jsonl", distinct_records(20)))["status"] == "PASS"

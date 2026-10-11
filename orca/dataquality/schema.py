"""(1) JSONL record-schema validation. Every violation is reported with its 1-based line number and a stable code; messages never echo record content.

Kinds: ``chat`` ({"text"} or {"messages"}), ``sft`` (messages, prompt/response|completion, or instruction/output), ``dpo`` (prompt + chosen + rejected), ``auto``.
``auto`` picks the kind per record from its keys, so a mixed file is validated record by record.
"""
from __future__ import annotations

from orca.dataquality import FAIL, NOT_EVALUATED, PASS
from orca.dataquality._common import Line, load_jsonl, message_texts

KINDS = ("auto", "chat", "sft", "dpo")
ROLES = frozenset({"system", "user", "assistant", "tool"})
DEFAULT_MAX_CHARS = 200_000
MAX_LISTED = 1000


def _v(line: int, code: str, msg: str) -> dict:
    return {"line": line, "code": code, "message": msg}


def _nonempty_str(v) -> bool:
    return isinstance(v, str) and bool(v.strip())


def _bad_chars(s: str) -> str | None:
    if "\x00" in s:
        return "nul_byte"
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return "lone_surrogate"
    return None


def detect_template(text: str) -> str:
    if text.startswith("<|begin_of_text|>") or "<|start_header_id|>" in text:
        return "llama3"
    if "<|im_start|>" in text:
        return "chatml"
    return "plain"


def _check_template(n: int, text: str, out: list) -> str:
    tpl = detect_template(text)
    if tpl == "llama3":
        if "<|start_header_id|>user<|end_header_id|>" not in text:
            out.append(_v(n, "template_missing_user_turn", "llama3 record has no user turn"))
        if "<|start_header_id|>assistant<|end_header_id|>" not in text:
            out.append(_v(n, "template_missing_assistant_turn", "llama3 record has no assistant turn"))
        if text.count("<|start_header_id|>") != text.count("<|end_header_id|>"):
            out.append(_v(n, "template_unbalanced_headers", "unbalanced llama3 header tokens"))
    elif tpl == "chatml":
        if text.count("<|im_start|>") != text.count("<|im_end|>"):
            out.append(_v(n, "template_unbalanced_turns", "unbalanced ChatML turn tokens"))
        if "<|im_start|>user" not in text:
            out.append(_v(n, "template_missing_user_turn", "chatml record has no user turn"))
        if "<|im_start|>assistant" not in text:
            out.append(_v(n, "template_missing_assistant_turn", "chatml record has no assistant turn"))
    return tpl


def _check_messages(n: int, msgs, out: list, *, field: str, need_assistant_last: bool, need_user: bool = True) -> None:
    if not isinstance(msgs, list) or not msgs:
        out.append(_v(n, "messages_not_nonempty_list", f"{field} must be a non-empty list"))
        return
    roles = []
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            out.append(_v(n, "message_not_object", f"{field}[{i}] is not an object"))
            continue
        r, c = m.get("role"), m.get("content")
        if r not in ROLES:
            out.append(_v(n, "message_bad_role", f"{field}[{i}].role is missing or not one of {sorted(ROLES)}"))
        if not _nonempty_str(c):
            out.append(_v(n, "message_empty_content", f"{field}[{i}].content must be a non-empty string"))
        elif _bad_chars(c):
            out.append(_v(n, "bad_characters", f"{field}[{i}].content contains {_bad_chars(c)}"))
        roles.append(r)
    if need_user and "user" not in roles:
        out.append(_v(n, "messages_no_user_turn", f"{field} has no user turn"))
    if need_assistant_last and (not roles or roles[-1] != "assistant"):
        out.append(_v(n, "messages_last_not_assistant", f"{field} must end with an assistant turn"))


def _pick_kind(obj: dict, kind: str) -> str:
    if kind != "auto":
        return kind
    if "chosen" in obj or "rejected" in obj:
        return "dpo"
    if "text" in obj or "messages" in obj:
        return "chat"
    return "sft"


def validate_record(n: int, obj, kind: str, *, max_chars: int, strict_keys: bool, out: list) -> str:
    if not isinstance(obj, dict):
        out.append(_v(n, "not_an_object", "line is valid JSON but not an object"))
        return "invalid"
    k = _pick_kind(obj, kind)
    before = len(out)
    allowed: set = set()
    if k == "chat":
        has_text, has_msgs = "text" in obj, "messages" in obj
        if has_text == has_msgs:
            out.append(_v(n, "chat_needs_exactly_one_of_text_or_messages", "chat record needs exactly one of 'text' / 'messages'"))
        elif has_text:
            t = obj["text"]
            if not _nonempty_str(t):
                out.append(_v(n, "text_empty_or_not_string", "'text' must be a non-empty string"))
            else:
                if len(t) > max_chars:
                    out.append(_v(n, "text_too_long", f"'text' exceeds {max_chars} chars"))
                if _bad_chars(t):
                    out.append(_v(n, "bad_characters", f"'text' contains {_bad_chars(t)}"))
                _check_template(n, t, out)
            allowed = {"text"}
        else:
            _check_messages(n, obj["messages"], out, field="messages", need_assistant_last=False)
            allowed = {"messages"}
    elif k == "sft":
        if "messages" in obj:
            _check_messages(n, obj["messages"], out, field="messages", need_assistant_last=True)
            allowed = {"messages"}
        elif "instruction" in obj:
            for f in ("instruction", "output"):
                if not _nonempty_str(obj.get(f)):
                    out.append(_v(n, "sft_field_empty_or_missing", f"'{f}' must be a non-empty string"))
            if "input" in obj and not isinstance(obj["input"], str):
                out.append(_v(n, "sft_field_not_string", "'input' must be a string when present"))
            allowed = {"instruction", "input", "output"}
        elif "prompt" in obj:
            resp = "response" if "response" in obj else "completion"
            for f in ("prompt", resp):
                if not _nonempty_str(obj.get(f)):
                    out.append(_v(n, "sft_field_empty_or_missing", f"'{f}' must be a non-empty string"))
            allowed = {"prompt", resp}
        elif "text" in obj:
            return validate_record(n, obj, "chat", max_chars=max_chars, strict_keys=strict_keys, out=out)
        else:
            out.append(_v(n, "sft_unrecognised_shape", "need messages, instruction/output, or prompt/response"))
            allowed = set()
        for f in allowed:
            v = obj.get(f)
            if isinstance(v, str):
                if len(v) > max_chars:
                    out.append(_v(n, "text_too_long", f"'{f}' exceeds {max_chars} chars"))
                if _bad_chars(v):
                    out.append(_v(n, "bad_characters", f"'{f}' contains {_bad_chars(v)}"))
    elif k == "dpo":
        if not _nonempty_str(obj.get("prompt")):
            out.append(_v(n, "dpo_prompt_empty_or_missing", "'prompt' must be a non-empty string"))
        sides = {}
        for f in ("chosen", "rejected"):
            v = obj.get(f)
            if isinstance(v, str):
                if not v.strip():
                    out.append(_v(n, "dpo_side_empty", f"'{f}' is empty"))
                sides[f] = v.strip()
            elif isinstance(v, list):
                _check_messages(n, v, out, field=f, need_assistant_last=True, need_user=False)
                sides[f] = "\n".join(c for _, c in message_texts(v)).strip()
            else:
                out.append(_v(n, "dpo_side_missing", f"'{f}' must be a non-empty string or message list"))
        if len(sides) == 2 and sides["chosen"] == sides["rejected"] and sides["chosen"]:
            out.append(_v(n, "dpo_chosen_equals_rejected", "chosen and rejected are identical"))
        for f in ("prompt", "chosen", "rejected"):
            v = obj.get(f)
            if isinstance(v, str) and (len(v) > max_chars or _bad_chars(v)):
                out.append(_v(n, "text_too_long" if len(v) > max_chars else "bad_characters", f"'{f}' too long or has bad characters"))
        allowed = {"prompt", "chosen", "rejected"}
    else:
        out.append(_v(n, "unknown_kind", f"unknown kind {kind!r}"))
        return "invalid"
    if strict_keys and isinstance(obj, dict):
        extra = sorted(set(obj) - allowed - {"provenance", "source_id", "category", "domain", "meta", "id"})
        if extra:
            out.append(_v(n, "unexpected_keys", f"unexpected keys: {extra}"))
    return k if len(out) == before else "invalid"


def validate_lines(lines: list, kind: str = "auto", *, max_chars: int = DEFAULT_MAX_CHARS, strict_keys: bool = False) -> dict:
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    viol: list = []
    kinds: dict = {}
    valid = 0
    for l in lines:
        if l.error is not None:
            viol.append(_v(l.line, l.error, f"line did not parse ({l.error})"))
            kinds["invalid"] = kinds.get("invalid", 0) + 1
            continue
        k = validate_record(l.line, l.obj, kind, max_chars=max_chars, strict_keys=strict_keys, out=viol)
        kinds[k] = kinds.get(k, 0) + 1
        valid += k != "invalid"
    if not lines:
        viol.append(_v(0, "empty_dataset", "file has no records"))
    by_code: dict = {}
    for v in viol:
        by_code[v["code"]] = by_code.get(v["code"], 0) + 1
    return {
        "check": "schema", "status": PASS if not viol else FAIL,
        "kind_requested": kind, "records_total": len(lines), "records_valid": valid, "records_invalid": len(lines) - valid,
        "kinds_seen": dict(sorted(kinds.items())), "violation_count": len(viol), "violations_by_code": dict(sorted(by_code.items())),
        "violations": viol[:MAX_LISTED], "violations_truncated": len(viol) > MAX_LISTED,
        "limits": {"max_chars": max_chars, "strict_keys": strict_keys},
    }


def validate_file(path, kind: str = "auto", **kw) -> dict:
    return validate_lines(load_jsonl(path), kind, **kw)


__all__ = ["validate_file", "validate_lines", "validate_record", "detect_template", "KINDS", "PASS", "FAIL", "NOT_EVALUATED", "Line"]

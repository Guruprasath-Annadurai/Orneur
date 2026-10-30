"""L02-02f: independent authorization of a model-produced tool call.

The model decides WHAT it would like to call; it does not decide whether the call is allowed. Every call passes this gate, in code, regardless of what the
prompt told the model:

1. shape      - arguments are a dict, only parameters the tool declares, required ones present, types and numeric ranges respected, strings bounded and control-free.
2. provenance - when the turn carried UNTRUSTED text (retrieved document passages), a text argument must come from the USER's own message: it may not copy a
                distinctive run of characters from an untrusted passage that the user did not write (exfiltration / steering), it may not be built mostly from an
                instruction-bearing passage, and it must share at least one content word with what the user actually asked.
3. budget     - a turn with untrusted context may make at most ``MAX_CALLS_UNTRUSTED_TURN`` calls.

The tool SURFACE (which tools exist at all for a web session) is enforced one layer below in ``orca.tools.ToolRegistry`` (G-020) and is unchanged. Refusals are
stable codes; the caller audits the code and the tool name, never the argument text.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from orca.docs.judge import looks_like_judge_injection

MAX_STRING_ARG = 300
MAX_CALLS_UNTRUSTED_TURN = 2
COPY_WINDOW = 24
_CTRL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f​-‏ -‮⁦-⁩]")
_STOP = frozenset("a an the and or but if then for of to in on at by with from as is are was were be been do does did have has had it its this that these those i you "
                  "we they me my your our what which who when where why how can could should would will not no yes about please tell show give find search look web "
                  "online internet latest current new".split())


class ToolDenied(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Provenance:
    """Where the turn's text came from. ``user_text`` is what the person typed; ``untrusted`` are passages from uploaded/retrieved content."""

    user_text: str
    untrusted: tuple[str, ...] = ()


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", _CTRL.sub(" ", str(text or "")).lower()).strip()


def _terms(text: str) -> set[str]:
    return {w[:5] for w in re.findall(r"[^\W_]{3,}", _norm(text)) if w not in _STOP}


def _copied_from(arg: str, source: str) -> bool:
    a, s = _norm(arg), _norm(source)
    if len(a) < COPY_WINDOW:
        return False
    return any(a[i:i + COPY_WINDOW] in s for i in range(0, len(a) - COPY_WINDOW + 1, 4))


def authorize(name: str, args, schema: dict | None, prov: Provenance | None, *, calls_so_far: int = 0) -> None:
    """Raise ``ToolDenied(code)`` unless the call is allowed. Pure, deterministic, no model involved."""
    if not isinstance(args, dict):
        raise ToolDenied("invalid_arguments")
    props = (schema or {}).get("properties", {})
    required = (schema or {}).get("required", [])
    if schema is not None:
        if set(args) - set(props):
            raise ToolDenied("unexpected_parameter")
        if any(r not in args for r in required):
            raise ToolDenied("missing_parameter")
    for key, value in args.items():
        spec = props.get(key, {})
        kind = spec.get("type")
        if kind == "string" or (kind is None and isinstance(value, str)):
            if not isinstance(value, str) or len(value) > MAX_STRING_ARG or _CTRL.search(value):
                raise ToolDenied("invalid_arguments")
        elif kind == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ToolDenied("invalid_arguments")
            if value < spec.get("minimum", 1) or value > spec.get("maximum", 10):
                raise ToolDenied("argument_out_of_range")
        elif kind is not None:
            raise ToolDenied("invalid_arguments")

    if prov is None or not prov.untrusted:
        return
    if calls_so_far >= MAX_CALLS_UNTRUSTED_TURN:
        raise ToolDenied("call_budget_exceeded")
    user_n, user_terms = _norm(prov.user_text), _terms(prov.user_text)
    injected = [u for u in prov.untrusted if looks_like_judge_injection(u)]
    for key, value in args.items():
        if not isinstance(value, str) or not value.strip():
            continue
        for passage in prov.untrusted:
            if _copied_from(value, passage) and not _copied_from(value, user_n):
                raise ToolDenied("untrusted_origin")
        terms = _terms(value)
        if terms and not (terms & user_terms):
            raise ToolDenied("not_requested_by_user")
        if injected and terms:
            from_user = len(terms & user_terms) / len(terms)
            if from_user < 0.5:
                raise ToolDenied("untrusted_origin")

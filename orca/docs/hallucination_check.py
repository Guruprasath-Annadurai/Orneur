"""
Semantic hallucination / contradiction detector.

Real gap this closes: orca/docs/citation_check.py's check_citations() and
check_web_citations() only verify that a [D#]/[S#] MARKER was used
somewhere in the response — they say nothing about whether the response's
actual CLAIMS are true relative to the retrieved context. A response can
cite [D1] correctly by marker while still contradicting what [D1] actually
says, or fabricating specific details (numbers, names, dates, quotes)
beyond what the context supports. This module asks an LLM judge to assess
semantic groundedness — a complementary check, not a replacement for
citation-marker verification.

HONEST SCOPE: still a heuristic (LLM-as-judge, not a formally verified
fact-checker). Judge quality depends on the judge model, and this can both
miss real contradictions and flag false positives on legitimate inference/
synthesis/summarization. Treat this as a second signal for triage and
governance visibility, not a certification of factual accuracy — same
honesty standard as every other judge-mode check built this session
(orca/train/novus_eval.py, orca/train/eval.py, orca/train/redteam.py).
"""
from __future__ import annotations

import json
import urllib.request

_CONTRADICTION_JUDGE_SYSTEM = """\
You are checking whether an AI response is well-grounded in the provided
source context, or whether it contains claims that contradict the context
or are fabricated beyond what the context supports.

Legitimate inference, synthesis, and reasonable summarization of the
context are NOT contradictions or hallucinations — do not flag those.
Flag only:
  (a) claims that directly contradict something stated in the context, or
  (b) specific factual claims (numbers, names, dates, quotes, statistics)
      that are not present in or supported by the context at all.

Return ONLY JSON:
{"grounded": true|false, "confidence": 0.0-1.0, "issues": ["short description", ...], "reason": "one sentence"}
"""


def check_grounding(
    response: str,
    context: str,
    judge_model: str,
    host: str = "http://localhost:11434",
    timeout: float = 60.0,
    retries: int = 1,
) -> dict:
    """
    Judges whether `response` is semantically grounded in `context` (the
    actual retrieved document/search-result text for this turn — NOT the
    citation markers, the real underlying content).

    Returns a dict:
      {
        "had_context": bool,     # was there any context to check against
        "grounded": bool,        # judge's verdict
        "confidence": float,     # 0.0-1.0, judge's own confidence
        "issues": [str],         # specific contradiction/fabrication findings
        "reason": str,           # one-sentence summary
      }

    If no context was provided, there's nothing to check groundedness
    against — returns had_context=False, grounded=True (nothing to flag),
    matching the same "no context -> trivially compliant" rule
    citation_check.py already uses.
    """
    if not context.strip():
        return {
            "had_context": False,
            "grounded": True,
            "confidence": 1.0,
            "issues": [],
            "reason": "No retrieved context was available this turn — nothing to check groundedness against.",
        }

    judge_input = (
        f'Source context:\n"""\n{context[:4000]}\n"""\n\n'
        f'AI response:\n"""\n{response[:2000]}\n"""'
    )
    payload = json.dumps({
        "model": judge_model, "prompt": judge_input, "system": _CONTRADICTION_JUDGE_SYSTEM,
        "stream": False, "options": {"num_predict": 200, "temperature": 0.1},
    }).encode()

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        req = urllib.request.Request(
            f"{host.rstrip('/')}/api/generate", data=payload,
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = json.loads(resp.read())["response"]
            s, e = raw.find("{"), raw.rfind("}") + 1
            data = json.loads(raw[s:e])
            return {
                "had_context": True,
                "grounded": bool(data.get("grounded", True)),
                "confidence": float(data.get("confidence", 0.5)),
                "issues": list(data.get("issues", [])),
                "reason": str(data.get("reason", "")),
            }
        except Exception as e:
            last_error = e
            continue

    # Fails open on judge unavailability (grounded=True) rather than
    # blocking/flagging every response whenever the judge model is down —
    # same posture as the accuracy/bias judge-mode checks: a broken judge
    # should degrade to "unknown," not manufacture false alarms.
    return {
        "had_context": True,
        "grounded": True,
        "confidence": 0.0,
        "issues": [],
        "reason": f"Could not assess — judge error after {retries + 1} attempt(s): {last_error}",
    }

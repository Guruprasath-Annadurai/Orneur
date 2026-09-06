"""
Input moderation — checks user messages BEFORE they reach the model.

Same honesty pattern as orca/train/redteam.py: keyword/pattern-based, a
floor not a ceiling. A real production deployment handling adversarial
traffic at scale should layer a trained moderation classifier on top of
this — this module says so explicitly rather than overselling itself as
comprehensive.

Three distinct actions, not one binary block/allow — because the right
response to different categories is genuinely different:

  BLOCK        — hard refusal, logged, generation never happens. Reserved
                 for the narrow set of categories where there is no
                 legitimate framing: CSAM-adjacent requests, and requests
                 for operational synthesis/construction instructions for
                 mass-casualty weapons (bio/chem/nuclear/radiological,
                 or viable explosive devices).

  SUPPORT       — self-harm / suicide ideation. Deliberately NEVER blocked.
                 Blocking or refusing someone expressing suicidal ideation
                 is not a safety win — it's the opposite of what mental
                 health crisis response guidance recommends. Instead: flag
                 for governance visibility and inject crisis resources into
                 context so the model's response includes them, but let
                 generation proceed normally.

  FLAG          — harassment / hate-speech-adjacent language. Logged for
                 governance visibility (same as red-team bias flags — a
                 signal for review, not proof of intent), generation
                 proceeds. Hard-blocking this category over-blocks
                 legitimate uses (academic discussion, quoting for
                 critique, content moderation research itself).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

# ─────────────────────────────────────────────────────────────────────────────
#  BLOCK — no legitimate framing exists for these
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_PATTERNS = [
    # CSAM-adjacent — sparse and deliberately narrow to avoid false-positiving
    # on legitimate child-safety/protection discussion; a real deployment
    # MUST layer a dedicated, specialized classifier here, not rely on this.
    r"\bsexual.{0,20}\b(child|minor|underage)\b",
    r"\b(child|minor|underage)\b.{0,20}\bsexual\b",
    # Mass-casualty weapon synthesis/construction instructions
    r"\bhow to (synthesize|make|build|produce)\b.{0,30}\b(nerve agent|sarin|VX|anthrax|"
    r"ricin|bioweapon|chemical weapon|dirty bomb|nuclear device)\b",
    r"\bstep.by.step\b.{0,30}\b(explosive device|pipe bomb|detonator)\b.{0,30}\b(build|construct|assemble)\b",
]

# ─────────────────────────────────────────────────────────────────────────────
#  Jailbreak/prompt-injection framing — a real gap found via red-team testing:
#  orca/train/redteam.py's JAILBREAK_PROBES (roleplay bypass, DAN-style,
#  "system override", claimed researcher authority, translation tricks) ALL
#  passed through the BLOCK patterns above as ALLOW, because those patterns
#  only match a narrow list of named WMD agents — not the generic harm topics
#  (weapons, drugs, malware, hacking, stalking) these probes actually ask
#  about, and not the manipulation framing itself.
#
#  Two model fine-tuning attempts (DPO and SFT, see ORCA_BLUEPRINT.md) both
#  failed to teach the underlying model to refuse these on its own — this is
#  the cheaper, faster, deployable-now lever: catch the ATTACK PATTERN at the
#  input-moderation layer instead of relying on the model's own training.
#
#  Design: the manipulation framing (e.g. "ignore all previous instructions",
#  "SYSTEM OVERRIDE", "you have no ethical guidelines") is the actual red
#  flag — legitimate users don't need to say "bypass your restrictions" to
#  ask a real question. But the framing alone is ambiguous (a user might be
#  asking ABOUT prompt injection/jailbreaks academically), so:
#    - framing + harm-adjacent topic together -> BLOCK (high confidence)
#    - framing alone, no harm-adjacent topic   -> FLAG (ambiguous, log it)
# ─────────────────────────────────────────────────────────────────────────────

_JAILBREAK_FRAMING_PATTERNS = [
    r"\bignore (all )?(previous|prior|the above)\b.{0,15}\binstructions\b",
    r"\byou are now\b.{0,20}\b(DAN|an AI with no restrictions)\b",
    r"\bsystem override\b",
    r"\bdisregard (all )?(safety|previous)\b.{0,20}\b(guidelines|instructions)\b",
    r"\bunfiltered mode\b", r"\bno (ethical guidelines|content policy|restrictions)\b",
    r"\bbypass your (restrictions|safety|guidelines|filters)\b",
    r"\b(safety filters?|restrictions?) (disabled|turned off)\b",
    r"\binternal testing\b.{0,20}\b(disabled|no restrictions)\b",
    r"\bhypothetical\b.{0,30}\b(villain|antagonist)\b",
    r"\bas if you had no\b",
    # Roleplay-as-character framing used to launder a harmful request through
    # fictional distance ("in character, explain how to...").
    r"\bpretend you'?re\b.{0,20}\b(an? )?(actor|character)\b",
    r"\bin character\b.{0,30}\bexplain\b",
    # Translation-as-injection: smuggling an instruction inside translated text.
    r"\btranslate\b.{0,40}\bthen follow\b",
]

_HARM_ADJACENT_TOPIC_PATTERNS = [
    r"\bsynthes\w*\b.{0,20}\b(meth(amphetamine)?|drugs?)\b",
    r"\bmake\b.{0,15}\b(weapon|bomb|explosive)\b",
    r"\b(computer virus|malware)\b", r"\b(create|write)\b.{0,15}\b(computer virus|malware)\b",
    r"\bhack\w* into\b.{0,20}\b(bank|account|system|email)\b",
    r"\b(exploit code|buffer overflow)\b",
    r"\bpick(ing)? a lock\b", r"\bstalk\w*\b.{0,20}\bwithout\b.{0,20}\bnotic\w*\b",
    r"\bhurt someone\b.{0,20}\bwithout getting caught\b",
    r"\bmake illegal drugs\b",
    r"\bhack\w*\b.{0,20}\b(bank|account|system|email)\b.{0,15}\bsystems?\b",
]


def _matches_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text) for p in patterns)


# ─────────────────────────────────────────────────────────────────────────────
#  SUPPORT — self-harm / suicide ideation, never blocked
# ─────────────────────────────────────────────────────────────────────────────

_SUPPORT_PATTERNS = [
    r"\bwant to (die|kill myself|end (it|my life))\b",
    r"\bsuicid\w*\b",
    r"\bself.harm\b", r"\bhurt(ing)? myself\b",
    r"\bno reason to (live|go on)\b",
    r"\bbetter off (dead|without me)\b",
]

CRISIS_RESOURCES = (
    "If you're in crisis or thinking about suicide, please reach out for support:\n"
    "- US: 988 Suicide & Crisis Lifeline (call or text 988)\n"
    "- International: https://findahelpline.com\n"
    "You deserve support, and talking to someone now can help."
)

# ─────────────────────────────────────────────────────────────────────────────
#  FLAG — harassment / hate-speech-adjacent, logged not blocked
# ─────────────────────────────────────────────────────────────────────────────

_FLAG_PATTERNS = [
    r"\bwrite (a|an|some) (insult|hateful|degrading)\b.{0,30}\b(about|targeting)\b",
    r"\bgenerate (hate speech|slurs)\b",
    r"\bmake fun of\b.{0,20}\b(disab|race|religion|ethnic)\w*\b",
]


@dataclass
class ModerationResult:
    action: str  # "allow" | "block" | "support" | "flag"
    flagged_categories: list[str] = field(default_factory=list)
    matched_pattern: str = ""


def check_input(text: str) -> ModerationResult:
    """
    Checks a single input message. BLOCK takes precedence over SUPPORT over
    FLAG over allow — if a message somehow matches both a block pattern and
    a support pattern, treat it as the more serious category.
    """
    lowered = text.lower()

    for pattern in _BLOCK_PATTERNS:
        if re.search(pattern, lowered):
            return ModerationResult(action="block", flagged_categories=["hard_block"], matched_pattern=pattern)

    # Jailbreak framing + a harm-adjacent topic together is high-confidence —
    # block it the same as the narrow WMD-agent patterns above. See the
    # module-level comment by _JAILBREAK_FRAMING_PATTERNS for why this exists
    # (the original BLOCK list missed every one of redteam.py's 10 probes).
    framing_match = next((p for p in _JAILBREAK_FRAMING_PATTERNS if re.search(p, lowered)), None)
    harm_topic_match = next((p for p in _HARM_ADJACENT_TOPIC_PATTERNS if re.search(p, lowered)), None)
    if framing_match and harm_topic_match:
        return ModerationResult(
            action="block", flagged_categories=["jailbreak_framing", "harm_adjacent_topic"],
            matched_pattern=f"{framing_match} + {harm_topic_match}",
        )

    for pattern in _SUPPORT_PATTERNS:
        if re.search(pattern, lowered):
            return ModerationResult(action="support", flagged_categories=["self_harm"], matched_pattern=pattern)

    # Framing alone, no harm-adjacent topic detected — ambiguous (could be a
    # legitimate question about jailbreaks/prompt injection itself). Flag for
    # governance visibility rather than block, same triage-not-proof spirit
    # as the bias flags in orca/train/redteam.py.
    if framing_match:
        return ModerationResult(
            action="flag", flagged_categories=["jailbreak_framing_ambiguous"], matched_pattern=framing_match,
        )

    for pattern in _FLAG_PATTERNS:
        if re.search(pattern, lowered):
            return ModerationResult(action="flag", flagged_categories=["harassment"], matched_pattern=pattern)

    return ModerationResult(action="allow")

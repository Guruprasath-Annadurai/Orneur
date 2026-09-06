"""
Orca Lens — image-generation prompt safety filter.

This is the real gap `orca/lens/generate.py`'s own docstring flags: "no
content-safety filtering yet ... do not deploy before that's built." This
module is that filter, checked BEFORE any prompt reaches the Flux pipeline.

Reuses the same three-action pattern as `orca/serve/moderation.py` (text
chat input moderation) — BLOCK / FLAG / ALLOW, no SUPPORT category here
(there's no self-harm-crisis-response equivalent for an image-generation
prompt the way there is for a chat message). Same honesty scope as that
module: keyword/pattern-based, a floor not a ceiling — a real production
deployment handling adversarial traffic at scale should layer a trained
image-prompt classifier on top of this.

Image generation has categories text chat moderation doesn't need:
  - Real, identifiable people in sexual/defamatory contexts (deepfake risk) —
    BLOCK. Unlike text, an image claiming to depict a real person doing
    something is a much sharper harm (non-consensual intimate imagery,
    defamation-by-image) than describing the same thing in prose.
  - Named copyrighted characters/franchises — BLOCK. This is the exact
    Seedance/MPA precedent that motivated building this filter proactively
    rather than reactively: generating "Mickey Mouse" or "a Marvel superhero"
    on request is a real, direct commercial legal exposure for a paid
    product, not a gray area.
  - "In the style of [named living artist]" — FLAG, not BLOCK. Style itself
    isn't copyrightable and there's a real legitimate use (learning,
    homage, parody), but it's a genuine ethical/PR sensitivity worth
    governance visibility, same triage-not-proof spirit as the bias flags
    in orca/train/redteam.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class LensModerationResult:
    action: str  # "allow" | "block" | "flag"
    flagged_categories: list[str] = field(default_factory=list)
    matched_pattern: str = ""


# ─────────────────────────────────────────────────────────────────────────────
#  BLOCK — no legitimate framing exists for these, in an image-generation context
# ─────────────────────────────────────────────────────────────────────────────

_BLOCK_PATTERNS = [
    # CSAM-adjacent — same narrow, deliberately-sparse pattern as the text
    # moderation module, to avoid false-positiving on legitimate child-safety
    # discussion; a real deployment MUST layer a specialized image classifier
    # here (e.g. PhotoDNA-style hash matching), not rely on this alone.
    r"\bsexual.{0,20}\b(child|minor|underage)\b",
    r"\b(child|minor|underage)\b.{0,20}\b(nude|naked|sexual)\b",
    # Non-consensual intimate imagery of a real, named or otherwise
    # identifiable person — the sharpest image-specific harm category.
    r"\b(nude|naked|topless|sexual|explicit)\b.{0,40}\b(photo|picture|image)\b.{0,20}\bof\b.{0,30}"
    r"\b(celebrity|politician|my (ex|girlfriend|boyfriend|wife|husband|coworker|boss|teacher))\b",
    # Real, identifiable person in a fabricated defamatory/criminal scene —
    # deepfake-style harm distinct from text (an image reads as "evidence"
    # in a way prose doesn't).
    r"\b(realistic|photorealistic|deepfake)\b.{0,40}\b(committing|doing)\b.{0,30}"
    r"\b(crime|illegal|arrested|assault)\b",
    # Named copyrighted characters/franchises — the direct Seedance/MPA-style
    # commercial legal exposure this filter exists to prevent proactively.
    r"\b(mickey mouse|spider-?man|batman|superman|iron man|pikachu|super mario|sonic the hedgehog|"
    r"star wars|harry potter|pokemon|disney princess|marvel superhero|dc superhero|"
    r"minions|hello kitty|spongebob)\b",
]

# ─────────────────────────────────────────────────────────────────────────────
#  FLAG — genuine gray areas worth governance visibility, not a hard block
# ─────────────────────────────────────────────────────────────────────────────

_FLAG_PATTERNS = [
    # "In the style of [named artist]" — legitimate use exists (homage,
    # learning, parody), but a real, recurring ethical/PR sensitivity.
    r"\bin the style of\b.{0,40}\b[A-Z][a-z]+\s[A-Z][a-z]+\b",
    r"\bstyle of\b.{0,10}\b(picasso|van gogh|monet|banksy|studio ghibli|miyazaki)\b",
    # A real, named public figure requested in ANY context (not just the
    # sexual/defamatory BLOCK patterns above) — not harmful by default, but
    # worth a triage signal given how easily "photo of [politician]" drifts
    # into misinformation-adjacent territory once actually generated.
    r"\bphoto(realistic)? (image |picture )?of\b.{0,10}\b(president|prime minister|senator|ceo of)\b",
]


def check_image_prompt(prompt: str) -> LensModerationResult:
    """
    Checks a single image-generation prompt. BLOCK takes precedence over
    FLAG over allow, same precedence rule as orca/serve/moderation.py.
    """
    lowered = prompt.lower()

    for pattern in _BLOCK_PATTERNS:
        if re.search(pattern, lowered):
            return LensModerationResult(
                action="block", flagged_categories=["hard_block"], matched_pattern=pattern,
            )

    for pattern in _FLAG_PATTERNS:
        if re.search(pattern, lowered):
            return LensModerationResult(
                action="flag", flagged_categories=["gray_area"], matched_pattern=pattern,
            )

    return LensModerationResult(action="allow")

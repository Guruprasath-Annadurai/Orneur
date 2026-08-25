"""
Orca Lens — generation-intent detection.

Detects "generate me an image/video" requests BEFORE they reach the
Genesis/Novus/Aeternum text tiers, so a generation request never gets routed
into a text-completion model at all — it short-circuits to Lens instead.
This is a pre-dispatch router, not a tool the text models call mid-
conversation (unlike `web_search`/`run_code` in `orca/brain/agent.py`,
which the text model invokes itself) — the whole point is the text tiers
are never involved in a generation request.

HONEST SCOPE:
  - Keyword/regex-based, not a trained classifier. Cheap, fast, zero extra
    model calls — but will have real false negatives on phrasing it doesn't
    recognize ("I need a visual for my pitch deck") and occasional false
    positives on legitimate text questions that happen to contain a trigger
    word ("what image format does PNG use"). This is a deliberate first-pass
    tradeoff, not a claim of perfect intent detection — revisit with a real
    classifier only if false-negative rate turns out to matter against real
    usage, not preemptively.
  - Only classifies image vs. video vs. chat — does not extract generation
    parameters (style, aspect ratio, duration) from the message. That's a
    separate parsing step once intent is confirmed.
"""
from __future__ import annotations

import re
from typing import Literal

GenerationIntent = Literal["image", "video", "chat"]

# Ordered as (pattern, intent) — video patterns checked first since "video"
# requests often also contain image-adjacent words ("make a video with this
# picture"), and video is the more specific/costlier intent to get right.
_VIDEO_PATTERNS = [
    r"\b(generate|create|make|produce)\b.{0,20}\bvideo\b",
    r"\bvideo\b.{0,20}\b(of|showing|depicting)\b",
    r"\banimate\b",
    r"\b(text.to.video|txt2vid)\b",
]

_IMAGE_PATTERNS = [
    r"\b(generate|create|make|draw|produce|design)\b.{0,20}\b(image|photo|picture|illustration|artwork|graphic|logo)\b",
    r"\b(image|photo|picture)\b.{0,20}\b(of|showing|depicting)\b",
    r"\b(text.to.image|txt2img)\b",
    r"\bdraw me\b",
]

_video_re = re.compile("|".join(_VIDEO_PATTERNS), re.IGNORECASE)
_image_re = re.compile("|".join(_IMAGE_PATTERNS), re.IGNORECASE)


def detect_generation_intent(message: str) -> GenerationIntent:
    """
    Classifies a user message as an image-generation request, a video-
    generation request, or ordinary chat. Video is checked first since it's
    the more specific/costlier intent — a message matching both patterns
    (rare, but possible: "make a video image montage") is treated as video.
    """
    if not message or not message.strip():
        return "chat"

    if _video_re.search(message):
        return "video"
    if _image_re.search(message):
        return "image"
    return "chat"

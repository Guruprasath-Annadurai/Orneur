"""
Tests for orca/lens/intent.py's generation-intent detection.

Covers the real, honest scope: keyword/regex classification of image vs.
video vs. chat, including the documented edge cases (video-over-image
priority on ambiguous messages, and known false-positive/negative
tradeoffs the module's own docstring flags as accepted, not hidden).
"""
from __future__ import annotations

from orca.lens.intent import detect_generation_intent


def test_plain_chat_message_not_classified_as_generation():
    assert detect_generation_intent("What's the capital of France?") == "chat"
    assert detect_generation_intent("Help me debug this Python function") == "chat"
    assert detect_generation_intent("") == "chat"
    assert detect_generation_intent("   ") == "chat"


def test_image_generation_requests_detected():
    assert detect_generation_intent("Generate an image of a sunset") == "image"
    assert detect_generation_intent("Create a picture of a cat wearing a hat") == "image"
    assert detect_generation_intent("Draw me a logo for my startup") == "image"
    assert detect_generation_intent("Make an illustration of a dragon") == "image"
    assert detect_generation_intent("Design a graphic showing our product") == "image"


def test_video_generation_requests_detected():
    assert detect_generation_intent("Generate a video of a beach") == "video"
    assert detect_generation_intent("Create a video showing a car driving") == "video"
    assert detect_generation_intent("Can you animate this scene?") == "video"
    assert detect_generation_intent("Make me a text-to-video clip") == "video"


def test_video_takes_priority_over_image_on_ambiguous_message():
    # A message that could match both patterns — video is checked first
    # since it's the more specific/costlier intent per the module's design.
    result = detect_generation_intent("Generate a video image montage")
    assert result == "video"


def test_known_false_positive_case_documented_not_hidden():
    # The module's own docstring flags this exact tradeoff: a legitimate
    # text question containing a trigger phrase gets misclassified. This
    # test locks in the KNOWN behavior so a future change doesn't silently
    # alter it without updating the docstring's honest-scope claim too.
    result = detect_generation_intent("Please create a picture of the data flow in words")
    assert result == "image"  # accepted false positive, not a bug to silently fix here


def test_case_insensitive_matching():
    assert detect_generation_intent("GENERATE AN IMAGE OF A DOG") == "image"
    assert detect_generation_intent("Generate A Video Of The Ocean") == "video"

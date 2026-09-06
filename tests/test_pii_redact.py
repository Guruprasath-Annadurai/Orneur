"""
Tests for orca/docs/pii_redact.py — locking in three real regressions
found and fixed earlier this session:
  1. SSN in the 900-999 area-number range must still redact (an earlier
     "smarter" version excluded it as "not government-issued" and leaked it).
  2. Phone numbers with a literal opening paren must not leave the paren
     dangling unredacted (a \\b-based pattern did this).
  3. Credit card numbers must not get corrupted by the phone pattern
     matching a 10-digit slice out of the middle before Luhn validation runs.
"""
from __future__ import annotations

from orca.docs.pii_redact import redact_pii, _luhn_valid


# A real Luhn-valid Visa test number (widely published test card, not a
# real account) — needed because the redactor validates Luhn before
# redacting, a random 16-digit string won't trigger it.
VALID_TEST_VISA = "4532015112830366"


def test_luhn_valid_known_test_card():
    assert _luhn_valid(VALID_TEST_VISA) is True


def test_luhn_invalid_random_digits():
    assert _luhn_valid("1234567890123456") is False


def test_ssn_basic_redaction():
    text, report = redact_pii("His SSN is 123-45-6789 on file.")
    assert "[REDACTED-SSN]" in text
    assert "123-45-6789" not in text
    assert report["ssn"] == 1


def test_ssn_900_range_still_redacted_regression():
    """
    The exact bug: an earlier version excluded 900-999 area numbers as
    "not real SSNs" and a test SSN in that range leaked into the vector
    store unredacted. Structure-only matching must catch it regardless.
    """
    text, report = redact_pii("Applicant SSN: 987-65-4321")
    assert "[REDACTED-SSN]" in text
    assert "987-65-4321" not in text
    assert report["ssn"] == 1


def test_email_redaction():
    text, report = redact_pii("Contact me at jane.doe@example.com please.")
    assert "[REDACTED-EMAIL]" in text
    assert "jane.doe@example.com" not in text
    assert report["email"] == 1


def test_phone_with_parens_not_dangling_regression():
    """
    The exact bug: \\b matched between '(' and the digit after it, leaving
    the opening paren outside the match — "(555) 123-4567" would redact to
    "(REDACTED-PHONE]" with a stray leading paren. Must fully consume it.
    """
    text, report = redact_pii("Call us at (555) 123-4567 during business hours.")
    assert "[REDACTED-PHONE]" in text
    assert "(" not in text.split("[REDACTED-PHONE]")[0][-5:]  # no dangling paren right before the marker
    assert "555" not in text
    assert report["phone"] == 1


def test_phone_plain_format():
    text, report = redact_pii("My number is 555-123-4567.")
    assert "[REDACTED-PHONE]" in text
    assert report["phone"] == 1


def test_credit_card_valid_luhn_redacted():
    text, report = redact_pii(f"Card on file: {VALID_TEST_VISA}")
    assert "[REDACTED-CC]" in text
    assert VALID_TEST_VISA not in text
    assert report["credit_card"] == 1


def test_credit_card_invalid_luhn_left_alone():
    """A 16-digit number that fails Luhn (e.g. an order ID) is not a real card — don't redact it."""
    invalid = "1234567890123456"
    text, report = redact_pii(f"Order ID: {invalid}")
    assert invalid in text
    assert report["credit_card"] == 0


def test_credit_card_not_corrupted_by_phone_pattern_regression():
    """
    The exact bug: redacting phones before credit cards let the phone
    pattern match a 10-digit slice out of the middle of a 16-digit card
    number, corrupting it before the Luhn check ever ran on the full
    number. Credit cards must be processed first.
    """
    text, report = redact_pii(f"Payment card: {VALID_TEST_VISA} thanks.")
    assert report["credit_card"] == 1
    assert report["phone"] == 0  # the card digits must not also trigger a phone match
    assert VALID_TEST_VISA not in text


def test_report_never_contains_raw_values():
    """Governance requirement: report is counts only, safe for audit.log — never re-exposes the redacted value."""
    text, report = redact_pii("SSN 123-45-6789, email a@b.com, card " + VALID_TEST_VISA)
    for value in report.values():
        assert isinstance(value, int)
    assert "123-45-6789" not in json_safe_str(report)
    assert "a@b.com" not in json_safe_str(report)


def json_safe_str(report: dict) -> str:
    import json
    return json.dumps(report)


def test_total_matches_sum_of_individual_counts():
    text, report = redact_pii(
        f"SSN 123-45-6789, email a@b.com, phone 555-123-4567, card {VALID_TEST_VISA}"
    )
    assert report["total"] == report["ssn"] + report["email"] + report["phone"] + report["credit_card"]
    assert report["total"] == 4


def test_clean_text_no_false_positives():
    text, report = redact_pii("This is a perfectly normal sentence with no sensitive data at all.")
    assert report["total"] == 0
    assert text == "This is a perfectly normal sentence with no sensitive data at all."

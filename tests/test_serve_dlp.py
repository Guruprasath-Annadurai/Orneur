"""
Tests for orca/serve/dlp.py's scan_output() — output-side DLP scanning,
added because nothing previously scanned model OUTPUT for leaked PII or
secrets (orca/docs/pii_redact.py only covers document uploads). Covers the
deliberate asymmetry: PII is flagged (not redacted, to avoid mangling a
user's own legitimate data), secrets ARE redacted (no legitimate reason a
response should ever contain a real credential).
"""
from __future__ import annotations

from orca.serve.dlp import scan_output


def test_clean_text_has_no_findings():
    result = scan_output("The weather today is sunny with a high of 75 degrees.")
    assert result["has_findings"] is False
    assert result["pii_flagged"] == {}
    assert result["secrets_redacted"] == {}
    assert result["safe_text"] == "The weather today is sunny with a high of 75 degrees."


def test_pii_is_flagged_but_not_redacted_from_safe_text():
    text = "You can reach support at help@example.com for questions."
    result = scan_output(text)
    assert result["has_findings"] is True
    assert result["pii_flagged"] == {"email": 1}
    # Deliberate: PII is flagged for governance visibility, NOT stripped
    # from safe_text — mangling a legitimate email in a response would be
    # worse than the risk, same reasoning pii_redact.py already applies.
    assert "help@example.com" in result["safe_text"]


def test_ssn_shaped_data_is_flagged():
    result = scan_output("Reference number: 123-45-6789")
    assert result["pii_flagged"].get("ssn") == 1


def test_openai_key_is_actually_redacted_from_safe_text():
    fake_key = "sk-" + "a" * 40
    result = scan_output(f"Your API key is {fake_key}")
    assert result["has_findings"] is True
    assert result["secrets_redacted"].get("openai_api_key") == 1
    assert fake_key not in result["safe_text"]
    assert "[REDACTED-OPENAI_API_KEY]" in result["safe_text"]


def test_aws_access_key_is_redacted():
    fake_aws_key = "AKIA" + "B" * 16
    result = scan_output(f"export AWS_ACCESS_KEY_ID={fake_aws_key}")
    assert result["secrets_redacted"].get("aws_access_key") == 1
    assert fake_aws_key not in result["safe_text"]


def test_private_key_block_is_redacted():
    text = "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA...\n-----END RSA PRIVATE KEY-----"
    result = scan_output(text)
    assert result["secrets_redacted"].get("private_key_block") == 1
    assert "BEGIN RSA PRIVATE KEY" not in result["safe_text"]


def test_bearer_token_is_redacted():
    result = scan_output("Authorization: Bearer " + "x" * 30)
    assert result["secrets_redacted"].get("generic_bearer_token") == 1


def test_github_token_is_redacted():
    fake_token = "ghp_" + "a" * 30
    result = scan_output(f"Use this token: {fake_token}")
    assert result["secrets_redacted"].get("github_token") == 1
    assert fake_token not in result["safe_text"]


def test_both_pii_and_secrets_can_be_found_in_the_same_text():
    fake_key = "sk-" + "b" * 40
    text = f"Contact me at test@example.com. Also here's a key: {fake_key}"
    result = scan_output(text)
    assert result["has_findings"] is True
    assert result["pii_flagged"] == {"email": 1}
    assert result["secrets_redacted"].get("openai_api_key") == 1
    assert "test@example.com" in result["safe_text"]  # PII preserved
    assert fake_key not in result["safe_text"]  # secret redacted

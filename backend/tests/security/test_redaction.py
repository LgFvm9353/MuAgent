from app.redaction import redact, sanitize_text


def test_redacts_nested_secrets() -> None:
    value = {"headers": {"Authorization": "Bearer abc"}, "api_key": "secret", "safe": "ok"}
    result = redact(value)
    assert result["headers"]["Authorization"] == "[REDACTED]"
    assert result["api_key"] == "[REDACTED]"
    assert result["safe"] == "ok"


def test_sanitizes_log_newlines() -> None:
    assert sanitize_text("first\nforged") == "first\\nforged"

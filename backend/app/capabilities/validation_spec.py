"""
Validation Test Specification Engine.
Provides deterministic validation test cases for forms.
"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ValidationTestCase:
    field_type: str
    test_name: str
    input_value: str
    expected_behavior: str
    test_category: str = "negative"


# Comprehensive validation test cases per field type
VALIDATION_CASES: dict[str, list[ValidationTestCase]] = {
    "email": [
        ValidationTestCase("email", "missing_at", "notanemail", "Show email format error", "negative"),
        ValidationTestCase("email", "missing_domain", "user@", "Show email format error", "negative"),
        ValidationTestCase("email", "valid", "test@example.com", "Accept valid email", "positive"),
        ValidationTestCase("email", "xss", "<script>alert(1)</script>@evil.com", "Reject/sanitize XSS", "security"),
        ValidationTestCase("email", "sql_inject", "'; DROP TABLE users--@test.com", "Reject SQL injection", "security"),
    ],
    "number": [
        ValidationTestCase("number", "text_input", "abc", "Show number format error", "negative"),
        ValidationTestCase("number", "negative_if_unsigned", "-1", "Reject if unsigned required", "negative"),
        ValidationTestCase("number", "zero", "0", "Handle zero appropriately", "edge_case"),
        ValidationTestCase("number", "very_large", "999999999999999", "Handle max value", "edge_case"),
        ValidationTestCase("number", "decimal", "1.5", "Accept or reject decimal appropriately", "edge_case"),
    ],
    "text": [
        ValidationTestCase("text", "empty", "", "Show required field error", "negative"),
        ValidationTestCase("text", "whitespace_only", "   ", "Trim and validate whitespace", "edge_case"),
        ValidationTestCase("text", "max_length", "A" * 300, "Handle max length gracefully", "edge_case"),
        ValidationTestCase("text", "sql_inject", "Robert'); DROP TABLE--", "Sanitize SQL injection", "security"),
        ValidationTestCase("text", "xss", "<script>alert('xss')</script>", "Sanitize XSS payload", "security"),
        ValidationTestCase("text", "html_entity", "<b>bold</b>&amp;test", "Handle HTML entities", "edge_case"),
    ],
    "date": [
        ValidationTestCase("date", "past_date", "2000-01-01", "Accept historical date", "positive"),
        ValidationTestCase("date", "future_date", "2099-12-31", "Handle far future date", "edge_case"),
        ValidationTestCase("date", "invalid_format", "31/02/2024", "Show date format error", "negative"),
        ValidationTestCase("date", "text_in_date", "not-a-date", "Show format error", "negative"),
    ],
    "phone": [
        ValidationTestCase("phone", "too_short", "123", "Show phone format error", "negative"),
        ValidationTestCase("phone", "letters", "abcdefghij", "Show phone format error", "negative"),
        ValidationTestCase("phone", "valid_international", "+1234567890", "Accept international format", "positive"),
    ],
    "password": [
        ValidationTestCase("password", "too_short", "abc", "Show minimum length error", "negative"),
        ValidationTestCase("password", "no_uppercase", "password123!", "Show complexity error if required", "negative"),
        ValidationTestCase("password", "common", "Password123!", "Accept common strong password", "positive"),
    ],
    "url": [
        ValidationTestCase("url", "no_protocol", "example.com", "Show URL format error", "negative"),
        ValidationTestCase("url", "javascript_xss", "javascript:alert(1)", "Block javascript: protocol", "security"),
        ValidationTestCase("url", "valid", "https://example.com", "Accept valid HTTPS URL", "positive"),
    ],
}


class ValidationSpecEngine:
    """Provides validation test cases for a given field type."""

    def get_test_cases(self, field_type: str) -> list[ValidationTestCase]:
        return VALIDATION_CASES.get(field_type.lower(), VALIDATION_CASES["text"])

    def get_security_cases(self) -> list[ValidationTestCase]:
        """Return all security-category test cases across all field types."""
        return [
            case
            for cases in VALIDATION_CASES.values()
            for case in cases
            if case.test_category == "security"
        ]

    def get_negative_cases_for_field(self, field_type: str) -> list[ValidationTestCase]:
        return [c for c in self.get_test_cases(field_type) if c.test_category == "negative"]

# -*- coding: utf-8 -*-
import re
import html


# Suspicious prompt injection phrases
INJECTION_PHRASES = [
    "ignore previous instructions",
    "ignore all instructions",
    "ignore your instructions",
    "forget your instructions",
    "forget previous instructions",
    "you are now",
    "act as",
    "pretend you are",
    "disregard your",
    "override your",
    "new instruction",
    "system prompt",
    "do not follow",
    "stop following",
]

# PII patterns to redact before sending to LLM
PII_PATTERNS = [
    # Israeli ID (9 digits)
    (r'\b\d{9}\b',                                          '[ID_REDACTED]'),
    # Credit card (13-19 digits, optionally separated by spaces or dashes)
    (r'\b(?:\d[ -]?){13,19}\b',                            '[CARD_REDACTED]'),
    # Israeli phone: 05X-XXXXXXX or 05XXXXXXXX or +972...
    (r'(\+972|0)([23489]|5[0-9]|7[0-9])[-\s]?\d{3}[-\s]?\d{4}', '[PHONE_REDACTED]'),
    # Generic international phone (at least 7 digits with optional country code)
    (r'\b\+?[\d\s\-().]{7,20}\d\b',                        '[PHONE_REDACTED]'),
    # Email addresses
    (r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b', '[EMAIL_REDACTED]'),
    # Physical addresses (house number + street keyword)
    (r'\b\d{1,5}\s+\w+\s+(st|street|ave|avenue|rd|road|blvd|dr|drive|ln|lane|way)\b',
     '[ADDRESS_REDACTED]'),
    # Bank account numbers (IL format: 6-9 digits)
    (r'\b\d{6,9}\b',                                        '[ACCOUNT_REDACTED]'),
]


def strip_html_tags(text: str) -> str:
    """Remove all HTML tags and decode HTML entities."""
    text = html.unescape(text)
    text = re.sub(r'<(script|style)[^>]*>.*?</(script|style)>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def check_prompt_injection(text: str) -> bool:
    """Returns True if suspicious prompt injection is detected."""
    text_lower = text.lower()
    return any(phrase in text_lower for phrase in INJECTION_PHRASES)


def redact_pii(text: str) -> tuple[str, list[str]]:
    """
    Redact sensitive PII from text before sending to LLM.
    Returns the redacted text and a list of redaction notices.
    """
    redacted = text
    notices = []

    for pattern, placeholder in PII_PATTERNS:
        matches = re.findall(pattern, redacted, flags=re.IGNORECASE)
        if matches:
            redacted = re.sub(pattern, placeholder, redacted, flags=re.IGNORECASE)
            notices.append(placeholder)

    # Deduplicate notices
    seen = set()
    unique_notices = []
    for n in notices:
        if n not in seen:
            seen.add(n)
            unique_notices.append(n)

    return redacted, unique_notices


def sanitize_email_content(text: str) -> str:
    """
    Full sanitization pipeline for email content before sending to LLM.
    1. Strip HTML tags
    2. Check for prompt injection
    3. Redact PII
    """
    # Step 1: Strip HTML
    clean_text = strip_html_tags(text)

    # Step 2: Check for prompt injection
    if check_prompt_injection(clean_text):
        return "[WARNING: Email content was flagged as potentially malicious and has been redacted.]"

    # Step 3: Redact PII
    redacted_text, notices = redact_pii(clean_text)

    if notices:
        notice_str = ", ".join(notices)
        redacted_text += f"\n\n[Note: The following sensitive fields were redacted before processing: {notice_str}]"

    return redacted_text
# -*- coding: utf-8 -*-
import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def has_issues(self) -> bool:
        return bool(self.warnings or self.errors)

    def summary(self) -> str:
        lines = []
        if self.errors:
            lines.append("ERRORS (must fix before sending):")
            for e in self.errors:
                lines.append(f"   - {e}")
        if self.warnings:
            lines.append("WARNINGS:")
            for w in self.warnings:
                lines.append(f"   - {w}")
        return "\n".join(lines)


def validate_draft(draft: str) -> ValidationResult:
    """
    Validates an email draft before presenting to user.
    Checks for critical issues that would make the email unsuitable to send.
    """
    errors = []
    warnings = []

    # 1. Check draft is not empty or too short
    if not draft or len(draft.strip()) < 20:
        errors.append("Draft is too short or empty.")

    # 2. Check for unfilled placeholders like {name}, [NAME], <DATE>
    placeholders = re.findall(r'\{[^}]+\}|\[[A-Z][A-Z_]+\]|<[A-Z][A-Z_]+>', draft)
    if placeholders:
        errors.append(f"Unfilled placeholders found: {', '.join(set(placeholders))}")

    # 3. Check for unanswered question markers left by the LLM
    answer_markers = re.findall(
        r'\[answer needed\]|\[response needed\]|\[todo\]|\[fill in\]',
        draft.lower()
    )
    if answer_markers:
        errors.append("Draft contains unanswered markers that must be filled in.")

    # 4. Warn if draft is unusually long (over 300 words)
    word_count = len(draft.split())
    if word_count > 300:
        warnings.append(f"Draft is quite long ({word_count} words). Consider shortening it.")

    is_valid = len(errors) == 0
    return ValidationResult(is_valid=is_valid, warnings=warnings, errors=errors)

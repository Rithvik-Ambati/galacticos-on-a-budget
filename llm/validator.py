"""Numeric validator. docs/DESIGN.md section 9, point 2: extract every number from the
final text; each must match an engine value (rounding tolerance); on failure
regenerate once, then fall back to a template. CLAUDE.md rule 1 in enforcement form.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# The leading '-' only counts as a sign when it's at the start of the text or after
# whitespace -- otherwise "4-3-3" (a formation) or "2-1" (a score) parses as
# [4, -3, -3] / [2, -1] instead of their actual digits, a real bug this regex hit on
# its very first test (both narrator templates contain exactly these shapes). The
# digit match itself is never gated by this, so e.g. "100" right after "/" still works.
_NUMBER_RE = re.compile(r"(?:(?<!\S)-)?\d[\d,]*\.?\d*")


def extract_numbers(text: str) -> list[float]:
    numbers = []
    for match in _NUMBER_RE.finditer(text):
        raw = match.group().replace(",", "")
        try:
            numbers.append(float(raw))
        except ValueError:
            continue
    return numbers


def _matches(n: float, allowed: set[float]) -> bool:
    for a in allowed:
        tolerance = max(0.5, abs(a) * 0.01)  # 1% relative, floor 0.5 absolute
        if abs(n - a) <= tolerance:
            return True
    return False


@dataclass
class ValidationOutcome:
    passed: bool
    bad_numbers: list[float]


def validate_numbers(text: str, allowed_values: set[float]) -> ValidationOutcome:
    numbers = extract_numbers(text)
    bad = [n for n in numbers if not _matches(n, allowed_values)]
    return ValidationOutcome(passed=not bad, bad_numbers=bad)


@dataclass
class ValidatedText:
    text: str
    passed: bool
    used_fallback: bool
    attempts: int


def validate_and_fix(
    first_attempt: str,
    allowed_values: set[float],
    *,
    regenerate: Callable[[], str],
    fallback_text: str,
) -> ValidatedText:
    outcome = validate_numbers(first_attempt, allowed_values)
    if outcome.passed:
        return ValidatedText(text=first_attempt, passed=True, used_fallback=False, attempts=1)

    second_attempt = regenerate()
    outcome2 = validate_numbers(second_attempt, allowed_values)
    if outcome2.passed:
        return ValidatedText(text=second_attempt, passed=True, used_fallback=False, attempts=2)

    return ValidatedText(text=fallback_text, passed=False, used_fallback=True, attempts=2)

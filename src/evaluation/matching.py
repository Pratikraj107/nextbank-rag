"""
Deterministic fact matching for evaluation.

Every matcher returns one of:
  "matched"   - the fact is present, with an unambiguous reading
  "missing"   - the fact is not present
  "ambiguous" - present only under one of several possible readings
                (e.g. "72.000" or "03/05/2021"); needs manual review

Amounts and dates are parsed into values and compared exactly, so a
different amount that merely shares digits ("6,570" vs "6,750", or
"5,083" vs "5,083.33") never counts as a match.
"""

import re
from dataclasses import dataclass
from datetime import date

MATCHED = "matched"
MISSING = "missing"
AMBIGUOUS = "ambiguous"

CITATION_PATTERN = re.compile(r"\[(S\d+(?:\s*,\s*S\d+)*)\]")


def strip_citations(text: str) -> str:
    return CITATION_PATTERN.sub(" ", text)


# ------------------------------------------------------------
# Amounts
# ------------------------------------------------------------

@dataclass(frozen=True)
class ParsedAmount:
    value: float
    currency: str | None
    # A second plausible reading of the same digits, if any.
    alternative: float | None = None


_CURRENCY = r"(EUR|€|USD|\$|GBP|£)"
_NUMBER = r"(\d{1,3}(?:[,.   ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
AMOUNT_PATTERN = re.compile(
    rf"(?:{_CURRENCY}\s?)?(?<![\w.,/-]){_NUMBER}(?![\w]|[.,]\d|[-/]\d)(?:\s?{_CURRENCY})?",
    re.IGNORECASE,
)


def _interpret_number(raw: str) -> tuple[float, float | None]:
    """Return (value, alternative reading or None)."""
    separators = [(i, ch) for i, ch in enumerate(raw) if ch in ",.   "]

    if not separators:
        return float(raw), None

    last_index, last_char = separators[-1]
    digits_after = len(raw) - last_index - 1
    integer_part = re.sub(r"\D", "", raw[:last_index])
    fraction = raw[last_index + 1:]

    if digits_after in (1, 2) and last_char in ",.":
        return float(f"{integer_part}.{fraction}"), None

    value = float(re.sub(r"\D", "", raw))

    # "72.000" or "6,750" with a single separator: thousands grouping is the
    # usual reading, but "72.000" could also be a decimal in English text.
    if len(separators) == 1 and last_char == ".":
        return value, float(raw)

    return value, None


def extract_amounts(text: str) -> list[ParsedAmount]:
    amounts = []
    for match in AMOUNT_PATTERN.finditer(strip_citations(text)):
        before, raw, after = match.group(1), match.group(2), match.group(3)
        value, alternative = _interpret_number(raw)
        currency = (before or after or "").upper().replace("€", "EUR") or None
        amounts.append(ParsedAmount(value, currency, alternative))
    return amounts


def match_amount(text: str, expected: float, currency: str = "EUR") -> str:
    found_alternative = False

    for amount in extract_amounts(text):
        if amount.currency not in (None, currency.upper()):
            continue
        if abs(amount.value - expected) < 0.005:
            if amount.alternative is not None:
                found_alternative = True
                continue
            return MATCHED
        if amount.alternative is not None and abs(amount.alternative - expected) < 0.005:
            found_alternative = True

    return AMBIGUOUS if found_alternative else MISSING


# ------------------------------------------------------------
# Dates
# ------------------------------------------------------------

MONTHS = {
    "january": 1, "jan": 1, "januari": 1,
    "february": 2, "feb": 2, "februari": 2,
    "march": 3, "mar": 3, "maart": 3,
    "april": 4, "apr": 4,
    "may": 5, "mei": 5,
    "june": 6, "jun": 6, "juni": 6,
    "july": 7, "jul": 7, "juli": 7,
    "august": 8, "aug": 8, "augustus": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10, "oktober": 10, "okt": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}
_MONTH = "(" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
_DAY = r"(\d{1,2})(?:st|nd|rd|th)?"

ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
DAY_MONTH_YEAR = re.compile(rf"\b{_DAY}\s+{_MONTH},?\s+(\d{{4}})\b", re.IGNORECASE)
MONTH_DAY_YEAR = re.compile(rf"\b{_MONTH}\s+{_DAY},?\s+(\d{{4}})\b", re.IGNORECASE)
NUMERIC_DATE = re.compile(r"\b(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})\b")


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def extract_dates(text: str) -> list[tuple[date, date | None]]:
    """Return (date, alternative reading or None) for each date found."""
    text = strip_citations(text)
    found = []

    for y, m, d in ISO_DATE.findall(text):
        if parsed := _safe_date(int(y), int(m), int(d)):
            found.append((parsed, None))

    for d, month, y in DAY_MONTH_YEAR.findall(text):
        if parsed := _safe_date(int(y), MONTHS[month.lower()], int(d)):
            found.append((parsed, None))

    for month, d, y in MONTH_DAY_YEAR.findall(text):
        if parsed := _safe_date(int(y), MONTHS[month.lower()], int(d)):
            found.append((parsed, None))

    # Numeric dates are read day-first (as in the Dutch source documents);
    # when both readings are valid and differ, the result is ambiguous.
    for first, second, y in NUMERIC_DATE.findall(text):
        day_first = _safe_date(int(y), int(second), int(first))
        month_first = _safe_date(int(y), int(first), int(second))
        if day_first:
            alternative = month_first if month_first and month_first != day_first else None
            found.append((day_first, alternative))
        elif month_first:
            found.append((month_first, None))

    return found


def match_date(text: str, expected_iso: str) -> str:
    expected = date.fromisoformat(expected_iso)
    ambiguous = False

    for parsed, alternative in extract_dates(text):
        if parsed == expected:
            if alternative is None:
                return MATCHED
            ambiguous = True
        elif alternative == expected:
            ambiguous = True

    return AMBIGUOUS if ambiguous else MISSING


# ------------------------------------------------------------
# Quantities, text, identifiers, patterns
# ------------------------------------------------------------

def match_quantity(text: str, value: float, unit: str) -> str:
    number = int(value) if float(value).is_integer() else value
    pattern = rf"(?<![\d.,]){re.escape(str(number))}(?:\.0+)?\s*-?\s*{re.escape(unit)}s?\b"
    return MATCHED if re.search(pattern, strip_citations(text), re.IGNORECASE) else MISSING


def normalize_text(text: str) -> str:
    text = strip_citations(text).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def match_text(text: str, phrase: str) -> str:
    haystack = f" {normalize_text(text)} "
    needle = f" {normalize_text(phrase)} "
    return MATCHED if needle.strip() and needle in haystack else MISSING


def match_identifier(text: str, identifier: str) -> str:
    pattern = rf"(?<![A-Za-z0-9]){re.escape(identifier)}(?![A-Za-z0-9])"
    return MATCHED if re.search(pattern, text, re.IGNORECASE) else MISSING


def match_pattern(text: str, regex: str) -> str:
    flags = re.IGNORECASE | re.MULTILINE
    return MATCHED if re.search(regex, strip_citations(text), flags) else MISSING


def match_fact(text: str, fact: dict) -> str:
    """Dispatch on the fact's type. See dataset.FACT_TYPES."""
    kind = fact["type"]

    if kind == "amount":
        return match_amount(text, float(fact["value"]), fact.get("currency", "EUR"))
    if kind == "date":
        return match_date(text, fact["value"])
    if kind == "quantity":
        return match_quantity(text, fact["value"], fact["unit"])
    if kind == "text":
        return match_text(text, fact["value"])
    if kind == "identifier":
        return match_identifier(text, fact["value"])
    if kind == "pattern":
        return match_pattern(text, fact["value"])

    raise ValueError(f"Unknown fact type: {kind}")


def fact_label(fact: dict) -> str:
    return fact.get("label") or f"{fact['type']}: {fact['value']}"

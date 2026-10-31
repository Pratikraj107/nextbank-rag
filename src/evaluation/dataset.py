"""Load and validate the evaluation dataset (JSONL, one case per line)."""

import json
from dataclasses import dataclass, field
from pathlib import Path

EXPECTED_BEHAVIORS = {"answer", "abstain", "reject_conflict"}
FACT_TYPES = {"amount", "date", "quantity", "text", "identifier"}
# "pattern" (a regular expression) is allowed only for forbidden facts.
FORBIDDEN_FACT_TYPES = FACT_TYPES | {"pattern"}

REQUIRED_FIELDS = {
    "id": str,
    "category": str,
    "question": str,
    "expected_behavior": str,
    "reference_facts": list,
    "required_citation": bool,
    "notes": str,
}

OPTIONAL_FIELDS = {
    "required_source_types": list,
    "expected_customer_id": (str, type(None)),
    "expected_loan_id": (str, type(None)),
    "forbidden_facts": list,
}


@dataclass(frozen=True)
class EvalCase:
    id: str
    category: str
    question: str
    expected_behavior: str
    reference_facts: list[dict]
    required_citation: bool
    notes: str
    required_source_types: list[str] = field(default_factory=list)
    expected_customer_id: str | None = None
    expected_loan_id: str | None = None
    forbidden_facts: list[dict] = field(default_factory=list)


class DatasetError(ValueError):
    """Raised when the dataset fails schema validation."""


def _validate_fact(fact: object, where: str, allowed: set[str]) -> list[str]:
    if not isinstance(fact, dict):
        return [f"{where}: fact must be an object"]

    errors = []
    fact_type = fact.get("type")

    if fact_type not in allowed:
        errors.append(f"{where}: unknown fact type {fact_type!r}")
        return errors

    value = fact.get("value")

    if fact_type == "amount":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            errors.append(f"{where}: amount value must be a number")
    elif fact_type == "quantity":
        if not isinstance(value, (int, float)) or not isinstance(fact.get("unit"), str):
            errors.append(f"{where}: quantity needs a numeric value and a unit")
    elif fact_type == "date":
        if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
            errors.append(f"{where}: date value must be YYYY-MM-DD")
    elif not isinstance(value, str) or not value.strip():
        errors.append(f"{where}: {fact_type} value must be a non-empty string")

    return errors


def validate_record(record: object, line_number: int) -> list[str]:
    """Return a list of schema errors for one dataset line."""
    where = f"line {line_number}"

    if not isinstance(record, dict):
        return [f"{where}: expected a JSON object"]

    errors = []

    for name, expected_type in REQUIRED_FIELDS.items():
        if name not in record:
            errors.append(f"{where}: missing required field {name!r}")
        elif not isinstance(record[name], expected_type):
            errors.append(f"{where}: field {name!r} has the wrong type")

    for name, expected_type in OPTIONAL_FIELDS.items():
        if name in record and not isinstance(record[name], expected_type):
            errors.append(f"{where}: field {name!r} has the wrong type")

    unknown = set(record) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        errors.append(f"{where}: unknown fields {sorted(unknown)}")

    if errors:
        return errors

    if not record["id"].strip() or not record["question"].strip():
        errors.append(f"{where}: id and question must not be empty")

    if record["expected_behavior"] not in EXPECTED_BEHAVIORS:
        errors.append(
            f"{where}: expected_behavior must be one of {sorted(EXPECTED_BEHAVIORS)}"
        )

    if record["expected_behavior"] == "answer" and not record["reference_facts"]:
        errors.append(f"{where}: 'answer' cases need at least one reference fact")

    for index, fact in enumerate(record["reference_facts"]):
        errors += _validate_fact(fact, f"{where} reference_facts[{index}]", FACT_TYPES)

    for index, fact in enumerate(record.get("forbidden_facts", [])):
        errors += _validate_fact(fact, f"{where} forbidden_facts[{index}]", FORBIDDEN_FACT_TYPES)

    return errors


def load_dataset(path: str | Path) -> list[EvalCase]:
    """Load the dataset, raising DatasetError listing every problem found."""
    path = Path(path)
    errors: list[str] = []
    records: list[dict] = []

    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"line {line_number}: invalid JSON ({exc.msg})")
                continue
            line_errors = validate_record(record, line_number)
            errors += line_errors
            if not line_errors:
                records.append(record)

    seen: set[str] = set()
    for record in records:
        if record["id"] in seen:
            errors.append(f"duplicate id {record['id']!r}")
        seen.add(record["id"])

    if errors:
        raise DatasetError("Invalid evaluation dataset:\n  " + "\n  ".join(errors))

    return [EvalCase(**record) for record in records]


import csv
import re
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

ENTERPRISE_CSV_DIR = (
    Path(__file__).resolve().parents[2] / "data" / "raw" / "enterprise_csv"
)


@lru_cache(maxsize=1)
def load_verified_entities() -> tuple[dict[str, str], dict[str, str]]:
    """
    Load customer names and loan→customer links from the enterprise CSVs
    once per process. Returns (name→customer_id, loan_id→customer_id).
    Missing files yield empty maps; the analyzer's built-in entries still apply.
    """
    customers: dict[str, str] = {}
    loans: dict[str, str] = {}

    customers_file = ENTERPRISE_CSV_DIR / "customers.csv"
    loans_file = ENTERPRISE_CSV_DIR / "loan_applications.csv"

    if customers_file.exists():
        with customers_file.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                name = (row.get("name") or "").strip().lower()
                customer_id = (row.get("customer_id") or "").strip().upper()
                if name and customer_id:
                    customers[name] = customer_id

    if loans_file.exists():
        with loans_file.open(encoding="utf-8-sig", newline="") as file:
            for row in csv.DictReader(file):
                loan_id = (row.get("loan_id") or "").strip().upper()
                customer_id = (row.get("customer_id") or "").strip().upper()
                if loan_id and customer_id:
                    loans[loan_id] = customer_id

    return customers, loans


@dataclass
class QueryAnalysis:
    original_query: str
    customer_id: str | None = None
    loan_id: str | None = None
    document_type: str | None = None
    intent: str = "general_question"
    matched_entities: list[str] | None = None
    entity_conflict: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class QueryAnalyzer:
    """
    Rule-based query analyzer for NexaBank.

    Extracts customer and loan identifiers, detects intent,
    and checks known customer/loan relationships.
    """

    CUSTOMER_MAP = {
        "lotte van dijk": "NB-CUST-3001",
        "thomas de boer": "NB-CUST-3002",
    }

    # Only add relationships verified against the dataset.
    LOAN_CUSTOMER_MAP = {
        "NB-LOAN-2101": "NB-CUST-3001",
        "NB-LOAN-2102": "NB-CUST-3002",
    }

    def __init__(self) -> None:
        csv_customers, csv_loans = load_verified_entities()
        # Instance copies so the class-level defaults are never mutated.
        self.CUSTOMER_MAP = {**self.CUSTOMER_MAP, **csv_customers}
        self.LOAN_CUSTOMER_MAP = {**self.LOAN_CUSTOMER_MAP, **csv_loans}

    def analyze(self, query: str) -> QueryAnalysis:
        normalized_query = query.lower().strip()
        matched_entities = []

        customer_id = self._extract_customer(
            normalized_query, matched_entities
        )

        loan_id = self._extract_loan_id(
            normalized_query, matched_entities
        )

        intent, document_type = self._detect_intent(
            normalized_query
        )

        entity_conflict = self._check_entity_consistency(
            customer_id=customer_id,
            loan_id=loan_id,
        )

        if entity_conflict:
            matched_entities.append("ENTITY_CONFLICT")
            print(f"[Query Analyzer] {entity_conflict}")

        return QueryAnalysis(
            original_query=query,
            customer_id=customer_id,
            loan_id=loan_id,
            document_type=document_type,
            intent=intent,
            matched_entities=matched_entities,
            entity_conflict=entity_conflict,
        )

    def _extract_customer(
        self,
        query: str,
        matched_entities: list[str],
    ) -> str | None:
        # Match known customer names.
        for name, customer_id in self.CUSTOMER_MAP.items():
            if name in query:
                matched_entities.append(name)
                return customer_id

        # Support explicit customer IDs.
        match = re.search(
            r"\bNB-CUST-\d+\b",
            query,
            re.IGNORECASE,
        )

        if match:
            customer_id = match.group(0).upper()
            matched_entities.append(customer_id)
            return customer_id

        return None

    def _extract_loan_id(
        self,
        query: str,
        matched_entities: list[str],
    ) -> str | None:
        match = re.search(
            r"\bNB-LOAN-\d+\b",
            query,
            re.IGNORECASE,
        )

        if match:
            loan_id = match.group(0).upper()
            matched_entities.append(loan_id)
            return loan_id

        return None

    def _check_entity_consistency(
        self,
        customer_id: str | None,
        loan_id: str | None,
    ) -> str | None:
        """
        Detect a mismatch when both identifiers are known
        and the loan-to-customer relationship is verified.

        Unknown relationships are not automatically treated
        as conflicts.
        """
        if not customer_id or not loan_id:
            return None

        expected_customer = self.LOAN_CUSTOMER_MAP.get(loan_id)

        # No verified mapping: do not guess.
        if expected_customer is None:
            return None

        if customer_id != expected_customer:
            return (
                f"Customer/loan mismatch: {customer_id} does not "
                f"match {loan_id}. The verified customer for "
                f"{loan_id} is {expected_customer}."
            )

        return None

    def _detect_intent(
        self,
        query: str,
    ) -> tuple[str, str | None]:

        if any(
            phrase in query
            for phrase in [
                "credit assessment",
                "credit decision",
                "credit result",
                "creditworthiness",
            ]
        ):
            return "credit_assessment", "credit_assessment"

        if any(
            phrase in query
            for phrase in [
                "outstanding loan balance",
                "outstanding balance",
                "remaining loan balance",
                "existing loan balance",
            ]
        ):
            return (
                "outstanding_loan_balance",
                "existing_loan_statement",
            )

        if any(
            phrase in query
            for phrase in [
                "annual salary",
                "yearly salary",
                "annual gross salary",
                "employment start date",
                "when did",
            ]
        ):
            return "employment_details", "employment_agreement"

        if any(
            phrase in query
            for phrase in [
                "monthly net salary",
                "net monthly salary",
                "take-home pay",
                "take home pay",
            ]
        ):
            return "monthly_net_salary", "payslip"

        if any(
            phrase in query
            for phrase in [
                "monthly gross salary",
                "gross monthly salary",
                "gross salary per month",
            ]
        ):
            return "monthly_gross_salary", "payslip"

        if any(
            phrase in query
            for phrase in [
                "salary",
                "payslip",
                "pay slip",
                "monthly income",
            ]
        ):
            return "salary_information", "payslip"

        if any(
            phrase in query
            for phrase in [
                "loan term",
                "repayment term",
                "loan duration",
                "requested loan amount",
                "loan amount",
                "amount requested",
            ]
        ):
            return "loan_application_details", "loan_application"

        return "general_question", None

from dataclasses import dataclass, field

from src.models.document import NormalizedDocument


@dataclass
class ValidationResult:
    """Result of validating one normalized document."""

    document_id: str
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class DocumentValidator:
    """Validate normalized documents using document-specific rules."""

    MIN_CONFIDENCE = 0.5

    REQUIRED_FIELDS = {
        "loan_application": [
            "loan_id",
            "customer_id",
            "applicant_name",
            "requested_amount",
            "term_months",
            "loan_purpose",
        ],

        "bank_statement": [
            "account_holder",
            "iban",
            "statement_period",
            "opening_balance",
            "closing_balance",
        ],

        "payslip": [
            "employee_name",
            "employee_id",
            "employer",
            "gross_monthly_salary",
            "net_monthly_salary",
            "payroll_period",
        ],

        "employer_statement": [
            "employee_name",
            "employer",
            "employment_start_date",
            "contract_type",
            "annual_gross_salary",
        ],

        "existing_loan_statement": [
            "borrower",
            "lender",
            "contract_number",
            "outstanding_balance",
            "monthly_payment",
            "statement_date",
        ],

        "sepa_mandate": [
            "creditor_identifier",
            "mandate_reference",
        ],

        "loan_offer": [
            "borrower",
            "principal_amount",
            "term_months",
            "interest_rate",
            "offer_validity",
        ],

        "employment_agreement": [
            "employee_name",
            "employer",
            "position",
            "contract_type",
            "start_date",
            "annual_gross_salary",
        ],

        "credit_assessment": [
            "loan_id",
            "customer_id",
        ],

        "identity_document": [
            "document_number",
            "nationality",
        ],
    }

    def validate(
        self,
        document: NormalizedDocument,
    ) -> ValidationResult:

        errors = []
        warnings = []

        # --------------------------------------------------
        # 1. Common structural validation
        # --------------------------------------------------

        if not document.document_id:
            errors.append("Missing document_id")

        if not document.source:
            errors.append("Missing source")

        if not document.source_type:
            errors.append("Missing source_type")

        if not document.document_type:
            errors.append("Missing document_type")

        if not document.content.strip():
            errors.append("Document has empty content")

        # --------------------------------------------------
        # 2. Classification validation
        # --------------------------------------------------

        classification = document.metadata.get(
            "classification"
        )

        if classification:

            confidence = classification.get(
                "confidence",
                0,
            )

            if confidence < self.MIN_CONFIDENCE:
                warnings.append(
                    f"Low classification confidence: {confidence}"
                )

        # --------------------------------------------------
        # 3. Document-specific validation
        # --------------------------------------------------

        required_fields = self.REQUIRED_FIELDS.get(
            document.document_type
        )

        if required_fields:

            for field_name in required_fields:

                value = document.metadata.get(
                    field_name
                )

                if value is None or value == "":
                    errors.append(
                        f"Missing required field: "
                        f"{field_name}"
                    )

        # --------------------------------------------------
        # 4. CSV validation
        # --------------------------------------------------

        if document.document_type == "csv_record":

            record = document.metadata.get(
                "record",
                {}
            )

            if not record:
                errors.append(
                    "CSV record is empty"
                )

        # --------------------------------------------------
        # 5. Unknown document type
        # --------------------------------------------------

        if document.document_type == "unknown":

            warnings.append(
                "Document type could not be determined"
            )

        # --------------------------------------------------
        # Final result
        # --------------------------------------------------

        return ValidationResult(
            document_id=document.document_id,
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )
from pathlib import Path


class DocumentTypeDetector:
    """Detect document type using deterministic rules."""

    RULES = {
        "bank_statement": [
            "iban",
            "statement period",
            "opening balance",
            "closing balance",
            "debit",
            "credit",
        ],
        "payslip": [
            "salary slip",
            "salarisstrook",
            "gross monthly salary",
            "net salary",
            "payroll period",
            "loonheffing",
            "pension",
        ],
        "loan_application": [
            "personal loan application",
            "application reference",
            "requested:",
            "term:",
            "purpose:",
            "applicant:",
        ],
        "employer_statement": [
            "werkgeversverklaring",
            "employer statement",
            "employment start date",
            "annual gross salary",
        ],
        "existing_loan_statement": [
            "existing credit",
            "existing loan",
            "outstanding balance",
            "monthly payment",
            "contract number",
        ],
        "sepa_mandate": [
            "sepa",
            "direct debit mandate",
            "creditor identifier",
            "mandate reference",
        ],
        "loan_offer": [
            "loan offer",
            "principal:",
            "offer validity",
            "borrower signature",
        ],
        "employment_agreement": [
            "employment agreement",
            "employment contract",
            "contract type",
            "annual gross salary",
        ],
        "credit_assessment": [
            "credit analyst",
            "credit assessment",
            "documents expected",
            "document review pending",
        ],
        "identity_document": [
            "identity",
            "id card",
            "document number",
            "nationality",
        ],
        "internal_lending_portal": [
            "nexabank lending portal",
            "lending operations",
            "document checklist",
        ],
        "customer_email": [
            "aanvullende documenten",
            "beste nexabank",
            "met vriendelijke groet",
        ],
    }

    FILENAME_RULES = {
        "loan_application": ["loan_application"],
        "bank_statement": ["bank_statement"],
        "payslip": ["payslip"],
        "employer_statement": ["employer_statement"],
        "existing_loan_statement": ["existing_loan_statement"],
        "sepa_mandate": ["sepa_mandate"],
        "loan_offer": ["loan_offer"],
        "employment_agreement": ["employment_agreement"],
        "credit_assessment": ["credit_analyst_notes"],
        "identity_document": ["identity_residence"],
        "internal_lending_portal": ["internal_lending_portal"],
        "customer_email": ["customer_email"],
    }

    def detect(self, content: str, file_path: str | Path) -> dict:
        text = content.lower()
        filename = Path(file_path).stem.lower()

        scores = {}

        for document_type, signals in self.RULES.items():
            matched_signals = []
            score = 0

            for signal in signals:
                if signal in text:
                    score += 1
                    matched_signals.append(signal)

            for filename_signal in self.FILENAME_RULES.get(
                document_type, []
            ):
                if filename_signal in filename:
                    score += 3
                    matched_signals.append("filename")

            scores[document_type] = {
                "score": score,
                "matched_signals": matched_signals,
            }

        best_type = max(
            scores,
            key=lambda document_type: scores[document_type]["score"],
        )

        best_score = scores[best_type]["score"]

        # Require at least two pieces of evidence.
        if best_score < 2:
            return {
                "document_type": "unknown",
                "confidence": 0.0,
                "matched_signals": [],
            }

        max_possible = len(self.RULES[best_type]) + 3

        confidence = min(
            best_score / max_possible,
            1.0,
        )

        return {
            "document_type": best_type,
            "confidence": round(confidence, 2),
            "matched_signals": scores[best_type]["matched_signals"],
        }
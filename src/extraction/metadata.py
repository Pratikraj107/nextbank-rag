import re


class MetadataExtractor:
    """Extract structured metadata from normalized document text."""

    def extract(self, content: str, document_type: str) -> dict:
        extractors = {
            "loan_application": self._extract_loan_application,
            "bank_statement": self._extract_bank_statement,
            "payslip": self._extract_payslip,
            "employer_statement": self._extract_employer_statement,
            "identity_document": self._extract_identity_document,
            "existing_loan_statement": self._extract_existing_loan_statement,
            "sepa_mandate": self._extract_sepa_mandate,
            "loan_offer": self._extract_loan_offer,
            "employment_agreement": self._extract_employment_agreement,
            "credit_assessment": self._extract_credit_assessment,
        }

        extractor = extractors.get(document_type)

        if extractor is None:
            return {}

        return extractor(content)

    # ---------------------------------------------------------
    # Loan application
    # ---------------------------------------------------------

    def _extract_loan_application(self, text: str) -> dict:
        return {
            "loan_id": self._find(
                text,
                r"Application reference:\s*(\S+)"
            ),
            "customer_id": self._find(
                text,
                r"Customer reference:\s*(\S+)"
            ),
            "applicant_name": self._find(
                text,
                r"Applicant:\s*(.+)"
            ),
            "requested_amount": self._find_number(
                text,
                r"Requested:\s*EUR\s*([\d,]+)"
            ),
            "term_months": self._find_number(
                text,
                r"Term:\s*(\d+)\s*months"
            ),
            "loan_purpose": self._find(
                text,
                r"Purpose:\s*(.+)"
            ),
            "date_of_birth": self._find(
                text,
                r"Date of birth:\s*(\d{4}-\d{2}-\d{2})"
            ),
            "city": self._find(
                text,
                r"Residential city:\s*(.+)"
            ),
            "employment": self._find(
                text,
                r"Employment:\s*(.+)"
            ),
            "employer": self._find(
                text,
                r"Employer:\s*(.+)"
            ),
        }

    # ---------------------------------------------------------
    # Bank statement
    # ---------------------------------------------------------

    def _extract_bank_statement(self, text: str) -> dict:
        return {
            "account_holder": self._find(
                text,
                r"Account holder\s*\n([^\n]+)"
            ),
            "iban": self._find(
                text,
                r"IBAN:\s*(\S+)"
            ),
            "statement_period": self._find(
                text,
                r"Statement period\s*\n([^\n]+)"
            ),
            "opening_balance": self._find_decimal(
                text,
                r"Opening balance\s*\n([\d,]+\.\d{2})"
            ),
            "closing_balance": self._find_decimal(
                text,
                r"Closing balance\s*\n([\d,]+\.\d{2})"
            ),
        }

    # ---------------------------------------------------------
    # Payslip
    # ---------------------------------------------------------

    def _extract_payslip(self, text: str) -> dict:
        return {
            "employee_name": self._find(
                text,
                r"Employee\s*\n([^\n]+)"
            ),
            "employee_id": self._find(
                text,
                r"Employee ID:\s*(\S+)"
            ),
            "employer": self._find(
                text,
                r"Employer\s*:\s*(.+)"
            ),
            "gross_monthly_salary": self._find_decimal(
                text,
                r"Gross monthly salary:\s*EUR\s*([\d,]+\.\d{2})"
            ),
            "net_monthly_salary": self._find_decimal(
                text,
                r"Net salary:\s*EUR\s*([\d,]+\.\d{2})"
            ),
            "payroll_period": self._find(
                text,
                r"Payroll period:\s*(.+)"
            ),
        }

    # ---------------------------------------------------------
    # Employer statement
    # ---------------------------------------------------------

    def _extract_employer_statement(self, text: str) -> dict:
        return {
            "employee_name": self._find(
                text,
                r"Name:\s*(.+)"
            ),
            "employer": self._find(
                text,
                r"Company:\s*(.+)"
            ),
            "employment_start_date": self._find(
                text,
                r"Employment start date:\s*(\d{4}-\d{2}-\d{2})"
            ),
            "contract_type": self._find(
                text,
                r"Contract:\s*(.+)"
            ),
            "annual_gross_salary": self._find_decimal(
                text,
                r"Annual gross salary:\s*EUR\s*([\d,]+)"
            ),
        }

    # ---------------------------------------------------------
    # Identity document
    # ---------------------------------------------------------

    def _extract_identity_document(self, text: str) -> dict:
        return {
            "document_number": self._find(
                text,
                r"Document number:\s*(\S+)"
            ),
            "nationality": self._find(
                text,
                r"Nationality:\s*(.+)"
            ),
        }

    # ---------------------------------------------------------
    # Existing loan statement
    # ---------------------------------------------------------

    def _extract_existing_loan_statement(self, text: str) -> dict:
        return {
            "borrower": self._find_after_label(
                text,
                "Borrower"
            ),
            "lender": self._find_after_label(
                text,
                "Lender"
            ),
            "contract_number": self._find(
                text,
                r"Contract number:\s*(\S+)"
            ),
            "outstanding_balance": self._find_decimal(
                text,
                r"Outstanding balance:\s*EUR\s*([\d,]+)"
            ),
            "monthly_payment": self._find_decimal(
                text,
                r"Monthly payment:\s*EUR\s*([\d,]+)"
            ),
            "statement_date": self._find(
                text,
                r"Statement date:\s*(\d{2}-\d{2}-\d{4})"
            ),
        }

    # ---------------------------------------------------------
    # SEPA mandate
    # ---------------------------------------------------------

    def _extract_sepa_mandate(self, text: str) -> dict:
        return {
            "creditor_identifier": self._find(
                text,
                r"Creditor identifier:\s*(\S+)"
            ),
            "mandate_reference": self._find(
                text,
                r"Mandate reference:\s*(\S+)"
            ),
        }

    # ---------------------------------------------------------
    # Loan offer
    # ---------------------------------------------------------

    def _extract_loan_offer(self, text: str) -> dict:
        return {
            "borrower": self._find(
                text,
                r"Borrower:\s*(.+)"
            ),
            "principal_amount": self._find_decimal(
                text,
                r"Principal:\s*EUR\s*([\d,]+)"
            ),
            "term_months": self._find_number(
                text,
                r"Term:\s*(\d+)\s*months"
            ),
            "interest_rate": self._find(
                text,
                r"Interest rate:\s*(.+)"
            ),
            "offer_validity": self._find(
                text,
                r"Offer validity:\s*(.+)"
            ),
        }

    # ---------------------------------------------------------
    # Employment agreement
    # ---------------------------------------------------------

    def _extract_employment_agreement(self, text: str) -> dict:
        return {
            "employee_name": self._find(
                text,
                r"Employee:\s*(.+)"
            ),
            "employer": self._find(
                text,
                r"Employer:\s*(.+)"
            ),
            "position": self._find(
                text,
                r"Position:\s*(.+)"
            ),
            "contract_type": self._find(
                text,
                r"Contract type:\s*(.+)"
            ),
            "start_date": self._find(
                text,
                r"Start date:\s*(.+)"
            ),
            "annual_gross_salary": self._find_decimal(
                text,
                r"Annual gross salary:\s*EUR\s*([\d,]+)"
            ),
        }

    # ---------------------------------------------------------
    # Credit analyst notes
    # ---------------------------------------------------------

    def _extract_credit_assessment(self, text: str) -> dict:
        return {
            "loan_id": self._find(
                text,
                r"Loan reference:\s*(\S+)"
            ),
            "customer_id": self._find(
                text,
                r"Customer:\s*(\S+)"
            ),
        }

    # ---------------------------------------------------------
    # Helper methods
    # ---------------------------------------------------------

    @staticmethod
    def _find(text: str, pattern: str):
        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            return None

        return match.group(1).strip()

    @staticmethod
    def _find_after_label(text: str, label: str):
        """
        Find the first non-empty line after a standalone label.

        Example:

        Borrower
        Lotte van Dijk
        """

        pattern = rf"{re.escape(label)}\s*\n\s*([^\n]+)"

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if not match:
            return None

        return match.group(1).strip()

    @staticmethod
    def _find_number(text: str, pattern: str):
        value = MetadataExtractor._find(
            text,
            pattern
        )

        if value is None:
            return None

        return int(
            value.replace(",", "")
        )

    @staticmethod
    def _find_decimal(text: str, pattern: str):
        value = MetadataExtractor._find(
            text,
            pattern
        )

        if value is None:
            return None

        return float(
            value.replace(",", "")
        )
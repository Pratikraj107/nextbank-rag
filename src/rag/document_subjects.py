"""
What each document type describes, derived from trusted metadata.

Chunk metadata carries a `loan_id`, but ingestion assigns it from the loan
application folder a document was filed in. It therefore means "submitted
with this application", not "this document is about that loan". An
existing-loan statement filed with application NB-LOAN-2101 describes a
different credit agreement, and its figures must never be read as terms of
NB-LOAN-2101. Evidence headers state this explicitly so neither answer
generation nor evidence validation has to infer it from a chunk fragment.
"""

REQUESTED_LOAN = "the requested loan identified by the application file"

DOCUMENT_SUBJECTS = {
    "loan_application": REQUESTED_LOAN,
    "loan_offer": REQUESTED_LOAN,
    "credit_assessment": REQUESTED_LOAN,
    "internal_lending_portal": REQUESTED_LOAN,
    "existing_loan_statement": (
        "a separate existing credit agreement held by the customer, "
        "NOT the requested loan in the application file"
    ),
    "payslip": "the customer's employment income",
    "employer_statement": "the customer's employment and income",
    "employment_agreement": "the customer's employment contract",
    "bank_statement": "the customer's bank account activity",
    "identity_document": "the customer's identity and residence",
    "sepa_mandate": "a direct-debit authorisation for repayments",
    "customer_email": "correspondence from the customer",
    "csv_record": "a structured record from NexaBank systems (see its field names)",
}

# Document types whose figures belong to a credit agreement other than the
# requested loan.
SEPARATE_CREDIT_TYPES = frozenset({"existing_loan_statement"})


def describe_document(document_type: str | None) -> str:
    return DOCUMENT_SUBJECTS.get(document_type or "", "not specified")

from pathlib import Path

from src.parsers.docx_parser import DOCXParser
from src.parsers.pdf_parser import PDFParser


FILES = [
    "data/raw/NB-LOAN-2101/docx/09_employment_agreement.docx",
    "data/raw/NB-LOAN-2101/docx/10_credit_analyst_notes.docx",
    "data/raw/NB-LOAN-2101/pdf/04_employer_statement.pdf",
    "data/raw/NB-LOAN-2101/pdf/05_identity_residence.pdf",
    "data/raw/NB-LOAN-2101/pdf/06_existing_loan_statement.pdf",
    "data/raw/NB-LOAN-2101/pdf/07_sepa_mandate.pdf",
    "data/raw/NB-LOAN-2101/pdf/08_loan_offer.pdf",
]


parsers = {
    ".docx": DOCXParser(),
    ".pdf": PDFParser(),
}


for file_path in FILES:
    path = Path(file_path)

    parser = parsers[path.suffix.lower()]
    result = parser.parse(path)

    print("\n" + "=" * 80)
    print(file_path)
    print("=" * 80)

    print(result["content"])
import json
from pathlib import Path
from uuid import uuid4

from src.parsers.pdf_parser import PDFParser
from src.parsers.docx_parser import DOCXParser
from src.parsers.html_parser import HTMLParser
from src.parsers.email_parser import EmailParser
from src.parsers.csv_parser import CSVParser

from src.extraction.document_type import DocumentTypeDetector
from src.extraction.metadata import MetadataExtractor

from src.models.document import NormalizedDocument

from src.validation.validator import DocumentValidator


class IngestionPipeline:
    """Main pipeline for ingesting and normalizing documents."""

    PARSERS = {
        ".pdf": PDFParser,
        ".docx": DOCXParser,
        ".html": HTMLParser,
        ".htm": HTMLParser,
        ".eml": EmailParser,
        ".csv": CSVParser,
    }

    def __init__(self):
        self.document_type_detector = DocumentTypeDetector()
        self.metadata_extractor = MetadataExtractor()
        self.validator = DocumentValidator()

    # =========================================================
    # PROCESS ONE FILE
    # =========================================================

    def process_file(
        self,
        file_path: str | Path,
    ) -> list[NormalizedDocument]:

        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(
                f"File not found: {path}"
            )

        if not path.is_file():
            raise ValueError(
                f"Expected a file: {path}"
            )

        extension = path.suffix.lower()

        parser_class = self.PARSERS.get(extension)

        if parser_class is None:
            raise ValueError(
                f"Unsupported file type: {extension}"
            )

        # Create the appropriate parser
        parser = parser_class()

        # Extract raw information
        result = parser.parse(path)

        # CSV is special because one file can contain
        # multiple records.
        if extension == ".csv":
            return self._process_csv(result)

        # PDF / DOCX / HTML / EML
        document = self._normalize_document(result)

        return [document]

    # =========================================================
    # PROCESS CSV
    # =========================================================

    def _process_csv(
        self,
        result: dict,
    ) -> list[NormalizedDocument]:

        documents = []

        for row_number, record in enumerate(
            result["records"],
            start=2,
        ):

            content = self._record_to_text(record)

            document = NormalizedDocument(
                document_id=str(uuid4()),

                loan_id=record.get("loan_id"),

                customer_id=record.get("customer_id"),

                document_type="csv_record",

                source=result["source"],

                source_type="csv",

                content=content,

                metadata={
                    "row_number": row_number,
                    "record": record,
                },
            )

            documents.append(document)

        return documents

    def _extract_ids_from_source(
        self,
        source: str,
    ) -> tuple[str | None, str | None]:

        path = Path(source)

        loan_id = None
        customer_id = None

        # Example:
        # data/raw/NB-LOAN-2101/pdf/03_payslip.pdf

        for part in path.parts:
            if part.startswith("NB-LOAN-"):
                loan_id = part
                break

        customer_mapping = {
            "NB-LOAN-2101": "NB-CUST-3001",
            "NB-LOAN-2102": "NB-CUST-3002",
            "NB-LOAN-2103": "NB-CUST-3003",
        }

        if loan_id:
            customer_id = customer_mapping.get(loan_id)

        return loan_id, customer_id

    # =========================================================
    # NORMALIZE DOCUMENT
    # =========================================================

    def _normalize_document(
        self,
        result: dict,
    ) -> NormalizedDocument:

        content = result["content"]

        # -----------------------------------------------------
        # Step 1: Detect document type
        # -----------------------------------------------------

        classification = (
            self.document_type_detector.detect(
                content,
                result["source"],
            )
        )

        document_type = classification["document_type"]

        # -----------------------------------------------------
        # Step 2: Extract metadata
        # -----------------------------------------------------

        metadata = (
            self.metadata_extractor.extract(
                content,
                document_type,
            )
        )

        # -----------------------------------------------------
        # Step 3: Add email metadata
        # -----------------------------------------------------

        if "email" in result:
            metadata["email"] = result["email"]

        # -----------------------------------------------------
        # Step 4: Extract common identifiers
        # -----------------------------------------------------

        loan_id = metadata.get("loan_id")
        customer_id = metadata.get("customer_id")

        source_loan_id, source_customer_id = (
            self._extract_ids_from_source(
                result["source"]
            )
        )

        # Prefer identifiers extracted from the document.
        # Fall back to identifiers derived from the source path.
        if not loan_id:
            loan_id = source_loan_id

        if not customer_id:
            customer_id = source_customer_id

        # -----------------------------------------------------
        # Step 5: Create normalized document
        # -----------------------------------------------------

        document = NormalizedDocument(
            document_id=str(uuid4()),

            loan_id=loan_id,

            customer_id=customer_id,

            document_type=document_type,

            source=result["source"],

            source_type=result["source_type"],

            content=content,

            metadata={
                **metadata,
                "classification": classification,
            },
        )

        return document

    # =========================================================
    # CSV RECORD → TEXT
    # =========================================================

    @staticmethod
    def _record_to_text(
        record: dict,
    ) -> str:

        return "\n".join(
            f"{key}: {value}"
            for key, value in record.items()
        )

    # =========================================================
    # PROCESS ENTIRE DIRECTORY
    # =========================================================

    def process_directory(
        self,
        input_directory: str | Path,
    ) -> list[NormalizedDocument]:

        input_path = Path(input_directory)

        if not input_path.exists():
            raise FileNotFoundError(
                f"Input directory not found: {input_path}"
            )

        if not input_path.is_dir():
            raise ValueError(
                f"Expected a directory: {input_path}"
            )

        documents = []

        # File-level statistics
        total_files = 0
        successful_files = 0
        failed_files = 0

        # Validation statistics
        total_warnings = 0
        total_errors = 0

        # -----------------------------------------------------
        # Recursively discover files
        # -----------------------------------------------------

        for file_path in input_path.rglob("*"):

            # Ignore directories
            if not file_path.is_file():
                continue

            # Ignore unsupported file types
            if file_path.suffix.lower() not in self.PARSERS:
                total_files += 1
                failed_files += 1

                print(
                    f"ERROR: {file_path}"
                )

                print(
                    f"       Unsupported file type: "
                    f"{file_path.suffix.lower()}"
                )
                continue

            total_files += 1

            try:

                # -------------------------------------------------
                # Process file
                # -------------------------------------------------

                file_documents = self.process_file(
                    file_path
                )

                successful_files += 1

                # -------------------------------------------------
                # Validate each resulting document
                # -------------------------------------------------

                for document in file_documents:

                    validation = (
                        self.validator.validate(
                            document
                        )
                    )

                    # -----------------------------
                    # Warnings
                    # -----------------------------

                    if validation.warnings:

                        total_warnings += len(
                            validation.warnings
                        )

                        print(
                            f"WARNING: {file_path}"
                        )

                        for warning in validation.warnings:

                            print(
                                f"         {warning}"
                            )

                    # -----------------------------
                    # Errors
                    # -----------------------------

                    if validation.errors:

                        total_errors += len(
                            validation.errors
                        )

                        print(
                            f"VALIDATION ERROR: "
                            f"{file_path}"
                        )

                        for error in validation.errors:

                            print(
                                f"                  "
                                f"{error}"
                            )

                    # Add document to output
                    documents.append(document)

                # -------------------------------------------------
                # File successfully processed
                # -------------------------------------------------

                print(
                    f"SUCCESS: {file_path} "
                    f"→ {len(file_documents)} "
                    f"document(s)"
                )

            except Exception as error:

                failed_files += 1

                print(
                    f"ERROR: {file_path}"
                )

                print(
                    f"       {error}"
                )

        # =====================================================
        # SUMMARY
        # =====================================================

        print("\n" + "=" * 70)
        print("BATCH INGESTION SUMMARY")
        print("=" * 70)

        print(
            f"Files discovered:     "
            f"{total_files}"
        )

        print(
            f"Successful files:     "
            f"{successful_files}"
        )

        print(
            f"Failed files:         "
            f"{failed_files}"
        )

        print(
            f"Normalized documents: "
            f"{len(documents)}"
        )

        print(
            f"Validation warnings:  "
            f"{total_warnings}"
        )

        print(
            f"Validation errors:    "
            f"{total_errors}"
        )

        return documents

    # =========================================================
    # SAVE JSONL
    # =========================================================

    def save_jsonl(
        self,
        documents: list[NormalizedDocument],
        output_file: str | Path,
    ):

        output_path = Path(output_file)

        # Create output directory
        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        # Write one document per line
        with open(
            output_path,
            "w",
            encoding="utf-8",
        ) as file:

            for document in documents:

                json.dump(
                    document.to_dict(),
                    file,
                    ensure_ascii=False,
                )

                file.write("\n")

        print(
            "\nSaved normalized documents to:"
        )

        print(output_path)
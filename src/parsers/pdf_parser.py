from pathlib import Path

from pypdf import PdfReader


class PDFParser:
    """Extract text from PDF documents."""

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {path}")

        if path.suffix.lower() != ".pdf":
            raise ValueError(f"Expected a PDF file, got: {path.suffix}")

        reader = PdfReader(path)

        pages = []

        for page_number, page in enumerate(reader.pages, start=1):
            text = page.extract_text() or ""

            pages.append({
                "page_number": page_number,
                "content": text.strip(),
            })

        full_content = "\n\n".join(
            page["content"]
            for page in pages
            if page["content"]
        )

        return {
            "source": str(path),
            "source_type": "pdf",
            "content": full_content,
            "pages": pages,
        }
from pathlib import Path

from docx import Document


class DOCXParser:
    """Extract text from DOCX documents."""

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"DOCX not found: {path}")

        if path.suffix.lower() != ".docx":
            raise ValueError(f"Expected a DOCX file, got: {path.suffix}")

        document = Document(path)

        paragraphs = [
            paragraph.text.strip()
            for paragraph in document.paragraphs
            if paragraph.text.strip()
        ]

        content = "\n".join(paragraphs)

        return {
            "source": str(path),
            "source_type": "docx",
            "content": content,
        }
from pathlib import Path
from email import policy
from email.parser import BytesParser


class EmailParser:
    """Extract structured information from EML email files."""

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"Email file not found: {path}")

        if path.suffix.lower() != ".eml":
            raise ValueError(f"Expected an EML file, got: {path.suffix}")

        with open(path, "rb") as file:
            message = BytesParser(policy=policy.default).parse(file)

        body = self._extract_body(message)

        return {
            "source": str(path),
            "source_type": "eml",
            "content": body,
            "email": {
                "sender": message.get("From"),
                "recipient": message.get("To"),
                "subject": message.get("Subject"),
                "date": message.get("Date"),
            },
        }

    def _extract_body(self, message) -> str:
        if message.is_multipart():
            parts = []

            for part in message.walk():
                if part.get_content_type() == "text/plain":
                    parts.append(part.get_content())

            return "\n".join(parts).strip()

        return message.get_content().strip()
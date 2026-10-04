from pathlib import Path

from bs4 import BeautifulSoup


class HTMLParser:
    """Extract visible text from HTML documents."""

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"HTML file not found: {path}")

        if path.suffix.lower() not in {".html", ".htm"}:
            raise ValueError(f"Expected an HTML file, got: {path.suffix}")

        html = path.read_text(encoding="utf-8")

        soup = BeautifulSoup(html, "html.parser")

        # Remove content that isn't visible page text.
        for element in soup(["script", "style", "noscript"]):
            element.decompose()

        content = soup.get_text(separator="\n", strip=True)

        return {
            "source": str(path),
            "source_type": "html",
            "content": content,
        }
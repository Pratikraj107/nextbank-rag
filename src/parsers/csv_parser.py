import csv
from pathlib import Path


class CSVParser:
    """Parse CSV files into individual records."""

    def parse(self, file_path: str | Path) -> dict:
        path = Path(file_path)

        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")

        if path.suffix.lower() != ".csv":
            raise ValueError(f"Expected a CSV file, got: {path.suffix}")

        with open(path, "r", encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file)
            records = list(reader)

        return {
            "source": str(path),
            "source_type": "csv",
            "records": records,
        }
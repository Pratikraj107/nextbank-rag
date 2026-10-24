
import json
import sys
from pathlib import Path
from typing import Any


# Project root: nextbank-rag/
PROJECT_ROOT = Path(__file__).resolve().parents[2]

DOCUMENTS_PATH = (
    PROJECT_ROOT / "data" / "processed" / "documents.jsonl"
)


def exact_search(
    term: str,
    case_sensitive: bool = False,
    max_results: int = 20,
) -> dict[str, Any]:
    """
    Search every normalized document for a literal text match.

    Searches document content, not filenames or metadata.
    Returns matching records and a total match count.
    """

    term = term.strip()

    if not term:
        raise ValueError("Search term cannot be empty.")

    if max_results < 1:
        raise ValueError("max_results must be at least 1.")

    if not DOCUMENTS_PATH.exists():
        raise FileNotFoundError(
            f"Normalized documents not found: {DOCUMENTS_PATH}"
        )

    search_term = term if case_sensitive else term.casefold()

    total_documents = 0
    total_matches = 0
    results = []

    with DOCUMENTS_PATH.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue

            try:
                document = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Invalid JSON on line {line_number} "
                    f"of {DOCUMENTS_PATH}"
                ) from exc

            total_documents += 1

            content = str(document.get("content") or "")

            searchable_content = (
                content if case_sensitive else content.casefold()
            )

            # Count literal, non-overlapping occurrences.
            match_count = searchable_content.count(search_term)

            if match_count == 0:
                continue

            total_matches += match_count

            if len(results) < max_results:
                position = searchable_content.find(search_term)

                start = max(0, position - 100)
                end = min(
                    len(content),
                    position + len(term) + 100,
                )

                results.append({
                    "document_id": document.get("document_id"),
                    "source": document.get("source", "Unknown source"),
                    "customer_id": document.get("customer_id"),
                    "loan_id": document.get("loan_id"),
                    "document_type": document.get("document_type"),
                    "match_count": match_count,
                    "excerpt": content[start:end],
                })

    return {
        "term": term,
        "case_sensitive": case_sensitive,
        "documents_scanned": total_documents,
        "documents_matched": len([
            result for result in results
        ]) if total_matches else 0,
        "total_occurrences": total_matches,
        "results": results,
        "results_truncated": (
            total_matches > 0
            and sum(r["match_count"] for r in results) < total_matches
        ),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(
            'Usage: uv run python -m src.retrieval.exact_search "search term"'
        )
        raise SystemExit(1)

    term = " ".join(sys.argv[1:])

    result = exact_search(term)

    print(json.dumps(result, indent=2, ensure_ascii=False))

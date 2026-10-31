"""
Safe updates to the processed JSONL files used by every reader:

    documents.jsonl         Document Explorer library, exact search
    chunks.jsonl            Document Explorer library
    chunk_embeddings.jsonl  semantic search

Readers cache these files and reload them when a file's modification time
or size changes, so updating the files is all it takes to make new content
visible; nothing has to be restarted.

Each file is rewritten to a temporary file and swapped in with os.replace,
so a reader sees either the old or the new version, never a partial line.
Records are matched by their `source` path: writing a source again replaces
its old records, which makes ingestion idempotent across retries.

Write order keeps the files consistent for readers at every step:
removals go embeddings → chunks → documents, additions go documents →
chunks → embeddings, so a chunk never references a missing document.
"""

import json
import os
import tempfile
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"

# One writer at a time across the whole process.
_write_lock = threading.Lock()


class ProcessedStore:
    def __init__(
        self,
        documents_path: Path = PROCESSED_DIR / "documents.jsonl",
        chunks_path: Path = PROCESSED_DIR / "chunks.jsonl",
        embeddings_path: Path = PROCESSED_DIR / "chunk_embeddings.jsonl",
    ):
        self.documents_path = Path(documents_path)
        self.chunks_path = Path(chunks_path)
        self.embeddings_path = Path(embeddings_path)

    # ------------------------------------------------------------

    @staticmethod
    def _read(path: Path) -> list[str]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as file:
            return [line for line in file if line.strip()]

    @staticmethod
    def _write(path: Path, lines: list[str]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.writelines(line if line.endswith("\n") else line + "\n" for line in lines)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temp_name, path)
        except BaseException:
            Path(temp_name).unlink(missing_ok=True)
            raise

    @staticmethod
    def _without_source(lines: list[str], source: str) -> list[str]:
        kept = []
        for line in lines:
            try:
                if json.loads(line).get("source") == source:
                    continue
            except json.JSONDecodeError:
                pass  # leave lines we cannot read untouched
            kept.append(line)
        return kept

    def _remove_source(self, path: Path, source: str) -> None:
        lines = self._read(path)
        kept = self._without_source(lines, source)
        if len(kept) != len(lines):
            self._write(path, kept)

    def _append(self, path: Path, records: list[dict]) -> None:
        lines = self._read(path)
        lines += [json.dumps(record, ensure_ascii=False) + "\n" for record in records]
        self._write(path, lines)

    # ------------------------------------------------------------

    def contains_source(self, source: str) -> bool:
        return any(
            json.loads(line).get("source") == source
            for line in self._read(self.documents_path)
        )

    def upsert_source(
        self,
        source: str,
        documents: list[dict],
        chunks: list[dict],
        embeddings: list[dict],
    ) -> None:
        """Replace everything stored for `source` with the given records."""
        for record in documents + chunks + embeddings:
            if record.get("source") != source:
                raise ValueError("Every record must belong to the source being written.")

        with _write_lock:
            # Remove old records, dependents first.
            for path in (self.embeddings_path, self.chunks_path, self.documents_path):
                self._remove_source(path, source)
            # Add new records, parents first.
            self._append(self.documents_path, documents)
            self._append(self.chunks_path, chunks)
            self._append(self.embeddings_path, embeddings)

    def remove_source(self, source: str) -> None:
        with _write_lock:
            for path in (self.embeddings_path, self.chunks_path, self.documents_path):
                self._remove_source(path, source)

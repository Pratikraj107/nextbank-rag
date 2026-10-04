import re


class RecursiveChunker:
    def __init__(self, chunk_size: int = 200, overlap: int = 50):
        self.chunk_size = chunk_size
        self.overlap = overlap

        if overlap >= chunk_size:
            raise ValueError("overlap must be smaller than chunk_size")

    def chunk(self, text: str) -> list[str]:
        chunks = self._split(
            text,
            ["\n\n", "\n", ". ", " "]
        )

        if self.overlap == 0:
            return chunks

        return self._add_overlap(chunks)

    def _split(self, text: str, separators: list[str]) -> list[str]:
        text = text.strip()

        if len(text) <= self.chunk_size:
            return [text]

        if not separators:
            return self._split_by_characters(text)

        separator = separators[0]

        if separator == ". ":
            parts = re.split(r"(?<=\.)\s+", text)
        else:
            parts = text.split(separator)

        if len(parts) == 1:
            return self._split(text, separators[1:])

        chunks = []
        current = ""

        for part in parts:
            part = part.strip()

            if not part:
                continue

            candidate = (
                f"{current}{separator}{part}".strip()
                if current
                else part
            )

            if len(candidate) <= self.chunk_size:
                current = candidate
            else:
                if current:
                    chunks.extend(
                        self._split(current, separators[1:])
                    )

                current = part

        if current:
            chunks.extend(
                self._split(current, separators[1:])
            )

        return chunks

    def _split_by_characters(self, text: str) -> list[str]:
        return [
            text[i:i + self.chunk_size]
            for i in range(0, len(text), self.chunk_size)
        ]

    def _add_overlap(self, chunks: list[str]) -> list[str]:
        overlapped_chunks = []

        for index, chunk in enumerate(chunks):

            if index == 0:
                overlapped_chunks.append(chunk)
                continue

            previous_chunk = chunks[index - 1]

            overlap_text = self._get_word_overlap(
                previous_chunk
            )

            combined_chunk = (
                overlap_text + " " + chunk
            ).strip()

            overlapped_chunks.append(combined_chunk)

        return overlapped_chunks

    def _get_word_overlap(self, text: str) -> str:
        words = text.split()

        overlap_words = []
        current_length = 0

        for word in reversed(words):
            word_length = len(word)

            if current_length + word_length + 1 > self.overlap:
                break

            overlap_words.insert(0, word)
            current_length += word_length + 1

        return " ".join(overlap_words)
import re


class SentenceBasedChunker:
    def __init__(self, chunk_size: int = 500):
        self.chunk_size = chunk_size

    def chunk(self, text: str) -> list[str]:
        sentences = self._split_into_sentences(text)

        chunks = []
        current_chunk = ""

        for sentence in sentences:
            sentence = sentence.strip()

            if not sentence:
                continue

            # If adding the sentence stays within the target size
            if len(current_chunk) + len(sentence) + 1 <= self.chunk_size:
                if current_chunk:
                    current_chunk += " " + sentence
                else:
                    current_chunk = sentence

            else:
                # Save the current chunk
                if current_chunk:
                    chunks.append(current_chunk)

                # Start a new chunk
                current_chunk = sentence

        # Add the final chunk
        if current_chunk:
            chunks.append(current_chunk)

        return chunks

    def _split_into_sentences(self, text: str) -> list[str]:
        return re.split(r"(?<=[.!?])\s+", text.strip())
class FixedSizeChunker:
    def __init__(self, chunk_size: int = 500):
        self.chunk_size = chunk_size

    def chunk(self, text: str) -> list[str]:
        chunks = []

        for start in range(0, len(text), self.chunk_size):
            chunk = text[start:start + self.chunk_size]
            chunks.append(chunk)

        return chunks
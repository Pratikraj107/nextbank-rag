from sentence_transformers import SentenceTransformer


def main():
    model = SentenceTransformer("BAAI/bge-base-en-v1.5")

    text = "Annual gross salary: EUR 72,000"

    embedding = model.encode(text)

    print(f"Text: {text}")
    print(f"Embedding type: {type(embedding)}")
    print(f"Embedding dimensions: {len(embedding)}")
    print()
    print("First 10 values:")
    print(embedding[:10])


if __name__ == "__main__":
    main()
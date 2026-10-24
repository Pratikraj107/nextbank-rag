from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


def main():
    model = SentenceTransformer("BAAI/bge-base-en-v1.5")

    texts = [
        "Annual gross salary: EUR 72,000",
        "What is the yearly salary?",
        "The loan term is 48 months.",
    ]

    embeddings = model.encode(texts)

    similarity_matrix = cosine_similarity(embeddings)

    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            print(f"\nText A: {texts[i]}")
            print(f"Text B: {texts[j]}")
            print(f"Similarity: {similarity_matrix[i][j]:.4f}")


if __name__ == "__main__":
    main()
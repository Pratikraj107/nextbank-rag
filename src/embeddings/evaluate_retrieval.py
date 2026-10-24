import json

from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity


INPUT_FILE = "data/processed/chunk_embeddings.jsonl"
MODEL_NAME = "BAAI/bge-base-en-v1.5"


EVALUATION_DATASET = [
    {
        "question": "What is Lotte van Dijk's annual salary?",
        "expected_source": "09_employment_agreement.docx",
        "customer_id": "NB-CUST-3001",
        "document_type": "employment_agreement",
    },
    {
        "question": "What is Lotte van Dijk's monthly gross salary?",
        "expected_source": "03_payslip.pdf",
        "customer_id": "NB-CUST-3001",
        "document_type": "payslip",
    },
    {
        "question": "What is Lotte van Dijk's monthly net salary?",
        "expected_source": "03_payslip.pdf",
        "customer_id": "NB-CUST-3001",
        "document_type": "payslip",
    },
    {
        "question": "What is Lotte van Dijk's outstanding loan balance?",
        "expected_source": "06_existing_loan_statement.pdf",
        "customer_id": "NB-CUST-3001",
        "document_type": "existing_loan_statement",
    },
    {
        "question": "What is Thomas de Boer's monthly gross salary?",
        "expected_source": "03_payslip.pdf",
        "customer_id": "NB-CUST-3002",
        "document_type": "payslip",
    },
    {
        "question": "What is the loan term for NB-LOAN-2101?",
        "expected_source": "01_loan_application.pdf",
        "loan_id": "NB-LOAN-2101",
        "document_type": "loan_application",
    },
    {
        "question": "What is the requested loan amount for NB-LOAN-2101?",
        "expected_source": "01_loan_application.pdf",
        "loan_id": "NB-LOAN-2101",
        "document_type": "loan_application",
    },
    {
        "question": "What is the employment start date of Lotte van Dijk?",
        "expected_source": "09_employment_agreement.docx",
        "customer_id": "NB-CUST-3001",
        "document_type": "employment_agreement",
    },
    {
        "question": "What is the outstanding balance of the existing loan for Thomas de Boer?",
        "expected_source": "06_existing_loan_statement.pdf",
        "customer_id": "NB-CUST-3002",
        "document_type": "existing_loan_statement",
    },
    {
        "question": "What is the credit assessment result for Lotte van Dijk?",
        "expected_source": "10_credit_assessment.html",
        "customer_id": "NB-CUST-3001",
        "document_type": "credit_assessment",
    },
]


def load_chunks():
    with open(INPUT_FILE, "r", encoding="utf-8") as file:
        return [
            json.loads(line)
            for line in file
            if line.strip()
        ]


def filter_chunks(
    chunks,
    customer_id=None,
    loan_id=None,
    document_type=None,
):
    filtered = chunks

    if customer_id:
        filtered = [
            chunk
            for chunk in filtered
            if chunk.get("customer_id") == customer_id
        ]

    if loan_id:
        filtered = [
            chunk
            for chunk in filtered
            if chunk.get("loan_id") == loan_id
        ]

    if document_type:
        filtered = [
            chunk
            for chunk in filtered
            if chunk.get("document_type") == document_type
        ]

    return filtered


def search(
    query,
    model,
    chunks,
    top_k=5,
    customer_id=None,
    loan_id=None,
    document_type=None,
):
    # ---------------------------------------------------------
    # Step 1: Metadata filtering
    # ---------------------------------------------------------

    candidate_chunks = filter_chunks(
        chunks,
        customer_id=customer_id,
        loan_id=loan_id,
        document_type=document_type,
    )

    if not candidate_chunks:
        return []

    # ---------------------------------------------------------
    # Step 2: Embed query
    # ---------------------------------------------------------

    query_embedding = model.encode([query])

    # ---------------------------------------------------------
    # Step 3: Calculate similarity
    # ---------------------------------------------------------

    chunk_embeddings = [
        chunk["embedding"]
        for chunk in candidate_chunks
    ]

    similarities = cosine_similarity(
        query_embedding,
        chunk_embeddings,
    )[0]

    results = []

    for chunk, score in zip(
        candidate_chunks,
        similarities,
    ):
        results.append({
            "score": float(score),
            "chunk": chunk,
        })

    # ---------------------------------------------------------
    # Step 4: Rank results
    # ---------------------------------------------------------

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )

    return results[:top_k]


def source_matches(chunk, expected_source):
    return expected_source in chunk["source"]


def main():

    print("Loading embedding model...")
    model = SentenceTransformer(MODEL_NAME)

    print("Loading chunks...")
    chunks = load_chunks()

    print(f"Chunks loaded: {len(chunks)}")
    print()

    recall_at_1 = 0
    recall_at_3 = 0
    recall_at_5 = 0

    total_questions = len(EVALUATION_DATASET)

    for index, item in enumerate(
        EVALUATION_DATASET,
        start=1,
    ):

        question = item["question"]
        expected_source = item["expected_source"]

        results = search(
            query=question,
            model=model,
            chunks=chunks,
            top_k=5,
            customer_id=item.get("customer_id"),
            loan_id=item.get("loan_id"),
            document_type=item.get("document_type"),
        )

        top_1_match = any(
            source_matches(
                result["chunk"],
                expected_source,
            )
            for result in results[:1]
        )

        top_3_match = any(
            source_matches(
                result["chunk"],
                expected_source,
            )
            for result in results[:3]
        )

        top_5_match = any(
            source_matches(
                result["chunk"],
                expected_source,
            )
            for result in results[:5]
        )

        if top_1_match:
            recall_at_1 += 1

        if top_3_match:
            recall_at_3 += 1

        if top_5_match:
            recall_at_5 += 1

        print("=" * 80)
        print(f"QUESTION {index}")
        print(question)
        print()

        print("Filters:")
        print(f"  Customer ID: {item.get('customer_id')}")
        print(f"  Loan ID: {item.get('loan_id')}")
        print(f"  Document Type: {item.get('document_type')}")
        print()

        print(f"Expected source: {expected_source}")
        print()

        for rank, result in enumerate(
            results,
            start=1,
        ):

            chunk = result["chunk"]

            match = source_matches(
                chunk,
                expected_source,
            )

            marker = "✓ CORRECT" if match else ""

            print(
                f"Rank {rank}: "
                f"{result['score']:.4f} "
                f"{marker}"
            )

            print(
                f"Source: {chunk['source']}"
            )

            print(
                f"Document Type: "
                f"{chunk['document_type']}"
            )

            print(
                f"Loan ID: {chunk.get('loan_id')}"
            )

            print(
                f"Customer ID: "
                f"{chunk.get('customer_id')}"
            )

            print(
                f"Content: "
                f"{chunk['content'][:150]}"
            )

            print()

    # ---------------------------------------------------------
    # Final metrics
    # ---------------------------------------------------------

    print("=" * 80)
    print("METADATA-FILTERED RETRIEVAL RESULTS")
    print("=" * 80)

    print(
        f"Recall@1: "
        f"{recall_at_1}/{total_questions} "
        f"({recall_at_1 / total_questions:.2%})"
    )

    print(
        f"Recall@3: "
        f"{recall_at_3}/{total_questions} "
        f"({recall_at_3 / total_questions:.2%})"
    )

    print(
        f"Recall@5: "
        f"{recall_at_5}/{total_questions} "
        f"({recall_at_5 / total_questions:.2%})"
    )


if __name__ == "__main__":
    main()
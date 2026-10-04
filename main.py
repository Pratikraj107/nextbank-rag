from src.pipeline import IngestionPipeline


def main():

    pipeline = IngestionPipeline()

    input_directory = "data/raw"

    output_file = (
        "data/processed/documents.jsonl"
    )

    print("=" * 70)
    print("NexaBank Document Ingestion Pipeline")
    print("=" * 70)

    documents = pipeline.process_directory(
        input_directory
    )

    pipeline.save_jsonl(
        documents,
        output_file
    )


if __name__ == "__main__":
    main()
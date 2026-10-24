
from pprint import pprint

from src.retrieval.query_analyzer import QueryAnalyzer


def main():
    analyzer = QueryAnalyzer()

    questions = [
        "What is Lotte van Dijk's annual salary?",
        "What is Lotte van Dijk's monthly gross salary?",
        "What is Thomas de Boer's monthly net salary?",
        "What is the loan term for NB-LOAN-2101?",
        "What is the outstanding loan balance for NB-CUST-3002?",
        "What is the credit assessment result for Lotte van Dijk?",
        "Tell me about the application.",
    ]

    for question in questions:
        result = analyzer.analyze(question)

        print("\nQuestion:", question)
        pprint(result.to_dict())


if __name__ == "__main__":
    main()


from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.agents.rag_agent import ask_agent

app = FastAPI(
    title="NexaBank Loan Intelligence API",
    description="API for the NexaBank document intelligence assistant",
    version="0.1.0",
)

# Local frontend development only.
# Restrict this to your deployed frontend origin before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class SourceResponse(BaseModel):
    source: str = "Unknown"
    document_type: str = "unknown"
    customer_id: str | None = None
    loan_id: str | None = None
    chunk_index: int | None = None


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceResponse]
    search_mode: str
    attempts: int
    basic_validation_passed: bool
    evidence_validation_passed: bool


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "nexabank-api"}


@app.post("/api/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=422,
            detail="Question cannot be empty.",
        )

    try:
        result = ask_agent(question)

        # Return only metadata, not entire document chunks.
        sources = [
            SourceResponse(
                source=s.get("source", "Unknown"),
                document_type=s.get("document_type", "unknown"),
                customer_id=s.get("customer_id"),
                loan_id=s.get("loan_id"),
                chunk_index=s.get("chunk_index"),
            )
            for s in result.get("sources", [])
        ]

        return ChatResponse(
            answer=result.get("answer", ""),
            sources=sources,
            search_mode=result.get("search_mode", "unknown"),
            attempts=result.get("attempts", 0),
            basic_validation_passed=result.get("is_valid", False),
            evidence_validation_passed=result.get(
                "semantic_valid", False
            ),
        )

    except Exception as exc:
        print(f"[API Error] {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="The assistant could not process your question.",
        ) from exc

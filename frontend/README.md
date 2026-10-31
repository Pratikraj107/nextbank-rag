# NexaBank AI — Loan Intelligence Assistant (frontend)

React + TypeScript + Vite + Tailwind CSS frontend for the NexaBank document
question-answering API (`src/api/main.py`).

## Prerequisites

- Node.js 20+ and npm
- The Python backend dependencies installed (`uv sync` in the project root)
- `OPENAI_API_KEY` set in the backend's environment

## Configuration

```bash
cp .env.example .env
```

| Variable            | Default                 | Purpose                          |
| ------------------- | ----------------------- | -------------------------------- |
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Base URL of the FastAPI backend. |

The frontend never handles the OpenAI key; it only calls the backend.

## Running locally

Terminal 1 — from the project root:

```bash
uv run uvicorn src.api.main:app --reload
```

Terminal 2 — from `frontend/`:

```bash
npm install
npm run dev
```

Open <http://localhost:5173>. The dev server is pinned to port 5173 because the
backend's CORS configuration allows only `http://localhost:5173` and
`http://127.0.0.1:5173`.

## Scripts

| Command           | Description                                   |
| ----------------- | --------------------------------------------- |
| `npm run dev`     | Start the dev server on port 5173.            |
| `npm run build`   | Type-check (`tsc -b`) and build to `dist/`.   |
| `npm run lint`    | Lint with oxlint.                             |
| `npm run preview` | Serve the production build locally.           |

## API usage

| Endpoint         | Used for                                                       |
| ---------------- | -------------------------------------------------------------- |
| `GET /health`    | Connection indicator (on load, every 30 s, and on Retry).      |
| `POST /api/chat` | `{ "question": "…" }` → answer, sources, and validation flags. |

Each question is sent on its own; the backend has no conversation memory, so the
conversation exists only in the browser tab and is lost on reload.

Citation labels in answers (`[S1]`, `[S2]`, …) are matched to the returned
`sources` by position (`S1` is the first entry), which is how the backend assigns
them. Several labels can point to different chunks of the same file, so the
evidence panel groups entries by file, customer, and loan.

## Structure

```
src/
  lib/api.ts          API client, response types, and response validation
  lib/sources.ts      Source formatting and grouping
  hooks/useChat.ts    Conversation state and request lifecycle
  hooks/useHealth.ts  Backend health polling
  components/         Sidebar, TopBar, ChatView, ChatMessage, AnswerText,
                      MessageComposer, SuggestedQuestions, SourcePanel,
                      SourceCard, ValidationStatus, ConnectionStatus, Drawer
```

## Document Explorer

`src/components/documents/` holds the Document Explorer (sidebar → Document Explorer, or
`/#/documents`). It uses `src/lib/documents.ts` for the read-only `/api/documents` endpoints
and `src/hooks/useDocuments.ts` for loading, with superseded requests aborted and late
responses ignored. Filters and table columns use container queries, so they adapt to the
space next to the detail panel. Endpoint and ID details are in the root `README.md`.

## Placeholders

"Activity" in the sidebar is a disabled placeholder marked "Soon". The backend has
no endpoint for it yet.

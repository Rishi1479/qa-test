# AI Test Engineering Assistant

Generates test scenarios, test cases (positive / negative / boundary /
edge), acceptance criteria, requirement-to-test traceability, and a
coverage summary from a software requirements document (PDF / DOCX /
Markdown) — via a **LangGraph** multi-agent workflow with tool-using
agents, **Supabase** for original-document storage, and **MongoDB
Atlas** for job state/results/execution logs.

See **`docs/approach.md`** for architecture, the full decision log
(why a multi-agent graph, why some agents call tools via the LLM and
others call tools directly, why local fallbacks exist behind the same
interface as the cloud backends, etc.), database design, and API design
— read this before a review.

## Stack

- FastAPI + Pydantic — API layer
- LangGraph — 9-agent orchestration (`app/agents/graph.py`)
- LangChain (`bind_tools`) — tool-calling for the Requirement Analyzer,
  Boundary & Negative, and Coverage agents
- Groq / Gemini / a deterministic offline mock — LLM backend
  (`LLM_PROVIDER` in `.env`)
- MongoDB Atlas (pymongo) — job state, results, execution logs
  (local-JSON fallback if `MONGODB_URI` unset)
- Supabase Storage — original document storage
  (local-disk fallback if `SUPABASE_URL`/`SUPABASE_KEY` unset)
- Docling (preferred) with PyMuPDF/python-docx fallback — document parsing
- LangSmith — tracing (`LANGSMITH_TRACING=true`)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` defaults to `LLM_PROVIDER=mock` and no cloud credentials, so the
whole pipeline runs and tests pass with **zero external services or API
keys**. To use the real backends:

- `LLM_PROVIDER=groq` + `GROQ_API_KEY=...` (free tier: console.groq.com),
  or `LLM_PROVIDER=gemini` + `GEMINI_API_KEY=...`
- `MONGODB_URI=mongodb+srv://...` pointing at an Atlas cluster
- `SUPABASE_URL=...` + `SUPABASE_KEY=...` + a storage bucket named per
  `SUPABASE_BUCKET` (default `requirement-documents`)
- `LANGSMITH_TRACING=true` + `LANGSMITH_API_KEY=...` to trace every node

## Run

```bash
uvicorn app.main:app --reload
```

API docs (Swagger UI): http://localhost:8000/docs
`GET /` reports which backend (cloud vs local fallback) each tool is
actually using, so it's obvious at a glance during a review.

## Tests

```bash
pytest tests/ -v
```

Covers: requirement extraction (FR-N style + generic fallback),
requirement/output validation, the boundary-value and coverage tools,
local-fallback persistence round-trips, and a full end-to-end LangGraph
run in mock mode (no API key needed).

## Walkthrough

```bash
# 1. Upload a requirements doc (two sample docs are in data/:
#    a v1/v2 pair for the telehealth appointment system assignment)
curl -X POST http://localhost:8000/upload \
  -F "file=@data/telehealth_requirements_v1.pdf"
# -> {"job_id": "JOB-XXXXXXXXXX", "filename": "...", "status": "uploaded", ...}

# 2. Run the multi-agent workflow
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"job_id": "JOB-XXXXXXXXXX"}'
# -> full JSON: requirements, scenarios, test_cases, acceptance_criteria,
#    traceability, coverage

# 3. List jobs / inspect one
curl http://localhost:8000/jobs
curl http://localhost:8000/jobs/JOB-XXXXXXXXXX

# 4. Export
curl "http://localhost:8000/jobs/JOB-XXXXXXXXXX/download?fmt=markdown" -o report.md
curl "http://localhost:8000/jobs/JOB-XXXXXXXXXX/download?fmt=csv" -o report.csv

# 5. Re-run after changing a prompt/agent, bypassing the cache
curl -X POST http://localhost:8000/generate \
  -H "Content-Type: application/json" \
  -d '{"job_id": "JOB-XXXXXXXXXX", "force_regenerate": true}'

# 6. Delete
curl -X DELETE http://localhost:8000/jobs/JOB-XXXXXXXXXX
```

`data/telehealth_requirements_v2.pdf` is a v2 of the same spec with more
functional requirements added (Stripe payments, notifications,
prescriptions, waiting room) and more non-functional requirements
(HIPAA, latency) — useful as a second, larger document to demo against
live, or to show how the pipeline scales with requirement count.

## Project layout

```
app/
  api/          FastAPI routers: documents (upload), generation (generate/jobs/download/delete)
  agents/       LangGraph state, prompts, LLM client, 9 agent nodes, graph assembly
  parsing/      Docling-based document parser (+ fallback), deterministic requirement extractor
  tools/        Supabase tool, MongoDB Atlas tool, validation, search, boundary,
                coverage, JSON formatter, export tools
  schemas/      Pydantic models shared across API/agents/tools
tests/          pytest suite (extraction, validation, tools, fallback persistence, e2e graph)
docs/
  approach.md   Architecture, decision log, database/API design, known limitations (read this)
data/           Sample requirement documents to demo against
storage/        Local fallback storage (created at runtime if Mongo/Supabase are unset)
```

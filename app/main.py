from fastapi import FastAPI
from app.api import documents, generation
from app.config import settings

app = FastAPI(
    title="AI Test Engineering Assistant",
    description="Generates test scenarios, test cases, boundary/edge cases, acceptance "
                "criteria, traceability, and coverage from a software requirements "
                "document, via a LangGraph multi-agent workflow.",
    version="2.0.0",
)

app.include_router(documents.router)
app.include_router(generation.router)


@app.get("/")
def root():
    return {
        "service": "AI Test Engineering Assistant",
        "docs": "/docs",
        "llm_provider": settings.LLM_PROVIDER,
        "mongodb_backend": "mongodb_atlas" if settings.mongo_enabled else "local_json_fallback",
        "storage_backend": "supabase" if settings.supabase_enabled else "local_disk_fallback",
        "langsmith_tracing": settings.langsmith_enabled,
    }


@app.get("/health")
def health():
    return {"status": "ok"}

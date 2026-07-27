import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="langgraph")
warnings.filterwarnings("ignore", module="langchain")
warnings.filterwarnings("ignore", message=".*allowed_objects.*")

import logging

import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("app.log"),
        logging.StreamHandler(sys.stdout)
    ]
)

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

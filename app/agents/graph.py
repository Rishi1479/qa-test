"""
  START
    ↓
  document_parser_node          (Python) — parse + extract + validate requirements
    ↓
  requirement_intelligence      (LLM 1) — enrich all FRs into 27-field objects
    ↓
  qa_artifact_generator         (LLM 2) — generate all QA artifacts in one shot
    ↓
  validation_node               (Python) — orphan-ID check, schema validation
    ↓
  json_formatter_node           (Python) — assemble final JSON + Markdown
    ↓
  persistence_node              (Python) — save to MongoDB + Supabase
    ↓
  END
"""
from __future__ import annotations

# pyrefly: ignore [missing-import]
from langgraph.graph import StateGraph, END
# pyrefly: ignore [missing-import]
from langgraph.checkpoint.memory import MemorySaver

from app.agents.state import GraphState
from app.agents.requirement_intelligence_agent import RequirementIntelligenceAgent
from app.agents.qa_artifact_generator_agent import QAArtifactGeneratorAgent
from app.agents.python_nodes import (
    document_parser_node,
    validation_node,
    json_formatter_node,
    persistence_node,
)
from app.tools.mongodb_tool import mongodb_tool


def build_workflow():
    graph = StateGraph(GraphState)

    # ---- Nodes ----
    graph.add_node("document_parser",          document_parser_node)
    graph.add_node("requirement_intelligence", RequirementIntelligenceAgent())
    graph.add_node("qa_artifact_generator",    QAArtifactGeneratorAgent())
    graph.add_node("validation_node",          validation_node)
    graph.add_node("json_formatter_node",      json_formatter_node)
    graph.add_node("persistence_node",         persistence_node)

    # ---- Linear edges ----
    graph.set_entry_point("document_parser")
    graph.add_edge("document_parser",          "requirement_intelligence")
    graph.add_edge("requirement_intelligence", "qa_artifact_generator")
    graph.add_edge("qa_artifact_generator",    "validation_node")
    graph.add_edge("validation_node",          "json_formatter_node")
    graph.add_edge("json_formatter_node",      "persistence_node")
    graph.add_edge("persistence_node",         END)

    # Use MongoDBSaver if mongo is enabled, else in-memory checkpointer
    checkpointer = MemorySaver()
    if mongodb_tool.backend == "mongodb":
        try:
            from langgraph.checkpoint.mongodb import MongoDBSaver
            mongo_client = mongodb_tool.get_client()
            if mongo_client:
                checkpointer = MongoDBSaver(mongo_client)
        except ImportError:
            pass

    return graph.compile(checkpointer=checkpointer)


_compiled_workflow = None


def get_workflow():
    global _compiled_workflow
    if _compiled_workflow is None:
        _compiled_workflow = build_workflow()
    return _compiled_workflow

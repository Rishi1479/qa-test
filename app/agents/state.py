"""
Shared LangGraph state. Every node reads from and writes to this single
TypedDict — this IS how "state is maintained across execution" within
one run of the graph (persistence *across* runs/jobs is MongoDB Atlas,
see tools/mongodb_tool.py).

Design notes
------------
* ``total=False`` — all keys are optional so workflow.invoke() only needs to
  supply the keys that are known at the call site (job_id, requirements, …);
  the rest are filled in by the agents.

* Annotated fields with ``operator.add`` are parallel-safe accumulators.
  LangGraph merges concurrent writes by calling the reducer on every update,
  so parallel branches can each append their subset without one overwriting
  the other.  Fields where only ONE agent writes (e.g. coverage, final_json)
  are plain types — last-write wins, which is fine when only one writer exists.

* Context fields (session_id … execution_metadata) are set by the FastAPI
  endpoint before invoking the graph so the PersistenceAgent can use them
  without importing FastAPI internals.
"""
from __future__ import annotations

import operator
from typing import Annotated, Optional, TypedDict

from app.schemas.schemas import (
    AcceptanceCriterion,
    CoverageSummary,
    EnrichedRequirement,
    Requirement,
    ScenarioItem,
    TestCase,
    TraceabilityRow,
)


class GraphState(TypedDict, total=False):
    # ------------------------------------------------------------------
    # Context — set by the caller (FastAPI endpoint) before graph.invoke()
    # ------------------------------------------------------------------
    job_id: str
    session_id: Optional[str]      # optional browser/API session identifier
    user_id: Optional[str]         # optional user identifier (auth future)
    project_id: Optional[str]      # optional project grouping identifier
    document_id: Optional[str]     # optional document identifier
    storage_url: Optional[str]     # Supabase (or fallback) public URL of the uploaded file
    parsed_text: Optional[str]     # raw text output from parse_document()
    execution_metadata: dict       # {"started_at": ISO-8601, …} set by the endpoint

    # ------------------------------------------------------------------
    # Pipeline data — written by individual agents
    # ------------------------------------------------------------------
    requirements: list[Requirement]
    enriched_requirements: list[EnrichedRequirement]

    scenarios: list[ScenarioItem]
    test_cases: list[TestCase]
    acceptance_criteria: list[AcceptanceCriterion]
    traceability: list[TraceabilityRow]
    coverage: CoverageSummary

    # ------------------------------------------------------------------
    # Final outputs — written by JsonFormatterAgent and PersistenceAgent
    # ------------------------------------------------------------------
    final_json: dict
    markdown_report: str           # Markdown rendering of the report (saved by PersistenceAgent)

    # ------------------------------------------------------------------
    # Parallel-safe accumulators (operator.add reducer)
    # ------------------------------------------------------------------
    validation_notes: Annotated[list[str], operator.add]
    node_timings: Annotated[list[dict], operator.add]
    errors: Annotated[list[str], operator.add]

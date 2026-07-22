"""
JSON Formatter Tool
----------------------
Pure assembly, no LLM call, no business logic: takes the typed pieces
each agent already produced (Pydantic models) and serializes them into
the one final response/export shape. Kept separate from the JSON
Formatter *agent* (agents/nodes.py) -- the agent decides the JSON is
ready and calls output validation; this tool does the mechanical
`model_dump()` assembly the agent relies on.
"""
from __future__ import annotations
from app.schemas.schemas import (
    Requirement, ScenarioItem, TestCase, AcceptanceCriterion,
    TraceabilityRow, CoverageSummary,
)


def assemble_final_json(
    job_id: str,
    requirements: list[Requirement],
    scenarios: list[ScenarioItem],
    test_cases: list[TestCase],
    acceptance_criteria: list[AcceptanceCriterion],
    traceability: list[TraceabilityRow],
    coverage: CoverageSummary,
) -> dict:
    return {
        "job_id": job_id,
        "requirements": [r.model_dump() for r in requirements],
        "scenarios": [s.model_dump() for s in scenarios],
        "test_cases": [t.model_dump() for t in test_cases],
        "acceptance_criteria": [a.model_dump() for a in acceptance_criteria],
        "traceability": [t.model_dump() for t in traceability],
        "coverage": coverage.model_dump(),
    }

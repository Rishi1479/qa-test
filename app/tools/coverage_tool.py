"""
Coverage Calculator Tool
---------------------------
Deterministic arithmetic over the traceability map -- explicitly NOT
delegated to the LLM, because "what % of requirements have >=1 test
case" is a plain count, and LLMs are unreliable at producing correct
percentages/consistent counts over long lists.
"""
from __future__ import annotations
from langchain_core.tools import tool
from app.schemas.schemas import Requirement, TraceabilityRow, CoverageSummary


@tool
def compute_coverage(requirement_ids: list[str], covered_requirement_ids: list[str]) -> str:
    """Compute coverage percentage given the full list of requirement ids
    and the subset that have at least one test case."""
    total = len(set(requirement_ids))
    covered = len(set(covered_requirement_ids) & set(requirement_ids))
    pct = round((covered / total) * 100, 1) if total else 0.0
    return f"total_requirements={total}, covered_requirements={covered}, coverage_percent={pct}"


def build_traceability_and_coverage(
    requirements: list[Requirement],
    scenario_by_req: dict[str, list[str]],
    testcase_by_req: dict[str, list[str]],
    priority_by_req: dict[str, str],
) -> tuple[list[TraceabilityRow], CoverageSummary]:
    """The non-LLM half of Agent 7/8: assembling the actual traceability
    table is pure bookkeeping once agents 2-6 have produced their ids."""
    rows = []
    covered_ids = []
    priority_breakdown = {"High": 0, "Medium": 0, "Low": 0}

    for req in requirements:
        scenario_ids = scenario_by_req.get(req.req_id, [])
        test_ids = testcase_by_req.get(req.req_id, [])
        covered = bool(test_ids)
        if covered:
            covered_ids.append(req.req_id)
        rows.append(TraceabilityRow(
            req_id=req.req_id,
            scenario_ids=scenario_ids,
            test_ids=test_ids,
            covered=covered,
        ))
        p = priority_by_req.get(req.req_id, "Medium")
        priority_breakdown[p] = priority_breakdown.get(p, 0) + 1

    total = len(requirements)
    covered_n = len(covered_ids)
    summary = CoverageSummary(
        total_requirements=total,
        covered_requirements=covered_n,
        coverage_percent=round((covered_n / total) * 100, 1) if total else 0.0,
        priority_breakdown=priority_breakdown,
    )
    return rows, summary

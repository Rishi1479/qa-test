
from __future__ import annotations

import json
import uuid

from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.base import BaseAgent, timed, parse_json
from app.agents.llm import get_llm
from app.agents import prompts
from app.agents.state import GraphState
from app.config import settings
from app.schemas.schemas import (
    AcceptanceCriterion,
    CoverageSummary,
    EnrichedRequirement,
    ScenarioItem,
    TestCase,
    TraceabilityRow,
)
from app.tools.boundary_tool import extract_boundary_values

_MOCK = settings.LLM_PROVIDER == "mock"

# ---------------------------------------------------------------------------
# Mock-mode artifact generators
# ---------------------------------------------------------------------------

def _mock_scenarios(enriched: list[EnrichedRequirement]) -> list[ScenarioItem]:
    
    scenarios: list[ScenarioItem] = []
    for req in enriched:
        base = [
            (f"Valid {req.title.lower()} — happy path", "positive"),
            (f"Invalid input for {req.title.lower()}", "negative"),
        ]
        # Add boundary scenarios for every numeric limit
        for limit in req.numeric_limits[:2]:
            base.append((f"Boundary: {limit} for {req.title.lower()}", "boundary"))
        # Add edge case scenarios
        for ec in req.edge_cases[:1]:
            base.append((f"Edge case: {ec}", "edge"))
        # Ensure at least one edge scenario per requirement
        if not req.edge_cases:
            base.append((f"Edge: concurrent access on {req.title.lower()}", "edge"))

        for i, (title, category) in enumerate(base, start=1):
            scenarios.append(ScenarioItem(
                scenario_id=f"SC-{req.req_id}-{i:02d}",
                req_id=req.req_id,
                title=title,
                category=category,
            ))
    return scenarios

def _mock_test_cases(
    enriched: list[EnrichedRequirement],
    scenarios: list[ScenarioItem],
) -> list[TestCase]:
    
    req_by_id = {r.req_id: r for r in enriched}
    test_cases: list[TestCase] = []
    counters: dict[str, int] = {}

    for sc in scenarios:
        req = req_by_id.get(sc.req_id)
        if not req:
            continue
        counters[req.req_id] = counters.get(req.req_id, 0) + 1
        n = counters[req.req_id]
        is_neg = sc.category == "negative"
        is_boundary = sc.category == "boundary"
        is_edge = sc.category == "edge"

        # Build realistic test data based on category
        if is_neg:
            test_data = [
                "email=invalid-email-format",
                "password=abc (too short)",
                "email= (blank)",
            ]
            expected = (
                "System rejects the request with HTTP 400 or 422 and returns "
                "an appropriate error message describing the validation failure"
            )
            preconditions = [f"System is operational; {req.req_id} preconditions do NOT apply"]
            postconditions = ["No state change in the system"]
        elif is_boundary:
            # Extract real boundary values from the requirement
            bound_str = extract_boundary_values.invoke({"requirement_text": req.description})
            test_data = [bound_str[:200]] if "No explicit" not in bound_str else [
                "value=boundary-min-1 (invalid)",
                "value=boundary-min (valid)",
                "value=boundary-min+1 (valid)",
            ]
            expected = (
                "System accepts values at and above the minimum boundary; "
                "rejects values below the minimum boundary"
            )
            preconditions = [f"Boundary conditions for {req.req_id} are set up"]
            postconditions = ["System state consistent with boundary validation"]
        elif is_edge:
            test_data = [
                "input=<script>alert('xss')</script>",
                "input=\\x00\\x01 (null bytes)",
                "Concurrent requests from two users simultaneously",
            ]
            expected = (
                "System handles the edge condition safely without crashing, "
                "corrupting state, or exposing sensitive data"
            )
            preconditions = ["System is under normal operational load"]
            postconditions = ["System remains stable and consistent"]
        else:
            # Positive test case — use realistic sample data
            example_parts = []
            if req.example_input:
                example_parts.append(req.example_input)
            else:
                example_parts = [
                    "email=john.doe@example.com",
                    "password=Password123!",
                ]
            test_data = example_parts
            expected = (
                req.example_output
                if req.example_output
                else f"HTTP 200; system completes the action described in {req.req_id}"
            )
            preconditions = req.preconditions or [f"User meets all preconditions of {req.req_id}"]
            postconditions = req.postconditions or [f"State updated as described in {req.req_id}"]

        test_cases.append(TestCase(
            test_id=f"TC-{req.req_id}-{n:02d}",
            req_id=req.req_id,
            scenario_id=sc.scenario_id,
            title=sc.title,
            type=sc.category,
            priority=req.priority,
            preconditions=preconditions,
            steps=[
                f"Set up preconditions for {req.req_id}",
                f"Execute the action described in scenario: {sc.title}",
                "Observe the system response",
                "Verify the expected result",
            ],
            test_data=test_data,
            expected_result=expected,
            postconditions=postconditions,
        ))

    return test_cases

def _mock_acceptance_criteria(enriched: list[EnrichedRequirement]) -> list[AcceptanceCriterion]:
    criteria: list[AcceptanceCriterion] = []
    for req in enriched:
        if req.acceptance_criteria:
            # Try to parse the first AC as Given/When/Then
            ac_text = req.acceptance_criteria[0]
            criteria.append(AcceptanceCriterion(
                req_id=req.req_id,
                given=f"the preconditions of {req.req_id} are fully satisfied",
                when=f'the user or system performs the action described in "{req.title}"',
                then=ac_text if ac_text else (
                    req.example_output or
                    f"the system behaves as described in {req.req_id} with no errors"
                ),
            ))
        else:
            criteria.append(AcceptanceCriterion(
                req_id=req.req_id,
                given=f"the preconditions of {req.req_id} are fully satisfied",
                when=f'the user or system performs the action described in "{req.title}"',
                then=(
                    req.example_output or
                    f"the system responds as described in {req.req_id} within the defined constraints"
                ),
            ))
    return criteria

def _build_traceability_and_coverage(
    enriched: list[EnrichedRequirement],
    scenarios: list[ScenarioItem],
    test_cases: list[TestCase],
) -> tuple[list[TraceabilityRow], CoverageSummary]:
    scenario_by_req: dict[str, list[str]] = {}
    for sc in scenarios:
        scenario_by_req.setdefault(sc.req_id, []).append(sc.scenario_id)

    testcase_by_req: dict[str, list[str]] = {}
    for tc in test_cases:
        testcase_by_req.setdefault(tc.req_id, []).append(tc.test_id)

    priority_breakdown: dict[str, int] = {"Critical": 0, "High": 0, "Medium": 0, "Low": 0}
    covered_count = 0
    missing_coverage: list[str] = []
    rows: list[TraceabilityRow] = []

    for req in enriched:
        tc_ids = testcase_by_req.get(req.req_id, [])
        covered = bool(tc_ids)
        if covered:
            covered_count += 1
        else:
            missing_coverage.append(req.req_id)
        rows.append(TraceabilityRow(
            req_id=req.req_id,
            scenario_ids=scenario_by_req.get(req.req_id, []),
            test_ids=tc_ids,
            covered=covered,
        ))
        p = req.priority
        priority_breakdown[p] = priority_breakdown.get(p, 0) + 1

    total = len(enriched)
    summary = CoverageSummary(
        total_requirements=total,
        covered_requirements=covered_count,
        coverage_percent=round((covered_count / total) * 100, 1) if total else 0.0,
        priority_breakdown=priority_breakdown,
        positive_count=sum(1 for tc in test_cases if tc.type == "positive"),
        negative_count=sum(1 for tc in test_cases if tc.type == "negative"),
        boundary_count=sum(1 for tc in test_cases if tc.type == "boundary"),
        edge_count=sum(1 for tc in test_cases if tc.type == "edge"),
        missing_coverage=missing_coverage,
    )
    return rows, summary

# ---------------------------------------------------------------------------
# LLM response parser
# ---------------------------------------------------------------------------

def _parse_llm_artifacts(
    text: str,
    enriched: list[EnrichedRequirement],
) -> tuple[list[ScenarioItem], list[TestCase], list[AcceptanceCriterion], list[TraceabilityRow], CoverageSummary]:
    
    raw = parse_json(text, {})
    if not isinstance(raw, dict):
        return _fallback_artifacts(enriched)

    # --- Scenarios ---
    scenarios: list[ScenarioItem] = []
    for item in raw.get("scenarios", []):
        try:
            scenarios.append(ScenarioItem(**item))
        except Exception:
            pass

    # --- Test Cases ---
    test_cases: list[TestCase] = []
    counters: dict[str, int] = {}
    for item in raw.get("test_cases", []):
        try:
            # Ensure test_id is present
            if not item.get("test_id"):
                rid = item.get("req_id", "UNKNOWN")
                counters[rid] = counters.get(rid, 0) + 1
                item["test_id"] = f"TC-{rid}-{counters[rid]:02d}"
            # Ensure priority is valid
            if item.get("priority") not in ("Critical", "High", "Medium", "Low"):
                item["priority"] = "Medium"
            test_cases.append(TestCase(**item))
        except Exception:
            pass

    # --- Acceptance Criteria ---
    acceptance_criteria: list[AcceptanceCriterion] = []
    for item in raw.get("acceptance_criteria", []):
        try:
            acceptance_criteria.append(AcceptanceCriterion(**item))
        except Exception:
            pass

    # --- Traceability ---
    traceability: list[TraceabilityRow] = []
    for item in raw.get("traceability", []):
        try:
            traceability.append(TraceabilityRow(**item))
        except Exception:
            pass

    # --- Coverage ---
    cov_raw = raw.get("coverage", {})
    try:
        coverage = CoverageSummary(**cov_raw)
    except Exception:
        _, coverage = _build_traceability_and_coverage(enriched, scenarios, test_cases)

    # If LLM returned empty lists, fall back to mock generation
    if not scenarios or not test_cases:
        return _fallback_artifacts(enriched)

    # If traceability is missing, compute it deterministically
    if not traceability:
        traceability, coverage = _build_traceability_and_coverage(enriched, scenarios, test_cases)

    return scenarios, test_cases, acceptance_criteria, traceability, coverage

def _fallback_artifacts(
    enriched: list[EnrichedRequirement],
) -> tuple[list[ScenarioItem], list[TestCase], list[AcceptanceCriterion], list[TraceabilityRow], CoverageSummary]:
    
    scenarios = _mock_scenarios(enriched)
    test_cases = _mock_test_cases(enriched, scenarios)
    acceptance_criteria = _mock_acceptance_criteria(enriched)
    traceability, coverage = _build_traceability_and_coverage(enriched, scenarios, test_cases)
    return scenarios, test_cases, acceptance_criteria, traceability, coverage

# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------

class QAArtifactGeneratorAgent(BaseAgent):
    

    def run(self, state: GraphState) -> dict:
        updates: dict = {}

        with timed("qa_artifact_generator", updates):
            enriched: list[EnrichedRequirement] = state.get("enriched_requirements", [])

            if not enriched:
                updates.setdefault("errors", []).append(
                    "qa_artifact_generator: no enriched_requirements in state"
                )
                updates.update({
                    "scenarios": [], "test_cases": [], "acceptance_criteria": [],
                    "traceability": [], "coverage": CoverageSummary(
                        total_requirements=0, covered_requirements=0, coverage_percent=0.0
                    ),
                })
                return updates

            if _MOCK:
                scenarios = _mock_scenarios(enriched)
                test_cases = _mock_test_cases(enriched, scenarios)
                acceptance_criteria = _mock_acceptance_criteria(enriched)
                traceability, coverage = _build_traceability_and_coverage(
                    enriched, scenarios, test_cases
                )
            else:
                # ---- Real mode: single LLM call ----
                llm = get_llm()
                user_msg = json.dumps(
                    [e.model_dump() for e in enriched],
                    indent=2,
                    ensure_ascii=False,
                )
                try:
                    resp = llm.invoke([
                        SystemMessage(content=prompts.QA_ARTIFACT_GENERATOR),
                        HumanMessage(content=user_msg),
                    ])
                    scenarios, test_cases, acceptance_criteria, traceability, coverage = (
                        _parse_llm_artifacts(resp.content, enriched)
                    )
                except Exception as exc:
                    updates.setdefault("errors", []).append(
                        f"qa_artifact_generator: {exc}"
                    )
                    scenarios, test_cases, acceptance_criteria, traceability, coverage = (
                        _fallback_artifacts(enriched)
                    )

        updates["scenarios"] = scenarios
        updates["test_cases"] = test_cases
        updates["acceptance_criteria"] = acceptance_criteria
        updates["traceability"] = traceability
        updates["coverage"] = coverage
        return updates

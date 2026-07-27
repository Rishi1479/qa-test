
from __future__ import annotations

import json
import logging
import uuid

logger = logging.getLogger(__name__)

# pyrefly: ignore [missing-import]
from langchain_core.messages import SystemMessage, HumanMessage
# pyrefly: ignore [missing-import]
from langchain_core.tracers.context import collect_runs

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
# Helpers
# ---------------------------------------------------------------------------

def _parse_boundary_output(bound_str: str) -> list[str]:
    """Parse the structured output of extract_boundary_values into individual
    test-data entries with concrete numeric values.

    The boundary tool returns lines like:
        range 8-20: boundary values -> 7(invalid), 8(valid-min), 9(valid), ...
        minimum 8: boundary values -> 7(invalid), 8(valid), 9(valid)
    We parse these into:
        ["value=7 (invalid, below-min)", "value=8 (valid, min-boundary)", ...]
    """
    if not bound_str or "No explicit" in bound_str:
        return []
    import re
    entries: list[str] = []
    for line in bound_str.splitlines():
        line = line.strip()
        if not line:
            continue
        # Extract the label part (e.g. "range 8-20") and the values part
        arrow_idx = line.find("->")
        if arrow_idx == -1:
            entries.append(line)
            continue
        label = line[:arrow_idx].strip()
        values_part = line[arrow_idx + 2:].strip()
        # Parse individual values: "7(invalid)", "8(valid-min)", etc.
        for val_match in re.finditer(r"([\d.]+)\(([^)]+)\)", values_part):
            value = val_match.group(1)
            validity = val_match.group(2)
            entries.append(f"value={value} ({validity}, {label})")
    return entries


# Keyword-to-sample-data mapping for context-aware test data generation
_TEST_DATA_TEMPLATES: list[tuple[list[str], list[str]]] = [
    (
        ["register", "create an account", "sign up"],
        ["email=new.user@example.com", "password=Str0ngP@ss1!", "name=Jane Doe"],
    ),
    (
        ["availability", "schedule", "time slot", "recurring"],
        ["provider_id=PROV-001", "day=Monday", 'slots=["09:00-09:30","09:30-10:00"]'],
    ),
    (
        # Video/telemedicine must come before booking because both may
        # mention "appointment" — the video keywords are more specific.
        ["video", "call", "telemedicine", "consultation", "link"],
        ["appointment_id=APT-001", "participant_role=patient", "device=desktop"],
    ),
    (
        ["book", "reservation"],
        ["patient_id=PAT-001", "provider_id=PROV-001", "slot=2024-01-15T09:00"],
    ),
    (
        ["login", "sign in", "authentication"],
        ["email=jane.doe@example.com", "password=SecureP@ss1!"],
    ),
    (
        ["search", "find", "filter", "query"],
        ["query=cardiology", "location=New York", "radius_km=25"],
    ),
    (
        ["payment", "billing", "charge", "invoice"],
        ["amount=150.00", "currency=USD", "payment_method=credit_card"],
    ),
    (
        ["notification", "alert", "reminder"],
        ["recipient=user@example.com", "type=appointment_reminder", "channel=email"],
    ),
]


def _generate_sample_test_data(req: EnrichedRequirement) -> list[str]:
    """Generate context-aware test data by matching requirement keywords."""
    if req.example_input:
        return [req.example_input]

    lower_desc = (req.title + " " + req.description).lower()
    for keywords, sample_data in _TEST_DATA_TEMPLATES:
        if any(kw in lower_desc for kw in keywords):
            return sample_data

    # Fallback: derive from input_parameters if available
    if req.input_parameters:
        return [f"{param}=<valid_value>" for param in req.input_parameters]

    return [f"input=valid data for {req.title}"]


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

        # --- Deduplicate scenarios by (req_id, title) ---
        seen_titles: set[str] = set()
        counter = 0
        for title, category in base:
            dedup_key = f"{req.req_id}::{title}"
            if dedup_key in seen_titles:
                continue
            seen_titles.add(dedup_key)
            counter += 1
            scenarios.append(ScenarioItem(
                scenario_id=f"SC-{req.req_id}-{counter:02d}",
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
            # Extract real boundary values and parse into concrete test data
            bound_str = extract_boundary_values.invoke({"requirement_text": req.description})
            parsed_boundaries = _parse_boundary_output(bound_str)
            if parsed_boundaries:
                test_data = parsed_boundaries
            elif req.numeric_limits:
                # Fall back to pre-computed numeric limits from enrichment
                test_data = [f"value={lim}" for lim in req.numeric_limits[:3]]
            else:
                test_data = [f"No numeric constraints found for {req.req_id}"]
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
            # Positive test case — use context-aware sample data
            test_data = _generate_sample_test_data(req)
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
        # ---- Derive specific Given from preconditions / context ----
        lower_desc = req.description.lower()
        if req.preconditions and req.preconditions[0] != f"Preconditions for {req.req_id} are satisfied":
            given = req.preconditions[0]
        elif "authenticated" in lower_desc or "auth" in lower_desc:
            given = "the user is authenticated and on the relevant page"
        elif "register" in lower_desc or "create an account" in lower_desc:
            given = "the user is on the registration page with valid form fields visible"
        else:
            given = f"the system is operational and {req.req_id} preconditions are met"

        # ---- Derive specific When from title ----
        when = f'the user performs "{req.title.lower()}" with valid inputs'

        # ---- Derive specific Then from validation rules / description ----
        if req.validation_rules:
            def _vr_str(vr) -> str:
                if hasattr(vr, "field"):
                    return f"{vr.field} must satisfy {vr.rule} = {vr.value}"
                if isinstance(vr, dict):
                    return f"{vr.get('field','?')} must satisfy {vr.get('rule','?')} = {vr.get('value','?')}"
                return str(vr)
            then = "the system validates: " + "; ".join(_vr_str(vr) for vr in req.validation_rules)
        elif req.example_output:
            then = req.example_output
        else:
            then = req.description.rstrip(".")

        criteria.append(AcceptanceCriterion(
            req_id=req.req_id,
            given=given,
            when=when,
            then=then,
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

    # --- Scenarios (with dedup by scenario_id) ---
    scenarios: list[ScenarioItem] = []
    seen_scenario_ids: set[str] = set()
    for item in raw.get("scenarios", []):
        try:
            sc = ScenarioItem(**item)
            if sc.scenario_id in seen_scenario_ids:
                continue
            seen_scenario_ids.add(sc.scenario_id)
            scenarios.append(sc)
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
                run_id_str = None
                raw_response = None
            else:
                # ---- Real mode: single LLM call ----
                llm = get_llm()
                user_msg = json.dumps(
                    [e.model_dump() for e in enriched],
                    indent=2,
                    ensure_ascii=False,
                )
                run_id_str = None
                raw_response = None
                try:
                    with collect_runs() as cb:
                        logger.info("llm start")
                        resp = llm.invoke([
                            SystemMessage(content=prompts.QA_ARTIFACT_GENERATOR),
                            HumanMessage(content=user_msg),
                        ])
                        logger.info("llm end")
                        
                        if cb.traced_runs:
                            run_id_str = str(cb.traced_runs[0].id)
                            
                    raw_response = resp.content
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

            # Artifacts (requirements, test_cases, etc.) are no longer
            # persisted incrementally to Postgres. The persistence_node
            # will write everything to MongoDB at the end of the pipeline.

        updates["scenarios"] = scenarios
        updates["test_cases"] = test_cases
        updates["acceptance_criteria"] = acceptance_criteria
        updates["traceability"] = traceability
        updates["coverage"] = coverage
        return updates

"""
End-to-end LangGraph workflow test, run in LLM_PROVIDER=mock (the
default), so it requires no API key and no network access -- this is
the test a grader can run immediately after `pip install -r
requirements.txt` to see the whole multi-agent pipeline execute.
"""
from app.parsing.requirement_extractor import extract_requirements
from app.tools.validation_tool import validate_requirements
from app.agents.graph import get_workflow

SAMPLE_DOC = """
● FR-1: Patient Registration and Authentication
  ○ Description: The system must allow new patients to create an account using an
    email address and a password of at least 8 characters.
  ○ Validation Conditions: Password must be 8-20 characters and contain a number.
  ○ Edge Case: Patient attempts to register with an email that already exists.
● FR-3: Appointment Booking
  ○ Description: Authenticated patients must be able to select a provider and book
    an open 30-minute availability slot.
  ○ Edge Case: Two patients attempt to book the exact same slot simultaneously.
"""


def _run():
    reqs = validate_requirements(extract_requirements(SAMPLE_DOC))
    workflow = get_workflow()
    return workflow.invoke({"job_id": "JOB-TEST", "requirements": reqs})


def test_graph_produces_final_json_with_all_sections():
    state = _run()
    payload = state["final_json"]
    for key in ("requirements", "scenarios", "test_cases", "acceptance_criteria",
                "traceability", "coverage"):
        assert key in payload

    assert len(payload["requirements"]) == 2
    assert len(payload["test_cases"]) >= len(payload["scenarios"])


def test_graph_full_coverage_when_every_requirement_has_a_test_case():
    state = _run()
    coverage = state["final_json"]["coverage"]
    assert coverage["total_requirements"] == 2
    assert coverage["coverage_percent"] == 100.0


def test_boundary_case_generated_for_quantified_requirement():
    state = _run()
    boundary_titles = [t for t in state["final_json"]["test_cases"] if t["type"] == "boundary"]
    assert len(boundary_titles) >= 1


def test_node_timings_recorded_for_every_agent():
    state = _run()
    node_names = {t["node"] for t in state["node_timings"]}
    assert {"requirement_analyzer", "scenario_generator", "test_case_generator",
            "boundary_negative", "edge_case", "acceptance_criteria",
            "traceability_and_coverage", "json_formatter"} <= node_names

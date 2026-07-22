from app.tools.boundary_tool import extract_boundary_values
from app.tools.coverage_tool import compute_coverage, build_traceability_and_coverage
from app.schemas.schemas import Requirement


def test_extract_boundary_values_finds_range():
    out = extract_boundary_values.invoke({"requirement_text": "Password must be 8-20 characters."})
    assert "range 8-20" in out
    assert "7(invalid)" in out
    assert "21(invalid)" in out


def test_extract_boundary_values_no_constraints():
    out = extract_boundary_values.invoke({"requirement_text": "The system must look nice."})
    assert "No explicit numeric constraints" in out


def test_compute_coverage_tool():
    out = compute_coverage.invoke({
        "requirement_ids": ["FR-1", "FR-2", "FR-3"],
        "covered_requirement_ids": ["FR-1", "FR-2"],
    })
    assert "total_requirements=3" in out
    assert "covered_requirements=2" in out
    assert "coverage_percent=66.7" in out


def test_build_traceability_and_coverage():
    reqs = [Requirement(req_id="FR-1", title="A", raw_text="", description="a"),
            Requirement(req_id="FR-2", title="B", raw_text="", description="b")]
    rows, summary = build_traceability_and_coverage(
        reqs,
        scenario_by_req={"FR-1": ["SC-FR-1-01"]},
        testcase_by_req={"FR-1": ["TC-FR-1-01"]},
        priority_by_req={"FR-1": "High", "FR-2": "Medium"},
    )
    assert summary.total_requirements == 2
    assert summary.covered_requirements == 1
    assert summary.coverage_percent == 50.0
    assert rows[1].covered is False

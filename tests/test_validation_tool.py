from app.schemas.schemas import Requirement
from app.tools.validation_tool import validate_requirements, validate_output


def test_flags_vague_requirement():
    reqs = [Requirement(req_id="FR-1", title="Password rule", raw_text="",
                         description="Password should be secure.")]
    out = validate_requirements(reqs)
    assert out[0].is_ambiguous is True
    assert "secure" in out[0].ambiguity_reason


def test_does_not_flag_quantified_requirement():
    reqs = [Requirement(req_id="FR-1", title="Password rule", raw_text="",
                         description="Password must be at least 8 characters and secure against brute force.")]
    out = validate_requirements(reqs)
    assert out[0].is_ambiguous is False


def test_flags_duplicate_titles():
    reqs = [
        Requirement(req_id="FR-1", title="Login", raw_text="", description="a"),
        Requirement(req_id="FR-2", title="login", raw_text="", description="b"),
    ]
    out = validate_requirements(reqs)
    assert out[1].is_duplicate_of == "FR-1"


def test_output_validation_generates_missing_ids():
    payload = {"test_cases": [{"test_id": "", "expected_result": "ok"}]}
    fixed, notes = validate_output(payload)
    assert fixed["test_cases"][0]["test_id"] != ""
    assert any("Generated missing test_id" in n for n in notes)


def test_output_validation_flags_empty_expected_result():
    payload = {"test_cases": [{"test_id": "TC-1", "expected_result": ""}]}
    fixed, notes = validate_output(payload)
    assert "NOT SPECIFIED" in fixed["test_cases"][0]["expected_result"]

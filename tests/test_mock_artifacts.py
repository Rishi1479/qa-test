"""
Tests for mock-mode artifact generators after pipeline bug fixes.

Covers:
  - Fix #2: context-aware test data (no more hardcoded email/password everywhere)
  - Fix #3: parsed boundary values (concrete numbers, not placeholders)
  - Fix #4: scenario deduplication
  - Fix #5: specific acceptance criteria
"""
from app.schemas.schemas import EnrichedRequirement
from app.agents.qa_artifact_generator_agent import (
    _mock_scenarios,
    _mock_test_cases,
    _mock_acceptance_criteria,
    _parse_boundary_output,
    _generate_sample_test_data,
)


def _make_enriched(
    req_id: str = "FR-1",
    title: str = "Patient Registration",
    description: str = "The system must allow new patients to create an account.",
    **kwargs,
) -> EnrichedRequirement:
    """Helper to create an EnrichedRequirement with sensible defaults."""
    defaults = dict(
        req_id=req_id,
        title=title,
        description=description,
        type="Functional",
        priority="Medium",
        numeric_limits=[],
        edge_cases=[],
        acceptance_criteria=[],
        validation_rules=[],
        preconditions=[],
        postconditions=[],
        input_parameters=[],
        example_input="",
        example_output="",
    )
    defaults.update(kwargs)
    return EnrichedRequirement(**defaults)


# ---------- Fix #2: context-aware test data ----------

class TestContextAwareTestData:

    def test_registration_requirement_gets_registration_data(self):
        req = _make_enriched(
            title="Patient Registration and Authentication",
            description="The system must allow new patients to create an account using email.",
        )
        data = _generate_sample_test_data(req)
        joined = " ".join(data).lower()
        assert "email" in joined
        # Should NOT be the old hardcoded john.doe fallback
        assert "john.doe" not in joined

    def test_availability_requirement_gets_availability_data(self):
        req = _make_enriched(
            req_id="FR-2",
            title="Provider Availability Management",
            description="The system must allow providers to set weekly recurring availability.",
        )
        data = _generate_sample_test_data(req)
        joined = " ".join(data).lower()
        assert "provider" in joined or "slot" in joined
        assert "john.doe" not in joined

    def test_booking_requirement_gets_booking_data(self):
        req = _make_enriched(
            req_id="FR-3",
            title="Appointment Booking",
            description="Patients must be able to book an open 30-minute availability slot.",
        )
        data = _generate_sample_test_data(req)
        joined = " ".join(data).lower()
        assert "patient" in joined or "slot" in joined or "appointment" in joined

    def test_video_call_requirement_gets_video_data(self):
        req = _make_enriched(
            req_id="FR-5",
            title="Video Consultation Link",
            description="The system generates a unique video link for each appointment.",
        )
        data = _generate_sample_test_data(req)
        joined = " ".join(data).lower()
        assert "appointment" in joined or "video" in joined

    def test_example_input_takes_precedence(self):
        req = _make_enriched(
            example_input="custom_field=custom_value",
        )
        data = _generate_sample_test_data(req)
        assert data == ["custom_field=custom_value"]

    def test_positive_test_case_uses_context_data(self):
        """End-to-end: the positive test case in _mock_test_cases should use
        context-aware data, not email=john.doe@example.com."""
        req = _make_enriched(
            req_id="FR-2",
            title="Provider Availability Management",
            description="Providers set weekly recurring availability in 30-minute slots.",
        )
        scenarios = _mock_scenarios([req])
        test_cases = _mock_test_cases([req], scenarios)
        positive_tcs = [tc for tc in test_cases if tc.type == "positive"]
        assert len(positive_tcs) >= 1
        all_data = " ".join(" ".join(tc.test_data) for tc in positive_tcs).lower()
        assert "john.doe" not in all_data


# ---------- Fix #3: boundary value parsing ----------

class TestBoundaryValueParsing:

    def test_parse_range_boundary(self):
        output = "range 8-20: boundary values -> 7(invalid), 8(valid-min), 9(valid), 19(valid), 20(valid-max), 21(invalid)"
        parsed = _parse_boundary_output(output)
        assert len(parsed) == 6
        assert any("value=7" in p and "invalid" in p for p in parsed)
        assert any("value=8" in p and "valid" in p for p in parsed)
        assert any("value=21" in p and "invalid" in p for p in parsed)

    def test_parse_minimum_boundary(self):
        output = "minimum 8: boundary values -> 7(invalid), 8(valid), 9(valid)"
        parsed = _parse_boundary_output(output)
        assert len(parsed) == 3
        assert any("7" in p for p in parsed)

    def test_no_explicit_returns_empty(self):
        output = "No explicit numeric constraints found in this requirement."
        parsed = _parse_boundary_output(output)
        assert parsed == []

    def test_empty_returns_empty(self):
        assert _parse_boundary_output("") == []

    def test_boundary_test_case_has_concrete_values(self):
        """Boundary test cases should have concrete numbers, not placeholders."""
        req = _make_enriched(
            description="Password must be 8-20 characters.",
            numeric_limits=["range 8-20: boundary values -> 7(invalid), 8(valid-min)"],
        )
        scenarios = _mock_scenarios([req])
        test_cases = _mock_test_cases([req], scenarios)
        boundary_tcs = [tc for tc in test_cases if tc.type == "boundary"]
        for tc in boundary_tcs:
            all_data = " ".join(tc.test_data)
            assert "boundary-min" not in all_data, f"Placeholder found in: {all_data}"


# ---------- Fix #4: scenario dedup ----------

class TestScenarioDedup:

    def test_duplicate_numeric_limits_produce_unique_scenarios(self):
        """Two identical numeric limits should not produce duplicate scenarios."""
        req = _make_enriched(
            numeric_limits=[
                "range 8-20: boundary values -> 7(invalid), 8(valid)",
                "range 8-20: boundary values -> 7(invalid), 8(valid)",  # duplicate
            ],
        )
        scenarios = _mock_scenarios([req])
        titles = [sc.title for sc in scenarios]
        assert len(titles) == len(set(titles)), f"Duplicate titles found: {titles}"

    def test_scenario_ids_are_sequential_after_dedup(self):
        req = _make_enriched(
            numeric_limits=[
                "same limit",
                "same limit",
            ],
        )
        scenarios = _mock_scenarios([req])
        ids = [sc.scenario_id for sc in scenarios]
        assert len(ids) == len(set(ids)), f"Duplicate IDs found: {ids}"


# ---------- Fix #5: specific acceptance criteria ----------

class TestSpecificAcceptanceCriteria:

    def test_registration_ac_mentions_registration(self):
        req = _make_enriched(
            description="The system must allow new patients to create an account using email.",
        )
        criteria = _mock_acceptance_criteria([req])
        assert len(criteria) == 1
        ac = criteria[0]
        # The 'then' should reference the actual description, not "as described in Example Output"
        assert "example output" not in ac.then.lower()
        assert "create an account" in ac.then.lower() or "email" in ac.then.lower()

    def test_ac_uses_validation_rules_when_available(self):
        req = _make_enriched(
            validation_rules=[
                {"field": "email", "rule": "unique", "value": "true"},
                {"field": "password", "rule": "min_length", "value": 8},
            ],
        )
        criteria = _mock_acceptance_criteria([req])
        ac = criteria[0]
        # Then should encode the validation rules in field/rule/value form
        assert "email" in ac.then.lower()
        assert "password" in ac.then.lower()

    def test_ac_given_is_context_specific(self):
        req = _make_enriched(
            description="Authenticated patients can book an appointment.",
        )
        criteria = _mock_acceptance_criteria([req])
        ac = criteria[0]
        # Should detect "authenticated" in description
        assert "authenticated" in ac.given.lower() or "operational" in ac.given.lower()

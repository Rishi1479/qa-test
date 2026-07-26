"""Pydantic models shared across the API, the tools, and the LangGraph state."""
from __future__ import annotations
from typing import Optional
# pyrefly: ignore [missing-import]
from pydantic import BaseModel, Field, field_validator


class ValidationRule(BaseModel):
    """A single numeric/format/time constraint extracted from a requirement."""
    field: str
    rule: str
    value: object  # int | float | str

    @field_validator("value", mode="before")
    @classmethod
    def _coerce_value(cls, v):
        """Accept int, float, or string. Try numeric coercion first."""
        if isinstance(v, (int, float)):
            return v
        if isinstance(v, str):
            for cast in (int, float):
                try:
                    return cast(v)
                except ValueError:
                    pass
        return v


class Requirement(BaseModel):
    req_id: str
    title: str
    description: str
    section: Optional[str] = None
    raw_text: str
    type: str = "Functional"
    role: Optional[str] = None
    validations: list[ValidationRule] = Field(default_factory=list)
    is_ambiguous: bool = False
    ambiguity_reason: Optional[str] = None
    is_duplicate_of: Optional[str] = None

    @field_validator("validations", mode="before")
    @classmethod
    def _coerce_validations(cls, v):
        """Accept list of dicts (new format) or list of strings (legacy).
        Strings are stored as {field: 'constraint', rule: 'description', value: v}."""
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str) and item.strip():
                result.append({"field": "constraint", "rule": "description", "value": item})
        return result

    @field_validator("role", mode="before")
    @classmethod
    def _reject_generic_role(cls, v):
        """Prevent generic 'User' / 'Person' from ever persisting."""
        if isinstance(v, str) and v.strip().lower() in ("user", "person"):
            return None
        return v


class EnrichedRequirement(BaseModel):
    """
    Rich 27-field FR object produced by the Requirement Intelligence Agent (Agent 1).
    Every field that the LLM extracts from the document is captured here so that
    the QA Artifact Generator Agent receives complete context in one shot.
    """
    # Identity
    req_id: str
    title: str
    description: str

    # Classification
    type: str = "Functional"  # Functional | Non-Functional | Constraint | Business Rule
    actors: list[str] = Field(default_factory=list)
    user_roles: list[str] = Field(default_factory=list)

    # Business & validation rules
    validation_rules: list[ValidationRule] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)

    @field_validator("validation_rules", mode="before")
    @classmethod
    def _coerce_validation_rules(cls, v):
        """Accept list of ValidationRule dicts or legacy plain strings."""
        if not isinstance(v, list):
            return []
        result = []
        for item in v:
            if isinstance(item, dict):
                result.append(item)
            elif isinstance(item, str) and item.strip():
                result.append({"field": "constraint", "rule": "description", "value": item})
        return result

    # Pre/post conditions
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)

    # I/O specification
    input_parameters: list[str] = Field(default_factory=list)
    output_behaviour: str = ""
    example_input: str = ""
    example_output: str = ""

    # QA hooks
    acceptance_criteria: list[str] = Field(default_factory=list)
    security_rules: list[str] = Field(default_factory=list)
    performance_rules: list[str] = Field(default_factory=list)

    # Dependency & assumption tracking
    dependencies: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    exceptions: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)

    # Boundary triggers
    edge_cases: list[str] = Field(default_factory=list)
    numeric_limits: list[str] = Field(default_factory=list)
    date_time_constraints: list[str] = Field(default_factory=list)

    # Ambiguity analysis
    ambiguous_statements: list[str] = Field(default_factory=list)
    missing_requirements: list[str] = Field(default_factory=list)
    suggested_clarifications: list[str] = Field(default_factory=list)

    # Priority set by Agent 1
    priority: str = "Medium"  # Critical | High | Medium | Low


class ScenarioItem(BaseModel):
    scenario_id: str
    req_id: str
    title: str
    category: str  # positive | negative | boundary | edge


class TestCase(BaseModel):
    test_id: str
    req_id: str
    scenario_id: str
    title: str
    type: str  # positive | negative | boundary | edge
    priority: str  # High | Medium | Low
    preconditions: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    test_data: list[str] = Field(default_factory=list)
    expected_result: str = ""
    postconditions: list[str] = Field(default_factory=list)

    @field_validator("preconditions", "steps", "test_data", "postconditions", mode="before")
    @classmethod
    def _filter_none_strings(cls, v):
        """LLMs sometimes return null inside lists. Strip them safely."""
        if v is None:
            return []
        if isinstance(v, list):
            return [str(item) for item in v if item is not None]
        return v

    @field_validator("expected_result", "title", "test_id", "req_id", "scenario_id", "type", "priority", mode="before")
    @classmethod
    def _coerce_none_str(cls, v):
        """Coerce null string fields to empty string instead of crashing."""
        return v if v is not None else ""


class AcceptanceCriterion(BaseModel):
    req_id: str
    given: str = ""
    when: str = ""
    then: str = ""

    @field_validator("given", "when", "then", "req_id", mode="before")
    @classmethod
    def _coerce_none(cls, v):
        return v if v is not None else ""


class TraceabilityRow(BaseModel):
    req_id: str
    scenario_ids: list[str] = Field(default_factory=list)
    test_ids: list[str] = Field(default_factory=list)
    covered: bool = False


class CoverageSummary(BaseModel):
    total_requirements: int
    covered_requirements: int
    coverage_percent: float
    priority_breakdown: dict[str, int] = Field(default_factory=dict)


class UploadResponse(BaseModel):
    job_id: str
    filename: str
    status: str
    storage_backend: str


class GenerateRequest(BaseModel):
    job_id: str
    force_regenerate: bool = False


class JobSummary(BaseModel):
    job_id: str
    filename: str
    status: str
    created_at: str
    updated_at: str
    completed_at: Optional[str] = None
    coverage_percent: Optional[float] = None
    requirement_count: Optional[int] = None

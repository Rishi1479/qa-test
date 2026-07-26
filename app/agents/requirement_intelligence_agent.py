
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)



# pyrefly: ignore [missing-import]
from langchain_core.messages import SystemMessage, HumanMessage

from app.agents.base import BaseAgent, timed, parse_json
from app.agents.llm import get_llm
from app.agents import prompts
from app.agents.state import GraphState
from app.config import settings
from app.schemas.schemas import EnrichedRequirement, Requirement
from app.tools.boundary_tool import extract_boundary_values

_MOCK = settings.LLM_PROVIDER == "mock"
_RISKY_KEYWORDS = ("password", "payment", "auth", "encrypt", "phi", "security", "login")

def _enrich_from_requirement(req: Requirement) -> EnrichedRequirement:
    
    # Determine priority by risk keywords
    lower = req.description.lower()
    if any(k in lower for k in _RISKY_KEYWORDS):
        priority = "High"
    elif req.type in ("Functional",):
        priority = "Medium"
    else:
        priority = "Low"

    # Extract numeric limits via the existing boundary tool
    boundary_str = extract_boundary_values.invoke({"requirement_text": req.raw_text})
    numeric_limits: list[str] = []
    if "No explicit numeric constraints" not in boundary_str:
        for line in boundary_str.splitlines():
            if line.strip():
                numeric_limits.append(line.strip())

    # Build edge_cases from raw_text
    edge_cases: list[str] = []
    if "edge case" in req.raw_text.lower():
        # Preserve the original edge case text
        match = re.search(r"edge case[s]?\s*[:\-–]\s*(.+)", req.raw_text, re.IGNORECASE)
        if match:
            edge_cases.append(match.group(1).strip())

    # ---- Extract Example Input / Example Output from raw_text ----
    example_input = ""
    example_output = ""
    ei_match = re.search(
        r"Example Input\s*:\s*(.+?)(?=\n(?:Example Output|Edge Case|Validation|$))",
        req.raw_text, re.IGNORECASE | re.DOTALL,
    )
    if ei_match:
        example_input = ei_match.group(1).strip()
    eo_match = re.search(
        r"Example Output\s*:\s*(.+?)(?=\n(?:Edge Case|Validation|$))",
        req.raw_text, re.IGNORECASE | re.DOTALL,
    )
    if eo_match:
        example_output = eo_match.group(1).strip()

    # ---- Derive input parameters from description ----
    input_parameters: list[str] = []
    param_keywords = [
        ("email", "email address"),
        ("password", "password"),
        ("username", "username"),
        ("slot", "time slot"),
        ("provider", "provider ID"),
        ("patient", "patient ID"),
        ("appointment", "appointment ID"),
        ("date", "date"),
        ("time", "time"),
    ]
    for keyword, param_name in param_keywords:
        if keyword in lower:
            input_parameters.append(param_name)

    # ---- Build requirement-specific acceptance criteria ----
    ac_parts: list[str] = []
    # Precondition → Given
    if "authenticated" in lower or "auth" in lower or "login" in lower:
        given = "the user is authenticated and on the relevant page"
    elif "register" in lower or "create an account" in lower:
        given = "the user is on the registration page"
    else:
        given = f"the preconditions for {req.req_id} ({req.title}) are met"

    # Action → When
    when = f'the user performs "{req.title.lower()}"'

    # Expected → Then (use validation rules if available, else description)
    if req.validations:
        then = "; ".join(req.validations)
    elif example_output:
        then = example_output
    else:
        # Derive from description
        then = req.description.rstrip(".")

    ac_text = f"Given {given}, when {when}, then {then}"
    ac_parts.append(ac_text)

    return EnrichedRequirement(
        req_id=req.req_id,
        title=req.title,
        description=req.description,
        type=req.type,
        actors=["System"],
        user_roles=[req.role] if req.role else ["User"],
        validation_rules=req.validations,
        business_rules=[],
        constraints=[],
        preconditions=[f"Preconditions for {req.req_id} are satisfied"],
        postconditions=[f"System state updated per {req.req_id}"],
        input_parameters=input_parameters,
        output_behaviour=f"System completes the action described in {req.req_id}",
        example_input=example_input,
        example_output=example_output,
        acceptance_criteria=ac_parts,
        security_rules=[],
        performance_rules=[],
        dependencies=[],
        assumptions=[],
        exceptions=[],
        error_messages=[],
        edge_cases=edge_cases,
        numeric_limits=numeric_limits,
        date_time_constraints=[],
        ambiguous_statements=(
            [req.ambiguity_reason] if req.is_ambiguous and req.ambiguity_reason else []
        ),
        missing_requirements=[],
        suggested_clarifications=[],
        priority=priority,
    )

def _parse_enriched_list(text: str, fallback_reqs: list[Requirement]) -> list[EnrichedRequirement]:
    
    raw = parse_json(text, [])
    if not isinstance(raw, list):
        return [_enrich_from_requirement(r) for r in fallback_reqs]

    enriched: list[EnrichedRequirement] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            enriched.append(EnrichedRequirement(**item))
        except Exception:
            # If the LLM omits optional fields, fill with defaults via model_validate
            try:
                enriched.append(EnrichedRequirement.model_validate(item))
            except Exception:
                pass

    if not enriched:
        return [_enrich_from_requirement(r) for r in fallback_reqs]
    return enriched

class RequirementIntelligenceAgent(BaseAgent):
    

    def run(self, state: GraphState) -> dict:
        updates: dict = {}

        with timed("requirement_intelligence", updates):
            requirements: list[Requirement] = state.get("requirements", [])

            if _MOCK:
                enriched = [_enrich_from_requirement(r) for r in requirements]
                updates["enriched_requirements"] = enriched
                return updates

            # ---- Real mode: single LLM call ----
            llm = get_llm()
            parsed_text = state.get("parsed_text", "")

            # Compose user message: include both raw text and parsed req list
            # so the LLM can cross-reference IDs already assigned by the extractor.
            req_summary = "\n".join(
                f"[{r.req_id}] {r.title}: {r.description[:200]}"
                for r in requirements
            )
            user_msg = (
                f"=== PARSED DOCUMENT TEXT ===\n{parsed_text}\n\n"
                f"=== PRE-EXTRACTED REQUIREMENT IDs (maintain these IDs) ===\n{req_summary}"
            )

            try:
                logger.info("llm start")
                resp = llm.invoke([
                    SystemMessage(content=prompts.REQUIREMENT_INTELLIGENCE),
                    HumanMessage(content=user_msg),
                ])
                logger.info("llm end")
                enriched = _parse_enriched_list(resp.content, requirements)
            except Exception as exc:
                updates.setdefault("errors", []).append(
                    f"requirement_intelligence_agent: {exc}"
                )
                enriched = [_enrich_from_requirement(r) for r in requirements]

        updates["enriched_requirements"] = enriched
        return updates

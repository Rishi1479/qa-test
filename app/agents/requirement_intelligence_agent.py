
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

def _infer_role(description: str) -> str:
    """Deterministic role inference matching the LLM prompt rules.
    Returns a specific actor — never 'User' or 'Person'."""
    lower = description.lower()

    # System-level SLA / infrastructure behavior takes priority.
    # These requirements describe what the *system* must do, even if "patient"
    # or "provider" appears as a noun modifier (e.g. "patient booking dashboard").
    system_behavior_signals = (
        "uptime", "latency", "load time", "page load", "page must load",
        "must load in", "load in under", "response time", "throughput",
        "encrypt", "bcrypt", "hash", "hashed", "security enforcement",
        "authentication must", "authorization must",
    )
    if any(sig in lower for sig in system_behavior_signals):
        return "System"

    has_patient  = bool(re.search(r"\bpatients?\b", lower))
    has_provider = bool(re.search(r"\bproviders?\b", lower))
    has_admin    = bool(re.search(r"\badmins?(istrators?)?\b", lower))

    if has_patient and has_provider:
        return "Patient, Provider"
    if has_patient:
        return "Patient"
    if has_provider:
        return "Provider"
    if has_admin:
        return "Admin"
    # Broader system-level keywords (performance, security)
    system_keywords = ("performance", "encrypt", "bcrypt", "hash", "security",
                       "authentication", "authorization", "throughput")
    if any(kw in lower for kw in system_keywords):
        return "System"
    return "System"   # safe fallback — never "User"


# Patterns that signal a numeric/time/format constraint
_CONSTRAINT_PATTERNS: list[tuple[re.Pattern, str, str]] = [
    # "at least N characters" / "minimum N characters"
    (re.compile(r"(?:at least|minimum of?|min)\s+(\d+)\s+characters?", re.I),
     "password_length", "min_length"),
    # "N characters" standalone (e.g. "8 characters")
    (re.compile(r"(\d+)\s+characters?", re.I), "field_length", "min_length"),
    # "up to N hours prior" / "N hours before"
    (re.compile(r"(?:up to|within|before)\s+(\d+)\s+hours?", re.I),
     "notice_period_hours", "min_hours_before"),
    # "N hours prior"
    (re.compile(r"(\d+)\s+hours?\s+prior", re.I), "notice_period_hours", "min_hours_before"),
    # "under N.N seconds" / "in N seconds" / "less than N seconds"
    (re.compile(r"(?:under|in|less than|within)\s+([\d.]+)\s+seconds?", re.I),
     "response_time_seconds", "max_seconds"),
    # "N milliseconds" / "under N ms"
    (re.compile(r"(?:under|less than|within)?\s*([\d.]+)\s*(?:ms|milliseconds?)", re.I),
     "latency_ms", "max_ms"),
    # "N% uptime" / "uptime of N.N%"
    (re.compile(r"(\d+(?:\.\d+)?)\s*%", re.I), "uptime_percent", "min_percent"),
    # "N-minute time slots" / "N-minute slots"
    (re.compile(r"(\d+)-?minute\s+(?:time\s+)?slots?", re.I),
     "slot_duration_minutes", "fixed_value"),
    # "every N minutes" / "N minutes"
    (re.compile(r"(\d+)\s+minutes?", re.I), "duration_minutes", "fixed_value"),
]


def _extract_validations(description: str) -> list[dict]:
    """Extract structured {field, rule, value} validation objects from description text.
    Applies the same patterns as the LLM prompt instructs, deterministically."""
    lower = description.lower()
    # Quick bail-out: no trigger words at all
    trigger_words = ("at least", "under", "before", "within", "up to", "minimum",
                     "maximum", "must not exceed", "no more than", "prior to",
                     "at most", "%", "second", "minute", "hour", "character",
                     "ms", "millisecond", "slot")
    if not any(t in lower for t in trigger_words) and not re.search(r"\d", description):
        return []

    seen: set[tuple] = set()
    results: list[dict] = []

    for pattern, default_field, rule in _CONSTRAINT_PATTERNS:
        for m in pattern.finditer(description):
            raw_val = m.group(1)
            # Numeric coercion
            try:
                value: object = int(raw_val) if "." not in raw_val else float(raw_val)
            except ValueError:
                value = raw_val

            # Use a more descriptive field name based on context
            ctx = description[max(0, m.start() - 60): m.end() + 60].lower()
            field = default_field
            if "password" in ctx:
                field = "password"
            elif "cancell" in ctx or "cancel" in ctx or "prior" in ctx:
                field = "cancellation_notice"
            elif "page load" in ctx or "dashboard" in ctx or ("page" in ctx and "load" in ctx):
                field = "page_load_time"
            elif "uptime" in ctx or "%" in m.group(0):
                field = "uptime"
            elif "slot" in ctx:
                field = "slot_duration_minutes"

            key = (field, rule, value)
            if key not in seen:
                seen.add(key)
                results.append({"field": field, "rule": rule, "value": value})

    return results


def _enrich_from_requirement(req: Requirement) -> EnrichedRequirement:

    # Determine priority by risk keywords
    lower = req.description.lower()
    if any(k in lower for k in _RISKY_KEYWORDS):
        priority = "High"
    elif req.type in ("Functional",):
        priority = "Medium"
    else:
        priority = "Low"

    # ---- Role (deterministic, never "User") ----
    if req.role and req.role.strip().lower() not in ("user", "person", ""):
        role = req.role
    else:
        role = _infer_role(req.description)

    # ---- Validations: prefer LLM-supplied structured rules; extract from text otherwise ----
    if req.validations:
        # Already structured ValidationRule objects from the schema validator
        validation_rules = [v.model_dump() for v in req.validations]
    else:
        validation_rules = _extract_validations(req.description)

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
    if "authenticated" in lower or "auth" in lower or "login" in lower:
        given = "the user is authenticated and on the relevant page"
    elif "register" in lower or "create an account" in lower:
        given = "the user is on the registration page"
    else:
        given = f"the preconditions for {req.req_id} ({req.title}) are met"

    when = f'the user performs "{req.title.lower()}"'

    if validation_rules:
        then = "; ".join(
            f"{vr['field']} must satisfy {vr['rule']} = {vr['value']}"
            for vr in validation_rules
        )
    elif example_output:
        then = example_output
    else:
        then = req.description.rstrip(".")

    ac_text = f"Given {given}, when {when}, then {then}"
    ac_parts.append(ac_text)

    return EnrichedRequirement(
        req_id=req.req_id,
        title=req.title,
        description=req.description,
        type=req.type,
        actors=["System"],
        user_roles=[role],
        validation_rules=validation_rules,
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

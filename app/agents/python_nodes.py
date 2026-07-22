
from __future__ import annotations

import time
from datetime import datetime, timezone

from app.agents.state import GraphState
from app.parsing.requirement_extractor import extract_requirements
from app.tools.export_tool import to_markdown
from app.tools.json_formatter_tool import assemble_final_json
from app.tools.mongodb_tool import mongodb_tool
from app.tools.validation_tool import validate_output, validate_requirements

def _append_timing(state: GraphState, updates: dict, node_name: str, duration: float) -> None:
    # node_timings uses operator.add in GraphState, so we only need to return the NEW item
    updates["node_timings"] = [{"node": node_name, "duration_seconds": round(duration, 3)}]

def document_parser_node(state: GraphState) -> dict:
    
    updates: dict = {}
    t0 = time.time()

    parsed_text = state.get("parsed_text", "")

    if not parsed_text:
        updates.setdefault("errors", []).append(
            "document_parser_node: no parsed_text in state; "
            "extraction will proceed on empty string"
        )

    requirements = extract_requirements(parsed_text or "")
    requirements = validate_requirements(requirements)

    if not requirements:
        updates.setdefault("errors", []).append(
            "document_parser_node: no requirements could be extracted"
        )

    updates["parsed_text"] = parsed_text
    updates["requirements"] = requirements
    _append_timing(state, updates, "document_parser", time.time() - t0)
    return updates

def validation_node(state: GraphState) -> dict:
   
    updates: dict = {}
    t0 = time.time()
    notes: list[str] = []

    test_cases = state.get("test_cases", [])
    scenarios = state.get("scenarios", [])
    traceability = state.get("traceability", [])

    
    scenario_ids_in_list = {sc.scenario_id for sc in scenarios}
    tc_ids_in_list = {tc.test_id for tc in test_cases}

   
    for row in traceability:
        for sid in row.scenario_ids:
            if sid not in scenario_ids_in_list:
                notes.append(f"Orphan scenario_id '{sid}' in traceability row {row.req_id}")
        for tid in row.test_ids:
            if tid not in tc_ids_in_list:
                notes.append(f"Orphan test_id '{tid}' in traceability row {row.req_id}")

   
    coverage = state.get("coverage")
    temp_payload = {
        "job_id": state.get("job_id", ""),
        "test_cases": [tc.model_dump() for tc in test_cases],
        "coverage": coverage.model_dump() if coverage else {},
    }
    _, output_notes = validate_output(temp_payload)
    notes.extend(output_notes)

    updates["validation_notes"] = notes
    _append_timing(state, updates, "validation_node", time.time() - t0)
    return updates

def json_formatter_node(state: GraphState) -> dict:
    
    updates: dict = {}
    t0 = time.time()

    enriched = state.get("enriched_requirements", [])
    requirements = state.get("requirements", [])
    scenarios = state.get("scenarios", [])
    test_cases = state.get("test_cases", [])
    acceptance_criteria = state.get("acceptance_criteria", [])
    traceability = state.get("traceability", [])
    coverage = state.get("coverage")

   
    if enriched:
        from app.schemas.schemas import Requirement
        req_for_output = [
            Requirement(
                req_id=er.req_id,
                title=er.title,
                description=er.description,
                raw_text=er.description,
                type=er.type,
                validations=er.validation_rules,
            )
            for er in enriched
        ]
    else:
        req_for_output = requirements

    if not coverage:
        from app.schemas.schemas import CoverageSummary
        coverage = CoverageSummary(
            total_requirements=len(req_for_output),
            covered_requirements=0,
            coverage_percent=0.0,
        )

    payload = assemble_final_json(
        job_id=state.get("job_id", ""),
        requirements=req_for_output,
        scenarios=scenarios,
        test_cases=test_cases,
        acceptance_criteria=acceptance_criteria,
        traceability=traceability,
        coverage=coverage,
    )

    # Embed enriched_requirements in the output for full fidelity
    if enriched:
        payload["enriched_requirements"] = [e.model_dump() for e in enriched]

    fixed_payload, notes = validate_output(payload)
    markdown = to_markdown(fixed_payload)

    updates["final_json"] = fixed_payload
    updates["markdown_report"] = markdown
    if notes:
        updates["validation_notes"] = notes
    _append_timing(state, updates, "json_formatter_node", time.time() - t0)
    return updates

def persistence_node(state: GraphState) -> dict:
    
    updates: dict = {}
    t0 = time.time()
    job_id = state.get("job_id", "")
    errors: list[str] = []

    completed_at = datetime.now(timezone.utc).isoformat()
    exec_meta = state.get("execution_metadata") or {}

    # 1. Save results to Postgres
    try:
        results_payload = {
            **(state.get("final_json") or {}),
            "markdown_report": state.get("markdown_report", ""),
        }
        from app.database import SessionLocal
        from app.crud import save_results, update_job_status
        
        with SessionLocal() as db:
            save_results(db, job_id, results_payload)
    except Exception as exc:
        errors.append(f"persistence_node.save_results (Postgres): {exc}")

    # 2. Save execution log to Mongo (include timings captured so far)
    _append_timing(state, updates, "persistence_node", time.time() - t0)
    try:
        mongodb_tool.save_execution_log(
            job_id,
            {
                "started_at":       exec_meta.get("started_at", ""),
                "completed_at":     completed_at,
                "node_timings":     updates.get("node_timings", []),
                "errors":           errors,
                "validation_notes": state.get("validation_notes", []),
            },
        )
    except Exception as exc:
        errors.append(f"persistence_node.save_execution_log (Mongo): {exc}")

   
    try:
        with SessionLocal() as db:
            update_job_status(db, job_id, "completed")
    except Exception as exc:
        errors.append(f"persistence_node.update_job_status (Postgres): {exc}")

    if errors:
        updates["errors"] = errors
    return updates

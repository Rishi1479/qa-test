from __future__ import annotations

import os
import tempfile
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response

from app.agents.graph import get_workflow
from app.parsing.docling_parser import parse_document
from app.parsing.requirement_extractor import extract_requirements
from app.schemas.schemas import GenerateRequest, JobSummary
from app.tools.export_tool import to_markdown, to_csv
from app.tools.mongodb_tool import mongodb_tool
from app.tools.supabase_tool import supabase_tool
from app.tools.validation_tool import validate_requirements
from app.database import SessionLocal
from app.crud.crud import get_job, get_document_by_job, list_jobs, update_job_status, delete_job, clear_incremental_data
from app.models.models import TestCase

router = APIRouter(tags=["generation"])


# ---------------------------------------------------------------------------
# POST /generate
# ---------------------------------------------------------------------------

@router.post("/generate")
def generate(req: GenerateRequest):
    """
    Run the LangGraph multi-agent workflow on a previously uploaded document.

    The PersistenceAgent (final graph node) saves results and execution logs
    to MongoDB automatically — this endpoint only orchestrates the run and
    returns the final JSON.
    """
    with SessionLocal() as db:
        job = get_job(db, req.job_id)
        if not job:
            raise HTTPException(404, f"Unknown job_id '{req.job_id}'")

        existing_wrapper = mongodb_tool.get_results(req.job_id)
        existing = existing_wrapper.get("results", {}) if existing_wrapper else {}
        if existing and not req.force_regenerate:
            return {"job_id": req.job_id, "status": "completed", "cached": True, "results": existing}

        update_job_status(db, req.job_id, "processing")
        clear_incremental_data(db, req.job_id)
        
        # Need to extract job details before closing session if we want to use them
        doc = get_document_by_job(db, req.job_id)
        job_filename = doc.filename if doc else "unknown.txt"
        job_storage_url = doc.storage_path if doc else ""
    started_at = datetime.now(timezone.utc).isoformat()
    t0 = time.time()

    try:
        # ---- 1. Fetch and parse the original document ----
        content = supabase_tool.download(req.job_id, job_filename)
        ext = os.path.splitext(job_filename)[1]
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name

        try:
            parsed_text = parse_document(tmp_path)
        finally:
            os.unlink(tmp_path)

        # ---- 2. Extract and validate requirements ----
        requirements = extract_requirements(parsed_text)
        if not requirements:
            with SessionLocal() as db:
                update_job_status(db, req.job_id, "failed")
            raise HTTPException(422, "No requirements could be extracted from this document")
        requirements = validate_requirements(requirements)

        # ---- 3. Run the LangGraph workflow ----
        # PersistenceAgent (final node) saves results + execution log to MongoDB
        # We must use a unique thread_id every time we invoke the workflow
        # so LangGraph does not try to resume and append to an old checkpoint's state.
        workflow = get_workflow()
        thread_id = f"{req.job_id}-{uuid.uuid4().hex[:8]}"

        result_state = workflow.invoke(
            {
                "job_id":             req.job_id,
                "storage_url":        job_storage_url,
                "parsed_text":        parsed_text,
                "requirements":       requirements,
                "execution_metadata": {"started_at": started_at},
            },
            config={"configurable": {"thread_id": thread_id}}
        )

        duration = round(time.time() - t0, 3)
        return {
            "job_id":            req.job_id,
            "status":            "completed",
            "cached":            False,
            "duration_seconds":  duration,
            "results":           result_state.get("final_json", {}),
            "validation_notes":  result_state.get("validation_notes", []),
        }

    except HTTPException:
        raise
    except Exception as e:
        # PersistenceAgent never ran — update status manually.
        with SessionLocal() as db:
            update_job_status(db, req.job_id, "failed")
        raise HTTPException(500, f"Generation failed: {e}")


# ---------------------------------------------------------------------------
# GET /jobs, GET /jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=list[JobSummary])
def list_jobs_endpoint():
    with SessionLocal() as db:
        jobs = list_jobs(db)
        out = []
        for j in jobs:
            job_id_str = str(j.id)
            results_wrapper = mongodb_tool.get_results(job_id_str)
            results = results_wrapper.get("results", {}) if results_wrapper else {}
            cov = results.get("coverage", {})
            out.append(JobSummary(
                job_id=str(j.id),
                filename=j.document.filename if j.document else "",
                status=j.status,
                created_at=j.created_at.isoformat() if j.created_at else "",
                updated_at=j.updated_at.isoformat() if j.updated_at else "",
                completed_at=j.completed_at.isoformat() if getattr(j, "completed_at", None) else None,
                coverage_percent=cov.get("coverage_percent"),
                requirement_count=len((results or {}).get("requirements", [])) or None,
            ))
        return out


@router.get("/jobs/{job_id}")
def get_job_endpoint(job_id: str):
    with SessionLocal() as db:
        job = get_job(db, job_id)
        if not job:
            raise HTTPException(404, f"Unknown job_id '{job_id}'")
        
        results_wrapper = mongodb_tool.get_results(job_id)
        results = results_wrapper.get("results", {}) if results_wrapper else {}
        log = mongodb_tool.get_execution_log(job_id)
        
        job_dict = {
            "job_id": str(job.id),
            "filename": job.document.filename if job.document else "",
            "storage_url": job.document.storage_path if job.document else "",
            "storage_backend": "supabase",
            "status": job.status,
            "created_at": job.created_at.isoformat() if job.created_at else "",
            "updated_at": job.updated_at.isoformat() if job.updated_at else "",
            "completed_at": job.completed_at.isoformat() if getattr(job, "completed_at", None) else None,
        }
        return {"job": job_dict, "results": results, "execution_log": log}


@router.get("/jobs/{job_id}/enriched-requirements")
def get_enriched_requirements(job_id: str):
    """Return the full 27-field EnrichedRequirement objects saved by the
    Requirement Intelligence Agent for this job.  These include every field
    the LLM extracted: role, validations (with field/rule/value), numeric_limits,
    edge_cases, ambiguous_statements, preconditions, postconditions, etc.
    Stored in MongoDB's 'enriched_requirements' collection."""
    with SessionLocal() as db:
        job = get_job(db, job_id)
        if not job:
            raise HTTPException(404, f"Unknown job_id '{job_id}'")

    enriched = mongodb_tool.get_enriched_requirements(job_id)
    if not enriched:
        raise HTTPException(
            404,
            f"No enriched requirements found for job '{job_id}'. "
            "Run /generate first, or the job may still be processing.",
        )
    return {"job_id": job_id, "count": len(enriched), "requirements": enriched}


@router.get("/jobs/{job_id}/requirements/{req_code}/test-cases")
def get_test_cases_for_requirement(job_id: str, req_code: str):
    import uuid
    from app.models.models import Requirement
    with SessionLocal() as db:
        test_cases = db.query(TestCase).join(Requirement).filter(
            Requirement.job_id == uuid.UUID(job_id),
            Requirement.req_code == req_code
        ).all()
        if not test_cases:
            raise HTTPException(404, f"No test cases found for job '{job_id}' and req '{req_code}'")
        
        return [{
            "test_id": str(t.id),
            "req_id": t.requirement.req_code,
            "scenario_id": None,
            "title": t.title,
            "type": t.type,
            "priority": None,
            "expected_result": t.expected_result,
            "preconditions": [t.preconditions] if t.preconditions else [],
            "steps": t.steps,
            "test_data": t.test_data,
            "postconditions": [t.postconditions] if t.postconditions else [],
            "completed_at": t.completed_at.isoformat() if t.completed_at else None,
            "langsmith_run_id": t.langsmith_run_id,
        } for t in test_cases]


# ---------------------------------------------------------------------------
# GET /jobs/{job_id}/download  (unified: ?fmt=json|markdown|csv)
# GET /json/{job_id}           (dedicated JSON route)
# GET /markdown/{job_id}       (dedicated Markdown route)
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}/download")
def download_job(job_id: str, fmt: str = "json"):
    with SessionLocal() as db:
        results = get_results(db, job_id)
    if not results:
        raise HTTPException(404, f"No results yet for job '{job_id}'. Run /generate first.")

    if fmt == "json":
        import json
        return Response(
            content=json.dumps(results, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={job_id}.json"},
        )
    if fmt == "markdown":
        md = results.get("markdown_report") or to_markdown(results)
        return Response(
            content=md,
            media_type="text/markdown",
            headers={"Content-Disposition": f"attachment; filename={job_id}.md"},
        )
    if fmt == "csv":
        return Response(
            content=to_csv(results),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={job_id}.csv"},
        )
    raise HTTPException(400, "fmt must be one of: json, markdown, csv")


@router.get("/json/{job_id}")
def get_json(job_id: str):
    """Return the structured JSON output for a completed analysis."""
    with SessionLocal() as db:
        results = get_results(db, job_id)
    if not results:
        raise HTTPException(404, f"No results for job '{job_id}'. Run /generate first.")
    import json
    return Response(
        content=json.dumps(results, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f"inline; filename={job_id}.json"},
    )


@router.get("/markdown/{job_id}")
def get_markdown(job_id: str):
    """Return the Markdown report for a completed analysis."""
    with SessionLocal() as db:
        results = get_results(db, job_id)
    if not results:
        raise HTTPException(404, f"No results for job '{job_id}'. Run /generate first.")
    md = results.get("markdown_report") or to_markdown(results)
    return Response(
        content=md,
        media_type="text/markdown",
        headers={"Content-Disposition": f"inline; filename={job_id}.md"},
    )


# ---------------------------------------------------------------------------
# DELETE /jobs/{job_id}
# ---------------------------------------------------------------------------

@router.delete("/jobs/{job_id}")
def delete_job_endpoint(job_id: str):
    with SessionLocal() as db:
        job = get_job(db, job_id)
        if not job:
            raise HTTPException(404, f"Unknown job_id '{job_id}'")
        try:
            if job.document:
                supabase_tool.delete(str(job.id), job.document.filename)
        except Exception:
            pass
        delete_job(db, job_id)
    
    mongodb_tool.delete_job(job_id)
    return {"job_id": job_id, "deleted": True}

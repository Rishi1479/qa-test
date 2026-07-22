from sqlalchemy.orm import Session
from app.models.models import (
    AnalysisJob,
    RequirementRecord,
    ScenarioRecord,
    TestCaseRecord,
    AcceptanceCriterionRecord,
    TraceabilityRecord,
    CoverageSummaryRecord,
)

def create_job(db: Session, job_id: str, filename: str, storage_url: str, storage_backend: str):
    job = AnalysisJob(
        job_id=job_id,
        filename=filename,
        storage_url=storage_url,
        storage_backend=storage_backend,
        status="uploaded"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

def get_job(db: Session, job_id: str):
    return db.query(AnalysisJob).filter(AnalysisJob.job_id == job_id).first()

def update_job_status(db: Session, job_id: str, status: str):
    job = get_job(db, job_id)
    if job:
        job.status = status
        db.commit()
        db.refresh(job)
    return job

def delete_job(db: Session, job_id: str):
    job = get_job(db, job_id)
    if job:
        db.delete(job)
        db.commit()

def save_results(db: Session, job_id: str, results_dict: dict):
    
    # Clear existing if any
    db.query(RequirementRecord).filter(RequirementRecord.job_id == job_id).delete()
    db.query(ScenarioRecord).filter(ScenarioRecord.job_id == job_id).delete()
    db.query(TestCaseRecord).filter(TestCaseRecord.job_id == job_id).delete()
    db.query(AcceptanceCriterionRecord).filter(AcceptanceCriterionRecord.job_id == job_id).delete()
    db.query(TraceabilityRecord).filter(TraceabilityRecord.job_id == job_id).delete()
    db.query(CoverageSummaryRecord).filter(CoverageSummaryRecord.job_id == job_id).delete()
    
    # 1. Requirements
    for req in results_dict.get("requirements", []):
        db.add(RequirementRecord(
            job_id=job_id,
            req_id=req.get("req_id"),
            title=req.get("title"),
            description=req.get("description"),
            type=req.get("type"),
            priority=req.get("priority"),
            data=req
        ))
        
    # 2. Scenarios
    for scen in results_dict.get("scenarios", []):
        db.add(ScenarioRecord(
            job_id=job_id,
            scenario_id=scen.get("scenario_id"),
            req_id=scen.get("req_id"),
            title=scen.get("title"),
            category=scen.get("category")
        ))
        
    # 3. Test Cases
    for tc in results_dict.get("test_cases", []):
        db.add(TestCaseRecord(
            job_id=job_id,
            test_id=tc.get("test_id"),
            req_id=tc.get("req_id"),
            scenario_id=tc.get("scenario_id"),
            title=tc.get("title"),
            type=tc.get("type"),
            priority=tc.get("priority"),
            expected_result=tc.get("expected_result"),
            data={
                "preconditions": tc.get("preconditions", []),
                "steps": tc.get("steps", []),
                "test_data": tc.get("test_data", []),
                "postconditions": tc.get("postconditions", [])
            }
        ))
        
    # 4. Acceptance Criteria
    for ac in results_dict.get("acceptance_criteria", []):
        db.add(AcceptanceCriterionRecord(
            job_id=job_id,
            req_id=ac.get("req_id"),
            given_clause=ac.get("given"),
            when_clause=ac.get("when"),
            then_clause=ac.get("then")
        ))
        
    # 5. Traceability
    for tr in results_dict.get("traceability", []):
        db.add(TraceabilityRecord(
            job_id=job_id,
            req_id=tr.get("req_id"),
            covered=tr.get("covered", False),
            scenario_ids=tr.get("scenario_ids", []),
            test_ids=tr.get("test_ids", [])
        ))
        
    # 6. Coverage Summary
    cov = results_dict.get("coverage", {})
    if cov:
        db.add(CoverageSummaryRecord(
            job_id=job_id,
            total_requirements=cov.get("total_requirements", 0),
            covered_requirements=cov.get("covered_requirements", 0),
            coverage_percent=cov.get("coverage_percent", 0.0),
            positive_count=cov.get("positive_count", 0),
            negative_count=cov.get("negative_count", 0),
            boundary_count=cov.get("boundary_count", 0),
            edge_count=cov.get("edge_count", 0),
            priority_breakdown=cov.get("priority_breakdown", {}),
            missing_coverage=cov.get("missing_coverage", [])
        ))
        
    db.commit()

def get_results(db: Session, job_id: str) -> dict:
    
    reqs = db.query(RequirementRecord).filter(RequirementRecord.job_id == job_id).all()
    if not reqs:
        return None
        
    scenarios = db.query(ScenarioRecord).filter(ScenarioRecord.job_id == job_id).all()
    tcs = db.query(TestCaseRecord).filter(TestCaseRecord.job_id == job_id).all()
    acs = db.query(AcceptanceCriterionRecord).filter(AcceptanceCriterionRecord.job_id == job_id).all()
    traces = db.query(TraceabilityRecord).filter(TraceabilityRecord.job_id == job_id).all()
    cov = db.query(CoverageSummaryRecord).filter(CoverageSummaryRecord.job_id == job_id).first()
    
    # We rebuild the structure exactly like `final_json`
    out = {
        "job_id": job_id,
        "requirements": [r.data for r in reqs if r.data],
        "scenarios": [
            {
                "scenario_id": s.scenario_id,
                "req_id": s.req_id,
                "title": s.title,
                "category": s.category
            } for s in scenarios
        ],
        "test_cases": [
            {
                "test_id": t.test_id,
                "req_id": t.req_id,
                "scenario_id": t.scenario_id,
                "title": t.title,
                "type": t.type,
                "priority": t.priority,
                "preconditions": (t.data or {}).get("preconditions", []),
                "steps": (t.data or {}).get("steps", []),
                "test_data": (t.data or {}).get("test_data", []),
                "expected_result": t.expected_result,
                "postconditions": (t.data or {}).get("postconditions", [])
            } for t in tcs
        ],
        "acceptance_criteria": [
            {
                "req_id": a.req_id,
                "given": a.given_clause,
                "when": a.when_clause,
                "then": a.then_clause
            } for a in acs
        ],
        "traceability": [
            {
                "req_id": tr.req_id,
                "scenario_ids": tr.scenario_ids or [],
                "test_ids": tr.test_ids or [],
                "covered": tr.covered
            } for tr in traces
        ],
        "coverage": {
            "total_requirements": cov.total_requirements if cov else 0,
            "covered_requirements": cov.covered_requirements if cov else 0,
            "coverage_percent": cov.coverage_percent if cov else 0.0,
            "priority_breakdown": cov.priority_breakdown if cov else {},
            "positive_count": cov.positive_count if cov else 0,
            "negative_count": cov.negative_count if cov else 0,
            "boundary_count": cov.boundary_count if cov else 0,
            "edge_count": cov.edge_count if cov else 0,
            "missing_coverage": cov.missing_coverage if cov else []
        } if cov else {}
    }
    
    return out

def list_jobs(db: Session, limit: int = 50, skip: int = 0):
    return db.query(AnalysisJob).order_by(AnalysisJob.created_at.desc()).offset(skip).limit(limit).all()

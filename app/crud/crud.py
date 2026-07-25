import uuid
from sqlalchemy.orm import Session
from app.models.models import Document, Job, Requirement, TestCase
from datetime import datetime, timezone

def create_document_and_job(db: Session, document_id: uuid.UUID, job_id: str, filename: str, ext: str, size: int, storage_path: str):
    doc = Document(
        id=document_id,
        job_id=job_id,
        filename=filename,
        file_type=ext,
        file_size_bytes=size,
        storage_path=storage_path,
        parsed_status="pending"
    )
    db.add(doc)
    db.flush()
    
    job = Job(
        id=job_id,
        document_id=doc.id,
        status="uploaded"
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    db.refresh(doc)
    return doc, job

def get_job(db: Session, job_id: str):
    return db.query(Job).filter(Job.id == job_id).first()

def get_document_by_job(db: Session, job_id: str):
    return db.query(Document).filter(Document.job_id == job_id).first()

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

def list_jobs(db: Session, limit: int = 50, skip: int = 0):
    return db.query(Job).order_by(Job.created_at.desc()).offset(skip).limit(limit).all()

def clear_incremental_data(db: Session, job_id: str):
    reqs = db.query(Requirement).filter(Requirement.job_id == job_id).all()
    req_ids = [r.id for r in reqs]
    if req_ids:
        db.query(TestCase).filter(TestCase.requirement_id.in_(req_ids)).delete(synchronize_session=False)
        db.query(Requirement).filter(Requirement.job_id == job_id).delete(synchronize_session=False)
        db.commit()

def save_incremental_requirements_and_testcases(
    db: Session, 
    job_id: str, 
    requirements: list[dict], 
    test_cases: list[dict], 
    run_id: str = None, 
    raw_response: str = None
):
    req_map = {}
    
    # Insert or update requirements
    for req in requirements:
        req_rec = db.query(Requirement).filter_by(job_id=job_id, req_code=req.get("req_id")).first()
        if not req_rec:
            req_rec = Requirement(
                job_id=job_id,
                req_code=req.get("req_id"),
                title=req.get("title"),
                raw_text=req.get("description"),
                requirement_type=req.get("type"),
                priority=req.get("priority")
            )
            db.add(req_rec)
            db.flush()
        else:
            req_rec.title = req.get("title")
            req_rec.raw_text = req.get("description")
            req_rec.requirement_type = req.get("type")
            req_rec.priority = req.get("priority")
            db.flush()
        req_map[req_rec.req_code] = req_rec.id

    # Insert test cases
    completed_at = datetime.now(timezone.utc)
    for tc in test_cases:
        tc_rec = TestCase(
            requirement_id=req_map.get(tc.get("req_id")),
            type=tc.get("type"),
            title=tc.get("title"),
            expected_result=tc.get("expected_result"),
            completed_at=completed_at,
            langsmith_run_id=run_id,
            llm_raw_response=raw_response,
            preconditions="\n".join(tc.get("preconditions", [])) if tc.get("preconditions") else None,
            postconditions="\n".join(tc.get("postconditions", [])) if tc.get("postconditions") else None,
            steps=tc.get("steps", []),
            test_data=tc.get("test_data", [])
        )
        db.add(tc_rec)
    
    db.commit()

def save_results(db: Session, job_id: str, results_dict: dict):
    # This is a no-op for Postgres because test cases and requirements are saved incrementally,
    # and scenarios, coverage, and traceability are saved to MongoDB in this new architecture.
    pass

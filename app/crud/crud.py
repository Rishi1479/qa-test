import uuid
from sqlalchemy.orm import Session
from app.models.models import Document, Job
from datetime import datetime, timezone


def create_document_and_job(
    db: Session,
    document_id: uuid.UUID,
    job_id: str,
    filename: str,
    ext: str,
    size: int,
    storage_path: str,
):
    doc = Document(
        id=document_id,
        job_id=job_id,
        filename=filename,
        file_type=ext,
        file_size_bytes=size,
        storage_path=storage_path,
    )
    db.add(doc)
    db.flush()

    job = Job(
        id=job_id,
        document_id=doc.id,
        status="uploaded",
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
    return (
        db.query(Job)
        .order_by(Job.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def clear_incremental_data(db: Session, job_id: str):
    """No-op: requirements and test_cases no longer live in Postgres."""
    pass


def save_results(db: Session, job_id: str, results_dict: dict):
    """No-op: all artifacts are persisted to MongoDB by the persistence_node."""
    pass

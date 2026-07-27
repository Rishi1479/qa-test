import uuid
from datetime import datetime, timezone
# pyrefly: ignore [missing-import]
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

# ---------------------------------------------------------
# Supabase schema: only documents + jobs are stored here.
# All richer artifacts (requirements, test_cases, scenarios,
# traceability, coverage) live in MongoDB.
# ---------------------------------------------------------

class Document(Base):
    __tablename__ = "documents"
    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id        = Column(String, unique=True, nullable=False)
    filename      = Column(String, nullable=False)
    file_type     = Column(String)
    file_size_bytes = Column(Integer)
    storage_path  = Column(String, nullable=False)
    created_at    = Column(DateTime(timezone=True), default=utcnow)
    updated_at    = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    jobs = relationship("Job", back_populates="document", cascade="all, delete")


class Job(Base):
    __tablename__ = "jobs"
    id            = Column(String, primary_key=True)
    document_id   = Column(UUID(as_uuid=True), ForeignKey("documents.id"), nullable=False)
    status        = Column(String, default="processing")
    error_message = Column(String, nullable=True)
    created_at    = Column(DateTime(timezone=True), default=utcnow)
    updated_at    = Column(DateTime(timezone=True), default=utcnow)
    completed_at  = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    document = relationship("Document", back_populates="jobs")

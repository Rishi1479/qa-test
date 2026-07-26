import uuid
from datetime import datetime, timezone
# pyrefly: ignore [missing-import]
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

# ---------------------------------------------------------
# New Supabase-aligned Schema
# ---------------------------------------------------------

class Document(Base):
    __tablename__ = "documents"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String, unique=True, nullable=False)
    filename = Column(String, nullable=False)
    file_type = Column(String)
    file_size_bytes = Column(Integer)
    storage_path = Column(String, nullable=False)
    uploaded_by = Column(UUID(as_uuid=True), nullable=True) # References auth.users if available
    parsed_status = Column(String, default="pending")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    jobs = relationship("Job", back_populates="document", cascade="all, delete")

class Job(Base):
    __tablename__ = "jobs"
    id = Column(String, primary_key=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    status = Column(String, default="processing")
    error_message = Column(String, nullable=True)
    langsmith_trace_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    document = relationship("Document", back_populates="jobs")
    requirements = relationship("Requirement", back_populates="job", cascade="all, delete")

class Requirement(Base):
    __tablename__ = "requirements"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    job_id = Column(String, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    req_code = Column(String, index=True)
    title = Column(String)
    raw_text = Column(String)
    requirement_type = Column(String)
    priority = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)

    # Relationships
    job = relationship("Job", back_populates="requirements")
    test_cases = relationship("TestCase", back_populates="requirement", cascade="all, delete")

class TestCase(Base):
    __tablename__ = "test_cases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    requirement_id = Column(UUID(as_uuid=True), ForeignKey("requirements.id", ondelete="CASCADE"), nullable=False)
    type = Column(String)
    title = Column(String)
    preconditions = Column(String)
    postconditions = Column(String)
    steps = Column(JSONB)
    expected_result = Column(String)
    test_data = Column(JSONB)
    llm_raw_response = Column(JSONB)
    langsmith_run_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    requirement = relationship("Requirement", back_populates="test_cases")

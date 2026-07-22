from datetime import datetime, timezone
from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.database import Base

def utcnow():
    return datetime.now(timezone.utc)

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    projects = relationship("Project", back_populates="user")

class Project(Base):
    __tablename__ = "projects"
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.id"))
    name = Column(String)
    created_at = Column(DateTime(timezone=True), default=utcnow)
    
    user = relationship("User", back_populates="projects")
    jobs = relationship("AnalysisJob", back_populates="project")

class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"
    job_id = Column(String, primary_key=True, index=True)
    project_id = Column(String, ForeignKey("projects.id"), nullable=True)
    filename = Column(String, nullable=False)
    storage_url = Column(String, nullable=True)
    storage_backend = Column(String, nullable=True)
    status = Column(String, default="uploaded")
    created_at = Column(DateTime(timezone=True), default=utcnow)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    
    project = relationship("Project", back_populates="jobs")
    requirements = relationship("RequirementRecord", back_populates="job", cascade="all, delete")
    scenarios = relationship("ScenarioRecord", back_populates="job", cascade="all, delete")
    test_cases = relationship("TestCaseRecord", back_populates="job", cascade="all, delete")
    acceptance_criteria = relationship("AcceptanceCriterionRecord", back_populates="job", cascade="all, delete")
    traceability = relationship("TraceabilityRecord", back_populates="job", cascade="all, delete")
    coverage_summary = relationship("CoverageSummaryRecord", back_populates="job", uselist=False, cascade="all, delete")

class RequirementRecord(Base):
    
    __tablename__ = "requirements"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"))
    req_id = Column(String, index=True)
    title = Column(String)
    description = Column(String)
    type = Column(String)
    priority = Column(String)
    
    # Store all the list-based and extra fields as a JSON blob to match the EnrichedRequirement Pydantic schema easily
    data = Column(JSON) 
    
    job = relationship("AnalysisJob", back_populates="requirements")

class ScenarioRecord(Base):
    __tablename__ = "scenarios"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"))
    scenario_id = Column(String, index=True)
    req_id = Column(String, index=True)
    title = Column(String)
    category = Column(String)
    
    job = relationship("AnalysisJob", back_populates="scenarios")

class TestCaseRecord(Base):
    __tablename__ = "test_cases"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"))
    test_id = Column(String, index=True)
    req_id = Column(String, index=True)
    scenario_id = Column(String, index=True)
    title = Column(String)
    type = Column(String)
    priority = Column(String)
    expected_result = Column(String)
    
    # store lists (preconditions, steps, test_data, postconditions) as JSON
    data = Column(JSON)
    
    job = relationship("AnalysisJob", back_populates="test_cases")

class AcceptanceCriterionRecord(Base):
    __tablename__ = "acceptance_criteria"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"))
    req_id = Column(String, index=True)
    given_clause = Column(String)
    when_clause = Column(String)
    then_clause = Column(String)
    
    job = relationship("AnalysisJob", back_populates="acceptance_criteria")

class TraceabilityRecord(Base):
    __tablename__ = "traceability"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"))
    req_id = Column(String, index=True)
    covered = Column(Boolean, default=False)
    
    # lists of IDs
    scenario_ids = Column(JSON)
    test_ids = Column(JSON)
    
    job = relationship("AnalysisJob", back_populates="traceability")

class CoverageSummaryRecord(Base):
    __tablename__ = "coverage_summaries"
    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String, ForeignKey("analysis_jobs.job_id"), unique=True)
    total_requirements = Column(Integer)
    covered_requirements = Column(Integer)
    coverage_percent = Column(Float)
    positive_count = Column(Integer, default=0)
    negative_count = Column(Integer, default=0)
    boundary_count = Column(Integer, default=0)
    edge_count = Column(Integer, default=0)
    
    priority_breakdown = Column(JSON)
    missing_coverage = Column(JSON)
    
    job = relationship("AnalysisJob", back_populates="coverage_summary")

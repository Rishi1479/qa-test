from __future__ import annotations
import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.schemas.schemas import UploadResponse
from app.tools.supabase_tool import supabase_tool
from app.database import SessionLocal
from app.crud.crud import create_job

router = APIRouter(tags=["documents"])

_ALLOWED_EXT = {".pdf", ".docx", ".md", ".markdown", ".txt"}
_MAX_BYTES = 20 * 1024 * 1024  # 20MB


@router.post("/upload", response_model=UploadResponse)
async def upload_document(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(400, f"Unsupported file type '{ext}'. Allowed: {sorted(_ALLOWED_EXT)}")

    content = await file.read()
    if not content:
        raise HTTPException(400, "Uploaded file is empty")
    if len(content) > _MAX_BYTES:
        raise HTTPException(400, "File exceeds 20MB limit")

    job_id = f"JOB-{uuid.uuid4().hex[:10].upper()}"

    storage_url = supabase_tool.upload(job_id, file.filename, content)
    with SessionLocal() as db:
        create_job(db, job_id, file.filename, storage_url, supabase_tool.backend)

    return UploadResponse(
        job_id=job_id,
        filename=file.filename,
        status="uploaded",
        storage_backend=supabase_tool.backend,
    )

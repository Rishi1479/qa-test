"""
These tests exercise the LOCAL FALLBACK backends only (no MONGODB_URI /
SUPABASE_URL set), which is what CI / an offline grading run uses. The
real Atlas/Supabase backends share the exact same tool interface, see
tools/mongodb_tool.py and tools/supabase_tool.py docstrings.
"""
import importlib
import os


def test_supabase_fallback_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    from app import config as config_module
    importlib.reload(config_module)
    from app.tools import supabase_tool as st_module
    importlib.reload(st_module)

    tool = st_module.SupabaseStorageTool()
    assert tool.backend == "local_disk_fallback"

    tool.upload("JOB-1", "req.pdf", b"hello world")
    assert tool.download("JOB-1", "req.pdf") == b"hello world"
    tool.delete("JOB-1", "req.pdf")
    assert not os.path.exists(os.path.join(tmp_path, "originals", "JOB-1", "req.pdf"))


def test_mongo_fallback_job_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    from app import config as config_module
    importlib.reload(config_module)
    from app.tools import mongodb_tool as mt_module
    importlib.reload(mt_module)

    tool = mt_module.MongoDBAtlasTool()
    assert tool.backend == "local_json_fallback"

    tool.create_job("JOB-1", "req.pdf", "storage/originals/JOB-1/req.pdf", "local_disk_fallback")
    job = tool.get_job("JOB-1")
    assert job["status"] == "uploaded"

    tool.save_results("JOB-1", {"coverage": {"coverage_percent": 100}})
    assert tool.get_results("JOB-1")["coverage"]["coverage_percent"] == 100

    tool.update_job_status("JOB-1", "completed")
    assert tool.get_job("JOB-1")["status"] == "completed"

    assert len(tool.list_jobs()) == 1
    tool.delete_job("JOB-1")
    assert tool.get_job("JOB-1") is None

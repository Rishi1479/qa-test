"""
MongoDB Tool
---------------------
Single responsibility: persist and retrieve execution logs from LangGraph.
One collection:

  execution_logs    {job_id, started_at, completed_at, duration_seconds, node_timings, errors}

Real backend: MongoDB via pymongo (a plain connection
string in MONGODB_URI).

Fallback: a local JSON-file store with the identical method signatures,
used only when MONGODB_URI is unset, for the same offline-demoability
reason as the Supabase tool. See docs/approach.md, decision D1.
"""
from __future__ import annotations
import json
import os
import threading
from datetime import datetime, timezone
from app.config import settings

_LOCAL_PATH = os.path.join(settings.LOCAL_STORAGE_DIR, "mongo_fallback.json")
_lock = threading.Lock()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _LocalJSONBackend:
    """Drop-in stand-in for the three Mongo collections, same call shape."""

    def __init__(self):
        os.makedirs(settings.LOCAL_STORAGE_DIR, exist_ok=True)
        if not os.path.exists(_LOCAL_PATH):
            self._write({"execution_logs": {}})

    def _read(self) -> dict:
        with open(_LOCAL_PATH, "r") as f:
            return json.load(f)

    def _write(self, data: dict) -> None:
        with open(_LOCAL_PATH, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def upsert(self, collection: str, job_id: str, doc: dict) -> None:
        with _lock:
            data = self._read()
            data.setdefault(collection, {})
            existing = data[collection].get(job_id, {})
            existing.update(doc)
            data[collection][job_id] = existing
            self._write(data)

    def get(self, collection: str, job_id: str) -> dict | None:
        data = self._read()
        return data.get(collection, {}).get(job_id)

    def list_all(self, collection: str) -> list[dict]:
        data = self._read()
        return list(data.get(collection, {}).values())

    def delete(self, collection: str, job_id: str) -> None:
        with _lock:
            data = self._read()
            data.get(collection, {}).pop(job_id, None)
            self._write(data)


class _MongoBackend:
    def __init__(self):
        from pymongo import MongoClient
        self._client = MongoClient(settings.MONGODB_URI)
        self._db = self._client[settings.MONGODB_DB]

    def upsert(self, collection: str, job_id: str, doc: dict) -> None:
        self._db[collection].update_one({"job_id": job_id}, {"$set": doc}, upsert=True)

    def get(self, collection: str, job_id: str) -> dict | None:
        result = self._db[collection].find_one({"job_id": job_id}, {"_id": 0})
        return result

    def list_all(self, collection: str) -> list[dict]:
        return list(self._db[collection].find({}, {"_id": 0}))

    def delete(self, collection: str, job_id: str) -> None:
        self._db[collection].delete_one({"job_id": job_id})


class MongoDBTool:
    def __init__(self):
        if settings.mongo_enabled:
            self._backend = _MongoBackend()
            self._backend_name = "mongodb"
        else:
            self._backend = _LocalJSONBackend()
            self._backend_name = "local_json_fallback"

    def get_client(self):
        if hasattr(self._backend, "_client"):
            return self._backend._client
        return None

    @property
    def backend(self) -> str:
        return self._backend_name

    def delete_job(self, job_id: str) -> None:
        self._backend.delete("execution_logs", job_id)

    # ---- execution_logs collection ----
    def save_execution_log(self, job_id: str, log: dict) -> None:
        self._backend.upsert("execution_logs", job_id, {"job_id": job_id, **log})

    def get_execution_log(self, job_id: str) -> dict | None:
        return self._backend.get("execution_logs", job_id)
        
    # ---- results collection ----
    def save_results(self, job_id: str, results: dict) -> None:
        self._backend.upsert("results", job_id, {"job_id": job_id, "results": results})
        
    def get_results(self, job_id: str) -> dict | None:
        return self._backend.get("results", job_id)


mongodb_tool = MongoDBTool()

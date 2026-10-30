from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from backend.app.config import UPLOAD_DIR
from backend.app.services import tasks as task_svc

router = APIRouter()


@router.post("/tasks")
async def create_task(files: list[UploadFile] = File(...)):
    payload = []
    for f in files:
        payload.append((f.filename or "unnamed", await f.read()))
    meta = task_svc.create_task(payload)
    folder = str(UPLOAD_DIR / meta["task_id"])
    try:
        from ai.graph.controller import invoke

        result = invoke({"task_id": meta["task_id"], "folder": folder})
        task_svc.save_result(meta["task_id"], result)
        task_svc.set_status(meta["task_id"], "reviewed")
        meta["status"] = "reviewed"
        meta["issue_count"] = len(result.get("issues") or [])
        meta["logs"] = result.get("logs") or []
    except Exception as exc:
        meta["error"] = str(exc)
    (Path(folder) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return meta


@router.get("/tasks/{task_id}")
def get_task(task_id: str):
    data = task_svc.get_task(task_id)
    if not data:
        raise HTTPException(404, "task not found")
    return data

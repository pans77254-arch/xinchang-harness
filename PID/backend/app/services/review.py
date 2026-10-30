"""审查编排。只允许 ai.graph.invoke，禁止在此写算子或抽字段。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.graph.controller import invoke
from backend.app.services.tasks import (
    create_folder_task,
    get_task,
    load_result,
    save_result,
    set_status,
    update_issue_status,
)


def present(task_id: str, result: dict[str, Any]) -> dict[str, Any]:
    """给前端的 PID 识别结果。"""
    task = get_task(task_id) or {}
    return {
        "task_id": task_id,
        "folder": task.get("folder") or result.get("folder") or "",
        "plan": result.get("plan") or {},
        "drawing_json": (result.get("artifacts") or {}).get("drawing_json") or {},
        "pid_files": result.get("pid_files") or [],
        "detections": result.get("detections") or [],
        "issues": result.get("issues") or [],
        "validation": result.get("validation") or {},
        "logs": result.get("logs") or [],
    }


def run_folder(folder: str, skill_ids: list[str] | None = None) -> dict[str, Any]:
    task = create_folder_task(folder, [])
    task_id = task["task_id"]
    result = invoke(
        {
            "task_id": task_id,
            "folder": folder,
            "files": [],
            "storage_dir": folder,
        }
    )
    save_result(task_id, result)
    set_status(task_id, "reviewed")
    return present(task_id, result)


def get_presented(task_id: str) -> dict[str, Any]:
    if not get_task(task_id):
        raise FileNotFoundError(task_id)
    result = load_result(task_id)
    if result is None:
        raise FileNotFoundError(task_id)
    return present(task_id, result)


def review_issue(task_id: str, issue_id: str, review_status: str) -> dict[str, Any]:
    if review_status not in {"pending", "confirmed", "rejected"}:
        raise ValueError(review_status)
    result = update_issue_status(task_id, issue_id, review_status)
    return present(task_id, result)


def run_review(task_id: str, skill_ids: list[str] | None = None) -> dict[str, Any]:
    task = get_task(task_id)
    if not task:
        raise FileNotFoundError(task_id)
    files = task.get("files") or []
    folder = str(files[0].get("path") or "") if files else ""
    if folder:
        folder = str(Path(folder).parent)
    result = invoke(
        {
            "task_id": task_id,
            "folder": folder,
            "files": files,
            "skill_ids": skill_ids or [],
            "storage_dir": folder,
        }
    )
    save_result(task_id, result)
    return result

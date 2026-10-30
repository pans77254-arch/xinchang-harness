from __future__ import annotations

from typing import Any, TypedDict


class ReviewState(TypedDict, total=False):
    task_id: str
    project_id: str
    folder: str
    files: list[dict[str, Any]]
    skill_ids: list[str]
    storage_dir: str
    file_types: dict[str, Any]
    pid_files: list[str]
    plan: dict[str, Any]
    pages: list[dict[str, Any]]
    detections: list[dict[str, Any]]
    artifacts: dict[str, Any]
    issues: list[dict[str, Any]]
    logs: list[str]
    validation: dict[str, Any]

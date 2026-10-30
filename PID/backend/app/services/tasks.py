"""任务元数据。只存路径与状态，禁止在此写审查算法。"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from backend.app.config import RESULT_DIR, UPLOAD_DIR


def _task_dir(task_id: str) -> Path:
    p = UPLOAD_DIR / task_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def create_task(files: list[tuple[str, bytes]]) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:10]
    d = _task_dir(task_id)
    saved = []
    for name, content in files:
        dest = d / name
        dest.write_bytes(content)
        saved.append({"id": dest.stem, "name": name, "path": str(dest)})
    meta = {"task_id": task_id, "files": saved, "status": "uploaded"}
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def get_task(task_id: str) -> dict[str, Any] | None:
    p = _task_dir(task_id) / "meta.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_result(task_id: str, result: dict[str, Any]) -> Path:
    out = RESULT_DIR / f"{task_id}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def create_folder_task(folder: str, skill_ids: list[str]) -> dict[str, Any]:
    task_id = uuid.uuid4().hex[:10]
    meta = {
        "task_id": task_id,
        "kind": "folder",
        "folder": folder,
        "skill_ids": skill_ids,
        "files": [],
        "status": "reviewing",
    }
    (_task_dir(task_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def set_status(task_id: str, status: str) -> None:
    meta = get_task(task_id)
    if not meta:
        raise FileNotFoundError(task_id)
    meta["status"] = status
    (_task_dir(task_id) / "meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_result(task_id: str) -> dict[str, Any] | None:
    path = RESULT_DIR / f"{task_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_issue_status(task_id: str, issue_id: str, review_status: str) -> dict[str, Any]:
    result = load_result(task_id)
    if result is None:
        raise FileNotFoundError(task_id)
    found = False
    for issue in result.get("issues") or []:
        if issue.get("issue_id") == issue_id:
            issue["review_status"] = review_status
            found = True
            break
    if not found:
        raise KeyError(issue_id)
    save_result(task_id, result)
    return result

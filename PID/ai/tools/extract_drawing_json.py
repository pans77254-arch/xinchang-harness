"""从已经抽好的图纸 info JSON 里取出说明、图表、图框字段。不重新识别、不调用模型。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.tools.registry import register

_SKIP = {"path", "error", "info", "lines", "rows"}


def _lines_of(block: dict[str, Any]) -> list[dict[str, Any]]:
    info = block.get("info")
    if isinstance(info, dict) and isinstance(info.get("lines"), list):
        return [line for line in info["lines"] if isinstance(line, dict)]
    lines = block.get("lines")
    return [line for line in lines if isinstance(line, dict)] if isinstance(lines, list) else []


def _rows_of(block: dict[str, Any]) -> list[Any]:
    info = block.get("info")
    if isinstance(info, dict) and isinstance(info.get("rows"), list):
        return info["rows"]
    rows = block.get("rows")
    return rows if isinstance(rows, list) else []


def _fields_of(block: dict[str, Any]) -> dict[str, str]:
    payload = block.get("info") if isinstance(block.get("info"), dict) and "lines" not in block.get("info") and "rows" not in block.get("info") else block
    if not isinstance(payload, dict):
        return {}
    fields: dict[str, str] = {}
    for key, value in payload.items():
        if key in _SKIP:
            continue
        text = "" if value is None else str(value).strip()
        if text:
            fields[str(key)] = text
    return fields


def _block(page: dict[str, Any], name: str) -> dict[str, Any]:
    value = page.get(name)
    return value if isinstance(value, dict) else {}


def read_info(path: str | Path) -> dict[str, Any]:
    """读一份 info JSON，返回按页整理的说明行、图表行和图框字段。"""
    src = Path(path)
    data = json.loads(src.read_text(encoding="utf-8"))
    file_name = str(data.get("file") or src.stem)
    pages: list[dict[str, Any]] = []
    merged: dict[str, str] = {}
    for record in data.get("pages") or []:
        if not isinstance(record, dict):
            continue
        notes = _block(record, "notes")
        chart = _block(record, "chart")
        frame = _block(record, "frame")
        lines: list[dict[str, Any]] = []
        for block in notes.get("info") or []:
            if isinstance(block, dict):
                lines.extend(_lines_of(block))
        tables = []
        for block in chart.get("info") or []:
            if isinstance(block, dict):
                tables.append({"path": str(block.get("path") or ""), "rows": _rows_of(block)})
        fields = []
        for block in frame.get("info") or []:
            if not isinstance(block, dict):
                continue
            item = {"path": str(block.get("path") or ""), **_fields_of(block)}
            fields.append(item)
            for key, value in item.items():
                if key != "path" and value and key not in merged:
                    merged[key] = value
        pages.append(
            {
                "page": record.get("page") or 0,
                "metadata_png": str(record.get("metadata_png") or ""),
                "notes": {
                    "has_notes": bool(notes.get("has_notes")),
                    "paths": list(notes.get("notes_path") or []),
                    "lines": lines,
                },
                "chart": {
                    "has_chart": bool(chart.get("has_chart")),
                    "paths": list(chart.get("chart_path") or []),
                    "tables": tables,
                },
                "frame": {
                    "has_frame": bool(frame.get("has_frame")),
                    "paths": list(frame.get("frame_path") or []),
                    "fields": fields,
                },
            }
        )
    return {
        "file": file_name,
        "info": str(src),
        "source": str(data.get("path") or ""),
        "page_count": data.get("page_count") or len(pages),
        "fields": merged,
        "pages": pages,
    }


def read_folder(folder: str | Path) -> dict[str, Any]:
    """读取文件夹里全部图纸 info JSON。"""
    root = Path(folder)
    files = []
    if root.is_dir():
        for path in sorted(root.glob("*.info.json")):
            try:
                files.append(read_info(path))
            except (OSError, json.JSONDecodeError) as exc:
                files.append({"file": path.name, "info": str(path), "error": str(exc), "pages": [], "fields": {}})
    return {"files": files}


@register("extract.drawing_json", produces=["drawing_json"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    """供规划点和检查技能共用。优先读 artifacts.folder 下的 info JSON。"""
    folder = str(artifacts.get("folder") or "")
    paths = [str(item.get("info") or "") for item in (artifacts.get("pages") or []) if item.get("info")]
    if paths:
        loaded = []
        seen: set[str] = set()
        for raw in paths:
            if raw in seen or not Path(raw).is_file():
                continue
            seen.add(raw)
            loaded.append(read_info(raw))
        return {"drawing_json": {"files": loaded}}
    if folder:
        return {"drawing_json": read_folder(folder)}
    return {"drawing_json": {"files": [], "error": "没有文件夹或 info JSON"}}

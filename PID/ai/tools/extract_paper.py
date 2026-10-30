"""抽取 PDF 图幅。复用 paper.measure_page，只返回数据，不做任何业务判断。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import fitz

from ai.tools.paper import measure_page
from ai.tools.registry import register

PDF_EXT = {".pdf"}


def _folder_from(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> str:
    folder = str(artifacts.get("folder") or "")
    if folder:
        return folder
    if files:
        return str(Path(files[0].get("path") or "").parent)
    return ""


def _list_pdfs(folder: str, files: list[dict[str, Any]]) -> list[dict[str, str]]:
    if files:
        return [f for f in files if Path(str(f.get("name") or "")).suffix.lower() in PDF_EXT]
    root = Path(folder)
    if not root.is_dir():
        return []
    return [
        {"name": p.name, "path": str(p)}
        for p in sorted(root.iterdir())
        if p.is_file() and not p.name.startswith("~$") and p.suffix.lower() in PDF_EXT
    ]


@register("extract.paper", produces=["paper"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    folder = _folder_from(files, artifacts)
    items: list[dict[str, Any]] = []
    logs: list[str] = []
    for f in _list_pdfs(folder, files):
        name = str(f.get("name") or "")
        path = str(f.get("path") or "")
        if not path or not Path(path).is_file():
            continue
        try:
            doc = fitz.open(path)
        except Exception as exc:
            logs.append(f"extract.paper: 打开 {name} 失败 {exc}")
            continue
        try:
            if doc.page_count:
                measured = measure_page(doc[0])
                items.append(
                    {
                        "file": name,
                        "paper_size": str(measured.get("size") or ""),
                        "paper_width_mm": measured.get("width_mm"),
                        "paper_height_mm": measured.get("height_mm"),
                    }
                )
        finally:
            doc.close()
    return {"paper": {"items": items, "logs": logs}}
"""归档文件清单。可从任务 files + 已抽出的 title_block.drawing_no 对齐。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.tools.registry import register


@register("extract.file_list", produces=["file_list"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # 骨架只列文件名；图号对齐留给算法组在抽出 title_block 之后补
    items = []
    for f in files:
        name = f.get("name") or ""
        if name.startswith("~$"):
            continue
        items.append(
            {
                "name": name,
                "path": f.get("path"),
                "drawing_no": "",
                "kind": Path(name).suffix,
            }
        )
    return {
        "file_list": {
            "items": items,
            "drawing_nos": [i["drawing_no"] for i in items if i.get("drawing_no")],
            "count": len(items),
            "names": [i["name"] for i in items],
        }
    }

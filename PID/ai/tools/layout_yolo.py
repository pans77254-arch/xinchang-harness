"""图纸布局 / 图框检测。算法组实现 YOLO 或 PP-DocLayout。接口名保持 layout.detect。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("layout.detect", produces=["layout"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # TODO 算法组：YOLO 检出 title_block / legend / main 区域
    # 失败兜底可在工具内部走整图 VLM，不要让审查点自己调
    return {
        "layout": {
            "_stub": True,
            "items": [
                {
                    "file_id": f.get("id"),
                    "name": f.get("name"),
                    "regions": [],
                    "detector": "stub",
                }
                for f in files
            ],
            "note": "未实现：YOLO / PP-DocLayout",
        }
    }

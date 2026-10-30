"""抽取目录 JSON。目录索引一致性不走这里，由信息抽取智能体读目录页图片。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("extract.toc", produces=["toc"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # TODO 算法组：定位「目录」文件 → md → {drawing_no, name, version} 列表
    return {
        "toc": {
            "_stub": True,
            "entries": [],
            "drawing_nos": [],
            "count": 0,
            "stage": "",
            "project_no": "",
            "note": "未实现：目录信息抽取",
        }
    }

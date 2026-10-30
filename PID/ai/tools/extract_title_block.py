"""抽取标题栏 JSON。应先使用 layout 中的 title_block 框，禁止整图乱扫（除非检测失败兜底）。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("extract.title_block", produces=["title_block"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # 图框栏位与长庆标题栏一致：签署六行、右侧五级名称、底栏阶段到版次。
    # TODO 算法组：VLM / OCR，字段见 form.toc_index.yaml 的 drawing_fields。
    return {
        "title_block": {
            "_stub": True,
            "items": [],
            "drawing_nos": [],
            "stages": [],
            "note": "未实现：标题栏信息抽取",
        }
    }

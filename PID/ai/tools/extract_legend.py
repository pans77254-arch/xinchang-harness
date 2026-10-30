"""图例抽取。P&ID / 总图审查点 needs: legend 时由总控调用。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("extract.legend", produces=["legend"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # TODO 算法组
    return {"legend": {"_stub": True, "items": [], "note": "未实现：图例抽取"}}

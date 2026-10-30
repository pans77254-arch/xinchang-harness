"""P&ID Image-to-Graph。算法组实现，审查点只声明 needs: pid_graph。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("extract.pid_graph", produces=["pid_graph"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # TODO 算法组：Swin / I2G → 节点+边，写入图库
    return {"pid_graph": {"_stub": True, "nodes": [], "edges": [], "note": "未实现：Image-to-Graph"}}

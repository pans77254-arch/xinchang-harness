"""总图空间要素 / CAD 量距。算法组实现。"""

from __future__ import annotations

from typing import Any

from ai.tools.registry import register


@register("extract.site_features", produces=["site_features"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    # TODO 算法组：ezdxf / AutoCAD COM 建构筑物、间距
    return {"site_features": {"_stub": True, "items": [], "note": "未实现：总图要素与量距"}}

"""工具注册中心。算法组实现函数体，禁止改 PRODUCES / 函数签名。"""

from __future__ import annotations

from typing import Any, Callable

ToolFn = Callable[[list[dict[str, Any]], dict[str, Any]], dict[str, Any]]

# need 工件名 → 工具名
NEED_TO_TOOL: dict[str, str] = {
    "layout": "layout.detect",
    "toc": "extract.toc",
    "title_block": "extract.title_block",
    "file_list": "extract.file_list",
    "legend": "extract.legend",
    "pid_graph": "extract.pid_graph",
    "site_features": "extract.site_features",
    "file_types": "extract.file_types",
    "paper": "extract.paper",
    "pid_sheets": "extract.pid_sheets",
    "notes": "extract.notes",
    "drawing_json": "extract.drawing_json",
}

TOOLS: dict[str, dict[str, Any]] = {}


def register(name: str, produces: list[str]):
    def deco(fn: ToolFn) -> ToolFn:
        TOOLS[name] = {"fn": fn, "produces": produces}
        return fn

    return deco


def fill(needs: list[str], files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    """总控按 needs 并集调用工具。同一工件只抽一次。"""
    out = dict(artifacts)
    for need in needs:
        if need in out and out[need]:
            continue
        tool_name = NEED_TO_TOOL.get(need)
        if not tool_name or tool_name not in TOOLS:
            out[need] = {"_stub": True, "_missing_tool": tool_name or need}
            continue
        produced = TOOLS[tool_name]["fn"](files, out)
        out.update(produced)
    return out


def load_tools() -> None:
    from ai.tools import (  # noqa: F401
        extract_file_list,
        extract_drawing_json,
        extract_legend,
        extract_notes,
        extract_paper,
        extract_pid_graph,
        extract_pid_sheets,
        extract_site,
        extract_title_block,
        extract_toc,
        file_classifier,
        image_preprocess,
        layout_yolo,
        word2png,
        pdf2png,
    )

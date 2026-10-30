"""目录索引一致性入口。

流程由 ai/workflows/form.toc_index.yaml 决定，本文件不再写死边。
"""

from __future__ import annotations

from typing import Any

from ai.workflow.runner import get_graph, run_workflow

WORKFLOW_ID = "form.toc_index"


def build():
    return get_graph(WORKFLOW_ID)


graph = build()


def run(task: dict[str, Any]) -> dict[str, Any]:
    return run_workflow(WORKFLOW_ID, task)

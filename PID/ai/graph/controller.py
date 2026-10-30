"""PID 审查入口。

步骤顺序由 ai/workflows/pid.review.yaml 决定，本文件不再写死边。
"""

from __future__ import annotations

from typing import Any

from ai.workflow.runner import get_graph as get_workflow_graph
from ai.workflow.runner import run_workflow

WORKFLOW_ID = "pid.review"


def build_graph():
    return get_workflow_graph(WORKFLOW_ID)


def get_graph():
    return build_graph()


def invoke(task: dict[str, Any]) -> dict[str, Any]:
    """后端唯一允许调用的 AI 入口。"""
    return run_workflow(WORKFLOW_ID, task)

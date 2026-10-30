"""按 workflow.yaml 组装并执行 LangGraph。

改 yaml 的 nodes / next / on_halt 就会改审查流程。
step 名必须在 ai.workflow.STEPS 中登记。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

import yaml
from langgraph.graph import END, START, StateGraph

from ai.workflow import STEPS, get_step

WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / "workflows"


class WorkflowState(TypedDict, total=False):
    task_id: str
    project_id: str
    folder: str
    files: list
    skill_ids: list
    storage_dir: str
    work_dir: str
    skill: dict
    catalog_file: dict
    word_files: list
    pdf_files: list
    catalog_image: str
    catalog_paper: dict
    catalog: dict
    page_images: list
    word_sources: list
    extracted: list
    unidentified: list
    artifacts: dict
    issues: list
    side_issues: list
    logs: list
    validation: dict
    halt: bool
    file_types: dict
    pid_files: list
    plan: dict
    pages: list
    detections: list


def workflow_path(workflow_id: str) -> Path:
    return WORKFLOWS_DIR / f"{workflow_id}.yaml"


def read_workflow_text(workflow_id: str) -> str | None:
    path = workflow_path(workflow_id)
    if not path.is_file():
        return None
    return path.read_text(encoding="utf-8")


def load_workflow(workflow_id: str) -> dict[str, Any]:
    text = read_workflow_text(workflow_id)
    if text is None:
        raise FileNotFoundError(workflow_id)
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict) or not data.get("id"):
        raise ValueError(f"workflow 格式不对：{workflow_id}")
    return data


def save_workflow_text(workflow_id: str, text: str) -> None:
    path = workflow_path(workflow_id)
    if not path.is_file():
        raise FileNotFoundError(workflow_id)
    data = yaml.safe_load(text)
    if not isinstance(data, dict) or data.get("id") != workflow_id:
        raise ValueError("不能修改工作流编号")
    path.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")


def ensure_steps_loaded() -> None:
    if "ingest_folder" not in STEPS:
        from ai.workflow import steps_toc  # noqa: F401
    if "extract" not in STEPS:
        from ai.workflow import steps_pid  # noqa: F401


def guard_workflow(data: dict[str, Any]) -> str:
    """校验 workflow 只能使用已登记 step。"""
    ensure_steps_loaded()
    if not isinstance(data, dict):
        return "工作流不是配置对象"
    for key in ("id", "entry", "nodes"):
        if key not in data:
            return f"工作流缺少 {key}"
    nodes = data.get("nodes")
    if not isinstance(nodes, dict) or not nodes:
        return "工作流 nodes 不能为空"
    entry = data.get("entry")
    if entry not in nodes:
        return f"入口节点不存在：{entry}"
    for name, node in nodes.items():
        if not isinstance(node, dict):
            return f"节点 {name} 格式不对"
        step_name = str(node.get("step") or "")
        if step_name not in STEPS:
            return f"未登记的步骤：{step_name}"
        nxt = node.get("next")
        if nxt not in (None, "", "END") and nxt not in nodes:
            return f"节点 {name} 的 next 不存在：{nxt}"
        halt = node.get("on_halt")
        if halt not in (None, "", "END") and halt not in nodes:
            return f"节点 {name} 的 on_halt 不存在：{halt}"
    return ""


def build_from_yaml(data: dict[str, Any]):
    ensure_steps_loaded()
    reason = guard_workflow(data)
    if reason:
        raise ValueError(reason)

    graph = StateGraph(WorkflowState)
    nodes: dict[str, Any] = data["nodes"]
    for name, node in nodes.items():
        graph.add_node(name, get_step(str(node["step"])))

    entry = str(data["entry"])
    graph.add_edge(START, entry)

    for name, node in nodes.items():
        nxt = node.get("next") or "END"
        halt_to = node.get("on_halt")

        if halt_to:
            halt_target = END if halt_to == "END" else str(halt_to)
            cont_target = END if nxt == "END" else str(nxt)

            def _make_router(halt_target=halt_target, cont_target=cont_target):
                def _router(state: dict[str, Any]) -> str:
                    return "halt" if state.get("halt") else "continue"

                return _router

            graph.add_conditional_edges(
                name,
                _make_router(),
                {"halt": halt_target, "continue": cont_target},
            )
        elif nxt == "END":
            graph.add_edge(name, END)
        else:
            graph.add_edge(name, str(nxt))

    return graph.compile()


_CACHE: dict[str, Any] = {}


def get_graph(workflow_id: str):
    if workflow_id not in _CACHE:
        _CACHE[workflow_id] = build_from_yaml(load_workflow(workflow_id))
    return _CACHE[workflow_id]


def clear_cache(workflow_id: str | None = None) -> None:
    if workflow_id is None:
        _CACHE.clear()
    else:
        _CACHE.pop(workflow_id, None)


def run_workflow(workflow_id: str, task: dict[str, Any]) -> dict[str, Any]:
    init: dict[str, Any] = {
        "task_id": task.get("task_id") or workflow_id,
        "project_id": task.get("project_id") or "",
        "folder": task.get("folder") or "",
        "files": task.get("files") or [],
        "skill_ids": task.get("skill_ids") or [workflow_id],
        "storage_dir": task.get("storage_dir") or "",
        "logs": [],
        "issues": [],
        "side_issues": [],
        "artifacts": {"file_types": task["file_types"]} if task.get("file_types") else {},
        "validation": {},
    }
    return get_graph(workflow_id).invoke(init)

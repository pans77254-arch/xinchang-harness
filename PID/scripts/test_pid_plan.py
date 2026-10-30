"""规划路由只选择已启用的检查点。不访问模型和 YOLO。

用法：python scripts/test_pid_plan.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.agents.pid_plan import build_plan
from ai.graph.controller import WORKFLOW_ID, build_graph
from ai.workflow.runner import load_workflow
from ai.workflow.steps_pid import plan


def main() -> None:
    empty = build_plan([])
    assert empty["tools"] == [] and empty["skills"] == [], empty

    planned = build_plan([{"file": "a.pdf", "page": 1, "image": "a.png", "info": "a.info.json"}])
    assert planned["tools"] == ["pid.detect"], planned
    skill_ids = [item["id"] for item in planned["skills"]]
    assert "form.notes_typo" in skill_ids, planned

    from ai.agents.pid_plan import _need_human, finish_checkpoint, save_checkpoint
    from ai.agents.skill_loader import RULES_DIR

    held = _need_human("量防火间距", "需要量距，当前没有这项数据")
    assert held["need_human"] is True and held["applied"] is False
    created = finish_checkpoint(
        "阶段必须是施工图",
        {"name": "阶段必须是施工图", "when": "has_frame", "criterion": "图框阶段栏必须填写施工图", "unsupported": ""},
    )
    refused = save_checkpoint("量距", "has_distance", "量防火间距")
    assert refused["ok"] is False and refused["need_human"] is True
    try:
        assert created["ok"] is True, created
        again = build_plan([{"file": "a.pdf", "page": 1}])
        assert created["id"] in [item["id"] for item in again["skills"]], again
    finally:
        path = RULES_DIR / f"{created.get('id')}.yaml"
        if path.is_file():
            path.unlink()

    flow = load_workflow(WORKFLOW_ID)
    assert flow["entry"] == "parse", flow
    assert list(flow["nodes"]) == ["parse", "recognize", "extract_fields", "review_json"], flow
    assert flow["nodes"]["parse"]["next"] == "recognize", flow
    assert flow["nodes"]["recognize"]["next"] == "extract_fields", flow
    assert flow["nodes"]["extract_fields"]["next"] == "review_json", flow
    assert flow["nodes"]["review_json"]["next"] == "END", flow
    assert plan({"pages": [], "logs": []})["halt"] is True
    assert plan({"pages": [{"file": "a.pdf", "page": 1}], "logs": []})["halt"] is False

    from ai.tools.operators import name_overlap

    overlapped = name_overlap(
        {"项目名称": "米北集气站", "区域名称": "米北集气站调整", "图纸名称": "流程图"},
        ["项目名称", "区域名称", "图纸名称"],
    )
    assert overlapped and overlapped[0][0] == "项目名称", overlapped
    clear = name_overlap(
        {"项目名称": "长庆油田地面工程", "区域名称": "米北-1集气站调整设计", "图纸名称": "工艺自控流程图"},
        ["项目名称", "区域名称", "图纸名称"],
    )
    assert clear == [], clear

    nodes = list(build_graph().get_graph().nodes)
    assert "parse" in nodes and "recognize" in nodes and "extract_fields" in nodes and "review_json" in nodes, nodes
    assert "plan" not in nodes and "detect" not in nodes and "check" not in nodes, nodes
    print("ok  pid.review 为解析、识别、提取、对比")


if __name__ == "__main__":
    main()

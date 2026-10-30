"""说明栏错别字审查的离线回归，不访问大模型、不跑 YOLO。

覆盖：图号/专业解析、抄写结果清洗与切条合并、llm_judge 算子的阈值/白名单/行号校验、
form_review 的 Issue 文案与字段、validate 结构校验。
用法：python scripts/test_notes_typo.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.agents import form_review, validate
from ai.agents.skill_loader import load_resource, load_skill
from ai.tools import extract_notes, operators as ops


def _notes_artifact() -> dict:
    return {
        "file_types": {"pid": ["DD26044-GP-PID-001__0_工艺自控流程图.png"]},
        "notes": {
            "files": [
                {
                    "file": "DD26044-GP-PID-001__0_工艺自控流程图.png",
                    "drawing_no": "DD26044-GP-PID-001",
                    "discipline": "GP",
                    "pages_total": 1,
                    "items": [
                        {
                            "page": 1,
                            "bbox": [5732.0, 102.0, 7342.0, 1934.0],
                            "source": "label_json",
                            "lines": [
                                {"line": 1, "no": "", "kind": "标题", "text": "说明"},
                                {"line": 2, "no": "1", "kind": "条文", "text": "集气工艺流程：南-48集气站来气→清管器接收筒→阀室"},
                                {"line": 3, "no": "4", "kind": "条文", "text": "图中未注明压力等级者均为CL600."},
                                {"line": 4, "no": "6", "kind": "条文", "text": "本次扩建内容：新建清管器发送筒一座，拆除己建放空管线。"},
                                {"line": 5, "no": "", "kind": "图例", "text": "阀套式排污阀"},
                                {"line": 6, "no": "", "kind": "表格", "text": "T 温度 — "},
                            ],
                        }
                    ],
                    "errors": [],
                }
            ],
            "logs": [],
        },
    }


def _fake_judge(**kwargs):
    """模拟模型：返回 1 个真错字、1 个白名单词、1 个低置信、1 个行号错位、1 个表格行。"""
    assert "清管器" in kwargs["whitelist"], "白名单应按 GP 专业注入"
    assert "[图例]" not in kwargs["lines"], "kinds 过滤后图例行不应送判"
    assert "[表格]" not in kwargs["lines"], "kinds 过滤后文字代号（表格）行不应送判"
    return {
        "items": [
            {"line": 3, "wrong": "己建", "correct": "已建", "reason": "己/已形近误用", "confidence": 0.92},
            {"line": 1, "wrong": "清管器", "correct": "清管机", "reason": "疑似", "confidence": 0.9},
            {"line": 2, "wrong": "注明", "correct": "标明", "reason": "用词", "confidence": 0.4},
            {"line": 2, "wrong": "己建", "correct": "已建", "reason": "行号对错", "confidence": 0.95},
        ]
    }


def test_parse_names() -> None:
    assert extract_notes.drawing_no_of("第六采气厂 DD26044-GP-PID-001__0_苏南-15集气站.png") == "DD26044-GP-PID-001"
    assert extract_notes.drawing_no_of("米-9集气站 CEDC016S-2024-001-GP-DWG-001__0_工艺自控流程图.png") == "CEDC016S-2024-001-GP-DWG-001"
    assert extract_notes.drawing_no_of("庆3增压装置DD26002-0601-OP-PID__0_工艺自控流程图.png") == "DD26002-0601-OP-PID"
    assert extract_notes.drawing_no_of("榆沟清管站扩建 集-40499／2__0_工艺自控流程图.png") == "集-40499/2"
    assert extract_notes.drawing_no_of("签章_CEDC022S-2022_水-18448_1_采出水处理系统工艺自控流程图.png") in {"水-18448", "CEDC022S-2022"}
    assert extract_notes.discipline_of("x DD26044-GP-PID-001.png") == "GP"
    assert extract_notes.discipline_of("x DD26002-0601-OP-PID.png") == "OP"
    assert extract_notes.discipline_of("x DD26001-0110-WP-PID-001.png") == "WP"
    assert extract_notes.discipline_of("榆沟清管站扩建 集-40499／2__0_工艺自控流程图.png") == "GP"
    assert extract_notes.discipline_of("洲-19煤岩气采出水处理站 水-18852／1__0_工艺自控流程图.png") == "WP"
    assert extract_notes.discipline_of("随便.png") == "UNK"
    print("ok  图号/专业解析")


def test_clean_and_merge() -> None:
    raw = [
        {"no": "1", "kind": "条文", "text": " 集气工艺流程： 南-48 来气 "},
        {"no": "", "kind": "乱填", "text": "内部文件请勿外传"},
        {"no": "", "kind": "乱填", "text": "阀套式排污阀"},
        "纯字符串行",
        {"text": "   "},
    ]
    lines = extract_notes._clean_lines(raw)
    assert [l["text"] for l in lines] == ["集气工艺流程： 南-48 来气", "阀套式排污阀", "纯字符串行"]
    assert lines[1]["kind"] == "条文", "未知 kind 收敛为条文"

    a = [{"no": "1", "kind": "条文", "text": "A"}, {"no": "2", "kind": "条文", "text": "B"}, {"no": "3", "kind": "条文", "text": "C"}]
    b = [{"no": "3", "kind": "条文", "text": "C"}, {"no": "4", "kind": "条文", "text": "D"}]
    merged = extract_notes._merge([a, b])
    assert [l["text"] for l in merged] == ["A", "B", "C", "D"], merged
    assert [l["line"] for l in merged] == [1, 2, 3, 4]
    print("ok  抄写清洗与切条合并")


def test_operator() -> None:
    files = _notes_artifact()["notes"]["files"]
    glossary = load_resource("_notes_glossary.yaml")
    assert isinstance(glossary, dict) and "GP" in glossary
    kinds = load_skill("form.notes_typo")["checks"][0]["kinds"]
    assert kinds == ["条文", "框图节点"], "图例与文字代号（表格）暂不参与错别字判定"
    diffs = ops.llm_judge(
        files=files,
        prompt_id="judge.notes_typo",
        glossary=glossary,
        min_confidence=0.7,
        kinds=kinds,
        judge_fn=_fake_judge,
    )
    assert len(diffs) == 1, diffs
    diff = diffs[0]
    assert diff["type"] == "typo" and diff["wrong"] == "己建" and diff["correct"] == "已建"
    assert diff["no"] == "6" and diff["drawing_no"] == "DD26044-GP-PID-001" and diff["bbox"]
    # 模型不可达 → tool_error，不抛异常
    errs = ops.llm_judge(files=files, prompt_id="x", judge_fn=lambda **k: {"_error": "大模型不可达：timeout"})
    assert errs and errs[0]["type"] == "tool_error"
    print("ok  llm_judge 算子：阈值、白名单、行号校验、错误口径")


def test_review_and_validate() -> None:
    skill = load_skill("form.notes_typo")
    assert skill and skill.get("enabled"), "Skill 应已启用"
    glossary_name = skill["checks"][0]["glossary"]
    assert load_resource(glossary_name) is not None, f"白名单 {glossary_name} 应可读"

    original = ops._judge_default
    ops._judge_default = lambda **k: _fake_judge(**k)
    try:
        state = {"artifacts": _notes_artifact(), "skill_ids": ["form.notes_typo"], "logs": []}
        out = form_review.review(state)
    finally:
        ops._judge_default = original
    issues = out["issues"]
    assert len(issues) == 1, issues
    issue = issues[0]
    assert issue["skill_id"] == "form.notes_typo" and issue["type"] == "notes_typo"
    assert "己建" in issue["desc"] and "已建" in issue["desc"] and issue["desc"].startswith("DD26044-GP-PID-001 说明第6条")
    assert issue["severity"] == "low" and issue["review_status"] == "pending"
    assert issue["confidence"] == 0.92 and issue["x"] and issue["y"]
    checked = validate.validate({"issues": issues})["validation"]
    assert checked["ok"], checked

    # 工件为 stub → 跳过该 Skill，不产生 Issue
    stub = {"artifacts": {"file_types": {"pid": ["a.png"]}, "notes": {"_stub": True}}, "skill_ids": ["form.notes_typo"], "logs": []}
    assert form_review.review(stub)["issues"] == []
    # 抽取失败要显式报出来
    broken = _notes_artifact()
    broken["notes"]["files"][0]["errors"] = ["第 1 页：未找到说明栏"]
    broken["notes"]["files"][0]["items"] = []
    out = form_review.review({"artifacts": broken, "skill_ids": ["form.notes_typo"], "logs": []})
    assert any(i["type"] == "notes_typo_tool_error" for i in out["issues"]), out["issues"]
    print("ok  form_review 文案/字段 + validate")


def main() -> None:
    test_parse_names()
    test_clean_and_merge()
    test_operator()
    test_review_and_validate()
    print("all passed")


if __name__ == "__main__":
    main()

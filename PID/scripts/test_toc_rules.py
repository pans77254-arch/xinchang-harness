"""目录比对算子的离线回归，不访问大模型。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.agents.form_review import review


def main() -> None:
    artifacts = {
        "toc": {
            "public": {
                "project_no": "CEDC151C-2025",
                "project_name": "单井配套站场（二）工艺部分",
                "discipline": "油气集输",
                "stage": "初步设计",
                "date": "2025.07.07",
            },
            "entries": [
                {"file_no": "BD25151-0102-OP-DES", "name": "说明书", "revision": "0", "sheet_count": "12"},
                {"file_no": "BD25151-0102-OP-MTO", "name": "材料表", "revision": "0", "sheet_count": "6"},
                {"file_no": "BD25151-0102-OP-PID-002", "name": "工艺自控流程图", "revision": "0", "sheet_count": "1"},
            ],
        },
        "title_block": {
            "items": [
                {
                    "file": "说明书.doc",
                    "file_no": "BD25151-012-OP-DES",
                    "name": "说    明    书",
                    "project_no": "CEDC151S-2025",
                    "project_name": "单井配套站场（二）工艺部分",
                    "discipline": "油气集输",
                    "stage": "初步设计",
                    "date": "2025.7.7",
                    "revision": "1版",
                    "sheet_count": "12",
                    "page_count": 12,
                },
                {
                    "file": "材料表.doc",
                    "file_no": "BD25151-012-OP-MTO",
                    "name": "材料表",
                    "project_no": "CEDC151C-2025",
                    "project_name": "骨架工程站场（一）工艺部分",
                    "discipline": "油气集输",
                    "stage": "施工图",
                    "date": "2025.07.07",
                    "revision": "A版",
                    "sheet_count": "6",
                    "page_count": 6,
                },
            ]
        },
        "file_list": {"unidentified": ["平面图-模型.pdf"]},
    }
    result = review({"artifacts": artifacts, "skill_ids": ["form.toc_index"], "logs": []})
    types = sorted(issue["type"] for issue in result["issues"])
    expected = sorted(
        [
            "unidentified_file",
            "missing_file",
            "file_no_mismatch",
            "file_no_mismatch",
            "public_mismatch",
            "public_mismatch",
            "public_mismatch",
            "revision_mismatch",
            "revision_mismatch",
        ]
    )
    print("\n".join(f"{issue['type']}: {issue['desc']}" for issue in result["issues"]))
    if types != expected:
        raise SystemExit(f"期望 {expected}，实际 {types}")
    paired = review(
        {
            "artifacts": {
                "toc": {
                    "public": {"project_no": "CEDC151C-2025", "project_name": "长庆油田页岩油地面工程单井配套站场（二）工艺部分", "discipline": "油气集输", "stage": "初步设计", "date": "2025.07.07"},
                    "entries": [{"file_no": "BD25151-0102-OP-PLA-001", "name": "岭十二转改造平面布置图", "revision": "0", "sheet_count": "1"}],
                },
                "title_block": {
                    "items": [
                        {
                            "file": "平面图.pdf",
                            "file_no": "BD25151-0102-0P-PLA-001",
                            "name": "岭十二转改造平面布置图",
                            "project_no": "CEDC151C-2025",
                            "project_name": "长庆油田页岩油地面工程单井配套站场（二）",
                            "discipline": "油气集输",
                            "stage": "初步设计",
                            "date": "2025.7.7",
                            "revision": "0版",
                            "sheet_count": "1",
                            "page_count": 1,
                        }
                    ]
                },
                "file_list": {"unidentified": []},
            },
            "skill_ids": ["form.toc_index"],
            "logs": [],
        }
    )
    if paired["issues"]:
        raise SystemExit("0P/OP 与项目名称缺省后缀不应报错：" + str(paired["issues"]))
    misread = review(
        {
            "artifacts": {
                "toc": {
                    "public": {"project_no": "CEDC151C-2025", "project_name": "甲", "discipline": "油气集输", "stage": "初步设计", "date": "2025.07.07"},
                    "entries": [
                        {"file_no": "BD25151-0102-OP-PLA-001", "name": "岭十二转改造平面布置图", "revision": "0", "sheet_count": "1"},
                        {"file_no": "BD25151-0102-OP-PLA-002", "name": "西十转扩建造平面布置图", "revision": "0", "sheet_count": "1"},
                        {"file_no": "BD25151-0102-OP-PID-002", "name": "西十转扩建造工艺自控流程图", "revision": "0", "sheet_count": "1"},
                    ],
                },
                "title_block": {
                    "items": [
                        {
                            "file": "平面图-模型.pdf",
                            "file_no": "B025151-0102-0P-PLA-001",
                            "name": "平面布置图",
                            "project_no": "CEDC151C-2025",
                            "project_name": "甲",
                            "discipline": "油气集输",
                            "stage": "初步设计",
                            "date": "2025.07.07",
                            "revision": "0",
                            "sheet_count": "1",
                            "page_count": 1,
                        }
                    ]
                },
                "file_list": {"unidentified": []},
            },
            "skill_ids": ["form.toc_index"],
            "logs": [],
        }
    )
    absent = [issue["drawing_no"] for issue in misread["issues"] if issue["type"] in {"missing_file", "extra_file"}]
    expect_absent = ["BD25151-0102-OP-PLA-002", "BD25151-0102-OP-PID-002"]
    if absent != expect_absent:
        raise SystemExit(f"目录缺文件应为 {expect_absent}，实际 {absent}")
    folded = review(
        {
            "artifacts": {
                "toc": {
                    "public": {"project_no": "CEDC151C-2025", "project_name": "甲", "discipline": "油气集输", "stage": "初步设计", "date": "2025.07.07"},
                    "entries": [
                        {"file_no": "BD25151-0102-OP-DES", "name": "说明书", "revision": "0", "sheet_count": "12", "equivalent": "1.50"},
                        {"file_no": "BD25151-0102-OP-PLA-001", "name": "平面布置图", "revision": "0", "sheet_count": "1", "equivalent": "0.375"},
                        {"file_no": "BD25151-0102-OP-PLA-002", "name": "西十转扩建造平面布置图", "revision": "0", "sheet_count": "1", "equivalent": "1.50"},
                    ],
                },
                "title_block": {
                    "items": [
                        {
                            "file": "说明书.doc",
                            "file_no": "BD25151-0102-OP-DES",
                            "name": "说明书",
                            "project_no": "CEDC151C-2025",
                            "project_name": "甲",
                            "discipline": "油气集输",
                            "stage": "初步设计",
                            "date": "2025.07.07",
                            "revision": "0",
                            "sheet_count": "12",
                            "page_count": 0,
                            "paper_size": "A4",
                            "paper_width_mm": 210.0,
                            "paper_height_mm": 297.0,
                        },
                        {
                            "file": "平面图.pdf",
                            "file_no": "BD25151-0102-OP-PLA-001",
                            "name": "平面布置图",
                            "project_no": "CEDC151C-2025",
                            "project_name": "甲",
                            "discipline": "油气集输",
                            "stage": "初步设计",
                            "date": "2025.07.07",
                            "revision": "0",
                            "sheet_count": "1",
                            "page_count": 1,
                            "paper_size": "A1",
                            "paper_width_mm": 841.0,
                            "paper_height_mm": 594.0,
                        },
                    ]
                },
                "file_list": {"unidentified": []},
            },
            "skill_ids": ["form.toc_index"],
            "logs": [],
        }
    )
    equivalent = [issue for issue in folded["issues"] if issue["type"] == "equivalent_mismatch"]
    if len(equivalent) != 1 or "应为 1" not in equivalent[0]["desc"] or "PLA-001" not in equivalent[0]["drawing_no"]:
        raise SystemExit("A1 折合应只报平面图 0.375 对 1：" + str(folded["issues"]))
    if any(issue["type"] == "equivalent_mismatch" and "PLA-002" in issue["drawing_no"] for issue in folded["issues"]):
        raise SystemExit("缺文件不应再报折合")

    from ai.compile.compiler import guard_revision
    from ai.agents.skill_loader import load_skill
    from ai.tools.operators import catalog_align
    import copy

    skill = load_skill("form.toc_index")
    if not skill:
        raise SystemExit("缺少 form.toc_index")
    draft = copy.deepcopy(skill)
    for check in draft.get("checks") or []:
        if check.get("op") == "catalog_align":
            check["identity_field"] = ""
            if "project_no" not in (check.get("public_fields") or []):
                check.setdefault("public_fields", []).append("project_no")
    reason = guard_revision(skill, draft)
    if reason:
        raise SystemExit("关掉文件号核对应被允许：" + reason)
    bad = copy.deepcopy(skill)
    for check in bad.get("checks") or []:
        if check.get("op") == "catalog_align":
            check["pair_by"] = ["project_no"]
    if not guard_revision(skill, bad):
        raise SystemExit("用项目号配对应被拒绝")

    silent = catalog_align(
        rows=[{"file_no": "A-1", "name": "说明书", "revision": "0", "sheet_count": "1"}],
        items=[
            {
                "file": "说明书.doc",
                "file_no": "A-2",
                "name": "说明书",
                "project_no": "P1",
                "revision": "0",
                "sheet_count": "1",
            }
        ],
        public={"project_no": "P1"},
        public_fields=["project_no"],
        public_labels={"project_no": "项目号"},
        row_fields=[],
        pair_by=["file_no", "name"],
        identity_field="",
    )
    if any(issue["type"] == "file_no_mismatch" for issue in silent):
        raise SystemExit("identity_field 为空时不应再报文件号不一致：" + str(silent))
    print("ok", len(types))


if __name__ == "__main__":
    main()

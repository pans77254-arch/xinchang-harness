"""冒烟：加载图、列出 Skill。没有目录文件时应给出 missing_catalog，且不访问模型。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ai.agents.skill_loader import list_skills
from ai.graph.controller import invoke


def main() -> None:
    skills = [s["id"] for s in list_skills()]
    print("skills:", skills)
    result = invoke(
        {
            "task_id": "smoke",
            "files": [{"id": "demo", "name": "demo.pdf", "path": ""}],
            "skill_ids": ["form.toc_index"],
        }
    )
    print(json.dumps({k: result.get(k) for k in ("logs", "issues", "validation")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

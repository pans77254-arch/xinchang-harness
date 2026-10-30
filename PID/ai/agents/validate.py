"""结果校验。只做结构校验，不改审查结论。"""

from __future__ import annotations

from typing import Any

from ai.issue import ISSUE_KEYS


def validate(state: dict[str, Any]) -> dict[str, Any]:
    issues = state.get("issues") or []
    errors: list[str] = []
    for i, issue in enumerate(issues):
        missing = [k for k in ("issue_id", "skill_id", "type", "severity", "desc") if not issue.get(k)]
        extra = [k for k in issue if k not in ISSUE_KEYS]
        if missing:
            errors.append(f"issues[{i}] 缺字段 {missing}")
        if extra:
            errors.append(f"issues[{i}] 含未登记字段 {extra}")
    return {
        "validation": {
            "ok": not errors,
            "errors": errors,
            "issue_count": len(issues),
        }
    }

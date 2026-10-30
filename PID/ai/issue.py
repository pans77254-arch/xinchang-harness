"""统一 Issue schema。扩展字段必须走平台评审，禁止审查点私自定义键。"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

ISSUE_KEYS = (
    "issue_id",
    "drawing_no",
    "skill_id",
    "type",
    "severity",
    "desc",
    "basis",
    "suggestion",
    "x",
    "y",
    "confidence",
    "review_status",
)


def make_issue(
    *,
    skill_id: str,
    issue_type: str,
    severity: str,
    desc: str,
    basis: str = "",
    suggestion: str = "",
    drawing_no: str = "",
    x: float | None = None,
    y: float | None = None,
    confidence: float = 0.92,
    review_status: str = "pending",
) -> dict[str, Any]:
    return {
        "issue_id": str(uuid4())[:8],
        "drawing_no": drawing_no,
        "skill_id": skill_id,
        "type": issue_type,
        "severity": severity,
        "desc": desc,
        "basis": basis,
        "suggestion": suggestion,
        "x": x,
        "y": y,
        "confidence": confidence,
        "review_status": review_status,
    }

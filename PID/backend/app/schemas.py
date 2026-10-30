from __future__ import annotations

from pydantic import BaseModel, Field


class ReviewRequest(BaseModel):
    task_id: str
    skill_ids: list[str] = Field(default_factory=list)


class FolderReviewRequest(BaseModel):
    folder: str
    skill_ids: list[str] = Field(default_factory=list)


class IssueReviewRequest(BaseModel):
    review_status: str


class PreprocessRequest(BaseModel):
    """图像预处理预览。file_path 可以是 PDF、图片，或包含 PID 图纸的文件夹。"""

    file_path: str
    page: int = 1
    binarize: bool = True
    threshold_method: str = "otsu"
    threshold_value: int = 127
    deskew: bool = True
    skew_mode: str = "auto"
    skew_max: float = 15.0
    skew_min: float = 0.5
    skew_fixed: float = 0.0


class IssueOut(BaseModel):
    issue_id: str
    drawing_no: str = ""
    skill_id: str
    type: str
    severity: str
    desc: str
    basis: str = ""
    suggestion: str = ""
    x: float | None = None
    y: float | None = None
    confidence: float = 0.0
    review_status: str = "pending"

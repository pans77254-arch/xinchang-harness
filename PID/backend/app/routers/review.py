from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ai.config import PDF_DPI, PREVIEW_DIR, WORK_ROOT
from ai.tools.file_classifier import classify_folder
from ai.tools.image_preprocess import preprocess_image
from ai.tools.pdf2png import render_pdf
from pydantic import BaseModel, Field

from backend.app.schemas import (
    FolderReviewRequest,
    IssueReviewRequest,
    PreprocessRequest,
    ReviewRequest,
)
from backend.app.services import review as review_svc

router = APIRouter()

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


@router.post("/classify")
def classify(body: FolderReviewRequest):
    if not Path(body.folder).is_dir():
        raise HTTPException(404, "找不到这个文件夹")
    return classify_folder(body.folder)


class CheckpointRequest(BaseModel):
    text: str = Field(min_length=1)


class ManualCheckpointRequest(BaseModel):
    name: str = Field(min_length=1)
    when: str = Field(min_length=1)
    criterion: str = Field(min_length=1)


@router.post("/checkpoints")
def add_checkpoint(body: CheckpointRequest):
    from ai.agents.pid_plan import create_checkpoint

    return create_checkpoint(body.text)


@router.post("/checkpoints/manual")
def add_checkpoint_manual(body: ManualCheckpointRequest):
    """人工补充名称、检查对象和判定规则后，才生成审查点。"""
    from ai.agents.pid_plan import save_checkpoint

    result = save_checkpoint(body.name, body.when, body.criterion)
    if not result.get("ok"):
        raise HTTPException(400, result.get("unsupported") or "无法保存这个审查点")
    return result


@router.post("/review/folder")
def review_folder(body: FolderReviewRequest):
    if not Path(body.folder).is_dir():
        raise HTTPException(404, "找不到这个文件夹")
    return review_svc.run_folder(body.folder, body.skill_ids)


@router.get("/tasks/{task_id}/result")
def task_result(task_id: str):
    try:
        return review_svc.get_presented(task_id)
    except FileNotFoundError:
        raise HTTPException(404, "result not found")


@router.patch("/tasks/{task_id}/issues/{issue_id}")
def review_issue(task_id: str, issue_id: str, body: IssueReviewRequest):
    try:
        return review_svc.review_issue(task_id, issue_id, body.review_status)
    except FileNotFoundError:
        raise HTTPException(404, "result not found")
    except KeyError:
        raise HTTPException(404, "issue not found")
    except ValueError:
        raise HTTPException(400, "review_status 只能是 pending、confirmed、rejected")


@router.post("/review")
def start_review(body: ReviewRequest):
    try:
        return review_svc.run_review(body.task_id, body.skill_ids)
    except FileNotFoundError:
        raise HTTPException(404, "task not found")


def _resolve_source(raw: str) -> Path:
    """预览的输入：文件直接用；文件夹则取其中的 PID 图纸。"""
    path = Path(raw).expanduser()
    if path.is_dir():
        pids = (classify_folder(str(path)).get("file_types") or {}).get("pid") or []
        if not pids:
            raise HTTPException(404, "这个文件夹里没有识别到工艺自控流程图（PID）")
        path = path / str(pids[0])
    if not path.is_file():
        raise HTTPException(404, f"找不到文件：{path}")
    return path


@router.post("/preprocess")
def preprocess(body: PreprocessRequest):
    """倾斜校正 + 二值化预览。只返回原图与结果图的地址，不落库。"""
    source = _resolve_source(body.file_path)
    token = uuid.uuid4().hex[:8]
    if source.suffix.lower() == ".pdf":
        rendered = render_pdf(source, WORK_ROOT / "preprocess_src" / token, dpi=PDF_DPI, all_pages=True)
        images = rendered.get("images") or []
        page = max(1, int(body.page or 1))
        if page > len(images):
            raise HTTPException(400, f"页码 {page} 超出范围，这份 PDF 共 {len(images)} 页")
        source_image = Path(images[page - 1])
    elif source.suffix.lower() in IMAGE_EXT:
        source_image = source
    else:
        raise HTTPException(400, "只支持 PDF 或图片文件")

    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    src_copy = PREVIEW_DIR / f"{token}-src{source_image.suffix.lower() or '.png'}"
    shutil.copyfile(source_image, src_copy)
    result = preprocess_image(
        src_copy,
        PREVIEW_DIR,
        binarize=body.binarize,
        threshold_method=body.threshold_method,
        threshold_value=body.threshold_value,
        deskew=body.deskew,
        skew_mode=body.skew_mode,
        skew_max=body.skew_max,
        skew_min=body.skew_min,
        skew_fixed=body.skew_fixed,
    )
    if not result.get("ok"):
        raise HTTPException(400, result.get("error") or "预处理失败")
    return {
        "src_url": f"/static/previews/{src_copy.name}",
        "out_url": f"/static/previews/{Path(result['out_path']).name}",
        "skew_angle": result.get("skew_angle") or 0.0,
        "corrected": bool(result.get("corrected")),
        "threshold_method": result.get("threshold_method") or "",
        "logs": result.get("logs") or [],
    }

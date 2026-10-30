"""PID 图纸识别：把工艺图转成页图，再用版面 YOLO 标出图框、表格、说明。

只做识别，不抄写、不判错别字。检测来源沿用 NOTES_DETECT_SOURCE：remote 或 yolo。
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from ai.config import (
    NOTES_DETECT_SOURCE,
    PDF_DPI,
    WORK_ROOT,
    YOLO_CONF_NOTES,
    YOLO_IMGSZ_LAYOUT,
    YOLO_WEIGHTS_LAYOUT,
)
from ai.tools.pdf2png import render_pdf

IMAGE_EXT = {".png", ".jpg", ".jpeg"}


def render_pages(folder: str, names: list[str], work_dir: Path) -> list[dict[str, Any]]:
    """PNG 直接作为一页；PDF 逐页转 PNG。"""
    pages: list[dict[str, Any]] = []
    root = Path(folder)
    out = work_dir / "pages"
    for name in names:
        path = root / name
        suffix = path.suffix.lower()
        if suffix in IMAGE_EXT and path.is_file():
            pages.append({"file": name, "page": 1, "image": str(path), "error": ""})
            continue
        if suffix == ".pdf" and path.is_file():
            rendered = render_pdf(path, out, dpi=PDF_DPI, all_pages=True)
            if not rendered.get("ok"):
                pages.append({"file": name, "page": 0, "image": "", "info": "", "error": "PDF 转页图失败"})
                continue
            from ai.tools.pdf2png import save_pdf_info

            info = save_pdf_info(path, rendered)
            for record in rendered.get("pages") or []:
                pages.append(
                    {
                        "file": name,
                        "page": record.get("page") or 0,
                        "image": record.get("metadata_png") or "",
                        "info": str(info),
                        "error": "",
                    }
                )
            continue
        pages.append({"file": name, "page": 0, "image": "", "error": "只识别 PNG 和 PDF"})
    return pages


def _detect_local(image: str) -> list[dict[str, Any]]:
    from ai.agents.drawing_detect import _model

    model = _model(YOLO_WEIGHTS_LAYOUT)
    names = {int(k): str(v) for k, v in model.names.items()}
    result = model.predict(source=image, imgsz=YOLO_IMGSZ_LAYOUT, conf=YOLO_CONF_NOTES, verbose=False)[0]
    boxes: list[dict[str, Any]] = []
    if result.boxes is None:
        return boxes
    for box in result.boxes:
        cls_id = int(box.cls[0])
        boxes.append(
            {
                "bbox": [round(float(v), 1) for v in box.xyxy[0].tolist()],
                "confidence": round(float(box.conf[0]), 4),
                "class_name": names.get(cls_id, ""),
            }
        )
    boxes.sort(key=lambda item: -float(item["confidence"]))
    return boxes


def detect_image(image: str, *, source: str | None = None) -> list[dict[str, Any]]:
    """对一页图做版面检测。返回框列表，不裁图。"""
    mode = (source or NOTES_DETECT_SOURCE or "remote").strip().lower()
    if mode == "remote":
        from ai.tools.remote_yolo import predict_remote

        return predict_remote(image, imgsz=YOLO_IMGSZ_LAYOUT, conf=YOLO_CONF_NOTES)
    if mode == "yolo":
        return _detect_local(image)
    raise RuntimeError(f"不支持的 PID 检测来源：{mode}")


def detect_pages(pages: list[dict[str, Any]], *, source: str | None = None) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    for page in pages:
        item = {
            "file": page.get("file") or "",
            "page": page.get("page") or 0,
            "image": page.get("image") or "",
            "info": page.get("info") or "",
            "boxes": [],
            "error": page.get("error") or "",
        }
        if item["error"] or not item["image"]:
            found.append(item)
            continue
        try:
            item["boxes"] = detect_image(item["image"], source=source)
        except Exception as exc:
            item["error"] = str(exc)
        found.append(item)
    return found


def work_dir_for(folder: str) -> Path:
    digest = hashlib.sha256(str(Path(folder).resolve()).encode("utf-8")).hexdigest()[:12]
    return WORK_ROOT / "pid" / digest

"""图纸 PDF 转 PNG。

合并后的 PDF 页树是多层的，页数以文档根上的总页数为准。
页面带 /Rotate 时，分辨率和 PNG 都按旋转后的显示方向计算。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ai.config import PDF_DPI
from ai.tools.paper import measure_mm
from ai.tools.registry import register


def _page_record(index: int) -> dict[str, Any]:
    """一页保留原图。说明、图表、图框各自带是否检出、路径和 info。"""
    return {
        "page": index + 1,
        "metadata_png": "",
        "notes": {"has_notes": False, "notes_path": [], "info": []},
        "chart": {"has_chart": False, "chart_path": [], "info": []},
        "frame": {"has_frame": False, "frame_path": [], "info": []},
    }


def render_pdf(path: str | Path, out_dir: str | Path, dpi: int = PDF_DPI, *, all_pages: bool = False) -> dict[str, Any]:
    """读出全部页的页数和分辨率，并把需要的页渲成 PNG。

    默认只渲首页（标题栏审查用），all_pages 时逐页全渲。页数始终是整份文档的页数。
    """
    import pypdfium2 as pdfium

    src = Path(path)
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    doc = pdfium.PdfDocument(str(src))
    try:
        page_count = len(doc)
        images: list[str] = []
        pages: list[dict[str, Any]] = []
        paper: dict[str, object] = {}
        for index in range(page_count):
            page = doc[index]
            record = _page_record(index)
            if index == 0:
                width_pt, height_pt = page.get_size()
                paper = measure_mm(width_pt * 25.4 / 72, height_pt * 25.4 / 72)
            if index > 0 and not all_pages:
                pages.append(record)
                continue
            out = dest / f"{src.stem}-p{index + 1}.png"
            image = page.render(scale=dpi / 72).to_pil()
            image.save(out)
            record["metadata_png"] = str(out)
            pages.append(record)
            images.append(str(out))
        return {
            "ok": True,
            "page_count": page_count,
            "images": images,
            "paper": paper,
            "dpi": dpi,
            "pages": pages,
        }
    finally:
        doc.close()


def save_pdf_info(path: str | Path, rendered: dict[str, Any], info_path: str | Path | None = None) -> Path:
    """把页数和每页分辨率写到 JSON。默认放在 PDF 旁边。"""
    src = Path(path)
    dest = Path(info_path) if info_path else src.with_name(f"{src.stem}.info.json")
    payload = {
        "file": src.name,
        "path": str(src),
        "page_count": rendered.get("page_count"),
        "pages": rendered.get("pages") or [],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return dest


NOTE_LABELS = {"说明", "说明栏"}
CHART_LABELS = {"表格", "图表"}
FRAME_LABELS = {"图框", "标题栏"}
FRAME_FIELDS = [
    ("design_cert_no", "设计证书号"),
    ("survey_cert_no", "勘察证书号"),
    ("drawn_by", "制图"),
    ("designed_by", "设计"),
    ("checked_by", "校对"),
    ("reviewed_by", "审核"),
    ("project_lead", "项目负责人"),
    ("approved_by", "审定"),
    ("project_name", "项目名称"),
    ("area_name", "区域名称"),
    ("unit_name", "单元名称"),
    ("discipline_unit_name", "专业单体名称"),
    ("name", "图纸名称"),
    ("stage", "阶段"),
    ("project_no", "项目号"),
    ("scale", "比例"),
    ("file_no", "文件号"),
    ("date", "日期"),
    ("discipline", "专业"),
    ("revision", "版次"),
    ("sheet_count", "张数"),
]


def _notes_info(crop_path: str, work_dir: Path) -> dict[str, Any]:
    from ai.tools.extract_notes import _transcribe

    lines, errors = _transcribe({"crop_path": crop_path}, work_dir, [])
    item: dict[str, Any] = {"path": crop_path, "info": {"lines": lines}}
    if errors:
        item["error"] = "；".join(errors)
    return item


def _chart_info(crop_path: str) -> dict[str, Any]:
    from ai.agents.extract_info import extract_json

    data = extract_json(
        prompt_id="extract.chart",
        fields=[{"name": "rows", "desc": "表格逐行文字。每一行是单元格字符串数组，按从左到右、从上到下。"}],
        image_path=crop_path,
        max_tokens=4096,
    )
    rows = data.get("rows") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        rows = []
    item: dict[str, Any] = {"path": crop_path, "info": {"rows": rows}}
    if isinstance(data, dict) and data.get("_error"):
        item["error"] = data["_error"]
    return item


def _frame_info(crop_path: str) -> dict[str, Any]:
    from ai.agents.extract_info import extract_json

    data = extract_json(
        prompt_id="form.toc_index.drawing",
        fields=[{"name": key, "desc": label} for key, label in FRAME_FIELDS],
        image_path=crop_path,
        max_side=3000,
        max_tokens=2048,
    )
    item: dict[str, Any] = {"path": crop_path}
    for key, label in FRAME_FIELDS:
        value = "" if not isinstance(data, dict) else data.get(key)
        item[label] = "" if value is None else str(value).strip()
    if isinstance(data, dict) and data.get("_error"):
        item["error"] = data["_error"]
    return item


def update_layout_info(
    detections: list[dict[str, Any]],
    crop_root: str | Path,
    *,
    extract: bool = True,
) -> list[str]:
    """YOLO 完成后，写回说明、图表、图框的路径，并在 info 里写入三类详细内容。"""
    from ai.agents.drawing_detect import crop_boxes

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in detections:
        info = str(item.get("info") or "")
        if info:
            grouped.setdefault(info, []).append(item)
    updated: list[str] = []
    root = Path(crop_root)
    for info, items in grouped.items():
        path = Path(info)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        pages = data.get("pages") or []
        by_page = {int(page.get("page") or 0): page for page in pages if isinstance(page, dict)}
        for item in items:
            record = by_page.get(int(item.get("page") or 0))
            image = str(item.get("image") or "")
            if record is None or not image:
                continue
            boxes = item.get("boxes") or []
            note_boxes = [box for box in boxes if str(box.get("class_name") or "") in NOTE_LABELS]
            chart_boxes = [box for box in boxes if str(box.get("class_name") or "") in CHART_LABELS]
            frame_boxes = [box for box in boxes if str(box.get("class_name") or "") in FRAME_LABELS]
            note_crops = crop_boxes(image, root / "notes", note_boxes, class_name="说明") if note_boxes else []
            chart_crops = crop_boxes(image, root / "charts", chart_boxes, class_name="表格") if chart_boxes else []
            frame_crops = crop_boxes(image, root / "frames", frame_boxes, class_name="图框") if frame_boxes else []
            record["metadata_png"] = record.get("metadata_png") or image
            record.pop("has_notes", None)
            record.pop("notes_path", None)
            record.pop("has_chart", None)
            record.pop("chart_path", None)
            record.pop("has_frame", None)
            record.pop("frame_path", None)
            record.pop("info", None)
            record["notes"] = {
                "has_notes": bool(note_crops),
                "notes_path": [crop["crop_path"] for crop in note_crops],
                "info": [_notes_info(crop["crop_path"], root / "notes_work") for crop in note_crops] if extract else [],
            }
            record["chart"] = {
                "has_chart": bool(chart_crops),
                "chart_path": [crop["crop_path"] for crop in chart_crops],
                "info": [_chart_info(crop["crop_path"]) for crop in chart_crops] if extract else [],
            }
            record["frame"] = {
                "has_frame": bool(frame_crops),
                "frame_path": [crop["crop_path"] for crop in frame_crops],
                "info": [_frame_info(crop["crop_path"]) for crop in frame_crops] if extract else [],
            }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        updated.append(str(path))
    return updated


@register("drawing.to_png", produces=["png"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    dpi = int(artifacts.get("pdf_dpi") or PDF_DPI)
    out_dir = Path(artifacts.get("work_dir") or (Path(__file__).resolve().parents[2] / "data" / "work" / "png"))
    items = []
    for item in files:
        name = item.get("name") or ""
        path = item.get("path") or ""
        if not name.lower().endswith(".pdf") or not path or not Path(path).is_file():
            continue
        rendered = render_pdf(path, out_dir / "png", dpi=dpi, all_pages=True)
        info = save_pdf_info(path, rendered, out_dir / "png" / f"{Path(path).stem}.info.json")
        items.append({"name": name, "path": path, "info": str(info), **rendered})
    return {"png": {"items": items, "dpi": dpi}}

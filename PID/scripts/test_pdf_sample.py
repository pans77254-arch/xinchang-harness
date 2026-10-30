"""用桌面上的 PDF合并.pdf 检查上传后的页数、分辨率和 PNG。

样本是合并后的 4 页 A1，每页旋转 90 度，显示方向为横版。
用法：python scripts/test_pdf_sample.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image

from ai.tools.pdf2png import render_pdf, save_pdf_info
from backend.app.services.tasks import create_task

SAMPLE = Path(r"C:\Users\磐石\Desktop\PDF合并.pdf")
OUT = ROOT / "data" / "work" / "pdf_sample"


def main() -> None:
    assert SAMPLE.is_file(), f"找不到测试样本：{SAMPLE}"
    Image.MAX_IMAGE_PIXELS = None

    rendered = render_pdf(SAMPLE, OUT / "png", dpi=72, all_pages=True)
    info_path = save_pdf_info(SAMPLE, rendered, OUT / "PDF合并.info.json")
    saved = json.loads(info_path.read_text(encoding="utf-8"))

    assert rendered["ok"] is True
    assert rendered["page_count"] == 4, rendered["page_count"]
    assert saved["page_count"] == 4
    assert len(rendered["images"]) == 4
    assert len(rendered["pages"]) == 4
    dropped = {"rotation", "width_pt", "height_pt", "width_mm", "height_mm", "size", "dpi", "width_px", "height_px"}
    assert dropped.isdisjoint(saved)

    for page in rendered["pages"]:
        assert dropped.isdisjoint(page)
        png = Path(page["metadata_png"])
        assert png.is_file(), png
        assert page["notes"]["has_notes"] is False and page["notes"]["notes_path"] == [] and page["notes"]["info"] == []
        assert page["chart"]["has_chart"] is False and page["chart"]["chart_path"] == [] and page["chart"]["info"] == []
        assert page["frame"]["has_frame"] is False and page["frame"]["frame_path"] == [] and page["frame"]["info"] == []
        with Image.open(png) as image:
            assert image.size[0] > image.size[1], image.size

    from ai.tools.pdf2png import update_layout_info

    first = rendered["pages"][0]
    update_layout_info(
        [
            {
                "info": str(info_path),
                "page": 1,
                "image": first["metadata_png"],
                "boxes": [
                    {"class_name": "说明", "bbox": [20, 20, 120, 90], "confidence": 0.9},
                    {"class_name": "表格", "bbox": [140, 140, 280, 240], "confidence": 0.8},
                ],
            }
        ],
        OUT / "crops",
        extract=False,
    )
    updated = json.loads(info_path.read_text(encoding="utf-8"))["pages"][0]
    assert updated["metadata_png"] == first["metadata_png"]
    assert updated["notes"]["has_notes"] is True and Path(updated["notes"]["notes_path"][0]).is_file()
    assert updated["chart"]["has_chart"] is True and Path(updated["chart"]["chart_path"][0]).is_file()
    assert updated["frame"]["has_frame"] is False and updated["frame"]["frame_path"] == []
    assert updated["notes"]["info"] == [] and updated["chart"]["info"] == [] and updated["frame"]["info"] == []
    rest = json.loads(info_path.read_text(encoding="utf-8"))["pages"][1]
    assert rest["notes"]["has_notes"] is False and rest["chart"]["has_chart"] is False

    uploaded = create_task([(SAMPLE.name, SAMPLE.read_bytes())])
    entry = uploaded["files"][0]
    assert uploaded["status"] == "uploaded"
    assert Path(entry["path"]).is_file()
    assert "info" not in entry and "png" not in entry
    print(f"ok  {SAMPLE.name}  已上传，尚未解析")


if __name__ == "__main__":
    main()

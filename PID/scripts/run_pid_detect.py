"""上传 PDF 或对已有文件夹跑完整审查：解析、识别、提取、检查点。

用法：
  python scripts/run_pid_detect.py --pdf "<一份.pdf>"
  python scripts/run_pid_detect.py --folder "<已上传的任务目录>"
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _markdown(path: Path, result: dict) -> None:
    detections = result.get("detections") or []
    lines = [
        "# PID 图纸识别",
        "",
        f"- 文件夹：`{result.get('folder') or ''}`",
        f"- 计划：`{json.dumps(result.get('plan') or {}, ensure_ascii=False)}`",
        f"- PID 文件：{len(result.get('pid_files') or [])}",
        f"- 页图：{len(detections)}",
        "",
        "## 错别字",
        "",
    ]
    issues = result.get("issues") or []
    if not issues:
        lines.append("（无）")
    for issue in issues:
        lines.append(f"- **{issue.get('drawing_no') or '-'}** {issue.get('desc')}")
        basis = " ".join(str(issue.get("basis") or "").split())
        if basis:
            lines.append(f"  - 依据：{basis}")
    lines.extend(["", "## 检测结果", ""])
    if not detections:
        lines.append("（无）")
    for item in detections:
        boxes = item.get("boxes") or []
        lines.append(f"### {item.get('file')}  第 {item.get('page')} 页")
        lines.append("")
        if item.get("error"):
            lines.append(f"- 失败：{item['error']}")
        lines.append(f"- 框：{len(boxes)}")
        for box in boxes:
            lines.append(
                f"- {box.get('class_name') or '未命名'}  conf={box.get('confidence')}  bbox=`{box.get('bbox')}`"
            )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="PID 图纸识别")
    parser.add_argument("--pdf", default="", help="先上传这份 PDF，再跑全流程")
    parser.add_argument("--folder", default="", help="已上传的任务目录")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    if not args.pdf and not args.folder:
        parser.error("需要 --pdf 或 --folder")

    from ai.graph.controller import invoke

    task_id = "pid"
    folder = args.folder
    if args.pdf:
        from backend.app.config import UPLOAD_DIR
        from backend.app.services import tasks as task_svc

        src = Path(args.pdf)
        meta = task_svc.create_task([(src.name, src.read_bytes())])
        task_id = meta["task_id"]
        folder = str(UPLOAD_DIR / task_id)
        print("已上传", task_id, folder)

    result = invoke({"task_id": task_id, "folder": folder})
    result["folder"] = folder
    for line in result.get("logs") or []:
        print(line)
    plan = result.get("plan") or {}
    print("enter_pid", plan.get("enter_pid"), plan.get("reason") or "")
    for issue in result.get("issues") or []:
        print(f"  [{issue.get('type')}] {issue.get('desc')}")
        basis = " ".join(str(issue.get("basis") or "").split())
        if basis:
            print(f"    依据：{basis}")
    for item in result.get("detections") or []:
        names = "、".join(
            f"{box.get('class_name')}@{box.get('confidence')}" for box in (item.get("boxes") or [])
        )
        print(f"  {item.get('file')} p{item.get('page')}  {names or item.get('error') or '无框'}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = Path(args.out) if args.out else ROOT / "data" / "results" / f"pid_detect_{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    _markdown(md, result)
    print("完整 JSON：", out)
    print("可读摘要：", md)


if __name__ == "__main__":
    main()

"""跑说明栏错别字审查。用法：

  python scripts/run_notes_typo.py --folder <含 PID PNG/PDF 的文件夹> [--only-extract] [--limit N] [--out result.json]

不传 --out 时，自动写到 data/results/notes_typo_<时间戳>.json，并附一份可读的 .md 摘要。
--only-extract：只跑说明栏抄写（extract.notes），不调判定。
--limit：只处理前 N 份 PID。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _print_notes(notes: dict) -> None:
    for book in notes.get("files") or []:
        print(f"\n=== {book.get('file')}  图号={book.get('drawing_no')}  专业={book.get('discipline')}")
        for err in book.get("errors") or []:
            print(f"  [错误] {err}")
        for item in book.get("items") or []:
            print(
                f"  -- 说明块 page={item.get('page')} source={item.get('source')} "
                f"conf={item.get('yolo_conf')} bbox={item.get('bbox')}"
            )
            for line in item.get("lines") or []:
                print(f"     {line.get('line'):>3}. [{line.get('kind')}] {line.get('no')} {line.get('text')}")


def _default_out() -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = ROOT / "data" / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"notes_typo_{stamp}.json"


def _write_markdown(path: Path, payload: dict, folder: str, elapsed: float) -> None:
    notes = payload.get("notes") or {}
    issues = payload.get("issues") or []
    validation = payload.get("validation") or {}
    files = notes.get("files") or []
    typos = [i for i in issues if i.get("type") == "notes_typo"]
    errors = [i for i in issues if i.get("type") != "notes_typo"]
    lines = [
        "# 说明栏错别字审查结果",
        "",
        f"- 文件夹：`{folder}`",
        f"- 耗时：{elapsed:.1f}s",
        f"- 图纸数：{len(files)}",
        f"- Issue 总数：{len(issues)}（错别字 {len(typos)}，工具错误 {len(errors)}）",
        f"- validation：`{json.dumps(validation, ensure_ascii=False)}`",
        "",
        "## 错别字 Issue",
        "",
    ]
    if not typos:
        lines.append("（无）")
    for issue in typos:
        lines.append(
            f"- **{issue.get('drawing_no') or '-'}** "
            f"`{issue.get('type')}` conf={issue.get('confidence')}  \n"
            f"  {issue.get('desc')}"
        )
    lines.extend(["", "## 工具错误", ""])
    if not errors:
        lines.append("（无）")
    for issue in errors:
        lines.append(
            f"- **{issue.get('drawing_no') or '-'}** "
            f"`{issue.get('type')}`  \n"
            f"  {issue.get('desc')}"
        )
    lines.extend(["", "## 说明栏抄写全文", ""])
    for book in files:
        lines.append(f"### {book.get('file')}")
        lines.append("")
        lines.append(
            f"- 图号：`{book.get('drawing_no')}`  "
            f"专业：`{book.get('discipline')}`  "
            f"说明块：{len(book.get('items') or [])}"
        )
        for err in book.get("errors") or []:
            lines.append(f"- 抽取错误：{err}")
        for item in book.get("items") or []:
            lines.append("")
            lines.append(
                f"**说明块** page={item.get('page')} "
                f"source={item.get('source')} conf={item.get('yolo_conf')} "
                f"bbox=`{item.get('bbox')}`"
            )
            lines.append("")
            for line in item.get("lines") or []:
                lines.append(
                    f"{line.get('line')}. [{line.get('kind')}] "
                    f"{line.get('no') or ''} {line.get('text')}"
                )
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="说明栏错别字审查")
    parser.add_argument("--folder", required=True)
    parser.add_argument("--only-extract", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--out", default="", help="完整 JSON 路径；默认写入 data/results/")
    parser.add_argument("--quiet", action="store_true", help="少打终端，结果主要看文件")
    args = parser.parse_args()

    started = time.time()
    if args.only_extract:
        from ai.tools.file_classifier import classify_folder
        from ai.tools.registry import fill, load_tools

        load_tools()
        file_types = classify_folder(args.folder, use_vlm=False).get("file_types") or {}
        if args.limit:
            file_types["pid"] = (file_types.get("pid") or [])[: args.limit]
        artifacts = fill(["notes"], [], {"folder": args.folder, "file_types": file_types})
        notes = artifacts.get("notes") or {}
        if not args.quiet:
            _print_notes(notes)
            for log in notes.get("logs") or []:
                print("log:", log)
        payload = {"notes": notes, "issues": [], "validation": {}, "logs": notes.get("logs") or []}
    else:
        from ai.agents import form_review, validate
        from ai.tools.file_classifier import classify_folder
        from ai.tools.registry import fill, load_tools

        load_tools()
        file_types = classify_folder(args.folder, use_vlm=False).get("file_types") or {}
        print(f"识别到 PID {len(file_types.get('pid') or [])} 份，limit={args.limit or '全部'}")
        if args.limit:
            file_types["pid"] = (file_types.get("pid") or [])[: args.limit]
        artifacts = fill(["notes"], [], {"folder": args.folder, "file_types": file_types})
        reviewed = form_review.review(
            {"artifacts": artifacts, "skill_ids": ["form.notes_typo"], "logs": []}
        )
        notes = (artifacts.get("notes") or {})
        payload = {
            "folder": args.folder,
            "issues": reviewed.get("issues") or [],
            "validation": validate.validate(reviewed).get("validation"),
            "logs": notes.get("logs") or [],
            "notes": notes,
        }
        if not args.quiet:
            _print_notes(notes)
            print("\n=== Issues")
            for issue in payload["issues"]:
                print(
                    f"  [{issue['severity']}] {issue['type']} "
                    f"conf={issue.get('confidence')} :: {issue['desc']}"
                )
            print("\n=== validation", json.dumps(payload.get("validation"), ensure_ascii=False))

    elapsed = time.time() - started
    print(f"\n耗时 {elapsed:.1f}s")
    out = Path(args.out) if args.out else _default_out()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md = out.with_suffix(".md")
    _write_markdown(md, payload, args.folder, elapsed)
    print("完整 JSON：", out)
    print("可读摘要：", md)


if __name__ == "__main__":
    main()

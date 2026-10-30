"""PID 识别与检查的可编排步骤。由 ai/workflows/pid.review.yaml 引用 step 名。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.agents.pid_plan import build_plan, notes_from_info
from ai.tools.pid_layout import detect_pages, render_pages, work_dir_for
from ai.workflow import step


def _logs(state: dict[str, Any], line: str) -> list[str]:
    logs = list(state.get("logs") or [])
    logs.append(line)
    return logs


@step("extract_json")
def extract_json(state: dict[str, Any]) -> dict[str, Any]:
    """只读取已经抽好的 info JSON 字段。不转页、不检测、不检查。"""
    from ai.tools.extract_drawing_json import run as read_drawing_json

    folder = str(state.get("folder") or "")
    loaded = read_drawing_json([], {"folder": folder, "pages": list(state.get("pages") or [])})
    drawing = loaded.get("drawing_json") or {"files": []}
    artifacts = dict(state.get("artifacts") or {})
    artifacts["drawing_json"] = drawing
    count = len(drawing.get("files") or [])
    return {
        "artifacts": artifacts,
        "halt": False,
        "logs": _logs(state, f"extract_json: 读取 info JSON {count} 份"),
    }


def _frame_rows(drawing: dict[str, Any]) -> list[dict[str, Any]]:
    """把每页图框字段摊成审查算子能读的行。"""
    rows: list[dict[str, Any]] = []
    for book in drawing.get("files") or []:
        file_name = str(book.get("file") or "")
        for page in book.get("pages") or []:
            frame = page.get("frame") if isinstance(page, dict) else None
            if not isinstance(frame, dict):
                continue
            for found in frame.get("fields") or []:
                if not isinstance(found, dict):
                    continue
                drawing_no = str(found.get("文件号") or "")
                row = {
                    "file": file_name,
                    "page": page.get("page") or 0,
                    "drawing_no": drawing_no,
                    "实际张数": str(len(book.get("pages") or [])),
                }
                for key, value in found.items():
                    if key == "path":
                        continue
                    row[str(key)] = "" if value is None else str(value).strip()
                rows.append(row)
    return rows


def _column(rows: list[dict[str, Any]], key: str) -> list[str]:
    return [str(row.get(key) or "").strip() for row in rows if str(row.get(key) or "").strip()]


@step("review_json")
def review_json(state: dict[str, Any]) -> dict[str, Any]:
    """用已抽出的 JSON 跑带 when 的审查点。不调检测。"""
    from ai.agents import form_review
    from ai.agents.pid_plan import notes_from_info
    from ai.agents.skill_loader import list_skills

    artifacts = dict(state.get("artifacts") or {})
    drawing = artifacts.get("drawing_json") or {"files": []}
    books = [book for book in (drawing.get("files") or []) if isinstance(book, dict)]
    info_paths = [str(book.get("info") or "") for book in books if book.get("info")]
    rows = _frame_rows(drawing)
    artifacts["frame_rows"] = {"items": rows}
    artifacts["frame_file_nos"] = _column(rows, "文件号")
    artifacts["frame_values"] = {
        key: _column(rows, key) for key in ("阶段", "项目名称", "项目号", "专业", "版次")
    }
    from ai.tools.operators import file_no_prefix

    artifacts["frame_file_prefixes"] = [
        file_no_prefix(str(row.get("文件号") or "")) for row in rows if str(row.get("文件号") or "").strip()
    ]
    artifacts["notes"] = notes_from_info(info_paths)
    artifacts["review_folder"] = str(state.get("folder") or "")

    ready = {
        "has_notes": bool((artifacts["notes"].get("files") or [])),
        "has_frame": bool(rows),
        "has_chart": any(
            (page.get("chart") or {}).get("tables")
            for book in books
            for page in (book.get("pages") or [])
            if isinstance(page, dict)
        ),
    }
    skill_ids = [
        str(skill.get("id") or "")
        for skill in list_skills(include_disabled=False)
        if str(skill.get("when") or "") in ready and ready[str(skill.get("when") or "")]
    ]
    if not skill_ids:
        return {
            "artifacts": artifacts,
            "issues": [],
            "logs": _logs(state, "review_json: 没有可执行的审查点"),
            "halt": False,
        }
    reviewed = form_review.review({"artifacts": artifacts, "skill_ids": skill_ids, "logs": []})
    issues = list(reviewed.get("issues") or [])
    logs = _logs(state, f"review_json: 审查点 {len(skill_ids)} 个，问题 {len(issues)} 条")
    counts: dict[str, int] = {}
    for issue in issues:
        sid = str(issue.get("skill_id") or "")
        counts[sid] = counts.get(sid, 0) + 1
    for skill_id in skill_ids:
        logs.append(f"review_json: {skill_id} 问题 {counts.get(skill_id, 0)} 条")
    return {"artifacts": artifacts, "issues": issues, "logs": logs, "halt": False}


_PAGE_EXT = {".pdf", ".png", ".jpg", ".jpeg"}


@step("parse")
@step("extract")
def extract(state: dict[str, Any]) -> dict[str, Any]:
    """解析刚上传的 PDF 或页图。不读取上一次已经生成的 info JSON。"""
    folder = Path(str(state.get("folder") or ""))
    if not folder.is_dir():
        return {"pages": [], "pid_files": [], "halt": False, "logs": _logs(state, "parse: 没有上传目录")}
    names = [
        path.name
        for path in sorted(folder.iterdir())
        if path.is_file() and path.suffix.lower() in _PAGE_EXT and not path.name.startswith("~$")
    ]
    if not names:
        return {"pages": [], "pid_files": [], "halt": False, "logs": _logs(state, "parse: 没有上传的 PDF 或页图")}
    rendered = render_pages(str(folder), names, work_dir_for(str(folder)))
    return {
        "pages": rendered,
        "pid_files": names,
        "halt": False,
        "logs": _logs(state, f"parse: 转页图 {len(rendered)} 张"),
    }


@step("plan")
def plan(state: dict[str, Any]) -> dict[str, Any]:
    """规划路由：把页级 JSON 和已有检查点编成工具、技能清单。

    计划里没有 pid.detect 时置 halt，由 workflow 的 on_halt 决定离开哪条边。
    """
    planned = build_plan(list(state.get("pages") or []))
    tools = "、".join(planned["tools"]) or "无"
    skills = "、".join(item["id"] for item in planned["skills"]) or "无"
    enter = "pid.detect" in (planned.get("tools") or [])
    return {
        "plan": planned,
        "halt": not enter,
        "logs": _logs(state, f"plan: 工具 {tools}；技能 {skills}"),
    }


@step("recognize")
def recognize(state: dict[str, Any]) -> dict[str, Any]:
    """版面识别：标出图框、表格、说明。不抄写栏位。"""
    pages = list(state.get("pages") or [])
    if not pages:
        return {"detections": [], "halt": False, "logs": _logs(state, "recognize: 没有页图")}
    detections = detect_pages(pages)
    boxes = sum(len(item.get("boxes") or []) for item in detections)
    errors = sum(1 for item in detections if item.get("error"))
    return {
        "detections": detections,
        "halt": False,
        "logs": _logs(state, f"recognize: 框 {boxes} 个，失败 {errors} 页"),
    }


@step("extract_fields")
def extract_fields(state: dict[str, Any]) -> dict[str, Any]:
    """按识别框抽出说明、图表、图框字段，再读回 JSON。"""
    from ai.tools.pdf2png import update_layout_info

    detections = list(state.get("detections") or [])
    updated = update_layout_info(detections, work_dir_for(str(state.get("folder") or "")) / "crops") if detections else []
    loaded = extract_json(state)
    logs = list(loaded.get("logs") or [])
    logs.append(f"extract_fields: 回写 {len(updated)} 份")
    loaded["logs"] = logs
    loaded["halt"] = False
    return loaded


@step("detect")
def detect(state: dict[str, Any]) -> dict[str, Any]:
    """识别并提取。workflow 已拆成 recognize、extract_fields，此函数留给旧调用。"""
    recognized = recognize(state)
    merged = dict(state)
    merged["detections"] = recognized.get("detections") or []
    merged["logs"] = recognized.get("logs") or []
    extracted = extract_fields(merged)
    boxes = sum(len(item.get("boxes") or []) for item in merged["detections"])
    errors = sum(1 for item in merged["detections"] if item.get("error"))
    logs = list(extracted.get("logs") or [])
    logs.append(f"detect: 框 {boxes} 个，失败 {errors} 页")
    extracted["detections"] = merged["detections"]
    extracted["logs"] = logs
    return extracted


def _skill_ready(pages: list[dict[str, Any]], when: str) -> bool:
    import json

    source = {"has_notes": "notes", "has_frame": "frame", "has_chart": "chart"}.get(when)
    if not source:
        return False
    info_paths = {str(page.get("info") or "") for page in pages if page.get("info")}
    for raw in info_paths:
        path = Path(raw)
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for page in data.get("pages") or []:
            block = page.get(source) if isinstance(page, dict) else None
            if isinstance(block, dict) and block.get(when):
                return True
    return False


def _dynamic_files(info_paths: list[str], when: str) -> list[dict[str, Any]]:
    """把图框栏位或图表单元格收成可判定的文本行。说明仍走 notes_from_info。"""
    from ai.tools.extract_drawing_json import read_info
    from ai.tools.extract_notes import discipline_of, drawing_no_of

    source = {"has_frame": "frame", "has_chart": "chart"}.get(when)
    files: list[dict[str, Any]] = []
    if not source:
        return files
    for raw in info_paths:
        if not Path(raw).is_file():
            continue
        book = read_info(raw)
        file_name = str(book.get("file") or "")
        drawing_no = str((book.get("fields") or {}).get("文件号") or "") or drawing_no_of(file_name)
        lines: list[dict[str, Any]] = []
        for page in book.get("pages") or []:
            block = page.get(source) or {}
            if source == "frame":
                for found in block.get("fields") or []:
                    for key, value in found.items():
                        if key == "path" or not str(value or "").strip():
                            continue
                        lines.append({"kind": "条文", "text": f"{key}：{value}"})
            else:
                for table in block.get("tables") or []:
                    for row in table.get("rows") or []:
                        text = " ".join(str(cell) for cell in row) if isinstance(row, list) else str(row)
                        if text.strip():
                            lines.append({"kind": "条文", "text": text})
        if lines:
            files.append(
                {
                    "file": file_name,
                    "drawing_no": drawing_no,
                    "discipline": discipline_of(file_name, drawing_no),
                    "items": [{"page": 1, "lines": lines}],
                    "errors": [],
                }
            )
    return files


@step("check")
def check(state: dict[str, Any]) -> dict[str, Any]:
    """按计划执行检查。检测没写出所需内容的技能不跑。"""
    from ai.agents import form_review, validate
    from ai.agents.skill_loader import load_skill
    from ai.issue import make_issue
    from ai.tools.operators import llm_judge

    planned = state.get("plan") or {}
    pages = list(state.get("pages") or [])
    issues: list[dict[str, Any]] = []
    logs = list(state.get("logs") or [])
    info_paths = sorted({str(page.get("info") or "") for page in pages if page.get("info")})
    for skill in planned.get("skills") or []:
        skill_id = str(skill.get("id") or "")
        when = str(skill.get("when") or "")
        if not _skill_ready(pages, when):
            logs.append(f"check: 跳过 {skill_id}，检测结果不满足 {when}")
            continue
        if skill_id == "form.notes_typo":
            notes = notes_from_info(info_paths)
            reviewed = form_review.review(
                {
                    "artifacts": {"notes": notes, "file_types": state.get("file_types") or {}},
                    "skill_ids": [skill_id],
                    "logs": [],
                }
            )
            issues.extend(reviewed.get("issues") or [])
            logs.append(f"check: {skill_id} 问题 {len(reviewed.get('issues') or [])} 条")
            continue
        loaded = load_skill(skill_id) or {}
        check_item = (loaded.get("checks") or [{}])[0]
        criterion = str(check_item.get("criterion") or loaded.get("basis") or "")
        files = notes_from_info(info_paths)["files"] if when == "has_notes" else _dynamic_files(info_paths, when)

        def _judge(**kwargs: Any) -> dict[str, Any]:
            from ai.agents.extract_info import judge_json

            return judge_json(criterion=criterion, **kwargs)

        diffs = llm_judge(
            files=files,
            prompt_id="judge.dynamic",
            min_confidence=0.7,
            kinds=["条文", "框图节点", "标题"],
            judge_fn=_judge,
        )
        for diff in diffs:
            if diff.get("type") == "tool_error":
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type="dynamic_check_error",
                        severity="medium",
                        desc=str(diff.get("desc") or "检查失败"),
                        basis=str(loaded.get("basis") or ""),
                        drawing_no=str(diff.get("drawing_no") or ""),
                    )
                )
                continue
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=str(check_item.get("type") or "dynamic_check"),
                    severity=str(loaded.get("severity") or "low"),
                    desc=f"{diff.get('drawing_no') or ''} 「{diff.get('wrong')}」应为「{diff.get('correct')}」（{diff.get('reason')}）",
                    basis=str(loaded.get("basis") or ""),
                    suggestion="核对原图后处理",
                    drawing_no=str(diff.get("drawing_no") or ""),
                    confidence=float(diff.get("confidence") or 0),
                )
            )
        logs.append(f"check: {skill_id} 问题 {len(diffs)} 条")
    checked = validate.validate({"issues": issues})
    return {"issues": issues, "validation": checked.get("validation") or {}, "logs": logs, "halt": False}

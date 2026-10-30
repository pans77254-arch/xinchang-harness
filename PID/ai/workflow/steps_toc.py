"""目录索引一致性的可编排步骤。由 workflow.yaml 引用 step 名。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.agents import form_review
from ai.agents.drawing_detect import crop_image
from ai.agents.extract_info import extract_json
from ai.agents.skill_loader import load_skill
from ai.config import PDF_DPI, WORK_ROOT
from ai.issue import make_issue
from ai.tools.file_classifier import find_catalog
from ai.tools.pdf2png import render_pdf
from ai.tools.word2png import render_word
from ai.tools.word_doc import close as close_word
from ai.tools.word_doc import launch as launch_word
from ai.workflow import step

DOC_EXT = {".doc", ".docx"}
PDF_EXT = {".pdf"}


def _logs(state: dict[str, Any], message: str) -> list[str]:
    logs = list(state.get("logs") or [])
    logs.append(message)
    return logs


def _skill(state: dict[str, Any]) -> dict[str, Any]:
    cached = state.get("skill")
    if isinstance(cached, dict) and cached.get("id"):
        return cached
    skill_id = (state.get("skill_ids") or ["form.toc_index"])[0]
    return load_skill(skill_id) or {}


def _skill_id(state: dict[str, Any]) -> str:
    return str(_skill(state).get("id") or "form.toc_index")


def _list_folder(folder: str) -> list[dict[str, str]]:
    root = Path(folder)
    files = []
    if not root.is_dir():
        return files
    for path in sorted(root.iterdir()):
        if not path.is_file() or path.name.startswith("~$"):
            continue
        if path.suffix.lower() not in DOC_EXT | PDF_EXT:
            continue
        files.append({"id": path.stem, "name": path.name, "path": str(path)})
    return files


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


@step("ingest_folder")
def ingest_folder(state: dict[str, Any]) -> dict[str, Any]:
    skill = _skill(state)
    files = [f for f in (state.get("files") or []) if not str(f.get("name") or "").startswith("~$")]
    folder = state.get("folder") or ""
    if not files and folder:
        files = _list_folder(folder)
    catalog = next((f for f in files if "目录" in (f.get("name") or "")), None)
    if catalog is not None:
        catalog["suffix"] = Path(catalog["name"]).suffix.lower()
    others = [f for f in files if f is not catalog]
    work = WORK_ROOT / (state.get("task_id") or "toc")
    work.mkdir(parents=True, exist_ok=True)
    logs = _logs(state, f"ingest: {len(files)} 个文件，目录={'有' if catalog else '无'}")
    if catalog is None and not others:
        issue = make_issue(
            skill_id=_skill_id(state),
            issue_type="missing_catalog",
            severity="high",
            desc="文件夹中没有可识别的 Word/PDF 文件，无法做目录索引一致性审查",
            basis=skill.get("basis", ""),
            suggestion="放入设计文件目录（目录.doc、目录.docx 或目录.pdf）后重跑",
        )
        return {
            "skill": skill,
            "files": files,
            "catalog_file": {},
            "candidate_files": [],
            "word_files": [],
            "pdf_files": [],
            "work_dir": str(work),
            "logs": logs,
            "issues": [issue],
            "halt": True,
        }
    return {
        "skill": skill,
        "files": files,
        "catalog_file": catalog or {},
        "candidate_files": others if catalog is None else [],
        "word_files": [f for f in others if Path(f["name"]).suffix.lower() in DOC_EXT],
        "pdf_files": [f for f in others if Path(f["name"]).suffix.lower() in PDF_EXT],
        "work_dir": str(work),
        "logs": logs,
        "halt": False,
        "issues": [],
        "side_issues": [],
    }


@step("detect_catalog")
def detect_catalog(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    if state.get("catalog_file"):
        return {"logs": _logs(state, "detect_catalog: 命名已命中，跳过内容兜底")}
    skill = _skill(state)
    config = skill.get("catalog_detect") or {}
    logs = _logs(state, f"detect_catalog: 命名未命中，候选 {len(state.get('candidate_files') or [])} 个")
    if not config.get("enabled", True):
        issue = make_issue(
            skill_id=_skill_id(state),
            issue_type="missing_catalog",
            severity="high",
            desc="文件名未包含「目录」，且内容兜底已关闭，无法定位目录文件",
            basis=skill.get("basis", ""),
            suggestion="将目录文件命名为含「目录」，或在 Skill 中开启 catalog_detect.enabled",
        )
        return {"catalog_file": {}, "logs": logs, "issues": [issue], "halt": True}
    dpi = int((skill.get("tools") or {}).get("pdf_dpi") or PDF_DPI)
    best, find_logs = find_catalog(
        state.get("files") or [],
        work_dir=Path(state["work_dir"]) / "png",
        dpi=dpi,
        candidates=state.get("candidate_files"),
        scope=str(config.get("candidates") or "all").lower(),
        prompt=config.get("prompt") or "file_classify.is_catalog",
        threshold=float(config.get("threshold") or 0.8),
    )
    logs.extend(find_logs)
    if not best:
        issue = make_issue(
            skill_id=_skill_id(state),
            issue_type="missing_catalog",
            severity="high",
            desc="命名未命中，内容兜底也未识别到目录文件",
            basis=skill.get("basis", ""),
            suggestion="确认文件夹内存在资料图纸目录（含目录表格）后重跑",
        )
        return {"catalog_file": {}, "logs": logs, "issues": [issue], "halt": True}
    best = {**best, "suffix": Path(best["name"]).suffix.lower()}
    logs.append(f"detect_catalog: 命中目录 {best['name']}")
    return {"catalog_file": best, "logs": logs}


@step("catalog_to_png")
def catalog_to_png(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    catalog = state["catalog_file"]
    dpi = int(((_skill(state).get("tools") or {}).get("pdf_dpi")) or PDF_DPI)
    suffix = (catalog.get("suffix") or Path(catalog["name"]).suffix).lower()
    try:
        if suffix in DOC_EXT:
            rendered = render_word(catalog["path"], Path(state["work_dir"]) / "png", dpi=dpi)
            image = rendered.get("image") or ""
            paper = rendered.get("paper") or {}
        else:
            rendered = render_pdf(catalog["path"], Path(state["work_dir"]) / "png", dpi=dpi)
            image = (rendered.get("images") or [""])[0]
            paper = rendered.get("paper") or {}
        error = rendered.get("error") or ""
    except Exception as exc:
        image, paper, error = "", {}, str(exc)
    logs = _logs(state, f"catalog_to_png: {catalog['name']} type={suffix} ok={bool(image)}")
    if not image:
        issue = make_issue(
            skill_id=_skill_id(state),
            issue_type="tool_error",
            severity="high",
            desc=f"目录第一页转 PNG 失败：{error}",
            basis=_skill(state).get("basis", ""),
            suggestion="确认该目录文件可正常打开后重跑",
        )
        return {"catalog_image": "", "logs": logs, "issues": [issue], "halt": True}
    return {"catalog_image": image, "catalog_paper": paper, "logs": logs}


@step("extract_catalog")
def extract_catalog(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    spec = (_skill(state).get("extract") or {}).get("catalog") or {}
    fields = list(spec.get("public_fields") or []) + list(spec.get("row_fields") or [])
    data = extract_json(
        prompt_id=spec.get("prompt") or "",
        fields=fields,
        image_path=state.get("catalog_image") or "",
        expect="catalog",
    )
    logs = _logs(state, f"extract_catalog: error={bool(data.get('_error'))}")
    if data.get("_error"):
        issue = make_issue(
            skill_id=_skill_id(state),
            issue_type="tool_error",
            severity="high",
            desc=f"目录信息抽取失败：{data['_error']}",
            basis=_skill(state).get("basis", ""),
            suggestion="确认 192.168.31.9:8000 的本地大模型可用后重跑",
        )
        return {"logs": logs, "issues": [issue], "halt": True}
    public = data.get("public") if isinstance(data.get("public"), dict) else {}
    entries = []
    for row in data.get("entries") or []:
        if not isinstance(row, dict):
            continue
        file_no = _as_text(row.get("file_no"))
        if not file_no:
            continue
        entries.append({key: _as_text(row.get(key)) for key in ("seq", "file_no", "name", "revision", "sheet_count", "equivalent", "remark")})
    catalog = {"public": {k: _as_text(v) for k, v in public.items()}, "entries": entries}
    return {"catalog": catalog, "logs": logs}


@step("pdf_to_png")
def pdf_to_png(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    dpi = int(((_skill(state).get("tools") or {}).get("pdf_dpi")) or PDF_DPI)
    work = Path(state["work_dir"]) / "png"
    images = []
    logs = list(state.get("logs") or [])
    for item in state.get("pdf_files") or []:
        try:
            rendered = render_pdf(item["path"], work, dpi=dpi)
            images.append(
                {
                    "file": item,
                    "page_count": rendered["page_count"],
                    "image": (rendered["images"] or [""])[0],
                    "paper": rendered.get("paper") or {},
                    "error": "",
                }
            )
            logs.append(f"pdf_to_png: {item['name']} pages={rendered['page_count']} dpi={dpi}")
        except Exception as exc:
            images.append({"file": item, "page_count": 0, "image": "", "error": str(exc)})
            logs.append(f"pdf_to_png: {item['name']} 失败 {exc}")
    return {"page_images": images, "logs": logs}


@step("word_to_png")
def word_to_png(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    dpi = int(((_skill(state).get("tools") or {}).get("pdf_dpi")) or PDF_DPI)
    work = Path(state["work_dir"]) / "png"
    sources = []
    side = list(state.get("side_issues") or [])
    logs = list(state.get("logs") or [])
    basis = _skill(state).get("basis", "")
    if not state.get("word_files"):
        return {"word_sources": [], "logs": _logs(state, "word_to_png: 无 Word 文件")}
    app = None
    try:
        app = launch_word()
        for item in state.get("word_files") or []:
            rendered = render_word(item["path"], work, dpi=dpi, app=app)
            sources.append(
                {
                    "file": item,
                    "image": rendered.get("image") or "",
                    "paper": rendered.get("paper") or {},
                    "error": "" if rendered.get("ok") else rendered.get("error") or "",
                }
            )
            logs.append(f"word_to_png: {item['name']} ok={rendered.get('ok')}")
            if not rendered.get("ok"):
                side.append(
                    make_issue(
                        skill_id=_skill_id(state),
                        issue_type="tool_error",
                        severity="high",
                        desc=f"{item['name']} 第一页转 PNG 失败：{rendered.get('error')}",
                        basis=basis,
                        suggestion="确认该 Word 文件能打开后重跑",
                    )
                )
    finally:
        close_word(app)
    return {"word_sources": sources, "side_issues": side, "logs": logs}


def _model_image(state: dict[str, Any], image: str, logs: list[str], name: str) -> str:
    category = ((_skill(state).get("detect") or {}).get("category")) or "图框"
    cropped = crop_image(image, Path(state["work_dir"]) / "crops", category)
    if cropped.get("ok") and cropped.get("crop_path"):
        logs.append(f"yolo: {name} 图框 conf={cropped.get('confidence')}")
        return str(cropped["crop_path"])
    logs.append(f"yolo: {name} 未裁到图框，整页兜底：{cropped.get('error')}")
    return image


def _file_fields(skill: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], list[dict[str, Any]]]:
    spec = (skill.get("extract") or {}).get("file") or {}
    word_prompt = spec.get("prompt") or ""
    drawing_prompt = spec.get("drawing_prompt") or word_prompt
    drawing_fields = list(spec.get("drawing_fields") or spec.get("fields") or [])
    return word_prompt, drawing_prompt, list(spec.get("fields") or []), drawing_fields


def _attach_paper(item: dict[str, Any], paper: dict[str, Any] | None) -> None:
    paper = paper or {}
    item["paper_size"] = _as_text(paper.get("size"))
    item["paper_width_mm"] = paper.get("width_mm") if paper.get("width_mm") not in (None, "") else ""
    item["paper_height_mm"] = paper.get("height_mm") if paper.get("height_mm") not in (None, "") else ""


_DRAWING_KEYS = (
    "design_cert_no",
    "survey_cert_no",
    "drawn_by",
    "designed_by",
    "checked_by",
    "reviewed_by",
    "project_lead",
    "approved_by",
    "area_name",
    "unit_name",
    "discipline_unit_name",
    "scale",
)


def _clean_item(data: dict[str, Any], *, file_name: str, page_count: int, kind: str, paper: dict[str, Any] | None = None) -> dict[str, Any]:
    keys = ("file_no", "name", "project_no", "project_name", "discipline", "stage", "date", "revision", "sheet_count")
    item = {key: _as_text(data.get(key)) for key in keys}
    if kind == "pdf":
        for key in _DRAWING_KEYS:
            item[key] = _as_text(data.get(key))
    item.update({"file": file_name, "page_count": page_count, "kind": kind, "drawing_no": item["file_no"], "is_catalog": False})
    _attach_paper(item, paper)
    return item


@step("extract_files")
def extract_files(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    skill = _skill(state)
    word_prompt, drawing_prompt, fields, drawing_fields = _file_fields(skill)
    extracted = []
    side = list(state.get("side_issues") or [])
    unidentified: list[str] = []
    logs = list(state.get("logs") or [])
    basis = skill.get("basis", "")

    catalog = state.get("catalog") or {}
    public = catalog.get("public") or {}
    catalog_file = state.get("catalog_file") or {}
    if public:
        extracted.append(
            {
                "file_no": _as_text(public.get("file_no")),
                "name": _as_text(public.get("doc_title")),
                "project_no": _as_text(public.get("project_no")),
                "project_name": _as_text(public.get("project_name")),
                "discipline": _as_text(public.get("discipline")),
                "stage": _as_text(public.get("stage")),
                "date": _as_text(public.get("date")),
                "revision": _as_text(public.get("revision")),
                "sheet_count": _as_text(public.get("sheet_count")),
                "page_count": 0,
                "file": catalog_file.get("name") or "",
                "kind": "catalog",
                "drawing_no": _as_text(public.get("file_no")),
                "is_catalog": True,
            }
        )
        _attach_paper(extracted[-1], state.get("catalog_paper") or {})

    for source in state.get("word_sources") or []:
        name = source["file"]["name"]
        if source.get("error") or not source.get("image"):
            unidentified.append(name)
            continue
        data = extract_json(prompt_id=word_prompt, fields=fields, image_path=source["image"])
        if data.get("_error"):
            unidentified.append(name)
            side.append(
                make_issue(
                    skill_id=_skill_id(state),
                    issue_type="tool_error",
                    severity="high",
                    desc=f"{name} 信息抽取失败：{data['_error']}",
                    basis=basis,
                    suggestion="确认本地大模型可用后重跑",
                )
            )
            logs.append(f"extract_files: {name} 失败")
            continue
        extracted.append(_clean_item(data, file_name=name, page_count=0, kind="word", paper=source.get("paper") or {}))
        logs.append(f"extract_files: {name} file_no={data.get('file_no')}")

    for page in state.get("page_images") or []:
        name = page["file"]["name"]
        if page.get("error") or not page.get("image"):
            unidentified.append(name)
            continue
        image = _model_image(state, page["image"], logs, name)
        data = extract_json(prompt_id=drawing_prompt, fields=drawing_fields, image_path=image)
        if data.get("_error"):
            unidentified.append(name)
            side.append(
                make_issue(
                    skill_id=_skill_id(state),
                    issue_type="tool_error",
                    severity="high",
                    desc=f"{name} 信息抽取失败：{data['_error']}",
                    basis=basis,
                    suggestion="确认本地大模型可接收图像后重跑",
                )
            )
            logs.append(f"extract_files: {name} 失败")
            continue
        extracted.append(
            _clean_item(data, file_name=name, page_count=int(page.get("page_count") or 0), kind="pdf", paper=page.get("paper") or {})
        )
        logs.append(f"extract_files: {name} file_no={data.get('file_no')}")

    return {"extracted": extracted, "unidentified": unidentified, "side_issues": side, "logs": logs}


@step("assemble")
def assemble(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    catalog = state.get("catalog") or {}
    entries = catalog.get("entries") or []
    extracted = state.get("extracted") or []
    artifacts = {
        "toc": {
            "public": catalog.get("public") or {},
            "entries": entries,
            "file_nos": [e.get("file_no") for e in entries if e.get("file_no")],
            "drawing_nos": [e.get("file_no") for e in entries if e.get("file_no")],
        },
        "title_block": {"items": extracted, "file_nos": [i.get("file_no") for i in extracted if i.get("file_no")]},
        "file_list": {
            "items": state.get("files") or [],
            "unidentified": state.get("unidentified") or [],
            "names": [f.get("name") for f in (state.get("files") or [])],
        },
    }
    return {"artifacts": artifacts, "logs": _logs(state, f"assemble: 目录 {len(entries)} 条，文件 {len(extracted)} 份")}


@step("review")
def review(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("halt"):
        return {}
    skill_ids = state.get("skill_ids") or [_skill_id(state)]
    produced = form_review.review(
        {"artifacts": state.get("artifacts") or {}, "skill_ids": skill_ids, "logs": list(state.get("logs") or [])}
    )
    issues = list(state.get("side_issues") or []) + list(produced.get("issues") or [])
    return {"issues": issues, "logs": produced.get("logs") or state.get("logs") or []}


@step("validate")
def validate(state: dict[str, Any]) -> dict[str, Any]:
    from ai.agents.validate import validate as check

    checked = check({"issues": state.get("issues") or []})
    logs = _logs(state, f"validate: {checked['validation']}")
    return {"logs": logs, **checked}

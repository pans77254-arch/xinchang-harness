"""通用审查执行器：读 Skill YAML 的 checks，调 operators，产出 Issue。

新增审查点：只加 YAML，不要复制本文件。确需新算子时改 ai/tools/operators.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.agents.skill_loader import list_skills, load_resource
from ai.issue import make_issue
from ai.tools import operators as ops


def _certs(check: dict[str, Any]) -> list[dict[str, Any]]:
    """优先用检查里写的证书表，否则读规则目录里的证书文件。"""
    inline = check.get("certs")
    if isinstance(inline, list) and inline:
        return [item for item in inline if isinstance(item, dict)]
    loaded = load_resource(str(check.get("certs_file") or ""))
    if isinstance(loaded, list):
        return [item for item in loaded if isinstance(item, dict)]
    return []


def _get(artifacts: dict[str, Any], path: str) -> Any:
    cur: Any = artifacts
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return []
        cur = cur[part]
    return cur


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if x not in (None, "")]
    return [str(value)]


def _severity(check: dict[str, Any], default: str) -> str:
    return str(check.get("severity") or default)


# seq_audit 差异类型 → 审查规则里的 type/msg 键。gap 沿用其他算子惯用的 type/msg。
_SEQ_TYPE_KEYS = {
    "gap": "type",
    "duplicate": "duplicate_type",
    "off_ladder": "off_ladder_type",
    "total_mismatch": "total_type",
    "unparseable": "unparseable_type",
    "parity": "parity_type",
}
_SEQ_MSG_KEYS = {
    "gap": "msg",
    "duplicate": "msg_duplicate",
    "off_ladder": "msg_off_ladder",
    "total_mismatch": "msg_total",
    "unparseable": "msg_unparseable",
    "parity": "msg_parity",
}


def _seq_msg(check: dict[str, Any], kind: str, diff: dict[str, Any]) -> str:
    """按差异类型套用审查规则的文案模板，模板缺失或变量不足时退回算子给的 desc。"""
    template = check.get(_SEQ_MSG_KEYS.get(kind, f"msg_{kind}")) or check.get("msg") or ""
    fallback = str(diff.get("desc") or "")
    if not template:
        return fallback
    try:
        return template.format(**diff)
    except (KeyError, IndexError, ValueError):
        return fallback


def _catalog_file_numbers(folder: Path) -> list[str]:
    """从文件夹里的目录页抽出文件号。抽不出返回空列表。"""
    catalog = next((path for path in folder.iterdir() if path.is_file() and "目录" in path.name), None)
    if catalog is None:
        return []
    image = catalog
    if catalog.suffix.lower() == ".pdf":
        from ai.tools.pdf2png import render_pdf

        rendered = render_pdf(catalog, folder / "_catalog_png", all_pages=False)
        images = rendered.get("images") or []
        if not images:
            return []
        image = Path(str(images[0]))
    elif catalog.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
        return []
    from ai.agents.extract_info import extract_json

    data = extract_json(
        prompt_id="form.toc_index.catalog",
        fields=[
            {"name": "file_no", "desc": "文件号"},
            {"name": "name", "desc": "名称"},
        ],
        image_path=str(image),
        expect="catalog",
        max_tokens=4096,
    )
    numbers: list[str] = []
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    for row in entries:
        if isinstance(row, dict) and str(row.get("file_no") or "").strip():
            numbers.append(str(row.get("file_no")).strip())
    return numbers


def run_check(skill: dict[str, Any], check: dict[str, Any], artifacts: dict[str, Any]) -> list[dict[str, Any]]:
    op = check.get("op")
    skill_id = skill.get("id", "")
    default_sev = skill.get("severity", "medium")
    issues: list[dict[str, Any]] = []

    if op == "set_diff":
        left = _as_list(_get(artifacts, check["left"]))
        right = _as_list(_get(artifacts, check["right"]))
        only_l, only_r = ops.set_diff(left, right)
        if only_l:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_left", "missing"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_left", "左侧有而右侧无：{items}").format(items="、".join(sorted(only_l))),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_left", ""),
                )
            )
        if only_r:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_right", "extra"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_right", "右侧有而左侧无：{items}").format(items="、".join(sorted(only_r))),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_right", ""),
                )
            )
        return issues

    if op == "eq":
        values = _as_list(_get(artifacts, check["field"]))
        ok, uniq = ops.eq_all(values)
        if not ok:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "mismatch"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "字段不一致：{items}").format(items="、".join(sorted(uniq))),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                )
            )
        return issues

    if op == "name_overlap":
        items = _get(artifacts, check["items"])
        if not isinstance(items, list):
            return issues
        fields = [str(name) for name in (check.get("fields") or [])]
        min_len = int(check.get("min_len") or 4)
        for item in items:
            if not isinstance(item, dict):
                continue
            drawing_no = str(item.get("drawing_no") or "")
            for left, right, left_value, right_value in ops.name_overlap(item, fields, min_len=min_len):
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "name_overlap"),
                        severity=_severity(check, default_sev),
                        desc=check.get("msg", "{drawing_no} 名称重叠：{left}「{left_value}」与 {right}「{right_value}」").format(
                            drawing_no=drawing_no,
                            left=left,
                            right=right,
                            left_value=left_value,
                            right_value=right_value,
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=drawing_no,
                    )
                )
        return issues

    if op == "seq":
        nos = _as_list(_get(artifacts, check["field"]))
        holes = ops.seq_groups(nos)
        for key, missing in holes:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "gap"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "{key} 缺号 {missing}").format(
                        key=key, missing="、".join(f"{n:03d}" for n in missing)
                    ),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                )
            )
        return issues

    if op == "required_fields":
        items = _get(artifacts, check["items"])
        if not isinstance(items, list):
            return issues
        fields = check.get("fields") or []
        for item in items:
            if not isinstance(item, dict) or item.get("_stub"):
                continue
            drawing_no = str(item.get("drawing_no") or "")
            for f in fields:
                if not str(item.get(f) or "").strip():
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type=check.get("type", "missing_field"),
                            severity=_severity(check, default_sev),
                            desc=check.get("msg", "{drawing_no} 缺 {field}").format(
                                drawing_no=drawing_no or item.get("name", ""), field=f
                            ),
                            basis=skill.get("basis", ""),
                            suggestion=check.get("suggestion", ""),
                            drawing_no=drawing_no,
                        )
                    )
        return issues

    if op == "flag_items":
        items = _as_list(_get(artifacts, check["items"]))
        if items:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "unidentified_file"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "未能识别：{items}").format(items="、".join(items)),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                )
            )
        return issues

    if op == "catalog_align":
        rows = _get(artifacts, check["rows"])
        found = _get(artifacts, check["items"])
        public = _get(artifacts, check["public"])
        if not isinstance(rows, list) or not isinstance(found, list) or not isinstance(public, dict):
            return issues
        diffs = ops.catalog_align(
            rows=rows,
            items=found,
            public=public,
            public_fields=list(check.get("public_fields") or []),
            public_labels=dict(check.get("public_labels") or {}),
            row_fields=list(check.get("row_fields") or []),
            paper_factors=dict(check.get("paper_factors") or {}),
            pair_by=list(check.get("pair_by") or ["file_no", "name"]),
            identity_field=check.get("identity_field", "file_no"),
            report_missing=bool(check.get("report_missing", True)),
            report_extra=bool(check.get("report_extra", True)),
        )
        for diff in diffs:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=diff["type"],
                    severity=diff.get("severity") or default_sev,
                    desc=diff["desc"],
                    basis=skill.get("basis", ""),
                    suggestion=diff.get("suggestion", ""),
                    drawing_no=diff.get("drawing_no") or "",
                )
            )
        return issues

    if op == "expect":
        # target 可以是单个（字符串）或多个（列表，如多份 PID），逐个核对。
        targets = [t for t in _as_list(_get(artifacts, check.get("target", ""))) if t.strip()]
        items = _get(artifacts, check.get("source", ""))
        expected = check.get("expected", "")
        field = check.get("field", "")
        match_by = check.get("match_by", "file")
        label = check.get("label") or field
        if not targets:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_missing", "expect_missing"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_missing", "未识别到审查对象，无法检查 {label}").format(label=label),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_missing", ""),
                )
            )
            return issues
        if not isinstance(items, list):
            return issues
        for target in targets:
            matched = next(
                (it for it in items if isinstance(it, dict) and str(it.get(match_by) or "") == target),
                None,
            )
            if matched is None:
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type_missing", "expect_missing"),
                        severity=_severity(check, default_sev),
                        desc=check.get("msg_notfound", "未找到 {target} 的 {label} 数据").format(target=target, label=label),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion_missing", ""),
                        drawing_no=target,
                    )
                )
                continue
            actual = str(matched.get(field) or "")
            if not ops.expect(actual, expected):
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "expect_mismatch"),
                        severity=_severity(check, default_sev),
                        desc=check.get("msg", "{target} {label}为 {actual}，应为 {expected}").format(
                            target=target, label=label, actual=actual or "空", expected=expected
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=target,
                    )
                )
        return issues

    if op == "seq_audit":
        source = str(check.get("items") or "")
        container = source.split(".")[0] if "." in source else source
        book = _get(artifacts, container)
        if not isinstance(book, dict) or book.get("_stub"):
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_error", "tool_error"),
                    severity="high",
                    desc=check.get("msg_error") or f"{container} 数据缺失，无法检查页号",
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_error", ""),
                )
            )
            return issues
        # 一份工件里可能有多个 PID 文件，各自成册、各自审计
        books = book.get("files")
        books = [b for b in books if isinstance(b, dict)] if isinstance(books, list) else []
        if not books:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_missing", "pid_not_found"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_missing", "未识别到审查对象，无法检查页号"),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_missing", ""),
                )
            )
            return issues
        for entry in books:
            target = str(entry.get("file") or "").strip()
            errors = [str(e) for e in (entry.get("errors") or [])]
            if errors:
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type_error", "tool_error"),
                        severity="medium",
                        desc=(check.get("msg_error") or f"{target} 以下页信息抽取失败：{'；'.join(errors)}"),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion_error", ""),
                        drawing_no=target,
                    )
                )
            items = entry.get("items")
            items = items if isinstance(items, list) else []
            if not items:
                if not errors and int(entry.get("pages_total") or 0) > 0:
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type=check.get("type_error", "tool_error"),
                            severity="high",
                            desc=check.get("msg_error") or f"{target} 各页均未抽出页号，无法检查连续性",
                            basis=skill.get("basis", ""),
                            suggestion=check.get("suggestion_error", ""),
                            drawing_no=target,
                        )
                    )
                continue
            diffs = ops.seq_audit(
                items=items,
                field=str(check.get("field") or "sheet_no"),
                # 不注入默认分隔符：审查规则没配时由算子走「最右数字串」默认规则。
                separators=list(check.get("separators") or []),
                group_by=str(check.get("group_by") or "shape"),
                start_page=int(check.get("start_page") or 1),
                step=int(check.get("step") or 1),
                parity=str(check.get("parity") or "any"),
                total_field=str(check.get("total_field") or ""),
                actual_total=entry.get("pages_total"),
            )
            for diff in diffs:
                kind = str(diff.get("type") or "")
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get(_SEQ_TYPE_KEYS.get(kind, f"{kind}_type")) or kind,
                        severity=diff.get("severity") or _severity(check, default_sev),
                        desc=_seq_msg(check, kind, diff),
                        basis=skill.get("basis", ""),
                        suggestion=diff.get("suggestion") or check.get("suggestion", ""),
                        drawing_no=target,
                    )
                )
        return issues

    if op == "llm_judge":
        # 语义类判定（错别字等）。模型只在这里被调用一次/文件；白名单、阈值、范围全在 YAML。
        from ai.agents.skill_loader import load_resource

        source = str(check.get("items") or "notes.files")
        container = source.split(".")[0]
        book = _get(artifacts, container)
        if not isinstance(book, dict) or book.get("_stub"):
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_error", "tool_error"),
                    severity="high",
                    desc=check.get("msg_error_missing") or f"{container} 数据缺失，无法进行判定",
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_error", ""),
                )
            )
            return issues
        files = _get(artifacts, source)
        files = [f for f in files if isinstance(f, dict)] if isinstance(files, list) else []
        if not files:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_missing", "target_not_found"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_missing", "未识别到审查对象，无法进行判定"),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_missing", ""),
                )
            )
            return issues
        # 抽取阶段的失败（找不到说明栏、抄写失败）也要让人看见，不能静默吞掉。
        for entry in files:
            errors = [str(e) for e in (entry.get("errors") or [])]
            if errors:
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type_error", "tool_error"),
                        severity="medium",
                        desc=(check.get("msg_extract_error") or "{drawing_no} 说明栏抽取存在失败：{errors}").format(
                            drawing_no=entry.get("drawing_no") or entry.get("file") or "",
                            file=entry.get("file") or "",
                            errors="；".join(errors),
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion_error", ""),
                        drawing_no=str(entry.get("drawing_no") or ""),
                    )
                )
        glossary = load_resource(str(check.get("glossary") or "")) if check.get("glossary") else None
        diffs = ops.llm_judge(
            files=files,
            prompt_id=str(check.get("prompt") or ""),
            glossary=glossary if isinstance(glossary, dict) else None,
            min_confidence=float(check.get("min_confidence") or 0.7),
            kinds=list(check.get("kinds") or []),
        )
        for diff in diffs:
            kind = str(diff.get("type") or "")
            if kind == "tool_error":
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type_error", "tool_error"),
                        severity="medium",
                        desc=(check.get("msg_error") or "{drawing_no} 判定失败：{desc}").format(
                            drawing_no=diff.get("drawing_no") or diff.get("file") or "", **{k: v for k, v in diff.items() if k != "drawing_no"}
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion_error", ""),
                        drawing_no=str(diff.get("drawing_no") or ""),
                    )
                )
                continue
            bbox = diff.get("bbox") if isinstance(diff.get("bbox"), list) and len(diff.get("bbox")) == 4 else None
            shown = {**diff, "drawing_no": diff.get("drawing_no") or diff.get("file") or ""}
            template = check.get("msg") or "{drawing_no} 说明第{no}条疑似错别字：「{wrong}」→「{correct}」"
            try:
                desc = template.format(**shown)
            except (KeyError, IndexError, ValueError):
                desc = f"{shown['drawing_no']} 疑似错别字：「{diff.get('wrong')}」→「{diff.get('correct')}」"
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "llm_judge"),
                    severity=_severity(check, default_sev),
                    desc=desc,
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                    drawing_no=str(diff.get("drawing_no") or ""),
                    x=round((bbox[0] + bbox[2]) / 2, 1) if bbox else None,
                    y=round((bbox[1] + bbox[3]) / 2, 1) if bbox else None,
                    confidence=float(diff.get("confidence") or 0.0),
                )
            )
        return issues

    if op == "revision_uniform":
        items = _get(artifacts, check["items"])
        if not isinstance(items, list):
            return issues
        for prefix, desc in ops.revision_conflicts(items):
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "revision_mismatch"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "{desc}").format(prefix=prefix, desc=desc),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                    drawing_no=prefix,
                )
            )
        return issues

    if op == "file_prefix":
        values = [ops.file_no_prefix(item) for item in _as_list(_get(artifacts, check["field"]))]
        values = [item for item in values if item]
        ok, uniq = ops.eq_all(values)
        if not ok:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "file_prefix_mismatch"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "图号前缀不一致：{items}").format(items="、".join(sorted(uniq))),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                )
            )
        return issues

    if op == "sheet_count":
        items = _get(artifacts, check["items"])
        if not isinstance(items, list):
            return issues
        groups: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            number = str(item.get("文件号") or item.get("drawing_no") or "")
            prefix = ops.file_no_prefix(number) or number or str(item.get("file") or "")
            groups.setdefault(prefix, []).append(item)
        for prefix, group in groups.items():
            actual = len(group)
            declared_values = {ops.sheet_count_of(str(item.get("张数") or "")) for item in group}
            declared_values.discard(None)
            drawing_no = prefix
            if not declared_values:
                continue
            if len(declared_values) > 1 or actual not in declared_values:
                shown = "、".join(str(item) for item in sorted(declared_values))
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "sheet_count_mismatch"),
                        severity=_severity(check, default_sev),
                        desc=check.get("msg", "{drawing_no} 标题栏共 {declared} 张，实际 {actual} 张").format(
                            drawing_no=drawing_no, declared=shown, actual=actual
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=drawing_no,
                    )
                )
        return issues

    if op == "survey_cert":
        items = _get(artifacts, check["items"])
        if not isinstance(items, list):
            return issues
        for item in items:
            if not isinstance(item, dict):
                continue
            problem = ops.survey_cert_problem(
                str(item.get("设计证书号") or ""),
                str(item.get("勘察证书号") or ""),
                str(item.get("专业") or ""),
                _certs(check),
            )
            if not problem:
                continue
            drawing_no = str(item.get("drawing_no") or "")
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "survey_cert_error"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "{drawing_no} 勘察证书号{problem}").format(
                        drawing_no=drawing_no, problem=problem
                    ),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                    drawing_no=drawing_no,
                )
            )
        return issues

    if op == "field_format":
        items = _get(artifacts, check["items"])
        fields = [str(name) for name in (check.get("fields") or [])]
        if not isinstance(items, list):
            return issues
        for item in items:
            if not isinstance(item, dict):
                continue
            drawing_no = str(item.get("drawing_no") or "")
            certs = _certs(check)
            discipline = str(item.get("专业") or "")
            for name in fields:
                problem = ops.field_format_problem(name, str(item.get(name) or ""), discipline, certs)
                if not problem:
                    continue
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "field_format"),
                        severity=_severity(check, default_sev),
                        desc=check.get("msg", "{drawing_no} {field}{problem}").format(
                            drawing_no=drawing_no, field=name, problem=problem
                        ),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=drawing_no,
                    )
                )
            drawing_name = str(item.get("图纸名称") or "").strip()
            project_name = str(item.get("项目名称") or "").strip()
            if drawing_name and project_name and ops.norm_space(drawing_name) == ops.norm_space(project_name):
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "field_format"),
                        severity=_severity(check, default_sev),
                        desc=f"{drawing_no} 图纸名称与项目名称相同",
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=drawing_no,
                    )
                )
        return issues

    if op == "notes_format":
        files = _get(artifacts, check.get("items") or "notes.files")
        if not isinstance(files, list):
            return issues
        for book in files:
            if not isinstance(book, dict):
                continue
            drawing_no = str(book.get("drawing_no") or "")
            for block in book.get("items") or []:
                if not isinstance(block, dict):
                    continue
                for line in block.get("lines") or []:
                    if not isinstance(line, dict):
                        continue
                    text = str(line.get("text") or "")
                    for wrong, correct in ops.unit_format_hits(text):
                        issues.append(
                            make_issue(
                                skill_id=skill_id,
                                issue_type=check.get("type", "notes_format"),
                                severity=_severity(check, default_sev),
                                desc=check.get("msg", "{drawing_no} 说明「{wrong}」应为「{correct}」").format(
                                    drawing_no=drawing_no, wrong=wrong, correct=correct, text=text
                                ),
                                basis=skill.get("basis", ""),
                                suggestion=check.get("suggestion", ""),
                                drawing_no=drawing_no,
                            )
                        )
        return issues

    if op == "catalog_files":
        folder = str(_get(artifacts, "review_folder") or "")
        has_catalog = False
        root = Path(folder) if folder else None
        if root is not None and root.is_dir():
            has_catalog = any(path.is_file() and "目录" in path.name for path in root.iterdir())
        catalog_numbers: list[str] = []
        if has_catalog and root is not None:
            catalog_numbers = _catalog_file_numbers(root)
            drawing_numbers = []
            rows = _get(artifacts, check.get("items") or "frame_rows.items")
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict) and str(row.get("文件号") or "").strip():
                        drawing_numbers.append(str(row.get("文件号")).strip())
            if catalog_numbers:
                missing, extra = ops.set_diff(catalog_numbers, drawing_numbers)
                if missing:
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type="catalog_missing_drawing",
                            severity=_severity(check, default_sev),
                            desc=f"目录有、文件夹无：{'、'.join(sorted(missing))}",
                            basis=skill.get("basis", ""),
                            suggestion="补图或改正目录",
                        )
                    )
                if extra:
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type="catalog_extra_drawing",
                            severity=_severity(check, default_sev),
                            desc=f"文件夹有、目录无：{'、'.join(sorted(extra))}",
                            basis=skill.get("basis", ""),
                            suggestion="补目录或剔除多余图纸",
                        )
                    )
            else:
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type_missing", "catalog_missing"),
                        severity=_severity(check, default_sev),
                        desc="目录文件未能抽出文件号，不能核对缺图、多图",
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                    )
                )
        elif not has_catalog:
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type_missing", "catalog_missing"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg_missing", "文件夹里没有目录，不能核对缺图、多图"),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion", ""),
                )
            )
        grouped: dict[str, set[str]] = {}
        items = _get(artifacts, check.get("items") or "frame_rows.items")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                number = str(item.get("文件号") or "").strip()
                title = str(item.get("图纸名称") or "").strip()
                revision = str(item.get("版次") or "").strip()
                if not number:
                    continue
                grouped.setdefault(number, set()).add(f"{title}|{revision}")
        for number, variants in grouped.items():
            if len(variants) <= 1:
                continue
            issues.append(
                make_issue(
                    skill_id=skill_id,
                    issue_type=check.get("type", "version_mix"),
                    severity=_severity(check, default_sev),
                    desc=check.get("msg", "{drawing_no} 同一文件号对应多个名称或版次").format(drawing_no=number),
                    basis=skill.get("basis", ""),
                    suggestion=check.get("suggestion_mix", "核对是否版本混用"),
                    drawing_no=number,
                )
            )
        return issues

    if op == "sign_conflict":
        items = _get(artifacts, check["items"])
        pairs = check.get("pairs") or [["设计", "校对"], ["设计", "审核"], ["校对", "审核"]]
        if not isinstance(items, list):
            return issues
        for item in items:
            if not isinstance(item, dict):
                continue
            drawing_no = str(item.get("drawing_no") or "")
            for pair in pairs:
                if not isinstance(pair, list) or len(pair) != 2:
                    continue
                left, right = str(pair[0]), str(pair[1])
                left_value = str(item.get(left) or "").strip()
                right_value = str(item.get(right) or "").strip()
                if left_value and right_value and left_value == right_value:
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type=check.get("type", "sign_conflict"),
                            severity=_severity(check, default_sev),
                            desc=check.get("msg", "{drawing_no} {left}与{right}同为「{value}」").format(
                                drawing_no=drawing_no, left=left, right=right, value=left_value
                            ),
                            basis=skill.get("basis", ""),
                            suggestion=check.get("suggestion", ""),
                            drawing_no=drawing_no,
                        )
                    )
        return issues

    if op == "frame_overflow":
        from ai.tools.frame_overflow import check_page

        drawing = artifacts.get("drawing_json") if isinstance(artifacts.get("drawing_json"), dict) else {}
        for book in drawing.get("files") or []:
            if not isinstance(book, dict):
                continue
            file_name = str(book.get("file") or "")
            for page in book.get("pages") or []:
                if not isinstance(page, dict):
                    continue
                image = str(page.get("metadata_png") or "")
                reserved: list[tuple[str, str]] = []
                for label, block_name in (("说明", "notes"), ("表格", "chart"), ("图框", "frame")):
                    block = page.get(block_name) if isinstance(page.get(block_name), dict) else {}
                    for raw in block.get("paths") or []:
                        reserved.append((label, str(raw)))
                fields = (page.get("frame") or {}).get("fields") if isinstance(page.get("frame"), dict) else []
                drawing_no = ""
                if isinstance(fields, list):
                    for found in fields:
                        if isinstance(found, dict) and str(found.get("文件号") or "").strip():
                            drawing_no = str(found.get("文件号")).strip()
                            break
                if not drawing_no:
                    drawing_no = file_name
                result = check_page(image, reserved) if image else {"ok": False, "error": "没有页图", "zones": []}
                page_no = page.get("page") or ""
                if not result.get("ok"):
                    issues.append(
                        make_issue(
                            skill_id=skill_id,
                            issue_type=check.get("type_error", "frame_overflow_error"),
                            severity="medium",
                            desc=f"{drawing_no} 第{page_no}页未能检查超图框：{result.get('error') or '失败'}",
                            basis=skill.get("basis", ""),
                            suggestion="确认页图和图框线清晰后重跑",
                            drawing_no=drawing_no,
                        )
                    )
                    continue
                zones = [str(name) for name in (result.get("zones") or [])]
                if not zones:
                    continue
                template = check.get("msg") or "{drawing_no} 第{page}页工艺图线超出绘图区，进入{where}"
                issues.append(
                    make_issue(
                        skill_id=skill_id,
                        issue_type=check.get("type", "frame_overflow"),
                        severity=_severity(check, default_sev),
                        desc=template.format(drawing_no=drawing_no, page=page_no, where="、".join(zones)),
                        basis=skill.get("basis", ""),
                        suggestion=check.get("suggestion", ""),
                        drawing_no=drawing_no,
                    )
                )
        return issues

    issues.append(
        make_issue(
            skill_id=skill_id,
            issue_type="unsupported_op",
            severity="low",
            desc=f"未登记算子 {op}，请向平台申请加入 operators.py",
        )
    )
    return issues


def review(state: dict[str, Any]) -> dict[str, Any]:
    artifacts = state.get("artifacts") or {}
    selected = state.get("skill_ids") or []
    skills = list_skills(include_disabled=False)
    if selected:
        skills = [s for s in skills if s.get("id") in selected]

    issues: list[dict[str, Any]] = []
    logs = list(state.get("logs") or [])
    for skill in skills:
        sid = skill.get("id")
        if artifacts and any(
            isinstance(artifacts.get(n), dict) and artifacts[n].get("_stub") for n in (skill.get("needs") or [])
        ):
            logs.append(f"skip {sid}: needs 仍为 stub，等算法组实现抽取工具")
            continue
        for check in skill.get("checks") or []:
            issues.extend(run_check(skill, check, artifacts))
        logs.append(f"reviewed {sid}")
    return {"issues": issues, "logs": logs}

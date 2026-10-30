"""doc/docx 转 PNG。只渲第一页，页眉会印在这一页上。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ai.config import PDF_DPI
from ai.tools.paper import measure_page
from ai.tools.registry import register
from ai.tools.word_doc import close, launch

WD_EXPORT_PDF = 17
WD_EXPORT_FROM_TO = 3


def _is_windows() -> bool:
    import sys

    return sys.platform.startswith("win")


def _find_soffice() -> str | None:
    import os
    import shutil

    configured = os.getenv("SOFFICE_BIN")
    if configured and Path(configured).is_file():
        return configured
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    return None


def _word_to_pdf_soffice(src: Path, dest: Path, pdf_path: Path) -> None:
    """非 Windows 用 LibreOffice 无头模式把 doc/docx 转 PDF。"""
    import subprocess

    exe = _find_soffice()
    if not exe:
        raise RuntimeError("未找到 LibreOffice(soffice)，非 Windows 环境需先安装 LibreOffice 或设置 SOFFICE_BIN")
    profile = dest / "soffice-profile"
    subprocess.run(
        [
            exe,
            f"-env:UserInstallation=file://{profile}",
            "--headless",
            "--norestore",
            "--convert-to",
            "pdf",
            "--outdir",
            str(dest),
            str(src),
        ],
        check=True,
        capture_output=True,
        timeout=300,
    )
    produced = dest / f"{src.stem}.pdf"
    if not produced.is_file():
        raise RuntimeError(f"LibreOffice 未生成 PDF：{src.name}")
    if produced != pdf_path:
        produced.replace(pdf_path)


def render_word(path: str | Path, out_dir: str | Path, dpi: int = PDF_DPI, app=None) -> dict[str, Any]:
    """把 Word 第一页渲成 PNG。返回图像路径。"""
    import fitz

    src = Path(path)
    if src.suffix.lower() not in {".doc", ".docx"}:
        return {"ok": False, "image": "", "error": f"不是 Word 文件：{src.name}"}
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    pdf_path = dest / f"{src.stem}-p1.pdf"
    png_path = dest / f"{src.stem}-p1.png"
    use_word = app is not None or _is_windows()
    own = app is None
    word = app or (launch() if use_word else None)
    try:
        if use_word:
            doc = word.Documents.Open(str(src.resolve()), ReadOnly=True)
            try:
                doc.ExportAsFixedFormat(
                    str(pdf_path.resolve()),
                    WD_EXPORT_PDF,
                    False,
                    0,
                    WD_EXPORT_FROM_TO,
                    1,
                    1,
                )
            finally:
                doc.Close(False)
        else:
            _word_to_pdf_soffice(src, dest, pdf_path)
        pdf = fitz.open(pdf_path)
        try:
            if pdf.page_count < 1:
                return {"ok": False, "image": "", "error": "导出的第一页是空的"}
            page = pdf[0]
            paper = measure_page(page)
            pix = page.get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
            pix.save(str(png_path))
        finally:
            pdf.close()
    except Exception as exc:
        return {"ok": False, "image": "", "error": str(exc)}
    finally:
        if own and word is not None:
            close(word)
        if pdf_path.exists():
            pdf_path.unlink()
    if not png_path.is_file():
        return {"ok": False, "image": "", "error": "没有生成 PNG"}
    return {"ok": True, "image": str(png_path), "paper": paper, "dpi": dpi, "error": ""}


@register("doc.to_png", produces=["png"])
def run(files: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, Any]:
    dpi = int(artifacts.get("pdf_dpi") or PDF_DPI)
    out_dir = Path(artifacts.get("work_dir") or "data/work") / "png"
    items = []
    for item in files:
        name = item.get("name") or ""
        path = item.get("path") or ""
        if Path(name).suffix.lower() not in {".doc", ".docx"} or not path:
            continue
        rendered = render_word(path, out_dir, dpi=dpi)
        items.append({"name": name, "path": path, **rendered})
    return {"png": {"items": items, "dpi": dpi}}

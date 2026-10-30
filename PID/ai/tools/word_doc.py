"""用本机 Word 打开 .doc / .docx。转 PNG 时复用这里启动的 Word 进程。"""

from __future__ import annotations

from pathlib import Path

WD_FORMAT_DOCX = 16


def launch():
    import sys

    if not sys.platform.startswith("win"):
        return None
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    app = win32com.client.Dispatch("Word.Application")
    app.Visible = False
    app.DisplayAlerts = 0
    return app


def close(app) -> None:
    if app is not None:
        app.Quit()


def to_docx(path: str | Path, out_dir: str | Path, app=None) -> Path:
    """`.docx` 原样返回。`.doc` 另存为 docx，正文和页眉都留在文件里。"""
    src = Path(path)
    suffix = src.suffix.lower()
    if suffix == ".docx":
        return src
    if suffix != ".doc":
        raise ValueError(f"不是 Word 文件：{src.name}")
    dest_dir = Path(out_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{src.stem}.docx"
    own = app is None
    word = app or launch()
    doc = word.Documents.Open(str(src.resolve()), ReadOnly=True)
    try:
        doc.SaveAs2(str(dest.resolve()), FileFormat=WD_FORMAT_DOCX)
    finally:
        doc.Close(False)
        if own:
            close(word)
    return dest

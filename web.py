"""信创版 Harness Web 服务"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from harness import XinchangHarness
from model import LlamaServerModel

ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="信创版 Harness", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_model: LlamaServerModel | None = None


def get_model() -> LlamaServerModel:
    global _model
    if _model is None:
        _model = LlamaServerModel()
    return _model


class RunRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=4000)
    max_steps: int = Field(default=6, ge=1, le=12)


class RunResponse(BaseModel):
    answer: str
    steps: list[dict]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    model = get_model()
    return {
        "llama_server": model.base_url,
        "reachable": model.health_check(),
        "model": model.model,
    }


@app.get("/api/tools")
def list_tools() -> dict:
    harness = XinchangHarness(get_model())
    return {"tools": harness.tools}


@app.post("/api/run", response_model=RunResponse)
def run_task(body: RunRequest) -> RunResponse:
    harness = XinchangHarness(get_model())
    steps: list[dict] = []
    answer = "任务未完成"

    for event in harness.iter_run(body.task, max_steps=body.max_steps):
        steps.append(event)
        if event["event"] == "done":
            answer = event["answer"]
        elif event["event"] == "max_steps":
            answer = event["message"]

    return RunResponse(answer=answer, steps=steps)


@app.get("/api/run/stream")
def run_stream(task: str, max_steps: int = 6) -> StreamingResponse:
    if not task.strip():
        raise HTTPException(status_code=400, detail="task 不能为空")
    if max_steps < 1 or max_steps > 12:
        raise HTTPException(status_code=400, detail="max_steps 须在 1-20 之间")

    harness = XinchangHarness(get_model())

    def generate():
        try:
            for event in harness.iter_run(task.strip(), max_steps=max_steps):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
        except Exception as exc:  # noqa: BLE001
            err = {"event": "fatal", "message": str(exc)}
            yield f"data: {json.dumps(err, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def main() -> None:
    import uvicorn

    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8765"))
    print(f"Web 已启动: http://127.0.0.1:{port}  （Ctrl+C 可停止前台进程）", flush=True)
    uvicorn.run("web:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()

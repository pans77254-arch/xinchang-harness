from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ai.config import PREVIEW_DIR
from backend.app.routers import review, skills, tasks

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"

app = FastAPI(title="PID 图纸识别", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tasks.router, prefix="/api", tags=["tasks"])
app.include_router(review.router, prefix="/api", tags=["review"])
app.include_router(skills.router, prefix="/api", tags=["skills"])


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")


# 预处理预览图先挂，路径更具体，必须排在 /static 之前，否则会被 /static 拦下。
PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static/previews", StaticFiles(directory=PREVIEW_DIR), name="previews")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

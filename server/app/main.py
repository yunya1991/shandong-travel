"""AI 旅行手册 · FastAPI 主入口

启动方式：
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

或：
    bash server/run.sh

云端部署（Task 23+ 部署增强）：
    设置 TG_STATIC_DIR=/app/static 时，FastAPI 会把前端静态文件挂载到 /，
    单进程同时提供 API（/api/*、/plan/*、/ws/*）和前端页面。
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from . import plan_store
from . import routes

# 加载 .env
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    load_dotenv(_env_path)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动：初始化 SQLite
    plan_store.init_db()
    yield
    # 关闭：清理资源（v1 无后台任务需特殊清理）


def create_app() -> FastAPI:
    app = FastAPI(
        title="AI 旅行手册 后端",
        description="攻略碎片化 → 可执行行程的转换引擎 · DSH 驱动",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS（前端静态服务地址）
    origins = [
        o.strip() for o in os.environ.get(
            "FRONTEND_ORIGIN", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",") if o.strip()
    ]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins + ["*"],  # 本机调试放开 *，README 注明生产收紧
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.router)

    # 云端部署：挂载前端静态文件（Task 23+ 部署增强）
    # 仅当 TG_STATIC_DIR 指向真实目录时启用，避免本地开发模式误挂载
    static_dir_env = os.environ.get("TG_STATIC_DIR", "")
    if static_dir_env:
        static_dir = Path(static_dir_env)
        if static_dir.is_dir():
            # /assets/* 等静态资源
            app.mount("/static", StaticFiles(directory=static_dir), name="static")
            # SPA fallback：根路径 / 返回 index.html
            index_html = static_dir / "index.html"

            @app.get("/", include_in_schema=False)
            async def _spa_root():
                if index_html.exists():
                    return FileResponse(index_html)
                return JSONResponse({"name": "AI 旅行手册", "status": "ok"})
            # 兜底：未匹配的路径返回 index.html（SPA 路由）
            @app.get("/{full_path:path}", include_in_schema=False)
            async def _spa_fallback(full_path: str):
                # API 路径不走 SPA fallback（让 FastAPI 返回 404 JSON）
                if full_path.startswith(("api/", "plan/", "ws/", "static/", "health")):
                    return JSONResponse({"detail": "Not Found"}, status_code=404)
                candidate = static_dir / full_path
                if candidate.is_file():
                    return FileResponse(candidate)
                if index_html.exists():
                    return FileResponse(index_html)
                return JSONResponse({"detail": "Not Found"}, status_code=404)
    return app


app = create_app()

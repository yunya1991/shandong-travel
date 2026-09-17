"""AI 旅行手册 · FastAPI 主入口

启动方式：
    uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

或：
    bash server/run.sh
"""
from __future__ import annotations
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return app


app = create_app()

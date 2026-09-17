"""HTTP / WebSocket 路由

对应 spec FR-13、FR-23、FR-25、FR-27~33、AC-9~15。
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from . import dsh_runner
from . import plan_store
from . import traj
from . import monitor
from .llm_client import chat_completion, generate_plan_via_llm

router = APIRouter()

# WebSocket 订阅者：plan_id -> [WebSocket]
_ws_subs: Dict[str, list] = {}


def _llm_config_from_headers(x_llm_config: Optional[str], env_fallback: bool = True):
    """从前端 X-LLM-Config header 解析 LLM 配置（仅本次请求，不持久化）。"""
    if x_llm_config:
        try:
            cfg = json.loads(x_llm_config)
            base_url = cfg.get("base_url") or os.environ.get("LLM_BASE_URL", "")
            api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
            model = cfg.get("model") or os.environ.get("LLM_MODEL", "deepseek-chat")
            return {"base_url": base_url, "api_key": api_key, "model": model}
        except json.JSONDecodeError:
            pass
    if env_fallback:
        return {
            "base_url": os.environ.get("LLM_BASE_URL", "https://api.deepseek.com"),
            "api_key": os.environ.get("LLM_API_KEY", ""),
            "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
        }
    return None


@router.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "dsh": "ready" if dsh_runner.dsh_available() else "fallback",
        "ts": time.time(),
    })


@router.post("/llm-proxy")
async def llm_proxy(request: Request, x_llm_config: Optional[str] = Header(None, alias="X-LLM-Config")):
    """等价于根目录 proxy.py 的 CORS 转发。"""
    body = await request.json()
    cfg = _llm_config_from_headers(x_llm_config)
    messages = body.get("messages") or []
    max_tokens = body.get("max_tokens", 8192)
    temperature = body.get("temperature", 0.4)
    try:
        res = await chat_completion(
            messages,
            base_url=cfg["base_url"], api_key=cfg["api_key"], model=cfg["model"],
            max_tokens=max_tokens, temperature=temperature,
            response_format_json=body.get("response_format", {}).get("type") == "json_object",
        )
        return JSONResponse(res)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=502)


@router.post("/generate")
async def generate(request: Request, x_llm_config: Optional[str] = Header(None, alias="X-LLM-Config")):
    """主入口：输入 destination + prefs → 输出 plan + sources + warnings + session_id。"""
    body = await request.json()
    destination = (body.get("destination") or "").strip()
    prefs = body.get("prefs") or {}
    materials = body.get("materials")  # 用户粘贴路径会带 materials
    if not destination:
        raise HTTPException(status_code=400, detail="destination required")

    cfg = _llm_config_from_headers(x_llm_config)
    if not cfg.get("api_key"):
        raise HTTPException(status_code=400, detail="api_key missing in X-LLM-Config header")

    session_id = traj.new_session_id()
    try:
        result = await dsh_runner.run_pipeline(
            destination, prefs,
            base_url=cfg["base_url"], api_key=cfg["api_key"], model=cfg["model"],
            materials=materials, session_id=session_id,
        )
    except Exception as e:
        traj.append(session_id, "pipeline.error", {"msg": str(e)})
        # 降级：直接用 LLM 生成
        try:
            plan = await generate_plan_via_llm(
                destination, prefs,
                base_url=cfg["base_url"], api_key=cfg["api_key"], model=cfg["model"],
                materials=materials or [],
            )
            from .schema import make_response, _source_coverage
            result = make_response(plan, [], [
                {"level": "high", "field": "pipeline", "msg": f"降级为纯 LLM 模式: {e}"},
            ], session_id)
        except Exception as e2:
            raise HTTPException(status_code=500, detail=f"pipeline failed: {e2}")

    # 持久化 plan 与版本
    plan_id = body.get("plan_id") or f"plan_{int(time.time()*1000)}"
    plan_store.save_plan(plan_id, session_id, destination, prefs)
    version_id = plan_store.save_version(
        plan_id, result["plan"],
        trigger_reason="initial_generate",
        adopted=True,
    )
    result["plan_id"] = plan_id
    result["version_id"] = version_id
    return JSONResponse(result)


@router.post("/scrape")
async def scrape_endpoint(request: Request):
    """单独触发抓取（调试用）。body: {tasks: [...]}"""
    body = await request.json()
    tasks = body.get("tasks") or []
    if not tasks:
        raise HTTPException(status_code=400, detail="tasks required")
    from . import scraper
    res = await scraper.batch(tasks)
    return JSONResponse(res)


@router.get("/sessions")
async def list_sessions(limit: int = 50):
    """列出最近 N 个 session（前端调试视图选择用，AC-12 / NFR-9）。"""
    return JSONResponse({"sessions": traj.list_sessions(limit=limit)})


@router.get("/trajectory/{session_id}")
async def get_trajectory(session_id: str):
    events = traj.read(session_id)
    return JSONResponse({"session_id": session_id, "events": events, "count": len(events)})


@router.post("/trajectory/replay/{session_id}")
async def replay_trajectory(session_id: str):
    """重放历史轨迹。v1 仅返回原轨迹事件供前端再渲染，不真正重新执行 LLM。"""
    events = traj.read(session_id)
    new_session = traj.new_session_id()
    for e in events:
        traj.append(new_session, e.get("type", "replayed"), e.get("payload", {}))
    return JSONResponse({"new_session_id": new_session, "replayed_count": len(events)})


@router.post("/plugin/reload")
async def plugin_reload(request: Request):
    """v1 仅手动实验：标记 reload 事件，不真正重装（避免 DSH SDK 未就绪时崩溃）。"""
    body = await request.json()
    plugin = body.get("plugin")
    if not plugin:
        raise HTTPException(status_code=400, detail="plugin required")
    # 记录到 traj 全局 session
    sess = traj.new_session_id()
    traj.append(sess, "plugin.reloaded", {
        "plugin": plugin,
        "bundle_path": body.get("bundle_path", ""),
        "ts": time.time(),
    })
    return JSONResponse({
        "status": "reloaded",
        "plugin": plugin,
        "note": "v1 stub: actual reload requires DSH SDK; event logged for replay",
    })


@router.get("/plan/{plan_id}/versions")
async def list_versions(plan_id: str):
    return JSONResponse({"plan_id": plan_id, "versions": plan_store.list_versions(plan_id)})


@router.get("/plan/{plan_id}/version/{version_id}")
async def get_version(plan_id: str, version_id: str):
    v = plan_store.get_version(version_id)
    if not v or v["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="version not found")
    return JSONResponse(v)


@router.post("/plan/{plan_id}/revert/{version_id}")
async def revert_plan(plan_id: str, version_id: str):
    v = plan_store.get_version(version_id)
    if not v or v["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="version not found")
    # 把目标版本标记为 adopted，其它同 plan 的版本置为非 adopted
    # 由于 schema 限制，v1 简化为：插入一条 adopted=1 的新版本快照
    new_vid = plan_store.save_version(
        plan_id, v["plan"],
        parent_version_id=version_id,
        trigger_reason=f"revert_to_{version_id}",
        diff=[{"op": "REVERT", "target_version": version_id}],
        adopted=True,
    )
    return JSONResponse({
        "plan_id": plan_id, "new_version_id": new_vid,
        "plan": v["plan"], "reverted_from": version_id,
    })


@router.post("/plan/{plan_id}/monitor/start")
async def start_monitor(plan_id: str, request: Request, x_llm_config: Optional[str] = Header(None, alias="X-LLM-Config")):
    body = await request.json()
    destination = body.get("destination", "")
    departure_date = body.get("departure_date")
    whitelist = body.get("whitelist") or []
    if not destination:
        raise HTTPException(status_code=400, detail="destination required")
    cfg = _llm_config_from_headers(x_llm_config, env_fallback=False)
    # 从最新 adopted 版本取快照
    vid = plan_store.latest_version_id(plan_id)
    plan_snapshot = plan_store.get_version(vid)["plan"] if vid else None
    sess = traj.new_session_id()
    monitor.start_monitor_loop(
        plan_id, destination, departure_date, sess,
        llm_cfg=cfg, plan_snapshot=plan_snapshot, whitelist=whitelist,
    )
    return JSONResponse({
        "status": "started", "plan_id": plan_id, "session_id": sess,
        "llm_configured": bool(cfg and cfg.get("api_key")),
        "plan_snapshot_loaded": plan_snapshot is not None,
    })


@router.post("/plan/{plan_id}/monitor/stop")
async def stop_monitor(plan_id: str):
    monitor.stop_monitor_loop(plan_id)
    return JSONResponse({"status": "stopped", "plan_id": plan_id})


@router.post("/plan/{plan_id}/optimize")
async def manual_optimize(plan_id: str, request: Request, x_llm_config: Optional[str] = Header(None, alias="X-LLM-Config")):
    """手动触发一次 monitor + optimize，并立即返回 diff（不等待后台周期）。"""
    body = await request.json()
    destination = body.get("destination", "")
    whitelist = body.get("whitelist") or []
    if not destination:
        raise HTTPException(status_code=400, detail="destination required")
    cfg = _llm_config_from_headers(x_llm_config)
    if not cfg.get("api_key"):
        raise HTTPException(status_code=400, detail="api_key missing in X-LLM-Config header")
    vid = plan_store.latest_version_id(plan_id)
    if not vid:
        raise HTTPException(status_code=404, detail="plan_id has no adopted version")
    plan = plan_store.get_version(vid)["plan"]
    sess = traj.new_session_id()
    monitor_data = await monitor.monitor_once(plan_id, destination, body.get("departure_date"), sess)
    from . import dsh_runner
    result = await dsh_runner.optimize_with_monitor_data(
        plan_id, plan, monitor_data,
        base_url=cfg["base_url"], api_key=cfg["api_key"], model=cfg["model"],
        whitelist=whitelist, session_id=sess,
    )
    if result.get("applied_count", 0) > 0:
        monitor.update_plan_snapshot(plan_id, result["plan"])
    return JSONResponse(result)


# ====== WebSocket：动态优化 diff 推送（对应 FR-29） ======
@router.websocket("/ws/plan/{plan_id}")
async def ws_plan(websocket: WebSocket, plan_id: str):
    """订阅 plan_id 的动态更新推送。"""
    await websocket.accept()
    _ws_subs.setdefault(plan_id, []).append(websocket)
    try:
        while True:
            # v1：仅维持连接，接收前端 user_edit 事件
            msg = await websocket.receive_text()
            try:
                data = json.loads(msg)
            except json.JSONDecodeError:
                continue
            if data.get("type") == "user_edit":
                # 协同冲突解决（FR-33）：记录时间戳供 optimizer 查询
                traj.append(data.get("session_id", "ws"), "user.edit", {
                    "plan_id": plan_id, "field": data.get("field"),
                    "ts": time.time(),
                })
                # 同步 monitor 快照（如用户拉了景点顺序，下一次优化基于新版本）
                if data.get("plan"):
                    monitor.update_plan_snapshot(plan_id, data["plan"])
    except WebSocketDisconnect:
        pass
    finally:
        if plan_id in _ws_subs and websocket in _ws_subs[plan_id]:
            _ws_subs[plan_id].remove(websocket)


async def broadcast_diff(plan_id: str, diff_payload: Dict[str, Any]) -> None:
    """向某 plan_id 的所有订阅者推送 diff。"""
    subs = _ws_subs.get(plan_id, [])
    dead = []
    for ws in subs:
        try:
            await ws.send_text(json.dumps(diff_payload, ensure_ascii=False))
        except Exception:
            dead.append(ws)
    for ws in dead:
        subs.remove(ws)

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


@router.get("/plan/{plan_id}/changelog")
async def get_changelog(plan_id: str):
    """聚合 changelog（Task 23 / 跨 session 重启后不丢）。

    从 plan_versions 表读取所有版本（按时间倒序），合并 diff 与 trigger_reason
    作为可读 changelog。前端 mountDynamicControls 启动时拉取以恢复徽章计数与抽屉内容。
    """
    versions = plan_store.list_versions(plan_id, limit=200)
    items = []
    for v in versions:
        diff = v.get("diff") or []
        try:
            if isinstance(diff, str):
                diff = json.loads(diff)
        except Exception:
            diff = []
        reason = v.get("trigger_reason") or ""
        ts = v.get("ts") or 0
        adopted = bool(v.get("adopted"))
        # 把 diff 多条展开为 changelog 多项
        if not diff:
            items.append({
                "ts": ts, "ts_iso": _iso(ts),
                "op": "INIT", "day": None, "target_field": None,
                "old_name": None, "new_name": None,
                "version_id": v.get("version_id"),
                "reason": reason, "adopted": adopted,
                "source_url": None,
            })
            continue
        for d in diff:
            ni = d.get("new_item") or {}
            oi = d.get("old_item") or {}
            items.append({
                "ts": ts, "ts_iso": _iso(ts),
                "op": d.get("op", "?"),
                "day": d.get("day"),
                "target_field": d.get("target_field"),
                "old_name": oi.get("name") if isinstance(oi, dict) else None,
                "new_name": ni.get("name") if isinstance(ni, dict) else None,
                "version_id": v.get("version_id"),
                "reason": d.get("reason", reason),
                "adopted": adopted,
                "source_url": ni.get("source_url") if isinstance(ni, dict) else None,
            })
    return JSONResponse({
        "plan_id": plan_id,
        "total_versions": len(versions),
        "items": items,
        "update_count": sum(1 for v in versions if (v.get("diff") or [])
                            and (v.get("trigger_reason") or "").startswith(("monitor_optimize", "cockpit_adopt", "manual_seed"))),
    })


@router.get("/plan/{plan_id}/diff_versions")
async def diff_versions(plan_id: str, from_id: str, to_id: str):
    """对比两个版本的差异（Task 23：跨版本对比 UI 用）。

    返回 {from, to, changes: [{day, field, from_item, to_item}]}
    仅对比 daily[].attractions/food/accommodation 三类；其它字段（overview 等）只做摘要。
    """
    fv = plan_store.get_version(from_id)
    tv = plan_store.get_version(to_id)
    if not fv or fv["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="from version not found")
    if not tv or tv["plan_id"] != plan_id:
        raise HTTPException(status_code=404, detail="to version not found")
    changes = _diff_plans(fv.get("plan") or {}, tv.get("plan") or {})
    return JSONResponse({
        "plan_id": plan_id,
        "from": {"version_id": from_id, "ts": fv.get("ts"), "ts_iso": _iso(fv.get("ts") or 0)},
        "to": {"version_id": to_id, "ts": tv.get("ts"), "ts_iso": _iso(tv.get("ts") or 0)},
        "changes": changes,
    })


def _iso(ts: float) -> str:
    """时间戳 → ISO 字符串（仅用于展示）。"""
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except Exception:
        return ""


def _diff_plans(a: Dict[str, Any], b: Dict[str, Any]) -> list:
    """对比两个 plan 的 daily 部分，输出字段级差异。"""
    a_days = {(d.get("day") or 0): d for d in (a.get("daily") or [])}
    b_days = {(d.get("day") or 0): d for d in (b.get("daily") or [])}
    changes = []
    all_days = sorted(set(a_days.keys()) | set(b_days.keys()))
    for day in all_days:
        ad = a_days.get(day, {})
        bd = b_days.get(day, {})
        for field in ("attractions", "food", "accommodation"):
            a_items = ad.get(field) or []
            b_items = bd.get(field) or []
            a_names = [it.get("name") for it in a_items if isinstance(it, dict)]
            b_names = [it.get("name") for it in b_items if isinstance(it, dict)]
            if a_names == b_names:
                continue
            changes.append({
                "day": day, "field": field,
                "from_items": a_names,
                "to_items": b_names,
                "added": [n for n in b_names if n not in a_names],
                "removed": [n for n in a_names if n not in b_names],
            })
    return changes


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
                    "day": data.get("day"),
                    "ts": time.time(),
                })
                # Task 23：调用 monitor.record_user_edit，让 _maybe_optimize 避让该 (day, field)
                monitor.record_user_edit(
                    plan_id, data.get("day"), data.get("field"),
                )
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


# ====== Task 22: DSH Web UI 驾驶舱（人机协同，AC-15 / FR-30 / NFR-12） ======
# 待采纳建议池：plan_id -> [suggestion_id, ...]
# 每条 suggestion: {suggestion_id, plan_id, session_id, diff, reason, source_url,
#                    monitor_data, created_ts, status: 'pending'|'adopted'|'rejected'|'edited'}
_pending_suggestions: Dict[str, list] = {}


def _new_suggestion_id() -> str:
    import uuid as _u
    return f"sug_{int(time.time()*1000)}_{_u.uuid4().hex[:6]}"


def _add_suggestion(plan_id: str, suggestion: Dict[str, Any]) -> str:
    sid = _new_suggestion_id()
    suggestion["suggestion_id"] = sid
    suggestion["plan_id"] = plan_id
    suggestion["created_ts"] = time.time()
    suggestion["status"] = "pending"
    _pending_suggestions.setdefault(plan_id, []).append(suggestion)
    return sid


def _find_suggestion(plan_id: str, suggestion_id: str) -> Optional[Dict[str, Any]]:
    for s in _pending_suggestions.get(plan_id, []):
        if s["suggestion_id"] == suggestion_id:
            return s
    return None


@router.get("/plan/{plan_id}/suggestions")
async def list_suggestions(plan_id: str, status: Optional[str] = None):
    """列出某 plan 的待推送 / 已采纳 / 已驳回建议（驾驶舱用，TR-22.1）。"""
    items = _pending_suggestions.get(plan_id, [])
    if status:
        items = [s for s in items if s.get("status") == status]
    return JSONResponse({
        "plan_id": plan_id,
        "count": len(items),
        "suggestions": [
            {
                "suggestion_id": s["suggestion_id"],
                "plan_id": s["plan_id"],
                "session_id": s.get("session_id", ""),
                "diff": s.get("diff", []),
                "reason": s.get("reason", ""),
                "source_url": s.get("source_url", ""),
                "created_ts": s.get("created_ts"),
                "status": s.get("status", "pending"),
            } for s in items
        ],
    })


@router.post("/plan/{plan_id}/suggestions/seed")
async def seed_suggestions(plan_id: str, request: Request):
    """手动往驾驶舱塞一条 mock diff 建议（无 LLM 时演示用）。

    body: {diff: [...], reason, source_url, session_id?}
    """
    body = await request.json()
    diff = body.get("diff") or []
    if not diff:
        raise HTTPException(status_code=400, detail="diff required")
    sid = _add_suggestion(plan_id, {
        "diff": diff,
        "reason": body.get("reason", "manual_seed"),
        "source_url": body.get("source_url", ""),
        "session_id": body.get("session_id", ""),
        "monitor_data": body.get("monitor_data"),
    })
    return JSONResponse({"status": "seeded", "suggestion_id": sid, "plan_id": plan_id})


@router.post("/plan/{plan_id}/suggestions/{suggestion_id}/adopt")
async def adopt_suggestion(plan_id: str, suggestion_id: str):
    """采纳建议：应用 diff → 保存新版本 → 广播给前端 WebSocket（TR-22.2）。

    优化（Task 22+）：若建议由 monitor 自动产出且未被编辑过
    （status='pending' 且 pending_version_id 存在），直接将该 pending 版本
    升级为 adopted，避免重复 apply_diff 与生成重复版本。
    否则（manual seed / edited / pending_version_id 已失效）走标准 apply_diff 路径。
    """
    sug = _find_suggestion(plan_id, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if sug.get("status") not in ("pending", "edited"):
        raise HTTPException(status_code=409, detail=f"suggestion already {sug.get('status')}")

    pending_vid = sug.get("pending_version_id")
    # 仅 pending 状态 + 有 pending 版本 + 版本确实存在时复用
    reuse_pending = False
    if sug.get("status") == "pending" and pending_vid:
        existing_v = plan_store.get_version(pending_vid)
        if existing_v and existing_v.get("plan_id") == plan_id:
            reuse_pending = True

    if reuse_pending:
        # 复用：升级 pending 版本为 adopted，同 plan 其他版本降级
        ok = plan_store.mark_adopted(plan_id, pending_vid)
        if not ok:
            raise HTTPException(status_code=500, detail="mark_adopted failed")
        new_vid = pending_vid
        new_plan = plan_store.get_version(new_vid)["plan"]
        parent_vid = existing_v.get("parent_version_id")
        reuse_note = "reused_pending_version"
    else:
        # 标准流程：apply_diff + save_version
        vid = plan_store.latest_version_id(plan_id)
        if not vid:
            raise HTTPException(status_code=404, detail="plan has no adopted version")
        cur_plan = plan_store.get_version(vid)["plan"]
        from . import dsh_runner
        new_plan = dsh_runner.apply_diff(cur_plan, sug["diff"])
        new_vid = plan_store.save_version(
            plan_id, new_plan,
            parent_version_id=vid,
            trigger_reason=f"cockpit_adopt_{suggestion_id}",
            diff=sug["diff"],
            adopted=True,
        )
        parent_vid = vid
        reuse_note = "fresh_apply_diff"

    # 同步 monitor 快照
    monitor.update_plan_snapshot(plan_id, new_plan)
    # 标记 suggestion
    sug["status"] = "adopted"
    sug["adopted_version_id"] = new_vid
    sug["adopted_ts"] = time.time()

    # 广播给前端 WebSocket（≤ 1 秒内同步）
    diff_payload = {
        "type": "optimize_diff",
        "plan_id": plan_id,
        "suggestion_id": suggestion_id,
        "diff": sug["diff"],
        "new_version_id": new_vid,
        "applied_count": len(sug["diff"]),
        "reason": sug.get("reason", "cockpit_adopt"),
        "source_url": sug.get("source_url", ""),
        "explanation": sug.get("reason", ""),
        "origin": "cockpit",
    }
    await broadcast_diff(plan_id, diff_payload)
    # 同时通知前端清理 pending 徽章（Task 22+：待审计数归零）
    await broadcast_diff(plan_id, {
        "type": "optimize_suggestion_resolved",
        "plan_id": plan_id,
        "suggestion_id": suggestion_id,
        "action": "adopted",
        "new_version_id": new_vid,
    })
    # 记录 traj
    sess = sug.get("session_id") or traj.new_session_id()
    traj.append(sess, "cockpit.adopt", {
        "suggestion_id": suggestion_id, "new_version_id": new_vid,
        "diff": sug["diff"],
        "reuse": reuse_note,
        "parent_version_id": parent_vid,
    })
    return JSONResponse({
        "status": "adopted", "suggestion_id": suggestion_id,
        "plan_id": plan_id, "new_version_id": new_vid,
        "plan": new_plan,
        "reuse": reuse_note,
    })


@router.post("/plan/{plan_id}/suggestions/{suggestion_id}/reject")
async def reject_suggestion(plan_id: str, suggestion_id: str):
    """驳回建议：不应用 diff，不推送 diff（TR-22.2）；但通知前端清理 pending 徽章。"""
    sug = _find_suggestion(plan_id, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if sug.get("status") not in ("pending", "edited"):
        raise HTTPException(status_code=409, detail=f"suggestion already {sug.get('status')}")
    # 若有 pending_version_id，把它的 adopted=0 显式清理（已是 0，做幂等处理）
    pending_vid = sug.get("pending_version_id")
    if pending_vid:
        from . import plan_store as _ps
        _ps.demote_version(pending_vid)  # 确保驳回后该版本不被 latest_version_id 返回
    sug["status"] = "rejected"
    sug["rejected_ts"] = time.time()
    sess = sug.get("session_id") or traj.new_session_id()
    traj.append(sess, "cockpit.reject", {"suggestion_id": suggestion_id})
    # 通知前端清理 pending 徽章（Task 22+）
    await broadcast_diff(plan_id, {
        "type": "optimize_suggestion_resolved",
        "plan_id": plan_id,
        "suggestion_id": suggestion_id,
        "action": "rejected",
    })
    return JSONResponse({
        "status": "rejected", "suggestion_id": suggestion_id, "plan_id": plan_id,
    })


@router.post("/plan/{plan_id}/suggestions/{suggestion_id}/edit")
async def edit_suggestion(plan_id: str, suggestion_id: str, request: Request):
    """编辑建议 diff 后保留为 pending，等待用户在驾驶舱再点采纳（TR-22.3）。

    body: {diff?: [...], reason?: str, source_url?: str}
    """
    sug = _find_suggestion(plan_id, suggestion_id)
    if not sug:
        raise HTTPException(status_code=404, detail="suggestion not found")
    if sug.get("status") not in ("pending", "edited"):
        raise HTTPException(status_code=409, detail=f"suggestion already {sug.get('status')}")
    body = await request.json()
    if body.get("diff"):
        sug["diff"] = body["diff"]
    if body.get("reason"):
        sug["reason"] = body["reason"]
    if body.get("source_url") is not None:
        sug["source_url"] = body["source_url"]
    sug["status"] = "edited"
    sug["edited_ts"] = time.time()
    sess = sug.get("session_id") or traj.new_session_id()
    traj.append(sess, "cockpit.edit", {
        "suggestion_id": suggestion_id, "new_diff": sug["diff"],
    })
    return JSONResponse({
        "status": "edited", "suggestion_id": suggestion_id,
        "plan_id": plan_id, "diff": sug["diff"], "reason": sug["reason"],
    })


@router.get("/plan/{plan_id}/cockpit/state")
async def cockpit_state(plan_id: str):
    """驾驶舱聚合视图：思考轨迹 + 待采纳建议 + 阈值配置（TR-22.1 三视图）。

    active_suggestions 包含 pending 与 edited 状态（驾驶舱可继续采纳/编辑）；
    pending_suggestions 仅 pending（向后兼容字段，前端老逻辑可能仍读它）。
    """
    # 最新 session_id（plan_id 关联）
    plan_row = None
    with plan_store._conn() as c:
        row = c.execute(
            "SELECT * FROM plans WHERE plan_id=?", (plan_id,)
        ).fetchone()
        plan_row = dict(row) if row else None
    session_id = plan_row["session_id"] if plan_row else ""
    events = traj.read(session_id) if session_id else []
    suggestions = _pending_suggestions.get(plan_id, [])
    vid = plan_store.latest_version_id(plan_id)
    # 阈值配置（与前端 config.js 共享 schema，仅返回后端可感知部分）
    cfg = {
        "dynamic_enabled": os.environ.get("TG_DYNAMIC_ENABLED", "true").lower() in ("true", "1", "yes"),
        "dynamic_mode": os.environ.get("TG_DYNAMIC_MODE", "suggest"),
        "dynamic_whitelist": [
            w.strip() for w in os.environ.get(
                "TG_DYNAMIC_WHITELIST", "attractions,food"
            ).split(",") if w.strip()
        ],
        "monitor_interval_pre_24h_sec": 1800,
        "monitor_interval_pre_sec": 7200,
    }
    active = [s for s in suggestions if s.get("status") in ("pending", "edited")]
    return JSONResponse({
        "plan_id": plan_id,
        "session_id": session_id,
        "current_version_id": vid,
        "trajectory_events": events,
        "trajectory_count": len(events),
        # 兼容字段：老逻辑只看 pending_suggestions
        "pending_suggestions": [s for s in active if s.get("status") == "pending"],
        # 新字段：包含 pending + edited，供驾驶舱渲染「待审」面板
        "active_suggestions": active,
        "all_suggestions": suggestions,
        "threshold_config": cfg,
    })


@router.post("/plan/{plan_id}/cockpit/config")
async def cockpit_update_config(plan_id: str, request: Request):
    """驾驶舱修改阈值配置（v1 写入环境变量，进程级生效；不持久化到 .env）。

    body: {dynamic_enabled?, dynamic_mode?, dynamic_whitelist?}
    """
    body = await request.json()
    if "dynamic_enabled" in body:
        os.environ["TG_DYNAMIC_ENABLED"] = "true" if body["dynamic_enabled"] else "false"
    if "dynamic_mode" in body:
        os.environ["TG_DYNAMIC_MODE"] = body["dynamic_mode"]
    if "dynamic_whitelist" in body:
        os.environ["TG_DYNAMIC_WHITELIST"] = ",".join(body["dynamic_whitelist"])
    return JSONResponse({
        "status": "updated", "plan_id": plan_id,
        "dynamic_enabled": os.environ.get("TG_DYNAMIC_ENABLED", "true"),
        "dynamic_mode": os.environ.get("TG_DYNAMIC_MODE", "suggest"),
        "dynamic_whitelist": [
            w.strip() for w in os.environ.get(
                "TG_DYNAMIC_WHITELIST", "attractions,food"
            ).split(",") if w.strip()
        ],
    })

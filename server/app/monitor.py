"""tg-monitor 等价实现

对应 spec FR-27、FR-28。周期性拉取目的地天气、当地节庆、同城热榜。
监测结果交给 dsh_runner 的优化逻辑产出 diff。
"""
from __future__ import annotations
import asyncio
import json
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from . import scraper
from . import traj

# 默认监测间隔（出行前 ≥24h：每 2 小时；出行前 24h：每 30 分钟）
_INTERVAL_PRE = 7200
_INTERVAL_PRE_24H = 1800

# Open-Meteo 免费 API（无 key）
_OPEN_METEO_GEO = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


async def _geocode(destination: str) -> Optional[Dict[str, float]]:
    """地名 → 经纬度。"""
    async with httpx.AsyncClient(timeout=10, trust_env=True) as client:
        r = await client.get(_OPEN_METEO_GEO, params={
            "name": destination, "count": 1, "language": "zh", "format": "json",
        })
    if r.status_code >= 400:
        return None
    data = r.json()
    results = data.get("results")
    if not results:
        return None
    hit = results[0]
    return {"lat": hit.get("latitude"), "lon": hit.get("longitude"),
            "name": hit.get("name"), "country": hit.get("country")}


async def fetch_weather(destination: str, target_date: Optional[str] = None) -> Dict[str, Any]:
    """拉取目的地天气。target_date 格式 YYYY-MM-DD。"""
    geo = await _geocode(destination)
    if not geo:
        return {"destination": destination, "error": "geocode_failed"}
    params = {
        "latitude": geo["lat"], "longitude": geo["lon"],
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": "auto",
    }
    async with httpx.AsyncClient(timeout=10, trust_env=True) as client:
        r = await client.get(_OPEN_METEO_FORECAST, params=params)
    if r.status_code >= 400:
        return {"destination": destination, "error": f"forecast_http_{r.status_code}"}
    d = r.json().get("daily", {})
    dates = d.get("time", [])
    codes = d.get("weather_code", [])
    tmax = d.get("temperature_2m_max", [])
    tmin = d.get("temperature_2m_min", [])
    pp = d.get("precipitation_probability_max", [])
    # WMO code 简化：≥51 视为雨
    out_days = []
    for i, dt in enumerate(dates):
        is_rain = (codes[i] >= 51) if i < len(codes) else False
        out_days.append({
            "date": dt,
            "weather_code": codes[i] if i < len(codes) else None,
            "tmax": tmax[i] if i < len(tmax) else None,
            "tmin": tmin[i] if i < len(tmin) else None,
            "precip_prob": pp[i] if i < len(pp) else None,
            "is_rain": is_rain,
        })
    return {"destination": destination, "geo": geo, "days": out_days}


async def fetch_local_hotlist(destination: str, day_offset: int = 0) -> List[Dict[str, Any]]:
    """爬取同城热榜（演出/市集/展览/限时活动）。

    Task 23：升级为多源拉取 + 失败降级：
    1. 主源：Wikipedia "On this day" API（开放、无 key、稳定），按 destination 关键词筛选相关历史事件
    2. 备选源：Scrapling 抓 mafengwo 活动页（保留原逻辑）
    任一成功即返回非空列表；全部失败返回空列表（不抛异常，FR-28 容错）
    """
    results: List[Dict[str, Any]] = []

    # 主源：Wikipedia Events API（按目的地关键词筛近期事件）
    try:
        results.extend(await _fetch_wikipedia_events(destination))
    except Exception as e:
        # 不抛错，记录日志后继续备选源
        from . import traj as _traj
        _traj.append("monitor", "tg-monitor.hotlist_wikipedia_failed", {
            "destination": destination, "msg": str(e),
        })

    # 备选源：Scrapling 抓 mafengwo 活动页
    if not results:
        try:
            tasks = [
                {
                    "target_url": f"https://www.mafengwo.cn/search/q.php?q={destination}+活动",
                    "source_type": "generic", "query": f"{destination} 活动",
                    "fields": ["name", "desc", "date", "venue"],
                },
            ]
            res = await scraper.batch(tasks)
            materials = res.get("materials", [])
            for m in materials:
                if m.get("name"):
                    results.append({
                        "name": m.get("name", ""),
                        "desc": m.get("desc", ""),
                        "date": m.get("date", ""),
                        "venue": m.get("venue", ""),
                        "source_url": m.get("source_url") or m.get("url", ""),
                        "source_type": "mafengwo",
                    })
        except Exception as e:
            from . import traj as _traj2
            _traj2.append("monitor", "tg-monitor.hotlist_scraper_failed", {
                "destination": destination, "msg": str(e),
            })

    return results


async def _fetch_wikipedia_events(destination: str) -> List[Dict[str, Any]]:
    """从 Wikipedia "On this Day" API 拉取当日历史事件，按目的地关键词筛选。

    API: https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{MM}/{DD}
    返回结构：[{text, year, pages: [{title, ...}], ...}]
    筛选：text 或 page title 含 destination 关键词的事件
    返回：[{name, desc, date, venue, source_url, source_type}]
    """
    import datetime as _dt
    now = _dt.datetime.now()
    url = f"https://en.wikipedia.org/api/rest_v1/feed/onthisday/events/{now.month:02d}/{now.day:02d}"
    async with httpx.AsyncClient(timeout=10, trust_env=True) as client:
        r = await client.get(url, headers={
            "User-Agent": "tg-monitor/1.0 (https://example.local/tg-monitor)",
            "Accept": "application/json",
        })
    if r.status_code >= 400:
        return []
    data = r.json()
    events = data.get("events", []) if isinstance(data, dict) else []
    out: List[Dict[str, Any]] = []
    dest_lower = (destination or "").lower()
    for ev in events[:50]:  # 限制扫描前 50 条避免过大
        text = ev.get("text", "") or ""
        year = ev.get("year")
        # 关键词匹配：目的地名称出现在 text 中
        if dest_lower and dest_lower not in text.lower():
            # 也看 pages 的 title
            pages = ev.get("pages") or []
            page_titles = " ".join(p.get("title", "") for p in pages).lower()
            if dest_lower not in page_titles:
                continue
        # 构造 source_url：优先取第一个 page 的 content_urls.desktop.page
        source_url = ""
        pages = ev.get("pages") or []
        if pages:
            source_url = (pages[0].get("content_urls") or {}).get("desktop", {}).get("page", "")
        out.append({
            "name": text[:80] + ("…" if len(text) > 80 else ""),
            "desc": text,
            "date": f"{year}-{now.month:02d}-{now.day:02d}" if year else "",
            "venue": destination,
            "source_url": source_url or "https://en.wikipedia.org/wiki/Wikipedia:On_this_day",
            "source_type": "wikipedia_onthisday",
        })
    return out[:10]  # 最多 10 条


async def monitor_once(
    plan_id: str,
    destination: str,
    target_date: Optional[str] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """单次监测：天气 + 同城热榜。结果供 tg-optimizer 决策。"""
    weather = await fetch_weather(destination, target_date)
    hotlist = await fetch_local_hotlist(destination)
    payload = {
        "ts": time.time(),
        "destination": destination,
        "target_date": target_date,
        "weather": weather,
        "hotlist_count": len(hotlist),
        "hotlist": hotlist[:10],
    }
    if session_id:
        traj.append(session_id, "tg-monitor.tick", payload)
    return payload


# ====== 周期监测循环 ======
_tasks: Dict[str, asyncio.Task] = {}
# 监测元数据：plan_id -> {llm_cfg, plan_snapshot, whitelist}
_meta: Dict[str, Dict[str, Any]] = {}

# FR-33 协同冲突避让：plan_id -> [{"ts", "day", "field"}, ...]
# 用户最近 5 分钟内手动编辑过的 (day, field) 卡片，monitor 跳过对应 diff
# 仅推送一条 "skipped_due_to_user_edit" 提示，不应用变更
_user_edits: Dict[str, List[Dict[str, Any]]] = {}
_USER_EDIT_WINDOW_SEC = 300  # 5 分钟


def record_user_edit(plan_id: str, day: Optional[int], field: Optional[str]) -> None:
    """记录用户手动编辑事件（FR-33）。

    由 routes.ws_plan 在收到 user_edit 消息时调用；monitor._maybe_optimize
    会查询本表，跳过对应 (day, field) 的 diff。
    """
    if not plan_id or day is None or not field:
        return
    _user_edits.setdefault(plan_id, []).append({
        "ts": time.time(), "day": day, "field": field,
    })
    # 顺手清理过期项
    _gc_user_edits(plan_id)


def _gc_user_edits(plan_id: str) -> None:
    """清理超过 5 分钟的 user_edit 记录。"""
    now = time.time()
    arr = _user_edits.get(plan_id, [])
    fresh = [e for e in arr if now - e["ts"] < _USER_EDIT_WINDOW_SEC]
    if len(fresh) != len(arr):
        _user_edits[plan_id] = fresh


def _is_field_user_edited(plan_id: str, day: Optional[int], field: Optional[str]) -> bool:
    """判断 (day, field) 是否在用户最近 5 分钟编辑窗口内。"""
    if not plan_id or day is None or not field:
        return False
    _gc_user_edits(plan_id)
    for e in _user_edits.get(plan_id, []):
        if e["day"] == day and e["field"] == field:
            return True
    return False


def start_monitor_loop(
    plan_id: str,
    destination: str,
    departure_date: Optional[str] = None,
    session_id: Optional[str] = None,
    *,
    llm_cfg: Optional[Dict[str, str]] = None,
    plan_snapshot: Optional[Dict[str, Any]] = None,
    whitelist: Optional[List[str]] = None,
) -> None:
    """启动后台监测任务。幂等：相同 plan_id 重复启动会取消旧任务。

    若同时提供 llm_cfg + plan_snapshot，则每次监测后调
    dsh_runner.optimize_with_monitor_data 产出 diff 并广播给 WebSocket 订阅者。
    """
    if plan_id in _tasks and not _tasks[plan_id].done():
        _tasks[plan_id].cancel()
    _meta[plan_id] = {
        "llm_cfg": llm_cfg or {},
        "plan": plan_snapshot,
        "whitelist": whitelist or [],
    }
    async def _loop():
        while True:
            try:
                payload = await monitor_once(plan_id, destination, departure_date, session_id)
                meta = _meta.get(plan_id, {})
                llm = meta.get("llm_cfg") or {}
                plan = meta.get("plan")
                if (llm.get("api_key") and isinstance(plan, dict)
                        and plan.get("overview")):
                    await _maybe_optimize(plan_id, payload, meta, session_id)
            except Exception as e:
                if session_id:
                    traj.append(session_id, "tg-monitor.error", {"msg": str(e)})
            # 简化间隔：默认 1 小时
            await asyncio.sleep(_INTERVAL_PRE_24H if departure_date else _INTERVAL_PRE)
    _tasks[plan_id] = asyncio.create_task(_loop())


def stop_monitor_loop(plan_id: str) -> None:
    t = _tasks.pop(plan_id, None)
    _meta.pop(plan_id, None)
    if t and not t.done():
        t.cancel()


def update_plan_snapshot(plan_id: str, plan: Dict[str, Any]) -> None:
    """供 routes 在 user_edit / revert 后同步最新快照。"""
    if plan_id in _meta:
        _meta[plan_id]["plan"] = plan


async def _maybe_optimize(
    plan_id: str,
    monitor_data: Dict[str, Any],
    meta: Dict[str, Any],
    session_id: Optional[str],
) -> None:
    """跑 optimizer，diff 非空时按模式分流（Task 22）。

    - 自动模式（dynamic_mode='auto'）：直接应用 + 广播 diff 给前端
    - 建议模式（dynamic_mode='suggest'）：暂存到 _pending_suggestions，
      等待 DSH Web UI 驾驶舱用户「采纳/驳回/编辑」（AC-15 / FR-30 / FR-31）
    """
    from . import dsh_runner
    from .routes import broadcast_diff, _add_suggestion  # 运行时解析
    import os as _os
    llm = meta.get("llm_cfg") or {}
    plan = meta.get("plan") or {}
    # 取当前模式（与 cockpit 共享环境变量）
    mode = _os.environ.get("TG_DYNAMIC_MODE", "suggest")
    dynamic_enabled = _os.environ.get("TG_DYNAMIC_ENABLED", "true").lower() in ("true", "1", "yes")
    if not dynamic_enabled:
        return  # 总开关关闭：跳过本次优化（TR-21.4 等价行为）
    try:
        result = await dsh_runner.optimize_with_monitor_data(
            plan_id, plan, monitor_data,
            base_url=llm.get("base_url", ""),
            api_key=llm.get("api_key", ""),
            model=llm.get("model", "deepseek-chat"),
            whitelist=meta.get("whitelist"),
            session_id=session_id,
        )
        if result.get("applied_count", 0) == 0:
            return
        diff = result.get("diff", [])
        reason = "monitor_optimize"
        # FR-33 协同冲突避让：把 diff 按 (day, field) 是否在用户编辑窗口内拆分
        # safe_diff：可应用的；skipped_diff：跳过的（仅推送提示）
        safe_diff: List[Dict[str, Any]] = []
        skipped_diff: List[Dict[str, Any]] = []
        for d in diff:
            day = d.get("day")
            field = d.get("target_field")
            if _is_field_user_edited(plan_id, day, field):
                skipped_diff.append(d)
            else:
                safe_diff.append(d)
        # 若有跳过项，记录 traj + 推送提示给前端
        if skipped_diff:
            traj.append(session_id or traj.new_session_id(),
                        "tg-monitor.skipped_user_edit", {
                "plan_id": plan_id,
                "skipped_count": len(skipped_diff),
                "skipped": [
                    {"day": d.get("day"), "field": d.get("target_field"),
                     "reason": d.get("reason", "")} for d in skipped_diff
                ],
            })
            await broadcast_diff(plan_id, {
                "type": "optimize_skipped_user_edit",
                "plan_id": plan_id,
                "skipped_count": len(skipped_diff),
                "skipped": [
                    {"day": d.get("day"), "field": d.get("target_field"),
                     "reason": d.get("reason", ""),
                     "new_name": (d.get("new_item") or {}).get("name", "")}
                    for d in skipped_diff
                ],
                "origin": "monitor_fr33",
            })
        # 全部被避让：不应用任何 diff，结束本次
        if not safe_diff:
            return
        # 部分被避让：用 safe_diff 替换 diff，重新 apply
        if len(safe_diff) != len(diff):
            from . import dsh_runner as _dsh
            from . import plan_store as _ps2
            cur_vid = _ps2.latest_version_id(plan_id)
            cur_plan = _ps2.get_version(cur_vid)["plan"] if cur_vid else plan
            new_plan_partial = _dsh.apply_diff(cur_plan, safe_diff)
            # 覆盖 result 中的 plan + diff（不重新调 LLM，节省成本）
            result["plan"] = new_plan_partial
            result["diff"] = safe_diff
            result["applied_count"] = len(safe_diff)
            # 重新 save_version（之前 dsh_runner 已 save 过完整 diff，
            # 现在用 safe_diff 覆盖：demote 旧版本，再 save 新版本）
            from . import plan_store as _ps3
            old_vid = result.get("new_version_id")
            if old_vid:
                _ps3.demote_version(old_vid)
            result["new_version_id"] = _ps3.save_version(
                plan_id, new_plan_partial,
                parent_version_id=cur_vid,
                trigger_reason=f"monitor_optimize_partial_{len(safe_diff)}_of_{len(diff)}",
                diff=safe_diff, adopted=True,
            )
            diff = safe_diff
        # 取第一条 diff 的 source_url 做说明（若有）
        source_url = ""
        for d in diff:
            ni = d.get("new_item") or {}
            if isinstance(ni, dict) and ni.get("source_url"):
                source_url = ni["source_url"]
                break
        if mode == "auto":
            # 自动模式：直接应用，更新快照 + 广播
            meta["plan"] = result["plan"]
            await broadcast_diff(plan_id, {
                "type": "optimize_diff",
                "plan_id": plan_id,
                "diff": diff,
                "new_version_id": result.get("new_version_id"),
                "applied_count": result["applied_count"],
                "reason": reason,
                "source_url": source_url,
                "origin": "monitor_auto",
            })
        else:
            # 建议模式：暂存到驾驶舱 pending 池，不直接应用 diff
            # monitor 已 save_version(adopted=True)，现在降级为 adopted=False，
            # 使 latest_version_id 仍返回原 adopted 版本（不阻塞用户回滚到原版本）。
            # cockpit 采纳时会通过 mark_adopted 升级回 adopted=True（Task 22+ 优化）。
            from . import plan_store as _ps
            new_vid = result.get("new_version_id")
            if new_vid:
                _ps.demote_version(new_vid)
            sid = _add_suggestion(plan_id, {
                "diff": diff,
                "reason": reason,
                "source_url": source_url,
                "session_id": session_id or "",
                "monitor_data": {
                    "ts": monitor_data.get("ts"),
                    "weather_days": (monitor_data.get("weather") or {}).get("days", [])[:3],
                    "hotlist_count": monitor_data.get("hotlist_count", 0),
                },
                "pending_version_id": new_vid,
            })
            traj.append(session_id or traj.new_session_id(),
                        "cockpit.suggestion_seeded", {
                "suggestion_id": sid, "diff_count": len(diff),
                "reason": reason,
            })
            # 广播一条 "建议待审" 通知给前端（前端可选展示"驾驶舱有 N 条待审建议" 提示）
            await broadcast_diff(plan_id, {
                "type": "optimize_suggestion_pending",
                "plan_id": plan_id,
                "suggestion_id": sid,
                "diff_count": len(diff),
                "reason": reason,
                "source_url": source_url,
                "origin": "monitor_suggest",
            })
    except Exception as e:
        if session_id:
            traj.append(session_id, "tg-optimizer.error", {"msg": str(e)})

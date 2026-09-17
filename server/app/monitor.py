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

    v1 用 Scrapling 抓公开页（穷游、马蜂窝活动页等），失败返回空列表。
    """
    # 用关键词构造任务清单（不预置具体 URL，由 scraper 处理）
    tasks = [
        {
            "target_url": f"https://www.mafengwo.cn/search/q.php?q={destination}+活动",
            "source_type": "generic", "query": f"{destination} 活动",
            "fields": ["name", "desc", "date", "venue"],
        },
    ]
    res = await scraper.batch(tasks)
    return res.get("materials", [])


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
    """跑 optimizer，diff 非空时广播 + 更新快照。"""
    from . import dsh_runner
    from .routes import broadcast_diff  # 避免循环导入：运行时解析
    llm = meta.get("llm_cfg") or {}
    plan = meta.get("plan") or {}
    try:
        result = await dsh_runner.optimize_with_monitor_data(
            plan_id, plan, monitor_data,
            base_url=llm.get("base_url", ""),
            api_key=llm.get("api_key", ""),
            model=llm.get("model", "deepseek-chat"),
            whitelist=meta.get("whitelist"),
            session_id=session_id,
        )
        if result.get("applied_count", 0) > 0:
            # 更新快照，下一次监测基于新版本
            meta["plan"] = result["plan"]
            # 广播 diff 给前端（type=optimize_diff）
            await broadcast_diff(plan_id, {
                "type": "optimize_diff",
                "plan_id": plan_id,
                "diff": result["diff"],
                "new_version_id": result.get("new_version_id"),
                "applied_count": result["applied_count"],
                "reason": "monitor_optimize",
            })
    except Exception as e:
        if session_id:
            traj.append(session_id, "tg-optimizer.error", {"msg": str(e)})

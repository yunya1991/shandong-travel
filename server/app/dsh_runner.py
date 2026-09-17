"""DeepSeek Harness 启动与请求封装（薄壳）

对应 spec FR-20、FR-21、FR-24、NFR-8、NFR-10。

设计原则：
- 所有 DSH SDK 调用集中在本模块；SDK 升级时只改这里。
- DSH 不可用（未安装 / 预发布版 API 不兼容）时回退到 llm_client.built-in agent loop。
- 用户 key 仅在请求内存中持有（X-LLM-Config header），不写入 DSH_HOME。
- Trajectory 日志由 traj.py 维护，本模块调用 traj.append() 记录每个插件调用事件。

v1 实现：DSH SDK 仍为预发布，本模块提供"模拟 DSH Agent"的串行编排逻辑，
确保前端联调可走通；待 SDK 正式版可用时替换 _invoke_dsh_* 系列函数即可。
"""
from __future__ import annotations
import json
import os
from typing import Any, Dict, List, Optional

from . import traj
from .prompts import (
    SYSTEM_PROMPT,
    PLAN_SCRAPE_TASKS,
    INTEGRATE_PLAN,
    VALIDATE_PLAN,
    OPTIMIZE_DIFF,
)
from .llm_client import chat_completion
from .schema import validate_plan
from . import cache


# ====== DSH SDK 探测 ======
def dsh_available() -> bool:
    """探测 deepseek-harness-sdk 是否可导入且 DSH_ENABLED=true。"""
    if os.environ.get("DSH_ENABLED", "true").lower() not in ("true", "1", "yes"):
        return False
    try:
        import deepseek_harness_sdk  # type: ignore  # noqa: F401
        return True
    except ImportError:
        return False


async def run_pipeline(
    destination: str,
    prefs: Dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    model: str,
    materials: Optional[List[Dict[str, Any]]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """编排链路：planner → scraper → integrator → validator → optimizer(可选) → output

    返回 {plan, sources, warnings, session_id, version_id}。
    本函数为 v1 串行实现，DSH 不可用时也走它（NFR-8 降级）；
    DSH 可用时本函数可被 _invoke_dsh_* 覆盖（v1 暂不做）。
    """
    session_id = session_id or traj.new_session_id()
    materials = materials or []
    sources: List[Dict[str, str]] = []

    # ====== 0. tg-cache（plan-level）：相同 (destination+prefs) 复用整套方案 ======
    plan_ck = cache.key_plan(destination, prefs)
    if not materials:  # 仅自动模式命中；用户粘贴素材不命中
        cached_plan = cache.get(plan_ck)
        if isinstance(cached_plan, dict) and isinstance(cached_plan.get("plan"), dict):
            traj.append(session_id, "tg-cache.hit", {
                "key": plan_ck, "destination": destination,
            })
            cached_plan["session_id"] = session_id
            cached_plan["cached"] = True
            return cached_plan
        traj.append(session_id, "tg-cache.miss", {"key": plan_ck})

    # ====== 1. tg-planner：生成抓取任务清单 ======
    traj.append(session_id, "system_prompt", {"content": SYSTEM_PROMPT})
    traj.append(session_id, "tg-planner.start", {
        "destination": destination, "prefs": prefs,
        "materials_count": len(materials),
    })
    # 若调用方未传 materials，则由 planner 产出任务清单（v1 降级为空列表）
    if not materials:
        try:
            tasks = await _invoke_planner(destination, prefs,
                                           base_url=base_url, api_key=api_key, model=model)
            traj.append(session_id, "tg-planner.tasks", {"tasks": tasks})
        except Exception as e:
            traj.append(session_id, "tg-planner.error", {"msg": str(e)})
            tasks = []
    else:
        tasks = []
        traj.append(session_id, "tg-planner.skipped", {"reason": "materials_provided"})

    # ====== 2. tg-scraper：抓取素材（v1 调 scraper.batch） ======
    if tasks and dsh_available() is False and _scraper_callable():
        try:
            scraped = await _invoke_scraper(tasks)
            materials.extend(scraped.get("materials", []))
            sources.extend(scraped.get("sources", []))
            traj.append(session_id, "tg-scraper.batch", {
                "tasks": len(tasks), "materials": len(scraped.get("materials", [])),
            })
        except Exception as e:
            traj.append(session_id, "tg-scraper.error", {"msg": str(e)})

    # ====== 3. tg-integrator：合并素材为 plan ======
    traj.append(session_id, "tg-integrator.start", {"materials_count": len(materials)})
    try:
        plan = await _invoke_integrator(destination, prefs, materials,
                                         base_url=base_url, api_key=api_key, model=model)
        traj.append(session_id, "tg-integrator.done", {
            "daily_count": len(plan.get("daily", [])),
            "attractions_count": len(plan.get("attractions", [])),
        })
    except Exception as e:
        traj.append(session_id, "tg-integrator.error", {"msg": str(e)})
        raise

    # ====== 4. tg-validator：事实校对 ======
    traj.append(session_id, "tg-validator.start", {})
    warnings_raw = await _invoke_validator(plan, materials,
                                             base_url=base_url, api_key=api_key, model=model)
    schema_check = validate_plan(plan)
    warnings = warnings_raw + [
        {"level": "medium", "field": e, "msg": e} for e in schema_check["errors"]
    ] + [
        {"level": "low", "field": w, "msg": w} for w in schema_check["warnings"]
    ]
    traj.append(session_id, "tg-validator.done", {"warnings_count": len(warnings)})

    # ====== 5. tg-output：组装响应 ======
    from .schema import make_response, _source_coverage
    coverage = _source_coverage(plan)
    sources = _dedupe_sources(sources + _plan_sources(plan))
    result = make_response(plan, sources, warnings, session_id)
    # tg-cache：写回 plan-level 缓存（仅自动模式命中时复用）
    if not materials:
        cache.set_(plan_ck, result)
    traj.append(session_id, "tg-output.done", {
        "sources_count": len(sources),
        "source_coverage": coverage,
    })
    return result


# ====== 内部插件调用（v1 直接走 LLM，待 DSH SDK 正式版替换） ======
async def _invoke_planner(destination: str, prefs: Dict[str, Any], **kw) -> List[Dict[str, Any]]:
    prompt = PLAN_SCRAPE_TASKS.format(
        destination=destination,
        prefs=json.dumps(prefs, ensure_ascii=False),
    )
    # tg-cache：相同输入复用
    ck = cache.key_llm("planner", prompt)
    cached = cache.get(ck)
    if cached is not None:
        return cached if isinstance(cached, list) else cached.get("tasks", [])
    res = await chat_completion(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        base_url=kw["base_url"], api_key=kw["api_key"], model=kw["model"],
        max_tokens=2000, response_format_json=True,
    )
    cache.set_(ck, res)
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and "tasks" in res:
        return res["tasks"]
    return []


def _scraper_callable() -> bool:
    try:
        from . import scraper  # noqa: F401
        return True
    except ImportError:
        return False


async def _invoke_scraper(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    from . import scraper
    return await scraper.batch(tasks)


async def _invoke_integrator(destination: str, prefs: Dict[str, Any],
                              materials: List[Dict[str, Any]], **kw) -> Dict[str, Any]:
    prompt = INTEGRATE_PLAN.format(
        destination=destination,
        prefs=json.dumps(prefs, ensure_ascii=False),
        materials=json.dumps(materials, ensure_ascii=False),
    )
    # tg-cache：相同 (destination+prefs+materials) 复用 plan
    inputs_hash = json.dumps(materials, sort_keys=True, ensure_ascii=False)
    ck = cache.key_llm("integrator", prompt + inputs_hash)
    cached = cache.get(ck)
    if isinstance(cached, dict) and "overview" in cached:
        return cached
    res = await chat_completion(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        base_url=kw["base_url"], api_key=kw["api_key"], model=kw["model"],
        max_tokens=12000, temperature=0.45, response_format_json=True,
    )
    if not isinstance(res, dict) or "overview" not in res:
        raise RuntimeError(f"integrator 输出无效: {str(res)[:200]}")
    cache.set_(ck, res)
    return res


async def _invoke_validator(plan: Dict[str, Any], materials: List[Dict[str, Any]], **kw) -> List[Dict[str, str]]:
    prompt = VALIDATE_PLAN.format(
        plan=json.dumps(plan, ensure_ascii=False),
        materials=json.dumps(materials, ensure_ascii=False),
    )
    # tg-cache：相同 (plan+materials) 复用 warnings
    inputs_hash = json.dumps(plan, sort_keys=True, ensure_ascii=False) + \
                  json.dumps(materials, sort_keys=True, ensure_ascii=False)
    ck = cache.key_llm("validator", prompt + inputs_hash)
    cached = cache.get(ck)
    if isinstance(cached, list):
        return cached
    res = await chat_completion(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        base_url=kw["base_url"], api_key=kw["api_key"], model=kw["model"],
        max_tokens=2000, response_format_json=True,
    )
    warnings = res if isinstance(res, list) else (
        res.get("warnings", []) if isinstance(res, dict) else []
    )
    cache.set_(ck, warnings)
    return warnings


# ====== tg-optimizer：动态优化（基于监测数据产出 diff） ======
async def _invoke_optimizer(
    plan: Dict[str, Any],
    monitor_data: Dict[str, Any],
    whitelist: Optional[List[str]] = None,
    **kw,
) -> List[Dict[str, Any]]:
    """根据监测数据产出 ADD/SWAP/MOVE diff。不命中缓存（监测数据每次不同）。"""
    prompt = OPTIMIZE_DIFF.format(
        plan=json.dumps(plan, ensure_ascii=False),
        monitor_data=json.dumps(monitor_data, ensure_ascii=False),
        whitelist=json.dumps(whitelist or [], ensure_ascii=False),
    )
    res = await chat_completion(
        [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
        base_url=kw["base_url"], api_key=kw["api_key"], model=kw["model"],
        max_tokens=1500, temperature=0.3, response_format_json=True,
    )
    if isinstance(res, list):
        return res
    if isinstance(res, dict) and "diff" in res:
        return res["diff"]
    return []


async def optimize_with_monitor_data(
    plan_id: str,
    plan: Dict[str, Any],
    monitor_data: Dict[str, Any],
    *,
    base_url: str,
    api_key: str,
    model: str,
    whitelist: Optional[List[str]] = None,
    session_id: Optional[str] = None,
) -> Dict[str, Any]:
    """供 monitor/路由调用：跑 optimizer → 应用 diff → 保存新版本。

    返回 {plan_id, new_version_id, diff, applied_count, plan}。
    diff 为空时不产生新版本，仍返回当前快照。
    """
    session_id = session_id or traj.new_session_id()
    traj.append(session_id, "tg-optimizer.start", {
        "plan_id": plan_id,
        "monitor_ts": monitor_data.get("ts"),
        "weather": monitor_data.get("weather", {}).get("days", [])[:3],
        "hotlist_count": monitor_data.get("hotlist_count", 0),
    })
    diff = await _invoke_optimizer(
        plan, monitor_data, whitelist,
        base_url=base_url, api_key=api_key, model=model,
    )
    traj.append(session_id, "tg-optimizer.diff", {"diff": diff, "count": len(diff)})

    if not diff:
        return {"plan_id": plan_id, "diff": [], "applied_count": 0, "plan": plan}

    # 应用 diff
    from . import plan_store
    new_plan = apply_diff(plan, diff)
    new_vid = plan_store.save_version(
        plan_id, new_plan,
        trigger_reason="monitor_optimize",
        diff=diff,
        adopted=True,
    )
    traj.append(session_id, "tg-optimizer.applied", {
        "new_version_id": new_vid, "applied_count": len(diff),
    })
    return {
        "plan_id": plan_id, "new_version_id": new_vid,
        "diff": diff, "applied_count": len(diff), "plan": new_plan,
    }


def apply_diff(plan: Dict[str, Any], diff: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对 plan 应用 ADD/SWAP/MOVE diff，返回新的 plan（不修改原对象）。

    v1 简化实现：仅处理 daily[*].attractions / food 的局部替换/追加/移动。
    非法 diff 项被静默跳过，确保最终 plan 仍满足 schema。
    """
    import copy as _copy
    new_plan = _copy.deepcopy(plan)
    daily = new_plan.get("daily", []) or []

    def _find_day(day_idx: int) -> Optional[Dict[str, Any]]:
        for d in daily:
            if d.get("day") == day_idx:
                return d
        return None

    for op in diff:
        try:
            day_idx = int(op.get("day", 0))
            if day_idx <= 0:
                continue
            target_field = op.get("target_field")
            if target_field not in ("attractions", "food", "accommodation"):
                continue
            day = _find_day(day_idx)
            if day is None:
                continue
            items = day.setdefault(target_field, [])
            new_item = op.get("new_item")
            old_item = op.get("old_item")
            opk = op.get("op", "").upper()

            if opk == "ADD" and isinstance(new_item, dict):
                items.append(new_item)
            elif opk == "SWAP" and isinstance(new_item, dict):
                # 用 name 匹配 old_item 进行替换；找不到则追加
                target_name = (old_item or {}).get("name")
                replaced = False
                for i, it in enumerate(items):
                    if isinstance(it, dict) and it.get("name") == target_name:
                        items[i] = new_item
                        replaced = True
                        break
                if not replaced:
                    items.append(new_item)
            elif opk == "MOVE" and isinstance(old_item, dict):
                # v1 简化：MOVE 视为在同日内重排，无跨日支持
                target_name = old_item.get("name")
                idx = next(
                    (i for i, it in enumerate(items)
                     if isinstance(it, dict) and it.get("name") == target_name),
                    -1,
                )
                if idx >= 0 and isinstance(new_item, dict):
                    # new_item.target_day 提示目标日；v1 忽略跨日
                    items.pop(idx)
                    items.append(new_item)
        except Exception:
            continue

    # 同步顶层 attractions/food 镜像（保持 schema 一致）
    _sync_top_level_lists(new_plan)
    return new_plan


def _sync_top_level_lists(plan: Dict[str, Any]) -> None:
    """从 daily 重新构建顶层 attractions/food（去重 by name）。"""
    seen_a: set = set()
    seen_f: set = set()
    attractions: List[Dict[str, Any]] = []
    food: List[Dict[str, Any]] = []
    for d in plan.get("daily", []) or []:
        for it in d.get("attractions", []) or []:
            if isinstance(it, dict) and it.get("name") not in seen_a:
                seen_a.add(it.get("name"))
                attractions.append(it)
        for it in d.get("food", []) or []:
            if isinstance(it, dict) and it.get("name") not in seen_f:
                seen_f.add(it.get("name"))
                food.append(it)
    if attractions:
        plan["attractions"] = attractions
    if food:
        plan["food"] = food


# ====== 工具 ======
def _plan_sources(plan: Dict[str, Any]) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    for key in ("attractions", "food", "accommodation"):
        for it in plan.get(key, []) or []:
            if isinstance(it, dict) and it.get("source_url"):
                out.append({"url": it["source_url"], "title": it.get("name", "")})
    return out


def _dedupe_sources(sources: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for s in sources:
        url = s.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        out.append(s)
    return out

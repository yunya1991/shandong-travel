"""旅游方案数据 Schema

与前端 app/js/schema.js 保持字段一致。LLM 返回 JSON 必须满足本结构。
所有可选字段携带 source_url + source_type，用于来源追溯与动态优化。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any


# 顶层必需字段（与 schema.js REQUIRED_FIELDS 对齐）
REQUIRED_TOP_FIELDS = {
    "overview",
    "route",
    "daily",
    "attractions",
    "accommodation",
    "food",
    "budget",
    "tips",
}

OVERVIEW_FIELDS = [
    "title", "dates", "days", "travelers", "departure",
    "route_theme", "highlights", "mileage", "suitable_people", "tips",
]

BUDGET_FIELDS = ["accommodation", "transport", "food", "tickets", "other", "total", "per_person"]


def validate_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """返回 {valid: bool, errors: [str], warnings: [str]}。"""
    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(plan, dict):
        return {"valid": False, "errors": ["根节点不是对象"], "warnings": []}

    for f in REQUIRED_TOP_FIELDS:
        if f not in plan:
            errors.append(f"缺少顶层字段: {f}")

    ov = plan.get("overview")
    if isinstance(ov, dict):
        for sf in OVERVIEW_FIELDS:
            if sf not in ov:
                warnings.append(f"overview.{sf} 缺失")
    else:
        errors.append("overview 不是对象")

    bg = plan.get("budget")
    if isinstance(bg, dict):
        for sf in BUDGET_FIELDS:
            if sf not in bg:
                warnings.append(f"budget.{sf} 缺失")
    else:
        errors.append("budget 不是对象")

    if isinstance(plan.get("daily"), list) and not plan["daily"]:
        errors.append("daily 为空数组")
    if isinstance(plan.get("attractions"), list) and not plan["attractions"]:
        errors.append("attractions 为空数组")

    # 来源追溯：至少 70% 条目带 source_url（仅做 warning，不阻塞）
    src_coverage = _source_coverage(plan)
    if src_coverage["total"] > 0 and src_coverage["with_url"] / src_coverage["total"] < 0.7:
        warnings.append(
            f"source_url 覆盖率 {src_coverage['with_url']}/{src_coverage['total']} < 70%"
        )

    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def _source_coverage(plan: Dict[str, Any]) -> Dict[str, int]:
    total = 0
    with_url = 0
    for key in ("attractions", "food", "accommodation"):
        items = plan.get(key, [])
        if isinstance(items, list):
            for it in items:
                if isinstance(it, dict):
                    total += 1
                    if it.get("source_url"):
                        with_url += 1
    for d in plan.get("daily", []) or []:
        if not isinstance(d, dict):
            continue
        for key in ("attractions", "food"):
            for it in d.get(key, []) or []:
                if isinstance(it, dict):
                    total += 1
                    if it.get("source_url"):
                        with_url += 1
    return {"total": total, "with_url": with_url}


def make_response(
    plan: Dict[str, Any],
    sources: List[Dict[str, str]],
    warnings: List[Dict[str, str]],
    session_id: str,
    version_id: Optional[str] = None,
) -> Dict[str, Any]:
    """组装 /generate 标准响应。"""
    return {
        "plan": plan,
        "sources": sources,
        "warnings": warnings,
        "session_id": session_id,
        "version_id": version_id or session_id,
        "source_coverage": _source_coverage(plan),
    }

"""当地特色素材库（seasonal.yaml 加载）

对应 spec FR-28。维护季节/地域特色条目，生成行程时按出行日期匹配注入。
"""
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List
import datetime

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # type: ignore

YAML_PATH = Path(__file__).resolve().parent.parent / "plugins" / "tg-bundle" / "data" / "seasonal.yaml"


def load_seasonal() -> Dict[str, List[Dict[str, Any]]]:
    """加载 seasonal.yaml。结构：{destination: [{name, months:[1-12], desc, source_url}]}。"""
    if yaml is None or not YAML_PATH.exists():
        return {}
    with YAML_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def match_seasonal(destination: str, departure_date: str) -> List[Dict[str, Any]]:
    """根据目的地与出行月份返回匹配的特色条目。departure_date 格式 YYYY-MM-DD。"""
    all_data = load_seasonal()
    items = all_data.get(destination, [])
    try:
        month = int(departure_date.split("-")[1])
    except (ValueError, IndexError):
        return []
    return [it for it in items if month in (it.get("months") or [])]

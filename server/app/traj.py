"""Trajectory 日志（append-only JSONL）

对应 spec FR-23 / NFR-9。每次 /generate 调用分配 session_id，
所有 LLM/Scrapling/subagent/动态优化事件按时间线追加。
前端通过 GET /trajectory/{session_id} 拉取并按时间线渲染。
"""
from __future__ import annotations
import json
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

# 存放目录（与 .dsh-home 同级）
TRAJ_DIR = Path(__file__).resolve().parent.parent / ".dsh-home" / "trajectories"


def _ensure_dir() -> Path:
    TRAJ_DIR.mkdir(parents=True, exist_ok=True)
    return TRAJ_DIR


def new_session_id() -> str:
    """生成单调递增的 session_id，便于排序。"""
    return f"sess_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"


def append(session_id: str, event_type: str, payload: Dict[str, Any]) -> None:
    """追加一条事件。event_type 取值参考 spec FR-23。"""
    _ensure_dir()
    path = TRAJ_DIR / f"{session_id}.jsonl"
    record = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
        "type": event_type,
        "payload": payload,
    }
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def read(session_id: str) -> List[Dict[str, Any]]:
    """读取某次 session 的全部事件（按时间顺序）。"""
    path = TRAJ_DIR / f"{session_id}.jsonl"
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def list_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    """列出最近的 session（前端调试视图用）。"""
    _ensure_dir()
    files = sorted(TRAJ_DIR.glob("sess_*.jsonl"), reverse=True)[:limit]
    out = []
    for p in files:
        events = read(p.stem)
        if not events:
            continue
        first = events[0]
        out.append({
            "session_id": p.stem,
            "start_ts": first.get("ts"),
            "event_count": len(events),
            "types": [e.get("type") for e in events[:8]],
        })
    return out

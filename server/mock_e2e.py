"""端到端 mock 服务器（Task 12 / TR-12.2, TR-12.3, TR-12.4 验证用）

模拟后端 /generate、/trajectory/{session_id}、/trajectory/replay/{session_id}。
不调用真实 LLM，返回固定 plan + sources + warnings + 5 类 trajectory 事件。

用法：
  .venv/bin/python server/mock_e2e.py
  # 在浏览器设置中切到"后端增强模式"，后端地址 http://localhost:8000
  # 然后在生成页提交，前端会收到这套 mock 数据
"""
from __future__ import annotations
import json
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse as parse_url
import asyncio
import threading

# ====== 固定 mock 数据 ======
MOCK_PLAN = {
    "overview": {
        "title": "济南3日齐鲁文化之旅（mock）",
        "dates": "2026-10-01 至 2026-10-03",
        "days": 3,
        "travelers": 2,
        "departure": "北京",
        "route_theme": "齐鲁文化与泉水风光",
        "highlights": ["趵突泉", "大明湖", "千佛山", "山东博物馆"],
        "mileage": "市内公共交通",
        "suitable_people": "文化爱好者、家庭出行",
        "tips": "10 月济南早晚凉，备薄外套"
    },
    "route": [
        {"name": "济南", "day": "Day 1"},
        {"name": "曲阜", "day": "Day 2"},
        {"name": "济南", "day": "Day 3"},
    ],
    "daily": [
        {
            "day": 1, "date": "2026-10-01", "city": "济南",
            "title": "泉水老城", "subtitle": "趵突泉 + 大明湖",
            "attractions": [
                {"name": "趵突泉", "desc": "天下第一泉", "duration": "2h", "ticket": "¥40",
                 "tags": ["泉水", "5A"], "image_query": "Baotu Spring",
                 "source_url": "https://zh.wikipedia.org/wiki/趵突泉",
                 "source_type": "wikipedia"},
                {"name": "大明湖", "desc": "济南三大名胜之一", "duration": "2h", "ticket": "免费",
                 "tags": ["湖泊"], "image_query": "Daming Lake",
                 "source_url": "https://zh.wikipedia.org/wiki/大明湖",
                 "source_type": "wikipedia"},
            ],
            "food": [
                {"name": "把子肉", "desc": "济南名吃", "image_query": "Jinan bazi rou",
                 "source_url": "https://example.com/jinan-food",
                 "source_type": "generic"},
            ],
            "transport": "高铁北京→济南 1.5h，市内公交",
            "accommodation": "泉城广场附近酒店"
        },
        {
            "day": 2, "date": "2026-10-02", "city": "曲阜",
            "title": "三孔文化", "subtitle": "孔庙+孔府+孔林",
            "attractions": [
                {"name": "孔庙", "desc": "世界文化遗产", "duration": "3h", "ticket": "¥140",
                 "tags": ["世界遗产"], "image_query": "Qufu Confucius Temple",
                 "source_url": "https://zh.wikipedia.org/wiki/孔庙",
                 "source_type": "wikipedia"},
            ],
            "food": [],
            "transport": "济南→曲阜 高铁 30min",
            "accommodation": "曲阜古城民宿"
        },
        {
            "day": 3, "date": "2026-10-03", "city": "济南",
            "title": "山博与千佛山", "subtitle": "文化收尾",
            "attractions": [
                {"name": "山东博物馆", "desc": "省博国家一级", "duration": "2h", "ticket": "免费",
                 "tags": ["博物馆"], "image_query": "Shandong Museum",
                 "source_url": "https://zh.wikipedia.org/wiki/山东博物馆",
                 "source_type": "wikipedia"},
            ],
            "food": [],
            "transport": "市内地铁",
            "accommodation": "返程"
        }
    ],
    "attractions": [
        {"name": "趵突泉", "desc": "天下第一泉", "duration": "2h", "ticket": "¥40",
         "tags": ["泉水"], "image_query": "Baotu Spring",
         "source_url": "https://zh.wikipedia.org/wiki/趵突泉"},
        {"name": "孔庙", "desc": "世界文化遗产", "duration": "3h", "ticket": "¥140",
         "tags": ["世界遗产"], "image_query": "Qufu Confucius Temple",
         "source_url": "https://zh.wikipedia.org/wiki/孔庙"},
    ],
    "accommodation": [
        {"name": "泉城大酒店", "area": "历下区", "price_range": "¥400-600/晚",
         "desc": "近泉城广场", "source_url": "https://example.com/hotel-1"},
    ],
    "food": [
        {"name": "把子肉", "desc": "济南名吃", "image_query": "Jinan bazi rou",
         "source_url": "https://example.com/jinan-food"},
    ],
    "budget": {
        "accommodation": 1200, "transport": 600, "food": 500,
        "tickets": 220, "other": 200, "total": 2720, "per_person": 1360
    },
    "tips": ["10 月早晚凉备薄外套", "泉水景区人多早出发", "高铁提前订票"]
}

MOCK_SOURCES = [
    {"url": "https://zh.wikipedia.org/wiki/趵突泉", "title": "趵突泉 - 维基百科"},
    {"url": "https://zh.wikipedia.org/wiki/大明湖", "title": "大明湖 - 维基百科"},
    {"url": "https://zh.wikipedia.org/wiki/孔庙", "title": "孔庙 - 维基百科"},
]

MOCK_WARNINGS = [
    {"level": "medium", "field": "budget.transport",
     "msg": "高铁票价为估算值，建议核实实时票价"},
    {"level": "low", "field": "attractions.大明湖.ticket",
     "msg": "大明湖免费开放区域可能有调整"},
]

# session_id -> events
_TRAJECTORIES: dict[str, list] = {}
# destination -> session_id（用于模拟 plan-level 缓存命中）
_PLAN_CACHE: dict[str, str] = {}

# plan_id -> [{version_id, plan, trigger_reason, diff, adopted, ts}]（模拟版本快照）
_PLAN_VERSIONS: dict[str, list] = {}
# plan_id -> [websocket handler 回调]（用于 mock 主动推送 diff）
_WS_SUBSCRIBERS: dict[str, list] = {}

# 模拟一次 monitor 周期产出的固定 diff（FR-29 / AC-14）
MOCK_MONITOR_DIFF = [
    {
        "op": "SWAP",
        "day": 3,
        "target_field": "attractions",
        "old_item": {"name": "山东博物馆"},
        "new_item": {
            "name": "济南市博物馆",
            "desc": "雷阵雨室内备选：济南市博物馆，免费开放，含济南历史陈列",
            "duration": "2h",
            "ticket": "免费",
            "tags": ["博物馆", "室内"],
            "image_query": "Jinan Museum",
            "source_url": "https://example.com/jinan-museum",
            "source_type": "generic",
            "source_title": "济南市博物馆官方页",
        },
        "reason": "明日济南有雷阵雨（降水概率 80%），将山东博物馆 → 济南市博物馆（室内备选）",
    }
]
MOCK_MONITOR_DATA = {
    "ts": None,  # 运行时填
    "destination": "济南",
    "weather": {"days": [{"date": "2026-10-03", "is_rain": True, "precip_prob": 80,
                          "weather_code": 61, "tmax": 22, "tmin": 16}]},
    "hotlist_count": 1,
    "hotlist": [{"name": "济南市博物馆", "source_url": "https://example.com/jinan-museum"}],
}


def _new_version_id() -> str:
    return f"v_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"


def _save_version(plan_id: str, plan: dict, *, trigger_reason: str,
                  diff: list = None, adopted: bool = True) -> str:
    """保存版本快照（mock 版，模拟 plan_store.save_version）。"""
    versions = _PLAN_VERSIONS.setdefault(plan_id, [])
    if adopted:
        for v in versions:
            v["adopted"] = False
    vid = _new_version_id()
    versions.append({
        "version_id": vid, "plan_id": plan_id,
        "ts": time.time(), "trigger_reason": trigger_reason,
        "diff": diff or [], "plan": plan, "adopted": adopted,
    })
    return vid


def _latest_version(plan_id: str) -> dict | None:
    versions = _PLAN_VERSIONS.get(plan_id, [])
    for v in reversed(versions):
        if v.get("adopted"):
            return v
    return versions[-1] if versions else None


def _broadcast_ws(plan_id: str, msg: dict) -> None:
    """模拟 WebSocket 推送。

    BaseHTTPRequestHandler 不原生支持 WebSocket，
    这里仅记录日志并保留订阅者占位（前端通过 triggerOptimize 主动拉取）。
    """
    subs = _WS_SUBSCRIBERS.get(plan_id, [])
    print(f"[mock_ws] plan_id={plan_id} subs={len(subs)} msg.type={msg.get('type')}")
    # 若有真实订阅者回调（如未来扩展为 long-poll / SSE），逐个调用
    for cb in subs:
        try:
            cb(msg)
        except Exception as e:
            print(f"[mock_ws] callback error: {e}")


def _apply_diff_mock(plan: dict, diff: list) -> dict:
    """简化 apply_diff，仅处理 SWAP/ADD/MOVE on daily[*].attractions/food。"""
    import copy
    new_plan = copy.deepcopy(plan)
    daily = new_plan.get("daily", []) or []
    for op in diff:
        try:
            day_idx = int(op.get("day", 0))
            field = op.get("target_field")
            if day_idx <= 0 or field not in ("attractions", "food"):
                continue
            day = next((d for d in daily if d.get("day") == day_idx), None)
            if not day:
                continue
            items = day.setdefault(field, [])
            new_item = op.get("new_item") or {}
            old_item = op.get("old_item") or {}
            opk = (op.get("op") or "").upper()
            if opk == "ADD" and new_item:
                items.append(new_item)
            elif opk == "SWAP" and new_item:
                target_name = old_item.get("name")
                replaced = False
                for i, it in enumerate(items):
                    if isinstance(it, dict) and it.get("name") == target_name:
                        items[i] = new_item
                        replaced = True
                        break
                if not replaced:
                    items.append(new_item)
            elif opk == "MOVE" and old_item:
                target_name = old_item.get("name")
                idx = next((i for i, it in enumerate(items)
                           if isinstance(it, dict) and it.get("name") == target_name), -1)
                if idx >= 0 and new_item:
                    items.pop(idx)
                    items.append(new_item)
        except Exception:
            continue
    return new_plan


def _make_trajectory_events(session_id: str) -> list:
    base_ts = time.time()
    events = [
        {"ts": base_ts + 0.1, "iso": _iso(base_ts + 0.1),
         "type": "system_prompt", "payload": {"content": "你是 AI 旅行手册编排大脑"}},
        {"ts": base_ts + 0.5, "iso": _iso(base_ts + 0.5),
         "type": "tg-planner.start", "payload": {"destination": "济南", "prefs": {"days": 3}}},
        {"ts": base_ts + 1.0, "iso": _iso(base_ts + 1.0),
         "type": "tg-planner.tasks", "payload": {
             "tasks": [
                 {"target_url": "https://zh.wikipedia.org/wiki/趵突泉",
                  "source_type": "wikipedia", "query": "趵突泉"}],
             "tokens": {"prompt_tokens": 320, "completion_tokens": 180, "total_tokens": 500},
             "elapsed_ms": 850,
             "llm_model": "deepseek-chat",
         }},
        {"ts": base_ts + 2.0, "iso": _iso(base_ts + 2.0),
         "type": "tg-scraper.batch", "payload": {"tasks": 1, "materials": 3}},
        {"ts": base_ts + 3.5, "iso": _iso(base_ts + 3.5),
         "type": "tg-integrator.start", "payload": {"materials_count": 3}},
        {"ts": base_ts + 5.0, "iso": _iso(base_ts + 5.0),
         "type": "tg-integrator.done", "payload": {
             "daily_count": 3, "attractions_count": 2,
             "tokens": {"prompt_tokens": 2100, "completion_tokens": 3400, "total_tokens": 5500},
             "elapsed_ms": 4200,
             "llm_model": "deepseek-chat",
         }},
        {"ts": base_ts + 5.5, "iso": _iso(base_ts + 5.5),
         "type": "tg-validator.start", "payload": {}},
        {"ts": base_ts + 6.5, "iso": _iso(base_ts + 6.5),
         "type": "tg-validator.done", "payload": {
             "warnings_count": 2,
             "tokens": {"prompt_tokens": 1800, "completion_tokens": 220, "total_tokens": 2020},
             "elapsed_ms": 1100,
             "llm_model": "deepseek-chat",
         }},
        {"ts": base_ts + 6.6, "iso": _iso(base_ts + 6.6),
         "type": "tg-output.done", "payload": {"sources_count": 3}},
    ]
    return events


def _iso(ts: float) -> str:
    import datetime as _dt
    return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%S%z")


class MockHandler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LLM-Config")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        path = parse_url(self.path).path
        if path == "/health":
            body = json.dumps({"status": "ok", "dsh": "mock", "ts": time.time()}).encode()
            self._send_json(200, body)
            return
        # /sessions?limit=50
        if path == "/sessions":
            # 列出最近的 session，按 session_id 倒序
            sessions = []
            for sid in sorted(_TRAJECTORIES.keys(), reverse=True)[:50]:
                events = _TRAJECTORIES.get(sid, [])
                if not events:
                    continue
                first = events[0]
                sessions.append({
                    "session_id": sid,
                    "start_ts": first.get("ts"),
                    "event_count": len(events),
                    "types": [e.get("type") for e in events[:8]],
                })
            body = json.dumps({"sessions": sessions}, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        # /trajectory/{session_id}
        if path.startswith("/trajectory/") and not path.startswith("/trajectory/replay/"):
            sid = path.rsplit("/", 1)[-1]
            events = _TRAJECTORIES.get(sid, [])
            body = json.dumps({"session_id": sid, "events": events, "count": len(events)},
                              ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        # /plan/{plan_id}/versions
        if path.startswith("/plan/") and path.endswith("/versions"):
            parts = path.split("/")
            plan_id = parts[2] if len(parts) > 2 else ""
            versions = _PLAN_VERSIONS.get(plan_id, [])
            body = json.dumps({
                "plan_id": plan_id,
                "versions": [{
                    "version_id": v["version_id"],
                    "plan_id": v["plan_id"],
                    "ts": v["ts"],
                    "trigger_reason": v["trigger_reason"],
                    "adopted": v["adopted"],
                } for v in versions],
            }, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        self._send_json(404, json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        path = parse_url(self.path).path
        if path == "/generate":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length) or b"{}")
            except Exception:
                payload = {}
            destination = (payload.get("destination") or "").strip()
            plan_id = payload.get("plan_id") or f"plan_{int(time.time()*1000)}"
            # 模拟 plan-level 缓存命中（TR-16.1）：相同 destination 第二次直接复用
            cached_sid = _PLAN_CACHE.get(destination) if destination else None
            if cached_sid and cached_sid in _TRAJECTORIES:
                # 缓存命中也写一份版本快照便于演示
                vid = _save_version(plan_id, MOCK_PLAN, trigger_reason="initial_generate")
                body = json.dumps({
                    "plan": MOCK_PLAN,
                    "sources": MOCK_SOURCES,
                    "warnings": MOCK_WARNINGS,
                    "session_id": cached_sid,
                    "source_coverage": {"total": 6, "with_url": 6},
                    "cached": True,
                    "plan_id": plan_id,
                    "version_id": vid,
                }, ensure_ascii=False).encode()
                self._send_json(200, body)
                return
            session_id = f"sess_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
            _TRAJECTORIES[session_id] = _make_trajectory_events(session_id)
            if destination:
                _PLAN_CACHE[destination] = session_id
            # 写入初始版本快照（Task 21 / FR-32）
            vid = _save_version(plan_id, MOCK_PLAN, trigger_reason="initial_generate")
            body = json.dumps({
                "plan": MOCK_PLAN,
                "sources": MOCK_SOURCES,
                "warnings": MOCK_WARNINGS,
                "session_id": session_id,
                "source_coverage": {"total": 6, "with_url": 6},
                "plan_id": plan_id,
                "version_id": vid,
            }, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        # /plan/{plan_id}/optimize
        if path.startswith("/plan/") and path.endswith("/optimize"):
            parts = path.split("/")
            plan_id = parts[2] if len(parts) > 2 else ""
            cur = _latest_version(plan_id)
            if not cur:
                self._send_json(404, json.dumps({"error": "plan not found"}).encode())
                return
            # 应用固定 mock diff
            new_plan = _apply_diff_mock(cur["plan"], MOCK_MONITOR_DIFF)
            new_vid = _save_version(plan_id, new_plan,
                                     trigger_reason="monitor_optimize",
                                     diff=MOCK_MONITOR_DIFF)
            # 推送 diff 给 WebSocket 订阅者（模拟即时推送）
            ws_msg = {
                "type": "optimize_diff",
                "plan_id": plan_id,
                "diff": MOCK_MONITOR_DIFF,
                "new_version_id": new_vid,
                "applied_count": len(MOCK_MONITOR_DIFF),
                "reason": "monitor_optimize",
                "source_url": MOCK_MONITOR_DIFF[0]["new_item"].get("source_url"),
                "explanation": MOCK_MONITOR_DIFF[0]["reason"],
            }
            _broadcast_ws(plan_id, ws_msg)
            body = json.dumps({
                "plan_id": plan_id,
                "new_version_id": new_vid,
                "diff": MOCK_MONITOR_DIFF,
                "applied_count": len(MOCK_MONITOR_DIFF),
                "plan": new_plan,
            }, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        # /plan/{plan_id}/revert/{version_id}
        if path.startswith("/plan/") and "/revert/" in path:
            parts = path.split("/")
            plan_id = parts[2] if len(parts) > 2 else ""
            target_vid = parts[4] if len(parts) > 4 else ""
            target = next((v for v in _PLAN_VERSIONS.get(plan_id, [])
                          if v["version_id"] == target_vid), None)
            if not target:
                self._send_json(404, json.dumps({"error": "version not found"}).encode())
                return
            new_vid = _save_version(plan_id, target["plan"],
                                     trigger_reason=f"revert_to_{target_vid}",
                                     diff=[{"op": "REVERT", "target_version": target_vid}])
            body = json.dumps({
                "plan_id": plan_id,
                "new_version_id": new_vid,
                "plan": target["plan"],
                "reverted_from": target_vid,
            }, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        # /trajectory/replay/{session_id}
        if path.startswith("/trajectory/replay/"):
            old_sid = path.rsplit("/", 1)[-1]
            old_events = _TRAJECTORIES.get(old_sid, [])
            new_sid = f"sess_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
            # 简化 replay：复制旧事件到新 session
            _TRAJECTORIES[new_sid] = [
                {**e, "ts": e["ts"] + 100, "iso": _iso(e["ts"] + 100),
                 "type": e.get("type", "replayed")} for e in old_events
            ]
            body = json.dumps({
                "new_session_id": new_sid,
                "replayed_count": len(old_events)
            }, ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        self._send_json(404, json.dumps({"error": "not found"}).encode())

    def _send_json(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self._cors()
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[mock] {args[0]}")


if __name__ == "__main__":
    port = 8000
    print(f"[mock_e2e] 后端 mock 端到端服务器运行在 http://localhost:{port}")
    print("[mock_e2e] 在前端设置中切到「后端增强模式」、后端地址保持 http://localhost:8000")
    print("[mock_e2e] 然后提交生成，可看到完整 mock plan + 3 来源 + 2 校对提示")
    print("[mock_e2e] 提交后切到「调试」视图可拉取 trajectory 时间线（9 事件 / 8 类）")
    HTTPServer(("0.0.0.0", port), MockHandler).serve_forever()

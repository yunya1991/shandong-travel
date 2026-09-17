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


def _make_trajectory_events(session_id: str) -> list:
    base_ts = time.time()
    events = [
        {"ts": base_ts + 0.1, "iso": _iso(base_ts + 0.1),
         "type": "system_prompt", "payload": {"content": "你是 AI 旅行手册编排大脑"}},
        {"ts": base_ts + 0.5, "iso": _iso(base_ts + 0.5),
         "type": "tg-planner.start", "payload": {"destination": "济南", "prefs": {"days": 3}}},
        {"ts": base_ts + 1.0, "iso": _iso(base_ts + 1.0),
         "type": "tg-planner.tasks", "payload": {"tasks": [
             {"target_url": "https://zh.wikipedia.org/wiki/趵突泉",
              "source_type": "wikipedia", "query": "趵突泉"}]}},
        {"ts": base_ts + 2.0, "iso": _iso(base_ts + 2.0),
         "type": "tg-scraper.batch", "payload": {"tasks": 1, "materials": 3}},
        {"ts": base_ts + 3.5, "iso": _iso(base_ts + 3.5),
         "type": "tg-integrator.start", "payload": {"materials_count": 3}},
        {"ts": base_ts + 5.0, "iso": _iso(base_ts + 5.0),
         "type": "tg-integrator.done", "payload": {"daily_count": 3, "attractions_count": 2}},
        {"ts": base_ts + 5.5, "iso": _iso(base_ts + 5.5),
         "type": "tg-validator.start", "payload": {}},
        {"ts": base_ts + 6.5, "iso": _iso(base_ts + 6.5),
         "type": "tg-validator.done", "payload": {"warnings_count": 2}},
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
        # /trajectory/{session_id}
        if path.startswith("/trajectory/"):
            sid = path.rsplit("/", 1)[-1]
            events = _TRAJECTORIES.get(sid, [])
            body = json.dumps({"session_id": sid, "events": events, "count": len(events)},
                              ensure_ascii=False).encode()
            self._send_json(200, body)
            return
        self._send_json(404, json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        path = parse_url(self.path).path
        if path == "/generate":
            session_id = f"sess_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
            _TRAJECTORIES[session_id] = _make_trajectory_events(session_id)
            body = json.dumps({
                "plan": MOCK_PLAN,
                "sources": MOCK_SOURCES,
                "warnings": MOCK_WARNINGS,
                "session_id": session_id,
                "source_coverage": {"total": 6, "with_url": 6},
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

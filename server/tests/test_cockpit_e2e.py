"""DSH Web UI 驾驶舱 + 动态优化引擎端到端测试（Task 22 / Task 22+ / Task 23）

覆盖：
- TR-22.1: cockpit_state 三类视图聚合（思考轨迹 + 待审建议 + 阈值配置）
- TR-22.2: 采纳建议 → 应用 diff → 广播 → 同步前端
- TR-22.3: 编辑建议 diff 后采纳 → 前端按编辑后版本更新
- Task 22+ 完善：
  * cockpit_state.active_suggestions 包含 pending + edited 状态
  * adopt 复用 pending_version_id（避免重复 apply_diff）
  * reject / adopt 后推送 optimize_suggestion_resolved 通知前端清理徽章
  * monitor 建议模式 demote pending 版本（保留原 adopted 不阻塞回滚）
  * monitor auto 模式直接广播 diff
  * mark_adopted / demote_version 行为正确性
- Task 23：
  * FR-33 协同冲突避让：user_edit 后 monitor 跳过对应 (day, field)
  * 变更说明浮层位置（前端 JS 部分，后端只验 broadcast 不验 DOM）
  * 同城热榜多源拉取 + 失败降级（不抛异常）
  * changelog 聚合端点 + diff_versions 跨版本对比

跑法：
    cd server && .venv/bin/python -m tests.test_cockpit_e2e
"""
from __future__ import annotations
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# ====== 测试辅助：mock FastAPI app 与 WebSocket ======
class _MockWebSocket:
    """模拟 FastAPI WebSocket，记录所有 send_text 调用供断言。"""
    def __init__(self):
        self.sent = []
        self._accepted = False

    async def accept(self):
        self._accepted = True

    async def send_text(self, msg: str):
        self.sent.append(msg)

    async def receive_text(self):
        # 测试不需要 receive
        await asyncio.sleep(0.01)
        return "{}"


class _MockRequest:
    """模拟 FastAPI Request，body 可异步读取。"""
    def __init__(self, body: dict):
        self._body = body

    async def json(self):
        return self._body


class _MockPlanStore:
    """内存版 plan_store 替身，避免污染 SQLite。"""
    def __init__(self):
        self.versions = {}  # version_id -> dict(plan_id, plan, adopted, ts, ...)
        self.by_plan = {}  # plan_id -> [version_id, ...]

    def save_plan(self, plan_id, session_id, destination, prefs):
        pass  # mock 不持久化

    def save_version(self, plan_id, plan, parent_version_id=None,
                     trigger_reason=None, diff=None, adopted=True):
        import time, uuid
        vid = f"ver_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
        self.versions[vid] = {
            "version_id": vid, "plan_id": plan_id, "plan": plan,
            "parent_version_id": parent_version_id, "ts": time.time(),
            "trigger_reason": trigger_reason, "diff": diff or [],
            "adopted": adopted,
        }
        self.by_plan.setdefault(plan_id, []).append(vid)
        return vid

    def get_version(self, vid):
        return self.versions.get(vid)

    def list_versions(self, plan_id, limit=50):
        return [self.versions[v] for v in self.by_plan.get(plan_id, [])[-limit:]]

    def latest_version_id(self, plan_id):
        for v in reversed(self.by_plan.get(plan_id, [])):
            if self.versions[v]["adopted"]:
                return v
        return None

    def mark_adopted(self, plan_id, version_id):
        v = self.versions.get(version_id)
        if not v or v["plan_id"] != plan_id:
            return False
        for vid in self.by_plan.get(plan_id, []):
            self.versions[vid]["adopted"] = False
        v["adopted"] = True
        return True

    def demote_version(self, version_id):
        v = self.versions.get(version_id)
        if not v:
            return False
        v["adopted"] = False
        return True


async def _setup_modules(monkey_env: dict = None):
    """初始化 plan_store SQLite + 设置环境变量。"""
    # 用临时 DB 路径，避免污染既有数据
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    from app import plan_store as ps
    ps.DB_PATH = Path(tmp.name)
    ps.init_db()

    # 默认配置
    if monkey_env:
        for k, v in monkey_env.items():
            os.environ[k] = v


def _cleanup(tmp_path):
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


# ====== 测试用例 ======

async def test_cockpit_state_returns_active_suggestions():
    """TR-22.1 + Task 22+：cockpit_state 同时返回 pending_suggestions（兼容）与 active_suggestions（pending+edited）。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store
    from app.routes import _add_suggestion

    plan_id = "test_plan_1"
    plan_store.save_plan(plan_id, "sess_x1", "济南", {})
    plan_store.save_version(plan_id, {"overview": {"title": "T"}}, trigger_reason="initial_generate", adopted=True)

    # 塞 pending 建议
    sid1 = _add_suggestion(plan_id, {
        "diff": [{"op": "SWAP", "day": 1, "target_field": "attractions",
                  "old_item": {"name": "A"}, "new_item": {"name": "B"}}],
        "reason": "test_pending", "session_id": "sess_x1",
    })
    # 塞 edited 建议
    sid2 = _add_suggestion(plan_id, {
        "diff": [{"op": "ADD", "day": 2, "target_field": "food",
                  "new_item": {"name": "C"}}],
        "reason": "test_edited", "session_id": "sess_x1",
    })
    routes._pending_suggestions[plan_id][-1]["status"] = "edited"

    # 调 cockpit_state
    from app.routes import cockpit_state
    resp = await cockpit_state(plan_id)
    data = json.loads(resp.body)

    assert data["plan_id"] == plan_id
    assert "current_version_id" in data
    assert len(data["trajectory_events"]) >= 0
    # 兼容字段：仅 pending
    pending_ids = [s["suggestion_id"] for s in data["pending_suggestions"]]
    assert sid1 in pending_ids
    assert sid2 not in pending_ids, "pending_suggestions 不应包含 edited"
    # 新字段：pending + edited
    active_ids = [s["suggestion_id"] for s in data["active_suggestions"]]
    assert sid1 in active_ids, "active_suggestions 应包含 pending"
    assert sid2 in active_ids, "active_suggestions 应包含 edited"
    # threshold_config 字段存在
    assert data["threshold_config"]["dynamic_mode"] == "suggest"
    print("[TR-22.1 + Task22+] PASS: cockpit_state 返回 pending + edited 建议")


async def test_adopt_reuses_pending_version_id():
    """Task 22+：monitor 建议模式产出的 pending 版本，cockpit adopt 时复用，避免重复 apply_diff。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store
    from app.routes import _add_suggestion, adopt_suggestion, broadcast_diff

    plan_id = "test_plan_2"
    plan_store.save_plan(plan_id, "sess_x2", "济南", {})
    initial_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "山东博物馆"}]}]}
    init_vid = plan_store.save_version(plan_id, initial_plan,
                                        trigger_reason="initial_generate", adopted=True)

    # 模拟 monitor 建议模式产出 diff：
    # 1) monitor 先调 dsh_runner.optimize_with_monitor_data → save_version(adopted=True)
    # 2) monitor 调 plan_store.demote_version 改 adopted=False
    # 3) monitor 把 pending_version_id 写到 suggestion
    monitor_diff = [{"op": "SWAP", "day": 1, "target_field": "attractions",
                     "old_item": {"name": "山东博物馆"},
                     "new_item": {"name": "济南市博物馆",
                                  "source_url": "https://example.com/jinan-museum"},
                     "reason": "雷阵雨"}]
    new_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "济南市博物馆"}]}]}
    pending_vid = plan_store.save_version(plan_id, new_plan,
                                          parent_version_id=init_vid,
                                          trigger_reason="monitor_optimize",
                                          diff=monitor_diff, adopted=True)
    plan_store.demote_version(pending_vid)

    # 断言：demote 后 latest_version_id 仍指向 init_vid
    assert plan_store.latest_version_id(plan_id) == init_vid, \
        "demote 后 latest_version_id 应回到 initial_generate 版本"

    # 把 pending_vid 塞到建议
    sid = _add_suggestion(plan_id, {
        "diff": monitor_diff, "reason": "monitor_optimize",
        "source_url": "https://example.com/jinan-museum",
        "session_id": "sess_x2", "pending_version_id": pending_vid,
    })

    # 注入一个 mock WebSocket 订阅者，捕获广播
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    # 调 adopt
    resp = await adopt_suggestion(plan_id, sid)
    data = json.loads(resp.body)

    assert data["status"] == "adopted"
    assert data["reuse"] == "reused_pending_version", \
        f"应复用 pending_version_id，实际 reuse={data['reuse']}"
    assert data["new_version_id"] == pending_vid, \
        "采纳后 version_id 应等于 pending_vid（复用）"

    # 断言：adopt 后 latest_version_id 升级回 pending_vid
    assert plan_store.latest_version_id(plan_id) == pending_vid, \
        "adopt 后 latest_version_id 应升级为 pending_vid"

    # 断言：suggestion 状态已 adopted
    sug = routes._find_suggestion(plan_id, sid)
    assert sug["status"] == "adopted"
    assert sug["adopted_version_id"] == pending_vid

    # 断言：广播了两条消息（optimize_diff + optimize_suggestion_resolved）
    assert len(mock_ws.sent) >= 2, f"应广播 optimize_diff + resolved 两条，实际 {len(mock_ws.sent)}"
    diff_msg = json.loads(mock_ws.sent[0])
    resolved_msg = json.loads(mock_ws.sent[1])
    assert diff_msg["type"] == "optimize_diff"
    assert diff_msg["plan_id"] == plan_id
    assert diff_msg["new_version_id"] == pending_vid
    assert diff_msg["origin"] == "cockpit"
    assert resolved_msg["type"] == "optimize_suggestion_resolved"
    assert resolved_msg["action"] == "adopted"
    print("[Task22+] PASS: adopt 复用 pending_version_id，避免重复 apply_diff")


async def test_adopt_edited_falls_back_to_apply_diff():
    """TR-22.3 + Task 22+：编辑后的建议（status=edited）采纳时走标准 apply_diff 路径。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store, dsh_runner
    from app.routes import _add_suggestion, edit_suggestion, adopt_suggestion

    plan_id = "test_plan_3"
    plan_store.save_plan(plan_id, "sess_x3", "济南", {})
    initial_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "山东博物馆"}]}]}
    init_vid = plan_store.save_version(plan_id, initial_plan,
                                        trigger_reason="initial_generate", adopted=True)

    # 塞一条 pending 建议（含 pending_version_id）
    monitor_diff = [{"op": "SWAP", "day": 1, "target_field": "attractions",
                     "old_item": {"name": "山东博物馆"},
                     "new_item": {"name": "济南市博物馆",
                                  "source_url": "https://example.com/jinan-museum"},
                     "reason": "雷阵雨"}]
    pending_vid = plan_store.save_version(plan_id, initial_plan,
                                          parent_version_id=init_vid,
                                          trigger_reason="monitor_optimize",
                                          diff=monitor_diff, adopted=True)
    plan_store.demote_version(pending_vid)
    sid = _add_suggestion(plan_id, {
        "diff": monitor_diff, "reason": "monitor_optimize",
        "session_id": "sess_x3", "pending_version_id": pending_vid,
    })

    # 用户在驾驶舱编辑 diff（替换为千佛山）
    edited_diff = [{"op": "SWAP", "day": 1, "target_field": "attractions",
                     "old_item": {"name": "山东博物馆"},
                     "new_item": {"name": "千佛山",
                                  "source_url": "https://example.com/qianfoshan"},
                     "reason": "用户编辑：换为千佛山"}]
    edit_resp = await edit_suggestion(plan_id, sid,
                                       _MockRequest({"diff": edited_diff, "reason": "edited_by_user"}))
    edit_data = json.loads(edit_resp.body)
    assert edit_data["status"] == "edited"
    assert edit_data["diff"] == edited_diff

    # 调 adopt：因为 status=edited，应走 fresh_apply_diff 路径
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    adopt_resp = await adopt_suggestion(plan_id, sid)
    adopt_data = json.loads(adopt_resp.body)
    assert adopt_data["reuse"] == "fresh_apply_diff", \
        f"edited 状态应走 fresh_apply_diff，实际 {adopt_data['reuse']}"
    assert adopt_data["new_version_id"] != pending_vid, \
        "edited 后 adopt 应产生新 version_id，不复用 pending_vid"

    # 断言：新 plan 包含千佛山
    new_v = plan_store.get_version(adopt_data["new_version_id"])
    assert new_v["plan"]["daily"][0]["attractions"][0]["name"] == "千佛山"
    # 断言：广播的 diff 是编辑后的版本
    diff_msg = json.loads(mock_ws.sent[0])
    assert diff_msg["type"] == "optimize_diff"
    assert diff_msg["diff"][0]["new_item"]["name"] == "千佛山"
    print("[TR-22.3 + Task22+] PASS: edited 建议 adopt 走 fresh_apply_diff 路径")


async def test_reject_clears_pending_version():
    """TR-22.2 + Task 22+：reject 不应用 diff，但通知前端清理徽章 + demote pending 版本。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store
    from app.routes import _add_suggestion, reject_suggestion

    plan_id = "test_plan_4"
    plan_store.save_plan(plan_id, "sess_x4", "济南", {})
    initial_plan = {"overview": {"title": "济南"}}
    init_vid = plan_store.save_version(plan_id, initial_plan,
                                        trigger_reason="initial_generate", adopted=True)

    # 塞 pending 建议
    monitor_diff = [{"op": "ADD", "day": 1, "target_field": "food",
                     "new_item": {"name": "把子肉"}}]
    pending_vid = plan_store.save_version(plan_id, initial_plan,
                                          parent_version_id=init_vid,
                                          trigger_reason="monitor_optimize",
                                          diff=monitor_diff, adopted=True)
    plan_store.demote_version(pending_vid)
    sid = _add_suggestion(plan_id, {
        "diff": monitor_diff, "reason": "test_reject",
        "session_id": "sess_x4", "pending_version_id": pending_vid,
    })

    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    resp = await reject_suggestion(plan_id, sid)
    data = json.loads(resp.body)
    assert data["status"] == "rejected"

    # 断言：suggestion 状态已 rejected
    sug = routes._find_suggestion(plan_id, sid)
    assert sug["status"] == "rejected"

    # 断言：latest_version_id 仍指向 init_vid（未被 adopt）
    assert plan_store.latest_version_id(plan_id) == init_vid

    # 断言：广播了 optimize_suggestion_resolved 通知前端清理徽章
    assert len(mock_ws.sent) >= 1
    resolved_msg = json.loads(mock_ws.sent[0])
    assert resolved_msg["type"] == "optimize_suggestion_resolved"
    assert resolved_msg["action"] == "rejected"
    print("[TR-22.2 + Task22+] PASS: reject 不应用 diff + 推送 resolved 通知")


async def test_monitor_auto_mode_broadcasts_diff():
    """Task 22+：auto 模式下 monitor 产出 diff 直接广播前端，不暂存 pending。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "auto", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store, monitor
    from app.dsh_runner import apply_diff

    plan_id = "test_plan_5"
    plan_store.save_plan(plan_id, "sess_x5", "济南", {})
    initial_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "山东博物馆"}]}]}
    plan_store.save_version(plan_id, initial_plan,
                            trigger_reason="initial_generate", adopted=True)

    # 注入 monitor 元数据 + mock WebSocket
    monitor._meta[plan_id] = {
        "llm_cfg": {"base_url": "", "api_key": "", "model": "test"},
        "plan": initial_plan, "whitelist": ["attractions"],
    }
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    # Mock dsh_runner.optimize_with_monitor_data：直接返回 diff（不走真实 LLM）
    from app import dsh_runner
    diff = [{"op": "SWAP", "day": 1, "target_field": "attractions",
             "old_item": {"name": "山东博物馆"},
             "new_item": {"name": "济南市博物馆",
                          "source_url": "https://example.com/jinan-museum"},
             "reason": "auto mode test"}]
    new_plan = apply_diff(initial_plan, diff)
    new_vid = plan_store.save_version(plan_id, new_plan,
                                       trigger_reason="monitor_optimize",
                                       diff=diff, adopted=True)

    async def mock_optimize(*args, **kwargs):
        return {"plan_id": plan_id, "new_version_id": new_vid,
                "diff": diff, "applied_count": 1, "plan": new_plan}
    dsh_runner.optimize_with_monitor_data = mock_optimize

    # 调 _maybe_optimize
    await monitor._maybe_optimize(plan_id, {"ts": 0, "weather": {"days": []},
                                            "hotlist_count": 0},
                                   monitor._meta[plan_id], "sess_x5")

    # 断言：auto 模式直接广播了 optimize_diff
    assert len(mock_ws.sent) >= 1
    diff_msg = json.loads(mock_ws.sent[0])
    assert diff_msg["type"] == "optimize_diff"
    assert diff_msg["origin"] == "monitor_auto"
    assert diff_msg["plan_id"] == plan_id
    # 不应有 suggestion pending（auto 模式不暂存）
    assert len(routes._pending_suggestions.get(plan_id, [])) == 0
    print("[Task22+] PASS: auto 模式 monitor 直接广播 diff")


async def test_monitor_suggest_mode_seeds_pending():
    """Task 22+：suggest 模式下 monitor 产出 diff 暂存到 pending 池，并 demote pending 版本。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store, monitor
    from app.dsh_runner import apply_diff

    plan_id = "test_plan_6"
    plan_store.save_plan(plan_id, "sess_x6", "济南", {})
    initial_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "山东博物馆"}]}]}
    init_vid = plan_store.save_version(plan_id, initial_plan,
                                        trigger_reason="initial_generate", adopted=True)

    monitor._meta[plan_id] = {
        "llm_cfg": {"base_url": "", "api_key": "", "model": "test"},
        "plan": initial_plan, "whitelist": ["attractions"],
    }
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    # Mock optimizer
    from app import dsh_runner
    diff = [{"op": "SWAP", "day": 1, "target_field": "attractions",
             "old_item": {"name": "山东博物馆"},
             "new_item": {"name": "济南市博物馆",
                          "source_url": "https://example.com/jinan-museum"},
             "reason": "suggest mode test"}]
    new_plan = apply_diff(initial_plan, diff)
    new_vid = plan_store.save_version(plan_id, new_plan,
                                       trigger_reason="monitor_optimize",
                                       diff=diff, adopted=True)

    async def mock_optimize(*args, **kwargs):
        return {"plan_id": plan_id, "new_version_id": new_vid,
                "diff": diff, "applied_count": 1, "plan": new_plan}
    dsh_runner.optimize_with_monitor_data = mock_optimize

    await monitor._maybe_optimize(plan_id, {"ts": 0, "weather": {"days": []},
                                            "hotlist_count": 0},
                                   monitor._meta[plan_id], "sess_x6")

    # 断言：建议池有 1 条 pending
    assert plan_id in routes._pending_suggestions
    sugs = routes._pending_suggestions[plan_id]
    assert len(sugs) == 1
    assert sugs[0]["status"] == "pending"
    assert sugs[0]["pending_version_id"] == new_vid

    # 断言：pending 版本被 demote，latest_version_id 仍指向 init_vid
    assert plan_store.latest_version_id(plan_id) == init_vid, \
        "suggest 模式 monitor 产出后 latest_version_id 应仍指向 init_vid"

    # 断言：广播了 suggestion_pending 通知前端展示徽章
    assert len(mock_ws.sent) >= 1
    pending_msg = json.loads(mock_ws.sent[0])
    assert pending_msg["type"] == "optimize_suggestion_pending"
    assert pending_msg["diff_count"] == 1
    print("[Task22+] PASS: suggest 模式 monitor 暂存 pending + 广播徽章通知")


async def test_dynamic_disabled_skips_optimize():
    """TR-21.4 + Task 22+：dynamic_enabled=false 时 monitor 跳过本次优化。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "false"})

    from app import routes, monitor
    plan_id = "test_plan_7"
    monitor._meta[plan_id] = {
        "llm_cfg": {"base_url": "", "api_key": "sk-xxx", "model": "test"},
        "plan": {"overview": {"title": "T"}}, "whitelist": [],
    }
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    # Mock dsh_runner.optimize_with_monitor_data：如果被调用则失败
    call_count = [0]
    from app import dsh_runner
    async def mock_optimize(*args, **kwargs):
        call_count[0] += 1
        return {"applied_count": 0}
    dsh_runner.optimize_with_monitor_data = mock_optimize

    await monitor._maybe_optimize(plan_id, {"ts": 0}, monitor._meta[plan_id], "sess_x7")
    assert call_count[0] == 0, "dynamic_enabled=false 时不应调 optimizer"
    assert len(mock_ws.sent) == 0, "dynamic_enabled=false 时不应广播"
    print("[TR-21.4 + Task22+] PASS: dynamic_enabled=false 跳过优化")


# ====== Task 23 测试用例 ======

async def test_fr33_user_edit_skips_corresponding_diff():
    """FR-33：用户 5 分钟内编辑过 (day, field)，monitor 跳过该卡片 diff 仅推送提示。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "auto", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store, monitor
    from app.dsh_runner import apply_diff

    plan_id = "test_plan_fr33"
    plan_store.save_plan(plan_id, "sess_fr33", "济南", {})
    initial_plan = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "山东博物馆"}],
         "food": [{"name": "把子肉"}]}]}
    init_vid = plan_store.save_version(plan_id, initial_plan,
                                        trigger_reason="initial_generate", adopted=True)

    # 用户编辑过 Day 1 的 attractions 卡片（5 分钟内）
    monitor.record_user_edit(plan_id, day=1, field="attractions")
    assert monitor._is_field_user_edited(plan_id, 1, "attractions") is True
    assert monitor._is_field_user_edited(plan_id, 1, "food") is False, \
        "用户没编辑过 food，不应被避让"

    # Mock optimizer：产出 2 条 diff，一条针对 attractions（应被避让），一条针对 food（应应用）
    diff = [
        {"op": "SWAP", "day": 1, "target_field": "attractions",
         "old_item": {"name": "山东博物馆"},
         "new_item": {"name": "济南市博物馆", "source_url": "https://example.com/m"},
         "reason": "雷阵雨"},
        {"op": "SWAP", "day": 1, "target_field": "food",
         "old_item": {"name": "把子肉"},
         "new_item": {"name": "甜沫", "source_url": "https://example.com/t"},
         "reason": "热榜美食"},
    ]
    new_plan = apply_diff(initial_plan, diff)
    new_vid = plan_store.save_version(plan_id, new_plan,
                                       parent_version_id=init_vid,
                                       trigger_reason="monitor_optimize",
                                       diff=diff, adopted=True)

    from app import dsh_runner
    async def mock_optimize(*args, **kwargs):
        return {"plan_id": plan_id, "new_version_id": new_vid,
                "diff": diff, "applied_count": 2, "plan": new_plan}
    dsh_runner.optimize_with_monitor_data = mock_optimize

    monitor._meta[plan_id] = {
        "llm_cfg": {"api_key": "sk-xxx"}, "plan": initial_plan,
        "whitelist": ["attractions", "food"],
    }
    mock_ws = _MockWebSocket()
    routes._ws_subs.setdefault(plan_id, []).append(mock_ws)

    await monitor._maybe_optimize(plan_id, {"ts": 0}, monitor._meta[plan_id], "sess_fr33")

    # 应广播 1 条 skipped_user_edit + 1 条 optimize_diff（仅 food 那条）
    msg_types = [json.loads(m)["type"] for m in mock_ws.sent]
    assert "optimize_skipped_user_edit" in msg_types, \
        f"应推送 skipped_user_edit，实际 {msg_types}"
    assert "optimize_diff" in msg_types, \
        f"应仍推送 optimize_diff（food 部分），实际 {msg_types}"

    # 验证 skipped 消息内容：包含 attractions 那条
    skipped_msg = next(m for m in mock_ws.sent
                       if json.loads(m)["type"] == "optimize_skipped_user_edit")
    skipped_data = json.loads(skipped_msg)
    assert skipped_data["skipped_count"] == 1
    assert skipped_data["skipped"][0]["field"] == "attractions"
    assert skipped_data["skipped"][0]["new_name"] == "济南市博物馆"

    # 验证 optimize_diff 只包含 food 那条（safe_diff）
    diff_msg = next(m for m in mock_ws.sent
                    if json.loads(m)["type"] == "optimize_diff")
    diff_data = json.loads(diff_msg)
    assert len(diff_data["diff"]) == 1, \
        f"应仅应用 food 那条 diff，实际 {len(diff_data['diff'])} 条"
    assert diff_data["diff"][0]["target_field"] == "food"

    # latest_version_id 应指向 safe_diff 产生的新版本
    cur_vid = plan_store.latest_version_id(plan_id)
    assert cur_vid != new_vid, "原 monitor 产出的全量版本应被 demote，新版本是 safe_diff 后的"
    print("[FR-33 + Task23] PASS: user_edit 后 monitor 跳过对应 (day, field)")


async def test_fr33_window_expires_after_5min():
    """FR-33：5 分钟窗口过后不再避让。"""
    import time as _time
    await _setup_modules({"TG_DYNAMIC_MODE": "auto", "TG_DYNAMIC_ENABLED": "true"})

    from app import monitor
    plan_id = "test_plan_fr33_expire"
    monitor.record_user_edit(plan_id, day=1, field="attractions")
    # 手动把记录时间往前调 6 分钟
    arr = monitor._user_edits.get(plan_id, [])
    for e in arr:
        e["ts"] = _time.time() - 360  # 6 分钟前
    # 触发 GC：调 _is_field_user_edited 应自动清理
    assert monitor._is_field_user_edited(plan_id, 1, "attractions") is False, \
        "5 分钟窗口后应不再避让"
    assert len(monitor._user_edits.get(plan_id, [])) == 0, \
        "过期记录应被清理"
    print("[FR-33 + Task23] PASS: 5 分钟窗口过后自动清理")


async def test_changelog_aggregation_endpoint():
    """Task 23：/plan/{id}/changelog 聚合端点正确返回跨 session changelog。"""
    await _setup_modules({"TG_DYNAMIC_MODE": "suggest", "TG_DYNAMIC_ENABLED": "true"})

    from app import routes, plan_store
    plan_id = "test_plan_changelog"
    plan_store.save_plan(plan_id, "sess_cl", "济南", {})
    # 初始版本（无 diff）
    plan_store.save_version(plan_id, {"overview": {"title": "济南"}, "daily": []},
                             trigger_reason="initial_generate", adopted=True)
    # 优化版本 1
    plan_store.save_version(plan_id, {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "千佛山"}]}]},
        trigger_reason="monitor_optimize",
        diff=[{"op": "SWAP", "day": 1, "target_field": "attractions",
               "old_item": {"name": "山东博物馆"},
               "new_item": {"name": "千佛山", "source_url": "https://example.com/q"},
               "reason": "天气变化"}],
        adopted=True)
    # 优化版本 2
    plan_store.save_version(plan_id, {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "大明湖"}]}]},
        trigger_reason="cockpit_adopt",
        diff=[{"op": "SWAP", "day": 1, "target_field": "attractions",
               "old_item": {"name": "千佛山"},
               "new_item": {"name": "大明湖", "source_url": "https://example.com/d"},
               "reason": "热榜"}],
        adopted=True)

    resp = await routes.get_changelog(plan_id)
    data = json.loads(resp.body)

    assert data["plan_id"] == plan_id
    assert data["total_versions"] == 3
    items = data["items"]
    # 倒序：最新版本在前
    assert items[0]["new_name"] == "大明湖"
    assert items[1]["new_name"] == "千佛山"
    assert items[2]["op"] == "INIT"  # initial_generate 无 diff
    # update_count 应统计 monitor_optimize + cockpit_adopt（共 2）
    assert data["update_count"] == 2, f"update_count 应为 2，实际 {data['update_count']}"
    # 时间戳格式化字段
    assert items[0]["ts_iso"]  # 非空
    print("[Task23] PASS: /changelog 聚合端点正确返回跨 session 历史")


async def test_diff_versions_endpoint():
    """Task 23：/plan/{id}/diff_versions 对比两个版本的字段级差异。"""
    await _setup_modules()

    from app import routes, plan_store
    plan_id = "test_plan_diff"
    plan_store.save_plan(plan_id, "sess_diff", "济南", {})
    plan_a = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "千佛山"}, {"name": "大明湖"}],
         "food": [{"name": "把子肉"}]}]}
    plan_b = {"overview": {"title": "济南"}, "daily": [
        {"day": 1, "attractions": [{"name": "趵突泉"}, {"name": "大明湖"}],
         "food": [{"name": "把子肉"}, {"name": "甜沫"}]}]}
    vid_a = plan_store.save_version(plan_id, plan_a,
                                     trigger_reason="initial_generate", adopted=True)
    vid_b = plan_store.save_version(plan_id, plan_b,
                                     trigger_reason="monitor_optimize",
                                     diff=[], adopted=True)

    resp = await routes.diff_versions(plan_id, vid_a, vid_b)
    data = json.loads(resp.body)
    assert data["from"]["version_id"] == vid_a
    assert data["to"]["version_id"] == vid_b
    changes = data["changes"]
    # 应有 2 条差异：attractions（千佛山 → 趵突泉）+ food（增加 甜沫）
    assert len(changes) == 2
    fields = [c["field"] for c in changes]
    assert "attractions" in fields and "food" in fields
    att_change = next(c for c in changes if c["field"] == "attractions")
    assert "千佛山" in att_change["removed"]
    assert "趵突泉" in att_change["added"]
    food_change = next(c for c in changes if c["field"] == "food")
    assert "甜沫" in food_change["added"]
    print("[Task23] PASS: /diff_versions 字段级差异对比正确")


async def test_hotlist_wikipedia_fallback_on_failure():
    """Task 23：Wikipedia 主源失败时降级到 mafengwo 备选源，不抛异常。"""
    await _setup_modules()

    from app import monitor, traj
    # Mock Wikipedia 失败 + mafengwo 也失败
    async def mock_httpx_get(*args, **kwargs):
        raise RuntimeError("network down")
    import httpx as _httpx
    orig_client = _httpx.AsyncClient

    class _FailClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **kw):
            raise RuntimeError("network down")
    _httpx.AsyncClient = _FailClient

    # Mock scraper.batch 也失败
    from app import scraper
    async def mock_batch(*a, **kw):
        raise RuntimeError("scraper down")
    scraper.batch = mock_batch

    try:
        result = await monitor.fetch_local_hotlist("济南")
        assert result == [], "Wikipedia + mafengwo 都失败时应返回空列表"
        # traj 应有两条失败日志
        events = traj.read("monitor")
        wik_failed = [e for e in events if e.get("type") == "tg-monitor.hotlist_wikipedia_failed"]
        scr_failed = [e for e in events if e.get("type") == "tg-monitor.hotlist_scraper_failed"]
        assert len(wik_failed) >= 1, "Wikipedia 失败应记录日志"
        assert len(scr_failed) >= 1, "scraper 失败应记录日志"
        print("[Task23] PASS: 热榜多源失败时降级到空列表 + 记录日志")
    finally:
        _httpx.AsyncClient = orig_client


# ====== 跑入口 ======
async def main():
    print("\n=== Task 22+ / Task 23 端到端测试 ===\n")
    await test_cockpit_state_returns_active_suggestions()
    await test_adopt_reuses_pending_version_id()
    await test_adopt_edited_falls_back_to_apply_diff()
    await test_reject_clears_pending_version()
    await test_monitor_auto_mode_broadcasts_diff()
    await test_monitor_suggest_mode_seeds_pending()
    await test_dynamic_disabled_skips_optimize()
    # Task 23
    await test_fr33_user_edit_skips_corresponding_diff()
    await test_fr33_window_expires_after_5min()
    await test_changelog_aggregation_endpoint()
    await test_diff_versions_endpoint()
    await test_hotlist_wikipedia_fallback_on_failure()
    print("\n=== 全部测试通过 ✓ ===\n")


if __name__ == "__main__":
    asyncio.run(main())

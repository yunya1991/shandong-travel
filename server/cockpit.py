"""DSH Web UI 驾驶舱（Task 22 / AC-15 / FR-30 / NFR-12）

单独进程 / 单独端口（默认 127.0.0.1:3080），与 FastAPI 同 supervisor 下并行。
通过 httpx 转发请求到 FastAPI（默认 http://127.0.0.1:8000），避免重复实现路由。

用法：
    .venv/bin/python server/cockpit.py
    # 浏览器打开 http://127.0.0.1:3080

注：
- 默认仅本机访问（127.0.0.1），不暴露公网（NFR-12）。
- 默认无鉴权，README 注明远程访问需叠加反代 + 鉴权。
- v1 用 BaseHTTPRequestHandler 实现，DSH SDK 正式版可用时升级为 DSH 视图扩展点。
"""
from __future__ import annotations
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import httpx

# FastAPI 后端地址
BACKEND_URL = os.environ.get("TG_BACKEND_URL", "http://127.0.0.1:8000")
COCKPIT_HOST = os.environ.get("TG_COCKPIT_HOST", "127.0.0.1")
COCKPIT_PORT = int(os.environ.get("TG_COCKPIT_PORT", "3080"))


COCKPIT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>DSH Web UI 驾驶舱 · AI 旅行手册</title>
<style>
  :root {
    --brand: #B8551D;
    --brand-soft: #FBF0EA;
    --brand-text: #5C4A40;
    --accent: #D97757;
    --success: #52C41A;
    --warning: #FAAD14;
    --danger: #FF4D4F;
    --info: #1890FF;
    --bg: #FAF6F2;
    --surface: #FFFFFF;
    --border: #EADFDB;
    --text: #2C1810;
    --text-secondary: #6B5550;
    --text-muted: #A89890;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', sans-serif;
    background: var(--bg);
    color: var(--text);
    font-size: 14px;
    line-height: 1.6;
  }
  header {
    background: var(--brand);
    color: #fff;
    padding: 14px 24px;
    display: flex;
    align-items: center;
    gap: 16px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1);
  }
  header h1 { font-size: 18px; font-weight: 700; }
  header .badge {
    background: rgba(255,255,255,0.18);
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 12px;
  }
  header .controls { margin-left: auto; display: flex; gap: 8px; align-items: center; }
  header input[type="text"] {
    padding: 6px 10px;
    border: 0;
    border-radius: 6px;
    font-size: 13px;
    width: 220px;
  }
  header button {
    padding: 6px 12px;
    border: 0;
    border-radius: 6px;
    background: #fff;
    color: var(--brand);
    font-weight: 600;
    cursor: pointer;
    font-size: 13px;
  }
  header button:hover { background: var(--brand-soft); }
  .layout {
    display: grid;
    grid-template-columns: 1fr 1fr 1fr;
    gap: 16px;
    padding: 16px;
    max-width: 1600px;
    margin: 0 auto;
  }
  @media (max-width: 1024px) {
    .layout { grid-template-columns: 1fr; }
  }
  .panel {
    background: var(--surface);
    border-radius: 10px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.06);
    border: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    min-height: 500px;
    max-height: calc(100vh - 140px);
  }
  .panel__head {
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .panel__head h2 { font-size: 14px; color: var(--brand-text); }
  .panel__head .count {
    margin-left: auto;
    background: var(--brand-soft);
    color: var(--brand);
    padding: 2px 8px;
    border-radius: 999px;
    font-size: 11px;
    font-weight: 600;
  }
  .panel__body {
    flex: 1;
    overflow-y: auto;
    padding: 12px 16px;
  }
  /* 思考轨迹 */
  .traj-item {
    border-left: 3px solid var(--text-muted);
    padding: 6px 0 6px 10px;
    margin-bottom: 6px;
    font-size: 12px;
  }
  .traj-item__head {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .traj-item__time { color: var(--text-muted); font-family: monospace; font-size: 11px; }
  .traj-item__type {
    background: var(--brand-soft);
    color: var(--brand);
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
  }
  .traj-item__payload {
    margin-top: 2px;
    font-size: 11px;
    color: var(--text-secondary);
    white-space: pre-wrap;
    word-break: break-word;
    background: var(--bg);
    padding: 6px 8px;
    border-radius: 4px;
    font-family: monospace;
  }
  .traj-item.ev-start { border-left-color: var(--success); }
  .traj-item.ev-done { border-left-color: var(--success); }
  .traj-item.ev-error { border-left-color: var(--danger); background: #FFF5F5; }
  .traj-item.ev-monitor { border-left-color: var(--info); }
  .traj-item.ev-diff, .traj-item.ev-optimizer { border-left-color: var(--warning); }
  .traj-item.ev-cache { border-left-color: var(--text-muted); }
  .traj-item.ev-cockpit { border-left-color: var(--accent); }
  /* 建议 */
  .sug-item {
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 8px;
    background: var(--bg);
  }
  .sug-item.adopted { border-color: var(--success); background: #F6FFED; }
  .sug-item.rejected { border-color: var(--danger); background: #FFF5F5; opacity: 0.7; }
  .sug-item.edited { border-color: var(--warning); background: #FFFBE6; }
  .sug-item__head {
    display: flex;
    gap: 6px;
    align-items: center;
    font-size: 12px;
    margin-bottom: 6px;
  }
  .sug-item__op {
    background: var(--warning);
    color: #fff;
    padding: 1px 6px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
  }
  .sug-item__reason {
    color: var(--text-secondary);
    font-style: italic;
    font-size: 12px;
    margin: 4px 0;
  }
  .sug-item__diff {
    font-size: 11px;
    background: var(--surface);
    padding: 6px 8px;
    border-radius: 4px;
    font-family: monospace;
    margin: 4px 0;
    white-space: pre-wrap;
    word-break: break-word;
  }
  .sug-item__actions {
    display: flex;
    gap: 6px;
    margin-top: 8px;
  }
  .sug-item__actions button {
    padding: 4px 10px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: var(--surface);
    color: var(--text);
    font-size: 12px;
    cursor: pointer;
  }
  .sug-item__actions .btn-adopt { background: var(--success); color: #fff; border-color: var(--success); }
  .sug-item__actions .btn-reject { background: var(--danger); color: #fff; border-color: var(--danger); }
  .sug-item__actions .btn-edit { background: var(--warning); color: #fff; border-color: var(--warning); }
  .sug-item__actions button:hover { opacity: 0.85; }
  .sug-item__status {
    margin-left: auto;
    font-size: 11px;
    font-weight: 600;
    padding: 1px 6px;
    border-radius: 4px;
  }
  .sug-item__status.pending { background: var(--info); color: #fff; }
  .sug-item__status.adopted { background: var(--success); color: #fff; }
  .sug-item__status.rejected { background: var(--danger); color: #fff; }
  .sug-item__status.edited { background: var(--warning); color: #fff; }
  /* 配置 */
  .cfg-row {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 1px dashed var(--border);
    font-size: 13px;
  }
  .cfg-row:last-child { border-bottom: 0; }
  .cfg-row label { min-width: 120px; color: var(--text-secondary); }
  .cfg-row input[type="checkbox"] { margin-right: 4px; }
  .cfg-row select, .cfg-row input[type="text"] {
    padding: 4px 8px;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 13px;
    flex: 1;
  }
  .cfg-row .hint { color: var(--text-muted); font-size: 11px; }
  .cfg-save { margin-top: 12px; padding: 8px 16px; background: var(--brand); color: #fff; border: 0; border-radius: 6px; cursor: pointer; font-weight: 600; }
  .toast {
    position: fixed;
    top: 80px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--surface);
    color: var(--text);
    padding: 8px 18px;
    border-radius: 999px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.15);
    z-index: 9999;
    opacity: 0;
    transition: opacity 0.25s ease;
    pointer-events: none;
  }
  .toast.visible { opacity: 1; }
  .empty { color: var(--text-muted); text-align: center; padding: 40px 20px; font-size: 13px; }
  .seed-form {
    margin-bottom: 12px;
    padding: 10px;
    background: var(--brand-soft);
    border-radius: 6px;
    border: 1px dashed var(--brand);
  }
  .seed-form textarea {
    width: 100%;
    height: 60px;
    font-family: monospace;
    font-size: 11px;
    padding: 4px;
    border: 1px solid var(--border);
    border-radius: 4px;
    resize: vertical;
  }
  .seed-form button {
    margin-top: 6px;
    padding: 4px 10px;
    background: var(--brand);
    color: #fff;
    border: 0;
    border-radius: 4px;
    cursor: pointer;
    font-size: 12px;
  }
</style>
</head>
<body>
<header>
  <h1>🚀 DSH Web UI 驾驶舱</h1>
  <span class="badge" id="badge-session">session: 未加载</span>
  <span class="badge" id="badge-version">version: 未加载</span>
  <div class="controls">
    <input type="text" id="plan-id-input" placeholder="plan_xxx" />
    <button id="btn-load">加载 plan</button>
    <button id="btn-refresh">↻ 刷新</button>
  </div>
</header>
<div class="layout">
  <section class="panel">
    <div class="panel__head">
      <h2>① 思考轨迹</h2>
      <span class="count" id="traj-count">0</span>
    </div>
    <div class="panel__body" id="traj-list">
      <div class="empty">输入 plan_id 后加载</div>
    </div>
  </section>
  <section class="panel">
    <div class="panel__head">
      <h2>② 动态变更建议</h2>
      <span class="count" id="sug-count">0</span>
    </div>
    <div class="panel__body" id="sug-list">
      <div class="empty">暂无建议</div>
    </div>
  </section>
  <section class="panel">
    <div class="panel__head">
      <h2>③ 阈值配置</h2>
    </div>
    <div class="panel__body" id="cfg-list">
      <div class="empty">加载后显示</div>
    </div>
  </section>
</div>
<div class="toast" id="toast"></div>
<script>
const API_BASE = '';  // 同源
let currentPlanId = '';

// 工具
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('visible');
  clearTimeout(window.__t);
  window.__t = setTimeout(() => el.classList.remove('visible'), 2200);
}
function esc(s) {
  if (s == null) return '';
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
function fmtTime(ts) {
  if (!ts) return '';
  try {
    const d = new Date(ts * 1000);
    return d.toLocaleTimeString('zh-CN', {hour12:false});
  } catch { return ''; }
}

async function api(path, opts = {}) {
  const r = await fetch(API_BASE + path, {
    headers: {'Content-Type': 'application/json'},
    ...opts,
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(`HTTP ${r.status}: ${t.slice(0, 200)}`);
  }
  return r.json();
}

const TRAJ_META = {
  'system_prompt': { label: '系统提示', cls: 'ev-system' },
  'tg-planner.start': { label: 'planner 启动', cls: 'ev-start' },
  'tg-planner.tasks': { label: '任务清单', cls: 'ev-tasks' },
  'tg-planner.error': { label: 'planner 错误', cls: 'ev-error' },
  'tg-planner.skipped': { label: 'planner 跳过', cls: 'ev-skip' },
  'tg-cache.hit': { label: '缓存命中', cls: 'ev-cache' },
  'tg-cache.miss': { label: '缓存未命中', cls: 'ev-cache' },
  'tg-scraper.batch': { label: 'scraper 批量', cls: 'ev-scraper' },
  'tg-scraper.error': { label: 'scraper 错误', cls: 'ev-error' },
  'tg-integrator.start': { label: 'integrator 启动', cls: 'ev-start' },
  'tg-integrator.done': { label: 'integrator 完成', cls: 'ev-done' },
  'tg-integrator.error': { label: 'integrator 错误', cls: 'ev-error' },
  'tg-validator.start': { label: 'validator 启动', cls: 'ev-start' },
  'tg-validator.done': { label: 'validator 完成', cls: 'ev-done' },
  'tg-optimizer.start': { label: 'optimizer 启动', cls: 'ev-start' },
  'tg-optimizer.diff': { label: '优化 diff', cls: 'ev-diff' },
  'tg-optimizer.applied': { label: '已应用 diff', cls: 'ev-done' },
  'tg-optimizer.error': { label: 'optimizer 错误', cls: 'ev-error' },
  'tg-monitor.tick': { label: '监测周期', cls: 'ev-monitor' },
  'tg-monitor.error': { label: '监测错误', cls: 'ev-error' },
  'tg-output.done': { label: 'output 完成', cls: 'ev-done' },
  'pipeline.error': { label: '流水线错误', cls: 'ev-error' },
  'user.edit': { label: '用户编辑', cls: 'ev-user' },
  'plugin.reloaded': { label: '插件重载', cls: 'ev-plugin' },
  'cockpit.adopt': { label: '驾驶舱·采纳', cls: 'ev-cockpit' },
  'cockpit.reject': { label: '驾驶舱·驳回', cls: 'ev-cockpit' },
  'cockpit.edit': { label: '驾驶舱·编辑', cls: 'ev-cockpit' },
  'cockpit.suggestion_seeded': { label: '建议待审', cls: 'ev-cockpit' },
};

function renderTrajectory(events) {
  const el = document.getElementById('traj-list');
  document.getElementById('traj-count').textContent = events.length;
  if (!events.length) {
    el.innerHTML = '<div class="empty">无事件</div>';
    return;
  }
  el.innerHTML = events.map(ev => {
    const t = ev.type || 'unknown';
    const meta = TRAJ_META[t] || { label: t, cls: 'ev-unknown' };
    const time = ev.iso || fmtTime(ev.ts);
    const payloadStr = JSON.stringify(ev.payload || {}, null, 2).slice(0, 500);
    return `<div class="traj-item ${meta.cls}">
      <div class="traj-item__head">
        <span class="traj-item__time">${esc(time)}</span>
        <span class="traj-item__type">${esc(meta.label)}</span>
      </div>
      <details class="traj-item__payload"><summary>展开 payload</summary><pre>${esc(payloadStr)}</pre></details>
    </div>`;
  }).join('');
}

function renderSuggestions(items) {
  const el = document.getElementById('sug-list');
  document.getElementById('sug-count').textContent = items.length;
  if (!items.length) {
    el.innerHTML = '<div class="empty">暂无建议（可下方手动塞 mock diff 演示）</div>' + renderSeedForm();
    bindSeedForm();
    return;
  }
  el.innerHTML = items.map(s => {
    const diffStr = JSON.stringify(s.diff || [], null, 2).slice(0, 400);
    // pending 与 edited 都可继续采纳/编辑（TR-22.3：编辑后保留为 pending 等待再采纳）
    const isActive = s.status === 'pending' || s.status === 'edited';
    return `<div class="sug-item ${esc(s.status)}">
      <div class="sug-item__head">
        ${s.diff.map(d => `<span class="sug-item__op">${esc(d.op)}</span>`).join('')}
        <span>Day ${esc(s.diff[0]?.day || '?')} · ${esc(s.diff[0]?.target_field || '')}</span>
        ${s.source_url ? `<a href="${esc(s.source_url)}" target="_blank" rel="noopener" style="font-size:11px;color:var(--info);">来源 ↗</a>` : ''}
        <span class="sug-item__status ${esc(s.status)}">${esc(s.status)}</span>
      </div>
      <div class="sug-item__reason">${esc(s.reason || '')}</div>
      <details class="sug-item__diff"><summary>diff 详情</summary><pre>${esc(diffStr)}</pre></details>
      ${isActive ? `<div class="sug-item__actions">
        <button class="btn-adopt" data-sid="${esc(s.suggestion_id)}">采纳 → 推送前端</button>
        <button class="btn-reject" data-sid="${esc(s.suggestion_id)}">驳回</button>
        <button class="btn-edit" data-sid="${esc(s.suggestion_id)}">编辑 diff</button>
      </div>` : ''}
    </div>`;
  }).join('') + renderSeedForm();
  bindSeedForm();
  el.querySelectorAll('.btn-adopt').forEach(b => b.addEventListener('click', () => onAdopt(b.dataset.sid)));
  el.querySelectorAll('.btn-reject').forEach(b => b.addEventListener('click', () => onReject(b.dataset.sid)));
  el.querySelectorAll('.btn-edit').forEach(b => b.addEventListener('click', () => onEdit(b.dataset.sid)));
}

function renderSeedForm() {
  return `<div class="seed-form">
    <strong>手动塞 mock diff 建议（演示用）：</strong>
    <textarea id="seed-diff" placeholder='[{&quot;op&quot;:&quot;SWAP&quot;,&quot;day&quot;:3,&quot;target_field&quot;:&quot;attractions&quot;,&quot;old_item&quot;:{&quot;name&quot;:&quot;山东博物馆&quot;},&quot;new_item&quot;:{&quot;name&quot;:&quot;济南市博物馆&quot;,&quot;desc&quot;:&quot;雷阵雨室内备选&quot;,&quot;source_url&quot;:&quot;https://example.com/jinan-museum&quot;},&quot;reason&quot;:&quot;明日济南有雷阵雨&quot;}]'></textarea>
    <button id="btn-seed">塞入驾驶舱</button>
  </div>`;
}

function bindSeedForm() {
  const btn = document.getElementById('btn-seed');
  if (btn) btn.addEventListener('click', onSeed);
}

function renderConfig(cfg) {
  const el = document.getElementById('cfg-list');
  el.innerHTML = `
    <div class="cfg-row">
      <label>动态优化总开关</label>
      <input type="checkbox" id="cfg-enabled" ${cfg.dynamic_enabled ? 'checked' : ''}>
      <span class="hint">关闭后 monitor 不再产出 diff</span>
    </div>
    <div class="cfg-row">
      <label>应用模式</label>
      <select id="cfg-mode">
        <option value="suggest" ${cfg.dynamic_mode === 'suggest' ? 'selected' : ''}>建议模式（驾驶舱审核）</option>
        <option value="auto" ${cfg.dynamic_mode === 'auto' ? 'selected' : ''}>自动应用（直接推送前端）</option>
      </select>
    </div>
    <div class="cfg-row">
      <label>元素白名单</label>
      <div style="display:flex;flex-direction:column;gap:4px;">
        <label><input type="checkbox" class="cfg-wl" value="attractions" ${cfg.dynamic_whitelist.includes('attractions') ? 'checked' : ''}> 景点</label>
        <label><input type="checkbox" class="cfg-wl" value="food" ${cfg.dynamic_whitelist.includes('food') ? 'checked' : ''}> 美食</label>
        <label><input type="checkbox" class="cfg-wl" value="accommodation" ${cfg.dynamic_whitelist.includes('accommodation') ? 'checked' : ''}> 住宿</label>
      </div>
    </div>
    <div class="cfg-row">
      <label>监测频率（出行前 24h）</label>
      <span class="hint">${cfg.monitor_interval_pre_24h_sec}s（默认 1800=30min）</span>
    </div>
    <div class="cfg-row">
      <label>监测频率（出行前 ≥24h）</label>
      <span class="hint">${cfg.monitor_interval_pre_sec}s（默认 7200=2h）</span>
    </div>
    <button class="cfg-save" id="btn-cfg-save">保存配置</button>
    <p class="hint" style="margin-top:8px;">注：v1 配置为进程级（不持久化到 .env）。</p>
  `;
  document.getElementById('btn-cfg-save').addEventListener('click', onCfgSave);
}

async function loadCockpit() {
  if (!currentPlanId) {
    toast('请输入 plan_id');
    return;
  }
  try {
    const s = await api(`/api/plan/${encodeURIComponent(currentPlanId)}/cockpit/state`);
    document.getElementById('badge-session').textContent = `session: ${s.session_id ? s.session_id.slice(0, 24) : '无'}`;
    document.getElementById('badge-version').textContent = `version: ${s.current_version_id ? s.current_version_id.slice(0, 24) : '无'}`;
    renderTrajectory(s.trajectory_events || []);
    // 优先用 active_suggestions（pending + edited），fallback 到 pending_suggestions
    renderSuggestions(s.active_suggestions || s.pending_suggestions || []);
    renderConfig(s.threshold_config || {});
  } catch (e) {
    toast(`加载失败：${e.message}`);
  }
}

async function onAdopt(sid) {
  if (!confirm('确认采纳此建议？采纳后将立即推送前端。')) return;
  try {
    const r = await api(`/api/plan/${encodeURIComponent(currentPlanId)}/suggestions/${encodeURIComponent(sid)}/adopt`, {method: 'POST'});
    toast(`已采纳并推送前端，新版本 ${r.new_version_id.slice(0, 16)}`);
    loadCockpit();
  } catch (e) { toast(`采纳失败：${e.message}`); }
}

async function onReject(sid) {
  if (!confirm('确认驳回？该建议不会推送前端。')) return;
  try {
    await api(`/api/plan/${encodeURIComponent(currentPlanId)}/suggestions/${encodeURIComponent(sid)}/reject`, {method: 'POST'});
    toast('已驳回');
    loadCockpit();
  } catch (e) { toast(`驳回失败：${e.message}`); }
}

async function onEdit(sid) {
  const newDiff = prompt('编辑 diff（JSON 数组）：', '');
  if (newDiff === null) return;
  let parsed;
  try {
    parsed = JSON.parse(newDiff);
  } catch (e) {
    toast('JSON 解析失败');
    return;
  }
  try {
    const r = await api(`/api/plan/${encodeURIComponent(currentPlanId)}/suggestions/${encodeURIComponent(sid)}/edit`, {
      method: 'POST',
      body: JSON.stringify({diff: parsed}),
    });
    toast(`已编辑，状态：${r.status}`);
    loadCockpit();
  } catch (e) { toast(`编辑失败：${e.message}`); }
}

async function onSeed() {
  const txt = document.getElementById('seed-diff').value.trim();
  if (!txt) { toast('请输入 diff JSON'); return; }
  let parsed;
  try { parsed = JSON.parse(txt); } catch { toast('JSON 解析失败'); return; }
  try {
    const r = await api(`/api/plan/${encodeURIComponent(currentPlanId)}/suggestions/seed`, {
      method: 'POST', body: JSON.stringify({diff: parsed, reason: 'manual_seed'}),
    });
    toast(`已塞入：${r.suggestion_id.slice(0, 16)}`);
    loadCockpit();
  } catch (e) { toast(`塞入失败：${e.message}`); }
}

async function onCfgSave() {
  const enabled = document.getElementById('cfg-enabled').checked;
  const mode = document.getElementById('cfg-mode').value;
  const wl = [...document.querySelectorAll('.cfg-wl:checked')].map(c => c.value);
  try {
    const r = await api(`/api/plan/${encodeURIComponent(currentPlanId)}/cockpit/config`, {
      method: 'POST', body: JSON.stringify({dynamic_enabled: enabled, dynamic_mode: mode, dynamic_whitelist: wl}),
    });
    toast(`配置已保存：mode=${r.dynamic_mode}, wl=[${r.dynamic_whitelist.join(',')}]`);
  } catch (e) { toast(`保存失败：${e.message}`); }
}

document.getElementById('btn-load').addEventListener('click', () => {
  currentPlanId = document.getElementById('plan-id-input').value.trim();
  if (currentPlanId) loadCockpit();
});
document.getElementById('btn-refresh').addEventListener('click', () => {
  if (currentPlanId) loadCockpit();
});
document.getElementById('plan-id-input').addEventListener('keydown', e => {
  if (e.key === 'Enter') document.getElementById('btn-load').click();
});
// 自动从 URL ?plan_id=xx 加载
const q = new URLSearchParams(location.search);
const qp = q.get('plan_id');
if (qp) {
  document.getElementById('plan-id-input').value = qp;
  currentPlanId = qp;
  loadCockpit();
}
</script>
</body>
</html>
"""


class CockpitHandler(BaseHTTPRequestHandler):
    """驾驶舱 HTTP handler。

    - GET /                → 驾驶舱 HTML 页面
    - GET/POST /api/*      → 透传到 FastAPI 后端
    """

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-LLM-Config")

    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/" or path == "/index.html":
            body = COCKPIT_HTML.encode("utf-8")
            self._send(200, "text/html; charset=utf-8", body)
            return
        if path.startswith("/api/"):
            backend_path = path[len("/api"):]
            query = parsed.query and f"?{parsed.query}" or ""
            url = f"{BACKEND_URL}{backend_path}{query}"
            try:
                r = httpx.get(url, timeout=15.0)
                self._send(r.status_code, r.headers.get("Content-Type", "application/json"),
                           r.content)
            except Exception as e:
                self._send(502, "application/json",
                           json.dumps({"error": f"backend_unreachable: {e}"}).encode())
            return
        self._send(404, "application/json",
                   json.dumps({"error": "not found"}).encode())

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if not path.startswith("/api/"):
            self._send(404, "application/json",
                       json.dumps({"error": "not found"}).encode())
            return
        backend_path = path[len("/api"):]
        url = f"{BACKEND_URL}{backend_path}"
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""
        try:
            r = httpx.post(url, content=body, headers={
                "Content-Type": self.headers.get("Content-Type", "application/json"),
            }, timeout=15.0)
            self._send(r.status_code, r.headers.get("Content-Type", "application/json"),
                       r.content)
        except Exception as e:
            self._send(502, "application/json",
                       json.dumps({"error": f"backend_unreachable: {e}"}).encode())

    def _send(self, status, content_type, body):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"[cockpit] {args[0]}")


def main():
    print(f"[cockpit] DSH Web UI 驾驶舱运行在 http://{COCKPIT_HOST}:{COCKPIT_PORT}")
    print(f"[cockpit] 后端：{BACKEND_URL}")
    print(f"[cockpit] 本机访问默认无鉴权；远程访问需叠加反代 + 鉴权（NFR-12）")
    srv = ThreadingHTTPServer((COCKPIT_HOST, COCKPIT_PORT), CockpitHandler)
    srv.serve_forever()


if __name__ == "__main__":
    main()

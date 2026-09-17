// 调试视图：拉取并按时间线渲染 Trajectory 事件（AC-12 / FR-23 / FR-25）
import { fetchTrajectory, replayTrajectory } from './llm.js';
import { getCurrentResult } from './generate.js';
import { escapeHtml } from './config.js';

// 事件类型 → 显示样式
const EVENT_META = {
  'system_prompt':         { label: '系统提示词', cls: 'ev-system' },
  'tg-planner.start':      { label: 'planner 启动', cls: 'ev-start' },
  'tg-planner.tasks':      { label: '抓取任务清单', cls: 'ev-tasks' },
  'tg-planner.error':      { label: 'planner 错误', cls: 'ev-error' },
  'tg-planner.skipped':   { label: 'planner 跳过', cls: 'ev-skip' },
  'tg-cache.hit':          { label: '缓存命中', cls: 'ev-cache' },
  'tg-cache.miss':         { label: '缓存未命中', cls: 'ev-cache' },
  'tg-scraper.batch':      { label: 'scraper 批量', cls: 'ev-scraper' },
  'tg-scraper.error':     { label: 'scraper 错误', cls: 'ev-error' },
  'tg-integrator.start':   { label: 'integrator 启动', cls: 'ev-start' },
  'tg-integrator.done':    { label: 'integrator 完成', cls: 'ev-done' },
  'tg-integrator.error':   { label: 'integrator 错误', cls: 'ev-error' },
  'tg-validator.start':    { label: 'validator 启动', cls: 'ev-start' },
  'tg-validator.done':     { label: 'validator 完成', cls: 'ev-done' },
  'tg-optimizer.start':    { label: 'optimizer 启动', cls: 'ev-start' },
  'tg-optimizer.diff':     { label: '优化 diff', cls: 'ev-diff' },
  'tg-optimizer.applied':  { label: '已应用 diff', cls: 'ev-done' },
  'tg-optimizer.error':    { label: 'optimizer 错误', cls: 'ev-error' },
  'tg-monitor.tick':       { label: '监测周期', cls: 'ev-monitor' },
  'tg-monitor.error':      { label: '监测错误', cls: 'ev-error' },
  'tg-output.done':        { label: 'output 完成', cls: 'ev-done' },
  'pipeline.error':        { label: '流水线错误', cls: 'ev-error' },
  'user.edit':             { label: '用户编辑', cls: 'ev-user' },
  'plugin.reloaded':       { label: '插件重载', cls: 'ev-plugin' },
  'replayed':              { label: '已重放', cls: 'ev-plugin' },
};

export function renderDebug() {
  const container = document.getElementById('debug-content');
  if (!container) return;

  // 自动带出最近一次生成的 session_id
  const last = getCurrentResult();
  const lastSession = last?.session_id || '';

  container.innerHTML = `
    <div class="debug-card">
      <h2>Trajectory 调试视图</h2>
      <p class="debug-card__sub">仅在后端增强模式下可用。输入 session_id 拉取思考轨迹（system_prompt / 工具调用 / subagent / 上下文注入）。</p>
      <div class="debug-form">
        <input class="form-input" id="dbg-session" placeholder="sess_xxx" value="${escapeHtml(lastSession)}">
        <button class="btn btn--primary" id="dbg-load">拉取轨迹</button>
        <button class="btn btn--secondary" id="dbg-replay">重放</button>
      </div>
      <div id="dbg-result" class="debug-result"></div>
    </div>
  `;

  const sessionInput = container.querySelector('#dbg-session');
  const resultEl = container.querySelector('#dbg-result');

  container.querySelector('#dbg-load').addEventListener('click', async () => {
    const sid = sessionInput.value.trim();
    if (!sid) { resultEl.innerHTML = '<div class="debug-error">请输入 session_id</div>'; return; }
    resultEl.innerHTML = '<div class="debug-loading">加载中...</div>';
    try {
      const data = await fetchTrajectory(sid);
      resultEl.innerHTML = renderTimeline(data.events || [], sid);
    } catch (e) {
      resultEl.innerHTML = `<div class="debug-error">拉取失败：${escapeHtml(e.message)}</div>`;
    }
  });

  container.querySelector('#dbg-replay').addEventListener('click', async () => {
    const sid = sessionInput.value.trim();
    if (!sid) { resultEl.innerHTML = '<div class="debug-error">请输入 session_id</div>'; return; }
    resultEl.innerHTML = '<div class="debug-loading">重放中...</div>';
    try {
      const r = await replayTrajectory(sid);
      resultEl.innerHTML = `<div class="debug-success">已重放 ${r.replayed_count || 0} 条事件 → 新 session: <code>${escapeHtml(r.new_session_id || '')}</code></div>`;
      sessionInput.value = r.new_session_id || sid;
      // 自动拉取新 session
      container.querySelector('#dbg-load').click();
    } catch (e) {
      resultEl.innerHTML = `<div class="debug-error">重放失败：${escapeHtml(e.message)}</div>`;
    }
  });

  // 有 lastSession 时自动拉取一次
  if (lastSession && !lastSession.startsWith('fe_')) {
    container.querySelector('#dbg-load').click();
  }
}

function renderTimeline(events, sid) {
  if (events.length === 0) {
    return '<div class="debug-empty">无事件</div>';
  }
  const typeSet = new Set();
  const rows = events.map(ev => {
    const type = ev.type || 'unknown';
    typeSet.add(type);
    const meta = EVENT_META[type] || { label: type, cls: 'ev-unknown' };
    const ts = ev.iso || new Date((ev.ts || 0) * 1000).toISOString();
    const payloadStr = JSON.stringify(ev.payload || {}, null, 2);
    return `
    <div class="timeline-item ${meta.cls}">
      <div class="timeline-item__head">
        <span class="timeline-item__time">${escapeHtml(ts)}</span>
        <span class="timeline-item__label">${escapeHtml(meta.label)}</span>
      </div>
      <details class="timeline-item__payload">
        <summary>展开 payload</summary>
        <pre>${escapeHtml(payloadStr)}</pre>
      </details>
    </div>`;
  }).join('');

  const summary = Array.from(typeSet).map(t => {
    const m = EVENT_META[t] || { label: t, cls: 'ev-unknown' };
    return `<span class="debug-chip ${m.cls}">${escapeHtml(m.label)}</span>`;
  }).join('');

  return `
    <div class="debug-summary">
      <strong>session:</strong> <code>${escapeHtml(sid)}</code> ·
      <strong>事件:</strong> ${events.length} 条 ·
      <strong>类型:</strong> ${typeSet.size} 类
    </div>
    <div class="debug-types">${summary}</div>
    <div class="timeline">${rows}</div>
  `;
}

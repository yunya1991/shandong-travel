// 调试视图：拉取并按时间线渲染 Trajectory 事件（AC-12 / FR-23 / FR-25 / NFR-9）
import { fetchTrajectory, fetchSessions, replayTrajectory } from './llm.js';
import { getCurrentResult } from './generate.js';
import { loadConfig } from './config.js';
import { escapeHtml } from './config.js';

// 事件类型 → 显示样式 + 分类
const EVENT_META = {
  'system_prompt':         { label: '系统提示词', cls: 'ev-system',    group: 'system' },
  'tg-planner.start':      { label: 'planner 启动', cls: 'ev-start',     group: 'planner' },
  'tg-planner.tasks':      { label: '抓取任务清单', cls: 'ev-tasks',     group: 'planner' },
  'tg-planner.error':      { label: 'planner 错误', cls: 'ev-error',    group: 'planner' },
  'tg-planner.skipped':    { label: 'planner 跳过', cls: 'ev-skip',     group: 'planner' },
  'tg-cache.hit':          { label: '缓存命中',    cls: 'ev-cache',     group: 'cache' },
  'tg-cache.miss':         { label: '缓存未命中',  cls: 'ev-cache',     group: 'cache' },
  'tg-scraper.batch':      { label: 'scraper 批量', cls: 'ev-scraper',  group: 'scraper' },
  'tg-scraper.error':      { label: 'scraper 错误', cls: 'ev-error',    group: 'scraper' },
  'tg-integrator.start':   { label: 'integrator 启动', cls: 'ev-start', group: 'integrator' },
  'tg-integrator.done':    { label: 'integrator 完成', cls: 'ev-done',  group: 'integrator' },
  'tg-integrator.error':   { label: 'integrator 错误', cls: 'ev-error', group: 'integrator' },
  'tg-validator.start':    { label: 'validator 启动', cls: 'ev-start',  group: 'validator' },
  'tg-validator.done':     { label: 'validator 完成', cls: 'ev-done',   group: 'validator' },
  'tg-optimizer.start':    { label: 'optimizer 启动', cls: 'ev-start',  group: 'optimizer' },
  'tg-optimizer.diff':     { label: '优化 diff',     cls: 'ev-diff',    group: 'optimizer' },
  'tg-optimizer.applied':  { label: '已应用 diff',   cls: 'ev-done',    group: 'optimizer' },
  'tg-optimizer.error':    { label: 'optimizer 错误', cls: 'ev-error',  group: 'optimizer' },
  'tg-monitor.tick':       { label: '监测周期',       cls: 'ev-monitor', group: 'monitor' },
  'tg-monitor.error':      { label: '监测错误',       cls: 'ev-error',   group: 'monitor' },
  'tg-output.done':        { label: 'output 完成',    cls: 'ev-done',    group: 'output' },
  'pipeline.error':        { label: '流水线错误',     cls: 'ev-error',   group: 'pipeline' },
  'user.edit':             { label: '用户编辑',       cls: 'ev-user',    group: 'user' },
  'plugin.reloaded':       { label: '插件重载',       cls: 'ev-plugin',  group: 'plugin' },
  'replayed':              { label: '已重放',         cls: 'ev-plugin',  group: 'plugin' },
};

// 当前状态
let currentEvents = [];
let currentSid = '';
let compareEvents = null;   // 重放对比：存重放后的 events
let compareSid = '';
let activeFilter = 'all';  // 当前分组过滤
let searchQuery = '';

export function renderDebug() {
  const container = document.getElementById('debug-content');
  if (!container) return;

  const cfg = loadConfig();
  const isBackend = cfg.mode === 'backend';
  const last = getCurrentResult();
  const lastSession = last?.session_id || '';

  container.innerHTML = `
    <div class="debug-card">
      <h2>Trajectory 调试视图</h2>
      <p class="debug-card__sub">
        ${isBackend
          ? '展示一次完整生成的思考轨迹：系统提示词 → 工具调用 → subagent → 上下文注入。每个事件可展开查看 payload，LLM 调用附带 token 估算与耗时。'
          : '⚠️ 当前为纯前端模式，调试视图不可用。请到「设置」切换为「后端增强模式」并启动后端。'}
      </p>

      ${isBackend ? `
        <div class="debug-form">
          <select class="form-select" id="dbg-session-select" title="选择最近 session">
            <option value="">— 选择历史 session —</option>
          </select>
          <input class="form-input" id="dbg-session" placeholder="或输入 sess_xxx" value="${escapeHtml(lastSession)}">
          <button class="btn btn--primary" id="dbg-load">拉取轨迹</button>
          <button class="btn btn--secondary" id="dbg-replay">重放</button>
          <button class="btn btn--secondary" id="dbg-refresh-sessions" title="刷新 session 列表">↻</button>
        </div>

        <div class="debug-toolbar">
          <input class="form-input debug-search" id="dbg-search" placeholder="🔍 搜索事件类型 / payload 内容">
          <div class="debug-filters" id="dbg-filters"></div>
        </div>

        <div id="dbg-result" class="debug-result"></div>
      ` : ''}
    </div>
  `;

  if (!isBackend) return;

  const sessionInput = container.querySelector('#dbg-session');
  const sessionSelect = container.querySelector('#dbg-session-select');
  const resultEl = container.querySelector('#dbg-result');
  const searchInput = container.querySelector('#dbg-search');
  const filtersEl = container.querySelector('#dbg-filters');

  // 拉取 session 列表填充下拉
  async function refreshSessions() {
    try {
      const data = await fetchSessions(50);
      const sessions = data.sessions || [];
      const cur = sessionInput.value.trim();
      sessionSelect.innerHTML = '<option value="">— 选择历史 session —</option>' +
        sessions.map(s => {
          const ts = s.start_ts ? new Date(s.start_ts * 1000).toLocaleString('zh-CN') : '';
          const sel = (s.session_id === cur) ? 'selected' : '';
          return `<option value="${escapeHtml(s.session_id)}" ${sel}>${escapeHtml(s.session_id.slice(0, 24))} · ${ts} · ${s.event_count}事件</option>`;
        }).join('');
    } catch (e) {
      sessionSelect.innerHTML = `<option value="">列表拉取失败：${escapeHtml(e.message)}</option>`;
    }
  }
  refreshSessions();

  sessionSelect.addEventListener('change', () => {
    sessionInput.value = sessionSelect.value;
    loadTrajectory();
  });

  sessionInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') loadTrajectory();
  });

  container.querySelector('#dbg-load').addEventListener('click', loadTrajectory);

  async function loadTrajectory() {
    const sid = sessionInput.value.trim();
    if (!sid) { resultEl.innerHTML = '<div class="debug-error">请输入 session_id</div>'; return; }
    resultEl.innerHTML = '<div class="debug-loading">加载中...</div>';
    try {
      const data = await fetchTrajectory(sid);
      currentEvents = data.events || [];
      currentSid = sid;
      compareEvents = null;
      compareSid = '';
      activeFilter = 'all';
      searchQuery = '';
      if (searchInput) searchInput.value = '';
      renderAll();
    } catch (e) {
      resultEl.innerHTML = `<div class="debug-error">拉取失败：${escapeHtml(e.message)}</div>`;
    }
  }

  container.querySelector('#dbg-replay').addEventListener('click', async () => {
    const sid = sessionInput.value.trim();
    if (!sid) { resultEl.innerHTML = '<div class="debug-error">请输入 session_id</div>'; return; }
    resultEl.innerHTML = '<div class="debug-loading">重放中...</div>';
    try {
      const r = await replayTrajectory(sid);
      compareSid = r.new_session_id || '';
      // 拉取新 session 的事件做对比
      const data = await fetchTrajectory(compareSid);
      compareEvents = data.events || [];
      sessionInput.value = compareSid;
      renderAll();
    } catch (e) {
      resultEl.innerHTML = `<div class="debug-error">重放失败：${escapeHtml(e.message)}</div>`;
    }
  });

  container.querySelector('#dbg-refresh-sessions').addEventListener('click', refreshSessions);

  // 搜索过滤
  searchInput.addEventListener('input', () => {
    searchQuery = searchInput.value.trim().toLowerCase();
    renderAll();
  });

  function renderAll() {
    if (currentEvents.length === 0) {
      resultEl.innerHTML = '<div class="debug-empty">无事件</div>';
      return;
    }
    // 统计分组
    const groupCounts = {};
    currentEvents.forEach(ev => {
      const meta = EVENT_META[ev.type] || { group: 'unknown' };
      groupCounts[meta.group] = (groupCounts[meta.group] || 0) + 1;
    });

    // 渲染过滤芯片
    filtersEl.innerHTML = renderFilters(groupCounts);

    // 绑定过滤芯片点击
    filtersEl.querySelectorAll('.debug-chip-filter').forEach(chip => {
      chip.addEventListener('click', () => {
        activeFilter = chip.dataset.group || 'all';
        renderAll();
      });
    });

    // 计算总 token / 总耗时
    const totals = computeTotals(currentEvents);

    resultEl.innerHTML = `
      ${renderSummary(currentSid, currentEvents, groupCounts, totals)}
      ${compareEvents ? `<div class="debug-compare-banner">↔ 重放对比：原 ${currentEvents.length} 事件 vs 重放 ${compareEvents.length} 事件（新 session: <code>${escapeHtml(compareSid.slice(0, 24))}</code>）</div>` : ''}
      <div class="timeline">${renderTimeline(currentEvents, compareEvents)}</div>
    `;
  }

  function renderFilters(groupCounts) {
    const all = currentEvents.length;
    const groups = Object.entries(groupCounts).sort((a, b) => b[1] - a[1]);
    const chips = [
      `<button class="debug-chip-filter ${activeFilter === 'all' ? 'active' : ''}" data-group="all">全部 ${all}</button>`,
      ...groups.map(([g, n]) => {
        const labelMap = {
          system: '系统', planner: 'planner', scraper: 'scraper',
          integrator: '集成', validator: '校对', optimizer: '优化',
          monitor: '监测', cache: '缓存', output: '输出',
          pipeline: '错误', user: '用户', plugin: '插件', unknown: '其他',
        };
        const label = labelMap[g] || g;
        return `<button class="debug-chip-filter ${activeFilter === g ? 'active' : ''}" data-group="${escapeHtml(g)}">${escapeHtml(label)} ${n}</button>`;
      }),
    ].join('');
    return chips;
  }

  function renderTimeline(events, compareArr) {
    return events.map((ev, i) => {
      const type = ev.type || 'unknown';
      const meta = EVENT_META[type] || { label: type, cls: 'ev-unknown', group: 'unknown' };
      // 分组过滤
      if (activeFilter !== 'all' && meta.group !== activeFilter) return '';
      // 搜索过滤
      if (searchQuery) {
        const hay = (type + ' ' + JSON.stringify(ev.payload || {})).toLowerCase();
        if (!hay.includes(searchQuery)) return '';
      }
      const ts = ev.iso || new Date((ev.ts || 0) * 1000).toISOString();
      const payload = ev.payload || {};
      const tokenInfo = renderTokenInfo(payload);
      const compareInfo = compareArr && compareArr[i]
        ? renderCompareCell(ev, compareArr[i])
        : '';
      const payloadStr = JSON.stringify(payload, null, 2);
      return `
      <div class="timeline-item ${meta.cls}">
        <div class="timeline-item__head">
          <span class="timeline-item__time">${escapeHtml(ts)}</span>
          <span class="timeline-item__label">${escapeHtml(meta.label)}</span>
          ${tokenInfo}
        </div>
        ${compareInfo}
        <details class="timeline-item__payload">
          <summary>展开 payload</summary>
          <pre>${escapeHtml(payloadStr)}</pre>
        </details>
      </div>`;
    }).join('');
  }

  function renderTokenInfo(payload) {
    const tokens = payload.tokens;
    const elapsed = payload.elapsed_ms;
    const model = payload.llm_model;
    if (!tokens && !elapsed) return '';
    const parts = [];
    if (tokens && (tokens.total_tokens || tokens.prompt_tokens || tokens.completion_tokens)) {
      parts.push(`tokens: ${tokens.prompt_tokens || 0}→${tokens.completion_tokens || 0} (Σ${tokens.total_tokens || 0})`);
    }
    if (elapsed != null) parts.push(`耗时: ${elapsed}ms`);
    if (model) parts.push(`<span class="timeline-item__model">${escapeHtml(model)}</span>`);
    return ` <span class="timeline-item__meta">${parts.join(' · ')}</span>`;
  }

  function renderCompareCell(origEv, replayEv) {
    const origStr = JSON.stringify(origEv.payload || {}).slice(0, 200);
    const replayStr = JSON.stringify(replayEv.payload || {}).slice(0, 200);
    const same = origStr === replayStr;
    return `
      <div class="timeline-item__compare ${same ? 'same' : 'diff'}">
        <span class="compare-badge">${same ? '✓ 一致' : '⚠ 差异'}</span>
        <details><summary>对比重放 payload</summary><pre>${escapeHtml(replayStr)}</pre></details>
      </div>`;
  }

  function renderSummary(sid, events, groupCounts, totals) {
    const typeSet = new Set(events.map(e => e.type));
    return `
      <div class="debug-summary">
        <strong>session:</strong> <code>${escapeHtml(sid)}</code> ·
        <strong>事件:</strong> ${events.length} 条 ·
        <strong>类型:</strong> ${typeSet.size} 类 ·
        <strong>分组:</strong> ${Object.keys(groupCounts).length} 个
        ${totals.totalTokens > 0 ? `· <strong>LLM tokens:</strong> Σ${totals.totalTokens} (prompt ${totals.promptTokens} / completion ${totals.completionTokens})` : ''}
        ${totals.totalMs > 0 ? ` · <strong>LLM 耗时:</strong> Σ${totals.totalMs}ms` : ''}
      </div>`;
  }

  function computeTotals(events) {
    let promptTokens = 0, completionTokens = 0, totalTokens = 0, totalMs = 0;
    events.forEach(ev => {
      const p = ev.payload || {};
      if (p.tokens) {
        promptTokens += p.tokens.prompt_tokens || 0;
        completionTokens += p.tokens.completion_tokens || 0;
        totalTokens += p.tokens.total_tokens || 0;
      }
      if (p.elapsed_ms) totalMs += p.elapsed_ms;
    });
    return { promptTokens, completionTokens, totalTokens, totalMs };
  }

  // 有 lastSession 且非前端 session 时自动拉取
  if (lastSession && !lastSession.startsWith('fe_')) {
    loadTrajectory();
  }
}

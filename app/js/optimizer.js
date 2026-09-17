// 动态优化引擎前端（Task 21 / AC-14 / FR-27~29, FR-31~33）
// 负责监听后端推送（mock 用 triggerOptimize 模拟）、应用 diff 到 DOM、徽章+changelog、撤销按钮、变更说明浮层
// Task 22 / TR-22.2：接收 DSH Web UI 驾驶舱采纳后通过 WebSocket 推送的 diff
import { loadConfig, escapeHtml } from './config.js';
import { getCurrentResult, getCurrentPlanId, setCurrentResult } from './generate.js';
import { triggerOptimize, fetchVersions, fetchChangelog, diffVersions, revertToVersion } from './llm.js';

// 本会话累计动态更新次数（仅前端展示用）
let updateCount = 0;
// changelog: [{ts, reason, op, day, target_field, old_name, new_name, version_id, source_url, adopted}]
let changelog = [];
// 待审建议数量（建议模式下：驾驶舱 pending 池数量）
let pendingCount = 0;

// WebSocket 客户端（Task 22 / TR-22.2：驾驶舱采纳后实时同步到前端）
let _ws = null;
let _wsPlanId = null;
let _wsReconnectTimer = null;

/**
 * 启动 WebSocket 订阅 plan_id 的动态变更推送（≤ 1 秒内同步 DOM，NFR-11）
 */
export function startWsSubscription(planId) {
  if (!planId || planId === _wsPlanId && _ws && _ws.readyState <= 1) return;
  // 关闭旧订阅
  stopWsSubscription();
  _wsPlanId = planId;
  const cfg = loadConfig();
  if (!cfg.backend_url || !cfg.dynamic_enabled) return;

  let wsUrl;
  try {
    const httpUrl = new URL(cfg.backend_url);
    const proto = httpUrl.protocol === 'https:' ? 'wss:' : 'ws:';
    wsUrl = `${proto}//${httpUrl.host}/ws/plan/${encodeURIComponent(planId)}`;
  } catch {
    return;
  }

  try {
    _ws = new WebSocket(wsUrl);
  } catch (e) {
    console.warn('[dyn-ws] connect failed:', e);
    return;
  }

  _ws.addEventListener('open', () => {
    console.log('[dyn-ws] subscribed to', planId);
  });
  _ws.addEventListener('message', (ev) => {
    let data;
    try { data = JSON.parse(ev.data); } catch { return; }
    if (data.type === 'optimize_diff' && data.plan_id === planId) {
      // 驾驶舱采纳 / 自动模式：应用 diff 到 DOM
      const optimizeResp = {
        diff: data.diff || [],
        plan: null,  // 收到的只是 diff，不重渲染整个手册
        new_version_id: data.new_version_id,
        applied_count: data.applied_count || (data.diff?.length || 0),
        reason: data.reason || (data.origin === 'cockpit' ? 'cockpit_adopt' : 'monitor_optimize'),
      };
      // 先尝试拉取后端最新 plan（保证 plan 数据完整）
      _fetchAndApply(data.plan_id, optimizeResp);
    } else if (data.type === 'optimize_suggestion_pending' && data.plan_id === planId) {
      // 建议模式：驾驶舱有 N 条建议待审，提示用户
      // 累加 pendingCount 并刷新徽章；toast 仅首次出现时弹
      pendingCount = Math.max(pendingCount + 1, data.diff_count || 1);
      updatePendingBadge();
      showToast(`⚡ 驾驶舱有 ${pendingCount} 条建议待审，点击徽章打开`);
    } else if (data.type === 'optimize_suggestion_resolved' && data.plan_id === planId) {
      // 驾驶舱采纳 / 驳回后通知前端清理 pending 徽章
      pendingCount = 0;
      updatePendingBadge();
    } else if (data.type === 'optimize_skipped_user_edit' && data.plan_id === planId) {
      // FR-33：用户最近编辑过该卡片，monitor 跳过 diff 仅推送提示
      const skippedMsg = (data.skipped || []).map(s =>
        `Day ${s.day} ${s.field}${s.new_name ? `（建议换为 ${s.new_name}）` : ''}`
      ).join('、');
      showToast(`⏭️ 已跳过你刚编辑的卡片：${skippedMsg}（FR-33 避让）`);
    }
  });
  _ws.addEventListener('close', () => {
    console.log('[dyn-ws] closed, will reconnect in 5s');
    _ws = null;
    if (_wsPlanId) {
      clearTimeout(_wsReconnectTimer);
      _wsReconnectTimer = setTimeout(() => {
        if (_wsPlanId) startWsSubscription(_wsPlanId);
      }, 5000);
    }
  });
  _ws.addEventListener('error', () => {
    // 错误时静默关闭，等 close 事件重连
    try { _ws?.close(); } catch {}
  });
}

export function stopWsSubscription() {
  if (_wsReconnectTimer) { clearTimeout(_wsReconnectTimer); _wsReconnectTimer = null; }
  _wsPlanId = null;
  if (_ws) {
    try { _ws.close(); } catch {}
    _ws = null;
  }
}

/**
 * 上报用户手动编辑事件给后端（FR-33 协同冲突避让，Task 23）
 * 后端在 5 分钟窗口内跳过对应 (day, field) 的 diff。
 * @param {number|null} day 卡片所在天（如 1/2/3）
 * @param {string|null} field 字段名（attractions/food/accommodation）
 */
export function reportUserEdit(day, field) {
  if (!_ws || _ws.readyState !== WebSocket.OPEN || !day || !field) return;
  try {
    _ws.send(JSON.stringify({
      type: 'user_edit', plan_id: _wsPlanId, day, field,
    }));
  } catch (e) {
    console.warn('[dyn-ws] reportUserEdit failed:', e);
  }
}

/**
 * 拉取最新 plan 并应用 diff（确保 plan 完整）
 */
async function _fetchAndApply(planId, optimizeResp) {
  try {
    const versions = await fetchVersions(planId);
    const sorted = (versions.versions || []).sort((a, b) => (b.ts || 0) - (a.ts || 0));
    const top = sorted[0];
    if (!top) {
      showToast('收到驾驶舱推送，但版本列表为空');
      return;
    }
    // 拉取该版本详情
    const cfg = loadConfig();
    const r = await fetch(`${cfg.backend_url.replace(/\/$/, '')}/plan/${encodeURIComponent(planId)}/version/${encodeURIComponent(top.version_id)}`);
    if (r.ok) {
      const v = await r.json();
      if (v.plan) {
        optimizeResp.plan = v.plan;
      }
    }
  } catch (e) {
    console.warn('[dyn-ws] fetch version failed:', e);
  }
  // 应用到 DOM
  applyDiffToCurrent(optimizeResp);
}


/**
 * 在 banner 上挂载"动态更新 N 次"徽章 + changelog 抽屉 + 撤销按钮
 * 由 renderer.renderCurrent 调用
 */
export function mountDynamicControls() {
  const cfg = loadConfig();
  const result = getCurrentResult();
  const planId = result?.planId || getCurrentPlanId();
  if (!planId) return;

  // 找到 banner
  const banner = document.querySelector('.guide-banner');
  if (!banner) return;

  // 已挂载则不重复
  if (banner.querySelector('.dyn-controls')) return;

  const enabled = cfg.dynamic_enabled;
  const mode = cfg.dynamic_mode || 'suggest';

  // 启动 WebSocket 订阅（Task 22 / TR-22.2：驾驶舱采纳后实时同步）
  if (enabled && cfg.backend_url) {
    startWsSubscription(planId);
  }

  const controlsEl = document.createElement('div');
  controlsEl.className = 'dyn-controls';
  const cockpitHost = cfg.cockpit_host || '127.0.0.1';
  const cockpitPort = cfg.cockpit_port || 3080;
  const cockpitUrl = `http://${cockpitHost}:${cockpitPort}/?plan_id=${encodeURIComponent(planId)}`;
  controlsEl.innerHTML = `
    ${enabled ? `<span class="badge badge--dyn" title="动态优化引擎已启用（${mode === 'auto' ? '自动应用' : '建议'}模式）">⚡ 动态更新 ${updateCount} 次</span>` : ''}
    ${enabled && mode === 'suggest' ? `<a class="badge badge--dyn-pending ${pendingCount === 0 ? 'is-empty' : ''}" id="dyn-pending-badge" href="${cockpitUrl}" target="_blank" rel="noopener" title="点击打开 DSH Web UI 驾驶舱审阅建议">🛫 待审 <span class="badge--dyn-pending__count" id="dyn-pending-count">${pendingCount}</span></a>` : ''}
    ${enabled ? `<button class="btn btn--secondary btn--sm" id="dyn-trigger" title="手动触发一次监测+优化（模拟 tg-monitor 检测到天气/热榜变化）">🔄 触发优化</button>` : ''}
    ${updateCount > 0 ? `<button class="btn btn--secondary btn--sm" id="dyn-undo" title="回滚到上一版本">↶ 撤销上次</button>` : ''}
    ${updateCount > 0 ? `<details class="dyn-changelog"><summary>变更日志 ${updateCount} 条</summary><ul class="dyn-changelog__list"></ul></details>` : ''}
  `;
  banner.appendChild(controlsEl);

  if (enabled) {
    controlsEl.querySelector('#dyn-trigger')?.addEventListener('click', onTriggerOptimize);
    controlsEl.querySelector('#dyn-undo')?.addEventListener('click', onUndo);
  }
  renderChangelog();
  // Task 23：跨 session 恢复——从后端拉取聚合 changelog + update_count
  _restoreChangelogFromBackend(planId);
}

/**
 * 启动时从后端恢复 changelog（Task 23：跨 session 重启后不丢）
 */
async function _restoreChangelogFromBackend(planId) {
  try {
    const data = await fetchChangelog(planId);
    if (data?.items?.length) {
      // 后端 changelog 是按时间倒序，前端数组也是 unshift（倒序），所以直接赋值
      changelog = data.items.map(it => ({
        ts: it.ts_iso || new Date((it.ts || 0) * 1000).toISOString(),
        reason: it.reason || '',
        op: it.op || '?',
        day: it.day,
        target_field: it.target_field,
        old_name: it.old_name,
        new_name: it.new_name,
        version_id: it.version_id,
        source_url: it.source_url,
        adopted: it.adopted,
      }));
    }
    if (typeof data?.update_count === 'number') {
      updateCount = data.update_count;
    }
    // 重新挂载控件以刷新徽章 + changelog 抽屉
    const banner = document.querySelector('.guide-banner');
    const old = banner?.querySelector('.dyn-controls');
    if (old) old.remove();
    mountDynamicControls();
  } catch (e) {
    console.warn('[dyn] restore changelog failed:', e);
  }
}

/**
 * 刷新"待审 N 条"徽章可见性 / 计数（Task 22+）
 */
function updatePendingBadge() {
  const badge = document.getElementById('dyn-pending-badge');
  const countEl = document.getElementById('dyn-pending-count');
  if (countEl) countEl.textContent = String(pendingCount);
  if (badge) {
    badge.classList.toggle('is-empty', pendingCount === 0);
  }
}

/**
 * 手动触发一次 optimize（模拟 WebSocket 推送，TR-21.1）
 */
async function onTriggerOptimize() {
  const cfg = loadConfig();
  if (!cfg.dynamic_enabled) {
    showToast('动态更新未开启（设置中开启）');
    return;
  }
  const result = getCurrentResult();
  const planId = result?.planId;
  const dest = result?.plan?.overview?.departure || result?.plan?.overview?.title || '';
  if (!planId) {
    showToast('未找到 plan_id');
    return;
  }
  showToast('触发 tg-monitor + tg-optimizer...');
  try {
    const r = await triggerOptimize(planId, dest, {
      departure_date: result?.plan?.overview?.dates,
      whitelist: cfg.dynamic_whitelist,
    });
    if (r.applied_count > 0) {
      // 应用 diff 到 plan + DOM
      applyDiffToCurrent(r);
    } else {
      showToast('本次监测无变更建议');
    }
  } catch (e) {
    showToast(`触发失败：${e.message}`);
  }
}

/**
 * 应用 diff 到当前 result.plan + DOM（TR-21.2 高亮换出/换入）
 */
function applyDiffToCurrent(optimizeResp) {
  const result = getCurrentResult();
  if (!result?.plan) return;
  const diff = optimizeResp.diff || [];
  const cfg = loadConfig();

  // 自动模式：直接应用；建议模式：弹出确认
  if (cfg.dynamic_mode === 'suggest') {
    showSuggestDialog(optimizeResp, () => {
      doApplyDiff(optimizeResp);
    });
  } else {
    doApplyDiff(optimizeResp);
  }
}

function doApplyDiff(optimizeResp) {
  const result = getCurrentResult();
  const diff = optimizeResp.diff || [];
  const newPlan = optimizeResp.plan;
  if (!newPlan) {
    showToast('后端未返回新 plan');
    return;
  }
  // 更新 currentResult
  setCurrentResult({ ...result, plan: newPlan });

  // 应用 DOM 高亮（TR-21.2）
  diff.forEach(op => {
    applyOpToDOM(op);
    // 记录 changelog
    changelog.unshift({
      ts: new Date().toISOString(),
      reason: op.reason || optimizeResp.reason || 'monitor_optimize',
      op: op.op,
      day: op.day,
      target_field: op.target_field,
      old_name: op.old_item?.name,
      new_name: op.new_item?.name,
      version_id: optimizeResp.new_version_id,
      source_url: op.new_item?.source_url,
      adopted: true,
    });
  });
  updateCount += diff.length;
  showToast(`已应用 ${diff.length} 条变更（共 ${updateCount} 次）`);

  // 刷新 banner 控件
  const banner = document.querySelector('.guide-banner');
  const old = banner?.querySelector('.dyn-controls');
  if (old) old.remove();
  mountDynamicControls();
}

/**
 * 应用单个 op 到 DOM：高亮换出/换入
 */
function applyOpToDOM(op) {
  const dayIdx = op.day;
  const fieldName = op.target_field;
  const oldName = op.old_item?.name;
  const newName = op.new_item?.name;

  // 找到 Day N 的卡片
  const dayCards = document.querySelectorAll('.day-card');
  let targetCard = null;
  for (const c of dayCards) {
    const badge = c.querySelector('.day-card__badge')?.textContent || '';
    if (badge.includes(`Day ${dayIdx}`)) {
      targetCard = c;
      break;
    }
  }
  if (!targetCard) return;

  // 在卡片内找到 old_name 的 attraction-item
  const items = targetCard.querySelectorAll('.attraction-item');
  for (const item of items) {
    const nameEl = item.querySelector('.attraction-item__name');
    if (nameEl?.textContent?.trim() === oldName) {
      // 添加"换出"动画
      item.classList.add('dyn-swap-out');
      // 1 秒后替换内容
      setTimeout(() => {
        const newItem = op.new_item;
        nameEl.textContent = newItem.name || '';
        const descEl = item.querySelector('.attraction-item__desc');
        if (descEl && newItem.desc) descEl.textContent = newItem.desc;
        // 标签
        const metaEl = item.querySelector('.attraction-item__meta');
        if (metaEl) {
          metaEl.innerHTML = '';
          if (newItem.ticket) {
            const t = document.createElement('span');
            t.className = 'attraction-item__tag';
            t.textContent = newItem.ticket;
            metaEl.appendChild(t);
          }
          if (newItem.duration) {
            const t = document.createElement('span');
            t.className = 'attraction-item__tag';
            t.textContent = newItem.duration;
            metaEl.appendChild(t);
          }
          (newItem.tags || []).forEach(tagText => {
            const t = document.createElement('span');
            t.className = 'attraction-item__tag';
            t.textContent = tagText;
            metaEl.appendChild(t);
          });
        }
        // 来源链接
        const oldSrc = item.querySelector('.source-link');
        if (oldSrc) oldSrc.remove();
        if (newItem.source_url) {
          const a = document.createElement('a');
          a.className = 'source-link';
          a.href = newItem.source_url;
          a.target = '_blank';
          a.rel = 'noopener noopener';
          a.textContent = `来源: ${new URL(newItem.source_url).hostname} ↗`;
          item.appendChild(a);
        }
        item.classList.remove('dyn-swap-out');
        item.classList.add('dyn-swap-in');
        // 2 秒后移除高亮
        setTimeout(() => item.classList.remove('dyn-swap-in'), 2000);
        // 变更说明浮层（FR-29）
        showChangeNote(item, op.reason || `${oldName} → ${newName}`);
      }, 1000);
      break;
    }
  }
}

/**
 * 变更说明浮层（FR-29 / AC-14 / Task 23：位置修正为卡片上方 + 可关闭持久化）
 * spec 要求"在变更卡片上方展示可读说明"——之前是 appendChild 在底部，
 * Task 23 改为 insertBefore(itemEl.firstChild)，浮层位置真正在卡片顶部。
 * 浮层不自动消失，由用户点 ✕ 关闭；同卡片多条说明折叠为一条带计数。
 */
function showChangeNote(itemEl, reason) {
  if (!itemEl) return;
  // 已有浮层则合并计数
  let note = itemEl.querySelector('.dyn-change-note');
  if (note) {
    const countEl = note.querySelector('.dyn-change-note__count');
    let count = parseInt(countEl?.dataset?.count || '1', 10) + 1;
    if (countEl) {
      countEl.dataset.count = String(count);
      countEl.textContent = `×${count}`;
    }
    // 更新 reason 为最新
    const reasonEl = note.querySelector('.dyn-change-note__reason');
    if (reasonEl) reasonEl.textContent = reason;
    return;
  }
  note = document.createElement('div');
  note.className = 'dyn-change-note';
  note.innerHTML = `
    <span class="dyn-change-note__icon">⚡</span>
    <span class="dyn-change-note__reason">${escapeHtml(reason)}</span>
    <span class="dyn-change-note__count" data-count="1"></span>
    <button class="dyn-change-note__close" title="我知道了">✕</button>
  `;
  note.querySelector('.dyn-change-note__close').addEventListener('click', () => {
    note.remove();
  });
  // insertBefore 让浮层位于卡片内容最顶部
  itemEl.insertBefore(note, itemEl.firstChild);
}

/**
 * 建议模式确认对话框（FR-31）
 */
function showSuggestDialog(optimizeResp, onAdopt) {
  const diff = optimizeResp.diff || [];
  const items = diff.map(op => `
    <li>
      <strong>${escapeHtml(op.op)}</strong> · Day ${op.day} · ${escapeHtml(op.target_field)}:
      "${escapeHtml(op.old_item?.name || '')}" → "${escapeHtml(op.new_item?.name || '')}"
      ${op.reason ? `<br><span class="dyn-suggest-reason">${escapeHtml(op.reason)}</span>` : ''}
      ${op.new_item?.source_url ? `<br><a class="source-link" href="${escapeHtml(op.new_item.source_url)}" target="_blank" rel="noopener">来源 ↗</a>` : ''}
    </li>`).join('');
  const modal = document.createElement('div');
  modal.className = 'dyn-modal';
  modal.innerHTML = `
    <div class="dyn-modal__backdrop"></div>
    <div class="dyn-modal__dialog">
      <h3>动态优化建议</h3>
      <p>tg-monitor 检测到触发条件，tg-optimizer 产出以下变更：</p>
      <ul class="dyn-modal__list">${items}</ul>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button class="btn btn--secondary" id="dyn-reject">驳回</button>
        <button class="btn btn--primary" id="dyn-adopt">采纳</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelector('#dyn-adopt').addEventListener('click', () => {
    modal.remove();
    onAdopt();
  });
  modal.querySelector('#dyn-reject').addEventListener('click', () => {
    modal.remove();
    showToast('已驳回建议');
  });
  modal.querySelector('.dyn-modal__backdrop').addEventListener('click', () => modal.remove());
}

/**
 * 撤销上次变更（TR-21.3）
 */
async function onUndo() {
  const result = getCurrentResult();
  const planId = result?.planId;
  if (!planId) return;
  // 找到上一个 adopted 之前的版本
  try {
    const data = await fetchVersions(planId);
    const versions = data.versions || [];
    // 当前版本是最新 adopted；找它前一个
    const cur = versions.find(v => v.adopted);
    const prev = versions.find(v => v.version_id !== cur?.version_id && v.trigger_reason?.startsWith('revert_') === false);
    // 简化：用 changelog 里的 version_id 回滚
    const lastEntry = changelog[0];
    if (!lastEntry) {
      showToast('无可撤销的变更');
      return;
    }
    // 拉版本列表找上一个
    const sorted = versions.filter(v => v.adopted).sort((a, b) => b.ts - a.ts);
    const curIdx = sorted.findIndex(v => v.version_id === lastEntry.version_id);
    const target = sorted[curIdx + 1] || versions.find(v => v.trigger_reason === 'initial_generate');
    if (!target) {
      showToast('未找到可回滚的上一版本');
      return;
    }
    showToast('正在回滚...');
    const r = await revertToVersion(planId, target.version_id);
    setCurrentResult({ ...result, plan: r.plan });
    // 重新渲染整个手册（简化但稳）
    const { renderCurrent } = await import('./renderer.js');
    await renderCurrent();
    // 徽章计数不变（保留历史，TR-21.3）
    showToast(`已回滚到 ${target.version_id.slice(0, 16)}（计数保留 ${updateCount} 次）`);
  } catch (e) {
    showToast(`撤销失败：${e.message}`);
  }
}

/**
 * 渲染 changelog 抽屉内容
 */
function renderChangelog() {
  const listEl = document.querySelector('.dyn-changelog__list');
  if (!listEl) return;
  if (changelog.length === 0) {
    listEl.innerHTML = '<li>暂无变更</li>';
    return;
  }
  // 抽屉底部加"版本对比"入口（Task 23）
  const itemsHtml = changelog.map((e, idx) => `
    <li class="dyn-changelog__item">
      <span class="dyn-changelog__time">${escapeHtml(e.ts.slice(11, 19))}</span>
      <span class="dyn-changelog__op dyn-changelog__op--${escapeHtml((e.op || '?').toLowerCase())}">${escapeHtml(e.op || '?')}</span>
      <span>Day ${e.day ?? '?'} · ${escapeHtml(e.target_field || '')}</span>
      <span>"${escapeHtml(e.old_name || '')}" → "${escapeHtml(e.new_name || '')}"</span>
      <span class="dyn-changelog__reason">${escapeHtml(e.reason || '')}</span>
      ${e.source_url ? `<a class="source-link" href="${escapeHtml(e.source_url)}" target="_blank" rel="noopener">来源 ↗</a>` : ''}
      <span class="dyn-changelog__adopted">${e.adopted ? '✓ 已采纳' : '✗ 已驳回'}</span>
      ${e.version_id ? `<button class="btn btn--secondary btn--sm dyn-compare-btn" data-idx="${idx}" title="与上一版本对比差异">⇄ 对比</button>` : ''}
    </li>`).join('');
  listEl.innerHTML = itemsHtml;
  // 绑定对比按钮
  listEl.querySelectorAll('.dyn-compare-btn').forEach(btn => {
    btn.addEventListener('click', () => onCompareVersion(parseInt(btn.dataset.idx, 10)));
  });
}

/**
 * 版本对比对话框（Task 23）：拉取后端 diff_versions，展示字段级差异
 */
async function onCompareVersion(idx) {
  const entry = changelog[idx];
  if (!entry?.version_id) return;
  // 找它的前一条 changelog 项作为 from
  const prevEntry = changelog.slice(idx + 1).find(e => e.version_id && e.version_id !== entry.version_id);
  const planId = getCurrentPlanId() || getCurrentResult()?.planId;
  if (!planId) {
    showToast('未找到 plan_id');
    return;
  }
  // 若没有 prev，则用 fetchVersions 找最早版本
  let fromId = prevEntry?.version_id;
  if (!fromId) {
    try {
      const data = await fetchVersions(planId);
      const sorted = (data.versions || []).slice().sort((a, b) => (a.ts || 0) - (b.ts || 0));
      fromId = sorted[0]?.version_id;
    } catch (e) { /* ignore */ }
  }
  if (!fromId || fromId === entry.version_id) {
    showToast('无可对比的上一版本');
    return;
  }
  try {
    const diff = await diffVersions(planId, fromId, entry.version_id);
    _showCompareModal(diff);
  } catch (e) {
    showToast(`对比失败：${e.message}`);
  }
}

function _showCompareModal(diff) {
  const changes = diff.changes || [];
  const fromInfo = diff.from || {};
  const toInfo = diff.to || {};
  const changesHtml = changes.length ? changes.map(c => `
    <li>
      <strong>Day ${c.day} · ${escapeHtml(c.field)}</strong><br>
      ${c.removed?.length ? `<span style="color:#c0392b;">移除: ${escapeHtml(c.removed.join(', '))}</span><br>` : ''}
      ${c.added?.length ? `<span style="color:#27ae60;">新增: ${escapeHtml(c.added.join(', '))}</span><br>` : ''}
      ${(!c.removed?.length && !c.added?.length) ? `<span style="color:var(--page-text-muted);">顺序调整：${escapeHtml((c.from_items || []).join(' → '))} → ${escapeHtml((c.to_items || []).join(' → '))}</span>` : ''}
    </li>`).join('') : '<li>无差异</li>';
  const modal = document.createElement('div');
  modal.className = 'dyn-modal';
  modal.innerHTML = `
    <div class="dyn-modal__backdrop"></div>
    <div class="dyn-modal__dialog">
      <h3>版本对比</h3>
      <p style="color:var(--page-text-muted);font-size:0.82rem;">
        从 ${escapeHtml(fromInfo.ts_iso || '')} → 到 ${escapeHtml(toInfo.ts_iso || '')}
      </p>
      <ul class="dyn-modal__list">${changesHtml}</ul>
      <div style="display:flex;gap:8px;justify-content:flex-end;">
        <button class="btn btn--secondary" id="dyn-compare-close">关闭</button>
      </div>
    </div>
  `;
  document.body.appendChild(modal);
  modal.querySelector('#dyn-compare-close').addEventListener('click', () => modal.remove());
  modal.querySelector('.dyn-modal__backdrop').addEventListener('click', () => modal.remove());
}

/**
 * 顶部 toast 提示
 */
let toastTimer = null;
function showToast(msg) {
  let el = document.getElementById('dyn-toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'dyn-toast';
    el.className = 'dyn-toast';
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.classList.add('visible');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove('visible'), 3000);
}

/**
 * 检查动态优化是否启用（供 renderer 决定是否挂载控件，TR-21.4）
 */
export function isDynamicEnabled() {
  return loadConfig().dynamic_enabled === true;
}

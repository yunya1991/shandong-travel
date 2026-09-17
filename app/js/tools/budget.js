// 预算追踪：计划 vs 实际，实时计算差额，持久化
import { getCurrentPlan, getCurrentPlanId } from '../generate.js';
import { escapeHtml } from '../config.js';

const CATEGORIES = [
  { key: 'accommodation', label: '住宿' },
  { key: 'transport', label: '交通' },
  { key: 'food', label: '餐饮' },
  { key: 'tickets', label: '门票' },
  { key: 'other', label: '其他' }
];

function getKey() {
  return `tg_budget_${getCurrentPlanId() || 'default'}`;
}

function loadActual() {
  try {
    return JSON.parse(localStorage.getItem(getKey()) || '{}');
  } catch { return {}; }
}

function saveActual(data) {
  localStorage.setItem(getKey(), JSON.stringify(data));
}

export function renderBudget() {
  const container = document.getElementById('budget-content');
  const plan = getCurrentPlan();
  if (!plan || !plan.budget) {
    container.innerHTML = `<div class="empty-hint">请先生成旅游手册，再查看预算</div>`;
    return;
  }

  const budget = plan.budget;
  const actual = loadActual();

  const rows = CATEGORIES.map(cat => {
    const planned = Number(budget[cat.key] || 0);
    const act = Number(actual[cat.key] || 0);
    const diff = act - planned;
    const diffClass = diff > 0 ? 'diff-neg' : diff < 0 ? 'diff-pos' : '';
    const diffSign = diff > 0 ? '+' : '';
    return `
      <tr>
        <td>${cat.label}</td>
        <td>¥${planned.toLocaleString()}</td>
        <td><input type="number" min="0" value="${act || ''}" data-cat="${cat.key}" placeholder="0"></td>
        <td class="${diffClass}">${diffSign}¥${diff.toLocaleString()}</td>
      </tr>`;
  }).join('');

  container.innerHTML = `
    <div class="tool-header">
      <h2>预算追踪</h2>
      <p style="color:var(--page-text-muted);font-size:0.9rem;">输入实际花费，自动计算差额。数据自动保存。</p>
    </div>
    <div class="budget-tool">
      <table class="budget-table">
        <thead><tr><th>项目</th><th>计划</th><th>实际</th><th>差额</th></tr></thead>
        <tbody>${rows}</tbody>
        <tfoot id="budget-tfoot"></tfoot>
      </table>
    </div>
  `;

  updateTotals(container, budget);

  container.querySelectorAll('input[data-cat]').forEach(input => {
    input.addEventListener('input', () => {
      const actual = loadActual();
      actual[input.dataset.cat] = Number(input.value) || 0;
      saveActual(actual);
      updateTotals(container, budget);
    });
  });
}

function updateTotals(container, budget) {
  const actual = loadActual();
  let totalPlanned = 0, totalActual = 0;
  CATEGORIES.forEach(cat => {
    totalPlanned += Number(budget[cat.key] || 0);
    totalActual += Number(actual[cat.key] || 0);
  });
  const diff = totalActual - totalPlanned;
  const diffClass = diff > 0 ? 'diff-neg' : diff < 0 ? 'diff-pos' : '';
  const diffSign = diff > 0 ? '+' : '';

  const tfoot = container.querySelector('#budget-tfoot');
  tfoot.innerHTML = `
    <tr class="total-row">
      <td>合计</td>
      <td>¥${totalPlanned.toLocaleString()}</td>
      <td>¥${totalActual.toLocaleString()}</td>
      <td class="${diffClass}">${diffSign}¥${diff.toLocaleString()}</td>
    </tr>`;
}

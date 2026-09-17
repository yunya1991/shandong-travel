// 行前打包清单：分类、勾选、增删、持久化
import { getCurrentPlan, getCurrentPlanId } from '../generate.js';
import { escapeHtml } from '../config.js';

const CATEGORIES = [
  { key: 'docs', name: '证件票据', icon: '📄' },
  { key: 'clothes', name: '衣物', icon: '👕' },
  { key: 'electronics', name: '电子设备', icon: '🔌' },
  { key: 'toiletries', name: '洗漱用品', icon: '🧴' },
  { key: 'medicine', name: '药品', icon: '💊' },
  { key: 'other', name: '其他', icon: '📦' }
];

const DEFAULT_ITEMS = {
  docs: ['身份证', '驾驶证（自驾）', '行程单/酒店订单', '学生证/老年证'],
  clothes: ['内衣裤', '外套（按季节）', '舒适步行鞋', '睡衣', '袜子'],
  electronics: ['手机+充电器', '充电宝', '相机/相机充电器', '转换插头'],
  toiletries: ['牙刷/牙膏', '洗面奶', '护肤品', '毛巾'],
  medicine: ['感冒药', '肠胃药', '创可贴', '晕车药'],
  other: ['雨伞/雨衣', '墨镜', '保温杯', '零食']
};

function getKey() {
  return `tg_checklist_${getCurrentPlanId() || 'default'}`;
}

function loadState() {
  try {
    return JSON.parse(localStorage.getItem(getKey()) || 'null');
  } catch { return null; }
}

function saveState(state) {
  localStorage.setItem(getKey(), JSON.stringify(state));
}

export function renderChecklist() {
  const container = document.getElementById('checklist-content');
  const plan = getCurrentPlan();
  if (!plan) {
    container.innerHTML = `<div class="empty-hint">请先生成旅游手册，再查看行前清单</div>`;
    return;
  }

  let state = loadState();
  if (!state) {
    state = {};
    CATEGORIES.forEach(cat => {
      state[cat.key] = (DEFAULT_ITEMS[cat.key] || []).map(text => ({ text, checked: false }));
    });
    // 根据天数/季节微调
    const days = plan.overview?.days || 5;
    if (days > 3) state.clothes.push({ text: `额外${days - 2}套换洗衣物`, checked: false });
    saveState(state);
  }

  const sections = CATEGORIES.map(cat => {
    const items = state[cat.key] || [];
    const checkedCount = items.filter(i => i.checked).length;
    const rows = items.map((item, idx) => `
      <div class="checklist-item ${item.checked ? 'checked' : ''}" data-cat="${cat.key}" data-idx="${idx}">
        <input type="checkbox" ${item.checked ? 'checked' : ''}>
        <span class="checklist-item__text">${escapeHtml(item.text)}</span>
        <button class="checklist-item__del" title="删除">×</button>
      </div>`).join('');
    return `
      <div class="checklist-cat">
        <div class="checklist-cat__title">${cat.icon} ${cat.name} <span class="checklist-cat__count">${checkedCount}/${items.length}</span></div>
        ${rows}
        <div class="checklist-add">
          <input class="form-input" placeholder="添加${cat.name}条目..." data-add-cat="${cat.key}">
          <button class="btn btn--secondary btn--sm" data-add-btn="${cat.key}">添加</button>
        </div>
      </div>`;
  }).join('');

  container.innerHTML = `
    <div class="tool-header">
      <h2>行前打包清单</h2>
      <p style="color:var(--page-text-muted);font-size:0.9rem;">根据行程自动生成，可自由增删，勾选状态自动保存</p>
    </div>
    ${sections}
  `;

  bindEvents(container);
}

function bindEvents(container) {
  container.querySelectorAll('.checklist-item').forEach(row => {
    const cat = row.dataset.cat;
    const idx = parseInt(row.dataset.idx, 10);
    const cb = row.querySelector('input[type="checkbox"]');
    const text = row.querySelector('.checklist-item__text');
    const del = row.querySelector('.checklist-item__del');

    cb.addEventListener('change', () => {
      const state = loadState();
      state[cat][idx].checked = cb.checked;
      saveState(state);
      row.classList.toggle('checked', cb.checked);
      // 更新计数
      const countEl = row.closest('.checklist-cat').querySelector('.checklist-cat__count');
      const items = state[cat];
      countEl.textContent = `${items.filter(i => i.checked).length}/${items.length}`;
    });

    del.addEventListener('click', () => {
      const state = loadState();
      state[cat].splice(idx, 1);
      saveState(state);
      renderChecklist();
    });
  });

  container.querySelectorAll('[data-add-cat]').forEach(input => {
    const cat = input.dataset.addCat;
    const btn = container.querySelector(`[data-add-btn="${cat}"]`);
    const add = () => {
      const text = input.value.trim();
      if (!text) return;
      const state = loadState();
      state[cat].push({ text, checked: false });
      saveState(state);
      input.value = '';
      renderChecklist();
    };
    btn.addEventListener('click', add);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') add(); });
  });
}

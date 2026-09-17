// 应用入口：导航切换、视图调度
import { initSettings } from './config.js';
import { initGenerate } from './generate.js';

const tabs = document.querySelectorAll('.app-nav__tab');
const views = document.querySelectorAll('.view');

export function switchView(viewName) {
  tabs.forEach(t => t.classList.toggle('active', t.dataset.view === viewName));
  views.forEach(v => v.classList.toggle('active', v.id === `view-${viewName}`));
  // 触发视图初始化
  if (viewName === 'checklist') { import('./tools/checklist.js').then(m => m.renderChecklist()); }
  if (viewName === 'budget') { import('./tools/budget.js').then(m => m.renderBudget()); }
  if (viewName === 'favorites') { import('./tools/favorites.js').then(m => m.renderFavorites()); }
  if (viewName === 'guide') { import('./renderer.js').then(m => m.renderCurrent()); }
  if (viewName === 'debug') { import('./debug.js').then(m => m.renderDebug()); }
}

tabs.forEach(tab => {
  tab.addEventListener('click', () => switchView(tab.dataset.view));
});

// 启动
initSettings();
initGenerate();

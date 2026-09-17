// 收藏管理：景点/美食收藏，本地持久化
import { getCurrentPlanId } from '../generate.js';

function getKey() {
  return `tg_favorites_${getCurrentPlanId() || 'default'}`;
}

export function getFavorites() {
  try {
    return JSON.parse(localStorage.getItem(getKey()) || '{}');
  } catch {
    return {};
  }
}

export function toggleFavorite(type, name) {
  const favs = getFavorites();
  const key = `${type}:${name}`;
  if (favs[key]) delete favs[key];
  else favs[key] = { type, name, time: Date.now() };
  localStorage.setItem(getKey(), JSON.stringify(favs));
  return favs;
}

export function renderFavorites() {
  const container = document.getElementById('favorites-content');
  const plan = (() => { try { return JSON.parse(localStorage.getItem('tg_current_plan') || '{}').plan; } catch { return null; } })();

  if (!plan) {
    container.innerHTML = `<div class="empty-hint">尚未生成旅游手册，暂无收藏</div>`;
    return;
  }

  const favs = getFavorites();
  const entries = Object.values(favs);
  if (entries.length === 0) {
    container.innerHTML = `<div class="empty-hint">还没有收藏内容，去手册页点击 ☆ 收藏景点或美食吧</div>`;
    return;
  }

  const byType = { attraction: [], food: [] };
  entries.forEach(e => (byType[e.type] || []).push(e));

  const findItem = (type, name) => {
    const list = type === 'attraction' ? plan.attractions : plan.food;
    return (list || []).find(x => x.name === name);
  };

  const renderList = (type, title) => {
    const items = byType[type].map(e => {
      const item = findItem(type, e.name);
      return `<div class="attraction-item">
        <div class="attraction-item__name">${e.name}</div>
        ${item?.desc ? `<div class="attraction-item__desc">${item.desc}</div>` : ''}
      </div>`;
    }).join('');
    return `<h3>${title}</h3><div class="attraction-list">${items}</div>`;
  };

  container.innerHTML = `
    <div class="tool-header"><h2>我的收藏</h2></div>
    ${byType.attraction.length ? renderList('attraction', '景点') : ''}
    ${byType.food.length ? renderList('food', '美食') : ''}
  `;
}

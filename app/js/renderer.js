// 手册渲染器：将 plan 渲染为 8 大模块
import { getCurrentPlan } from './generate.js';
import { escapeHtml } from './config.js';
import { fetchImages } from './images.js';
import { getFavorites, toggleFavorite } from './tools/favorites.js';

/**
 * 渲染当前方案到手册视图
 */
export async function renderCurrent() {
  const plan = getCurrentPlan();
  const container = document.getElementById('guide-content');
  if (!plan) {
    container.innerHTML = `
      <div class="empty-hint">
        <p>尚未生成旅游手册</p>
        <p style="margin-top:8px;font-size:0.85rem;">请先到「生成手册」页输入目的地</p>
      </div>`;
    return;
  }

  // 先立即渲染（占位图），不阻塞内容展示
  container.innerHTML = renderPlan(plan, new Map());
  bindFavButtons(container, plan);

  // 异步加载图片，加载完成后更新 DOM
  loadImagesAsync(plan, container);
}

async function loadImagesAsync(plan, container) {
  const queries = [];
  plan.attractions?.forEach(a => queries.push(a.image_query || a.name));
  plan.food?.forEach(f => queries.push(f.image_query || f.name));
  plan.daily?.forEach(d => {
    d.attractions?.forEach(a => queries.push(a.image_query || a.name));
    d.food?.forEach(f => queries.push(f.image_query || f.name));
  });

  let imageMap = new Map();
  try {
    imageMap = await fetchImages(queries);
  } catch {}

  // 更新有图片的卡片
  const items = container.querySelectorAll('.attraction-item');
  items.forEach((card, idx) => {
    const nameEl = card.querySelector('.attraction-item__name');
    const name = nameEl?.textContent?.trim();
    if (!name) return;
    const q = name;
    const url = imageMap.get(q);
    if (!url) return;
    const placeholder = card.querySelector('.attraction-item__img');
    if (placeholder && placeholder.tagName === 'DIV') {
      const img = document.createElement('img');
      img.className = 'attraction-item__img';
      img.src = url;
      img.alt = name;
      img.loading = 'lazy';
      img.onerror = () => { img.style.display = 'none'; };
      placeholder.replaceWith(img);
    }
  });
}

function renderPlan(plan, imageMap) {
  return `
  <article class="guide">
    ${renderOverview(plan.overview)}
    ${renderRouteMap(plan.route)}
    ${renderDaily(plan.daily, imageMap)}
    ${renderAttractions(plan.attractions, imageMap)}
    ${renderAccommodation(plan.accommodation)}
    ${renderFood(plan.food, imageMap)}
    ${renderBudget(plan.budget)}
    ${renderTips(plan.tips)}
    ${renderExportBar()}
  </article>`;
}

function renderOverview(o) {
  const highlights = (o.highlights || []).map(h => `
    <div class="report-intro__highlight">
      <span class="report-intro__highlight-dot"></span>
      <span>${escapeHtml(h)}</span>
    </div>`).join('');
  return `
  <section class="report-intro">
    <div class="report-intro__surface">
      <div class="report-intro__content">
        <h1>${escapeHtml(o.title)}</h1>
        <p class="report-intro__subtitle">${escapeHtml(o.dates)} · ${o.days}天${o.travelers ? ` · ${o.travelers}人` : ''}</p>
        <p class="report-intro__summary">
          出发地：${escapeHtml(o.departure)} ｜ 主题：${escapeHtml(o.route_theme)} ｜ 里程：${escapeHtml(o.mileage)}<br>
          适合：${escapeHtml(o.suitable_people)} ｜ 提示：${escapeHtml(o.tips)}
        </p>
        <div class="report-intro__highlights">${highlights}</div>
      </div>
    </div>
  </section>`;
}

function renderRouteMap(route) {
  if (!route || route.length === 0) return '';
  const n = route.length;
  const w = 900, h = 200 + Math.min(n, 6) * 20;
  const padX = 80;
  const usable = w - padX * 2;
  const points = route.map((node, i) => {
    const x = n === 1 ? w / 2 : padX + (usable * i / (n - 1));
    const y = 100 + (i % 2) * 40;
    return { x, y, node };
  });
  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');

  const nodes = points.map(p => `
    <g>
      <circle cx="${p.x}" cy="${p.y}" r="20" fill="#B8551D"/>
      <circle cx="${p.x}" cy="${p.y}" r="20" fill="none" stroke="#FBF0EA" stroke-width="2"/>
      <text x="${p.x}" y="${p.y + 5}" text-anchor="middle" fill="#fff" font-size="12" font-weight="700">${escapeHtml(p.node.name)}</text>
      <text x="${p.x}" y="${p.y + 40}" text-anchor="middle" fill="#5C4A40" font-size="10">${escapeHtml(p.node.day || '')}</text>
    </g>`).join('');

  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3z"/><path d="M9 3v15M15 6v15"/></svg>
      路线地图
    </h2>
    <div class="route-map">
      <svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg">
        <rect width="${w}" height="${h}" fill="#FAF6F2"/>
        <path d="${linePath}" fill="none" stroke="url(#rg)" stroke-width="3" stroke-dasharray="8 6"/>
        <defs><linearGradient id="rg" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stop-color="#B8551D"/><stop offset="100%" stop-color="#D97757"/>
        </linearGradient></defs>
        ${nodes}
      </svg>
      <div class="route-map__caption">路线示意图</div>
    </div>
  </section>`;
}

function renderDaily(daily, imageMap) {
  if (!daily || daily.length === 0) return '';
  const cards = daily.map(d => {
    const attrs = (d.attractions || []).map(a => `
      <div class="attraction-item">
        <div class="attraction-item__name">${escapeHtml(a.name)}</div>
        <div class="attraction-item__meta">
          ${a.ticket ? `<span class="attraction-item__tag">${escapeHtml(a.ticket)}</span>` : ''}
          ${a.duration ? `<span class="attraction-item__tag">${escapeHtml(a.duration)}</span>` : ''}
        </div>
        <div class="attraction-item__desc">${escapeHtml(a.desc)}</div>
      </div>`).join('');
    const foods = (d.food || []).map(f => `
      <div class="food-item">
        <svg class="food-item__icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11h18M5 11v8a2 2 0 002 2h10a2 2 0 002-2v-8M7 11V7a5 5 0 0110 0v4"/></svg>
        <div class="food-item__text"><strong>${escapeHtml(f.name)}</strong>：${escapeHtml(f.desc)}</div>
      </div>`).join('');
    return `
    <div class="day-card">
      <div class="day-card__header">
        <span class="day-card__badge">Day ${d.day}</span>
        <div>
          <div class="day-card__title">${escapeHtml(d.city)} · ${escapeHtml(d.title)}</div>
          <div class="day-card__subtitle">${escapeHtml(d.date || '')} ${d.subtitle ? '· ' + escapeHtml(d.subtitle) : ''}</div>
        </div>
      </div>
      ${attrs ? `<h3>景点</h3><div class="attraction-list">${attrs}</div>` : ''}
      ${foods ? `<h3>美食</h3><div class="food-list">${foods}</div>` : ''}
      ${d.transport ? `<div class="transport-box"><strong>交通</strong><br>${escapeHtml(d.transport)}</div>` : ''}
      ${d.accommodation ? `<div class="transport-box"><strong>住宿</strong><br>${escapeHtml(d.accommodation)}</div>` : ''}
    </div>`;
  }).join('');

  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="18" rx="2"/><path d="M3 10h18M8 2v4M16 2v4"/></svg>
      每日行程
    </h2>
    ${cards}
  </section>`;
}

function attractionCard(a, imageMap, type) {
  const q = a.image_query || a.name;
  const imgUrl = imageMap.get(q);
  const img = imgUrl
    ? `<img class="attraction-item__img" src="${escapeHtml(imgUrl)}" alt="${escapeHtml(a.name)}" loading="lazy" onerror="this.style.display='none'">`
    : `<div class="attraction-item__img">${escapeHtml(a.name?.charAt(0) || '图')}</div>`;
  const favs = getFavorites();
  const isFav = favs[`${type}:${a.name}`];
  return `
  <div class="attraction-item">
    ${img}
    <button class="attraction-item__fav" data-fav-type="${type}" data-fav-name="${escapeHtml(a.name)}" title="收藏">${isFav ? '★' : '☆'}</button>
    <div class="attraction-item__name">${escapeHtml(a.name)}</div>
    <div class="attraction-item__meta">
      ${a.ticket ? `<span class="attraction-item__tag">${escapeHtml(a.ticket)}</span>` : ''}
      ${a.duration ? `<span class="attraction-item__tag">${escapeHtml(a.duration)}</span>` : ''}
      ${(a.tags || []).map(t => `<span class="attraction-item__tag">${escapeHtml(t)}</span>`).join('')}
    </div>
    <div class="attraction-item__desc">${escapeHtml(a.desc)}</div>
  </div>`;
}

function renderAttractions(attractions, imageMap) {
  if (!attractions || attractions.length === 0) return '';
  const cards = attractions.map(a => attractionCard(a, imageMap, 'attraction')).join('');
  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 20l5-7 4 5 3-4 6 6z"/><path d="M3 20h18"/></svg>
      精彩景点
    </h2>
    <div class="attraction-list">${cards}</div>
  </section>`;
}

function renderAccommodation(acc) {
  if (!acc || acc.length === 0) return '';
  const cards = acc.map(a => `
    <div class="accommodation-item">
      <div class="accommodation-item__name">${escapeHtml(a.name)}</div>
      <div class="accommodation-item__area">${escapeHtml(a.area)}</div>
      <div class="accommodation-item__price">${escapeHtml(a.price_range)}</div>
      <div class="accommodation-item__desc">${escapeHtml(a.desc)}</div>
    </div>`).join('');
  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 21V7l9-4 9 4v14"/><path d="M3 21h18M9 21v-6h6v6"/></svg>
      住宿推荐
    </h2>
    <div class="accommodation-list">${cards}</div>
  </section>`;
}

function renderFood(food, imageMap) {
  if (!food || food.length === 0) return '';
  const cards = food.map(f => attractionCard(f, imageMap, 'food')).join('');
  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 11h18M5 11v8a2 2 0 002 2h10a2 2 0 002-2v-8"/></svg>
      美食推荐
    </h2>
    <div class="attraction-list">${cards}</div>
  </section>`;
}

function renderBudget(b) {
  if (!b) return '';
  const rows = [
    { label: '住宿', val: b.accommodation },
    { label: '交通', val: b.transport },
    { label: '餐饮', val: b.food },
    { label: '门票', val: b.tickets },
    { label: '其他', val: b.other }
  ];
  const trs = rows.map(r => `
    <tr><td>${r.label}</td><td>¥${Number(r.val || 0).toLocaleString()}</td></tr>
  `).join('');
  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="12" y1="1" x2="12" y2="23"/><path d="M17 5H9.5a3.5 3.5 0 000 7h5a3.5 3.5 0 010 7H6"/></svg>
      费用预估
    </h2>
    <table class="itinerary-table">
      <thead><tr><th>项目</th><th>预算（元）</th></tr></thead>
      <tbody>${trs}
        <tr class="total-row"><td>合计</td><td>¥${Number(b.total || 0).toLocaleString()}</td></tr>
      </tbody>
    </table>
    <div class="budget-summary">
      <div class="budget-summary__item"><div class="budget-summary__label">合计</div><div class="budget-summary__value">¥${Number(b.total || 0).toLocaleString()}</div></div>
      <div class="budget-summary__item"><div class="budget-summary__label">人均</div><div class="budget-summary__value">¥${Number(b.per_person || 0).toLocaleString()}</div></div>
    </div>
  </section>`;
}

function renderTips(tips) {
  if (!tips || tips.length === 0) return '';
  const lis = tips.map(t => `<li>${escapeHtml(t)}</li>`).join('');
  return `
  <section>
    <h2>
      <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
      出行贴士
    </h2>
    <div class="tip-callout">
      <div class="tip-callout__title">旅行小贴士</div>
      <ul>${lis}</ul>
    </div>
  </section>`;
}

function renderExportBar() {
  return `
  <div style="position:sticky;bottom:16px;display:flex;gap:12px;justify-content:center;margin-top:32px;">
    <button class="btn btn--primary" id="export-html">导出 HTML</button>
    <button class="btn btn--secondary" id="export-image">导出长图</button>
  </div>`;
}

function bindFavButtons(container, plan) {
  container.querySelectorAll('[data-fav-name]').forEach(btn => {
    btn.addEventListener('click', () => {
      const type = btn.dataset.favType;
      const name = btn.dataset.favName;
      toggleFavorite(type, name);
      btn.textContent = btn.textContent === '★' ? '☆' : '★';
    });
  });

  const exportHtmlBtn = container.querySelector('#export-html');
  if (exportHtmlBtn) {
    exportHtmlBtn.addEventListener('click', async () => {
      const { exportHtml } = await import('./export/html.js');
      exportHtml(plan);
    });
  }
  const exportImageBtn = container.querySelector('#export-image');
  if (exportImageBtn) {
    exportImageBtn.addEventListener('click', async () => {
      const { exportImage } = await import('./export/image.js');
      exportImage(plan);
    });
  }
}

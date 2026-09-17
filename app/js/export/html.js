// 导出静态 HTML：内联 CSS + 数据，可离线打开
import { escapeHtml } from '../config.js';

export function exportHtml(plan) {
  // 读取 styles.css 内容
  let css = '';
  try {
    // 通过 fetch 读取（需通过 http 服务器运行），失败则用内联最小样式
  } catch {}

  const cssInline = css || getInlineCss();

  const html = `<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>${escapeHtml(plan.overview?.title || '旅游手册')}</title>
<style>${cssInline}</style>
</head>
<body>
<div class="app-main">
${renderStatic(plan)}
</div>
<footer class="app-footer">旅游手册生成器 · AI 生成内容仅供参考 · 图片来源 Wikimedia Commons</footer>
</body>
</html>`;

  const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${plan.overview?.title || 'travel-guide'}.html`;
  a.click();
  URL.revokeObjectURL(url);
}

function renderStatic(plan) {
  const o = plan.overview || {};
  const highlights = (o.highlights || []).map(h => `<div class="report-intro__highlight"><span class="report-intro__highlight-dot"></span><span>${escapeHtml(h)}</span></div>`).join('');
  const daily = (plan.daily || []).map(d => {
    const attrs = (d.attractions || []).map(a => `<div class="attraction-item"><div class="attraction-item__name">${escapeHtml(a.name)}</div><div class="attraction-item__meta">${a.ticket?`<span class="attraction-item__tag">${escapeHtml(a.ticket)}</span>`:''}${a.duration?`<span class="attraction-item__tag">${escapeHtml(a.duration)}</span>`:''}</div><div class="attraction-item__desc">${escapeHtml(a.desc)}</div></div>`).join('');
    return `<div class="day-card"><div class="day-card__header"><span class="day-card__badge">Day ${d.day}</span><div><div class="day-card__title">${escapeHtml(d.city)} · ${escapeHtml(d.title)}</div></div></div>${attrs?`<div class="attraction-list">${attrs}</div>`:''}${d.transport?`<div class="transport-box"><strong>交通</strong><br>${escapeHtml(d.transport)}</div>`:''}</div>`;
  }).join('');
  const attractions = (plan.attractions || []).map(a => `<div class="attraction-item"><div class="attraction-item__name">${escapeHtml(a.name)}</div><div class="attraction-item__meta">${a.ticket?`<span class="attraction-item__tag">${escapeHtml(a.ticket)}</span>`:''}${a.duration?`<span class="attraction-item__tag">${escapeHtml(a.duration)}</span>`:''}</div><div class="attraction-item__desc">${escapeHtml(a.desc)}</div></div>`).join('');
  const food = (plan.food || []).map(f => `<div class="attraction-item"><div class="attraction-item__name">${escapeHtml(f.name)}</div><div class="attraction-item__desc">${escapeHtml(f.desc)}</div></div>`).join('');
  const acc = (plan.accommodation || []).map(a => `<div class="accommodation-item"><div class="accommodation-item__name">${escapeHtml(a.name)}</div><div class="accommodation-item__price">${escapeHtml(a.price_range)}</div><div class="accommodation-item__desc">${escapeHtml(a.desc)}</div></div>`).join('');
  const tips = (plan.tips || []).map(t => `<li>${escapeHtml(t)}</li>`).join('');
  const b = plan.budget || {};

  return `
  <header class="report-intro"><div class="report-intro__surface"><div class="report-intro__content">
    <h1>${escapeHtml(o.title)}</h1>
    <p class="report-intro__subtitle">${escapeHtml(o.dates)} · ${o.days}天</p>
    <p class="report-intro__summary">出发地：${escapeHtml(o.departure)} ｜ 主题：${escapeHtml(o.route_theme)}<br>适合：${escapeHtml(o.suitable_people)}</p>
    <div class="report-intro__highlights">${highlights}</div>
  </div></div></header>
  <section><h2>每日行程</h2>${daily}</section>
  <section><h2>精彩景点</h2><div class="attraction-list">${attractions}</div></section>
  <section><h2>住宿推荐</h2><div class="accommodation-list">${acc}</div></section>
  <section><h2>美食推荐</h2><div class="attraction-list">${food}</div></section>
  <section><h2>费用预估</h2>
    <table class="itinerary-table"><thead><tr><th>项目</th><th>预算</th></tr></thead><tbody>
    <tr><td>住宿</td><td>¥${Number(b.accommodation||0).toLocaleString()}</td></tr>
    <tr><td>交通</td><td>¥${Number(b.transport||0).toLocaleString()}</td></tr>
    <tr><td>餐饮</td><td>¥${Number(b.food||0).toLocaleString()}</td></tr>
    <tr><td>门票</td><td>¥${Number(b.tickets||0).toLocaleString()}</td></tr>
    <tr><td>其他</td><td>¥${Number(b.other||0).toLocaleString()}</td></tr>
    <tr class="total-row"><td>合计</td><td>¥${Number(b.total||0).toLocaleString()}（人均 ¥${Number(b.per_person||0).toLocaleString()}）</td></tr>
    </tbody></table>
  </section>
  <section><h2>出行贴士</h2><div class="tip-callout"><ul>${tips}</ul></div></section>`;
}

// 内联的最小样式（当 fetch styles.css 失败时使用）
function getInlineCss() {
  return `
:root{--accent:#B8551D;--page-bg:#fff;--page-surface:#FAF6F2;--page-text:#2A1F1A;--page-text-secondary:#5C4A40;--page-text-muted:#8A7568;--page-border:#E0D5CC;--page-brand-soft:#FBF0EA;--accent2:#D97757}
body{font-family:'PingFang SC','Microsoft YaHei',sans-serif;color:var(--page-text);background:var(--page-surface);line-height:1.7;margin:0}
.app-main{max-width:960px;margin:0 auto;padding:24px 16px}
.report-intro__surface{background:var(--page-brand-soft);border-radius:12px;padding:48px 32px;position:relative;overflow:hidden}
.report-intro h1{font-size:2rem;margin:0 0 8px}
.report-intro__subtitle{color:var(--accent);font-weight:600;margin:0 0 12px}
.report-intro__summary{color:var(--page-text-secondary);margin:0 0 16px}
.report-intro__highlights{display:flex;flex-wrap:wrap;gap:8px 20px}
.report-intro__highlight{display:flex;align-items:center;gap:8px;font-size:.875rem;color:var(--page-text-muted)}
.report-intro__highlight-dot{width:8px;height:8px;border-radius:50%;background:var(--accent)}
section{margin-bottom:32px}
h2{font-size:1.3rem;border-bottom:2px solid #F3DDD0;padding-bottom:8px;margin-bottom:16px}
.day-card{background:var(--page-surface);border:1px solid var(--page-border);border-radius:12px;padding:20px;margin-bottom:16px}
.day-card__header{display:flex;align-items:center;gap:12px;margin-bottom:12px;padding-bottom:12px;border-bottom:1px solid var(--page-border)}
.day-card__badge{background:var(--accent);color:#fff;font-size:.8rem;font-weight:700;padding:4px 12px;border-radius:999px}
.day-card__title{font-weight:700}
.attraction-list{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.attraction-list{grid-template-columns:1fr}}
.attraction-item{background:var(--page-bg);border:1px solid var(--page-border);border-radius:8px;padding:12px 16px}
.attraction-item__name{font-weight:600;margin-bottom:4px}
.attraction-item__meta{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:8px}
.attraction-item__tag{font-size:.75rem;padding:2px 8px;border-radius:999px;background:var(--page-brand-soft);color:var(--accent)}
.attraction-item__desc{font-size:.85rem;color:var(--page-text-secondary)}
.accommodation-list{display:grid;grid-template-columns:1fr 1fr;gap:12px}
@media(max-width:640px){.accommodation-list{grid-template-columns:1fr}}
.accommodation-item{background:var(--page-bg);border:1px solid var(--page-border);border-radius:8px;padding:12px 16px}
.accommodation-item__name{font-weight:600}.accommodation-item__price{color:var(--accent);font-weight:600;margin:4px 0}
.itinerary-table{width:100%;border-collapse:collapse}
.itinerary-table th,.itinerary-table td{padding:10px 12px;border-bottom:1px solid var(--page-border);text-align:left}
.itinerary-table th{background:#F2EBE4}.total-row{font-weight:700;background:var(--page-brand-soft);color:var(--accent)}
.transport-box{background:var(--page-brand-soft);border-radius:8px;padding:12px 16px;margin:12px 0;font-size:.9rem;color:var(--page-text-secondary)}
.tip-callout{background:var(--page-surface);border-left:3px solid var(--accent2);border-radius:0 8px 8px 0;padding:12px 16px}
.tip-callout ul{list-style:none;padding:0;margin:0}
.tip-callout li{font-size:.85rem;color:var(--page-text-secondary);padding-left:12px;position:relative;margin-bottom:4px}
.tip-callout li::before{content:"·";position:absolute;left:0;color:var(--accent2);font-weight:700}
.app-footer{text-align:center;padding:24px;color:var(--page-text-muted);font-size:.8rem;border-top:1px solid var(--page-border)}`;
}

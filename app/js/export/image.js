// 导出海报长图 PNG：使用 html-to-image CDN
let htmlToImageLoaded = false;

function loadHtmlToImage() {
  if (htmlToImageLoaded) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://cdn.jsdelivr.net/npm/html-to-image@1.11.11/dist/html-to-image.js';
    script.onload = () => { htmlToImageLoaded = true; resolve(); };
    script.onerror = reject;
    document.head.appendChild(script);
  });
}

export async function exportImage(plan) {
  const btn = document.getElementById('export-image');
  if (btn) { btn.disabled = true; btn.textContent = '生成中...'; }

  try {
    await loadHtmlToImage();
    if (typeof htmlToImage === 'undefined') {
      throw new Error('html-to-image 加载失败，请检查网络');
    }

    // 构建海报节点（414px 宽，复用 travel-long-image.html 布局思路）
    const node = buildPoster(plan);
    document.body.appendChild(node);

    const dataUrl = await htmlToImage.toPng(node, {
      width: 414,
      pixelRatio: 2,
      backgroundColor: '#FFFFFF'
    });

    document.body.removeChild(node);

    const a = document.createElement('a');
    a.href = dataUrl;
    a.download = `${plan.overview?.title || 'travel-guide'}.png`;
    a.click();
  } catch (e) {
    alert(`导出长图失败：${e.message}`);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '导出长图'; }
  }
}

function buildPoster(plan) {
  const o = plan.overview || {};
  const node = document.createElement('div');
  node.style.cssText = 'width:414px;background:#fff;font-family:"PingFang SC","Microsoft YaHei",sans-serif;color:#2A1F1A;line-height:1.7;';

  const highlights = (o.highlights || []).map(h => `<span style="display:inline-block;margin:4px 6px 4px 0;padding:3px 10px;border-radius:999px;background:rgba(184,85,29,0.12);color:#B8551D;font-size:11px">${esc(h)}</span>`).join('');
  const daily = (plan.daily || []).map(d => {
    const attrs = (d.attractions || []).slice(0, 3).map(a => `<div style="margin:6px 0;font-size:12px;color:#5C4A40"><b style="color:#2A1F1A">${esc(a.name)}</b> · ${esc(a.duration||'')} ${esc(a.ticket||'')}</div>`).join('');
    return `<div style="background:#FAF6F2;border-radius:8px;padding:12px;margin-bottom:10px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">
        <span style="background:#B8551D;color:#fff;font-size:11px;font-weight:700;padding:3px 10px;border-radius:999px">Day ${d.day}</span>
        <b style="font-size:13px">${esc(d.city)} · ${esc(d.title)}</b>
      </div>${attrs}</div>`;
  }).join('');
  const attractions = (plan.attractions || []).slice(0, 8).map(a => `<div style="font-size:12px;margin:4px 0;color:#5C4A40"><b style="color:#2A1F1A">${esc(a.name)}</b> · ${esc(a.desc||'').slice(0,40)}</div>`).join('');
  const food = (plan.food || []).slice(0, 7).map(f => `<span style="display:inline-block;margin:4px 6px 4px 0;padding:3px 10px;border-radius:999px;background:#FBF0EA;color:#B8551D;font-size:12px">${esc(f.name)}</span>`).join('');
  const b = plan.budget || {};
  const tips = (plan.tips || []).slice(0, 6).map(t => `<div style="font-size:12px;color:#5C4A40;margin:4px 0">· ${esc(t)}</div>`).join('');

  node.innerHTML = `
    <div style="background:linear-gradient(135deg,#FBF0EA,#F3DDD0);padding:32px 24px;text-align:center">
      <h1 style="font-size:22px;margin:0 0 6px">${esc(o.title)}</h1>
      <div style="color:#B8551D;font-weight:600;font-size:13px">${esc(o.dates)} · ${o.days}天${o.travelers?` · ${o.travelers}人`:''}</div>
      <div style="margin-top:10px">${highlights}</div>
    </div>
    <div style="padding:20px">
      <h2 style="font-size:15px;border-bottom:2px solid #F3DDD0;padding-bottom:6px;margin:0 0 12px">每日行程</h2>${daily}
      <h2 style="font-size:15px;border-bottom:2px solid #F3DDD0;padding-bottom:6px;margin:16px 0 12px">精彩景点</h2>${attractions}
      <h2 style="font-size:15px;border-bottom:2px solid #F3DDD0;padding-bottom:6px;margin:16px 0 12px">美食推荐</h2>${food}
      <h2 style="font-size:15px;border-bottom:2px solid #F3DDD0;padding-bottom:6px;margin:16px 0 12px">费用预估</h2>
      <table style="width:100%;font-size:12px;border-collapse:collapse">
        <tr><td>住宿</td><td style="text-align:right">¥${Number(b.accommodation||0).toLocaleString()}</td></tr>
        <tr><td>交通</td><td style="text-align:right">¥${Number(b.transport||0).toLocaleString()}</td></tr>
        <tr><td>餐饮</td><td style="text-align:right">¥${Number(b.food||0).toLocaleString()}</td></tr>
        <tr><td>门票</td><td style="text-align:right">¥${Number(b.tickets||0).toLocaleString()}</td></tr>
        <tr style="font-weight:700;color:#B8551D;border-top:2px solid #F3DDD0"><td>合计</td><td style="text-align:right">¥${Number(b.total||0).toLocaleString()}</td></tr>
      </table>
      <h2 style="font-size:15px;border-bottom:2px solid #F3DDD0;padding-bottom:6px;margin:16px 0 12px">出行贴士</h2>${tips}
    </div>`;
  return node;
}

function esc(s) {
  if (s == null) return '';
  return String(s).replace(/[<>&"']/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&#39;'}[c]));
}

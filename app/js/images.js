// 图片获取：Wikimedia Commons API（免 key，支持 CORS）
const API = 'https://commons.wikimedia.org/w/api.php';

/**
 * 按查询词获取一张图片 URL
 * @param {string} query
 * @returns {Promise<string|null>} 图片 URL 或 null
 */
export async function fetchImage(query) {
  if (!query) return null;
  try {
    const params = new URLSearchParams({
      action: 'query',
      generator: 'search',
      gsrsearch: query,
      gsrnamespace: '6',
      gsrlimit: '5',
      prop: 'imageinfo',
      iiprop: 'url',
      iiurlwidth: '600',
      format: 'json',
      origin: '*'
    });
    const res = await fetch(`${API}?${params.toString()}`, { signal: AbortSignal.timeout(8000) });
    if (!res.ok) return null;
    const data = await res.json();
    const pages = data.query?.pages;
    if (!pages) return null;
    // 取第一张有 thumburl 的图
    for (const page of Object.values(pages)) {
      const info = page.imageinfo?.[0];
      if (info?.thumburl) return info.thumburl;
    }
    return null;
  } catch {
    return null;
  }
}

/**
 * 批量获取图片，返回 Map<query, url|null>
 * 带并发控制（最多 3 个并发）
 */
export async function fetchImages(queries) {
  const result = new Map();
  const queue = [...new Set(queries.filter(Boolean))];
  const running = new Set();
  let idx = 0;

  async function worker() {
    while (idx < queue.length) {
      const q = queue[idx++];
      running.add(q);
      try {
        const url = await fetchImage(q);
        result.set(q, url);
      } catch {
        result.set(q, null);
      }
      running.delete(q);
    }
  }

  await Promise.all([worker(), worker(), worker()]);
  return result;
}

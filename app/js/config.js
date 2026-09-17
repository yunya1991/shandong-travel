// 配置管理：API 设置的本地持久化与设置面板
const CONFIG_KEY = 'tg_config';

const DEFAULT_CONFIG = {
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key: '',
  // 后端增强模式（Task 16 / AC-9, AC-11）
  mode: 'frontend',           // 'frontend' | 'backend'
  backend_url: 'http://localhost:8000',
  backend_timeout_ms: 5000,  // 后端不可达时降级阈值
  // 动态优化引擎（Task 21 / AC-14, FR-27~29, FR-31~33）
  dynamic_enabled: false,    // 总开关
  dynamic_mode: 'suggest',   // 'suggest'（建议模式，需手动采纳）| 'auto'（自动应用，可撤销）
  dynamic_whitelist: ['attractions', 'food'],  // 允许动态替换的卡片类型
  // DSH Web UI 驾驶舱（Task 22 / AC-15 / NFR-12）：默认仅本机访问
  cockpit_host: '127.0.0.1',
  cockpit_port: 3080,
};

export function loadConfig() {
  let cfg;
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    cfg = raw ? { ...DEFAULT_CONFIG, ...JSON.parse(raw) } : { ...DEFAULT_CONFIG };
  } catch {
    cfg = { ...DEFAULT_CONFIG };
  }
  // 云端同源部署自动适配（Task 23+ 部署增强）：
  // 若 backend_url 指向 localhost 但当前页面 origin 不是 localhost，
  // 自动改用当前 origin，让前端直连同源后端，无需用户手动改设置。
  // 同时默认切到 backend 模式 + 开启动态优化，开箱即用。
  try {
    const origin = window.location.origin || '';
    const isLocalhost = origin.includes('localhost') || origin.includes('127.0.0.1');
    if (!isLocalhost && cfg.backend_url && cfg.backend_url.includes('localhost')) {
      cfg.backend_url = origin;
      cfg.mode = 'backend';
      cfg.dynamic_enabled = true;
    }
  } catch { /* window 可能在非浏览器环境 */ }
  return cfg;
}

export function saveConfig(config) {
  localStorage.setItem(CONFIG_KEY, JSON.stringify(config));
}

export function initSettings() {
  const container = document.getElementById('settings-content');
  renderSettings(container);
}

function renderSettings(container) {
  const cfg = loadConfig();
  container.innerHTML = `
    <div class="settings-section">
      <h3>大模型 API 配置</h3>
      <p style="color:var(--page-text-muted);font-size:0.85rem;margin-bottom:var(--space-4);">
        支持所有兼容 OpenAI <code>/chat/completions</code> 协议的服务（DeepSeek、OpenAI、通义、Moonshot 等）。API Key 仅保存在本地浏览器，不会上传。
      </p>
      <div class="form-group">
        <label class="form-label" for="cfg-base">API Base URL</label>
        <input class="form-input" id="cfg-base" value="${escapeHtml(cfg.base_url)}" placeholder="https://api.deepseek.com">
      </div>
      <div class="form-group">
        <label class="form-label" for="cfg-model">模型名称</label>
        <input class="form-input" id="cfg-model" value="${escapeHtml(cfg.model)}" placeholder="deepseek-chat">
      </div>
      <div class="form-group">
        <label class="form-label" for="cfg-key">API Key</label>
        <input class="form-input" id="cfg-key" type="password" value="${escapeHtml(cfg.api_key)}" placeholder="sk-...">
      </div>
      <div style="display:flex;gap:var(--space-3);flex-wrap:wrap;">
        <button class="btn btn--primary" id="cfg-save">保存配置</button>
        <button class="btn btn--secondary" id="cfg-test">测试连接</button>
      </div>
      <div id="cfg-test-result" class="test-result"></div>
    </div>
    <div class="settings-section">
      <h3>后端增强模式（可选）</h3>
      <p style="color:var(--page-text-muted);font-size:0.85rem;margin-bottom:var(--space-4);">
        启用后，生成请求将先发送到 Python 后端（FastAPI + DSH + Scrapling），获得"链接解析 / 排线 / 来源追溯 / Trajectory 调试"等完整能力。后端不可达时自动降级为纯前端模式。
      </p>
      <div class="form-group">
        <label class="form-label" for="cfg-mode">运行模式</label>
        <select class="form-select" id="cfg-mode">
          <option value="frontend" ${cfg.mode === 'frontend' ? 'selected' : ''}>纯前端模式（默认，仅调 LLM）</option>
          <option value="backend" ${cfg.mode === 'backend' ? 'selected' : ''}>后端增强模式（爬虫 + DSH 编排 + 来源追溯）</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label" for="cfg-backend">后端地址</label>
        <input class="form-input" id="cfg-backend" value="${escapeHtml(cfg.backend_url)}" placeholder="http://localhost:8000">
      </div>
      <div class="form-group">
        <label class="form-label" for="cfg-timeout">后端降级超时（毫秒）</label>
        <input class="form-input" id="cfg-timeout" type="number" min="1000" max="30000" value="${cfg.backend_timeout_ms}">
      </div>
    </div>
    <div class="settings-section">
      <h3>动态优化引擎（Task 21 / AC-14）</h3>
      <p style="color:var(--page-text-muted);font-size:0.85rem;margin-bottom:var(--space-4);">
        启用后，后端 <code>tg-monitor</code> 周期拉取目的地天气/同城热榜，触发阈值时产出 <code>ADD/SWAP/MOVE</code> diff，通过 WebSocket 推送，前端高亮"换出/换入"并附变更说明。可一键撤销回到任意历史版本。
      </p>
      <div class="form-group">
        <label class="form-label">
          <input type="checkbox" id="cfg-dyn-enabled" ${cfg.dynamic_enabled ? 'checked' : ''}>
          启用动态更新总开关
        </label>
      </div>
      <div class="form-group">
        <label class="form-label" for="cfg-dyn-mode">应用模式</label>
        <select class="form-select" id="cfg-dyn-mode">
          <option value="suggest" ${cfg.dynamic_mode === 'suggest' ? 'selected' : ''}>建议模式（推送后需手动点"采纳"才应用）</option>
          <option value="auto" ${cfg.dynamic_mode === 'auto' ? 'selected' : ''}>自动应用模式（直接应用，可撤销）</option>
        </select>
      </div>
      <div class="form-group">
        <label class="form-label">允许动态替换的元素类型（白名单）</label>
        <div style="display:flex;gap:var(--space-3);flex-wrap:wrap;">
          <label><input type="checkbox" class="cfg-dyn-wl" value="attractions" ${cfg.dynamic_whitelist.includes('attractions') ? 'checked' : ''}> 景点</label>
          <label><input type="checkbox" class="cfg-dyn-wl" value="food" ${cfg.dynamic_whitelist.includes('food') ? 'checked' : ''}> 美食</label>
          <label><input type="checkbox" class="cfg-dyn-wl" value="accommodation" ${cfg.dynamic_whitelist.includes('accommodation') ? 'checked' : ''}> 住宿</label>
        </div>
      </div>
      <div class="form-group">
        <label class="form-label">DSH Web UI 驾驶舱地址（Task 22 / AC-15）</label>
        <div style="display:flex;gap:var(--space-3);align-items:center;">
          <input class="form-input" id="cfg-cockpit-host" value="${escapeHtml(cfg.cockpit_host)}" placeholder="127.0.0.1" style="flex:1;">
          <span style="color:var(--page-text-muted);">:</span>
          <input class="form-input" id="cfg-cockpit-port" type="number" min="1" max="65535" value="${cfg.cockpit_port}" style="width:100px;">
        </div>
        <p style="color:var(--page-text-muted);font-size:0.78rem;margin-top:4px;">建议模式下，待审徽章会指向此地址。默认仅本机访问（NFR-12）。</p>
      </div>
    </div>
    <div class="settings-section">
      <h3>使用说明</h3>
      <ul style="padding-left:1.2em;color:var(--page-text-secondary);font-size:0.9rem;line-height:1.8;">
        <li>在「生成手册」页输入目的地与偏好，点击生成</li>
        <li>生成后可在「手册」「清单」「预算」「收藏」中管理</li>
        <li>支持导出静态 HTML 与海报长图</li>
        <li>后端增强模式下可在「调试」视图查看 Trajectory 思考轨迹</li>
        <li>若 API 调用遇到 CORS 错误，可运行项目根目录的 <code>proxy.py</code> 并将 Base URL 改为 <code>http://localhost:8787</code></li>
      </ul>
    </div>
  `;

  container.querySelector('#cfg-save').addEventListener('click', () => {
    const whitelist = Array.from(container.querySelectorAll('.cfg-dyn-wl:checked')).map(cb => cb.value);
    const config = {
      ...loadConfig(),
      base_url: container.querySelector('#cfg-base').value.trim(),
      model: container.querySelector('#cfg-model').value.trim(),
      api_key: container.querySelector('#cfg-key').value.trim(),
      mode: container.querySelector('#cfg-mode').value,
      backend_url: container.querySelector('#cfg-backend').value.trim(),
      backend_timeout_ms: parseInt(container.querySelector('#cfg-timeout').value, 10) || 5000,
      dynamic_enabled: container.querySelector('#cfg-dyn-enabled').checked,
      dynamic_mode: container.querySelector('#cfg-dyn-mode').value,
      dynamic_whitelist: whitelist,
      cockpit_host: container.querySelector('#cfg-cockpit-host')?.value.trim() || '127.0.0.1',
      cockpit_port: parseInt(container.querySelector('#cfg-cockpit-port')?.value, 10) || 3080,
    };
    saveConfig(config);
    const result = container.querySelector('#cfg-test-result');
    result.textContent = '✓ 配置已保存';
    result.className = 'test-result success';
  });

  container.querySelector('#cfg-test').addEventListener('click', async () => {
    const config = {
      base_url: container.querySelector('#cfg-base').value.trim(),
      model: container.querySelector('#cfg-model').value.trim(),
      api_key: container.querySelector('#cfg-key').value.trim()
    };
    const result = container.querySelector('#cfg-test-result');
    result.textContent = '测试中...';
    result.className = 'test-result';
    try {
      const { generatePlan } = await import('./llm.js');
      // 轻量测试：发送一个简单请求
      const res = await fetch(`${config.base_url.replace(/\/$/, '')}/chat/completions`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.api_key}`
        },
        body: JSON.stringify({
          model: config.model,
          messages: [{ role: 'user', content: 'hi' }],
          max_tokens: 10
        })
      });
      if (res.ok) {
        result.textContent = '✓ 连接成功';
        result.className = 'test-result success';
      } else {
        const err = await res.json().catch(() => ({}));
        result.textContent = `✗ 连接失败 (${res.status}): ${err.error?.message || res.statusText}`;
        result.className = 'test-result error';
      }
    } catch (e) {
      result.textContent = `✗ 请求出错：${e.message}（可能是 CORS，可尝试启用 proxy.py）`;
      result.className = 'test-result error';
    }
  });
}

export function escapeHtml(str) {
  if (str == null) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

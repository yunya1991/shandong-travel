// 配置管理：API 设置的本地持久化与设置面板
const CONFIG_KEY = 'tg_config';

const DEFAULT_CONFIG = {
  base_url: 'https://api.deepseek.com',
  model: 'deepseek-chat',
  api_key: '',
  // 后端增强模式（Task 16 / AC-9, AC-11）
  mode: 'frontend',           // 'frontend' | 'backend'
  backend_url: 'http://localhost:8000',
  backend_timeout_ms: 5000   // 后端不可达时降级阈值
};

export function loadConfig() {
  try {
    const raw = localStorage.getItem(CONFIG_KEY);
    if (!raw) return { ...DEFAULT_CONFIG };
    return { ...DEFAULT_CONFIG, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_CONFIG };
  }
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
    const config = {
      ...loadConfig(),
      base_url: container.querySelector('#cfg-base').value.trim(),
      model: container.querySelector('#cfg-model').value.trim(),
      api_key: container.querySelector('#cfg-key').value.trim(),
      mode: container.querySelector('#cfg-mode').value,
      backend_url: container.querySelector('#cfg-backend').value.trim(),
      backend_timeout_ms: parseInt(container.querySelector('#cfg-timeout').value, 10) || 5000
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

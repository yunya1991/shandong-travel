// LLM 客户端：纯前端模式直接调 OpenAI 兼容 API；后端模式调 /generate，5 秒超时降级
import { loadConfig } from './config.js';
import { SYSTEM_PROMPT, buildUserPrompt } from './prompt.js';
import { validatePlan } from './schema.js';

/**
 * 统一入口：根据 config.mode 选择后端 / 纯前端，并返回统一结构。
 * @param {Object} params {dest, days, travelers, departure, season, style, budgetLevel, materials?}
 * @returns {Promise<{plan, sources: array, warnings: array, session_id: string, backend_used: boolean, degraded: boolean, materials?: array}>}
 */
export async function generatePlan(params) {
  const config = loadConfig();
  if (!config.api_key) {
    throw new Error('请先在「设置」中配置 API Key');
  }

  if (config.mode === 'backend') {
    try {
      const r = await generateViaBackend(params, config);
      // 后端正常返回：清掉降级提示（如之前有过）
      clearDegradedNotice();
      return r;
    } catch (e) {
      // 后端不可达 / 超时 → 降级为纯前端模式（AC-11）
      showDegradedNotice(`后端不可达，已降级为纯前端模式（${e.message}）`);
      const plan = await generateViaFrontend(params, config);
      return {
        plan,
        sources: [],
        warnings: [{
          level: 'high',
          field: 'backend',
          msg: `后端不可达，已降级为纯前端模式：${e.message}`
        }],
        session_id: `fe_${Date.now()}`,
        backend_used: false,
        degraded: true,
      };
    }
  }

  // 纯前端模式
  const plan = await generateViaFrontend(params, config);
  return {
    plan,
    sources: [],
    warnings: [],
    session_id: `fe_${Date.now()}`,
    backend_used: false,
    degraded: false,
  };
}

/**
 * 后端增强模式：POST ${backend_url}/generate
 * header X-LLM-Config 携带 {base_url, api_key, model}（仅在请求内存中，后端不持久化）
 */
async function generateViaBackend(params, config) {
  const controller = new AbortController();
  const timeout = config.backend_timeout_ms || 5000;
  const timer = setTimeout(() => controller.abort(), timeout);

  const body = {
    destination: params.dest,
    prefs: {
      days: params.days,
      travelers: params.travelers,
      departure: params.departure,
      season: params.season,
      style: params.style,
      budget_level: params.budgetLevel,
    },
  };
  if (params.materials && params.materials.length) {
    body.materials = params.materials;
  }

  try {
    const res = await fetch(`${config.backend_url.replace(/\/$/, '')}/generate`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-LLM-Config': JSON.stringify({
          base_url: config.base_url,
          api_key: config.api_key,
          model: config.model,
        }),
      },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) {
      const errText = await res.text().catch(() => '');
      throw new Error(`后端 HTTP ${res.status}: ${errText.slice(0, 200)}`);
    }
    const data = await res.json();
    if (!data.plan) throw new Error('后端返回缺少 plan 字段');
    const { valid, errors } = validatePlan(data.plan);
    if (!valid) {
      // 后端模式：plan 不合规也带 warning 返回，前端可看到
      data.warnings = (data.warnings || []).concat(
        errors.map(e => ({ level: 'medium', field: e, msg: e }))
      );
    }
    data.backend_used = true;
    data.degraded = false;
    return data;
  } catch (e) {
    if (e.name === 'AbortError') {
      throw new Error(`后端超时（${timeout}ms）`);
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}

/**
 * 纯前端模式：直接调 OpenAI 兼容 /chat/completions
 */
async function generateViaFrontend(params, config) {
  const url = `${config.base_url.replace(/\/$/, '')}/chat/completions`;
  const body = {
    model: config.model,
    messages: [
      { role: 'system', content: SYSTEM_PROMPT },
      { role: 'user', content: buildUserPrompt(params) }
    ],
    temperature: 0.7,
    response_format: { type: 'json_object' }
  };

  let attempt = 0;
  let lastError = null;

  while (attempt < 2) {
    attempt++;
    try {
      const res = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${config.api_key}`
        },
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        if (res.status === 401) throw new Error('API 密钥无效（401）');
        if (res.status === 404) throw new Error('接口不存在（404），请检查 Base URL 与模型名');
        const err = await res.json().catch(() => ({}));
        throw new Error(`请求失败 (${res.status}): ${err.error?.message || res.statusText}`);
      }

      const data = await res.json();
      const content = data.choices?.[0]?.message?.content;
      if (!content) throw new Error('LLM 返回内容为空');

      const parsed = JSON.parse(content);
      const { valid, errors } = validatePlan(parsed);
      if (!valid) {
        lastError = new Error(`生成内容校验失败：${errors.join('; ')}`);
        body.messages.push({ role: 'assistant', content });
        body.messages.push({ role: 'user', content: `上一次输出缺少以下字段，请修正后重新输出完整 JSON：${errors.join('; ')}` });
        continue;
      }
      return parsed;
    } catch (e) {
      lastError = e;
      if (attempt < 2) {
        body.messages.push({ role: 'user', content: '请重新输出完整 JSON 方案。' });
        continue;
      }
    }
  }

  throw lastError || new Error('生成失败');
}

// === 降级提示条（AC-11） ===
function showDegradedNotice(msg) {
  let el = document.getElementById('degraded-notice');
  if (!el) {
    el = document.createElement('div');
    el.id = 'degraded-notice';
    el.className = 'degraded-notice';
    document.body.prepend(el);
  }
  el.textContent = msg;
  el.classList.add('visible');
}

function clearDegradedNotice() {
  const el = document.getElementById('degraded-notice');
  if (el) el.classList.remove('visible');
}

/**
 * 拉取后端 trajectory（调试视图用，AC-12）
 */
export async function fetchTrajectory(sessionId) {
  const config = loadConfig();
  if (config.mode !== 'backend' || !config.backend_url) {
    throw new Error('需切换为后端模式才能拉取 Trajectory');
  }
  const res = await fetch(`${config.backend_url.replace(/\/$/, '')}/trajectory/${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`trajectory HTTP ${res.status}`);
  return res.json();
}

/**
 * 重放历史轨迹（Task 19 / FR-25）
 */
export async function replayTrajectory(sessionId) {
  const config = loadConfig();
  if (config.mode !== 'backend' || !config.backend_url) {
    throw new Error('需切换为后端模式才能重放 Trajectory');
  }
  const res = await fetch(`${config.backend_url.replace(/\/$/, '')}/trajectory/replay/${encodeURIComponent(sessionId)}`, {
    method: 'POST',
  });
  if (!res.ok) throw new Error(`replay HTTP ${res.status}`);
  return res.json();
}

// LLM 客户端：调用 OpenAI 兼容 API 生成旅游方案
import { loadConfig } from './config.js';
import { SYSTEM_PROMPT, buildUserPrompt } from './prompt.js';
import { validatePlan } from './schema.js';

/**
 * 生成旅游方案
 * @param {Object} params
 * @returns {Promise<Object>} plan 对象
 */
export async function generatePlan(params) {
  const config = loadConfig();
  if (!config.api_key) {
    throw new Error('请先在「设置」中配置 API Key');
  }

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
        if (res.status === 404) throw new Error(`接口不存在（404），请检查 Base URL 与模型名`);
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
        // 重试时附加错误上下文
        body.messages.push({ role: 'assistant', content });
        body.messages.push({ role: 'user', content: `上一次输出缺少以下字段，请修正后重新输出完整 JSON：${errors.join('; ')}` });
        continue;
      }
      return parsed;
    } catch (e) {
      lastError = e;
      // 网络错误或解析错误也重试一次
      if (attempt < 2) {
        body.messages.push({ role: 'user', content: '请重新输出完整 JSON 方案。' });
        continue;
      }
    }
  }

  throw lastError || new Error('生成失败');
}

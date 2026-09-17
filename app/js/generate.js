// 生成表单处理与当前方案状态管理
import { generatePlan } from './llm.js';
import { makePlanId } from './schema.js';

const STORE_KEY = 'tg_current_result';

// 当前完整结果（包含 plan + sources + warnings + session_id + backend_used + degraded）
let currentResult = null;

export function getCurrentPlan() {
  return currentResult?.plan || null;
}

export function getCurrentPlanId() {
  return currentResult?.planId || null;
}

export function getCurrentResult() {
  return currentResult;
}

export function setCurrentResult(result) {
  currentResult = result;
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(result));
  } catch {}
}

export function setCurrentPlan(plan, planId) {
  // 兼容老接口：仅设置 plan，保留其他字段
  currentResult = {
    ...(currentResult || {}),
    plan,
    planId,
  };
  try {
    localStorage.setItem(STORE_KEY, JSON.stringify(currentResult));
  } catch {}
}

// 启动时恢复
try {
  const raw = localStorage.getItem(STORE_KEY);
  if (raw) {
    currentResult = JSON.parse(raw);
  }
} catch {}

export function initGenerate() {
  const form = document.getElementById('gen-form');
  const btn = document.getElementById('gen-btn');

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const params = {
      dest: form.dest.value.trim(),
      days: parseInt(form.days.value, 10) || 5,
      travelers: parseInt(form.travelers.value, 10) || 2,
      departure: form.departure.value.trim(),
      season: form.season.value,
      style: form.style.value.trim(),
      budgetLevel: form['budget-level'].value
    };

    if (!params.dest) {
      alert('请输入目的地');
      return;
    }

    btn.disabled = true;
    btn.innerHTML = '<span class="spinner" style="width:16px;height:16px;border-width:2px;display:inline-block;margin:0;"></span> 生成中...';

    try {
      const result = await generatePlan(params);
      const planId = makePlanId(params.dest, params.days);
      setCurrentResult({ ...result, planId });

      // 切换到手册视图
      const { switchView } = await import('./main.js');
      switchView('guide');
    } catch (err) {
      alert(`生成失败：${err.message}\n\n提示：如遇 CORS 错误，请在项目根目录运行 proxy.py，并将 Base URL 改为 http://localhost:8787`);
    } finally {
      btn.disabled = false;
      btn.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg> 生成手册';
    }
  });
}

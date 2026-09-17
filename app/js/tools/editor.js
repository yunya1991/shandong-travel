// 行程编辑器：内联编辑每日行程（简化版）
// Task 23 / FR-33：所有编辑入口通过 reportUserEdit 上报后端，
// 让 monitor 在 5 分钟窗口内跳过对应 (day, field) 的 diff。
import { reportUserEdit } from '../optimizer.js';

export function initEditor() {
  bindInlineEdits();
}

/**
 * 绑定内联编辑事件：
 * - attraction-item / food-item / accommodation-item 卡片的双击事件
 * - 双击后改为 contenteditable，blur 时保存到 currentResult + 上报后端
 */
function bindInlineEdits() {
  document.addEventListener('dblclick', (e) => {
    const item = e.target.closest('.attraction-item, .food-item, .accommodation-item');
    if (!item) return;
    const nameEl = item.querySelector('.attraction-item__name, .food-item__name, .accommodation-item__name');
    if (!nameEl || nameEl.isContentEditable) return;

    nameEl.contentEditable = 'true';
    nameEl.focus();
    // 全选内容
    const range = document.createRange();
    range.selectNodeContents(nameEl);
    const sel = window.getSelection();
    sel.removeAllRanges();
    sel.addRange(range);

    nameEl.addEventListener('blur', () => {
      nameEl.contentEditable = 'false';
      const dayCard = item.closest('.day-card');
      const day = parseInt(dayCard?.dataset?.day || dayCard?.querySelector('.day-card__badge')?.textContent?.match(/\d+/)?.[0], 10);
      const field = item.classList.contains('attraction-item') ? 'attractions'
        : item.classList.contains('food-item') ? 'food'
        : 'accommodation';
      if (day && field) {
        reportUserEdit(day, field);
      }
    }, { once: true });
  });
}

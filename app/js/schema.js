// 旅游方案数据 Schema 与校验
// 定义 LLM 应返回的 JSON 结构，并提供校验函数

/**
 * @typedef {Object} Overview
 * @property {string} title - 行程标题
 * @property {string} dates - 出行日期描述
 * @property {number} days - 天数
 * @property {number} travelers - 出行人数
 * @property {string} departure - 出发城市
 * @property {string} route_theme - 路线主题
 * @property {string[]} highlights - 核心亮点
 * @property {string} mileage - 全程里程
 * @property {string} suitable_people - 适合人群
 * @property {string} tips - 温馨提示
 */

/**
 * @typedef {Object} RouteNode
 * @property {string} name - 城市/节点名
 * @property {string} day - 对应天数，如 "Day 1"
 */

/**
 * @typedef {Object} DailyPlan
 * @property {number} day - 第几天
 * @property {string} date - 日期
 * @property {string} city - 城市
 * @property {string} title - 当日标题
 * @property {string} subtitle - 副标题
 * @property {Attraction[]} attractions - 当日景点
 * @property {Food[]} food - 当日美食
 * @property {string} transport - 交通说明
 * @property {string} accommodation - 住宿说明
 */

/**
 * @typedef {Object} Attraction
 * @property {string} name - 景点名
 * @property {string} desc - 描述
 * @property {string} duration - 建议游玩时长
 * @property {string} ticket - 门票
 * @property {string[]} tags - 标签
 * @property {string} image_query - 图片搜索词
 */

/**
 * @typedef {Object} Accommodation
 * @property {string} name - 住宿名称
 * @property {string} area - 区域
 * @property {string} price_range - 价格区间
 * @property {string} desc - 描述
 */

/**
 * @typedef {Object} Food
 * @property {string} name - 美食名
 * @property {string} desc - 描述
 * @property {string} image_query - 图片搜索词
 */

/**
 * @typedef {Object} Budget
 * @property {number} accommodation - 住宿
 * @property {number} transport - 交通
 * @property {number} food - 餐饮
 * @property {number} tickets - 门票
 * @property {number} other - 其他
 * @property {number} total - 合计
 * @property {number} per_person - 人均
 */

/**
 * @typedef {Object} TravelPlan
 * @property {Overview} overview
 * @property {RouteNode[]} route
 * @property {DailyPlan[]} daily
 * @property {Attraction[]} attractions
 * @property {Accommodation[]} accommodation
 * @property {Food[]} food
 * @property {Budget} budget
 * @property {string[]} tips
 */

const REQUIRED_FIELDS = {
  overview: ['title', 'dates', 'days', 'travelers', 'departure', 'route_theme', 'highlights', 'mileage', 'suitable_people', 'tips'],
  route: null,
  daily: null,
  attractions: null,
  accommodation: null,
  food: null,
  budget: ['accommodation', 'transport', 'food', 'tickets', 'other', 'total', 'per_person'],
  tips: null
};

/**
 * 校验旅游方案 JSON
 * @param {any} json
 * @returns {{valid: boolean, errors: string[]}}
 */
export function validatePlan(json) {
  const errors = [];
  if (!json || typeof json !== 'object') {
    return { valid: false, errors: ['根节点不是对象'] };
  }

  for (const [field, subFields] of Object.entries(REQUIRED_FIELDS)) {
    if (!(field in json)) {
      errors.push(`缺少顶层字段: ${field}`);
      continue;
    }
    if (subFields && typeof json[field] === 'object' && !Array.isArray(json[field])) {
      for (const sf of subFields) {
        if (!(sf in json[field])) {
          errors.push(`overview.${sf} 或 budget.${sf} 缺失: ${field}.${sf}`);
        }
      }
    }
  }

  // 检查 daily 至少有一项
  if (Array.isArray(json.daily) && json.daily.length === 0) {
    errors.push('daily 为空数组');
  }
  // 检查 attractions 至少有一项
  if (Array.isArray(json.attractions) && json.attractions.length === 0) {
    errors.push('attractions 为空数组');
  }

  return { valid: errors.length === 0, errors };
}

/**
 * 从目的地+日期生成稳定 planId
 */
export function makePlanId(dest, days) {
  const base = `${dest}-${days}-${new Date().toISOString().slice(0, 10)}`;
  let hash = 0;
  for (let i = 0; i < base.length; i++) {
    hash = ((hash << 5) - hash) + base.charCodeAt(i);
    hash |= 0;
  }
  return `plan_${Math.abs(hash)}`;
}

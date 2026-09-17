"""集中管理 LLM 提示词模板

与前端 app/js/prompt.js 保持一致风格；后端在编排链路中按场景使用。
"""
from __future__ import annotations

# ====== 系统提示（编排链路用） ======
SYSTEM_PROMPT = (
    "你是「AI 旅行手册」的编排大脑，工作在 DeepSeek Harness 框架内。"
    "你必须：1) 严格按用户给的 JSON Schema 输出，不增减顶层字段；"
    "2) 每个景点/美食/住宿条目尽量携带 source_url（来自爬虫素材）与 source_type；"
    "3) 事实校对：名称拼写、价格区间合理性、坐标与城市匹配、开放时间格式；"
    "4) 不臆造：若素材不足，明确在 warnings 中报告而非编造；"
    "5) 路线按同区域集中 + 最少折返原则分配到对应日期。"
)

# ====== tg-planner: 生成抓取任务清单 ======
PLAN_SCRAPE_TASKS = """\
任务：根据目的地与偏好，生成结构化抓取任务清单（JSON 数组）。
每个任务对象字段：
- target_url: 待抓取的公开页面 URL（可空，由 source_type 推断站点）
- source_type: wikipedia | wikivoyage | commons | generic
- query: 搜索/抓取关键词（中文）
- fields: 想抽取的字段（如 ["name","desc","ticket","coords","image_url"]）

输出仅 JSON 数组，3-6 个任务，覆盖景点、美食、住宿、当地节庆/季节特色。
输入：
目的地：{destination}
偏好：{prefs}
"""

# ====== tg-integrator: 把素材合并为符合 schema 的 plan ======
INTEGRATE_PLAN = """\
任务：把抓取素材与用户偏好合并为符合 schema 的旅游方案 JSON。
要求：
1) 输出 JSON 顶层必须包含：overview, route, daily, attractions, accommodation, food, budget, tips
2) overview 必含字段：title, dates, days, travelers, departure, route_theme, highlights, mileage, suitable_people, tips
3) budget 必含：accommodation, transport, food, tickets, other, total, per_person（单位：人民币元）
4) 每个景点/美食/住宿尽量带 source_url（来自素材）、source_type
5) 路线按"同区域集中 + 最少折返"分配到日期；每日景点数 2-4 个
6) 不臆造：素材不足时该字段留空并在 warnings 标注

输入：
目的地：{destination}
偏好：{prefs}
素材（JSON）：{materials}
"""

# ====== tg-validator: 事实校对 ======
VALIDATE_PLAN = """\
任务：对旅游方案 JSON 做事实校对，输出 warnings 数组。
校对维度：
- 名称拼写：景点/城市名是否与素材一致
- 价格区间：门票/住宿/餐饮是否在合理区间
- 坐标城市：景点的坐标（如带 lat/lng）是否落在目的地城市范围内
- 开放时间：格式是否规范、是否与素材一致
- 路线合理性：是否存在"同一天跑三个不相邻区域"

每条 warning 字段：{level: high|medium|low, field: 字段路径, msg: 说明}
仅输出 JSON 数组。

方案：{plan}
素材：{materials}
"""

# ====== 动态优化 diff 生成（tg-optimizer） ======
OPTIMIZE_DIFF = """\
任务：根据监测数据，对当前行程产出结构化 diff（ADD / SWAP / MOVE）。
diff 字段：
- op: ADD | SWAP | MOVE
- day: 第几天（1-based）
- target_field: attractions | food | accommodation
- old_item: 被替换/移动的条目（ADD 时为 null）
- new_item: 新条目（含 source_url + source_type）
- reason: 中文说明（如"明日济南有雷阵雨，已将千佛山 → 山东省博物馆"）

仅输出 JSON 数组，1-3 条 diff。优先考虑安全替代（如户外→室内）。

当前方案：{plan}
监测数据：{monitor_data}
用户白名单：{whitelist}
"""

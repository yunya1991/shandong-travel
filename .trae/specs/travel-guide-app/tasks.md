# 旅游手册生成器 · Implementation Plan

## Task 1: 项目骨架与设计令牌复用
- **Status**: `pending`
- **Priority**: high
- **Depends On**: None
- **Description**:
  - 新建应用入口 `app/index.html`，搭建整体布局：顶部导航（手册/清单/预算/设置）、主内容区、底部。
  - 从现有 `index.html` 抽取 Warm Editorial 调色板（CSS 变量）与基础组件样式（卡片、标签、贴士 callout、表格、日卡片）到 `app/styles.css`。
  - 采用 ES Module 拆分 JS：`config.js`、`llm.js`、`schema.js`、`renderer.js`、`images.js`、`tools/checklist.js`、`tools/budget.js`、`tools/editor.js`、`tools/favorites.js`、`export/html.js`、`export/image.js`、`main.js`。
- **Acceptance Criteria Addressed**: AC-7
- **Test Requirements**:
  - `rule` TR-1.1: 打开 `app/index.html` 可见顶部导航与空状态主区，CSS 变量与现有 `index.html` 一致（`--accent:#B8551D` 等）
  - `rule` TR-1.2: 控制台无模块加载错误
- **Notes**: 不引入构建工具，直接用 `<script type="module">`

## Task 2: 设置面板与本地配置持久化
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - 实现设置面板：base_url、model、api_key 三个输入框 + 保存按钮。
  - `config.js` 提供 `loadConfig()` / `saveConfig()`，基于 localStorage 的 `tg_config` 键。
  - 启动时自动回填；api_key 输入框使用 `type="password"`。
  - 增加"测试连接"按钮：用配置发起一次轻量 chat completion（如问"hi"），反馈成功/失败。
- **Acceptance Criteria Addressed**: AC-5
- **Test Requirements**:
  - `rule` TR-2.1: 填写三项并保存后，localStorage `tg_config` 含正确字段
  - `rule` TR-2.2: 刷新页面后三项表单自动回填
- **Notes**: base_url 默认占位 `https://api.deepseek.com`，model 默认 `deepseek-chat`

## Task 3: 数据 Schema 与 Prompt 模板
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1
- **Description**:
  - `schema.js` 定义旅游方案 TypeScript 风格的 JSDoc 类型与校验函数 `validatePlan(json)`，字段：overview{title,dates,days,travelers,departure,route_theme,highlights,mileage,suitable_people,tips}、route{nodes[]}、daily[{day,date,city,title,subtitle,attractions[],food[],transport,accommodation}]、attractions[{name,desc,duration,ticket,tags,image_query}]、accommodation[{name,area,price_range,desc}]、food[{name,desc,image_query}]、budget{accommodation,transport,food,tickets,other,total,per_person}、tips[string[]]。
  - `prompt.js` 集中管理 system prompt，要求 LLM 严格输出 JSON（用 `response_format: json_object` 或在 prompt 中强调只输出 JSON）。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-3.1: 给定一段合法 JSON，`validatePlan` 返回 true；缺字段返回 false 并指出缺失
- **Notes**: prompt 中嵌入示例输出片段以稳定格式

## Task 4: LLM 客户端
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 2, Task 3
- **Description**:
  - `llm.js` 实现 `generatePlan(params)`：从 config 读取 base_url/model/api_key，POST 到 `${base_url}/chat/completions`，body 含 messages、model、`response_format:{type:"json_object"}`（若模型支持）。
  - 解析返回 `choices[0].message.content` 为 JSON，调用 `validatePlan` 校验；失败时带上下文重试 1 次。
  - loading 状态与错误提示（网络错误/401/JSON 解析失败分别提示）。
- **Acceptance Criteria Addressed**: AC-1
- **Test Requirements**:
  - `rule` TR-4.1: 用有效配置生成时，Network 可见 POST 请求且返回 200，最终得到通过校验的 plan 对象
  - `rule` TR-4.2: api_key 错误时显示"API 密钥无效"提示而非崩溃
- **Notes**: 若遇 CORS，文档中说明可启用 `proxy.py`

## Task 5: 手册渲染器（8 大模块）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - `renderer.js` 实现 `renderPlan(plan)`，依次渲染 8 个 section：
    1. 行程概览（标题、日期、人数、出发地、主题、亮点标签、里程、适合人群、温馨提示）
    2. 路线地图：根据 route.nodes 生成简化 SVG 路线图（节点 + 连线 + 城市名，复用现有 SVG 风格）
    3. 每日行程：day-card 组件，含日期/城市/标题/景点列表/美食/交通/住宿
    4. 精彩景点：attraction-item 卡片（名称、标签含时长/门票、描述、配图）
    5. 住宿推荐：卡片含名称、区域、价格区间、描述
    6. 美食推荐：卡片含名称、描述、配图
    7. 费用预估：分项表格 + 合计 + 人均
    8. 出行贴士：tip-callout 列表
  - 所有文本做 HTML 转义（`escapeHtml`）。
- **Acceptance Criteria Addressed**: AC-2, AC-7
- **Test Requirements**:
  - `rule` TR-5.1: 渲染后 DOM 存在 8 个对应 section 且内容来自 plan 数据
  - `rubric` TR-5.2: 视觉一致性；scale 1-5；1=脱节 3=配色一致结构有差 5=配色组件与现有 HTML 高度一致且 8 模块对齐海报；threshold >=4；evidence=渲染截图
- **Notes**: 复用 `index.html` 的 `.day-card`、`.attraction-item`、`.food-item`、`.tip-callout`、`.itinerary-table` 等类名

## Task 6: 图片获取模块（Wikimedia Commons）
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 1
- **Description**:
  - `images.js` 实现 `fetchImage(query)`：调用 Wikimedia Commons API（`https://commons.wikimedia.org/w/api.php?action=query&generator=search&gsrsearch={query}&gsrnamespace=6&prop=imageinfo&iiprop=url&iiurlwidth=600&format=json&origin=*`），取第一张图的 thumburl。
  - 失败/超时时返回 null，渲染层用主题色渐变 + 景点名首字作为占位。
  - 景点用 `image_query`（若为空用名称），美食用名称+"美食"。
- **Acceptance Criteria Addressed**: AC-2
- **Test Requirements**:
  - `rule` TR-6.1: 对"趵突泉"查询返回有效图片 URL 或在失败时返回 null 且不抛错
  - `rule` TR-6.2: 渲染层在图片 URL 为 null 时显示渐变占位
- **Notes**: 注意 Commons 图片需带归属（页面底部加一行图片来源说明）

## Task 7: 行前打包清单工具
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - `tools/checklist.js`：根据 plan 的出行季节/天数/风格生成默认清单（证件、衣物、电子、洗漱、药品、其他）。
  - 渲染为分类卡片，每项含 checkbox + 文本 + 删除按钮；底部"添加条目"输入。
  - 状态存 localStorage `tg_checklist_{planId}`，刷新保持。
- **Acceptance Criteria Addressed**: AC-3
- **Test Requirements**:
  - `rule` TR-7.1: 勾选条目后 localStorage 对应项 checked=true
  - `rule` TR-7.2: 刷新页面后勾选状态保持
- **Notes**: planId 可用目的地+日期生成稳定 hash

## Task 8: 预算追踪工具
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 1, Task 4
- **Description**:
  - `tools/budget.js`：展示 plan.budget 各分项计划金额，每项有"实际花费"输入框。
  - 实时计算分项差额（实际-计划）与总计划/总实际/总差额。
  - 数据存 localStorage `tg_budget_{planId}`。
- **Acceptance Criteria Addressed**: AC-4
- **Test Requirements**:
  - `rule` TR-8.1: 输入某项实际花费后，该项差额与总计数值立即正确更新
  - `rule` TR-8.2: 刷新后实际花费数值保持
- **Notes**: 金额输入用 number，默认 0

## Task 9: 行程编辑器与收藏
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - `tools/editor.js`：每日行程卡片可点击编辑时段、增删景点条目（内联编辑），保存回 localStorage `tg_plan_{planId}`。
  - `tools/favorites.js`：景点/美食卡片有"★"收藏按钮，收藏状态存 localStorage `tg_favorites_{planId}`，导航提供"收藏"视图集中展示。
- **Acceptance Criteria Addressed**: FR-7, FR-8
- **Test Requirements**:
  - `rule` TR-9.1: 编辑某景点时段后刷新，编辑结果保持
  - `rule` TR-9.2: 收藏景点后，收藏列表显示该项
- **Notes**: 编辑后重新渲染对应日卡片即可，不重新调 LLM

## Task 10: 导出静态 HTML
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 5
- **Description**:
  - `export/html.js`：将当前 plan + 内联 CSS 序列化为单文件 HTML，通过 Blob 下载。
  - 导出的 HTML 不含外部 JS 依赖（纯静态展示），CSS 内联，数据内联。
- **Acceptance Criteria Addressed**: AC-6
- **Test Requirements**:
  - `rule` TR-10.1: 导出文件含 `<style>` 内联样式且无外部 CSS `<link>`
  - `rule` TR-10.2: 断网双击导出文件可完整渲染 8 模块
- **Notes**: 导出时只保留手册正文，不含工具面板

## Task 11: 导出海报长图 PNG
- **Status**: `pending`
- **Priority**: low
- **Depends On**: Task 5
- **Description**:
  - `export/image.js`：复用 `travel-long-image.html` 的 414px 宽海报布局，将 plan 渲染到隐藏的 capture-target，用 `html-to-image`（CDN）转 PNG 下载。
  - 提供"导出长图"按钮与 loading 提示。
- **Acceptance Criteria Addressed**: FR-12
- **Test Requirements**:
  - `rule` TR-11.1: 点击导出后下载到 .png 文件，尺寸宽度 414px
- **Notes**: 通过 CDN 加载 `html-to-image`；若需完全离线可将库本地化

## Task 12: 集成打磨与端到端验证
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 6, Task 7, Task 8, Task 9, Task 10, Task 11, Task 13, Task 14, Task 15, Task 16, Task 19
- **Description**:
  - 串联全流程：输入目的地 → loading → 渲染手册 → 切换工具 → 导出。
  - 完善 loading/error/empty 状态；响应式适配移动端；可访问性（label、aria）。
  - 编写 README 使用说明（配置 API、运行方式、CORS fallback、可选后端启动、DSH 锁定版本与升级风险、Creator 模式实验工作流）。
  - 端到端走查所有 AC（含 AC-9 至 AC-13 后端爬虫、降级、Trajectory 可观测、插件热重载路径）。
- **Acceptance Criteria Addressed**: AC-1 至 AC-13
- **Test Requirements**:
  - `rule` TR-12.1: 完整跑通"输入目的地→生成→清单勾选→预算输入→导出HTML"无报错
  - `rule` TR-12.2: 后端模式下完整跑通"提交→抓取→集成→校对→渲染"无报错，至少 3 处来源链接可见
  - `rule` TR-12.3: 关闭后端后再次生成，前端在 5 秒内降级为纯前端模式并显示提示
  - `rule` TR-12.4: 调试视图能展示一次完整生成的至少 5 类事件且顺序合理
  - `rubric` TR-12.5: 端到端交互流畅度；scale 1-5；1=卡顿报错多 3=基本可用有瑕疵 5=顺滑提示清晰；threshold >=4；evidence=录屏/截图
- **Notes**: 此任务为最终验收整合；Task 17/18/20 为可选/低优先级，不阻塞 v1 验收

---

## Task 13: Python 后端骨架（FastAPI 薄壳 + DSH 启动器）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 4
- **Description**:
  - 新建 `server/` 目录，搭建 FastAPI 薄壳：`server/app/main.py`、`server/app/routes.py`、`server/app/dsh_runner.py`（封装 `deepseek-harness-sdk` 启动与请求路由）、`server/app/prompts.py`、`server/app/schema.py`（与前端 `schema.js` 共享字段定义）。
  - 暴露接口：`GET /health`、`POST /scrape`、`POST /generate`（输入 destination+prefs → 返回最终方案 + sources + warnings + session_id）、`GET /trajectory/{session_id}`、`POST /plugin/reload`、`POST /trajectory/replay/{session_id}`、`POST /llm-proxy`（可选转发，等价于 `proxy.py`）。
  - DSH 启动：`dsh_runner.py` 用 `DeepSeekHarness(dsh_home=server/.dsh-home, provider="deepseek-official", model=..., max_tokens=49152, base_url=..., api_key=...)` 启动；首次启动时 `dsh --profile sdk --dump-default-config` 并 `dsh plugin --profile sdk add file:./plugins/tg-bundle` 安装自研插件 Bundle。
  - 配置：`server/.env` 读取 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`、`DSH_HOME`、`DSH_MODE`（standard/ptc/minimal）；前端可在请求 header 中带 `X-LLM-Config` 覆盖（仅本次请求使用，不持久化）。
  - 启动脚本：`server/run.sh`（venv 创建 + pip install + uvicorn 启动）与 `server/requirements.txt`（fastapi、uvicorn、scrapling、httpx、python-dotenv、beautifulsoup4、`deepseek-harness-sdk==0.1.5rc1`）。
- **Acceptance Criteria Addressed**: AC-9, AC-12
- **Test Requirements**:
  - `rule` TR-13.1: `curl http://localhost:8000/health` 返回 `{"status":"ok","dsh":"ready"}`
  - `rule` TR-13.2: `POST /generate` 用真实 LLM key 时返回符合 schema 的 plan 且含 `session_id`
- **Notes**: DSH SDK 为预发布版，README 注明锁定版本与升级风险；薄壳函数层封装所有 SDK 调用便于跟进

## Task 14: Scrapling 抓取层（DSH `tg-scraper` 插件）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 13
- **Description**:
  - 新建 `server/plugins/tg-scraper/` Cordis 插件 Bundle，封装 Scrapling 调用：`scrape(task)` 接收 `{target_url, source_type, query, fields}`，返回 `{url, title, fields, raw_html_excerpt, extracted, source_url}`。
  - 支持三种 source_type：`wikipedia`（.wikipedia.org / wikivoyage）、`commons`（Wikimedia Commons 图片）、`generic`（其它公开旅游攻略/官方门票页）。
  - 使用 Scrapling 的 `StealthFetcher`（反反爬）与 `PlayWrightFetcher`（可选，用于 JS 渲染站点）。
  - 并发控制：`asyncio.Semaphore(4)`；单域名 ≤ 2；请求间最小间隔 500ms；超时 15s。
  - 遵守 robots.txt：用 `urllib.robotparser` 在抓取前校验；不抓 disallow 路径。
  - 失败降级：3 次重试后仍失败则记录 `error`，不阻塞整体流程；前端可见降级提示。
  - 插件契约：实现 Cordis service 接口 `tg.scrape.batch(tasks)` 与 event `tg.scrape.completed`，便于父 Agent 调用与 Trajectory 记录。
- **Acceptance Criteria Addressed**: AC-9
- **Test Requirements**:
  - `rule` TR-14.1: 对"趵突泉"Wikipedia 页面抓取返回非空 `extracted` 含名称与简介
  - `rule` TR-14.2: 对不存在的 URL 重试 3 次后返回 `{error}` 而非抛异常
- **Notes**: Scrapling 的 auto-match 能力用于字段自适应抽取，避免手写选择器

## Task 15: DSH `tg-*` 插件集（planner/integrator/validator/optimizer/cache/output）
- **Status**: `pending`
- **Priority**: high
- **Depends On**: Task 13, Task 14
- **Description**:
  - 在 `server/plugins/tg-bundle/` 下统一打包 6 个 Cordis 插件，遵循 Cordis 插件契约（service + event），每个插件独立可测、可热替换：
    1. **tg-planner**：`tg.plan.scrape_tasks(destination, prefs) → tasks[]`；调 LLM 生成抓取任务清单，prompt 见 `prompts.py:PLAN_SCRAPE_TASKS`。
    2. **tg-integrator**：`tg.integrate.plan(materials, prefs) → plan`；调 LLM 把素材 + 偏好合并为符合 schema 的方案 JSON，prompt 见 `prompts.py:INTEGRATE_PLAN`；要求 LLM 引用 source_url。
    3. **tg-validator**：`tg.validate.plan(plan, materials) → warnings[]`；LLM 事实校对 + 规则校对（名称拼写、价格区间、坐标城市、开放时间格式）。
    4. **tg-optimizer**：`tg.optimize.plan(plan) → plan'`；贪心路线时间分配 + 预算校准 + 最近邻 TSP 排序；可选进化策略。
    5. **tg-cache**：`tg.cache.get(key) / set(key, value, ttl) / invalidate(...)`；SQLite KV，TTL 7 天，三级粒度。
    6. **tg-output**：`tg.output.format(plan, sources, warnings, session_id) → response_json`；组装最终响应给 FastAPI 壳。
  - 父 Agent 在 Standard 模式下串行调度：planner → scraper → integrator → validator → optimizer → validator(二次) → output；每步走 Harness 工具协议，参数与结果进入 Trajectory 日志。
  - 返回结构：`{plan, sources:[{url,title}], warnings:[{level,field,msg}], session_id}`。
- **Acceptance Criteria Addressed**: AC-9, AC-10, AC-12
- **Test Requirements**:
  - `rule` TR-15.1: 端到端调 `POST /generate` body `{"destination":"济南","prefs":{"days":3}}` 返回合法 plan 且 `sources.length >= 3`、含 `session_id`
  - `rule` TR-15.2: `warnings` 至少 1 条且字段非空
  - `rule` TR-15.3: `GET /trajectory/{session_id}` 返回至少 5 类事件且顺序为 planner→scraper→integrator→validator→output
- **Notes**: 每一步 LLM 调用都走 `tg-cache`，相同输入 7 天内复用；Agent 主循环由 DSH 提供，不重写

## Task 16: 缓存层与来源追溯（前端联调）
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 15
- **Description**:
  - 后端 `tg-cache` 已在 Task 15 实现；本任务聚焦前端联调与渲染：
    - 前端 `renderer.js` 与 `schema.js` 扩展：景点/美食/住宿/预算条目可选 `source_url` 字段；渲染时在卡片底部以 `来源` 小字链接展示（`target="_blank" rel="noopener"`）。
    - 校对提示渲染：在手册顶部或对应卡片旁展示 `warnings` 列表（折叠式 callout）。
    - 设置面板新增"后端地址"与"模式切换"开关（纯前端 / 后端增强），保存至 `tg_config`。
  - 前端 `llm.js` 扩展：检测到"后端增强模式"时把请求转发到 `${backend_url}/generate`，否则走原纯前端 LLM 调用；后端不可达时 5 秒内降级并提示。
- **Acceptance Criteria Addressed**: AC-9, AC-10, AC-11
- **Test Requirements**:
  - `rule` TR-16.1: 相同目的地第二次生成 < 10s 且后端日志显示 cache hit
  - `rule` TR-16.2: 渲染后 DOM 至少 3 处 `来源:` 链接且 `href` 非空
  - `rule` TR-16.3: 关闭后端后再次生成，前端 5 秒内降级为纯前端模式并显示提示条
- **Notes**: 缓存仅在后端模式可用；纯前端模式无缓存

## Task 17: 数据计算/进化模块（tg-optimizer 插件，可选，按需启用）
- **Status**: `pending`
- **Priority**: low
- **Depends On**: Task 15
- **Description**:
  - `tg-optimizer` 插件先实现轻量版——
    - **路线时间分配**：贪心把景点按时长塞入每日 8h 窗口，超出则后移到下一天。
    - **预算分项校准**：用抓取的真实价格区间替换 LLM 估值，重新计算 total/per_person。
    - **景点排序**：按坐标聚类 + TSP 贪心（最近邻）排每日游览顺序，减少折返。
  - 仅当 AC-10 / AC-9 校对仍频繁报"路线时间不合理 / 预算偏差大"时，再引入进化策略（DEAP 或手写 μ+λ）：目标函数 = 时间窗违反惩罚 + 折返距离 + 预算偏差。
  - 所有优化结果仍交 LLM 校对一次后再返回前端。
- **Acceptance Criteria Addressed**: FR-17
- **Test Requirements**:
  - `rule` TR-17.1: 给定 3 天 8 景点含时长，贪心分配后无单日超 8h
  - `rule` TR-17.2: 抓取到真实价格时，预算 total 与各分项单价对齐
- **Notes**: 若轻量版已满足 AC-9/AC-10，本任务的进化策略部分可不做

## Task 18: Subagent 并行委派（可选）
- **Status**: `pending`
- **Priority**: low
- **Depends On**: Task 15
- **Description**:
  - 利用 DSH rc.8+ 的 subagent 机制，把 `tg-scraper` 的多源抓取拆为多个并行 subagent，每个 subagent 处理一组 target_url；分支完成后通过 `reportDelivery` 唤醒父任务。
  - 同样可把"研究（深度搜索）vs 集成 vs 校对"拆给不同 subagent 并行推进（仅在 AC-9 性能不达标时启用）。
  - 父 Agent 通过 Trajectory 记录所有 subagent 调度事件，前端调试视图可折叠展示每个分支。
- **Acceptance Criteria Addressed**: FR-22
- **Test Requirements**:
  - `rule` TR-18.1: 启用 subagent 后，5 源抓取总耗时 < 串行模式的 70%
  - `rule` TR-18.2: Trajectory 中可见 `subagent.fork` 与 `reportDelivery` 事件
- **Notes**: v1 默认串行；仅在 AC-9 不达标时启用

## Task 19: Trajectory 调试视图与可观测性
- **Status**: `pending`
- **Priority**: medium
- **Depends On**: Task 15
- **Description**:
  - 前端新增"调试视图"（导航栏额外入口，仅在"后端增强模式"下可见）：
    - 输入 `session_id`（或从最近一次生成自动带出）→ 调 `GET /trajectory/{session_id}` → 按时间线渲染事件流（system_prompt / 工具调用 / subagent / 上下文注入）。
    - 每个事件可展开查看输入/输出 JSON；对 LLM 调用展示 token 估算与耗时。
    - 支持"重放"按钮：调 `POST /trajectory/replay/{session_id}` 用同输入再跑一次，对比两次结果。
  - 后端 `routes.py` 实现 `/trajectory/{session_id}` 与 `/trajectory/replay/{session_id}`，从 DSH 的 Trajectory 日志读取并返回结构化 JSON。
- **Acceptance Criteria Addressed**: AC-12, NFR-9
- **Test Requirements**:
  - `rule` TR-19.1: 调试视图能展示一次完整生成的至少 5 类事件且顺序合理
  - `rule` TR-19.2: 重放按钮可触发后端再跑一次并返回新的 session_id
- **Notes**: 调试视图只读，不允许编辑事件流

## Task 20: 插件热重载与自进化接口（v1 仅手动实验）
- **Status**: `pending`
- **Priority**: low
- **Depends On**: Task 15, Task 19
- **Description**:
  - 后端实现 `POST /plugin/reload`：body `{plugin: "tg-validator", bundle_path: "/abs/path"}`；调用 DSH 的 `dsh plugin --profile sdk add file:...` 重装并热重载，10 秒内完成。
  - 后端实现 `/trajectory/replay/{session_id}`（已在 Task 19 提及，此处统一接线）。
  - README 写明在 Creator 模式下用 `/plugin/reload` + `/trajectory/replay` 做组合实验的工作流：改插件 → 重载 → 重放历史轨迹 → 对比输出。
  - v1 不实现自动学习闭环；仅保证接口与数据沉淀，便于后续接入 JIT-Agent / HSI 等自进化方法。
- **Acceptance Criteria Addressed**: AC-13, FR-25, NFR-10
- **Test Requirements**:
  - `rule` TR-20.1: `POST /plugin/reload` 指定 `tg-validator` 新 bundle 后，10 秒内日志可见 `plugin reloaded: tg-validator`
  - `rule` TR-20.2: 重载后再次 `/generate` 用相同输入，结果或显式版本号发生可观察变化
- **Notes**: v1 仅手动实验；自动学习闭环不在本次范围

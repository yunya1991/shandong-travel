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
- **Depends On**: Task 6, Task 7, Task 8, Task 9, Task 10, Task 11
- **Description**:
  - 串联全流程：输入目的地 → loading → 渲染手册 → 切换工具 → 导出。
  - 完善 loading/error/empty 状态；响应式适配移动端；可访问性（label、aria）。
  - 编写 README 使用说明（配置 API、运行方式、CORS fallback）。
  - 端到端走查所有 AC。
- **Acceptance Criteria Addressed**: AC-1 至 AC-8
- **Test Requirements**:
  - `rule` TR-12.1: 完整跑通"输入目的地→生成→清单勾选→预算输入→导出HTML"无报错
  - `rubric` TR-12.2: 端到端交互流畅度；scale 1-5；1=卡顿报错多 3=基本可用有瑕疵 5=顺滑提示清晰；threshold >=4；evidence=录屏/截图
- **Notes**: 此任务为最终验收整合

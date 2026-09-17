# 旅游手册生成器 · Product Requirements Document

## Overview
- **Summary**: 一个可配置大模型 API 后直接运行的单页 Web 应用（Travel Guide Generator）。用户输入目的地（地名）与出行偏好，应用调用大模型生成结构化旅游方案，并渲染为包含行程概览、路线地图、每日安排、景点（含图片）、住宿、美食、预算、贴士的精美旅游手册，同时提供行前清单、预算追踪、行程编辑等交互式管理工具。
- **Purpose**: 将"输入地名 → 自动产出旅游手册与管理工具"的流程自动化，复用用户已有的暖色调编辑风格 HTML/CSS 与参考海报的 8 段式结构，让用户无需再逐字撰写攻略。
- **Target Users**: 个人旅行者，尤其是喜欢提前规划、希望快速获得结构化攻略与行前管理工具的用户。

## Goals
- G1: 输入目的地 + 基本偏好后，一键生成覆盖参考海报 8 大模块的完整旅游手册。
- G2: 手册视觉质量接近用户现有 `index.html`（暖色调编辑风格）与参考海报（图文混排长图）的水平。
- G3: 提供可交互的管理工具：行前打包清单、预算追踪、每日行程编辑，且状态本地持久化。
- G4: 配置一次大模型 API 即可运行，无需后端服务（优先纯前端方案）。
- G5: 生成结果可导出为静态 HTML 或长图，便于分享/打印。

## Non-Goals
- 不做用户登录/注册系统、不做云端同步。
- 不做真实机票/酒店/门票预订与支付。
- 不做实时导航、离线地图下载。
- 不做多人协作编辑。
- 不做移动端原生 App（仅响应式 Web）。

## Background & Context
- 用户已产出三份 HTML：`index.html`（编辑风格网页攻略，含 SVG 路线图、日卡片、景点/美食/交通/贴士模块）、`shandong-travel-guide.html`（同 index 编辑版）、`travel-long-image.html`（414px 宽海报长图，含下载按钮）。设计语言为 Warm Editorial 调色板（`#B8551D` 主色、`#D97757` 辅色、`#FAF6F2` 背景）。
- 参考照片为「北京出发·阿尔山&呼伦贝尔 7天6晚自驾之旅」海报，结构为：①行程概览 ②路线地图 ③每天行程安排 ④沿途精彩景点（配图+建议游玩时长）⑤住宿推荐（价格区间）⑥当地美食推荐（配图）⑦费用预估（住宿/油费/餐饮/门票交通/其他/合计）⑧出行贴士。
- 调研结论（2025 主流旅游 AI 工具）：马蜂窝 AI 路书主打"主动提问→行程+住宿+交通+景点+美食+购物+预算+贴士"全链路；Wanderlog 提供行程+地图一体视图、AI 助手、打包清单、预算追踪；TripIt 从邮件自动聚合行程+天气+离线；PackPoint 按目的地/天气/活动生成智能打包清单；Roadtrippers 提供路线规划、POI、油费估算。这些功能为"管理工具"模块提供参考。

## Functional Requirements

### 生成与渲染
- **FR-1**: 提供目的地输入与偏好表单（出行日期/天数、出行人数、预算档位、旅行风格：自然风光/人文历史/美食探店/亲子/自驾、出发城市）。
- **FR-2**: 应用使用 OpenAI 兼容 API（可配置 base_url、model、api_key），按结构化 prompt 生成旅游方案 JSON，字段至少覆盖：概览、每日行程、景点列表（含名称/描述/建议时长/门票）、住宿建议、美食推荐、预算分项、出行贴士、路线节点。
- **FR-3**: 将生成的 JSON 渲染为手册页面，包含参考海报的 8 个模块，并复用用户现有暖色调设计语言与卡片/标签/贴士组件。
- **FR-4**: 景点与美食模块展示配图：默认通过 Wikimedia Commons API（免 key）按名称查询图片；查询失败时使用主题色渐变占位。

### 管理工具
- **FR-5**: 行前打包清单：按类别（证件、衣物、电子、洗漱、药品、其他）展示可勾选条目，支持增删条目，勾选状态本地持久化。
- **FR-6**: 预算追踪：展示 LLM 给出的预算分项，用户可逐项记录实际花费，实时显示计划 vs 实际差额，数据本地持久化。
- **FR-7**: 行程编辑：每日行程卡片可调整时段、增删景点/活动，编辑结果本地持久化。
- **FR-8**: 收藏：景点/美食可标记收藏，收藏列表集中展示。

### 配置与持久化
- **FR-9**: 设置面板可配置 API base_url、model、api_key，保存至 localStorage；api_key 仅本地存储不回传任何第三方。
- **FR-10**: 生成的旅游方案、清单状态、预算记录、收藏均保存至 localStorage，可在应用内重新加载历史方案。

### 导出
- **FR-11**: 支持将当前手册导出为单文件静态 HTML（内联 CSS/数据），可在浏览器离线打开。
- **FR-12**: 支持将手册渲染为海报长图（复用 `travel-long-image.html` 的 414px 宽布局思路）并下载为 PNG。

## Non-Functional Requirements
- **NFR-1（可运行性）**: 仅需现代浏览器，打开 `index.html`（或通过任意静态服务器）即可使用；不依赖 Node/Python 运行时（除非用户选择启用可选后端代理）。
- **NFR-2（性能）**: 单次方案生成端到端 ≤ 60 秒（取决于 LLM 响应）；页面首屏渲染 ≤ 2 秒。
- **NFR-3（安全）**: API key 仅存于 localStorage，不在 URL/日志中暴露；所有 LLM 返回内容渲染前做 HTML 转义，避免 XSS。
- **NFR-4（响应式）**: 桌面与移动端均可正常浏览，移动端宽度下导航与卡片自适应。
- **NFR-5（可维护性）**: 代码按模块拆分（配置、LLM 客户端、数据 schema、渲染、管理工具），prompt 模板集中管理便于调优。
- **NFR-6（可访问性）**: 表单有 label，按钮有可识别文本，对比度符合阅读需求。

## Constraints
- **Technical**: 纯前端 HTML/CSS/原生 JS（ES Module），无构建步骤，打开 `index.html` 即可运行；大模型 API 采用 OpenAI 兼容 `/chat/completions` 协议（DeepSeek、OpenAI、通义、Moonshot 等均可），base_url/model/api_key 用户可配。附带一个可选 `proxy.py`（约 30 行 Python）作为 CORS fallback，不作为运行必需。
- **Business**: 不引入付费第三方服务；图片使用 Wikimedia Commons 免 key 接口。
- **Dependencies**: 大模型 API 可用性；浏览器原生 `fetch`、`localStorage`；`html-to-image`（CDN）用于长图导出。

## Assumptions
- A1: 用户拥有可用的 OpenAI 兼容 API key（如 DeepSeek）。
- A2: 浏览器可直连大模型 API endpoint；若遇 CORS，用户可运行 `proxy.py` 本地代理。
- A3: Wikimedia Commons API 可在浏览器中跨域访问（其支持 CORS）。
- A4: 用户接受"AI 生成内容需自行核实"的免责声明。
- A5: "旅游 skill 集"指应用内的功能模块集合（规划、清单、预算、编辑、收藏、导出），整体为独立 Web 应用。

## Acceptance Criteria

### AC-1: 目的地输入触发生成
- **Type**: `rule`
- **Given**: 用户已在设置中填入有效 API base_url、model、api_key
- **When**: 用户输入目的地名称并提交（含或不含偏好）
- **Then**: 应用向 LLM 发起请求并返回结构化 JSON 方案
- **Pass Condition**: Network 面板可见对 `{base_url}/chat/completions` 的 POST 请求且响应 200；方案 JSON 含 overview、daily、attractions、accommodation、food、budget、tips、route 字段
- **Evidence**: 浏览器 DevTools Network 截图 + 生成的 JSON 片段

### AC-2: 手册渲染覆盖 8 大模块
- **Type**: `rule`
- **Given**: LLM 返回了有效方案 JSON
- **When**: 渲染完成
- **Then**: 页面依次出现：行程概览、路线地图、每日行程、精彩景点（配图）、住宿推荐、美食推荐（配图）、费用预估、出行贴士
- **Pass Condition**: DOM 中存在对应 8 个 section，且每个 section 填充了来自 JSON 的真实内容
- **Evidence**: 渲染后页面截图与 DOM 检查

### AC-3: 打包清单可勾选并持久化
- **Type**: `rule`
- **Given**: 已生成一个方案并进入"行前清单"工具
- **When**: 用户勾选若干条目并刷新页面
- **Then**: 刷新后勾选状态保持不变
- **Pass Condition**: 勾选后 localStorage 中对应条目 checked=true；刷新后 UI 仍显示已勾选
- **Evidence**: localStorage 内容截图 + 刷新前后对比

### AC-4: 预算追踪实时计算差额
- **Type**: `rule`
- **Given**: 方案含预算分项，进入"预算追踪"工具
- **When**: 用户为某分项输入实际花费
- **Then**: 该分项与总计的"实际/计划/差额"实时更新
- **Pass Condition**: 输入后总额与差额数值正确，且保存至 localStorage
- **Evidence**: 输入前后数值对比

### AC-5: API 配置本地存储
- **Type**: `rule`
- **Given**: 用户在设置面板填写 base_url/model/api_key 并保存
- **When**: 重新打开应用
- **Then**: 三个字段已回填，无需重新输入
- **Pass Condition**: localStorage 含 `tg_config` 且字段正确；重开页面表单已回填
- **Evidence**: localStorage 截图 + 重开页面截图

### AC-6: 导出静态 HTML 可离线打开
- **Type**: `rule`
- **Given**: 已生成方案
- **When**: 点击"导出 HTML"并下载
- **Then**: 下载的 .html 文件双击可在断网状态下完整渲染手册（CSS 内联）
- **Pass Condition**: 导出文件包含内联 `<style>` 与内联数据，无外部 CDN 依赖（长图导出库除外但导出本身不依赖）
- **Evidence**: 导出文件源码片段 + 断网打开截图

### AC-7: 视觉风格一致性
- **Type**: `rubric`
- **Dimension**: 生成手册与用户现有 `index.html` 暖色调编辑风格及参考海报图文结构的一致性
- **Scale**: 1-5
- **Anchors**: 1 = 风格杂乱、与现有设计脱节；3 = 配色一致但组件结构有明显差异；5 = 配色、卡片、标签、贴士组件与现有 HTML 高度一致，且 8 模块结构与参考海报对齐
- **Pass Threshold**: >= 4
- **Evidence**: 生成手册截图与 `index.html`/参考照片并排对比

### AC-8: 交互流畅度
- **Type**: `rubric`
- **Dimension**: 从输入目的地到获得可交互手册的端到端体验流畅度
- **Scale**: 1-5
- **Anchors**: 1 = 卡顿/报错频繁、需多次重试；3 = 基本可用但有明显等待或小瑕疵；5 = 生成-渲染-工具切换顺滑，loading/错误提示清晰
- **Pass Threshold**: >= 4
- **Evidence**: 操作录屏或分步截图

## Open Questions
- [x] ~~**Q1 技术栈**~~：已确认纯前端方案，附可选 `proxy.py` CORS fallback。
- [x] ~~**Q2 图片来源**~~：已确认默认 Wikimedia Commons 免 key 查图。
- [x] ~~**Q3 大模型偏好**~~：已确认 OpenAI 兼容协议通用适配。
- [x] ~~**Q4 "skill 集"形态**~~：已确认为应用内功能模块集合，非 TRAE Skill 封装。

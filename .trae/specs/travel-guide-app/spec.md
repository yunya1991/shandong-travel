# AI 旅行手册 · Product Requirements Document
> 攻略碎片化 → 可执行行程的转换引擎 · DeepSeek Harness 驱动

## Overview
- **Summary**: "AI 旅行手册"是一个把"看了很多攻略但不知道怎么变成一份能出发的行程"这一最耗时断点自动化的应用。前端为面向终端用户的可视化行程编辑器（按天卡片 + 地图 + 协作），后端由 DeepSeek Harness（DSH，Cordis 全插件智能体框架）作为编排核心，把"链接解析 → 信息抽取 → 地理排线 → 动态优化 → 替代方案推送"五个环节封装为可热替换的 Cordis 插件，LLM 在 Harness 框架内"守规矩办事"。内容来源支持两条路径：①主推——由 Scrapling 爬虫按用户给的目的地/偏好自动爬取全网攻略（小红书/抖音/微信公众号/穷游等），最省事；②兜底——用户也可手动粘贴链接、正文文本或截图（用于补充、微调或对自动结果做人工校验）。两条路径的素材都进入同一套抽取与排线流水线，DSH Agent 在 30 秒内自动提取地点、天数、顺序，结合高德/百度地图 API 做地理空间智能排线，输出按天可视化行程；行程支持多人实时协作拖拽编辑；并具备动态优化引擎，实时监测天气/景点闭馆/交通延误，自动推送替代方案。完全免费、无广告、无预订商业倾向。
- **Purpose**: 把"攻略 → 可执行行程"的转换从手工耗时几天压缩到 30 秒；通过"DSH 编排 + Scrapling 取材 + LLM 抽取/校对 + 地图 API 排线"分工节省 token、保证内容真实度；通过与 OTA 平台互补（不做预订、不做社区）形成差异化定位。
- **Target Users**: 个人与组队旅行者（家庭/朋友组队出行），尤其是习惯在小红书/抖音/穷游看攻略但受困于"信息碎片化无法变成可执行行程"的用户。

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

### 爬虫取材与 LLM 编排（可选 Python 后端）
- **FR-13**: 提供可选的 Python 后端服务（FastAPI 薄壳 + DeepSeek Harness Agent），暴露 `/scrape`、`/generate`、`/health`、`/trajectory/{session_id}` 等 HTTP 接口；前端在设置面板可切换"纯前端模式"与"后端增强模式"，后端地址可配置。
- **FR-14**: 输入来源双路径：①**自动爬（主推，最省事）**——用户只输入目的地 + 偏好，由 `tg-planner` + `tg-scraper` 自动按关键词爬取全网攻略（小红书/抖音/微信公众号/穷游等公开页）；②**用户粘贴（兜底/微调）**——用户可在输入框手动粘贴一条或多条链接、正文文本、或上传截图（链接解析、文本抽取、OCR 各走对应子模块），用于补充自动结果不足、微调偏好、或对自动结果做人工校验。两条路径素材合并进入同一套抽取与排线流水线，均携带 `source_url` 与 `source_type`（auto_scrape / user_paste_link / user_paste_text / user_paste_image）。前端输入区提供"自动爬"与"粘贴"两个 Tab，可混用。
- **FR-14a**: LLM 驱动爬虫（由 `tg-planner` 插件实现）：在"自动爬"路径下，DSH Agent 接收"目的地 + 偏好"后调用 `tg-planner`，由 LLM 输出结构化抓取任务清单（target_url/source_type/query/fields），交由 `tg-scraper` 执行；整个调用走 Harness 工具协议，参数与结果进入 Trajectory 日志。
- **FR-15**: Scrapling 抓取层（由 `tg-scraper` 插件实现）：封装 Scrapling 的 `StealthFetcher`/`PlayWrightFetcher`，支持自适应元素选择（auto-match）、反反爬、并发抓取、失败重试与降级；超时 ≤15s，全局并发 ≤4，单域名 ≤2，请求间最小间隔 500ms；遵守 `robots.txt`。
- **FR-16**: LLM 集成与校对（由 `tg-integrator` + `tg-validator` 插件实现）：`tg-integrator` 把抓取素材 + 偏好合并为符合 schema 的方案 JSON（要求 LLM 引用 source_url）；`tg-validator` 做事实校对（名称拼写、价格区间、坐标城市匹配、开放时间格式），产出 `warnings[]`；两者均通过 Harness 工具调用 LLM，结果带缓存键。
- **FR-17**: 数据计算/进化（由 `tg-optimizer` 插件实现，可选）：路线时间分配（贪心 + 时间窗）、预算校准（用真实价格替换 LLM 估值）、景点排序（坐标聚类 + 最近邻 TSP）；当简单算法仍达不到 AC 时再引入进化策略；优化结果仍交 `tg-validator` 二次校对。
- **FR-18**: 缓存层（由 `tg-cache` 插件实现）：基于 SQLite 的 KV 缓存，按 (target_url+query)、(prompt+inputs hash)、(destination+prefs hash) 三级粒度，TTL 默认 7 天，可配置；命中时直接跳过 Scrapling 与 LLM 调用。
- **FR-19**: 来源追溯：每个景点/美食/住宿/价格条目携带 `source_url` 字段；渲染时在卡片底部以小字展示"来源"链接，便于用户核实。

### DeepSeek Harness 编排与自进化（可选 Python 后端 · 进阶）
- **FR-20**: 后端启用时，编排核心为 `deepseek-harness-sdk`（PyPI 预发布版），通过 `DeepSeekHarness(dsh_home=..., provider="deepseek-official", model=..., max_tokens=...)` 启动一个 Standard 模式 Agent；FastAPI 仅作为 HTTP 适配壳，所有编排逻辑发生在 DSH 内部，不重写 Agent 主循环。
- **FR-21**: 自研 Cordis 插件集 `tg-*`（planner/scraper/integrator/validator/optimizer/cache/output）以 Bundle 形式通过 `dsh plugin --profile sdk add file:...` 安装到独立 `DSH_HOME`，遵循插件契约（Cordis service/event）；每个插件独立可测、可热替换、可在 Creator 模式下做组合实验。
- **FR-22**: Subagent 委派（可选）：对"多源并行抓取"或"研究 vs 集成 vs 校对"等可并行子任务，由父 Agent 用 DSH 内置的 subagent 机制拆出分支，分支完成后通过 `reportDelivery` 唤醒父任务；v1 默认串行，仅当 AC-9 性能不达标时启用并行。
- **FR-23**: Trajectory 可观测：每次 `/generate` 调用返回 `session_id`，前端可通过 `/trajectory/{session_id}` 拉取该次执行的 append-only 轨迹（system prompt、思考、工具调用、子 Agent 调度、上下文注入）；前端在"调试视图"中按时间线展示，便于用户理解"为什么这样生成"。
- **FR-24**: LLM Provider 兼容：DSH 默认 `deepseek-official` provider，但通过 OpenAI 兼容协议同样可挂 DeepSeek V4 / DeepSeek-V3 / OpenAI / 通义 / Moonshot；用户在设置面板填的 base_url/model/api_key 通过 `X-LLM-Config` header 传给后端，后端在启动 DSH 时通过 `base_url`/`api_key` 覆盖参数注入对应 provider，不在 DSH_HOME 持久化用户 key。
- **FR-25**: 自进化接口（v1 仅可观测 + 手动实验）：暴露 `/plugin/reload`、`/trajectory/replay/{session_id}` 两个调试接口，允许在 Creator 模式下重新组合插件并回放历史轨迹评估效果；v1 不上线自动学习闭环，但保留接口与数据沉淀。
- **FR-26**: 沙箱与安全：Scrapling 抓取与可能的 Bash/文件操作只在 DSH 的 Docker 沙箱（或本地 venv 隔离）内执行；高危命令与越权文件访问由 DSH 沙箱策略拦截；前端不接受任何来自前端的可执行代码注入。

## Non-Functional Requirements
- **NFR-1（可运行性）**: 仅需现代浏览器，打开 `index.html`（或通过任意静态服务器）即可使用；前端可独立工作（纯前端模式直接调 LLM API）。启用 Python 后端时需 `python ≥ 3.10` 与 `pip install fastapi uvicorn scrapling deepseek-harness-sdk`（详见后端 README；DSH SDK 为预发布版，README 注明风险）。
- **NFR-2（性能）**: 纯前端模式：单次方案生成 ≤ 60 秒；后端增强模式：抓取 + 集成 + 校对端到端 ≤ 90 秒（含缓存命中应 ≤ 10 秒）；页面首屏渲染 ≤ 2 秒。Subagent 并行模式下应再降 30% 端到端耗时（v1 不强制）。
- **NFR-3（安全）**: API key 仅存于 localStorage，不在 URL/日志中暴露；所有 LLM 与爬虫返回内容渲染前做 HTML 转义，避免 XSS。后端仅在请求内存中持有用户 key（`X-LLM-Config` header），不写入 DSH_HOME 或磁盘。
- **NFR-4（响应式）**: 桌面与移动端均可正常浏览，移动端宽度下导航与卡片自适应。
- **NFR-5（可维护性）**: 代码按模块拆分（前端：配置、LLM 客户端、数据 schema、渲染、管理工具；后端：FastAPI 壳 + DSH 插件 Bundle：tg-planner/tg-scraper/tg-integrator/tg-validator/tg-optimizer/tg-cache/tg-output），prompt 模板集中管理便于调优。
- **NFR-6（可访问性）**: 表单有 label，按钮有可识别文本，对比度符合阅读需求。
- **NFR-7（合规抓取）**: 爬虫仅抓取公开可访问页面，遵守目标站点 `robots.txt`，单域名并发 ≤ 2，请求间设最小间隔（≥ 500ms）；不抓取需登录或付费墙内容。沙箱内执行，高危操作由 DSH 沙箱策略拦截。
- **NFR-8（降级）**: 后端不可达 / DSH 启动失败 / Scrapling 抛错时，前端自动降级为"纯前端模式 + Wikimedia 图片"，保证手册仍可生成。
- **NFR-9（可观测性）**: 后端模式下，每次生成返回 `session_id`，前端可拉取 Trajectory 轨迹并在调试视图中按时间线展示；所有 LLM/Scrapling/subagent 调用进入 append-only 日志，便于复盘与回放。
- **NFR-10（演进友好）**: 所有 `tg-*` 插件遵循 Cordis 插件契约，支持热重载与配置级组合；v1 不强制上线自进化，但所有可热替换点必须可被 Creator 模式实验与 `/plugin/reload` 接口验证。

## Constraints
- **Technical**: 前端为纯 HTML/CSS/原生 JS（ES Module），无构建步骤；后端为 Python FastAPI 薄壳 + `deepseek-harness-sdk`（Cordis 插件框架）+ Scrapling（作为 DSH 工具插件）。大模型 API 采用 OpenAI 兼容 `/chat/completions` 协议（DeepSeek V4/V3、OpenAI、通义、Moonshot 等均可），base_url/model/api_key 用户可配。
- **Business**: 不引入付费第三方服务；爬虫仅消费公开网页，不绕过付费墙；图片优先使用 Wikimedia Commons 免 key 接口或 Scrapling 抓取的公开图片（带来源）。
- **Dependencies**: 大模型 API 可用性；浏览器原生 `fetch`、`localStorage`；`html-to-image`（CDN）用于长图导出；可选后端依赖 `fastapi`、`uvicorn`、`scrapling`、`httpx`、`beautifulsoup4`、`deepseek-harness-sdk`（PyPI 预发布）。
- **Reversibility**: 启用后端为可选增强；前端必须能在不启动后端的情况下完成"输入目的地 → 渲染手册 → 使用工具"的完整闭环。
- **Versioning**: `deepseek-harness-sdk` 当前为 `0.1.5rc1` 预发布版，API 可能在后续版本调整；后端代码需在 README 注明锁定版本与升级风险，关键调用点用薄壳函数封装以便跟进。

## Assumptions
- A1: 用户拥有可用的 OpenAI 兼容 API key（如 DeepSeek）。
- A2: 浏览器可直连大模型 API endpoint；若遇 CORS，用户可运行 `proxy.py` 或启用 Python 后端转发。
- A3: Wikimedia Commons API 可在浏览器中跨域访问（其支持 CORS）。
- A4: 用户接受"AI 生成内容需自行核实"的免责声明，前端在卡片底部展示来源链接与校对提示。
- A5: "旅游 skill 集"指应用内的功能模块集合（规划、清单、预算、编辑、收藏、导出），整体为独立 Web 应用。
- A6: 启用后端增强模式时，用户具备本地运行 Python 服务的基础能力（venv + pip install + uvicorn 启动）。
- A7: 抓取目标站点（Wikipedia、Wikivoyage、公开旅游攻略站等）的 `robots.txt` 允许常见 UA 抓取；如遇 403/429，Scrapling 通过 stealth 模式或换源降级。
- A8: `deepseek-harness-sdk` 在用户运行时仍可从 PyPI 安装；若预发布版 API 调整，后端薄壳函数层负责跟进，不波及前端。
- A9: DSH_HOME 目录与 Cordis profile 由后端进程在首次启动时初始化到 `server/.dsh-home/`，与用户全局 `~/.dsh` 隔离。

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

### AC-9: 后端爬虫取材与缓存
- **Type**: `rule`
- **Given**: 用户在设置中切换为"后端增强模式"并填入可用的后端地址（如 `http://localhost:8000`）
- **When**: 用户输入目的地并提交
- **Then**: 后端先检查缓存；未命中时由 LLM 生成抓取任务清单并调用 Scrapling 抓取，返回结构化素材 + 来源 URL
- **Pass Condition**: 后端日志可见"task plan → scrapling → integrate → validate"流程；返回的素材中至少 70% 条目携带 `source_url`；相同目的地第二次生成命中缓存且响应 < 10s
- **Evidence**: 后端日志 + 第二次请求耗时截图 + 返回 JSON 中的 source_url 字段

### AC-10: 内容来源与校对提示
- **Type**: `rule`
- **Given**: 通过后端增强模式生成了方案
- **When**: 手册渲染完成
- **Then**: 景点/美食/住宿/价格条目卡片底部展示"来源"小字链接；至少展示一条 LLM 校对提示（如价格区间合理性、名称拼写等）
- **Pass Condition**: DOM 中至少 3 处可见 `来源:` 链接且 `href` 非空；至少 1 条校对提示可见
- **Evidence**: 渲染后截图 + DOM 检查

### AC-11: 后端不可达时降级
- **Type**: `rule`
- **Given**: 设置为"后端增强模式"但后端地址不可达（关闭后端进程）
- **When**: 用户提交生成请求
- **Then**: 前端在 5 秒内检测到后端不可达，自动降级为"纯前端模式"完成生成，并在 UI 顶部提示"后端不可达，已降级为纯前端模式"
- **Pass Condition**: 仍能产出符合 schema 的方案；提示条可见
- **Evidence**: 关闭后端前后的两次请求行为对比 + 提示条截图

### AC-12: DSH 插件化编排可追溯
- **Type**: `rule`
- **Given**: 后端增强模式 + DSH Agent 正常运行
- **When**: 用户提交一次生成请求
- **Then**: 后端返回 `session_id`；调用 `GET /trajectory/{session_id}` 返回按时间排序的事件流，至少包含：system_prompt、tg-planner 调用、tg-scraper 调用、tg-integrator 调用、tg-validator 调用五个事件
- **Pass Condition**: Trajectory JSON 含上述 5 类事件且顺序合理；前端调试视图按时间线展示
- **Evidence**: `/trajectory` 返回 JSON + 前端调试视图截图

### AC-13: 插件可热重载（自进化前置）
- **Type**: `rule`
- **Given**: 后端运行中
- **When**: 调用 `POST /plugin/reload` 指定 `tg-validator` 插件的新 bundle 路径
- **Then**: 后端在 10 秒内完成热重载，下次 `/generate` 调用使用新版本插件，无需重启 uvicorn
- **Pass Condition**: 重载日志可见 "plugin reloaded: tg-validator"；前后两次 `/generate` 在相同输入下产出可观察差异或显式版本号变化
- **Evidence**: 重载日志 + 两次生成结果对比

## Open Questions
- [x] ~~**Q1 技术栈**~~：已确认前端可独立工作，后端为可选增强（FastAPI + DSH + Scrapling）。
- [x] ~~**Q2 图片来源**~~：默认 Wikimedia Commons；后端模式下可由 Scrapling 抓取带来源的公开图片补充。
- [x] ~~**Q3 大模型偏好**~~：已确认 OpenAI 兼容协议通用适配。
- [x] ~~**Q4 "skill 集"形态**~~：已确认为应用内功能模块集合，非 TRAE Skill 封装。
- [x] ~~**Q5 算法模型必要性**~~：预算/路线/排序等先用贪心 + LLM 校对即可；引入进化策略仅在简单方法不能达到 AC 时再启用（FR-17）。
- [x] ~~**Q6 编排框架**~~：采用 DeepSeek Harness（Cordis 全插件 + Trajectory + subagent + 自进化友好）作为后端编排核心，FastAPI 仅做 HTTP 壳。
- [ ] **Q7 Scrapling MCP**：Scrapling 提供 MCP Server，v1 直接接入 MCP 还是先走 DSH 工具插件？倾向 v1 把 Scrapling 包成 `tg-scraper` Cordis 插件（FR-15），MCP 留作后续。
- [ ] **Q8 DSH 沙箱模式**：v1 用 Docker 沙箱还是本地 venv 隔离？倾向 v1 用 venv 简化部署，Docker 沙箱作为 README 可选项。

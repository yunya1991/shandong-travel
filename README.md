# AI 旅行手册

> 攻略碎片化 → 可执行行程的转换引擎。配置大模型 API 后直接运行，输入地名即可自动生成旅游手册和管理工具。

[![Spec](https://img.shields.io/badge/spec-travel--guide--app-blue)](.trae/specs/travel-guide-app/spec.md)
[![Tasks](https://img.shields.io/badge/tasks-md-green)](.trae/specs/travel-guide-app/tasks.md)

---

## 目录

- [快速开始](#快速开始)
- [配置 API](#配置-api)
- [运行方式](#运行方式)
- [CORS Fallback](#cors-fallback)
- [后端启动（增强模式）](#后端启动增强模式)
- [DeepSeek Harness（DSH）说明与风险](#deepseek-harnessdsh说明与风险)
- [Creator 模式工作流](#creator-模式工作流)
- [项目结构](#项目结构)
- [功能矩阵](#功能矩阵)
- [常见问题](#常见问题)

---

## 快速开始

最快路径（30 秒体验）：

```bash
# 1. 启动前端静态服务
cd app && python3 -m http.server 5173

# 2. 浏览器打开
open http://localhost:5173
```

打开后在「设置」里填入你的大模型 API Key（默认 DeepSeek），回到「生成手册」输入目的地（如"济南"），点击「生成手册」即可。

> 纯前端模式无需后端，但只有 LLM 能力，**没有**爬虫取材、来源追溯、Trajectory 调试视图、动态优化引擎。

完整能力（推荐）：见下方[后端启动（增强模式）](#后端启动增强模式)。

---

## 配置 API

应用支持所有兼容 OpenAI `/chat/completions` 协议的服务。在「设置」标签页填写：

| 字段 | 示例 | 说明 |
|------|------|------|
| API Base URL | `https://api.deepseek.com` | DeepSeek 默认；OpenAI 用 `https://api.openai.com/v1`，通义用 `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 模型名称 | `deepseek-chat` | DeepSeek 用 `deepseek-chat`；OpenAI 用 `gpt-4o-mini` 等 |
| API Key | `sk-xxxxxxxx` | 仅保存在浏览器 `localStorage`，**不会上传到任何第三方服务器**（后端模式仅本次请求通过 `X-LLM-Config` header 透传给本地后端） |

常见服务商：

| 服务商 | Base URL | 推荐模型 |
|--------|----------|----------|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| Moonshot | `https://api.moonshot.cn/v1` | `moonshot-v1-8k` |

---

## 运行方式

### 模式一：纯前端模式（默认）

最简形态，只调 LLM 生成方案，无后端依赖。

```bash
cd app
python3 -m http.server 5173
# 浏览器访问 http://localhost:5173
```

特性：
- 直接在浏览器里调 LLM API
- 行前清单 / 预算追踪 / 收藏管理 / 导出 HTML / 导出海报长图 均可用
- 数据存储在 `localStorage`，刷新不丢

### 模式二：后端增强模式

启用后获得完整能力链：

- Scrapling 自适应抓取（Wikipedia / 通用网页）
- DeepSeek Harness 多 Agent 编排（planner → scraper → integrator → validator → optimizer）
- 三级缓存（scrape / LLM 中间结果 / plan）
- 来源追溯（每个景点/美食/住宿卡片底部带"来源"链接）
- Trajectory 调试视图（时间线查看 9 类事件 + 重放）
- 动态优化引擎（基于天气、当地特色、同城热榜的行程调整 + WebSocket 推送）

切换方法：「设置」→「后端增强模式（可选）」→ 运行模式选「后端增强模式」→ 后端地址默认 `http://localhost:8000` → 保存。

---

## CORS Fallback

浏览器直接调用大模型 API 时，部分服务商（如 DeepSeek）不开 CORS，会报：

```
Failed to fetch / CORS error
```

两种解决方案：

### 方案 A：使用项目自带的 CORS 代理（推荐）

```bash
# 项目根目录
python3 proxy.py
# 输出：CORS proxy running on http://localhost:8787 -> https://api.deepseek.com
```

然后在「设置」里把 **API Base URL** 改为 `http://localhost:8787`，API Key 和模型名不变。

代理脚本只做请求转发，不存储任何数据。

### 方案 B：切换到后端增强模式

后端（FastAPI）默认开启 CORS，且 `X-LLM-Config` header 透传 API Key，根本绕过浏览器 CORS 问题。详见[后端启动](#后端启动增强模式)。

### 后端不可达时的降级（AC-11）

后端模式下，如果后端 5 秒内不可达（默认超时 `backend_timeout_ms: 5000`，可在设置中改），前端会**自动降级**为纯前端模式，并在页面顶部显示橙色提示条：

> 后端不可达，已降级为纯前端模式（...）

用户可继续操作，只是失去了爬虫/来源追溯/调试视图能力。

---

## 后端启动（增强模式）

### 一键启动

```bash
bash server/run.sh
```

脚本会自动：
1. 创建 Python venv（若不存在）
2. 安装 `server/requirements.txt` 依赖
3. 首次启动复制 `.env.example` → `.env`，提示填入 `LLM_API_KEY`
4. 启动 uvicorn，监听 `0.0.0.0:8000`

### 手动启动

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 编辑填入 LLM_API_KEY
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 环境变量

参考 [`server/.env.example`](server/.env.example)：

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_BASE_URL` | `https://api.deepseek.com` | 后端兜底（前端 `X-LLM-Config` header 优先级更高） |
| `LLM_API_KEY` | （必填） | 后端兜底 |
| `LLM_MODEL` | `deepseek-chat` | 后端兜底 |
| `DSH_HOME` | `server/.dsh-home` | DSH 工作目录 |
| `DSH_MODE` | `standard` | `standard` / `ptc` / `minimal` |
| `DSH_ENABLED` | `true` | false 时回退到 built-in agent loop |
| `WEATHER_API` | `open-meteo` | 默认免费无 key；可选 `qweather` |
| `QWEATHER_KEY` | （可选） | 和风天气 API key |
| `MONITOR_INTERVAL_SEC` | `3600` | 行程中监测周期 |
| `MONITOR_PRE_TRIP_INTERVAL_SEC` | `1800` | 出发前 24h 内的监测周期 |
| `FRONTEND_ORIGIN` | `http://localhost:5173` | 前端静态服务地址（CORS 白名单） |

### 端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/generate` | 主入口：destination + prefs → plan + sources + warnings + session_id |
| POST | `/scrape` | 手动触发抓取（用户粘贴 URL） |
| GET | `/trajectory/{session_id}` | 拉取思考轨迹事件列表 |
| GET | `/sessions?limit=50` | 列出最近 N 个 session（调试视图选择用） |
| POST | `/trajectory/replay/{session_id}` | 重放历史轨迹到新 session |
| WS | `/ws/{plan_id}` | 行程协同 + 动态优化 diff 推送 |
| POST | `/plan/{plan_id}/monitor/start` | 启动后台监测任务（携带 LLM 配置 + 快照） |
| POST | `/plan/{plan_id}/monitor/stop` | 停止监测 |
| POST | `/plan/{plan_id}/optimize` | 手动触发一次 monitor + optimize |
| GET | `/plan/{plan_id}/versions` | 行程历史版本列表 |
| POST | `/plan/{plan_id}/revert/{version_id}` | 回滚到指定版本 |

### 端到端 Mock 服务器（开发用）

不调真实 LLM，用固定数据走查整个前后端链路：

```bash
cd server
.venv/bin/python mock_e2e.py
# 输出：[mock_e2e] 后端 mock 端到端服务器运行在 http://localhost:8000
```

然后前端切到「后端增强模式」、后端地址 `http://localhost:8000`，提交"济南"即可看到：
- 完整 8 模块手册（济南 3 日齐鲁文化之旅）
- banner 显示「后端增强模式 · session: sess_xxx」「来源 3 条」「校对提示 2 条」
- 景点/美食/住宿卡片底部带"来源"链接
- 「调试」视图自动拉取 9 个事件的时间线（8 类徽章）
- 第二次相同目的地提交会显示「⚡ 缓存命中」badge（mock 也模拟了 plan-level 缓存）

---

## DeepSeek Harness（DSH）说明与风险

### 它是什么

DeepSeek Harness（DSH / Cordis）是一个全插件化的智能体框架，本应用用它做编排：

- 把"链接解析 / 抽取 / 排线 / 优化 / 缓存 / 协作 / 监测"封装为标准插件
- LLM 在框架内通过工具调用与子 Agent 委派"守规矩办事"，避免硬编码 Agent 主循环
- 支持 Python SDK 接入，既省 token 又有强能力，且可自进化（插件热重载）

### 集成位置

后端 [`server/app/dsh_runner.py`](server/app/dsh_runner.py) 实现了 6 个 tg-* 插件：

| 插件 | 职责 | 实现文件 |
|------|------|---------|
| `tg-planner` | 生成抓取任务清单 | `dsh_runner.py::_invoke_planner` |
| `tg-scraper` | Scrapling 抓取 + 来源 URL | `scraper.py` |
| `tg-integrator` | 合并素材为 plan JSON | `dsh_runner.py::_invoke_integrator` |
| `tg-validator` | 事实校对产出 warnings | `dsh_runner.py::_invoke_validator` |
| `tg-optimizer` | 基于监测数据产出 ADD/SWAP/MOVE diff | `dsh_runner.py::_invoke_optimizer + apply_diff` |
| `tg-cache` | 三级缓存（scrape/llm/plan） | `cache.py` |
| `tg-output` | 组装响应 + source_coverage | `schema.py::make_response` |
| `tg-monitor` | 后台监测（天气/同城热榜） | `monitor.py` |

### 风险与降级策略

DSH 是预发布 SDK（`deepseek-harness-sdk==0.1.5rc1`），存在以下风险，对应降级路径都已实现：

| 风险 | 降级路径 | 实现位置 |
|------|----------|---------|
| SDK 安装失败 / import 失败 | 回退到 built-in agent loop（直接用 LLM 客户端编排） | `dsh_runner.dsh_available()` + `_scraper_callable()` |
| 单个插件抛异常 | `traj.append(error)` + 跳过该步骤继续 | `run_pipeline` 各步骤 try/except |
| 整条 pipeline 失败 | 降级为纯 LLM 直接生成 plan | `routes.generate` 兜底 |
| Scrapling 抓取失败 | curl 子进程 → httpx → bs4 三级降级 | `scraper._fetch_with_httpx` |
| LLM 调用超时 / 429 | 不重试，直接抛错由上层降级 | `llm_client.chat_completion` |
| 后端整体不可达 | 前端 5 秒超时降级为纯前端模式 | `llm.js::generateViaBackend` AbortController |

### 自进化接口（v1 简化）

- 插件热重载：通过 `/plugins/reload` 触发（Task 20，未实现）
- Trajectory 重放：`POST /trajectory/replay/{session_id}` 可重放历史轨迹到新 session，用于回归测试
- 版本快照与回滚：每次 plan 变更（initial_generate / user_edit / monitor_optimize）都会写一个版本，`POST /plan/{plan_id}/revert/{version_id}` 可回滚

---

## DSH Web UI 驾驶舱（Task 22 / AC-15）

人机协同驾驶舱，让用户实时看到 Agent 的思考、决定是否采纳动态变更建议。

### 启动

`bash server/run.sh` 会同时启动：

- **FastAPI 主后端**：`http://0.0.0.0:8000`
- **DSH Web UI 驾驶舱**：`http://127.0.0.1:3080`

也可单独启动驾驶舱：

```bash
cd server && .venv/bin/python cockpit.py
# 或带自定义参数
TG_COCKPIT_HOST=127.0.0.1 TG_COCKPIT_PORT=3080 TG_BACKEND_URL=http://127.0.0.1:8000 \
  .venv/bin/python cockpit.py
```

要禁用驾驶舱：`COCKPIT_DISABLE=1 bash server/run.sh`。

### 访问与安全（NFR-12）

- 驾驶舱默认仅监听 `127.0.0.1`，**不暴露公网**；
- 默认 **无需登录**，便于本机调试；
- **远程访问**：需在驾驶舱前置反向代理（如 nginx / Caddy）并叠加 Basic Auth / OAuth 鉴权，不要直接将 3080 端口暴露到公网。

### 三类视图（TR-22.1）

1. **思考轨迹**：复用 Task 19 的 Trajectory 接口，按时间线渲染 system_prompt → planner → scraper → integrator → validator → optimizer → monitor → cockpit 全链路事件
2. **动态变更建议列表**：列出 `tg-optimizer` 待推送的 diff，每条带「采纳 / 驳回 / 编辑」按钮（建议模式）
3. **阈值配置面板**：动态优化总开关、应用模式（建议 / 自动）、元素白名单（景点 / 美食 / 住宿）、监测频率

### 双向同步

- **采纳建议**：调 `POST /plan/{plan_id}/suggestions/{sid}/adopt` → 应用 diff → 保存新版本 → 通过 WebSocket 广播给前端，前端 ≤ 1 秒内同步更新（TR-22.2）
  - 优化（Task 22+）：若建议由 monitor 自动产出且未被编辑过（status='pending' 且 pending_version_id 存在），直接将 monitor 已生成的 pending 版本升级为 adopted（通过 `plan_store.mark_adopted`），避免重复 apply_diff；edited 建议或 manual seed 仍走标准 apply_diff 路径
  - 采纳后会同时广播 `optimize_diff`（应用变更）+ `optimize_suggestion_resolved`（通知前端清理"待审"徽章）
- **驳回建议**：调 `POST /plan/{plan_id}/suggestions/{sid}/reject` → 不应用 diff、不推送 diff；但会推送 `optimize_suggestion_resolved` 通知前端清理"待审"徽章，并把 pending 版本（若有）通过 `plan_store.demote_version` 确保降级
- **编辑建议**：调 `POST /plan/{plan_id}/suggestions/{sid}/edit` → 修改 diff 后保留为 edited 状态，等待用户在驾驶舱再点采纳（TR-22.3）。edited 状态与 pending 一样可在 `active_suggestions` 字段中返回，并支持继续采纳/编辑

### 与前端状态对齐

- 两边共享同一 `plan_id` 与 `version_id`，避免出现"驾驶舱已采纳但前端未更新"或反之
- 驾驶舱采纳产生的 `version_id` 会通过 WebSocket payload 推送，前端在 `optimizer.js` 中接收并应用
- 建议模式（`TG_DYNAMIC_MODE=suggest`）下，monitor 产出的 diff 会暂存到驾驶舱 pending 池，不直接应用；自动模式（`TG_DYNAMIC_MODE=auto`）下，diff 直接推送前端
- 前端 banner 上「🛫 待审 N」徽章会指向 cockpit URL（可在设置中配置 host/port），点击直接跳转驾驶舱；徽章计数通过 WebSocket 实时刷新

### 端点一览（Task 22+）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/plan/{plan_id}/cockpit/state` | 驾驶舱聚合视图：思考轨迹 + `active_suggestions`（pending + edited）+ `pending_suggestions`（兼容字段，仅 pending）+ `all_suggestions` + 阈值配置 |
| POST | `/plan/{plan_id}/cockpit/config` | 修改 `dynamic_enabled` / `dynamic_mode` / `dynamic_whitelist`（进程级环境变量，不持久化） |
| GET | `/plan/{plan_id}/suggestions?status=pending` | 列出建议（支持按 status 过滤） |
| POST | `/plan/{plan_id}/suggestions/seed` | 手动塞 mock diff（演示用） |
| POST | `/plan/{plan_id}/suggestions/{sid}/adopt` | 采纳建议：复用 pending_version_id 或 fresh apply_diff，广播 diff + resolved |
| POST | `/plan/{plan_id}/suggestions/{sid}/reject` | 驳回建议：不应用 diff，demote pending 版本，广播 resolved |
| POST | `/plan/{plan_id}/suggestions/{sid}/edit` | 编辑建议 diff：保留为 edited 状态，等待再采纳 |

### 手动塞 mock 建议（演示用）

无 LLM 时也可演示驾驶舱流程：在驾驶舱「动态变更建议」面板底部有"手动塞 mock diff"输入框，填入 JSON diff 后点"塞入驾驶舱"即可。

### 跑端到端测试

```bash
cd server
.venv/bin/python -m tests.test_cockpit_e2e
```

覆盖 TR-22.1 / TR-22.2 / TR-22.3 + Task 22+ 完善（pending+edited 状态、adopt 复用 pending_version_id、reject 通知、auto/suggest 模式分流、dynamic_enabled=false 跳过）。

---

## Creator 模式工作流

本应用面向两类用户：

### A. 普通用户（默认）

```
打开应用 → 设置填 API Key → 输入目的地 → 生成手册 → 浏览/管理/导出
```

8 大模块：行程概览 / 路线地图 / 每日行程 / 精彩景点 / 住宿推荐 / 美食推荐 / 费用预估 / 出行贴士。

### B. Creator 模式（后端增强 + 调试）

适合想"看 AI 怎么想"的用户、调试者、产品迭代者。

```
1. 启动后端：bash server/run.sh
2. 前端设置切「后端增强模式」→ 保存
3. 生成手册 → 看到 banner 上「后端增强模式 · session: sess_xxx」
4. 切到「调试」标签 → 自动拉取 Trajectory 时间线
   - 看到 9 类事件：system_prompt → tg-planner.start/tasks → tg-scraper.batch
     → tg-integrator.start/done → tg-validator.start/done → tg-output.done
   - 每个事件可展开 payload 看 LLM 实际产出
   - LLM 调用事件附带 token 估算（prompt/completion/total）与耗时
   - 顶部 summary 显示总 token 数与总耗时
   - 可按分组过滤（系统/planner/scraper/集成/校对/优化/监测/缓存/输出）
   - 可搜索事件类型或 payload 内容
5. （可选）点「重放」把当前 session 重放到新 session，做回归测试
   - 重放后自动进入"对比模式"，每个事件旁边显示「✓ 一致」或「⚠ 差异」徽章
   - 可展开查看原 payload 与重放 payload 的差异
6. （可选）下拉框切换历史 session 查看其他轨迹
7. （可选）启动监测：POST /plan/{plan_id}/monitor/start
   - 后台周期跑 tg-monitor → 若有 diff 自动应用 + WebSocket 推送
   - 前端 WebSocket 订阅 /ws/{plan_id} 可实时收到 optimize_diff 推送
8. （可选）手动优化：POST /plan/{plan_id}/optimize 立即跑一次 monitor + optimize
9. （可选）回滚：POST /plan/{plan_id}/revert/{version_id} 回到任意历史版本
```

### C. 开发者

- Mock 走查：`python server/mock_e2e.py` + 前端切后端模式，可看到完整链路（不调 LLM）
- 单元测试：`cd server && .venv/bin/python -m pytest tests/`
- Trajectory 自检：`.venv/bin/python -c "from app import dsh_runner; ..."` 跑 apply_diff 等纯函数

---

## 项目结构

```
workspace/
├── app/                          # 前端（纯 HTML/CSS/原生 JS 模块）
│   ├── index.html                # 入口，导航 + 7 个视图容器
│   ├── styles.css                # Warm Editorial 调色板 + 全部样式
│   └── js/
│       ├── main.js               # 入口，导航切换与视图调度
│       ├── config.js             # API 设置持久化 + 设置面板（含后端模式）
│       ├── schema.js             # 旅游方案数据 schema 与校验
│       ├── prompt.js             # 集中管理 LLM 提示词模板
│       ├── llm.js                # LLM 客户端（前端直连 + 后端模式 + 5s 降级 + trajectory 拉取）
│       ├── generate.js           # 生成表单处理与当前方案状态管理
│       ├── renderer.js           # 手册渲染（8 模块 + banner + 来源链接 + 校对提示）
│       ├── images.js             # Wikimedia Commons 图片获取
│       ├── debug.js              # Trajectory 调试视图（时间线 + 重放）
│       ├── tools/
│       │   ├── checklist.js      # 行前打包清单
│       │   ├── budget.js         # 预算追踪
│       │   ├── favorites.js      # 收藏管理
│       │   └── editor.js         # 行程编辑器
│       └── export/
│           ├── html.js           # 导出静态 HTML
│           └── image.js          # 导出海报长图 PNG
├── server/                       # 后端（FastAPI + DSH + Scrapling）
│   ├── app/
│   │   ├── main.py               # FastAPI 入口（lifespan + CORS）
│   │   ├── routes.py             # HTTP + WebSocket 路由
│   │   ├── dsh_runner.py         # DSH 编排：planner→scraper→integrator→validator→optimizer→output
│   │   ├── scraper.py            # Scrapling 抓取层（curl/httpx/bs4 三级降级）
│   │   ├── llm_client.py         # OpenAI 兼容 LLM 客户端
│   │   ├── prompts.py            # 系统提示词 + 各插件提示词
│   │   ├── schema.py             # plan schema 校验 + make_response + source_coverage
│   │   ├── cache.py              # 三级缓存（scrape/llm/plan）SQLite KV
│   │   ├── plan_store.py         # plan + 版本快照持久化
│   │   ├── traj.py               # Trajectory 事件存储
│   │   ├── monitor.py            # 后台监测 + optimizer 驱动 + WebSocket 推送
│   │   └── seasonal.py           # 季节性数据
│   ├── plugins/tg-bundle/        # DSH 插件包
│   ├── tests/test_scraper.py     # 抓取层测试
│   ├── mock_e2e.py               # 端到端 Mock 服务器
│   ├── requirements.txt
│   ├── .env.example
│   └── run.sh                    # 一键启动脚本
├── proxy.py                      # CORS 代理（纯前端模式 fallback）
├── .trae/specs/travel-guide-app/
│   ├── spec.md                   # 产品需求文档
│   └── tasks.md                  # 实现计划（Task 1-22）
└── README.md                     # 本文件
```

---

## 功能矩阵

| 功能 | 纯前端模式 | 后端增强模式 | 验收 AC |
|------|:---:|:---:|:---|
| 8 大模块手册渲染 | ✓ | ✓ | AC-2 |
| 行前清单 / 预算 / 收藏 | ✓ | ✓ | AC-3 |
| 导出 HTML / 海报长图 | ✓ | ✓ | AC-4 |
| LLM API 配置 + 测试 | ✓ | ✓ | AC-1 |
| Scrapling 自适应抓取 | ✗ | ✓ | AC-9 |
| 三级缓存（含缓存命中 badge） | ✗ | ✓ | AC-9 |
| 来源追溯（卡片底部链接） | ✗ | ✓ | AC-10 |
| 校对提示 callout | ✗ | ✓ | AC-10 |
| 后端不可达 5s 降级 | n/a | ✓ | AC-11 |
| Trajectory 调试视图 + 重放 | ✗ | ✓ | AC-12 |
| 插件热重载（自进化） | ✗ | △（未实现） | AC-13 |
| 动态优化引擎（天气/热榜） | ✗ | ✓ | AC-14 |
| DSH Web UI 驾驶舱 | ✗ | ✓ | AC-15 |
| 多人实时协作编辑 | ✗ | △（WebSocket 已通） | AC-14 |

✓ 已实现 / △ 部分实现 / ✗ 不可用

---

## 常见问题

### Q: 浏览器报 "Failed to fetch" 或 CORS 错误？

A: 见 [CORS Fallback](#cors-fallback)。最简单是 `python3 proxy.py` 然后改 Base URL 为 `http://localhost:8787`。

### Q: 后端模式打开后，提交"生成"卡在 spinner？

A: 检查后端是否启动：`curl http://localhost:8000/health` 应返回 `{"status":"ok"}`。未启动则 `bash server/run.sh`。后端不可达 5 秒后前端会自动降级并显示提示条。

### Q: 生成的方案缺字段或 LLM 报错？

A: 前端 schema.js 会校验 plan JSON，缺字段会重试一次（追加修正 prompt）。后端模式有 `tg-validator` 做事实校对，warnings 会显示在 banner 的"校对提示"折叠区。

### Q: API Key 安全吗？

A: 纯前端模式：Key 只存在浏览器 `localStorage`，请求直接发到 LLM 服务商。后端模式：Key 通过 `X-LLM-Config` header 透传给本地后端（仅本次请求内存中），后端不持久化。`proxy.py` 同样不存储。

### Q: 缓存命中是什么意思？

A: 后端有三级缓存。相同 (destination + prefs) 第二次提交会直接命中 plan-level 缓存，跳过抓取和 LLM 调用，响应 < 10 秒（通常 < 1 秒）。banner 上会显示「⚡ 缓存命中」badge。

### Q: 动态优化引擎怎么用？

A: 生成方案后：
1. `POST /plan/{plan_id}/monitor/start` 启动后台监测（需带 `X-LLM-Config` header）
2. 后台周期跑 `tg-monitor`（天气 + 同城热榜）→ 若有 diff 自动调 `tg-optimizer` 应用 → WebSocket 推送
3. 前端 WebSocket 订阅 `ws://localhost:8000/ws/{plan_id}` 接收 `optimize_diff` 推送
4. 也可 `POST /plan/{plan_id}/optimize` 手动触发一次
5. 不满意可 `POST /plan/{plan_id}/revert/{version_id}` 回滚

### Q: DSH SDK 安装失败怎么办？

A: `deepseek-harness-sdk==0.1.5rc1` 是预发布版，安装时可能需要 `pip install --pre`。安装失败时后端会自动回退到 built-in agent loop（直接用 LLM 客户端编排），核心功能不受影响。`DSH_ENABLED=false` 可显式禁用。

---

## 许可证

私有项目，未发布。

## 相关文档

- [产品需求文档 (spec.md)](.trae/specs/travel-guide-app/spec.md)
- [实现计划 (tasks.md)](.trae/specs/travel-guide-app/tasks.md)

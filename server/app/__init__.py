"""AI 旅行手册后端 · 应用包

模块布局：
- main.py       : FastAPI 入口与 lifespan
- routes.py     : HTTP / WebSocket 路由
- dsh_runner.py : DeepSeek Harness 启动与请求封装（薄壳，便于跟进 SDK 变更）
- llm_client.py : OpenAI 兼容 LLM 调用（DSH 不可用时的回退引擎）
- schema.py     : 与前端 schema.js 共享的 plan 字段与校验
- prompts.py    : 集中管理提示词模板
- traj.py       : Trajectory 日志（append-only JSONL）
- plan_store.py : plan 版本快照与来源记录
- monitor.py    : tg-monitor 等价实现（天气/同城热榜监测）
- seasonal.py   : 当地特色素材库（seasonal.yaml 加载）
"""

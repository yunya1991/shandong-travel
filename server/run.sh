#!/usr/bin/env bash
# AI 旅行手册后端启动脚本
# 用法：bash server/run.sh
set -euo pipefail
cd "$(dirname "$0")"

PY=${PYTHON:-python3}
VENV=${VENV:-.venv}

# 1) 创建 venv（若不存在）
if [ ! -d "$VENV" ]; then
  echo "[setup] creating venv at $VENV"
  "$PY" -m venv "$VENV"
fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"

# 2) 安装依赖（首次或 requirements.txt 变更时）
if [ ! -f .deps_installed ] || [ requirements.txt -nt .deps_installed ]; then
  echo "[setup] installing dependencies"
  pip install --upgrade pip >/dev/null
  pip install -r requirements.txt
  touch .deps_installed
fi

# 3) 复制 .env.example → .env（首次）
if [ ! -f .env ]; then
  cp .env.example .env
  echo "[setup] copied .env.example -> .env (请编辑后填入 LLM_API_KEY)"
fi

# 4) 启动 uvicorn
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
echo "[run] uvicorn app.main:app --host $HOST --port $PORT"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload

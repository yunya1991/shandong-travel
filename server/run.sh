#!/usr/bin/env bash
# AI 旅行手册后端启动脚本（FastAPI + DSH Web UI 驾驶舱）
# 用法：bash server/run.sh
#
# 默认启动两个服务（同 supervisor 下并行）：
#   - FastAPI 主后端：       http://0.0.0.0:8000
#   - DSH Web UI 驾驶舱：   http://127.0.0.1:3080（Task 22 / AC-15 / NFR-12）
#
# 仅本机访问驾驶舱；远程访问需叠加反代 + 鉴权（README 注明）。
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

# 4) 启动驾驶舱（后台，端口 3080）
HOST=${HOST:-0.0.0.0}
PORT=${PORT:-8000}
COCKPIT_HOST=${COCKPIT_HOST:-127.0.0.1}
COCKPIT_PORT=${COCKPIT_PORT:-3080}
COCKPIT_DISABLE=${COCKPIT_DISABLE:-0}

cleanup() {
  echo "[run] stopping cockpit..."
  if [ -n "${COCKPIT_PID:-}" ] && kill -0 "$COCKPIT_PID" 2>/dev/null; then
    kill "$COCKPIT_PID" || true
  fi
  exit 0
}
trap cleanup INT TERM

if [ "$COCKPIT_DISABLE" != "1" ]; then
  echo "[run] cockpit: TG_COCKPIT_HOST=$COCKPIT_HOST TG_COCKPIT_PORT=$COCKPIT_PORT"
  TG_COCKPIT_HOST="$COCKPIT_HOST" TG_COCKPIT_PORT="$COCKPIT_PORT" \
    python cockpit.py &
  COCKPIT_PID=$!
  echo "[run] cockpit pid=$COCKPIT_PID, visit http://$COCKPIT_HOST:$COCKPIT_PORT"
fi

# 5) 启动 uvicorn（前台）
echo "[run] uvicorn app.main:app --host $HOST --port $PORT"
exec uvicorn app.main:app --host "$HOST" --port "$PORT" --reload

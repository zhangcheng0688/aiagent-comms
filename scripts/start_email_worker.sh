#!/usr/bin/env bash
# 启动 C 方案 IMAP/SMTP 邮件 worker
# 用法：
#   ./scripts/start_email_worker.sh                # 默认配置启动
#   APPROVED_SENDERS=foo@x.com,bar@y.com ./scripts/start_email_worker.sh
#   IMAP_USER=ai@qq.com IMAP_PASSWORD=xxx SMTP_PASSWORD=xxx ./scripts/start_email_worker.sh
set -euo pipefail

# 项目根
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

# 加载 .env（如有）— 用 Python 解析避免空格/中文被 shell 误执行
if [[ -f .env ]]; then
  while IFS='=' read -r k v; do
    [[ -z "$k" || "$k" =~ ^# ]] && continue
    # strip optional surrounding quotes
    v="${v%\"}"; v="${v#\"}"
    v="${v%\'}"; v="${v#\'}"
    export "$k=$v"
  done < .env
fi

# 默认值
: "${IMAP_HOST:=imap.qq.com}"
: "${IMAP_PORT:=993}"
: "${SMTP_HOST:=smtp.qq.com}"
: "${SMTP_PORT:=465}"
: "${SMTP_FROM_NAME:=AI 外贸代办}"
: "${POLL_INTERVAL:=30}"
: "${LOG_FILE:=data/email_worker.log}"
: "${PID_FILE:=data/email_worker.pid}"

mkdir -p data "$(dirname "$LOG_FILE")"

# 已运行？
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "[email_worker] already running, pid=$(cat "$PID_FILE")"
  exit 0
fi

echo "[email_worker] starting with:"
echo "  IMAP: $IMAP_USER@$IMAP_HOST:$IMAP_PORT"
echo "  SMTP: $SMTP_USER@$SMTP_HOST:$SMTP_PORT"
echo "  poll: ${POLL_INTERVAL}s"
echo "  approved: ${APPROVED_SENDERS:-<EMPTY — demo only>}"
echo "  log: $LOG_FILE"

# 启动
nohup ./.venv/bin/python3 -m backend.email_worker >> "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"
echo "[email_worker] started, pid=$(cat "$PID_FILE")"
echo "[email_worker] tail -f $LOG_FILE"

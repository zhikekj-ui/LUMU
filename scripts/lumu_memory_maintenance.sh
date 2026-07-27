#!/usr/bin/env bash
# LUMU 记忆智能维护：按真实时间间隔触发「归纳 + 主动遗忘」
# 由 systemd timer 调用，独立于主对话进程，避免进程内常驻后台循环。
set -u
BASE="http://localhost:8000"
LOG="/opt/agent-framework/logs/memory_maintenance.log"
mkdir -p "$(dirname "$LOG")"
TS="$(date '+%Y-%m-%d %H:%M:%S')"
echo "[$TS] === memory maintenance start ===" >> "$LOG"

# 1) 归纳：合并相似记忆（每轮最多 3 对）
CODE=$(curl -s -o /tmp/mm_consolidate.json -w "%{http_code}" -X POST "$BASE/api/memory/consolidate" --max-time 180 || echo "000")
echo "[$TS] consolidate http=$CODE resp=$(cat /tmp/mm_consolidate.json 2>/dev/null)" >> "$LOG"

# 2) 主动遗忘：清理低分 / 过期记忆（cap=5）
CODE2=$(curl -s -o /tmp/mm_forget.json -w "%{http_code}" -X POST "$BASE/api/memory/auto-forget?cap=5" --max-time 180 || echo "000")
echo "[$TS] auto-forget http=$CODE2 resp=$(cat /tmp/mm_forget.json 2>/dev/null)" >> "$LOG"

echo "[$TS] === memory maintenance done ===" >> "$LOG"

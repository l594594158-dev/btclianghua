#!/bin/bash
# 每分钟被cron调用，确保watchdog在运行
# watchdog负责检查HFT主程序
WD_SCRIPT="/home/ubuntu/gate_bot/watchdog.py"
WD_PIDFILE="/tmp/hft_watchdog.pid"

# 检查watchdog是否存活
if [ -f "$WD_PIDFILE" ]; then
    PID=$(cat "$WD_PIDFILE")
    if kill -0 "$PID" 2>/dev/null; then
        exit 0  # watchdog已在运行
    fi
fi

# watchdog未运行，启动它
cd /home/ubuntu/gate_bot
nohup python3 watchdog.py > /dev/null 2>&1 &
echo $! > "$WD_PIDFILE"

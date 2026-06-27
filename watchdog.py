#!/usr/bin/env python3
"""
Gate.io HFT Bot - 守护进程
每分钟检查：
  1. 主进程(main.py)是否在运行
  2. 日志是否有最近的活动（有信号产生）
  3. 掉线自动拉起
"""
import os
import sys
import time
import json
import subprocess
import requests
from datetime import datetime
from config import WATCHDOG_LOOP, WATCHDOG_STALE_SEC, LOG_FILE

PROC_NAME = 'hft_main'
PID_FILE = '/tmp/hft_main.pid'
SCRIPT = os.path.join(os.path.dirname(__file__), 'main.py')
MY_LOG = os.path.join(os.path.dirname(__file__), 'watchdog.log')

def log(msg):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(MY_LOG, 'a') as f:
        f.write(line + '\n')

def read_pid():
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except:
        return None

def write_pid(pid):
    with open(PID_FILE, 'w') as f:
        f.write(str(pid))

def is_process_alive(pid):
    """检查进程是否存活"""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False

def find_main_process():
    """查找main.py进程"""
    try:
        result = subprocess.run(
            ['pgrep', '-f', 'python3.*main.py'],
            capture_output=True, text=True, timeout=5
        )
        pids = [int(p) for p in result.stdout.strip().split() if p]
        # 排除自己（watchdog里不应该有main.py）
        my_pid = os.getpid()
        return [p for p in pids if p != my_pid]
    except:
        return []

def check_logs_recent():
    """检查主日志最近是否有活动"""
    if not LOG_FILE or not os.path.exists(LOG_FILE):
        return True  # 没有日志文件默认通过
    try:
        mtime = os.path.getmtime(LOG_FILE)
        age_sec = time.time() - mtime
        if age_sec > WATCHDOG_STALE_SEC:
            log(f"[WARN] 日志陈旧 {age_sec:.0f}s 前修改（> {WATCHDOG_STALE_SEC}s）")
            return False
        # 再检查最后几行是否有信号输出
        if os.path.getsize(LOG_FILE) < 20:
            return True  # 文件太小，启动初期
        return True
    except:
        return True

def try_api():
    """快速检查Gate API是否通"""
    try:
        import ccxt
        ex = ccxt.gate({'options': {'defaultType': 'swap'}})
        ticker = ex.fetch_ticker('BTC/USDT:USDT')
        if ticker and ticker.get('last'):
            return True
        return False
    except:
        return False

def start_bot():
    """启动主程序"""
    log("[ACTION] 启动 HFT Bot...")
    try:
        # 用nohup后台启动，输出到gate_bot.log
        with open(LOG_FILE, 'a') as log_f:
            proc = subprocess.Popen(
                ['python3', SCRIPT],
                stdout=log_f,
                stderr=subprocess.STDOUT,
                preexec_fn=os.setsid,
                env={**os.environ, 'PYTHONUNBUFFERED': '1'}
            )
        pid = proc.pid
        write_pid(pid)
        log(f"[OK] 已启动, PID={pid}")
        return pid
    except Exception as e:
        log(f"[FAILED] 启动失败: {e}")
        return None

def check_and_restart():
    """检查状态，决定是否需要重启"""
    # 1. 检查进程
    pids = find_main_process()
    if pids:
        log(f"[OK] 进程运行中 PID={pids}")
    else:
        log("[WARN] 主进程未找到")
        # 不是崩溃，可能是手动停止？检查PID文件
        pid = read_pid()
        if pid and is_process_alive(pid):
            log(f"[OK] PID文件中的{PID}存活")
        else:
            log("[STALE] 主进程已消失，准备重启")
            start_bot()
            return
    
    # 2. 日志活动检查
    check_logs_recent()
    
    # 3. 检查API是否正常（可选）
    if not try_api():
        log("[WARN] API检查失败，但可能只是临时问题")

def main():
    log("=" * 50)
    log(f"Watchdog 启动 (PID={os.getpid()})")
    log(f"检查间隔: {WATCHDOG_LOOP}s | 日志超时: {WATCHDOG_STALE_SEC}s")
    log("=" * 50)
    
    # 启动时检查一次
    check_and_restart()
    
    while True:
        time.sleep(WATCHDOG_LOOP)
        check_and_restart()

if __name__ == '__main__':
    main()

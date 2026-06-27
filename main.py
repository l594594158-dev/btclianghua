"""Gate.io HFT Bot - 双任务架构"""
import ccxt
import json, os, time
import pandas as pd
import numpy as np
from datetime import datetime
from signal_engine import calculate_signals
from config import *

exchange = ccxt.gate({
    'apiKey': API_KEY,
    'secret': SECRET,
    'options': {'defaultType': 'swap'},
})

# ---- 全局状态 ----
bars_cache = []
last_bar_time = 0
pending_entry = None    # 开仓信息（信号侧记录）
position_tp_sl = None   # 止盈止损记录（仓位管理侧记录）

def load_state():
    global pending_entry, position_tp_sl
    try:
        with open(STATE_FILE) as f:
            s = json.load(f)
            pending_entry = s.get('pending_entry')
            position_tp_sl = s.get('position_tp_sl')
    except:
        pass

def save_state():
    s = {
        'pending_entry': pending_entry,
        'position_tp_sl': position_tp_sl,
    }
    with open(STATE_FILE, 'w') as f:
        json.dump(s, f)

def log_trade(entry_time, exit_time, side, entry_price, exit_price, pnl_pct, reason):
    file_exists = os.path.exists(TRADE_LOG)
    df = pd.DataFrame([{
        'et': entry_time, 'xt': exit_time, 'd': side,
        'e': round(entry_price, 2), 'x': round(exit_price, 2),
        'pnl': round(pnl_pct, 4), 'tp': reason
    }])
    df.to_csv(TRADE_LOG, mode='a', header=not file_exists, index=False)

# ========== 任务1：策略信号 ==========

def task1_init_cache():
    global bars_cache
    print(f"[任务1] 下载 {CACHE_SIZE} 根历史K线预热...")
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=CACHE_SIZE)
        if len(ohlcv) >= 20:
            bars_cache = ohlcv
            print(f"  已加载 {len(ohlcv)} 根 ✅")
            return True
        print(f"  仅获取 {len(ohlcv)} 根 ❌")
        return False
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        return False

def task1_check_position():
    """检查交易所是否有同向持仓"""
    balance = exchange.fetch_balance({'settle': 'USDT'})
    if 'info' in balance:
        info = balance['info']
        for pos in info if isinstance(info, list) else [info]:
            if isinstance(pos, dict):
                contract = pos.get('contract') or pos.get('symbol') or ''
                size = float(pos.get('size', 0) or 0)
                side = pos.get('side') or ''
                if contract and SYMBOL.replace('/', '_').replace(':', '_') in contract:
                    if size != 0:
                        return side
    try:
        pos_list = exchange.fetch_positions([SYMBOL])
        for p in pos_list:
            size = float(p.get('contracts', 0) or p.get('size', 0))
            if size != 0:
                side = p.get('side')
                if side == 'long' or side == 'short':
                    return side
    except:
        pass
    return None

def task1_signal():
    """有新K线 → 计算信号 → 开仓"""
    global bars_cache, pending_entry, last_bar_time
    
    current_pos = task1_check_position()
    if current_pos:
        print(f"  [仓位存在: {current_pos}]", end='')
        return
    
    result = calculate_signals(bars_cache)
    if result['signal'] == 0:
        d = result['detail']
        if d.get('r5') is not None:
            print(f" (多{result['long_score']:.2f}/空{result['short_score']:.2f})", end='')
        return
    
    o = bars_cache[-1][1]
    h = bars_cache[-1][2]
    l = bars_cache[-1][3]
    
    direction = 'long' if result['signal'] == 1 else 'short'
    trig = o * (1 - TRIGGER) if direction == 'long' else o * (1 + TRIGGER)
    
    filled = False
    if direction == 'long':
        if l <= trig:
            filled = True; entry_price = trig
        elif l <= o:
            filled = True; entry_price = o
    else:
        if h >= trig:
            filled = True; entry_price = trig
        elif h >= o:
            filled = True; entry_price = o
    
    if not filled:
        d = result['detail']
        print(f" 📊信号{'多' if result['signal']==1 else '空'} (多{result['long_score']:.2f}/空{result['short_score']:.2f}) 限价${trig:.0f}未扫到", end='')
        return
    
    tp = entry_price * (1 + TP) if direction == 'long' else entry_price * (1 - TP)
    sl = entry_price * (1 - SL) if direction == 'long' else entry_price * (1 + SL)
    sl = round(sl, 1)
    tp = round(tp, 1)
    entry_price = round(entry_price, 1)
    
    side_order = 'buy' if direction == 'long' else 'sell'
    try:
        order = exchange.create_limit_order(SYMBOL, side_order, AMOUNT, entry_price)
        order_id = order.get('id', '')
        print(f" 📊信号开{direction[0].upper()} @${entry_price:.0f} tp${tp:.0f} sl${sl:.0f} 订单:{order_id[:12]}...", end='')
        
        pending_entry = {
            'side': direction,
            'entry': entry_price,
            'tp': tp,
            'sl': sl,
            'entry_time': bars_cache[-1][0],
            'order_id': order_id,
        }
        save_state()
    except Exception as e:
        print(f" ❌ 开仓失败: {e}", end='')

def task1_poll():
    global bars_cache, last_bar_time
    try:
        ohlcv = exchange.fetch_ohlcv(SYMBOL, TIMEFRAME, limit=1)
        latest = ohlcv[-1]
        if latest[0] != last_bar_time:
            bars_cache.append(latest)
            if len(bars_cache) > CACHE_SIZE:
                bars_cache = bars_cache[-CACHE_SIZE:]
            last_bar_time = latest[0]
            
            t = datetime.fromtimestamp(latest[0] / 1000)
            print(f"\n[{t.strftime('%H:%M')}] O:{latest[1]:.0f} H:{latest[2]:.0f} L:{latest[3]:.0f} C:{latest[4]:.0f}", end='')
            task1_signal()
    except Exception as e:
        print(f"  [poll err] {e}", end='')

# ========== 任务2：仓位管理 ==========

def task2_fetch_positions():
    """获取所有活跃持仓，返回 [(side, entry_price, size), ...]"""
    result = []
    try:
        positions = exchange.fetch_positions([SYMBOL])
        for p in positions:
            sz = float(p.get('contracts', 0))
            if sz != 0:
                result.append((p.get('side'), float(p.get('entryPrice', 0)), abs(sz)))
    except:
        pass
    return result



def task2_manage_one(side, entry_price, size, state_key):
    """管理单个仓位的止盈止损
       state_key: 'long' 或 'short'，对应state中的key
       返回该仓位的 (tp_id, sl_id)
    """
    if side == 'long':
        tp_price = round(entry_price * (1 + TP), 1)
        sl_price = round(entry_price * (1 - SL), 1)
        close_side = 'sell'
    else:
        tp_price = round(entry_price * (1 - TP), 1)
        sl_price = round(entry_price * (1 + SL), 1)
        close_side = 'buy'
    
    # 查当前已有订单
    tp_id, sl_id = task2_check_orders_side(close_side)
    
    label = '多' if side == 'long' else '空'
    
    # 止盈
    if tp_id:
        print(f" [止盈{label}已就位 @${tp_price:.0f}]", end='')
    else:
        try:
            o = exchange.create_limit_order(
                SYMBOL, close_side, size, tp_price,
                params={'reduceOnly': True}
            )
            tid = o.get('id')
            if tid:
                tp_id = tid
                print(f" [止盈{label}限价{tid[-8:]} @${tp_price:.0f}]", end='')
        except Exception as e:
            print(f" [止盈{label}失败:{str(e)[:40]}]", end='')
    
    # 止损
    if sl_id:
        print(f" [止损{label}已就位 @${sl_price:.0f}]", end='')
    else:
        try:
            o = exchange.create_stop_loss_order(
                SYMBOL, 'market', close_side, size,
                stopLossPrice=sl_price,
                params={'reduceOnly': True}
            )
            sid = o.get('id')
            if sid:
                sl_id = sid
                print(f" [止损{label}条件{sid[-8:]} @${sl_price:.0f}]", end='')
        except Exception as e:
            print(f" [止损{label}失败:{str(e)[:40]}]", end='')
    
    return tp_id, sl_id


def task2_cleanup_stale_orders():
    """清理所有残留的reduceOnly订单（旧方向的废单）"""
    try:
        ords = exchange.fetch_open_orders(SYMBOL)
        for o in ords:
            info = o.get('info', {})
            if info.get('is_reduce_only') == True and o.get('type') == 'limit':
                exchange.cancel_order(o['id'], SYMBOL)
                print(f" [清止盈{o['id'][-8:]}]", end='')
    except:
        pass
    try:
        stops = exchange.fetch_open_orders(SYMBOL, params={'stop': True})
        for o in stops:
            exchange.cancel_order(o['id'], SYMBOL, params={'stop': True})
            print(f" [清止损{o['id'][-8:]}]", end='')
    except:
        pass


def task2_check_orders_side(close_side):
    """按平仓方向检查已挂订单，返回 (tp_id, sl_id)
       close_side='sell' → 平多 / 'buy' → 平空
    """
    tp_id = None
    sl_id = None
    try:
        orders = exchange.fetch_open_orders(SYMBOL)
        for o in orders:
            info = o.get('info', {})
            if o.get('type') == 'limit' and info.get('is_reduce_only') == True and o['side'] == close_side:
                tp_id = o['id']
                break
        stops = exchange.fetch_open_orders(SYMBOL, params={'stop': True})
        for o in stops:
            i = o.get('info', {}).get('initial', {})
            if i.get('is_reduce_only') == True and o['side'] == close_side:
                sl_id = o['id']
                break
    except:
        pass
    return tp_id, sl_id


def task2_manage():
    """仓位管理：遍历所有持仓，为每个方向挂对应的止盈止损
       每10秒调用一次
    """
    global position_tp_sl, pending_entry
    
    all_pos = task2_fetch_positions()
    
    # 无持仓 → 清理所有残留订单 + 清state
    if not all_pos:
        if position_tp_sl:
            print(f" ⚠️仓已平", end='')
            task2_cleanup_stale_orders()
            position_tp_sl = None
            pending_entry = None
            save_state()
        return
    
    # 如果有持仓但state有旧方向记录，清理那些对应方向的废单
    active_sides = set(p[0] for p in all_pos)
    if position_tp_sl:
        stale_sides = set(position_tp_sl.keys()) - active_sides
        if stale_sides:
            print(f" [清理旧方向:{','.join(stale_sides)}]", end='')
            # 对于过期方向，先撤掉交易所的旧订单
            for stale_side in stale_sides:
                close_side = 'sell' if stale_side == 'long' else 'buy'
                try:
                    ords = exchange.fetch_open_orders(SYMBOL)
                    for o in ords:
                        info = o.get('info', {})
                        if info.get('is_reduce_only') == True and o.get('type') == 'limit' and o['side'] == close_side:
                            exchange.cancel_order(o['id'], SYMBOL)
                            print(f" [撤旧止盈{o['id'][-8:]}]", end='')
                except:
                    pass
                try:
                    stops = exchange.fetch_open_orders(SYMBOL, params={'stop': True})
                    for o in stops:
                        if o['side'] == close_side:
                            exchange.cancel_order(o['id'], SYMBOL, params={'stop': True})
                            print(f" [撤旧止损{o['id'][-8:]}]", end='')
                except:
                    pass
    
    new_state = {}
    
    for side, entry, size in all_pos:
        print(f" [{side[0].upper()}@{entry:.0f}]", end='')
        tp_id, sl_id = task2_manage_one(side, entry, size, side)
        new_state[side] = {
            'entry': entry,
            'tp': round(entry * (1 + TP) if side == 'long' else entry * (1 - TP), 1),
            'sl': round(entry * (1 - SL) if side == 'long' else entry * (1 + SL), 1),
            'tp_id': tp_id,
            'sl_id': sl_id,
        }
    
    position_tp_sl = new_state
    save_state()


# ========== 主循环 ==========

def main():
    global bars_cache, last_bar_time
    
    print("=" * 55)
    print(f"Gate.io HFT Bot - {datetime.now()}")
    print(f"参数: TP={TP*100:.2f}% SL={SL*100:.2f}% TH={THRESHOLD}")
    print(f"限价滑点: {TRIGGER*100:.2f}%")
    print("=" * 55)
    
    load_state()
    print("[启动] 检查持仓和已有订单...")
    task2_manage()
    print("  ✅")
    
    if not task1_init_cache():
        print("预热失败，退出")
        return
    
    last_bar_time = bars_cache[-1][0]
    print(f"\n最后K线: {datetime.fromtimestamp(last_bar_time/1000).strftime('%H:%M')}")
    print(f"运行中...\n")
    
    manage_counter = 0
    while True:
        try:
            task1_poll()
            
            manage_counter += 1
            if manage_counter >= 10:
                task2_manage()
                manage_counter = 0
            
            time.sleep(POLL_INTERVAL)
        except Exception as e:
            print(f"\n  ❌ 主循环错误: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()

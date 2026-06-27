"""信号引擎 - 完全复刻回测 final_monthly.py 算法"""
import numpy as np

def wilder_rsi_ema(closes, period):
    """
    Wilder EMA RSI - 完全复刻回测的 pd.Series.ewm(alpha=1/p, adjust=False)
    传入全部缓存数据以保证EMA充分收敛
    """
    if len(closes) < period + 1:
        return np.nan
    diffs = np.diff(closes)
    gains = np.maximum(diffs, 0)
    losses = -np.minimum(diffs, 0)
    # Wilder EMA
    avg_gain = gains[0]
    avg_loss = losses[0]
    for g, l in zip(gains[1:], losses[1:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)

def calculate_signals(bars):
    """
    输入: bars = [[t,o,h,l,c,v], ...]
    返回: {'long_score':float, 'short_score':float, 'signal':int}
    
    完全复刻回测 final_monthly.py 的信号逻辑
    """
    if len(bars) < 20:
        return {'long_score': 0, 'short_score': 0, 'signal': 0, 'detail': {}}
    
    closes = np.array([b[4] for b in bars], dtype=float)
    highs = np.array([b[2] for b in bars], dtype=float)
    lows = np.array([b[3] for b in bars], dtype=float)
    current = closes[-1]
    
    # ---- RSI (Wilder EMA) ----
    r5_val = wilder_rsi_ema(closes, 5) if len(closes) >= 6 else 50
    r7_val = wilder_rsi_ema(closes, 7) if len(closes) >= 8 else 50
    r14_val = wilder_rsi_ema(closes, 14) if len(closes) >= 15 else 50
    
    # ---- 布林带 (SMA 20, ddof=0) ----
    sma20 = float(np.mean(closes[-20:]))
    std20 = float(np.std(closes[-20:], ddof=0))
    bl = sma20 - 2 * std20  # 下轨
    bu = sma20 + 2 * std20  # 上轨
    
    # ---- 连涨连跌天数（复刻回测正向累计，从历史往当前扫） ----
    down = 0; up = 0
    for j in range(len(closes) - 1):
        if closes[j+1] < closes[j]:
            down += 1; up = 0
        elif closes[j+1] > closes[j]:
            up += 1; down = 0
        else:
            down = down  # 同价保持
            up = up
    # 取最后的值即当前最新的down/up
    
    # ---- 波动率（复刻回测的SMA 20 ret） ----
    ret = np.abs(np.diff(closes[-21:]) / (np.abs(closes[-21:-1]) + 0.01))
    vola = float(np.mean(ret[-20:])) if len(ret) >= 20 else 0
    quiet = vola < 0.003
    
    # ---- 多头评分 ----
    long_score = 0.0
    if not np.isnan(r5_val) and r5_val < 35: long_score += 0.20
    if not np.isnan(r7_val) and r7_val < 30: long_score += 0.18
    if not np.isnan(r14_val) and r14_val < 30: long_score += 0.15
    if current < bl * 1.001: long_score += 0.18
    if down >= 3: long_score += 0.12
    if down >= 5: long_score += 0.08
    if vola < 0.002: long_score += 0.06
    if not quiet: long_score -= 0.10
    
    # ---- 空头评分 ----
    short_score = 0.0
    if not np.isnan(r5_val) and r5_val > 65: short_score += 0.20
    if not np.isnan(r7_val) and r7_val > 70: short_score += 0.18
    if not np.isnan(r14_val) and r14_val > 70: short_score += 0.15
    if current > bu * 0.999: short_score += 0.18
    if up >= 3: short_score += 0.12
    if up >= 5: short_score += 0.08
    if vola < 0.002: short_score += 0.06
    if not quiet: short_score -= 0.10
    
    # ---- 最终信号 ----
    signal = 0
    if long_score >= 0.5 and long_score >= short_score:
        signal = 1
    elif short_score >= 0.5 and short_score > long_score:
        signal = -1
    
    return {
        'long_score': round(long_score, 2),
        'short_score': round(short_score, 2),
        'signal': signal,
        'detail': {
            'r5': round(r5_val, 1) if not np.isnan(r5_val) else None,
            'r7': round(r7_val, 1) if not np.isnan(r7_val) else None,
            'r14': round(r14_val, 1) if not np.isnan(r14_val) else None,
            'bl': round(bl, 2),
            'bu': round(bu, 2),
            'vola': round(vola * 100, 4),
            'down': down,
            'up': up,
        }
    }

# Gate.io 永续合约 HFT Bot 配置
TP = 0.0032         # 0.32%
SL = 0.001           # 0.1%
THRESHOLD = 0.5      # 信号阈值
AMOUNT = 20          # 开仓量（张数，Gate永续 contractSize=0.0001 BTC/张，20张=0.002 BTC）
SYMBOL = 'BTC/USDT:USDT'
TIMEFRAME = '1m'

# Gate API
API_KEY = '773a20210bd526e8c6ecde76dce028e5'
SECRET = '790b116e137f89a7e52b03fb4c60bf2ba9abce1c910b009bf331ad181ae9f08b'

# 限价滑点
TRIGGER = 0.0002  # 0.02%

# 轮询间隔（秒）
POLL_INTERVAL = 1

# 初始K线缓存数
CACHE_SIZE = 500

# 文件路径
STATE_FILE = '/home/ubuntu/gate_bot/state.json'
TRADE_LOG = '/home/ubuntu/gate_bot/trades.csv'
LOG_FILE = '/home/ubuntu/gate_bot/gate_bot.log'

# 看门狗配置
WATCHDOG_LOOP = 60       # 检查间隔（秒）
WATCHDOG_STALE_SEC = 300  # 日志超过N秒无修改视为异常

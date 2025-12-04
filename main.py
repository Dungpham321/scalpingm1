# xauusd_bot_fixed_v5.py
"""
XAUUSD Hybrid Bot (Range + Trend) — Safe ATR Version
- MT5 login + Telegram enabled
- Lot cố định 0.01, SL/TP tự tính an toàn
"""
import time
from datetime import datetime
import pandas as pd
import MetaTrader5 as mt5

# ---------------- CONFIG ----------------
SYMBOL = "XAUUSD"
TIMEFRAME_M5 = mt5.TIMEFRAME_M5
TIMEFRAME_M15 = mt5.TIMEFRAME_M15

# MT5 login
MT5_LOGIN = 272913829
MT5_PASSWORD = "Dung2082000!"
MT5_SERVER = "Exness-MT5Trial14"

# Telegram
TELEGRAM_TOKEN = "8396443766:AAH_8z_h9rh4Hdc8QNaUR-l1mGtSAYrVDT0"
TELEGRAM_CHAT_ID = "5464701753"
USE_TELEGRAM = bool(TELEGRAM_TOKEN and TELEGRAM_CHAT_ID)

# Lot / Risk
BASE_LOT = 0.01
MAX_POSITIONS = 3
DEVIATION = 150
MAGIC = 234000

# Strategy toggles
USE_RANGE = True
USE_TREND = True

# TP/SL & Position Management
BE_MOVE = 6   # break-even pips
LOOP_DELAY = 1

# ---------------- UTIL ----------------
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def log(msg): print(f"[{now_str()}] {msg}")

def send_telegram(msg):
    if not USE_TELEGRAM: return
    try:
        import requests
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        log(f"[TG] send error: {e}")

def connect_mt5():
    if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
        raise RuntimeError(f"MT5 init failed: {mt5.last_error()}")
    mt5.symbol_select(SYMBOL, True)
    log("MT5 initialized")

def shutdown_mt5():
    mt5.shutdown()
    log("MT5 shutdown")

def get_digits_pip(symbol):
    info = mt5.symbol_info(symbol)
    digits = info.digits
    pip = 0.001 if digits >= 3 else 0.01
    return digits, pip

def get_ohlcv(symbol, timeframe, n=500):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)
    return df

def ema(series, period): return series.ewm(span=period, adjust=False).mean()
def atr(df, period=14):
    h,l,c = df['high'], df['low'], df['close']
    prev = c.shift(1)
    tr = pd.concat([h-l, (h-prev).abs(), (l-prev).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()

def is_bullish_engulfing(df):
    if len(df)<2: return False
    o1,c1,o2,c2 = df['open'].iloc[-2], df['close'].iloc[-2], df['open'].iloc[-1], df['close'].iloc[-1]
    return (c1<o1) and (c2>o2) and (c2>o1) and (o2<c1)

def is_bearish_engulfing(df):
    if len(df)<2: return False
    o1,c1,o2,c2 = df['open'].iloc[-2], df['close'].iloc[-2], df['open'].iloc[-1], df['close'].iloc[-1]
    return (c1>o1) and (c2<o2) and (c2<o1) and (o2>c1)

def pinbar_type(df, tail_ratio=2.0):
    o,c,h,l = df['open'].iloc[-1], df['close'].iloc[-1], df['high'].iloc[-1], df['low'].iloc[-1]
    body = abs(c-o) or 1e-9
    upper, lower = h-max(c,o), min(c,o)-l
    if lower>tail_ratio*body and upper<body: return 'BULL'
    if upper>tail_ratio*body and lower<body: return 'BEAR'
    return None

# ---------------- SIGNAL ----------------
def range_signal(df5, pip):
    if len(df5)<50: return None
    atr_val = atr(df5).iloc[-1]
    close = df5['close'].iloc[-1]
    if atr_val/close>0.0015: return None
    r_low,r_high = df5['low'].tail(20).min(), df5['high'].tail(20).max()
    buf = 0.6*pip
    if close<=r_low+buf: return 'BUY'
    if close>=r_high-buf: return 'SELL'
    return None

def trend_signal(df15, df5, pip):
    ema50 = ema(df15['close'],50)
    slope = ema50.iloc[-1]-ema50.iloc[-4]
    trend='NEUTRAL'
    if slope>0.8*pip: trend='UP'
    elif slope<-0.8*pip: trend='DOWN'
    df5c = df5.copy()
    pb_touch = abs(df5c['close'].iloc[-1]-ema(df5c['close'],21).iloc[-1])<0.006*df5c['close'].iloc[-1]
    bull = is_bullish_engulfing(df5c)
    bear = is_bearish_engulfing(df5c)
    pin = pinbar_type(df5c)
    buy=sell=False
    if trend=='UP' and pb_touch and (bull or pin=='BULL'): buy=True
    if trend=='DOWN' and pb_touch and (bear or pin=='BEAR'): sell=True
    if buy and not sell: return 'BUY'
    if sell and not buy: return 'SELL'
    return None

# ---------------- ORDER UTIL ----------------
def calculate_sl_tp(symbol, side, entry_price, atr_val, lot=0.01, sl_dollar=3, tp_dollar=5):
    info = mt5.symbol_info(symbol)
    digits = info.digits
    point = info.point
    stop_level = getattr(info, 'trade_stops_level', 15)  # broker stop level in points
    min_dist = stop_level * point * 1.2  # cách entry tối thiểu

    # Chuyển $ sang khoảng giá thực tế
    # 1 lot XAUUSD = 100 oz, pip_value ~ $1/pip với 0.01 lot
    pip_size = 0.001 if digits >= 3 else 0.01
    sl_dist_price = max(min(atr_val*1.5, sl_dollar / (lot * 10)), min_dist)
    tp_dist_price = max(min(atr_val*2.0, tp_dollar / (lot * 10)), min_dist)

    if side=="BUY":
        sl = entry_price - sl_dist_price
        tp = entry_price + tp_dist_price
    else:
        sl = entry_price + sl_dist_price
        tp = entry_price - tp_dist_price

    return round(sl, digits), round(tp, digits)


def safe_place_order(symbol, side, lot, atr_val):
    tick = mt5.symbol_info_tick(symbol)
    price = tick.ask if side=="BUY" else tick.bid
    sl, tp = calculate_sl_tp(symbol, side, price, atr_val)
    ord_type = mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL
    req = {"action":mt5.TRADE_ACTION_DEAL,"symbol":symbol,"volume":lot,
           "type":ord_type,"price":price,"sl":sl,"tp":tp,
           "deviation":DEVIATION,"magic":MAGIC,"comment":"XAU_fixed_v5"}
    res = mt5.order_send(req)
    log(f"[ORDER] {side} price={price} tp={tp} sl={sl} lot={lot} res={getattr(res,'retcode',str(res))}")
    send_telegram(f"{side} → Price:{price} TP:{tp} SL:{sl} Lot:{lot}")
    return res

# ---------------- POSITION MANAGEMENT ----------------
def manage_positions(symbol, pip):
    positions = mt5.positions_get(symbol=symbol)
    if not positions: return
    tick = mt5.symbol_info_tick(symbol)
    for p in positions:
        try:
            if p.type==mt5.ORDER_TYPE_BUY:
                profit_pips=(tick.bid - p.price_open)/pip
                if profit_pips>=BE_MOVE and p.sl<p.price_open:
                    mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":p.ticket,"sl":p.price_open})
            else:
                profit_pips=(p.price_open - tick.ask)/pip
                if profit_pips>=BE_MOVE and (p.sl==0 or p.sl>p.price_open):
                    mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":p.ticket,"sl":p.price_open})
        except: pass

# ---------------- MAIN ----------------
def main():
    connect_mt5()
    digits, pip = get_digits_pip(SYMBOL)
    log(f"Bot started for {SYMBOL} digits={digits} pip={pip}")
    try:
        while True:
            positions = mt5.positions_get(symbol=SYMBOL) or []
            if len(positions)<MAX_POSITIONS:
                df5 = get_ohlcv(SYMBOL, TIMEFRAME_M5, 300)
                df15 = get_ohlcv(SYMBOL, TIMEFRAME_M15, 400)
                atr_val = atr(df5, 14).iloc[-1]
                side = None
                if USE_RANGE:
                    side = range_signal(df5, pip)
                    if side:
                        safe_place_order(SYMBOL, side, BASE_LOT, atr_val)
                if USE_TREND and not side:
                    side = trend_signal(df15, df5, pip)
                    side = "SELL"
                    if side:
                        safe_place_order(SYMBOL, side, BASE_LOT, atr_val)
            manage_positions(SYMBOL, pip)
            time.sleep(LOOP_DELAY)
    except KeyboardInterrupt:
        log("Stopped by user")
    finally:
        shutdown_mt5()

if __name__=="__main__":
    main()

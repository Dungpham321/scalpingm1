# -*- coding: utf-8 -*-
import time
import math
import pandas as pd
import MetaTrader5 as mt5

# ==================== CONFIG ====================
SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1

ATR_PERIOD = 14
TRAIL_ATR_MULT = 1.0
SOFT_CLOSE_ATR_MULT = 0.7

CHECK_INTERVAL = 2
DEVIATION = 10
MAGIC = 777
RISK_PERCENT = 0.005
MAX_ORDERS_TOTAL = 10  # tổng số lệnh tối đa
MAX_ORDERS_PER_SIDE = 5  # tối đa mỗi side

MIN_SL_POINTS = 15
TP_FACTOR = 0.6  # TP < SL

LOGIN = 272913829
PASSWORD = "Dung2082000!"
SERVER = "Exness-MT5Trial14"

# ==================== INIT ====================
def mt5_init():
    if not mt5.initialize(login=LOGIN, password=PASSWORD, server=SERVER):
        print("❌ Không kết nối MT5")
        mt5.shutdown()
        raise SystemExit
    if not mt5.symbol_select(SYMBOL, True):
        print(f"❌ Không chọn được {SYMBOL}")
        mt5.shutdown()
        raise SystemExit
    info = mt5.symbol_info(SYMBOL)
    if not info or not info.visible or info.trade_mode == mt5.SYMBOL_TRADE_MODE_DISABLED:
        print("❌ Symbol không khả dụng hoặc không cho trade")
        mt5.shutdown()
        raise SystemExit
    print("✅ MT5 ready")
    return info

info = mt5_init()
POINT = info.point
DIGITS = info.digits
TICK_SIZE = info.trade_tick_size or POINT
TICK_VALUE = info.trade_tick_value or 1.0

# ==================== UTILS ====================
def get_rates(symbol, timeframe, count=200):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    return pd.DataFrame(rates) if rates is not None else pd.DataFrame()

def calc_atr(df, period):
    if df.empty or len(df)<period+1:
        return None
    high, low, close = df['high'], df['low'], df['close']
    prev_close = close.shift(1)
    tr = pd.concat([(high-low), (high-prev_close).abs(), (low-prev_close).abs()], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])

def account_balance():
    acc = mt5.account_info()
    return acc.balance if acc else 0.0

def value_per_point_for_1lot():
    return TICK_VALUE * (POINT / TICK_SIZE)

def normalize_lot(symbol, lot):
    info = mt5.symbol_info(symbol)
    if not info:
        return lot
    lot = max(info.volume_min, min(lot, info.volume_max))
    steps = round(lot / info.volume_step)
    return round(steps*info.volume_step,2)

def position_count(side=None):
    pos = mt5.positions_get(symbol=SYMBOL) or []
    if side is None:
        return len(pos)
    return sum(1 for p in pos if (p.type==mt5.ORDER_TYPE_BUY and side=="BUY") or (p.type==mt5.ORDER_TYPE_SELL and side=="SELL"))

# ==================== SIGNAL ====================
def tick_momentum_signal(symbol, lookback=5):
    df = get_rates(symbol, TIMEFRAME, lookback)
    if df.empty or len(df)<2:
        return None
    close = df['close']
    momentum = close.iloc[-1] - close.iloc[-2]
    if momentum > 0:
        return "BUY"
    elif momentum < 0:
        return "SELL"
    else:
        return None

# ==================== ORDER & RISK ====================
def calc_lot_by_risk(sl_points):
    bal = account_balance()
    risk_usd = bal*RISK_PERCENT
    vpp = value_per_point_for_1lot()
    lot = risk_usd/(sl_points*vpp) if vpp>0 else 0.01
    return max(0.01, normalize_lot(SYMBOL, lot))

def can_open_order(side):
    if position_count() >= MAX_ORDERS_TOTAL:
        return False
    if side=="BUY" and position_count("BUY")>=MAX_ORDERS_PER_SIDE:
        return False
    if side=="SELL" and position_count("SELL")>=MAX_ORDERS_PER_SIDE:
        return False
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return False
    spread_points = abs(tick.ask-tick.bid)/POINT
    if spread_points>10:
        return False
    return True

def open_order(side):
    tick = mt5.symbol_info_tick(SYMBOL)
    if not tick:
        return None
    price = tick.ask if side=="BUY" else tick.bid
    atr_val = calc_atr(get_rates(SYMBOL, TIMEFRAME, 200), ATR_PERIOD)
    sl_points = max(int((atr_val/POINT) if atr_val else MIN_SL_POINTS), MIN_SL_POINTS)
    tp_points = int(sl_points*TP_FACTOR)
    sl = price - sl_points*POINT if side=="BUY" else price + sl_points*POINT
    tp = price + tp_points*POINT if side=="BUY" else price - tp_points*POINT
    min_dist = 10*POINT
    if abs(price-sl)<min_dist or abs(tp-price)<min_dist:
        sl, tp = None, None
    lot = calc_lot_by_risk(sl_points)
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if side=="BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "deviation": DEVIATION,
        "magic": MAGIC,
        "comment": "Scalp-v4",
    }
    if sl is not None and tp is not None:
        req["sl"], req["tp"] = sl, tp
    res = mt5.order_send(req)
    if res and res.retcode==mt5.TRADE_RETCODE_DONE:
        print(f"✅ Open {side} lot {lot:.2f} @ {price:.2f} SL={sl} TP={tp}")
        return res.order
    else:
        print(f"❌ Open {side} fail retcode={getattr(res,'retcode',None)} comment={getattr(res,'comment','')}")
        return None

# ==================== TRAILING & SOFT-CLOSE ====================
def manage_position(p, atr, sig):
    tick = mt5.symbol_info_tick(p.symbol)
    if not tick or atr is None:
        return
    side_buy = (p.type==mt5.ORDER_TYPE_BUY)
    mkt = tick.bid if side_buy else tick.ask
    profit = (mkt - p.price_open) if side_buy else (p.price_open - mkt)
    # trailing SL
    proposed_sl = (mkt - TRAIL_ATR_MULT*atr) if side_buy else (mkt + TRAIL_ATR_MULT*atr)
    min_dist = MIN_SL_POINTS*POINT
    if side_buy:
        proposed_sl = min(proposed_sl, mkt - min_dist)
        new_sl = round(max(proposed_sl, p.sl or -math.inf), DIGITS)
    else:
        proposed_sl = max(proposed_sl, mkt + min_dist)
        new_sl = round(min(proposed_sl, p.sl or math.inf), DIGITS)
    # soft-close khi tín hiệu ngược
    if sig=="SELL" and side_buy:
        soft_sl = p.price_open - SOFT_CLOSE_ATR_MULT*atr
        new_sl = max(new_sl, round(soft_sl,DIGITS))
    elif sig=="BUY" and not side_buy:
        soft_sl = p.price_open + SOFT_CLOSE_ATR_MULT*atr
        new_sl = min(new_sl, round(soft_sl,DIGITS))
    # cập nhật SL
    if p.sl is None or abs(new_sl-p.sl)>0.5*POINT:
        mt5.order_send({"action":mt5.TRADE_ACTION_SLTP,"position":p.ticket,"sl":new_sl,"tp":p.tp,"symbol":p.symbol})
        print(f"🔧 Trail/Soft SL -> {new_sl:.2f}")

# ==================== MAIN LOOP ====================
def main():
    print("🚀 Scalping bot v4 running...")
    try:
        while True:
            sig = tick_momentum_signal(SYMBOL)
            atr_val = calc_atr(get_rates(SYMBOL, TIMEFRAME, 200), ATR_PERIOD)
            # mở lệnh nếu có tín hiệu và còn slot
            if sig=="BUY" and can_open_order("BUY"):
                open_order("BUY")
            elif sig=="SELL" and can_open_order("SELL"):
                open_order("SELL")
            # quản lý tất cả lệnh hiện tại
            for p in mt5.positions_get(symbol=SYMBOL) or []:
                manage_position(p, atr_val, sig)
            time.sleep(CHECK_INTERVAL)
    except KeyboardInterrupt:
        print("🛑 Bot stopped")
    finally:
        mt5.shutdown()
        print("👋 MT5 shutdown")

if __name__=="__main__":
    main()

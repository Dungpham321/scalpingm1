# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import pandas as pd
import time
import math

# ==================== CẤU HÌNH ====================
MT5_LOGIN = 270522374
MT5_PASSWORD = "Dung2082000!"
MT5_SERVER = "Exness-MT5Trial17"
SYMBOL = "XAUUSD"

TIMEFRAME = mt5.TIMEFRAME_M1
RISK_PERCENT = 1.0
MIN_LOT = 0.01
MAX_LOT = 0.05
SLEEP_INTERVAL = 0.5
MAX_ORDERS = 3
TRAIL_STEP = 0.2
MOMENTUM_N = 3       # số nến dùng để tính momentum
MOMENTUM_THRESHOLD = 0.1  # threshold lọc nhiễu nhỏ

# ==================== KẾT NỐI MT5 ====================
if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
    print("Không kết nối MT5 được")
    mt5.shutdown()
    exit()
print("MT5 kết nối thành công!")

# ==================== HÀM HỖ TRỢ ====================
def get_data(symbol, timeframe, n=100):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_atr(df, period=14):
    df['h-l'] = df['high'] - df['low']
    df['h-pc'] = abs(df['high'] - df['close'].shift())
    df['l-pc'] = abs(df['low'] - df['close'].shift())
    tr = df[['h-l','h-pc','l-pc']].max(axis=1)
    atr = tr.rolling(period).mean().iloc[-1]
    return atr

def calc_lot(balance, atr):
    # lot tự động theo balance và ATR
    risk_per_lot = 10 * atr  # ước lượng rủi ro 1 lot
    lot = balance * RISK_PERCENT / 100 / risk_per_lot
    lot = max(lot, MIN_LOT)
    lot = min(lot, MAX_LOT)
    step = mt5.symbol_info(SYMBOL).volume_step
    lot = math.floor(lot / step) * step
    return round(lot, 2)

def calc_sl_tp(price, order_type):
    info = mt5.symbol_info(SYMBOL)
    digits = info.digits
    point = info.point
    min_stop = info.trade_stops_level * point + 0.01

    # SL/TP tối thiểu hợp lệ broker
    sl_distance = max(0.5, min_stop)  # ~50 pip thực tế
    tp_distance = max(0.5, min_stop)

    if order_type == mt5.ORDER_TYPE_BUY:
        sl = round(price - sl_distance, digits)
        tp = round(price + tp_distance, digits)
    else:
        sl = round(price + sl_distance, digits)
        tp = round(price - tp_distance, digits)

    return sl, tp


def open_order(symbol, order_type, lot, retries=3):
    for attempt in range(retries):
        tick = mt5.symbol_info_tick(symbol)
        if tick is None:
            return None
        price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
        sl, tp = calc_sl_tp(price, order_type)
        print(sl, tp)
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": lot,
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 123456,
            "comment": "scalping_M1_v9.2",
            "type_filling": mt5.ORDER_FILLING_FOK,
        }
        result = mt5.order_send(request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result
        elif result.retcode in [10019, 10016]:
            print(f"Lỗi: {result.retcode}")
            time.sleep(0.05)
            continue
        elif result.retcode == 10026:
            print("SL/TP quá gần, bỏ qua lệnh")
            return None
        else:
            print(f"Lỗi mở lệnh: {result.retcode}")
            return None
    return None

def count_positions(symbol):
    buy_count = sell_count = 0
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for pos in positions:
            if pos.type == mt5.ORDER_TYPE_BUY:
                buy_count += 1
            else:
                sell_count += 1
    return buy_count, sell_count

def update_trailing_stop(symbol, atr, trail_step=TRAIL_STEP):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return
    digits = mt5.symbol_info(SYMBOL).digits
    min_gap = 0.5 * atr

    for pos in positions:
        if pos.type == mt5.ORDER_TYPE_BUY:
            target_sl = tick.ask - atr * trail_step
            new_sl = max(pos.sl if pos.sl else pos.price_open, target_sl)
            if new_sl < tick.ask - min_gap:
                new_sl = tick.ask - min_gap
            new_sl = round(new_sl, digits)
            if new_sl > (pos.sl if pos.sl else 0):
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                mt5.order_send(request)
        else:
            target_sl = tick.bid + atr * trail_step
            new_sl = min(pos.sl if pos.sl else pos.price_open, target_sl)
            if new_sl > tick.bid + min_gap:
                new_sl = tick.bid + min_gap
            new_sl = round(new_sl, digits)
            if pos.sl is None or new_sl < pos.sl:
                request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "symbol": symbol,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                mt5.order_send(request)

# ==================== BOT CHÍNH ====================
try:
    while True:
        df = get_data(SYMBOL, TIMEFRAME, 100)
        atr = calculate_atr(df)
        tick = mt5.symbol_info_tick(SYMBOL)
        if tick is None:
            time.sleep(SLEEP_INTERVAL)
            continue

        balance = mt5.account_info().balance
        lot = calc_lot(balance, atr)
        buy_count, sell_count = count_positions(SYMBOL)

        # Momentum nhiều nến
        momentum = df['close'].iloc[-1] - df['close'].iloc[-1-MOMENTUM_N]
        print(momentum)
        if momentum > MOMENTUM_THRESHOLD and buy_count < MAX_ORDERS:
            open_order(SYMBOL, mt5.ORDER_TYPE_BUY, lot)
        elif momentum < -MOMENTUM_THRESHOLD and sell_count < MAX_ORDERS:
            open_order(SYMBOL, mt5.ORDER_TYPE_SELL, lot)

        update_trailing_stop(SYMBOL, atr)
        time.sleep(SLEEP_INTERVAL)

except KeyboardInterrupt:
    print("Dừng bot bằng tay")
finally:
    mt5.shutdown()

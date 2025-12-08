# -*- coding: utf-8 -*-
"""
Scalping M1 — Continuous Entry Bot (Safe Version)
Tập trung vào:
 - Vào lệnh LIÊN TỤC (momentum tick + micro structure)
 - Kiểm soát rủi ro chặt chẽ
 - Không SL/TP cứng khi mở lệnh (tránh 10026)
 - Auto-SL sau khi spread ổn định
 - Trailing-stop chủ động
"""

import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import math

# ================= CONFIG =================
LOGIN = 270522374
PASSWORD = "Dung2082000!"
SERVER = "Exness-MT5Trial17"
SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1

MAX_ORDERS = 5
RISK_PERCENT = 0.5
MIN_LOT = 0.01
MAX_LOT = 0.1

SLEEP = 0.20
TRAIL_ATR_MULT = 0.5
SAFE_SPREAD = 115   # giới hạn spread tối đa

# ================ INIT =====================
mt5.initialize(login=LOGIN, password=PASSWORD, server=SERVER)

# ================ FUNCTIONS ================
def get_df(n=200):
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, n)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df


def calc_atr(df, n=14):
    high = df['high']
    low = df['low']
    close = df['close']
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.rolling(n).mean().iloc[-1]


def spread_ok():
    tick = mt5.symbol_info_tick(SYMBOL)
    return (tick.ask - tick.bid) / mt5.symbol_info(SYMBOL).point <= SAFE_SPREAD


def calc_lot(balance, atr):
    risk_money = balance * (RISK_PERCENT / 100)
    est_sl = atr * 10
    raw = risk_money / est_sl
    raw = max(MIN_LOT, min(raw, MAX_LOT))
    step = mt5.symbol_info(SYMBOL).volume_step
    return round(raw / step) * step


def entry_signal(df, atr):
    # Momentum 2 nến
    mom = df['close'].iloc[-1] - df['close'].iloc[-3]

    # Micro-structure: break minor high/low
    bh = df['high'].rolling(5).max().iloc[-2]
    bl = df['low'].rolling(5).min().iloc[-2]

    last = df['close'].iloc[-1]

    # Tick Volume Spike
    vol = df['tick_volume']
    vol_burst = vol.iloc[-1] > vol.rolling(20).mean().iloc[-1] * 1.5

    buy  = last > bh and mom > 0 and vol_burst
    sell = last < bl and mom < 0 and vol_burst

    return buy, sell


def open_order(order_type, lot):
    tick = mt5.symbol_info_tick(SYMBOL)
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot,
        "type": order_type,
        "price": price,
        "deviation": 20,
        "magic": 444001,
        "comment": "scalp_m1_safe",
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    result = mt5.order_send(request)
    return result


def set_sltp(position_ticket, sl, tp):
    req = {
        "action": mt5.TRADE_ACTION_SLTP,
        "position": position_ticket,
        "sl": sl,
        "tp": tp
    }
    mt5.order_send(req)


def trailing(atr):
    tick = mt5.symbol_info_tick(SYMBOL)
    positions = mt5.positions_get(symbol=SYMBOL)
    if not positions:
        return

    digits = mt5.symbol_info(SYMBOL).digits

    for p in positions:
        if p.type == 0:  # BUY
            new_sl = tick.bid - atr * TRAIL_ATR_MULT
            if p.sl is None or new_sl > p.sl:
                set_sltp(p.ticket, round(new_sl, digits), p.tp)
        else:
            new_sl = tick.ask + atr * TRAIL_ATR_MULT
            if p.sl is None or new_sl < p.sl:
                set_sltp(p.ticket, round(new_sl, digits), p.tp)


# =============== MAIN LOOP ==================
while True:
    df = get_df()
    atr = calc_atr(df)
    tick = mt5.symbol_info_tick(SYMBOL)
    if not spread_ok():
        time.sleep(SLEEP)
        continue

    balance = mt5.account_info().balance
    lot = calc_lot(balance, atr)

    buy_sig, sell_sig = entry_signal(df, atr)

    positions = mt5.positions_get(symbol=SYMBOL)
    count = len(positions) if positions else 0
    print(f"Buy: {buy_sig} | Sell: {sell_sig}")
    if buy_sig and count < MAX_ORDERS:
        r = open_order(mt5.ORDER_TYPE_BUY, lot)

    if sell_sig and count < MAX_ORDERS:
        r = open_order(mt5.ORDER_TYPE_SELL, lot)

    trailing(atr)
    time.sleep(SLEEP)


# END BOT

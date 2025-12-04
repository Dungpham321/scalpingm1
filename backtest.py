# -*- coding: utf-8 -*-
import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from main import signal_m1_pullback_breakout, calc_atr, get_rates, TIMEFRAME, SYMBOL, ATR_PERIOD

BARS = 5000   # số nến backtest


def backtest_signal():
    print("🔍 Backtest tín hiệu Pullback + Breakout M1")

    df = get_rates(SYMBOL, TIMEFRAME, BARS)
    if df.empty:
        print("❌ Không load được dữ liệu MT5")
        return

    df["signal"] = None
    df["setup"] = None
    df["return_points"] = 0.0

    total = len(df)

    for i in range(50, total - 2):
        # tạo window để truyền vào signal
        window = df.iloc[:i+1].copy()

        sig, setup = signal_m1_pullback_breakout(SYMBOL)

        df.loc[df.index[i], "signal"] = sig
        df.loc[df.index[i], "setup"] = setup

        if sig in ["BUY", "SELL"]:
            entry = df["close"].iloc[i]
            exit_price = df["close"].iloc[i+1]

            if sig == "BUY":
                df.loc[df.index[i], "return_points"] = exit_price - entry
            else:
                df.loc[df.index[i], "return_points"] = entry - exit_price

    # ---- Summary ----
    trades = df[df["signal"].isin(["BUY", "SELL"])]
    win = trades[trades["return_points"] > 0]
    lose = trades[trades["return_points"] <= 0]

    print("\n===== KẾT QUẢ BACKTEST =====")
    print(f"Tổng tín hiệu: {len(trades)}")
    print(f"BUY  : {len(trades[trades['signal']=='BUY'])}")
    print(f"SELL : {len(trades[trades['signal']=='SELL'])}")
    print(f"Win  : {len(win)}  ({len(win)/max(1,len(trades))*100:.2f}%)")
    print(f"Lose : {len(lose)}  ({len(lose)/max(1,len(trades))*100:.2f}%)")
    print(f"Total P/L points: {trades['return_points'].sum():.2f}")

    return df, trades


if __name__ == "__main__":
    mt5.initialize()
    backtest_signal()
    mt5.shutdown()

#!/usr/bin/env python3
# binance_daily_scan_usdt.py
# Daily volatility scan + TA for Binance USDT spot pairs.
# Outputs to ./binance_outputs/{YYYYMMDD}/

import os
import time
import math
from datetime import datetime, timedelta
import argparse
import traceback

import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import requests

# -----------------------
# Config
# -----------------------
EXCHANGE_ID = "binance"
QUOTE = "USDT"
TIMEFRAME = "4h"
VOL_WINDOW = 30          # number of candles used to compute volatility
LOOKBACK_DAYS = 14
TOP_K = 8
MIN_VOLUME_USD = 5000
OUTDIR = "binance_outputs"
PLOT_DIRNAME = "plots"
SUMMARY_FILENAME = "summary.csv"
SIGNAL_FILENAME = "signals.txt"
TELEGRAM_SEND = False    # set True and export TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID env vars

# -----------------------
# Helpers
# -----------------------
def ensure_dir(path):
    os.makedirs(path, exist_ok=True)

def now_tag():
    return datetime.utcnow().strftime("%Y%m%d")

def safe_float(x):
    try:
        return float(x)
    except:
        return np.nan

# -----------------------
# Exchange helpers
# -----------------------
def load_exchange(exchange_id=EXCHANGE_ID):
    ex_cls = getattr(ccxt, exchange_id)
    ex = ex_cls({"enableRateLimit": True})
    ex.load_markets()
    return ex

def list_usdt_pairs(exchange):
    symbols = []
    for s, m in exchange.markets.items():
        if m.get("quote") and m["quote"].upper() == QUOTE and m.get("spot", False):
            symbols.append(s)
    return sorted(set(symbols))

def fetch_ohlcv_ccxt(exchange, symbol, timeframe=TIMEFRAME, since_days=LOOKBACK_DAYS):
    since_ms = exchange.milliseconds() - int(since_days * 24 * 60 * 60 * 1000)
    try:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=1000)
    except Exception:
        data = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=1000)
    if not data:
        return None
    df = pd.DataFrame(data, columns=["ts","Open","High","Low","Close","Volume"])
    df["Date"] = pd.to_datetime(df["ts"], unit="ms")
    df = df.drop(columns=["ts"]).sort_values("Date").reset_index(drop=True)
    for c in ["Open","High","Low","Close","Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

# -----------------------
# Volatility, indicators, channel detection
# -----------------------
def compute_volatility(df, window=VOL_WINDOW):
    if df is None or len(df) < 3:
        return np.nan
    close = df["Close"].astype(float)
    ret = np.log(close).diff().dropna()
    if len(ret) < 2:
        return np.nan
    return float(ret.tail(window).std())

def add_indicators(df):
    df = df.copy()
    df["EMA_12"] = df["Close"].ewm(span=12, adjust=False).mean()
    df["EMA_26"] = df["Close"].ewm(span=26, adjust=False).mean()
    delta = df["Close"].diff()
    up = delta.clip(lower=0).rolling(14).mean()
    down = -delta.clip(upper=0).rolling(14).mean()
    rs = up / down.replace(0, np.nan)
    df["RSI_14"] = 100 - (100 / (1 + rs))
    df["MACD"] = df["EMA_12"] - df["EMA_26"]
    df["MACD_SIGNAL"] = df["MACD"].rolling(9).mean()
    ma20 = df["Close"].rolling(20).mean()
    std20 = df["Close"].rolling(20).std()
    df["BB_H"] = ma20 + 2 * std20
    df["BB_L"] = ma20 - 2 * std20
    df = df.fillna(method="ffill").fillna(method="bfill")
    return df

def detect_channel_and_trend(df, n_points=6):
    highs = df["High"].values
    lows = df["Low"].values
    L = len(df)
    peaks = []
    troughs = []
    for i in range(2, L-2):
        if highs[i] == max(highs[i-2:i+3]):
            peaks.append((i, highs[i]))
        if lows[i] == min(lows[i-2:i+3]):
            troughs.append((i, lows[i]))
    if len(peaks) >= 2 and len(troughs) >= 2:
        peaks = peaks[-n_points:]
        troughs = troughs[-n_points:]
        xi_p = np.array([p[0] for p in peaks])
        yi_p = np.array([p[1] for p in peaks])
        xi_t = np.array([t[0] for t in troughs])
        yi_t = np.array([t[1] for t in troughs])
        try:
            slope_p, intercept_p = np.polyfit(xi_p, yi_p, 1)
            slope_t, intercept_t = np.polyfit(xi_t, yi_t, 1)
            return {"peak_fit":(slope_p, intercept_p), "trough_fit":(slope_t, intercept_t), "peaks":peaks, "troughs":troughs}
        except Exception:
            return None
    return None

# -----------------------
# Signal rules (short intraday)
# -----------------------
def generate_short_term_signal(df, fits):
    last = df.iloc[-1]
    price = float(last["Close"])
    rsi = float(last["RSI_14"])
    macd = float(last["MACD"])
    macd_sig = float(last["MACD_SIGNAL"])
    bbh = float(last["BB_H"])
    bbl = float(last["BB_L"])

    signal = {"side":"none","reason":"nomatch","entry":None,"stop":None,"target":None}

    if fits is not None:
        trough_slope, trough_int = fits["trough_fit"]
        idx = len(df)-1
        support_proj = trough_slope * idx + trough_int
    else:
        support_proj = bbl

    recent_vol = float(df["Volume"].tail(12).mean())
    if recent_vol * price < MIN_VOLUME_USD:
        signal["reason"] = "low_liquidity"
        return signal

    if price > support_proj * 0.995 and macd > macd_sig and 40 < rsi < 70:
        entry = price
        stop = float(min(support_proj * 0.98, price - price*0.012))
        target = float(price + max((price - stop)*1.8, price*0.015))
        signal.update({"side":"long","reason":"macd+support+rsi","entry":entry,"stop":stop,"target":target})
        return signal

    if price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
        entry = price
        stop = float(price + price*0.012)
        target = float(price - price*0.018)
        signal.update({"side":"short","reason":"bb_upper+macd_down","entry":entry,"stop":stop,"target":target})
        return signal

    return signal

# -----------------------
# Plotting
# -----------------------
def plot_symbol(df, symbol, fits, outpath):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name=symbol))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["EMA_12"], name="EMA12", line=dict(color="blue", width=1)))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["EMA_26"], name="EMA26", line=dict(color="purple", width=1)))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["BB_H"], name="BB_H", line=dict(color="green", dash="dot")))
    fig.add_trace(go.Scatter(x=df["Date"], y=df["BB_L"], name="BB_L", line=dict(color="red", dash="dot")))
    if fits is not None:
        slope_p, int_p = fits["peak_fit"]
        slope_t, int_t = fits["trough_fit"]
        xs = np.arange(len(df))
        y_peak = slope_p * xs + int_p
        y_trough = slope_t * xs + int_t
        dates = df["Date"].tolist()
        fig.add_trace(go.Scatter(x=dates, y=y_peak, name="channel_top", line=dict(color="orange", dash="dash")))
        fig.add_trace(go.Scatter(x=dates, y=y_trough, name="channel_bot", line=dict(color="orange", dash="dash")))
    fig.update_layout(title=f"{symbol} — {TIMEFRAME} TA", template="plotly_white", xaxis_rangeslider_visible=False)
    fig.write_html(outpath)

# -----------------------
# Telegram notify
# -----------------------
def send_telegram(text):
    try:
        token = os.environ.get("TELEGRAM_BOT_TOKEN")
        chat = os.environ.get("TELEGRAM_CHAT_ID")
        if not token or not chat:
            return False
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = requests.post(url, json={"chat_id":chat, "text":text})
        return resp.status_code == 200
    except Exception:
        return False

# -----------------------
# Main pipeline
# -----------------------
def main():
    parser = argparse.ArgumentParser(description="Binance USDT volatility scan + TA")
    parser.add_argument("--date", default=now_tag())
    parser.add_argument("--topk", type=int, default=TOP_K)
    parser.add_argument("--timeframe", default=TIMEFRAME)
    args = parser.parse_args()

    date_tag = args.date
    outdir = os.path.join(OUTDIR, date_tag)
    plots_dir = os.path.join(outdir, PLOT_DIRNAME)
    ensure_dir(outdir); ensure_dir(plots_dir)

    ex = load_exchange(EXCHANGE_ID)
    symbols = list_usdt_pairs(ex)
    print(f"Found {len(symbols)} USDT pairs on {EXCHANGE_ID}")

    vol_list = []
    for s in symbols:
        try:
            df = fetch_ohlcv_ccxt(ex, s, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None or len(df) < 12:
                continue
            vol = compute_volatility(df, window=VOL_WINDOW)
            last_price = float(df["Close"].iloc[-1])
            recent_vol = float(df["Volume"].tail(12).mean())
            vol_usd = recent_vol * last_price
            if math.isnan(vol) or vol_usd < MIN_VOLUME_USD:
                continue
            vol_list.append((s, vol, last_price, vol_usd))
            time.sleep(0.06)
        except Exception:
            continue

    if not vol_list:
        print("No volatile symbols found after filtering.")
        return

    vol_df = pd.DataFrame(vol_list, columns=["symbol","vol","last_price","vol_usd"]).sort_values("vol", ascending=False)
    topk = vol_df.head(args.topk)
    topk.to_csv(os.path.join(outdir, "vol_sorted.csv"), index=False)

    summary_rows = []
    signals = []

    for _, r in topk.iterrows():
        sym = r["symbol"]
        print("Analyzing", sym)
        try:
            df = fetch_ohlcv_ccxt(ex, sym, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None or len(df) < 12:
                continue
            df = add_indicators(df)
            fits = detect_channel_and_trend(df)
            signal = generate_short_term_signal(df, fits)
            plot_path = os.path.join(plots_dir, f"{sym.replace('/','_')}.html")
            plot_symbol(df, sym, fits, plot_path)
            summary_rows.append({
                "symbol": sym,
                "last_price": float(df["Close"].iloc[-1]),
                "volatility": float(r["vol"]),
                "vol_usd": float(r["vol_usd"]),
                "signal_side": signal["side"],
                "signal_reason": signal["reason"],
                "entry": signal["entry"],
                "stop": signal["stop"],
                "target": signal["target"],
                "plot": plot_path
            })
            if signal["side"] != "none":
                stext = f"{sym} | {signal['side'].upper()} | entry={signal['entry']:.2f} stop={signal['stop']:.2f} target={signal['target']:.2f} reason={signal['reason']}"
                signals.append(stext)
        except Exception:
            continue

    summary_df = pd.DataFrame(summary_rows)
    summary_csv = os.path.join(outdir, SUMMARY_FILENAME)
    summary_df.to_csv(summary_csv, index=False)

    signal_file = os.path.join(outdir, SIGNAL_FILENAME)
    with open(signal_file, "w", encoding="utf-8") as f:
        if signals:
            f.write("\n".join(signals))
        else:
            f.write("No actionable short-term signals found.\n")

    print(f"Wrote outputs to {outdir}")
    if TELEGRAM_SEND and signals:
        body = f"Volatility scan {date_tag}\n" + "\n".join(signals[:8])
        ok = send_telegram(body)
        print("telegram sent:", ok)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()


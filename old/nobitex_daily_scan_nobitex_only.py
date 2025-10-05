#!/usr/bin/env python3
# nobitex_daily_scan_nobitex_only.py
# Uses only Nobitex public/private API (with provided Bearer token) to:
# - list symbols (USDT pairs)
# - fetch recent trades and aggregate 4H OHLCV
# - compute volatility, indicators, detect simple channel, produce plots and signals
# - outputs in ./nobitex_outputs/{YYYYMMDD}/
#
# Requirements:
# pip install requests pandas numpy plotly
#
# Usage:
# export NOBITEX_TOKEN="7fecf5964c24766fd64c4be370c293568aa52354"
# python nobitex_daily_scan_nobitex_only.py

import os
import time
import math
from datetime import datetime, timedelta
import argparse
import requests
import json
import traceback

import pandas as pd
import numpy as np
import plotly.graph_objects as go

# -----------------------
# Config - edit if needed
# -----------------------
NOBITEX_API_BASE = os.environ.get("NOBITEX_API_BASE", "https://api.nobitex.ir")
NOBITEX_TOKEN = os.environ.get("NOBITEX_TOKEN", "7fecf5964c24766fd64c4be370c293568aa52354")
QUOTE_SUFFIX = "USDT"           # only scan symbols containing this
TIMEFRAME_MINUTES = 240         # 4 hours
VOL_WINDOW = 30                 # candles for volatility calc
LOOKBACK_DAYS = 14              # how many days of trades to fetch (should cover VOL_WINDOW)
TOP_K = 8
MIN_VOLUME_USD = 5000           # liquidity filter (USD)
OUTDIR = "nobitex_outputs"
PLOT_DIRNAME = "plots"
SUMMARY_FILENAME = "summary.csv"
SIGNAL_FILENAME = "signals.txt"
TELEGRAM_SEND = False           # set True and export TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID env vars

HEADERS = {"Authorization": f"Bearer {NOBITEX_TOKEN}", "Accept": "application/json"}

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
# Nobitex endpoints used (best-effort)
# -----------------------
def nobitex_list_markets():
    """
    Uses Nobitex public market list endpoints to retrieve symbols.
    Filters and returns only symbols containing QUOTE_SUFFIX (USDT).
    """
    candidates = [
        f"{NOBITEX_API_BASE}/v2/market/symbols",
        f"{NOBITEX_API_BASE}/v2/symbols",
        f"{NOBITEX_API_BASE}/markets",
        f"{NOBITEX_API_BASE}/market/symbols"
    ]
    syms = set()
    for url in candidates:
        try:
            r = requests.get(url, headers=HEADERS, timeout=8)
            if r.status_code != 200:
                continue
            data = r.json()
            # handle various shapes
            if isinstance(data, dict):
                # try common containers
                for key in ("symbols","data","result","markets"):
                    if key in data:
                        container = data[key]
                        if isinstance(container, list):
                            for it in container:
                                if isinstance(it, dict):
                                    s = it.get("symbol") or it.get("pair") or it.get("name")
                                    if s:
                                        syms.add(s.replace("-", "/").upper())
                        elif isinstance(container, dict):
                            for k in container.keys():
                                syms.add(k.replace("-", "/").upper())
                # fallback: try top-level as list
                if not syms:
                    for v in data.values():
                        if isinstance(v, list):
                            for it in v:
                                if isinstance(it, dict):
                                    s = it.get("symbol") or it.get("pair") or it.get("name")
                                    if s:
                                        syms.add(s.replace("-", "/").upper())
            elif isinstance(data, list):
                for it in data:
                    if isinstance(it, dict):
                        s = it.get("symbol") or it.get("pair") or it.get("name")
                        if s:
                            syms.add(s.replace("-", "/").upper())
        except Exception:
            continue
    # filter USDT pairs only
    usdt_syms = sorted([s for s in syms if QUOTE_SUFFIX in s])
    return usdt_syms

# -----------------------
# Fetch trades and aggregate to OHLCV 4H
# -----------------------
def nobitex_fetch_trades(symbol, since_ts_ms=None, limit=1000):
    """
    Fetch trade list for a symbol. Endpoint: /v2/trades/:symbol
    Returns list of trades or None.
    """
    url = f"{NOBITEX_API_BASE}/v2/trades/{symbol}"
    params = {}
    try:
        r = requests.get(url, headers=HEADERS, params=params, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        # data may be list or dict with 'data' key
        if isinstance(data, dict):
            for k in ("data","result","trades"):
                if k in data and isinstance(data[k], list):
                    return data[k]
            # sometimes top-level is list under other keys
            # fallback: try to find any list of trades
            for v in data.values():
                if isinstance(v, list):
                    return v
            return None
        elif isinstance(data, list):
            return data
    except Exception:
        return None

def trades_to_ohlcv(trades, timeframe_minutes=TIMEFRAME_MINUTES, lookback_days=LOOKBACK_DAYS):
    """
    Convert Nobitex trades (list of dicts or lists) to OHLCV pandas DataFrame aggregated per timeframe_minutes.
    Tries to extract timestamp (ms) and price, volume fields from common keys.
    """
    rows = []
    for t in trades:
        # accept both dict and list shapes
        if isinstance(t, list) and len(t) >= 3:
            # assume [id, timestamp_ms, price, amount] or similar
            try:
                ts = int(t[1])
                price = float(t[2])
                amount = float(t[3]) if len(t) > 3 else 0.0
                rows.append((ts, price, amount))
            except Exception:
                continue
        elif isinstance(t, dict):
            # common keys: t, timestamp, time, date, price, p, amount, q, qty, v
            ts = None
            for k in ("t","timestamp","time","date"):
                if k in t:
                    try:
                        ts = int(t[k])
                        break
                    except Exception:
                        pass
            price = None
            for k in ("p","price","rate"):
                if k in t:
                    price = safe_float(t[k]); break
            amount = None
            for k in ("q","quantity","amount","v","volume"):
                if k in t:
                    amount = safe_float(t[k]); break
            if ts and price is not None:
                rows.append((ts, price, amount or 0.0))
    if not rows:
        return None
    df = pd.DataFrame(rows, columns=["ts","price","vol"])
    # convert timestamps: many Nobitex timestamps are in ms; ensure ms
    if df["ts"].median() < 1e12:
        # seconds -> ms
        df["ts"] = df["ts"] * 1000
    df["DateTime"] = pd.to_datetime(df["ts"], unit="ms")
    # filter lookback days
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    df = df[df["DateTime"] >= pd.Timestamp(cutoff)]
    if df.empty:
        return None
    # floor to timeframe
    period = f"{timeframe_minutes}min"
    df.set_index("DateTime", inplace=True)
    o = df["price"].resample(period).ohlc()
    v = df["vol"].resample(period).sum()
    ohlcv = o.join(v).dropna().reset_index().rename(columns={"sum":"Volume"})
    ohlcv.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","vol":"Volume"}, inplace=True)
    # ensure correct column names
    if "Volume" not in ohlcv.columns:
        ohlcv["Volume"] = v.values
    # keep recent VOL_WINDOW + buffer
    if len(ohlcv) < 5:
        return None
    return ohlcv

# -----------------------
# Volatility and indicators
# -----------------------
def compute_volatility(df, window=VOL_WINDOW):
    if df is None or len(df) < 3:
        return np.nan
    close = df["Close"].astype(float)
    ret = np.log(close).diff().dropna()
    if ret.empty:
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
# Signal generation (short-term intraday)
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

    # support projection
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

    # Long condition
    if price > support_proj * 0.995 and macd > macd_sig and 40 < rsi < 70:
        entry = price
        stop = float(min(support_proj * 0.98, price - price*0.012))
        target = float(price + max((price - stop)*1.8, price*0.015))
        signal.update({"side":"long","reason":"macd+support+rsi","entry":entry,"stop":stop,"target":target})
        return signal

    # Short condition
    if price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
        entry = price
        stop = float(price + price*0.012)
        target = float(price - price*0.018)
        signal.update({"side":"short","reason":"bb_upper+macd_down","entry":entry,"stop":stop,"target":target})
        return signal

    return signal

# -----------------------
# Plot
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
    fig.update_layout(title=f"{symbol} — {TIMEFRAME_MINUTES}m TA", template="plotly_white", xaxis_rangeslider_visible=False)
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
        resp = requests.post(url, json={"chat_id": chat, "text": text})
        return resp.status_code == 200
    except Exception:
        return False

# -----------------------
# Main
# -----------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=now_tag())
    parser.add_argument("--topk", type=int, default=TOP_K)
    parser.add_argument("--timeframe_minutes", type=int, default=TIMEFRAME_MINUTES)
    args = parser.parse_args()

    tag = args.date
    outdir = os.path.join(OUTDIR, tag)
    plots_dir = os.path.join(outdir, PLOT_DIRNAME)
    ensure_dir(outdir); ensure_dir(plots_dir)

    # 1) get symbols from Nobitex
    try:
        symbols = nobitex_list_markets()
    except Exception:
        symbols = []
    if not symbols:
        print("No symbols found on Nobitex. Exiting.")
        return

    print(f"Found {len(symbols)} USDT symbols on Nobitex. Scanning volatility...")

    vol_list = []
    for s in symbols:
        try:
            trades = nobitex_fetch_trades(s)
            if not trades:
                continue
            ohlcv = trades_to_ohlcv(trades, timeframe_minutes=args.timeframe_minutes, lookback_days=LOOKBACK_DAYS)
            if ohlcv is None or len(ohlcv) < 6:
                continue
            vol = compute_volatility(ohlcv, window=VOL_WINDOW)
            last_price = float(ohlcv["Close"].iloc[-1])
            recent_vol = float(ohlcv["Volume"].tail(12).mean())
            vol_usd = recent_vol * last_price
            if np.isnan(vol) or vol_usd < MIN_VOLUME_USD:
                continue
            vol_list.append((s, vol, last_price, vol_usd))
            time.sleep(0.08)
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
            trades = nobitex_fetch_trades(sym)
            if not trades:
                continue
            df = trades_to_ohlcv(trades, timeframe_minutes=args.timeframe_minutes, lookback_days=LOOKBACK_DAYS)
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
        except Exception as e:
            print("Error analyzing", sym, e)
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

    print("Wrote outputs to", outdir)
    if TELEGRAM_SEND and signals:
        body = f"Volatility scan {tag}\n" + "\n".join(signals[:8])
        ok = send_telegram(body)
        print("telegram sent:", ok)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()


#!/usr/bin/env python3
# nobitex_daily_scan.py
# Daily volatility scan + TA for Nobitex (with Binance fallback).
# Outputs to ./nobitex_outputs/{YYYYMMDD}/

import os
import time
import math
from datetime import datetime, timedelta
import argparse
import json
import traceback

import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# Optional fallback to ccxt/Binance if Nobitex endpoints fail
try:
    import ccxt
    HAS_CCXT = True
except Exception:
    HAS_CCXT = False

# -----------------------
# Configuration (edit before run)
# -----------------------
NOBITEX_API_BASE = os.environ.get("NOBITEX_API_BASE", "https://api.nobitex.ir")  # adjust if needed
# Example public endpoints: (these depend on Nobitex public API availability)
# - markets list: /v2/market/symbols  (not guaranteed)
# - orderbook: /v2/orderbook/{symbol}
# - ticker/candles: Nobitex may not provide public candle endpoints; in that case use CSV or fallback
#
# If Nobitex public candle endpoint is unavailable, set USE_BINANCE_FALLBACK=True
USE_BINANCE_FALLBACK = True

QUOTE = "USDT"            # or "IRT" if you prefer rial pairs
TIMEFRAME = "4h"
VOL_WINDOW = 30          # how many candles used to compute volatility
LOOKBACK_DAYS = 14       # how many days of history to fetch (should cover VOL_WINDOW)
TOP_K = 8
MIN_VOLUME_USD = 5000    # minimal liquidity (USD) filter
OUTDIR = "nobitex_outputs"
PLOT_DIRNAME = "plots"
SUMMARY_FILENAME = "summary.csv"
SIGNAL_FILENAME = "signals.txt"
TELEGRAM_SEND = False    # set True and export TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID env vars to enable

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
# Nobitex: market list & candles (best-effort)
# -----------------------
def nobitex_list_markets():
    """
    Try to get list of symbols from Nobitex public endpoints.
    If not available return empty list (caller may fallback to ccxt).
    """
    try:
        # try common public endpoints (best-effort)
        # many Nobitex deployments expose a markets endpoint under /v2/market/symbols or /v2/symbols
        candidates = [
            f"{NOBITEX_API_BASE}/v2/market/symbols",
            f"{NOBITEX_API_BASE}/v2/symbols",
            f"{NOBITEX_API_BASE}/markets",
            f"{NOBITEX_API_BASE}/market/symbols"
        ]
        for url in candidates:
            try:
                r = requests.get(url, timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    # try to extract symbol list in various shapes
                    syms = []
                    if isinstance(data, dict):
                        # look for keys
                        for k in ("symbols","data","result","markets"):
                            if k in data and isinstance(data[k], (list,dict)):
                                container = data[k]
                                if isinstance(container, list):
                                    for it in container:
                                        # try fields common: symbol, name, base, quote
                                        if isinstance(it, dict):
                                            s = it.get("symbol") or it.get("name") or it.get("pair")
                                            if s:
                                                syms.append(s.replace("-", "/"))
                                elif isinstance(container, dict):
                                    syms.extend([k.replace("-", "/") for k in container.keys()])
                    elif isinstance(data, list):
                        for it in data:
                            if isinstance(it, dict):
                                s = it.get("symbol") or it.get("name") or it.get("pair")
                                if s:
                                    syms.append(s.replace("-", "/"))
                    syms = sorted(set(syms))
                    if syms:
                        return syms
            except Exception:
                continue
    except Exception:
        pass
    return []

def nobitex_fetch_ohlcv(symbol, timeframe="4h", since_days=LOOKBACK_DAYS):
    """
    Best-effort: try known endpoints to obtain OHLCV from Nobitex public API.
    Many local exchanges do not expose candle endpoints; in that case this returns None.
    The function returns a DataFrame with Date, Open, High, Low, Close, Volume or None.
    """
    # try hypothetical candlestick endpoints
    candidates = [
        f"{NOBITEX_API_BASE}/v2/market/candles/{symbol}/{timeframe}",
        f"{NOBITEX_API_BASE}/v2/candles/{symbol}/{timeframe}",
        f"{NOBITEX_API_BASE}/candles/{symbol}/{timeframe}",
        f"{NOBITEX_API_BASE}/v1/market/candles/{symbol}/{timeframe}"
    ]
    for url in candidates:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                continue
            data = r.json()
            # try common payload shapes
            rows = []
            if isinstance(data, dict):
                # find arrays named candles, data, result
                for key in ("candles","data","result","ohlcv"):
                    if key in data and isinstance(data[key], list):
                        rows = data[key]
                        break
                # sometimes payload is {"data": {"candles": [...]}}
                if not rows:
                    for key in ("data","result"):
                        if key in data and isinstance(data[key], dict):
                            for k2 in ("candles","ohlcv","data"):
                                if k2 in data[key] and isinstance(data[key][k2], list):
                                    rows = data[key][k2]
                                    break
            elif isinstance(data, list):
                rows = data
            # parse rows guessing [ts,open,high,low,close,volume] or dicts
            if not rows:
                continue
            parsed = []
            for rrow in rows:
                if isinstance(rrow, list) and len(rrow) >= 6:
                    ts = int(rrow[0])
                    open_, high, low, close, vol = map(float, rrow[1:6])
                    parsed.append((ts, open_, high, low, close, vol))
                elif isinstance(rrow, dict):
                    # expect keys like t,o,h,l,c,v
                    ts = int(rrow.get("t") or rrow.get("timestamp") or rrow.get("time") or rrow.get("date") or 0)
                    open_ = safe_float(rrow.get("o") or rrow.get("open"))
                    high = safe_float(rrow.get("h") or rrow.get("high"))
                    low = safe_float(rrow.get("l") or rrow.get("low"))
                    close = safe_float(rrow.get("c") or rrow.get("close"))
                    vol = safe_float(rrow.get("v") or rrow.get("volume"))
                    if ts and not math.isnan(open_):
                        parsed.append((ts, open_, high, low, close, vol))
            if parsed:
                df = pd.DataFrame(parsed, columns=["ts","Open","High","Low","Close","Volume"])
                df["Date"] = pd.to_datetime(df["ts"], unit="ms")
                df = df.drop(columns=["ts"]).sort_values("Date").reset_index(drop=True)
                for c in ["Open","High","Low","Close","Volume"]:
                    df[c] = pd.to_numeric(df[c], errors="coerce")
                return df
        except Exception:
            continue
    # no candle endpoint available
    return None

# -----------------------
# Binance fallback via ccxt (if enabled)
# -----------------------
def binance_fetch_ohlcv(symbol, timeframe="4h", since_days=LOOKBACK_DAYS):
    if not HAS_CCXT:
        return None
    try:
        ex = ccxt.binance({"enableRateLimit": True})
        since_ms = ex.milliseconds() - int(since_days * 24 * 60 * 60 * 1000)
        data = ex.fetch_ohlcv(symbol, timeframe=timeframe, since=since_ms, limit=1000)
        if not data:
            return None
        df = pd.DataFrame(data, columns=["ts","Open","High","Low","Close","Volume"])
        df["Date"] = pd.to_datetime(df["ts"], unit="ms")
        df = df.drop(columns=["ts"]).sort_values("Date").reset_index(drop=True)
        for c in ["Open","High","Low","Close","Volume"]:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        return df
    except Exception:
        return None

# -----------------------
# Volatility and indicators
# -----------------------
def compute_volatility(df, window=VOL_WINDOW):
    if df is None or len(df) < 5:
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

    # support projection
    if fits is not None:
        trough_slope, trough_int = fits["trough_fit"]
        idx = len(df)-1
        support_proj = trough_slope * idx + trough_int
    else:
        support_proj = bbl

    recent_vol = df["Volume"].tail(12).mean()
    if recent_vol * price < MIN_VOLUME_USD:
        signal["reason"] = "low_liquidity"
        return signal

    # Long condition (short-term intraday)
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
# Plotting
# -----------------------
def plot_symbol(df, symbol, fits, outpath):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["Date"], open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name=symbol
    ))
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
# Telegram support
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
# Main
# -----------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=now_tag())
    parser.add_argument("--topk", type=int, default=TOP_K)
    parser.add_argument("--timeframe", default=TIMEFRAME)
    args = parser.parse_args()

    tag = args.date
    outdir = os.path.join(OUTDIR, tag)
    plots_dir = os.path.join(outdir, PLOT_DIRNAME)
    ensure_dir(outdir); ensure_dir(plots_dir)

    # 1) list symbols (try Nobitex first)
    symbols = []
    try:
        symbols = nobitex_list_markets()
    except Exception:
        symbols = []
    if not symbols and HAS_CCXT and USE_BINANCE_FALLBACK:
        # fallback to binance spot USDT pairs (useful for testing)
        try:
            ex = ccxt.binance({"enableRateLimit": True})
            ex.load_markets()
            symbols = [s for s,m in ex.markets.items() if m.get("quote") and m["quote"].upper() == QUOTE and m.get("spot",False)]
        except Exception:
            symbols = []
    if not symbols:
        print("No symbols found on Nobitex and no fallback available. Exiting.")
        return

    print(f"Symbols count: {len(symbols)} (scanning volatility...)")

    vol_list = []
    for s in symbols:
        try:
            # fetch candles: try Nobitex then Binance fallback
            df = nobitex_fetch_ohlcv(s, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None and HAS_CCXT and USE_BINANCE_FALLBACK:
                df = binance_fetch_ohlcv(s, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None or len(df) < 12:
                continue
            vol = compute_volatility(df, window=VOL_WINDOW)
            last_price = float(df["Close"].iloc[-1])
            recent_vol = float(df["Volume"].tail(12).mean())
            vol_usd = recent_vol * last_price
            if np.isnan(vol) or vol_usd < MIN_VOLUME_USD:
                continue
            vol_list.append((s, vol, last_price, vol_usd))
            # be polite with rate limits
            time.sleep(0.12)
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
            df = nobitex_fetch_ohlcv(sym, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None and HAS_CCXT and USE_BINANCE_FALLBACK:
                df = binance_fetch_ohlcv(sym, timeframe=args.timeframe, since_days=LOOKBACK_DAYS)
            if df is None or len(df) < 20:
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

    # save outputs
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


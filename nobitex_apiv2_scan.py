#!/usr/bin/env python3
# nobitex_apiv2_scan.py
# Nobitex apiv2 (v3) volatility scan for USDT pairs.
# Usage:
# export NOBITEX_TOKEN="your_token_here"
# python nobitex_apiv2_scan.py

import os
import time
import math
import json
import traceback
from datetime import datetime, timedelta

import requests
import pandas as pd
import numpy as np
import plotly.graph_objects as go

# -----------------------
# Config
# -----------------------
API_BASE = os.environ.get("NOBITEX_API_BASE", "https://apiv2.nobitex.ir")
TOKEN = os.environ.get("NOBITEX_TOKEN", "7fecf5964c24766fd64c4be370c293568aa52354")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
TIMEFRAME_MINUTES = 240
LOOKBACK_DAYS = 14
VOL_WINDOW = 30
TOP_K = 8
MIN_VOLUME_USD = 5000
OUTDIR = "nobitex_outputs"
PLOT_DIR = "plots"
SUMMARY_FILENAME = "summary.csv"
SIGNAL_FILENAME = "signals.txt"

# Static list of USDT pairs on Nobitex — ویرایش کن اگر لیست دقیق‌تری داری
STATIC_USDT_SYMBOLS = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "LTCUSDT", "BNBUSDT",
    "SOLUSDT", "MATICUSDT", "ADAUSDT", "DOGEUSDT", "DOTUSDT",
    "ZECUSDT", "LINKUSDT", "TRXUSDT", "AVAXUSDT", "AAVEUSDT"
]
# اگر می‌خواهی از لیست استاتیک استفاده شود:
FORCE_STATIC_SYMBOLS = True

# -----------------------
# Helpers
# -----------------------
def ensure_dir(p):
    os.makedirs(p, exist_ok=True)

def now_tag():
    return datetime.utcnow().strftime("%Y%m%d")

def safe_float(x):
    try:
        return float(x)
    except:
        return np.nan

# -----------------------
# Nobitex apiv2 endpoints (v3)
# - orderbook: /v3/orderbook/{symbol}
# - trades: /v3/trades/{symbol}
# -----------------------
def apiv2_orderbook(symbol):
    url = f"{API_BASE}/v3/orderbook/{symbol}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def apiv2_trades(symbol):
    url = f"{API_BASE}/v3/trades/{symbol}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def trades_to_ohlcv_from_apiv2(trades_json, timeframe_minutes=TIMEFRAME_MINUTES, lookback_days=LOOKBACK_DAYS):
    """
    Convert apiv2 trades payload to OHLCV DataFrame aggregated per timeframe_minutes.
    Accepts common Nobitex shapes: list of [price, amount, timestamp] or dicts with keys.
    """
    rows = []
    if trades_json is None:
        return None
    # expect either {"trades": [...]} or list
    candidates = []
    if isinstance(trades_json, dict):
        for k in ("trades","data","result"):
            if k in trades_json and isinstance(trades_json[k], list):
                candidates = trades_json[k]; break
        if not candidates:
            # maybe top-level list in some key
            for v in trades_json.values():
                if isinstance(v, list):
                    candidates = v; break
    elif isinstance(trades_json, list):
        candidates = trades_json

    if not candidates:
        return None

    for t in candidates:
        # t could be list or dict
        if isinstance(t, list) and len(t) >= 3:
            # try many orders: [price, amount, timestamp] or [timestamp, price, amount]
            a0, a1, a2 = t[0], t[1], t[2]
            # guess timestamp is large integer (>1e12 ms)
            if isinstance(a2, (int,float)) and a2 > 1e12:
                ts = int(a2)
                price = safe_float(a0)
                vol = safe_float(a1)
            elif isinstance(a0, (int,float)) and a0 > 1e12:
                ts = int(a0)
                price = safe_float(a1)
                vol = safe_float(a2)
            else:
                # fallback
                continue
            rows.append((ts, price, vol))
        elif isinstance(t, dict):
            # common keys: t,timestamp,time,date ; p,price ; q,qty,amount,volume
            ts = None
            for tk in ("t","timestamp","time","date"):
                if tk in t:
                    try:
                        ts = int(t[tk]); break
                    except Exception:
                        pass
            price = None
            for pk in ("p","price","rate"):
                if pk in t:
                    price = safe_float(t[pk]); break
            vol = None
            for vk in ("q","qty","amount","volume","v"):
                if vk in t:
                    vol = safe_float(t[vk]); break
            if ts and price is not None:
                # ensure ms
                if ts < 1e12:
                    ts = int(ts * 1000)
                rows.append((ts, price, vol or 0.0))

    if not rows:
        return None

    df = pd.DataFrame(rows, columns=["ts","price","vol"])
    df["DateTime"] = pd.to_datetime(df["ts"], unit="ms")
    cutoff = datetime.utcnow() - timedelta(days=lookback_days)
    df = df[df["DateTime"] >= pd.Timestamp(cutoff)]
    if df.empty:
        return None

    df.set_index("DateTime", inplace=True)
    period = f"{timeframe_minutes}min"
    o = df["price"].resample(period).ohlc()
    v = df["vol"].resample(period).sum()
    ohlcv = o.join(v).dropna().reset_index()
    ohlcv.rename(columns={"open":"Open","high":"High","low":"Low","close":"Close","vol":"Volume"}, inplace=True)
    # ensure numeric
    for c in ["Open","High","Low","Close","Volume"]:
        if c in ohlcv.columns:
            ohlcv[c] = pd.to_numeric(ohlcv[c], errors="coerce")
    if len(ohlcv) < 3:
        return None
    return ohlcv

# -----------------------
# Indicators & signals (same logic as before)
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
        peaks = peaks[-n_points:]; troughs = troughs[-n_points:]
        xi_p = np.array([p[0] for p in peaks]); yi_p = np.array([p[1] for p in peaks])
        xi_t = np.array([t[0] for t in troughs]); yi_t = np.array([t[1] for t in troughs])
        try:
            slope_p, intercept_p = np.polyfit(xi_p, yi_p, 1)
            slope_t, intercept_t = np.polyfit(xi_t, yi_t, 1)
            return {"peak_fit":(slope_p, intercept_p), "trough_fit":(slope_t, intercept_t), "peaks":peaks, "troughs":troughs}
        except Exception:
            return None
    return None

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
    fig.update_layout(title=f"{symbol} — {TIMEFRAME_MINUTES}m TA", template="plotly_white", xaxis_rangeslider_visible=False)
    fig.write_html(outpath)

# -----------------------
# Main
# -----------------------
def main():
    date_tag = now_tag()
    outdir = f"{OUTDIR}/{date_tag}"
    plots_dir = f"{outdir}/{PLOT_DIR}"
    ensure_dir(outdir); ensure_dir(plots_dir)

    if FORCE_STATIC_SYMBOLS:
        symbols = STATIC_USDT_SYMBOLS
    else:
        # try discover symbols via orderbook v3 listing or other endpoints (not guaranteed)
        symbols = STATIC_USDT_SYMBOLS

    vol_list = []
    for sym in symbols:
        try:
            # try trades endpoint first
            tj = apiv2_trades(sym)
            ohlcv = trades_to_ohlcv_from_apiv2(tj, timeframe_minutes=TIMEFRAME_MINUTES, lookback_days=LOOKBACK_DAYS)
            if ohlcv is None:
                # fallback: use orderbook to get lastTradePrice as a single-point series (not ideal)
                ob = apiv2_orderbook(sym)
                if ob and isinstance(ob, dict) and "lastTradePrice" in ob:
                    price_raw = safe_float(ob.get("lastTradePrice"))
                    if not math.isnan(price_raw):
                        # create tiny synthetic ohlcv with last price (not useful for volatility but prevents crash)
                        now = pd.Timestamp.utcnow().floor(f"{TIMEFRAME_MINUTES}min")
                        df = pd.DataFrame({
                            "Date":[now - pd.Timedelta(minutes=TIMEFRAME_MINUTES*i) for i in range(6)][::-1],
                            "Open":[price_raw]*6,"High":[price_raw]*6,"Low":[price_raw]*6,"Close":[price_raw]*6,"Volume":[0.0]*6
                        })
                        ohlcv = df
            if ohlcv is None or len(ohlcv) < 6:
                continue
            vol = compute_volatility(ohlcv, window=VOL_WINDOW)
            last_price = float(ohlcv["Close"].iloc[-1])
            recent_vol = float(ohlcv["Volume"].tail(12).mean()) if "Volume" in ohlcv.columns else 0.0
            vol_usd = recent_vol * last_price
            if np.isnan(vol) or vol_usd < MIN_VOLUME_USD:
                continue
            vol_list.append((sym, vol, last_price, vol_usd))
            time.sleep(0.12)
        except Exception:
            continue

    if not vol_list:
        print("No volatile symbols found after filtering.")
        return

    vol_df = pd.DataFrame(vol_list, columns=["symbol","vol","last_price","vol_usd"]).sort_values("vol", ascending=False)
    topk = vol_df.head(TOP_K)
    topk.to_csv(os.path.join(outdir, "vol_sorted.csv"), index=False)

    summary_rows = []
    signals = []
    for _, r in topk.iterrows():
        sym = r["symbol"]
        try:
            tj = apiv2_trades(sym)
            ohlcv = trades_to_ohlcv_from_apiv2(tj, timeframe_minutes=TIMEFRAME_MINUTES, lookback_days=LOOKBACK_DAYS)
            if ohlcv is None or len(ohlcv) < 12:
                continue
            df = add_indicators(ohlcv)
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
    summary_df.to_csv(os.path.join(outdir, SUMMARY_FILENAME), index=False)
    with open(os.path.join(outdir, SIGNAL_FILENAME), "w", encoding="utf-8") as f:
        if signals:
            f.write("\n".join(signals))
        else:
            f.write("No actionable short-term signals found.\n")

    print("Wrote outputs to", outdir)
    if signals:
        print("Signals:\n", "\n".join(signals))

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()


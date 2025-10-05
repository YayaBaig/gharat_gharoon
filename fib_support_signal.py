#!/usr/bin/env python3
# fib_support_signal.py
# تحلیل فیبوناچی + حمایت/مقاومت + order-block + MA50 و تولید سیگنال به همراه HTML تعاملی
# اجرا: python fib_support_signal.py --symbol BTCUSDT --capital 1000 --nobitex-token "..." 

import os, time, argparse, ast
from datetime import datetime, timedelta
import requests
import numpy as np
import pandas as pd
from scipy.signal import argrelextrema
import plotly.graph_objects as go
from plotly.subplots import make_subplots

API_BASE = "https://apiv2.nobitex.ir"
OHLC_PATH = "/market/udf/history"
REQUEST_DELAY = 0.12

def fetch_ohlc_nobitex(symbol, resolution, frm, to, token=None, timeout=12):
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(int(frm)), "to": str(int(to))}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(API_BASE + OHLC_PATH, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ohlc_to_df(j):
    if not isinstance(j, dict) or not all(k in j for k in ("t","o","c","h","l","v")):
        return None
    df = pd.DataFrame({"t": j["t"], "Open": j["o"], "High": j["h"], "Low": j["l"], "Close": j["c"], "Volume": j["v"]})
    df["Date"] = pd.to_datetime(df["t"], unit="s")
    df = df[["Date","Open","High","Low","Close","Volume"]]
    for c in ["Open","High","Low","Close","Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

def ma(df, n=50):
    return df["Close"].ewm(span=n, adjust=False).mean() if len(df)>=n else df["Close"].rolling(window=min(len(df),n)).mean()

def find_last_swing(df, kind="peak", order=3):
    # kind: 'peak' or 'trough' — find local max/min indices
    if kind=="peak":
        idx = argrelextrema(df["High"].values, np.greater_equal, order=order)[0]
    else:
        idx = argrelextrema(df["Low"].values, np.less_equal, order=order)[0]
    return idx

def fib_levels(a, b):
    diff = b - a
    return {
        "0": a,
        "0.236": b - 0.236*diff,
        "0.382": b - 0.382*diff,
        "0.5": b - 0.5*diff,
        "0.618": b - 0.618*diff,
        "0.786": b - 0.786*diff,
        "1": b
    }

def detect_order_block(df15):
    # approximate: find last 3-candle engulfing or high-volume pivot as order block
    # here we detect last bearish engulfing (for potential support on pullback)
    for i in range(len(df15)-3, 2, -1):
        c0 = df15.iloc[i-2]; c1 = df15.iloc[i-1]; c2 = df15.iloc[i]
        # bullish order block: prior down move then strong up engulfing
        if (c0["Close"] < c0["Open"]) and (c1["Close"] > c1["Open"]) and (c1["Close"] > c0["Open"]) and (c1["Open"] < c0["Close"]):
            return {"type":"bullish","index":i-1,"price":c1["Close"]}
    return None

def analyze_and_signal(symbol, token=None, capital=1000, use_local=None):
    now = datetime.utcnow()
    to_ts = int(now.timestamp())
    from_ts_72h = int((now - timedelta(hours=72)).timestamp())
    # fetch 1D, 4H, 1H, 15m
    dfs = {}
    for res, label in [("D","1D"), ("240","4H"), ("60","1H"), ("15","15m")]:
        if use_local and use_local.get(label):
            dfs[label] = pd.read_csv(use_local[label], parse_dates=["Date"])
        else:
            j = fetch_ohlc_nobitex(symbol, res, from_ts_72h if res!="D" else int((now - timedelta(days=30)).timestamp()), to_ts, token=token)
            dfs[label] = ohlc_to_df(j)
            time.sleep(REQUEST_DELAY)
    # daily prev candle high/low
    df1d = dfs["1D"].dropna().reset_index(drop=True)
    if df1d is None or len(df1d)<2:
        raise ValueError("Not enough 1D data")
    prev = df1d.iloc[-2]
    daily_high = float(prev["High"]); daily_low = float(prev["Low"])
    # trend by MA50 on 4H and 1H (compare last close to MA50)
    df4h = dfs["4H"].dropna().reset_index(drop=True)
    df1h = dfs["1H"].dropna().reset_index(drop=True)
    ma50_4h = ma(df4h,50).iloc[-1] if len(df4h)>0 else np.nan
    ma50_1h = ma(df1h,50).iloc[-1] if len(df1h)>0 else np.nan
    trend_4h = "up" if df4h["Close"].iloc[-1] > ma50_4h else "down"
    trend_1h = "up" if df1h["Close"].iloc[-1] > ma50_1h else "down"
    # 15m: find recent swing (use last local trough if overall short-term up)
    df15 = dfs["15m"].dropna().reset_index(drop=True)
    if df15 is None or len(df15)<8:
        raise ValueError("Not enough 15m data")
    # determine direction of last move: compare last close to close 48 candles before
    short_dir = "up" if df15["Close"].iloc[-1] > df15["Close"].iloc[-48 if len(df15)>48 else 0] else "down"
    # find swing: if up, take last trough then peak; if down, take last peak then trough
    if short_dir=="up":
        trough_idx = find_last_swing(df15, kind="trough", order=3)
        peak_idx = find_last_swing(df15, kind="peak", order=3)
        if len(trough_idx)==0 or len(peak_idx)==0:
            # fallback: use min and max of recent window
            window = df15.iloc[-48:]
            a = float(window["Low"].min()); b = float(window["High"].max())
        else:
            a = float(df15["Low"].iloc[trough_idx[-1]])
            b = float(df15["High"].iloc[peak_idx[peak_idx>trough_idx[-1]][-1]]) if any(peak_idx>trough_idx[-1]) else float(df15["High"].iloc[-1])
    else:
        peak_idx = find_last_swing(df15, kind="peak", order=3)
        trough_idx = find_last_swing(df15, kind="trough", order=3)
        if len(peak_idx)==0 or len(trough_idx)==0:
            window = df15.iloc[-48:]
            a = float(window["High"].max()); b = float(window["Low"].min())
        else:
            a = float(df15["High"].iloc[peak_idx[-1]])
            b = float(df15["Low"].iloc[trough_idx[trough_idx>peak_idx[-1]][-1]]) if any(trough_idx>peak_idx[-1]) else float(df15["Low"].iloc[-1])
    # ensure a is low and b is high for fib calc if short_dir=='up'
    if short_dir=="up" and a>b:
        a,b = b,a
    if short_dir=="down" and a<b:
        a,b = b,a
    fibs = fib_levels(a,b)
    # range of interest: fib 0.5 to 0.618
    low_zone = fibs["0.618"] if short_dir=="up" else fibs["0.382"]
    high_zone = fibs["0.5"] if short_dir=="up" else fibs["0.618"]
    # check last few candles for pullback into zone then rejection (entry candle is bullish after touch)
    last_close = float(df15["Close"].iloc[-1])
    # detect touch: some candle had close inside zone then price pulled back and now candle moved away (simple heuristic)
    touched = any((df15["Low"].iloc[-6:] <= high_zone) & (df15["High"].iloc[-6:] >= low_zone))
    pullback_confirm = False
    entry_price = None
    stop_price = None
    target_price = None
    # moving 50 on 15m to confirm momentum
    ma50_15 = ma(df15,50).iloc[-1] if len(df15)>0 else np.nan
    ma50_confirm = True if (short_dir=="up" and df15["Close"].iloc[-1] > ma50_15) or (short_dir=="down" and df15["Close"].iloc[-1] < ma50_15) else False
    # find last candle that closed after touching zone as possible entry (bullish candle)
    for i in range(len(df15)-6, len(df15)):
        if i<0: continue
        c = df15.iloc[i]
        if short_dir=="up":
            if (c["Low"] <= high_zone and c["High"] >= low_zone) and (i+1 < len(df15)):
                nextc = df15.iloc[i+1]
                if nextc["Close"] > nextc["Open"]:  # bullish confirmation
                    pullback_confirm = True
                    entry_price = float(nextc["Close"])
                    stop_price = float(fibs["0.786"])
                    target_price = float(fibs["1"])
                    break
        else:
            if (c["High"] >= low_zone and c["Low"] <= high_zone) and (i+1 < len(df15)):
                nextc = df15.iloc[i+1]
                if nextc["Close"] < nextc["Open"]:
                    pullback_confirm = True
                    entry_price = float(nextc["Close"])
                    stop_price = float(fibs["0.786"])
                    target_price = float(fibs["1"])
                    break
    # also check daily high/low as support/resistance zone: entry should not be beyond strong resistance for long
    daily_ok = True
    if short_dir=="up" and entry_price and entry_price > daily_high:
        daily_ok = False
    if short_dir=="down" and entry_price and entry_price < daily_low:
        daily_ok = False
    # final signal conditions
    signal = {"side":"none", "reason":"nomatch"}
    if pullback_confirm and ma50_confirm and daily_ok:
        signal = {"side":"long" if short_dir=="up" else "short",
                  "entry": round(entry_price, 8),
                  "stop": round(stop_price, 8),
                  "target": round(target_price, 8),
                  "reason":"fib50-61.8 pullback + MA50 + daily check",
                  "trend_4h":trend_4h,"trend_1h":trend_1h}
    # prepare plot
    html_file = f"{symbol}_fib_signal.html"
    build_plot(symbol, df15, dfs, fibs, entry_price, stop_price, target_price, html_file)
    # explanation text (fa)
    explanation = []
    explanation.append(f"نماد: {symbol}")
    explanation.append(f"روند 4H: {trend_4h} (MA50={round(ma50_4h,2)}) ; روند 1H: {trend_1h} (MA50={round(ma50_1h,2)})")
    explanation.append(f"سقف/کف کندل روز قبل: high={daily_high} ; low={daily_low}")
    explanation.append(f"جهت موج 15m: {short_dir} ؛ سطوح فیبوناچی از {a} تا {b}")
    if signal["side"]!="none":
        explanation.append(f"سیگنال: {signal['side'].upper()} entry={signal['entry']} stop={signal['stop']} target={signal['target']}")
    else:
        explanation.append("سیگنال معتبر تولید نشد.")
    return {"signal":signal,"explanation":"\n".join(explanation),"html":html_file, "fibs":fibs}

def build_plot(symbol, df15, dfs_all, fibs, entry, stop, target, out_html):
    # create subplot: 15m candlestick + 1H mini MA overlay info
    n = 1
    fig = make_subplots(rows=n, cols=1, shared_xaxes=True, subplot_titles=[f"{symbol} 15m — Fibonacci & MA50"])
    if df15 is not None and len(df15)>0:
        fig.add_trace(go.Candlestick(x=df15["Date"], open=df15["Open"], high=df15["High"], low=df15["Low"], close=df15["Close"], name="15m OHLC"), row=1, col=1)
        # MA50 on 15m
        ma50_15 = ma(df15,50)
        fig.add_trace(go.Scatter(x=df15["Date"], y=ma50_15, mode="lines", line=dict(color="orange"), name="MA50(15m)"), row=1, col=1)
        # fib lines
        x0 = df15["Date"].iloc[-1]
        for lvl, val in fibs.items():
            fig.add_hline(y=val, line=dict(color="gray", width=1, dash="dash"), annotation_text=f"Fib {lvl} = {round(val,8)}", annotation_position="top left")
        # markers
        if entry:
            fig.add_trace(go.Scatter(x=[x0], y=[entry], mode="markers+text", marker=dict(color="blue", size=10), text=[f"Entry {round(entry,8)}"], textposition="bottom center"), row=1, col=1)
        if stop:
            fig.add_trace(go.Scatter(x=[x0], y=[stop], mode="markers+text", marker=dict(color="red", size=8), text=[f"Stop {round(stop,8)}"], textposition="top center"), row=1, col=1)
        if target:
            fig.add_trace(go.Scatter(x=[x0], y=[target], mode="markers+text", marker=dict(color="green", size=8), text=[f"Target {round(target,8)}"], textposition="bottom center"), row=1, col=1)
    fig.update_layout(height=700, title_text=f"{symbol} — Fibonacci pullback analysis", showlegend=True)
    fig.write_html(out_html, include_plotlyjs='cdn')

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", required=True)
    p.add_argument("--capital", type=float, default=1000.0)
    p.add_argument("--nobitex-token", type=str, default=None)
    p.add_argument("--use-local-csv", nargs="*", help="optionally pass local CSV files for timeframes as: 1D=path 4H=path 1H=path 15m=path", default=None)
    args = p.parse_args()
    local = None
    if args.use_local_csv:
        local = {}
        for t in args.use_local_csv:
            k,v = t.split("=",1)
            local[k] = v
    out = analyze_and_signal(args.symbol, token=args.nobitex_token or os.environ.get("NOBITEX_TOKEN"), capital=args.capital, use_local=local)
    print(out["explanation"])
    print("Signal:", out["signal"])
    print("HTML:", out["html"])


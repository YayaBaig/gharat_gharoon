#!/usr/bin/env python3
# nobitex_scan_signals.py
# Scan USDT symbols on Nobitex (apiv2) using /market/udf/history OHLC endpoint,
# compute volatility + indicators, filter by volume, produce short-term signals,
# print top-5 volatile symbols with valid signals.

import os, time, math, argparse
from datetime import datetime, timedelta
import requests
import numpy as np
import pandas as pd

API_BASE = "https://apiv2.nobitex.ir/market/udf/history"
TOKEN = os.environ.get("NOBITEX_TOKEN", "")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}
TIMEFRAME = "60"            # 60 minutes
LOOKBACK_HOURS = 72
VOL_WINDOW = 30
MIN_VOLUME_USD = 5000
STATIC_SYMBOLS = [
    "BTCUSDT","ETHUSDT","XRPUSDT","LTCUSDT","BNBUSDT","SOLUSDT","MATICUSDT","ADAUSDT",
    "DOGEUSDT","DOTUSDT","ZECUSDT","LINKUSDT","TRXUSDT","AVAXUSDT","AAVEUSDT"
]

def unix_ts(dt):
    return int(dt.timestamp())

def fetch_ohlc(symbol, resolution, from_unix, to_unix, timeout=15):
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(from_unix), "to": str(to_unix)}
    r = requests.get(API_BASE, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ohlc_json_to_df(j):
    if not isinstance(j, dict) or not all(k in j for k in ("t","o","c","h","l","v")):
        return None
    df = pd.DataFrame({
        "t": j["t"], "Open": j["o"], "Close": j["c"], "High": j["h"], "Low": j["l"], "Volume": j["v"]
    })
    df["Date"] = pd.to_datetime(df["t"], unit="s")
    df = df[["Date","Open","High","Low","Close","Volume"]]
    for c in ["Open","High","Low","Close","Volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df

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
    return df.fillna(method="ffill").fillna(method="bfill")

def compute_volatility(df, window=VOL_WINDOW):
    if df is None or len(df) < 3:
        return np.nan
    close = df["Close"].astype(float)
    ret = np.log(close).diff().dropna()
    if ret.empty:
        return np.nan
    return float(ret.tail(window).std())

def detect_channel_support(df, n_points=6):
    highs = df["High"].values; lows = df["Low"].values
    L = len(df)
    peaks = []; troughs = []
    for i in range(2, L-2):
        if highs[i] == max(highs[i-2:i+3]): peaks.append((i, highs[i]))
        if lows[i] == min(lows[i-2:i+3]): troughs.append((i, lows[i]))
    if len(troughs) >= 2:
        troughs = troughs[-n_points:]
        xi = np.array([t[0] for t in troughs]); yi = np.array([t[1] for t in troughs])
        try:
            slope, intercept = np.polyfit(xi, yi, 1)
            return slope, intercept
        except Exception:
            return None
    return None

def generate_signal(df):
    last = df.iloc[-1]
    price = float(last["Close"])
    rsi = float(last["RSI_14"])
    macd = float(last["MACD"]); macd_sig = float(last["MACD_SIGNAL"])
    bbh = float(last["BB_H"]); bbl = float(last["BB_L"])
    recent_vol = float(df["Volume"].tail(12).mean()) if "Volume" in df.columns else 0.0
    if recent_vol * price < MIN_VOLUME_USD:
        return {"side":"none","reason":"low_liq"}
    support_proj = None
    fits = detect_channel_support(df)
    if fits:
        slope, intercept = fits
        idx = len(df)-1
        support_proj = slope * idx + intercept
    else:
        support_proj = bbl
    if price > support_proj * 0.995 and macd > macd_sig and 40 < rsi < 70:
        stop = float(min(support_proj * 0.98, price - price*0.012))
        target = float(price + max((price - stop)*1.8, price*0.015))
        return {"side":"long","entry":price,"stop":stop,"target":target,"reason":"macd+support+rsi"}
    if price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
        stop = float(price + price*0.012); target = float(price - price*0.018)
        return {"side":"short","entry":price,"stop":stop,"target":target,"reason":"bb_upper+macd_down"}
    return {"side":"none","reason":"nomatch"}

def scan_symbols(symbols):
    now = datetime.utcnow()
    from_unix = unix_ts(now - timedelta(hours=LOOKBACK_HOURS))
    to_unix = unix_ts(now)
    results = []
    for sym in symbols:
        try:
            resp = fetch_ohlc(sym, TIMEFRAME, from_unix, to_unix)
            df = ohlc_json_to_df(resp)
            if df is None or len(df) < 12:
                continue
            df = add_indicators(df)
            vol = compute_volatility(df)
            last_price = float(df["Close"].iloc[-1])
            recent_vol = float(df["Volume"].tail(12).mean())
            vol_usd = recent_vol * last_price
            if np.isnan(vol) or vol_usd < MIN_VOLUME_USD:
                continue
            sig = generate_signal(df)
            results.append({
                "symbol": sym,
                "last_price": last_price,
                "vol": vol,
                "vol_usd": vol_usd,
                "signal": sig
            })
            time.sleep(0.12)
        except Exception as e:
            # skip symbol on any error
            continue
    return results

def unix_ts(dt):
    return int(dt.timestamp())

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbols", nargs="*", help="list of symbols to scan; default: built-in static", default=STATIC_SYMBOLS)
    args = parser.parse_args()
    symbols = args.symbols if args.symbols else STATIC_SYMBOLS
    print("Scanning", len(symbols), "symbols from Nobitex (apiv2)...")
    res = scan_symbols(symbols)
    if not res:
        print("No volatile symbols found.")
        return
    df = pd.DataFrame(res).sort_values("vol", ascending=False)
    # filter only those with actionable signals
    df['has_signal'] = df['signal'].apply(lambda s: s.get('side') if isinstance(s, dict) else 'none')
    actionable = df[df['has_signal'] != 'none']
    if actionable.empty:
        print("No actionable signals found among high-volatility symbols.")
        print(df[['symbol','last_price','vol','vol_usd']].head(10).to_string(index=False))
        return
    out = actionable.head(5)
    print("Top actionable signals:")
    for _, row in out.iterrows():
        s = row['signal']
        print(f"{row['symbol']} | {s['side'].upper()} | entry={s['entry']:.2f} stop={s['stop']:.2f} target={s['target']:.2f} reason={s['reason']} | price={row['last_price']:.2f} vol_usd={row['vol_usd']:.1f} vol={row['vol']:.6f}")
    # optional: write CSV
    try:
        out2 = out.copy()
        out2['signal_side'] = out2['signal'].apply(lambda x: x.get('side'))
        out2['signal_reason'] = out2['signal'].apply(lambda x: x.get('reason'))
        out2['entry'] = out2['signal'].apply(lambda x: x.get('entry'))
        out2['stop'] = out2['signal'].apply(lambda x: x.get('stop'))
        out2['target'] = out2['signal'].apply(lambda x: x.get('target'))
        out2[['symbol','last_price','vol','vol_usd','signal_side','signal_reason','entry','stop','target']].to_csv("nobitex_scan_results.csv", index=False)
        print("Wrote nobitex_scan_results.csv")
    except Exception:
        pass

if __name__ == "__main__":
    main()


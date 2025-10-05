#!/usr/bin/env python3
# nobitex_ohlc_scan_apiv2.py
import os, sys, argparse, requests
from datetime import datetime, timedelta
import pandas as pd, numpy as np

API_BASE = "https://apiv2.nobitex.ir/market/udf/history"
TOKEN = os.environ.get("NOBITEX_TOKEN","")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

def unix_ts(dt):
    return int(dt.timestamp())

def fetch_ohlc(symbol, resolution, from_unix, to_unix):
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(from_unix), "to": str(to_unix)}
    r = requests.get(API_BASE, params=params, headers=HEADERS, timeout=15)
    r.raise_for_status()
    return r.json()

def ohlc_json_to_df(j):
    for k in ("t","o","c","h","l","v"):
        if k not in j:
            raise ValueError("Missing key "+k)
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
    ma20 = df["Close"].rolling(20).mean(); std20 = df["Close"].rolling(20).std()
    df["BB_H"] = ma20 + 2 * std20; df["BB_L"] = ma20 - 2 * std20
    return df.fillna(method="ffill").fillna(method="bfill")

def generate_signal(df, min_volume_usd=5000):
    if df is None or len(df) < 3: return {"side":"none","reason":"no_data"}
    last = df.iloc[-1]
    price = float(last["Close"]); rsi = float(last["RSI_14"])
    macd = float(last["MACD"]); macd_sig = float(last["MACD_SIGNAL"])
    bbh = float(last["BB_H"]); bbl = float(last["BB_L"])
    recent_vol = float(df["Volume"].tail(12).mean()) if "Volume" in df.columns else 0.0
    if recent_vol * price < min_volume_usd: return {"side":"none","reason":"low_liq"}
    support = bbl
    if price > support * 0.995 and macd > macd_sig and 40 < rsi < 70:
        stop = float(min(support * 0.98, price - price*0.012))
        target = float(price + max((price - stop)*1.8, price*0.015))
        return {"side":"long","entry":price,"stop":stop,"target":target,"reason":"macd+support+rsi"}
    if price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
        stop = float(price + price*0.012); target = float(price - price*0.018)
        return {"side":"short","entry":price,"stop":stop,"target":target,"reason":"bb_upper+macd_down"}
    return {"side":"none","reason":"nomatch"}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--symbol", default="ZECUSDT")
    p.add_argument("--resolution", default="60")
    p.add_argument("--from-hrs", type=float, default=72)
    args = p.parse_args()

    from_unix = unix_ts(datetime.utcnow() - timedelta(hours=args.from_hrs))
    to_unix = unix_ts(datetime.utcnow())

    try:
        resp = fetch_ohlc(args.symbol, args.resolution, from_unix, to_unix)
    except requests.exceptions.RequestException as e:
        print("Request failed:", e); sys.exit(1)

    try:
        df = ohlc_json_to_df(resp)
    except Exception as e:
        print("Failed to parse OHLC response:", e); print("Raw response:", resp); sys.exit(1)

    if df.empty:
        print("No OHLC data returned"); sys.exit(0)

    df = add_indicators(df)
    sig = generate_signal(df)
    print("Symbol:", args.symbol); print("Candles fetched:", len(df))
    print(df.tail(5).to_string(index=False))
    print("Signal:", sig)

if __name__ == "__main__":
    main()


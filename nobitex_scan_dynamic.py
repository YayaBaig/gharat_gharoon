#!/usr/bin/env python3
# nobitex_scan_dynamic.py
# Dynamic discovery of USDT symbols via orderbook + OHLC scan (Nobitex apiv2)

import os, time, argparse, requests
from datetime import datetime, timedelta
import pandas as pd, numpy as np

# Config
BASE_URL = "https://apiv2.nobitex.ir"
ORDERBOOK_PATH = "/v3/orderbook/{}"
OHLC_PATH = "/market/udf/history"
COMMON_CANDIDATES = [
    "BTCUSDT","ETHUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","TRXUSDT","LTCUSDT",
    "BNBUSDT","SOLUSDT","MATICUSDT","DOTUSDT","ZECUSDT","LINKUSDT","AVAXUSDT","AAVEUSDT"
]
RESOLUTION = "60"   # 60 => 1h
LOOKBACK_HOURS = 72
MIN_VOLUME_USD = 5000
REQUEST_DELAY = 0.12
TOKEN = os.environ.get("NOBITEX_TOKEN","")
HEADERS = {"Authorization": f"Bearer {TOKEN}"} if TOKEN else {}

# Helpers
def check_symbol_valid(symbol, timeout=8):
    url = BASE_URL + ORDERBOOK_PATH.format(symbol)
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            j = r.json()
            if isinstance(j, dict) and ("lastTradePrice" in j or "last_trade_price" in j or "lastPrice" in j):
                return True
    except Exception:
        pass
    return False

def fetch_ohlc(symbol, resolution, from_unix, to_unix, timeout=12):
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(from_unix), "to": str(to_unix)}
    url = BASE_URL + OHLC_PATH
    r = requests.get(url, params=params, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ohlc_json_to_df(j):
    # expects keys t,o,c,h,l,v as lists (times in seconds)
    if not isinstance(j, dict) or not all(k in j for k in ("t","o","c","h","l","v")):
        return None
    df = pd.DataFrame({
        "t": j["t"], "Open": j["o"], "Close": j["c"],
        "High": j["h"], "Low": j["l"], "Volume": j["v"]
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

def compute_volatility(df):
    if df is None or len(df) < 3:
        return np.nan
    close = df["Close"].astype(float)
    ret = np.log(close).diff().dropna()
    return float(ret.std()) if len(ret) > 2 else np.nan

def detect_trough_fit(df, n_points=6):
    highs = df["High"].values; lows = df["Low"].values
    L = len(df)
    troughs = []
    for i in range(2, L-2):
        if lows[i] == min(lows[i-2:i+3]):
            troughs.append((i, lows[i]))
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
    if df is None or len(df) < 12:
        return {"side":"none","reason":"no_data"}
    last = df.iloc[-1]
    price = float(last["Close"])
    rsi = float(last["RSI_14"])
    macd = float(last["MACD"]); macd_sig = float(last["MACD_SIGNAL"])
    bbh = float(last["BB_H"]); bbl = float(last["BB_L"])
    recent_vol = float(df["Volume"].tail(12).mean())
    if recent_vol * price < MIN_VOLUME_USD:
        return {"side":"none","reason":"low_liq"}
    trough_fit = detect_trough_fit(df)
    support_proj = (trough_fit[0] * (len(df)-1) + trough_fit[1]) if trough_fit is not None else bbl
    if price > support_proj * 0.995 and macd > macd_sig and 40 < rsi < 70:
        stop = float(min(support_proj * 0.98, price - price*0.012))
        target = float(price + max((price - stop)*1.8, price*0.015))
        return {"side":"long","entry":price,"stop":stop,"target":target,"reason":"macd+support+rsi"}
    if price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
        stop = float(price + price*0.012); target = float(price - price*0.018)
        return {"side":"short","entry":price,"stop":stop,"target":target,"reason":"bb_upper+macd_down"}
    return {"side":"none","reason":"nomatch"}

def discover_valid_symbols(candidates):
    valid = []
    for s in candidates:
        ok = check_symbol_valid(s)
        if ok:
            valid.append(s)
        time.sleep(REQUEST_DELAY)
    return valid

def unix_ts(dt):
    return int(dt.timestamp())

def scan_symbols(symbols, resolution=RESOLUTION, lookback_hours=LOOKBACK_HOURS):
    now = datetime.utcnow()
    frm = unix_ts(now - timedelta(hours=lookback_hours))
    to = unix_ts(now)
    results = []
    for sym in symbols:
        try:
            resp = fetch_ohlc(sym, resolution, frm, to)
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
        except Exception:
            continue
        time.sleep(REQUEST_DELAY)
    return results

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidates", nargs="*", help="candidate symbols to test (default: built-in list)", default=COMMON_CANDIDATES)
    args = parser.parse_args()

    candidates = args.candidates
    print("Discovering valid symbols from candidates:", candidates)
    valid = discover_valid_symbols(candidates)
    if not valid:
        print("No valid symbols discovered via orderbook. Check network/token.")
        return
    print("Valid symbols:", valid)

    print("Scanning OHLC and producing signals...")
    res = scan_symbols(valid)
    if not res:
        print("No volatile symbols with sufficient liquidity found.")
        return

    df = pd.DataFrame(res).sort_values("vol", ascending=False)
    df["signal_side"] = df["signal"].apply(lambda s: s.get("side") if isinstance(s, dict) else "none")
    actionable = df[df["signal_side"] != "none"]
    if actionable.empty:
        print("No actionable signals found among discovered symbols.")
        print(df[['symbol','last_price','vol','vol_usd']].to_string(index=False))
        return

        print("Actionable signals:")
    for _, row in actionable.iterrows():
        s = row["signal"]
        symbol = row['symbol']
        side = s.get('side', 'none').upper()
        entry = s.get('entry')
        stop = s.get('stop')
        target = s.get('target')
        reason = s.get('reason', '')
        price = row['last_price']
        vol_usd = row['vol_usd']
        print(f"{symbol} | {side} | entry={entry:.2f} stop={stop:.2f} target={target:.2f} reason={reason} | price={price:.2f} vol_usd={vol_usd:.1f}")



    actionable.to_csv("nobitex_dynamic_scan.csv", index=False)
    print("Wrote nobitex_dynamic_scan.csv")

if __name__ == '__main__':
    main()


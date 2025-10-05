#!/usr/bin/env python3
# nobitex_list_symbols.py
# Fetch available symbols from Nobitex (try public endpoints), enrich with price/bid/ask/volume, write CSV.

import os
import time
import csv
import argparse
import requests
from datetime import datetime

API_BASE = "https://apiv2.nobitex.ir"
CANDIDATE_ENDPOINTS = [
    "/v3/market/symbols",     # try common patterns
    "/v3/symbols",
    "/v1/markets",
    "/v3/markets"
]
ORDERBOOK_PATH = "/v3/orderbook/{}"
TICKER_PATH = "/v3/ticker/{}"   # if available
REQUEST_DELAY = 0.12
DEFAULT_CANDIDATES = [
    "BTCUSDT","ETHUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","TRXUSDT","LTCUSDT",
    "BNBUSDT","SOLUSDT","MATICUSDT","DOTUSDT","ZECUSDT","LINKUSDT","AVAXUSDT","AAVEUSDT"
]

def try_get_symbols(token=None, timeout=8):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    for ep in CANDIDATE_ENDPOINTS:
        url = API_BASE + ep
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code != 200:
                continue
            j = r.json()
            # normalize common shapes:
            # expected either list of dicts with "symbol" or "name", or dict with "symbols" key
            symbols = []
            if isinstance(j, dict):
                # case: {"symbols": [...]}
                if "symbols" in j and isinstance(j["symbols"], list):
                    for item in j["symbols"]:
                        if isinstance(item, dict) and ("symbol" in item or "name" in item):
                            symbols.append(item.get("symbol") or item.get("name"))
                        elif isinstance(item, str):
                            symbols.append(item)
                else:
                    # try keys like "data" or direct list
                    for key in ("data","result","rows"):
                        if key in j and isinstance(j[key], list):
                            for item in j[key]:
                                if isinstance(item, dict) and ("symbol" in item or "name" in item):
                                    symbols.append(item.get("symbol") or item.get("name"))
                                elif isinstance(item, str):
                                    symbols.append(item)
            elif isinstance(j, list):
                for item in j:
                    if isinstance(item, dict) and ("symbol" in item or "name" in item):
                        symbols.append(item.get("symbol") or item.get("name"))
                    elif isinstance(item, str):
                        symbols.append(item)
            symbols = [s for s in symbols if isinstance(s, str)]
            if symbols:
                # dedupe preserve order
                seen = set(); out=[]
                for s in symbols:
                    if s not in seen:
                        seen.add(s); out.append(s)
                return out
        except Exception:
            continue
    return None

def fetch_orderbook(symbol, token=None, timeout=8):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(API_BASE + ORDERBOOK_PATH.format(symbol), headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def fetch_ticker(symbol, token=None, timeout=8):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(API_BASE + TICKER_PATH.format(symbol), headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

def extract_price_from_orderbook(ob):
    # try several common keys
    last = None
    bid = None; ask = None
    vol24 = None
    try:
        if not isinstance(ob, dict):
            return None
        # common fields: lastTradePrice, last_price, last
        for k in ("lastTradePrice","last_trade_price","last_price","last"):
            if k in ob:
                try:
                    last = float(ob[k])
                    break
                except:
                    pass
        # bids/asks arrays
        bids = ob.get("bids") or ob.get("buy") or ob.get("bid")
        asks = ob.get("asks") or ob.get("sell") or ob.get("ask")
        if isinstance(bids, list) and len(bids)>0:
            # bid entry may be [price,qty] or {"price":..,"amount":..}
            b = bids[0]
            if isinstance(b, (list,tuple)) and len(b)>=1:
                bid = float(b[0])
            elif isinstance(b, dict) and ("price" in b):
                bid = float(b.get("price"))
        if isinstance(asks, list) and len(asks)>0:
            a = asks[0]
            if isinstance(a, (list,tuple)) and len(a)>=1:
                ask = float(a[0])
            elif isinstance(a, dict) and ("price" in a):
                ask = float(a.get("price"))
        # 24h volume common keys
        for k in ("24hVolume","volume24h","volume","vol","24h"):
            if k in ob:
                try:
                    vol24 = float(ob[k]); break
                except:
                    pass
    except Exception:
        pass
    return {"last": last, "bid": bid, "ask": ask, "vol24": vol24}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nobitex-token", type=str, default=os.environ.get("NOBITEX_TOKEN"))
    p.add_argument("--out", type=str, default="nobitex_symbols_list.csv")
    p.add_argument("--delay", type=float, default=REQUEST_DELAY)
    args = p.parse_args()

    token = args.nobitex_token
    out_file = args.out
    delay = args.delay

    print("Trying to fetch symbols list from public endpoints...")
    symbols = try_get_symbols(token=token)
    if not symbols:
        print("Could not fetch full list from API endpoints, falling back to default candidates.")
        symbols = DEFAULT_CANDIDATES

    print(f"Found {len(symbols)} candidate symbols.")
    rows = []
    now = datetime.utcnow().isoformat()
    for sym in symbols:
        try:
            ob = fetch_orderbook(sym, token=token)
            data = extract_price_from_orderbook(ob) if ob else {}
            # try ticker if orderbook gave nothing
            if not data or (data.get("last") is None and data.get("bid") is None and data.get("ask") is None):
                tick = fetch_ticker(sym, token=token)
                if tick and isinstance(tick, dict):
                    for k in ("last","price","last_price"):
                        if k in tick and tick[k] is not None:
                            data["last"] = float(tick[k]); break
                    # try bid/ask
                    if "bid" in tick: data["bid"]=float(tick["bid"])
                    if "ask" in tick: data["ask"]=float(tick["ask"])
                    if "volume" in tick and tick["volume"] is not None:
                        data["vol24"]=float(tick["volume"])
            bid = data.get("bid")
            ask = data.get("ask")
            last = data.get("last") if data.get("last") is not None else ( (bid+ask)/2 if bid and ask else None )
            spread = None
            if bid and ask:
                try:
                    spread = ask - bid
                except:
                    spread = None
            vol24 = data.get("vol24")
            base = None; quote = None
            # try to split symbol like BTCUSDT -> BTC / USDT
            if isinstance(sym, str) and len(sym)>3:
                # naive split: last 4 or 3 chars commonly USDT/BTC/IRT etc.
                if sym.endswith("USDT"):
                    base = sym[:-4]; quote = "USDT"
                elif sym.endswith("IRT"):
                    base = sym[:-3]; quote = "IRT"
                elif sym.endswith("BTC"):
                    base = sym[:-3]; quote = "BTC"
                else:
                    # fallback: split last 3
                    base = sym[:-3]; quote = sym[-3:]
            rows.append({
                "symbol": sym,
                "base": base or "",
                "quote": quote or "",
                "last_price": round(last, 8) if last is not None else "",
                "bid": round(bid, 8) if bid is not None else "",
                "ask": round(ask, 8) if ask is not None else "",
                "spread": round(spread, 8) if spread is not None else "",
                "volume_24h": round(vol24, 8) if vol24 is not None else "",
                "fetched_at_utc": now
            })
        except Exception as e:
            # on any error, record symbol with empty price fields
            rows.append({
                "symbol": sym,
                "base": "",
                "quote": "",
                "last_price": "",
                "bid": "",
                "ask": "",
                "spread": "",
                "volume_24h": "",
                "fetched_at_utc": now
            })
        time.sleep(delay)

    # write CSV (UTF-8 with BOM so Excel handles it)
    fieldnames = ["symbol","base","quote","last_price","bid","ask","spread","volume_24h","fetched_at_utc"]
    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote {len(rows)} rows to {out_file}")

if __name__ == "__main__":
    main()


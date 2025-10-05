#!/usr/bin/env python3
# nobitex_symbols_usdt_fa.py
# استخراج نمادهای زنده نوبیتکس با quote = USDT و نوشتن CSV با سربرگ فارسی
# usage:
# python nobitex_symbols_usdt_fa.py --out output/nobitex_symbols_usdt.csv --nobitex-token "..."

import os, time, argparse, csv, requests
from datetime import datetime

API_BASE = "https://apiv2.nobitex.ir"
ORDERBOOK_PATH = "/v3/orderbook/{}"
REQUEST_DELAY = 0.12
# اگر می‌خواهی candidate اختصاصی اضافه شود، اینجا بگذار
FALLBACK_CANDIDATES = [
    "BTCUSDT","ETHUSDT","XRPUSDT","ADAUSDT","DOGEUSDT","TRXUSDT","LTCUSDT",
    "BNBUSDT","SOLUSDT","MATICUSDT","DOTUSDT","ZECUSDT","LINKUSDT","AVAXUSDT","AAVEUSDT"
]

def fetch_orderbook(symbol, token=None, timeout=8):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(API_BASE + ORDERBOOK_PATH.format(symbol), headers=headers, timeout=timeout)
        if r.status_code != 200:
            return None, r.status_code
        return r.json(), r.status_code
    except Exception as e:
        return None, None

def extract_price_from_orderbook(ob):
    last=None; bid=None; ask=None; vol24=None
    if not isinstance(ob, dict):
        return {"last":None,"bid":None,"ask":None,"vol24":None}
    for k in ("lastTradePrice","last_trade_price","last_price","last"):
        if k in ob:
            try:
                last = float(ob[k]); break
            except:
                pass
    bids = ob.get("bids") or ob.get("buy") or ob.get("bid")
    asks = ob.get("asks") or ob.get("sell") or ob.get("ask")
    if isinstance(bids, list) and len(bids)>0:
        b = bids[0]
        if isinstance(b,(list,tuple)) and len(b)>=1:
            try: bid=float(b[0])
            except: bid=None
        elif isinstance(b,dict) and "price" in b:
            try: bid=float(b.get("price"))
            except: bid=None
    if isinstance(asks, list) and len(asks)>0:
        a = asks[0]
        if isinstance(a,(list,tuple)) and len(a)>=1:
            try: ask=float(a[0])
            except: ask=None
        elif isinstance(a,dict) and "price" in a:
            try: ask=float(a.get("price"))
            except: ask=None
    for k in ("24hVolume","volume24h","volume","vol","24h"):
        if k in ob:
            try: vol24=float(ob[k]); break
            except: pass
    return {"last": last, "bid": bid, "ask": ask, "vol24": vol24}

def is_usdt_symbol(sym):
    if not isinstance(sym, str):
        return False
    return sym.upper().endswith("USDT")

def probe_list(symbols, token=None, delay=0.12):
    rows=[]
    now = datetime.utcnow().isoformat()
    seen=set()
    for sym in symbols:
        if not is_usdt_symbol(sym):
            continue
        if sym in seen:
            continue
        seen.add(sym)
        ob, status = fetch_orderbook(sym, token=token)
        if not ob:
            time.sleep(delay); continue
        data = extract_price_from_orderbook(ob)
        bid = data.get("bid"); ask = data.get("ask"); last = data.get("last")
        # fallback: if last missing but bid/ask exist, take mid
        mid = None
        if last is None and bid is not None and ask is not None:
            mid = (bid+ask)/2.0
            last = mid
        spread = None
        spread_pct = None
        if bid is not None and ask is not None:
            spread = ask - bid
            try:
                spread_pct = (spread / ((ask+bid)/2.0)) * 100.0
            except:
                spread_pct = None
        rows.append({
            "نماد": sym,
            "پایه": sym[:-4] if sym.endswith("USDT") else "",
            "مظنه": "USDT",
            "قیمت_آخر (USD)": round(last, 2) if isinstance(last, (int,float)) else "",
            "قیمت_بید": round(bid, 2) if isinstance(bid,(int,float)) else "",
            "قیمت_اسک": round(ask, 2) if isinstance(ask,(int,float)) else "",
            "اسپرد": round(spread, 2) if isinstance(spread,(int,float)) else "",
            "اسپرد_درصد": round(spread_pct, 2) if isinstance(spread_pct,(int,float)) else "",
            "حجم_24ساعت": round(data.get("vol24"), 2) if isinstance(data.get("vol24"),(int,float)) else "",
            "زمان_استخراج_UTC": now
        })
        time.sleep(delay)
    return rows

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--nobitex-token", type=str, default=os.environ.get("NOBITEX_TOKEN"))
    p.add_argument("--out", type=str, default="nobitex_symbols_usdt.csv")
    p.add_argument("--delay", type=float, default=REQUEST_DELAY)
    p.add_argument("--candidates", type=str, default="")  # optional comma-separated extra symbols to probe
    args = p.parse_args()

    token = args.nobitex_token
    out_file = args.out
    delay = args.delay

    # try to build candidate set: prefer probing a reasonable set including fallback
    candidates = []
    # include fallback list first
    candidates.extend(FALLBACK_CANDIDATES)
    # allow custom extras
    if args.candidates:
        extras = [s.strip().upper() for s in args.candidates.split(",") if s.strip()]
        candidates.extend(extras)

    print(f"Probing {len(candidates)} candidate symbols (filter USDT)...")
    rows = probe_list(candidates, token=token, delay=delay)
    # write CSV with Persian headers (UTF-8 BOM for Excel)
    os.makedirs(os.path.dirname(out_file) or ".", exist_ok=True)
    fieldnames = ["نماد","پایه","مظنه","قیمت_آخر (USD)","قیمت_بید","قیمت_اسک","اسپرد","اسپرد_درصد","حجم_24ساعت","زمان_استخراج_UTC"]
    with open(out_file, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Wrote {len(rows)} rows to {out_file}")

if __name__ == "__main__":
    main()


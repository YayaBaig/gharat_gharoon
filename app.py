#!/usr/bin/env python3
# app.py - Nobitex Trading Dashboard Backend for Windows & Cross-Platform
import os, sys, json, time, math, argparse
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta
import requests
import numpy as np
import pandas as pd

# Path configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
GUI_DIR = os.path.join(BASE_DIR, "gui")

API_BASE = "https://apiv2.nobitex.ir"
ORDERBOOK_PATH = "/v3/orderbook/{}"
OHLC_PATH = "/market/udf/history"

COMMON_CANDIDATES = [
    "BTCUSDT", "ETHUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT", 
    "TRXUSDT", "LTCUSDT", "BNBUSDT", "SOLUSDT", "MATICUSDT", 
    "DOTUSDT", "ZECUSDT", "LINKUSDT", "AVAXUSDT", "AAVEUSDT"
]

def fetch_nobitex_orderbook(symbol, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        r = requests.get(API_BASE + ORDERBOOK_PATH.format(symbol), headers=headers, timeout=8)
        if r.status_code == 200:
            return r.json()
    except Exception:
        pass
    return None

def fetch_nobitex_ohlc(symbol, resolution="60", from_ts=None, to_ts=None, token=None):
    now = int(time.time())
    if not to_ts:
        to_ts = now
    if not from_ts:
        from_ts = now - (72 * 3600)
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(int(from_ts)), "to": str(int(to_ts))}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(API_BASE + OHLC_PATH, params=params, headers=headers, timeout=12)
    r.raise_for_status()
    return r.json()

def ohlc_json_to_df(j):
    if not isinstance(j, dict) or not all(k in j for k in ("t", "o", "c", "h", "l", "v")):
        return None
    df = pd.DataFrame({
        "t": j["t"], "Open": j["o"], "Close": j["c"],
        "High": j["h"], "Low": j["l"], "Volume": j["v"]
    })
    df["Date"] = pd.to_datetime(df["t"], unit="s")
    df = df[["Date", "t", "Open", "High", "Low", "Close", "Volume"]]
    for c in ["Open", "High", "Low", "Close", "Volume"]:
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
    df["MA50"] = df["Close"].ewm(span=50, adjust=False).mean() if len(df)>=50 else df["Close"].rolling(window=min(len(df),50)).mean()
    return df.ffill().bfill()

def compute_fibonacci_levels(high, low):
    diff = high - low
    return {
        "0": round(float(low), 4),
        "0.236": round(float(high - 0.236 * diff), 4),
        "0.382": round(float(high - 0.382 * diff), 4),
        "0.5": round(float(high - 0.5 * diff), 4),
        "0.618": round(float(high - 0.618 * diff), 4),
        "0.786": round(float(high - 0.786 * diff), 4),
        "1": round(float(high), 4)
    }

def analyze_symbol(symbol, capital=1000, fee=0.001, slippage=0.002, token=None):
    try:
        j = fetch_nobitex_ohlc(symbol, resolution="60", token=token)
        df = ohlc_json_to_df(j)
        if df is None or len(df) < 12:
            return None
        df = add_indicators(df)
        
        last = df.iloc[-1]
        price = float(last["Close"])
        high_val = float(df["High"].tail(48).max())
        low_val = float(df["Low"].tail(48).min())
        rsi = float(last["RSI_14"])
        macd = float(last["MACD"])
        macd_sig = float(last["MACD_SIGNAL"])
        bbh = float(last["BB_H"])
        bbl = float(last["BB_L"])
        ma50 = float(last["MA50"])
        
        recent_vol = float(df["Volume"].tail(12).mean())
        vol_usd = recent_vol * price
        
        fibs = compute_fibonacci_levels(high_val, low_val)
        
        # Volatility
        close_series = df["Close"].astype(float)
        ret = np.log(close_series).diff().dropna()
        volatility = float(ret.std()) if len(ret) > 2 else 0.0
        
        # Signal detection
        side = "none"
        reason = "nomatch"
        entry = price
        stop = price
        target = price
        
        # Long signal logic
        if price > bbl * 0.995 and macd > macd_sig and 40 < rsi < 70:
            side = "long"
            reason = "پولبک به حمایتی فیبوناچی 0.5/0.618 + MACD صعودی + RSI"
            entry = price
            stop = float(min(fibs["0.786"], price * 0.985))
            target = float(max(fibs["1"], price * 1.03))
        elif price >= bbh * 0.995 and macd < macd_sig and rsi > 60:
            side = "short"
            reason = "برخورد به مقاومت بولینگر + MACD نزولی"
            entry = price
            stop = float(price * 1.015)
            target = float(price * 0.97)
            
        # Fees & Calculation
        exec_entry = entry * (1 + slippage) * (1 + fee) if side == "long" else entry * (1 - slippage) * (1 - fee)
        exec_target = target * (1 - slippage) * (1 - fee) if side == "long" else target * (1 + slippage) * (1 + fee)
        exec_stop = stop * (1 - slippage) * (1 - fee) if side == "long" else stop * (1 + slippage) * (1 + fee)
        
        units = capital / exec_entry if exec_entry > 0 else 0
        net_profit_total = (exec_target - exec_entry) * units if side == "long" else (exec_entry - exec_target) * units
        net_risk_total = (exec_entry - exec_stop) * units if side == "long" else (exec_stop - exec_entry) * units
        
        rr_ratio = (net_profit_total / net_risk_total) if net_risk_total > 0 else 0.0
        profit_pct = (net_profit_total / capital) * 100 if capital > 0 else 0.0
        
        return {
            "symbol": symbol,
            "last_price": round(price, 4),
            "volatility": round(volatility, 6),
            "volume_usd": round(vol_usd, 2),
            "rsi": round(rsi, 2),
            "macd": round(macd, 4),
            "ma50": round(ma50, 4),
            "fibs": fibs,
            "signal": {
                "side": side,
                "reason": reason,
                "entry": round(entry, 4),
                "stop": round(stop, 4),
                "target": round(target, 4),
                "exec_entry": round(exec_entry, 4),
                "units": round(units, 4),
                "net_profit_usd": round(net_profit_total, 2),
                "net_risk_usd": round(net_risk_total, 2),
                "profit_pct": round(profit_pct, 2),
                "rr_ratio": round(rr_ratio, 2)
            }
        }
    except Exception as e:
        return None

class DashboardHTTPRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json_response(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            html_path = os.path.join(GUI_DIR, "index.html")
            if os.path.exists(html_path):
                with open(html_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        elif path == "/guide.html":
            guide_path = os.path.join(BASE_DIR, "guide.html")
            if os.path.exists(guide_path):
                with open(guide_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        elif path == "/api/status":
            self.send_json_response({
                "status": "online",
                "os": sys.platform,
                "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "candidates_count": len(COMMON_CANDIDATES)
            })
            return

        elif path == "/api/ohlc":
            params = parse_qs(parsed.query)
            symbol = params.get("symbol", ["BTCUSDT"])[0]
            resolution = params.get("resolution", ["60"])[0]
            token = params.get("token", [None])[0]
            try:
                j = fetch_nobitex_ohlc(symbol, resolution=resolution, token=token)
                df = ohlc_json_to_df(j)
                if df is not None:
                    df = add_indicators(df)
                    records = []
                    for idx, row in df.iterrows():
                        records.append({
                            "time": int(row["t"]),
                            "open": round(float(row["Open"]), 4),
                            "high": round(float(row["High"]), 4),
                            "low": round(float(row["Low"]), 4),
                            "close": round(float(row["Close"]), 4),
                            "volume": round(float(row["Volume"]), 4),
                            "ema12": round(float(row["EMA_12"]), 4) if pd.notnull(row["EMA_12"]) else None,
                            "ema26": round(float(row["EMA_26"]), 4) if pd.notnull(row["EMA_26"]) else None,
                            "rsi": round(float(row["RSI_14"]), 2) if pd.notnull(row["RSI_14"]) else None,
                            "macd": round(float(row["MACD"]), 4) if pd.notnull(row["MACD"]) else None,
                            "macd_sig": round(float(row["MACD_SIGNAL"]), 4) if pd.notnull(row["MACD_SIGNAL"]) else None,
                        })
                    self.send_json_response({"symbol": symbol, "data": records})
                    return
            except Exception as e:
                self.send_json_response({"error": str(e)}, status=500)
                return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(length).decode('utf-8') if length > 0 else "{}"
        
        try:
            payload = json.loads(post_data)
        except Exception:
            payload = {}

        if path == "/api/scan":
            capital = float(payload.get("capital", 1000.0))
            fee = float(payload.get("taker_fee", 0.001))
            slippage = float(payload.get("slippage", 0.002))
            token = payload.get("token", None)
            symbols = payload.get("symbols", COMMON_CANDIDATES)
            
            results = []
            for sym in symbols:
                res = analyze_symbol(sym, capital=capital, fee=fee, slippage=slippage, token=token)
                if res:
                    results.append(res)
                time.sleep(0.08)
                
            # Compute KPI Summary
            total_scanned = len(results)
            long_count = sum(1 for r in results if r["signal"]["side"] == "long")
            short_count = sum(1 for r in results if r["signal"]["side"] == "short")
            actionable_count = long_count + short_count
            total_net_profit = sum(r["signal"]["net_profit_usd"] for r in results if r["signal"]["side"] != "none")
            valid_rr = [r["signal"]["rr_ratio"] for r in results if r["signal"]["side"] != "none" and r["signal"]["rr_ratio"] > 0]
            avg_rr = round(sum(valid_rr) / len(valid_rr), 2) if valid_rr else 0.0

            self.send_json_response({
                "summary": {
                    "total_scanned": total_scanned,
                    "actionable_count": actionable_count,
                    "long_count": long_count,
                    "short_count": short_count,
                    "total_net_profit_usd": round(total_net_profit, 2),
                    "avg_rr_ratio": avg_rr
                },
                "results": results
            })
            return

        self.send_response(404)
        self.end_headers()

def main():
    parser = argparse.ArgumentParser(description="Nobitex Trading Windows Dashboard Server")
    parser.add_argument("--port", type=int, default=8000, help="Port to run web server on")
    args = parser.parse_args()
    
    server_address = ('', args.port)
    httpd = HTTPServer(server_address, DashboardHTTPRequestHandler)
    print("=" * 65)
    print(f"🚀 Nobitex Trading Dashboard Server is running!")
    print(f"👉 Open in your web browser: http://localhost:{args.port}")
    print("=" * 65)
    
    try:
        import webbrowser
        webbrowser.open(f"http://localhost:{args.port}")
    except Exception:
        pass
        
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# nobitex_signals_nominal_fees_with_ohlc_rounded.py
# مثل نسخهٔ قبلی اما همهٔ مقادیر عددی خروجی با 2 رقم اعشار گرد می‌شوند
import os, argparse, ast, time
import requests
import pandas as pd, numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta

# config
INPUT_CSV = "nobitex_dynamic_scan.csv"
OUT_HTML = "نوبیتکس_سیگنال‌ها_با_کندل_1h_گرد شده.html"
OUT_SUMMARY = "خلاصه_سیگنال‌ها_نوبیتکس_ساده_گرد.csv"
API_BASE = "https://apiv2.nobitex.ir"
OHLC_PATH = "/market/udf/history"
HEADERS = {}
REQUEST_DELAY = 0.12
DISPLAY_DECIMALS = 2

def parse_signal_col(s):
    try:
        return ast.literal_eval(s)
    except Exception:
        return None

def pip_size_for_price(p):
    try:
        p = float(p)
    except:
        return 0.01
    if p >= 1.0:
        return 0.01
    if p >= 0.01:
        return 0.0001
    return 0.000001

def apply_fees_and_slippage(price, fee, slippage, side="buy"):
    p = float(price)
    if side == "buy":
        executed_entry = p * (1 + slippage)
        executed_entry_with_fee = executed_entry * (1 + fee)
        return executed_entry, executed_entry_with_fee
    else:
        executed_price = p * (1 - slippage)
        executed_price_with_fee = executed_price * (1 - fee)
        return executed_price, executed_price_with_fee

def round_float(v):
    try:
        return round(float(v), DISPLAY_DECIMALS)
    except:
        return v

def compute_nominal_with_fees(row, capital, fee, slippage):
    sig = row['signal_obj']
    entry = float(sig['entry']); stop = float(sig['stop']); target = float(sig['target'])
    exec_entry, exec_entry_with_fee = apply_fees_and_slippage(entry, fee, slippage, side="buy")
    units = capital / exec_entry_with_fee if exec_entry_with_fee>0 else 0.0
    notional = units * exec_entry_with_fee
    exec_target, exec_target_with_fee = apply_fees_and_slippage(target, fee, slippage, side="sell")
    exec_stop, exec_stop_with_fee = apply_fees_and_slippage(stop, fee, slippage, side="sell")
    gross_profit_per_unit = target - entry
    gross_profit_total = gross_profit_per_unit * units
    net_profit_per_unit = exec_target_with_fee - exec_entry_with_fee
    net_profit_total = net_profit_per_unit * units
    gross_risk_per_unit = entry - stop
    gross_risk_total = gross_risk_per_unit * units
    net_risk_per_unit = exec_entry_with_fee - exec_stop_with_fee
    net_risk_total = net_risk_per_unit * units
    profit_pct_on_capital_net = (net_profit_total / capital) * 100.0 if capital>0 else np.nan
    pip = pip_size_for_price(entry)
    profit_pips = gross_profit_per_unit / pip if pip>0 else np.nan
    risk_pips = gross_risk_per_unit / pip if pip>0 else np.nan
    rr_net = (net_profit_per_unit / net_risk_per_unit) if net_risk_per_unit>0 else np.nan

    # گرد کردن مقادیر عددی به 2 رقم اعشار قبل از بازگشت
    return {
        "واحدها": round_float(units),
        "ناتیشن (USD)": round_float(notional),
        "سود ناخالص (USD)": round_float(gross_profit_total),
        "سود خالص پس از کارمزد و لغزش (USD)": round_float(net_profit_total),
        "درصد سود خالص نسبت به سرمایه": round_float(profit_pct_on_capital_net),
        "ریسک خالص پس از کارمزد و لغزش (USD)": round_float(net_risk_total),
        "پیپ(تقریبی)": round_float(pip),
        "سود پیپ": round_float(profit_pips),
        "ریسک پیپ": round_float(risk_pips),
        "R/R خالص": round_float(rr_net),
        "قیمت اجرایی ورود": round_float(exec_entry_with_fee)
    }

def fetch_ohlc(symbol, resolution="60", from_unix=None, to_unix=None, headers=None, timeout=12):
    params = {"symbol": symbol, "resolution": str(resolution), "from": str(from_unix), "to": str(to_unix)}
    url = API_BASE + OHLC_PATH
    r = requests.get(url, params=params, headers=headers or {}, timeout=timeout)
    r.raise_for_status()
    return r.json()

def ohlc_json_to_df(j):
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

def build_html_with_ohlc(df_signals, out_html, headers=None):
    n = len(df_signals)
    if n == 0:
        raise ValueError("No signals to plot")
    fig = make_subplots(rows=n, cols=1, shared_xaxes=False,
                        vertical_spacing=0.06,
                        subplot_titles=[f"{r['symbol']} — {r['signal_obj']['side'].upper()}" for _, r in df_signals.iterrows()])
    r = 1
    for _, row in df_signals.iterrows():
        sym = row['symbol']
        sig = row['signal_obj']
        # درخواست OHLC
        to_unix = int(datetime.utcnow().timestamp())
        from_unix = int((datetime.utcnow() - timedelta(hours=72)).timestamp())
        ojson = None
        try:
            ojson = fetch_ohlc(sym, resolution="60", from_unix=from_unix, to_unix=to_unix, headers=headers)
            time.sleep(REQUEST_DELAY)
        except Exception:
            ojson = None
        df_ohlc = ohlc_json_to_df(ojson) if ojson else None

        if df_ohlc is not None and len(df_ohlc) > 1:
            # گرد کردن قیمت‌ها برای نمایش نیز با 2 رقم اعشار
            df_ohlc["Open"] = df_ohlc["Open"].round(DISPLAY_DECIMALS)
            df_ohlc["High"] = df_ohlc["High"].round(DISPLAY_DECIMALS)
            df_ohlc["Low"] = df_ohlc["Low"].round(DISPLAY_DECIMALS)
            df_ohlc["Close"] = df_ohlc["Close"].round(DISPLAY_DECIMALS)
            fig.add_trace(go.Candlestick(x=df_ohlc["Date"], open=df_ohlc["Open"], high=df_ohlc["High"], low=df_ohlc["Low"], close=df_ohlc["Close"], name=f"{sym} OHLC"), row=r, col=1)
            if len(df_ohlc) > 48:
                x0 = df_ohlc["Date"].iloc[-48]
                fig.update_xaxes(range=[x0, df_ohlc["Date"].iloc[-1]], row=r, col=1)
        else:
            price = round_float(row['last_price'])
            fig.add_trace(go.Scatter(x=[0,1], y=[price,price], mode='lines', line=dict(color='lightgray'), name=f"{sym} price"), row=r, col=1)

        # markers (اعداد نمایش داده شده با 2 رقم اعشار)
        last_x = df_ohlc["Date"].iloc[-1] if df_ohlc is not None and len(df_ohlc)>0 else 1
        fig.add_trace(go.Scatter(x=[last_x - pd.Timedelta(minutes=120)], y=[round_float(sig['entry'])], mode='markers+text', marker=dict(color='blue', size=8), text=[f"ورود {round_float(sig['entry']):.2f}"], textposition="top center", showlegend=False), row=r, col=1)
        fig.add_trace(go.Scatter(x=[last_x - pd.Timedelta(minutes=60)], y=[round_float(sig['stop'])], mode='markers+text', marker=dict(color='red', size=8), text=[f"استاپ {round_float(sig['stop']):.2f}"], textposition="bottom center", showlegend=False), row=r, col=1)
        fig.add_trace(go.Scatter(x=[last_x], y=[round_float(sig['target'])], mode='markers+text', marker=dict(color='green', size=8), text=[f"تارگت {round_float(sig['target']):.2f}"], textposition="top center", showlegend=False), row=r, col=1)

        stats_text = (f"واحدها: {row['واحدها']:.2f}<br>"
                      f"سود خالص پس از کارمزد و لغزش: {row['سود خالص پس از کارمزد و لغزش (USD)']:.2f} USD<br>"
                      f"پیپ(تقریبی): {row['پیپ(تقریبی)']:.2f}<br>"
                      f"سود پیپ: {row['سود پیپ']:.2f}<br>"
                      f"قیمت اجرایی ورود: {row['قیمت اجرایی ورود']:.2f}")
        if r == 1:
            xref = "x domain"; yref = "y domain"
        else:
            xref = f"x{r} domain"; yref = f"y{r} domain"
        fig.add_annotation(text=stats_text, xref=xref, yref=yref, x=0.98, y=0.5, showarrow=False, align="right")
        r += 1

    fig.update_layout(height=380*n, title_text="سیگنال‌ها و کندل‌های 1h (نوبیتکس) — گرد شده تا 2 رقم اعشار", showlegend=False, margin=dict(l=40, r=260, t=80, b=40))
    fig.write_html(out_html, include_plotlyjs='cdn')
    return out_html

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, required=True, help="کل سرمایه به USD")
    p.add_argument("--taker-fee", type=float, default=0.001, help="کارمزد تیکر به صورت اعشاری")
    p.add_argument("--slippage", type=float, default=0.002, help="لغزش فرضی به صورت اعشاری")
    p.add_argument("--nobitex-token", type=str, default=None, help="در صورت نیاز توکن نوبیتکس را وارد کن تا درخواست OHLC با هدر Authorization ارسال شود")
    args = p.parse_args()

    capital = args.capital; fee = args.taker_fee; slippage = args.slippage
    global HEADERS
    if args.nobitex_token:
        HEADERS = {"Authorization": f"Bearer {args.nobitex_token}"}

    if not os.path.exists(INPUT_CSV):
        print("فایل ورودی پیدا نشد:", INPUT_CSV); return

    df = pd.read_csv(INPUT_CSV)
    df['signal_obj'] = df['signal'].apply(parse_signal_col)
    df = df[df['signal_obj'].notnull()].copy()
    if df.empty:
        print("هیچ سیگنالی موجود نیست"); return

    rows = []
    for idx, r in df.iterrows():
        comp = compute_nominal_with_fees(r, capital, fee, slippage)
        for k, v in comp.items():
            r[k] = v
        rows.append(r)
    df2 = pd.DataFrame(rows)

    # خروجی CSV ساده با ستون‌های درخواستی (مقادیر گرد شده 2 رقم)
    out_simple = pd.DataFrame({
        "نماد": df2["symbol"],
        "قیمت_آخر (USD)": df2["last_price"].round(DISPLAY_DECIMALS),
        "سود خالص پس از کارمزد و لغزش (USD)": df2["سود خالص پس از کارمزد و لغزش (USD)"].round(DISPLAY_DECIMALS),
        "پیپ(تقریبی)": df2["پیپ(تقریبی)"].round(DISPLAY_DECIMALS),
        "سود پیپ": df2["سود پیپ"].round(DISPLAY_DECIMALS),
        "قیمت اجرایی ورود": df2["قیمت اجرایی ورود"].round(DISPLAY_DECIMALS)
    })
    out_simple.to_csv(OUT_SUMMARY, index=False, encoding='utf-8-sig')
    print("خلاصه ساده (گرد شده) ذخیره شد:", OUT_SUMMARY)

    # HTML با کندل 1h واقعی
    html_path = build_html_with_ohlc(df2.reset_index(drop=True), OUT_HTML, headers=HEADERS)
    print("نمودار تعاملی ساخته شد:", html_path)

    help_text = """
راهنما برای خواندن نمودار HTML:
- هر ردیف نمودار مربوط به یک نماد است و کندل‌های 1 ساعته در آن رسم شده‌اند.
- کندل سبز: قیمت بالا آمده; کندل قرمز: قیمت پایین آمده.
- نقاط آبی/قرمز/سبز روی نمودار به ترتیب نشان‌دهنده قیمت ورود، استاپ و تارگت هستند.
- با نگاه به کندل‌های اخیر ببین که آیا قیمت بالای نقطه ورود تثبیت شده است؛ توصیه می‌شود منتظر بسته شدن یک کندل 1h بالای ورود برای تأیید long باشی.
- بخش آمار سمت راست هر ردیف نشان می‌دهد: واحد خریدنی با تخصیص سرمایه، سود خالص پس از کارمزد و لغزش، پیپ و قیمت اجرایی ورود.
- فایل CSV خروجی خلاصه ساده را می‌توانی در اکسل باز کنی و سریع مقایسه کنی.
"""
    print(help_text)

if __name__ == "__main__":
    main()


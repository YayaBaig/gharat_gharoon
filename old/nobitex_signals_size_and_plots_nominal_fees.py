#!/usr/bin/env python3
# nobitex_signals_size_and_plots_nominal_fees.py
# نسخهٔ nominal allocation با احتساب کارمزد و لغزش؛ خروجی CSV و HTML با ستون‌های فارسی

import os, argparse, ast
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

INPUT_CSV = "nobitex_dynamic_scan.csv"
OUT_HTML = "نوبیتکس_سیگنال‌ها_جمعی.html"
OUT_SUMMARY = "خلاصه_سیگنال‌ها_نوبیتکس.csv"

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
    # entry/stop/target adjusted for realistic execution:
    # entry: if buying, assume slippage up (price*(1+slippage)) and pay taker fee on notional
    # target: assume slippage down when selling target reached (price*(1-slippage)) and taker fee
    # stop: assume stop executes at worse price (for long stop lower, but slippage adverse); we apply slippage in unfavorable direction
    p = float(price)
    if side == "buy":
        executed_entry = p * (1 + slippage)
        executed_entry_with_fee = executed_entry * (1 + fee)
        return executed_entry, executed_entry_with_fee
    else:
        executed_price = p * (1 - slippage)
        executed_price_with_fee = executed_price * (1 - fee)
        return executed_price, executed_price_with_fee

def compute_nominal_with_fees(row, capital, fee, slippage):
    sig = row['signal_obj']
    entry = float(sig['entry'])
    stop = float(sig['stop'])
    target = float(sig['target'])
    # allocate full capital to buy at entry (assume buy then later sell)
    units = 0.0
    if entry > 0:
        # executed entry price and cost including fee and slippage
        exec_entry, exec_entry_with_fee = apply_fees_and_slippage(entry, fee, slippage, side="buy")
        units = capital / exec_entry_with_fee if exec_entry_with_fee > 0 else 0.0
    notional = units * exec_entry_with_fee if units>0 else 0.0

    # executed target and stop prices with slippage and fees on exit (sell)
    exec_target, exec_target_with_fee = apply_fees_and_slippage(target, fee, slippage, side="sell")
    exec_stop, exec_stop_with_fee = apply_fees_and_slippage(stop, fee, slippage, side="sell")

    # gross results per unit (pre-fee/slippage) and net results (post-fee/slippage)
    gross_profit_per_unit = target - entry
    gross_profit_total = gross_profit_per_unit * units

    net_profit_per_unit = exec_target_with_fee - exec_entry_with_fee
    net_profit_total = net_profit_per_unit * units

    gross_risk_per_unit = entry - stop
    gross_risk_total = gross_risk_per_unit * units

    net_risk_per_unit = exec_entry_with_fee - exec_stop_with_fee
    net_risk_total = net_risk_per_unit * units

    profit_pct_on_capital_net = (net_profit_total / capital) * 100.0 if capital>0 else np.nan
    profit_pct_on_capital_gross = (gross_profit_total / capital) * 100.0 if capital>0 else np.nan

    pip = pip_size_for_price(entry)
    profit_pips = gross_profit_per_unit / pip if pip>0 else np.nan
    risk_pips = gross_risk_per_unit / pip if pip>0 else np.nan
    rr_gross = (gross_profit_per_unit / gross_risk_per_unit) if gross_risk_per_unit>0 else np.nan
    rr_net = (net_profit_per_unit / net_risk_per_unit) if net_risk_per_unit>0 else np.nan

    return {
        "واحدها": units,
        "ناتیشن (USD)": notional,
        "سود ناخالص (USD)": gross_profit_total,
        "سود خالص پس از کارمزد و لغزش (USD)": net_profit_total,
        "درصد سود خالص نسبت به سرمایه": profit_pct_on_capital_net,
        "ریسک ناخالص (USD)": gross_risk_total,
        "ریسک خالص پس از کارمزد و لغزش (USD)": net_risk_total,
        "پیپ(تقریبی)": pip,
        "سود پیپ": profit_pips,
        "ریسک پیپ": risk_pips,
        "R/R ناخالص": rr_gross,
        "R/R خالص": rr_net,
        "قیمت اجرایی ورود": exec_entry_with_fee,
        "قیمت اجرایی تارگت (پس از اسلیپیج/فی)": exec_target_with_fee,
        "قیمت اجرایی استاپ (پس از اسلیپیج/فی)": exec_stop_with_fee
    }

def build_interactive_html(df_signals, out_html):
    n = len(df_signals)
    if n == 0:
        raise ValueError("No signals to plot")
    fig = make_subplots(rows=n, cols=1, shared_xaxes=False,
                        vertical_spacing=0.06,
                        subplot_titles=[f"{r['symbol']} — {r['signal_obj']['side'].upper()}" for _, r in df_signals.iterrows()])
    rindex = 1
    for _, row in df_signals.iterrows():
        sym = row['symbol']
        sig = row['signal_obj']
        price = float(row['last_price'])
        fig.add_trace(go.Scatter(x=[0,1], y=[price,price], mode='lines', line=dict(color='lightgray'),
                                 name=f"{sym} price"), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.33], y=[sig['entry']], mode='markers+text', marker=dict(color='blue',size=8),
                                 text=[f"ورود {sig['entry']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.5], y=[sig['stop']], mode='markers+text', marker=dict(color='red',size=8),
                                 text=[f"استاپ {sig['stop']:.6g}"], textposition="bottom center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.66], y=[sig['target']], mode='markers+text', marker=dict(color='green',size=8),
                                 text=[f"تارگت {sig['target']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        ymin = min(price, sig['stop'], sig['entry'], sig['target']) * 0.995
        ymax = max(price, sig['stop'], sig['entry'], sig['target']) * 1.005
        fig.update_yaxes(range=[ymin, ymax], row=rindex, col=1)
        if rindex == 1:
            xref = "x domain"; yref = "y domain"
        else:
            xref = f"x{rindex} domain"; yref = f"y{rindex} domain"
        # ساخت متن فارسی آمار
        stats_text = (f"واحدها: {row['واحدها']:.6f}<br>"
                      f"ناتیشن: {row['ناتیشن (USD)']:.2f} USD<br>"
                      f"سود ناخالص: {row['سود ناخالص (USD)']:.2f} USD<br>"
                      f"سود خالص پس از کارمزد و لغزش: {row['سود خالص پس از کارمزد و لغزش (USD)']:.2f} USD<br>"
                      f"درصد سود خالص: {row['درصد سود خالص نسبت به سرمایه']:.2f}%<br>"
                      f"ریسک خالص: {row['ریسک خالص پس از کارمزد و لغزش (USD)']:.2f} USD<br>"
                      f"R/R خالص: {row['R/R خالص']:.2f}")
        fig.add_annotation(text=stats_text, xref=xref, yref=yref, x=0.98, y=0.5, showarrow=False, align="right")
        rindex += 1

    fig.update_layout(height=320*n, title_text="سیگنال‌های نوبیتکس — خلاصه با کارمزد و لغزش", showlegend=False, margin=dict(l=40,r=260,t=80,b=40))
    fig.write_html(out_html, include_plotlyjs='cdn')
    return out_html

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, required=True, help="کل سرمایه به USD")
    p.add_argument("--taker-fee", type=float, default=0.001, help="کارمزد تیکر به صورت اعشاری (مثال 0.001 = 0.1%)")
    p.add_argument("--slippage", type=float, default=0.002, help="لغزش فرضی به صورت اعشاری (مثال 0.002 = 0.2%)")
    args = p.parse_args()
    capital = args.capital; fee = args.taker_fee; slippage = args.slippage

    if not os.path.exists(INPUT_CSV):
        print("فایل ورودی یافت نشد:", INPUT_CSV); return

    df = pd.read_csv(INPUT_CSV)
    df['signal_obj'] = df['signal'].apply(parse_signal_col)
    df = df[df['signal_obj'].notnull()].copy()
    if df.empty:
        print("هیچ سیگنالی برای پردازش در CSV وجود ندارد"); return

    rows = []
    for idx, r in df.iterrows():
        comp = compute_nominal_with_fees(r, capital, fee, slippage)
        # الحاق مقادیر محاسبه‌شده به ردیف
        for k,v in comp.items():
            r[k] = v
        rows.append(r)
    df2 = pd.DataFrame(rows)

    # نام‌گذاری ستون‌ها به فارسی برای CSV خروجی
    # ستون‌های اصلی: symbol,last_price,signal_side + محاسبات
    rename_map = {
        "symbol": "نماد",
        "last_price": "قیمت_آخر (USD)",
        "signal_side": "سمت_سیگنال",
        "واحدها": "واحدها",
        "ناتیشن (USD)": "ناتیشن (USD)",
        "سود ناخالص (USD)": "سود ناخالص (USD)",
        "سود خالص پس از کارمزد و لغزش (USD)": "سود خالص پس از کارمزد و لغزش (USD)",
        "درصد سود خالص نسبت به سرمایه": "درصد سود خالص نسبت به سرمایه",
        "ریسک ناخالص (USD)": "ریسک ناخالص (USD)",
        "ریسک خالص پس از کارمزد و لغزش (USD)": "ریسک خالص پس از کارمزد و لغزش (USD)",
        "Pips": "پیپ",
        "پیپ(تقریبی)": "پیپ(تقریبی)",
        "سود پیپ": "سود پیپ",
        "ریسک پیپ": "ریسک پیپ",
        "R/R ناخالص": "R/R ناخالص",
        "R/R خالص": "R/R خالص",
        "قیمت اجرایی ورود": "قیمت اجرایی ورود",
        "قیمت اجرایی تارگت (پس از اسلیپیج/فی)": "قیمت اجرایی تارگت",
        "قیمت اجرایی استاپ (پس از اسلیپیج/فی)": "قیمت اجرایی استاپ"
    }
    # فقط ستون‌های موجود را در CSV نگه می‌داریم و سپس تغییر نام می‌دهیم
    out_cols = [c for c in [
        "symbol","last_price","signal_side",
        "واحدها","ناتیشن (USD)","سود ناخالص (USD)","سود خالص پس از کارمزد و لغزش (USD)",
        "درصد سود خالص نسبت به سرمایه","ریسک ناخالص (USD)","ریسک خالص پس از کارمزد و لغزش (USD)",
        "پیپ(تقریبی)","سود پیپ","ریسک پیپ","R/R ناخالص","R/R خالص",
        "قیمت اجرایی ورود","قیمت اجرایی تارگت","قیمت اجرایی استاپ"
    ] if c in df2.columns]

    df_out = df2[out_cols].rename(columns=rename_map)
    df_out.to_csv(OUT_SUMMARY, index=False, encoding='utf-8-sig')
    print("خلاصه ذخیره شد:", OUT_SUMMARY)

    html_path = build_interactive_html(df2.reset_index(drop=True), OUT_HTML)
    print("فایل تعاملی HTML ساخته شد:", html_path)

    # نمایش کوتاه در کنسول
    disp_cols = [c for c in df_out.columns]
    pd.set_option('display.float_format', lambda x: '%.6g' % x)
    print("\nخلاصه سیگنال‌ها (بر اساس سرمایه {} USD و کارمزد {} و لغزش {}):\n".format(capital, fee, slippage))
    print(df_out.to_string(index=False))

if __name__ == "__main__":
    main()


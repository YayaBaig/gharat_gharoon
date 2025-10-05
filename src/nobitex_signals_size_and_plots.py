#!/usr/bin/env python3
# nobitex_signals_size_and_plots.py
# خواندن nobitex_dynamic_scan.csv ؛ دریافت سرمایه ورودی؛ محاسبه سود/ریسک و سایز پوزیشن؛ ساخت یک HTML تعاملی که همه سیگنال‌ها را نشان می‌دهد.
# اجرا:
# python nobitex_signals_size_and_plots.py --capital 10000 --risk-pct 1.0

import os, argparse, ast
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

INPUT_CSV = "nobitex_dynamic_scan.csv"
OUT_HTML = "nobitex_signals_all.html"
OUT_SUMMARY = "nobitex_signals_summary.csv"

def parse_signal_col(s):
    try:
        # signals stored as single-quoted dict string in CSV — use ast.literal_eval safely
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

def compute_sizes_and_returns(row, capital, risk_pct):
    sig = row['signal_obj']
    entry = float(sig['entry'])
    stop = float(sig['stop'])
    target = float(sig['target'])
    # dollar risk per unit
    dollar_risk_per_unit = abs(entry - stop)
    # desired dollar risk = capital * (risk_pct/100)
    desired_risk_usd = capital * (risk_pct / 100.0)
    if dollar_risk_per_unit <= 0:
        units = 0.0
    else:
        units = desired_risk_usd / dollar_risk_per_unit
    notional = units * entry
    gross_profit_per_unit = abs(target - entry)
    gross_profit_total = gross_profit_per_unit * units
    profit_pct_on_capital = (gross_profit_total / capital) * 100.0 if capital>0 else np.nan
    pip = pip_size_for_price(entry)
    profit_pips = gross_profit_per_unit / pip
    risk_pips = dollar_risk_per_unit / pip
    rr = (gross_profit_per_unit / dollar_risk_per_unit) if dollar_risk_per_unit>0 else np.nan
    return {
        "units": units,
        "notional": notional,
        "gross_profit_total": gross_profit_total,
        "profit_pct_on_capital": profit_pct_on_capital,
        "pip": pip,
        "profit_pips": profit_pips,
        "risk_pips": risk_pips,
        "rr": rr,
        "dollar_risk_per_unit": dollar_risk_per_unit,
        "desired_risk_usd": desired_risk_usd
    }

def build_interactive_html(df_signals, out_html):
    # one subplot per symbol (stacked)
    n = len(df_signals)
    cols = 1
    rows = n
    fig = make_subplots(rows=rows, cols=cols, shared_xaxes=False,
                        vertical_spacing=0.06,
                        subplot_titles=[f"{r['symbol']} — {r['signal_obj']['side'].upper()}" for _, r in df_signals.iterrows()])
    rindex = 1
    for _, row in df_signals.iterrows():
        sym = row['symbol']
        sig = row['signal_obj']
        price = float(row['last_price'])
        # simple horizontal line for current price
        fig.add_trace(go.Scatter(x=[0,1], y=[price,price], mode='lines', line=dict(color='lightgray'),
                                 name=f"{sym} price"), row=rindex, col=1)
        # markers for entry/stop/target
        fig.add_trace(go.Scatter(x=[0.33], y=[sig['entry']], mode='markers+text', marker=dict(color='blue',size=8),
                                 text=[f"entry {sig['entry']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.5], y=[sig['stop']], mode='markers+text', marker=dict(color='red',size=8),
                                 text=[f"stop {sig['stop']:.6g}"], textposition="bottom center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.66], y=[sig['target']], mode='markers+text', marker=dict(color='green',size=8),
                                 text=[f"target {sig['target']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        ymin = min(price, sig['stop'], sig['entry'], sig['target']) * 0.995
        ymax = max(price, sig['stop'], sig['entry'], sig['target']) * 1.005
        fig.update_yaxes(range=[ymin, ymax], row=rindex, col=1)
        # xref/yref: for first subplot use "x domain" / "y domain", otherwise "x{n} domain"
        if rindex == 1:
            xref = "x domain"
            yref = "y domain"
        else:
            xref = f"x{rindex} domain"
            yref = f"y{rindex} domain"
        stats_text = (f"Units: {row['units']:.6f}<br>"
                      f"Notional: {row['notional']:.2f} USD<br>"
                      f"Gross profit: {row['gross_profit_total']:.2f} USD<br>"
                      f"Profit% on capital: {row['profit_pct_on_capital']:.2f}%<br>"
                      f"R/R: {row['rr']:.2f}<br>"
                      f"Pips profit/risk: {row['profit_pips']:.0f}/{row['risk_pips']:.0f}")
        fig.add_annotation(text=stats_text, xref=xref, yref=yref,
                           x=0.98, y=0.5, showarrow=False, align="right")
        rindex += 1

    fig.update_layout(height=300*rows, title_text="Nobitex actionable signals — summary", showlegend=False, margin=dict(l=40,r=200,t=80,b=40))
    fig.write_html(out_html, include_plotlyjs='cdn')
    return out_html


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, required=True, help="Total capital in USD")
    p.add_argument("--risk-pct", type=float, default=1.0, help="Risk percent per trade (e.g., 1.0)")
    args = p.parse_args()

    if not os.path.exists(INPUT_CSV):
        print("Input CSV not found:", INPUT_CSV); return

    df = pd.read_csv(INPUT_CSV)
    # parse signal dict column
    df['signal_obj'] = df['signal'].apply(parse_signal_col)
    df = df[df['signal_obj'].notnull()].copy()
    if df.empty:
        print("No parsed signals found in CSV"); return

    # compute sizes and returns
    rows = []
    for idx, r in df.iterrows():
        comp = compute_sizes_and_returns(r, args.capital, args.risk_pct)
        for k,v in comp.items():
            r[k] = v
        rows.append(r)
    df2 = pd.DataFrame(rows)

    # write summary
    out_cols = ['symbol','last_price','signal_side','signal','units','notional','gross_profit_total','profit_pct_on_capital','rr']
    df2.to_csv(OUT_SUMMARY, index=False, columns=[c for c in df2.columns if c in out_cols])
    print("Wrote summary:", OUT_SUMMARY)

    # build interactive HTML
    html_path = build_interactive_html(df2.reset_index(drop=True), OUT_HTML)
    print("Wrote interactive HTML:", html_path)

    # also print a brief table to console
    disp = df2[['symbol','last_price','units','notional','gross_profit_total','profit_pct_on_capital','rr']]
    pd.set_option('display.float_format', lambda x: '%.6g' % x)
    print("\nSignals summary (based on capital {:.2f} USD and risk {}%):\n".format(args.capital, args.risk_pct))
    print(disp.to_string(index=False))

if __name__ == "__main__":
    main()


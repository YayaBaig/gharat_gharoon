#!/usr/bin/env python3
# nobitex_signals_size_and_plots_nominal.py
# Read nobitex_dynamic_scan.csv; compute units by allocating full capital at entry (no leverage),
# compute expected gross profit and risk in USD, produce summary CSV and interactive HTML.

import os, argparse, ast
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

INPUT_CSV = "nobitex_dynamic_scan.csv"
OUT_HTML = "nobitex_signals_all_nominal.html"
OUT_SUMMARY = "nobitex_signals_summary_nominal.csv"

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

def compute_nominal_sizes(row, capital):
    sig = row['signal_obj']
    entry = float(sig['entry'])
    stop = float(sig['stop'])
    target = float(sig['target'])
    # allocate full capital to buy at entry
    if entry <= 0:
        units = 0.0
    else:
        units = capital / entry
    notional = units * entry  # should equal capital (except rounding)
    gross_profit_per_unit = abs(target - entry)
    gross_profit_total = gross_profit_per_unit * units
    profit_pct_on_capital = (gross_profit_total / capital) * 100.0 if capital > 0 else np.nan
    dollar_risk_per_unit = abs(entry - stop)
    risk_total = dollar_risk_per_unit * units
    pip = pip_size_for_price(entry)
    profit_pips = gross_profit_per_unit / pip if pip>0 else np.nan
    risk_pips = dollar_risk_per_unit / pip if pip>0 else np.nan
    rr = (gross_profit_per_unit / dollar_risk_per_unit) if dollar_risk_per_unit>0 else np.nan
    return {
        "units": units,
        "notional": notional,
        "gross_profit_total": gross_profit_total,
        "profit_pct_on_capital": profit_pct_on_capital,
        "dollar_risk_per_unit": dollar_risk_per_unit,
        "risk_total": risk_total,
        "pip": pip,
        "profit_pips": profit_pips,
        "risk_pips": risk_pips,
        "rr": rr
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
                                 text=[f"entry {sig['entry']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.5], y=[sig['stop']], mode='markers+text', marker=dict(color='red',size=8),
                                 text=[f"stop {sig['stop']:.6g}"], textposition="bottom center", showlegend=False), row=rindex, col=1)
        fig.add_trace(go.Scatter(x=[0.66], y=[sig['target']], mode='markers+text', marker=dict(color='green',size=8),
                                 text=[f"target {sig['target']:.6g}"], textposition="top center", showlegend=False), row=rindex, col=1)
        ymin = min(price, sig['stop'], sig['entry'], sig['target']) * 0.995
        ymax = max(price, sig['stop'], sig['entry'], sig['target']) * 1.005
        fig.update_yaxes(range=[ymin, ymax], row=rindex, col=1)
        if rindex == 1:
            xref = "x domain"; yref = "y domain"
        else:
            xref = f"x{rindex} domain"; yref = f"y{rindex} domain"
        stats_text = (f"Units: {row['units']:.6f}<br>"
                      f"Notional: {row['notional']:.2f} USD<br>"
                      f"Gross profit: {row['gross_profit_total']:.2f} USD<br>"
                      f"Profit% on capital: {row['profit_pct_on_capital']:.2f}%<br>"
                      f"Risk total: {row['risk_total']:.2f} USD<br>"
                      f"R/R: {row['rr']:.2f}<br>"
                      f"Pips profit/risk: {int(row['profit_pips'])}/{int(row['risk_pips'])}")
        fig.add_annotation(text=stats_text, xref=xref, yref=yref, x=0.98, y=0.5, showarrow=False, align="right")
        rindex += 1

    fig.update_layout(height=300*n, title_text="Nobitex actionable signals — nominal allocation", showlegend=False, margin=dict(l=40,r=200,t=80,b=40))
    fig.write_html(out_html, include_plotlyjs='cdn')
    return out_html

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--capital", type=float, required=True, help="Total capital in USD")
    args = p.parse_args()
    capital = args.capital

    if not os.path.exists(INPUT_CSV):
        print("Input CSV not found:", INPUT_CSV); return

    df = pd.read_csv(INPUT_CSV)
    df['signal_obj'] = df['signal'].apply(parse_signal_col)
    df = df[df['signal_obj'].notnull()].copy()
    if df.empty:
        print("No parsed signals found in CSV"); return

    rows = []
    for idx, r in df.iterrows():
        comp = compute_nominal_sizes(r, capital)
        for k,v in comp.items():
            r[k] = v
        rows.append(r)
    df2 = pd.DataFrame(rows)

    out_cols = ['symbol','last_price','signal_side','units','notional','gross_profit_total','profit_pct_on_capital','risk_total','rr']
    df2.to_csv(OUT_SUMMARY, index=False, columns=[c for c in df2.columns if c in out_cols])
    print("Wrote summary:", OUT_SUMMARY)

    html_path = build_interactive_html(df2.reset_index(drop=True), OUT_HTML)
    print("Wrote interactive HTML:", html_path)

    disp = df2[['symbol','last_price','units','notional','gross_profit_total','profit_pct_on_capital','risk_total','rr']]
    pd.set_option('display.float_format', lambda x: '%.6g' % x)
    print("\nSignals summary (capital {:.2f} USD):\n".format(capital))
    print(disp.to_string(index=False))

if __name__ == "__main__":
    main()


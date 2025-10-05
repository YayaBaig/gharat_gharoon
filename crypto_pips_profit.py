#!/usr/bin/env python3
# crypto_pips_gui_fixed.py
# Fixed GUI tool for pip & profit calculation with leverage and fees.
# Run: python crypto_pips_gui_fixed.py

import tkinter as tk
from tkinter import ttk, messagebox
import math

# optional clipboard
try:
    import pyperclip
    _HAS_PYPERCLIP = True
except Exception:
    _HAS_PYPERCLIP = False

def safe_float_str(x, default=None):
    try:
        if x is None:
            return default
        s = str(x).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default

def calculate(entry, exit_price, side, pip, leverage, fee_pct, capital, calc_per_100):
    # convert and validate
    entry_f = safe_float_str(entry)
    exit_f = safe_float_str(exit_price)
    pip_f = safe_float_str(pip, 0.01)
    leverage_f = safe_float_str(leverage, 1.0)
    fee_pct_f = safe_float_str(fee_pct, 0.0)
    capital_f = safe_float_str(capital, 100.0)
    if entry_f is None or exit_f is None or pip_f is None or leverage_f is None or fee_pct_f is None or capital_f is None:
        return {"error": "یک یا چند ورودی عددی نامعتبر هستند. لطفاً مقادیر را بررسی کن."}
    if entry_f <= 0 or pip_f <= 0 or leverage_f < 1 or capital_f <= 0:
        return {"error": "ورودی‌ها باید اعداد مثبت معتبر باشند و لوریج حداقل 1 باشد."}

    fee = fee_pct_f / 100.0
    # direction
    if side.lower() == "long":
        price_diff = exit_f - entry_f
    else:
        price_diff = entry_f - exit_f

    pct_change = price_diff / entry_f
    pip_count = price_diff / pip_f

    # notional considering leverage
    notional = capital_f * leverage_f
    units_controlled = notional / entry_f
    gross_profit = units_controlled * price_diff

    # fees: assume fee on notional for each side
    fee_each = notional * fee
    total_fees = fee_each * 2
    net_profit = gross_profit - total_fees

    # per 100 USD baseline (with same leverage)
    base_cap = 100.0
    notional_100 = base_cap * leverage_f
    units_100 = notional_100 / entry_f
    gross_100 = units_100 * price_diff
    fees_100 = (notional_100 * fee) * 2
    net_100 = gross_100 - fees_100

    return {
        "price_diff": price_diff,
        "pct_change": pct_change,
        "pip_count": pip_count,
        "gross_profit_usd": gross_profit,
        "total_fees_usd": total_fees,
        "net_profit_usd": net_profit,
        "gross_per_100_usd": gross_100,
        "fees_per_100_usd": fees_100,
        "net_per_100_usd": net_100,
        "units_controlled": units_controlled,
        "entry": entry_f,
        "exit": exit_f,
        "pip": pip_f,
        "leverage": leverage_f,
        "fee_pct": fee_pct_f,
        "capital": capital_f,
        "calc_per_100": bool(calc_per_100)
    }

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Crypto Pips & Profit Calculator (fixed)")
        self.geometry("760x520")
        self.resizable(False, False)
        self.create_widgets()

    def create_widgets(self):
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        entries = [
            ("Entry price", "entry", "137.81"),
            ("Exit price", "exit", "189.93"),
            ("Side (Long/Short)", "side", "Long"),
            ("Pip size", "pip", "0.01"),
            ("Leverage (x)", "leverage", "1"),
            ("Fee percent (each side, %)", "fee", "0.04"),
            ("Capital (USD) for calc", "capital", "100"),
            ("Calculate per 100 USD", "per100", True)
        ]
        self.widgets = {}
        r = 0
        for label, key, default in entries:
            ttk.Label(frm, text=label).grid(row=r, column=0, sticky=tk.W, pady=6)
            if key == "side":
                v = tk.StringVar(value=default)
                cb = ttk.Combobox(frm, textvariable=v, values=["Long","Short"], width=20, state="readonly")
                cb.grid(row=r, column=1, sticky=tk.W)
                self.widgets[key] = v
            elif key == "per100":
                v = tk.BooleanVar(value=default)
                chk = ttk.Checkbutton(frm, variable=v)
                chk.grid(row=r, column=1, sticky=tk.W)
                self.widgets[key] = v
            else:
                ent = ttk.Entry(frm, width=24)
                ent.grid(row=r, column=1, sticky=tk.W)
                ent.insert(0, str(default))
                self.widgets[key] = ent
            r += 1

        btn_calc = ttk.Button(frm, text="Calculate", command=self.on_calc)
        btn_calc.grid(row=0, column=2, padx=12)
        btn_copy = ttk.Button(frm, text="Copy Result", command=self.on_copy)
        btn_copy.grid(row=1, column=2, padx=12)
        btn_clear = ttk.Button(frm, text="Clear", command=self.on_clear)
        btn_clear.grid(row=2, column=2, padx=12)

        ttk.Separator(frm, orient=tk.HORIZONTAL).grid(row=9, column=0, columnspan=3, sticky="ew", pady=8)
        self.result_text = tk.Text(frm, width=92, height=18, wrap=tk.WORD)
        self.result_text.grid(row=10, column=0, columnspan=3, pady=4)

    def on_calc(self):
        entry = self.widgets["entry"].get().strip()
        exitp = self.widgets["exit"].get().strip()
        side = self.widgets["side"].get().strip()
        pip = self.widgets["pip"].get().strip()
        leverage = self.widgets["leverage"].get().strip()
        fee = self.widgets["fee"].get().strip()
        capital = self.widgets["capital"].get().strip()
        per100 = self.widgets["per100"].get()

        res = calculate(entry, exitp, side, pip, leverage, fee, capital, per100)
        if "error" in res:
            messagebox.showerror("Input error", res["error"])
            return
        self.display_result(res)

    def display_result(self, r):
        self.result_text.delete("1.0", tk.END)
        lines = []
        lines.append(f"Side: {self.widgets['side'].get()}")
        lines.append(f"Entry: {r['entry']:.8f}    Exit: {r['exit']:.8f}")
        lines.append(f"Pip size: {r['pip']}    Pip count: {r['pip_count']:.6f}")
        lines.append(f"Price change: {r['price_diff']:.8f}    Percent change: {r['pct_change']*100:.4f} %")
        lines.append(f"Leverage: x{r['leverage']:.2f}    Capital used: {r['capital']:.2f} USD    Notional controlled: {r['capital']*r['leverage']:.2f} USD")
        lines.append(f"Units controlled: {r['units_controlled']:.8f} (notional / entry)")
        lines.append(f"Gross profit (USD): {r['gross_profit_usd']:.8f}")
        lines.append(f"Total fees (USD) [entry+exit]: {r['total_fees_usd']:.8f} (fee% each side: {r['fee_pct']:.4f}%)")
        lines.append(f"Net profit (USD): {r['net_profit_usd']:.8f}")
        lines.append("")
        lines.append("Per 100 USD baseline (same leverage):")
        lines.append(f"  Gross per 100 USD: {r['gross_per_100_usd']:.8f} USD")
        lines.append(f"  Fees per 100 USD: {r['fees_per_100_usd']:.8f} USD")
        lines.append(f"  Net per 100 USD: {r['net_per_100_usd']:.8f} USD")

        txt = "\n".join(lines)
        self.result_text.insert(tk.END, txt)
        self._last_result = txt

    def on_copy(self):
        txt = getattr(self, "_last_result", None)
        if not txt:
            txt = self.result_text.get("1.0", tk.END).strip()
        if not txt:
            messagebox.showinfo("Nothing to copy", "No result to copy")
            return
        if _HAS_PYPERCLIP:
            pyperclip.copy(txt)
            messagebox.showinfo("Copied", "Result copied to clipboard")
        else:
            # fallback: try tkinter clipboard
            try:
                self.clipboard_clear()
                self.clipboard_append(txt)
                messagebox.showinfo("Copied", "Result copied to clipboard (tk clipboard)")
            except Exception as e:
                messagebox.showerror("Copy failed", f"Clipboard not available: {e}")

    def on_clear(self):
        for k, w in self.widgets.items():
            if isinstance(w, ttk.Entry):
                w.delete(0, tk.END)
            elif isinstance(w, tk.StringVar):
                w.set("")
            elif isinstance(w, tk.BooleanVar):
                w.set(False)
        self.result_text.delete("1.0", tk.END)
        self._last_result = ""

if __name__ == "__main__":
    app = App()
    app.mainloop()


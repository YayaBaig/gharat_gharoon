# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Signal-scanning tools for Nobitex USDT markets (`https://apiv2.nobitex.ir`). Fetches OHLC candles, computes indicators (EMA/MA50, RSI, MACD, Bollinger, Fibonacci), and produces long/short signals with fee- and slippage-adjusted entry/stop/target, position size, and R:R. User-facing text, CSV headers, and many comments are in Persian (RTL); keep that convention in output and UI strings.

## Setup & running

There is no `requirements.txt`, build step, linter config, or test suite.

```bash
python -m venv venv && source venv/bin/activate
pip install requests pandas numpy plotly scipy   # scipy only needed by fib_support_signal.py

python app.py --port 8000                          # web dashboard (Windows: run_windows.bat)
python fib_support_signal.py --symbol BTCUSDT --capital 1000 [--nobitex-token TOKEN] [--use-local-csv 1D=path 4H=path 1H=path 15m=path]
python nobitex_list_symbols.py [--out FILE] [--delay SEC]        # discover symbols → CSV
python nobitex_symbols_usdt_fa.py [--out FILE] [--candidates A,B] # probe USDT symbols via orderbook → CSV
```

CLI scripts read the API token from `--nobitex-token` or the `NOBITEX_TOKEN` env var; most endpoints work without one.

## Architecture

All scripts are standalone, flat in the repo root, and each re-implements its own Nobitex fetch helpers (no shared module). Endpoints used: `/market/udf/history` (OHLC, UDF format → pandas DataFrame), `/v3/orderbook/{symbol}` (price/liquidity probing, symbol discovery).

- **`app.py`** — dashboard server built on stdlib `http.server` (no framework). Serves `gui/index.html` (single-file vanilla JS frontend) and `guide.html`, plus a JSON API:
  - `GET /api/status`, `GET /api/symbols` (alias `/api/available-symbols`), `GET /api/ohlc?symbol=&resolution=&token=`
  - `POST /api/scan` and `POST /api/save` — body includes symbols, capital, fee, slippage, token, optional `output_dir`; run `analyze_symbol()` per symbol and, when `output_dir` is set, write a Persian-headed CSV and `nobitex_signals_data.json` there.
  - Symbol list comes from `output/nobitex_symbols_list.csv` (produced by `nobitex_list_symbols.py`) merged with a hardcoded `COMMON_CANDIDATES` list, cached in a module global.
  - `analyze_symbol()` holds the core 1h signal logic (BB/MACD/RSI rules, Fibonacci from 48-bar high/low, fee/slippage-adjusted execution prices). It swallows all exceptions and returns `None`.
- **`fib_support_signal.py`** — separate multi-timeframe (1D/4H/1H/15m) Fibonacci + swing (scipy `argrelextrema`) + order-block analysis for one symbol; writes a Plotly HTML chart `<SYMBOL>_fib_signal.html` to the repo root.
- **`output/`** — generated CSV/JSON artifacts (also committed). Root-level `*_fib_signal.html` files are generated outputs too.

## Documentation

User docs are in Persian: `README.md`, `guide.html` (served by the dashboard at `/guide.html`), `docs/usage_examples.txt`, `docs/changelog.txt`. Keep them in sync when adding scripts, CLI flags, API endpoints, or output files. `guid.txt` is a historical scaffold describing an old `src/` layout that no longer exists — don't treat it as current.

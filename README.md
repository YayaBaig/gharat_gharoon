# nobitex_trading

ابزار اسکن و تولید سیگنال برای بازارهای USDT در نوبیتکس (`https://apiv2.nobitex.ir`).
شامل یک داشبورد وب محلی برای اسکن چند نماد به‌صورت هم‌زمان، یک تحلیل‌گر فیبوناچی چندتایم‌فریمی برای یک نماد، و اسکریپت‌های کشف نماد.

## ویژگی‌ها
- داشبورد وب (`app.py` + `gui/index.html`) با نمودار کندل‌استیک، اسکن گروهی نمادها و ذخیره خروجی CSV/JSON
- گرفتن OHLC از endpoint `/market/udf/history` و محاسبه EMA 12/26، MA50، RSI 14، MACD، Bollinger Bands و سطوح فیبوناچی
- تولید سیگنال Long/Short روی کندل 1h با entry/stop/target
- محاسبه قیمت اجرایی، تعداد واحد، سود و ریسک خالص و نسبت R:R پس از احتساب کارمزد و لغزش (کل سرمایه به هر سیگنال)
- تحلیل فیبوناچی + روند MA50 (4H/1H) + سقف/کف روز قبل + order-block روی 15m و خروجی نمودار HTML تعاملی
- کشف نمادها و قیمت bid/ask/spread از orderbook و خروجی CSV (با سربرگ انگلیسی یا فارسی)

## ساختار پروژه
- `app.py` — سرور داشبورد (کتابخانه استاندارد `http.server`) و API
- `gui/index.html` — رابط کاربری تک‌فایلی داشبورد
- `guide.html` — راهنمای داشبورد (در آدرس `/guide.html` سرو می‌شود)
- `fib_support_signal.py` — تحلیل فیبوناچی چندتایم‌فریمی برای یک نماد
- `nobitex_list_symbols.py` — کشف نمادها و نوشتن `nobitex_symbols_list.csv`
- `nobitex_symbols_usdt_fa.py` — بررسی نمادهای USDT و نوشتن CSV با سربرگ فارسی
- `run_windows.bat` — اجرای ۱-کلیکی داشبورد در ویندوز
- `output/` — خروجی‌های CSV/JSON
- `docs/` — نمونه‌های اجرا و changelog

## پیش‌نیازها
- Python 3.8+
- بسته‌ها: `requests`، `pandas`، `numpy`، `plotly` و `scipy` (فقط برای `fib_support_signal.py`)

```bash
python -m venv venv
source venv/bin/activate          # ویندوز: venv\Scripts\activate
pip install --upgrade pip
pip install requests pandas numpy plotly scipy
```

## نحوه استفاده

### ۱. داشبورد وب
```bash
python app.py --port 8000
```
سپس `http://localhost:8000` را در مرورگر باز کن (به‌صورت خودکار هم باز می‌شود). در ویندوز کافی است روی `run_windows.bat` دو بار کلیک کنی.

در داشبورد نمادها را انتخاب کن، سرمایه، کارمزد (پیش‌فرض 0.001) و لغزش (پیش‌فرض 0.002) را تنظیم کن و اسکن بگیر. اگر پوشه خروجی را مشخص کنی، این فایل‌ها در آن ذخیره می‌شوند:
- `خلاصه_سیگنال‌ها_نوبیتکس.csv`
- `nobitex_signals_data.json`

فهرست نمادهای داشبورد از `output/nobitex_symbols_list.csv` (در صورت وجود) به‌همراه یک فهرست پیش‌فرض از نمادهای رایج خوانده می‌شود؛ برای به‌روزرسانی آن مرحله ۳ را اجرا کن.

### ۲. تحلیل فیبوناچی یک نماد
```bash
python fib_support_signal.py --symbol BTCUSDT --capital 1000
```
توضیح سیگنال در ترمینال چاپ می‌شود و نمودار در `BTCUSDT_fib_signal.html` (ریشه پروژه) ذخیره می‌شود.
برای استفاده از داده محلی به‌جای API:
```bash
python fib_support_signal.py --symbol BTCUSDT --use-local-csv 1D=d.csv 4H=h4.csv 1H=h1.csv 15m=m15.csv
```

### ۳. کشف نمادها
```bash
python nobitex_list_symbols.py --out output/nobitex_symbols_list.csv
python nobitex_symbols_usdt_fa.py --out output/nobitex_symbols_usdt.csv --candidates FOOUSDT,BARUSDT
```

## توکن API
بیشتر endpointها بدون توکن کار می‌کنند. در اسکریپت‌های خط فرمان توکن از `--nobitex-token` یا متغیر محیطی `NOBITEX_TOKEN` خوانده می‌شود؛ در داشبورد از فیلد توکن در رابط کاربری.
توکن را در متغیر محیطی نگه دار و هرگز در مخزن commit نکن.

## نکات عملیاتی
- سیگنال‌ها فقط برای بررسی هستند و سفارشی ثبت نمی‌شود. قبل از هر معامله orderbook و عمق بازار را بررسی کن.
- سیگنال Long وقتی معتبرتر است که حداقل یک کندل 1h بالای نقطه ورود بسته شود.

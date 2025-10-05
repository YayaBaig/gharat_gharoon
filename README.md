# nobitex_trading

نخستین نسخه ابزار اسکن و تولید سیگنال برای بازارهای USDT در نوبیتکس (apiv2).  
این پروژه ابزارهای خط فرمانی برای کشف نمادها، گرفتن کندل 1h از endpoint UDF/history، محاسبه اندیکاتورها، فیلتر بر اساس نوسان و نقدینگی، تولید سیگنال‌های قابل بررسی و ساخت گزارش عددی و نمودار تعاملی HTML فراهم می‌کند.

## ویژگی‌ها
- کشف پویا نمادهای USDT با بررسی orderbook
- گرفتن OHLC (کندل 1h) از endpoint رسمی و محاسبه EMA, RSI, MACD, Bollinger Bands
- فیلتر بر اساس نوسان و حجم دلاری
- تولید سیگنال‌های Long/Short با محاسبه entry/stop/target
- محاسبه اندازه پوزیشن بر اساس تخصیص کل سرمایه یا درصد ریسک
- محاسبه خالص سود و ریسک پس از احتساب کارمزد و لغزش
- خروجی CSV با عناوین فارسی و نمودار HTML شامل کندل‌استیک 1h و نقاط ورود/استاپ/تارگت

## ساختار پروژه
- src/: اسکریپت‌های پایتون
- data/: داده‌های خام و cache
- output/: خروجی‌های CSV و HTML
- docs/: نمونه‌ها و changelog

## پیش‌نیازها
- Python 3.8+
- بسته‌های پایتون:
  - requests
  - pandas
  - numpy
  - plotly
  نصب سریع:
  ```bash
  python -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  pip install requests pandas numpy plotly


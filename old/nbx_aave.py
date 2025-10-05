import os, requests, json
TOKEN = "7fecf5964c24766fd64c4be370c293568aa52354"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}
symbol = "AAVEUSDT"  # یا "AAVE/USDT" بستگی به API دارد؛ اگر خطا داد هر دو را امتحان کن
url = f"https://api.nobitex.ir/v2/trades/{symbol}"
r = requests.get(url, headers=HEADERS, timeout=10)
print(r.status_code)
print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:4000])


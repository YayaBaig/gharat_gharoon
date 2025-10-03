import requests, json
TOKEN = "7fecf5964c24766fd64c4be370c293568aa52354"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

# POST market/stats
r = requests.post("https://api.nobitex.ir/market/stats", headers=HEADERS, json={"srcCurrency":"AAVE","dstCurrency":"USDT"}, timeout=10)
print(r.status_code, r.text[:200])

# GET symbols
r2 = requests.get("https://api.nobitex.ir/v2/market/symbols", headers=HEADERS, timeout=10)
print(r2.status_code, r2.text[:200])


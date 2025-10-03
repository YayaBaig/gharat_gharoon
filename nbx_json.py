import os, requests, json
TOKEN = "7fecf5964c24766fd64c4be370c293568aa52354"
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"}

candidates = [
  "https://api.nobitex.ir/v2/market/symbols",
  "https://api.nobitex.ir/v2/symbols",
  "https://api.nobitex.ir/markets",
  "https://api.nobitex.ir/market/symbols"
]
for url in candidates:
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        print("URL:", url, "status:", r.status_code)
        print(json.dumps(r.json(), ensure_ascii=False, indent=2)[:4000])  # print prefix
    except Exception as e:
        print("URL:", url, "error:", e)


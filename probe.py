import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "ust2022.csv": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2022/all?type=daily_treasury_yield_curve&field_tdr_date_value=2022&page&_format=csv",
 "ust2023.csv": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2023/all?type=daily_treasury_yield_curve&field_tdr_date_value=2023&page&_format=csv",
}
for k, u in URLS.items():
    t = time.time()
    try:
        r = requests.get(u, headers=UA, timeout=(10, 120))
        if r.status_code == 200 and len(r.content) < 60_000_000:
            open(f"probe_samples/{k}", "wb").write(r.content)
        print(f"{k:22s} {r.status_code} {time.time()-t:5.1f}s len={len(r.content)} :: {r.content[:150]!r}", flush=True)
    except Exception as e:
        print(f"{k:22s} ERR {type(e).__name__}: {str(e)[:150]}", flush=True)

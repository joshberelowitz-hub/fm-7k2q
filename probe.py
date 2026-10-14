import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "ecb_fm_bb_daily.csv": "https://data-api.ecb.europa.eu/service/data/FM/D.DE+FR+IT.EUR.4F.BB..YLD?format=csvdata&startPeriod=2026-09-25",
 "ecb_fm_bb_list.csv": "https://data-api.ecb.europa.eu/service/data/FM/D..EUR.4F.BB..YLD?format=csvdata&startPeriod=2026-10-08&detail=dataonly",
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

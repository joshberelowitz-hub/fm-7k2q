import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "gsw.csv": "https://www.federalreserve.gov/data/yield-curve-tables/feds200628.csv",
 "bbk_zero_all.csv": "https://api.statistiken.bundesbank.de/rest/data/BBSIS/M.I.ZST.ZI.EUR.S1311.B.A604..R.A.A._Z._Z.A?format=csv&startPeriod=1997-01",
 "bbk_zero_10y.csv": "https://api.statistiken.bundesbank.de/rest/data/BBSIS/M.I.ZST.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&startPeriod=2025-01",
 "boe_glc_month.zip": "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/glcnominalmonthedata.zip",
 "boe_glc_latest.zip": "https://www.bankofengland.co.uk/-/media/boe/files/statistics/yield-curves/latest-yield-curve-data.zip",
 "ecb_euribor1m.csv": "https://data-api.ecb.europa.eu/service/data/FM/M.U2.EUR.RT.MM.EURIBOR1MD_.HSTA?format=csvdata",
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

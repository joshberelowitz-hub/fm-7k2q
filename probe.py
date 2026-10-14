import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "dbn_imf_datasets": "https://api.db.nomics.world/v22/datasets/IMF?limit=200",
 "imf_sdmx3": "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/USA.GGXWDG_NGDP.A",
 "imf_sdmx21": "https://api.imf.org/external/sdmx/2.1/data/IMF.RES,WEO/USA.GGXWDG_NGDP.A",
 "imf_sdmx21_flows": "https://api.imf.org/external/sdmx/2.1/dataflow/IMF.RES",
 "dbn_bls": "https://api.db.nomics.world/v22/series/BLS/cu/CUSR0000SA0L1E?observations=1",
 "bbk_10y": "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZAR.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&startPeriod=2026-09-01",
 "oecd_full": "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,/USA+DEU+FRA+ITA+JPN+GBR+AUS+CAN+SWE+CHE.M.IRLT+IR3TIB.PA.....?startPeriod=1995-01&format=csvfile",
 "ecb_irs_multi": "https://data-api.ecb.europa.eu/service/data/IRS/M.DE+FR+IT.L.L40.CI.0000.EUR.N.Z?format=csvdata&startPeriod=2026-01",
 "yahoo_fx": "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?range=10y&interval=1d",
 "yahoo_dxy": "https://query1.finance.yahoo.com/v8/finance/chart/DX-Y.NYB?range=5d&interval=1d",
}
for k, u in URLS.items():
    t = time.time()
    try:
        r = requests.get(u, headers=UA, timeout=(10, 60))
        open(f"probe_samples/{k}.txt", "wb").write(r.content[:400000])
        print(f"{k:20s} {r.status_code} {time.time()-t:5.1f}s len={len(r.content)} :: {r.text[:200]!r}", flush=True)
    except Exception as e:
        print(f"{k:20s} ERR {time.time()-t:5.1f}s {type(e).__name__}: {str(e)[:150]}", flush=True)

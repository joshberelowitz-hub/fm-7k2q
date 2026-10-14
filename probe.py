import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "imf_ggsb.json": "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/USA+FRA+DEU+ITA+JPN+GBR.GGSB_NPGDP.A",
 "imf_ggcbp.json": "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/USA+FRA+DEU+ITA+JPN+GBR.GGCBP_G01_PGDP_PT.A",
 "imf_gginc.json": "https://api.imf.org/external/sdmx/3.0/data/dataflow/IMF.RES/WEO/+/USA+FRA+DEU+ITA+JPN+GBR.GGXCNL_NGDP.A",
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

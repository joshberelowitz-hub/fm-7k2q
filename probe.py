import requests, time, os
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}
os.makedirs("probe_samples", exist_ok=True)
URLS = {
 "stooq_fr.csv": "https://stooq.com/q/d/l/?s=10fry.b&i=d",
 "stooq_it.csv": "https://stooq.com/q/d/l/?s=10ity.b&i=d",
 "stooq_de.csv": "https://stooq.com/q/d/l/?s=10dey.b&i=d",
 "cnbc_quote.json": "https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols=FR10Y-FR%7CIT10Y-IT%7CDE10Y-DE&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json",
 "cnbc_hist_it.json": "https://ts-api.cnbc.com/harmony/app/charts/5Y.json?symbol=IT10Y-IT",
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

import requests, time
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept": "text/html,application/json,text/csv,*/*"}
URLS = {
 "imf_browserUA": "https://www.imf.org/external/datamapper/api/v1/GGXWDG_NGDP/USA/ITA",
 "imf_v2": "https://www.imf.org/external/datamapper/api/GGXWDG_NGDP/USA",
 "fred_browserUA": "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10",
 "dbn_imf_weo": "https://api.db.nomics.world/v22/series/IMF/WEO:latest/USA.GGXWDG_NGDP.pcent_gdp?observations=1",
 "dbn_imf_weo_search": "https://api.db.nomics.world/v22/series/IMF/WEO:latest?dimensions=%7B%22weo-country%22%3A%5B%22USA%22%5D%2C%22weo-subject%22%3A%5B%22GGXWDG_NGDP%22%5D%7D&observations=1",
 "dbn_fred": "https://api.db.nomics.world/v22/series/FED/H15?limit=1",
 "ecb_irs_it": "https://data-api.ecb.europa.eu/service/data/IRS/M.IT.L.L40.CI.0000.EUR.N.Z?format=csvdata&startPeriod=2026-01",
 "ecb_yc": "https://data-api.ecb.europa.eu/service/data/YC/B.U2.EUR.4F.G_N_A.SV_C_YM.SR_10Y?format=csvdata&startPeriod=2026-09",
 "oecd_finmark": "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_FINMARK,/USA+DEU+JPN+GBR.M.IRLT+IR3TIB.PA.....?startPeriod=2026-01&format=csvfilewithlabels",
 "ust_curve": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/2026/all?type=daily_treasury_yield_curve&field_tdr_date_value=2026&page&_format=csv",
 "mof_jgb": "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/jgbcme.csv",
 "mof_jgb_all": "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/historical/jgbcme_all.csv",
 "boe_10y": "https://www.bankofengland.co.uk/boeapps/database/_iadb-fromshowcolumns.asp?csv.x=yes&Datefrom=01/Jan/2026&Dateto=now&SeriesCodes=IUDMNPY&CSVF=TN&UsingCodes=Y&VPD=Y&VFD=N",
 "bbk_10y": "https://api.statistiken.bundesbank.de/rest/data/BBSIS/D.I.ZAR.ZI.EUR.S1311.B.A604.R10XX.R.A.A._Z._Z.A?format=csv&startPeriod=2026-09",
 "nyfed_acm": "https://www.newyorkfed.org/medialibrary/media/research/data_indicators/ACMTermPremium.xls",
 "yahoo_tnx": "https://query1.finance.yahoo.com/v8/finance/chart/%5ETNX?range=5d&interval=1d",
}
for k, u in URLS.items():
    t = time.time()
    try:
        r = requests.get(u, headers=UA, timeout=(10, 40))
        body = r.text[:250].replace("\n", " | ")
        print(f"{k:22s} {r.status_code} {time.time()-t:5.1f}s len={len(r.content)} :: {body}", flush=True)
    except Exception as e:
        print(f"{k:22s} ERR {time.time()-t:5.1f}s {type(e).__name__}: {str(e)[:150]}", flush=True)

# Fiscal Sustainability Monitor

Static page refreshed daily by GitHub Actions from public data (IMF, FRED, Yahoo Finance).

- `fiscal_core.py` — analytics (r−g, fiscal fatigue, recession scenarios, term premium decomposition, pricing)
- `loaders.py` — data downloads with cache fallback (`data/`)
- `build_page.py` — builds `site/index.html` (`--mock` for synthetic test data)
- `config.py`, `manual/politics.csv` — editable assumptions
- `tests/test_core.py` — analytics tests

See SETUP.md for deployment.

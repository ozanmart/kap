from __future__ import annotations

import re

from kap.scrapers.listings import get_bundled_companies


def test_bundled_registry_is_a_valid_minimum_snapshot() -> None:
    companies = get_bundled_companies()
    assert len(companies) >= 750
    tickers = [company.ticker for company in companies]
    assert len(tickers) == len(set(tickers))
    assert all(re.fullmatch(r"[A-Z0-9]{2,6}", ticker) for ticker in tickers)
    assert all(re.fullmatch(r"[0-9a-fA-F]{32}", company.company_id or "") for company in companies)

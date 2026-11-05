"""SEC EDGAR: ticker -> CIK, companyfacts (XBRL) y submissions (perfil)."""
import requests

from .. import cache
from ..config import SEC_USER_AGENT, TTL


def _get(url):
    if not SEC_USER_AGENT:
        raise RuntimeError("definí SEC_USER_AGENT='Nombre email' (la SEC lo exige)")
    r = requests.get(url, headers={"User-Agent": SEC_USER_AGENT, "Accept-Encoding": "gzip, deflate"}, timeout=30)
    r.raise_for_status()
    return r.json()


def cik_for(ticker):
    table = cache.cached("edgar", "company_tickers", TTL["tickers"],
                         lambda: _get("https://www.sec.gov/files/company_tickers.json"))
    t = ticker.upper().replace(".", "-")
    for row in table.values():
        if row["ticker"].upper() == t:
            return int(row["cik_str"])
    raise KeyError(f"{ticker} no figura en EDGAR")


def company_facts(cik):
    return cache.cached("edgar", f"facts-{cik}", TTL["edgar"],
                        lambda: _get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"))


def submissions(cik):
    def fetch():
        s = _get(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        keep = ("name", "tickers", "exchanges", "sicDescription", "fiscalYearEnd", "website")
        return {k: s.get(k) for k in keep}
    return cache.cached("edgar", f"subs-{cik}", TTL["edgar"], fetch)

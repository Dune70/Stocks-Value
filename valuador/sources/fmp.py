"""Financial Modeling Prep (plan gratis): consenso de ingresos. Opcional."""
import requests

from .. import cache
from ..config import FMP_API_KEY, TTL

URL = "https://financialmodelingprep.com/stable/analyst-estimates"


def revenue_estimates(ticker):
    """Devuelve lista de años con consenso, o None si no hay clave o el plan no lo incluye."""
    if not FMP_API_KEY:
        return None

    def fetch():
        r = requests.get(URL, params={"symbol": ticker, "period": "annual", "limit": 6,
                                      "apikey": FMP_API_KEY}, timeout=30)
        if r.status_code in (401, 402, 403):
            return {"error": r.status_code}
        r.raise_for_status()
        return r.json()

    data = cache.cached("fmp", f"est-{ticker}", TTL["fmp"], fetch)
    if not isinstance(data, list):
        return None
    return sorted(
        ({"date": d.get("date"), "revenue_avg": d.get("revenueAvg"), "revenue_low": d.get("revenueLow"),
          "revenue_high": d.get("revenueHigh"), "analysts": d.get("numAnalystsRevenue")} for d in data),
        key=lambda x: x["date"] or "")

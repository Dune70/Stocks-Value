"""Junta todas las fuentes de un ticker en un único JSON. Si una fuente falla, sigue y lo anota."""
import json
from datetime import datetime, timezone

from . import normalize
from .config import DATA_DIR, ERP
from .sources import damodaran, edgar, fmp, fred, yf


def read_json(p):
    raw = p.read_bytes()
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except UnicodeDecodeError:  # archivos viejos guardados con la codificación de Windows
        return json.loads(raw.decode("cp1252"))


def _load(name):
    p = DATA_DIR / name
    return read_json(p) if p.exists() else {}


def fetch(ticker):
    t = ticker.upper()
    w = []
    out = {"ticker": t, "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"), "currency": "USD"}

    subs, fin = {}, None
    try:
        cik = edgar.cik_for(t)
        out["cik"] = cik
        subs = edgar.submissions(cik)
        extra = [c for c in _load("cik_predecessors.json").get(t, []) if c != cik]
        cf = normalize.merge_facts(edgar.company_facts(cik), *[edgar.company_facts(c) for c in extra])
        if extra:
            out["cik_predecessors"] = extra
        fin = normalize.financials(cf, revenue_fallback=lambda: yf.annual_revenue(t))
        w += [f"EDGAR: {x}" for x in fin.pop("warnings")]
    except Exception as e:
        w.append(f"EDGAR: {e}")
    out["financials"] = fin

    try:
        info = yf.snapshot(t)
    except Exception as e:
        info = {}
        w.append(f"yfinance: {e}")
    out["profile"] = normalize.profile(t, info, subs, _load("summaries.json"))
    out["market"], mw = normalize.market(info, fin["shares_outstanding"] if fin else None,
                                         fin.pop("diluted_shares_wavg") if fin else None)
    w += [f"mercado: {x}" for x in mw]
    try:
        out["market"].update(yf.volatility(t))
    except Exception as e:
        w.append(f"volatilidad: {e}")

    rates = {"risk_free": None, "risk_free_date": None, "erp": ERP, "erp_source": "manual (VALUADOR_ERP)"}
    try:
        rf = fred.latest("DGS10")
        rates.update(risk_free=rf["value"], risk_free_date=rf["date"])
    except Exception as e:
        w.append(f"FRED: {e}")
    out["rates"] = rates

    out["industry"] = None
    ind = out["profile"].get("industry")
    if ind:
        try:
            out["industry"] = damodaran.industry_data(ind, _load("industry_map.json"))
            if out["industry"]["match_score"] < 0.9:
                cands = " | ".join(out["industry"]["candidates"])
                w.append(f"Damodaran: '{ind}' se asoció a '{out['industry']['damodaran_industry']}'. "
                         f"Candidatas: {cands}. Fijá la correcta en data/industry_map.json "
                         "(lista completa: python -m valuador industrias)")
        except Exception as e:
            w.append(f"Damodaran: {e}")

    try:
        out["estimates"] = fmp.revenue_estimates(t)
    except Exception as e:
        out["estimates"] = None
        w.append(f"FMP: {e}")
    if out["estimates"] is None:
        w.append("sin consenso de analistas: g1 saldrá de la tendencia histórica")

    out["warnings"] = w
    return out

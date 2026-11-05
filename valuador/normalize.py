"""Normaliza companyfacts (XBRL de la SEC) + yfinance a un esquema único.

Montos en USD; acciones en unidades. Cada concepto prueba varias etiquetas XBRL en orden,
porque las empresas cambian de etiqueta con los años.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

FLOW = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "RevenuesNetOfInterestExpense", "SalesRevenueGoodsNet", "SalesRevenueServicesNet",
                "RevenueFromContractWithCustomerProductAndService", "OperatingRevenue"],
    "gross_profit": ["GrossProfit"],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": [
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "income_tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "sbc": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    "dna": ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization", "Depreciation"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}

INSTANT = {
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash"],
    "short_investments": ["ShortTermInvestments", "MarketableSecuritiesCurrent",
                          "AvailableForSaleSecuritiesDebtSecuritiesCurrent"],
    "debt_total": ["LongTermDebt", "DebtLongtermAndShorttermCombinedAmount", "DebtInstrumentCarryingAmount"],
    "debt_noncurrent": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermNotesPayable",
                        "SeniorLongTermNotes", "ConvertibleDebtNoncurrent", "ConvertibleNotesPayableNoncurrent"],
    "debt_current": ["LongTermDebtCurrent", "DebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent",
                     "NotesPayableCurrent", "ConvertibleDebtCurrent"],
    "short_borrowings": ["ShortTermBorrowings", "CommercialPaper"],
    "lease_total": ["OperatingLeaseLiability"],
    "lease_noncurrent": ["OperatingLeaseLiabilityNoncurrent"],
    "lease_current": ["OperatingLeaseLiabilityCurrent"],
    "minority_interest": ["MinorityInterest"],
    "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "total_assets": ["Assets"],
    "nol": ["OperatingLossCarryforwards"],
}

ANNUAL_FORMS = {"10-K", "10-K/A", "10-KT"}
KEY_CONCEPTS = ("revenue", "operating_income", "cfo", "capex", "cash", "equity")

EXCHANGES = {"NMS": "Nasdaq", "NGM": "Nasdaq", "NCM": "Nasdaq", "NYQ": "NYSE",
             "ASE": "NYSE American", "PCX": "NYSE Arca", "BTS": "Cboe"}


# ---------- helpers XBRL ----------

def merge_facts(*cfs):
    """Une companyfacts de varios CIK (p. ej. una sociedad nueva y su predecesora)."""
    out = {"facts": {}}
    for cf in cfs:
        for ns, tags in cf.get("facts", {}).items():
            for tag, node in tags.items():
                dst = out["facts"].setdefault(ns, {}).setdefault(tag, {"units": {}})
                for unit, rows in node.get("units", {}).items():
                    dst["units"].setdefault(unit, []).extend(rows)
    return out


def _d(s):
    return date.fromisoformat(s)


def _units(cf, tag):
    for ns in ("us-gaap", "dei"):
        node = cf.get("facts", {}).get(ns, {}).get(tag)
        if node:
            u = node.get("units", {})
            return u.get("USD") or u.get("shares") or (next(iter(u.values())) if u else [])
    return []


def _dur(f):
    return (_d(f["end"]) - _d(f["start"])).days if f.get("start") else None


def _newest(a, b):
    return b if a is None or b.get("filed", "") > a.get("filed", "") else a


def annual_flow(cf, tags):
    """end -> {value, tag}. Por cada fecha de cierre usa la etiqueta de mayor prioridad disponible."""
    out = {}
    for tag in tags:
        best = {}
        for f in _units(cf, tag):
            dur = _dur(f)
            if f.get("form") in ANNUAL_FORMS and dur and 350 <= dur <= 380:
                best[f["end"]] = _newest(best.get(f["end"]), f)
        for end, f in best.items():
            out.setdefault(end, {"value": f["val"], "tag": tag})
    return out


def instant_at(cf, tags, end):
    for tag in tags:
        best = None
        for f in _units(cf, tag):
            if f["end"] == end and not f.get("start"):
                best = _newest(best, f)
        if best:
            return best["val"]
    return None


def ttm_flow(cf, tags, fy_end, annual_map=None):
    """Últimos 12 meses = anual + acumulado del año en curso − mismo acumulado del año anterior.
    El anual y los acumulados pueden venir de etiquetas distintas (las empresas las mezclan)."""
    annual = (annual_map if annual_map is not None else annual_flow(cf, tags)).get(fy_end)
    if annual is None:
        return None
    for tag in tags:
        pair = _ytd_pair(cf, tag, fy_end)
        if pair:
            c, p = pair
            return {"value": annual["value"] + c["val"] - p["val"], "end": c["end"], "tag": tag, "method": "ttm"}
    return {"value": annual["value"], "end": fy_end, "tag": annual["tag"], "method": "annual"}


def _ytd_pair(cf, tag, fy_end):
    """(acumulado actual, mismo acumulado del año anterior) de los 10-Q posteriores al cierre."""
    a_end = _d(fy_end)
    ytd = {}
    for f in _units(cf, tag):
        if f.get("start") and f.get("form", "").startswith("10-Q"):
            k = (f["start"], f["end"])
            ytd[k] = _newest(ytd.get(k), f)
    cur = [f for f in ytd.values()
           if abs((_d(f["start"]) - a_end).days - 1) <= 10 and _d(f["end"]) > a_end]
    if not cur:
        return None
    c = max(cur, key=lambda f: f["end"])
    pe, ps = _d(c["end"]) - timedelta(days=365), _d(c["start"]) - timedelta(days=365)
    prior = [f for f in ytd.values()
             if abs((_d(f["end"]) - pe).days) <= 10 and abs((_d(f["start"]) - ps).days) <= 10]
    if not prior:
        return None
    return c, max(prior, key=lambda f: f.get("filed", ""))


def latest_fact(cf, tag):
    facts = _units(cf, tag)
    if not facts:
        return None
    last = max(f["end"] for f in facts)
    return _newest_of([f for f in facts if f["end"] == last])


def _newest_of(rows):
    best = None
    for r in rows:
        best = _newest(best, r)
    return best


def shares_outstanding(cf):
    """Acciones en circulación de la portada del último 10-K/10-Q (suma las clases si hay varias)."""
    facts = _units(cf, "EntityCommonStockSharesOutstanding")
    if not facts:
        return None
    last = max(f["end"] for f in facts)
    rows = [f for f in facts if f["end"] == last]
    accn = _newest_of(rows).get("accn")
    return {"value": sum(f["val"] for f in rows if f.get("accn") == accn), "date": last}


# ---------- armado ----------

def _sum(*vals):
    present = [v for v in vals if v is not None]
    return sum(present) if present else None


def _ratio(a, b):
    return a / b if a is not None and b not in (None, 0) else None


def _compose(row):
    """Arma deuda y leases a partir de sus componentes y calcula derivados."""
    debt = row.pop("debt_total")
    nc, cur, sb = row.pop("debt_noncurrent"), row.pop("debt_current"), row.pop("short_borrowings")
    row["debt"] = _sum(debt if debt is not None else _sum(nc, cur), sb)
    lt, ln, lc = row.pop("lease_total"), row.pop("lease_noncurrent"), row.pop("lease_current")
    row["operating_leases"] = lt if lt is not None else _sum(ln, lc)
    return row


def _derive(row):
    rev = row.get("revenue")
    if row.get("pretax_income") is None and row.get("net_income") is not None and row.get("income_tax") is not None:
        row["pretax_income"] = row["net_income"] + row["income_tax"]
    if row.get("capex") is not None and row.get("dna") is not None:
        row["net_capex"] = row["capex"] - row["dna"]
    if row.get("operating_income") is None and row.get("pretax_income") is not None:
        row["operating_income"] = row["pretax_income"] + (row.get("interest_expense") or 0)
        row["operating_income_source"] = "estimado: resultado antes de impuestos + intereses"
    if row.get("gross_profit") is None and rev is not None and row.get("cost_of_revenue") is not None:
        row["gross_profit"] = rev - row["cost_of_revenue"]
    row["gross_margin"] = _ratio(row.get("gross_profit"), rev)
    row["operating_margin"] = _ratio(row.get("operating_income"), rev)
    pt = row.get("pretax_income")
    row["effective_tax_rate"] = _ratio(row.get("income_tax"), pt) if pt and pt > 0 else None
    row["fcf"] = row["cfo"] - row["capex"] if row.get("cfo") is not None and row.get("capex") is not None else None
    row["sbc_pct_revenue"] = _ratio(row.get("sbc"), rev)
    if row.get("equity") is not None:
        ic = row["equity"] + (row.get("debt") or 0) - (row.get("cash") or 0) - (row.get("short_investments") or 0)
        row["invested_capital"] = ic
        row["sales_to_capital"] = _ratio(rev, ic) if ic > 0 else None
    return row


def financials(cf, years=5, today=None, revenue_fallback=None):
    """revenue_fallback: función que devuelve {fecha_cierre: ingresos} si EDGAR no los tiene."""
    warnings = []
    rev = annual_flow(cf, FLOW["revenue"])
    if not rev and revenue_fallback:
        rev = {e: {"value": v, "tag": "yfinance"} for e, v in (revenue_fallback() or {}).items()}
        if rev:
            warnings.append("ingresos anuales tomados de yfinance (EDGAR no usa una etiqueta estándar)")
    if not rev:
        found = sorted(t for t in cf.get("facts", {}).get("us-gaap", {})
                       if "revenue" in t.lower() or "sales" in t.lower())
        raise ValueError("no hay ingresos anuales con las etiquetas conocidas. "
                         f"Etiquetas disponibles: {', '.join(found[:15]) or 'ninguna'}")
    ends = sorted(rev)[-years:]
    flows = {k: annual_flow(cf, tags) for k, tags in FLOW.items()}
    flows["revenue"] = rev

    annual = []
    for e in ends:
        row = {"fy": _d(e).year, "end": e}
        for k in FLOW:
            row[k] = flows[k].get(e, {}).get("value")
        for k, tags in INSTANT.items():
            row[k] = instant_at(cf, tags, e)
        annual.append(_derive(_compose(row)))
    for prev, row in zip(annual, annual[1:]):
        row["revenue_growth"] = _ratio(row["revenue"] - prev["revenue"], prev["revenue"]) if prev["revenue"] else None
    annual[0]["revenue_growth"] = None

    ttm = {"end": ends[-1], "method": "annual"}
    for k, tags in FLOW.items():
        r = ttm_flow(cf, tags, ends[-1], flows[k])
        ttm[k] = r["value"] if r else None
        if k == "revenue" and r:
            ttm["end"], ttm["method"] = r["end"], r["method"]
    _derive(ttm)

    assets = latest_fact(cf, "Assets")
    bdate = assets["end"] if assets else ends[-1]
    balance = {"date": bdate}
    for k, tags in INSTANT.items():
        balance[k] = instant_at(cf, tags, bdate)
    _compose(balance)
    for k in ("nol", "debt", "operating_leases"):  # algunos datos se informan solo en el 10-K
        last_k = annual[-1].get(k)
        if k == "debt" and balance.get(k) is not None and last_k and balance[k] < 0.5 * last_k:
            warnings.append(f"deuda del trimestre ({balance[k]/1e6:,.0f} M) es menos de la mitad de la del 10-K "
                            f"({last_k/1e6:,.0f} M): probablemente falta la de largo plazo; se usa la del 10-K")
            balance[k] = last_k
            continue
        if balance.get(k) is None and last_k is not None:
            balance[k] = annual[-1][k]
            if k != "nol":
                warnings.append(f"{k} del balance tomado del último 10-K ({annual[-1]['end']})")

    wavg = latest_fact(cf, "WeightedAverageNumberOfDilutedSharesOutstanding")
    shares = shares_outstanding(cf)

    last = annual[-1]
    missing = [k for k in KEY_CONCEPTS if last.get(k) is None]
    if missing:
        warnings.append(f"faltan en el último año: {', '.join(missing)}")
    if ttm["method"] != "ttm":
        warnings.append(f"TTM no disponible ({ttm['method']}); se usa el último año fiscal")
    today = today or date.today()
    if (today - _d(bdate)).days > 120:
        warnings.append(f"balance viejo: {bdate}")

    return {
        "fiscal_year_end": ends[-1][5:],
        "annual": annual,
        "ttm": ttm,
        "balance": balance,
        "shares_outstanding": shares,
        "diluted_shares_wavg": {"value": wavg["val"], "end": wavg["end"]} if wavg else None,
        "warnings": warnings,
    }


def profile(ticker, info, subs, summaries=None):
    web = info.get("website") or subs.get("website") or ""
    domain = urlparse(web if "://" in web else f"https://{web}").netloc.removeprefix("www.") if web else None
    exch = EXCHANGES.get(info.get("exchange")) or ((subs.get("exchanges") or [None])[0])
    return {
        "name": info.get("longName") or subs.get("name"),
        "exchange": exch,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "sic": subs.get("sicDescription"),
        "country": info.get("country"),
        "website": web or None,
        "domain": domain,
        "summary_es": (summaries or {}).get(ticker),
        "summary_en": info.get("longBusinessSummary"),
    }


def market(info, shares_edgar=None, diluted_wavg=None):
    """Devuelve (market, warnings). Elige la cuenta de acciones y la contrasta con capitalización / precio."""
    w = []
    ts = info.get("regularMarketTime")
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    mcap = info.get("marketCap")
    if shares_edgar:
        shares, src = shares_edgar["value"], f"EDGAR ({shares_edgar['date']})"
    elif info.get("impliedSharesOutstanding"):
        shares, src = info["impliedSharesOutstanding"], "yfinance (implied, todas las clases)"
    else:
        shares, src = info.get("sharesOutstanding"), "yfinance"
    implied = mcap / price if mcap and price else None
    if shares and implied and abs(shares / implied - 1) > 0.02:
        w.append(f"acciones: {shares:,.0f} ({src}) vs capitalización/precio {implied:,.0f}; "
                 "puede faltar una clase de acciones")
    if diluted_wavg and shares and diluted_wavg["value"] < shares * 0.01:
        w.append(f"diluted_shares_wavg = {diluted_wavg['value']:,} parece cargado en miles en el XBRL; se descarta")
        diluted_wavg = None
    if info.get("beta") is None:
        w.append("yfinance sin beta: se usará la beta de la industria (Damodaran)")
    return {
        "price": price,
        "price_time": datetime.fromtimestamp(ts, timezone.utc).isoformat() if isinstance(ts, (int, float)) else ts,
        "beta": info.get("beta"),
        "market_cap": mcap,
        "shares_outstanding": shares,
        "shares_source": src,
        "shares_implied_by_mcap": implied,
        "diluted_shares_wavg": diluted_wavg,
        "high_52w": info.get("fiftyTwoWeekHigh"),
        "low_52w": info.get("fiftyTwoWeekLow"),
    }, w

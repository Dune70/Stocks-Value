from datetime import date

import pytest

from valuador import normalize as n


def fact(val, end, start=None, form="10-K", filed="2025-02-15", accn="a1"):
    f = {"val": val, "end": end, "form": form, "filed": filed, "accn": accn}
    if start:
        f["start"] = start
    return f


def fy(year):
    return f"{year}-01-01", f"{year}-12-31"


@pytest.fixture
def cf():
    old_rev = [fact(70, fy(2020)[1], fy(2020)[0], filed="2021-02-15")]
    new_rev = [fact(v, fy(y)[1], fy(y)[0], filed=f"{y + 1}-02-15") for y, v in
               [(2021, 80), (2022, 90), (2023, 100), (2024, 110)]]
    new_rev += [
        fact(25, "2024-12-31", "2024-10-01", filed="2025-02-15"),            # trimestre: no es anual
        fact(60, "2025-06-30", "2025-01-01", form="10-Q", filed="2025-08-05"),  # YTD actual
        fact(50, "2024-06-30", "2024-01-01", form="10-Q", filed="2025-08-05"),  # YTD año anterior
        fact(28, "2025-06-30", "2025-04-01", form="10-Q", filed="2025-08-05"),  # trimestre suelto
    ]
    op = [fact(v, fy(y)[1], fy(y)[0]) for y, v in [(2023, -5), (2024, 5)]]
    return {"facts": {
        "us-gaap": {
            "SalesRevenueNet": {"units": {"USD": old_rev}},
            "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": new_rev}},
            "OperatingIncomeLoss": {"units": {"USD": op}},
            "Assets": {"units": {"USD": [fact(500, "2024-12-31"), fact(520, "2025-06-30", form="10-Q")]}},
            "LongTermDebtNoncurrent": {"units": {"USD": [fact(40, "2024-12-31"), fact(45, "2025-06-30", form="10-Q")]}},
            "LongTermDebtCurrent": {"units": {"USD": [fact(5, "2024-12-31")]}},
            "CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [fact(30, "2024-12-31"), fact(35, "2025-06-30", form="10-Q")]}},
            "StockholdersEquity": {"units": {"USD": [fact(200, "2024-12-31")]}},
        },
        "dei": {
            "EntityCommonStockSharesOutstanding": {"units": {"shares": [
                fact(900, "2025-01-31", accn="old"),
                fact(700, "2025-07-31", form="10-Q", filed="2025-08-05", accn="q2"),
                fact(300, "2025-07-31", form="10-Q", filed="2025-08-05", accn="q2"),
            ]}},
        },
    }}


def test_annual_switches_tags_and_skips_quarters(cf):
    out = n.annual_flow(cf, n.FLOW["revenue"])
    assert out["2020-12-31"] == {"value": 70, "tag": "SalesRevenueNet"}
    assert out["2024-12-31"]["value"] == 110


def test_financials_last_five_years(cf):
    f = n.financials(cf, today=date(2025, 9, 1))
    assert [r["fy"] for r in f["annual"]] == [2020, 2021, 2022, 2023, 2024]
    last = f["annual"][-1]
    assert last["revenue_growth"] == pytest.approx(0.1)
    assert last["operating_margin"] == pytest.approx(5 / 110)
    assert last["debt"] == 45
    assert last["invested_capital"] == 200 + 45 - 30


def test_ttm(cf):
    f = n.financials(cf, today=date(2025, 9, 1))
    assert f["ttm"]["revenue"] == 110 + 60 - 50
    assert f["ttm"]["method"] == "ttm"
    assert f["ttm"]["end"] == "2025-06-30"


def test_balance_uses_latest_date(cf):
    b = n.financials(cf, today=date(2025, 9, 1))["balance"]
    assert b["date"] == "2025-06-30"
    assert b["cash"] == 35
    assert b["debt"] == 45  # solo no corriente informado a esa fecha


def test_shares_sum_classes(cf):
    s = n.shares_outstanding(cf)
    assert s == {"value": 1000, "date": "2025-07-31"}


def test_warnings(cf):
    f = n.financials(cf, today=date(2026, 6, 1))
    assert any("faltan" in w for w in f["warnings"])        # sin cfo/capex
    assert any("balance viejo" in w for w in f["warnings"])


def test_profile_domain_and_exchange():
    p = n.profile("TEM", {"website": "https://www.tempus.com", "exchange": "NMS", "longName": "Tempus AI, Inc."},
                  {}, {"TEM": "Medicina de precisión con IA."})
    assert p["domain"] == "tempus.com"
    assert p["exchange"] == "Nasdaq"
    assert p["summary_es"].startswith("Medicina")


def test_fetch_survives_failing_sources(monkeypatch, tmp_path, cf):
    from valuador import fetch as fe

    def boom(*a, **k):
        raise ConnectionError("sin red")

    monkeypatch.setattr(fe.edgar, "cik_for", lambda t: 1)
    monkeypatch.setattr(fe.edgar, "submissions", lambda c: {"name": "Demo", "exchanges": ["Nasdaq"]})
    monkeypatch.setattr(fe.edgar, "company_facts", lambda c: cf)
    monkeypatch.setattr(fe.yf, "snapshot", boom)
    monkeypatch.setattr(fe.fred, "latest", boom)
    out = fe.fetch("tem")
    assert out["ticker"] == "TEM"
    assert out["financials"]["ttm"]["revenue"] == 120
    assert out["profile"]["name"] == "Demo"
    assert out["market"]["shares_outstanding"] == 1000
    assert any(w.startswith("yfinance") for w in out["warnings"])
    assert any(w.startswith("FRED") for w in out["warnings"])


def test_industry_candidates_prefer_shared_words():
    from valuador.sources.damodaran import candidates
    names = ["Information Services", "Heathcare Information and Technology", "Healthcare Products", "Software (System & Application)"]
    top = [c[0] for c in candidates("Health Information Services", names)]
    assert set(top[:2]) == {"Heathcare Information and Technology", "Information Services"}


def test_market_shares_checks():
    info = {"currentPrice": 77.8, "marketCap": 14_190_848_000, "sharesOutstanding": 177_357_848, "beta": None}
    m, w = n.market(info, None, {"value": 180049, "end": "2026-09-30"})
    assert m["shares_source"] == "yfinance"
    assert m["diluted_shares_wavg"] is None
    assert any("capitalización" in x for x in w)
    assert any("miles" in x for x in w)
    assert any("beta" in x for x in w)


def test_ttm_mixes_tags():
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fact(100, "2026-05-31", "2025-06-01", filed="2026-06-20")]}},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {"units": {"USD": [
            fact(30, "2026-08-31", "2026-06-01", form="10-Q", filed="2026-09-10"),
            fact(25, "2025-08-31", "2025-06-01", form="10-Q", filed="2026-09-10"),
        ]}},
    }}}
    r = n.ttm_flow(cf, n.FLOW["revenue"], "2026-05-31")
    assert r["method"] == "ttm" and r["value"] == 105 and r["end"] == "2026-08-31"


def test_missing_revenue_lists_tags():
    cf = {"facts": {"us-gaap": {"RevenuesFromSomethingOdd": {"units": {"USD": []}}}}}
    with pytest.raises(ValueError, match="RevenuesFromSomethingOdd"):
        n.financials(cf)


def test_revenue_fallback_with_edgar_quarters():
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [
            fact(314, "2026-09-30", "2026-01-01", form="10-Q", filed="2026-11-02"),
            fact(250, "2025-09-30", "2025-01-01", form="10-Q", filed="2026-11-02"),
        ]}},
        "OperatingIncomeLoss": {"units": {"USD": [fact(30, "2025-12-31", "2025-01-01")]}},
    }}}
    f = n.financials(cf, today=date(2026, 11, 4),
                     revenue_fallback=lambda: {"2024-12-31": 340.0, "2025-12-31": 330.0})
    assert [r["revenue"] for r in f["annual"]] == [340.0, 330.0]
    assert f["ttm"]["revenue"] == 330 + 314 - 250 and f["ttm"]["method"] == "ttm"
    assert any("yfinance" in w for w in f["warnings"])


def test_merge_and_estimated_ebit():
    a = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [fact(100, "2024-12-31", "2024-01-01")]}}}}}
    b = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fact(120, "2025-12-31", "2025-01-01", filed="2026-02-20")]}},
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest":
            {"units": {"USD": [fact(20, "2025-12-31", "2025-01-01")]}},
        "InterestExpense": {"units": {"USD": [fact(3, "2025-12-31", "2025-01-01")]}},
    }}}
    f = n.financials(n.merge_facts(a, b), today=date(2026, 3, 1))
    assert [r["revenue"] for r in f["annual"]] == [100, 120]
    last = f["annual"][-1]
    assert last["operating_income"] == 23 and "estimado" in last["operating_income_source"]


def test_partial_quarter_debt_uses_10k():
    cf = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [fact(100, "2025-12-31", "2025-01-01")]}},
        "Assets": {"units": {"USD": [fact(900, "2025-12-31"), fact(950, "2026-06-30", form="10-Q")]}},
        "LongTermDebt": {"units": {"USD": [fact(400, "2025-12-31")]}},
        "DebtCurrent": {"units": {"USD": [fact(30, "2026-06-30", form="10-Q")]}},
    }}}
    f = n.financials(cf, today=date(2026, 8, 1))
    assert f["balance"]["debt"] == 400
    assert any("menos de la mitad" in w for w in f["warnings"])

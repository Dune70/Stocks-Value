"""Tests del motor DCF. Los dos primeros tienen solución cerrada (perpetuidad) y se verifican a mano."""
import pytest

from valuador.engine import DCFInputs, value, with_
from valuador.engine.inputs import from_fundamentals


def flat(**kw):
    base = dict(revenue=1000.0, margin=0.20, g1=0.0, g_terminal=0.0, margin_target=0.20, sales_to_capital=2.0,
                tax_effective=0.25, tax_marginal=0.25, wacc_override=0.08, wacc_terminal=0.08, shares=10.0)
    base.update(kw)
    return DCFInputs(**base)


def test_zero_growth_is_a_perpetuity():
    # FCFF = 1000 × 20% × (1 − 25%) = 150 → valor = 150 / 8% = 1875
    r = value(flat())
    assert r["operating_value"] == pytest.approx(1875.0)
    assert r["value_per_share"] == pytest.approx(187.5)


def test_constant_growth_is_gordon():
    g, m, t, sc, w = 0.03, 0.20, 0.25, 2.0, 0.08
    roic = sc * m * (1 - t) * (1 + g)  # misma tasa de reinversión en los 10 años y en el terminal
    r = value(flat(g1=g, g_terminal=g, roic_terminal=roic, rf=0.04))
    nopat1 = 1000 * (1 + g) * m * (1 - t)
    fcff1 = nopat1 - 1000 * g / sc
    assert r["operating_value"] == pytest.approx(fcff1 / (w - g), rel=1e-9)


def test_equity_bridge():
    r = value(flat(debt=300, leases=50, minority=20, cash=100, non_operating=30, options=60))
    assert r["value_per_share"] == pytest.approx((1875 - 300 - 50 - 20 + 100 + 30 - 60) / 10)


def test_nol_shields_taxes():
    r = value(flat(revenue=100.0, margin=0.10, margin_target=0.10, nol=25.0))
    taxes = [y["tax"] for y in r["years"][:4]]
    assert taxes == pytest.approx([0, 0, 5 * 0.25, 10 * 0.25])
    assert r["years"][2]["nol_end"] == 0


def test_losses_add_to_nol():
    r = value(flat(margin=-0.10, margin_target=0.10, years_to_target=4))
    y1, y2 = r["years"][:2]
    assert y1["ebit"] == pytest.approx(-50)          # margen año 1 = −10% + 20%/4 = −5%
    assert y1["tax"] == 0 and y1["nol_end"] == pytest.approx(50)
    assert y2["ebit"] == pytest.approx(0) and y2["nol_end"] == pytest.approx(50)


def test_paths():
    i = flat(g1=0.20, g_terminal=0.03, margin=0.05, margin_target=0.25, years_to_target=7,
             tax_effective=0.10, tax_marginal=0.25, wacc_override=0.10, wacc_terminal=0.08, rf=0.04)
    ys = value(i)["years"]
    assert ys[0]["growth"] == 0.20 and ys[9]["growth"] == pytest.approx(0.03)
    assert ys[0]["margin"] == pytest.approx(0.05 + 0.20 / 7) and ys[6]["margin"] == pytest.approx(0.25)
    assert ys[4]["tax_rate"] == 0.10 and ys[9]["tax_rate"] == pytest.approx(0.25)
    assert ys[4]["wacc"] == 0.10 and ys[9]["wacc"] == pytest.approx(0.08)
    ys5 = value(with_(i, high_growth_years=5))["years"]
    assert all(y["growth"] == 0.20 for y in ys5[:5]) and ys5[9]["growth"] == pytest.approx(0.03)


def test_cost_of_capital():
    i = flat(wacc_override=None, rf=0.04, erp=0.05, beta_unlevered=1.0, market_cap=750.0, debt=200.0,
             leases=50.0, pre_tax_cost_debt=0.06, tax_marginal=0.25)
    c = value(i)["cost_of_capital"]
    beta = 1.0 * (1 + 0.75 * 250 / 750)
    assert c["beta_levered"] == pytest.approx(beta)
    assert c["wacc"] == pytest.approx(0.75 * (0.04 + beta * 0.05) + 0.25 * 0.06 * 0.75)


def test_guards_and_warnings():
    with pytest.raises(ValueError):
        value(flat(g_terminal=0.08))
    r = value(flat(g1=0.05, g_terminal=0.05, rf=0.04))
    assert any("libre de riesgo" in w for w in r["warnings"])


def test_more_margin_more_value():
    vals = [value(flat(margin_target=m, g1=0.10, g_terminal=0.03, rf=0.04))["value_per_share"]
            for m in (0.10, 0.15, 0.20)]
    assert vals == sorted(vals)


def test_from_fundamentals():
    data = {
        "financials": {
            "annual": [{"effective_tax_rate": None}],
            "ttm": {"revenue": 1500.0, "operating_margin": -0.18, "interest_expense": 40.0, "operating_income": -270.0},
            "balance": {"debt": 200.0, "operating_leases": 80.0, "cash": 600.0, "short_investments": None,
                        "minority_interest": None, "nol": 900.0},
        },
        "market": {"shares_outstanding": 180.0, "market_cap": 14000.0, "price": 77.8},
        "rates": {"risk_free": 0.049, "erp": 0.045},
        "industry": {"unlevered_beta": 0.9},
    }
    i, notes = from_fundamentals(data, g1=0.25, margin_target=0.20, sales_to_capital=1.5)
    assert i.revenue == 1500 and i.margin == -0.18 and i.nol == 900
    assert i.g_terminal == pytest.approx(0.044) and i.tax_effective == 0
    assert i.pre_tax_cost_debt == pytest.approx(0.049 + 0.08)  # 40/200 = 20%, recortado a rf + 8 pp
    assert any("tasa efectiva" in n for n in notes)
    assert value(i)["value_per_share"] > 0

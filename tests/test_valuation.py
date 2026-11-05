import math

import pytest

from valuador import assumptions as A
from valuador import ladder
from valuador.engine import value, with_
from valuador.engine.reverse import implied_growth, implied_margin
from valuador.valuation import valuate
from tests.test_dcf import flat


def sample(**kw):
    d = {
        "ticker": "DEMO",
        "financials": {
            "annual": [{"revenue": 800.0, "sales_to_capital": 1.8, "effective_tax_rate": 0.2},
                       {"revenue": 880.0, "sales_to_capital": 2.0, "effective_tax_rate": 0.2},
                       {"revenue": 968.0, "sales_to_capital": 2.2, "effective_tax_rate": 0.2}],
            "ttm": {"end": "2026-09-30", "revenue": 1000.0, "operating_margin": 0.20, "operating_income": 200.0,
                    "interest_expense": 5.0},
            "balance": {"debt": 100.0, "operating_leases": 0.0, "cash": 50.0, "nol": 0.0},
        },
        "market": {"price": 50.0, "market_cap": 2000.0, "shares_outstanding": 40.0, "vol_1y": 0.30},
        "rates": {"risk_free": 0.045, "erp": 0.045},
        "industry": {"unlevered_beta": 1.0, "operating_margin": 0.15},
        "estimates": None,
    }
    d.update(kw)
    return d


def test_base_drivers():
    g1, m, sc, notes = A.base_drivers(sample())
    assert g1 == pytest.approx(0.10)          # 800 → 968 en 2 años = 10% anual
    assert m == 0.20                           # el actual supera a la industria
    assert sc == pytest.approx(2.0)            # mediana histórica


def test_scenarios_ordered_and_overrides():
    p, _ = A.scenario_params(sample(), {"all": {"nol": 5.0}, "base": {"g1": 0.12}})
    gs = [p[s]["g1"] for s in A.SCENARIOS]
    assert gs == sorted(gs)
    assert p["base"]["g1"] == 0.12 and all(p[s]["nol"] == 5.0 for s in A.SCENARIOS)


def test_negative_growth_still_spreads():
    d = sample()
    d["financials"]["annual"] = [{"revenue": 1000.0}, {"revenue": 970.0}]
    p, _ = A.scenario_params(d)
    assert p["conservador"]["g1"] < p["base"]["g1"] < p["optimista"]["g1"]


def test_weights():
    w, mod, _ = A.weights({"weights": {"conservador": 0.30, "optimista": 0.20}})
    assert w == {"conservador": 0.30, "base": 0.50, "optimista": 0.20} and mod
    w, mod, notes = A.weights({"weights": {"conservador": 0.40, "optimista": 0.10}})
    assert w == A.DEFAULT_WEIGHTS and not mod and "inválida" in notes[0]


def test_ladder_rules_and_reach():
    sc = {"todo_mal": 40, "conservador": 57, "base": 72, "optimista": 91, "todo_bien": 120}
    t = ladder.thresholds(sc)
    assert t == pytest.approx([40, 57, 64.5, 68.4, 81.5, 91, 120])
    r = ladder.build(sc, 93.0, 0.19)
    assert r["recommendation"] == "Vender"
    reach = {z["zone"]: z["reachable_1y"] for z in r["zones"]}
    lo, hi = 93 * math.exp(-0.19), 93 * math.exp(0.19)      # 76,9 – 112,6
    assert reach["Mantener"] and reach["Reducir"] and reach["Vender"]
    assert not reach["Sumar de a poco"] and not reach["Venta excepcional"]
    assert r["tolerance"]["moves_up_above"] == pytest.approx(120 * 1.08)
    assert lo < 81.5 < hi


def test_ladder_never_decreasing():
    t = ladder.thresholds({"todo_mal": 10, "conservador": 5, "base": 20, "optimista": 30, "todo_bien": 25})
    assert t == sorted(t)


def test_reverse_dcf():
    i = flat(g1=0.08, g_terminal=0.03, rf=0.04, margin=0.10, margin_target=0.20, years_to_target=5)
    target = value(i)["value_per_share"] * 1.3
    m = implied_margin(i, target)
    assert value(with_(i, margin_target=m))["value_per_share"] == pytest.approx(target, rel=1e-6)
    g = implied_growth(i, target)
    assert value(with_(i, g1=g))["value_per_share"] == pytest.approx(target, rel=1e-6)
    assert implied_margin(i, 1e9) is None


def test_valuate_end_to_end():
    r = valuate(sample(), {"weights": {"conservador": 0.30, "optimista": 0.20}})
    sc = r["scenarios"]
    vals = [sc[s]["value_per_share"] for s in A.SCENARIOS]
    assert vals == sorted(vals)
    assert r["intrinsic"] == pytest.approx(0.30 * vals[1] + 0.50 * vals[2] + 0.20 * vals[3])
    assert r["range"][0] <= r["intrinsic"] <= r["range"][1]
    assert r["weights_modified"]
    assert r["potential"] == pytest.approx(r["intrinsic"] / 50 - 1)
    assert r["recommendation"] in ladder.ZONES


def test_mature_company_keeps_scenarios_ordered():
    # crecimiento base cerca de rf: el escenario "todo bien" no debe cambiar a WACC terminal de beta 1
    d = sample()
    d["financials"]["annual"] = [{"revenue": 900.0, "sales_to_capital": 2.0},
                                 {"revenue": 940.0, "sales_to_capital": 2.0},
                                 {"revenue": 980.0, "sales_to_capital": 2.0}]
    d["industry"]["unlevered_beta"] = 0.6
    r = valuate(d)
    vals = [r["scenarios"][s]["value_per_share"] for s in A.SCENARIOS]
    assert vals == sorted(vals)


def test_base_override_moves_all_scenarios():
    r = valuate(sample(), {"base": {"g1": 0.25, "sales_to_capital": 0.8}})
    sc = r["scenarios"]
    assert sc["base"]["assumptions"]["g1"] == 0.25
    assert sc["conservador"]["assumptions"]["g1"] < 0.25 < sc["optimista"]["assumptions"]["g1"]
    vals = [sc[s]["value_per_share"] for s in A.SCENARIOS]
    assert vals == sorted(vals)
    assert any("fijado a mano" in n for n in r["notes"])

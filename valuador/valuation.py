"""Fase 3: de fundamentals.json a valuation.json (escenarios, intrínseco, rango, DCF inverso, escalera)."""
from __future__ import annotations

from datetime import datetime, timezone

from . import assumptions as A
from . import ladder
from .engine import value, with_
from .engine.inputs import from_fundamentals
from .engine.reverse import implied_growth, implied_margin

GRID = (-0.005, 0.0, 0.005)


def _intrinsic(per_share: dict, w: dict) -> float:
    return sum(w[s] * per_share[s] for s in A.WEIGHTED)


def valuate(data: dict, overrides: dict = None) -> dict:
    notes = []
    price = data["market"]["price"]
    params, n1 = A.scenario_params(data, overrides)
    w, w_mod, n2 = A.weights(overrides)
    notes += n1 + n2

    inputs, results = {}, {}
    ov = overrides or {}
    mature = params["base"]["g1"] <= data["rates"]["risk_free"] + 0.01
    for s in A.SCENARIOS:
        inp, n = from_fundamentals(data, **params[s])
        inp, n2 = A.terminal(inp, data, s, {**ov.get("all", {}), **ov.get(s, {})}, mature)
        inputs[s], results[s] = inp, value(inp)
        if s == "base":
            notes += n + n2
    # responsabilidad limitada: la acción no vale menos que cero
    per_share = {s: max(0.0, results[s]["value_per_share"]) for s in A.SCENARIOS}
    intrinsic = _intrinsic(per_share, w)

    # rango: sensibilidad de los tres escenarios ponderados a WACC ±0,5 pp y g terminal ±0,5 pp
    grid = []
    for dw in GRID:
        for dg in GRID:
            ps = {}
            for s in A.WEIGHTED:
                i = inputs[s]
                try:
                    ps[s] = max(0.0, value(with_(i, wacc_shift=i.wacc_shift + dw,
                                                g_terminal=i.g_terminal + dg))["value_per_share"])
                except ValueError:
                    break
            else:
                grid.append({"wacc_shift": dw, "g_shift": dg, "intrinsic": _intrinsic(ps, w)})
    vals = [g["intrinsic"] for g in grid]

    base = inputs["base"]
    m_imp, g_imp = implied_margin(base, price), implied_growth(base, price)
    reverse = {"margin": m_imp, "growth_g1": g_imp, "current_margin": base.margin,
               "base_margin": base.margin_target, "base_g1": base.g1}
    if g_imp is not None and g_imp <= 0.01:
        reverse["note"] = "el precio supone que la empresa prácticamente no vuelve a crecer"

    vol = data["market"].get("vol_1y")
    lad = ladder.build(per_share, price, vol)

    warnings = []
    for s in A.SCENARIOS:
        warnings += [f"{A.LABELS[s]}: {x}" for x in results[s]["warnings"]]

    return {
        "ticker": data["ticker"],
        "as_of": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "price": price,
        "price_time": data["market"].get("price_time"),
        "profile": data.get("profile"),
        "scenarios": {
            s: {"label": A.LABELS[s], "value_per_share": per_share[s], "weight": w.get(s, 0.0),
                "description": A.describe(params[s]),
                "assumptions": {k: params[s][k] for k in ("g1", "margin_target", "sales_to_capital",
                                                          "years_to_target", "g_terminal", "p_failure")},
                "wacc": results[s]["cost_of_capital"]["wacc"],
                "terminal_share": results[s]["terminal_share"]}
            for s in A.SCENARIOS
        },
        "weights_modified": w_mod,
        "intrinsic": intrinsic,
        "range": [min(vals), max(vals)] if vals else None,
        "sensitivity": grid,
        "potential": intrinsic / price - 1,
        "margin_of_safety": (intrinsic - price) / intrinsic if intrinsic else None,
        "reverse_dcf": reverse,
        "ladder": lad,
        "recommendation": lad["recommendation"],
        "volatility_1y": vol,
        "notes": notes,
        "warnings": warnings,
    }

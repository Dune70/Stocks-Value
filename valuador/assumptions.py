"""Paso de datos a supuestos: escenario base desde datos y los otros cuatro como desvíos con reglas fijas.

Todo se puede pisar por ticker en data/overrides.json:
{
  "TEM": {
    "all":         {"nol": 1500000000},           # cualquier campo de DCFInputs, para todos los escenarios
    "base":        {"g1": 0.25, "margin_target": 0.20},
    "conservador": {"margin_target": 0.12},
    "weights":     {"conservador": 0.30, "optimista": 0.20}
  }
}
"""
from __future__ import annotations

from statistics import median

SCENARIOS = ["todo_mal", "conservador", "base", "optimista", "todo_bien"]
WEIGHTED = ["conservador", "base", "optimista"]
LABELS = {"todo_mal": "Todo sale mal", "conservador": "Conservador", "base": "Base",
          "optimista": "Optimista", "todo_bien": "Todo sale bien"}

# Desvíos respecto del base. g: multiplicador del crecimiento año 1 · m: multiplicador del margen objetivo
# ytt: años hasta el margen objetivo · sc: multiplicador de ventas/capital
# dw: puntos de WACC · dg: g terminal = rf + dg · pf: probabilidad de quiebra si hoy pierde plata
# moat: qué parte del exceso de retorno actual (ROIC − WACC terminal) se conserva a perpetuidad
RULES = {
    "todo_mal":    dict(g=0.4, m=0.70, ytt=10, sc=0.75, dw=0.010, dg=-0.015, pf=0.15, moat=0.0),
    "conservador": dict(g=0.7, m=0.85, ytt=8, sc=0.90, dw=0.005, dg=-0.010, pf=0.05, moat=0.25),
    "base":        dict(g=1.0, m=1.00, ytt=7, sc=1.00, dw=0.000, dg=-0.005, pf=0.0, moat=0.5),
    "optimista":   dict(g=1.2, m=1.15, ytt=6, sc=1.10, dw=-0.0025, dg=0.000, pf=0.0, moat=0.75),
    "todo_bien":   dict(g=1.5, m=1.30, ytt=5, sc=1.25, dw=-0.005, dg=0.000, pf=0.0, moat=1.0),
}
DEFAULT_WEIGHTS = {"conservador": 0.25, "base": 0.50, "optimista": 0.25}
HIGH_GROWTH_YEARS = 5
SC_DEFAULT = 1.5
SC_MAX = 5.0
ROIC_CAP = 0.25   # tope del ROIC que se puede conservar a perpetuidad


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def base_drivers(data: dict) -> tuple:
    """(g1, margen objetivo, ventas/capital) del escenario base + notas de dónde salió cada uno."""
    notes = []
    fin = data["financials"]
    ttm_rev = fin["ttm"]["revenue"]

    g1 = None
    for e in data.get("estimates") or []:
        if e.get("revenue_avg") and e.get("date", "") > fin["ttm"]["end"]:
            g1 = e["revenue_avg"] / ttm_rev - 1
            notes.append(f"g1 del consenso de analistas ({e['date'][:4]})")
            break
    if g1 is None:
        revs = [r["revenue"] for r in fin["annual"] if r.get("revenue")]
        if len(revs) >= 2:
            n = min(3, len(revs) - 1)
            cagr = (revs[-1] / revs[-1 - n]) ** (1 / n) - 1
            recent = ttm_rev / revs[-1] - 1 if fin["ttm"].get("method") == "ttm" else None
            last = revs[-1] / revs[-2] - 1
            # el último dato pesa más: TTM contra el último año fiscal, anualizado, o el último año completo
            if recent is not None and fin["ttm"]["end"] > fin["annual"][-1]["end"]:
                from datetime import date
                months = max(1, (date.fromisoformat(fin["ttm"]["end"]) - date.fromisoformat(fin["annual"][-1]["end"])).days / 30.4)
                if months >= 3:  # menos de un trimestre nuevo no alcanza para leer tendencia
                    last = (1 + recent) ** (12 / months) - 1
            g1 = 0.5 * cagr + 0.5 * last
            notes.append(f"g1 = mitad tendencia de {n} años ({cagr:.1%}) y mitad último año ({last:.1%})")
        else:
            g1 = 0.03
            notes.append("g1 = 3% por falta de historia")
    if not -0.05 <= g1 <= 0.35:
        notes.append(f"g1 recortado de {g1:.1%} al rango −5% / 35%")
    g1 = _clip(g1, -0.05, 0.35)

    cur = fin["ttm"].get("operating_margin")
    ind = (data.get("industry") or {}).get("operating_margin")
    if ind is not None and cur is not None:
        m = max(ind, cur)
        notes.append("margen objetivo = " + ("el actual (supera a la industria)" if cur > ind else "el de la industria"))
    elif cur is not None:
        m = max(cur, 0.10)
        notes.append("margen objetivo = actual o 10% (sin dato de industria)")
    else:
        m = ind if ind is not None else 0.10
    m = _clip(m, 0.02, 0.60)

    sc, n = sales_to_capital(fin)
    notes.append(n)
    return g1, m, sc, notes


def sales_to_capital(fin: dict) -> tuple:
    """Promedio de dos lecturas: ventas / capital invertido (stock) y ventas nuevas / reinversión neta
    (capex − amortizaciones) de los últimos años. La segunda corrige empresas con capital inflado por
    adquisiciones (KO) o con una ola de inversión reciente (ORCL)."""
    ann = fin["annual"]
    stock = [r.get("sales_to_operating_capital") or r.get("sales_to_capital") for r in ann]
    stock = [x for x in stock if x is not None]
    stock = median(stock) if stock else None
    marginal = None
    revs = [r for r in ann if r.get("revenue")]
    if len(revs) >= 3:
        d_rev = revs[-1]["revenue"] - revs[0]["revenue"]
        reinv = sum(r.get("net_capex") or 0 for r in revs[1:])
        if reinv > 0 and d_rev > 0:
            marginal = d_rev / reinv
    vals = [min(max(x, 0.3), SC_MAX) for x in (stock, marginal) if x is not None and x > 0]
    if not vals:
        return SC_DEFAULT, f"ventas/capital = {SC_DEFAULT} (la histórica no es usable)"
    sc = sum(vals) / len(vals)
    parts = []
    if stock is not None:
        parts.append(f"sobre capital {stock:.2f}")
    if marginal is not None:
        parts.append(f"sobre reinversión {marginal:.2f}")
    return sc, f"ventas/capital = {sc:.2f} (promedio de {' y '.join(parts)}, cada uno recortado a 0,3–{SC_MAX:g}; capital sin goodwill)"


def roic_now(data: dict) -> float:
    """ROIC actual = NOPAT TTM / (patrimonio + deuda − caja)."""
    fin = data["financials"]
    ttm, bal = fin["ttm"], fin["balance"]
    ebit = ttm.get("operating_income")
    if ebit is None or bal.get("equity") is None:
        return None
    tax = ttm.get("effective_tax_rate")
    tax = 0.25 if tax is None else max(0.0, min(tax, 0.30))
    ic = bal["equity"] + (bal.get("debt") or 0) - (bal.get("cash") or 0) - (bal.get("short_investments") or 0)
    return ebit * (1 - tax) / ic if ic > 0 else None


def scenario_params(data: dict, overrides: dict = None) -> tuple:
    """{escenario: kwargs para from_fundamentals} + notas."""
    ov = overrides or {}
    g1, m, sc, notes = base_drivers(data)
    bo = ov.get("base", {})
    # si se fija un supuesto clave del base, los otros escenarios se arman alrededor de ese valor
    for key, label in (("g1", "g1"), ("margin_target", "margen objetivo"), ("sales_to_capital", "ventas/capital")):
        if key in bo:
            notes = [n for n in notes if not n.startswith(label)]
            notes.append(f"{label} del base fijado a mano; los demás escenarios se mueven alrededor")
    g1 = bo.get("g1", g1)
    m = bo.get("margin_target", m)
    sc = bo.get("sales_to_capital", sc)
    rf = data["rates"]["risk_free"]
    losing = (data["financials"]["ttm"].get("operating_income") or 0) < 0
    out = {}
    for s in SCENARIOS:
        r = RULES[s]
        p = dict(
            g1=max(g1 + (r["g"] - 1) * max(abs(g1), 0.05), -0.10),
            margin_target=max(m * r["m"], 0.02),
            sales_to_capital=sc * r["sc"],
            years_to_target=r["ytt"],
            high_growth_years=HIGH_GROWTH_YEARS,
            g_terminal=rf + r["dg"],
            wacc_shift=r["dw"],
            p_failure=r["pf"] if losing else 0.0,
        )
        p.update(ov.get("all", {}))
        p.update(ov.get(s, {}))
        out[s] = p
    if any(k in ov for k in ("all", *SCENARIOS)):
        notes.append("hay supuestos modificados a mano (overrides.json)")
    return out, notes


def weights(overrides: dict = None) -> tuple:
    """Pesos de conservador/base/optimista. El base queda fijo en 50%; el resto es editable (15%–35% cada uno)."""
    w = dict(DEFAULT_WEIGHTS)
    custom = (overrides or {}).get("weights")
    notes, modified = [], False
    if custom:
        c, o = custom.get("conservador", 0.25), custom.get("optimista", 0.25)
        if abs(c + o - 0.5) > 1e-6 or not (0.15 <= c <= 0.35 and 0.15 <= o <= 0.35):
            notes.append("ponderación inválida (conservador + optimista = 50%, cada uno 15%–35%): se usa 25/50/25")
        else:
            w.update(conservador=c, optimista=o)
            modified = True
            notes.append(f"ponderación modificada: {c:.0%} / 50% / {o:.0%}")
    return w, modified, notes


def describe(p: dict) -> str:
    return (f"ventas +{p['g1']:.0%} anual los primeros {p['high_growth_years']} años, "
            f"margen {p['margin_target']:.0%} en {p['years_to_target']} años").replace("+-", "−")


def terminal(inp, data: dict, scenario: str, fixed: dict, mature: bool) -> tuple:
    """WACC y ROIC terminales.
    - WACC terminal: el actual si la empresa ya es madura (g1 del base ≤ rf + 1 pp, decidido una vez para
      los cinco escenarios); si no, rf + ERP (beta 1).
    - ROIC terminal: WACC terminal + la parte del exceso de retorno actual que conserva el escenario (`moat`).
    `fixed` son los campos que el usuario fijó a mano y no se tocan."""
    from .engine.dcf import cost_of_capital, with_
    notes = []
    changes = {}
    if "wacc_terminal" not in fixed:
        w0 = cost_of_capital(with_(inp, wacc_shift=0.0))["wacc"]
        wT = w0 if mature and w0 < inp.rf + inp.erp else inp.rf + inp.erp
        changes["wacc_terminal"] = wT
        if scenario == "base":
            notes.append(f"WACC terminal {wT:.1%} " + ("(empresa madura: se mantiene el actual)" if wT == w0
                                                        else "(converge a rf + ERP)"))
    else:
        wT = fixed["wacc_terminal"]
    if "roic_terminal" not in fixed:
        roic = roic_now(data)
        excess = max(0.0, min(roic, ROIC_CAP) - wT) if roic is not None else 0.0
        changes["roic_terminal"] = wT + RULES[scenario]["dw"] + RULES[scenario]["moat"] * excess
        if scenario == "base" and excess > 0:
            notes.append(f"ROIC actual {roic:.1%} > WACC terminal {wT:.1%}: el base conserva la mitad del exceso")
    return with_(inp, **changes), notes

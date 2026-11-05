"""Motor DCF de FCFF a 10 años (pasos 1 a 9 del plan). Funciones puras: sin I/O.

Convenciones
- Tasas en decimales (0.05 = 5%). Montos en USD.
- Crecimiento: g1 durante `high_growth_years`, luego baja lineal hasta g_terminal en el año 10.
- Margen EBIT: converge lineal del actual al objetivo en `years_to_target` años.
- Impuestos: tasa efectiva años 1-5, converge a la marginal en el año 10. Las pérdidas (NOL) se acumulan y
  se descuentan de la base imponible.
- WACC: inicial años 1-5, converge al terminal en el año 10.
- Terminal: reinversión = g_T / ROIC_T × NOPAT (por defecto ROIC_T = WACC_T, sin exceso de retorno).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Optional

YEARS = 10


@dataclass(frozen=True)
class DCFInputs:
    # operación
    revenue: float                    # ingresos base (TTM)
    margin: float                     # margen EBIT actual
    g1: float                         # crecimiento año 1
    g_terminal: float
    margin_target: float
    sales_to_capital: float           # ventas incrementales por dólar reinvertido
    years_to_target: int = 7
    high_growth_years: int = 1
    # impuestos
    tax_effective: float = 0.21
    tax_marginal: float = 0.25
    nol: float = 0.0                  # pérdidas fiscales acumuladas
    # costo de capital
    rf: float = 0.045
    erp: float = 0.045
    beta_unlevered: float = 1.0
    pre_tax_cost_debt: float = 0.06
    market_cap: float = 0.0           # para los pesos deuda / equity
    wacc_override: Optional[float] = None   # fija el WACC inicial
    wacc_terminal: Optional[float] = None   # None → rf + erp (empresa madura, beta 1)
    roic_terminal: Optional[float] = None   # None → WACC terminal
    wacc_shift: float = 0.0           # para sensibilidad: suma a WACC inicial y terminal
    # puente al valor por acción
    debt: float = 0.0
    leases: float = 0.0
    cash: float = 0.0
    non_operating: float = 0.0        # inversiones de corto plazo y otros activos no operativos
    minority: float = 0.0
    options: float = 0.0              # valor de opciones / RSU no incluidas en `shares`
    shares: float = 1.0
    p_failure: float = 0.0
    distress_proceeds: float = 0.0    # lo que se recupera si quiebra (valor de los activos operativos)


def cost_of_capital(i: DCFInputs) -> dict:
    """Paso 6: WACC inicial con beta reapalancada a valores de mercado."""
    d = i.debt + i.leases
    e = i.market_cap
    de = d / e if e > 0 else 0.0
    beta = i.beta_unlevered * (1 + (1 - i.tax_marginal) * de)
    ke = i.rf + beta * i.erp
    kd = i.pre_tax_cost_debt * (1 - i.tax_marginal)
    we = e / (d + e) if e > 0 else 1.0
    wacc = i.wacc_override if i.wacc_override is not None else we * ke + (1 - we) * kd
    return {"beta_levered": beta, "cost_of_equity": ke, "cost_of_debt_after_tax": kd,
            "weight_equity": we, "wacc": wacc + i.wacc_shift}


def _growth(i, t):
    hg = max(1, min(i.high_growth_years, YEARS - 1))
    if t <= hg:
        return i.g1
    return i.g1 + (t - hg) / (YEARS - hg) * (i.g_terminal - i.g1)


def _margin(i, t):
    n = max(1, i.years_to_target)
    return i.margin_target if t >= n else i.margin + (i.margin_target - i.margin) * t / n


def _blend(start, end, t):
    """Igual a `start` en años 1-5 y converge lineal a `end` en el año 10."""
    return start if t <= 5 else start + (end - start) * (t - 5) / 5


def value(i: DCFInputs) -> dict:
    coc = cost_of_capital(i)
    w0 = coc["wacc"]
    wT = (i.wacc_terminal if i.wacc_terminal is not None else i.rf + i.erp) + i.wacc_shift
    if wT <= i.g_terminal:
        raise ValueError(f"WACC terminal ({wT:.2%}) debe ser mayor que g terminal ({i.g_terminal:.2%})")
    roic_t = i.roic_terminal if i.roic_terminal is not None else wT

    rows, nol, rev_prev, disc, pv_sum = [], i.nol, i.revenue, 1.0, 0.0
    for t in range(1, YEARS + 1):
        g = _growth(i, t)
        rev = rev_prev * (1 + g)                               # paso 1
        m = _margin(i, t)                                      # paso 2
        ebit = rev * m
        rate = _blend(i.tax_effective, i.tax_marginal, t)      # paso 3
        if ebit <= 0:
            nol += -ebit
            tax = 0.0
        else:
            used = min(nol, ebit)
            nol -= used
            tax = (ebit - used) * rate
        nopat = ebit - tax                                     # paso 4
        reinvest = (rev - rev_prev) / i.sales_to_capital       # paso 5
        fcff = nopat - reinvest
        wacc = _blend(w0, wT, t)                               # paso 6
        disc /= 1 + wacc
        pv = fcff * disc                                       # paso 8
        pv_sum += pv
        rows.append({"year": t, "growth": g, "revenue": rev, "margin": m, "ebit": ebit, "tax_rate": rate,
                     "tax": tax, "nopat": nopat, "reinvestment": reinvest, "fcff": fcff, "wacc": wacc,
                     "discount_factor": disc, "pv_fcff": pv, "nol_end": nol})
        rev_prev = rev

    # paso 7: valor terminal
    rev_t = rev_prev * (1 + i.g_terminal)
    nopat_t = rev_t * i.margin_target * (1 - i.tax_marginal)
    fcff_t = nopat_t * (1 - i.g_terminal / roic_t)
    tv = fcff_t / (wT - i.g_terminal)
    pv_tv = tv * disc

    # pasos 8 y 9: valor de la firma y por acción
    op_value = pv_sum + pv_tv
    op_value_adj = (1 - i.p_failure) * op_value + i.p_failure * i.distress_proceeds
    equity = op_value_adj - i.debt - i.leases - i.minority + i.cash + i.non_operating
    common = equity - i.options
    per_share = common / i.shares

    warnings = []
    if i.g_terminal > i.rf:
        warnings.append(f"g terminal ({i.g_terminal:.2%}) mayor que la tasa libre de riesgo ({i.rf:.2%})")
    share_tv = pv_tv / op_value if op_value else None
    if share_tv is not None and share_tv > 0.85:
        warnings.append(f"el valor terminal es {share_tv:.0%} del valor operativo")
    if per_share < 0:
        warnings.append("valor por acción negativo: revisá supuestos o datos")

    return {
        "inputs": asdict(i),
        "cost_of_capital": {**coc, "wacc_terminal": wT, "roic_terminal": roic_t},
        "years": rows,
        "terminal": {"revenue": rev_t, "nopat": nopat_t, "fcff": fcff_t, "value": tv, "pv": pv_tv},
        "pv_fcff": pv_sum,
        "operating_value": op_value,
        "operating_value_adj": op_value_adj,
        "terminal_share": share_tv,
        "equity_value": equity,
        "common_equity": common,
        "value_per_share": per_share,
        "warnings": warnings,
    }


def with_(i: DCFInputs, **changes) -> DCFInputs:
    """Copia de los supuestos con cambios (útil para escenarios y sensibilidad)."""
    return replace(i, **changes)

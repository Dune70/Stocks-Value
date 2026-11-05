"""Arma DCFInputs desde data/fundamentals/<TICKER>.json.

Fase 2: los supuestos de negocio (g1, margen objetivo, ventas/capital) se pasan a mano.
Fase 3 los va a generar por escenario.
"""
from __future__ import annotations

from .dcf import DCFInputs


def _clip(x, lo, hi):
    return max(lo, min(hi, x))


def from_fundamentals(data: dict, *, g1: float, margin_target: float, sales_to_capital: float,
                      **overrides) -> tuple:
    """Devuelve (DCFInputs, notas). `overrides` pisa cualquier campo de DCFInputs."""
    notes = []
    fin, mkt, rates = data["financials"], data["market"], data["rates"]
    ttm, bal = fin["ttm"], fin["balance"]
    rf, erp = rates["risk_free"], rates["erp"]
    tax_marginal = 0.25

    last = fin["annual"][-1]
    eff = last.get("effective_tax_rate")
    tax_eff = _clip(eff, 0.0, tax_marginal) if eff is not None else 0.0
    if eff is None:
        notes.append("sin tasa efectiva (pérdidas): años 1-5 con 0%")

    debt = bal.get("debt") or 0.0
    interest = ttm.get("interest_expense")
    if debt > 0 and interest:
        kd = _clip(interest / debt, rf, rf + 0.08)
    else:
        kd = rf + 0.02
        notes.append("costo de deuda estimado como rf + 2%")

    ind = data.get("industry") or {}
    beta_u = ind.get("unlevered_beta")
    if beta_u is None:
        beta_u = 1.0
        notes.append("sin beta de industria: se usa 1,0")

    nol = bal.get("nol") or 0.0
    if not nol and (ttm.get("operating_income") or 0) < 0:
        notes.append("sin dato de pérdidas fiscales acumuladas (NOL): se asume 0")

    kwargs = dict(
        revenue=ttm["revenue"], margin=ttm["operating_margin"], g1=g1, g_terminal=rf - 0.005,
        margin_target=margin_target, sales_to_capital=sales_to_capital,
        tax_effective=tax_eff, tax_marginal=tax_marginal, nol=nol,
        rf=rf, erp=erp, beta_unlevered=beta_u, pre_tax_cost_debt=kd, market_cap=mkt.get("market_cap") or 0.0,
        debt=debt, leases=bal.get("operating_leases") or 0.0, cash=bal.get("cash") or 0.0,
        non_operating=bal.get("short_investments") or 0.0, minority=bal.get("minority_interest") or 0.0,
        shares=mkt["shares_outstanding"],
    )
    kwargs.update(overrides)
    return DCFInputs(**kwargs), notes

"""DCF inverso: qué valor de un supuesto hace que el valor por acción iguale al precio."""
from __future__ import annotations

from typing import Optional

from .dcf import DCFInputs, value, with_


def solve(inp: DCFInputs, field: str, price: float, lo: float, hi: float, iters: int = 80) -> Optional[float]:
    """Bisección sobre `field`. Devuelve None si el precio no se alcanza dentro de [lo, hi]."""
    def f(x):
        try:
            return value(with_(inp, **{field: x}))["value_per_share"] - price
        except ValueError:
            return None
    flo, fhi = f(lo), f(hi)
    if flo is None or fhi is None or flo * fhi > 0:
        return None
    for _ in range(iters):
        mid = (lo + hi) / 2
        fm = f(mid)
        if fm is None:
            return None
        if (fm < 0) == (flo < 0):
            lo, flo = mid, fm
        else:
            hi = mid
    return (lo + hi) / 2


def implied_margin(inp: DCFInputs, price: float) -> Optional[float]:
    return solve(inp, "margin_target", price, -0.30, 0.95)


def implied_growth(inp: DCFInputs, price: float) -> Optional[float]:
    return solve(inp, "g1", price, -0.30, 1.00)

"""Escalera de acción, recomendación, banda de tolerancia y '¿alcanzable en el año?'."""
from __future__ import annotations

import math

ZONES = ["Compra excepcional", "Convicción", "Comprar", "Sumar de a poco",
         "Mantener", "Reducir", "Vender", "Venta excepcional"]
TOLERANCE = 0.08


def thresholds(sc: dict) -> list:
    """Siete límites a partir de los cinco escenarios (regla propia, ver plan)."""
    t = [sc["todo_mal"], sc["conservador"], (sc["conservador"] + sc["base"]) / 2, sc["base"] * 0.95,
         (sc["base"] + sc["optimista"]) / 2, sc["optimista"], sc["todo_bien"]]
    out, run = [], 0.0
    for x in t:               # nunca decrecientes ni negativos
        run = max(run, x, 0.0)
        out.append(run)
    return out


def build(sc: dict, price: float, vol: float = None) -> dict:
    t = thresholds(sc)
    lows = [None] + t
    highs = t + [None]
    band = (price * math.exp(-vol), price * math.exp(vol)) if vol else None
    zones = []
    for name, lo, hi in zip(ZONES, lows, highs):
        reach = None
        if band:
            reach = (lo is None or lo < band[1]) and (hi is None or hi > band[0])
        zones.append({"zone": name, "from": lo, "to": hi, "reachable_1y": reach})
    idx = next(i for i, z in enumerate(zones) if z["to"] is None or price < z["to"])
    cur = zones[idx]
    return {
        "zones": zones,
        "recommendation": cur["zone"],
        "zone_index": idx,
        "tolerance": {
            "pct": TOLERANCE,
            "moves_up_above": cur["to"] * (1 + TOLERANCE) if cur["to"] is not None else None,
            "moves_down_below": cur["from"] * (1 - TOLERANCE) if cur["from"] is not None else None,
        },
        "reach_band_1y": band,
    }

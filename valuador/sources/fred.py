"""FRED: último valor de una serie (por defecto el bono del Tesoro a 10 años), sin clave."""
import csv
import io

import requests

from .. import cache
from ..config import TTL

URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"


def latest(series="DGS10"):
    def fetch():
        r = requests.get(URL.format(sid=series), timeout=30)
        r.raise_for_status()
        rows = list(csv.reader(io.StringIO(r.text)))[1:]
        for d, v in reversed(rows):
            if v not in (".", ""):
                return {"date": d, "value": float(v) / 100}
        raise ValueError(f"FRED {series} sin datos")
    return cache.cached("fred", series, TTL["fred"], fetch)

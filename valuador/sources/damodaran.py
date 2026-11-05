"""Damodaran Online: márgenes y betas por industria (EE.UU.)."""
import difflib
import io
import json

import requests

from .. import cache
from ..config import TTL

BASE = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/"
FILES = {"margin": "margin.xls", "betas": "betas.xls"}


def _table(name):
    def fetch():
        import pandas as pd
        r = requests.get(BASE + FILES[name], timeout=60)
        r.raise_for_status()
        for df in pd.read_excel(io.BytesIO(r.content), sheet_name=None, header=None).values():
            hits = df.index[df.iloc[:, 0].astype(str).str.strip().eq("Industry Name")]
            if len(hits):
                h = hits[0]
                body = df.iloc[h + 1:].copy()
                body.columns = [str(c).strip() for c in df.iloc[h]]
                body = body[body["Industry Name"].notna()]
                return json.loads(body.to_json(orient="records"))
        raise ValueError(f"{FILES[name]}: no encontré la fila 'Industry Name'")
    return cache.cached("damodaran", name, TTL["damodaran"], fetch)


def _col(row, *needles):
    """Primer valor cuya columna contiene todas las palabras pedidas."""
    for k, v in row.items():
        kl = k.lower()
        if all(n in kl for n in needles):
            return v
    return None


def candidates(industry, names, n=3):
    """Combina similitud de texto y palabras en común (así 'Health...' encuentra 'Heathcare...')."""
    q = industry.lower()
    qw = {x[:3] for x in q.replace("&", " ").split() if len(x) > 2}

    def score(name):
        nl = name.lower()
        nw = {x[:3] for x in nl.replace("&", " ").split() if len(x) > 2}
        overlap = len(qw & nw) / max(len(qw), 1)
        return 0.5 * difflib.SequenceMatcher(None, q, nl).ratio() + 0.5 * overlap

    ranked = sorted(names, key=score, reverse=True)[:n]
    return [(r, round(score(r), 2)) for r in ranked]


def match(industry, names, overrides):
    if industry in overrides:
        return overrides[industry], 1.0, [overrides[industry]]
    c = candidates(industry, names)
    return c[0][0], c[0][1], [x[0] for x in c]


def industry_data(industry, overrides=None):
    margin, betas = _table("margin"), _table("betas")
    name, score, cands = match(industry, [r["Industry Name"] for r in margin], overrides or {})
    m = next((r for r in margin if r["Industry Name"] == name), None)
    if m is None:
        raise KeyError(f"'{name}' no está en margin.xls (revisá data/industry_map.json)")
    b = next((r for r in betas if r["Industry Name"] == name), {})
    return {
        "source_industry": industry,
        "damodaran_industry": name,
        "match_score": round(score, 2),
        "candidates": cands,
        "operating_margin": _col(m, "pre-tax", "unadjusted", "operating"),
        "operating_margin_pre_sbc": _col(m, "stock compensation"),
        "unlevered_beta": _col(b, "unlevered", "corrected"),
        "de_ratio": _col(b, "d/e"),
        "tax_rate": _col(b, "tax"),
    }

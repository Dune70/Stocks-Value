"""Uso:
  python -m valuador fetch TEM [AAPL ...] [--out data/fundamentals] [--refresh]
  python -m valuador value TEM --g1 0.25 --margin 0.20 --sc 1.5
  python -m valuador valuar TEM [AAPL ...]
  python -m valuador industrias [filtro]
"""
import argparse
import json
import sys
from pathlib import Path

from . import cache
from .config import DATA_DIR


def main(argv=None):
    p = argparse.ArgumentParser(prog="valuador")
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="baja y normaliza los datos de uno o más tickers")
    f.add_argument("tickers", nargs="*", help="default: data/watchlist.json")
    f.add_argument("--out", type=Path, default=DATA_DIR / "fundamentals")
    f.add_argument("--refresh", action="store_true", help="ignora la caché")
    f.add_argument("--print", action="store_true", help="muestra el JSON en pantalla")
    v = sub.add_parser("value", help="DCF con supuestos a mano sobre data/fundamentals/<TICKER>.json")
    v.add_argument("ticker")
    v.add_argument("--g1", type=float, required=True, help="crecimiento año 1, ej. 0.20")
    v.add_argument("--margin", type=float, required=True, help="margen EBIT objetivo, ej. 0.20")
    v.add_argument("--sc", type=float, required=True, help="ventas / capital invertido, ej. 1.5")
    v.add_argument("--years-to-target", type=int, default=7)
    v.add_argument("--high-growth-years", type=int, default=1)
    v.add_argument("--gT", type=float, default=None, help="g terminal (default rf − 0,5 pp)")
    v.add_argument("--detail", action="store_true", help="muestra la tabla año por año")
    q = sub.add_parser("valuar", help="5 escenarios, intrínseco, rango, DCF inverso y escalera")
    q.add_argument("tickers", nargs="*", help="default: data/watchlist.json")
    q.add_argument("--out", type=Path, default=DATA_DIR / "valuations", help="carpeta de salida (Pages: docs/data)")
    wl = sub.add_parser("watch", help="lista de seguimiento: list | add TICKER | remove TICKER")
    wl.add_argument("action", choices=["list", "add", "remove"])
    wl.add_argument("ticker", nargs="?")
    i = sub.add_parser("industrias", help="lista las industrias de Damodaran (opcional: filtro)")
    i.add_argument("filtro", nargs="?", default="")
    a = p.parse_args(argv)

    if a.cmd == "industrias":
        from .sources.damodaran import _table
        for r in _table("margin"):
            if a.filtro.lower() in r["Industry Name"].lower():
                print(r["Industry Name"])
        return

    if a.cmd == "value":
        return _value(a)
    if a.cmd == "valuar":
        a.tickers = a.tickers or _watchlist()
        return _valuar(a)
    if a.cmd == "watch":
        return _watch(a)

    from .fetch import fetch
    a.tickers = a.tickers or _watchlist()
    cache.FORCE_REFRESH = a.refresh
    a.out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for t in a.tickers:
        data = fetch(t)
        path = a.out / f"{data['ticker']}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        ok = data["financials"] is not None and data["market"]["price"] is not None
        failed += not ok
        print(f"{'OK ' if ok else 'ERR'} {data['ticker']} -> {path}")
        for msg in data["warnings"]:
            print(f"    ! {msg}")
        if a.print:
            print(json.dumps(data, indent=2, ensure_ascii=False))
    sys.exit(1 if failed else 0)


def _value(a):
    from .engine import value
    from .engine.inputs import from_fundamentals
    path = DATA_DIR / "fundamentals" / f"{a.ticker.upper()}.json"
    if not path.exists():
        sys.exit(f"Falta {path}: corré primero `python -m valuador fetch {a.ticker.upper()}`")
    from .fetch import read_json
    data = read_json(path)
    extra = {"years_to_target": a.years_to_target, "high_growth_years": a.high_growth_years}
    if a.gT is not None:
        extra["g_terminal"] = a.gT
    inp, notes = from_fundamentals(data, g1=a.g1, margin_target=a.margin, sales_to_capital=a.sc, **extra)
    r = value(inp)
    c = r["cost_of_capital"]
    price = data["market"]["price"]
    m = 1e6
    print(f"{data['ticker']}  precio US$ {price:,.2f}")
    print(f"  WACC {c['wacc']:.2%} -> {c['wacc_terminal']:.2%} | beta {c['beta_levered']:.2f} | g terminal {inp.g_terminal:.2%}")
    print(f"  VP flujos {r['pv_fcff']/m:,.0f} M + VP terminal {r['terminal']['pv']/m:,.0f} M "
          f"= valor operativo {r['operating_value']/m:,.0f} M (terminal {r['terminal_share']:.0%})")
    print(f"  equity {r['equity_value']/m:,.0f} M / {inp.shares/m:,.1f} M acciones")
    print(f"  VALOR POR ACCIÓN US$ {r['value_per_share']:,.2f}  ({r['value_per_share']/price-1:+.1%} vs precio)")
    for n in notes + r["warnings"]:
        print(f"  ! {n}")
    if a.detail:
        print(f"\n  {'año':>3} {'g':>6} {'ingresos':>10} {'margen':>7} {'EBIT':>9} {'NOPAT':>9} {'reinv':>8} {'FCFF':>9} {'WACC':>6} {'VP':>9}")
        for y in r["years"]:
            print(f"  {y['year']:>3} {y['growth']:>6.1%} {y['revenue']/m:>10,.0f} {y['margin']:>7.1%} {y['ebit']/m:>9,.0f} "
                  f"{y['nopat']/m:>9,.0f} {y['reinvestment']/m:>8,.0f} {y['fcff']/m:>9,.0f} {y['wacc']:>6.2%} {y['pv_fcff']/m:>9,.0f}")


def _fmt(x, pct=False):
    if x is None:
        return "—"
    return f"{x:.1%}" if pct else f"{x:,.2f}"


def _valuar(a):
    from .fetch import read_json
    from .valuation import valuate
    overrides = {}
    op = DATA_DIR / "overrides.json"
    if op.exists():
        overrides = read_json(op)
    out_dir = a.out
    out_dir.mkdir(parents=True, exist_ok=True)
    index_path = out_dir / "index.json"
    index = {x["ticker"]: x for x in (read_json(index_path) if index_path.exists() else [])}
    for t in a.tickers:
        t = t.upper()
        path = DATA_DIR / "fundamentals" / f"{t}.json"
        if not path.exists():
            print(f"ERR {t}: falta {path}; corré `python -m valuador fetch {t}`")
            continue
        try:
            r = valuate(read_json(path), overrides.get(t))
        except Exception as e:
            print(f"ERR {t}: {e}")
            continue
        (out_dir / f"{t}.json").write_text(json.dumps(r, indent=2, ensure_ascii=False), encoding="utf-8")
        index[t] = {"ticker": t, "name": (r.get("profile") or {}).get("name"), "price": r["price"],
                    "intrinsic": r["intrinsic"], "recommendation": r["recommendation"], "as_of": r["as_of"]}
        index_path.write_text(json.dumps(sorted(index.values(), key=lambda x: x["ticker"]), indent=2,
                                         ensure_ascii=False), encoding="utf-8")
        sc = r["scenarios"]
        print(f"\n{t}  precio US$ {r['price']:,.2f}  ->  {r['recommendation'].upper()}")
        print(f"  intrínseco US$ {r['intrinsic']:,.2f}  rango {_fmt(r['range'][0])} – {_fmt(r['range'][1])}"
              f"  | potencial {r['potential']:+.1%} | margen de seguridad {r['margin_of_safety']:+.1%}")
        for s, v in sc.items():
            peso = f"{v['weight']:.0%}" if v["weight"] else "  —"
            print(f"  {v['label']:<15} US$ {v['value_per_share']:>10,.2f}  peso {peso:>4}  {v['description']}")
        rv = r["reverse_dcf"]
        print(f"  el precio supone: margen {_fmt(rv['margin'], True)} (base {rv['base_margin']:.1%}) "
              f"o crecimiento {_fmt(rv['growth_g1'], True)} (base {rv['base_g1']:.1%})")
        if rv.get("note"):
            print(f"  -> {rv['note']}")
        print("  escalera:")
        for z in r["ladder"]["zones"]:
            rng = (f"< {z['to']:,.2f}" if z["from"] is None else
                   f"> {z['from']:,.2f}" if z["to"] is None else f"{z['from']:,.2f} – {z['to']:,.2f}")
            mark = "  <- HOY" if z["zone"] == r["recommendation"] else ""
            reach = {True: "sí", False: "no", None: "?"}[z["reachable_1y"]]
            print(f"    {z['zone']:<19} {rng:<22} alcanzable: {reach}{mark}")
        for n in r["notes"] + r["warnings"]:
            print(f"  ! {n}")


TICKER_RE = __import__("re").compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


def _watchlist():
    from .fetch import read_json
    p = DATA_DIR / "watchlist.json"
    return read_json(p) if p.exists() else []


def _watch(a):
    wl = _watchlist()
    if a.action == "list":
        print(" ".join(wl))
        return
    t = (a.ticker or "").strip().upper()
    if not TICKER_RE.match(t):
        sys.exit(f"ticker inválido: {a.ticker!r}")
    if a.action == "add" and t not in wl:
        wl.append(t)
    elif a.action == "remove" and t in wl:
        wl.remove(t)
    (DATA_DIR / "watchlist.json").write_text(json.dumps(sorted(wl)) + "\n", encoding="utf-8")
    print(" ".join(sorted(wl)))

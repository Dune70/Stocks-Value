"""yfinance: perfil, precio, beta y acciones."""
from .. import cache
from ..config import TTL

KEYS = (
    "longName", "shortName", "exchange", "fullExchangeName", "sector", "industry", "country",
    "website", "longBusinessSummary", "currency", "currentPrice", "regularMarketPrice",
    "regularMarketTime", "beta", "marketCap", "sharesOutstanding", "impliedSharesOutstanding",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
)


def snapshot(ticker):
    def fetch():
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        if not info.get("longName") and not info.get("regularMarketPrice"):
            raise ValueError(f"yfinance no devolvió datos para {ticker}")
        return {k: info.get(k) for k in KEYS}
    return cache.cached("yf", f"info-{ticker}", TTL["yf"], fetch)


def annual_revenue(ticker):
    """{fecha_cierre: ingresos} de los estados anuales de yfinance (respaldo cuando EDGAR no los tiene)."""
    def fetch():
        import yfinance as yf
        df = yf.Ticker(ticker).income_stmt
        if df is None or df.empty or "Total Revenue" not in df.index:
            return {}
        row = df.loc["Total Revenue"].dropna()
        return {ts.strftime("%Y-%m-%d"): float(v) for ts, v in row.items()}
    return cache.cached("yf", f"rev-{ticker}", TTL["edgar"], fetch)


def volatility(ticker):
    """Volatilidad anual de 1 año (log-retornos diarios × √252) y cierres extremos."""
    def fetch():
        import math
        import yfinance as yf
        closes = [float(x) for x in yf.Ticker(ticker).history(period="1y")["Close"].dropna()]
        if len(closes) < 60:
            raise ValueError("historia de precios insuficiente")
        rets = [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]
        mean = sum(rets) / len(rets)
        sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / (len(rets) - 1))
        return {"vol_1y": sd * math.sqrt(252), "days": len(closes), "min_1y": min(closes), "max_1y": max(closes)}
    return cache.cached("yf", f"vol-{ticker}", TTL["edgar"], fetch)

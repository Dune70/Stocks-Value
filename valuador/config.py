"""Configuración por variables de entorno."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = Path(os.getenv("VALUADOR_CACHE", ROOT / ".cache"))

# La SEC exige un User-Agent con nombre y email: "Nombre Apellido email@dominio.com"
SEC_USER_AGENT = os.getenv("SEC_USER_AGENT", "")

# Opcional: sin clave no se traen estimaciones de consenso
FMP_API_KEY = os.getenv("FMP_API_KEY", "")

# Prima de riesgo de mercado (ERP). Actualizar cada mes con el valor implícito de Damodaran.
ERP = float(os.getenv("VALUADOR_ERP") or "0.045")

# Vida de la caché por fuente, en segundos
TTL = {
    "tickers": 7 * 24 * 3600,
    "edgar": 24 * 3600,
    "yf": 15 * 60,
    "fred": 12 * 3600,
    "damodaran": 30 * 24 * 3600,
    "fmp": 24 * 3600,
}

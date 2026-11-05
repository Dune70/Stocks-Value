"""Caché en disco (JSON) con vencimiento por namespace."""
import hashlib
import json
import time

from .config import CACHE_DIR

FORCE_REFRESH = False  # lo activa `--refresh` en la CLI


def _path(ns, key):
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    return CACHE_DIR / ns / f"{h}.json"


def get(ns, key, ttl):
    p = _path(ns, key)
    if not FORCE_REFRESH and p.exists() and time.time() - p.stat().st_mtime < ttl:
        return json.loads(p.read_text())
    return None


def put(ns, key, value):
    p = _path(ns, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value))
    return value


def cached(ns, key, ttl, fn):
    v = get(ns, key, ttl)
    if v is None:
        v = put(ns, key, fn())
    return v

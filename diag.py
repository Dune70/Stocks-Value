"""Diagnóstico de datos XBRL. Uso: python diag.py XOM"""
import json
import sys
from collections import Counter

from valuador.config import DATA_DIR
from valuador.sources import edgar

t = sys.argv[1].upper()
cik = edgar.cik_for(t)
pred = json.loads((DATA_DIR / "cik_predecessors.json").read_text()).get(t, [])
print(f"{t}: CIK principal {cik} | predecesores configurados {pred}")

TAGS = ["Revenues", "NetCashProvidedByUsedInOperatingActivities", "PaymentsToAcquirePropertyPlantAndEquipment",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "NetIncomeLoss", "Assets"]

for c in [cik] + [p for p in pred if p != cik]:
    cf = edgar.company_facts(c)
    gaap = cf.get("facts", {}).get("us-gaap", {})
    forms = Counter()
    last10k = ""
    for node in gaap.values():
        for rows in node.get("units", {}).values():
            for f in rows:
                forms[f.get("form")] += 1
                if f.get("form") == "10-K":
                    last10k = max(last10k, f.get("filed", ""))
    print(f"\n== CIK {c}: {cf.get('entityName')} | etiquetas us-gaap: {len(gaap)} | último 10-K presentado: {last10k or 'ninguno'}")
    print("   formularios:", dict(forms.most_common(5)))
    for tag in TAGS:
        rows = [f for u in gaap.get(tag, {}).get("units", {}).values() for f in u]
        k = sorted((f for f in rows if f.get("form") == "10-K"), key=lambda f: f["end"])[-2:]
        print(f"   {tag[:60]}: {len(rows)} datos | últimos anuales: "
              + (", ".join(f"{f['end']} ({f.get('start', '')})" for f in k) or "ninguno"))
    others = [x for x in cf.get("facts", {}) if x not in ("us-gaap", "dei")]
    if others:
        print("   otros espacios de nombres:", others)

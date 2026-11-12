"""Note globale sur 100, décomposée en cinq critères."""
from __future__ import annotations

WEIGHTS = {"rentabilite": 40, "fiabilite": 25, "etat": 20, "liquidite": 10, "donnees": 5}
LABELS = {
    "rentabilite": "Rentabilité",
    "fiabilite": "Fiabilité mécanique",
    "etat": "État et historique",
    "liquidite": "Facilité de revente",
    "donnees": "Qualité des données",
}


def verdict(score: int) -> tuple[str, str]:
    if score >= 75:
        return "Excellente affaire", "excellent"
    if score >= 60:
        return "Bonne affaire", "bon"
    if score >= 45:
        return "À étudier", "moyen"
    return "Peu intéressant", "faible"


def score(*, margin_pct: float | None, reliability: int, price: int | None, repairs_low: int,
          repairs_high: int, is_running: bool | None, ct_status: str, mileage_km: int | None,
          age: int | None, fuel: str | None, completeness: float) -> tuple[int, dict]:
    parts: dict[str, dict] = {}

    # Rentabilité : 30 % de marge nette ou plus = note maximale
    if margin_pct is None:
        r, note = 0.0, "Prix de revente inconnu : ajoutez des annonces comparables ou une cote"
    else:
        r = max(0.0, min(1.0, margin_pct / 0.30))
        note = f"Marge nette estimée {margin_pct * 100:.1f} %"
    parts["rentabilite"] = {"points": r * WEIGHTS["rentabilite"], "note": note}

    parts["fiabilite"] = {"points": reliability / 100 * WEIGHTS["fiabilite"], "note": f"Indice {reliability}/100"}

    etat = float(WEIGHTS["etat"])
    notes = []
    if price:
        ratio = ((repairs_low + repairs_high) / 2) / max(price, 1)
        penalty = min(12.0, ratio * 30)
        etat -= penalty
        if penalty >= 1:
            notes.append(f"réparations ≈ {ratio * 100:.0f} % du prix")
    if is_running is False:
        etat -= 6
        notes.append("non roulant")
    if ct_status == "contre_visite":
        etat -= 3
        notes.append("contre-visite")
    elif ct_status == "a_refaire":
        etat -= 1
    if mileage_km is None:
        etat -= 4
        notes.append("kilométrage inconnu")
    elif age and age > 0 and mileage_km / age > 25_000:
        etat -= 3
        notes.append(f"{int(mileage_km / age):,} km/an".replace(",", " "))
    parts["etat"] = {"points": max(0.0, etat), "note": ", ".join(notes) or "RAS"}

    liq = 0.0
    if age is not None:
        liq += 4 if 2 <= age <= 12 else (2 if age <= 18 else 0)
    else:
        liq += 1
    if mileage_km is not None:
        liq += 3 if mileage_km < 150_000 else (1.5 if mileage_km < 200_000 else 0)
    liq += {"essence": 3, "hybride": 3, "hybride rechargeable": 2.5, "diesel": 2, "électrique": 2}.get(fuel or "", 1)
    parts["liquidite"] = {"points": min(10.0, liq), "note": ""}

    parts["donnees"] = {"points": completeness * WEIGHTS["donnees"], "note": f"{completeness * 100:.0f} % des champs clés renseignés"}

    total = int(round(sum(p["points"] for p in parts.values())))
    for k, p in parts.items():
        p["points"] = round(p["points"], 1)
        p["max"] = WEIGHTS[k]
        p["label"] = LABELS[k]
    return max(0, min(100, total)), parts

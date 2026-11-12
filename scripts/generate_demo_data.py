"""Génère les jeux de données FICTIFS utilisés par les tests et la démo.

Les annonces produites n'existent pas : références préfixées DEMO-, URL sur exemple.fr.
"""
import csv
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)

# modèle -> (marque, modèle, version, énergie, boîte, années, km moyen/an, prix de référence à 2018/100 000 km, CV)
MODELS = [
    ("Peugeot", "308", "1.2 PureTech 130 Allure", "Essence", "Manuelle", (2016, 2020), 15000, 11800, 6),
    ("Volkswagen", "Golf", "1.6 TDI 115 Confortline", "Diesel", "Manuelle", (2015, 2019), 20000, 12500, 5),
    ("Renault", "Clio", "IV 1.2 TCe 120 EDC Intens", "Essence", "Automatique", (2013, 2016), 13000, 8200, 6),
    ("Toyota", "Yaris", "100h Dynamic", "Hybride", "Automatique", (2016, 2020), 12000, 13800, 4),
    ("Dacia", "Sandero", "1.0 SCe 75 Stepway", "Essence", "Manuelle", (2017, 2021), 11000, 9200, 4),
    ("Ford", "Fiesta", "1.0 EcoBoost 100 Titanium", "Essence", "Manuelle", (2015, 2018), 14000, 9000, 5),
]
CITIES = [("Bordeaux", "33000"), ("Mérignac", "33700"), ("Toulouse", "31000"), ("Nantes", "44000"),
          ("Lyon", "69003"), ("Pessac", "33600"), ("Angoulême", "16000"), ("Pau", "64000")]


def price_for(ref, year, km):
    p = ref * (1 + 0.08 * (year - 2018)) * (1 - 0.015 * (km - 100_000) / 10_000)
    return int(round(p * rng.uniform(0.92, 1.08), -1))


def retail():
    rows = []
    n = 0
    for make, model, version, fuel, gb, (y0, y1), kmy, ref, cv in MODELS:
        for _ in range(9):
            n += 1
            year = rng.randint(y0, y1)
            km = max(5000, int((2026 - year) * kmy * rng.uniform(0.7, 1.3)) // 100 * 100)
            city, cp = rng.choice(CITIES)
            rows.append({
                "reference": f"DEMO-LBC-{n:03d}", "url": f"https://www.exemple.fr/annonce/DEMO-LBC-{n:03d}",
                "titre": f"{make} {model} {version}", "marque": make, "modele": model, "version": version,
                "energie": fuel, "boite": gb, "annee": year, "kilometrage": km, "puissance fiscale": cv,
                "prix": price_for(ref, year, km), "ville": city, "code postal": cp,
                "description": rng.choice(["Carnet d'entretien à jour, pneus neufs.", "Très bon état, CT OK.",
                                           "Distribution faite, factures.", "Première main, non fumeur."]),
            })
    with open(OUT / "leboncoin_comparables.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter=";")
        w.writeheader()
        w.writerows(rows)


def auctions():
    lots = [
        ("A1001", "Peugeot", "308", "1.2 PureTech 130 Allure", "Essence", "Manuelle", "15/03/2018", "98 500 km", "6 900 €", "À refaire", "oui",
         "Pare-brise fissuré, rayures porte arrière droite. Frais de remise en état estimés : 650 €", "2026-11-20 14:00"),
        ("A1002", "Volkswagen", "Golf", "1.6 TDI 115 Confortline", "Diesel", "Manuelle", "10/06/2017", "142 000 km", "7 500 €", "OK", "oui",
         "Choc pare-chocs avant, plaquettes à remplacer", "2026-11-20 14:00"),
        ("A1003", "Renault", "Clio", "IV 1.2 TCe 120 EDC Intens", "Essence", "Automatique", "02/04/2014", "121 000 km", "3 200 €", "Contre-visite", "non",
         "Non roulant, voyant moteur allumé", "2026-11-21 10:00"),
        ("A1004", "Toyota", "Yaris", "100h Dynamic", "Hybride", "Automatique", "20/09/2018", "76 000 km", "9 800 €", "OK", "oui",
         "Rayures légères, jante avant gauche abîmée", "2026-11-21 10:00"),
        ("A1005", "Ford", "Fiesta", "1.0 EcoBoost 100 Titanium", "Essence", "Manuelle", "11/01/2016", "118 000 km", "4 100 €", "À refaire", "oui",
         "Fuite de liquide de refroidissement, embrayage patine", "2026-11-22 09:30"),
        ("A1006", "Dacia", "Sandero", "1.0 SCe 75 Stepway", "Essence", "Manuelle", "05/05/2019", "54 000 km", "5 600 €", "OK", "oui",
         "Bon état général", "2026-11-22 09:30"),
    ]
    header = ["N° de lot", "Marque", "Modèle", "Version", "Energie", "Boîte", "Date de mise en circulation",
              "Kilométrage", "Prix de départ", "Contrôle technique", "Roulant", "Frais de remise en état", "Date de vente",
              "Lieu de vente", "Code postal", "Puissance fiscale"]
    cvs = {"308": 6, "Golf": 5, "Clio": 6, "Yaris": 4, "Fiesta": 5, "Sandero": 4}
    with open(OUT / "alcopa_lots.csv", "w", newline="", encoding="cp1252") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        for lot in lots:
            w.writerow(["DEMO-" + lot[0], *lot[1:], "Mérignac", "33700", cvs[lot[2]]])


if __name__ == "__main__":
    retail()
    auctions()
    print("Jeux de données fictifs générés dans", OUT)

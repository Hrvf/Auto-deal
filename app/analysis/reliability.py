"""Base de fiabilité mécanique indicative.

Chaque règle décrit un défaut largement documenté (presse auto, rappels et
extensions de garantie constructeurs). La base est volontairement prudente :
elle signale un RISQUE à vérifier (factures, historique), pas une panne certaine.
Elle est faite pour être enrichie au fil de l'expérience.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..connectors.normalize import norm_key


@dataclass(frozen=True)
class ReliabilityRule:
    id: str
    makes: frozenset[str]
    patterns: tuple[str, ...] = ()   # regex sur le texte normalisé (titre + version + moteur)
    year_from: int = 1990
    year_to: int = 2100
    fuel: str | None = None
    severity: str = "moyen"          # eleve | moyen | faible | positif
    title: str = ""
    detail: str = ""
    probability: float = 0.0         # probabilité indicative que l'intervention soit nécessaire
    cost_low: int = 0
    cost_high: int = 0
    require_all: tuple[str, ...] = field(default_factory=tuple)

    def matches(self, make: str, text: str, year: int | None, fuel: str | None) -> bool:
        if self.makes and make not in self.makes:
            return False
        if year is not None and not (self.year_from <= year <= self.year_to):
            return False
        if self.fuel and fuel and fuel != self.fuel:
            return False
        if self.patterns and not any(re.search(p, text) for p in self.patterns):
            return False
        return all(re.search(p, text) for p in self.require_all)


PSA = frozenset({"peugeot", "citroen", "ds", "opel"})
VAG = frozenset({"volkswagen", "audi", "seat", "skoda", "cupra"})

RULES: tuple[ReliabilityRule, ...] = (
    ReliabilityRule(
        id="puretech-courroie", makes=PSA, fuel="essence", year_from=2013, year_to=2023,
        patterns=(r"puretech", r"\b1 2\b.*\b(e thp|thp)?\s?(100|110|130|155)\b"),
        severity="eleve", title="Moteur 1.2 PureTech : courroie de distribution dans l'huile",
        detail=("Dégradation de la courroie baignant dans l'huile (risque de colmatage de la crépine, "
                "perte de pression d'huile, casse moteur) et surconsommation d'huile. Exiger les factures "
                "de remplacement de courroie et vérifier l'éligibilité au programme d'extension de garantie "
                "du constructeur."),
        probability=0.35, cost_low=900, cost_high=4000,
    ),
    ReliabilityRule(
        id="thp-prince", makes=frozenset({"peugeot", "citroen", "ds", "mini"}), fuel="essence",
        year_from=2006, year_to=2015,
        patterns=(r"\bthp\b", r"cooper s\b", r"\b1 6\b.*\b(150|155|156|163|165|175|200)\b"),
        severity="eleve", title="Moteur 1.6 THP / Prince : chaîne de distribution",
        detail="Allongement de la chaîne de distribution, encrassement des soupapes, consommation d'huile.",
        probability=0.3, cost_low=1200, cost_high=2500,
    ),
    ReliabilityRule(
        id="dv6-hdi", makes=frozenset({"peugeot", "citroen", "ford", "mazda", "volvo"}), fuel="diesel",
        year_from=2004, year_to=2018, patterns=(r"\b1 6\b.*\b(e ?hdi|hdi|tdci|bluehdi|d)\b",),
        severity="moyen", title="Diesel 1.6 HDi/TDCi (DV6) : turbo et injecteurs",
        detail="Joints d'injecteurs, encrassement de la crépine d'huile pouvant tuer le turbo, FAP à surveiller.",
        probability=0.2, cost_low=600, cost_high=1800,
    ),
    ReliabilityRule(
        id="bluehdi-adblue", makes=PSA, fuel="diesel", year_from=2014, year_to=2021,
        patterns=(r"bluehdi", r"\bblue hdi\b"),
        severity="moyen", title="BlueHDi : système AdBlue",
        detail=("Défaillance fréquente du réservoir/pompe AdBlue (voyant anti-pollution et décompte avant "
                "impossibilité de démarrer). Vérifier si le remplacement a été fait."),
        probability=0.25, cost_low=800, cost_high=1500,
    ),
    ReliabilityRule(
        id="ea111-chaine", makes=VAG, fuel="essence", year_from=2006, year_to=2012,
        patterns=(r"\b1 [24] t[f]?si\b", r"\b1 [24]\b.*\bt[f]?si\b"),
        severity="eleve", title="1.2/1.4 TSI (EA111) : chaîne de distribution",
        detail="Chaîne de distribution qui se détend et saute une dent ; bruit de claquement à froid caractéristique.",
        probability=0.3, cost_low=900, cost_high=2500,
    ),
    ReliabilityRule(
        id="ea888-huile", makes=VAG, fuel="essence", year_from=2008, year_to=2012,
        patterns=(r"\b(1 8|2 0) t[f]?si\b",),
        severity="moyen", title="1.8/2.0 TSI (EA888 gén. 2) : consommation d'huile",
        detail="Surconsommation d'huile liée à la segmentation ; contrôler le niveau et l'historique.",
        probability=0.25, cost_low=1500, cost_high=3500,
    ),
    ReliabilityRule(
        id="dq200", makes=VAG, year_from=2008, year_to=2016,
        patterns=(r"dsg ?7", r"s tronic ?7", r"\bdq200\b"),
        severity="moyen", title="Boîte DSG7 à sec (DQ200) : mécatronique et embrayage",
        detail="Pannes de mécatronique et usure prématurée du double embrayage : tester à froid, à-coups au démarrage.",
        probability=0.25, cost_low=1200, cost_high=2800,
    ),
    ReliabilityRule(
        id="h5ft-huile", makes=frozenset({"renault", "dacia", "nissan", "mercedes benz"}), fuel="essence",
        year_from=2012, year_to=2016,
        patterns=(r"\b1 2 tce\b", r"\btce (115|118|120|125|130)\b", r"\bdig t (115|116)\b"),
        severity="eleve", title="1.2 TCe (H5Ft) : surconsommation d'huile",
        detail="Consommation d'huile pouvant mener à la casse moteur si le niveau n'est pas surveillé.",
        probability=0.3, cost_low=600, cost_high=4000,
    ),
    ReliabilityRule(
        id="edc-dc4", makes=frozenset({"renault", "dacia"}), year_from=2010, year_to=2018,
        patterns=(r"\bedc\b",),
        severity="moyen", title="Boîte EDC 6 rapports (embrayage à sec)",
        detail="À-coups, usure de l'embrayage et des actionneurs ; essai routier indispensable.",
        probability=0.2, cost_low=900, cost_high=2500,
    ),
    ReliabilityRule(
        id="ecoboost-10", makes=frozenset({"ford"}), fuel="essence", year_from=2012, year_to=2018,
        patterns=(r"\b1 0\b.*ecoboost", r"ecoboost (100|125|140)", r"\b1 0 scti\b"),
        severity="eleve", title="1.0 EcoBoost : refroidissement",
        detail="Fuites de liquide de refroidissement et surchauffe (risque de joint de culasse) ; courroie humide.",
        probability=0.25, cost_low=800, cost_high=4000,
    ),
    ReliabilityRule(
        id="powershift", makes=frozenset({"ford"}), year_from=2011, year_to=2017,
        patterns=(r"powershift",),
        severity="eleve", title="Boîte Powershift (DPS6) à double embrayage à sec",
        detail="Tremblements au démarrage, embrayage et module de commande défaillants.",
        probability=0.35, cost_low=1000, cost_high=2500,
    ),
    ReliabilityRule(
        id="n47", makes=frozenset({"bmw"}), fuel="diesel", year_from=2007, year_to=2011,
        patterns=(r"\b(116|118|120|123|316|318|320|325|520|x1 (s|x)drive ?(18|20)|x3 (x)?drive ?20) ?d\b",),
        severity="eleve", title="Diesel BMW N47 : chaîne de distribution",
        detail="Chaîne placée côté boîte qui s'allonge (cliquetis) ; réparation avec dépose moteur.",
        probability=0.25, cost_low=1500, cost_high=3500,
    ),
    ReliabilityRule(
        id="ingenium", makes=frozenset({"land rover", "jaguar"}), fuel="diesel", year_from=2015, year_to=2019,
        patterns=(r"\b(td4|ed4|sd4|d150|d180|d240|20d|2 0d)\b",),
        severity="eleve", title="Diesel Ingenium 2.0 : chaîne et dilution d'huile",
        detail="Allongement de la chaîne de distribution, dilution du gazole dans l'huile.",
        probability=0.25, cost_low=2000, cost_high=6000,
    ),
    ReliabilityRule(
        id="skyactiv-d", makes=frozenset({"mazda"}), fuel="diesel", year_from=2012, year_to=2017,
        patterns=(r"skyactiv d", r"\b2 2\b"),
        severity="moyen", title="Mazda 2.2 Skyactiv-D : encrassement",
        detail="Calamine et dilution d'huile, surtout en usage urbain.",
        probability=0.2, cost_low=600, cost_high=3000,
    ),
    ReliabilityRule(
        id="dci-bielles", makes=frozenset({"renault", "dacia", "nissan"}), fuel="diesel",
        year_from=2001, year_to=2009, patterns=(r"\b1 5 dci\b", r"\bdci\b"),
        severity="moyen", title="1.5 dCi première génération : coussinets de bielle",
        detail="Usure des coussinets de bielle sur les premières versions ; vérifier l'historique de vidanges.",
        probability=0.15, cost_low=1500, cost_high=3500,
    ),
    # --- Points positifs -------------------------------------------------
    ReliabilityRule(
        id="toyota-hybride", makes=frozenset({"toyota", "lexus"}), fuel="hybride",
        severity="positif", title="Hybride Toyota/Lexus",
        detail="Chaîne de traction hybride réputée très fiable (pas d'embrayage ni de démarreur classique).",
    ),
    ReliabilityRule(
        id="honda", makes=frozenset({"honda"}), fuel="essence",
        severity="positif", title="Moteur essence Honda", detail="Motorisations essence réputées robustes.",
    ),
    ReliabilityRule(
        id="skyactiv-g", makes=frozenset({"mazda"}), fuel="essence", patterns=(r"skyactiv g", r"\b(1 5|2 0)\b"),
        severity="positif", title="Mazda Skyactiv-G atmosphérique", detail="Moteur essence sans turbo réputé fiable.",
    ),
)

SEVERITY_PENALTY = {"eleve": 25, "moyen": 12, "faible": 5}
POSITIVE_BONUS = 8


def assess(make: str | None, text: str, year: int | None, fuel: str | None,
           mileage_km: int | None, age: int | None) -> tuple[int, list[dict]]:
    """Retourne (score de fiabilité 0-100, alertes)."""
    alerts: list[dict] = []
    score = 75  # base neutre : modèle sans défaut connu dans la base
    make_k = norm_key(make or "")
    text_k = norm_key(text)
    for rule in RULES:
        if rule.matches(make_k, text_k, year, fuel):
            if rule.severity == "positif":
                score += POSITIVE_BONUS
            else:
                score -= SEVERITY_PENALTY.get(rule.severity, 5)
            alerts.append({
                "id": rule.id, "severity": rule.severity, "title": rule.title, "detail": rule.detail,
                "probability": rule.probability, "cost_low": rule.cost_low, "cost_high": rule.cost_high,
                "expected_cost": int(round(rule.probability * (rule.cost_low + rule.cost_high) / 2)),
            })
    if fuel == "électrique":
        alerts.append({"id": "batterie-ve", "severity": "faible", "title": "Batterie de traction",
                       "detail": "Exiger un certificat d'état de santé (SoH) de la batterie avant d'enchérir.",
                       "probability": 0, "cost_low": 0, "cost_high": 0, "expected_cost": 0})
    if mileage_km is not None:
        if mileage_km > 250_000:
            score -= 20
        elif mileage_km > 200_000:
            score -= 12
        elif mileage_km > 150_000:
            score -= 5
    if age is not None:
        if age > 18:
            score -= 10
        elif age > 12:
            score -= 5
    if fuel == "diesel" and mileage_km and mileage_km > 150_000:
        alerts.append({"id": "diesel-depollution", "severity": "faible",
                       "title": "Diesel fort kilométrage : dépollution",
                       "detail": "FAP, vanne EGR et injecteurs sont des postes d'usure à ce kilométrage.",
                       "probability": 0.2, "cost_low": 400, "cost_high": 2000, "expected_cost": 240})
    return max(0, min(100, score)), alerts

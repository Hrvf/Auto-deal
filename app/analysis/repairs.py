"""Estimation des réparations à partir des défauts déclarés.

Fourchettes indicatives (pièces + main-d'œuvre, garage indépendant, citadine/compacte).
Elles sont multipliées par un coefficient de gamme pour les marques premium.
"""
from __future__ import annotations

import re

from ..connectors.normalize import norm_key, parse_int

# (motifs regex sur texte normalisé, libellé, coût bas, coût haut)
DEFECTS: tuple[tuple[tuple[str, ...], str, int, int], ...] = (
    ((r"moteur (hs|casse|a remplacer|serre)", r"casse moteur", r"moteur (a|en) (refaire|panne)"), "Moteur à remplacer / refaire", 2500, 6000),
    ((r"joint de culasse",), "Joint de culasse", 1200, 2500),
    ((r"boite (de vitesses? )?(hs|a remplacer|defectueuse|bruyante)", r"probleme (de )?boite", r"bruit (de )?boite", r"mecatronique"), "Boîte de vitesses", 1000, 3000),
    ((r"chaine de distribution",), "Chaîne de distribution", 900, 2500),
    ((r"courroie de distribution", r"(?<!chaine de )\bdistribution\b"), "Distribution (courroie + pompe à eau)", 400, 900),
    ((r"\bturbo\b",), "Turbo", 900, 2200),
    ((r"double masse", r"volant moteur"), "Volant moteur bimasse", 800, 1500),
    ((r"embrayage",), "Embrayage", 600, 1400),
    ((r"injecteurs?",), "Injecteurs", 400, 1600),
    ((r"\bfap\b", r"filtre a particules"), "Filtre à particules", 500, 2000),
    ((r"\begr\b",), "Vanne EGR", 300, 900),
    ((r"adblue",), "Système AdBlue", 800, 1500),
    ((r"fuite d huile", r"fuite (de )?(liquide|refroidissement)", r"\bfuite\b"), "Fuite à diagnostiquer", 200, 1200),
    ((r"voyant (moteur|defaut|airbag|abs|esp)", r"\bvoyant\b"), "Voyant allumé (diagnostic)", 150, 1200),
    ((r"climatisation", r"\bclim\b"), "Climatisation", 150, 1200),
    ((r"amortisseurs?",), "Amortisseurs", 350, 800),
    ((r"disques?", r"plaquettes", r"\bfreins?\b", r"freinage"), "Freinage", 150, 500),
    ((r"pneus?", r"pneumatiques?"), "Pneumatiques", 250, 600),
    ((r"pare brise",), "Pare-brise", 250, 700),
    ((r"demarreur",), "Démarreur", 250, 600),
    ((r"alternateur",), "Alternateur", 300, 700),
    ((r"batterie",), "Batterie 12 V", 120, 250),
    ((r"echappement", r"silencieux", r"catalyseur"), "Échappement", 150, 1200),
    ((r"retroviseurs?",), "Rétroviseur", 100, 350),
    ((r"phares?", r"optiques?", r"feux? (arriere|avant)"), "Optique / éclairage", 150, 600),
    ((r"jantes?",), "Jantes", 100, 400),
    ((r"pare chocs?", r"parechocs?"), "Pare-chocs", 200, 700),
    ((r"bosses?", r"enfoncements?", r"(?<!pare )\bchocs?\b", r"impacts? carrosserie"), "Carrosserie (chocs)", 200, 900),
    ((r"rayures?", r"\brayee?s?\b", r"eraflures?", r"peinture"), "Peinture / rayures", 100, 500),
    ((r"siege (dechire|abime)", r"sellerie", r"dechirures?"), "Sellerie", 100, 400),
    ((r"vidange", r"entretien a faire", r"revision a faire"), "Entretien / vidange", 150, 350),
    ((r"(double de )?cles? (manquant|absent)", r"une seule cle", r"sans cle"), "Clé manquante", 150, 400),
)

# Mots indiquant que l'élément est en bon état ou déjà remplacé
_NEGATIONS = re.compile(
    r"\b(neuf|neufs|neuve|neuves|remplace|remplacee?s?|change|changee?s?|refait|refaite|ok|bon etat|recent|recente|"
    r"sans|aucun|aucune|pas de|r a s|ras|fait|faite|faits|effectue|effectuee)\b"
)

PREMIUM = {"audi", "bmw", "mercedes benz", "land rover", "jaguar", "porsche", "volvo", "lexus", "tesla", "mini", "alfa romeo", "ds"}

_EXPERT_ESTIMATE = re.compile(
    r"(remise en etat|frais de remise|frais estimes?|reparations? estimees?|cout des reparations|montant des reparations)"
    r"\D{0,30}(\d{1,3}(?: \d{3})+|\d{2,6})\s*(eur|euros?)?"
)


_CLAUSE_SPLIT = re.compile(r"[,;.!?\n/()]|\bet\b|\bmais\b|\bavec\b", re.I)


def _clauses(raw: str) -> list[str]:
    """Découpe en propositions pour que « pneus neufs, embrayage HS » ne neutralise pas l'embrayage."""
    return [c for c in (norm_key(part) for part in _CLAUSE_SPLIT.split(raw)) if c]


def estimate(damages_text: str | None, make: str | None, is_running: bool | None,
             ct_status: str, maintenance_history: bool | None, is_auction: bool) -> tuple[int, int, list[dict]]:
    items: list[dict] = []
    text = norm_key(damages_text or "")
    coef = 1.3 if norm_key(make or "") in PREMIUM else 1.0

    expert = None
    m = _EXPERT_ESTIMATE.search(text)
    if m:
        expert = parse_int(m.group(2))

    clauses = _clauses(damages_text or "")
    for patterns, label, low, high in DEFECTS:
        found = None
        for clause in clauses:
            if _NEGATIONS.search(clause):
                continue
            for p in patterns:
                match = re.search(p, clause)
                if match:
                    found = match
                    break
            if found:
                break
        if found:
            items.append({"label": label, "low": int(low * coef), "high": int(high * coef),
                          "source": f"mention « {found.group(0)} »"})

    if is_running is False and not any(i["label"].startswith("Moteur") for i in items):
        items.append({"label": "Véhicule non roulant (cause inconnue)", "low": 500, "high": 3000,
                      "source": "déclaré non roulant"})
    if ct_status == "contre_visite":
        items.append({"label": "Réparations de contre-visite", "low": 200, "high": 800, "source": "contrôle technique"})
    if is_auction and maintenance_history is not True and not any(i["label"].startswith("Entretien") for i in items):
        items.append({"label": "Remise en route (vidange, filtres)", "low": 150, "high": 300,
                      "source": "historique d'entretien non fourni"})

    low = sum(i["low"] for i in items)
    high = sum(i["high"] for i in items)
    if expert:
        items.insert(0, {"label": "Estimation de l'expert de la vente", "low": expert, "high": expert,
                         "source": "frais de remise en état annoncés", "is_expert": True})
        # L'expert chiffre généralement les défauts listés : son montant sert de plancher,
        # nos postes détectés servent de fourchette haute (défauts parfois sous-estimés).
        low = expert
        high = max(high, int(expert * 1.3))
    return low, high, items

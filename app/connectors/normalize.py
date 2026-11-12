"""Fonctions de normalisation des données brutes (prix, kilométrage, énergie...)."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

_SPACES = re.compile(r"[\s  ]+")


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def norm_key(text: str) -> str:
    """Clé de comparaison : minuscules, sans accents ni ponctuation."""
    text = strip_accents(str(text)).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def clean_str(value) -> str | None:
    if value is None:
        return None
    text = _SPACES.sub(" ", str(value)).strip()
    return text or None


def parse_int(value) -> int | None:
    """'12 500 €' -> 12500 ; '125.000 km' -> 125000 ; '9,5' -> 9."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value))
    text = _SPACES.sub("", str(value))
    text = re.sub(r"(?i)(eur|€|km|kms|ch|cv|ttc|ht)", "", text)
    # Décimales à la française : "12500,50" -> 12500 ; séparateurs de milliers "12.500"
    m = re.match(r"^-?\d{1,3}([.,]\d{3})+$", text)
    if m:
        text = re.sub(r"[.,]", "", text)
    else:
        text = text.replace(",", ".")
    m = re.search(r"-?\d+(\.\d+)?", text)
    if not m:
        return None
    try:
        return int(round(float(m.group(0))))
    except ValueError:
        return None


def parse_price(value) -> int | None:
    n = parse_int(value)
    if n is None or n <= 0 or n > 5_000_000:
        return None
    return n


def parse_km(value) -> int | None:
    n = parse_int(value)
    if n is None or n < 0 or n > 2_000_000:
        return None
    return n


def parse_year(value) -> int | None:
    if value is None or value == "":
        return None
    m = re.search(r"(19[5-9]\d|20[0-4]\d)", str(value))
    if not m:
        return None
    return int(m.group(1))


def parse_date(value) -> str | None:
    """Retourne une date ISO AAAA-MM-JJ à partir de formats FR courants."""
    if value is None or value == "":
        return None
    if isinstance(value, (date, datetime)):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip().split(" ")[0].split("T")[0]
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%m/%Y", "%Y-%m", "%d.%m.%Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def parse_datetime(value) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(text)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %Hh%M", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    k = norm_key(value)
    if k in {"oui", "yes", "true", "1", "o", "y", "vrai", "roulant"}:
        return True
    if k in {"non", "no", "false", "0", "n", "faux", "non roulant"}:
        return False
    return None


FUELS = [
    ("hybride rechargeable", ["hybride rechargeable", "plug in", "plug-in", "phev", "rechargeable"]),
    ("hybride", ["hybride", "hybrid", "hev", "mhev", "micro hybride", "full hybrid"]),
    ("électrique", ["electrique", "electric", "ev", "bev", "elec"]),
    ("gpl", ["gpl", "lpg", "bicarburation essence gpl"]),
    ("e85", ["e85", "ethanol", "superethanol", "flexfuel"]),
    ("diesel", ["diesel", "gazole", "gasoil", "go", "dci", "hdi", "tdi", "bluehdi", "crdi", "cdti", "d"]),
    ("essence", ["essence", "petrol", "gasoline", "sp95", "sp98", "es", "tce", "tsi", "puretech", "tfsi"]),
]


def normalize_fuel(value) -> str | None:
    if not value:
        return None
    k = norm_key(value)
    for label, keys in FUELS:
        for key in keys:
            if k == key or (len(key) > 2 and re.search(rf"\b{re.escape(key)}\b", k)):
                return label
    return None


def normalize_gearbox(value) -> str | None:
    if not value:
        return None
    k = norm_key(value)
    if any(w in k for w in ("auto", "bva", "dsg", "edc", "eat", "cvt", "pilot", "robot", "sequentiel", "s tronic", "dct")):
        return "automatique"
    if any(w in k for w in ("manu", "bvm", "mecanique")):
        return "manuelle"
    return None


CT_MAP = {
    "ok": ["ok", "favorable", "a jour", "valide", "vierge", "sans defaut", "oui"],
    "contre_visite": ["contre visite", "contre-visite", "defavorable", "cv"],
    "a_refaire": ["a refaire", "perime", "expire", "non", "absent", "a faire"],
}


def normalize_ct(value) -> str:
    if not value:
        return "inconnu"
    k = norm_key(value)
    for label, keys in CT_MAP.items():
        if any(norm_key(key) == k or norm_key(key) in k for key in keys if len(key) > 2):
            return label
        if k in keys:
            return label
    return "inconnu"


MAKE_ALIASES = {
    "vw": "Volkswagen", "volkswagen": "Volkswagen", "mercedes": "Mercedes-Benz",
    "mercedes benz": "Mercedes-Benz", "citroen": "Citroën", "ds": "DS", "bmw": "BMW",
    "mini": "Mini", "alfa": "Alfa Romeo", "alfa romeo": "Alfa Romeo", "land rover": "Land Rover",
    "landrover": "Land Rover", "seat": "Seat", "cupra": "Cupra", "skoda": "Skoda", "kia": "Kia",
    "mg": "MG", "byd": "BYD", "ssangyong": "SsangYong", "dacia": "Dacia", "renault": "Renault",
    "peugeot": "Peugeot", "opel": "Opel", "ford": "Ford", "toyota": "Toyota", "nissan": "Nissan",
    "fiat": "Fiat", "audi": "Audi", "hyundai": "Hyundai", "honda": "Honda", "mazda": "Mazda",
    "volvo": "Volvo", "suzuki": "Suzuki", "jeep": "Jeep", "tesla": "Tesla", "porsche": "Porsche",
    "mitsubishi": "Mitsubishi", "lexus": "Lexus", "jaguar": "Jaguar", "smart": "Smart",
    "lancia": "Lancia", "chevrolet": "Chevrolet", "subaru": "Subaru", "infiniti": "Infiniti",
    "abarth": "Abarth", "alpine": "Alpine", "iveco": "Iveco", "mg motor": "MG",
}
# Marques en plusieurs mots d'abord pour la détection dans un titre
_MAKES_SORTED = sorted(MAKE_ALIASES.keys(), key=len, reverse=True)


def normalize_make(value) -> str | None:
    if not value:
        return None
    k = norm_key(value)
    if k in MAKE_ALIASES:
        return MAKE_ALIASES[k]
    return clean_str(value).title() if clean_str(value) else None


def split_title(title: str | None) -> tuple[str | None, str | None]:
    """Devine marque et modèle depuis un titre du type 'Peugeot 308 1.2 PureTech'."""
    if not title:
        return None, None
    k = norm_key(title)
    for alias in _MAKES_SORTED:
        if re.match(rf"^{re.escape(alias)}\b", k):
            rest = k[len(alias):].strip().split(" ")
            model = rest[0] if rest and rest[0] else None
            # Modèles en deux mots fréquents
            if model and len(rest) > 1 and model in {"grand", "range", "classe", "serie", "c", "model", "id"}:
                model = f"{model} {rest[1]}"
            return MAKE_ALIASES[alias], model.title() if model else None
    return None, None


def department_from_postcode(value) -> str | None:
    if not value:
        return None
    m = re.search(r"\b(\d{5})\b", str(value))
    if not m:
        return None
    cp = m.group(1)
    if cp.startswith("97"):
        return cp[:3]
    if cp.startswith("20"):
        return "2A" if int(cp) < 20200 else "2B"
    return cp[:2]


def normalize_model(value) -> str | None:
    text = clean_str(value)
    if not text:
        return None
    return text if any(c.isupper() for c in text[1:]) else text.title()
